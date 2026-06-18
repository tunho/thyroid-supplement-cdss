import re
from typing import List, Dict, Optional
from .constants import *
from .thyroid_rules import THYROID_DOMAIN_TERMS
from .utils import *
from .utils import _extract_korean_time_info, _contains_hangul, _translate_korean_text
from .gating import _detect_surgery_context_korean
from .client import search_pubmed_realtime

def _rescue_queries_for_primary(primary_subject: str) -> List[str]:
    p = (primary_subject or "").strip()
    if not p:
        return []
    return [
        f"({p}) AND (supplementation OR supplement OR deficiency OR ferritin OR anemia)",
        f"({p}) AND (safety OR adverse OR toxicity OR overdose)",
    ]



def _backfill_queries_for_postop(primary_subject: str) -> List[str]:
    """
    hard gate 후 결과가 너무 적을 때(1건 이하) 재현율을 보완하는 완화 검색어.
    - 갑상선 도메인 고정은 유지
    - postop 강제는 완화하되 safety/adverse 축은 유지
    """
    p = (primary_subject or "").strip()
    if not p:
        return []
    return [
        f"({p}) AND (thyroidectomy OR thyroid surgery OR postoperative OR surgery) AND (safety OR adverse OR complication)",
        f"({p}) AND (thyroid OR thyroid cancer) AND (safety OR toxicity OR adverse)",
        f"({p}) AND (radioiodine OR iodine-131 OR RAI) AND (adverse OR recovery OR salivary)",
    ]



def _thyroid_domain_clause() -> str:
    return "(" + " OR ".join(THYROID_DOMAIN_TERMS) + ")"



def _contains_thyroid_domain_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in THYROID_DOMAIN_TERMS) or any(
        k in str(text or "") for k in ["갑상선", "하시모토", "그레이브스", "갑상선염"]
    )



def _force_thyroid_domain_query(query: str, domain_mode: str = "strict") -> str:
    """
    갑상선 도메인 제약 적용.
    - strict: 항상 thyroid domain clause 강제
    - soft: 질의에 갑상선 시그널이 없을 때만 clause 추가
    - open: 도메인 제약 없음
    """
    q = _normalize_text(query)
    if not q:
        return q
    if domain_mode == "open":
        return q
    if domain_mode == "soft" and _contains_thyroid_domain_signal(q):
        return q
    if domain_mode == "strict" and _contains_thyroid_domain_signal(q):
        # strict 모드에서도 이미 갑상선 신호가 있으면 중복 clause를 붙이지 않음
        return q
    return f"({q}) AND {_thyroid_domain_clause()}"



def _postop_bucket_tokens(user_input: str) -> List[str]:
    """
    수술/시술 맥락 + 시간표현을 '버킷 토큰'으로만 변환합니다.
    숫자(3주)는 PubMed term에 넣지 않습니다.
    """
    if not _detect_surgery_context_korean(user_input):
        return []
    value, unit = _extract_korean_time_info(user_input)
    # 수술은 기본 postoperative
    tokens = ["postoperative"]
    # '초기 회복기' 정도만 추가 (대략적 버킷)
    if value is not None and unit == "week":
        if value <= 2:
            tokens.append("immediate postoperative")
        elif value <= 6:
            tokens.append("early postoperative")
    elif value is not None and unit == "day":
        if value <= 14:
            tokens.append("immediate postoperative")
    return tokens



