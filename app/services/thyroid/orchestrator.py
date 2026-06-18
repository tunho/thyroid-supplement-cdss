"""
app.services.thyroid.orchestrator — 갑상선 supplement 의사결정 파이프라인

공개 진입점:
  run_patient_thyroid_pipeline()  — 환자 전용: PubMed 없음, rule 없으면 즉시 상담 유도
  run_doctor_thyroid_pipeline()   — 의사 전용: PubMed 선택, PhysicianProfile 반영
  run_thyroid_decision_pipeline() — 하위 호환 alias (레거시 chat 경로 등)

내부 코어:
  _run_core_pipeline()            — 직접 호출 X
"""

from typing import List, Optional, Any, Dict
from domain.thyroid.schemas import PatientProfile, PhysicianProfile, DecisionResult, WarningSeverity, Decision
from domain.thyroid.rules import get_supplement_key, get_supplement_rule, is_verified_supplement
from domain.thyroid.safety import SafetyEngine
from domain.thyroid.decision import DecisionEngine
from domain.consultation.pubmed import get_realtime_pubmed_evidence
from domain.consultation.pubmed.doctor_query_builder import (
    get_doctor_pubmed_articles,
    is_levothyroxine_medication,
    is_supplement_registered,
)
from domain.thyroid.schemas import EvidenceRecord, EvidenceLevel
from domain.thyroid.profile import build_patient_profile, build_physician_profile
from domain.thyroid.scope_config import is_deferred_condition

_safety_engine = SafetyEngine()
_decision_engine = DecisionEngine()


def _fetch_pubmed_for_doctor(
    supplement_name: str,
    conditions: str | List[str],
    medications: str | List[str],
    focus: str,
    thyroid_context: str,
    message: str,
    age: int | None,
    sex: str | None,
    enhanced_search: bool = False,
    focus_explicit: bool = False,
    intent: str = "safety",
) -> List[EvidenceRecord]:
    """의사 경로 PubMed 조회 공용 helper. 실패 시 빈 리스트 반환.

    A5 interaction 분기 규칙:
      1. interaction + 레보티록신 → levo+absorption 전용 쿼리 (기존)
      2. interaction + 레보 없음 + focus_explicit=True → supp+absorption+domain (A3)
      3. interaction + 레보 없음 + focus_explicit=False → effective_focus=general (realtime)

    pre_slots: general 경로에서 API 추론한 intent·thyroid_context를 realtime에 전달.
    """
    cond_str = ", ".join(conditions) if isinstance(conditions, list) else (conditions or "")
    meds_str = ", ".join(medications) if isinstance(medications, list) else (medications or "")

    # A5: interaction + 레보 없음 + 자동 추론 → general 강등
    effective_focus = focus
    if focus == "interaction" and not is_levothyroxine_medication(meds_str) and not focus_explicit:
        effective_focus = "general"

    articles: List[Dict] = []
    try:
        canonical = get_supplement_key(supplement_name) or supplement_name
        if effective_focus != "general" or is_supplement_registered(canonical):
            articles = get_doctor_pubmed_articles(
                canonical=canonical,
                medications=meds_str,
                focus=effective_focus,
                thyroid_context=thyroid_context,
                supplement_display=supplement_name,
                enhanced_search=enhanced_search,
            ) or []
        else:
            # canonical이 _SUPPLEMENT_TERMS에 없는 완전 미등록 성분
            articles = get_realtime_pubmed_evidence(
                user_input=f"{supplement_name} {message}".strip(),
                conditions=cond_str,
                medications=meds_str,
                age=age,
                sex=sex,
                pre_slots={"intent": intent, "thyroid_context": thyroid_context},
            ) or []
    except Exception as e:
        print(f"[orchestrator] PubMed 조회 오류: {e}")

    records: List[EvidenceRecord] = []
    for a in articles:
        lvl_val = a.get("evidence_level", "insufficient")
        try:
            e_level = EvidenceLevel(lvl_val)
        except ValueError:
            e_level = EvidenceLevel.INSUFFICIENT
        records.append(EvidenceRecord(
            pmid=a.get("pmid"),
            title=a.get("title") or "",
            abstract=a.get("abstract"),
            year=a.get("year"),
            evidence_level=e_level,
            journal=a.get("source_type"),
        ))
    return records


# ══════════════════════════════════════════════════════════
# 내부 코어 — 직접 호출하지 말 것
# ══════════════════════════════════════════════════════════

