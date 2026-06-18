"""
domain.thyroid.feedback — 의사 피드백 로거

케이스 피드백(상담 직후)과 일반 피드백(채널 2)을 JSONL로 저장·조회·회신한다.
audit.py와 동일 패턴(append-only JSONL, try/except 보호).

저장 파일:
  data/feedback/cases.jsonl   — 케이스 피드백 (전체 스냅샷)
  data/feedback/general.jsonl — 일반 피드백
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "feedback"


class FeedbackLogger:
    """JSONL 기반 피드백 저장·조회·회신."""

    def __init__(self, feedback_dir: Optional[Path] = None):
        self.feedback_dir = feedback_dir or _DEFAULT_FEEDBACK_DIR
        self._cases_path = self.feedback_dir / "cases.jsonl"
        self._general_path = self.feedback_dir / "general.jsonl"

    # ──────────────────────────────────────────────────────────
    # 케이스 피드백 (상담 전체 스냅샷 포함)
    # ──────────────────────────────────────────────────────────

    def submit_case(
        self,
        *,
        reviewer_id: str,
        consult_input: dict,
        consult_message: str,
        consult_response: dict,
        ratings: dict,
        comment: str = "",
    ) -> str:
        """케이스 피드백 1건을 저장하고 생성된 id를 반환한다."""
        feedback_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": feedback_id,
            "created_at": now,
            "reviewer_id": reviewer_id,
            "consult_input": consult_input,
            "consult_message": consult_message,
            "consult_response": consult_response,
            "feedback": {
                "submitted_at": now,
                "ratings": ratings,
                "comment": comment,
            },
            "team_reply": {
                "text": None,
                "replied_at": None,
                "status": "pending",
            },
        }
        self._append(self._cases_path, record)
        return feedback_id

    def list_cases(
        self,
        status: Optional[str] = None,
        reviewer_id: Optional[str] = None,
    ) -> list[dict]:
        """케이스 피드백 목록 반환 (status·reviewer_id 필터 선택)."""
        records = self._read_all(self._cases_path)
        if status:
            records = [r for r in records if r.get("team_reply", {}).get("status") == status]
        if reviewer_id:
            records = [r for r in records if r.get("reviewer_id") == reviewer_id]
        return records

    def reply_case(self, feedback_id: str, reply_text: str) -> bool:
        """케이스 피드백에 팀 답변을 기록한다."""
        return self._apply_reply(self._cases_path, feedback_id, reply_text)

    # ──────────────────────────────────────────────────────────
    # 일반 피드백 (채널 2 — 상담과 무관)
    # ──────────────────────────────────────────────────────────

    def submit_general(
        self,
        *,
        reviewer_id: str,
        category: str,
        message: str,
    ) -> str:
        """일반 피드백 1건을 저장하고 생성된 id를 반환한다."""
        feedback_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": feedback_id,
            "created_at": now,
            "reviewer_id": reviewer_id,
            "category": category,
            "message": message,
            "team_reply": {
                "text": None,
                "replied_at": None,
                "status": "pending",
            },
        }
        self._append(self._general_path, record)
        return feedback_id

    def list_general(
        self,
        status: Optional[str] = None,
        reviewer_id: Optional[str] = None,
    ) -> list[dict]:
        """일반 피드백 목록 반환."""
        records = self._read_all(self._general_path)
        if status:
            records = [r for r in records if r.get("team_reply", {}).get("status") == status]
        if reviewer_id:
            records = [r for r in records if r.get("reviewer_id") == reviewer_id]
        return records

    def reply_general(self, feedback_id: str, reply_text: str) -> bool:
        """일반 피드백에 팀 답변을 기록한다."""
        return self._apply_reply(self._general_path, feedback_id, reply_text)

    # ──────────────────────────────────────────────────────────
    # 공통 IO 헬퍼
    # ──────────────────────────────────────────────────────────

    def _append(self, path: Path, record: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"피드백 저장 실패 ({path.name}): {e}", exc_info=True)

    def _read_all(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        records = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            logger.error(f"피드백 읽기 실패 ({path.name}): {e}", exc_info=True)
        return records

    def _apply_reply(self, path: Path, feedback_id: str, reply_text: str) -> bool:
        """JSONL 전체 rewrite로 team_reply 갱신."""
        records = self._read_all(path)
        updated = False
        for r in records:
            if r.get("id") == feedback_id:
                r["team_reply"] = {
                    "text": reply_text,
                    "replied_at": datetime.now(timezone.utc).isoformat(),
                    "status": "replied",
                }
                updated = True
                break
        if not updated:
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"피드백 회신 저장 실패 ({path.name}): {e}", exc_info=True)
            return False
        return True
