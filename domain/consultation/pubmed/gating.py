import re
from typing import List, Dict, Tuple
from .text_normalizer import _normalize_english_query_text, _normalize_text, _contains_thyroid_domain_signal
from .utils import _contains_hangul, _core_subject_tokens
from .constants import SUPPLEMENT_EVIDENCE_HINTS


def _has_anchor_match(article: Dict, anchor_tokens: List[str]) -> bool:
    if not anchor_tokens:
        return True
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    if not _contains_thyroid_domain_signal(blob):
        return False
    return any(tok in blob for tok in anchor_tokens)


def _detect_surgery_context_korean(text: str) -> bool:
    raw = str(text or "")
    keywords = ["수술", "절제", "전절제", "반절제", "제거", "절제술", "수술했", "수술한", "수술후", "수술 후"]
    return any(k in raw for k in keywords)



def _requires_postop_hard_gate(user_input: str, primary_subject: str, extra_keywords: str = "") -> bool:
    text = f"{str(user_input or '')} {str(primary_subject or '')} {str(extra_keywords or '')}".lower()
    en_signals = ["postoperative", "post-surgical", "post surgery", "after surgery", "thyroidectomy", "surgery"]
    return _detect_surgery_context_korean(user_input) or any(s in text for s in en_signals)



def _allows_pregnancy_context(user_input: str, primary_subject: str, extra_keywords: str = "") -> bool:
    text = f"{str(user_input or '')} {str(primary_subject or '')} {str(extra_keywords or '')}".lower()
    ko_signals = ["임신", "산후", "수유", "출산", "산모"]
    en_signals = ["pregnan", "postpartum", "lactation", "breastfeeding", "maternal", "prenatal", "perinatal"]
    return any(k in str(user_input or "") for k in ko_signals) or any(s in text for s in en_signals)



def _has_postop_signal_in_article(article: Dict) -> bool:
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    signals = [
        "postoperative", "post-surgical", "post surgical", "after surgery",
        "surgery", "surgical", "thyroidectomy", "thyroid cancer surgery",
    ]
    return any(s in blob for s in signals)



def _is_pregnancy_or_postpartum_article(article: Dict) -> bool:
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    drift = [
        "pregnancy", "pregnant", "postpartum", "maternal", "prenatal",
        "perinatal", "breastfeeding", "lactation", "gestational",
    ]
    return any(d in blob for d in drift)



def _is_low_quality_metadata_article(article: Dict) -> bool:
    title = _normalize_text(str(article.get("title", "") or ""))
    abstract = _normalize_text(str(article.get("abstract", "") or ""))
    if not title:
        return True
    # 번역/색인성 제목만 있는 경우(예: [Therapy and prevention ...])는 근거 품질이 낮은 경우가 많아 제외
    if re.match(r"^\[[^\]]+\]\.?$", title):
        return True
    # 제목/초록 모두 지나치게 짧으면 근거로 쓰기 어려움
    if len(title) < 20 and len(abstract) < 120:
        return True
    return False



def _has_direct_postop_or_rai_signal(article: Dict) -> bool:
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    direct_terms = [
        "postoperative", "post-surgical", "post surgical", "after surgery",
        "thyroidectomy", "thyroid surgery",
        "radioiodine", "iodine-131", "rai", "salivary",
    ]
    return any(t in blob for t in direct_terms)



def _is_rai_related_article(article: Dict) -> bool:
    """RAI/iodine-131 관련 간접근거 논문 여부."""
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    rai_terms = ["radioiodine", "iodine-131", "rai", "i-131", "salivary"]
    return any(t in blob for t in rai_terms)



def _has_general_postop_signal(article: Dict) -> bool:
    """일반 수술후(post-thyroidectomy) 직접근거 여부 (RAI 제외)."""
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    postop_terms = [
        "postoperative", "post-surgical", "post surgical", "after surgery",
        "thyroidectomy", "thyroid surgery",
    ]
    return any(t in blob for t in postop_terms)



def _has_core_subject_match(article: Dict, core_tokens: List[str]) -> bool:
    if not core_tokens:
        return True
    blob = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
    return any(tok in blob for tok in core_tokens)


def _has_core_subject_in_title(article: Dict, core_tokens: List[str]) -> bool:
    """질문 핵심 개체(성분/주제)가 제목에 등장하는지 확인.

    title-only 매칭은 abstract에 성분이 부수적으로 언급된 무관 논문
    (예: 다른 약물의 부작용 보고에 zinc/magnesium이 단순 열거되어 통과)을
    제거하기 위한 엄격 게이트.
    """
    if not core_tokens:
        return True
    title = str(article.get("title", "") or "").lower()
    if not title:
        return False
    return any(tok in title for tok in core_tokens)


