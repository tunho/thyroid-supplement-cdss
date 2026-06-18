"""domain.thyroid.dose_safety — STEP 1 안전 트리거 (결정론, additive).

두 가지:
- `derive_lab_conditions`: lab 값 → *현재 상태* 조건 파생(예: calcium → hypercalcemia).
  decision 엔진의 avoid/contraindication 매칭 집합에 union (Fix A, #13).
  ※ past_history(과거 해소 질환)는 §15.1대로 미반영 — *현재 lab*만 사용.
- `assess_dose`: 입력 용량 추출 → 공식 상한섭취량(UL) 비교 → 'avoid'(UL 초과) /
  'caution'(운용상한 초과) / None(정상·미상). orchestrator에서 avoid 승격 (Fix B, #11).
  ※ 못 읽으면 None → 현행 유지(회귀 0). 단위 혼동(IU↔µg)이 최대 리스크라 supplement별 기준 고정.

UL 수치 출처: KDRI 2025 / NIH ODS (이미 룰에 존재하는 값).
"""
from __future__ import annotations

import re
from typing import Optional

# (UL value, UL unit, operational_ceiling | None). 출처 주석.
_SUPPLEMENT_UL: dict[str, tuple[float, str, Optional[float]]] = {
    "selenium":  (400.0, "µg", 200.0),   # [NIH-ODS/KDRI] UL 400µg; [갑상선 운용상한] 200µg
    "vitamin_d": (4000.0, "IU", None),   # [NIH-ODS/KDRI] UL 4,000 IU (=100µg)
    "iron":      (45.0, "mg", None),     # [NIH-ODS/KDRI] UL 45mg (일반 보충)
    "zinc":      (40.0, "mg", None),     # [NIH-ODS] UL 40mg
    "magnesium": (350.0, "mg", None),    # [NIH-ODS] 보충제 UL 350mg
    "iodine":    (1100.0, "µg", None),   # [NIH-ODS] 성인 UL 1,100µg
}

_KO_BIGNUM = {"만": 10000, "천": 1000}


def _norm_unit(u: str) -> Optional[str]:
    u = u.lower().strip()
    if u in ("µg", "ug", "mcg", "마이크로그램", "마이크로그람"):
        return "µg"
    if u in ("mg", "밀리그램", "밀리그람"):
        return "mg"
    if u in ("iu", "아이유"):
        return "IU"
    return None


_UNIT_RE = r"(iu|아이유|mg|밀리그램|밀리그람|µg|ug|mcg|마이크로그램|마이크로그람)"


def extract_dose(text: str) -> Optional[tuple[float, str]]:
    """자유 텍스트에서 (값, 단위) 추출. 못 읽으면 None(→ 보류)."""
    if not text:
        return None
    t = text.lower()
    # "5천 IU", "1만 mcg", "천 mg", "만 IU"  (N천/N만 = N×1000 / N×10000, N 생략 시 1)
    m = re.search(rf"(\d[\d,]*(?:\.\d+)?)?\s*(만|천)\s*{_UNIT_RE}", t)
    if m:
        unit = _norm_unit(m.group(3))
        if unit:
            mult = float(m.group(1).replace(",", "")) if m.group(1) else 1.0
            return (mult * _KO_BIGNUM[m.group(2)], unit)
    # "300µg", "10,000 IU", "350 mg"
    m = re.search(rf"([\d,]+(?:\.\d+)?)\s*{_UNIT_RE}", t)
    if m:
        unit = _norm_unit(m.group(2))
        if unit:
            return (float(m.group(1).replace(",", "")), unit)
    return None


def _convert(val: float, unit: str, target: str, canonical: str) -> Optional[float]:
    if unit == target:
        return val
    if canonical == "vitamin_d":          # 40 IU = 1 µg
        if unit == "µg" and target == "IU":
            return val * 40
        if unit == "IU" and target == "µg":
            return val / 40
    if unit == "µg" and target == "mg":
        return val / 1000
    if unit == "mg" and target == "µg":
        return val * 1000
    return None  # 변환 불가 → 보류


# [traceability 완전성] 용량/UL 관련 applied_rule 태그 → 가이드라인 출처.
#   cited_sources.json(rules.py+safety_rules.json 스캔)은 dose_safety를 못 보므로 여기 명시.
#   감사 스크립트가 dose 결정의 출처를 기계가독으로 검증 가능.
DOSE_TAG_SOURCES: dict[str, list[str]] = {
    "dose_exceeds_ul":               ["NIH-ODS", "KDRI2025"],          # 공식 UL
    "iodine_pregnancy_dose_ceiling": ["ATA2017-RecIV-10"],             # 임신·수유 500µg
    "ul_standard_comparison":        ["NIH-ODS", "KDRI2025", "MFDS"],  # 국가기준 비교
}


