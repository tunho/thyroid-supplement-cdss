"""
tests/test_thyroid_decision.py — 갑상선 supplement 의사결정 코어 테스트

외부 API(OpenAI, PubMed) 의존 없이 순수 rule 로직만 검증합니다.

테스트 케이스:
  1. Graves disease + iodine   → avoid 또는 contraindicated
  2. Hypothyroidism + iron deficiency suspicion → conditional_consider
  3. Graves orbitopathy + selenium → conditional_consider
  4. Unknown supplement          → insufficient_evidence
  5. Pregnancy flag              → safety warning 포함
  6. Levothyroxine + mineral     → interaction warning 포함
"""

import pytest

from domain.thyroid.decision import DecisionEngine
from domain.thyroid.profile import build_patient_profile
from domain.thyroid.rules import get_supplement_rule
from domain.thyroid.safety import SafetyEngine
from domain.thyroid.schemas import Decision, WarningSeverity
from domain.thyroid.response import PatientResponseFormatter, DoctorResponseFormatter


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def safety_engine():
    return SafetyEngine()


@pytest.fixture
def decision_engine():
    return DecisionEngine()


@pytest.fixture
def patient_formatter():
    return PatientResponseFormatter()


@pytest.fixture
def doctor_formatter():
    return DoctorResponseFormatter()


# ── Test 1: Graves disease + iodine → avoid / contraindicated ──

def test_graves_iodine_avoid(safety_engine, decision_engine):
    """Graves 환자에서 요오드 보충은 avoid 또는 contraindicated."""
    patient = build_patient_profile(diagnosis="graves_disease", medications="methimazole")
    rule = get_supplement_rule("iodine")
    assert rule is not None

    warnings = safety_engine.check(patient, "iodine", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="iodine",
        rule=rule,
        safety_warnings=warnings,
    )

    assert result.decision in (Decision.AVOID, Decision.CONTRAINDICATED), \
        f"Expected avoid/contraindicated, got {result.decision.value}"
    assert len(result.safety_warnings) > 0


# ── Test 2: Hypothyroidism + iron deficiency → conditional_consider ──

def test_hypothyroidism_iron_manage_interaction(safety_engine, decision_engine):
    """갑상선기능저하증 + 철결핍 + LT4 → manage_interaction (#4.1 taxonomy).
    성분 자체 문제가 아니라 LT4 병용 관리(복용 분리)가 핵심인 케이스."""
    patient = build_patient_profile(
        diagnosis="hypothyroidism,iron_deficiency",
        medications="levothyroxine",
    )
    rule = get_supplement_rule("iron")
    assert rule is not None

    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="iron",
        rule=rule,
        safety_warnings=warnings,
    )

    # levothyroxine_interaction 경고 → CONDITIONAL_CONSIDER가 MANAGE_INTERACTION으로 정밀화
    assert result.decision == Decision.MANAGE_INTERACTION, \
        f"Expected manage_interaction, got {result.decision.value}"


def test_iron_no_lt4_stays_conditional(safety_engine, decision_engine):
    """LT4 없는 철결핍 → conditional_consider 유지 (taxonomy는 LT4 상호작용 한정)."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings,
    )
    assert result.decision == Decision.CONDITIONAL_CONSIDER, \
        f"Expected conditional_consider, got {result.decision.value}"


def test_manage_interaction_patient_framing(safety_engine, decision_engine, patient_formatter):
    """#4.1 Phase 2 lock-in — 환자 포매터가 MANAGE_INTERACTION을 '복용 분리' 중심으로 표현."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings,
    )
    assert result.decision == Decision.MANAGE_INTERACTION
    out = patient_formatter.format(result, patient)
    assert out.can_take == "복용 가능 — 다른 약과 시간 분리 필요"
    assert "분리" in out.summary
    assert any("분리" in a for a in out.next_actions), "분리 안내가 next_actions에 있어야 함"


def test_manage_interaction_doctor_prompt_framing(safety_engine, decision_engine):
    """#4.1 Phase 3 lock-in — 의사 LLM 프롬프트가 병용관리 초점, 회피 프레이밍 미포함.
    LLM 출력은 비결정적이라 *프롬프트 조립*(결정론적)만 검증."""
    from unittest.mock import patch
    import domain.thyroid.llm_response as L

    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings,
    )
    assert result.decision == Decision.MANAGE_INTERACTION

    captured = {}
    def _fake(prompt, max_tokens=350):
        captured["p"] = prompt
        return "ok"
    with patch.object(L, "_call_llm", _fake):
        L.generate_doctor_llm_summary(
            result=result, physician=None, supplement_display="철분",
            conditions="hypothyroidism", medications="levothyroxine",
        )
    prompt = captured["p"]
    assert "병용 관리" in prompt, "MANAGE_INTERACTION 프롬프트는 병용관리 초점이어야 함"
    assert "비처방 건강 목적의 보충은 권장되지 않는다" not in prompt, "회피 프레이밍이 누출되면 안 됨"


# ── Test 3: Graves orbitopathy + selenium → conditional_consider ──

def test_graves_orbitopathy_selenium(safety_engine, decision_engine):
    """그레이브스 안병증 + 셀레늄 → conditional_consider (RCT 근거 있으나 주의 필요)."""
    patient = build_patient_profile(
        diagnosis="graves_orbitopathy",
        medications="methimazole",
    )
    rule = get_supplement_rule("selenium")
    assert rule is not None

    warnings = safety_engine.check(patient, "selenium", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="selenium",
        rule=rule,
        safety_warnings=warnings,
    )

    # selenium은 RCT 근거가 있지만 antithyroid drug warning → conditional
    assert result.decision in (Decision.RECOMMEND, Decision.CONDITIONAL_CONSIDER), \
        f"Expected recommend/conditional_consider, got {result.decision.value}"


# ── Test 3b: EUGOGO 2021 selenium 정밀 추출 반영 ──

