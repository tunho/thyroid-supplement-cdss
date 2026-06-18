"""
PubMed 논문 재정렬 — 규칙 기반 점수 + LLM cross-encoder 재랭킹

pubmed_service.py 에서 import 해서 사용합니다.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple

from openai import OpenAI

try:
    from .thyroid_rules import (
        THYROID_DOMAIN_TERMS,
        INTENT_OUTCOME_TERMS,
        HIGH_QUALITY_PUBTYPES,
        LOW_QUALITY_PUBTYPES,
        OFFTOPIC_SIGNALS,
        SCORING_WEIGHTS,
        JOURNAL_TIERS,
        TIER_SCORE_BONUS,
    )
except ImportError:
    from thyroid_rules import (  # type: ignore[no-redef]
        THYROID_DOMAIN_TERMS,
        INTENT_OUTCOME_TERMS,
        HIGH_QUALITY_PUBTYPES,
        LOW_QUALITY_PUBTYPES,
        OFFTOPIC_SIGNALS,
        SCORING_WEIGHTS,
        JOURNAL_TIERS,
        TIER_SCORE_BONUS,
    )

RERANK_CANDIDATE_K = 30
RERANK_TOP_K = 5


def _get_client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=key)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


# ─── 규칙 기반 논문 점수 계산 ─────────────────────────────────────────────
def score_article(
    article: Dict,
    relevance_tokens: List[str],
    intent: str = "safety",
    require_postop: bool = False,
    allow_pregnancy: bool = False,
) -> int:
    """
    규칙 기반으로 논문 적합도 점수를 계산합니다.

    Positive:
      - 갑상선 앵커가 제목/초록에 있는지
      - 성분(relevance_tokens)이 제목/초록에 있는지
      - 고품질 연구 유형인지
      - intent 아웃컴 용어가 초록에 있는지

    Negative:
      - 갑상선 신호 없음
      - 수의학/동물 연구
      - 인구 불일치 (postop 질문에 pregnancy 논문 등)
      - 저품질 연구 유형 (case report 등)
    """
    title = str(article.get("title", "") or "").lower()
    abstract = str(article.get("abstract", "") or "").lower()
    blob = f"{title} {abstract}"
    pub_types: List[str] = article.get("pub_types", []) or []

    score = 0
    sw = SCORING_WEIGHTS

    # ── Thyroid anchor ──────────────────────────────────────────────────
    thyroid_in_title = any(term in title for term in THYROID_DOMAIN_TERMS)
    thyroid_in_abstract = any(term in abstract for term in THYROID_DOMAIN_TERMS)
    if thyroid_in_title:
        score += sw["thyroid_anchor_in_title"]
    elif thyroid_in_abstract:
        score += sw["thyroid_anchor_in_abstract"]
    else:
        score += sw["thyroid_anchor_absent"]

    # ── Supplement/relevance tokens ─────────────────────────────────────
    generic = {"supplement", "supplementation", "intake", "oral", "dietary", "daily"}
    for t in relevance_tokens:
        if t in generic:
            continue
        if t in title:
            score += sw["supplement_in_title"]
        elif t in abstract:
            score += sw["supplement_in_abstract"]

    # ── Intent outcome terms in abstract ────────────────────────────────
    intent_terms = INTENT_OUTCOME_TERMS.get(intent, INTENT_OUTCOME_TERMS["safety"])
    if any(term in abstract for term in intent_terms):
        score += sw["intent_term_in_abstract"]

    # ── Publication type quality ─────────────────────────────────────────
    if any(pt in HIGH_QUALITY_PUBTYPES for pt in pub_types):
        score += sw["high_quality_study"]
    elif any(pt in LOW_QUALITY_PUBTYPES for pt in pub_types):
        score += sw["low_quality_study"]

    # ── Offtopic / veterinary ────────────────────────────────────────────
    if any(sig in blob for sig in OFFTOPIC_SIGNALS):
        score += sw["veterinary_signal"]

    # ── Population mismatch ──────────────────────────────────────────────
    if allow_pregnancy:
        pass  # TODO: add positive pregnancy filters if needed
    else:
        pregnancy_signals = [
            "pregnancy", "pregnant", "postpartum", "prenatal",
            "perinatal", "lactation", "gestational",
        ]
        if any(s in blob for s in pregnancy_signals):
            score += sw["population_mismatch"]

    # ── Postop mismatch ──────────────────────────────────────────────────
    if require_postop:
        postop_signals = [
            "postoperative", "post-surgical", "thyroidectomy",
            "after surgery", "radioiodine",
        ]
        if not any(s in blob for s in postop_signals):
            score += sw["population_mismatch"]

    # ── Journal Tier Bonus ──────────────────────────────────────────────
    journal = str(article.get("journal", "") or "").lower()
    tier = JOURNAL_TIERS.get(journal, "")
    bonus = TIER_SCORE_BONUS.get(tier, 0.0)
    if bonus > 0:
        score += int(bonus * 10)

    return score


# ─── 후보군 사전 선별 ─────────────────────────────────────────────────────
def preselect_candidates(
    articles: List[Dict],
    anchor_tokens: List[str],
    min_primary_score: int = 2,
    limit: int = RERANK_CANDIDATE_K,
) -> List[Dict]:
    """
    LLM 재랭킹 전 규칙 기반 후보 선별.

    1. 앵커/도메인 매칭 논문 우선
    2. primary_subject_relevance 최소값 이상
    3. 최대 limit 개 반환
    """
    if not articles:
        return []

    def _has_anchor(art: Dict) -> bool:
        if not anchor_tokens:
            return True
        blob = f"{art.get('title', '')} {art.get('abstract', '')}".lower()
        thyroid_ok = any(term in blob for term in THYROID_DOMAIN_TERMS)
        anchor_ok = any(tok in blob for tok in anchor_tokens)
        return thyroid_ok and anchor_ok

    pool = [a for a in articles if _has_anchor(a)]
    if not pool:
        pool = list(articles)

    pool = [a for a in pool if int(a.get("primary_subject_relevance") or 0) >= min_primary_score]
    if not pool:
        pool = list(articles[: min(limit, len(articles))])

    return pool[: min(limit, len(pool))]


# ─── LLM cross-encoder 재랭킹 ──────────────────────────────────────────────
_RERANK_SYSTEM_PROMPT = """\
You are a biomedical evidence reranker for a thyroid clinical decision support system.
Given a clinical query and candidate papers, score each paper 0-100 for direct relevance.

