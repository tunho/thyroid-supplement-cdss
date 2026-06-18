"""
domain.thyroid.schemas — 갑상선 supplement 의사결정 코어 데이터 모델

모든 컴포넌트(rules, safety, evidence, decision, response)가
이 파일의 Pydantic 모델만 주고받습니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[레이어 구분]

  HTTP 요청 IN (여기 없음)
    환자 → app/api/v1/endpoints/thyroid.py :: ThyroidPatientChatRequest
    의사 → app/api/v1/endpoints/thyroid.py :: ThyroidDoctorConsultRequest

  파이프라인 (여기)
    공용  → PatientProfile, SafetyWarning, EvidenceRecord, DecisionResult
    의사  → PhysicianProfile

  HTTP 응답 OUT (여기)
    환자  → PatientResponse
    의사  → DoctorResponse

[이름 주의]
  PatientProfile (여기)          = 결정용 임상 프로필 (진단·약·TSH 등)
  PatientProfile (domain/auth/)  = 회원 DB 프로필 (이름·가입일 등) ← 다른 클래스

[미사용]
  SupplementQuery — 현재 import 없음; intent 역할은 thyroid.py 의 IntentResult 가 담당
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# SHARED — 도메인 Enum (환자·의사 파이프라인 모두 사용)
# ══════════════════════════════════════════════════════════

class Decision(str, Enum):
    """[SHARED] DecisionEngine 최종 판단 6종 — LLM이 아닌 rule/evidence 로 결정."""
    RECOMMEND             = "recommend"
    CONDITIONAL_CONSIDER  = "conditional_consider"
    MANAGE_INTERACTION    = "manage_interaction"   # #4.1 성분 자체보다 LT4 병용 관리(분리·흡수)가 핵심
    AVOID                 = "avoid"
    CONTRAINDICATED       = "contraindicated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceLevel(str, Enum):
    """[SHARED] 논문·가이드라인 근거 강도."""
    # 연구 설계 기준
    GUIDELINE      = "guideline"
    META_ANALYSIS  = "meta_analysis"
    RCT            = "rct"
    OBSERVATIONAL  = "observational"
    MECHANISTIC       = "mechanistic"
    EXPERT_OPINION    = "expert_opinion"
    # 연구 설계 세부 — EVIDENCE_RANK 호환 (pubmed 반환값 ValueError 방지)
    COHORT            = "cohort"
    CASE_CONTROL      = "case_control"
    CASE_SERIES       = "case_series"
    CASE_REPORT       = "case_report"
    SYSTEMATIC_REVIEW = "systematic_review"
    # 강도 기반 레벨 — pubmed_postfilter 호환용
    HIGH           = "high"
    MODERATE       = "moderate"
    LOW_MODERATE   = "low-moderate"
    LOW            = "low"
    INSUFFICIENT   = "insufficient"


class WarningSeverity(str, Enum):
    """[SHARED] 안전 경고 심각도.
    CRITICAL → orchestrator 에서 즉시 CONTRAINDICATED early exit."""
    INFO     = "info"
    CAUTION  = "caution"
    WARNING  = "warning"
    CRITICAL = "critical"


# ══════════════════════════════════════════════════════════
# SHARED — 파이프라인 입력 (환자·의사 모두 사용)
# profile.build_patient_profile() 이 Thyroid*Request → 이 모델로 변환
# ══════════════════════════════════════════════════════════

class PatientProfile(BaseModel):
    """[SHARED] 결정용 환자 임상 프로필.

    주의: domain/auth/ 의 PatientProfile(회원 DB) 과 이름만 같고 다른 클래스.
    profile.build_patient_profile() 이 한국어 진단명을 canonical 영어 key 로 변환해 생성.
    """
    diagnosis:           List[str] = Field(default_factory=list, description="진단명 목록 (canonical key), e.g. ['hypothyroidism','hashimoto']")
    lab_values:          dict      = Field(default_factory=dict,  description="검사값, e.g. {'TSH': 8.5, 'freeT4': 0.6}")
    symptoms:            List[str] = Field(default_factory=list,  description="현재 증상")
    medications:         List[str] = Field(default_factory=list,  description="복용 중인 약물")
    current_supplements: List[str] = Field(default_factory=list,  description="현재 복용 중인 영양제")
    dietary_habits:      Optional[str] = None
    risk_factors:        List[str] = Field(default_factory=list,  description="위험요인: pregnancy, lactation, pediatric, elderly 등")
    age:                 Optional[int]   = None
    sex:                 Optional[str]   = None
    height_cm:           Optional[float] = None
    weight_kg:           Optional[float] = None
    past_history:        List[str] = Field(default_factory=list,  description="§15.1 병력 (과거 진단/질환)")
    surgical_history:    List[str] = Field(default_factory=list,  description="§15.1 수술력 (갑상선 절제술 등)")

    @property
    def bmi(self) -> Optional[float]:
        """§15.1 키·몸무게 기반 BMI (둘 다 있으면 계산, 소수1자리)."""
        if self.height_cm and self.weight_kg and self.height_cm > 0:
            h = self.height_cm / 100.0
            return round(self.weight_kg / (h * h), 1)
        return None


# ══════════════════════════════════════════════════════════
# DOCTOR-ONLY — 파이프라인 (의사 API 전용)
# decision.py / DoctorResponseFormatter 에서만 사용
# ══════════════════════════════════════════════════════════

class PhysicianProfile(BaseModel):
    """[DOCTOR-ONLY] 의사 성향 프로필.

    supplement_attitude → 상담 문구 톤 결정.
    risk_tolerance      → decision.py 에서 RECOMMEND → CONDITIONAL 강등 여부.
    """
    specialty:            Optional[str] = None
    years_experience:     Optional[int] = None
    supplement_attitude:  str = Field(default="neutral",   description="positive / neutral / cautious")
    risk_tolerance:       str = Field(default="moderate",  description="aggressive / moderate / conservative")
    guideline_preference: Optional[str] = None


# ══════════════════════════════════════════════════════════
# SHARED — 파이프라인 중간 산출물 (환자·의사 모두 사용)
# ══════════════════════════════════════════════════════════

class EvidenceRecord(BaseModel):
    """[SHARED] PubMed 등 외부 근거 1건.
    PubMed orchestrator → orchestrator.evidence_records → DecisionResult.evidence_records.
    """
    pmid:           Optional[str]  = None
    title:          str            = ""
    abstract:       Optional[str]  = None
    journal:        Optional[str]  = None
    year:           Optional[int]  = None
    evidence_level: EvidenceLevel  = EvidenceLevel.INSUFFICIENT
    source_type:    str            = Field(default="unknown", description="pubmed / guideline / nih_ods / who / mfds 등")
    url:            Optional[str]  = None
    journal_tier:   Optional[str]  = None  # A/B/C/D or None


class SafetyWarning(BaseModel):
    """[SHARED] SafetyEngine 이 생성하는 경고 1건.
    severity=CRITICAL → orchestrator 에서 즉시 CONTRAINDICATED 반환 (early exit).
    """
    category:           str            = Field(description="iodine_excess / selenium_toxicity / drug_interaction 등")
    message:            str
    severity:           WarningSeverity = WarningSeverity.CAUTION
    recommended_action: str            = Field(
        default="",
        description="권장 조치, e.g. '전문의 상담 후 복용 결정', '복용 중단 후 재평가'",
    )


class DecisionResult(BaseModel):
    """[SHARED] DecisionEngine 최종 판단 — 다운스트림(response, logging)의 단일 입력.

    흐름: orchestrator → DecisionResult → PatientResponseFormatter / DoctorResponseFormatter
                                        → generate_chat_response (LLM 자연어)
                                        → DecisionAuditLogger (JSONL)
    """
    decision:        Decision
    supplement_name: str
    confidence:      str          = Field(default="low",            description="high / medium / low")
    safety_warnings: List[SafetyWarning]  = Field(default_factory=list)
    evidence_records: List[EvidenceRecord] = Field(default_factory=list)
    rationale:       str          = Field(default="",              description="판단 근거 요약 (1–3문장)")
    recommendations:        List[str]        = Field(default_factory=list, description="구체적 권고 목록")
    counseling_points:      List[str]        = Field(default_factory=list, description="복용 방법·주의사항 (rule 정의)")
    monitoring_parameters:  List[str]        = Field(default_factory=list, description="추적 검사 항목 (의사 전용)")
    pre_physician_decision: Optional[Decision] = Field(default=None, description="의사 성향 조정 전 원래 decision — 조정 없으면 None")
    applied_rules:          List[str]        = Field(default_factory=list, description="적용된 rule id 목록 (디버깅용)")
    regimen_assessment:     Optional[dict]   = Field(default=None, description="§7.2 복용 간격 판정 {status, lt4_hour, supplement_hour} — MANAGE_INTERACTION 한정")


# ══════════════════════════════════════════════════════════
# PATIENT API OUT — 환자 HTTP 응답
# POST /api/v1/patient/thyroid-chat → PatientResponseFormatter → 이 모델
# ══════════════════════════════════════════════════════════

class PatientResponse(BaseModel):
    """[PATIENT API OUT] 환자용 최종 HTTP 응답.
    PatientResponseFormatter(DecisionResult) → 이 모델 → 프론트/챗봇.
    """
    summary:                      str            = Field(description="쉬운 설명 (1–2문장)")
    # §7.2 완화된 문구: '근거 있음 (상담 권고)' / '조건부 확인 필요' / '주의 필요 (상담 필수)' /
    #                  '금기 자료 있음 (상담 필수)' / '근거 제한적' / '정보필요' / '해당없음'
    can_take:                     str            = Field(description="복용 관련 요약 상태 (단정 지시가 아닌 근거·상담 중심 표현)")
    cautions:                     List[str]      = Field(default_factory=list)
    next_actions:                 List[str]      = Field(default_factory=list, description="다음 행동 권고")
    consult_doctor:               bool           = Field(default=True,         description="의사 상담 권고 여부")
    evidence_summary:             Optional[str]  = None
    chat_message:                 Optional[str]  = Field(default=None,         description="LLM 자연어 응답 (대화체); 없으면 summary 사용")
    evidence_level:               Optional[str]  = Field(default=None,         description="근거 수준 (guideline/rct/observational 등)")
    research_dose_summary:        Optional[str]  = Field(default=None,         description="§9.2 연구 사용 용량 및 공식 기준/상한 요약 (하위호환 합본)")
    research_dose:                Optional[str]  = Field(default=None,         description="§9.2 연구에서 사용된 용량 (단독)")
    official_dose_reference:      Optional[dict] = Field(default=None,         description="§9.2 공식 기준/상한 {text, source, limit_value}")
    reported_effects_summary:     Optional[str]  = Field(default=None,         description="보고된 효과 및 주요 부작용 요약")
    patient_factors:              List[str]      = Field(default_factory=list, description="lab values / 특수군 기반 확인 필요 사항")
    uncertainty_notes:            List[str]      = Field(default_factory=list, description="근거 한계 및 불확실성 안내")
    identified_supplement:        Optional[str]  = Field(default=None,         description="인식된 영양제 canonical key")
    identified_supplement_display: Optional[str] = Field(default=None,         description="인식된 영양제 표시명")
    identified_medications:       Optional[str]  = Field(default=None,         description="인식된 갑상선 관련 복용 약물")
    identified_conditions:        Optional[str]  = Field(default=None,         description="인식된 진단명/질환")
    top_warnings:                 List[dict] = Field(
        default_factory=list,
        description="CRITICAL/WARNING 경고 카드 최상단 노출용 [{message, severity, recommended_action}]"
    )
    iodine_pregnancy_alert:       Optional[dict] = Field(
        default=None,
        description="임신+iodine 조합 전용 강조 블록 {deficiency_risk, excess_risk, official_standard, action}"
    )
    # §6.2 브랜드명→제품 후보 (복수 제품 히트 시 재질문용). 프론트는 클릭형 칩으로 렌더.
    clarification_candidates:     List[str]      = Field(
        default_factory=list,
        description="§6.2 브랜드/제품명 재질문 후보 목록 (클릭 시 해당 제품명으로 재질의)"
    )
    # §15.3 일반 정보 vs 개인화 판단 모드 구분
    response_mode:                Optional[Literal["general", "personalized"]] = Field(
        default=None,
        description="'general': 진단/약물 정보 없이 일반 정보 제공 모드 / 'personalized': 개인 프로필 기반 판단 모드"
    )
    # §7.2 복용 간격 판정 (MANAGE_INTERACTION 한정) — 프론트 뱃지/색 매핑용
    regimen_assessment:           Optional[dict] = Field(
        default=None,
        description="§7.2 {status: separated|concurrent|unknown, lt4_hour, supplement_hour}"
    )


# ══════════════════════════════════════════════════════════
# DOCTOR API OUT — 의사 HTTP 응답
# POST /api/v1/doctor/thyroid-consult → DoctorResponseFormatter → 이 모델
# ══════════════════════════════════════════════════════════

class DoctorResponse(BaseModel):
    """[DOCTOR API OUT] 의사용 최종 HTTP 응답.
    DoctorResponseFormatter(DecisionResult, PhysicianProfile) → 이 모델 → 의사 UI.
    """
    conclusion:        str         = Field(description="요약 결론")
    decision:          Decision
    # §14.4 시스템 제안 결정 vs 의사 성향 조정 결정 분리 (optional)
    # system_suggested_decision: 성향 조정 전 원래 rule/safety 기반 결정
    # decision: 최종 적용 결정 (현재는 동일; 의사가 override 할 경우 physician_adjusted_decision 필드 추가 가능)
    system_suggested_decision:   Optional[Decision] = Field(default=None, description="§14.4 의사 성향 조정 전 순수 시스템 결정")
    physician_adjusted_decision: Optional[Decision] = Field(default=None, description="§14.4 의사 성향 조정 후 결정 (조정 없으면 None)")
    evidence_level:              str                = Field(default="insufficient")
    key_references:              List[str]          = Field(default_factory=list)
    safety_concerns:             List[str]          = Field(default_factory=list)
    patient_factors:             List[str]          = Field(default_factory=list, description="환자 성향 반영 포인트")
    counseling_points:           List[str]          = Field(default_factory=list, description="상담 시 활용 문구")
    monitoring_parameters:       List[str]          = Field(default_factory=list, description="추적 검사 항목")
    regulatory_note:             Optional[str]      = Field(default=None, description="§16.2-7 약전/MFDS/규제기관 안전성 note")
    guideline_conflict:          Optional[str]      = Field(default=None, description="§10.3 가이드라인 vs 개별 논문 충돌 안내 (없으면 None)")
    research_dose_summary:       Optional[str]      = Field(default=None, description="§9.2 연구 사용 용량 및 공식 기준 요약 (하위호환 합본)")
    research_dose:               Optional[str]      = Field(default=None, description="§9.2 연구에서 사용된 용량 (단독)")
    official_dose_reference:     Optional[dict]     = Field(default=None, description="§9.2 공식 기준/상한 {text, source, limit_value}")
    reported_effects_summary:    Optional[str]      = Field(default=None, description="§8.1 보고된 효과 및 부작용 요약")
    uncertainty_notes:           List[str]          = Field(default_factory=list)
    evidence_summaries:          List[dict]         = Field(default_factory=list, description="PubMed 논문 요약 목록 [{title,pmid,year,journal,abstract_snippet,evidence_level}]")
    physician_note:              Optional[str]      = Field(default=None, description="§14.4 의사 자유 코멘트 (요청 시 입력, 응답에 에코)")
    regimen_assessment:          Optional[dict]     = Field(default=None, description="§7.2 복용 간격 판정 {status, lt4_hour, supplement_hour} — MANAGE_INTERACTION 한정")
    decision_trace:              Optional[dict]     = Field(default=None, description="결정론 추적: {decision, system_suggested, applied_rules:[{code,label}], evidence_level, safety_flags} — LLM이 아닌 규칙이 판정했음을 의사 UI에 가시화")


