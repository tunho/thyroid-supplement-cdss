from typing import Dict, List, Optional, Tuple

from .client import fetch_pubmed_details, search_pubmed_realtime
from .context_builder import build_english_patient_context, generate_pubmed_queries
from .gating import (
    _allows_pregnancy_context,
    _apply_final_directness_gate,
    _apply_scenario_hard_gate,
    _filter_articles_with_anchor,
    _primary_suggests_supplement_intervention,
    _requires_postop_hard_gate,
)
from .llm_prompts import _generate_one_line_summary
from .pubmed_postfilter import summarize_evidence_levels
from .pubmed_reranker import (
    RERANK_CANDIDATE_K,
    RERANK_TOP_K,
    llm_rerank,
    preselect_candidates,
)
from .query_builder import _backfill_queries_for_postop, _rescue_queries_for_primary
from .ranking import _anchor_tokens_from_query, _rank_articles_by_primary_subject
from .utils import _core_subject_tokens, _normalize_text


def _initial_debug() -> Dict:
    return {
        "english_context": {},
        "queries": [],
        "query_candidates": [],
        "selected_query": "",
        "pmids": [],
        "article_count": 0,
        "search_stage": 1,
        "domain_mode": "strict",
        "search_rescue": False,
        "primary_subject_relevance_top": None,
        "grounding_on_topic_count": None,
        "dropped_offtopic_count": 0,
        "anchor_tokens": [],
        "rerank_enabled": True,
        "rerank_candidate_count": 0,
        "rerank_top_pmids": [],
        "scenario_require_postop": False,
        "scenario_allow_pregnancy": False,
        "scenario_hard_dropped_count": 0,
        "directness_dropped_count": 0,
        "core_subject_tokens": [],
        "supplement_evidence_gate": False,
        "backfill_used": False,
        "backfill_added_pmids": 0,
        "intent": "safety",
        "thyroid_context": "general",
        "evidence_level_summary": "",
    }