def test_eugogo2021_selenium_extraction():
    """EUGOGO 2021 Rec #7 + Marcocci 2011 정밀 추출이 selenium 룰에 반영됐는지 검증.

    - 정확한 PMID (EUGOGO2021:34297684, Marcocci2011:21591944) 부착
    - 염 200µg vs 원소 91.2µg 구분
    - 경증·활동성 한정 (중등도-중증 근거 없음)
    """
    rule = get_supplement_rule("selenium")
    assert rule is not None

    notes = rule["notes"]
    study = rule["study_dose"]
    # 염(sodium selenite 200µg) vs 원소 셀레늄 91.2µg 구분 — 값에 반영
    assert "91.2" in study, "원소 셀레늄 91.2µg 구분 누락"
    assert "Marcocci 2011" in study, "Marcocci 2011 근거 누락"
    # 경증·활동성 한정 + 중등도-중증 근거 없음
    assert "중등도-중증" in notes, "중등도-중증 근거 없음 단서 누락"
    # 셀레늄 결핍 지역 단서 (한국 적용 핵심)
    counseling = " ".join(rule["counseling_points"])
    assert "결핍" in counseling and "충족" in counseling, "selenium-deficient/replete 지역 단서 누락"

    # 정확한 PMID 인용은 소스 주석에 부착 — 소스 텍스트로 검증
    from pathlib import Path
    import domain.thyroid.rules as rules_mod
    src = Path(rules_mod.__file__).read_text(encoding="utf-8")
    assert "PMID:34297684" in src, "EUGOGO 2021 정확 PMID(34297684) 누락"
    assert "PMID:21591944" in src, "Marcocci 2011 정확 PMID(21591944) 누락"


# ── Test 4: Unknown supplement → insufficient_evidence ──

def test_unknown_supplement_insufficient(safety_engine, decision_engine):
    """rule 미등록 영양제 → insufficient_evidence."""
    patient = build_patient_profile(diagnosis="hypothyroidism")
    rule = get_supplement_rule("ashwagandha_extract_xyz")
    assert rule is None  # 미등록 확인

    warnings = safety_engine.check(patient, "ashwagandha_extract_xyz", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="ashwagandha_extract_xyz",
        rule=rule,
        safety_warnings=warnings,
    )

    assert result.decision == Decision.INSUFFICIENT_EVIDENCE, \
        f"Expected insufficient_evidence, got {result.decision.value}"


# ── Test 5: Pregnancy flag → safety warning ──

def test_pregnancy_safety_warning(safety_engine):
    """임신 risk_factor가 설정되면 pregnancy safety warning이 포함되어야 함."""
    patient = build_patient_profile(
        diagnosis="hypothyroidism",
        risk_factors="pregnancy",
    )
    rule = get_supplement_rule("iodine")

    warnings = safety_engine.check(patient, "iodine", rule)

    pregnancy_warnings = [w for w in warnings if w.category == "pregnancy_lactation"]
    assert len(pregnancy_warnings) > 0, "Pregnancy safety warning이 누락되었습니다."
    assert any(w.severity in (WarningSeverity.WARNING, WarningSeverity.CAUTION) for w in pregnancy_warnings)
    # recommended_action이 비어있지 않은지 확인
    assert all(w.recommended_action for w in pregnancy_warnings), \
        "Pregnancy warning에 recommended_action이 없습니다."


# ── Test 6: Levothyroxine + mineral → interaction warning ──

def test_levothyroxine_iron_interaction(safety_engine):
    """레보티록신 복용 중 철분제 → levothyroxine interaction warning."""
    patient = build_patient_profile(
        diagnosis="hypothyroidism",
        medications="levothyroxine",
    )
    rule = get_supplement_rule("iron")

    # §13.1 환자 모드 (기본값 is_doctor_mode=False)
    warnings_patient = safety_engine.check(patient, "iron", rule, is_doctor_mode=False)
    interaction_patient = [w for w in warnings_patient if w.category == "levothyroxine_interaction"]
    assert len(interaction_patient) > 0, "Levothyroxine interaction warning이 누락되었습니다."
    # §13.1: 환자용은 공복·식사 간격·상담 중심 (단독 "4시간" 강조 완화)
    assert any("간격" in w.message or "공복" in w.message or "상담" in w.recommended_action
               for w in interaction_patient), \
        "환자용 levothyroxine 안내에 간격/공복/상담 내용이 포함되어야 합니다."

    # §13.2 의사 모드
    warnings_doctor = safety_engine.check(patient, "iron", rule, is_doctor_mode=True)
    interaction_doctor = [w for w in warnings_doctor if w.category == "levothyroxine_interaction"]
    assert len(interaction_doctor) > 0, "의사 모드에서 Levothyroxine interaction warning이 누락되었습니다."
    assert any("4시간" in w.recommended_action or "흡수 저해" in w.message
               for w in interaction_doctor), \
        "의사용 levothyroxine 안내에 흡수 저해 또는 4시간 정보가 포함되어야 합니다."


# ── Test 7: Response formatters produce valid output ──