def _primary_suggests_supplement_intervention(primary_subject: str) -> bool:
    s = (primary_subject or "").lower().strip()
    if not s:
        return False
    if any(k in s for k in ("supplement", "supplementation", "nutraceutical", "intake")):
        return True
    # canonical supplement 이름이 단독으로 들어와도 보충제 검색으로 인식
    # (예: primary_subject="zinc" → True). title 게이트가 작동하도록 보강.
    try:
        from .thyroid_rules import ALLOWED_SUPPLEMENT_SYNONYMS
    except ImportError:
        from thyroid_rules import ALLOWED_SUPPLEMENT_SYNONYMS  # type: ignore[no-redef]
    for canonical, synonyms in ALLOWED_SUPPLEMENT_SYNONYMS.items():
        if canonical.lower() == s or s in canonical.lower().split():
            return True
        for syn in synonyms:
            if syn.lower() == s:
                return True
    return False



def _blob_has_supplement_evidence_signal(blob: str) -> bool:
    b = (blob or "").lower()
    if any(h in b for h in SUPPLEMENT_EVIDENCE_HINTS):
        return True
    if re.search(r"\b\d+\s*(mcg|mg|µg|μg|ug)\b", b):
        return True
    if re.search(r"\b\d+\s*iu\b", b):
        return True
    return False



def _apply_final_directness_gate(
    articles: List[Dict],
    require_postop: bool,
    primary_subject: str = "",
) -> Tuple[List[Dict], int]:
    """
    리랭크 전 최종 정밀도 게이트.
    - 메타데이터 품질이 낮은 논문 제거
    - 수술후 질문(require_postop)에서는 수술후/RAI 직접 시그널 없는 논문 제거
    """
    if not articles:
        return [], 0
    core_tokens = _core_subject_tokens(primary_subject)
    supplement_focused = _primary_suggests_supplement_intervention(primary_subject)
    kept: List[Dict] = []
    dropped = 0
    for art in articles:
        if _is_low_quality_metadata_article(art):
            dropped += 1
            continue
        # 버그 수정: 루프 변수는 `art`, 이전 코드는 `article`(미정의) 를 잘못 참조했음
        blob = f"{art.get('title', '')} {art.get('abstract', '')}".lower()
        # 일반화 규칙: 질문 핵심 개체(성분/주제) 토큰이 없으면 제외
        if not _has_core_subject_match(art, core_tokens):
            dropped += 1
            continue
        # 보충제 맥락 엄격 게이트: 성분 토큰이 제목에 없으면 제외
        # (abstract에만 부수적으로 언급된 무관 논문 차단 — 치과교정/항생제 약동학 등)
        if supplement_focused and core_tokens and not _has_core_subject_in_title(art, core_tokens):
            dropped += 1
            continue
        # 보충제 맥락: 성분 언급만으로는 부족 — 개입/시험/용량 신호 추가 요구
        if supplement_focused and core_tokens and not _blob_has_supplement_evidence_signal(blob):
            dropped += 1
            continue
        if require_postop and not _has_direct_postop_or_rai_signal(art):
            dropped += 1
            continue
        kept.append(art)
    if kept:
        return kept, dropped
    # 완화 폴백: 엄격 조건(postop/보충 개입 신호)만 생략, 핵심 성분 + 메타데이터 품질은 유지
    # 보충제 맥락에서는 title 매칭은 유지(폴백에서도 무관 논문 노출 차단)
    relaxed: List[Dict] = []
    for art in articles:
        if _is_low_quality_metadata_article(art):
            continue
        if not _has_core_subject_match(art, core_tokens):
            continue
        if supplement_focused and core_tokens and not _has_core_subject_in_title(art, core_tokens):
            continue
        relaxed.append(art)
    relaxed.sort(key=lambda x: int(x.get("primary_subject_relevance") or 0), reverse=True)
    relaxed = relaxed[:2]
    return relaxed, len(articles) - len(relaxed)



def _apply_scenario_hard_gate(
    articles: List[Dict],
    require_postop: bool,
    allow_pregnancy_context: bool,
) -> Tuple[List[Dict], int]:
    if not articles:
        return [], 0
    kept: List[Dict] = []
    dropped = 0
    for art in articles:
        if require_postop and not _has_postop_signal_in_article(art):
            dropped += 1
            continue
        if not allow_pregnancy_context and _is_pregnancy_or_postpartum_article(art):
            dropped += 1
            continue
        kept.append(art)
    if kept:
        return kept, dropped
    # 완전 공백 방지: 관련도 상위 2개만 최소 보존
    fallback = sorted(articles, key=lambda x: int(x.get("primary_subject_relevance") or 0), reverse=True)[:2]
    return fallback, max(dropped, len(articles) - len(fallback))