Scoring guidance:
- 80-100: Paper directly studies the supplement/intervention in the exact thyroid clinical context (e.g. selenium after thyroidectomy)
- 50-79:  Paper studies the supplement in thyroid disease, but not the exact scenario
- 20-49:  Paper mentions supplement and thyroid but not directly relevant (background, review of other population)
- 0-19:   Irrelevant, wrong population, veterinary, or off-topic

Penalties (hard rules):
- If query implies post-surgical context, papers WITHOUT postoperative/thyroidectomy/surgery signal → score ≤ 20
- If query is NOT about pregnancy/postpartum, pregnancy/postpartum papers → score ≤ 10
- Veterinary / animal-only studies → score ≤ 10
- Papers where supplement/thyroid co-occurrence is only incidental → score ≤ 30

Return JSON only: {"ranked": [{"pmid": "...", "score": 0-100}, ...]}\
Include only PMIDs from the candidate list.\
"""


def llm_rerank(
    query_text: str,
    candidates: List[Dict],
    require_postop: bool = False,
    allow_pregnancy: bool = False,
    supplement_name: str = "",
    limit: int = RERANK_CANDIDATE_K,
    debug: bool = False,
) -> List[Dict]:
    """
    LLM 기반 cross-encoder 재랭킹.
    실패 시 원본 순서(primary_subject_relevance 기준)를 유지합니다.

    Args:
        query_text:     재랭킹 기준 텍스트 (원문 + primary_subject + keywords)
        candidates:     preselect_candidates 결과
        require_postop: True이면 수술후 컨텍스트 — postop 시그널 없는 논문 강한 감점 지시
        allow_pregnancy: True이면 임신/산후 논문 허용
        limit:          LLM에 보낼 최대 후보 수
        debug:          True이면 raw LLM response 출력

    Returns:
        재랭킹된 논문 리스트 (rerank_score, rerank_rank 필드 추가됨)
    """
    q = _norm(query_text)
    if not q or not candidates:
        return candidates

    pool = candidates[: min(limit, len(candidates))]
    if len(pool) <= 1:
        return pool

    try:
        client = _get_client()
        cand_lines = []
        for idx, art in enumerate(pool, 1):
            cand_lines.append(
                f"[{idx}] PMID={art.get('pmid', '')}\n"
                f"Title: {art.get('title', '')}\n"
                f"Abstract: {str(art.get('abstract', '') or '')[:800]}"
            )

        context_note = ""
        if require_postop:
            context_note += "\n[CONTEXT] Query implies POST-OPERATIVE thyroid surgery context. Papers without surgery/postoperative/thyroidectomy signal should be scored ≤ 20."
        if not allow_pregnancy:
            context_note += "\n[CONTEXT] Query is NOT about pregnancy/postpartum. Pregnancy/postpartum papers should be scored ≤ 10."
        if supplement_name:
            context_note += (
                f"\n[CONTEXT] The queried supplement is '{supplement_name}'. "
                f"Papers that do NOT study '{supplement_name}' as a primary intervention should be scored ≤ 15."
            )

        prompt = (
            f"Query:\n{q}{context_note}\n\n"
            f"Candidates:\n" + "\n\n".join(cand_lines)
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw_text = response.choices[0].message.content or "{}"
        if debug:
            print(f"[reranker] raw: {raw_text[:400]}")

        # ── JSON 파싱 및 repair ─────────────────────────────────────────
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            # 1회 repair: 마지막 `]}}` 누락 등 간단한 케이스
            fixed = raw_text.strip()
            if not fixed.endswith("}"):
                fixed += "}"
            try:
                raw = json.loads(fixed)
            except Exception:
                print("[reranker] JSON repair failed, falling back to original order")
                return pool

        ranked_data = raw.get("ranked") if isinstance(raw, dict) else None
        if not isinstance(ranked_data, list):
            return pool

        by_pmid: Dict[str, Dict] = {
            str(a.get("pmid", "")): a for a in pool if a.get("pmid")
        }
        scored: List[Tuple[float, Dict]] = []
        used: set = set()

        for r in ranked_data:
            if not isinstance(r, dict):
                continue
            pmid = str(r.get("pmid", "")).strip()
            if not pmid or pmid not in by_pmid or pmid in used:
                continue
            try:
                sc = float(r.get("score", 0))
            except (TypeError, ValueError):
                sc = 0.0
            art = by_pmid[pmid]
            art["rerank_score"] = max(0.0, min(100.0, sc))
            scored.append((art["rerank_score"], art))
            used.add(pmid)

        remaining = [a for a in pool if str(a.get("pmid", "")) not in used]
        remaining.sort(
            key=lambda x: int(x.get("primary_subject_relevance") or 0), reverse=True
        )
        ordered = (
            [a for _, a in sorted(scored, key=lambda x: x[0], reverse=True)]
            + remaining
        )
        for rank, art in enumerate(ordered, 1):
            art["rerank_rank"] = rank

        return ordered

    except Exception as e:
        print(f"[reranker] LLM rerank failed: {e}")
        return pool


def sort_for_grounding(articles: List[Dict]) -> List[Dict]:
    """rerank_rank → primary_subject_relevance 순으로 정렬합니다."""
    return sorted(
        articles,
        key=lambda a: (
            int(a.get("rerank_rank", 10_000)),
            -int(a.get("primary_subject_relevance") or 0),
        ),
    )


def split_for_grounding(
    articles: List[Dict],
    primary_subject: str,
    min_score: int = 6,
    top_k: int = RERANK_TOP_K,
) -> Tuple[List[Dict], bool]:
    """
    답변 생성 LLM에 전달할 논문 선별.

    - primary_subject_relevance >= min_score 인 논문만 사용
    - 없으면 상위 3편 + weak_evidence=True (PMID 인용 억제용)
    """
    ps = (primary_subject or "").strip()
    if not ps or not articles:
        return articles, False

    on_topic = [
        a for a in articles if int(a.get("primary_subject_relevance") or 0) >= min_score
    ]
    if on_topic:
        return sort_for_grounding(on_topic)[: max(1, top_k)], False

    fallback_n = min(max(1, top_k), 3)
    return sort_for_grounding(articles)[:fallback_n], True
