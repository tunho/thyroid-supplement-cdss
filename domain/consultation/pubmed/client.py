from .text_normalizer import *
import requests
from typing import Dict
import os
import json
import time
import random
import xml.etree.ElementTree as ET
from typing import List, Dict

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
REQUEST_TIMEOUT_SEC = 20
MAX_RETRIES = 2
BACKOFF_BASE_SEC = 1.0

from .pubmed_postfilter import assign_evidence_level

def _request_with_retry(url: str, params: Dict[str, str]) -> requests.Response:
    """
    NCBI E-utilities 요청. 429/5xx 시 Retry-After 헤더 우선, 없으면 exponential backoff + jitter.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):  # 최대 3회 시도
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else (BACKOFF_BASE_SEC * (2 ** attempt))
                wait += random.uniform(0.1, 0.5)  # jitter
                print(f"[pubmed] 429 rate limit, waiting {wait:.1f}s (attempt {attempt})")
                if attempt <= MAX_RETRIES:
                    time.sleep(wait)
                    continue
                response.raise_for_status()
            elif response.status_code in {500, 502, 503, 504}:
                if attempt <= MAX_RETRIES:
                    wait = BACKOFF_BASE_SEC * attempt + random.uniform(0, 0.5)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt > MAX_RETRIES:
                break
            time.sleep(BACKOFF_BASE_SEC * attempt + random.uniform(0, 0.3))
    raise RuntimeError(f"PubMed request failed after {MAX_RETRIES + 1} attempts: {last_error}")

def search_pubmed_realtime(
    query: str,
    retmax: int = 5,
    mindate: str = "2021/01/01",
    high_quality_only: bool = True,
    domain_mode: str = "strict",
    sort: str = "relevance",
) -> List[str]:
    """
    PubMed 실시간 검색을 수행합니다.
    high_quality_only=True이면 Meta-Analysis, RCT, Systematic Review 필터를 적용합니다.
    """
    term = _strip_time_expressions_en(_normalize_english_query_text(query))
    term = _force_thyroid_domain_query(term, domain_mode=domain_mode)
    if not term:
        return []
    if high_quality_only:
        quality_filter = "(Meta-Analysis[Filter] OR Randomized Controlled Trial[Filter] OR Systematic Review[Filter])"
        term = f"({term}) AND {quality_filter}"

    params = {
        "db": "pubmed",
        "term": term,
        "retmax": retmax,
        "retmode": "json",
        "datetype": "pdat",
        "mindate": mindate,
        "sort": sort,
    }
    api_key = os.getenv("NCBI_API_KEY")
    if api_key and "optional" not in api_key.lower() and "your" not in api_key.lower():
        params["api_key"] = api_key

    try:
        response = _request_with_retry(ESEARCH_URL, params)
        data = response.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []

def fetch_pubmed_details(pmids: List[str]) -> List[Dict]:
    """
    PubMed XML에서 PMID·제목·연도·초록·pub_types·evidence_level을 파싱합니다.
    pub_types 가 있으면 evidence_level도 함께 계산합니다.
    """
    if not pmids:
        return []

    def _derive_pubmed_source_type(pub_types: List[str]) -> str:
        if not pub_types:
            return "PubMed"
        primary = str(pub_types[0]).strip()
        return primary or "PubMed"

    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    api_key = os.getenv("NCBI_API_KEY")
    if api_key and "optional" not in api_key.lower() and "your" not in api_key.lower():
        params["api_key"] = api_key

    try:
        response = _request_with_retry(EFETCH_URL, params)
        root = ET.fromstring(response.content)
        articles = []
        for article in root.findall(".//PubmedArticle"):
            pmid_node = article.find(".//PMID")
            if pmid_node is None:
                continue
            pmid = pmid_node.text or ""

            title_node = article.find(".//ArticleTitle")
            title = "".join(title_node.itertext()) if title_node is not None else "No Title"

            year_node = article.find(".//PubDate/Year")
            year = year_node.text if year_node is not None else "Unknown"

            abstract_parts = []
            for abstract_text in article.findall(".//AbstractText"):
                text = "".join(abstract_text.itertext())
                abstract_parts.append(text)
            abstract = "\n".join(abstract_parts) if abstract_parts else ""

            # PublicationType 목록 파싱
            pub_types: List[str] = []
            for pt_node in article.findall(".//PublicationType"):
                pt_text = (pt_node.text or "").strip()
                if pt_text and pt_text not in pub_types:
                    pub_types.append(pt_text)

            ev_level = assign_evidence_level(pub_types)

            articles.append({
                "pmid": pmid,
                "title": title,
                "year": year,
                "abstract": abstract,
                "pub_types": pub_types,
                "evidence_level": ev_level,
                "source_type": _derive_pubmed_source_type(pub_types),
                "abstract_only": True,
                "one_line_summary": None,
            })
        return articles
    except Exception as e:
        print(f"[pubmed_service] fetch_pubmed_details error: {e}")
        return []

