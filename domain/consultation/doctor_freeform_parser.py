"""
의사용 자유 입력(freeform) 파싱. 자연어 메시지에서 supplement, dose, conditions, medications를 추출합니다.
규칙 기반 intent / thyroid_context 도 함께 반환합니다.
"""
import json
import os
import re
from typing import Dict, Tuple

from openai import OpenAI

from .pubmed.pubmed_query_builder import detect_intent_rule, detect_thyroid_context_rule


SYSTEM_PROMPT = """당신은 의사가 진료 중 입력한 자연어 문장에서 보충제 검토에 필요한 정보를 추출하는 도우미입니다.
다음 JSON 형식으로만 응답하세요. 값이 없으면 빈 문자열 "" 로 두세요.

{"supplement": "보충제/성분명", "dose": "용량(예: 4g/day)", "conditions": "질환(쉼표구분)", "medications": "복용약(쉼표구분)"}

예시:
- "오메가3 4g 먹고 있는데 고혈압에 ARB 스타틴 써" → {"supplement": "오메가3", "dose": "4g/day", "conditions": "고혈압", "medications": "ARB, 스타틴"}
- "크롬 혈당 효과 알려줘 당뇨에 메트포르민" → {"supplement": "크롬", "dose": "", "conditions": "당뇨", "medications": "메트포르민"}
- "58세 남자 고혈압 고지혈증 ARB 스타틴 복용 중 오메가3 4g/day" → {"supplement": "오메가3", "dose": "4g/day", "conditions": "고혈압, 고지혈증", "medications": "ARB, 스타틴"}
- "2g 정도만 먹어도 될까요" → {"supplement": "", "dose": "2g/day", "conditions": "", "medications": ""}
"""


def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)


def parse_doctor_freeform(
    message: str,
    patient_conditions: str = "",
    patient_medications: str = "",
) -> Tuple[str, str, str, str]:
    """
    자연어 메시지에서 supplement, dose, conditions, medications를 추출합니다.
    patient_* 가 있으면 메시지에 없는 경우 보완용으로 사용합니다.
    Returns: (supplement, dose, conditions, medications)
    """
    message = (message or "").strip()
    if not message:
        return "", "", patient_conditions or "", patient_medications or ""

    client = _get_client()
    user_content = message
    if patient_conditions or patient_medications:
        user_content += f"\n\n[참고: 선택된 환자 - 질환: {patient_conditions or '없음'}, 복용약: {patient_medications or '없음'}]"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = (response.choices[0].message.content or "").strip()
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            supplement = str(data.get("supplement", "") or "").strip()
            dose = str(data.get("dose", "") or "").strip()
            conditions = str(data.get("conditions", "") or "").strip() or patient_conditions
            medications = str(data.get("medications", "") or "").strip() or patient_medications
            return supplement, dose, conditions, medications
    except Exception:
        pass

    return "", "", patient_conditions or "", patient_medications or ""


def parse_doctor_freeform_extended(
    message: str,
    patient_conditions: str = "",
    patient_medications: str = "",
) -> Dict:
    """
    parse_doctor_freeform 결과 + 규칙 기반 intent / thyroid_context 를 추가로 반환합니다.

    Returns:
        {
          "supplement": str,
          "dose": str,
          "conditions": str,
          "medications": str,
          "intent": str,          # 1차 intent (safety/postop/efficacy/…)
          "thyroid_context": str, # hashimoto/postop/graves/… (첫 번째 감지 값)
        }
    """
    supplement, dose, conditions, medications = parse_doctor_freeform(
        message, patient_conditions, patient_medications
    )
    combined_conditions = conditions or patient_conditions
    intents = detect_intent_rule(message)
    thyroid_ctxs = detect_thyroid_context_rule(message, combined_conditions)
    return {
        "supplement": supplement,
        "dose": dose,
        "conditions": conditions,
        "medications": medications,
        "intent": intents[0] if intents else "safety",
        "thyroid_context": thyroid_ctxs[0] if thyroid_ctxs else "general",
    }
