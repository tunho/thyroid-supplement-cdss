"""
domain.thyroid.llm_response — Rule 판단 결과를 LLM 자연어로 변환

generate_chat_response():
  - Rule 엔진의 DecisionResult를 받아 GPT-4o-mini로 대화체 응답 생성
  - 실패 시 None 반환 → 호출부에서 기존 summary 사용

generate_recommendation_response():
  - 진단명 기반 영양제 추천 안내
"""

from __future__ import annotations

import os
from typing import Optional

from domain.thyroid.schemas import Decision, DecisionResult, WarningSeverity

_DECISION_KO = {
    "recommend": "안전/권장",
    "conditional_consider": "조건부 가능",
    "manage_interaction": "상호작용 관리(복용 분리)",
    "avoid": "피해야 함",
    "contraindicated": "금기",
    "insufficient_evidence": "근거 부족",
}

# 성분별 MFDS 표준 기능성 (건강기능식품 고시형 원료 인정 기능성).
# 출처: 식약처 건강기능식품 기능성 원료 고시 — 단일 성분 표준 문구.
# DB 스크랩(복합제·교차오염·포맷 제각각)을 대체 → 규제 노트에 깨끗한 성분 기능성만 노출.
_MFDS_FUNCTION = {
    "iodine": "갑상선 호르몬의 합성에 필요 / 에너지 생성에 필요 / 신경 발달에 필요",
    "selenium": "유해산소로부터 세포를 보호하는 데 필요",
    "iron": "체내 산소 운반과 혈액 생성에 필요 / 에너지 생성에 필요",
    "vitamin_d": "칼슘과 인이 흡수되고 이용되는 데 필요 / 뼈의 형성과 유지에 필요 / 골다공증 발생 위험 감소에 도움",
    "zinc": "정상적인 면역 기능에 필요 / 정상적인 세포 분열에 필요",
    "magnesium": "에너지 이용에 필요 / 신경과 근육 기능 유지에 필요",
    "calcium": "뼈와 치아 형성에 필요 / 신경과 근육 기능 유지에 필요 / 정상적인 혈액 응고에 필요 / 골다공증 발생 위험 감소에 도움",
    "probiotics": "유산균 증식 및 유해균 억제 / 배변 활동 원활에 도움",
}


def fetch_mfds_context(supplement_name: str) -> str:
    """MFDS health_food DB에서 기능성 + 섭취량 조회 → 프롬프트용 텍스트. DB 없으면 빈 문자열."""
    try:
        from domain.mfds.db import search_health_food
        # 1순위: 큐레이션된 성분 표준 기능성 (깨끗·정확·출처 가능) — 복합제 블리딩 원천 차단.
        # supplement_name 은 한글("요오드")일 수 있으므로 canonical key로 정규화 후 조회.
        from domain.thyroid.rules import _resolve_supplement_key
        func = _MFDS_FUNCTION.get(_resolve_supplement_key(supplement_name))
        if func:
            return f"  * 기능성: {func}\n  * (출처: 식약처 건강기능식품 기능성 원료 고시)"
        # fallback: 큐레이션 없는 성분만 DB 스크랩 대표 1건 (가장 짧은 기능성).
        rows = search_health_food(supplement_name)
        candidates = [r for r in (rows or []) if (r.get("primary_function") or "").strip()]
        if not candidates:
            return ""
        candidates.sort(key=lambda r: len((r.get("primary_function") or "").strip()))
        r = candidates[0]
        lines = [f"  * 기능성: {r['primary_function'].strip()}"]
        if (r.get("intake_amount") or "").strip():
            lines.append(f"  * 섭취량: {r['intake_amount'].strip()}")
        return "\n".join(lines)
    except Exception:
        return ""


