"""§7.2 Regimen-aware 복용 간격 판정 (결정론적, LLM 미사용).

manage_interaction taxonomy(#4.1) 위에 얹는 레이어. LT4 와 흡수저해 성분의
*입력된 복용 타이밍*을 읽어 이미 분리돼 있는지(SEPARATED) / 같은 시간대인지
(CONCURRENT) / 정보가 없는지(UNKNOWN)를 판정한다.

설계 원칙:
- 순수 함수 · 외부 호출 없음 · 테스트 가능.
- 타이밍을 못 읽으면 반드시 UNKNOWN → 호출부는 현행 일반론 유지(회귀 없음, additive).
- 자유 입력 텍스트에서 (성분 ↔ 시간대) 연관을 절(clause) 단위로 추출.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class RegimenStatus(str, Enum):
    SEPARATED = "separated"      # ≥ MIN_GAP_HOURS 분리 → 흡수 간섭 우려 낮음 (안심)
    CONCURRENT = "concurrent"    # 같은 시간대 → 흡수 간섭 우려 (분리 권장)
    UNKNOWN = "unknown"          # 타이밍 정보 부족 → 현행 일반론 유지


# LT4 흡수는 복용 후 ~4시간이 권고 기준(ATA 2014 Q3b). 그 이상 떨어지면 SEPARATED.
MIN_GAP_HOURS = 4

# 시간대 토큰 → 대표 시각(24h). 더 구체적인 토큰을 먼저 매칭하도록 정렬.
_TIME_TOKENS: list[tuple[str, int]] = [
    (r"자기\s*전|취침\s*전|취침|잠자기\s*전|자기전|잘\s*때|bedtime|before\s*bed", 22),
    (r"\b밤|저녁\s*식후|night", 21),
    (r"저녁|dinner|evening", 19),
    (r"오후|afternoon", 15),
    (r"점심|정오|낮|noon|midday|lunch", 12),
    (r"공복|기상\s*직후|기상|아침\s*식전|아침|오전|새벽|morning|empty\s*stomach|\bam\b", 7),
]


def _time_positions(text: str) -> list[tuple[int, int]]:
    """텍스트 내 모든 시간 토큰의 (위치, 시각) 목록. 명시 '오전/오후 N시' 포함."""
    out: list[tuple[int, int]] = []
    # 명시 시각: "오후 9시", "9시", "21시", "오전 7시", "9:00"
    for m in re.finditer(r"(오전|오후|am|pm)?\s*(\d{1,2})\s*(?:시|:00|:\d{2})", text):
        hour, period = int(m.group(2)), m.group(1)
        if period in ("오후", "pm") and hour < 12:
            hour += 12
        if period in ("오전", "am") and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            out.append((m.start(), hour))
    for pattern, hour in _TIME_TOKENS:
        for m in re.finditer(pattern, text):
            out.append((m.start(), hour))
    return out


# 절(clause) 경계 — 콤마·세미콜론·연결어미·접속사 'and'. 같은 성분의 시간은 같은 절에서.
_CLAUSE_DELIM = re.compile(r"[,;\n·]|\band\b|먹고|드시고|복용하고|하고")
# 동시 복용 단서 — 한쪽 시간만 읽혀도 같은 시간대(CONCURRENT)로 보강.
_CONCURRENT_CUE = re.compile(r"동시|같이|함께|둘\s*다|same\s*time|together|both")


def extract_timing(text: str, keywords: list[str]) -> Optional[int]:
    """`keywords` 성분의 복용 시각을 추출.

    절(clause) 단위 우선: 키워드와 *같은 절*에 있는 시간 토큰을 그 성분의 시각으로.
    같은 절에 없으면 전체에서 최근접 토큰으로 fallback(자연 문장 견고성 유지).
    시간 토큰이 전혀 없거나 키워드가 없으면 None(→ UNKNOWN 유도)."""
    if not text:
        return None
    low = text.lower()
    times = _time_positions(low)
    if not times:
        return None
    delims = [m.start() for m in _CLAUSE_DELIM.finditer(low)]

    def clause_id(pos: int) -> int:
        return sum(1 for d in delims if d <= pos)

    # 같은 성분이 여러 번 나오면(예: 본문 + 구조화 약물필드 중복) *가장 앞 언급*을 우선.
    same_candidates: list[tuple[int, int]] = []  # (keyword_pos, hour)
    any_hour: Optional[int] = None
    any_dist: Optional[int] = None
    for kw in (k.lower() for k in keywords if k):
        for km in re.finditer(re.escape(kw), low):
            kpos = km.start()
            kc = clause_id(kpos)
            occ_hour: Optional[int] = None
            occ_dist: Optional[int] = None
            for tpos, hour in times:
                dist = abs(tpos - kpos)
                if any_dist is None or dist < any_dist:
                    any_dist, any_hour = dist, hour
                if clause_id(tpos) == kc and (occ_dist is None or dist < occ_dist):
                    occ_dist, occ_hour = dist, hour
            if occ_hour is not None:
                same_candidates.append((kpos, occ_hour))
    if same_candidates:
        return min(same_candidates, key=lambda x: x[0])[1]  # 최선두 언급의 시각
    return any_hour


def assess_regimen(lt4_hour: Optional[int], supplement_hour: Optional[int]) -> RegimenStatus:
    """두 복용 시각으로 분리 상태 판정. 한쪽이라도 None이면 UNKNOWN(보수적)."""
    if lt4_hour is None or supplement_hour is None:
        return RegimenStatus.UNKNOWN
    gap = abs(lt4_hour - supplement_hour)
    gap = min(gap, 24 - gap)  # 하루 순환 고려 (23시 vs 1시 = 2h)
    return RegimenStatus.SEPARATED if gap >= MIN_GAP_HOURS else RegimenStatus.CONCURRENT


# LT4 제품명 (safety_rules.json `levothyroxine_mineral_interaction` 와 동일 어휘)
LT4_KEYWORDS = [
    "levothyroxine", "레보티록신", "씬지로이드", "신지로이드", "씬지",
    "levothroid", "synthroid", "갑상선 호르몬제", "갑상선호르몬제",
    "갑상선약", "갑상선 약", "갑상샘약", "갑상선호르몬", "갑상선 호르몬",
]


# LT4 흡수에 영향을 주는 미네랄의 한/영 동의어 (메시지 매칭용)
_INTERACTION_SUPPLEMENT_SYNONYMS: dict[str, list[str]] = {
    "magnesium": ["magnesium", "마그네슘", "마그"],
    "iron":      ["iron", "ferrous", "철분", "철"],
    "calcium":   ["calcium", "칼슘"],
    "zinc":      ["zinc", "아연"],
}


def supplement_keywords(canonical: Optional[str], display: Optional[str]) -> list[str]:
    """문의 성분의 매칭 키워드 (canonical 동의어 + 표시명)."""
    kws = list(_INTERACTION_SUPPLEMENT_SYNONYMS.get((canonical or "").lower(), []))
    for extra in (display, canonical):
        if extra and extra not in kws:
            kws.append(extra)
    return kws


def assess_from_text(
    text: str,
    supplement_keywords: list[str],
) -> tuple[RegimenStatus, Optional[int], Optional[int]]:
    """자유 입력 텍스트에서 LT4·문의성분 타이밍을 추출해 판정까지.

    반환: (status, lt4_hour, supplement_hour) — 호출부 디버그/표시용."""
    lt4_hour = extract_timing(text, LT4_KEYWORDS)
    supp_hour = extract_timing(text, supplement_keywords)
    # 동시 복용 단서: 한쪽만 시각이 읽혔는데 "같이/동시/둘 다" 등이 있으면 같은 시간대로 본다.
    if text and _CONCURRENT_CUE.search(text.lower()):
        if supp_hour is None and lt4_hour is not None:
            supp_hour = lt4_hour
        elif lt4_hour is None and supp_hour is not None:
            lt4_hour = supp_hour
    return assess_regimen(lt4_hour, supp_hour), lt4_hour, supp_hour
