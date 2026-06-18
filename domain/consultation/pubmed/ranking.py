import json
import re
from typing import List, Dict, Tuple
from .text_normalizer import (
    _normalize_text, _normalize_english_query_text,
    _contains_thyroid_domain_signal, _force_thyroid_domain_query,
)
from .openai_client import _get_openai_client
from .constants import CONDITION_HINTS, MEDICATION_HINTS, SUPPLEMENT_HINTS
from .thyroid_rules import (
    THYROID_DOMAIN_TERMS, SCORING_WEIGHTS,
    HIGH_QUALITY_PUBTYPES, LOW_QUALITY_PUBTYPES,
    OFFTOPIC_SIGNALS,
)
from .pubmed_reranker import RERANK_CANDIDATE_K, RERANK_TOP_K
from .utils import _core_subject_tokens, _contains_hangul
from .gating import _has_general_postop_signal, _is_rai_related_article, _has_anchor_match

def _subject_relevance_tokens(primary_subject: str) -> List[str]:
    """PrimarySubject 문자열에서 제목·초록 매칭용 토큰을 뽑습니다."""
    s = (primary_subject or "").strip().lower()
    if not s:
        return []
    tokens = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", s)
    stop = {"the", "and", "for", "with", "or", "of", "in", "to", "a", "an", "vs", "as", "on", "at"}
    out = [t for t in tokens if t not in stop and len(t) >= 2]
    return list(dict.fromkeys(out))[:12]



def _expanded_relevance_tokens(primary_subject: str) -> List[str]:
    """질문 주제별 동의어·검사명을 더해 초록 매칭과 랭킹을 안정화합니다."""
    base = _subject_relevance_tokens(primary_subject)
    s = (primary_subject or "").lower()
    extra: List[str] = []
    if any(k in s for k in ("iron", "ferritin", "ferrous", "anemia", "anaemia")):
        extra.extend(["ferritin", "anemia", "anaemia", "hemoglobin", "deficiency"])
    if "calcium" in s:
        extra.extend(["calcium", "hypercalcemia", "stone"])
    if "vitamin d" in s or "vitamin d3" in s or "cholecalciferol" in s:
        extra.extend(["vitamin d", "25(oh)d", "25-hydroxy"])
    if "zinc" in s:
        extra.extend(["zinc", "zinc deficiency"])
    merged = list(dict.fromkeys([*base, *extra]))
    return merged[:18]



def _anchor_tokens_from_query(primary_subject: str, extra_keywords: str = "") -> List[str]:
    """
    질문 핵심 주제를 대표하는 앵커 토큰을 추출합니다.
    - 너무 일반적인 용어(safety, supplement 등)는 제거
    - 성분/핵심 개체에 가까운 토큰만 남겨 오프토픽 제거에 사용
    """
    text = _normalize_text(f"{primary_subject} {extra_keywords}").lower()
    tokens = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", text)
    stop = {
        "supplement", "supplementation", "intake", "safety", "interaction", "interference",
        "coadministration", "health", "effectiveness", "effect", "postoperative", "early",
        "immediate", "recovery", "after", "before", "with", "without", "and", "or",
    }
    anchors = [t for t in tokens if len(t) >= 3 and t not in stop]

    # 수면 의도 질문이면 수면 앵커를 우선 배치
    sleep_intent = any(
        t in text
        for t in ["sleep", "insomnia", "sleep quality", "latency", "sleep latency"]
    )
    if sleep_intent:
        priority = ["sleep", "insomnia", "quality", "latency"]
        merged = list(dict.fromkeys([*THYROID_DOMAIN_TERMS, *priority, *anchors]))
        return merged[:12]

    return list(dict.fromkeys([*THYROID_DOMAIN_TERMS, *anchors]))[:12]





def _article_subject_score(article: Dict, tokens: List[str]) -> int:
    if not tokens:
        return 0
    generic = {"supplement", "supplementation", "intake", "oral", "dietary", "daily"}
    title = str(article.get("title", "") or "").lower()
    abstract = str(article.get("abstract", "") or "").lower()
    blob = f"{title} {abstract}"
    pub_types: List[str] = article.get("pub_types", []) or []

    score = 0

    # 갑상선 도메인 가중치 (제목 vs 초록 구분)
    thyroid_in_title = _contains_thyroid_domain_signal(title)
    thyroid_in_abstract = _contains_thyroid_domain_signal(abstract)
    if thyroid_in_title:
        score += SCORING_WEIGHTS["thyroid_anchor_in_title"]
    elif thyroid_in_abstract:
        score += SCORING_WEIGHTS["thyroid_anchor_in_abstract"]
    else:
        score += SCORING_WEIGHTS["thyroid_anchor_absent"]

    # 성분/토큰 매칭
    for t in tokens:
        if t in generic:
            continue
        if t in title:
            score += SCORING_WEIGHTS["supplement_in_title"]
        elif t in abstract:
            score += SCORING_WEIGHTS["supplement_in_abstract"]

    # Publication type 품질 가중치
    if any(pt in HIGH_QUALITY_PUBTYPES for pt in pub_types):
        score += SCORING_WEIGHTS["high_quality_study"]
    elif any(pt in LOW_QUALITY_PUBTYPES for pt in pub_types):
        score += SCORING_WEIGHTS["low_quality_study"]

    # 수면 질문에서 도메인 이탈 패널티
    sleep_intent = any(t in tokens for t in ["sleep", "insomnia", "quality", "latency"])
    if sleep_intent:
        drift_terms = ["intravenous", "iv ", "asthma", "children", "pediatric", "paediatric"]
        drift_hits = sum(1 for dt in drift_terms if dt in blob)
        if drift_hits > 0:
            score -= (4 + drift_hits * 2)

    return score