def _call_llm(prompt: str, max_tokens: int = 250) -> Optional[str]:
    """공통 LLM 호출 헬퍼. 실패 시 None 반환."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text if text else None
    except Exception as e:
        print(f"[llm_response] LLM 호출 실패: {e}")
        return None


def _build_evidence_section(records: list | None) -> str:
    """PubMed evidence_records → 프롬프트용 섹션. 상위 3건만, 제목/연도/근거수준."""
    if not records:
        return ""
    lines = []
    for r in records[:3]:
        title = (getattr(r, "title", "") or "").strip()[:120]
        year = getattr(r, "year", "") or ""
        ev = getattr(r, "evidence_level", None)
        level = getattr(ev, "value", "") if ev else ""
        if title:
            tag = f"{year}|{level}".strip("|")
            prefix = f"[{tag}] " if tag else ""
            lines.append(f"  - {prefix}{title}")
    if not lines:
        return ""
    return "\n\n【PubMed 검색 결과】\n" + "\n".join(lines)


def _build_history_section(history: list[dict] | None) -> str:
    """대화 히스토리 → 프롬프트용 섹션 문자열."""
    if not history:
        return ""
    lines = []
    for h in history[-3:]:
        r = h.get("role", "")
        m = h.get("message", "")[:100]
        if r and m:
            role_ko = "사용자" if r == "user" else "AI"
            lines.append(f"  {role_ko}: {m}")
    if not lines:
        return ""
    return "\n\n【이전 대화】\n" + "\n".join(lines)


def generate_chat_response(
    result: DecisionResult,
    display_name: str,
    conditions: str = "",
    medications: str = "",
    study_dose: str = "",
    official_upper_limit: str = "",
    history: list[dict] | None = None,
    original_term: str | None = None,
    is_update_turn: bool = False,
    message: str = "",
) -> Optional[str]:
    """
    Rule 결과 → LLM 자연어 응답 생성.
    실패 또는 INSUFFICIENT_EVIDENCE 이면 None 반환.
    """
    decision_ko = _DECISION_KO.get(result.decision.value, result.decision.value) if result.decision else "판단 보류"

    # 실제 경고만 표시 (severity 필터 + 없으면 경고 섹션 자체 제외)
    actual_warnings = [
        w for w in result.safety_warnings[:3]
        if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
    ] if result.safety_warnings else []
    warnings_section = ""
    if actual_warnings:
        warnings_lines = "\n".join(f"  * {w.message}" for w in actual_warnings)
        warnings_section = f"\n경고:\n{warnings_lines}"

    recommendations_text = (
        ", ".join(result.counseling_points[:2])
        if result.counseling_points
        else ", ".join(result.recommendations[:2]) if result.recommendations
        else "전문의 상담"
    )

    # §7.2 Regimen-aware — 입력된 복용 타이밍 판정을 LLM 안내에 반영(일반 '4시간' 지시 대신).
    regimen_guide = ""
    _rs = (result.regimen_assessment or {}).get("status")
    if _rs == "separated":
        regimen_guide = (
            "\n\n【복용 시간 안내 — 우선 반영】 환자는 이미 갑상선 호르몬제와 이 영양제를 충분히 "
            "떨어진 시간대(예: 아침/취침 전)에 복용하고 있습니다. 따라서 '새로 4시간 간격을 두라'는 "
            "지시는 하지 말고, '현재 복용 간격이라면 흡수 간섭을 피하는 데 적절하다'고 안심시킨 뒤 "
            "TSH 등 갑상선 수치를 정기적으로 확인하라고 안내하세요."
        )
    elif _rs == "concurrent":
        regimen_guide = (
            "\n\n【복용 시간 안내 — 우선 반영】 환자는 현재 갑상선 호르몬제와 이 영양제를 비슷한 "
            "시간대에 복용하고 있어 흡수 간섭 우려가 있습니다. 복용 시간을 최소 4시간 이상 떨어뜨리는 "
            "것이 도움이 된다고 안내하고 담당의·약사와 복용 간격을 확인하라고 권고하세요."
        )

    mfds_context = fetch_mfds_context(display_name)
    # §9.2: "연구 사용 용량"과 "공식 기준/상한"을 분리 제시 (§9.1: "권장 용량" 직접 제시 금지)
    mfds_section = ""
    if study_dose or official_upper_limit or mfds_context:
        mfds_section = "\n\n【연구·공식 참고 정보】"
        if study_dose:
            mfds_section += f"\n연구에서 사용된 용량: {study_dose}"
        if official_upper_limit:
            mfds_section += f"\n공식 기준/상한: {official_upper_limit}"
        if mfds_context:
            mfds_section += f"\n식약처 기능성·섭취량 기준:\n{mfds_context}"

    history_section = _build_history_section(history)
    question_section = f"\n사용자 질문: {message.strip()}" if message and message.strip() else ""
    evidence_section = _build_evidence_section(result.evidence_records[:2]) if result.evidence_records else ""

    name_section = f"'{original_term}'({display_name})" if original_term and original_term.lower() != display_name.lower() else display_name

    # 의학적 모순(진단명-복용약 상충) 사전 연산 (Deterministic Contradiction Detection)
    deterministic_contradiction = ""
    cond_lower = (conditions or "").lower()
    med_lower = (medications or "").lower()
    
    hypo_terms = ["저하", "하시모토", "hashimoto", "hypo"]
    anti_thyroid_terms = ["메티마졸", "methimazole", "ptu", "프로필티오우라실", "안티로이드", "카비마졸"]
    hyper_terms = ["항진", "그레이브스", "graves", "hyper"]
    hormone_terms = ["씬지", "레보티록신", "신지", "levothyroxine", "synthroid", "컴파운드"]
    
    if any(c in cond_lower for c in hypo_terms) and any(m in med_lower for m in anti_thyroid_terms):
        deterministic_contradiction = "\n\n⚠️ [SYSTEM ALARM: FATAL MEDICAL CONTRADICTION DETECTED] ⚠️\n환자는 '저하증/하시모토' 질환을 가졌으나, 항진증 치료제인 '메티마졸/PTU'를 복용 중이라고 입력했습니다. 답변의 가장 첫 문장에서 이 모순을 부드럽게 지적하고 진단명과 약물명을 꼭 다시 확인하라고 안내해야 합니다."
    elif any(c in cond_lower for c in hyper_terms) and any(m in med_lower for m in hormone_terms):
        deterministic_contradiction = "\n\n⚠️ [SYSTEM ALARM: FATAL MEDICAL CONTRADICTION DETECTED] ⚠️\n환자는 '항진증/그레이브스병' 질환을 가졌으나, 저하증 치료제인 '씬지로이드/레보티록신'을 복용 중이라고 입력했습니다. 답변의 가장 첫 문장에서 이 모순을 부드럽게 지적하고 진단명과 약물명을 꼭 다시 확인하라고 안내해야 합니다."

    # 의학적 모순(진단명-복용약 상충) 감지 가이드 추가
    if deterministic_contradiction:
        mismatch_guide = f"""
