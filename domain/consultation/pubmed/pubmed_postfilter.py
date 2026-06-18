

"""
PubMed 후처리 — PMID 화이트리스트 적용 · 섹션 포맷 · evidence level 부여 · 답변 톤 교정

pubmed_service.py 에서 import 해서 사용합니다.
"""

import re
from typing import Dict, List, Optional, Tuple

try:
    from .thyroid_rules import (
        PUBTYPE_EVIDENCE_LEVEL,
        HIGH_QUALITY_PUBTYPES,
        LOW_QUALITY_PUBTYPES,
    )
except ImportError:
    from thyroid_rules import (  # type: ignore[no-redef]
        PUBTYPE_EVIDENCE_LEVEL,
        HIGH_QUALITY_PUBTYPES,
        LOW_QUALITY_PUBTYPES,
    )


# ─── Evidence level 계산 ─────────────────────────────────────────────────────
def assign_evidence_level(pub_types: List[str]) -> str:
    """
    논문의 PublicationType 목록을 받아 evidence level 문자열을 반환합니다.

    §10.2 EBM 피라미드 기반 우선순위:
    meta_analysis > rct > cohort > case_control > observational > ... > insufficient
    pub_types가 비어 있으면 "unknown"을 반환합니다.
    """
    if not pub_types:
        return "unknown"

    # EVIDENCE_RANK와 동일한 우선순위 체계 사용
    _PRIORITY = {
        "meta_analysis":     6,
        "systematic_review": 6,   # Fix B: Systematic Review 별도 레이블
        "rct":               5,
        "high":              5,   # 구형 레이블 호환
        "cohort":            4,
        "moderate":          4,   # 구형 레이블 호환
        "case_control":      3,
        "observational":     3,
        "low-moderate":      3,   # 구형 레이블 호환
        "case_series":       2,
        "case_report":       2,
        "low":               2,   # 구형 레이블 호환
        "insufficient":      1,
    }
    best = "insufficient"
    best_p = _PRIORITY["insufficient"]

    for pt in pub_types:
        level = PUBTYPE_EVIDENCE_LEVEL.get(pt)
        if level and _PRIORITY.get(level, 0) > best_p:
            best = level
            best_p = _PRIORITY[level]

    # Fix C: Phase cap — Phase I/II 태그가 있으면 상위 레벨을 억제
    # Phase I은 안전성/약동학 탐색, Phase II는 예비 효능 — RCT로 오분류 방지
    _PHASE_CAP = {
        "Clinical Trial, Phase I":  "observational",
        "Clinical Trial, Phase II": "cohort",
    }
    for pt in pub_types:
        cap_level = _PHASE_CAP.get(pt)
        if cap_level:
            cap_p = _PRIORITY.get(cap_level, 0)
            if best_p > cap_p:
                best = cap_level
                best_p = cap_p

    return best


_RCT_SIGNALS = frozenset({
    "randomized", "randomised", "crossover", "cross-over",
    "controlled", "double-blind", "placebo-controlled",
})


def uptype_if_journal_article(article: Dict) -> str:
    """
    pub_types가 Journal Article 단독이고 evidence_level이 insufficient인 경우,
    초록에 통제 연구 키워드가 있으면 low-moderate로 승격.
    directness 조건(score 임계값 통과)은 호출부에서 보장.
    """
    if article.get("evidence_level") != "insufficient":
        return article["evidence_level"]
    pts = set(article.get("pub_types") or [])
    if pts - {"Journal Article"}:
        return article["evidence_level"]
    abstract = (article.get("abstract") or "").lower()
    if any(kw in abstract for kw in _RCT_SIGNALS):
        return "low-moderate"
    return article["evidence_level"]


