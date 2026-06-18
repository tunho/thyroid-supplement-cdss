"""
domain.thyroid.profile — 환자/의사 프로파일 빌더

Raw request 데이터 → PatientProfile / PhysicianProfile 변환.
한국어 진단명은 canonical English key로 정규화합니다.
"""

from __future__ import annotations

import re
from typing import List, Optional

from domain.thyroid.schemas import PatientProfile, PhysicianProfile


# ──────────────────────────────────────────────────────────
# 한국어 진단명 → canonical key 매핑
# ──────────────────────────────────────────────────────────

_DIAGNOSIS_ALIASES = {
    # 그레이브스
    "그레이브스병": "graves_disease",
    "그레이브스": "graves_disease",
    "그레이브스_병": "graves_disease",
    "그레이브스질환": "graves_disease",
    "그레이브스 병": "graves_disease",
    "graves": "graves_disease",
    # 그레이브스 안병증
    "그레이브스 안병증": "graves_orbitopathy",
    "그레이브스안병증": "graves_orbitopathy",
    "그레이브스_안병증": "graves_orbitopathy",
    "갑상선 안병증": "graves_orbitopathy",
    "갑상선안병증": "graves_orbitopathy",
    "graves_ophthalmopathy": "graves_orbitopathy",
    # 갑상선기능항진증
    "갑상선기능항진증": "hyperthyroidism",
    "갑상선기능_항진증": "hyperthyroidism",
    "갑상선 기능 항진증": "hyperthyroidism",
    "갑상선항진증": "hyperthyroidism",
    "갑상선 항진": "hyperthyroidism",
    # 갑상선중독증 (thyrotoxicosis) — 갑상선호르몬 과잉 상태. 보수적으로 항진증과 동일 취급
    # (요오드 등 안전 판정에서 hyperthyroidism 경로). 임신성 일과성은 아래 별도 canonical 유지.
    "갑상선중독증": "hyperthyroidism",
    "갑상선 중독증": "hyperthyroidism",
    "갑상선중독": "hyperthyroidism",
    "thyrotoxicosis": "hyperthyroidism",
    # 갑상선기능저하증
    "갑상선기능저하증": "hypothyroidism",
    "갑상선기능_저하증": "hypothyroidism",
    "갑상선 기능 저하증": "hypothyroidism",
    "갑상선저하증": "hypothyroidism",
    "갑상선 저하": "hypothyroidism",
    # 하시모토
    "하시모토": "hashimoto",
    "하시모토 갑상선염": "hashimoto",
    "하시모토갑상선염": "hashimoto",
    "하시모토_갑상선염": "hashimoto",
    "하시모토병": "hashimoto",
    "자가면역 갑상선염": "autoimmune_thyroiditis",
    "자가면역갑상선염": "autoimmune_thyroiditis",
    # 임신/수유 (applicable_conditions 의 pregnancy/lactation 매칭)
    "임신": "pregnancy",
    "임신부": "pregnancy",
    "임신 중": "pregnancy",
    "임신중": "pregnancy",
    "임신부 상태": "pregnancy",
    "pregnant": "pregnancy",
    "pregnancy": "pregnancy",
    "수유": "lactation",
    "수유부": "lactation",
    "수유 중": "lactation",
    "수유중": "lactation",
    "모유수유": "lactation",
    "모유 수유": "lactation",
    "breastfeeding": "lactation",
    "lactation": "lactation",
    # 골다공증 (calcium/vitamin_d applicable_conditions 매칭)
    "골다공증": "osteoporosis",
    "골다공증증": "osteoporosis",
    "osteoporosis": "osteoporosis",
    "골감소증": "osteopenia",
    # 갑상선암
    "갑상선암": "thyroid_cancer",
    "갑상선 암": "thyroid_cancer",
    "갑상선유두암": "thyroid_cancer",
    "갑상선 유두암": "thyroid_cancer",
    "갑상선암 수술후": "thyroid_cancer_postop",
    "갑상선암 수술 후": "thyroid_cancer_postop",
    "갑상선암 수술후 상태": "thyroid_cancer_postop",
    "thyroid_cancer_postop": "thyroid_cancer_postop",
    # 갑상선 수술 후
    "갑상선 수술 후": "thyroidectomy_postop",
    "갑상선절제술": "thyroidectomy_postop",
    "갑상선 절제술": "thyroidectomy_postop",
    "갑상선전절제": "thyroidectomy_postop",
    # 기타
    "갑상선종": "goiter",
    "갑상선 결절": "thyroid_nodule",
    "갑상선결절": "thyroid_nodule",
    # 자율기능성 결절(AFTN) — iodine avoid (Jod-Basedow)
    "자율기능성갑상선결절": "autonomous_thyroid_nodule",
    "자율기능성 갑상선결절": "autonomous_thyroid_nodule",
    "자율결절": "autonomous_thyroid_nodule",
    # 아임상(무증상) 갑상선기능항진증
    "무증상갑상선기능항진증": "subclinical_hyperthyroidism",
    "무증상 갑상선기능항진증": "subclinical_hyperthyroidism",
    "아임상 갑상선기능항진증": "subclinical_hyperthyroidism",
    "아임상갑상선기능항진증": "subclinical_hyperthyroidism",
    "아임상 갑상선항진": "subclinical_hyperthyroidism",
    "철결핍": "iron_deficiency",
    "철분결핍": "iron_deficiency",
    "철분 결핍": "iron_deficiency",
    "빈혈": "iron_deficiency_anemia",
    "철결핍빈혈": "iron_deficiency_anemia",
    "철결핍성빈혈": "iron_deficiency_anemia",
    "철분결핍성빈혈": "iron_deficiency_anemia",
    "철분빈혈": "iron_deficiency_anemia",
    # 철 과부하 — 철분제 회피 조건 (iron avoid_conditions=hemochromatosis/iron_overload)
    "혈색소증": "hemochromatosis",
    "유전성 혈색소증": "hemochromatosis",
    "유전성혈색소증": "hemochromatosis",
    "철과부하": "iron_overload",
    "철 과부하": "iron_overload",
    "철과다": "iron_overload",
    "철 과다": "iron_overload",
    "비타민d 결핍": "vitamin_d_deficiency",
    "비타민d결핍": "vitamin_d_deficiency",
    # 고칼슘혈증·원발성 부갑상선항진증 — vitamin_d 회피 조건 (NIH-ODS; 진단명 진술 시 매칭)
    "고칼슘혈증": "hypercalcemia",
    "고칼슘 혈증": "hypercalcemia",
    "원발성 부갑상선항진증": "primary_hyperparathyroidism",
    "원발성부갑상선항진증": "primary_hyperparathyroidism",
    "부갑상선항진증": "primary_hyperparathyroidism",
    "부갑상선 항진증": "primary_hyperparathyroidism",
    "primary hyperparathyroidism": "primary_hyperparathyroidism",
    "phpt": "primary_hyperparathyroidism",
    # 산후 갑상선염 (ATA 2017 R85~R91)
    "산후 갑상선염": "postpartum_thyroiditis",
    "산후갑상선염": "postpartum_thyroiditis",
    "산후 갑상샘염": "postpartum_thyroiditis",
    "postpartum_thyroiditis": "postpartum_thyroiditis",
    # 아임상 갑상선기능저하 — 일반
    "아임상 갑상선기능저하": "subclinical_hypothyroidism",
    "아임상 갑상선기능저하증": "subclinical_hypothyroidism",
    "아임상 갑상선저하": "subclinical_hypothyroidism",
    "무증상 갑상선저하": "subclinical_hypothyroidism",
    "subclinical_hypothyroidism": "subclinical_hypothyroidism",
    # 임신 아임상 갑상선기능저하 (ATA 2017 R29)
    "임신 아임상 갑상선기능저하": "subclinical_hypothyroidism_pregnancy",
    "임신 아임상 갑상선저하": "subclinical_hypothyroidism_pregnancy",
    "임신중 아임상 갑상선저하": "subclinical_hypothyroidism_pregnancy",
    "subclinical_hypothyroidism_pregnancy": "subclinical_hypothyroidism_pregnancy",
    # 단독성 저티록신혈증 (ATA 2017 R30 / Q35)
    "단독성 저티록신혈증": "isolated_hypothyroxinemia",
    "단독 저티록신혈증": "isolated_hypothyroxinemia",
    "isolated_hypothyroxinemia": "isolated_hypothyroxinemia",
    # 임신성 일과성 갑상선중독증 (ATA 2017 Q51 / Q52 / R42)
    "임신성 일과성 갑상선중독증": "gestational_transient_thyrotoxicosis",
    "임신성 갑상선중독증": "gestational_transient_thyrotoxicosis",
    "임신 갑상선중독증": "gestational_transient_thyrotoxicosis",
    "gestational_thyrotoxicosis": "gestational_transient_thyrotoxicosis",
    "gestational_transient_thyrotoxicosis": "gestational_transient_thyrotoxicosis",
    # TPOAb 양성 (lab 상태 — 진단 아니지만 환자 입력 시 진단란에 자주 기입)
    # ATA 2017 R11/R12/R28/R92. 정확한 매칭은 PatientProfile.lab_values.TPOAb 에서 처리됨.
    "갑상선 자가항체 양성": "tpoab_positive",
    "tpo 항체 양성": "tpoab_positive",
    "tpoab 양성": "tpoab_positive",
    "tpo_ab_positive": "tpoab_positive",
    "tpoab_positive": "tpoab_positive",
}


