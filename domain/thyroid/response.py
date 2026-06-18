"""
domain.thyroid.response — 환자용/의사용 출력 포매터

같은 DecisionResult를 받아서:
  - PatientResponseFormatter → 쉬운 설명 중심
  - DoctorResponseFormatter  → 근거 수준, 불확실성, 상담 포인트 중심
"""

from __future__ import annotations

import re

from domain.thyroid.schemas import (
    Decision,
    DecisionResult,
    DoctorResponse,
    PatientProfile,
    PatientResponse,
    PhysicianProfile,
    WarningSeverity,
)
from domain.thyroid.rules import get_display_name, get_supplement_rule
from domain.thyroid.llm_response import generate_doctor_llm_summary, fetch_mfds_context
from domain.thyroid.evidence_rank import (
    EVIDENCE_RANK,
    sort_evidence_by_rank,
    detect_guideline_conflict,
    best_evidence_level,
)


# ══════════════════════════════════════════════════════════
# [조건] 태그 기반 결정적 콘텐츠 필터 (counseling/monitoring 등 리스트 슬롯)
#   환자 프로필에 맞는 항목만 선택 — 무관 조건 항목 제외, 매칭 > 일반 순.
#   "무엇을 보여줄지"는 결정적, "어떻게 말할지"만 LLM (AGENT_SPEC §6.5).
# ══════════════════════════════════════════════════════════

# 태그 키워드 → 환자 조건. (compound 태그는 OR 매칭)
# 키워드는 부분문자열(str) 또는 단어경계 패턴(re.Pattern) — 짧은 라틴 약어(GO 등)는
# goitrogenic·EUGOGO 같은 오매칭을 피하려 \b 경계 패턴 사용. _kw_hit 로 통일 처리.
# GO/TED: Graves orbitopathy / Thyroid Eye Disease 약어 (그레이브스 안병증 = hyper 축).
# 한국어 조사("GO엔")·인접 토큰까지 잡되 라틴 문자 경계만 사용 — 앞뒤가 a-z 가 아니면 매칭.
# \b 는 한글 조사를 word char 로 봐 "GO엔"을 놓치므로 (?<![a-z])…(?![a-z]) 사용.
# goitrogenic·eugogo·limited·reported 등 라틴 합성어 오매칭은 방지됨.
_GO_TOKEN = re.compile(r"(?<![a-z])go(?![a-z])")
_TED_TOKEN = re.compile(r"(?<![a-z])ted(?![a-z])")
_TAG_COND = [
    (("임신", "pregnan"), "pregnancy"),
    (("수유", "lactat", "breastfeed"), "lactation"),
    (("하시모토", "기능저하", "저하증", "hashimoto", "hypothyroid"), "hypo"),
    (("그레이브스", "항진", "graves", "hyper", "thyrotoxic", "중독증",
      "안병증", "orbitopathy", "eugogo", _GO_TOKEN, _TED_TOKEN), "hyper"),
    (("결절", "자율성", "독성선종", "tmng", "nodule"), "nodule"),  # "선종" 단독 제외(갑상선종=goiter 오매칭)
    (("갑상선암", "rai", "분화암", "cancer", "dtc"), "cancer"),
    (("메티마졸", "ptu", "methimazole", "propylthiouracil", "항갑상선"), "antithyroid"),
    (("lt4 복용", "레보티록신", "levothyroxine"), "lt4"),
    # 절제술 후 — generic "수술"은 iodine notes "수술 준비" 오매칭 → "절제술"/thyroidectom 한정
    (("절제술", "thyroidectom"), "surgery"),
]


def _kw_hit(kw, text: str) -> bool:
    """키워드 매칭 — str 은 부분문자열, re.Pattern 은 단어경계 검색."""
    if isinstance(kw, re.Pattern):
        return bool(kw.search(text))
    return kw in text
# 환자-무관 일반 태그 (조건 매칭 없이 항상 유지)
_GENERAL_TAGS = ("인구 집단", "다시마", "해조류 일반", "지역 단서", "일반 성인", "일반")
# niche 태그 — 기본 제외 (해당 설정 미추적, 기본 사용자는 비해당). 예: 저자원 지역 iodized oil
_NICHE_TAGS = ("저자원",)


def _patient_conditions(patient: PatientProfile | None) -> set[str]:
    """환자 프로필에서 활성 조건 집합 추출 (진단/위험요인/약물 토큰)."""
    if not patient:
        return set()
    # §15.1 결정 로직 반영 정책:
    #  - 병력(past_history)은 *미반영* — 과거(해소된) 질환을 현재 조건으로 오분류 방지(표시 전용).
    #  - 수술력(surgical_history)은 surgery 축에 반영 — 영구 사실, #6.4 절제술 scope와 동일 축.
    #  - 임신/수유는 현재상태(진단+위험요인)만.
    dx = " ".join(patient.diagnosis or []).lower()
    rf = " ".join(getattr(patient, "risk_factors", []) or []).lower()
    surg = " ".join(getattr(patient, "surgical_history", []) or []).lower()
    meds = " ".join(patient.medications or []).lower()
    cur_blob = f"{dx} {rf}"              # 현재상태 (임신/수유)
    conds: set[str] = set()
    if any(t in cur_blob for t in ("임신", "pregnan")):
        conds.add("pregnancy")
    if any(t in cur_blob for t in ("수유", "lactat", "breastfeed")):
        conds.add("lactation")
    if any(t in dx for t in ("하시모토", "hashimoto", "기능저하", "저하증", "hypothyroid")):
        conds.add("hypo")
    if any(t in dx for t in ("그레이브스", "graves", "항진", "hyper", "thyrotoxic", "중독증",
                             "안병증", "orbitopathy", "eugogo")):
        conds.add("hyper")
    if any(t in dx for t in ("결절", "nodule", "자율성", "autonomous", "tmng", "독성선종")):
        conds.add("nodule")
    if any(t in dx for t in ("갑상선암", "thyroid_cancer", "cancer", "분화암", "dtc")):
        conds.add("cancer")
    if any(t in meds for t in ("메티마졸", "methimazole", "ptu", "propylthiouracil", "항갑상선")):
        conds.add("antithyroid")
    if any(t in meds for t in ("레보티록신", "levothyroxine", "씬지로이드", "신지로이드", "synthroid")):
        conds.add("lt4")
    if any(t in f"{dx} {surg}" for t in ("절제술", "thyroidectom", "갑상선 수술", "갑상선수술")):
        conds.add("surgery")
    return conds


