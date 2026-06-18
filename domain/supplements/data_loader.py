import os
import json
from dataclasses import dataclass
from typing import Dict, List, Optional
import glob


@dataclass
class Document:
    id: int
    question: str
    answer: str
    category: Optional[str] = None
    source_file: str = ""


INTERNAL_SCHEMA_VERSION = "product_v1"

CATEGORY_RULES = [
    ("프로바이오틱스", ["프로바이오틱", "유산균", "락토", "비피더스", "프리바이오틱", "포스트바이오틱"]),
    ("오메가3", ["오메가3", "omega-3", "epa", "dha", "어유", "크릴"]),
    ("비타민D", ["비타민d", "vitamin d", "d3"]),
    ("비타민B", ["비타민b", "vitamin b", "엽산", "folate", "b1", "b2", "b6", "b12", "나이아신"]),
    ("비타민C", ["비타민c", "vitamin c", "아스코르빈"]),
    ("멀티비타민", ["종합비타민", "멀티비타민", "multivitamin"]),
    ("철분", ["철분", "iron"]),
    ("아연", ["아연", "zinc"]),
    ("셀레늄", ["셀레늄", "셀렌", "selenium"]),
    ("요오드", ["요오드", "아이오딘", "iodine"]),
    ("칼슘/마그네슘", ["칼슘", "마그네슘", "calcium", "magnesium"]),
    ("홍삼", ["홍삼", "인삼", "ginseng", "진세노사이드"]),
    ("단백질/아미노산", ["단백질", "프로틴", "아미노산", "bcaa", "카르니틴", "티로신", "타우린"]),
    ("관절/뼈", ["관절", "연골", "msm", "글루코사민", "콘드로이친", "보스웰리아", "뼈"]),
    ("눈건강", ["눈", "루테인", "지아잔틴", "아스타잔틴"]),
    ("간건강", ["간", "밀크씨슬", "실리마린"]),
    ("체지방/다이어트", ["다이어트", "체지방", "가르시니아", "녹차카테킨"]),
    ("면역", ["면역"]),
    ("여성건강", ["여성", "갱년기", "월경", "폐경"]),
    ("남성건강", ["남성", "전립선"]),
    ("어린이", ["키즈", "어린이", "베이비"]),
]


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_key(value: str) -> str:
    return _clean_text(value).replace(" ", "").lower()


def _first_nonempty(*values) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _merge_text_fields(*values) -> str:
    merged: List[str] = []
    seen = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = _normalize_key(cleaned)
        if key and key not in seen:
            merged.append(cleaned)
            seen.add(key)
    return "\n".join(merged)


def infer_category(
    product_name: str,
    functionality: str,
    ingredients: str,
    file_category: str = "",
) -> str:
    """
    전체 제품을 넓은 도메인 카테고리로 분류합니다.
    """
    if file_category and file_category not in {"API_건강기능식품", ".", ""}:
        return file_category

    text = f"{_clean_text(product_name)} {_clean_text(functionality)} {_clean_text(ingredients)}".lower()
    for category, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "기타"


def normalize_product_record(raw: dict, file_category: str = "") -> Dict[str, str]:
    """
    원본 JSON은 그대로 두고, 서비스 내부에서 사용할 표준 스키마로 변환합니다.
    - 중복 필드(주의사항/섭취주의사항)는 병합
    - 비어 있는 값은 빈 문자열로 유지
    - 이후 로직은 이 스키마만 사용하도록 고정
    """
    product_name = _first_nonempty(raw.get("제품명"), raw.get("PRDLST_NM"))
    functionality = _first_nonempty(raw.get("주된기능성"), raw.get("PRIMARY_FNCLTY"))
    intake_method = _first_nonempty(raw.get("섭취방법"), raw.get("NTK_MTHD"))
    warnings = _merge_text_fields(
        raw.get("섭취주의사항"),
        raw.get("주의사항"),
        raw.get("IFTKN_ATNT_MATR_CN"),
    )
    ingredients = _first_nonempty(raw.get("원재료전체"), raw.get("RAWMTRL_NM"))
    standard = _first_nonempty(raw.get("기준규격"), raw.get("STDR_STND"))
    manufacturer = _first_nonempty(raw.get("제조사"), raw.get("업소명"), raw.get("BSSH_NM"))
    report_no = _first_nonempty(raw.get("신고번호"), raw.get("품목제조신고번호"), raw.get("PRDLST_REPORT_NO"))
    shape = _first_nonempty(raw.get("제형"), raw.get("PRDT_SHAP_CD_NM"), raw.get("SHAP"))
    shelf_life = _first_nonempty(raw.get("소비기한"), raw.get("유통기한"), raw.get("POG_DAYCNT"))
    storage = _first_nonempty(raw.get("보존주의사항"), raw.get("CSTDY_MTHD"))
    product_type = _first_nonempty(raw.get("품목유형"), raw.get("PRDLST_DCNM"))
    appearance = _first_nonempty(raw.get("성상"), raw.get("DISPOS"))

    category = infer_category(
        product_name=product_name,
        functionality=functionality,
        ingredients=ingredients,
        file_category=file_category,
    )

    return {
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "name": product_name,
        "manufacturer": manufacturer,
        "report_no": report_no,
        "shelf_life": shelf_life,
        "appearance": appearance,
        "intake_method": intake_method,
        "functionality": functionality,
        "ingredients_raw": ingredients,
        "warnings": warnings,
        "storage_notes": storage,
        "shape": shape,
        "product_type": product_type,
        "standard": standard,
        "category": category,
    }