def evidence_badge(level: str) -> str:
    """evidence level → 간단한 한국어 뱃지 문자열."""
    _MAP = {
        # §10.2 재매핑 후 신규 레이블
        "meta_analysis":     "근거 강도: 높음 (메타분석)",
        "systematic_review": "근거 강도: 높음 (체계적 문헌고찰)",
        "rct":               "근거 강도: 보통-높음 (무작위대조시험)",
        "cohort":        "근거 강도: 보통 (코호트 연구)",
        "case_control":  "근거 강도: 낮음-보통 (증례대조 연구)",
        "observational": "근거 강도: 낮음 (관찰 연구)",
        "case_report":   "근거 강도: 불충분 (증례 보고)",
        "case_series":   "근거 강도: 불충분 (증례 시리즈)",
        # 기존 레이블 유지 (rule-level + 구형 레이블 호환)
        "high":         "근거 강도: 높음 (메타분석/체계적 고찰/RCT)",
        "moderate":     "근거 강도: 보통 (RCT)",
        "low-moderate": "근거 강도: 낮음-보통 (임상시험/리뷰)",
        "low":          "근거 강도: 낮음 (관찰/단면)",
        "insufficient": "근거 강도: 불충분 (증례 등)",
        "unknown":      "근거 강도: 불명",
    }
    return _MAP.get(level, f"근거 강도: {level}")