def _item_relevance(item: str, pconds: set[str]) -> str:
    """항목의 선두 [조건] 태그를 환자 조건과 대조 → 'matched'/'general'/'conflict'."""
    m = re.match(r"\s*\[([^\]]+)\]", item)
    if not m:
        return "general"                    # 태그 없음 = 일반
    tag = m.group(1).lower()
    if any(n in tag for n in _NICHE_TAGS):
        return "conflict"                   # niche(저자원 등) → 기본 제외
    if any(g in tag for g in _GENERAL_TAGS):
        return "general"
    req = {c for kws, c in _TAG_COND if any(_kw_hit(k, tag) for k in kws)}
    if not req:
        return "general"                    # 조건 못 읽음 → 일반(안전)
    return "matched" if (req & pconds) else "conflict"


def select_by_condition(items: list[str], patient: PatientProfile | None) -> list[str]:
    """리스트 슬롯을 환자 [조건] 태그로 필터·정렬 (matched > general, conflict 제외).
    환자 정보 없으면 필터 안 함(전부)."""
    if not items:
        return items
    pconds = _patient_conditions(patient)
    if not pconds:
        return list(items)
    matched, general = [], []
    for it in items:
        rel = _item_relevance(it, pconds)
        if rel == "matched":
            matched.append(it)
        elif rel == "general":
            general.append(it)
        # conflict → 제외
    return matched + general


# §6.1 dose-toxicity risk_tag → 의사용 안전 우려 문구 (룰에 데이터 존재, 표시로만 승격)
_DOSE_TOXICITY_RISK = {
    "hypercalcemia_risk": "고용량·장기 복용 시 고칼슘혈증·신결석·신기능 저하 위험",
}


def _extract_ul(official_upper_limit: str) -> str:
    """official_upper_limit 첫 세그먼트에서 선두 [태그] 제거한 UL 값 추출 (없으면 '')."""
    if not official_upper_limit:
        return ""
    first = official_upper_limit.split(";")[0]
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", first).strip()


# §9.3 공식 용량 출처 우선순위 라벨 (약전 > MFDS > NIH ODS > WHO > ATA > ETA)
_DOSE_SOURCE_PATTERNS = [
    ("약전",     ("약전", "pharmacopoeia")),
    ("MFDS",     ("MFDS", "식약처", "식품의약품안전처", "식품안전나라")),
    ("NIH ODS",  ("NIH", "ODS")),
    ("WHO",      ("WHO", "UNICEF")),
    ("ATA",      ("ATA",)),
    ("ETA",      ("ETA",)),
]


def _derive_dose_sources(text: str) -> str:
    """공식 기준 텍스트에서 출처 기관을 §9.3 우선순위로 추출해 ' · '로 결합 (없으면 '')."""
    if not text:
        return ""
    found: list[str] = []
    for label, keys in _DOSE_SOURCE_PATTERNS:
        if any(k in text for k in keys) and label not in found:
            found.append(label)
    return " · ".join(found)


def _build_official_dose_reference(upper_text: str) -> dict | None:
    """§9.2 공식 기준/상한 구조화 — {text, source, limit_value}. upper_text 없으면 None."""
    if not upper_text:
        return None
    return {
        "text": upper_text,
        "source": _derive_dose_sources(upper_text),
        "limit_value": _extract_ul(upper_text),
    }


# §16.1 환자용 쉬운 언어 — 인용코드·가이드라인 등급 같은 전문 표기를 결정론적으로 제거.
# (깊은 용어 평이화(TPOAb→갑상선 항체 등)는 LLM 영역 #8.3이라 범위 밖. 여기선 noise만 제거)
_PATIENT_STRIP_PATTERNS = [
    re.compile(r"\s*PMID:\s*\d+", re.I),
    re.compile(r"\s*\((?:ATA|ETA|EUGOGO|WHO|UNICEF|NIH|ODS|KDRI|MFDS|EFSA|Endocrine)[^)]*\)", re.I),
    re.compile(r"\s*\((?:Weak|Strong|Moderate|Low|High)[/\w\s,]*\)", re.I),  # 권고 등급 (Weak/moderate)
]
# 내부 코드 식별자(snake_case)·백틱·'safety rule' 포함 문장은 환자에게 노출 부적절 → 문장째 제거
_PATIENT_DROP_SENTENCE = re.compile(r"`|[a-z]+_[a-z]+_?[a-z]*|safety rule", re.I)
_PATIENT_SENT_SPLIT = re.compile(r"(?<=[.;])\s+")


def _plainify_for_patient(text: str) -> str:
    """환자용 쉬운 언어 정리(결정론적): (1) 내부 코드/식별자 포함 문장 제거,
    (2) 인용·권고등급·[스코프/인용] 브래킷 제거, (3) 공백·구두점 정리."""
    if not text:
        return text
    sents = [s for s in _PATIENT_SENT_SPLIT.split(text) if not _PATIENT_DROP_SENTENCE.search(s)]
    text = " ".join(sents)
    for pat in _PATIENT_STRIP_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\[[^\]]*\]", "", text)        # 잔여 [조건]/[인용] 브래킷
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.,;])", r"\1", text)
    return text.strip()


# 문자열 슬롯(notes/study_dose/official_upper_limit) 문장 분리 (.  ;  기준)
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+")


def filter_string_by_condition(text: str, patient: PatientProfile | None) -> str:
    """문자열 슬롯을 문장 단위 [조건] 필터 — 충돌 조건 문장 제외, 순서 보존.
    환자 정보 없으면 원문 그대로. 무태그 문장은 항상 유지."""
    if not text:
        return text
    pconds = _patient_conditions(patient)
    if not pconds:
        return text
    kept = [s for s in _SENT_SPLIT.split(text) if _item_relevance(s, pconds) != "conflict"]
    return " ".join(kept).strip()


# ── 근거 수준 한국어 표시명 ──
_EVIDENCE_LEVEL_KO: dict[str, str] = {
    "guideline":         "가이드라인",
    "meta_analysis":     "메타분석",
    "systematic_review": "체계적 문헌 고찰",
    "rct":               "무작위 대조 연구 (RCT)",
    "clinical":          "임상 연구",
    "high":              "높은 근거 수준",
    "cohort":            "코호트 연구",
    "observational":     "관찰 연구",
    "moderate":          "중간 근거 수준",
    "case_control":      "환자-대조군 연구",
    "case_series":       "증례 시리즈",
    "case_report":       "증례 보고",
    "mechanistic":       "기전 연구 (간접 근거)",
    "expert_opinion":    "전문가 의견",
    "low":               "낮은 근거 수준",
    "insufficient":      "근거 부족",
}