def get_rda_ul_context(age: Optional[int], sex: Optional[str]) -> str:
    if not age or not sex:
        return ""
    
    parts = ["[참고: 한국인 영양소 섭취기준(2020)]"]
    
    # Calcium
    cal_data = RDA_UL_GUIDELINES["calcium"].get(sex, {})
    if sex == "F":
        key = "19-49" if age < 50 else "50+"
    else:
        key = "19-49" if age < 50 else ("50-64" if age < 65 else "65+")
    c = cal_data.get(key)
    if c:
        parts.append(f"- 칼슘: 권장 {c['RDA']}mg, 상한 {c['UL']}mg")
    
    # Iron
    iron_data = RDA_UL_GUIDELINES["iron"].get(sex, {})
    key = "19-49" if (sex == "F" and age < 50) else ("19+" if sex == "M" else "50+")
    i = iron_data.get(key)
    if i:
        parts.append(f"- 철분: 권장 {i['RDA']}mg, 상한 {i['UL']}mg")
        
    # Vitamin D
    vd = RDA_UL_GUIDELINES["vitamin d"]["all"]
    key = "19-64" if age < 65 else "65+"
    v = vd.get(key)
    if v:
        parts.append(f"- 비타민D: 권장 {v['RDA']}µg, 상한 {v['UL']}µg")
        
    # Magnesium
    mag_data = RDA_UL_GUIDELINES["magnesium"].get(sex, {})
    m = mag_data.get("19+")
    if m:
        parts.append(f"- 마그네슘: 권장 {m['RDA']}mg, 상한 {m['UL']}mg")

    # Vitamin C
    vc = RDA_UL_GUIDELINES["vitamin c"]["all"].get("19+")
    if vc:
        parts.append(f"- 비타민C: 권장 {vc['RDA']}mg, 상한 {vc['UL']}mg")
        
    return "\n".join(parts)



def get_rda_ul_context_for_subject(
    primary_subject: str,
    age: Optional[int],
    sex: Optional[str],
) -> str:
    """
    질문의 핵심 성분(PrimarySubject)과 직접 관련된 RDA/UL만 우선 안내합니다.
    매칭되지 않으면 기존 전체 가이드를 반환합니다.
    """
    full = get_rda_ul_context(age, sex)
    if not age or not sex:
        return full
    s = (primary_subject or "").lower()
    if not s:
        return full

    header = "[참고: 한국인 영양소 섭취기준(2020) — 질문 성분 위주]"
    lines: List[str] = [header]

    def _iron_line() -> Optional[str]:
        iron_data = RDA_UL_GUIDELINES["iron"].get(sex, {})
        key = "19-49" if (sex == "F" and age < 50) else ("19+" if sex == "M" else "50+")
        i = iron_data.get(key)
        if not i:
            return None
        return (
            f"- 철분: 권장 {i['RDA']}mg/일, 상한 {i['UL']}mg/일 "
            f"(일반 성인 기준; 결핍·필요 여부는 혈액검사 등으로 확인)"
        )

    def _calcium_line() -> Optional[str]:
        cal_data = RDA_UL_GUIDELINES["calcium"].get(sex, {})
        if sex == "F":
            key = "19-49" if age < 50 else "50+"
        else:
            key = "19-49" if age < 50 else ("50-64" if age < 65 else "65+")
        c = cal_data.get(key)
        if not c:
            return None
        return f"- 칼슘: 권장 {c['RDA']}mg/일, 상한 {c['UL']}mg/일"

    def _vitd_line() -> Optional[str]:
        vd = RDA_UL_GUIDELINES["vitamin d"]["all"]
        key = "19-64" if age < 65 else "65+"
        v = vd.get(key)
        if not v:
            return None
        return f"- 비타민D: 권장 {v['RDA']}µg/일, 상한 {v['UL']}µg/일"

    if any(k in s for k in ("iron", "ferritin", "ferrous", "anaemia", "anemia")):
        il = _iron_line()
        return "\n".join(lines + [il]) if il else full

    if "calcium" in s:
        cl = _calcium_line()
        return "\n".join(lines + [cl]) if cl else full

    if "vitamin d" in s or "vitamin d3" in s or "cholecalciferol" in s:
        vl = _vitd_line()
        return "\n".join(lines + [vl]) if vl else full

    if "magnesium" in s:
        mag_data = RDA_UL_GUIDELINES["magnesium"].get(sex, {})
        m = mag_data.get("19+")
        if m:
            return "\n".join(lines + [f"- 마그네슘: 권장 {m['RDA']}mg/일, 상한 {m['UL']}mg/일"])
        return full

    if "vitamin c" in s or "ascorbic" in s:
        vc = RDA_UL_GUIDELINES["vitamin c"]["all"].get("19+")
        if vc:
            return "\n".join(lines + [f"- 비타민C: 권장 {vc['RDA']}mg/일, 상한 {vc['UL']}mg/일"])
        return full

    return full