def test_patient_response_format(safety_engine, decision_engine, patient_formatter):
    """PatientResponseFormatter가 유효한 PatientResponse를 생성하는지 확인."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings,
    )

    response = patient_formatter.format(result)
    assert response.summary
    # §7.2 완화된 문구로 갱신
    assert response.can_take in (
        "근거 있음 (상담 권고)", "조건부 확인 필요", "복용 가능 — 다른 약과 시간 분리 필요",
        "주의 필요 (상담 필수)", "금기 자료 있음 (상담 필수)", "근거 제한적",
        "정보필요", "해당없음",  # thyroid.py 에서 직접 set 하는 케이스
    )
    assert isinstance(response.cautions, list)
    assert isinstance(response.next_actions, list)


def test_doctor_response_format(safety_engine, decision_engine, doctor_formatter):
    """DoctorResponseFormatter가 유효한 DoctorResponse를 생성하는지 확인."""
    patient = build_patient_profile(diagnosis="graves_orbitopathy", medications="methimazole")
    rule = get_supplement_rule("selenium")
    warnings = safety_engine.check(patient, "selenium", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="selenium", rule=rule, safety_warnings=warnings,
    )

    response = doctor_formatter.format(result)
    assert response.conclusion
    assert response.decision in Decision
    assert isinstance(response.counseling_points, list)


def test_patient_input_height_weight_history(safety_engine, decision_engine, patient_formatter):
    """#15.1 — 키·몸무게→BMI(표시), 수술력→surgery 조건(반영), 병력→표시 전용(결정 미반영).
    과거(해소된) 그레이브스 병력이 현재 hyper 조건으로 오분류되지 않아야 함."""
    from domain.thyroid.response import _patient_conditions
    patient = build_patient_profile(
        diagnosis="갑상선기능저하증", height_cm=166, weight_kg=61,
        surgical_history="갑상선 전절제술", past_history="그레이브스병", age=39, sex="F",
    )
    assert patient.bmi == 22.1
    conds = _patient_conditions(patient)
    # 수술력 → surgery 반영 (영구 사실, #6.4 동일 축)
    assert "surgery" in conds
    assert "hypo" in conds              # 현재 진단
    # 병력은 결정 로직 미반영 — 과거 그레이브스가 현재 hyper로 오분류되면 안 됨
    assert "hyper" not in conds, "과거(해소된) 병력이 현재 조건으로 오분류되면 안 됨"
    # 단, 병력·수술력·BMI 는 patient_factors 에 표시(수집+표시는 유지)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="vitamin_d",
        rule=get_supplement_rule("vitamin_d"),
        safety_warnings=safety_engine.check(patient, "vitamin_d", get_supplement_rule("vitamin_d")),
    )
    pf = patient_formatter.format(result, patient).patient_factors
    assert any("BMI 22.1" in f for f in pf)
    assert any("수술력" in f for f in pf)
    assert any("병력" in f for f in pf)


def test_patient_doctor_expression_separation(safety_engine, decision_engine, patient_formatter, doctor_formatter):
    """#4/§16.1·§16.3 — 환자용은 쉬운 언어(인용·코드·raw 용량 제거), 의사용은 raw 유지(분리)."""
    import re as _re
    patient = build_patient_profile(diagnosis="hashimoto", medications="", age=45, sex="F")
    rule = get_supplement_rule("vitamin_d")
    warnings = safety_engine.check(patient, "vitamin_d", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="vitamin_d", rule=rule, safety_warnings=warnings,
    )
    po = patient_formatter.format(result, patient)
    do = doctor_formatter.format(result, conditions="hashimoto", medications="", patient=patient)

    JARGON = _re.compile(r"PMID|ATA 20|KDRI|NIH ODS|`|[a-z]+_[a-z]+_")
    patient_blob = " ".join(str(x or "") for x in (po.evidence_summary, po.research_dose_summary, po.research_dose))
    # §9.1: 환자엔 raw 연구용량 미제공
    assert po.research_dose is None
    # §16.1: 환자 텍스트에 인용/코드 전문표기 없음
    assert not JARGON.search(patient_blob), f"환자 응답에 전문표기 잔존: {patient_blob}"
    # §16.3: 의사 응답엔 raw 근거(연구용량/출처) 유지 → 분리 확인
    assert "NIH ODS" in (do.research_dose_summary or ""), "의사 응답은 raw 용량/출처를 유지해야 함"


# ── Test 9: Hashimoto + vitamin D → conditional_consider ──

def test_hashimoto_vitamin_d(safety_engine, decision_engine):
    """하시모토 갑상선염 + 비타민D → conditional_consider (관찰연구 수준 근거)."""
    patient = build_patient_profile(diagnosis="hashimoto")
    rule = get_supplement_rule("vitamin_d")
    assert rule is not None

    warnings = safety_engine.check(patient, "vitamin_d", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="vitamin_d",
        rule=rule,
        safety_warnings=warnings,
    )

    assert result.decision in (Decision.CONDITIONAL_CONSIDER, Decision.INSUFFICIENT_EVIDENCE), \
        f"Expected conditional_consider or insufficient_evidence, got {result.decision.value}"


# ── Test 10: Hyperthyroidism + ashwagandha → warning + avoid/insufficient ──

def test_hyperthyroidism_ashwagandha(safety_engine, decision_engine):
    """갑상선기능항진증 + ashwagandha → herb warning 포함, avoid/insufficient_evidence."""
    patient = build_patient_profile(diagnosis="hyperthyroidism")
    rule = get_supplement_rule("ashwagandha")
    # ashwagandha는 미등록이므로 rule == None

    warnings = safety_engine.check(patient, "ashwagandha", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="ashwagandha",
        rule=rule,
        safety_warnings=warnings,
    )

    # herb 경고 포함 확인
    herb_warnings = [w for w in warnings if w.category == "herb_thyrotoxicosis"]
    assert len(herb_warnings) > 0, "Ashwagandha에 대한 herb_thyrotoxicosis warning이 누락되었습니다."

    # 미등록이므로 insufficient_evidence
    assert result.decision in (Decision.AVOID, Decision.INSUFFICIENT_EVIDENCE), \
        f"Expected avoid/insufficient_evidence, got {result.decision.value}"


# ── Test 11: Korean diagnosis normalization ──

def test_korean_diagnosis_normalization():
    """한국어 진단명이 canonical English key로 정규화되는지 확인."""
    from domain.thyroid.profile import normalize_diagnosis

    assert normalize_diagnosis("그레이브스병") == "graves_disease"
    assert normalize_diagnosis("갑상선기능항진증") == "hyperthyroidism"
    assert normalize_diagnosis("갑상선기능저하증") == "hypothyroidism"
    assert normalize_diagnosis("하시모토") == "hashimoto"
    assert normalize_diagnosis("하시모토 갑상선염") == "hashimoto"
    assert normalize_diagnosis("그레이브스 안병증") == "graves_orbitopathy"
    # 임신/수유 — applicable_conditions(pregnancy/lactation) 매칭용 (서버 테스트로 발견된 누락)
    assert normalize_diagnosis("임신") == "pregnancy"
    assert normalize_diagnosis("임신부") == "pregnancy"
    assert normalize_diagnosis("수유") == "lactation"
    assert normalize_diagnosis("모유수유") == "lactation"


# ── Test 11b: Phase B ATA 2017 신규 진단명 alias ──

def test_ata2017_phase_b_alias_normalization():
    """Phase B 등록 5건의 신규 진단명/상태 alias 정규화 확인."""
    from domain.thyroid.profile import normalize_diagnosis

    # 산후 갑상선염 (ATA 2017 R85~R91)
    assert normalize_diagnosis("산후 갑상선염") == "postpartum_thyroiditis"
    assert normalize_diagnosis("산후갑상선염") == "postpartum_thyroiditis"
    # 아임상 갑상선기능저하 — 일반
    assert normalize_diagnosis("아임상 갑상선기능저하") == "subclinical_hypothyroidism"
    # 임신 아임상 갑상선기능저하 (R29)
    assert normalize_diagnosis("임신 아임상 갑상선기능저하") == "subclinical_hypothyroidism_pregnancy"
    # 단독성 저티록신혈증 (R30)
    assert normalize_diagnosis("단독성 저티록신혈증") == "isolated_hypothyroxinemia"
    # 임신성 일과성 갑상선중독증 (R42)
    assert normalize_diagnosis("임신성 갑상선중독증") == "gestational_transient_thyrotoxicosis"
    # TPOAb 양성 (lab 상태)
    assert normalize_diagnosis("TPOAb 양성") == "tpoab_positive"
    assert normalize_diagnosis("tpo_ab_positive") == "tpoab_positive"


