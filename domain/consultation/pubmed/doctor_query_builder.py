"""
domain.consultation.pubmed.doctor_query_builder

의사용 심층 분석 전용 PubMed 쿼리 빌더.
핵심 원칙: 폼에서 이미 구조화된 데이터(supplement, medications, focus)를
자유텍스트 파서에 넘기지 않고 직접 쿼리로 변환한다.

사용처: app/services/thyroid/orchestrator.py
"""

from __future__ import annotations

import os
import requests
import time
from typing import List, Dict, Optional
from domain.consultation.pubmed.client import fetch_pubmed_details
from domain.consultation.pubmed.pubmed_reranker import score_article, llm_rerank
from domain.consultation.pubmed.pubmed_postfilter import uptype_if_journal_article

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def _search_pubmed_structured(query: str, retmax: int = 10) -> List[str]:
    """
    PubMed 구조화 쿼리를 정규화 없이 그대로 NCBI에 전송.
    search_pubmed_realtime은 [Title/Abstract] 태그를 제거하므로 사용 불가.
    """
    params: Dict = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }
    api_key = os.getenv("NCBI_API_KEY", "")
    if api_key and "optional" not in api_key.lower() and "your" not in api_key.lower():
        params["api_key"] = api_key
    try:
        resp = requests.get(_ESEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"[doctor_query_builder] NCBI 검색 오류: {e}")
        return []

# ── 성분별 PubMed 검색 용어 ─────────────────────────────────────

_SUPPLEMENT_TERMS: Dict[str, List[str]] = {
    "calcium": [
        'calcium[Title/Abstract]',
        '"calcium supplement"[Title/Abstract]',
        '"coral calcium"[Title/Abstract]',
        '"calcium carbonate"[Title/Abstract]',
        '"calcium citrate"[Title/Abstract]',
    ],
    "selenium": [
        'selenium[Title/Abstract]',
        'selenomethionine[Title/Abstract]',
        'selenite[Title/Abstract]',
    ],
    "vitamin_d": [
        '"vitamin D"[Title/Abstract]',
        'cholecalciferol[Title/Abstract]',
        '"25-hydroxyvitamin D"[Title/Abstract]',
        '"25(OH)D"[Title/Abstract]',
    ],
    "iron": [
        'iron[Title/Abstract]',
        'ferrous[Title/Abstract]',
        'ferritin[Title/Abstract]',
    ],
    "zinc": [
        'zinc[Title/Abstract]',
    ],
    "magnesium": [
        'magnesium[Title/Abstract]',
    ],
    "omega3": [
        '"omega-3"[Title/Abstract]',
        '"fish oil"[Title/Abstract]',
        'DHA[Title/Abstract]',
        'EPA[Title/Abstract]',
    ],
    "iodine": [
        'iodine[Title/Abstract]',
        'iodide[Title/Abstract]',
        'kelp[Title/Abstract]',
        'seaweed[Title/Abstract]',
    ],
    "vitamin_b12": [
        '"vitamin B12"[Title/Abstract]',
        'cobalamin[Title/Abstract]',
        'cyanocobalamin[Title/Abstract]',
    ],
    "ashwagandha": [
        'ashwagandha[Title/Abstract]',
        '"Withania somnifera"[Title/Abstract]',
    ],
    "vitamin_c": [
        '"vitamin C"[Title/Abstract]',
        '"ascorbic acid"[Title/Abstract]',
    ],
    "probiotics": [
        'probiotic[Title/Abstract]',
        'probiotics[Title/Abstract]',
        'lactobacillus[Title/Abstract]',
        'bifidobacterium[Title/Abstract]',
        '"gut microbiota"[Title/Abstract]',
    ],
}

_LEVOTHYROXINE_TERMS = [
    '"Levothyroxine"[MeSH Terms]',
    'levothyroxine[Title/Abstract]',
    'thyroxine[Title/Abstract]',
    '"thyroid hormone replacement"[Title/Abstract]',
    '"L-thyroxine"[Title/Abstract]',
]

_ABSORPTION_TERMS = [
    'absorption[Title/Abstract]',
    'interaction[Title/Abstract]',
    'interference[Title/Abstract]',
    'bioavailability[Title/Abstract]',
    'coadministration[Title/Abstract]',
]

_THYROID_DOMAIN_TERMS = [
    'thyroid[Title/Abstract]',
    'hypothyroidism[Title/Abstract]',
    'hyperthyroidism[Title/Abstract]',
    'levothyroxine[Title/Abstract]',
    'TSH[Title/Abstract]',
]

