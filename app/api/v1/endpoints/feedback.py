"""
app.api.v1.endpoints.feedback — 피드백 API

POST /feedback/case            케이스 피드백 제출 (JWT 필수)
POST /feedback/general         일반 피드백 제출 (JWT 필수)
GET  /feedback/cases           케이스 피드백 목록 (status 필터, JWT 필수)
GET  /feedback/general-list    일반 피드백 목록 (status 필터, JWT 필수)
POST /feedback/cases/{id}/reply   팀 답변 (JWT 필수)
POST /feedback/general/{id}/reply 팀 답변 (JWT 필수)
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from domain.auth.auth_service import verify_token
from domain.thyroid.feedback import FeedbackLogger

router = APIRouter()
_feedback = FeedbackLogger()

# 운영자 doctor_id 목록 (이 ID로 로그인하면 전체 목록 + 답변 폼 노출)
ADMIN_DOCTOR_IDS: set[str] = {"dr_lee"}


# ──────────────────────────────────────────────────────────
# Request / Response 모델
# ──────────────────────────────────────────────────────────

class CaseFeedbackSubmit(BaseModel):
    consult_input: dict = Field(description="의사 폼 입력 전체 (supplement, conditions, lab_values 등)")
    consult_message: str = Field(default="", description="자연어 질문")
    consult_response: dict = Field(description="DoctorResponse 전체 JSON")
    ratings: dict = Field(
        default_factory=dict,
        description="{'overall': 'appropriate|needs_revision|unsafe', 'pubmed': 'ok|wrong|missing', 'counseling': 'ok|wrong|missing'}",
    )
    comment: str = Field(default="", max_length=2000)


class GeneralFeedbackSubmit(BaseModel):
    category: str = Field(
        default="other",
        description="rule | pubmed | ui | other",
    )
    message: str = Field(min_length=1, max_length=2000)


class ReplySubmit(BaseModel):
    reply_text: str = Field(min_length=1, max_length=2000)


class FeedbackSubmitResponse(BaseModel):
    id: str
    status: str = "saved"


# ──────────────────────────────────────────────────────────
# 케이스 피드백
# ──────────────────────────────────────────────────────────

@router.post("/case", response_model=FeedbackSubmitResponse)
def submit_case_feedback(
    body: CaseFeedbackSubmit,
    token_data: dict = Depends(verify_token),
):
    reviewer_id = token_data.get("sub", "unknown")
    feedback_id = _feedback.submit_case(
        reviewer_id=reviewer_id,
        consult_input=body.consult_input,
        consult_message=body.consult_message,
        consult_response=body.consult_response,
        ratings=body.ratings,
        comment=body.comment,
    )
    return FeedbackSubmitResponse(id=feedback_id)


@router.get("/cases")
def list_case_feedbacks(
    status: Optional[str] = Query(default=None, description="pending | replied"),
    token_data: dict = Depends(verify_token),
) -> list[dict[str, Any]]:
    reviewer_id = token_data.get("sub", "unknown")
    # 운영자면 전체, 아니면 본인 것만
    if reviewer_id in ADMIN_DOCTOR_IDS:
        return _feedback.list_cases(status=status)
    return _feedback.list_cases(status=status, reviewer_id=reviewer_id)


@router.post("/cases/{feedback_id}/reply", response_model=FeedbackSubmitResponse)
def reply_case_feedback(
    feedback_id: str,
    body: ReplySubmit,
    token_data: dict = Depends(verify_token),
):
    reviewer_id = token_data.get("sub", "unknown")
    if reviewer_id not in ADMIN_DOCTOR_IDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="팀 답변은 운영자만 작성할 수 있습니다.",
        )
    ok = _feedback.reply_case(feedback_id, body.reply_text)
    if not ok:
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    return FeedbackSubmitResponse(id=feedback_id, status="replied")


# ──────────────────────────────────────────────────────────
# 일반 피드백
# ──────────────────────────────────────────────────────────

@router.post("/general", response_model=FeedbackSubmitResponse)
def submit_general_feedback(
    body: GeneralFeedbackSubmit,
    token_data: dict = Depends(verify_token),
):
    reviewer_id = token_data.get("sub", "unknown")
    feedback_id = _feedback.submit_general(
        reviewer_id=reviewer_id,
        category=body.category,
        message=body.message,
    )
    return FeedbackSubmitResponse(id=feedback_id)


@router.get("/general-list")
def list_general_feedbacks(
    status: Optional[str] = Query(default=None, description="pending | replied"),
    token_data: dict = Depends(verify_token),
) -> list[dict[str, Any]]:
    reviewer_id = token_data.get("sub", "unknown")
    if reviewer_id in ADMIN_DOCTOR_IDS:
        return _feedback.list_general(status=status)
    return _feedback.list_general(status=status, reviewer_id=reviewer_id)


@router.post("/general/{feedback_id}/reply", response_model=FeedbackSubmitResponse)
def reply_general_feedback(
    feedback_id: str,
    body: ReplySubmit,
    token_data: dict = Depends(verify_token),
):
    reviewer_id = token_data.get("sub", "unknown")
    if reviewer_id not in ADMIN_DOCTOR_IDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="팀 답변은 운영자만 작성할 수 있습니다.",
        )
    ok = _feedback.reply_general(feedback_id, body.reply_text)
    if not ok:
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    return FeedbackSubmitResponse(id=feedback_id, status="replied")