【🚨 임상적 모순 감지 및 대응 지침】
환자의 질환(진단명)과 복용 약물 간에 심각한 의학적 모순이 감지되었습니다!
질문에 기계적으로 답변하기 전에 이를 반드시 부드럽게 지적하고 진단명이나 약물명을 다시 확인해 달라고 정중하게 요청하세요.{deterministic_contradiction}
"""
    else:
        mismatch_guide = ""

    if is_update_turn:
        prompt = f"""당신은 갑상선 환자를 위한 영양제 상담 전문가입니다.
사용자가 이전 대화에 이어 새로운 상태 정보(복용 약물: {medications or '없음'}, 질환: {conditions or '불명'})를 추가/확인해 준 상황입니다.

이전 판단을 번복하거나 영양제에 대한 전체적인 효능 소개를 처음부터 다시 장황하게 반복하지 마세요. 이전 대화(History)에서 이미 설명한 영양제의 기본적인 효능이나 일반 정보(예: "마그네슘은 에너지 이용과...")를 절대 처음부터 장황하게 반복하지 마세요. 
오직 사용자가 새로 추가/질문한 약물 정보에 결합된 실질적인 답변에만 온전히 집중하세요.

【판단 정보】
영양제: {name_section}
결정: {decision_ko}{warnings_section}
근거: {result.rationale or '없음'}
환자 질환: {conditions or '불명'}
복용 약물: {medications or '없음'}{question_section}{mfds_section}{history_section}
{mismatch_guide}{regimen_guide}