# ── Test 12: Korean diagnosis + Graves + iodine end-to-end ──

def test_korean_graves_iodine_avoid(safety_engine, decision_engine):
    """한국어 진단명 '그레이브스병'으로 입력해도 avoid/contraindicated."""
    patient = build_patient_profile(diagnosis="그레이브스병")
    rule = get_supplement_rule("iodine")

    warnings = safety_engine.check(patient, "iodine", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="iodine",
        rule=rule,
        safety_warnings=warnings,
    )

    assert result.decision in (Decision.AVOID, Decision.CONTRAINDICATED), \
        f"Expected avoid/contraindicated for Korean 그레이브스병, got {result.decision.value}"


# ── Test 13: infer_supplement_from_message ──

def test_infer_supplement_from_message():
    """자유 입력 메시지에서 영양제 키워드를 추출."""
    from domain.thyroid.rules import infer_supplement_from_message

    inferred, _ = infer_supplement_from_message("그레이브스병인데 요오드 영양제 먹어도 되나요?")
    assert inferred == "iodine"
    inferred, _ = infer_supplement_from_message("셀레늄 복용해도 괜찮을까요?")
    assert inferred == "selenium"
    inferred, _ = infer_supplement_from_message("비타민 D 보충제 추천해주세요")
    assert inferred == "vitamin_d"
    inferred, _ = infer_supplement_from_message("유산균 먹어도 되나요?")
    assert inferred == "probiotics"
    inferred, _ = infer_supplement_from_message("아무 관련 없는 메시지입니다")
    assert inferred is None


# ── Test 14: Conservative 의사 → RECOMMEND 강등 ──────────────────
def test_conservative_physician_downgrade(safety_engine, decision_engine):
    """conservative 의사에서 selenium/graves_orbitopathy는 CONDITIONAL_CONSIDER."""
    from domain.thyroid.profile import build_physician_profile
    patient = build_patient_profile(diagnosis="graves_orbitopathy")
    physician = build_physician_profile(risk_tolerance="conservative")
    rule = get_supplement_rule("selenium")
    assert rule is not None

    warnings = safety_engine.check(patient, "selenium", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="selenium",
        rule=rule,
        safety_warnings=warnings,
        physician=physician,
    )
    assert result.decision == Decision.CONDITIONAL_CONSIDER, (
        f"Expected CONDITIONAL_CONSIDER, got {result.decision.value}"
    )


# ── Test 15: Aggressive 의사 → confidence 상향 ────────────────────
def test_aggressive_physician_confidence_upgrade(safety_engine, decision_engine):
    """aggressive 의사 + vitamin_d + hashimoto → confidence medium 이상."""
    from domain.thyroid.profile import build_physician_profile
    patient = build_patient_profile(diagnosis="hashimoto")
    physician = build_physician_profile(risk_tolerance="aggressive")
    rule = get_supplement_rule("vitamin_d")
    assert rule is not None

    warnings = safety_engine.check(patient, "vitamin_d", rule)
    result = decision_engine.evaluate(
        patient=patient,
        supplement_name="vitamin_d",
        rule=rule,
        safety_warnings=warnings,
        physician=physician,
    )
    assert result.confidence in ("medium", "high"), (
        f"Expected medium/high confidence, got {result.confidence}"
    )


# ── Test 16: MFDS 경고 존재 확인 (iodine, selenium) ───────────────
def test_mfds_iodine_warning(safety_engine):
    """iodine SafetyEngine 결과에 MFDS upper_limit 경고 포함."""
    patient = build_patient_profile(diagnosis="hypothyroidism")
    rule = get_supplement_rule("iodine")
    warnings = safety_engine.check(patient, "iodine", rule)

    mfds = [w for w in warnings if w.category == "mfds_upper_limit"]
    assert len(mfds) >= 1, "MFDS upper_limit 경고가 없음"
    assert "MFDS" in mfds[0].message


def test_mfds_selenium_warning(safety_engine):
    """selenium SafetyEngine 결과에 MFDS upper_limit 경고 포함."""
    patient = build_patient_profile(diagnosis="hashimoto")
    rule = get_supplement_rule("selenium")
    warnings = safety_engine.check(patient, "selenium", rule)

    mfds = [w for w in warnings if w.category == "mfds_upper_limit"]
    assert len(mfds) >= 1, "MFDS upper_limit 경고가 없음"
    assert "MFDS" in mfds[0].message


# ── Test 17: Ashwagandha + Graves → CRITICAL warning ────────────
def test_ashwagandha_graves_critical_warning(safety_engine, decision_engine):
    """그레이브스병 + 아슈와간다 → CRITICAL safety warning 포함, avoid/insufficient."""
    from domain.thyroid.profile import build_patient_profile
    from domain.thyroid.rules import get_supplement_rule
    from domain.thyroid.schemas import Decision

    patient = build_patient_profile(diagnosis="graves_disease")
    rule = get_supplement_rule("ashwagandha")

    warnings = safety_engine.check(patient, "ashwagandha", rule)

    critical = [w for w in warnings if w.severity.value == "critical"]
    assert len(critical) >= 1, "Ashwagandha + Graves CRITICAL warning 누락"
    assert any("항진" in w.message or "grave" in w.message.lower() for w in critical)

    if rule:
        result = decision_engine.evaluate(
            patient=patient, supplement_name="ashwagandha",
            rule=rule, safety_warnings=warnings,
        )
        assert result.decision in (Decision.AVOID, Decision.CONTRAINDICATED)


# ── Test 18: Ashwagandha + pregnancy → CRITICAL warning ─────────
def test_ashwagandha_pregnancy_critical_warning(safety_engine):
    """임신 + 아슈와간다 → CRITICAL safety warning."""
    from domain.thyroid.profile import build_patient_profile
    from domain.thyroid.rules import get_supplement_rule

    patient = build_patient_profile(
        diagnosis="hypothyroidism",
        risk_factors="pregnancy",
    )
    rule = get_supplement_rule("ashwagandha")
    warnings = safety_engine.check(patient, "ashwagandha", rule)

    pregnancy_critical = [
        w for w in warnings
        if w.category == "pregnancy_contraindicated" and w.severity.value == "critical"
    ]
    assert len(pregnancy_critical) >= 1, "임신 + ashwagandha CRITICAL warning 누락"


