
from .context_builder import build_english_patient_context, generate_pubmed_queries
from .llm_prompts import _generate_one_line_summary
import json
from typing import List, Dict, Optional, Tuple
from .client import search_pubmed_realtime, fetch_pubmed_details
from .utils import _normalize_text, _core_subject_tokens
from .gating import (
    _primary_suggests_supplement_intervention, _requires_postop_hard_gate,
    _allows_pregnancy_context, _apply_scenario_hard_gate, _apply_final_directness_gate,
    _filter_articles_with_anchor
)
from .ranking import _anchor_tokens_from_query, _rank_articles_by_primary_subject
from .query_builder import _rescue_queries_for_primary, _backfill_queries_for_postop
from .pubmed_reranker import preselect_candidates, llm_rerank, RERANK_CANDIDATE_K, RERANK_TOP_K, split_for_grounding
from .pubmed_postfilter import summarize_evidence_levels
from .retriever import retrieve_pubmed_evidence

def collect_realtime_pubmed_evidence(
    user_input: str,
    conditions: str = "",
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    pre_slots: Optional[Dict] = None,
) -> Tuple[List[Dict], Dict]:
    """Compatibility wrapper for the shared PubMed retrieval core."""
    return retrieve_pubmed_evidence(
        user_input=user_input,
        conditions=conditions,
        medications=medications,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        pre_slots=pre_slots,
    )

def get_realtime_pubmed_evidence(
    user_input: str, 
    conditions: str = "", 
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    pre_slots: Optional[Dict] = None,
) -> List[Dict]:
    articles, _ = collect_realtime_pubmed_evidence(
        user_input=user_input,
        conditions=conditions,
        medications=medications,
        age=age,
        sex=sex,
        height=height,
        weight=weight,
        pre_slots=pre_slots,
    )
    return articles

from .openai_client import _get_openai_client
from .query_builder import get_rda_ul_context_for_subject
from .ranking import _split_articles_for_grounding_llm, _direct_postop_evidence_count
from .gating import _has_general_postop_signal, _is_rai_related_article
from .pubmed_postfilter import postprocess_answer, evidence_badge

def build_basic_pubmed_answer(
    user_input: str,
    articles: List[Dict],
    conditions: str = "",
    medications: str = "",
) -> str:
    if not articles:
        return "PubMed 검색은 수행했지만 관련 논문을 찾지 못했습니다."
    lines = [
        "PubMed API 기반 요약입니다.",
        f"- 질문: {user_input}",
    ]
    if conditions:
        lines.append(f"- 질환: {conditions}")
    if medications:
        lines.append(f"- 복용약: {medications}")
    lines.append("")
    lines.append("상위 논문:")
    for art in articles[:3]:
        lines.append(f"- {art.get('title')} ({art.get('year')})")
        if art.get("one_line_summary"):
            lines.append(f"  - 요약: {art.get('one_line_summary')}")
        lines.append(f"  - PMID: {art.get('pmid')}")
    return "\n".join(lines)


