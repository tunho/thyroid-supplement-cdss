import re
from typing import List, Dict, Tuple, Optional
from .constants import (
    CONDITION_HINTS, MEDICATION_HINTS, SUPPLEMENT_HINTS,
)
from .text_normalizer import (
    _normalize_text, _normalize_english_query_text,
    _strip_time_expressions_en, _force_thyroid_domain_query,
)
from .utils import (
    _translate_korean_text, _merge_supplement_signals, _extract_present_terms,
)
from .query_builder import _rescue_queries_for_primary, _backfill_queries_for_postop, _postop_bucket_tokens, get_rda_ul_context_for_subject
from .pubmed_query_builder import extract_search_slots, build_intent_queries, normalize_subject_with_priority
from .gating import _is_valid_primary_subject, _looks_like_sentence_primary
from .llm_prompts import _extract_english_keywords_with_ai, _english_pubmed_phrase_fallback

def build_english_patient_context(
    user_input: str,
    conditions: str = "",
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    pre_slots: Optional[Dict] = None,
) -> Dict[str, object]:
    """
    환자 컨텍스트를 영문으로 정제하고 검색 슬롯(intent, thyroid_context, primary_subject)을 추출합니다.
    extract_search_slots (AI + 규칙 폴백) 를 우선 사용하고,
    PrimarySubject 공백 시 기존 _extract_english_keywords_with_ai 로 보완합니다.

    pre_slots: 상위 레이어(orchestrator/API)에서 이미 추론한 intent·thyroid_context.
               제공되면 extract_search_slots LLM 호출을 스킵하고 규칙 보정만 수행.
    """
    if pre_slots:
        # 상위 추론값 우선 사용 — LLM extract_search_slots 스킵
        from .pubmed_query_builder import detect_intent_rule, detect_thyroid_context_rule
        intents_rule = detect_intent_rule(user_input)
        thyroid_ctx_rule = detect_thyroid_context_rule(user_input, conditions)
        primary_subject = normalize_subject_with_priority(
            primary_subject="",
            user_input=user_input,
            conditions=conditions,
            medications=medications,
        )
        intent = pre_slots.get("intent", intents_rule[0] if intents_rule else "safety")
        thyroid_context = pre_slots.get("thyroid_context", thyroid_ctx_rule[0] if thyroid_ctx_rule else "general")
        slots = {
            "primary_subject": primary_subject,
            "thyroid_context": thyroid_context,
            "intent": intent,
            "population": "adult",
            "keywords": "",
            "intents_rule": intents_rule,
            "thyroid_ctx_rule": thyroid_ctx_rule,
        }
    else:
        # ① 새 슬롯 추출기 (intent + thyroid_context + primary_subject) — LLM 포함
        slots = extract_search_slots(user_input, conditions, medications)

    primary_subject = slots.get("primary_subject", "").strip()
    intent = slots.get("intent", "safety")
    thyroid_context = slots.get("thyroid_context", "general")
    slot_keywords = slots.get("keywords", "")

    # ② primary_subject 공백 시 기존 AI 추출로 보완
    if not primary_subject or not _is_valid_primary_subject(primary_subject):
        ai_result = _extract_english_keywords_with_ai(user_input, conditions, medications)
        primary_subject = str(ai_result.get("PrimarySubject", "") or "").strip()
        if not primary_subject:
            primary_subject = _english_pubmed_phrase_fallback(user_input)
        extra_keywords = ai_result.get("Keywords", "")
    else:
        extra_keywords = slot_keywords

    # 요청 반영: 허용 성분 도메인(오메가3, 비타민D, 티록신, 셀레늄, 레티놀아세테이트, 요오드)으로 강제 정규화
    # 허용 리스트 밖 성분이면 primary_subject를 비워 검색 확장을 차단합니다.
    primary_subject = normalize_subject_with_priority(
        primary_subject=primary_subject,
        user_input=user_input,
        conditions=conditions,
        medications=medications,
    )

    refined_keywords_en = f"{primary_subject} {extra_keywords}".strip()

    translated_conditions = _translate_korean_text(conditions)
    translated_medications = _translate_korean_text(medications)

    profile_parts = []
    if age:
        profile_parts.append(f"{age}-year-old")
    if sex == "M":
        profile_parts.append("male")
    elif sex == "F":
        profile_parts.append("female")
    if height:
        profile_parts.append(f"height {height} cm")
    if weight:
        profile_parts.append(f"weight {weight} kg")
    if translated_conditions:
        profile_parts.append(f"conditions: {translated_conditions}")
    if translated_medications:
        profile_parts.append(f"medications: {translated_medications}")

    combined = _normalize_text(" ".join([
        refined_keywords_en,
        translated_conditions,
        translated_medications,
        " ".join(profile_parts),
    ]))

    supplements = _merge_supplement_signals(primary_subject, combined)
    conditions_found = _extract_present_terms(combined, CONDITION_HINTS)
    medications_found = _extract_present_terms(combined, MEDICATION_HINTS)

    # intent_terms: 슬롯 추출 결과를 기반으로 (기존 호환성 유지)
    intent_terms: List[str] = [intent] if intent else []
    if "interaction" in extra_keywords.lower() and "interaction" not in intent_terms:
        intent_terms.append("interaction")

    return {
        "question_en": refined_keywords_en,
        "primary_subject": primary_subject,
        "extra_keywords": extra_keywords,
        "conditions_en": translated_conditions,
        "medications_en": translated_medications,
        "profile_en": _normalize_text(", ".join(profile_parts)),
        "combined_en": combined,
        "supplements": supplements,
        "conditions": conditions_found,
        "medications": medications_found,
        "intents": intent_terms,
        # 새 슬롯 필드
        "intent": intent,
        "thyroid_context": thyroid_context,
        "population": slots.get("population", "adult"),
        "intents_rule": slots.get("intents_rule", []),
        "thyroid_ctx_rule": slots.get("thyroid_ctx_rule", []),
    }


