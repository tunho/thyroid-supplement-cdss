"""
갑상선 PubMed 파이프라인 — 도메인 규칙 테이블

모든 상수·맵·가중치를 이 파일에서 관리합니다.
하드코딩을 최소화하고 테이블 수정으로 동작을 조정할 수 있도록 설계했습니다.
"""

from typing import Dict, List, Set

# ─── 갑상선 도메인 앵커 키워드 ────────────────────────────────────────────
THYROID_DOMAIN_TERMS: List[str] = [
    "thyroid",
    "thyroidectomy",
    "hypothyroidism",
    "hyperthyroidism",
    "hashimoto",
    "graves",
    "thyroiditis",
    "levothyroxine",
    "thyroxine",
    "tsh",
    "thyroid cancer",
    "differentiated thyroid carcinoma",
    "radioiodine",
    "iodine-131",
]

# ─── 갑상선 임상 맥락 → PubMed anchor 문구 ──────────────────────────────
# 각 컨텍스트에서 쿼리 중심에 올 갑상선 임상 조건 표현
THYROID_CONTEXT_ANCHORS: Dict[str, str] = {
    "hashimoto":       "Hashimoto thyroiditis OR autoimmune thyroiditis",
    "graves":          "Graves disease OR hyperthyroidism",
    "hypothyroidism":  "hypothyroidism OR thyroid hormone deficiency",
    "hyperthyroidism": "hyperthyroidism OR thyrotoxicosis",
    "thyroid_cancer":  "thyroid cancer OR differentiated thyroid carcinoma OR papillary thyroid carcinoma",
    "postop":          "thyroidectomy OR postoperative thyroid surgery OR post-thyroidectomy",
    "levothyroxine":   "levothyroxine OR thyroid hormone replacement",
    "radioiodine":     "radioiodine OR iodine-131 OR radioactive iodine ablation",
    "general":         "thyroid",
}

# ─── Intent → 아웃컴 키워드 ────────────────────────────────────────────────
INTENT_OUTCOME_TERMS: Dict[str, List[str]] = {
    "efficacy": [
        "efficacy", "effectiveness", "benefit", "effect",
        "outcome", "response", "improvement",
    ],
    "safety": [
        "safety", "adverse", "toxicity", "side effect",
        "risk", "overdose", "tolerance",
    ],
    "interaction": [
        "interaction", "coadministration", "absorption",
        "interference", "bioavailability",
    ],
    "postop": [
        "postoperative", "post-surgical", "thyroidectomy",
        "complication", "wound healing",
    ],
    "dose": [
        "dose", "dosage", "optimal dose", "dose-response",
        "supplementation", "intake level",
    ],
    "monitoring": [
        "monitoring", "TSH", "free T4", "calcium",
        "parathyroid", "follow-up", "surveillance",
    ],
}

# ─── 논문 유형(PublicationType) → evidence level ──────────────────────────
PUBTYPE_EVIDENCE_LEVEL: Dict[str, str] = {
    # §10.2 EBM 피라미드 기반 재매핑 — EVIDENCE_RANK 키와 일치
    "Meta-Analysis":                         "meta_analysis",
    "Systematic Review":                     "systematic_review",
    "Randomized Controlled Trial":           "rct",
    "Randomized Controlled Trials as Topic": "rct",
    "Controlled Clinical Trial":             "rct",
    "Clinical Trial":                        "low-moderate",   # 비RCT 임상시험
    "Observational Study":                   "observational",
    "Cohort Study":                          "cohort",
    "Case-Control Study":                    "case_control",
    "Cross-Sectional Study":                 "observational",
    "Review":                                "low-moderate",
    "Case Reports":                          "case_report",
    "Comment":                               "insufficient",
    "Letter":                                "insufficient",
    "Editorial":                             "insufficient",
    "News":                                  "insufficient",
    "Published Erratum":                     "insufficient",
}

# ─── 논문 유형 분류 세트 ────────────────────────────────────────────────────
HIGH_QUALITY_PUBTYPES: Set[str] = {
    "Meta-Analysis",
    "Systematic Review",
    "Randomized Controlled Trial",
}
LOW_QUALITY_PUBTYPES: Set[str] = {
    "Case Reports",
    "Comment",
    "Letter",
    "Editorial",
    "News",
    "Published Erratum",
}

