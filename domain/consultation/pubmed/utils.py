from .text_normalizer import *
import re
from typing import List, Dict, Tuple, Optional
from .constants import *

def _contains_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))



def _extract_korean_time_info(text: str) -> Tuple[Optional[int], str]:
    """
    한국어 시간 표현에서 숫자와 단위를 추출합니다. 예: '3주' -> (3, 'week')
    """
    raw = str(text or "")
    m = re.search(r"(\d+)\s*(일|주|개월|달|년)", raw)
    if not m:
        return None, ""
    value = int(m.group(1))
    unit_kr = m.group(2)
    unit = {"일": "day", "주": "week", "개월": "month", "달": "month", "년": "year"}.get(unit_kr, "")
    return value, unit



def _translate_korean_text(text: str) -> str:
    translated = (text or "").lower()
    for src, tgt in sorted(TERM_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(src.lower(), tgt)
    translated = re.sub(r"[^\w\s\-\./()]+", " ", translated)
    return _normalize_text(translated)



def _extract_present_terms(text: str, candidates: List[str]) -> List[str]:
    lowered = f" {text.lower()} "
    found = []
    for candidate in candidates:
        token = candidate.lower()
        if token in lowered and candidate not in found:
            found.append(candidate)
    return found



def _merge_supplement_signals(primary_subject: str, combined_en: str) -> List[str]:
    """
    고정 SUPPLEMENT_HINTS 매칭 + AI가 추출한 PrimarySubject를 합칩니다.
    성분마다 사전에 엔트리를 추가하지 않아도 질문 핵심이 상호작용·보조 쿼리에 반영됩니다.
    """
    from_hints = _extract_present_terms(combined_en, SUPPLEMENT_HINTS)
    ps = _normalize_text(primary_subject or "")
    if not ps or len(ps) < 2:
        return from_hints
    out: List[str] = [ps]
    for h in from_hints:
        if h.lower() != ps.lower():
            out.append(h)
    return out




def _core_subject_tokens(primary_subject: str) -> List[str]:
    """
    질문 핵심 주제(성분/개체) 토큰을 일반화 방식으로 추출합니다.
    문맥/의도 토큰(safety, surgery 등)은 제외하고 핵심 개체만 남깁니다.
    """
    s = (primary_subject or "").lower()
    if not s:
        return []
    tokens = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", s)
    stop = {
        "supplement", "supplementation", "intake", "dose", "dosage", "safety",
        "interaction", "adverse", "effect", "effectiveness", "recommendation",
        "after", "before", "postoperative", "post", "early", "immediate",
        "surgery", "surgical", "thyroid", "thyroidectomy",
    }
    out = [t for t in tokens if len(t) >= 3 and t not in stop]
    return list(dict.fromkeys(out))[:8]



