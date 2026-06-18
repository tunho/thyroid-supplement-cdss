import re
from .thyroid_rules import THYROID_DOMAIN_TERMS

__all__ = [
    "_normalize_text", "_normalize_english_query_text", "_strip_time_expressions_en",
    "_thyroid_domain_clause", "_contains_thyroid_domain_signal", "_force_thyroid_domain_query"
]

def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def _normalize_english_query_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"[가-힣]+", " ", t)
    t = re.sub(r"[^0-9a-zA-Z\s\-\./()]+", " ", t)
    return _normalize_text(t)

def _strip_time_expressions_en(text: str) -> str:
    t = _normalize_text(text).lower()
    if not t:
        return ""
    t = re.sub(r"\b\d+\s*(day|days|week|weeks|month|months|year|years)\b", " ", t)
    t = re.sub(r"\b\d+\s*(d|wk|wks|mo|mos|yr|yrs)\b", " ", t)
    t = re.sub(r"\b(post|after)\s*op(erative)?\b", "postoperative", t)
    return _normalize_text(t)

def _thyroid_domain_clause() -> str:
    return "(" + " OR ".join(THYROID_DOMAIN_TERMS) + ")"

def _contains_thyroid_domain_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in THYROID_DOMAIN_TERMS) or any(
        k in str(text or "") for k in ["갑상선", "하시모토", "그레이브스", "갑상선염"]
    )

def _force_thyroid_domain_query(query: str, domain_mode: str = "strict") -> str:
    q = _normalize_text(query)
    if not q:
        return q
    if domain_mode == "open":
        return q
    if domain_mode == "soft" and _contains_thyroid_domain_signal(q):
        return q
    if domain_mode == "strict" and _contains_thyroid_domain_signal(q):
        return q
    return f"({q}) AND {_thyroid_domain_clause()}"
