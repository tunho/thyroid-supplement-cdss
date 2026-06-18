"""
domain.thyroid.mfds_service — MFDS / 식품안전나라 안전성 정보 조회

MFDS_API_KEY 환경변수 없어도 fallback 테이블로 동작.
모든 IO는 try/except로 보호 — 실패해도 서버 다운 없음.
"""
from __future__ import annotations

import logging
import os
import re
from typing import List

from domain.thyroid.schemas import SafetyWarning, WarningSeverity

logger = logging.getLogger(__name__)

MFDS_API_KEY = os.getenv("MFDS_API_KEY", "")

# MFDS 2023 기준 일일 최대 허용 섭취량 (보충제 기준) — DB 미등록 원료의 fallback
_MFDS_UL: dict[str, dict] = {
    "iodine":    {"ul": 2400, "unit": "µg/일",  "source": "MFDS 2023"},
    "selenium":  {"ul": 400,  "unit": "µg/일",  "source": "MFDS 2023"},
    "zinc":      {"ul": 35,   "unit": "mg/일",  "source": "MFDS 2023"},
    "vitamin_d": {"ul": 4000, "unit": "IU/일",  "source": "MFDS 2023"},
    "magnesium": {"ul": 350,  "unit": "mg/일",  "source": "MFDS 2023 (보충제)"},
    "iron":      {"ul": 45,   "unit": "mg/일",  "source": "MFDS 2023"},
    "omega3":    {"ul": 3000, "unit": "mg/일",  "source": "MFDS 2023 (EPA+DHA 합산)"},
    "calcium":   {"ul": 2500, "unit": "mg/일",  "source": "MFDS 2023"},
    "vitamin_b12": None,  # MFDS 공식 UL 미설정 — 경고 생략
}

# 주의사항 텍스트에서 감지할 키워드 → (category, severity, 경고 메시지 prefix)
_CAUTION_PATTERNS: list[tuple] = [
    (r"임산부|임부|수유부|수유|임신",
     "pregnancy_lactation", WarningSeverity.WARNING,
     "식약처 개별인정형 원료 정보: 임산부/수유부 섭취 주의"),
    (r"혈압약|혈압\s*약|항고혈압",
     "drug_interaction", WarningSeverity.WARNING,
     "식약처 개별인정형 원료 정보: 혈압약 복용 시 전문의 상담 필요"),
    (r"항응고|와파린|warfarin|혈액희석",
     "anticoagulant_interaction", WarningSeverity.WARNING,
     "식약처 개별인정형 원료 정보: 항응고제 복용 시 주의"),
    (r"노인|고령|신부전|신기능",
     "elderly_caution", WarningSeverity.CAUTION,
     "식약처 개별인정형 원료 정보: 노인/신기능 저하 시 주의"),
    (r"어린이|소아|영유아",
     "pediatric_caution", WarningSeverity.CAUTION,
     "식약처 개별인정형 원료 정보: 소아/어린이 섭취 주의"),
    (r"당뇨|혈당",
     "drug_interaction", WarningSeverity.CAUTION,
     "식약처 개별인정형 원료 정보: 당뇨/혈당약 복용 시 주의"),
]


def _parse_caution_warnings(
    supplement_name: str,
    caution_text: str,
    daily_intake: str,
) -> List[SafetyWarning]:
    """intake_caution 텍스트를 파싱해 SafetyWarning 목록 생성."""
    warnings: List[SafetyWarning] = []
    seen_categories: set[str] = set()

    for pattern, category, severity, prefix in _CAUTION_PATTERNS:
        if category in seen_categories:
            continue
        if re.search(pattern, caution_text, re.IGNORECASE):
            seen_categories.add(category)
            warnings.append(SafetyWarning(
                category=category,
                message=f"{prefix}: {caution_text[:120]}",
                severity=severity,
                recommended_action="복용 전 전문의 또는 약사와 상담하시기 바랍니다.",
            ))

    # 1일 섭취량 정보가 있으면 INFO로 추가
    if daily_intake and daily_intake not in (".", "-", ""):
        warnings.append(SafetyWarning(
            category="mfds_daily_intake",
            message=f"[식약처 개별인정형] {supplement_name} 1일 섭취량 기준: {daily_intake[:100]}",
            severity=WarningSeverity.INFO,
            recommended_action=f"1일 섭취량 기준({daily_intake[:60]})을 초과하지 않도록 확인하시기 바랍니다.",
        ))

    return warnings


def get_mfds_ingredient_warnings(supplement_name: str) -> List[SafetyWarning]:
    """
    health_food_ingredient(I-0040) DB에서 원료명 퍼지 검색 후
    intake_caution → SafetyWarning 목록 반환.
    실패 시 빈 리스트.
    """
    try:
        from domain.mfds.db import search_ingredient_info
        results = search_ingredient_info(supplement_name)
        if not results:
            return []

        warnings: List[SafetyWarning] = []
        seen_categories: set[str] = set()

        for row in results[:3]:  # 중복 방지: 상위 3건만
            caution = (row.get("intake_caution") or "").strip()
            daily = (row.get("daily_intake") or "").strip()
            if not caution and not daily:
                continue
            for w in _parse_caution_warnings(supplement_name, caution, daily):
                if w.category not in seen_categories:
                    seen_categories.add(w.category)
                    warnings.append(w)

        return warnings
    except Exception as e:
        logger.error(f"DB ingredient 조회 실패: {e}", exc_info=True)
        return []


def get_mfds_safety_warnings(supplement_name: str) -> List[SafetyWarning]:
    """
    1) DB(I-0040)에서 동적 주의사항 조회
    2) 하드코딩 _MFDS_UL로 상한선 경고 (fallback)
    실패 시 빈 리스트.
    """
    warnings: List[SafetyWarning] = []

    # ① DB 동적 주의사항
    warnings.extend(get_mfds_ingredient_warnings(supplement_name))

    # ② 하드코딩 UL (셀레늄/아연/요오드 등 DB 미등록 원료 커버)
    try:
        canonical = supplement_name.strip().lower().replace(" ", "_").replace("-", "_")
        info = _MFDS_UL.get(canonical)
        if info:
            warnings.append(SafetyWarning(
                category="mfds_upper_limit",
                message=(
                    f"[{info['source']}] {supplement_name} 일일 최대 허용 섭취량: "
                    f"{info['ul']} {info['unit']}. 초과 복용 시 독성 위험."
                ),
                severity=WarningSeverity.INFO,
                recommended_action=(
                    f"{supplement_name} 복용량이 {info['ul']} {info['unit']}을 "
                    f"초과하지 않도록 확인하시기 바랍니다."
                ),
            ))
    except Exception as e:
        logger.error(f"MFDS UL 경고 생성 실패: {e}", exc_info=True)

    return warnings