def normalize_diagnosis(dx: str) -> str:
    """한국어/영어 진단명을 canonical English key로 변환."""
    key = dx.strip().lower().replace("-", "_")
    # 공백 포함 매칭 (예: "그레이브스 안병증") 우선
    if key in _DIAGNOSIS_ALIASES:
        return _DIAGNOSIS_ALIASES[key]
    # 공백→언더스코어 변환 후 매칭
    key_underscore = key.replace(" ", "_")
    if key_underscore in _DIAGNOSIS_ALIASES:
        return _DIAGNOSIS_ALIASES[key_underscore]
    # 공백 제거 후 매칭 (예: "그레이브스안병증")
    key_no_space = key.replace(" ", "")
    if key_no_space in _DIAGNOSIS_ALIASES:
        return _DIAGNOSIS_ALIASES[key_no_space]
    # 매칭 안 되면 언더스코어 정규화만 적용
    return key_underscore


def _split_csv(text: Optional[str | List[str]]) -> List[str]:
    """콤마·슬래시·공백 구분 문자열을 리스트로 변환"""
    if text is None:
        return []
    if isinstance(text, list):
        return [str(x).strip() for x in text if str(x).strip()]
    if not text or not text.strip():
        return []
    parts = re.split(r"[,/;+]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _normalize_diagnosis_list(items: List[str]) -> List[str]:
    """진단명 리스트의 각 항목을 canonical key로 정규화."""
    return [normalize_diagnosis(dx) for dx in items if dx.strip()]


def build_patient_profile(
    *,
    diagnosis: str | List[str] = "",
    lab_values: dict | None = None,
    symptoms: str | List[str] = "",
    medications: str | List[str] = "",
    current_supplements: str | List[str] = "",
    dietary_habits: str | None = None,
    risk_factors: str | List[str] = "",
    age: int | None = None,
    sex: str | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
    past_history: str | List[str] = "",
    surgical_history: str | List[str] = "",
) -> PatientProfile:
    """Flexible builder: 문자열/리스트 모두 수용, 진단명은 canonical key로 정규화."""
    return PatientProfile(
        diagnosis=_normalize_diagnosis_list(_split_csv(diagnosis)),
        lab_values=lab_values or {},
        symptoms=_split_csv(symptoms),
        medications=_split_csv(medications),
        current_supplements=_split_csv(current_supplements),
        dietary_habits=dietary_habits,
        risk_factors=_split_csv(risk_factors),
        age=age,
        sex=sex,
        height_cm=height_cm,
        weight_kg=weight_kg,
        past_history=_split_csv(past_history),
        surgical_history=_split_csv(surgical_history),
    )


def build_physician_profile(
    *,
    specialty: str | None = None,
    years_experience: int | None = None,
    supplement_attitude: str = "neutral",
    risk_tolerance: str = "moderate",
    guideline_preference: str | None = None,
) -> PhysicianProfile:
    return PhysicianProfile(
        specialty=specialty,
        years_experience=years_experience,
        supplement_attitude=supplement_attitude,
        risk_tolerance=risk_tolerance,
        guideline_preference=guideline_preference,
    )