# §16.1-6 자료 수준 출처 문맥 문장
_EVIDENCE_SOURCE_CONTEXT: dict[str, str] = {
    "guideline":         "이 정보는 갑상선 관련 공식 임상 가이드라인(ATA/ETA/WHO 등)을 기반으로 합니다.",
    "meta_analysis":     "이 정보는 다수 임상시험을 종합한 메타분석 결과를 포함합니다.",
    "systematic_review": "이 정보는 체계적 문헌 고찰 결과를 기반으로 합니다.",
    "rct":               "이 정보는 무작위 대조 임상시험(RCT) 결과를 포함합니다.",
    "cohort":            "이 정보는 코호트 연구 등 관찰 연구 수준의 근거를 기반으로 합니다.",
    "observational":     "이 정보는 관찰 연구 수준의 근거를 기반으로 합니다.",
    "case_control":      "이 정보는 환자-대조군 연구 수준의 근거를 기반으로 합니다.",
    "insufficient":      "현재 갑상선 환자 대상의 충분한 공식 근거는 확인되지 않습니다.",
    "low":               "현재 근거 수준이 낮아 결과 해석에 주의가 필요합니다.",
}

# ── Decision → 환자용 표현 매핑 (§7.2 출력 문구 완화) ──
# 내부 Decision enum 은 유지; 사용자 노출 문구만 완화
_PATIENT_CAN_TAKE = {
    Decision.RECOMMEND:             "근거 있음 (상담 권고)",
    Decision.CONDITIONAL_CONSIDER:  "조건부 확인 필요",
    Decision.MANAGE_INTERACTION:    "복용 가능 — 다른 약과 시간 분리 필요",
    Decision.AVOID:                  "주의 필요 (상담 필수)",
    Decision.CONTRAINDICATED:        "금기 자료 있음 (상담 필수)",
    Decision.INSUFFICIENT_EVIDENCE:  "근거 제한적",
}

# ── Decision → 환자용 요약 프리픽스 (§7.2, §7.3 단정 표현 완화) ──
_PATIENT_SUMMARY_PREFIX = {
    Decision.RECOMMEND: (
        "일부 근거에서 {name}이(가) 도움이 될 가능성이 제시됩니다. "
        "개인 상태에 따라 효과가 다를 수 있으므로 전문의와 상의 후 복용하시기 바랍니다."
    ),
    Decision.CONDITIONAL_CONSIDER: (
        "{name}은(는) 조건에 따라 고려될 수 있으나, 환자 상태 확인이 필요합니다. "
        "복용 전 반드시 전문의·약사와 상담하세요."
    ),
    Decision.MANAGE_INTERACTION: (
        "{name} 자체보다 함께 복용하는 갑상선 호르몬제와의 복용 시간 분리가 중요합니다. "
        "흡수 방해를 피하도록 복용 간격·일정을 전문의·약사와 확인하세요."
    ),
    Decision.AVOID: (
        "{name}에 대해 주의가 필요한 정보가 있어 복용 전 전문가 상담이 필요합니다."
    ),
    Decision.CONTRAINDICATED: (
        "{name}은(는) 자료상 금기 또는 피해야 하는 상황으로 보고된 정보가 있습니다. "
        "복용 전 의사 또는 약사와 반드시 상담이 필요합니다."
    ),
    Decision.INSUFFICIENT_EVIDENCE: (
        "{name}에 대한 현재 확인 가능한 근거 수준은 제한적입니다. "
        "복용 여부는 전문의와 상담 후 결정하시기 바랍니다."
    ),
}


