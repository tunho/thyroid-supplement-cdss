


# ── 새 모듈 import (상대·절대 양쪽 호환) ────────────────────────────────────
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
REQUEST_TIMEOUT_SEC = 20
MAX_RETRIES = 2
BACKOFF_BASE_SEC = 1.0

TERM_TRANSLATIONS = {
    "칼슘제": "calcium supplement",
    "칼슘": "calcium",
    "비타민d": "vitamin d",
    "비타민 d": "vitamin d",
    "비타민c": "vitamin c",
    "비타민 c": "vitamin c",
    "비타민b12": "vitamin b12",
    "오메가3": "omega-3 fatty acids",
    "오메가 3": "omega-3 fatty acids",
    "크롬": "chromium",
    "마그네슘": "magnesium",
    "밀크씨슬": "milk thistle",
    "종합비타민": "multivitamin",
    "코엔자임q10": "coenzyme q10",
    "coq10": "coenzyme q10",
    "고혈압": "hypertension",
    "고지혈증": "hyperlipidemia",
    "고중성지방혈증": "hypertriglyceridemia",
    "당뇨": "diabetes",
    "당뇨병": "diabetes mellitus",
    "골다공증": "osteoporosis",
    "갑상선기능저하증": "hypothyroidism",
    "갑상선기능항진증": "hyperthyroidism",
    "갑상선": "thyroid",
    "지방간": "fatty liver",
    "만성 신질환": "chronic kidney disease",
    "신질환": "kidney disease",
    "고칼슘혈증": "hypercalcemia",
    "arb": "angiotensin receptor blocker",
    "스타틴": "statin",
    "메트포르민": "metformin",
    "항생제": "antibiotics",
    "항응고제": "anticoagulants",
    "항혈소판제": "antiplatelet agents",
    "병용": "coadministration",
    "같이 먹": "coadministration",
    "상호작용": "interaction",
    "주의": "safety",
    "안전": "safety",
    "효과": "effect",
    "복용": "administration",
    "추가로": "additional",
}

STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "in", "on", "for", "of", "to", "and",
    "with", "about", "patient", "female", "male", "year", "old", "taking", "use",
}

# PubMed 본문에 자주 등장하는 영문 표기만 유지. 미등록 성분은 AI PrimarySubject로 커버합니다.
SUPPLEMENT_HINTS = [
    "vitamin d", "calcium supplement", "calcium",
    "omega-3 fatty acids", "chromium",
    "magnesium", "milk thistle", "multivitamin", "coenzyme q10", "vitamin c", "vitamin b12",
]
CONDITION_HINTS = [
    "osteoporosis", "hypertension", "hyperlipidemia", "hypertriglyceridemia",
    "diabetes", "diabetes mellitus", "hypothyroidism", "hyperthyroidism",
    "fatty liver", "chronic kidney disease", "hypercalcemia",
]
MEDICATION_HINTS = [
    "angiotensin receptor blocker", "statin", "metformin", "antibiotics",
    "anticoagulants", "antiplatelet agents",
]

# 갑상선 도메인 고정 검색용 키워드 (thyroid_rules.py와 동기화)

# 재랭킹 상수 (pubmed_reranker.py 와 동기화)

# 보충제(영양소) 질문: 제목·초록에 성분명만 언급된 논문(배경/리뷰) 오탐을 줄이기 위해
# '개입·시험·용량' 신호를 함께 요구합니다. (특정 질환 블랙리스트 없이 일반화)
SUPPLEMENT_EVIDENCE_HINTS = [
    "supplementation",
    "supplement",
    "selenomethionine",
    "randomized",
    "placebo",
    "clinical trial",
    "controlled trial",
    "double-blind",
    "single-blind",
    "intervention",
    "nutraceutical",
]

# To fix circular or missing imports in processor

RDA_UL_GUIDELINES = {
    "calcium": {
        "M": {
            "19-49": {"RDA": 800, "UL": 2500},
            "50-64": {"RDA": 750, "UL": 2500},
            "65+": {"RDA": 700, "UL": 2000},
        },
        "F": {
            "19-49": {"RDA": 700, "UL": 2500},
            "50+": {"RDA": 800, "UL": 2000},
        }
    },
    "iron": {
        "M": {
            "19+": {"RDA": 10, "UL": 45},
        },
        "F": {
            "19-49": {"RDA": 14, "UL": 45},
            "50+": {"RDA": 9, "UL": 45},
        }
    },
    "vitamin d": {
        "all": {
            "19-64": {"RDA": 10, "UL": 100},
            "65+": {"RDA": 15, "UL": 100},
        }
    },
    "magnesium": {
        "M": {"19+": {"RDA": 350, "UL": 350}},
        "F": {"19+": {"RDA": 280, "UL": 350}},
    },
    "vitamin c": {
        "all": {"19+": {"RDA": 100, "UL": 2000}},
    }
}