# ─── Scoring 가중치 (규칙 기반 1차 점수) ────────────────────────────────
# pubmed_service._article_subject_score에서 사용
SCORING_WEIGHTS: Dict[str, int] = {
    "thyroid_anchor_in_title":    7,
    "thyroid_anchor_in_abstract": 4,
    "thyroid_anchor_absent":      -10,
    "supplement_in_title":        5,
    "supplement_in_abstract":     3,
    "intent_term_in_abstract":    2,
    "high_quality_study":         4,   # Meta-Analysis / Systematic Review / RCT
    "low_quality_study":          -2,  # Case report / Letter / Editorial
    "veterinary_signal":          -8,
    "population_mismatch":        -5,
}

# ─── 오프토픽 감점 시그널 (도메인 불문) ────────────────────────────────────
OFFTOPIC_SIGNALS: List[str] = [
    "veterinary", "cattle", "poultry", "swine", "ovine", "bovine", "equine",
]

# ─── Population 분류 시그널 ─────────────────────────────────────────────────
POPULATION_SIGNALS: Dict[str, List[str]] = {
    "pregnancy":  ["pregnan", "gestational", "prenatal"],
    "postpartum": ["postpartum", "lactation", "breastfeeding"],
    "pediatric":  ["pediatric", "paediatric", "children", "infant", "neonatal"],
    "elderly":    ["elderly", "older adult", "aged"],
    "adult":      ["adult", "adults"],
}

# ─── 허용 성분 도메인(갑상선 상담용) ───────────────────────────────────────
# 요청된 성분군만 검색 대상으로 제한합니다.
# key: canonical PubMed query term
# value: 한/영 동의어·유의어
ALLOWED_SUPPLEMENT_SYNONYMS: Dict[str, List[str]] = {
    "vitamin d supplementation": [
        "비타민d", "비타민 d", "vitamin d", "vit d", "vitamin d3", "d3",
        "cholecalciferol", "콜레칼시페롤", "농축콜레칼시페롤",
    ],
    "levothyroxine": [
        "레보티록신", "levothyroxine", "thyroxine", "티록신", "t4",
        "씬지로이드", "신지로이드",
    ],
    "selenium supplementation": [
        "셀레늄", "셀렌", "selenium", "selenomethionine",
    ],
    "calcium": [
        "칼슘", "산호칼슘", "calcium", "coral calcium",
        "calcium carbonate", "calcium citrate",
    ],
    "retinyl acetate": [
        "레티놀아세테이트", "레티닐아세테이트", "retinyl acetate",
        "vitamin a acetate", "비타민a", "비타민 a", "retinol acetate",
    ],
    "iodine supplementation": [
        "요오드", "아이오딘", "iodine", "iodide", "potassium iodide",
    ],
    "omega-3 fatty acids": [
        "오메가3", "오메가-3", "omega-3", "omega3", "fish oil",
        "dha", "epa", "피쉬오일", "어유",
    ],
    "iron supplementation": [
        "철분", "iron", "ferrous", "ferritin", "철분제",
    ],
    "zinc supplementation": [
        "아연", "zinc",
    ],
    "magnesium supplementation": [
        "마그네슘", "magnesium",
    ],
    "probiotic supplementation": [
        "프로바이오틱스", "probiotics", "lactobacillus", "bifidobacterium",
    ],
    "ashwagandha": [
        "아슈와간다", "ashwagandha", "withania somnifera",
    ],
    "vitamin b12": [
        "비타민b12", "비타민 b12", "vitamin b12", "cobalamin", "cyanocobalamin",
    ],
    "vitamin c supplementation": [
        "비타민c", "비타민 c", "vitamin c", "ascorbic acid",
    ],
    "red ginseng": [
        "홍삼", "red ginseng", "korean red ginseng", "panax ginseng",
    ],
    "turmeric": [
        "강황", "turmeric", "curcumin", "커큐민",
    ],
    "black garlic": [
        "흑마늘", "black garlic", "aged garlic extract",
    ],
}

ALLOWED_SUPPLEMENT_CANONICALS: Set[str] = set(ALLOWED_SUPPLEMENT_SYNONYMS.keys())


JOURNAL_TIERS: dict[str, str] = {
    # Tier A
    "thyroid": "A",
    "journal of clinical endocrinology & metabolism": "A",
    "jcem": "A",
    "european thyroid journal": "A",
    # Tier B
    "american journal of clinical nutrition": "B",
    "clinical nutrition": "B",
    "nutrients": "B",
    "nutrition reviews": "B",
    "frontiers in endocrinology": "B",
    "public health nutrition": "B",
    "bmc nutrition": "B",
    # Tier C
    "geroscience": "C",
    "frontiers in physiology": "C",
    # Tier D
    "integrative medicine": "D",
}

TIER_SCORE_BONUS: dict[str, float] = {
    "A": 0.3,
    "B": 0.15,
    "C": 0.05,
    "D": 0.0,
}