class PatientResponseFormatter:
    """환자용 — 쉬운 설명 중심 응답 생성."""

    def format(self, result: DecisionResult, patient: PatientProfile | None = None) -> PatientResponse:
        name = result.supplement_name
        summary = _PATIENT_SUMMARY_PREFIX.get(
            result.decision, "{name}에 대해 추가 확인이 필요합니다."
        ).format(name=name)

        # 주의사항 — WARNING/CRITICAL만 UI에 표시 (CAUTION은 LLM 프롬프트에서도 제외)
        cautions = []
        for w in result.safety_warnings:
            if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL):
                cautions.append(f"⚠️ {w.message}")

        # 다음 행동 — rule counseling_points 를 [조건] 태그로 환자 맞춤 필터 후 상위 3
        _filtered = select_by_condition(result.counseling_points, patient)
        next_actions = list(_filtered[:3]) if _filtered else list(result.recommendations[:3])
        # §7.3: "즉시 중단" 대신 상담 우선 안내
        if result.decision == Decision.CONTRAINDICATED:
            next_actions.insert(0, "해당 성분에 대해 금기 자료가 있습니다. 복용 전 의사 또는 약사와 반드시 상담이 필요합니다.")
        elif result.decision == Decision.AVOID:
            next_actions.insert(0, "복용 전 전문의·약사에게 관련 정보를 확인하시기 바랍니다.")
        elif result.decision == Decision.MANAGE_INTERACTION:
            # #4.1/§7.2 핵심은 복용 여부가 아니라 갑상선 호르몬제와의 복용 시간 분리.
            #   입력된 복용 타이밍이 있으면 그에 맞춰 안심/경고로 분기(regimen-aware).
            _status = (result.regimen_assessment or {}).get("status")
            if _status == "separated":
                next_actions.insert(0, "현재 입력하신 복용 간격이라면 갑상선 호르몬제와 흡수 간섭을 피하는 데 적절합니다. 현재 일정을 유지하면서 TSH 등 갑상선 수치를 정기적으로 확인하세요.")
            elif _status == "concurrent":
                # §13.1/§13.3 환자용: 처방형 "4시간" 대신 공복·식사 간격·상담 중심.
                next_actions.insert(0, "현재 갑상선 호르몬제와 비슷한 시간대에 복용하고 계셔서 흡수에 영향을 줄 수 있습니다 — 갑상선 호르몬제는 보통 공복에 복용하고, 다른 약·영양제와는 시간 간격을 두는 것이 좋습니다. 적절한 복용 간격은 담당의·약사와 확인하세요.")
            else:
                next_actions.insert(0, "복용 자체보다 갑상선 호르몬제와의 복용 시간 분리가 중요합니다 — 복용 간격·일정을 전문의·약사와 확인하세요.")
        elif result.decision == Decision.INSUFFICIENT_EVIDENCE:
            next_actions.insert(0, "전문의 상담 후 복용 여부를 결정하시기 바랍니다.")

        # 의사 상담 권고 여부
        has_high_risk = any(
            w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
            for w in result.safety_warnings
        )
        consult = has_high_risk or result.decision != Decision.RECOMMEND

        display_name = get_display_name(name) if name else None

        # ── 신규 필드: rule 데이터 + patient_factors ──────────────
        rule = get_supplement_rule(name) if name else None

        # 근거 요약 — notes 를 [조건] 필터 후 요약 (케이스 무관 문장 제거)
        # §16.1 환자용: 인용코드·등급 등 전문 표기 제거(쉬운 언어).
        evidence_summary = None
        if rule:
            notes_short = filter_string_by_condition(rule.get("notes", "") or "", patient)
            notes_plain = _plainify_for_patient(notes_short)[:180]
            if notes_plain:
                evidence_summary = notes_plain

        # evidence_level: rule 우선, PubMed best_evidence_level 보완 → 한국어 표시명으로 변환
        rule_level = rule.get("evidence_level", "") if rule else ""
        pubmed_best = best_evidence_level(result.evidence_records) if result.evidence_records else ""
        _raw_level = rule_level or pubmed_best or ""
        _ev_label = _EVIDENCE_LEVEL_KO.get(_raw_level, _raw_level) if _raw_level else None
        _ev_source = _EVIDENCE_SOURCE_CONTEXT.get(_raw_level, "")
        evidence_level = f"{_ev_label}\n{_ev_source}" if (_ev_label and _ev_source) else _ev_label

        # §9.1 환자용: raw 연구 용량(mg 덤프·인용)을 직접 제시하지 않음 — 개인별 상의 안내 +
        # 공식 상한(UL)만 안전 천장으로 쉬운 표현 유지. (의사용은 별도로 연구용량 그대로 노출)
        research_dose_summary = None
        research_dose = None          # §9.1 환자엔 raw 연구용량 미제공
        official_dose_reference = None
        if rule:
            upper = filter_string_by_condition(rule.get("official_upper_limit", ""), patient)
            official_dose_reference = _build_official_dose_reference(upper)
            _ul_plain = _plainify_for_patient(_extract_ul(upper)) if upper else ""
            _dose_msg = "용량은 진단·검사·복용 중인 약에 따라 달라 담당의와 상의가 필요합니다"
            if _ul_plain:
                _dose_msg += f" (참고 상한: {_ul_plain} 초과 주의)"
            research_dose_summary = _dose_msg + "."

        # reported_effects_summary: 기대 효과만 (환자용).
        # #8.1 경고 중복 제거 — 동일 WARNING/CRITICAL이 cautions·top_warnings에 이미 노출되므로
        # 여기서 주의/부작용을 재노출하지 않음(환자 과대 위험 인식 방지).
        reported_effects_summary = None
        if rule:
            benefits = select_by_condition(rule.get("possible_benefits", []), patient)
            if benefits:
                reported_effects_summary = "기대 효과: " + "; ".join(benefits[:2])

        # patient_factors: _build_patient_factors() 재사용 (lab values + 특수군)
        patient_factors = _build_patient_factors(patient, result)

        # uncertainty_notes: 근거 수준 낮음 + limited/insufficient evidence 경고
        uncertainty_notes: list[str] = []
        if result.confidence == "low":
            uncertainty_notes.append("현재 판단은 근거 수준이 낮아 불확실성이 높습니다.")
        if result.decision == Decision.INSUFFICIENT_EVIDENCE:
            uncertainty_notes.append("충분한 근거가 축적되면 판단이 변경될 수 있습니다.")
        for w in result.safety_warnings:
            if w.category in ("insufficient_evidence", "limited_evidence"):
                uncertainty_notes.append(w.message)

        top_warnings = [
            {
                "message": w.message,
                "severity": w.severity.value,
                "recommended_action": w.recommended_action,
            }
            for w in result.safety_warnings
            if w.severity in (WarningSeverity.CRITICAL, WarningSeverity.WARNING)
        ]

        # §12.3 임신 + iodine 전용 강조 블록
        iodine_pregnancy_alert = None
        if name == "iodine" and patient:
            _risk_set = {str(r).lower() for r in (patient.risk_factors or [])}
            _cond_set = {str(c).lower() for c in (patient.diagnosis or [])}
            _pregnancy_terms = {"pregnancy", "pregnant", "임신", "lactation", "breastfeeding", "수유"}
            if _risk_set & _pregnancy_terms or _cond_set & _pregnancy_terms:
                iodine_pregnancy_alert = {
                    "deficiency_risk": "임신 중 요오드 결핍은 태아 신경발달 장애, 유산, 갑상선기능저하와 연관될 수 있습니다.",
                    "excess_risk": "과잉 섭취 시 태아 갑상선 기능 억제(태아 갑상선종) 및 신생아 갑상선기능저하 위험이 있습니다.",
                    "official_standard": "WHO/UNICEF 권장 임신 중 요오드 일일 섭취량: 250µg (한국 식약처 기준: 240µg/일).",
                    "action": "담당 산부인과 또는 내분비내과 전문의와 현재 식사 내 요오드 섭취량 및 보충제 필요 여부를 반드시 확인하세요.",
                }

        return PatientResponse(
            summary=summary,
            can_take=_PATIENT_CAN_TAKE.get(result.decision, "판단 보류"),
            cautions=cautions[:5],
            next_actions=next_actions[:4],
            consult_doctor=consult,
            evidence_summary=evidence_summary,
            identified_supplement=name if name else None,
            identified_supplement_display=display_name if display_name else None,
            evidence_level=evidence_level,
            research_dose_summary=research_dose_summary,
            research_dose=research_dose,
            official_dose_reference=official_dose_reference,
            reported_effects_summary=reported_effects_summary,
            patient_factors=patient_factors[:4],
            uncertainty_notes=uncertainty_notes[:3],
            top_warnings=top_warnings,
            iodine_pregnancy_alert=iodine_pregnancy_alert,
            regimen_assessment=result.regimen_assessment,
        )


def _get_lab(lab: dict, *keys) -> float | None:
    """소문자 정규화된 lab dict에서 여러 키를 순서대로 탐색해 float 반환."""
    for k in keys:
        v = lab.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


# 진단축별 전형 증상 체크리스트 — 입력값이 아니라 임상 표준 교과서 수준의 확인 권장 목록.
# provenance: [clinical-standard]. "입력된 증상"과 명확히 다른 라벨("추가 확인 권장")로만 노출.
_HYPER_SYMPTOM_CHECKLIST = ["체중 감소", "심계항진", "진전(손떨림)", "열 불내성", "발한", "설사", "안구증상"]
_HYPO_SYMPTOM_CHECKLIST = ["피로", "체중 증가", "추위 불내성", "변비", "피부 건조", "서맥", "부종"]


