from .openai_client import _get_openai_client
from .text_normalizer import *
import os
import json
from typing import List, Dict, Tuple, Optional
from openai import OpenAI
from .constants import *
from .utils import *
from .gating import _looks_like_sentence_primary, _is_valid_primary_subject, _requires_postop_hard_gate, _has_general_postop_signal, _is_rai_related_article
from .query_builder import get_rda_ul_context_for_subject
from .ranking import _split_articles_for_grounding_llm, _direct_postop_evidence_count
from .pubmed_postfilter import postprocess_answer, evidence_badge

def _english_pubmed_phrase_fallback(user_input: str) -> str:
    """
    JSON 키워드 추출 실패·빈 PrimarySubject 시, 한국어 질문을 한 줄 영문 PubMed 검색구로 변환합니다.
    (성분별 수동 매핑 대신 동일 모델로 일반화)
    """
    q = (user_input or "").strip()
    if not q:
        return ""
    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Convert the following Korean clinical question into ONE short English phrase "
                        "for PubMed search. Use standard ingredient names (e.g. iron supplement, zinc, "
                        "vitamin D, omega-3). Output only the phrase, no quotes or explanation.\n\n"
                        f"{q}"
                    ),
                }
            ],
            temperature=0,
            max_tokens=48,
        )
        return _normalize_english_query_text(response.choices[0].message.content or "")
    except Exception as e:
        print(f"[pubmed_service] English phrase fallback error: {e}")
        return _normalize_english_query_text(_translate_korean_text(q))



def _retry_primary_subject_strict(user_input: str, conditions: str = "", medications: str = "") -> str:
    """
    2차 재시도: PrimarySubject를 영문 성분/주제 구절로만 강제 추출.
    """
    try:
        client = _get_openai_client()
        prompt = f"""Extract ONE concise English PubMed subject phrase from this Korean question.

Question: {user_input}
Conditions: {conditions}
Medications: {medications}

Rules:
- Output ONLY the phrase (no JSON, no explanation).
- 1 to 5 words preferred.
- Must be in English letters/numbers.
- Do not include full sentence or polite endings.
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=24,
        )
        return _normalize_english_query_text(response.choices[0].message.content or "")
    except Exception as e:
        print(f"[pubmed_service] Strict primary retry error: {e}")
        return ""



def _extract_english_keywords_with_ai(user_input: str, conditions: str = "", medications: str = "") -> Dict[str, str]:
    """
    AI를 사용하여 질문의 핵심 성분(Primary Subject)과 검색용 키워드를 분리하여 추출합니다.
    """
    prompt = f"""다음 한국어 의학 질문과 환자 정보를 분석하여 PubMed 검색용 정보를 추출하세요.

[질문]
{user_input}

[환자 상태]
질환: {conditions}
복용약: {medications}

[지침]
1. 'PrimarySubject': 질문의 핵심 성분·주제를 **표준 영문 PubMed 검색어 한 구절**로 쓰세요.
   - 한국어 성분명은 반드시 영문으로 바꿉니다 (예: 철분/철분제 → iron supplement, 아연 → zinc, 오메가3 → omega-3 fatty acids).
   - 질문이 약물·질환 중심이면 그에 맞는 영문 표현을 쓰세요.
2. 'Keywords': 검색에 도움이 될 추가 의학 키워드들을 영문으로 나열하세요. (예: absorption, safety)
   - 'PrimarySubject'에 이미 들어간 단어는 반복하지 마세요.
   - 상호작용이 질문의 핵심일 때만 interaction 등을 넣으세요.
3. 불필요한 한국어 조사·어미는 제거하세요.
4. JSON만 출력하세요. 키 이름은 정확히 PrimarySubject, Keywords 입니다.
   예: {{"PrimarySubject": "...", "Keywords": "..."}}
"""
    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" },
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        primary = _normalize_english_query_text(
            str(raw.get("PrimarySubject") or raw.get("primarySubject") or raw.get("primary_subject") or "")
        )
        keywords = _normalize_english_query_text(
            str(raw.get("Keywords") or raw.get("keywords") or "")
        )
        if not _is_valid_primary_subject(primary):
            primary = _retry_primary_subject_strict(user_input, conditions, medications)
        if not _is_valid_primary_subject(primary):
            primary = _english_pubmed_phrase_fallback(user_input)
        # Keywords는 문장형이면 버리고 빈값으로 정리
        if _looks_like_sentence_primary(keywords):
            keywords = ""
        return {"PrimarySubject": primary, "Keywords": keywords}
    except Exception as e:
        print(f"[pubmed_service] AI Keyword Extraction Error: {e}")
        primary = _retry_primary_subject_strict(user_input, conditions, medications)
        if not _is_valid_primary_subject(primary):
            primary = _english_pubmed_phrase_fallback(user_input)
        return {"PrimarySubject": primary, "Keywords": ""}



def _generate_one_line_summary(article: Dict) -> str:
    client = _get_openai_client()
    prompt = f"""다음 의학 논문의 제목과 초록을 읽고, 환자 상담에 유용한 핵심 내용을 한국어 한 줄로 요약하세요.

제목: {article['title']}
초록: {article['abstract'][:1200]}

[지침]
1. 한국어 한 줄로만 작성하세요.
2. 과장 없이 핵심 결론 위주로 쓰세요.
3. 논문에 없는 내용은 쓰지 마세요.
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content.strip()



