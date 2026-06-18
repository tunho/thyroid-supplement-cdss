"""
Phase 0 회귀 테스트 — safety.py data-driven 마이그레이션 동작 동일성.

기존 31개 분기 중 핵심 시나리오 + 트리거 유형별 1건 이상 커버.
"""
from __future__ import annotations

import pytest

from domain.thyroid.safety import SafetyEngine
from domain.thyroid.schemas import PatientProfile, WarningSeverity


@pytest.fixture
def engine():
    return SafetyEngine()


def _categories(warnings):
    return [w.category for w in warnings]


def _severities(warnings):
    return [w.severity for w in warnings]


# ──────────── 단일 trigger 유형별 ────────────

def test_iodine_graves_warning_not_critical(engine):
    """Phase C: Graves+요오드는 '건강목적 보충 회피'(WARNING→AVOID)이지 절대금기(CRITICAL) 아님.
    절대금기는 active_hyperthyroidism/iodine_allergy(contraindications) 만."""
    p = PatientProfile(diagnosis=["graves_disease"])
    rule = {"risk_tags": []}
    ws = engine.check(p, "요오드", rule)
    assert "iodine_excess" in _categories(ws)
    iodine_ws = [w for w in ws if w.category == "iodine_excess"]
    # 경고는 존재하되 WARNING (CRITICAL 조기 CONTRAINDICATED 방지 → avoid_conditions 로 AVOID)
    assert any(w.severity == WarningSeverity.WARNING for w in iodine_ws)
    assert not any(w.severity == WarningSeverity.CRITICAL for w in iodine_ws)


def test_iodine_hashimoto_warning_only(engine):
    p = PatientProfile(diagnosis=["hashimoto"])
    rule = {"risk_tags": []}
    ws = engine.check(p, "요오드", rule)
    iodine_ws = [w for w in ws if w.category == "iodine_excess"]
    assert any(w.severity == WarningSeverity.WARNING for w in iodine_ws)
    assert not any(w.severity == WarningSeverity.CRITICAL for w in iodine_ws)