_THYROID_CONTEXT_TERMS: Dict[str, List[str]] = {
    "hashimoto": [
        'hashimoto[Title/Abstract]',
        '"autoimmune thyroiditis"[Title/Abstract]',
        '"TPO antibody"[Title/Abstract]',
        '"thyroid peroxidase"[Title/Abstract]',
    ],
    "graves": [
        '"Graves disease"[Title/Abstract]',
        '"Graves\' disease"[Title/Abstract]',
        'hyperthyroidism[Title/Abstract]',
        '"thyroid stimulating immunoglobulin"[Title/Abstract]',
    ],
    "thyroidectomy_postop": [
        'thyroidectomy[Title/Abstract]',
        '"post-thyroidectomy"[Title/Abstract]',
        '"thyroid surgery"[Title/Abstract]',
        'hypoparathyroidism[Title/Abstract]',
    ],
    "hypothyroidism": [
        'hypothyroidism[Title/Abstract]',
        '"thyroid hormone deficiency"[Title/Abstract]',
    ],
}

# ── score_article()용 성분별 anchor 토큰 ────────────────────────

_DOCTOR_SUPPLEMENT_ANCHORS: Dict[str, List[str]] = {
    "calcium":   ["calcium", "coral calcium", "calcium carbonate", "calcium citrate", "calcium supplement"],
    "selenium":  ["selenium", "selenomethionine", "selenite"],
    "vitamin_d": ["vitamin d", "cholecalciferol", "25-hydroxyvitamin d", "25(oh)d"],
    "iron":      ["iron", "ferrous", "ferritin"],
    "zinc":      ["zinc"],
    "magnesium": ["magnesium"],
    "omega3":    ["omega-3", "fish oil", "dha", "epa"],
    "iodine":    ["iodine", "iodide", "kelp", "seaweed"],
    "vitamin_b12": ["vitamin b12", "cobalamin", "cyanocobalamin"],
    "ashwagandha": ["ashwagandha", "withania somnifera"],
    "vitamin_c": ["vitamin c", "ascorbic acid"],
    "probiotics": ["probiotic", "probiotics", "lactobacillus", "bifidobacterium", "gut microbiota", "gut-thyroid"],
}

_MIN_SCORE = 7   # 이 점수 미만 논문 제거
_MAX_RETURN = 8  # 최종 반환 최대 건수

# ── monitoring context별 핵심 biomarker ─────────────────────────
_MONITORING_BIOMARKERS: Dict[str, List[str]] = {
    "hashimoto": [
        '"TPO antibody"[Title/Abstract]',
        '"thyroid peroxidase antibody"[Title/Abstract]',
        '"anti-thyroglobulin"[Title/Abstract]',
        '"thyroid autoantibody"[Title/Abstract]',
    ],
    "graves": [
        '"TSH receptor antibody"[Title/Abstract]',
        '"TRAb"[Title/Abstract]',
        '"free T3"[Title/Abstract]',
        '"thyroid stimulating immunoglobulin"[Title/Abstract]',
    ],
    "thyroidectomy_postop": [
        '"serum calcium"[Title/Abstract]',
        '"parathyroid hormone"[Title/Abstract]',
        '"PTH"[Title/Abstract]',
        '"TSH suppression"[Title/Abstract]',
    ],
    "hypothyroidism": [
        '"TSH normalization"[Title/Abstract]',
        '"free T4"[Title/Abstract]',
        '"thyroid function"[Title/Abstract]',
        '"levothyroxine dose"[Title/Abstract]',
    ],
}

# ── focus → score_article intent 매핑 ────────────────────────────
# INTENT_OUTCOME_TERMS 키: efficacy, safety, interaction, postop, dose, monitoring
_FOCUS_TO_INTENT: Dict[str, str] = {
    "interaction": "interaction",
    "dosage":      "dose",       # "dosage" ≠ INTENT_OUTCOME_TERMS 키 "dose"
    "monitoring":  "monitoring",
    "general":     "efficacy",
}

# ── 약물명 → levothyroxine 정규화 ─────────────────────────────

_LEVOTHYROXINE_ALIASES = [
    "씬지로이드", "신지로이드", "레보티록신", "levothyroxine",
    "synthroid", "thyroxine", "l-thyroxine", "엘지로이드",
]