【응답 요구사항】
1. 분량은 반드시 120-220자 범위 (초과 금지, 짧고 핵심만 답변)
2. [🚨의학적 모순 감지]: 만약 환자의 질환(예: 하시모토/저하증)과 복용 약물(예: 메티마졸/프로필티오우라실/ptu/안티로이드) 사이에 상충되는 의학적 모순이 있다면(예: 저하증인데 호르몬 분비를 억제하는 항갑상선제를 복용하거나, 반대로 항진증/그레이브스병인데 호르몬제를 복용하는 경우), 다른 모든 요구사항보다 우선하여 이 모순을 첫 문장에서 친절히 지적하고 진단명이나 약물명을 꼭 다시 확인해보도록 권고하세요.
3. 추가되거나 변경된 정보(예: '메티마졸 복용을 확인했습니다')를 자연스럽게 언급하세요.
4. 새로 추가된 약물과 영양제 간의 상호작용 여부를 명확히 설명하세요.
   - 예: 메티마졸과 마그네슘은 상호작용이 없는 편이지만 복용 시간차 등을 가볍게 짚어주세요.
   - 만약 상호작용 주의가 필요한 경우(예: 갑상선 호르몬제와 철분·칼슘·마그네슘·아연) '갑상선 호르몬제는 공복에 복용하고 다른 약·영양제와 간격을 두는 것이 중요합니다. 담당의와 복용 간격을 확인하세요'라고 안내하세요. (§13.1: "4시간" 단독 강조 대신 공복·상담 중심 안내)
5. 기존 권장 사항을 한 줄로 아주 가볍게 요약 리마인드하며 전문의 상담 권고로 마무리하세요.
6. 인사말(안녕하세요 등)로 절대 시작하지 마세요.
"""
        res = _call_llm(prompt, max_tokens=220)
        is_med_empty = not medications or any(medications.strip() == m for m in ("칼슘제", "철분제", "제산제", "none", "없음"))
        if res and is_med_empty:
            target_q = "혹시 현재 복용 중인 약이 있으신가요? 약물 정보가 있으면 더 정확한 안내가 가능합니다."
            if target_q not in res:
                res = res.strip() + "\n\n" + target_q
        return res

    # INSUFFICIENT_EVIDENCE: 별도 프롬프트로 LLM 답변 생성 (근거 부족 명시)
    if result.decision == Decision.INSUFFICIENT_EVIDENCE:
        notes = (result.rationale or "").strip()
        evidence_section = _build_evidence_section(result.evidence_records)
        has_evidence = bool(result.evidence_records)

        evidence_tone = (
            "관련 연구가 있으나 갑상선 질환에 대한 직접 임상 근거는 제한적"
            if has_evidence
            else "갑상선 질환에 대한 직접적인 임상 근거가 부족"
        )

        insufficient_prompt = f"""당신은 갑상선 환자를 위한 영양제 근거·위험 정보 제공 전문가입니다.
근거가 부족하다는 사실 자체가 중요한 정보입니다. "근거 부족"으로 단정하지 말고 아래 항목을 가능한 범위에서 제시하세요. (§8.1)

환자: 갑상선 질환 {conditions or '불명'} / 복용 약물 {medications or '없음'}
문의 성분: {display_name}{question_section}

{f'참고 정보: {notes}' if notes else ''}
{f'식약처 데이터: {mfds_context}' if mfds_context else ''}{evidence_section}{history_section}
{mismatch_guide}

【응답 요구사항】
1. 200~280자 이내
2. "{evidence_tone}하다"는 점을 자연스럽게 언급
3. 가능하다면 다음 항목 중 해당되는 것만 간략히 포함: 현재 확인된 근거 수준 / 연구에서 사용된 용량 / 보고된 효과 또는 부작용 / 갑상선 환자 대상 근거 여부 / 근거의 한계
{f'4. 관련 연구가 있다면 어떤 연구인지 한 줄로 요약 (단, "근거 충분하다"고 단정하지 말 것)' if has_evidence else ''}
5. "복용 전 전문의 상담을 권고합니다"로 마무리
6. 인사말 없이 바로 핵심으로 시작
7. PMID·연도 같은 메타데이터는 응답에 포함하지 말 것
8. "복용하세요" 또는 "복용하지 마세요" 같은 단정 지시 금지"""
        res = _call_llm(insufficient_prompt, max_tokens=240)
        is_med_empty = not medications or any(medications.strip() == m for m in ("칼슘제", "철분제", "제산제", "none", "없음"))
        if res and is_med_empty:
            target_q = "혹시 현재 복용 중인 약이 있으신가요? 약물 정보가 있으면 더 정확한 안내가 가능합니다."
            if target_q not in res:
                res = res.strip() + "\n\n" + target_q
        return res

    medication_followup = (
        "\n10. 복용 약물 정보가 없습니다. 답변 마지막에 '혹시 현재 복용 중인 약이 있으신가요? 약물 정보가 있으면 더 정확한 안내가 가능합니다.' 라고 자연스럽게 한 문장으로 추가하세요."
        if not medications else ""
    )

    prompt = f"""당신은 갑상선 환자를 위한 영양제 근거·위험 정보 제공 전문가입니다.