def _run_core_pipeline(
    supplement_name: str,
    message: str = "",
    conditions: str | List[str] = "",
    medications: str | List[str] = "",
    current_supplements: str | List[str] = "",
    risk_factors: str | List[str] = "",
    symptoms: str | List[str] = "",
    dietary_habits: str | None = None,
    lab_values: dict = None,
    age: int = None,
    sex: str = None,
    height: float = None,
    weight: float = None,
    past_history: str | List[str] = "",
    surgical_history: str | List[str] = "",
    intent: str = "safety",
    thyroid_context: str = "general",
    focus: str = "general",
    # --- 경로 제어 파라미터 ---
    use_pubmed: bool = False,               # True일 때만 4단계 PubMed 실행
    allow_pubmed_fallback: bool = True,     # rule 없을 때 PubMed fallback 허용 (False=결정론: 외부호출 0)
    is_doctor_mode: bool = False,           # §13.2 의사/환자 메시지 분리 (allow_pubmed_fallback과 decouple)
    enhanced_search: bool = False,          # True: retmax 증가 + LLM 재랭킹 (의사 고급 검색)
    focus_explicit: bool = False,           # True: 프론트/API에서 focus 명시 (A5 interaction 분기)
    physician_profile: dict | None = None,
) -> tuple[PatientProfile, Optional[PhysicianProfile], DecisionResult]:

    # 1. Profile
    patient = build_patient_profile(
        diagnosis=conditions,
        medications=medications,
        current_supplements=current_supplements,
        risk_factors=risk_factors,
        symptoms=symptoms,
        dietary_habits=dietary_habits,
        lab_values=lab_values,
        age=age,
        sex=sex,
        height_cm=height,
        weight_kg=weight,
        past_history=past_history,
        surgical_history=surgical_history,
    )
    physician = build_physician_profile(**(physician_profile or {})) if physician_profile else None

    # 2. Rule lookup
    rule = get_supplement_rule(supplement_name)

    # 2b. Rule 없음 분기
    if rule is None:
        # 환자 경로: PubMed 없이 즉시 INSUFFICIENT_EVIDENCE + 전문의 상담 유도
        if not allow_pubmed_fallback:
            safety_warnings = _safety_engine.check(patient, supplement_name, None)
            result = DecisionResult(
                decision=Decision.INSUFFICIENT_EVIDENCE,
                supplement_name=supplement_name,
                confidence="low",
                safety_warnings=safety_warnings,
                evidence_records=[],
                rationale=(
                    f"'{supplement_name}'에 대한 갑상선 관련 규칙이 등록되어 있지 않습니다. "
                    "정확한 판단을 위해 전문의 상담을 권고합니다."
                ),
                recommendations=["갑상선 전문의와 상담 후 복용 여부를 결정하세요."],
                applied_rules=["no_rule_registered"],
            )
            return patient, physician, result

        # 의사 경로: 기존 PubMed fallback 유지
        evidence_records: List[EvidenceRecord] = []
        articles: List[Dict] = []
        try:
            cond_str = ", ".join(conditions) if isinstance(conditions, list) else (conditions or "")
            meds_str = ", ".join(medications) if isinstance(medications, list) else (medications or "")
            articles = get_realtime_pubmed_evidence(
                user_input=f"{supplement_name} thyroid",
                conditions=cond_str,
                medications=meds_str,
                age=age,
                sex=sex,
            ) or []
            for a in articles:
                lvl_val = a.get("evidence_level", "insufficient")
                try:
                    e_level = EvidenceLevel(lvl_val)
                except ValueError:
                    e_level = EvidenceLevel.INSUFFICIENT
                evidence_records.append(EvidenceRecord(
                    pmid=a.get("pmid"),
                    title=a.get("title") or "",
                    abstract=a.get("abstract"),
                    year=a.get("year"),
                    evidence_level=e_level,
                    journal=a.get("source_type"),
                ))
        except Exception as e:
            print(f"[orchestrator] PubMed fallback 오류: {e}")

        safety_warnings = _safety_engine.check(patient, supplement_name, None)

        if articles:
            rationale = (
                f"PubMed 검색 결과 {len(articles)}건의 관련 논문을 확인했으나, "
                f"{supplement_name}의 갑상선 질환에 대한 직접 임상 근거는 제한적입니다."
            )
        else:
            rationale = f"{supplement_name}에 대한 갑상선 관련 직접 임상 근거를 확인하지 못했습니다."

        result = DecisionResult(
            decision=Decision.INSUFFICIENT_EVIDENCE,
            supplement_name=supplement_name,
            confidence="low",
            safety_warnings=safety_warnings,
            evidence_records=evidence_records,
            rationale=rationale,
            recommendations=["전문의 상담 후 복용 여부를 결정하세요."],
            applied_rules=["pubmed_fallback"],
        )
        return patient, physician, result

    # 3. Safety Check (PubMed 이전 선실행 — CRITICAL 패턴 조기 차단)
    # §13.2 메시지 분리는 is_doctor_mode로 (PubMed fallback 여부와 독립 — 결정론 모드 호환)
    safety_warnings = _safety_engine.check(
        patient, supplement_name, rule,
        is_doctor_mode=is_doctor_mode,
    )

    critical = [w for w in safety_warnings if w.severity == WarningSeverity.CRITICAL]
    warning = [w for w in safety_warnings if w.severity == WarningSeverity.WARNING]

    # 3a. CRITICAL → 즉시 CONTRAINDICATED (early exit)
    if critical:
        rationale = "; ".join(w.message for w in critical[:2])
        _monitoring = rule.get("monitoring_parameters", []) if rule else []
        _counseling = rule.get("counseling_points", []) if rule else []
        result = DecisionResult(
            decision=Decision.CONTRAINDICATED,
            supplement_name=supplement_name,
            confidence="high",
            safety_warnings=safety_warnings,
            evidence_records=[],
            rationale=f"[CRITICAL] {rationale}",
            recommendations=[w.recommended_action for w in critical if w.recommended_action],
            applied_rules=["critical_early_stop"],
            monitoring_parameters=_monitoring,
            counseling_points=_counseling,
        )
        return patient, physician, result

    force_conditional = bool(warning)

    # 4. Evidence — use_pubmed=True일 때만
    evidence_records = []
    if use_pubmed:
        evidence_records = _fetch_pubmed_for_doctor(
            supplement_name=supplement_name,
            conditions=conditions,
            medications=medications,
            focus=focus,
            thyroid_context=thyroid_context,
            message=message,
            age=age,
            sex=sex,
            enhanced_search=enhanced_search,
            focus_explicit=focus_explicit,
            intent=intent,
        )

    # 4b. 미검증(롱테일) 게이트 — 안전검사·PubMed 근거는 유지하되, 미검증 LLM 룰 내용으로는
    #     판정하지 않고 근거부족 경로로 (AGENT_SPEC §3.7 / VERIFIED_SUPPLEMENTS). CRITICAL 안전은
    #     위 3a 에서 이미 처리됨.
    if not is_verified_supplement(supplement_name):
        result = DecisionResult(
            decision=Decision.INSUFFICIENT_EVIDENCE,
            supplement_name=supplement_name,
            confidence="low",
            safety_warnings=safety_warnings,
            evidence_records=evidence_records,
            rationale=(
                f"'{supplement_name}'은(는) 갑상선 관련 근거가 충분히 검증되지 않았습니다. "
                "정확한 판단을 위해 전문의 상담을 권고합니다."
            ),
            recommendations=["갑상선 전문의와 상담 후 복용 여부를 결정하세요."],
            applied_rules=["unverified_supplement"],
            monitoring_parameters=[],
            counseling_points=[],
        )
        return patient, physician, result

    # 5. Evaluate (최종 판단)
    result = _decision_engine.evaluate(
        patient=patient,
        supplement_name=supplement_name,
        rule=rule,
        safety_warnings=safety_warnings,
        evidence_records=evidence_records,
        physician=physician,
        force_conditional=force_conditional,
    )

    # 5d. STEP1 Fix B(#11): 입력 용량이 공식 상한섭취량(UL)을 초과하면 avoid 승격.
    #     용량을 못 읽으면(None) 현행 유지 → 회귀 0. 정상/운용상한(caution)은 미승격.
    #     INSUFFICIENT_EVIDENCE 포함: 조건 매칭이 없어도 UL 초과 용량은 안전상 avoid (용량 상한은 조건과 무관).
    #     이미 AVOID/CONTRAINDICATED 이면 미적용(동급/더 강함).
    if result.decision in (Decision.RECOMMEND, Decision.CONDITIONAL_CONSIDER, Decision.MANAGE_INTERACTION, Decision.INSUFFICIENT_EVIDENCE):
        from domain.thyroid.dose_safety import assess_dose
        from domain.thyroid.rules import _resolve_supplement_key
        _canon = _resolve_supplement_key(supplement_name)
        # 환자 조건 집합(diagnosis ∪ risk_factors) → 맥락 상한(임신 요오드)용
        _cond = {str(c).lower() for c in (list(patient.diagnosis or [])
                                          + list(getattr(patient, "risk_factors", []) or []))}
        _dose_verdict = assess_dose(_canon, message or "", _cond)
        if _dose_verdict == "avoid":
            # 임신·수유 요오드 상한(ATA 2017 §IV Rec 10)인지, 일반 UL 초과인지 추적성 구분
            _preg_iodine = _canon == "iodine" and bool({"pregnancy", "lactation"} & _cond)
            _tag = "iodine_pregnancy_dose_ceiling" if _preg_iodine else "dose_exceeds_ul"
            _why = ("[임신·수유 중 요오드 상한(500µg/일, ATA 2017) 초과 용량]" if _preg_iodine
                    else "[공식 상한섭취량(UL) 초과 용량]")
            result = result.model_copy(update={
                "decision": Decision.AVOID,
                "rationale": f"{_why} {result.rationale}",
                "applied_rules": list(result.applied_rules) + [_tag],
            })

    # 5d-2. UL 국가기준 상이(iodine·zinc) 비교 주석(§A-1) — 결정 불변, 추적성/투명성만.
    #       용량이 파싱되고 대상 성분이면 어느 결정에든 양 기준(NIH·KDRI) 표기.
    from domain.thyroid.dose_safety import dual_ul_comparison
    from domain.thyroid.rules import _resolve_supplement_key as _rsk2
    _ul_note = dual_ul_comparison(_rsk2(supplement_name), message or "")
    if _ul_note:
        result = result.model_copy(update={
            "rationale": f"{result.rationale} {_ul_note}".strip(),
            "applied_rules": list(result.applied_rules) + ["ul_standard_comparison"],
        })

    # 5d-3. 켈프/해조류 + 임신·수유 → avoid (ATA2017 §IV Rec10: 임신 켈프 회피; 요오드 함량 불규칙·과잉 위험).
    #       정량 없는 켈프는 dose 상한룰이 미발화 → 임신 recommend 경로로 새던 갭 차단.
    if _rsk2(supplement_name) == "iodine" and result.decision in (
        Decision.RECOMMEND, Decision.CONDITIONAL_CONSIDER, Decision.INSUFFICIENT_EVIDENCE
    ):
        _kelp = any(k in (message or "").lower() for k in ("켈프", "다시마", "해조", "미역", "kelp", "seaweed"))
        _cond_k = {str(c).lower() for c in (list(patient.diagnosis or [])
                                            + list(getattr(patient, "risk_factors", []) or []))}
        if _kelp and ({"pregnancy", "lactation"} & _cond_k):
            result = result.model_copy(update={
                "decision": Decision.AVOID,
                "rationale": ("[임신·수유 중 켈프/해조류 회피 — 요오드 함량 불규칙·과잉 위험, "
                              f"ATA2017 §IV Rec10] {result.rationale}"),
                "applied_rules": list(result.applied_rules) + ["iodine_kelp_pregnancy"],
            })

    # 5c. §7.2 Regimen-aware — MANAGE_INTERACTION 케이스에서 입력된 복용 타이밍으로
    #     분리 상태 판정. 타이밍을 못 읽으면 UNKNOWN → 포매터는 현행 일반론 유지(회귀 없음).
    if result.decision == Decision.MANAGE_INTERACTION:
        from domain.thyroid.regimen import assess_from_text, supplement_keywords
        from domain.thyroid.rules import _resolve_supplement_key

        def _as_text(x) -> str:
            return " ".join(x) if isinstance(x, list) else (x or "")

        timing_text = " ".join(
            [message, _as_text(medications), _as_text(current_supplements)]
        ).strip()
        canon = _resolve_supplement_key(supplement_name)
        status, lt4_h, supp_h = assess_from_text(
            timing_text, supplement_keywords(canon, supplement_name)
        )
        result = result.model_copy(update={"regimen_assessment": {
            "status": status.value, "lt4_hour": lt4_h, "supplement_hour": supp_h,
        }})

    # 5a. intent 문맥을 rationale에 보완 기록
    if intent not in ("safety", "supplement_query") and result.rationale:
        result = result.model_copy(update={"rationale": f"[intent:{intent}] {result.rationale}"})

    # 5b. Deferred condition note (§4.2, Phase 7) — 판정은 유지하되 rationale에 안내 추가
    cond_list = conditions if isinstance(conditions, list) else [c.strip() for c in (conditions or "").split(",") if c.strip()]
    deferred_hits = [c for c in cond_list if is_deferred_condition(c)]
    if deferred_hits:
        note = (
            f"[참고] 입력된 질환({', '.join(deferred_hits)})은 현재 시스템의 초기 지원 범위 밖입니다. "
            "판단 결과는 참고 수준으로만 활용하고 전문의와 반드시 확인하세요."
        )
        updated_rationale = f"{result.rationale}\n\n{note}" if result.rationale else note
        result = result.model_copy(update={"rationale": updated_rationale})

    return patient, physician, result