def _is_levothyroxine(medications: str) -> bool:
    med_lower = (medications or "").lower()
    return any(alias.lower() in med_lower for alias in _LEVOTHYROXINE_ALIASES)


# ── 항갑상선제(antithyroid) — 쿼리 컨텍스트 ─────────────────────────
_ANTITHYROID_ALIASES = [
    "메티마졸", "methimazole", "thiamazole", "ptu", "propylthiouracil",
    "carbimazole", "카르비마졸", "항갑상선",
]
_ANTITHYROID_TERMS = [
    'methimazole[Title/Abstract]',
    'propylthiouracil[Title/Abstract]',
    'carbimazole[Title/Abstract]',
    '"antithyroid drug"[Title/Abstract]',
    '"antithyroid agents"[Title/Abstract]',
]


def _is_antithyroid(medications: str) -> bool:
    med_lower = (medications or "").lower()
    return any(alias.lower() in med_lower for alias in _ANTITHYROID_ALIASES)


# Public alias — orchestrator·테스트에서 직접 참조
is_levothyroxine_medication = _is_levothyroxine


def _or_clause(terms: List[str]) -> str:
    return "(" + " OR ".join(terms) + ")"


# ── 쿼리 빌더 ────────────────────────────────────────────────────

def build_doctor_pubmed_queries(
    canonical: str,
    medications: str = "",
    focus: str = "general",
    thyroid_context: str = "general",
    supplement_display: str = "",
) -> List[str]:
    """
    의사 폼의 구조화된 파라미터에서 직접 PubMed 쿼리를 생성한다.

    Args:
        canonical:         supplement canonical key ("calcium", "selenium" 등)
        medications:       복용 약물 원문 ("씬지로이드", "levothyroxine" 등)
        focus:             "interaction" | "dosage" | "monitoring" | "general"
        thyroid_context:   "hashimoto" | "graves" | "thyroidectomy_postop" | "hypothyroidism" | "general"
        supplement_display: 원래 입력 이름 (fallback용)
    """
    supp_terms = _SUPPLEMENT_TERMS.get(canonical)
    if not supp_terms and supplement_display:
        # 등록되지 않은 성분 → 이름 그대로 쿼리에 사용
        supp_terms = [f'{supplement_display}[Title/Abstract]']
    if not supp_terms:
        return []

    supp_clause = _or_clause(supp_terms)
    levo_clause = _or_clause(_LEVOTHYROXINE_TERMS)
    abs_clause = _or_clause(_ABSORPTION_TERMS)
    domain_clause = _or_clause(_THYROID_DOMAIN_TERMS)

    ctx_terms = _THYROID_CONTEXT_TERMS.get(thyroid_context, [])
    ctx_clause = _or_clause(ctx_terms) if ctx_terms else None

    queries: List[str] = []

    if focus == "interaction" and _is_levothyroxine(medications):
        # 레보티록신 동반: 흡수 기전 특화 쿼리 (Q1+Q2)
        queries.append(f"{supp_clause} AND {levo_clause} AND {abs_clause}")
        queries.append(f"{supp_clause} AND {levo_clause} AND {domain_clause}")

    elif focus == "interaction":
        # 레보티록신 없는 interaction 명시 (A3): supp + absorption + thyroid_domain
        queries.append(f"{supp_clause} AND {abs_clause} AND {domain_clause}")
        if ctx_clause:
            queries.append(f"{supp_clause} AND {abs_clause} AND {ctx_clause}")

    elif focus == "dosage":
        # supplementation 제거 — 너무 포괄적, 용량 특이적 용어로 교체
        dose_clause = (
            '(dosage[Title/Abstract] OR dose[Title/Abstract] OR "optimal dose"[Title/Abstract]'
            ' OR "recommended dose"[Title/Abstract] OR "daily intake"[Title/Abstract]'
            ' OR "tolerable upper"[Title/Abstract] OR "dose-response"[Title/Abstract])'
        )
        queries.append(f"{supp_clause} AND {dose_clause} AND {domain_clause}")
        if ctx_clause:
            queries.append(f"{supp_clause} AND {dose_clause} AND {ctx_clause}")

    elif focus == "monitoring":
        # TSH 단독 제거 — 갑상선 논문 전반에 등장해 너무 포괄적
        monitor_clause = (
            '(monitoring[Title/Abstract] OR "follow-up"[Title/Abstract]'
            ' OR "thyroid function monitoring"[Title/Abstract]'
            ' OR "laboratory monitoring"[Title/Abstract]'
            ' OR "biomarker"[Title/Abstract] OR surveillance[Title/Abstract])'
        )
        queries.append(f"{supp_clause} AND {monitor_clause} AND {domain_clause}")
        # Q2: context + 진단별 핵심 biomarker 추가
        biomarker_terms = _MONITORING_BIOMARKERS.get(thyroid_context, [])
        if ctx_clause:
            if biomarker_terms:
                bm_clause = _or_clause(biomarker_terms)
                queries.append(f"{supp_clause} AND {bm_clause} AND {ctx_clause}")
            else:
                queries.append(f"{supp_clause} AND {monitor_clause} AND {ctx_clause}")

    else:
        # general: context 있으면 우선, 없으면 thyroid domain
        if ctx_clause:
            queries.append(f"{supp_clause} AND {ctx_clause}")
        queries.append(f"{supp_clause} AND {domain_clause}")

    # 약물 컨텍스트(일반): 항갑상선제 복용 시 supp+antithyroid 변형 추가 (전 성분).
    # 기존 쿼리를 좁히지 않고 *변형 1건* 추가 — 케이스 특이 논문(예: iodine+methimazole) 포착.
    if _is_antithyroid(medications):
        anti_clause = _or_clause(_ANTITHYROID_TERMS)
        queries.append(f"{supp_clause} AND {anti_clause} AND {ctx_clause or domain_clause}")

    return queries