# ── Test 19: Omega3 + 항응고제 → anticoagulant_interaction warning ─
def test_omega3_anticoagulant_warning(safety_engine):
    """오메가3 + 와파린 → anticoagulant_interaction warning."""
    from domain.thyroid.profile import build_patient_profile
    from domain.thyroid.rules import get_supplement_rule

    patient = build_patient_profile(
        diagnosis="hashimoto",
        medications="warfarin",
    )
    rule = get_supplement_rule("omega3")

    warnings = safety_engine.check(patient, "omega3", rule)

    ac_warnings = [w for w in warnings if w.category == "anticoagulant_interaction"]
    assert len(ac_warnings) >= 1, "Omega3 + 와파린 항응고제 경고 누락"


# ── Test 20: New supplements registered ─────────────────────────
def test_new_supplement_rules_registered():
    """신규 3종 영양제 rule 등록 확인."""
    from domain.thyroid.rules import get_supplement_rule

    assert get_supplement_rule("vitamin_b12") is not None
    assert get_supplement_rule("omega3") is not None
    assert get_supplement_rule("ashwagandha") is not None
    # synonym 정규화 확인
    assert get_supplement_rule("아슈와간다") is not None
    assert get_supplement_rule("오메가3") is not None


# ── Test 21: generate_chat_response is_update_turn ────────────────
def test_generate_chat_response_update_turn():
    """is_update_turn = True일 때 generate_chat_response가 올바르게 작동하는지 검증."""
    from domain.thyroid.llm_response import generate_chat_response
    from domain.thyroid.schemas import DecisionResult, Decision
    from unittest.mock import patch

    result = DecisionResult(
        decision=Decision.CONDITIONAL_CONSIDER,
        supplement_name="omega3",
        confidence="medium",
        rationale="오메가3는 항염증 효과가 있으나 고용량 복용 시 출혈 위험이 있음.",
    )

    with patch("domain.thyroid.llm_response._call_llm") as mock_call:
        mock_call.return_value = "신지록신 복용을 확인했습니다. 오메가3와 신지록신은 상호작용이 없습니다."
        
        resp = generate_chat_response(
            result=result,
            display_name="오메가3",
            conditions="갑상선기능저하증",
            medications="레보티록신",
            is_update_turn=True,
        )
        
        assert resp == "신지록신 복용을 확인했습니다. 오메가3와 신지록신은 상호작용이 없습니다."
        mock_call.assert_called_once()
        args, kwargs = mock_call.call_args
        prompt = args[0]
        assert "이전 판단을 번복하거나 영양제에 대한 전체적인 효능 소개를 처음부터 다시 장황하게 반복하지 마세요" in prompt
        assert "레보티록신" in prompt
        assert "갑상선기능저하증" in prompt


# ── Test 22: TSH 억제 + 골밀도 영양제 경고 ────────────────────────
def test_tsh_suppressed_bone_risk_warning(safety_engine):
    """TSH < 0.4 + 레보티록신 + 칼슘 조합에서 tsh_suppressed_bone_risk 경고 발생."""
    from domain.thyroid.profile import build_patient_profile
    from domain.thyroid.rules import get_supplement_rule

    patient = build_patient_profile(
        diagnosis="thyroidectomy_postop",
        medications="씬지로이드",
        lab_values={"TSH": 0.08},
    )
    rule = get_supplement_rule("calcium")

    warnings = safety_engine.check(patient, "산호칼슘", rule)

    bone_warnings = [w for w in warnings if w.category == "tsh_suppressed_bone_risk"]
    assert len(bone_warnings) == 1, "TSH 억제 + 칼슘 경고 누락"
    assert "0.08" in bone_warnings[0].message


# ── Test 23: TSH 정상 범위에서 억제 경고 미발생 ──────────────────────
def test_tsh_normal_no_bone_risk_warning(safety_engine):
    """TSH 정상(1.5) + 칼슘에서 tsh_suppressed_bone_risk 경고 없음."""
    from domain.thyroid.profile import build_patient_profile
    from domain.thyroid.rules import get_supplement_rule

    patient = build_patient_profile(
        diagnosis="thyroidectomy_postop",
        medications="씬지로이드",
        lab_values={"TSH": 1.5},
    )
    rule = get_supplement_rule("calcium")

    warnings = safety_engine.check(patient, "산호칼슘", rule)

    bone_warnings = [w for w in warnings if w.category == "tsh_suppressed_bone_risk"]
    assert len(bone_warnings) == 0, "TSH 정상 범위에서 억제 경고가 잘못 발생"


# ── Test 24: counseling_points + monitoring_parameters rule 로드 ──────
def test_calcium_counseling_monitoring_fields():
    """calcium rule에 counseling_points, monitoring_parameters가 올바르게 등록됨."""
    from domain.thyroid.rules import get_supplement_rule

    rule = get_supplement_rule("calcium")
    assert rule is not None
    assert len(rule.get("counseling_points", [])) >= 4, "counseling_points 항목 부족"
    assert len(rule.get("monitoring_parameters", [])) >= 4, "monitoring_parameters 항목 부족"
    cp_text = " ".join(rule["counseling_points"])
    assert "4시간" in cp_text, "레보티록신 간격 안내 누락"
    assert "elemental calcium" in cp_text or "원소 칼슘" in cp_text, "원소 칼슘 단위 안내 누락"
    mp_text = " ".join(rule["monitoring_parameters"])
    assert "TSH" in mp_text, "TSH 추적 항목 누락"
    assert "PTH" in mp_text, "PTH 추적 항목 누락"


# ── Test 25: DecisionResult에 신규 필드 전달 확인 ─────────────────────
def test_decision_result_passes_counseling_fields():
    """calcium + 갑상선전절제 케이스에서 DecisionResult에 counseling_points/monitoring_parameters 전달."""
    from domain.thyroid.decision import DecisionEngine
    from domain.thyroid.schemas import PatientProfile, Decision
    from domain.thyroid.rules import get_supplement_rule

    engine = DecisionEngine()
    patient = PatientProfile(diagnosis=["thyroidectomy_postop"], medications=[], lab_values={})
    rule = get_supplement_rule("calcium")

    result = engine.evaluate(
        patient=patient,
        supplement_name="calcium",
        rule=rule,
        safety_warnings=[],
    )

    assert result.decision in (Decision.RECOMMEND, Decision.CONDITIONAL_CONSIDER)
    assert len(result.counseling_points) >= 4, "counseling_points DecisionResult 전달 실패"
    assert len(result.monitoring_parameters) >= 4, "monitoring_parameters DecisionResult 전달 실패"


