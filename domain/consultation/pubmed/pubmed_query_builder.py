"""
PubMed 질의 빌더 — intent 분류 · 갑상선 맥락 추출 · 질의 템플릿 생성

pubmed_service.py 에서 import 해서 사용합니다.
모든 AI 호출 실패 시 규칙 기반 폴백으로 동작합니다.
"""

import json
import os
import re
from typing import Dict, List, Optional

from openai import OpenAI

try:
    from .thyroid_rules import (
        THYROID_CONTEXT_ANCHORS,
        INTENT_OUTCOME_TERMS,
        ALLOWED_SUPPLEMENT_SYNONYMS,
        ALLOWED_SUPPLEMENT_CANONICALS,
    )
    from .gating import _is_valid_primary_subject
except ImportError:
    from thyroid_rules import (  # type: ignore[no-redef]
        THYROID_CONTEXT_ANCHORS,
        INTENT_OUTCOME_TERMS,
        ALLOWED_SUPPLEMENT_SYNONYMS,
        ALLOWED_SUPPLEMENT_CANONICALS,
    )
    from gating import _is_valid_primary_subject  # type: ignore[no-redef]

# ─── 내부 유틸 ─────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _get_client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=key)


def _flatten_text(*parts: str) -> str:
    return _norm(" ".join([p for p in parts if p]))


def normalize_allowed_supplement_subject(primary_subject: str, raw_text: str = "") -> str:
    """
    허용된 성분 도메인으로만 primary_subject를 정규화합니다.

    - primary_subject 또는 raw_text(원문 질문/조건/약물)에서 동의어를 탐지
    - 탐지되면 canonical PubMed term 반환
    - 탐지 실패 시 빈 문자열 반환 (화이트리스트 밖 성분 차단)
    """
    base = _flatten_text(primary_subject, raw_text).lower()
    if not base:
        return ""

    # primary_subject가 과도하게 길어질 때(예: "selenium supplementation recovery")를 방지하기 위해
    # 주제 토큰이 아닌 의도/상황 토큰을 제거한 정규화 텍스트를 함께 사용합니다.
    noise_tokens = [
        "recovery", "postoperative", "post-surgical", "post surgical",
        "safety", "effectiveness", "benefit", "effect", "monitoring",
        "interaction", "complication",
    ]
    compact = base
    for nt in noise_tokens:
        compact = compact.replace(nt, " ")
    compact = _norm(compact)

    # 1) canonical이 이미 포함된 경우 우선 인정
    for canonical in ALLOWED_SUPPLEMENT_CANONICALS:
        if canonical.lower() in base or canonical.lower() in compact:
            return canonical

    # 2) 동의어 매칭
    for canonical, synonyms in ALLOWED_SUPPLEMENT_SYNONYMS.items():
        for s in synonyms:
            if s.lower() in base or s.lower() in compact:
                return canonical
    return ""


def normalize_subject_with_priority(
    primary_subject: str,
    user_input: str = "",
    conditions: str = "",
    medications: str = "",
) -> str:
    """
    질문 성분 우선 규칙으로 허용 성분 canonical을 결정합니다.

    우선순위:
      1) 모델이 뽑은 primary_subject 자체
      2) user_input(질문 본문)
      3) conditions
      4) medications

    이유:
    - 환자 복용약(예: levothyroxine)이 질문 성분(예: 비타민A)을 덮어쓰는 문제를 방지
    """
    # 1) 모델 primary_subject를 최우선
    c = normalize_allowed_supplement_subject(primary_subject, primary_subject)
    if c:
        return c

    # 2) 질문 본문에서 성분 탐지
    c = normalize_allowed_supplement_subject("", user_input)
    if c:
        return c

    # 3) 질환/상태 보조
    c = normalize_allowed_supplement_subject("", conditions)
    if c:
        return c

    # 4) 복용약은 마지막 보조 신호
    c = normalize_allowed_supplement_subject("", medications)
    if c:
        return c

    # 5) 화이트리스트 밖이면 AI가 추출한 원본 primary_subject를 폴백으로 사용 (검색 유연성 확보)
    if primary_subject and _is_valid_primary_subject(primary_subject):
        return primary_subject

    return ""