def _build_patient_factors(
    patient: PatientProfile | None,
    result: DecisionResult,
) -> list[str]:
    """
    PatientProfile의 lab_values, symptoms을 공인 임상 임계값으로 해석해 patient_factors 생성.
    LLM 없이 결정론적으로 생성한다.
    """
    factors: list[str] = []

    if patient:
        # §15.1 BMI (아시아-태평양 기준) + 수술력/병력 맥락
        _bmi = patient.bmi
        if _bmi is not None:
            _cat = ("저체중" if _bmi < 18.5 else "정상" if _bmi < 23
                    else "과체중" if _bmi < 25 else "비만")
            factors.append(f"BMI {_bmi} ({_cat})")
        _surg = getattr(patient, "surgical_history", []) or []
        if _surg:
            factors.append("수술력: " + ", ".join(_surg[:3]))
        _past = getattr(patient, "past_history", []) or []
        if _past:
            factors.append("병력: " + ", ".join(_past[:3]))

        lab = {k.lower(): v for k, v in (patient.lab_values or {}).items()}

        # TSH — 레보티록신 복용 여부에 따라 해석 분기
        _levo_kw = {"levothyroxine", "레보티록신", "씬지로이드", "신지로이드"}
        _levo_detected = any(
            kw in m.lower()
            for m in (patient.medications or [])
            for kw in _levo_kw
        )
        # 자가면역 갑상선염(하시모토/TPOAb+) 맥락 — 비-LT4 경계 TSH 해석에 사용 (#6.3)
        _dx_blob = (
            " ".join(patient.diagnosis or [])
            + " " + " ".join(getattr(patient, "risk_factors", []) or [])
        ).lower()
        _autoimmune = any(t in _dx_blob for t in (
            "하시모토", "hashimoto", "자가면역", "autoimmune", "tpoab", "tpo 항체", "항tpo",
        ))

        tsh = _get_lab(lab, "tsh")
        if tsh is not None:
            if tsh < 0.4:
                _hyper_dx = ("그레이브스", "항진", "graves", "hyper")
                _dx_str = " ".join(patient.diagnosis or []).lower()
                _is_hyper = any(t in _dx_str for t in _hyper_dx)
                if _is_hyper:
                    factors.append(
                        f"TSH {tsh} mIU/L — 억제 범위 (< 0.4), 갑상선기능항진 활성 반영 "
                        "(항갑상선제 치료 중 기대 소견)"
                    )
                else:
                    factors.append(
                        f"TSH {tsh} mIU/L — 억제 범위 (< 0.4), 과치료 또는 기능 항진 가능성"
                    )
            elif tsh > 4.5 and _levo_detected:
                factors.append(
                    f"TSH {tsh} mIU/L — 레보티록신 유지치료 중 조절 부족 가능성; "
                    "새 성분 추가 시 TSH/Free T4 추적 권고"
                )
            elif tsh > 4.5:
                factors.append(f"TSH {tsh} mIU/L — 정상 상한 초과, 갑상선 기능 저하 재평가 권고")
            elif tsh >= 4.0 and _levo_detected:
                # LT4 치료 중 4.0~4.5: 참고범위 상한 근처 = 치료 목표 상한 경계
                factors.append(
                    f"TSH {tsh} mIU/L — 레보티록신 치료 중 참고범위 상한 근처(경계 상승 가능); "
                    "복약 시간·공복 복용·흡수 방해 성분 병용 여부 확인 권장"
                )
            elif tsh >= 4.0 and _autoimmune:
                # 비-LT4 자가면역(하시모토/TPOAb+) 맥락: 4.0~4.5 경계 상승 가능 (#6.3).
                # 일반 건강인 4.x 는 정상으로 둠 — 아래 else.
                factors.append(
                    f"TSH {tsh} mIU/L — 자가면역 갑상선염 맥락에서 참고범위 상한 근처(경계 상승 가능); "
                    "Free T4·TPOAb 추이와 함께 재평가 권고"
                )
            else:
                factors.append(f"TSH {tsh} mIU/L — 정상 범위")

        # Free T4 (freeT4 또는 free_t4)
        ft4 = _get_lab(lab, "freet4", "free_t4")
        if ft4 is not None:
            if ft4 < 0.8:
                factors.append(f"Free T4 {ft4} ng/dL — 낮은 범위 (< 0.8)")
            elif ft4 <= 0.9:
                factors.append(f"Free T4 {ft4} ng/dL — 낮은 정상 범위 (경계, 0.8–0.9)")
            elif ft4 > 1.8:
                factors.append(f"Free T4 {ft4} ng/dL — 높은 범위 (> 1.8)")
            else:
                factors.append(f"Free T4 {ft4} ng/dL — 정상 범위")

        # 25-OH Vitamin D
        vit_d = _get_lab(lab, "25_oh_vitamin_d", "vitd", "vitamin_d", "25ohd")
        if vit_d is not None:
            if vit_d < 20:
                factors.append(f"25-OH vitamin D {vit_d} ng/mL — 결핍 범위 (< 20 ng/mL)")
            elif vit_d < 30:
                factors.append(f"25-OH vitamin D {vit_d} ng/mL — 불충분 범위 (20–30 ng/mL)")
            else:
                factors.append(f"25-OH vitamin D {vit_d} ng/mL — 정상 범위 (≥ 30 ng/mL)")

        # Calcium
        ca = _get_lab(lab, "calcium", "ca")
        if ca is not None:
            if ca < 8.5:
                factors.append(f"혈청 칼슘 {ca} mg/dL — 낮은 범위 (< 8.5)")
            elif ca > 10.5:
                factors.append(f"혈청 칼슘 {ca} mg/dL — 높은 범위 (> 10.5)")

        # Ferritin
        ferritin = _get_lab(lab, "ferritin")
        if ferritin is not None:
            if ferritin < 12:
                factors.append(f"Ferritin {ferritin} µg/L — 결핍 범위 (< 12)")
            elif ferritin < 30:
                factors.append(f"Ferritin {ferritin} µg/L — 낮은 정상 범위 (12–30)")

        # Zinc
        zinc = _get_lab(lab, "zinc")
        if zinc is not None:
            if zinc < 70:
                factors.append(f"혈청 zinc {zinc} µg/dL — 결핍 범위 (< 70)")

        # 증상 — 출력 무결성: *입력된* 증상만 "입력된" 라벨로 표시(추론·생성 금지), 없으면 "없음".
        # 의사 도구에서 입력 안 한 증상이 환자 증상처럼 보이는 것 방지 (provenance 명확화).
        # 추가로, 진단축 기반 전형 증상은 "추가 확인 권장"으로 *별도 라벨* — 입력값과 명확히 구분.
        _sx = [s for s in (patient.symptoms or []) if str(s).strip()]
        if _sx:
            factors.append(f"입력된 주요 증상: {', '.join(_sx[:5])}")
        else:
            factors.append("입력된 주요 증상: 없음")
        _pc = _patient_conditions(patient)
        _checklist = (
            _HYPER_SYMPTOM_CHECKLIST if "hyper" in _pc
            else _HYPO_SYMPTOM_CHECKLIST if "hypo" in _pc
            else []
        )
        # 이미 입력된 증상은 "미입력 항목"에서 제외 (라벨-동작 일치, 중복 방지)
        _remaining = [c for c in _checklist if not any(c in s or s in c for s in _sx)]
        if _remaining:
            factors.append(f"추가 확인 권장(미입력 항목): {', '.join(_remaining)}")

    # 기존 특수 인구군 safety_warning 유지 (임신·소아·노인)
    for w in result.safety_warnings:
        if w.category in ("pregnancy_lactation", "pediatric_caution", "elderly_caution"):
            if w.message not in factors:
                factors.append(w.message)

    return factors[:6]