# ── Test 26: conservative 의사 성향으로 pre_physician_decision 추적 ───
def test_conservative_physician_pre_decision_tracked():
    """conservative 의사 + selenium + hashimoto: RECOMMEND → CONDITIONAL_CONSIDER 조정 추적."""
    from domain.thyroid.decision import DecisionEngine
    from domain.thyroid.schemas import PatientProfile, PhysicianProfile, Decision
    from domain.thyroid.rules import get_supplement_rule

    engine = DecisionEngine()
    patient = PatientProfile(diagnosis=["hashimoto"], medications=[], lab_values={})
    physician = PhysicianProfile(risk_tolerance="conservative")
    rule = get_supplement_rule("selenium")

    result = engine.evaluate(
        patient=patient,
        supplement_name="selenium",
        rule=rule,
        safety_warnings=[],
        physician=physician,
    )

    assert result.decision == Decision.CONDITIONAL_CONSIDER, "conservative 성향이 CONDITIONAL로 조정되어야 함"
    assert result.pre_physician_decision == Decision.RECOMMEND, "pre_physician_decision이 원래 RECOMMEND여야 함"


# ── Test 27: DoctorResponseFormatter에서 신규 필드 생성 확인 ─────────
def test_doctor_formatter_new_fields():
    """calcium 결과에서 research_dose_summary, reported_effects_summary 생성 확인."""
    from domain.thyroid.response import DoctorResponseFormatter
    from domain.thyroid.decision import DecisionEngine
    from domain.thyroid.schemas import PatientProfile
    from domain.thyroid.rules import get_supplement_rule

    engine = DecisionEngine()
    patient = PatientProfile(diagnosis=["thyroidectomy_postop"], medications=[], lab_values={})
    rule = get_supplement_rule("calcium")

    result = engine.evaluate(
        patient=patient,
        supplement_name="calcium",
        rule=rule,
        safety_warnings=[],
    )

    formatter = DoctorResponseFormatter()
    response = formatter.format(result)

    assert response.research_dose_summary is not None, "research_dose_summary 미생성"
    assert any(c in response.research_dose_summary for c in ("mg", "µg", "/", "g")), \
        "research_dose_summary에 용량 정보 없음"
    assert response.reported_effects_summary is not None, "reported_effects_summary 미생성"
    assert "기대 효과" in response.reported_effects_summary


# ── Test 28: PUBTYPE_EVIDENCE_LEVEL 재매핑 확인 ──────────────────────
def test_pubtype_evidence_level_remapping():
    """§10.2 재매핑 + Fix B/C: Systematic Review 분리, Phase cap 확인."""
    from domain.consultation.pubmed.pubmed_postfilter import assign_evidence_level

    # 기존 매핑
    assert assign_evidence_level(["Randomized Controlled Trial"]) == "rct"
    assert assign_evidence_level(["Meta-Analysis"]) == "meta_analysis"
    assert assign_evidence_level(["Cohort Study"]) == "cohort"
    assert assign_evidence_level(["Case-Control Study"]) == "case_control"
    assert assign_evidence_level(["Case Reports"]) == "case_report"
    assert assign_evidence_level(["Observational Study"]) == "observational"

    # Fix B: Systematic Review는 meta_analysis와 구분
    assert assign_evidence_level(["Systematic Review"]) == "systematic_review"
    assert assign_evidence_level(["Systematic Review"]) != "meta_analysis"

    # Fix C: Phase cap — Phase I + RCT 동시 태그 → observational로 억제
    assert assign_evidence_level(["Clinical Trial, Phase I", "Randomized Controlled Trial"]) == "observational"
    # Phase II + RCT → cohort로 억제
    assert assign_evidence_level(["Clinical Trial, Phase II", "Randomized Controlled Trial"]) == "cohort"
    # Phase III + RCT → cap 없음, rct 유지
    assert assign_evidence_level(["Clinical Trial, Phase III", "Randomized Controlled Trial"]) == "rct"


# ── Test 29: EVIDENCE_RANK와 PUBTYPE_EVIDENCE_LEVEL 정합성 확인 ───────
def test_evidence_rank_consistency():
    """PUBTYPE_EVIDENCE_LEVEL의 모든 값이 EVIDENCE_RANK에 매핑되는지 확인."""
    from domain.consultation.pubmed.thyroid_rules import PUBTYPE_EVIDENCE_LEVEL
    from domain.thyroid.evidence_rank import EVIDENCE_RANK

    unmapped = [
        v for v in PUBTYPE_EVIDENCE_LEVEL.values()
        if v not in EVIDENCE_RANK
    ]
    assert not unmapped, f"EVIDENCE_RANK에 없는 레이블: {unmapped}"


# ── Test 30: patient_factors 자동 생성 (lab_values 임계값 해석) ──────────
def test_patient_factors_from_lab_values():
    """_build_patient_factors가 lab_values, symptoms을 임계값 기반으로 해석하는지 확인."""
    from domain.thyroid.response import _build_patient_factors
    from domain.thyroid.schemas import PatientProfile, DecisionResult, Decision

    # 비타민D 결핍 + TSH 정상 상한 + 증상
    patient = PatientProfile(
        lab_values={"25_oh_vitamin_d": 18, "TSH": 4.5, "freeT4": 0.9},
        symptoms=["피로", "우울감", "관절통"],
    )
    dummy_result = DecisionResult(
        decision=Decision.CONDITIONAL_CONSIDER,
        supplement_name="vitamin_d",
        confidence="moderate",
        safety_warnings=[],
        evidence_records=[],
        rationale="test",
        recommendations=[],
        applied_rules=[],
    )
    factors = _build_patient_factors(patient, dummy_result)

    assert any("결핍" in f for f in factors), "비타민D 결핍 문구가 없음"
    assert any("4.5" in f for f in factors), "TSH 값이 반영되지 않음"
    assert any("증상" in f for f in factors), "증상 항목이 없음"
    assert len(factors) <= 4