# ─── Intent: 규칙 기반 빠른 감지 ───────────────────────────────────────────
_INTENT_KO_SIGNALS: Dict[str, List[str]] = {
    "postop":      ["수술", "절제", "절제술", "수술했", "수술한", "수술 후", "수술직후", "수술 직후"],
    "interaction": ["상호작용", "같이 먹", "함께 먹", "병용", "간섭", "흡수", "같이"],
    "safety":      ["안전", "위험", "괜찮", "먹어도", "복용해도", "섭취해도", "부작용"],
    "efficacy":    ["효과", "효능", "도움", "좋은가", "효과적", "개선"],
    "dose":        ["용량", "얼마나", "권장량", "상한", "몇 mg", "몇 mcg"],
    "monitoring":  ["확인", "검사", "TSH", "T4", "모니터", "측정", "추적"],
}

_INTENT_EN_SIGNALS: Dict[str, List[str]] = {
    "postop":      ["postoperative", "thyroidectomy", "after surgery", "after operation"],
    "interaction": ["interaction", "coadministration", "absorption", "interference"],
    "safety":      ["safe", "safety", "adverse", "toxicity", "risk"],
    "efficacy":    ["efficacy", "effectiveness", "benefit"],
    "dose":        ["dose", "dosage", "optimal"],
    "monitoring":  ["monitoring", "tsh", "free t4"],
}

_VALID_INTENTS = frozenset(INTENT_OUTCOME_TERMS.keys())


def detect_intent_rule(user_input: str) -> List[str]:
    """규칙 기반 intent 감지 (AI 없는 빠른 경로). 기본값 ['safety']."""
    intents: List[str] = []
    raw_lower = (user_input or "").lower()
    for intent, signals in _INTENT_KO_SIGNALS.items():
        if any(s in user_input for s in signals):
            intents.append(intent)
    for intent, signals in _INTENT_EN_SIGNALS.items():
        if any(s in raw_lower for s in signals) and intent not in intents:
            intents.append(intent)
    return list(dict.fromkeys(intents)) or ["safety"]


# ─── Thyroid context: 규칙 기반 빠른 감지 ─────────────────────────────────
_THYROID_CTX_KO: Dict[str, List[str]] = {
    "hashimoto":       ["하시모토", "자가면역 갑상선염", "자가면역갑상선", "하시모"],
    "graves":          ["그레이브스", "그레이브"],
    "hypothyroidism":  ["갑상선기능저하", "기능저하", "저하증"],
    "hyperthyroidism": ["갑상선기능항진", "기능항진", "항진증"],
    "thyroid_cancer":  ["갑상선암", "갑상선 암", "갑상선 종양", "분화암", "갑상선암"],
    "postop":          ["수술", "절제", "절제술", "수술 후", "수술했", "수술한"],
    "levothyroxine":   ["레보티록신", "씬지로이드", "씬지"],
    "radioiodine":     ["방사성요오드", "RAI", "방사성 요오드", "방사선 요오드"],
}

_THYROID_CTX_EN: Dict[str, List[str]] = {
    "hashimoto":       ["hashimoto", "autoimmune thyroiditis"],
    "graves":          ["graves disease", "graves"],
    "hypothyroidism":  ["hypothyroid"],
    "hyperthyroidism": ["hyperthyroid"],
    "thyroid_cancer":  ["thyroid cancer", "thyroid carcinoma", "dtc", "ptc"],
    "postop":          ["thyroidectomy", "postoperative thyroid", "post-thyroidectomy"],
    "levothyroxine":   ["levothyroxine", "levo-thyroxine"],
    "radioiodine":     ["radioiodine", "iodine-131"],
}

_VALID_THYROID_CONTEXTS = frozenset(THYROID_CONTEXT_ANCHORS.keys())


def detect_thyroid_context_rule(user_input: str, conditions: str = "") -> List[str]:
    """규칙 기반 thyroid context 감지. 빈 리스트 = general."""
    combined = f"{user_input} {conditions}".lower()
    found: List[str] = []
    for ctx, signals in _THYROID_CTX_KO.items():
        if any(s.lower() in combined for s in signals):
            found.append(ctx)
    for ctx, signals in _THYROID_CTX_EN.items():
        if any(s in combined for s in signals) and ctx not in found:
            found.append(ctx)
    return list(dict.fromkeys(found))