# ─── PMID 화이트리스트 강제 ──────────────────────────────────────────────────
def sanitize_pmid_citations(
    answer: str,
    allowed_pmids: List[str],
    forbid_all: bool = False,
) -> str:
    """
    LLM이 허용 목록 밖 PMID를 인용하거나 마지막에 나열하는 습관을 제거합니다.

    Args:
        answer:       LLM 원본 답변
        allowed_pmids: 허용된 PMID 문자열 목록
        forbid_all:   True이면 모든 [PMID: …] 인용을 제거
    """
    text = str(answer or "")
    if not text.strip():
        return text

    # 끝줄 "근거/참고문헌/PMID:" 나열 제거
    text = re.sub(r"(?im)^\s*(근거|참고\s*문헌|references?)\s*:\s*.*$", "", text).strip()
    text = re.sub(r"(?im)^\s*pmid\s*:\s*.*$", "", text).strip()

    if forbid_all:
        return re.sub(r"\s*\[PMID:\s*[0-9,\s]+\]\s*", " ", text).strip()

    allow = {re.sub(r"\D", "", str(p)) for p in (allowed_pmids or []) if str(p).strip()}

    def _pmid_repl(match: re.Match) -> str:
        inside = match.group(1)
        nums = [re.sub(r"\D", "", x) for x in re.split(r"[,\s]+", inside) if x.strip()]
        kept = [n for n in nums if n and n in allow]
        if not kept:
            return ""
        return f"[PMID: {', '.join(kept)}]"

    text = re.sub(r"\[PMID:\s*([0-9,\s]+)\]", _pmid_repl, text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ─── 의사용 톤 교정 ────────────────────────────────────────────────────────────
def sanitize_doctor_tone(answer: str) -> str:
    """
    의사용 파이프라인에서 환자용 문구를 제거/치환합니다.
    """
    text = str(answer or "")
    if not text.strip():
        return text

    # ── "주치의/담당 의사/의사 + 상담/상의 + [문장 끝까지]" 제거 ─────────────────
    # 문장 종료 기준: 마침표·느낌표·줄바꿈 또는 문자열 끝
    replacements = [
        (
            r"주치의(?:와|에게)\s*상담[^\.。\n!]*[\.。!]?",
            "개별 임상평가가 필요합니다.",
        ),
        (
            r"담당\s*의사(?:와|에게)\s*상의[^\.。\n!]*[\.。!]?",
            "개별 임상평가가 필요합니다.",
        ),
        (
            r"의사(?:와|에게)\s*(?:상담|상의)[^\.。\n!]*[\.。!]?",
            "개별 임상평가가 필요합니다.",
        ),
        (r"환자분께서", "환자 기준으로"),
        (r"환자분이", "환자가"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ─── 섹션 포맷 정리 ────────────────────────────────────────────────────────────
def format_numbered_sections(answer: str) -> str:
    """
    '(1) ... (2) ...' 형태를 줄바꿈 기반 섹션으로 정리해 가독성을 높입니다.
    """
    text = str(answer or "").strip()
    if not text:
        return text

    # (1)~(9) 앞에 줄바꿈 강제
    text = re.sub(r"\s*(\([1-9]\)\s*)", r"\n\1", text)
    text = text.lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─── 논문 목록 품질 필터 ────────────────────────────────────────────────────────
def is_low_quality_metadata(article: Dict) -> bool:
    """
    메타데이터 품질이 너무 낮아 근거로 쓰기 어려운 논문을 식별합니다.
    - 번역/색인 전용 제목: [...]
    - 제목·초록 모두 지나치게 짧음
    """
    title = re.sub(r"\s+", " ", str(article.get("title", "") or "")).strip()
    abstract = re.sub(r"\s+", " ", str(article.get("abstract", "") or "")).strip()

    if not title:
        return True
    if re.match(r"^\[[^\]]+\]\.?$", title):
        return True
    if len(title) < 20 and len(abstract) < 120:
        return True
    return False


def filter_low_quality_metadata(
    articles: List[Dict],
) -> Tuple[List[Dict], int]:
    """메타데이터 품질 낮은 논문 제거. (kept, dropped_count) 반환."""
    kept = [a for a in articles if not is_low_quality_metadata(a)]
    dropped = len(articles) - len(kept)
    return kept, dropped


# ─── 최종 답변 후처리 통합 ────────────────────────────────────────────────────
def postprocess_answer(
    raw_answer: str,
    allowed_pmids: List[str],
    weak_evidence: bool = False,
) -> str:
    """
    PMID 화이트리스트 → 의사용 톤 → 섹션 포맷 순으로 후처리합니다.
    """
    step1 = sanitize_pmid_citations(raw_answer, allowed_pmids, forbid_all=weak_evidence)
    step2 = sanitize_doctor_tone(step1)
    step3 = format_numbered_sections(step2)
    return step3


# ─── 답변의 evidence level 요약 ────────────────────────────────────────────
def summarize_evidence_levels(articles: List[Dict]) -> str:
    """
    사용된 논문들의 evidence level을 집계해 한 줄 요약을 반환합니다.
    예: "근거 요약: 메타분석 1편, RCT 2편, 리뷰 1편"
    """
    if not articles:
        return ""

    counts: Dict[str, int] = {}
    for art in articles:
        level = art.get("evidence_level", "unknown")
        counts[level] = counts.get(level, 0) + 1

    _LABEL = {
        # §10.2 신규 레이블
        "meta_analysis":     "메타분석",
        "systematic_review": "체계적 문헌고찰",
        "rct":               "무작위대조시험(RCT)",
        "cohort":        "코호트 연구",
        "case_control":  "증례대조 연구",
        "observational": "관찰 연구",
        "case_report":   "증례 보고",
        "case_series":   "증례 시리즈",
        # 구형 레이블 호환
        "high":         "고품질(메타분석/RCT)",
        "moderate":     "중등도(RCT)",
        "low-moderate": "낮음-보통(임상시험/리뷰)",
        "low":          "낮음(관찰)",
        "insufficient": "불충분(증례 등)",
        "unknown":      "불명",
    }

    _ORDER = [
        "meta_analysis", "systematic_review", "rct", "cohort", "case_control", "observational",
        "case_series", "case_report",
        "high", "moderate", "low-moderate", "low", "insufficient", "unknown",
    ]

    parts = []
    for level in _ORDER:
        n = counts.get(level, 0)
        if n > 0:
            parts.append(f"{_LABEL.get(level, level)} {n}편")

    return "근거 수준 요약: " + ", ".join(parts) if parts else ""
