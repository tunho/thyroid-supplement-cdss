"""
domain.thyroid.supplement_resolver — 영양제 이름 해석 레이어

사용자 입력(메시지·명시 필드·히스토리)을 받아
판정에 사용할 canonical 성분 목록(IngredientCandidate[])을 반환한다.

해석 순서:
  A. explicit supplement 필드 또는 키워드/별칭 사전 — confidence=1.0
  B. MFDS health_food DB 검색 — 단일·복수 성분 추출
  C. LLM 구조화 추출 — 화이트리스트 key + confidence
  D. 히스토리 복원 — 현재 턴에서 못 찾은 경우

판정(Safety/Decision)은 이 모듈에서 하지 않는다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# 키워드 매칭 결과를 신뢰도 최우선으로 처리
_KEYWORD_CONFIDENCE = 1.0
_MFDS_CONFIDENCE    = 0.85
_LLM_CONFIDENCE_MIN = 0.70   # 이 값 미만이면 clarification 요청


# ──────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────

@dataclass
class IngredientCandidate:
    """판정 파이프라인에 넘길 성분 1건."""
    key: str            # SUPPLEMENT_RULES canonical key (예: "iodine")
    confidence: float   # 0.0 ~ 1.0
    source: str         # "keyword" | "mfds" | "llm" | "explicit" | "history"


@dataclass
class SupplementResolution:
    """resolve_supplement() 반환 결과."""
    raw_input: str
    product_label: Optional[str]             # 제품명/브랜드명 추정 (응답 문장용)
    ingredients: List[IngredientCandidate]   # 확정 성분 목록 (비면 needs_clarification)
    needs_clarification: bool                # True → 판정 스킵, 재질문 반환
    clarification_question: Optional[str]    # 재질문 본문 (LLM 생성 또는 기본 문장)
    clarification_candidates: List[str]      # 제품 후보 목록 (MFDS 히트)
    from_message: bool = True                # 현재 메시지에서 추출(True) vs 히스토리 복원(False)


# ──────────────────────────────────────────────────────────
# 공개 함수
# ──────────────────────────────────────────────────────────

def resolve_supplement(
    message: str,
    explicit_supplement: Optional[str] = None,
    history: Optional[List[dict]] = None,
) -> SupplementResolution:
    """
    사용자 입력 → SupplementResolution 반환.

    판정 파이프라인이 사용하는 유일한 해석 진입점.
    """
    text = (message or "").strip()

    # A. explicit supplement 필드 — UI에서 명시 입력된 경우
    if explicit_supplement and explicit_supplement.strip():
        result = _try_keyword(explicit_supplement.strip(), source="explicit")
        if result:
            return SupplementResolution(
                raw_input=text,
                product_label=explicit_supplement.strip(),
                ingredients=result,
                needs_clarification=False,
                clarification_question=None,
                clarification_candidates=[],
                from_message=False,
            )

    # A. 키워드/별칭 — 현재 메시지
    if text:
        result = _try_keyword(text, source="keyword")
        if result:
            return SupplementResolution(
                raw_input=text,
                product_label=result[0].key,
                ingredients=result,
                needs_clarification=False,
                clarification_question=None,
                clarification_candidates=[],
                from_message=True,
            )

    # B. MFDS 제품 검색 — 복수 성분 추출
    if text:
        mfds_result = _try_mfds(text)
        if mfds_result is not None:
            resolution, candidates = mfds_result
            if resolution:
                return SupplementResolution(
                    raw_input=text,
                    product_label=text,
                    ingredients=resolution,
                    needs_clarification=False,
                    clarification_question=None,
                    clarification_candidates=[],
                    from_message=True,
                )
            elif candidates:
                # 복수 제품 → 재질문
                q = _build_clarification_question(text, candidates)
                return SupplementResolution(
                    raw_input=text,
                    product_label=None,
                    ingredients=[],
                    needs_clarification=True,
                    clarification_question=q,
                    clarification_candidates=candidates,
                    from_message=True,
                )

    # C. LLM 구조화 추출
    if text:
        llm_result = _try_llm(text)
        if llm_result:
            low_conf = [c for c in llm_result if c.confidence < _LLM_CONFIDENCE_MIN]
            if not low_conf:
                # 모두 충분한 신뢰도
                product_label = _extract_brand_hint(text) or llm_result[0].key
                return SupplementResolution(
                    raw_input=text,
                    product_label=product_label,
                    ingredients=llm_result,
                    needs_clarification=False,
                    clarification_question=None,
                    clarification_candidates=[],
                    from_message=True,
                )
            else:
                # 신뢰도 낮은 항목 있음 → 재질문
                q = _build_clarification_question(text, [])
                return SupplementResolution(
                    raw_input=text,
                    product_label=None,
                    ingredients=[],
                    needs_clarification=True,
                    clarification_question=q,
                    clarification_candidates=[],
                    from_message=True,
                )

    # D. 히스토리 복원 — 이전 대화에서 영양제를 찾은 경우
    if history:
        hist_key, hist_label = _try_history(history)
        if hist_key:
            return SupplementResolution(
                raw_input=text,
                product_label=hist_label,
                ingredients=[IngredientCandidate(
                    key=hist_key,
                    confidence=_KEYWORD_CONFIDENCE,
                    source="history",
                )],
                needs_clarification=False,
                clarification_question=None,
                clarification_candidates=[],
                from_message=False,
            )

    # 모든 단계 실패
    return SupplementResolution(
        raw_input=text,
        product_label=None,
        ingredients=[],
        needs_clarification=True,
        clarification_question=None,
        clarification_candidates=[],
        from_message=True,
    )


# ──────────────────────────────────────────────────────────
# 내부 헬퍼: A — 키워드/별칭
# ──────────────────────────────────────────────────────────

def _try_keyword(text: str, source: str = "keyword") -> Optional[List[IngredientCandidate]]:
    """
    _SUPPLEMENT_ALIASES 기반 정확 매칭 — 문장 내 **모든** canonical key 추출.
    1개 이상 성공하면 IngredientCandidate 리스트, 실패하면 None.
    """
    try:
        keys = _keyword_all_matches(text)
        if keys:
            return [
                IngredientCandidate(key=k, confidence=_KEYWORD_CONFIDENCE, source=source)
                for k in keys
            ]
    except Exception as e:
        logger.debug(f"keyword match 실패: {e}")
    return None


def _keyword_only_match(text: str):
    """
    단일 canonical key 반환 (하위 호환용).
    (canonical_key, original_term) 반환. 실패하면 (None, None).
    """
    keys = _keyword_all_matches(text)
    if keys:
        return keys[0], None
    return None, None


def _keyword_all_matches(text: str) -> List[str]:
    """
    _SUPPLEMENT_ALIASES 사전을 이용해 메시지에서 **모든** canonical key를 추출.

    알고리즘:
      - 긴 alias 우선 매칭 (오버랩 방지)
      - 이미 소비된 텍스트 범위는 재사용하지 않아 "오메가3+비타민D" 같은 복수 성분 처리
    """
    from domain.thyroid.rules import SUPPLEMENT_RULES, _SUPPLEMENT_ALIASES  # type: ignore[attr-defined]

    t = text.strip().lower()
    sorted_aliases = sorted(_SUPPLEMENT_ALIASES.keys(), key=len, reverse=True)

    found: List[str] = []
    seen_keys: set = set()
    consumed: List[tuple] = []  # [(start, end), …] 소비된 위치

    def _is_consumed(start: int, end: int) -> bool:
        for s, e in consumed:
            if start < e and end > s:
                return True
        return False

    for alias in sorted_aliases:
        idx = 0
        while True:
            pos = t.find(alias, idx)
            if pos == -1:
                break
            end_pos = pos + len(alias)
            if not _is_consumed(pos, end_pos):
                canonical = _SUPPLEMENT_ALIASES[alias]
                if canonical in SUPPLEMENT_RULES and canonical not in seen_keys:
                    seen_keys.add(canonical)
                    found.append(canonical)
                    consumed.append((pos, end_pos))
            idx = pos + 1

    return found


# ──────────────────────────────────────────────────────────
# 내부 헬퍼: B — MFDS 복수 성분 추출
# ──────────────────────────────────────────────────────────

def _try_mfds(text: str):
    """
    MFDS health_food 검색 후 복수 canonical 추출.
    반환:
      (List[IngredientCandidate], [])   — 성분 확정 (단일·복수)
      (None, List[str])                 — 복수 제품 hit → 재질문 후보 목록
      None                              — DB 없음·오류·미인식
    """
    try:
        from domain.mfds.db import search_product_candidates
        candidates = search_product_candidates(text)

        if candidates.needs_clarification and candidates.product_names:
            # 복수 제품 → 재질문 후보 목록 반환
            return None, candidates.product_names[:5]

        if candidates.canonical:
            # 기존 단일 canonical
            ingredients = [IngredientCandidate(
                key=candidates.canonical,
                confidence=_MFDS_CONFIDENCE,
                source="mfds",
            )]
            # 매칭된 제품의 base_standard에서 추가 성분 추출 시도
            extra = _mfds_extract_multi(text, exclude={candidates.canonical})
            ingredients.extend(extra)
            return ingredients, []

    except Exception as e:
        logger.debug(f"MFDS 검색 실패: {e}")
    return None


def _mfds_extract_multi(text: str, exclude: set) -> List[IngredientCandidate]:
    """
    health_food 검색 결과의 base_standard/primary_function 전체 파싱 →
    exclude에 없는 추가 canonical key 목록 반환.
    복합제(켈프 등) 추가 성분 추출에 사용.
    """
    try:
        import sqlite3
        from domain.mfds.db import _get_conn  # type: ignore[attr-defined]
        from domain.thyroid.rules import normalize_supplement_name, SUPPLEMENT_RULES  # type: ignore[attr-defined]

        conn = _get_conn()
        t = f"%{text.lower()}%"
        rows = conn.execute(
            "SELECT base_standard, primary_function FROM health_food "
            "WHERE LOWER(item_name) LIKE ? LIMIT 5",
            (t,),
        ).fetchall()
        conn.close()

        _NOISE_TOKENS = {
            "성상", "납", "카드뮴", "비소", "총수은", "대장균", "이미", "이취",
            "표시량", "함유", "유지", "추출물", "분말", "정제", "캡슐", "정",
            "mg", "mcg", "iu", "이하", "이상", "함량", "기준",
        }

        found: List[IngredientCandidate] = []
        seen: set = set(exclude)

        for row in rows:
            base = (row[0] or "").strip()
            primary = (row[1] or "").strip()
            combined = primary + "\n" + base

            for tok in re.split(r'[\s,;\(\)/·\-\[\]]+', combined):
                tok = tok.strip()
                if len(tok) < 2 or tok.lower() in _NOISE_TOKENS:
                    continue
                key = normalize_supplement_name(tok)
                if key and key not in seen and key in SUPPLEMENT_RULES:
                    seen.add(key)
                    found.append(IngredientCandidate(
                        key=key,
                        confidence=_MFDS_CONFIDENCE,
                        source="mfds",
                    ))

        return found

    except Exception as e:
        logger.debug(f"MFDS 복수 성분 추출 실패: {e}")
        return []


# ──────────────────────────────────────────────────────────
# 내부 헬퍼: C — LLM 다중 성분 추출
# ──────────────────────────────────────────────────────────

def _try_llm(text: str) -> Optional[List[IngredientCandidate]]:
    """
    LLM 으로 화이트리스트 key + confidence 배열 추출.
    실패·미인식이면 None 반환.
    """
    try:
        import json as _json
        from domain.consultation.pubmed.openai_client import _get_openai_client  # type: ignore[attr-defined]
        from domain.thyroid.rules import SUPPLEMENT_RULES  # type: ignore[attr-defined]

        registered = list(SUPPLEMENT_RULES.keys())
        client = _get_openai_client()
        prompt = (
            "당신은 영양제·건강기능식품 성분 분류 전문가입니다.\n"
            "아래 사용자 문장에서 언급된 영양제·건강기능식품의 주성분을 파악하고,"
            " 등록된 canonical key 목록에서 매핑하세요.\n\n"
            f"[사용자 문장]\n{text}\n\n"
            f"[등록된 canonical key 목록]\n{', '.join(registered)}\n\n"
            "규칙:\n"
            "1. JSON 형식으로 반환:\n"
            '   {"product_label": "사용자가 말한 제품/브랜드명", '
            '"ingredients": [{"key": "canonical_key", "confidence": 0.0~1.0}]}\n'
            "2. ingredients 는 화학적으로 정확히 부합하는 성분만. 억지 매핑 금지.\n"
            "3. 성분이 없거나 목록에 없으면: "
            '{"product_label": "none", "ingredients": []}\n'
            "4. 브랜드명만(예: 고려은단, 종근당) 단독 언급이면 "
            '{"product_label": "브랜드명", "ingredients": []}\n'
            "5. confidence: 1.0=확실, 0.8=높음, 0.6=중간, 0.4=낮음.\n"
            "6. 설명 금지."
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = _json.loads(response.choices[0].message.content)
        raw_ingredients = raw.get("ingredients") or []
        if not raw_ingredients:
            return None

        results: List[IngredientCandidate] = []
        for item in raw_ingredients:
            key = (item.get("key") or "").strip().lower()
            conf = float(item.get("confidence") or 0.0)
            if key and key != "none" and key in SUPPLEMENT_RULES:
                results.append(IngredientCandidate(key=key, confidence=conf, source="llm"))

        return results if results else None

    except Exception as e:
        logger.debug(f"LLM 성분 추출 실패: {e}")
        return None


# ──────────────────────────────────────────────────────────
# 내부 헬퍼: D — 히스토리 복원
# ──────────────────────────────────────────────────────────

def _try_history(history: List[dict]):
    """
    이전 대화에서 영양제를 찾는다.
    (canonical_key, original_label) 반환. 없으면 (None, None).
    """
    try:
        from domain.thyroid.rules import infer_supplement_from_message  # type: ignore[attr-defined]
        for h in reversed(history):
            role = h.get("role", "")
            # structured 필드 우선
            h_supp = h.get("supplement")
            if h_supp:
                key, _ = _keyword_only_match(h_supp)
                if key:
                    return key, h_supp
            # 사용자 메시지 텍스트 재추출
            if role == "user":
                msg = h.get("message", "")
                if msg:
                    key, orig = _keyword_only_match(msg)
                    if key:
                        return key, orig
    except Exception as e:
        logger.debug(f"히스토리 복원 실패: {e}")
    return None, None


# ──────────────────────────────────────────────────────────
# 내부 헬퍼: 재질문 생성
# ──────────────────────────────────────────────────────────

def _build_clarification_question(user_input: str, candidates: List[str]) -> str:
    """재질문 LLM 생성. 실패 시 기본 문자열."""
    try:
        from domain.thyroid.llm_response import generate_clarification_response  # type: ignore[attr-defined]
        msg = generate_clarification_response(
            candidates=candidates,
            user_message=user_input,
            history=None,
        )
        if msg:
            return msg
    except Exception:
        pass
    if candidates:
        cand_str = ", ".join(f"'{c}'" for c in candidates[:4])
        return (
            f"'{user_input}'에 해당하는 제품이 여러 개 검색됩니다: {cand_str}. "
            "어떤 제품을 찾으시나요? 목록에 없으면 성분명(예: 오메가3, 비타민D)으로 입력해 주세요."
        )
    return (
        f"'{user_input}'을(를) 인식하지 못했습니다. "
        "제품의 성분명(예: 오메가3, 비타민D, 셀레늄)으로 입력해 주시면 정확한 답변이 가능합니다."
    )


def _extract_brand_hint(text: str) -> Optional[str]:
    """
    메시지에서 브랜드/제품명 힌트 추출 (LLM 응답의 product_label 보조).
    간단 휴리스틱: 영문 대소문자 혼합 단어나 따옴표 안 텍스트.
    """
    quoted = re.findall(r"['\"](.+?)['\"]", text)
    if quoted:
        return quoted[0]
    # 영문+숫자 브랜드명 패턴 (예: "Nature Made D3")
    brand = re.findall(r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z0-9]+)*", text)
    if brand:
        return brand[0]
    return None