# applied_rules(내부 사유 코드) → 의사 UI용 한글 라벨 (결정론 추적 카드)
_RULE_TRACE_LABELS = {
    "critical_safety_warning":   "중대 안전경고 → 조기 차단",
    "contraindication_match":    "금기 조건에 해당",
    "avoid_condition_match":     "회피 대상 진단·상태에 해당",
    "applicable_condition_match":"적용 가능 진단에 해당",
    "strong_evidence":           "가이드라인/RCT 수준 근거",
    "conditional_evidence":      "제한적 근거 → 조건부",
    "warning_present":           "안전 경고 동반 → 조건부",
    "no_condition_match":        "적용 조건 불일치 → 근거 보류",
    "dose_exceeds_ul":           "공식 상한섭취량(UL) 초과 용량 → 회피",
    "unverified_supplement":     "미검증 성분 → 판정 보류",
}


def _build_decision_trace(result, system_suggested, physician_adjusted, evidence_level) -> dict:
    """결정론 추적 정보 — '판정은 LLM이 아니라 규칙'을 의사 UI에 가시화 (§6 추적성)."""
    applied = [
        {"code": r, "label": _RULE_TRACE_LABELS.get(r, r)}
        for r in (result.applied_rules or [])
    ]
    safety_flags = sum(
        1 for w in result.safety_warnings
        if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
    )
    return {
        "decision": result.decision.value,
        "system_suggested": (system_suggested.value if system_suggested else result.decision.value),
        "physician_adjusted": bool(physician_adjusted),
        "applied_rules": applied,
        "evidence_level": evidence_level,
        "safety_flags": safety_flags,
        "note": "임상 판정은 결정론 규칙·안전검사가 내립니다. LLM은 위 결론을 자연어로 옮길 뿐 판정에 관여하지 않습니다.",
    }


