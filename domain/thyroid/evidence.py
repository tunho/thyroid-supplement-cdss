"""
domain.thyroid.evidence — 근거 검색 서비스

기존 pubmed_service.py를 wrapper로 감싸서 EvidenceRecord 리스트를 반환합니다.
PubMed 호출 실패 시 graceful fallback (빈 리스트 + 로그).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from domain.thyroid.schemas import EvidenceLevel, EvidenceRecord

logger = logging.getLogger(__name__)

# evidence_level 문자열 → EvidenceLevel enum 매핑
_LEVEL_MAP = {
    "high": EvidenceLevel.META_ANALYSIS,
    "moderate": EvidenceLevel.RCT,
    "low-moderate": EvidenceLevel.RCT,
    "low": EvidenceLevel.OBSERVATIONAL,
    "insufficient": EvidenceLevel.INSUFFICIENT,
    "unknown": EvidenceLevel.INSUFFICIENT,
}


class EvidenceService:
    """PubMed 검색 wrapper. 기존 pubmed_service를 EvidenceRecord로 변환."""

    def search(
        self,
        query: str,
        conditions: str = "",
        medications: str = "",
        max_results: int = 5,
    ) -> List[EvidenceRecord]:
        """
        기존 pubmed_service.get_realtime_pubmed_evidence() 호출 후
        결과를 EvidenceRecord 리스트로 변환.
        실패 시 빈 리스트 반환 (서버 다운 방지).
        """
        try:
            from domain.consultation.pubmed import get_realtime_pubmed_evidence
        except ImportError:
            logger.warning("pubmed_service를 import할 수 없습니다. 빈 근거 리스트를 반환합니다.")
            return []

        try:
            raw_articles = get_realtime_pubmed_evidence(
                user_input=query,
                conditions=conditions,
                medications=medications,
            )
            records = []
            if raw_articles:
                records = [self._convert(art) for art in raw_articles[:max_results]]

            # MFDS guideline record 추가
            supplement_hint = query.split()[0] if query else ""
            records.append(EvidenceRecord(
                title=f"MFDS 식품안전나라 — {supplement_hint} 기준치",
                source_type="mfds",
                evidence_level=EvidenceLevel.GUIDELINE,
                url="https://www.foodsafetykorea.go.kr",
                journal_tier=None,
            ))
            return records
        except Exception as e:
            logger.error(f"PubMed 검색 실패: {e}", exc_info=True)
            return []

    def _convert(self, article: dict) -> EvidenceRecord:
        """PubMed 원시 dict → EvidenceRecord 변환."""
        from domain.consultation.pubmed.thyroid_rules import JOURNAL_TIERS

        pmid = str(article.get("pmid", "") or "")
        raw_level = str(article.get("evidence_level", "unknown") or "unknown").lower()
        evidence_level = _LEVEL_MAP.get(raw_level, EvidenceLevel.INSUFFICIENT)

        journal_raw = str(article.get("journal", "") or "").lower().strip()
        journal_tier = JOURNAL_TIERS.get(journal_raw, None)

        year: Optional[int] = None
        raw_year = article.get("year") or article.get("pub_date")
        if raw_year:
            try:
                year = int(str(raw_year)[:4])
            except (ValueError, TypeError):
                pass

        return EvidenceRecord(
            pmid=pmid if pmid else None,
            title=str(article.get("title", "") or ""),
            abstract=str(article.get("abstract", "") or "") or None,
            journal=str(article.get("journal", "") or "") or None,
            year=year,
            evidence_level=evidence_level,
            source_type="pubmed",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            journal_tier=journal_tier,
        )