def generate_pubmed_grounded_answer(
    user_input: str,
    articles: List[Dict],
    conditions: str = "",
    medications: str = "",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    height: Optional[float] = None,
    weight: Optional[float] = None,
    english_context: Optional[Dict] = None,
) -> str:
    if not articles:
        return "[Legacy Engine] 관련된 최신 PubMed 논문을 찾지 못했습니다. 상단 'Patient Portal' 탭을 이용하시거나 브라우저를 강력 새로고침(Ctrl+F5) 해주세요."

    client = _get_openai_client()

    if (
        english_context
        and isinstance(english_context, dict)
        and str(english_context.get("primary_subject", "") or "").strip()
    ):
        ctx = english_context
    else:
        ctx = build_english_patient_context(
            user_input=user_input,
            conditions=conditions,
            medications=medications,
            age=age,
            sex=sex,
            height=height,
            weight=weight,
        )
    primary_subject = str(ctx.get("primary_subject", "") or "").strip()
    require_postop_answer = _requires_postop_hard_gate(
        user_input,
        primary_subject,
        str(ctx.get("extra_keywords", "") or ""),
    )

    # 새 모듈 split_for_grounding 사용
    grounding_articles, weak_evidence = split_for_grounding(articles, primary_subject)

    # postop 질문에서 RAI 간접근거와 일반 postop 직접근거를 분리
    q_lower = f"{str(user_input or '').lower()} {str(ctx.get('extra_keywords', '') or '').lower()}"
    query_mentions_rai = any(k in q_lower for k in ["rai", "radioiodine", "iodine-131", "방사성요오드"])
    if require_postop_answer and grounding_articles and not query_mentions_rai:
        # 질문이 일반 postop인데 RAI가 아닌 직접근거를 우선 순위로 배치
        non_rai_direct = [a for a in grounding_articles if _has_general_postop_signal(a) and not _is_rai_related_article(a)]
        rai_indirect = [a for a in grounding_articles if _is_rai_related_article(a)]
        other = [a for a in grounding_articles if a not in non_rai_direct and a not in rai_indirect]
        grounding_articles = non_rai_direct + rai_indirect + other

    direct_postop_n = _direct_postop_evidence_count(grounding_articles) if require_postop_answer else len(grounding_articles)
    rai_indirect_n = sum(1 for a in grounding_articles if _is_rai_related_article(a)) if require_postop_answer else 0
    allowed_pmids = [str(a.get("pmid", "")) for a in grounding_articles if a.get("pmid")]
    pmid_allowlist = ", ".join(allowed_pmids) if allowed_pmids else "(없음)"

    context_parts = []
    for idx, art in enumerate(grounding_articles):
        rel = art.get("primary_subject_relevance")
        ev_level = art.get("evidence_level", "unknown")
        pub_types_str = ", ".join(art.get("pub_types", []) or [])
        # 논문별 메타데이터 노트 (관련도 + evidence level + 논문 유형)
        meta_note = f" [근거강도: {evidence_badge(ev_level)}"
        if pub_types_str:
            meta_note += f" | 유형: {pub_types_str}"
        if rel is not None:
            meta_note += f" | 관련도: {rel}"
        meta_note += "]"
        context_parts.append(
            f"[{idx+1}] Title: {art['title']} ({art['year']}){meta_note}\n"
            f"Abstract: {art['abstract']}\nPMID: {art['pmid']}"
        )

    pubmed_context = "\n\n".join(context_parts) if context_parts else "(질문 주제와 직접 맞는 초록이 없어 일반 가이드 위주로 답하세요.)"

    patient_info = [
        f"- 질환: {conditions or '없음'}",
        f"- 복용약: {medications or '없음'}",
    ]
    if primary_subject:
        patient_info.append(f"- 질문 핵심 주제(영문): {primary_subject}")
    if age:
        patient_info.append(f"- 나이: {age}세")
    if sex:
        patient_info.append(f"- 성별: {'남성' if sex == 'M' else '여성' if sex == 'F' else sex}")
    if height:
        patient_info.append(f"- 키: {height}cm")
    if weight:
        patient_info.append(f"- 몸무게: {weight}kg")

    patient_context = "\n".join(patient_info)
    guideline_context = get_rda_ul_context_for_subject(primary_subject, age, sex)

    weak_note = ""
    if weak_evidence:
        weak_note = (
            "\n[경고] 아래 초록은 모두 질문 핵심 주제와의 **직접 관련도가 낮게** 평가되었습니다. "
            "**어떤 PMID도 근거로 인용하지 마세요.** 일반 원칙·가이드라인 중심으로 답하세요.\n"
        )

    evidence_track_note = ""
    if require_postop_answer:
        evidence_track_note = (
            f"\n[근거 트랙 분류]\n"
            f"- Track A (일반 postop 직접근거): {direct_postop_n}편\n"
            f"- Track B (RAI 관련 간접근거): {rai_indirect_n}편\n"
            f"- 질문에 RAI 언급이 없으면 Track B는 보조근거로만 사용하세요.\n"
        )

    prompt = f"""당신은 의사용 임상 의사결정 지원을 제공하는 전문의입니다.
아래 [PubMed 논문 근거]는 **답변에 인용해도 되는 논문만** 포함되어 있습니다 (검색 파이프라인에서 주제 관련도로 선별).

[환자 프로필]
{patient_context}

[영양소 섭취 가이드라인]
{guideline_context}

[사용자 질문]
{user_input}

[인용 허용 PMID — 이 번호만 [PMID: …]로 쓸 수 있음]
{pmid_allowlist}
{weak_note}
{evidence_track_note}
[PubMed 논문 근거 — 위 인용 허용 목록에 해당하는 초록만 포함]
{pubmed_context}

[지침]
0. **의사용 톤**: 환자에게 직접 말하듯이 쓰지 말고, 의사가 바로 활용할 수 있는 형태로 간결하게 작성하세요.
   - "주치의와 상담하세요/담당 의사와 상의하세요" 같은 문구는 쓰지 마세요.
1. **질문 우선**: 질문 핵심 주제(위 환자 프로필의 영문 주제)에 맞게 답하세요.
2. **PMID 사용 범위**: 답변에 [PMID: 숫자]를 쓸 수 있는 것은 **위 [인용 허용 PMID]에 나열된 번호만**입니다. 목록이 비었거나 경고가 있으면 **PMID를 전혀 쓰지 마세요.**
3. **끝줄 근거 목록 금지**: 답변 **마지막에** "근거:", "참고 문헌:", "PMID: …" 형태로 **PMID만 한 줄에 나열하지 마세요.** (문장마다 필요할 때만 해당 문장 뒤에 [PMID: X] 허용)
4. **근거 구분**: "제공된 논문 초록에 따르면"과 "일반적인 의학적 원리·가이드라인에 따르면"을 명확히 구분하세요.
5. **무관 주제**: 초록이 질문 성분(예: 철분)과 맞지 않으면 그 사실을 말하고, 칼슘·비타민D 등 **다른 주제 논문으로 철분 결론을 대체하지 마세요.**
6. **교과서적 상호작용**(철분-칼슘 흡수 간격 등)은 PMID 없이 "일반적인 의학적 원리에 따르면"으로 서술해도 됩니다.
7. **정직한 답변**: 직접 근거가 없으면 부족하다고 명시한 뒤, [영양소 섭취 가이드라인]과 표준적인 임상 안전 프레임(금기/주의군/모니터링/검사)을 제시하세요.
7-1. 수술후 맥락 질문이고 Track A(일반 postop 직접근거)가 2편 미만({direct_postop_n}편)일 때:
   - "일반적으로 안전하다", "권장된다", "효과적이다" 같은 단정 문구를 쓰지 마세요.
   - "직접 근거는 제한적이며, 간접 근거 기반의 조건부 판단"으로 표현하세요.
7-2. 질문에 RAI 언급이 없고 Track B(RAI 간접근거)만 있는 경우:
   - RAI 결과를 일반 수술후 회복의 직접효과로 단정하지 마세요.
   - "RAI 관련 간접근거"임을 명시하고 보조근거로만 해석하세요.
8. 출력 형식(권장):
   - (1) 결론(한 줄)
   - (2) 근거 요약(해당 시 문장 끝 [PMID: X])
   - (3) 안전성/상호작용 체크리스트(불확실하면 불확실하다고)
   - (4) 추가 확인 질문(필요시)
9. 한국어로 전문적이고 간결하게 작성하세요.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw_answer = response.choices[0].message.content.strip()
        # postprocess_answer: PMID 화이트리스트 → 의사용 톤 → 섹션 포맷 (새 postfilter 모듈)
        return postprocess_answer(raw_answer, allowed_pmids=allowed_pmids, weak_evidence=bool(weak_evidence))
    except Exception as e:
        print(f"[pubmed_service] generate_pubmed_grounded_answer error: {e}")
        return build_basic_pubmed_answer(
            user_input=user_input,
            articles=articles,
            conditions=conditions,
            medications=medications,
        )