def test_patient_factors_empty_lab():
    """lab_values가 없으면 patient_factors가 에러 없이 빈 리스트 반환."""
    from domain.thyroid.response import _build_patient_factors
    from domain.thyroid.schemas import DecisionResult, Decision

    dummy_result = DecisionResult(
        decision=Decision.CONDITIONAL_CONSIDER,
        supplement_name="zinc",
        confidence="moderate",
        safety_warnings=[],
        evidence_records=[],
        rationale="test",
        recommendations=[],
        applied_rules=[],
    )
    factors = _build_patient_factors(None, dummy_result)
    assert factors == []


def test_patient_factors_symptom_integrity():
    """출력 무결성: 입력 안 한 증상이 환자 증상처럼 표시되면 안 됨 (의사 도구 안전)."""
    from domain.thyroid.response import _build_patient_factors
    from domain.thyroid.schemas import DecisionResult, Decision, PatientProfile

    r = DecisionResult(
        decision=Decision.AVOID, supplement_name="iodine", confidence="high",
        safety_warnings=[], evidence_records=[], rationale="", recommendations=[],
        applied_rules=[],
    )
    # 증상 미입력 → "입력된 주요 증상: 없음" 명시
    f_none = _build_patient_factors(
        PatientProfile(diagnosis=["graves_disease"], lab_values={"TSH": 0.01}), r)
    assert any("입력된 주요 증상: 없음" in x for x in f_none)
    # 무결성 핵심: *입력 라벨* 줄에는 날조 증상이 절대 없어야 함 (체크리스트와 구분)
    _input_line = next(x for x in f_none if x.startswith("입력된 주요 증상"))
    assert not any(s in _input_line for s in ("체중", "심계", "안구")), "입력 라벨에 비입력 증상 혼입"
    # 전형 증상은 *별도 라벨* "추가 확인 권장"으로만 노출 (입력 아님이 명확)
    assert any(x.startswith("추가 확인 권장") for x in f_none)
    # 증상 입력됨 → provenance 명확 ("입력된 주요 증상:")
    f_sx = _build_patient_factors(
        PatientProfile(diagnosis=["graves_disease"], symptoms=["체중감소", "심계항진"]), r)
    _in = next(x for x in f_sx if x.startswith("입력된 주요 증상"))
    assert "체중감소" in _in and "심계항진" in _in


def test_condition_filter_string_and_niche():
    """Phase B: 문자열 슬롯 [조건] 필터 + niche(저자원) 제외 + 환자 무정보 시 미필터."""
    from domain.thyroid.response import filter_string_by_condition, select_by_condition
    from domain.thyroid.schemas import PatientProfile
    graves = PatientProfile(diagnosis=["graves_disease"])
    preg = PatientProfile(diagnosis=["graves_disease"], risk_factors=["임신"])
    txt = "[임신] 250 µg/일 권장; [수유] 250 µg; 일반 정보 문장."
    # 비임신 → [임신]/[수유] 제거, 무태그 문장 유지
    g = filter_string_by_condition(txt, graves)
    assert "250 µg/일 권장" not in g and "일반 정보 문장" in g
    # 임신부 → [임신] 보존
    assert "250 µg/일 권장" in filter_string_by_condition(txt, preg)
    # 환자 정보 없음 → 원문 그대로
    assert filter_string_by_condition(txt, None) == txt
    # niche(저자원) 리스트 항목 제외
    items = ["[저자원 지역] iodized oil 대안", "일반 항목"]
    assert "[저자원 지역] iodized oil 대안" not in select_by_condition(items, graves)


# ══════════════════════════════════════════════════════════
# §7.2 Regimen-aware — 복용 간격 판정 (FOLLOWUP #7.2)
# ══════════════════════════════════════════════════════════

from domain.thyroid.regimen import (
    assess_from_text, assess_regimen, extract_timing,
    supplement_keywords, RegimenStatus,
)


def test_regimen_parser_separated_morning_lt4_night_mg():
    """아침 LT4 / 밤 마그네슘 = 이미 분리 → SEPARATED."""
    st, lt4, supp = assess_from_text(
        "아침에 레보티록신, 자기 전에 마그네슘 먹어요", ["마그네슘", "magnesium"]
    )
    assert st == RegimenStatus.SEPARATED
    assert lt4 == 7 and supp == 22


def test_regimen_parser_natural_sentence_no_comma():
    """연결어미('먹고')로 이어진 자연 문장도 성분별 시각을 정확히 — 근접도 기반.
    (콤마 없는 실제 환자 문장에서 동시복용으로 오판하던 회귀 방지)."""
    st, lt4, supp = assess_from_text(
        "아침 공복에 갑상선약 먹고 자기 전에 마그네슘 먹는데 괜찮나요?",
        ["마그네슘", "magnesium"],
    )
    assert st == RegimenStatus.SEPARATED, "아침 LT4 / 밤 Mg는 분리로 판정돼야 함"
    assert lt4 == 7 and supp == 22


def test_regimen_parser_concurrent_same_time():
    """동시간대 복용 → CONCURRENT."""
    st, _, _ = assess_from_text("씬지로이드랑 아연 둘 다 아침에 먹어요", ["아연", "zinc"])
    assert st == RegimenStatus.CONCURRENT


def test_regimen_parser_explicit_hours():
    """명시 시각(오전 7시 / 오후 9시) 파싱 → SEPARATED."""
    st, lt4, supp = assess_from_text("레보티록신 오전 7시, 칼슘 오후 9시", ["칼슘", "calcium"])
    assert st == RegimenStatus.SEPARATED
    assert lt4 == 7 and supp == 21


def test_regimen_parser_unknown_when_no_timing():
    """타이밍 정보 없음 → UNKNOWN (보수적, 회귀 없음)."""
    st, _, _ = assess_from_text("마그네슘 복용 중인데 갑상선약도 먹어요", ["마그네슘"])
    assert st == RegimenStatus.UNKNOWN


def test_regimen_circular_gap():
    """하루 순환 고려 — 23시 vs 1시 = 2시간(CONCURRENT)."""
    assert assess_regimen(23, 1) == RegimenStatus.CONCURRENT
    assert assess_regimen(7, 22) == RegimenStatus.SEPARATED


def test_supplement_keywords_bilingual():
    kws = supplement_keywords("magnesium", "마그네슘")
    assert "magnesium" in kws and "마그네슘" in kws


