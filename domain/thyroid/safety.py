"""
domain.thyroid.safety — 갑상선 supplement 안전성 엔진

v2 (Phase 0): data-driven 마이그레이션.
모든 분기는 data/safety_rules.json 에서 로드. trigger 매칭은
domain.thyroid.safety_rules_engine 에 위임.

기존 시그니처 보존:
    SafetyEngine().check(patient, supplement_name, rule, is_doctor_mode=False)
        → List[SafetyWarning]

기존 함수 보존:
    _normalize_set      — 다른 모듈이 import 할 수 있어 유지
    _normalize_med_set  — 별칭 매핑 + MFDS DB fallback
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from domain.thyroid.schemas import (
    PatientProfile,
    SafetyWarning,
    WarningSeverity,
)
from domain.thyroid.rules import normalize_supplement_name
from domain.thyroid.safety_rules_engine import evaluate_safety_rules, get_rules


def _normalize_med_set(med_list: list) -> set:
    """의약품명 정규화: 하드코딩 별칭 + DB 조회 fallback."""
    result: set = set()
    try:
        from domain.mfds.db import normalize_drug_name as _db_norm
    except Exception:
        _db_norm = None

    for item in med_list:
        raw = str(item).strip()
        normalized = raw.lower().replace(" ", "_").replace("-", "_")
        result.add(normalized)
        if _db_norm:
            try:
                db_result = _db_norm(raw)
                if db_result:
                    result.add(db_result.lower().replace(" ", "_").replace("-", "_"))
            except Exception:
                pass
    return result


def _normalize_set(items: list) -> Set[str]:
    """소문자 정규화 + 공백/하이픈 → 언더스코어."""
    result: Set[str] = set()
    for item in items:
        normalized = str(item).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized:
            result.add(normalized)
    return result


class SafetyEngine:
    """Rule-based safety checker. LLM 호출 없이 작동.

    명세 rule_construction_v5 §7 — safety_rules.json 의 규칙을 evaluate_safety_rules
    에 위임. SafetyEngine 자체는 입출력 변환만 담당.
    """

    def check(
        self,
        patient: PatientProfile,
        supplement_name: str,
        rule: Dict[str, Any] | None,
        is_doctor_mode: bool = False,
    ) -> List[SafetyWarning]:
        """
        is_doctor_mode=True (의사 경로): 미네랄별 흡수 저해 전문 표현 (§13.2).
        is_doctor_mode=False (환자 경로, 기본값): 공복·식사 간격·상담 중심 (§13.1).
        """
        canonical = normalize_supplement_name(supplement_name) or ""
        dx_set = _normalize_set(patient.diagnosis)
        med_set = _normalize_med_set(patient.medications)
        risk_set = _normalize_set(patient.risk_factors)

        rule_dicts = evaluate_safety_rules(
            rules=get_rules(),
            supplement_name=supplement_name,
            canonical=canonical,
            dx_set=dx_set,
            risk_set=risk_set,
            med_set=med_set,
            rule=rule,
            age=patient.age,
            lab_values=patient.lab_values or {},
            is_doctor_mode=is_doctor_mode,
            existing_categories=set(),
        )

        warnings: List[SafetyWarning] = []
        for r in rule_dicts:
            warnings.append(SafetyWarning(
                category=r["category"],
                message=r["message"],
                severity=WarningSeverity(r["severity"].lower()),
                recommended_action=r["recommended_action"],
            ))

        # ⑩ MFDS 허용 상한치 경고 (별도 외부 함수, 기존 보존)
        from domain.thyroid.mfds_service import get_mfds_safety_warnings
        warnings.extend(get_mfds_safety_warnings(supplement_name))

        return warnings
