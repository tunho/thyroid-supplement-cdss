"""
app.api.v1.endpoints.thyroid — 갑상선 supplement 의사결정 코어 API

POST /api/v1/patient/thyroid-chat    → PatientResponse
POST /api/v1/doctor/thyroid-consult  → DoctorResponse

흐름:
  Request → PatientProfile → EvidenceService → SafetyEngine
  → DecisionEngine → Formatter → Response + Audit Log
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from typing import Any, Optional
from app.services.thyroid.orchestrator import (
    run_thyroid_decision_pipeline,
    run_patient_thyroid_pipeline,
    run_doctor_thyroid_pipeline,
)
from domain.thyroid.audit import DecisionAuditLogger
from domain.thyroid.response import DoctorResponseFormatter, PatientResponseFormatter
from domain.thyroid.rules import infer_supplement_from_message, infer_medications_from_message, get_display_name, get_supplement_rule
from domain.thyroid.llm_response import generate_chat_response, generate_recommendation_response
from domain.thyroid.schemas import DoctorResponse, PatientResponse, WarningSeverity
from domain.consultation.pubmed.pubmed_query_builder import detect_thyroid_context_rule, detect_intent_rule
from domain.auth.auth_service import verify_token, get_doctor_profile, get_patient_profile, decode_access_token
from domain.thyroid.doctor_search_context import resolve_doctor_search_context

router = APIRouter()

# 싱글톤 서비스 인스턴스
_patient_formatter = PatientResponseFormatter()
_doctor_formatter = DoctorResponseFormatter()
_audit_logger = DecisionAuditLogger()


# ──────────────────────────────────────────────────────────
# Request 모델 (환자용)
# ──────────────────────────────────────────────────────────

class ThyroidPatientChatRequest(BaseModel):
    """POST /api/v1/patient/thyroid-chat 요청 바디."""
    message: str = Field(min_length=1, max_length=5000, description="자유 입력 또는 영양제 이름")
    supplement: str | None = Field(default=None, max_length=200, description="영양제 이름 (optional)")
    conditions: str | list[str] | None = Field(default=None, description="진단명/질환 (comma separated or list)")
    medications: str | list[str] | None = Field(default=None, description="복용 중인 약물")
    current_supplements: str | list[str] | None = Field(default=None)
    lab_values: dict | None = Field(default=None, description="검사값, e.g. {'TSH': 8.5, 'freeT4': 0.6}")
    symptoms: str | list[str] | None = Field(default=None, description="현재 증상")
    dietary_habits: str | None = Field(default=None, description="식습관 / iodine 섭취 가능성")
    risk_factors: str | list[str] | None = Field(default=None, description="pregnancy, elderly 등")
    age: int | None = None
    sex: str | None = None
    height: float | None = Field(default=None, description="§15.1 키(cm)")
    weight: float | None = Field(default=None, description="§15.1 몸무게(kg)")
    past_history: str | list[str] | None = Field(default=None, description="§15.1 병력 (과거 진단/질환)")
    surgical_history: str | list[str] | None = Field(default=None, description="§15.1 수술력 (갑상선 절제술 등)")
    history: list[dict] | None = Field(default=None, description="이전 대화 기록 [{role, message, timestamp}]")
    use_pubmed: bool = False


# ──────────────────────────────────────────────────────────
# Request 모델 (의사용)
# ──────────────────────────────────────────────────────────

class ThyroidDoctorConsultRequest(BaseModel):
    """POST /api/v1/doctor/thyroid-consult 요청 바디."""
    message: str | None = Field(default=None, max_length=2000, description="의사의 구체적 질문/의문 사항")
    supplement: str = Field(min_length=1, max_length=200, description="판단 대상 영양제 이름")
    dose: str | None = Field(default=None, max_length=100)
    conditions: str | list[str] | None = Field(default=None)
    medications: str | list[str] | None = Field(default=None)
    current_supplements: str | list[str] | None = Field(default=None)
    lab_values: dict | None = Field(default=None, description="{'TSH': 8.5, 'freeT4': 0.6}")
    symptoms: str | list[str] | None = Field(default=None)
    dietary_habits: str | None = Field(default=None)
    risk_factors: str | list[str] | None = Field(default=None)
    age: int | None = None
    sex: str | None = None
    # Physician 프로파일
    specialty: str | None = None
    years_experience: int | None = None
    supplement_attitude: str = "neutral"
    risk_tolerance: str = "moderate"
    height: float | None = None
    weight: float | None = None
    intent: str = "safety"
    thyroid_context: str = "general"
    use_pubmed: bool = False
    enhanced_search: bool = False
    focus: str | None = Field(
        default=None,
        description="PubMed 검색 초점: general|interaction|dosage|monitoring. None=자동 추론",
    )
    physician_note: str | None = Field(
        default=None,
        max_length=1000,
        description="§14.4 의사 자유 코멘트 (응답에 에코되어 기록됨)",
    )


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────

@router.post("/patient/thyroid-chat", response_model=PatientResponse)
def patient_thyroid_chat(
    body: ThyroidPatientChatRequest,
    authorization: str | None = Header(default=None),
):
    """환자용 갑상선 영양제 의사결정 API."""

    token_data = _decode_optional_bearer_token(authorization)
    patient_profile_from_db = None
    if token_data and token_data.get("role") == "patient":
        try:
            patient_profile_from_db = get_patient_profile(token_data["sub"])
        except Exception:
            patient_profile_from_db = None

    db_conditions = patient_profile_from_db.conditions if patient_profile_from_db else None
    db_medications = patient_profile_from_db.medications if patient_profile_from_db else None

    # ── 갑상선 상태 추론 (메시지) ──
    inferred_conditions = None
    inferred_ctx = detect_thyroid_context_rule(body.message)
    if inferred_ctx:
        inferred_conditions = ",".join(inferred_ctx)

    # ── 영양제 해석 (Resolver) ─────────────────────────────
    # 키워드/별칭 → MFDS 복수 성분 → LLM 구조화 → 히스토리 복원 순서로 시도
    from domain.thyroid.supplement_resolver import resolve_supplement
    resolution = resolve_supplement(
        message=body.message,
        explicit_supplement=body.supplement,
        history=body.history,
    )
    # 하위 호환용 단일 영양제 변수 (의도 분류·약물 오분류 방지·로깅용)
    supplement_name: str = resolution.ingredients[0].key if resolution.ingredients else ""
    original_supplement_term: Optional[str] = resolution.product_label
    # 현재 메시지에서 직접 추출됐는지 여부 (히스토리 carry-over 감지용)
    supplement_in_message: bool = resolution.from_message and bool(resolution.ingredients)

    # ── 약물 추출 (메시지) ────────────────────────────────
    inferred_med_from_message = None
    if not body.medications and not db_medications:
        inferred_med = infer_medications_from_message(body.message)
        if inferred_med:
            # 영양제가 칼슘/철분일 때 같은 이름이 '약'으로 오분류되는 것 방지
            supp_display = get_display_name(supplement_name).lower() if supplement_name else ""
            orig_term = (original_supplement_term or "").lower()
            if inferred_med in ("칼슘제", "철분제") and any(
                k in supp_display or k in orig_term for k in ("칼슘", "철분", "calcium", "iron")
            ):
                inferred_med = None
        inferred_med_from_message = inferred_med

    # ── 히스토리 복원 (conditions + medications만; 영양제는 Resolver 담당) ──
    inferred_medications = None
    if body.history:
        for h in reversed(body.history):
            msg = h.get("message", "")
            role = h.get("role", "")
            h_cond = h.get("conditions")
            h_med = h.get("medications")
            if role == "user":
                if not h_cond and msg:
                    ctx_detected = detect_thyroid_context_rule(msg)
                    if ctx_detected:
                        h_cond = ",".join(ctx_detected)
                if not h_med and msg:
                    h_med = infer_medications_from_message(msg)
            if not inferred_conditions and h_cond:
                inferred_conditions = h_cond
            if not inferred_medications and h_med:
                inferred_medications = h_med
            if inferred_conditions and inferred_medications:
                break

    current_conditions = _first_present(body.conditions, db_conditions, inferred_conditions)
    current_medications = _first_present(body.medications, db_medications, inferred_medications, inferred_med_from_message)
    information_missing = {
        "supplement": resolution.needs_clarification or not bool(resolution.ingredients),
        "conditions": not _has_value(current_conditions),
        "medications": not _has_value(current_medications),
    }

    intent_result = _classify_patient_intent(body.message, supplement_name)

    # 이전 대화가 영양제 재질문(Clarification) 중이면 intent를 supplement_query로 보정
    is_in_clarification = False
    if body.history:
        last_assistant_msg = None
        for h in reversed(body.history):
            if h.get("role") == "assistant":
                last_assistant_msg = h.get("message", "")
                break
        if last_assistant_msg and any(
            k in last_assistant_msg
            for k in ["어떤 제품", "이 중에", "어떤 것", "확인해", "선택해", "찾으시나요", "알려주시면"]
        ):
            is_in_clarification = True

    if is_in_clarification and intent_result.primary_intent in ("general_chat", "unknown", "recommendation_query"):
        intent_result.intents = ["supplement_query"]

    if intent_result.primary_intent == "general_chat":
        _audit_logger.log(
            decision_result=_make_skipped_result(supplement_name),
            response_type="patient",
            request_summary={"supplement": supplement_name, "intents": intent_result.intents, "intent_skipped_pipeline": True},
        )
        return PatientResponse(
            summary="안녕하세요! 갑상선 영양제에 대해 궁금한 점을 알려주세요.",
            can_take="해당없음",
            cautions=[],
            next_actions=["궁금한 영양제 이름과 현재 갑상선 상태를 알려주시면 도움드릴게요."],
            consult_doctor=False,
        )

    if intent_result.primary_intent == "disease_query" and not supplement_name:
        _audit_logger.log(
            decision_result=_make_skipped_result(supplement_name),
            response_type="patient",
            request_summary={"supplement": supplement_name, "intents": intent_result.intents, "intent_skipped_pipeline": True},
        )
        return PatientResponse(
            summary="입력하신 영양제를 인식하지 못했습니다. 제품의 성분명(예: 오메가3, 비타민D, 셀레늄)으로 입력해 주시면 정확한 답변이 가능합니다. 📝",
            can_take="정보필요",
            cautions=[],
            next_actions=["성분명으로 입력해 주세요: 오메가3, 비타민D, 셀레늄, 철분 등",
                          "브랜드명보다 성분명으로 입력하시면 더 정확한 답변을 드릴 수 있습니다."],
            consult_doctor=False,
        )

    if intent_result.primary_intent == "unknown":
        _audit_logger.log(
            decision_result=_make_skipped_result(supplement_name),
            response_type="patient",
            request_summary={"supplement": supplement_name, "intents": intent_result.intents, "intent_skipped_pipeline": True},
        )
        return PatientResponse(
            summary="입력하신 내용을 이해하지 못했습니다. 궁금하신 영양제의 성분명(예: 오메가3, 비타민D, 셀레늄)과 현재 갑상선 상태를 함께 알려주시면 정확한 답변이 가능합니다. 📝",
            can_take="정보필요",
            cautions=[],
            next_actions=["성분명으로 입력해 주세요: 오메가3, 비타민D, 셀레늄, 철분 등",
                          "예: '오메가3 하시모토', '비타민D 갑상선기능저하증'"],
            consult_doctor=False,
        )

    if intent_result.primary_intent == "recommendation_query":
        _audit_logger.log(
            decision_result=_make_skipped_result(supplement_name),
            response_type="patient",
            request_summary={"supplement": supplement_name, "intents": intent_result.intents, "intent_skipped_pipeline": True},
        )
        if _has_value(current_conditions):
            rec_msg = generate_recommendation_response(
                conditions=current_conditions,
                medications=current_medications or "",
            )
            return PatientResponse(
                summary="진단에 따른 영양제 안내",
                can_take="해당없음",
                cautions=[],
                next_actions=["구체적인 영양제 이름을 말씀해 주시면 안전성을 확인해 드릴게요."],
                consult_doctor=True,
                chat_message=rec_msg,
            )
        return PatientResponse(
            summary="갑상선 상태에 따라 적절한 영양제가 달라집니다. 진단명을 알려주시면 더 정확하게 안내드릴게요.",
            can_take="해당없음",
            cautions=[],
            next_actions=["진단명을 알려주세요. 예: '하시모토', '갑상선기능저하증', '그레이브스병'"],
            consult_doctor=False,
        )

    # ── 영양제 재질문 게이트 (Resolver 결과 기반) ─────────────
    if information_missing["supplement"]:
        if resolution.clarification_candidates:
            # 복수 제품 히트 → 어떤 제품인지 재질문
            short_names = resolution.clarification_candidates[:4]
            _audit_logger.log(
                decision_result=_make_skipped_result(supplement_name),
                response_type="patient",
                request_summary={"supplement": supplement_name, "intents": intent_result.intents, "info_gate": "product_clarification"},
            )
            return PatientResponse(
                summary="여러 제품이 검색됩니다. 어떤 제품을 찾으시나요?",
                can_take="정보필요",
                cautions=[],
                next_actions=["위 목록에 없으면 성분명으로 입력해 주세요. 예: '오메가3', '비타민D'"],
                clarification_candidates=short_names,
                consult_doctor=False,
                chat_message=resolution.clarification_question,
            )
        else:
            # 전혀 인식 못한 경우
            _audit_logger.log(
                decision_result=_make_skipped_result(supplement_name),
                response_type="patient",
                request_summary={"supplement": supplement_name, "intents": intent_result.intents, "info_gate": "supplement_missing"},
            )
            raw_message = (body.message or "").strip()
            chat_msg = resolution.clarification_question
            if not chat_msg and raw_message:
                from domain.thyroid.llm_response import generate_unrecognized_response
                chat_msg = generate_unrecognized_response(user_message=raw_message, history=body.history)
            if raw_message:
                summary_msg = "입력하신 영양제를 인식하지 못했습니다. 제품의 성분명(예: 오메가3, 비타민D, 셀레늄)으로 입력해 주시면 정확한 답변이 가능합니다. 📝"
                next_action: list[str] = [
                    "성분명으로 입력해 주세요: 오메가3, 비타민D, 셀레늄, 철분 등",
                    "브랜드명보다 성분명으로 입력하시면 더 정확한 답변을 드릴 수 있습니다.",
                ]
            else:
                summary_msg = "어떤 영양제에 대해 궁금하신가요?"
                next_action = ["영양제 이름을 알려주세요. 예: '셀레늄', '비타민D', '오메가3', '철분'"]
            return PatientResponse(
                summary=summary_msg,
                can_take="정보필요",
                cautions=[],
                next_actions=next_action,
                consult_doctor=False,
                chat_message=chat_msg,
            )

    # ── §15.3 진단 정보 없음 → 짧은 재질문 반환 ──
    if information_missing["conditions"]:
        display_name = get_display_name(supplement_name)
        _audit_logger.log(
            decision_result=_make_skipped_result(supplement_name),
            response_type="patient",
            request_summary={
                "supplement": supplement_name,
                "intents": intent_result.intents,
                "info_gate": "conditions_missing",
                "response_mode": "general",
            },
        )
        return PatientResponse(
            summary=f"{display_name}에 대해 더 정확한 안내를 드리려면 현재 갑상선 진단명을 알려주세요.",
            can_take="정보필요",
            cautions=[],
            next_actions=[
                "진단명을 알려주세요. 예: '하시모토', '갑상선기능저하증', '그레이브스병', '갑상선기능항진증'",
                "복용 중인 약도 함께 알려주시면 약물 상호작용 정보를 포함할 수 있습니다.",
            ],
            consult_doctor=False,
            identified_supplement=supplement_name if supplement_name else None,
            identified_supplement_display=display_name if display_name else None,
            response_mode="general",
        )

    # ── 판정 파이프라인: 성분 N개 각각 실행 후 집계 ──────────
    _pipeline_kwargs = dict(
        conditions=current_conditions,
        medications=current_medications,
        current_supplements=body.current_supplements,
        risk_factors=body.risk_factors,
        symptoms=body.symptoms,
        dietary_habits=body.dietary_habits,
        lab_values=body.lab_values,
        age=body.age,
        sex=body.sex,
        height=body.height,
        weight=body.weight,
        past_history=body.past_history,
        surgical_history=body.surgical_history,
        intent=intent_result.primary_intent,
        focus=intent_result.focus,
    )

    if len(resolution.ingredients) <= 1:
        # 단일 성분 (기존 경로)
        patient, _, decision_result = run_patient_thyroid_pipeline(
            supplement_name=supplement_name, **_pipeline_kwargs
        )
    else:
        # 복수 성분 (복합제) → 각각 판정 후 집계
        all_results = []
        for ing in resolution.ingredients:
            _, _, dr = run_patient_thyroid_pipeline(
                supplement_name=ing.key, **_pipeline_kwargs
            )
            all_results.append(dr)
        decision_result = _aggregate_decisions(
            results=all_results,
            product_label=resolution.product_label or supplement_name,
        )

    response = _patient_formatter.format(decision_result, patient=patient)

    # 응답의 supplement 이름을 한국어로 변환
    display_name = get_display_name(decision_result.supplement_name)
    if display_name != decision_result.supplement_name:
        response = response.model_copy(update={
            "summary": response.summary.replace(decision_result.supplement_name, display_name)
        })

    # WARNING 시 응답 강조
    if any(w.severity == WarningSeverity.WARNING for w in decision_result.safety_warnings):
        response = response.model_copy(update={"summary": "[주의] " + response.summary})

    # LLM 자연어 응답 생성
    is_update_turn = False
    is_carried_over = bool(supplement_name) and not supplement_in_message
    if body.history and is_carried_over:
        last_assistant_msg = None
        for h in reversed(body.history):
            if h.get("role") == "assistant":
                last_assistant_msg = h.get("message", "")
                break
        if last_assistant_msg:
            missing_markers = ["상태가 필요합니다", "이해하지 못했습니다", "인식하지 못했습니다", "어떤 제품", "정보필요"]
            if not any(marker in last_assistant_msg for marker in missing_markers):
                is_update_turn = True

    _rule = get_supplement_rule(supplement_name)
    chat_msg = generate_chat_response(
        result=decision_result,
        display_name=display_name,
        conditions=current_conditions or "",
        medications=current_medications or "",
        study_dose=(_rule or {}).get("study_dose", ""),
        official_upper_limit=(_rule or {}).get("official_upper_limit", ""),
        history=body.history or [],
        original_term=original_supplement_term,
        is_update_turn=is_update_turn,
        message=body.message or "",
    )
    if chat_msg:
        response = response.model_copy(update={"chat_message": chat_msg})

    if current_medications:
        response = response.model_copy(update={"identified_medications": current_medications})

    if current_conditions:
        _cond_str = (
            current_conditions if isinstance(current_conditions, str)
            else ", ".join(current_conditions)
        )
        response = response.model_copy(update={"identified_conditions": _cond_str})

    # 약물 정보 없을 때 보수적 면책 주의 추가
    if not _has_value(current_medications):
        _med_note = (
            "복용 중인 약물 정보가 없어 약물 상호작용은 확인되지 않았습니다. "
            "레보티록신 등 갑상선 약을 복용 중이라면 반드시 전문의에게 확인하세요."
        )
        _notes = list(response.uncertainty_notes or [])
        if _med_note not in _notes:
            _notes.insert(0, _med_note)
        response = response.model_copy(update={"uncertainty_notes": _notes[:4]})

    # §15.3 개인화 모드 표시 (진단 + 성분 모두 있으면 personalized)
    response = response.model_copy(update={"response_mode": "personalized"})

    # Audit log
    _audit_logger.log(
        decision_result=decision_result,
        response_type="patient",
        request_summary={
            "supplement": supplement_name,
            "conditions": current_conditions,
            "medications": current_medications,
            "current_supplements": body.current_supplements,
            "lab_values": body.lab_values,
            "symptoms": body.symptoms,
            "dietary_habits": body.dietary_habits,
            "risk_factors": body.risk_factors,
            "age": body.age,
            "sex": body.sex,
            "patient_id": token_data.get("sub") if token_data else None,
            "context_sources": {
                "has_patient_profile": patient_profile_from_db is not None,
                "conditions": _context_source(body.conditions, db_conditions, inferred_conditions),
                "medications": _context_source(body.medications, db_medications),
                "supplement": "request" if _has_value(body.supplement) else "message_or_fallback",
            },
            "information_missing": information_missing,
            "intents": intent_result.intents,
            "focus": intent_result.focus,
            "safety_flag": intent_result.safety_flag,
            "intent_skipped_pipeline": False,
            # §15.3 응답 모드 + MVP scope 기록
            "response_mode": getattr(response, "response_mode", "personalized") or "personalized",
            "mvp_enabled": True,
        },
    )

    return response


@router.post("/doctor/thyroid-consult", response_model=DoctorResponse)
def doctor_thyroid_consult(
    body: ThyroidDoctorConsultRequest,
    token_data: dict | None = Depends(verify_token)
):
    """의사용 갑상선 영양제 의사결정 API."""

    # 1. 의사 프로필 로드 (토큰 우선, 바디 차선)
    physician_kwargs = {
        "specialty": body.specialty,
        "years_experience": body.years_experience,
        "supplement_attitude": body.supplement_attitude,
        "risk_tolerance": body.risk_tolerance,
    }

    if token_data and token_data.get("role") == "doctor":
        try:
            doc_profile = get_doctor_profile(token_data["sub"])
            physician_kwargs.update({
                "specialty": doc_profile.specialty,
                "years_experience": doc_profile.years_experience,
                "supplement_attitude": doc_profile.supplement_attitude,
                "risk_tolerance": doc_profile.risk_tolerance,
            })
        except Exception:
            pass

    doctor_safety_context = _layer1_preprocess(
        f"{body.message or ''} {body.conditions or ''} {body.medications or ''}",
        body.supplement,
    )

    # 2. intent/focus/thyroid_context 추론 (폼 기본값이면 메시지에서 추론)
    _cond_str = (
        ", ".join(body.conditions) if isinstance(body.conditions, list)
        else (body.conditions or "")
    )
    inferred = _infer_doctor_intent(body.message or "", _cond_str)
    resolved_intent = body.intent if body.intent != "safety" else inferred["intent"]
    resolved_thyroid_context = body.thyroid_context if body.thyroid_context != "general" else inferred["thyroid_context"]

    # focus: body.focus가 명시되면 우선 사용 (UI/API 명시), 없으면 메시지 추론
    focus_explicit = body.focus is not None
    resolved_focus = body.focus if focus_explicit else inferred["focus"]

    # 3. 파이프라인 실행
    patient, physician, decision_result = run_doctor_thyroid_pipeline(
        supplement_name=body.supplement,
        message=body.message,
        conditions=body.conditions,
        medications=body.medications,
        current_supplements=body.current_supplements,
        risk_factors=body.risk_factors,
        symptoms=body.symptoms,
        dietary_habits=body.dietary_habits,
        lab_values=body.lab_values,
        age=body.age,
        sex=body.sex,
        height=body.height,
        weight=body.weight,
        intent=resolved_intent,
        thyroid_context=resolved_thyroid_context,
        use_pubmed=body.use_pubmed,
        enhanced_search=body.enhanced_search,
        physician_profile=physician_kwargs,
        focus=resolved_focus,
        focus_explicit=focus_explicit,
    )

    response = _doctor_formatter.format(
        decision_result,
        physician=physician,
        conditions=body.conditions or "",
        medications=body.medications or "",
        patient=patient,
        message=body.message or "",
        physician_note=body.physician_note or None,
    )

    # Audit log
    _audit_logger.log(
        decision_result=decision_result,
        response_type="doctor",
        request_summary={
            "supplement": body.supplement,
            "dose": body.dose,
            "conditions": body.conditions,
            "medications": body.medications,
            "lab_values": body.lab_values,
            "safety_flag": doctor_safety_context["safety_flag"],
            "supplement_detected": doctor_safety_context["supplement_detected"],
            "focus_requested": body.focus,
            "focus_resolved": resolved_focus,
            "focus_explicit": focus_explicit,
        },
        physician_profile={
            "supplement_attitude": body.supplement_attitude,
            "risk_tolerance": body.risk_tolerance,
            "specialty": body.specialty,
        },
    )

    return response


@router.get("/analytics/summary")
def get_analytics_summary():
    """의사 결정 분석 요약 API."""
    from domain.thyroid.analytics import (
        load_audit_records,
        summarize_by_supplement,
        summarize_variability,
        summarize_by_physician_profile,
    )
    records = load_audit_records()
    return {
        "total_decisions": len(records),
        "by_supplement": summarize_by_supplement(records),
        "variability": summarize_variability(records),
        "by_physician_profile": summarize_by_physician_profile(records),
    }


# ──────────────────────────────────────────────────────────
# Intent 분류 (3계층 구조)
# Layer 1: Rule-based — 단독 인사 차단 + CRITICAL safety_flag + supplement_detected
# Layer 2: LLM — 전체 문장 맥락으로 intents[], focus 분류
# Layer 3: Router — LLM 실패 시 supplement_detected 기반 fallback
# ──────────────────────────────────────────────────────────

_GREETING_SIGNALS_KO = ["안녕", "감사", "고마워", "고맙", "반가워", "반갑", "ㅎㅇ", "ㅋㅋ", "ㅎㅎ"]
_GREETING_SIGNALS_EN = ["hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye"]
_GREETING_MAX_LEN = 20

_SUPPLEMENT_KEYWORDS = [
    "요오드", "iodine", "아이오딘",
    "켈프", "kelp", "다시마", "해조류", "블래더랙", "bladderwrack",
    "비오틴", "biotin",
    "철분", "iron",
    "칼슘", "calcium",
    "마그네슘", "magnesium",
    "아연", "zinc",
    "셀레늄", "selenium",
    "아슈와간다", "ashwagandha",
]

_CRITICAL_SAFETY_RULES = [
    {
        "reason": "iodine_or_seaweed_with_hyperthyroid",
        "supplement_terms": ["요오드", "iodine", "아이오딘", "켈프", "kelp", "다시마", "해조류", "블래더랙", "bladderwrack"],
        "condition_terms": ["항진", "항진증", "갑상선기능항진", "갑상선기능항진증", "그레이브스", "graves", "hyperthyroid", "hyperthyroidism"],
        "level": "critical",
    },
    {
        "reason": "iodine_or_seaweed_with_hashimoto",
        "supplement_terms": ["요오드", "iodine", "아이오딘", "켈프", "kelp", "다시마", "해조류", "블래더랙", "bladderwrack"],
        "condition_terms": ["하시모토", "hashimoto", "자가면역", "갑상선염"],
        "level": "caution",
    },
    {
        "reason": "biotin_with_thyroid_lab_test",
        "supplement_terms": ["비오틴", "biotin"],
        "condition_terms": ["검사", "피검사", "혈액검사", "갑상선검사", "tsh", "t3", "t4", "free t4", "lab", "test"],
        "level": "caution",
    },
    {
        "reason": "minerals_with_levothyroxine",
        "supplement_terms": ["철분", "iron", "칼슘", "calcium", "마그네슘", "magnesium", "아연", "zinc"],
        "condition_terms": ["씬지로이드", "신지로이드", "레보티록신", "levothyroxine", "갑상선약", "thyroid hormone"],
        "level": "interaction",
    },
    {
        "reason": "pregnancy_with_thyroid_medication",
        "supplement_terms": ["임신", "임산부", "pregnancy", "pregnant", "수유", "breastfeeding"],
        "condition_terms": ["씬지로이드", "신지로이드", "레보티록신", "levothyroxine", "항갑상선", "메티마졸", "methimazole", "ptu"],
        "level": "critical",
    },
    {
        "reason": "ashwagandha_with_hyperthyroid",
        "supplement_terms": ["아슈와간다", "ashwagandha", "위타니아"],
        "condition_terms": ["항진", "항진증", "갑상선기능항진", "갑상선기능항진증", "그레이브스", "graves", "hyperthyroid", "hyperthyroidism"],
        "level": "critical",
    },
]
_VALID_INTENTS = frozenset([
    "supplement_query",
    "safety_query",
    "evidence_query",
    "disease_query",
    "recommendation_query",
    "general_chat",
])
_VALID_FOCUS = frozenset(["general", "interaction", "dosage", "monitoring"])

_LLM_INTENT_SYSTEM_PROMPT = (
    "You are a question classifier for a Korean thyroid supplement consultation chatbot.\n\n"
    "Classify the user message into intents and a focus.\n\n"
    "Available intents (multiple allowed):\n"
    "- supplement_query: asking whether a supplement can be taken, its effects or benefits\n"
    "- safety_query: asking about side effects, dangers, risks, or drug interactions\n"
    "- evidence_query: asking for research, papers, studies, or clinical evidence\n"
    "- disease_query: asking what a disease is or for disease explanations (no supplement involved)\n"
    "- recommendation_query: asking which supplements are good or requesting supplement recommendations without naming a specific supplement\n"
    "- general_chat: pure greeting or off-topic with no medical content\n\n"
    "Available focus values: general, interaction, dosage, monitoring\n\n"
    "Rules:\n"
    "- Multiple intents allowed (e.g. supplement_query + safety_query)\n"
    "- If safety_flag is true, always include safety_query\n"
    "- If the user simply names a product/ingredient (e.g. '마그네슘', '종근당 프로폴리스야', '관절팔팔'), classify as [\"supplement_query\"]\n"
    "- Pure greeting only → [\"general_chat\"]\n"
    "- Disease explanation only → [\"disease_query\"]\n\n"
    "Return ONLY valid JSON, no other text:\n"
    "{\"intents\": [\"<intent>\"], \"focus\": \"<focus>\"}"
)


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k.lower() in text for k in keywords)


@dataclass
class IntentResult:
    intents: list = field(default_factory=lambda: ["supplement_query"])
    focus: str = "general"
    safety_flag: bool = False
    supplement_detected: bool = False

    @property
    def primary_intent(self) -> str:
        return self.intents[0] if self.intents else "unknown"


def _infer_doctor_intent(message: str, conditions: str) -> dict:
    """의사용 intent/focus/thyroid_context 추론. domain.thyroid.doctor_search_context 위임."""
    return resolve_doctor_search_context(message, conditions)


def _layer1_preprocess(message: str, supplement_name: str | None = None) -> dict:
    """Layer 1: 빠른 사전 처리. greeting / supplement / safety signal 반환."""
    msg = (message or "").strip()
    supp = (supplement_name or "").strip()

    msg_lower = msg.lower()
    combined = f"{msg} {supp}".lower()

    matched_reasons = []
    highest_level = None

    for rule in _CRITICAL_SAFETY_RULES:
        has_supplement_term = _contains_any(combined, rule["supplement_terms"])
        has_condition_term = _contains_any(combined, rule["condition_terms"])

        if has_supplement_term and has_condition_term:
            matched_reasons.append(rule["reason"])

            if rule["level"] == "critical":
                highest_level = "critical"
            elif highest_level != "critical" and rule["level"] == "interaction":
                highest_level = "interaction"
            elif highest_level not in ("critical", "interaction"):
                highest_level = "caution"

    safety_flag = bool(matched_reasons)

    supplement_detected = (
        _has_value(supp)
        or _contains_any(combined, _SUPPLEMENT_KEYWORDS)
    )

    has_greeting_signal = (
        any(signal in msg for signal in _GREETING_SIGNALS_KO)
        or any(signal in msg_lower for signal in _GREETING_SIGNALS_EN)
    )

    is_greeting = (
        not safety_flag
        and not supplement_detected
        and len(msg) <= _GREETING_MAX_LEN
        and has_greeting_signal
    )

    return {
        "is_greeting": is_greeting,
        "safety_flag": safety_flag,
        "safety_level": highest_level,
        "safety_reasons": matched_reasons,
        "supplement_detected": supplement_detected,
    }

def _layer2_llm_classify(message: str, safety_flag: bool, supplement_detected: bool) -> dict | None:
    """Layer 2: LLM으로 전체 문장 맥락 기반 intent 분류. 실패 시 None 반환."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        user_content = (
            f"safety_flag: {str(safety_flag).lower()}\n"
            f"supplement_detected: {str(supplement_detected).lower()}\n"
            f"user message: {message}"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _LLM_INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_tokens=60,
            temperature=0,
        )
        parsed = json.loads(resp.choices[0].message.content.strip())
        intents = [i for i in parsed.get("intents", []) if i in _VALID_INTENTS]
        focus = parsed.get("focus", "general")
        if focus not in _VALID_FOCUS:
            focus = "general"
        return {"intents": intents, "focus": focus} if intents else None
    except Exception:
        return None


