"""
domain.thyroid.doctor_search_context

의사 상담 검색 컨텍스트 추론.
1차: 키워드 매칭 (빠르고 안정적)
2차: focus="general"이면 LLM으로 재판단 (키워드가 실패한 애매한 질문)
"""

from __future__ import annotations

import json
import os
from typing import Optional

_DOCTOR_FOCUS_SYSTEM_PROMPT = (
    "You are a search context classifier for a Korean thyroid supplement clinical consultation system.\n"
    "The user is a physician. Classify the search focus and thyroid context from the message.\n\n"
    "focus values (choose one):\n"
    "- interaction: drug-supplement absorption interference or pharmacokinetic interaction\n"
    "- dosage: optimal dose, dose adjustment, dosing interval, how much\n"
    "- monitoring: lab follow-up, TSH tracking, clinical monitoring schedule\n"
    "- general: none of the above\n\n"
    "thyroid_context values (choose one):\n"
    "- hashimoto: Hashimoto thyroiditis, autoimmune thyroiditis, TPO antibody\n"
    "- graves: Graves disease, hyperthyroidism\n"
    "- thyroidectomy_postop: post-thyroidectomy, thyroid cancer surgery\n"
    "- hypothyroidism: hypothyroidism, low thyroid function\n"
    "- general: none of the above or unclear\n\n"
    "Return ONLY valid JSON, no other text:\n"
    "{\"focus\": \"<value>\", \"thyroid_context\": \"<value>\"}"
)


def _keyword_resolve(message: str, conditions: str) -> dict:
    """키워드 기반 1차 추론."""
    msg = (message or "").lower()
    cond = (conditions or "").lower()

    if any(k in msg for k in ["흡수", "상호작용", "간섭", "병용", "같이 먹", "같이먹",
                               "absorption", "interaction", "interference", "coadmin"]):
        focus = "interaction"
    elif any(k in msg for k in ["용량", "얼마나", "몇 mg", "몇mg", "적정량", "권장량",
                                 "dosage", "dose", "how much"]):
        focus = "dosage"
    elif any(k in msg for k in ["모니터링", "추적", "검사 주기", "tsh 확인",
                                 "monitoring", "follow"]):
        focus = "monitoring"
    else:
        focus = "general"

    if any(k in msg for k in ["논문", "근거", "연구", "문헌", "evidence", "paper", "study", "pubmed"]):
        intent = "evidence_query"
    elif focus == "interaction" or any(k in msg for k in ["위험", "부작용", "안전", "risk", "safety"]):
        intent = "safety_query"
    else:
        intent = "supplement_query"

    combined = f"{cond} {msg}"
    if any(k in combined for k in ["하시모토", "hashimoto", "자가면역 갑상선", "tpo 항체"]):
        thyroid_context = "hashimoto"
    elif any(k in combined for k in ["그레이브스", "graves", "항진증", "hyperthyroid"]):
        thyroid_context = "graves"
    elif any(k in combined for k in ["전절제", "절제술", "thyroidectomy", "갑상선 수술", "갑상선암"]):
        thyroid_context = "thyroidectomy_postop"
    elif any(k in combined for k in ["저하증", "hypothyroid", "기능저하"]):
        thyroid_context = "hypothyroidism"
    else:
        thyroid_context = "general"

    return {"intent": intent, "focus": focus, "thyroid_context": thyroid_context}


def _llm_resolve(message: str, conditions: str) -> Optional[dict]:
    """LLM 기반 2차 추론. focus="general"일 때만 호출. 실패 시 None."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        user_content = f"physician message: {message}\npatient conditions: {conditions or 'unknown'}"
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _DOCTOR_FOCUS_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_tokens=40,
            temperature=0,
        )
        parsed = json.loads(resp.choices[0].message.content.strip())
        valid_focus = {"interaction", "dosage", "monitoring", "general"}
        valid_ctx = {"hashimoto", "graves", "thyroidectomy_postop", "hypothyroidism", "general"}
        return {
            "focus": parsed.get("focus", "general") if parsed.get("focus") in valid_focus else "general",
            "thyroid_context": parsed.get("thyroid_context", "general") if parsed.get("thyroid_context") in valid_ctx else "general",
        }
    except Exception:
        return None


def resolve_doctor_search_context(message: str, conditions: str) -> dict:
    """
    의사 메시지·진단에서 검색 초점을 추론합니다.
    1차 키워드 매칭 → focus="general"이면 LLM 재판단.

    Returns:
        dict with keys:
          focus:          "interaction" | "dosage" | "monitoring" | "general"
          intent:         "evidence_query" | "safety_query" | "supplement_query"
          thyroid_context: "hashimoto" | "graves" | "thyroidectomy_postop"
                           | "hypothyroidism" | "general"
    """
    result = _keyword_resolve(message, conditions)

    if result["focus"] == "general":
        llm_result = _llm_resolve(message, conditions)
        if llm_result:
            result["focus"] = llm_result["focus"]
            if llm_result["thyroid_context"] != "general" and result["thyroid_context"] == "general":
                result["thyroid_context"] = llm_result["thyroid_context"]

    return result