시스템의 판단 결과를 바탕으로 근거와 위험 정보 중심으로 안내하세요. 단정적 처방·"복용하세요/하지 마세요" 지시는 금지합니다. (§2, §7)

【판단 정보】
영양제: {name_section}
결정: {decision_ko}{warnings_section}
근거: {result.rationale or '없음'}
권고: {recommendations_text}
환자 질환: {conditions or '불명'}
복용 약물: {medications or '없음'}{question_section}{mfds_section}{evidence_section}{history_section}
{mismatch_guide}{regimen_guide}

【응답 요구사항】
1. 반드시 200-350자 범위 (초과 금지)
2. 현재 확인 가능한 근거 수준과 왜 이 영양제가 관련 있는지 설명 (단정 X)
3. 경고가 있으면 "피해야 한다"가 아닌 위험 정보와 근거를 중심으로 설명
4. 용량은 "권장 용량"이 아닌 "연구에서 사용된 용량" 또는 "공식 기준 참고치"로만 언급
5. 갑상선 호르몬제(레보티록신 등) 복용자에게는 공복 복용·간격 안내를 상담 권고 중심으로 설명 (§13.1)
6. 전문의 상담 권고로 마무리
7. 인사말(안녕하세요 등)으로 절대 시작하지 말 것 — 영양제 이름 또는 근거로 바로 시작
8. 자연스러운 대화체, 의학 전문용어 최소화
9. 브랜드명이 있을 경우 '브랜드명(성분명)은...' 형식으로 첫 문장 시작{medication_followup}