def _looks_like_sentence_primary(text: str) -> bool:
    t = _normalize_text(text).lower()
    if not t:
        return True
    # 너무 긴 문장/잡다한 서술형이면 성분명 추출 실패로 간주
    if len(t.split()) > 8:
        return True
    bad_tokens = ["safe", "okay", "can i", "should i", "3 weeks", "week", "surgery"]
    return any(tok in t for tok in bad_tokens) and len(t.split()) >= 5



def _is_valid_primary_subject(text: str) -> bool:
    t = _normalize_english_query_text(text)
    if not t:
        return False
    if _contains_hangul(t):
        return False
    if _looks_like_sentence_primary(t):
        return False
    return True



def _filter_articles_for_output(articles: List[Dict], min_score_primary: int = 4, min_score_secondary: int = 2) -> Tuple[List[Dict], int]:
    """
    UI로 노출되는 pubmed_articles에서도 오프토픽을 줄이기 위한 필터.
    - 관련도 높은 논문이 있으면 우선 노출
    - 부족하면 중간 관련도까지 보충
    """
    if not articles:
        return [], 0
    primary = [a for a in articles if int(a.get("primary_subject_relevance") or 0) >= min_score_primary]
    secondary = [a for a in articles if min_score_secondary <= int(a.get("primary_subject_relevance") or 0) < min_score_primary]
    selected: List[Dict] = []
    if primary:
        selected.extend(primary)
        if len(selected) < 6:
            selected.extend(secondary[: max(0, 6 - len(selected))])
    else:
        # 관련도가 충분히 높은 논문이 없으면 노출을 최소화하여 오프토픽 유입 차단
        selected = secondary[:2]
    selected = selected[:8]
    dropped = max(0, len(articles) - len(selected))
    return selected, dropped



def _filter_articles_with_anchor(
    articles: List[Dict],
    anchor_tokens: List[str],
    min_score_primary: int = 6,
    min_score_secondary: int = 4,
    core_tokens: List[str] | None = None,
    require_title_core: bool = False,
) -> Tuple[List[Dict], int]:
    """
    관련도 점수 + 앵커 토큰 매칭을 함께 사용해 오프토픽을 강하게 제거합니다.
    앵커가 너무 공격적으로 작동해 결과가 비는 경우를 대비해 점진적 폴백을 둡니다.

    require_title_core=True 이면 core_tokens(성분 등) 가 제목에 있는 논문만 풀에 남깁니다.
    보충제 검색 시 abstract 부수 언급으로 무관 논문이 fallback으로 노출되는 문제를 차단합니다.
    """
    if not articles:
        return [], 0

    # 수면 의도면 sleep 앵커가 제목/초록에 전혀 없는 논문은 UI 노출에서 제외
    sleep_intent = any(t in anchor_tokens for t in ["sleep", "insomnia", "quality", "latency"])
    if sleep_intent:
        sleep_anchor_terms = ["sleep", "insomnia", "sleep quality", "sleep latency", "latency"]
        with_anchor = [
            a for a in articles
            if _has_anchor_match(a, anchor_tokens)
            and any(term in f"{a.get('title', '')} {a.get('abstract', '')}".lower() for term in sleep_anchor_terms)
        ]
    else:
        with_anchor = [a for a in articles if _has_anchor_match(a, anchor_tokens)]

    if require_title_core and core_tokens:
        with_anchor = [a for a in with_anchor if _has_core_subject_in_title(a, core_tokens)]

    pool = with_anchor
    if not pool:
        # 도메인 고정 모드에서는 앵커/도메인 불일치 논문을 노출하지 않음
        return [], len(articles)

    selected, dropped_local = _filter_articles_for_output(
        pool,
        min_score_primary=min_score_primary,
        min_score_secondary=min_score_secondary,
    )

    if selected:
        dropped_total = max(0, len(articles) - len(selected))
        return selected, dropped_total

    # 폴백: 관련도 점수 상위 2건은 보존(완전 공백 방지)
    fallback = sorted(pool, key=lambda x: int(x.get("primary_subject_relevance") or 0), reverse=True)[:2]
    dropped_total = max(0, len(articles) - len(fallback))
    return fallback, dropped_total