# ══════════════════════════════════════════════════════════
# 환자 래퍼 — POST /api/v1/patient/thyroid-chat
# PubMed 없음, rule 없으면 즉시 전문의 상담 유도
# ══════════════════════════════════════════════════════════

def run_patient_thyroid_pipeline(
    supplement_name: str,
    message: str = "",
    conditions: str | List[str] = "",
    medications: str | List[str] = "",
    current_supplements: str | List[str] = "",
    risk_factors: str | List[str] = "",
    symptoms: str | List[str] = "",
    dietary_habits: str | None = None,
    lab_values: dict = None,
    age: int = None,
    sex: str = None,
    height: float = None,
    weight: float = None,
    past_history: str | List[str] = "",
    surgical_history: str | List[str] = "",
    intent: str = "safety",
    focus: str = "general",
) -> tuple[PatientProfile, None, DecisionResult]:
    """환자 전용 파이프라인 — PubMed 활성(출처 미노출), PhysicianProfile 없음."""
    return _run_core_pipeline(
        supplement_name=supplement_name,
        message=message,
        conditions=conditions,
        medications=medications,
        current_supplements=current_supplements,
        risk_factors=risk_factors,
        symptoms=symptoms,
        dietary_habits=dietary_habits,
        lab_values=lab_values,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        past_history=past_history,
        surgical_history=surgical_history,
        intent=intent,
        focus=focus,
        use_pubmed=True,
        allow_pubmed_fallback=False,
        physician_profile=None,
    )


