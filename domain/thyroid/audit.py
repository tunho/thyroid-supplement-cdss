"""
domain.thyroid.audit — 의사결정 감사 로거

DecisionResult와 요청 메타데이터를 JSON Lines 파일로 기록합니다.
데이터/index가 없어도 서버가 죽지 않도록 모든 IO를 try/except로 보호합니다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from domain.thyroid.schemas import DecisionResult

logger = logging.getLogger(__name__)

# 기본 로그 저장 경로 (프로젝트 루트/data/audit/)
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "audit"


class DecisionAuditLogger:
    """Decision audit — JSON Lines append."""

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or _DEFAULT_LOG_DIR

    def log(
        self,
        *,
        decision_result: DecisionResult,
        response_type: str = "unknown",  # "patient" or "doctor"
        request_summary: dict | None = None,
        physician_profile: dict | None = None,
        extra: dict | None = None,
    ) -> None:
        """DecisionResult + 메타데이터를 audit 로그 파일에 1줄로 추가."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_path = self.log_dir / f"decisions_{today}.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "response_type": response_type,
                "supplement": decision_result.supplement_name,
                "decision": decision_result.decision.value,
                "confidence": decision_result.confidence,
                "applied_rules": decision_result.applied_rules,
                "safety_warning_count": len(decision_result.safety_warnings),
                "evidence_count": len(decision_result.evidence_records),
                "rationale": decision_result.rationale[:500],
                "request_summary": request_summary or {},
                "physician_profile": physician_profile or {},
            }
            if extra:
                record["extra"] = extra

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except Exception as e:
            # 로깅 실패로 서버가 죽으면 안 됨
            logger.error(f"Audit log 기록 실패: {e}", exc_info=True)