# ─── AI 기반 슬롯 추출 ────────────────────────────────────────────────────
_SLOT_EXTRACTION_PROMPT = """\
You are a clinical search slot extractor for PubMed queries about thyroid disease and supplements.

Korean question: {user_input}
Conditions: {conditions}
Medications: {medications}

Extract the following fields and return ONLY valid JSON (no explanation):
{{
  "primary_subject": "<1-4 word standard English PubMed term for supplement/intervention. e.g. selenium supplementation, iron supplement, vitamin D, magnesium>",
  "thyroid_context": "<most specific thyroid clinical context: hashimoto|graves|hypothyroidism|hyperthyroidism|thyroid_cancer|postop|levothyroxine|radioiodine|general>",
  "intent": "<primary clinical intent: safety|efficacy|interaction|postop|dose|monitoring>",
  "population": "<adult|elderly|pregnancy|postpartum|pediatric|unknown>",
  "keywords": "<2-5 additional English PubMed keywords, comma separated>"
}}

Rules:
- primary_subject MUST be in English, 1-4 words, standard medical/supplement term
- Do NOT include time expressions like "3 weeks" or "1 month" in primary_subject
- Do NOT include Korean characters in output values
- If question is about post-surgical safety (e.g. "수술 후 셀레늄"), intent must be "postop"
- thyroid_context "postop" = thyroidectomy/thyroid surgery context
- If asking about safety of taking a supplement after thyroid surgery, thyroid_context="postop" AND intent="safety"
"""