【예시】
셀레늄은 일부 연구에서 갑상선 항체(TPOAb) 수치를 낮추는 데 도움이 될 가능성이 보고되었습니다. 다만 연구마다 사용된 용량과 대상이 다르고 개인 상태에 따라 효과가 다를 수 있으므로, 실제 복용 여부와 용량은 담당 전문의와 상의 후 결정하시기 바랍니다."""

    res = _call_llm(prompt, max_tokens=300)
    
    # 약물이 비어있거나, 칼슘제/철분제/제산제처럼 영양제 문의에서 오추출될 수 있는 값만 존재할 경우 약물 질문 추가
    is_med_empty = not medications or any(medications.strip() == m for m in ("칼슘제", "철분제", "제산제", "none", "없음"))
    if res and is_med_empty:
        target_q = "혹시 현재 복용 중인 약이 있으신가요? 약물 정보가 있으면 더 정확한 안내가 가능합니다."
        if target_q not in res:
            res = res.strip() + "\n\n" + target_q
    return res


def generate_doctor_llm_summary(
    result: DecisionResult,
    physician: Optional[object],
    supplement_display: str,
    conditions: str = "",
    medications: str = "",
    message: str = "",
    reported_effects: str = "",
    counseling_points: Optional[list] = None,
    rationale: Optional[str] = None,
    interaction_dominated: bool = False,
) -> Optional[str]:
    """
    의사용 임상 서술 생성. rule formatter의 conclusion을 대체.
    PubMed 논문 연결 + 의사 성향 반영 + 전문 임상체.
    실패 시 None 반환 → 호출부에서 rule 텍스트로 fallback.

    counseling_points / rationale: 호출부에서 환자 [조건] 태그로 필터한 값을 전달.
      미전달(None) 시 result 원본 사용(하위호환). 순환 import 회피 위해 필터는 호출부 책임.
    """
    decision_ko = _DECISION_KO.get(result.decision.value, result.decision.value)

    # 환자 조건 필터된 값 우선 — GO/TED 등 진단 무관 적응증 누출 차단
    counseling_src = counseling_points if counseling_points is not None else result.counseling_points
    rationale_src = rationale if rationale is not None else result.rationale

    # 근거 논문 섹션 (상위 3건)
    evidence_section = _build_evidence_section(result.evidence_records)

    # 경고 섹션
    critical_warnings = [
        w for w in (result.safety_warnings or [])
        if w.severity.value in ("critical", "warning")
    ]
    warning_text = ""
    if critical_warnings:
        warning_text = "\n경고: " + "; ".join(w.message for w in critical_warnings[:2])

    # 의사 성향 반영
    risk_tolerance = "moderate"
    if physician:
        risk_tolerance = getattr(physician, "risk_tolerance", "moderate") or "moderate"
    tolerance_guide = {
        "conservative": "충분한 근거가 확보될 때까지 대기 전략도 합리적입니다.",
        "moderate":     "표준 용량 범위에서 시작하며 추적 관찰을 권고합니다.",
        "aggressive":   "근거 수준을 감안하여 시험적 투여도 고려할 수 있습니다.",
    }.get(risk_tolerance, "")
    # #4.3 상호작용 지배 케이스(LT4 흡수저해 성분 + LT4 복용 중)에서는 "표준 용량 시작"이
    # 무의미 → 흡수 관리 중심으로 교체 (moderate 한정).
    if interaction_dominated and risk_tolerance == "moderate":
        tolerance_guide = ("용량보다 레보티록신과의 복용 시간 분리·흡수 관리가 핵심이며, "
                           "용량은 적응증·검사 결과에 따라 조정합니다.")

    counseling_context = ""
    if counseling_src:
        lines = "\n".join(f"- {p}" for p in counseling_src[:4])
        counseling_context = f"\n【복용 가이드】\n{lines}"

    # 큐레이션된 기대효과 — 효능 주장은 이 범위로 한정 (환자 호소증상 echo 차단)
    effects_context = ""
    if reported_effects and reported_effects.strip():
        effects_context = f"\n【입증된 기대효과(이 범위 내에서만 효능 진술)】\n{reported_effects.strip()}"

    # 결정별 요구사항 3·5·6·11 분기 — '회피/비처방 보충 권장안됨' 프레이밍은 AVOID/CONTRA 전용.
    # conditional_consider/recommend 에 누출되면 "회피 권장" 같은 부정확한 톤이 됨(#1).
    if result.decision in (Decision.CONTRAINDICATED, Decision.AVOID):
        req_3 = ('3. 결정 근거를 첫 문장에서 명확히 진술하되, 제공된 근거에 처방 치료 예외가 있으면\n'
                 '   ★ "해당 성분은 피해야 한다" 같은 *성분 자체 금기* 단정으로 시작 금지 —\n'
                 '   "비처방 건강 목적의 보충은 권장되지 않는다" 형태로 시작')
        req_11 = ("11. ★ '회피/피함'은 *건강 목적 비처방 보충*에 한정 — 제공된 근거에 치료 목적 처방 예외\n"
                  "   (예: KI 처방, 수술 준비, 갑상선폭풍)가 있으면 '성분 자체 금기'로 단정하지 말고\n"
                  '   "비처방 건강목적 보충 회피 + 처방 하 치료 예외"를 구분해 서술')
        if result.decision == Decision.CONTRAINDICATED:
            req_5 = "5. 임상적 위험 기전 또는 약물 상호작용 메커니즘을 한 문장으로 설명"
            req_6 = "6. 현재 상태에서 이 영양제를 반드시 피해야 하는 임상적 이유를 재강조하는 문장으로 마무리 (복용 권장·용량 안내 금지)"
        else:
            req_5 = "5. 회피가 필요한 임상적 이유를 한 문장으로 설명"
            req_6 = f"6. 현 상태에서 복용을 피해야 하는 이유와 재평가가 필요한 조건을 한 문장으로 마무리 (복용 권장 문구 사용 금지)"
    elif result.decision == Decision.MANAGE_INTERACTION:
        # #4.1/§4.2 첫 문장 초점을 '조건부 고려'가 아니라 '병용 관리(분리·흡수)'로.
        req_3 = ('3. ★ 첫 문장 초점은 *복용 여부*가 아니라 *병용 관리* — 성분 자체는 사용 가능하나\n'
                 '   핵심은 레보티록신과의 복용 시간 분리·흡수 관리임을 명확히 진술.\n'
                 "   '회피/피해야/금기'로 시작·단정 금지")
        req_11 = ("11. ★ '회피/피함/금기' 프레이밍 사용 금지 (이 결정은 회피가 아님) — 성분 한계·\n"
                  '   불확실성은 "직접 근거 제한적/효과 미확립" 형태로 서술')
        req_5 = "5. 복용 시간 분리(공복·간격)·흡수 영향·필요 모니터링(TSH 등) 중 핵심 1~2개를 임상적으로 설명"
        req_6 = ("6. 마지막 문장: 레보티록신과의 복용 시간 분리·흡수 관리를 재확인하는 문장으로 마무리\n"
                 "   (복용 자체의 권장/금지 단정 대신 '관리' 중심)")
    else:
        # recommend / conditional_consider / insufficient_evidence — 회피·금기 프레이밍 금지
        req_3 = ('3. 결정 근거를 첫 문장에서 명확히 진술 — ★ 이 결정은 *회피·금기가 아니므로*\n'
                 '   "회피/피해야/권장되지 않는다"로 시작하거나 단정하지 말 것. 환자의 임상 질문 맥락\n'
                 "   (예: 증상 완화 목적)에서 조건부 고려 여부를 중심으로 서술")
        req_11 = ("11. ★ '회피/피함/금기' 프레이밍 사용 금지 (이 결정은 회피가 아님) — 비처방 보충의\n"
                  '   한계·불확실성은 "직접 근거 제한적/효과 미확립" 형태로 서술')
        req_5 = "5. 임상 적용 시 핵심 주의사항 1~2개 언급 (있을 경우에만)"
        req_6 = f'6. 마지막 문장: "{tolerance_guide}" 로 마무리'

    doctor_question_section = f"\n의사 질문: {message.strip()}" if message and message.strip() else ""

    prompt = f"""당신은 갑상선 전문 임상의를 위한 영양제 의사결정 지원 시스템입니다.