# ── 점수 기반 필터 + 정렬 ────────────────────────────────────────

def _anchor_present(art: Dict, anchors: List[str]) -> bool:
    """supplement anchor 토큰이 title 또는 abstract에 하나라도 있는지 확인."""
    text = ((art.get("title") or "") + " " + (art.get("abstract") or "")).lower()
    return any(a.lower() in text for a in anchors)


def _anchor_in_title(art: Dict, anchors: List[str]) -> bool:
    """supplement anchor 토큰이 title에 등장하는지 확인.

    abstract에 부수적으로 언급된 무관 분야 논문(치과교정/항생제 약동학 등)을 배제하기 위한 엄격 게이트.
    """
    title = (art.get("title") or "").lower()
    if not title:
        return False
    return any(a.lower() in title for a in anchors)


# 비암성/비수술 컨텍스트(하시모토·그레이브스·기능저하·기능항진)일 때 명백히 다른 도메인을 가리키는 시그널
_CANCER_CONTEXT_SIGNALS: List[str] = [
    "thyroid cancer", "thyroid carcinoma", "papillary thyroid", "follicular thyroid",
    "medullary thyroid", "anaplastic thyroid", "thyroid nodule", "thyroidectomy",
    "radioiodine", "iodine-131",
]
# 사용자 컨텍스트에 따라 "맞다고 인정"되는 보조 신호 (제목/abstract 둘 다 검사)
_CONTEXT_MATCH_SIGNALS: Dict[str, List[str]] = {
    "hashimoto":       ["hashimoto", "autoimmune thyroiditis", "tpo antibod", "thyroid peroxidas", "autoimmune thyroid"],
    "graves":          ["graves", "thyrotoxicosis", "tsh receptor"],
    "hypothyroidism":  ["hypothyroid", "thyroid hormone deficiency", "subclinical hypothyroid", "levothyroxine"],
    "hyperthyroidism": ["hyperthyroid", "thyrotoxicosis", "graves"],
}


def _is_context_mismatch(art: Dict, thyroid_context: str) -> bool:
    """thyroid_context가 비암성/비수술인데 논문 제목이 명백히 다른 도메인이면 True."""
    ctx = (thyroid_context or "").lower()
    if ctx not in _CONTEXT_MATCH_SIGNALS:
        return False
    title = (art.get("title") or "").lower()
    abstract = (art.get("abstract") or "").lower()
    if not title:
        return False
    if not any(s in title for s in _CANCER_CONTEXT_SIGNALS):
        return False
    # cancer 시그널이 있어도 사용자 컨텍스트 단어가 같이 등장하면 통과
    match_terms = _CONTEXT_MATCH_SIGNALS[ctx]
    if any(m in title or m in abstract for m in match_terms):
        return False
    return True