def _parse_product_record(raw: dict, file_category: str, source_file: str, doc_id: int) -> Optional[Document]:
    product = normalize_product_record(raw=raw, file_category=file_category)
    product_name = product["name"]
    if not product_name:
        return None

    context_text = f"""[제품명] {product['name']}
[기능성] {product['functionality']}
[섭취방법] {product['intake_method']}
[주의사항] {product['warnings']}
[원재료] {product['ingredients_raw']}
[기준규격] {product['standard']}
[업체명] {product['manufacturer']}
[신고번호] {product['report_no']}
[제형] {product['shape']}
[품목유형] {product['product_type']}
[소비기한] {product['shelf_life']}
[보관주의] {product['storage_notes']}
[분류] {product['category']}
[스키마버전] {product['schema_version']}
"""

    search_keywords = " ".join(
        x for x in [
            product["name"],
            product["functionality"].replace("\n", " "),
            product["ingredients_raw"].replace("\n", " "),
            product["warnings"].replace("\n", " "),
            product["category"],
        ] if x
    )

    return Document(
        id=doc_id,
        question=search_keywords,
        answer=context_text,
        category=product["category"],
        source_file=source_file,
    )


def load_data(data_dir: str, prefer_raw_all: bool = True) -> List[Document]:
    """
    건강기능식품 제품 JSON 데이터를 로드합니다.
    - prefer_raw_all=True 이면 raw_all_products.json(식약처 전체) 우선 사용
    - 없으면 개별 JSON들을 재귀 로드
    """
    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"Directory not found: {data_dir}")

    documents: List[Document] = []
    global_id = 0
    seen_keys = set()

    raw_all_path = os.path.join(data_dir, "raw_all_products.json")
    if prefer_raw_all and os.path.exists(raw_all_path):
        print(f"Loading full MFDS product catalog from {raw_all_path} ...")
        with open(raw_all_path, "r", encoding="utf-8") as f:
            raw_list = json.load(f)

        if not isinstance(raw_list, list):
            raise ValueError("raw_all_products.json is not a JSON list.")

        for row in raw_list:
            if not isinstance(row, dict):
                continue

            normalized = normalize_product_record(row)
            dedupe_key = _normalize_key(normalized["report_no"]) or _normalize_key(normalized["name"])
            if not dedupe_key or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            doc = _parse_product_record(
                raw=row,
                file_category="",
                source_file="raw_all_products.json",
                doc_id=global_id,
            )
            if doc is None:
                continue

            documents.append(doc)
            global_id += 1

        print(f"Successfully loaded {len(documents)} products from raw_all_products.json.")
        return documents

    print(f"Scanning JSON files in {data_dir}...")
    json_files = glob.glob(os.path.join(data_dir, "**", "*.json"), recursive=True)
    print(f"Found {len(json_files)} JSON files. Loading...")

    for file_path in json_files:
        source_file = os.path.basename(file_path)
        file_category = os.path.basename(os.path.dirname(file_path))
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue

            normalized = normalize_product_record(row, file_category=file_category)
            dedupe_key = _normalize_key(normalized["report_no"]) or _normalize_key(normalized["name"])
            if not dedupe_key or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            doc = _parse_product_record(
                raw=row,
                file_category=file_category,
                source_file=source_file,
                doc_id=global_id,
            )
            if doc is None:
                continue

            documents.append(doc)
            global_id += 1

    print(f"Successfully loaded {len(documents)} products.")
    return documents