def _rank_articles_by_primary_subject(articles: List[Dict], primary_subject: str) -> List[Dict]:
    tokens = _expanded_relevance_tokens(primary_subject)
    if not tokens:
        for art in articles:
            art["primary_subject_relevance"] = 0
        return articles
    scored: List[Tuple[int, Dict]] = []
    for art in articles:
        sc = _article_subject_score(art, tokens)
        art["primary_subject_relevance"] = sc
        scored.append((sc, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored]



def _preselect_candidates_for_rerank(articles: List[Dict], anchor_tokens: List[str], limit: int = RERANK_CANDIDATE_K) -> List[Dict]:
    """
    1차 규칙 기반 후보군 생성:
    - 앵커/도메인 매칭이 되는 논문 우선
    - 관련도 점수가 너무 낮은 논문은 제외
    """
    if not articles:
        return []
    pool = [a for a in articles if _has_anchor_match(a, anchor_tokens)]
    if not pool:
        pool = articles[:]
    pool = [a for a in pool if int(a.get("primary_subject_relevance") or 0) >= 2]
    if not pool:
        pool = articles[: min(limit, len(articles))]
    return pool[: min(limit, len(pool))]



def _llm_cross_encoder_rerank(
    query_text: str,
    candidates: List[Dict],
    limit: int = RERANK_CANDIDATE_K,
) -> List[Dict]:
    """
    LLM 기반 cross-encoder 스타일 재랭킹.
    후보 논문의 질문 적합도를 0~100 점수로 재평가해 정렬합니다.
    실패 시 원본 순서를 유지합니다.
    """
    q = _normalize_text(query_text)
    if not q or not candidates:
        return candidates
    pool = candidates[: min(limit, len(candidates))]
    if len(pool) <= 1:
        return pool
    try:
        client = _get_openai_client()
        cand_lines = []
        for idx, art in enumerate(pool, 1):
            cand_lines.append(
                f"[{idx}] PMID={art.get('pmid', '')}\n"
                f"Title: {art.get('title', '')}\n"
                f"Abstract: {str(art.get('abstract', '') or '')[:900]}"
            )
        prompt = f"""You are a biomedical reranker for PubMed evidence.
Given a clinical query, score each candidate paper for direct relevance.

Query:
{q}

Candidates:
{chr(10).join(cand_lines)}

Rules:
- Prefer direct match to scenario (disease/surgery/timing/outcome).
- Penalize off-topic populations/contexts.
- If the query implies postoperative/surgery context, papers without postoperative/surgery signal must be scored <= 20.
- If the query is not about pregnancy/postpartum, pregnancy/postpartum papers must be scored <= 10.
- Use title+abstract only.
- Return JSON only: {{"ranked":[{{"pmid":"...", "score": 0-100}}]}}
- Include only PMIDs from candidates.
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content or "{}")
        ranked = raw.get("ranked") if isinstance(raw, dict) else None
        if not isinstance(ranked, list):
            return pool

        by_pmid: Dict[str, Dict] = {str(a.get("pmid", "")): a for a in pool if a.get("pmid")}
        scored_articles: List[Tuple[float, Dict]] = []
        used_pmids = set()
        for r in ranked:
            if not isinstance(r, dict):
                continue
            pmid = str(r.get("pmid", "")).strip()
            if not pmid or pmid not in by_pmid or pmid in used_pmids:
                continue
            try:
                score = float(r.get("score", 0))
            except Exception:
                score = 0.0
            art = by_pmid[pmid]
            art["rerank_score"] = max(0.0, min(100.0, score))
            scored_articles.append((art["rerank_score"], art))
            used_pmids.add(pmid)

        # 모델 응답 누락분은 기존 관련도 순으로 뒤에 배치
        remaining = [a for a in pool if str(a.get("pmid", "")) not in used_pmids]
        remaining.sort(key=lambda x: int(x.get("primary_subject_relevance") or 0), reverse=True)
        ordered = [a for _, a in sorted(scored_articles, key=lambda x: x[0], reverse=True)] + remaining
        for rank, art in enumerate(ordered, 1):
            art["rerank_rank"] = rank
        return ordered
    except Exception as e:
        print(f"[pubmed_service] LLM rerank failed: {e}")
        return pool



def _sort_for_grounding(articles: List[Dict]) -> List[Dict]:
    return sorted(
        articles,
        key=lambda a: (
            int(a.get("rerank_rank", 10_000)),
            -int(a.get("primary_subject_relevance") or 0),
        ),
    )



def _split_articles_for_grounding_llm(
    articles: List[Dict],
    primary_subject: str,
    min_score: int = 6,
    top_k: int = RERANK_TOP_K,
) -> Tuple[List[Dict], bool]:
    """
    답변 생성 LLM에는 '질문 주제'와 제목·초록 관련도가 min_score 이상인 논문만 넣습니다.
    관련 논문이 하나도 없으면 상위 3편만 넣고 weak_evidence=True (PMID 인용 억제 안내용).
    """
    ps = (primary_subject or "").strip()
    if not ps or not articles:
        return articles, False
    on_topic = [a for a in articles if int(a.get("primary_subject_relevance") or 0) >= min_score]
    if on_topic:
        return _sort_for_grounding(on_topic)[: max(1, top_k)], False
    fallback_n = min(max(1, top_k), 3)
    return _sort_for_grounding(articles)[:fallback_n], True



def _direct_postop_evidence_count(articles: List[Dict]) -> int:
    # 기존 함수명 호환을 위해 유지: "직접 postop(비-RAI) 근거"를 우선 카운트
    return sum(1 for a in (articles or []) if _has_general_postop_signal(a) and not _is_rai_related_article(a))