def _score_and_filter(
    articles: List[Dict],
    canonical: str,
    supplement_display: str,
    focus: str,
    thyroid_context: str = "general",
) -> List[Dict]:
    """
    score_article()로 각 논문을 점수화한 뒤 임계값 이하 제거 후 정렬.
    anchor 토큰: canonical에 등록된 성분명, 없으면 supplement_display 사용.
    anchor가 title에 없거나 다른 갑상선 도메인(암/수술 등)으로 미스매치된 논문은 즉시 제외.
    """
    anchors = _DOCTOR_SUPPLEMENT_ANCHORS.get(canonical)
    if not anchors and supplement_display:
        anchors = [supplement_display.lower()]
    anchors = anchors or []

    intent = _FOCUS_TO_INTENT.get(focus, "safety")

    scored = []
    for art in articles:
        if anchors and not _anchor_in_title(art, anchors):
            continue  # supplement anchor가 title에 없으면 즉시 제외 (엄격 게이트)
        if _is_context_mismatch(art, thyroid_context):
            continue  # 사용자 컨텍스트와 다른 도메인(암/수술) 논문 제외
        s = score_article(art, relevance_tokens=anchors, intent=intent)
        if s >= _MIN_SCORE:
            art["evidence_level"] = uptype_if_journal_article(art)
            scored.append((s, art))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [art for _, art in scored[:_MAX_RETURN]]

    # 완전 공백 방지: title 게이트 완화 → anchor가 abstract에라도 있고 컨텍스트 일치하는 논문 중 상위 3건
    if not result and articles:
        anchor_ok = [
            a for a in articles
            if (not anchors or _anchor_present(a, anchors))
            and not _is_context_mismatch(a, thyroid_context)
        ]
        pool = anchor_ok if anchor_ok else []
        fallback = sorted(
            pool,
            key=lambda a: score_article(a, relevance_tokens=anchors, intent=intent),
            reverse=True,
        )
        for art in fallback[:3]:
            art["evidence_level"] = uptype_if_journal_article(art)
        result = fallback[:3]

    return result


# ── 메인 진입점 ───────────────────────────────────────────────────

_STANDARD_RETMAX   = 15   # 기본 검색: 쿼리당 15건, 풀 상한 30건
_ENHANCED_RETMAX   = 25   # 고급 검색: 쿼리당 25건, 풀 상한 60건


def get_doctor_pubmed_articles(
    canonical: str,
    medications: str = "",
    focus: str = "general",
    thyroid_context: str = "general",
    supplement_display: str = "",
    enhanced_search: bool = False,
) -> List[Dict]:
    """
    구조화된 파라미터로 PubMed 검색 후 score_article() 기반 필터·정렬 후 반환.

    enhanced_search=True 시:
      - 쿼리당 retmax 25건 (기본 15건)
      - 풀 상한 60건 (기본 30건)
      - LLM 재랭킹 적용 (score 기반 정렬 → LLM cross-encoder 재정렬)
    """
    retmax   = _ENHANCED_RETMAX if enhanced_search else _STANDARD_RETMAX
    pool_cap = 60 if enhanced_search else 30

    queries = build_doctor_pubmed_queries(
        canonical=canonical,
        medications=medications,
        focus=focus,
        thyroid_context=thyroid_context,
        supplement_display=supplement_display,
    )
    if not queries:
        return []

    pmid_seen: set = set()
    pmids: List[str] = []
    for query in queries:
        try:
            new_ids = _search_pubmed_structured(query, retmax=retmax)
            for pid in new_ids:
                if pid not in pmid_seen:
                    pmid_seen.add(pid)
                    pmids.append(pid)
            if new_ids:
                time.sleep(0.35)  # NCBI rate limit
        except Exception as e:
            print(f"[doctor_query_builder] 쿼리 오류: {e}")

    if not pmids:
        return []

    articles = fetch_pubmed_details(pmids[:pool_cap])
    scored = _score_and_filter(
        articles,
        canonical=canonical,
        supplement_display=supplement_display,
        focus=focus,
        thyroid_context=thyroid_context,
    )

    if enhanced_search and scored:
        query_text = f"{supplement_display or canonical} {focus} thyroid {thyroid_context}"
        scored = llm_rerank(
            query_text=query_text,
            candidates=scored,
            supplement_name=supplement_display or canonical,
        )

    return scored


def is_supplement_registered(canonical: str) -> bool:
    """canonical key가 doctor PubMed 쿼리 사전에 등록됐는지 확인."""
    return canonical in _SUPPLEMENT_TERMS