def extract_search_slots(
    user_input: str,
    conditions: str = "",
    medications: str = "",
) -> Dict:
    """
    AI로 검색 슬롯을 추출합니다. JSON 실패 또는 API 오류 시 규칙 기반 폴백.

    반환 Dict 키:
        primary_subject  str  — 표준 영문 PubMed 검색구
        thyroid_context  str  — hashimoto|graves|…|general
        intent           str  — safety|efficacy|interaction|postop|dose|monitoring
        population       str  — adult|elderly|pregnancy|postpartum|pediatric|unknown
        keywords         str  — 추가 영문 키워드 (쉼표 구분)
        intents_rule     List — 규칙 기반 intent 목록 (디버그용)
        thyroid_ctx_rule List — 규칙 기반 thyroid context 목록 (디버그용)
    """
    intents_rule = detect_intent_rule(user_input)
    thyroid_ctx_rule = detect_thyroid_context_rule(user_input, conditions)

    try:
        client = _get_client()
        prompt = _SLOT_EXTRACTION_PROMPT.format(
            user_input=user_input,
            conditions=conditions or "none",
            medications=medications or "none",
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        raw = json.loads(response.choices[0].message.content or "{}")

        # 정제
        primary = re.sub(r"[가-힣]", "", str(raw.get("primary_subject", "") or "")).strip()
        # 시간 표현 제거
        primary = re.sub(
            r"\b\d+\s*(day|days|week|weeks|month|months|year|years)\b",
            "",
            primary,
            flags=re.IGNORECASE,
        ).strip()
        primary = _norm(primary)
        # 요청 반영: 허용 성분(오메가3, 비타민D, 티록신, 셀레늄, 레티놀아세테이트, 요오드)만 허용
        primary = normalize_subject_with_priority(
            primary_subject=primary,
            user_input=user_input,
            conditions=conditions,
            medications=medications,
        )

        thyroid_ctx = _norm(str(raw.get("thyroid_context", "general") or "general")).lower()
        intent = _norm(str(raw.get("intent", "safety") or "safety")).lower()
        population = _norm(str(raw.get("population", "adult") or "adult")).lower()
        keywords = _norm(str(raw.get("keywords", "") or ""))

        # 검증 및 규칙 보정
        if intent not in _VALID_INTENTS:
            intent = intents_rule[0] if intents_rule else "safety"
        if thyroid_ctx not in _VALID_THYROID_CONTEXTS:
            thyroid_ctx = thyroid_ctx_rule[0] if thyroid_ctx_rule else "general"

        # 규칙에서 postop 강하게 감지 → 우선 적용
        if "postop" in thyroid_ctx_rule and thyroid_ctx not in (
            "postop", "thyroid_cancer", "radioiodine"
        ):
            thyroid_ctx = "postop"
        if "postop" in intents_rule and intent != "postop":
            intent = "postop"

        return {
            "primary_subject": primary,
            "thyroid_context": thyroid_ctx,
            "intent": intent,
            "population": population,
            "keywords": keywords,
            "intents_rule": intents_rule,
            "thyroid_ctx_rule": thyroid_ctx_rule,
        }

    except Exception as e:
        print(f"[query_builder] slot extraction failed: {e}")
        fallback_primary = normalize_subject_with_priority(
            primary_subject="",
            user_input=user_input,
            conditions=conditions,
            medications=medications,
        )
        return {
            "primary_subject": fallback_primary,
            "thyroid_context": thyroid_ctx_rule[0] if thyroid_ctx_rule else "general",
            "intent": intents_rule[0] if intents_rule else "safety",
            "population": "adult",
            "keywords": "",
            "intents_rule": intents_rule,
            "thyroid_ctx_rule": thyroid_ctx_rule,
        }


# ─── Intent 기반 쿼리 템플릿 ──────────────────────────────────────────────
def build_intent_queries(
    primary_subject: str,
    thyroid_context: str,
    intent: str,
    postop_tokens: List[str],
    conditions: List[str],
    medications: List[str],
    extra_keywords: str = "",
) -> List[str]:
    """
    Intent + thyroid_context + 성분명으로 최대 6개의 구체적 PubMed 질의를 생성합니다.
    호출 후 각 질의에 _force_thyroid_domain_query를 적용해야 합니다 (중복 방지용 분리).

    생성 템플릿:
      T1  성분 + 갑상선 앵커                       (항상 포함)
      T2  성분 + 갑상선 앵커 + intent 아웃컴        (항상 포함)
      T3  성분 + postop 버킷 + intent 아웃컴        (postop 맥락일 때)
      T4  성분 + 약물 + interaction 키워드           (interaction일 때)
      T5  성분 + 갑상선 앵커 + extra_keywords        (extra 있을 때)
      T6  성분 + 조건 + safety/effectiveness        (conditions 있을 때)
    """
    ps = _norm(primary_subject)
    if not ps:
        return []

    tc = THYROID_CONTEXT_ANCHORS.get(thyroid_context, THYROID_CONTEXT_ANCHORS["general"])
    outcome_terms = INTENT_OUTCOME_TERMS.get(intent, INTENT_OUTCOME_TERMS["safety"])
    # 쿼리가 너무 길어지지 않도록 최대 4개 아웃컴 사용
    intent_clause = " OR ".join(outcome_terms[:4])

    queries: List[str] = []

    # T1: 성분 + 갑상선 앵커 (기본 정밀도 쿼리)
    queries.append(f"({ps}) AND ({tc})")

    # T2: 성분 + 갑상선 앵커 + intent 아웃컴
    queries.append(f"({ps}) AND ({tc}) AND ({intent_clause})")

    # T3: postop 버킷 (수술 맥락)
    if postop_tokens or intent == "postop":
        postop_clause = " OR ".join(postop_tokens or ["postoperative", "thyroidectomy"])
        queries.append(f"({ps}) AND ({postop_clause}) AND ({intent_clause})")

    # T4: 약물 상호작용 — 환자가 명시한 약물 기반
    if intent == "interaction" and medications:
        med_clause = " OR ".join(medications[:2])
        queries.append(
            f"({ps}) AND ({med_clause}) AND (interaction OR absorption OR coadministration)"
        )

    # T4b: 갑상선 호르몬제 상호작용 — interaction intent라면 medications 누락 케이스에도
    # levothyroxine/thyroxine 을 강제 anchoring (D-H4 zinc, D-H6 magnesium 무관 논문 차단 보강)
    if intent == "interaction":
        queries.append(
            f"({ps}) AND (levothyroxine OR thyroxine) AND (interaction OR absorption OR coadministration)"
        )

    # T5: extra_keywords 포함
    # postop 질문에서는 extra_keywords를 과도하게 붙이면 검색 풀이 급격히 줄어드는 문제가 있어
    # 짧은 핵심 토큰일 때만 제한적으로 사용합니다.
    ek = _norm(extra_keywords)
    ek_tokens = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", ek.lower()) if ek else []
    if ek and (intent != "postop" or len(ek_tokens) <= 3):
        queries.append(f"({ps}) AND ({tc}) AND ({ek})")

    # T6: 환자 조건 포함
    if conditions:
        cond_clause = " OR ".join(conditions[:2])
        queries.append(f"({ps}) AND ({cond_clause}) AND (safety OR effectiveness)")

    # 토큰 집합 기준 중복 제거
    seen: set = set()
    unique: List[str] = []
    for q in queries:
        sig = " ".join(sorted(re.findall(r"[a-z0-9]+", q.lower())))
        if sig not in seen:
            seen.add(sig)
            unique.append(q)

    return unique[:6]