def test_selenium_default_caution(engine):
    p = PatientProfile(diagnosis=["hashimoto"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "셀레늄", rule)
    cats = _categories(ws)
    # 기본 CAUTION 셀레늄 토xicity
    selenium_warns = [w for w in ws if w.category == "selenium_toxicity"]
    assert len(selenium_warns) >= 1
    assert any(w.severity == WarningSeverity.CAUTION for w in selenium_warns)


def test_selenium_toxicity_history_adds_warning(engine):
    p = PatientProfile(diagnosis=["selenium_toxicity_history"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "셀레늄", rule)
    sel = [w for w in ws if w.category == "selenium_toxicity"]
    assert any(w.severity == WarningSeverity.WARNING for w in sel)
    assert any(w.severity == WarningSeverity.CAUTION for w in sel)


def test_pregnancy_risk_factor(engine):
    p = PatientProfile(diagnosis=[], risk_factors=["pregnancy"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "vitamin_d", rule)
    assert "pregnancy_lactation" in _categories(ws)


def test_pediatric_age_lt_18(engine):
    p = PatientProfile(diagnosis=["hashimoto"], age=10)
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    assert "pediatric_caution" in _categories(ws)


def test_elderly_age_gte_65(engine):
    p = PatientProfile(diagnosis=["hashimoto"], age=70)
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    assert "elderly_caution" in _categories(ws)


def test_pediatric_flag_dedup_when_age_also_lt_18(engine):
    """age<18 + risk_factor=pediatric 둘 다 있어도 중복 카테고리는 하나만."""
    p = PatientProfile(age=10, risk_factors=["pediatric"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    peds = [w for w in ws if w.category == "pediatric_caution"]
    assert len(peds) == 1  # dedup_category 동작


# ──────────── medication trigger ────────────

def test_iron_levothyroxine_patient_mode(engine):
    p = PatientProfile(diagnosis=["hypothyroidism"], medications=["레보티록신"])
    rule = {"risk_tags": ["drug_interaction"], "evidence_level": "rct"}
    ws = engine.check(p, "철분", rule, is_doctor_mode=False)
    levo = [w for w in ws if w.category == "levothyroxine_interaction"]
    assert len(levo) >= 1
    # 환자용 메시지: "공복" 포함
    assert any("공복" in w.message for w in levo)


def test_iron_levothyroxine_doctor_mode(engine):
    p = PatientProfile(diagnosis=["hypothyroidism"], medications=["levothyroxine"])
    rule = {"risk_tags": ["drug_interaction"], "evidence_level": "rct"}
    ws = engine.check(p, "iron", rule, is_doctor_mode=True)
    levo = [w for w in ws if w.category == "levothyroxine_interaction"]
    assert len(levo) >= 1
    # 의사용 메시지: "흡수 저해 가능성" 포함
    assert any("흡수 저해" in w.message for w in levo)


def test_antithyroid_drug_with_iodine(engine):
    p = PatientProfile(diagnosis=["graves_disease"], medications=["methimazole"])
    rule = {"risk_tags": [], "evidence_level": "guideline"}
    ws = engine.check(p, "요오드", rule)
    assert "antithyroid_drug_interaction" in _categories(ws)


def test_antithyroid_drug_with_other_supp_is_caution(engine):
    p = PatientProfile(diagnosis=["graves_disease"], medications=["methimazole"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "셀레늄", rule)
    assert "antithyroid_drug_caution" in _categories(ws)
    # iodine 전용 분기는 발동 안 함
    assert "antithyroid_drug_interaction" not in _categories(ws)


# ──────────── lab_lt 트리거 ────────────

def test_tsh_suppressed_bone_risk(engine):
    p = PatientProfile(
        diagnosis=["thyroidectomy_postop"],
        medications=["levothyroxine"],
        lab_values={"TSH": 0.3},
    )
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "vitamin_d", rule)
    assert "tsh_suppressed_bone_risk" in _categories(ws)
    bone = [w for w in ws if w.category == "tsh_suppressed_bone_risk"][0]
    # 메시지에 lab.TSH 값 포함
    assert "0.3" in bone.message


def test_tsh_not_suppressed_no_bone_warning(engine):
    p = PatientProfile(
        diagnosis=["hashimoto"],
        medications=["levothyroxine"],
        lab_values={"TSH": 1.5},
    )
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "vitamin_d", rule)
    assert "tsh_suppressed_bone_risk" not in _categories(ws)


# ──────────── rule_none ────────────

def test_no_rule_insufficient_evidence(engine):
    p = PatientProfile(diagnosis=["hashimoto"])
    ws = engine.check(p, "unknown_supplement", None)
    assert "insufficient_evidence" in _categories(ws)


# ──────────── 카테고리별 supplement 전용 분기 ────────────

def test_ashwagandha_hyperthyroid_critical(engine):
    p = PatientProfile(diagnosis=["hyperthyroidism"])
    rule = None
    ws = engine.check(p, "ashwagandha", rule)
    # ashwagandha → herb_thyrotoxicosis CRITICAL
    herb = [w for w in ws if w.category == "herb_thyrotoxicosis"]
    assert any(w.severity == WarningSeverity.CRITICAL for w in herb)


def test_ashwagandha_pregnancy_critical(engine):
    p = PatientProfile(diagnosis=[], risk_factors=["임신"])
    rule = None
    ws = engine.check(p, "ashwagandha", rule)
    assert "pregnancy_contraindicated" in _categories(ws)


def test_biotin_lab_interference(engine):
    p = PatientProfile()
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "biotin", rule)
    assert "lab_interference" in _categories(ws)


def test_magnesium_quinolone_korean_name(engine):
    p = PatientProfile(medications=["ciprofloxacin"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "magnesium", rule)
    abx = [w for w in ws if w.category == "antibiotic_absorption"]
    assert len(abx) == 1
    assert "마그네슘" in abx[0].message


def test_zinc_levofloxacin_korean_name(engine):
    p = PatientProfile(medications=["레보플록사신"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "zinc", rule)
    abx = [w for w in ws if w.category == "antibiotic_absorption"]
    assert len(abx) == 1
    assert "아연" in abx[0].message


def test_vitamin_d_thiazide(engine):
    p = PatientProfile(medications=["hydrochlorothiazide"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "vitamin_d", rule)
    assert "hypercalcemia_risk" in _categories(ws)


def test_selenium_warfarin(engine):
    p = PatientProfile(medications=["warfarin"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    anticoag = [w for w in ws if w.category == "anticoagulant_interaction"]
    assert len(anticoag) >= 1
    assert any("셀레늄" in w.message for w in anticoag)


def test_coq10_warfarin(engine):
    p = PatientProfile(medications=["와파린"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "coq10", rule)
    anticoag = [w for w in ws if w.category == "anticoagulant_interaction"]
    assert len(anticoag) >= 1
    assert any(w.severity == WarningSeverity.WARNING for w in anticoag)


def test_multivitamin_iodine_caution(engine):
    p = PatientProfile()
    rule = None
    ws = engine.check(p, "multivitamin", rule)
    assert "iodine_caution" in _categories(ws)


# ──────────── rule_evidence_level_in ────────────

def test_rule_evidence_level_mechanistic_info(engine):
    p = PatientProfile(diagnosis=["hashimoto"])
    rule = {"risk_tags": [], "evidence_level": "mechanistic"}
    ws = engine.check(p, "selenium", rule)
    assert "limited_evidence" in _categories(ws)


# ──────────── doctor 모드 메시지 분리 ────────────

def test_iron_levo_message_differs_by_mode(engine):
    p = PatientProfile(medications=["levothyroxine"])
    rule = {"risk_tags": [], "evidence_level": "rct"}
    w_patient = engine.check(p, "iron", rule, is_doctor_mode=False)
    w_doctor = engine.check(p, "iron", rule, is_doctor_mode=True)
    p_msg = [w.message for w in w_patient if w.category == "levothyroxine_interaction"][0]
    d_msg = [w.message for w in w_doctor if w.category == "levothyroxine_interaction"][0]
    assert p_msg != d_msg


# ──────────── Phase A: ATA 2017 임신·검사값 trigger ────────────

def test_pregnancy_tsh_elevated_warning(engine):
    """임신 + TSH 4.5 mIU/L → pregnancy_tsh_elevated WARNING 발동 (ATA 2017 R26)."""
    p = PatientProfile(
        diagnosis=[],
        risk_factors=["pregnancy"],
        lab_values={"TSH": 4.5},
    )
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    tsh = [w for w in ws if w.category == "pregnancy_tsh_elevated"]
    assert len(tsh) == 1
    assert tsh[0].severity == WarningSeverity.WARNING
    # 메시지에 lab.TSH 값 치환 확인
    assert "4.5" in tsh[0].message


def test_pregnancy_tsh_normal_no_warning(engine):
    """임신 + TSH 2.0 → pregnancy_tsh_elevated 미발동 (boundary)."""
    p = PatientProfile(
        risk_factors=["pregnancy"],
        lab_values={"TSH": 2.0},
    )
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    assert "pregnancy_tsh_elevated" not in _categories(ws)


def test_pregnancy_tpoab_selenium_caution(engine):
    """임신 + selenium + TPOAb > 0 → pregnancy_tpoab_selenium CAUTION (ATA 2017 R12)."""
    p = PatientProfile(
        risk_factors=["pregnancy"],
        lab_values={"TPOAb": 250},
    )
    rule = {"risk_tags": [], "evidence_level": "rct"}
    ws = engine.check(p, "selenium", rule)
    tpo = [w for w in ws if w.category == "pregnancy_tpoab_selenium"]
    assert len(tpo) == 1
    assert tpo[0].severity == WarningSeverity.CAUTION
    # 다른 영양제에는 발동 안 함
    ws2 = engine.check(p, "iron", rule)
    assert "pregnancy_tpoab_selenium" not in _categories(ws2)


def test_pregnancy_lt4_info(engine):
    """임신 + LT4 + 임의 영양제 → pregnancy_lt4_adjustment INFO (ATA 2017 R36)."""
    p = PatientProfile(
        diagnosis=["hypothyroidism"],
        risk_factors=["pregnancy"],
        medications=["레보티록신"],
    )
    rule = {"risk_tags": ["drug_interaction"], "evidence_level": "rct"}
    ws = engine.check(p, "iron", rule)
    lt4 = [w for w in ws if w.category == "pregnancy_lt4_adjustment"]
    assert len(lt4) == 1
    assert lt4[0].severity == WarningSeverity.INFO


def test_pregnancy_iodine_excess_info(engine):
    """임신 + iodine → pregnancy_iodine_excess INFO (ATA 2017 R10)."""
    p = PatientProfile(risk_factors=["임신"])
    rule = {"risk_tags": [], "evidence_level": "guideline"}
    ws = engine.check(p, "요오드", rule)
    info = [w for w in ws if w.category == "pregnancy_iodine_excess"]
    assert len(info) == 1
    assert info[0].severity == WarningSeverity.INFO


def test_lactation_iodine_excess_info(engine):
    """수유 + iodine → lactation_iodine_excess INFO (ATA 2017 R84)."""
    p = PatientProfile(risk_factors=["수유"])
    rule = {"risk_tags": [], "evidence_level": "guideline"}
    ws = engine.check(p, "iodine", rule)
    info = [w for w in ws if w.category == "lactation_iodine_excess"]
    assert len(info) == 1
    assert info[0].severity == WarningSeverity.INFO


# ──────────── Phase E: PDF cross-link 보강 ────────────

def test_pregnancy_lt4_doctor_msg_includes_4hr_interval(engine):
    """Phase E (a): pregnancy_lt4 의사 메시지에 '4시간 간격' 명시 확인."""
    p = PatientProfile(
        diagnosis=["hypothyroidism"],
        risk_factors=["pregnancy"],
        medications=["레보티록신"],
    )
    rule = {"risk_tags": ["drug_interaction"], "evidence_level": "rct"}
    ws = engine.check(p, "iron", rule, is_doctor_mode=True)
    lt4 = [w for w in ws if w.category == "pregnancy_lt4_adjustment"]
    assert len(lt4) == 1
    assert "4시간 간격" in lt4[0].message
