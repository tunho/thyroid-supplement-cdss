"""
domain.thyroid.evidence_rank — 근거 수준 우선순위 (§10)

교수님 답변 기반 근거 우선순위 (§10.1):
  1. Guideline
  2. Meta-analysis
  3. RCT
  4. Cohort study
  5. Case-control study
  6. Case series / case report
  7. Mechanistic study 또는 기타

가이드라인 vs 개별 논문 충돌 시 (§10.3):
  - 기본적으로 guideline 우선
  - 충돌 정보는 rationale 에 함께 표시
"""

from __future__ import annotations

from typing import List

from domain.thyroid.schemas import EvidenceRecord, EvidenceLevel


# ── §10.2 Evidence rank 상수 ──────────────────────────────
# [REVIEW_NEEDED] EBM 피라미드 기반 수치 — 순서 및 간격이 적절한지 확인 필요
EVIDENCE_RANK: dict[str, int] = {
    "guideline":         7,
    "meta_analysis":     6,
    "systematic_review": 6,   # 통계 합성 없는 체계적 고찰 (meta_analysis와 동급)
    "rct":               5,
    "high":           5,   # pubmed_postfilter 호환
    "clinical":       5,
    "cohort":         4,
    "moderate":       4,
    "case_control":   3,
    "observational":  3,
    "low-moderate":   3,   # EvidenceLevel enum raw value
    "low_moderate":   3,   # rank_evidence() normalize 후 조회 키
    "case_series":    2,
    "case_report":    2,
    "mechanistic":    1,
    "low":            1,
    "expert_opinion": 1,
    "insufficient":   0,
    "unknown":        0,
}


def rank_evidence(level: str) -> int:
    """EvidenceLevel 문자열을 정수 rank 로 변환."""
    return EVIDENCE_RANK.get(level.lower().replace("-", "_"), 0)


def best_evidence_level(records: List[EvidenceRecord]) -> str:
    """레코드 목록에서 가장 높은 evidence level 문자열 반환."""
    if not records:
        return "insufficient"
    return max(
        (r.evidence_level.value for r in records if r.evidence_level),
        key=rank_evidence,
        default="insufficient",
    )


def sort_evidence_by_rank(records: List[EvidenceRecord]) -> List[EvidenceRecord]:
    """§10 우선순위에 따라 레코드를 내림차순 정렬 (guideline 최상단)."""
    return sorted(
        records,
        key=lambda r: rank_evidence(r.evidence_level.value if r.evidence_level else "unknown"),
        reverse=True,
    )


def detect_guideline_conflict(records: List[EvidenceRecord]) -> str | None:
    """
    §10.3 가이드라인 vs 개별 논문 충돌 감지.
    guideline 레코드와 rct/meta_analysis 레코드가 모두 있을 때 안내 문구 반환.
    충돌이 없으면 None 반환.
    """
    has_guideline = any(
        r.evidence_level and r.evidence_level.value == "guideline"
        for r in records
    )
    has_higher_study = any(
        r.evidence_level and rank_evidence(r.evidence_level.value) >= rank_evidence("rct")
        and r.evidence_level.value != "guideline"
        for r in records
    )
    if has_guideline and has_higher_study:
        return (
            "[참고] 가이드라인 권고와 개별 임상 연구 결과 간에 차이가 있을 수 있습니다. "
            "기본적으로 가이드라인을 우선하되, 최신 연구 방향도 함께 검토하시기 바랍니다."
        )
    return None