def _layer3_route(layer1: dict, llm_result: dict | None) -> IntentResult:
    """Layer 3: LLM 결과 + Layer 1 컨텍스트로 최종 IntentResult 반환."""
    safety_flag = layer1["safety_flag"]
    supplement_detected = layer1["supplement_detected"]

    if llm_result:
        return IntentResult(
            intents=llm_result["intents"],
            focus=llm_result["focus"],
            safety_flag=safety_flag,
            supplement_detected=supplement_detected,
        )

    # LLM 실패 fallback: supplement_detected 기반 스마트 분기
    if supplement_detected:
        fallback_intent = "safety_query" if safety_flag else "supplement_query"
    else:
        fallback_intent = "unknown"  # 정보 수집 필요

    return IntentResult(
        intents=[fallback_intent],
        focus="general",
        safety_flag=safety_flag,
        supplement_detected=supplement_detected,
    )


def _classify_patient_intent(message: str, supplement_name: str) -> IntentResult:
    """3계층 intent 분류. IntentResult 반환."""
    layer1 = _layer1_preprocess(message, supplement_name)

    # Layer 1: 단독 인사말 → 즉시 반환 (LLM 호출 안 함)
    if layer1["is_greeting"]:
        return IntentResult(
            intents=["general_chat"],
            focus="general",
            safety_flag=False,
            supplement_detected=layer1["supplement_detected"],
        )

    # Layer 2: LLM 분류 (safety_flag, supplement_detected를 컨텍스트로 전달)
    llm_result = _layer2_llm_classify(message, layer1["safety_flag"], layer1["supplement_detected"])

    # Layer 3: 라우팅
    return _layer3_route(layer1, llm_result)