def generate_pubmed_queries(
    user_input: str,
    conditions: str = "",
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    _context: Optional[Dict] = None,  # 이미 생성된 context를 재사용할 때 전달
) -> List[str]:
    """
    Intent + thyroid_context 기반의 PubMed 질의를 생성합니다.
    build_intent_queries (새 모듈) 를 주 경로로 사용하고, 기존 방식으로 보완합니다.
    """
    context = _context or build_english_patient_context(
        user_input=user_input,
        conditions=conditions,
        medications=medications,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
    )

    primary = _normalize_english_query_text(str(context.get("primary_subject", "") or "").strip())
    extra_keywords = _normalize_english_query_text(str(context.get("extra_keywords", "") or "").strip())
    intent = str(context.get("intent", "safety") or "safety")
    thyroid_context = str(context.get("thyroid_context", "general") or "general")

    # 시간 숫자는 PubMed 쿼리에 넣지 않음 (버킷 토큰으로만 처리)
    primary = _strip_time_expressions_en(primary)
    extra_keywords = _strip_time_expressions_en(extra_keywords)
    if not _is_valid_primary_subject(primary):
        primary = _english_pubmed_phrase_fallback(user_input)
        primary = _strip_time_expressions_en(primary)
    primary = normalize_subject_with_priority(
        primary_subject=primary,
        user_input=user_input,
        conditions=conditions,
        medications=medications,
    )
    # 허용 성분 도메인 밖 질문은 PubMed 검색 질의를 만들지 않음
    if not primary:
        return []

    postop_tokens = _postop_bucket_tokens(user_input)

    # extra_keywords 노이즈 제거
    if extra_keywords:
        noisy = {"health", "thyroid health", "general health"}
        ek_tokens = [
            t for t in re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", extra_keywords.lower()) if t
        ]
        ek_tokens = [t for t in ek_tokens if t not in noisy]
        extra_keywords = _normalize_text(" ".join(dict.fromkeys(ek_tokens)))

    existing_conditions = context.get("conditions") or []
    existing_medications = context.get("medications") or []
    existing_supplements = context.get("supplements") or []

    queries: List[str] = []
    query_signatures: set = set()

    def add_query(query: str) -> None:
        q = _force_thyroid_domain_query(_normalize_text(query))
        if not q:
            return
        tokens = re.findall(r"[a-z0-9]+", q.lower())
        sig = " ".join(sorted(set(tokens)))
        if sig in query_signatures:
            return
        query_signatures.add(sig)
        if q not in queries:
            queries.append(q)

    # ── 신규: intent + thyroid_context 기반 템플릿 쿼리 ──────────────────
    if primary:
        intent_qs = build_intent_queries(
            primary_subject=primary,
            thyroid_context=thyroid_context,
            intent=intent,
            postop_tokens=postop_tokens,
            conditions=existing_conditions,
            medications=existing_medications,
            extra_keywords=extra_keywords,
        )
        for q in intent_qs:
            add_query(q)

    # ── 기존 방식 보완 쿼리 (검색 재현율 확보) ───────────────────────────
    if primary:
        # 상호작용 검색 (interaction intent 또는 기존 복용약 있을 때)
        all_existing = list(dict.fromkeys(existing_supplements + existing_medications))
        has_interaction_intent = intent == "interaction" or any(
            k in extra_keywords.lower() for k in ["interaction", "absorption", "interference"]
        )
        if all_existing and has_interaction_intent:
            for item in all_existing[:2]:
                if item.lower() not in primary.lower():
                    add_query(
                        f"({primary}) AND ({item}) AND (interaction OR absorption OR coadministration)"
                    )

        # 수술후 안전성 보완
        if postop_tokens:
            add_query(
                f"({primary}) AND ({' OR '.join(postop_tokens)}) AND (safety OR adverse OR complication)"
            )

        # 일반 보충/안전성 (백업)
        add_query(f"({primary}) AND (supplementation OR supplement OR intake OR safety OR deficiency)")

    return queries[:8]


