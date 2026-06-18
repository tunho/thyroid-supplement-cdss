"""
domain.thyroid.decision — Rule/Evidence 기반 의사결정 엔진

DecisionEngine.evaluate() 는 환자 프로파일, 의사 프로파일(optional),
supplement rule, safety warnings, evidence records를 종합하여
구조화된 DecisionResult를 반환합니다.

핵심 원칙:
  - LLM이 decision을 직접 결정하지 않는다.
  - 모든 판단은 rule table + evidence + safety check 조합.
  - 근거 부족 시 보수적으로 insufficient_evidence를 반환.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from domain.thyroid.dose_safety import derive_lab_conditions as _derive_lab_conditions
from domain.thyroid.schemas import (
    Decision,
    DecisionResult,
    EvidenceRecord,
    PatientProfile,
    PhysicianProfile,
    SafetyWarning,
    WarningSeverity,
)


class DecisionEngine:
    """Rule-based thyroid supplement decision engine."""

    def evaluate(
        self,
        patient: PatientProfile,
        supplement_name: str,
        rule: Dict[str, Any] | None,
        safety_warnings: List[SafetyWarning],
        evidence_records: List[EvidenceRecord] | None = None,
        physician: PhysicianProfile | None = None,
        force_conditional: bool = False,
    ) -> DecisionResult:
        """
        판단 흐름:
          1. rule 미등록 → insufficient_evidence
          2. contraindication 해당 → contraindicated
          3. CRITICAL safety warning 존재 → avoid 또는 contraindicated
          4. avoid_conditions 해당 → avoid
          5. applicable_conditions 해당 + 근거 충분 → recommend 또는 conditional_consider
          6. applicable_conditions 해당 + 근거 부족 → conditional_consider
          7. 그 외 → insufficient_evidence
        """
        applied_rules: List[str] = []
        recommendations: List[str] = []

        # ── Step 1: Rule 미등록 ──
        if rule is None:
            result = DecisionResult(
                decision=Decision.INSUFFICIENT_EVIDENCE,
                supplement_name=supplement_name,
                confidence="low",
                safety_warnings=safety_warnings,
                evidence_records=evidence_records or [],
                rationale=f"{supplement_name}에 대한 갑상선 질환 관련 rule이 등록되어 있지 않습니다.",
                recommendations=["전문의 상담 후 판단하시기 바랍니다."],
                applied_rules=["no_rule_registered"],
            )
            return self._apply_force_conditional(result, force_conditional)

        dx_set = _normalize_set(patient.diagnosis)
        # STEP1 Fix A(#13): lab 값에서 *현재 상태* 조건 파생(예: calcium→hypercalcemia)을
        #   매칭 집합에 union → avoid/contraindication 발화. past_history는 §15.1대로 미반영.
        dx_set |= _derive_lab_conditions(patient.lab_values or {})
        med_set = _normalize_set(patient.medications)

        # ── Step 2: Contraindication 확인 ──
        contraindications = set(_normalize_list(rule.get("contraindications", [])))
        matched_contra = dx_set & contraindications
        if matched_contra:
            applied_rules.append("contraindication_match")
            rule_monitoring = rule.get("monitoring_parameters", [])
            rule_counseling = rule.get("counseling_points", [])
            result = DecisionResult(
                decision=Decision.CONTRAINDICATED,
                supplement_name=supplement_name,
                confidence="high",
                safety_warnings=safety_warnings,
                evidence_records=evidence_records or [],
                rationale=f"금기 사항 해당: {', '.join(matched_contra)}",
                recommendations=["이 영양제는 현재 상태에서 금기입니다. 복용하지 마시기 바랍니다."],
                applied_rules=applied_rules,
                monitoring_parameters=rule_monitoring,
                counseling_points=rule_counseling,
            )
            return self._apply_force_conditional(result, force_conditional)

        # ── Step 3: CRITICAL safety warning → avoid ──
        critical_warnings = [w for w in safety_warnings if w.severity == WarningSeverity.CRITICAL]
        if critical_warnings:
            applied_rules.append("critical_safety_warning")
            rationale = "; ".join(w.message for w in critical_warnings[:2])
            rule_monitoring = rule.get("monitoring_parameters", [])
            rule_counseling = rule.get("counseling_points", [])
            result = DecisionResult(
                decision=Decision.AVOID,
                supplement_name=supplement_name,
                confidence="high",
                safety_warnings=safety_warnings,
                evidence_records=evidence_records or [],
                rationale=f"중대 안전 경고: {rationale}",
                recommendations=[w.recommended_action for w in critical_warnings if w.recommended_action],
                applied_rules=applied_rules,
                monitoring_parameters=rule_monitoring,
                counseling_points=rule_counseling,
            )
            return self._apply_force_conditional(result, force_conditional)

        # ── Step 4: Avoid conditions 확인 ──
        avoid_conditions = set(_normalize_list(rule.get("avoid_conditions", [])))
        matched_avoid = dx_set & avoid_conditions
        if matched_avoid:
            applied_rules.append("avoid_condition_match")
            rule_monitoring = rule.get("monitoring_parameters", [])
            rule_counseling = rule.get("counseling_points", [])
            result = DecisionResult(
                decision=Decision.AVOID,
                supplement_name=supplement_name,
                confidence="medium",
                safety_warnings=safety_warnings,
                evidence_records=evidence_records or [],
                rationale=f"회피 권고 상태 해당: {', '.join(matched_avoid)}",
                recommendations=[
                    "현재 진단 상태에서 이 영양제는 권장되지 않습니다.",
                    "대안 영양제 또는 전문의 상담을 고려하시기 바랍니다.",
                ],
                applied_rules=applied_rules,
                monitoring_parameters=rule_monitoring,
                counseling_points=rule_counseling,
            )
            return self._apply_force_conditional(result, force_conditional)

        # ── Step 5/6: Applicable conditions ──
        applicable = set(_normalize_list(rule.get("applicable_conditions", [])))
        matched_applicable = dx_set & applicable
        evidence_level = rule.get("evidence_level", "insufficient")
        strong_evidence = evidence_level in ("guideline", "rct", "meta_analysis", "clinical")

        # WARNING-level warnings 유무에 따라 conditional
        warning_level_warnings = [
            w for w in safety_warnings
            if w.severity in (WarningSeverity.WARNING, WarningSeverity.CRITICAL)
        ]

        if matched_applicable:
            applied_rules.append("applicable_condition_match")
            benefits = rule.get("possible_benefits", [])
            recommendations = list(benefits[:2])
            rule_counseling = rule.get("counseling_points", [])
            rule_monitoring = rule.get("monitoring_parameters", [])

            if strong_evidence and not warning_level_warnings:
                applied_rules.append("strong_evidence")
                raw_decision = Decision.RECOMMEND
                decision, confidence = _apply_physician_adjustment(
                    raw_decision,
                    "high" if evidence_level == "guideline" else "medium",
                    physician,
                    evidence_level,
                )
                result = DecisionResult(
                    decision=decision,
                    supplement_name=supplement_name,
                    confidence=confidence,
                    safety_warnings=safety_warnings,
                    evidence_records=evidence_records or [],
                    rationale=f"해당 진단({', '.join(matched_applicable)})에 대한 근거 수준: {evidence_level}",
                    recommendations=recommendations + [
                        "용량 및 복용 기간은 전문의 지시에 따라 결정하시기 바랍니다."
                    ],
                    counseling_points=rule_counseling,
                    monitoring_parameters=rule_monitoring,
                    pre_physician_decision=raw_decision if decision != raw_decision else None,
                    applied_rules=applied_rules,
                )
                return self._apply_force_conditional(result, force_conditional)
            else:
                applied_rules.append("conditional_evidence" if not strong_evidence else "warning_present")
                notes = rule.get("notes", "")
                raw_decision = Decision.CONDITIONAL_CONSIDER
                decision, confidence = _apply_physician_adjustment(
                    raw_decision,
                    "medium" if strong_evidence else "low",
                    physician,
                    evidence_level,
                )
                result = DecisionResult(
                    decision=decision,
                    supplement_name=supplement_name,
                    confidence=confidence,
                    safety_warnings=safety_warnings,
                    evidence_records=evidence_records or [],
                    rationale=(
                        f"해당 진단({', '.join(matched_applicable)})에 대해 조건부로 고려할 수 있습니다. "
                        f"근거 수준: {evidence_level}. {notes[:300] if notes else ''}"
                    ),
                    recommendations=recommendations + [
                        "복용 전 전문의 상담을 권고합니다.",
                        "주기적인 갑상선 기능 검사가 필요합니다.",
                    ],
                    counseling_points=rule_counseling,
                    monitoring_parameters=rule_monitoring,
                    pre_physician_decision=raw_decision if decision != raw_decision else None,
                    applied_rules=applied_rules,
                )
                return self._apply_force_conditional(result, force_conditional)

        # ── Step 7: 조건 불일치 — 근거 부족 ──
        applied_rules.append("no_condition_match")
        result = DecisionResult(
            decision=Decision.INSUFFICIENT_EVIDENCE,
            supplement_name=supplement_name,
            confidence="low",
            safety_warnings=safety_warnings,
            evidence_records=evidence_records or [],
            rationale=(
                f"현재 진단 정보({', '.join(dx_set) if dx_set else '미입력'})와 "
                f"{supplement_name} rule의 적용 조건이 일치하지 않아 충분한 판단 근거가 없습니다."
            ),
            recommendations=[
                "추가 검사 결과나 진단 정보를 입력하시면 더 정확한 판단이 가능합니다.",
                "전문의 상담을 권고합니다.",
            ],
            applied_rules=applied_rules,
        )
        return self._apply_force_conditional(result, force_conditional)

    def _apply_force_conditional(
        self,
        result: DecisionResult,
        force_conditional: bool,
    ) -> DecisionResult:
        """모든 결정 반환의 단일 finalization funnel.
        (1) force_conditional=True이고 RECOMMEND이면 CONDITIONAL_CONSIDER로 강제 변경,
        (2) 이어서 LT4 상호작용 taxonomy(#4.1)를 적용."""
        if force_conditional and result.decision == Decision.RECOMMEND:
            result = result.model_copy(
                update={
                    "decision": Decision.CONDITIONAL_CONSIDER,
                    "rationale": f"[WARNING 감지] {result.rationale}",
                }
            )
        return self._apply_interaction_taxonomy(result)

    def _apply_interaction_taxonomy(self, result: DecisionResult) -> DecisionResult:
        """#4.1 RECOMMEND/CONDITIONAL_CONSIDER + levothyroxine_interaction 경고가 있으면
        MANAGE_INTERACTION으로 정밀화 — 성분 자체 문제가 아니라 LT4 병용 관리(복용 분리·흡수)가
        핵심인 케이스. AVOID/CONTRAINDICATED/INSUFFICIENT는 절대 덮지 않음(no-op).

        트리거: safety.py 가 LT4 복용 + 흡수저해 성분일 때만 생성하는
        `levothyroxine_interaction` 경고(별도 LT4 탐지 불필요)."""
        if result.decision not in (Decision.RECOMMEND, Decision.CONDITIONAL_CONSIDER):
            return result
        has_lt4_interaction = any(
            w.category == "levothyroxine_interaction" for w in result.safety_warnings
        )
        if not has_lt4_interaction:
            return result
        return result.model_copy(update={"decision": Decision.MANAGE_INTERACTION})


def _apply_physician_adjustment(
    base_decision: Decision,
    base_confidence: str,
    physician: PhysicianProfile | None,
    evidence_level: str,
) -> tuple[Decision, str]:
    """
    §14.3 의사 성향(risk_tolerance, supplement_attitude)에 따른 결정/신뢰도 조정.

    ⚠️  자동 decision 변경 제한 (§14.3):
      - CONTRAINDICATED 또는 AVOID → 의사 성향으로 절대 완화하지 않는다.
      - RECOMMEND ↔ CONDITIONAL_CONSIDER 조정은 안전 경고 없고 근거 충분 시에만 허용.
      - 성향은 응답 톤, 근거 제시 방식, confidence 수준 보정에만 사용한다.
    """
    if physician is None:
        return base_decision, base_confidence

    tol = physician.risk_tolerance   # aggressive / moderate / conservative

    # §14.3: CONTRAINDICATED/AVOID 완화 금지 (guard)
    if base_decision in (Decision.CONTRAINDICATED, Decision.AVOID):
        return base_decision, base_confidence

    # 1. Conservative → RECOMMEND 강등 (안전 경고 없는 경우만 — 호출부에서 safety_warnings 기반으로 처리됨)
    if tol == "conservative" and base_decision == Decision.RECOMMEND:
        return Decision.CONDITIONAL_CONSIDER, "medium"

    # 2. Aggressive + 중간 근거 → confidence 상향 (decision 변경 없음)
    if tol == "aggressive" and evidence_level in ("observational", "rct"):
        if base_confidence == "low":
            base_confidence = "medium"

    return base_decision, base_confidence


# ── Helpers ──────────────────────────────────────────────

def _normalize_set(items: list) -> set:
    return {str(x).strip().lower().replace(" ", "_").replace("-", "_") for x in items if str(x).strip()}


def _normalize_list(items: list) -> list:
    return [str(x).strip().lower().replace(" ", "_").replace("-", "_") for x in items if str(x).strip()]