def _make_skipped_result(supplement_name: str):
    from domain.thyroid.schemas import DecisionResult, Decision
    return DecisionResult(
        decision=Decision.INSUFFICIENT_EVIDENCE,
        supplement_name=supplement_name or "unknown",
        confidence="low",
        rationale="파이프라인 실행 없이 intent 분류 단계에서 응답.",
        applied_rules=["intent_skip"],
    )


def _aggregate_decisions(results: list, product_label: str) -> "DecisionResult":
    """
    복수 성분 판정 결과를 제품 단위 단일 DecisionResult로 집계한다.

    집계 규칙 (심각도 우선):
      CONTRAINDICATED > AVOID > CONDITIONAL_CONSIDER > RECOMMEND > INSUFFICIENT_EVIDENCE

    경고(safety_warnings)는 전부 병합.
    근거(evidence_records)는 전부 병합.
    rationale 은 성분별 요약을 연결.
    """
    from domain.thyroid.schemas import DecisionResult, Decision

    _SEVERITY_ORDER = {
        Decision.CONTRAINDICATED:    5,
        Decision.AVOID:              4,
        Decision.CONDITIONAL_CONSIDER: 3,
        Decision.RECOMMEND:          2,
        Decision.INSUFFICIENT_EVIDENCE: 1,
    }

    if not results:
        return DecisionResult(
            decision=Decision.INSUFFICIENT_EVIDENCE,
            supplement_name=product_label,
            confidence="low",
            rationale="판정 결과 없음.",
        )

    if len(results) == 1:
        return results[0]

    # 최악 decision 선택
    worst = max(results, key=lambda r: _SEVERITY_ORDER.get(r.decision, 0))

    # 경고 병합 (중복 category 제거)
    seen_cats: set = set()
    merged_warnings = []
    for r in results:
        for w in r.safety_warnings:
            if w.category not in seen_cats:
                seen_cats.add(w.category)
                merged_warnings.append(w)

    # 근거 병합
    merged_evidence = []
    seen_pmids: set = set()
    for r in results:
        for ev in r.evidence_records:
            key = ev.pmid or ev.title
            if key not in seen_pmids:
                seen_pmids.add(key)
                merged_evidence.append(ev)

    # rationale 연결
    rationale_parts = []
    for r in results:
        if r.rationale:
            rationale_parts.append(f"[{r.supplement_name}] {r.rationale}")
    combined_rationale = " | ".join(rationale_parts) if rationale_parts else worst.rationale

    return DecisionResult(
        decision=worst.decision,
        supplement_name=product_label,
        confidence=worst.confidence,
        safety_warnings=merged_warnings,
        evidence_records=merged_evidence,
        rationale=combined_rationale,
        recommendations=worst.recommendations,
        applied_rules=list({rule for r in results for rule in r.applied_rules}),
    )


def _decode_optional_bearer_token(authorization: str | None) -> dict | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return decode_access_token(parts[1])


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _first_present(*values: Any) -> Any:
    for value in values:
        if _has_value(value):
            return value
    return None


def _context_source(request_value: Any, db_value: Any, inferred_value: Any = None) -> str:
    if _has_value(request_value):
        return "request"
    if _has_value(db_value):
        return "patient_profile"
    if _has_value(inferred_value):
        return "message_inference"
    return "missing"