# [임신·수유 요오드 상한] 전역 UL(1,100µg)보다 엄격. ATA 2017 §IV Rec 10:
#   임신·수유 중 500µg/일 초과 또는 켈프 형태 요오드 보충 회피(태아 갑상선 억제·갑상선종).
_IODINE_PREGNANCY_CEILING_UG = 500.0


def assess_dose(canonical: Optional[str], text: str,
                conditions: Optional[set] = None) -> Optional[str]:
    """'avoid'(UL 초과) / 'caution'(운용상한 초과·UL 이하) / None(정상·미상·미파싱).

    conditions: 환자 조건 canonical 집합(예: {'pregnancy'}). 맥락 상한 적용용(하위호환: None=현행).
    """
    info = _SUPPLEMENT_UL.get((canonical or "").lower())
    if not info:
        return None
    ul, ul_unit, op = info
    parsed = extract_dose(text)
    if not parsed:
        return None
    val_cmp = _convert(parsed[0], parsed[1], ul_unit, (canonical or "").lower())
    if val_cmp is None:
        return None
    # 맥락 상한: 임신·수유 중 요오드는 전역 UL보다 엄격한 500µg (ATA 2017 §IV Rec 10).
    if (canonical or "").lower() == "iodine" and ul_unit == "µg" and conditions:
        _c = {str(x).lower() for x in conditions}
        if ({"pregnancy", "lactation"} & _c) and val_cmp > _IODINE_PREGNANCY_CEILING_UG:
            return "avoid"
    if val_cmp > ul:
        return "avoid"
    if op is not None and val_cmp > op:
        return "caution"
    return None


# UL 국가기준 상이(NIH vs KDRI/MFDS) — 비교 출력용(§A-1). 결정은 NIH(보수) 기준 유지, 주석만 추가.
_DUAL_UL: dict[str, dict] = {
    "iodine": {"unit": "µg", "nih": 1100.0, "kdri": 2400.0},   # NIH 1,100 / MFDS·KDRI 2,400
    "zinc":   {"unit": "mg", "nih": 40.0,   "kdri": 35.0},     # NIH 40 / KDRI 35
}


def dual_ul_comparison(canonical: Optional[str], text: str) -> Optional[str]:
    """UL 국가기준이 상이한 성분(iodine·zinc)에서 입력 용량 ↔ 양 기준 비교 주석.

    §A-1: 추적성·투명성용. **결정을 바꾸지 않는다**(시스템 결정은 NIH 기준 유지).
    용량 미파싱·비대상 성분이면 None.
    """
    info = _DUAL_UL.get((canonical or "").lower())
    if not info:
        return None
    parsed = extract_dose(text)
    if not parsed:
        return None
    val = _convert(parsed[0], parsed[1], info["unit"], (canonical or "").lower())
    if val is None:
        return None
    u = info["unit"]
    strict, loose = min(info["nih"], info["kdri"]), max(info["nih"], info["kdri"])
    if val > loose:
        zone = "양 기준 모두 초과"
    elif val > strict:
        zone = "엄격 기준 초과·느슨 기준 이내(기준 상이 — 보수적 주의 권장)"
    else:
        zone = "양 기준 이내"
    return (f"[UL 국가기준 상이] NIH {info['nih']:.0f}{u} · KDRI/MFDS {info['kdri']:.0f}{u}; "
            f"입력 ~{val:.0f}{u} → {zone}. (시스템 결정은 NIH 기준)")


def derive_lab_conditions(lab_values: Optional[dict]) -> set[str]:
    """lab 값 → 현재 상태 조건 파생 (avoid/contra 매칭용). 표준 임상 컷오프."""
    out: set[str] = set()
    if not lab_values:
        return out
    ca = lab_values.get("calcium")
    if isinstance(ca, (int, float)):
        if ca >= 12.0:
            out.add("severe_hypercalcemia")   # [임상 컷오프] 중증 → vitamin_d 금기
        elif ca > 10.5:
            out.add("hypercalcemia")          # [임상 컷오프] 상한 초과 → vitamin_d 회피
    fer = lab_values.get("ferritin")
    if isinstance(fer, (int, float)) and fer < 30:
        out.add("iron_deficiency")            # [임상 컷오프] 혈청 ferritin <30 ng/mL = 철결핍
    return out