아래 정보를 바탕으로 전문 임상 서술을 작성하세요.

【판단 정보】
영양제: {supplement_display}
결정: {decision_ko}
근거: {rationale_src or "없음"}{warning_text}
환자 진단: {conditions or "미입력"}
복용 약물: {medications or "없음"}{doctor_question_section}{evidence_section}{counseling_context}{effects_context}

【작성 요구사항】
1. 300~450자 범위 (초과 금지)
2. 임상 전문체로 작성 (의학 용어, 영문 약어 허용)
{req_3}
4. PubMed 검색 결과가 있으면 핵심 근거 논문 방향을 한 문장으로 요약 (PMID·연도 메타 포함 금지)
{req_5}
{req_6}
7. 인사말 없이 영양제 이름 또는 결정으로 바로 시작
8. 환자에게 직접 설명하는 말투 금지 — 의사에게 제공하는 임상 요약문 형식
9. ★ 위 【판단 정보】에 *제공된 내용만* 사용 — 증상·검사값·상호작용을 임의로 지어내지 말 것
10. ★ 상호작용·위험은 *단방향·단정으로 단순화 금지* — 제공된 근거가 양방향(예: 악화/억제 모두)·
   불확실성을 담고 있으면 그대로 보존 (예: "약효를 떨어뜨린다"처럼 단정하지 말 것)
{req_11}
12. ★ 효능 진술은 위 【입증된 기대효과】 범위로만 한정 — 환자가 호소·언급한 목적이나 증상
   (예: 피로 개선)이 그 범위에 *없으면* 효능으로 단정하지 말 것. 해당 목적에 대한 직접
   근거가 없으면 "그 목적에 대한 직접 근거는 제한적/일관되지 않음"을 한 문장으로 *명시*
   (환자 질문을 효능으로 echo 금지)
13. ★ 위 【환자 진단】과 직접 관련 없는 *별도 적응증*(그레이브스 안병증/GO/TED/안병증/
   orbitopathy 등)은 언급하지 말 것 — 제공된 근거에 해당 표현이 있어도 현재 환자 진단과
   무관하면 제외
14. ★ 효능·기전을 "입증되었다/proven/확립되었다"로 *단정하지 말 것* —
   "관찰되었다/보고되었다/시사된다" 형태로 서술 (의학 서술 표준)
15. ★ 위 【복용 가이드】에 제공된 권고의 *강도를 넘기지 말 것* — "고려/가능"으로 제시된
   항목을 "바람직하다/권장된다/해야 한다"로 격상 금지. 제공된 표현의 강도를 그대로 유지"""

    return _call_llm(prompt, max_tokens=350)


def generate_recommendation_response(
    conditions: str,
    medications: str = "",
) -> Optional[str]:
    """
    진단명 기반 영양제 추천 안내.
    실패 시 None 반환.
    """
    prompt = f"""당신은 갑상선 환자를 위한 영양제 상담 전문가입니다.