class DoctorResponseFormatter:
    """의사용 — 근거 수준, 불확실성, 상담 포인트 중심."""

    def format(
        self,
        result: DecisionResult,
        physician: PhysicianProfile | None = None,
        conditions: str = "",
        medications: str = "",
        patient: PatientProfile | None = None,
        message: str = "",
        physician_note: str | None = None,
    ) -> DoctorResponse:
        # conditions/medications 는 요청 스키마상 str | list[str] 모두 허용 →
        # 이후 .lower()·f-string 사용을 위해 문자열로 정규화 (리스트 입력 시 500 방지)
        if isinstance(medications, (list, tuple)):
            medications = ", ".join(str(m) for m in medications if m)
        if isinstance(conditions, (list, tuple)):
            conditions = ", ".join(str(c) for c in conditions if c)

        # 결론 — rule 텍스트 (LLM 실패 시 fallback)
        conclusion = result.rationale or f"{result.supplement_name}: {result.decision.value}"

        # §10 근거 수준 — evidence_rank 모듈로 중앙 관리; guideline 우선 (§10.3)
        import re as _re
        _m = _re.search(r'근거 수준[:\s]+(\w[\w-]*)', result.rationale or "")
        rule_level = _m.group(1) if _m else result.confidence

        # CONTRAINDICATED/AVOID: rule의 evidence_level을 직접 사용
        # PubMed 간접 논문이 meta_analysis여도 safety ruling을 과장하지 않도록 방지
        _rule_for_evidence = get_supplement_rule(result.supplement_name)
        # §10.4 핵심/보조 근거 분리 (#4.5) — 헤드라인 evidence_level은 *결정의 핵심 근거* 기준.
        # 연관 PubMed 메타분석(예: 철결핍↔갑상선)이 max로 전체 등급을 끌어올리던 오인 차단.
        _supporting_evidence_note: str | None = None
        if result.decision in (Decision.CONTRAINDICATED, Decision.AVOID) and _rule_for_evidence:
            evidence_level = _rule_for_evidence.get("evidence_level", rule_level)
        elif result.evidence_records:
            best_pubmed = best_evidence_level(result.evidence_records)
            if _rule_for_evidence:
                # 룰 기반 결정: 헤드라인은 룰/가이드라인(핵심) 근거 유지. PubMed 최고등급이 더
                # 높아도 보조·연관 근거일 수 있어 max로 끌어올리지 않음 — 대신 보조 note로 분리 노출.
                evidence_level = rule_level
                if EVIDENCE_RANK.get(best_pubmed, 0) > EVIDENCE_RANK.get(rule_level, 0):
                    _supporting_evidence_note = (
                        f"핵심(결정) 근거 수준은 '{rule_level}'; PubMed 검색 최고 등급 "
                        f"'{best_pubmed}'는 직접 결정 근거가 아닌 보조·연관 근거일 수 있습니다 "
                        f"(개별 논문 등급은 근거 요약 참고)."
                    )
            else:
                # 룰 없음(PubMed fallback) → PubMed가 핵심 근거이므로 그대로 사용
                evidence_level = max(rule_level, best_pubmed, key=lambda v: EVIDENCE_RANK.get(v, 0))
        else:
            evidence_level = rule_level

        # §10.3 guideline 우선 정렬 + 충돌 감지
        sorted_records = sort_evidence_by_rank(result.evidence_records)
        guideline_conflict_note = detect_guideline_conflict(result.evidence_records)

        # 주요 문헌 (guideline 우선 정렬 후 상위 5건)
        key_refs = []
        for rec in sorted_records[:5]:
            ref = rec.title
            if rec.pmid:
                ref += f" (PMID: {rec.pmid})"
            if rec.journal and rec.year:
                ref += f" — {rec.journal}, {rec.year}"
            if rec.journal_tier:
                ref += f" [Tier {rec.journal_tier}]"
            key_refs.append(ref)

        # 안전 우려
        safety_concerns = [
            w.message for w in result.safety_warnings
            if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
        ]
        # INSUFFICIENT_EVIDENCE 케이스에서도 rule의 notes/avoid_conditions에 명시된
        # 갑상선 관련 잠재 위험을 안전 우려로 노출 (의사가 한눈에 잡도록).
        if result.decision == Decision.INSUFFICIENT_EVIDENCE and _rule_for_evidence:
            _avoid_conds = _rule_for_evidence.get("avoid_conditions", []) or []
            _contras = _rule_for_evidence.get("contraindications", []) or []
            _notes = (_rule_for_evidence.get("notes") or "").strip()
            if _notes and (_avoid_conds or _contras):
                # 첫 문장(또는 100자) 추출 → 가장 핵심 위험 메시지
                _first_sentence = _notes.split(".")[0].strip()
                if _first_sentence and _first_sentence not in safety_concerns:
                    safety_concerns.insert(0, f"[참고] {_first_sentence}.")

        # §6.1 고용량 독성 위험 표면화 (#6.1) — 룰에 dose-toxicity risk_tag 가 있는데
        # 안전경고가 발생하지 않아 "별도 경고 없음"이 되던 케이스(예: vitamin_d 권고)에서,
        # 상한(UL)·고용량 위험을 safety_concerns 로 승격. 데이터는 룰에 이미 존재.
        if _rule_for_evidence:
            _risk_tags = _rule_for_evidence.get("risk_tags", []) or []
            _has_dose_concern = any(
                k in c for c in safety_concerns for k in ("상한", "UL", "고용량", "고칼슘")
            )
            if not _has_dose_concern:
                for _rt in _risk_tags:
                    _msg = _DOSE_TOXICITY_RISK.get(_rt)
                    if _msg:
                        _ul = _extract_ul(_rule_for_evidence.get("official_upper_limit", ""))
                        safety_concerns.insert(0, _msg + (f" — 상한(UL) {_ul}" if _ul else ""))
                        break

        # 환자 성향 반영 포인트 — lab_values + symptoms 임계값 해석 + 특수 인구군 경고
        patient_factors = _build_patient_factors(patient, result)

        # 상담 문구 — rule counseling_points 를 [조건] 태그로 환자 맞춤 필터, 없으면 recommendations
        counseling_points = select_by_condition(result.counseling_points, patient) if result.counseling_points else list(result.recommendations[:4])
        for w in result.safety_warnings:
            if w.recommended_action and w.recommended_action not in counseling_points:
                counseling_points.append(w.recommended_action)
        
        # 의사 성향 접두사/접미사
        ATTITUDE_PREFIX = {
            "positive":  "적극적 보충 접근을 선호하시는 경우 — ",
            "neutral":   "",
            "cautious":  "신중한 접근을 권고드립니다 — ",
        }
        TOLERANCE_SUFFIX = {
            "aggressive":   "근거 수준을 감안하여 시험적 투여도 고려 가능합니다.",
            "moderate":     "표준 용량 범위에서 시작하시기를 권고합니다.",
            "conservative": "충분한 근거가 확보될 때까지 대기 전략도 합리적입니다.",
        }

        # CONTRAINDICATED/AVOID는 physician tolerance suffix 적용 제외
        # (금기 판정에서 "표준 용량 시작" 같은 문구는 임상적으로 부적절)
        _safe_to_apply_physician_tone = result.decision not in (
            Decision.CONTRAINDICATED, Decision.AVOID
        )
        # #4.3 상호작용 지배 케이스 — LT4 흡수저해 성분 + 환자가 LT4 복용 중이면
        # 핵심은 용량 시작이 아니라 복용 시간 분리·흡수 관리.
        _is_interaction_dominated = bool(
            _rule_for_evidence
            and "levothyroxine_timing" in (_rule_for_evidence.get("risk_tags") or [])
            and any(kw in medications.lower()
                    for kw in ("levothyroxine", "레보티록신", "씬지로이드", "신지로이드"))
        )
        if physician and _safe_to_apply_physician_tone:
            attitude = (physician.supplement_attitude or "neutral").lower()
            tolerance = (physician.risk_tolerance or "moderate").lower()
            prefix = ATTITUDE_PREFIX.get(attitude, "")
            suffix = TOLERANCE_SUFFIX.get(tolerance, "")
            if tolerance == "moderate" and _is_interaction_dominated:
                suffix = ("용량보다 레보티록신과의 복용 시간 분리·흡수 관리가 핵심이며, "
                          "용량은 적응증·검사 결과에 따라 조정합니다.")
            if prefix or suffix:
                counseling_points.insert(0, f"{prefix}{suffix}".strip(" — "))

        # counseling 은 위에서 select_by_condition 으로 이미 [조건] 필터됨 (구 _relevance 대체)
        counseling_points = counseling_points[:5]

        # 불확실성
        uncertainty_notes = []
        if result.confidence == "low":
            uncertainty_notes.append("현재 판단은 근거 수준이 낮아 불확실성이 높습니다.")
        if result.decision == Decision.INSUFFICIENT_EVIDENCE:
            uncertainty_notes.append("충분한 근거가 축적되면 판단이 변경될 수 있습니다.")
        limited_ev = [
            w for w in result.safety_warnings
            if w.category in ("insufficient_evidence", "limited_evidence")
        ]
        for w in limited_ev:
            uncertainty_notes.append(w.message)
        # §10.3 가이드라인 충돌 note — 전용 필드로 분리 노출 (uncertainty_notes에 묻지 않음)
        # §10.4 핵심/보조 근거 분리 note (#4.5)
        if _supporting_evidence_note:
            uncertainty_notes.append(_supporting_evidence_note)

        # evidence_summaries: guideline 우선 정렬 후 상위 8건
        evidence_summaries = []
        for rec in sorted_records[:8]:
            abstract = rec.abstract or ""
            evidence_summaries.append({
                "title": rec.title or "",
                "pmid": rec.pmid or "",
                "year": rec.year,
                "journal": rec.journal or "",
                "abstract_snippet": abstract[:300] + ("..." if len(abstract) > 300 else ""),
                "evidence_level": rec.evidence_level.value if rec.evidence_level else "",
            })

        # §14.4 physician decision 분리 (pre_physician_decision 기반으로 버그 수정)
        system_suggested = result.pre_physician_decision or result.decision
        physician_adjusted = result.decision if result.pre_physician_decision else None

        # §16.2-7 regulatory_note — MFDS 우선, 없으면 notes 안전성 부분 fallback
        rule = get_supplement_rule(result.supplement_name)
        mfds_raw = fetch_mfds_context(result.supplement_name)
        if mfds_raw:
            regulatory_note: str | None = mfds_raw[:300]
        elif rule:
            notes_text = rule.get("notes", "")
            regulatory_note = notes_text[:200] if notes_text else None
        else:
            regulatory_note = None

        # 임상 caveat — MFDS 기능성은 *일반 표시 문구*일 뿐, AVOID/CONTRAINDICATED 결정에서
        # 건강 목적 보충의 안전성을 의미하지 않음을 의사에게 명시 (일반 규칙, 케이스 무관).
        if regulatory_note and mfds_raw and result.decision in (Decision.AVOID, Decision.CONTRAINDICATED):
            regulatory_note = (
                "※ 아래 MFDS 기능성은 일반 표시 문구이며, 현재 임상 상태에서 "
                "건강 목적 보충의 안전성을 의미하지 않습니다.\n\n" + regulatory_note
            )

        # 레보티록신 흡수 저해 성분 + 레보티록신 복용 시 임상 연결 prefix 추가
        if regulatory_note and rule:
            _risk_tags = rule.get("risk_tags", [])
            if "levothyroxine_timing" in _risk_tags and medications:
                _levo_kw_check = ("levothyroxine", "레보티록신", "씬지로이드", "신지로이드")
                if any(kw in medications.lower() for kw in _levo_kw_check):
                    _prefix = (
                        "선택 성분은 레보티록신 흡수를 저해할 수 있어 복용 간격 조정이 필요합니다. "
                        "처방 시 복용 시간 분리 안내가 필요합니다.\n\n"
                    )
                    regulatory_note = _prefix + regulatory_note

        # §9.2 research_dose_summary — 연구용량/권장용량/공식상한을 독립 part로 조립.
        # #6.2: study_dose 부재(예: vitamin_d) 시 official_upper만 있어도 recommended_dose 를
        # "권장/임상 용량"으로 surface (기존엔 official_upper 존재 시 fallback에 도달 못 해 UL만 노출).
        research_dose_summary: str | None = None
        research_dose: str | None = None
        official_dose_reference: dict | None = None
        if rule:
            study_dose = filter_string_by_condition(rule.get("study_dose", ""), patient)
            official_upper = filter_string_by_condition(rule.get("official_upper_limit", ""), patient)
            parts = []
            if study_dose:
                research_dose = study_dose
                parts.append(f"연구 사용 용량: {study_dose}")
            elif (rec := filter_string_by_condition(rule.get("recommended_dose", ""), patient)):
                research_dose = rec
                parts.append(f"권장/임상 용량: {rec}")
            official_dose_reference = _build_official_dose_reference(official_upper)
            if official_upper:
                parts.append(f"공식 기준/상한: {official_upper}")
            research_dose_summary = "\n".join(parts) if parts else None

        # §8.1 reported_effects_summary — possible_benefits + WARNING 경고
        reported_effects_summary: str | None = None
        if rule:
            benefits = select_by_condition(rule.get("possible_benefits", []), patient)
            adverse = [
                w.message for w in result.safety_warnings
                if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
            ][:2]
            parts = []
            if benefits:
                parts.append("기대 효과: " + "; ".join(benefits))
            if adverse:
                parts.append("주의/부작용: " + adverse[0][:150])
            reported_effects_summary = "\n".join(parts) if parts else None

        # LLM 임상 서술 — 성공 시 rule conclusion 교체
        # counseling·rationale를 환자 [조건] 태그로 필터해 전달 (GO/TED 등 진단 무관 적응증 누출 차단).
        # 순환 import 회피: 필터는 여기(response.py)서 수행, llm_response는 schemas만 import.
        llm_conclusion = generate_doctor_llm_summary(
            result=result,
            physician=physician,
            supplement_display=result.supplement_name,
            conditions=conditions,
            medications=medications,
            message=message,
            reported_effects=reported_effects_summary,
            counseling_points=select_by_condition(result.counseling_points, patient),
            rationale=filter_string_by_condition(result.rationale or "", patient),
            interaction_dominated=_is_interaction_dominated,
        )

        # §7.2 의사용 복용 간격 판정 표시 (입력 타이밍 기반)
        _ra = result.regimen_assessment or {}
        _rstatus = _ra.get("status")
        if _rstatus in ("separated", "concurrent"):
            _l, _s = _ra.get("lt4_hour"), _ra.get("supplement_hour")
            _gap = min(abs(_l - _s), 24 - abs(_l - _s)) if _l is not None and _s is not None else None
            if _rstatus == "separated":
                counseling_points = [
                    f"[복용 간격] 입력 일정상 LT4(~{_l}시)와 {result.supplement_name}(~{_s}시)이 약 {_gap}시간 분리 — 흡수 간섭 우려 낮음, 현 일정 유지 + TSH 추적"
                ] + counseling_points
            else:
                counseling_points = [
                    f"[복용 간격] 입력 일정상 LT4(~{_l}시)와 {result.supplement_name}(~{_s}시)이 동시간대 — 흡수 간섭 우려, 최소 4시간 분리 권고"
                ] + counseling_points

        return DoctorResponse(
            conclusion=llm_conclusion or conclusion,
            decision=result.decision,
            system_suggested_decision=system_suggested if physician_adjusted else None,
            physician_adjusted_decision=physician_adjusted,
            evidence_level=evidence_level,
            key_references=key_refs,
            safety_concerns=safety_concerns[:5],
            patient_factors=patient_factors[:5],
            counseling_points=counseling_points,
            monitoring_parameters=select_by_condition(result.monitoring_parameters, patient),
            regulatory_note=regulatory_note,
            guideline_conflict=guideline_conflict_note,
            research_dose_summary=research_dose_summary,
            research_dose=research_dose,
            official_dose_reference=official_dose_reference,
            reported_effects_summary=reported_effects_summary,
            uncertainty_notes=uncertainty_notes[:4],
            evidence_summaries=evidence_summaries,
            physician_note=physician_note or None,
            regimen_assessment=result.regimen_assessment,
            decision_trace=_build_decision_trace(result, system_suggested, physician_adjusted, evidence_level),
        )