def test_regimen_patient_formatter_separated(safety_engine, decision_engine, patient_formatter):
    """SEPARATED → 환자 next_actions가 '안심(현 일정 유지)' 톤."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings)
    assert result.decision == Decision.MANAGE_INTERACTION
    result = result.model_copy(update={"regimen_assessment": {"status": "separated", "lt4_hour": 7, "supplement_hour": 22}})
    out = patient_formatter.format(result, patient)
    assert any("적절" in a and "유지" in a for a in out.next_actions), \
        "SEPARATED는 현 일정 유지(안심) 안내여야 함"
    assert out.regimen_assessment["status"] == "separated"


def test_regimen_patient_formatter_concurrent(safety_engine, decision_engine, patient_formatter):
    """CONCURRENT → 환자 next_actions가 '분리 권장(경고)' 톤."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings)
    result = result.model_copy(update={"regimen_assessment": {"status": "concurrent", "lt4_hour": 7, "supplement_hour": 7}})
    out = patient_formatter.format(result, patient)
    assert any("4시간" in a or "떨어뜨" in a for a in out.next_actions), \
        "CONCURRENT는 분리 권장(경고) 안내여야 함"


def test_regimen_unknown_keeps_legacy_behavior(safety_engine, decision_engine, patient_formatter):
    """UNKNOWN(또는 미부착) → 기존 일반론 유지 (회귀 없음)."""
    patient = build_patient_profile(diagnosis="hypothyroidism,iron_deficiency", medications="levothyroxine")
    rule = get_supplement_rule("iron")
    warnings = safety_engine.check(patient, "iron", rule)
    result = decision_engine.evaluate(patient=patient, supplement_name="iron", rule=rule, safety_warnings=warnings)
    out = patient_formatter.format(result, patient)  # regimen_assessment 미부착
    assert any("분리가 중요" in a for a in out.next_actions), \
        "타이밍 정보 없으면 기존 일반론 유지여야 함"


# ══════════════════════════════════════════════════════════
# Phase 0b / P3 — deterministic mode 외부호출 차단 (determinism 누수 수정)
# ══════════════════════════════════════════════════════════

def test_doctor_deterministic_no_external_call_for_unregistered():
    """결정론 모드(use_pubmed=False, allow_pubmed_fallback=False): 미등록 성분(rule=None)이어도
    PubMed 외부호출 0 + INSUFFICIENT_EVIDENCE. (rule-only primary가 실제 rule-only임을 보장)"""
    from unittest.mock import patch
    import app.services.thyroid.orchestrator as O

    with patch.object(O, "get_realtime_pubmed_evidence") as mock_pubmed:
        _, _, result = O.run_doctor_thyroid_pipeline(
            supplement_name="nonexistent_supplement_xyz",
            conditions="hashimoto",
            use_pubmed=False,
            allow_pubmed_fallback=False,
        )
    mock_pubmed.assert_not_called()
    assert result.decision == Decision.INSUFFICIENT_EVIDENCE


def test_doctor_fallback_calls_pubmed_when_allowed():
    """대조군: allow_pubmed_fallback=True(기본)면 미등록 성분에서 fallback이 PubMed를 호출.
    → 플래그가 외부호출을 실제로 게이트함을 입증(프로덕션 동작 보존)."""
    from unittest.mock import patch
    import app.services.thyroid.orchestrator as O

    with patch.object(O, "get_realtime_pubmed_evidence", return_value=[]) as mock_pubmed:
        _, _, result = O.run_doctor_thyroid_pipeline(
            supplement_name="nonexistent_supplement_xyz",
            conditions="hashimoto",
            use_pubmed=False,
            allow_pubmed_fallback=True,
        )
    mock_pubmed.assert_called_once()
    assert result.decision == Decision.INSUFFICIENT_EVIDENCE


# ══════════════════════════════════════════════════════════
# STEP 1 — 안전 트리거 (#13 lab→금기 / #11 용량→avoid)
# ══════════════════════════════════════════════════════════

from domain.thyroid import dose_safety as DS


def test_extract_dose_korean_units():
    assert DS.extract_dose("셀레늄 하루 300마이크로그램") == (300.0, "µg")
    assert DS.extract_dose("비타민D 하루 만 IU") == (10000.0, "IU")
    assert DS.extract_dose("철분 100mg") == (100.0, "mg")
    assert DS.extract_dose("그냥 먹어요") is None


def test_assess_dose_ul_thresholds():
    assert DS.assess_dose("selenium", "300마이크로그램") == "caution"   # 200<300<400
    assert DS.assess_dose("selenium", "500마이크로그램") == "avoid"     # >400
    assert DS.assess_dose("vitamin_d", "만 IU") == "avoid"             # 10000>4000
    assert DS.assess_dose("selenium", "150마이크로그램") is None        # 정상
    assert DS.assess_dose("selenium", "용량 모름") is None             # 미파싱 → 보류


def test_derive_lab_conditions_calcium():
    assert DS.derive_lab_conditions({"calcium": 10.8}) == {"hypercalcemia"}
    assert DS.derive_lab_conditions({"calcium": 12.5}) == {"severe_hypercalcemia"}
    assert DS.derive_lab_conditions({"calcium": 9.5}) == set()
    assert DS.derive_lab_conditions({}) == set()


def test_fixA_hypercalcemia_from_lab_triggers_avoid(safety_engine, decision_engine):
    """#13: lab calcium 10.8 → hypercalcemia 파생 → vitamin_d avoid 발화
    (진단명에 없어도 lab으로 잡음). past_history 아닌 현재 lab."""
    patient = build_patient_profile(diagnosis="hypothyroidism", lab_values={"calcium": 10.8})
    rule = get_supplement_rule("vitamin_d")
    warnings = safety_engine.check(patient, "vitamin_d", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="vitamin_d", rule=rule, safety_warnings=warnings,
    )
    assert result.decision in (Decision.AVOID, Decision.CONTRAINDICATED), \
        f"고칼슘혈증(lab)에서 비타민D는 avoid/contra여야 함, got {result.decision.value}"


def test_fixA_normal_calcium_no_trigger(safety_engine, decision_engine):
    """정상 calcium → hypercalcemia 미발화 (회귀 0)."""
    patient = build_patient_profile(diagnosis="hashimoto", lab_values={"calcium": 9.5, "25OH_vitD": 18})
    rule = get_supplement_rule("vitamin_d")
    warnings = safety_engine.check(patient, "vitamin_d", rule)
    result = decision_engine.evaluate(
        patient=patient, supplement_name="vitamin_d", rule=rule, safety_warnings=warnings,
    )
    assert result.decision not in (Decision.AVOID, Decision.CONTRAINDICATED), \
        "정상 calcium에서 비타민D가 avoid면 과발화"