환자의 갑상선 진단에 따라 도움이 될 수 있는 영양제를 안내하세요.

환자 정보:
- 진단: {conditions}
- 복용 약물: {medications or '없음'}

【응답 요구사항】
1. 200-300자 범위
2. 진단별 근거 있는 영양제 2-3가지 언급
3. 각 영양제가 왜 도움이 되는지 간단히 설명
4. 마지막에 "구체적인 영양제 이름을 말씀해 주시면 안전성을 더 자세히 확인해 드릴게요" 포함
5. 인사말로 절대 시작하지 말 것 — 바로 핵심으로 시작
6. 자연스러운 대화체"""

    return _call_llm(prompt, max_tokens=250)


def generate_clarification_response(
    candidates: list[str],
    user_message: str,
    history: list[dict] | None = None,
) -> Optional[str]:
    """
    여러 제품이 매칭되었을 때, 어떤 제품인지 질문하는 친절한 자연어 메시지 생성.
    """
    history_section = _build_history_section(history)
    candidates_str = ", ".join(f"'{c}'" for c in candidates)
    prompt = f"""당신은 갑상선 환자를 위한 영양제 상담 전문가입니다.
사용자가 입력한 메시지 "{user_message}"에서 여러 영양제 후보들이 검색되었습니다.

【검색된 후보 제품군】
{candidates_str}

【요구사항】
1. 사용자가 정확히 어떤 제품에 대해 묻고 있는지 친절하게 물어보세요.
2. 위 후보 제품군 중 하나인지 확인을 요청하되, 너무 딱딱하지 않고 부드러운 의사소통 톤을 유지하세요.
3. 안내의 마지막에 "참고로 제품명(브랜드명)보다는 핵심 성분명(예: 마그네슘, 오메가3 등)을 알려주시면 훨씬 더 빠르고 정확하게 갑상선 약과의 상호작용을 확인해 드릴 수 있습니다"라는 팁을 꼭 덧붙여주세요.
4. 150-250자 이내로 콤팩트하고 친절하게 답변하세요.
5. "안녕하세요"와 같은 의례적인 인사말로 시작하지 마세요. 바로 본론으로 시작하세요.
{history_section}"""
    return _call_llm(prompt, max_tokens=200)


def generate_unrecognized_response(
    user_message: str,
    history: list[dict] | None = None,
) -> Optional[str]:
    """
    영양제를 전혀 식별하지 못했을 때 성분명 입력을 유도하는 친절한 자연어 메시지 생성.
    """
    history_section = _build_history_section(history)
    prompt = f"""당신은 갑상선 환자를 위한 영양제 상담 전문가입니다.
사용자가 입력한 메시지 "{user_message}"에서 분석 가능한 갑상선 특화 영양제 성분을 찾지 못했습니다.

【요구사항】
1. 스스로 판단하기에 사용자 입력이 '특정 브랜드명이나 복합 제품명(예: 익스트림, 고려은단, 센트룸 등)'에 가깝다면:
   - 제품명만으로는 정확한 성분 파악이 어려움을 친절히 안내하고, 제품의 '핵심 주성분명(예: 오메가3, 마그네슘, 철분 등)'을 알려주시면 갑상선과의 상호작용을 확인해 드리겠다고 안내하세요.
2. 스스로 판단하기에 사용자 입력이 '일반적인 성분/약초명(예: 쏘팔메토, 홍삼, 효소 등)'에 가깝다면:
   - 해당 성분은 현재 저희 갑상선 특화 지식베이스에 안전성 가이드라인이 명확히 등록되어 있지 않아 안내가 어렵다고 솔직하고 정중하게 말씀해 주세요. (주의: 환자가 이미 성분명을 말했는데 "브랜드명 말고 성분명을 말해달라"고 동문서답하며 환자를 가르치려 들면 절대 안 됩니다.)
3. 150-250자 이내로 콤팩트하고 부드러운 대화체로 답변하세요.
4. "안녕하세요"와 같은 의례적인 인사말로 시작하지 마세요. 바로 본론으로 시작하세요.
{history_section}"""
    return _call_llm(prompt, max_tokens=200)