# ══════════════════════════════════════════════════════════
# 의사 래퍼 — POST /api/v1/doctor/thyroid-consult
# PubMed 선택, PhysicianProfile 반영, rule 없으면 PubMed fallback
# ══════════════════════════════════════════════════════════

def run_doctor_thyroid_pipeline(
    supplement_name: str,
    message: str = "",
    conditions: str | List[str] = "",
    medications: str | List[str] = "",
    current_supplements: str | List[str] = "",
    risk_factors: str | List[str] = "",
    symptoms: str | List[str] = "",
    dietary_habits: str | None = None,
    lab_values: dict = None,
    age: int = None,
    sex: str = None,
    height: float = None,
    weight: float = None,
    intent: str = "safety",
    thyroid_context: str = "general",
    use_pubmed: bool = False,
    allow_pubmed_fallback: bool = True,     # False + use_pubmed=False → 결정론(외부호출 0). 하네스 deterministic mode용
    enhanced_search: bool = False,
    physician_profile: dict | None = None,
    safety_flag: bool = False,
    focus: str = "general",
    focus_explicit: bool = False,
) -> tuple[PatientProfile, Optional[PhysicianProfile], DecisionResult]:
    """의사 전용 파이프라인 — PubMed 선택, PhysicianProfile 반영.

    결정론(rule-only) 평가: `use_pubmed=False, allow_pubmed_fallback=False` →
    미등록 성분(rule=None)이어도 PubMed/외부 호출 없이 INSUFFICIENT_EVIDENCE 반환."""
    patient, physician, result = _run_core_pipeline(
        supplement_name=supplement_name,
        message=message,
        conditions=conditions,
        medications=medications,
        current_supplements=current_supplements,
        risk_factors=risk_factors,
        symptoms=symptoms,
        dietary_habits=dietary_habits,
        lab_values=lab_values,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        intent=intent,
        thyroid_context=thyroid_context,
        focus=focus,
        use_pubmed=use_pubmed,
        enhanced_search=enhanced_search,
        allow_pubmed_fallback=allow_pubmed_fallback,
        is_doctor_mode=True,
        focus_explicit=focus_explicit,
        physician_profile=physician_profile,
    )

    # 의사 경로: CONTRAINDICATED여도 PubMed 근거 문헌 제공
    if (
        result.decision == Decision.CONTRAINDICATED
        and use_pubmed
        and not result.evidence_records
    ):
        records = _fetch_pubmed_for_doctor(
            supplement_name=supplement_name,
            conditions=conditions,
            medications=medications,
            focus=focus,
            thyroid_context=thyroid_context,
            message=message,
            age=age,
            sex=sex,
            enhanced_search=enhanced_search,
            focus_explicit=focus_explicit,
            intent=intent,
        )
        if records:
            result = result.model_copy(update={"evidence_records": records})

    return patient, physician, result


# ══════════════════════════════════════════════════════════
# 하위 호환 alias — 레거시 경로(chat/doctor.py 등)가 기존 이름으로 호출
# ══════════════════════════════════════════════════════════

run_thyroid_decision_pipeline = run_doctor_thyroid_pipeline