def retrieve_pubmed_evidence(
    user_input: str,
    conditions: str = "",
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    *,
    retmax_per_query: int = 8,
    max_pmids: int = 24,
    sort: str = "relevance",
    include_summaries: bool = True,
    enable_rerank: bool = True,
    pre_slots: Optional[Dict] = None,
) -> Tuple[List[Dict], Dict]:
    """
    PubMed evidence retrieval 공용 코어.

    quick endpoint와 RAG answer path가 같은 context/query 생성 경로를 쓰도록
    english_context, query_candidates, selected_query를 이 함수에서 단일 산출한다.

    pre_slots: orchestrator/API 상위 레이어의 intent·thyroid_context 추론값.
               제공 시 build_english_patient_context의 LLM 슬롯 추출 스킵.
    """
    debug = _initial_debug()
    debug["rerank_enabled"] = bool(enable_rerank)

    english_context = build_english_patient_context(
        user_input=user_input,
        conditions=conditions,
        medications=medications,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        pre_slots=pre_slots,
    )
    debug["english_context"] = english_context
    debug["intent"] = str(english_context.get("intent", "safety") or "safety")
    debug["thyroid_context"] = str(english_context.get("thyroid_context", "general") or "general")

    query_candidates = generate_pubmed_queries(
        user_input,
        conditions,
        medications,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        _context=english_context,
    )
    debug["queries"] = list(query_candidates)
    debug["query_candidates"] = list(query_candidates)

    all_pmids: List[str] = []

    def add_pmids(query: str, pmids: List[str]) -> None:
        if pmids and not debug["selected_query"]:
            debug["selected_query"] = query
        all_pmids.extend(pmids)

    # 1단계: 최근 5년 + 고품질 필터
    debug["search_stage"] = 1
    debug["domain_mode"] = "strict"
    for q in query_candidates:
        try:
            add_pmids(
                q,
                search_pubmed_realtime(
                    q,
                    retmax=retmax_per_query,
                    mindate="2021/01/01",
                    high_quality_only=True,
                    domain_mode="strict",
                    sort=sort,
                ),
            )
        except Exception as e:
            print(f"[pubmed_service] Stage 1 Search Error for query '{q}': {e}")

    # 2단계: 최근 5년 + 필터 해제
    unique_pmids = list(dict.fromkeys(all_pmids))
    if len(unique_pmids) < 3:
        debug["search_stage"] = 2
        debug["domain_mode"] = "strict"
        for q in query_candidates:
            try:
                add_pmids(
                    q,
                    search_pubmed_realtime(
                        q,
                        retmax=retmax_per_query,
                        mindate="2021/01/01",
                        high_quality_only=False,
                        domain_mode="strict",
                        sort=sort,
                    ),
                )
            except Exception as e:
                print(f"[pubmed_service] Stage 2 Search Error for query '{q}': {e}")

    # 3단계: 최근 10년 + 필터 해제 + soft 도메인
    unique_pmids = list(dict.fromkeys(all_pmids))
    if len(unique_pmids) < 3:
        debug["search_stage"] = 3
        debug["domain_mode"] = "soft"
        for q in query_candidates:
            try:
                add_pmids(
                    q,
                    search_pubmed_realtime(
                        q,
                        retmax=retmax_per_query,
                        mindate="2016/01/01",
                        high_quality_only=False,
                        domain_mode="soft",
                        sort=sort,
                    ),
                )
            except Exception as e:
                print(f"[pubmed_service] Stage 3 Search Error for query '{q}': {e}")

    # Fallback: 전체 키워드 조합 (단, thyroid 도메인 clause는 유지 → soft 모드)
    # open 모드로 풀어버리면 supplement만 매칭된 무관 분야 논문이 후보로 들어와 게이트를 통과시켰음
    unique_pmids = list(dict.fromkeys(all_pmids))
    if not unique_pmids:
        debug["domain_mode"] = "soft"
        primary_fallback = str(english_context.get("primary_subject", "") or "").strip()
        broad_terms = (
            ([primary_fallback] if primary_fallback else [])
            + (english_context.get("supplements") or [])
            + (english_context.get("conditions") or [])
            + (english_context.get("medications") or [])
        )
        broad_query = " ".join(list(dict.fromkeys([t for t in broad_terms if t]))[:6]).strip()
        if broad_query:
            try:
                add_pmids(
                    broad_query,
                    search_pubmed_realtime(
                        broad_query,
                        retmax=retmax_per_query,
                        mindate="2016/01/01",
                        high_quality_only=False,
                        domain_mode="soft",
                        sort=sort,
                    ),
                )
            except Exception as e:
                print(f"[pubmed_service] Broad fallback search error: {e}")

    # Fallback 2: canonical 성분 + 수술 맥락의 최소 질의
    unique_pmids = list(dict.fromkeys(all_pmids))
    if not unique_pmids:
        primary_subj_min = str(english_context.get("primary_subject", "") or "").strip()
        min_queries: List[str] = []
        if primary_subj_min:
            min_queries.append(f"{primary_subj_min} thyroidectomy postoperative")
            min_queries.append(f"{primary_subj_min} thyroid surgery safety")
        for mq in min_queries:
            if mq not in debug["queries"]:
                debug["queries"].append(f"[fallback-min] {mq}")
            try:
                add_pmids(
                    mq,
                    search_pubmed_realtime(
                        mq,
                        retmax=retmax_per_query,
                        mindate="2016/01/01",
                        high_quality_only=False,
                        domain_mode="soft",
                        sort=sort,
                    ),
                )
            except Exception as e:
                print(f"[pubmed_service] Minimal fallback search error for '{mq}': {e}")

    unique_pmids = list(dict.fromkeys(all_pmids))[:max_pmids]
    print(f"[pubmed_service] Total Unique PMIDs to fetch (Stage {debug['search_stage']}): {len(unique_pmids)}")
    debug["pmids"] = unique_pmids

    articles: List[Dict] = []
    primary_subj = str(english_context.get("primary_subject", "") or "").strip()
    extra_kw = str(english_context.get("extra_keywords", "") or "").strip()
    anchor_tokens = _anchor_tokens_from_query(primary_subj, extra_kw)
    debug["anchor_tokens"] = anchor_tokens
    debug["core_subject_tokens"] = _core_subject_tokens(primary_subj)
    debug["supplement_evidence_gate"] = _primary_suggests_supplement_intervention(primary_subj)
    require_postop = _requires_postop_hard_gate(user_input, primary_subj, extra_kw)
    allow_pregnancy = _allows_pregnancy_context(user_input, primary_subj, extra_kw)
    debug["scenario_require_postop"] = require_postop
    debug["scenario_allow_pregnancy"] = allow_pregnancy

    if unique_pmids:
        try:
            articles = fetch_pubmed_details(unique_pmids)
            print(f"[pubmed_service] Successfully fetched details for {len(articles)} articles")
            articles = _rank_articles_by_primary_subject(articles, primary_subj)
            top_rel = articles[0].get("primary_subject_relevance", 0) if articles else 0
            debug["primary_subject_relevance_top"] = top_rel

            if primary_subj and (top_rel < 4 or len(articles) < 4):
                debug["search_rescue"] = True
                rescue_qs = _rescue_queries_for_primary(primary_subj)
                for rq in rescue_qs:
                    if rq not in debug["queries"]:
                        debug["queries"].append(f"[rescue] {rq}")
                    try:
                        rescue_pmids = search_pubmed_realtime(
                            rq,
                            retmax=retmax_per_query,
                            mindate="2016/01/01",
                            high_quality_only=False,
                            domain_mode="soft",
                            sort=sort,
                        )
                        add_pmids(rq, rescue_pmids)
                        for pid in rescue_pmids:
                            if pid not in unique_pmids:
                                unique_pmids.append(pid)
                    except Exception as e:
                        print(f"[pubmed_service] Rescue search error for '{rq}': {e}")
                unique_pmids = list(dict.fromkeys(unique_pmids))[:max_pmids]
                debug["pmids"] = unique_pmids
                extra = fetch_pubmed_details(unique_pmids)
                by_pmid: Dict[str, Dict] = {a["pmid"]: a for a in articles if a.get("pmid")}
                for a in extra:
                    if a.get("pmid") and a["pmid"] not in by_pmid:
                        by_pmid[a["pmid"]] = a
                articles = list(by_pmid.values())
                articles = _rank_articles_by_primary_subject(articles, primary_subj)
                debug["primary_subject_relevance_top"] = (
                    articles[0].get("primary_subject_relevance", 0) if articles else 0
                )

            articles, hard_dropped = _apply_scenario_hard_gate(
                articles,
                require_postop=require_postop,
                allow_pregnancy_context=allow_pregnancy,
            )
            debug["scenario_hard_dropped_count"] = hard_dropped

            if len(articles) < 2 and primary_subj:
                backfill_queries = _backfill_queries_for_postop(primary_subj)
                added_pmids: List[str] = []
                for bq in backfill_queries:
                    if bq not in debug["queries"]:
                        debug["queries"].append(f"[backfill] {bq}")
                    try:
                        b_pmids = search_pubmed_realtime(
                            bq,
                            retmax=retmax_per_query,
                            mindate="2016/01/01",
                            high_quality_only=False,
                            domain_mode="strict",
                            sort=sort,
                        )
                        add_pmids(bq, b_pmids)
                    except Exception as e:
                        print(f"[pubmed_service] Backfill search error for '{bq}': {e}")
                        b_pmids = []
                    for pid in b_pmids:
                        if pid not in unique_pmids:
                            unique_pmids.append(pid)
                            added_pmids.append(pid)

                if added_pmids:
                    debug["backfill_used"] = True
                    debug["backfill_added_pmids"] = len(added_pmids)
                    unique_pmids = list(dict.fromkeys(unique_pmids))[: max(max_pmids, 30)]
                    debug["pmids"] = unique_pmids
                    merged = fetch_pubmed_details(unique_pmids)
                    by_pmid = {a["pmid"]: a for a in merged if a.get("pmid")}
                    articles = list(by_pmid.values())
                    articles = _rank_articles_by_primary_subject(articles, primary_subj)
                    articles, hard_dropped2 = _apply_scenario_hard_gate(
                        articles,
                        require_postop=require_postop,
                        allow_pregnancy_context=allow_pregnancy,
                    )
                    debug["scenario_hard_dropped_count"] = int(debug["scenario_hard_dropped_count"] or 0) + hard_dropped2

            articles, direct_dropped = _apply_final_directness_gate(
                articles,
                require_postop=require_postop,
                primary_subject=primary_subj,
            )
            debug["directness_dropped_count"] = direct_dropped

            if enable_rerank:
                rerank_query_text = _normalize_text(
                    " ".join([
                        str(primary_subj or ""),
                        str(extra_kw or ""),
                        str(user_input or ""),
                        str(conditions or ""),
                        str(medications or ""),
                    ])
                )
                rerank_candidates = preselect_candidates(
                    articles,
                    anchor_tokens=anchor_tokens,
                    limit=RERANK_CANDIDATE_K,
                )
                debug["rerank_candidate_count"] = len(rerank_candidates)
                reranked = llm_rerank(
                    query_text=rerank_query_text,
                    candidates=rerank_candidates,
                    require_postop=require_postop,
                    allow_pregnancy=allow_pregnancy,
                    supplement_name=str(primary_subj or ""),
                    limit=RERANK_CANDIDATE_K,
                )
                reranked_pmids = {str(a.get("pmid", "")) for a in reranked if a.get("pmid")}
                tail = [a for a in articles if str(a.get("pmid", "")) not in reranked_pmids]
                articles = reranked + tail
                debug["rerank_top_pmids"] = [
                    str(a.get("pmid", "")) for a in articles[:RERANK_TOP_K] if a.get("pmid")
                ]

            articles, dropped = _filter_articles_with_anchor(
                articles,
                anchor_tokens=anchor_tokens,
                min_score_primary=6,
                min_score_secondary=4,
                core_tokens=debug["core_subject_tokens"],
                require_title_core=debug["supplement_evidence_gate"],
            )
            debug["dropped_offtopic_count"] = dropped
            debug["grounding_on_topic_count"] = sum(
                1 for a in articles if int(a.get("primary_subject_relevance") or 0) >= 6
            )

            if include_summaries:
                for art in articles[:5]:
                    try:
                        art["one_line_summary"] = _generate_one_line_summary(art)
                    except Exception as summary_error:
                        print(f"[pubmed_service] Summary generation failed for PMID {art.get('pmid')}: {summary_error}")

            debug["evidence_level_summary"] = summarize_evidence_levels(articles[:5])

        except Exception as e:
            print(f"[pubmed_service] Fetch Details Error: {e}")

    debug["article_count"] = len(articles)
    return articles, debug
