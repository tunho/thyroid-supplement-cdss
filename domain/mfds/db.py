"""
domain.mfds.db — 식약처 로컬 SQLite DB 스키마 및 조회 모듈

data/mfds_cache.db 에 저장된 5개 API 데이터를 조회합니다.
데이터 수집은 scripts/sync_mfds_db.py 를 실행하세요.
"""
import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "mfds_cache.db")
)


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """테이블 및 인덱스 생성 (이미 존재하면 무시)."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dur_ingredient (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            dur_no              TEXT,
            dur_type            TEXT,
            ingredient_code     TEXT,
            ingredient_name_kr  TEXT,
            ingredient_name_en  TEXT,
            prohibited_content  TEXT,
            dosage_form         TEXT,
            notice_date         TEXT,
            raw_json            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_di_kr ON dur_ingredient(ingredient_name_kr);
        CREATE INDEX IF NOT EXISTS idx_di_en ON dur_ingredient(ingredient_name_en);
        CREATE INDEX IF NOT EXISTS idx_di_type ON dur_ingredient(dur_type);

        CREATE TABLE IF NOT EXISTS dur_product (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            item_seq            TEXT,
            item_name           TEXT,
            ingredient_name     TEXT,
            dur_type            TEXT,
            prohibited_content  TEXT,
            raw_json            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dp_item ON dur_product(item_name);
        CREATE INDEX IF NOT EXISTS idx_dp_ingr ON dur_product(ingredient_name);
        CREATE INDEX IF NOT EXISTS idx_dp_type ON dur_product(dur_type);

        CREATE TABLE IF NOT EXISTS drug_approval (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            item_seq            TEXT,
            item_name           TEXT,
            ingredient_name_kr  TEXT,
            ingredient_name_en  TEXT,
            company             TEXT,
            product_type        TEXT,
            raw_json            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_da_name   ON drug_approval(item_name);
        CREATE INDEX IF NOT EXISTS idx_da_ing_en ON drug_approval(ingredient_name_en);

        CREATE TABLE IF NOT EXISTS drug_easy (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            item_seq     TEXT,
            item_name    TEXT,
            effect       TEXT,
            usage_method TEXT,
            caution      TEXT,
            interaction  TEXT,
            side_effect  TEXT,
            raw_json     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_de_name ON drug_easy(item_name);

        CREATE TABLE IF NOT EXISTS health_food (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            item_no          TEXT,
            item_name        TEXT,
            company          TEXT,
            primary_function TEXT,
            intake_amount    TEXT,
            base_standard    TEXT,  -- 성분 + 용량 정보 (BASE_STANDARD)
            intake_hint      TEXT,  -- 섭취 주의사항 (INTAKE_HINT1)
            raw_json         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hf_name ON health_food(item_name);
        CREATE INDEX IF NOT EXISTS idx_hf_base ON health_food(base_standard);

        CREATE TABLE IF NOT EXISTS health_food_ingredient (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            recognition_no      TEXT,   -- 인정번호 (I-0040: HF_FNCLTY_MTRAL_RCOGN_NO)
            recognition_date    TEXT,   -- 인정일자 (PRMS_DT)
            company             TEXT,   -- 업체명 (BSSH_NM)
            raw_material_name   TEXT,   -- 신청원료명 (APLC_RAWMTRL_NM)
            daily_intake        TEXT,   -- 1일 섭취량 (DAY_INTK_CN)
            intake_caution      TEXT,   -- 섭취시 주의사항 (IFTKN_ATNT_MATR_CN)
            primary_function    TEXT,   -- 기능성 내용 (FNCLTY_CN)
            raw_json            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hfi_name ON health_food_ingredient(raw_material_name);
        CREATE INDEX IF NOT EXISTS idx_hfi_no   ON health_food_ingredient(recognition_no);
    """)
    conn.commit()
    conn.close()


def _to_list(rows) -> List[Dict]:
    return [dict(r) for r in rows]


# ── 공개 조회 함수 ──────────────────────────────────────────────────────────

def search_dur_ingredient(term: str) -> List[Dict]:
    """성분명(한/영)으로 DUR 성분 금기정보 검색."""
    t = f"%{term.lower()}%"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM dur_ingredient "
        "WHERE LOWER(ingredient_name_kr) LIKE ? OR LOWER(ingredient_name_en) LIKE ?",
        (t, t),
    ).fetchall()
    conn.close()
    return _to_list(rows)


def search_dur_product(
    term: str,
    dur_type: Optional[str] = None,
) -> List[Dict]:
    """
    품목명 또는 성분명으로 DUR 품목 조회.
    dur_type: '병용금기' | '임부금기' | '노인주의' | '특정연령금기' | None(전체)
    """
    t = f"%{term.lower()}%"
    conn = _get_conn()
    if dur_type:
        rows = conn.execute(
            "SELECT * FROM dur_product "
            "WHERE (LOWER(item_name) LIKE ? OR LOWER(ingredient_name) LIKE ?) "
            "AND dur_type = ?",
            (t, t, dur_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM dur_product "
            "WHERE LOWER(item_name) LIKE ? OR LOWER(ingredient_name) LIKE ?",
            (t, t),
        ).fetchall()
    conn.close()
    return _to_list(rows)


def normalize_drug_name(name: str) -> Optional[str]:
    """
    환자 입력 약물명(한글/상품명) → 영문 성분명 정규화.
    예: '씬지로이드' → 'levothyroxine sodium'
    """
    t = f"%{name.lower()}%"
    conn = _get_conn()
    row = conn.execute(
        "SELECT ingredient_name_en FROM drug_approval "
        "WHERE LOWER(item_name) LIKE ? AND ingredient_name_en != '' LIMIT 1",
        (t,),
    ).fetchone()
    conn.close()
    return row["ingredient_name_en"].lower().strip() if row else None


def search_easy_drug(term: str) -> List[Dict]:
    """e약은요 — 상호작용·부작용·주의사항 조회."""
    t = f"%{term.lower()}%"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM drug_easy WHERE LOWER(item_name) LIKE ?",
        (t,),
    ).fetchall()
    conn.close()
    return _to_list(rows)


def search_health_food(term: str) -> List[Dict]:
    """건강기능식품 제품명 검색."""
    t = f"%{term.lower()}%"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM health_food WHERE LOWER(item_name) LIKE ?",
        (t,),
    ).fetchall()
    conn.close()
    return _to_list(rows)


def search_ingredient_info(term: str) -> List[Dict]:
    """건강기능식품 개별인정형 원료 검색 (원료명 기준)."""
    t = f"%{term.lower()}%"
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM health_food_ingredient WHERE LOWER(raw_material_name) LIKE ?",
        (t,),
    ).fetchall()
    conn.close()
    return _to_list(rows)


def extract_canonical_from_product_name(text: str) -> Optional[str]:
    """
    제품명/브랜드명 텍스트에서 MFDS health_food DB를 통해 canonical 영양성분 key 추출.
    예: "네이쳐메이드 오메가3" → "omega3"
    매핑 실패 또는 DB 없으면 None 반환.
    """
    from domain.thyroid.rules import normalize_supplement_name

    if not text or len(text.strip()) < 2:
        return None

    try:
        conn = _get_conn()

        # 1) 입력 전체로 제품명 검색
        t = f"%{text.lower()}%"
        rows = conn.execute(
            "SELECT base_standard, primary_function FROM health_food "
            "WHERE LOWER(item_name) LIKE ? LIMIT 5",
            (t,),
        ).fetchall()

        # 2) 단어 분리 후 각 단어로 검색 (전체 검색 실패 시)
        word_search = False
        if not rows:
            import re
            raw_words = [w.strip() for w in re.split(r'[\s\-_]+', text.lower()) if w.strip()]
            words = []
            for w in raw_words:
                cleaned = re.sub(r'(은|는|이|가|을|를|의|에|에서|으로|로|품)$', '', w)
                if len(cleaned) >= 2:
                    words.append(cleaned)
            for word in words:
                wt = f"%{word}%"
                rows = conn.execute(
                    "SELECT base_standard, primary_function FROM health_food "
                    "WHERE LOWER(item_name) LIKE ? LIMIT 5",
                    (wt,),
                ).fetchall()
                if rows:
                    word_search = True
                    break

        conn.close()

        if not rows:
            return None

        # 단어 검색으로 5개 히트(LIMIT 도달) = 브랜드명만 입력한 경우 → 모호함
        # 추출된 canonical이 2가지 이상이면 None 반환 (재질문은 thyroid.py에서 처리)
        if word_search and len(rows) >= 5:
            return None

        import re

        # 무의미 토큰 필터 (성상, 납, 카드뮴 등 성분과 무관한 단어)
        _NOISE_TOKENS = {
            "성상", "납", "카드뮴", "비소", "총수은", "대장균", "이미", "이취",
            "표시량", "함유", "유지", "추출물", "분말", "정제", "캡슐", "정",
            "mg", "mcg", "iu", "이하", "이상", "이하", "함량", "기준",
        }

        def _try_tokens(text_chunk: str) -> Optional[str]:
            """텍스트에서 토큰 분리 후 canonical 매핑 시도."""
            for token in re.split(r'[\s,;\(\)/·\-]+', text_chunk):
                token = token.strip()
                if len(token) < 2 or token.lower() in _NOISE_TOKENS:
                    continue
                canonical = normalize_supplement_name(token)
                if canonical:
                    return canonical
            return None

        for row in rows:
            primary = (row[1] or "").strip()
            base = (row[0] or "").strip()

            # 1) primary_function의 [성분명] 패턴 파싱
            bracket_names = re.findall(r'\[([^\]]+)\]', primary)
            for bname in bracket_names:
                result = _try_tokens(bname)
                if result:
                    return result

            # 2) primary_function의 "- 비타민A :" 또는 "비타민A :" 패턴 파싱
            dash_names = re.findall(r'[-•]\s*([^:：\n]+)\s*[:：]', primary)
            for dname in dash_names:
                result = _try_tokens(dname.strip())
                if result:
                    return result

            # 3) base_standard에서 "비타민 A : 표시량..." 형태 파싱
            for line in base.splitlines():
                # "성상" 행 완전 건너뜀
                if "성상" in line:
                    continue
                # "항목명 : 수치" 행에서 항목명 부분만 추출
                colon_match = re.match(r'\s*[\d\)]*\s*([^:：\d\(]+)\s*[:：]', line)
                if colon_match:
                    candidate = colon_match.group(1).strip()
                    result = _try_tokens(candidate)
                    if result:
                        return result

    except Exception as e:
        print(f"[mfds.db] extract_canonical_from_product_name 오류: {e}")

    return None


@dataclass
class ProductCandidates:
    """브랜드/제품명 검색 결과."""
    product_names: List[str] = field(default_factory=list)
    canonical: Optional[str] = None
    needs_clarification: bool = False


def search_product_candidates(text: str) -> ProductCandidates:
    """
    브랜드명/제품명으로 DB 검색 후 후보 목록 반환.
    - 결과 1~2개 or 단일 canonical → needs_clarification=False, canonical 반환
    - 결과 3개 이상 or 복수 canonical → needs_clarification=True, 제품 목록 반환
    """
    from domain.thyroid.rules import normalize_supplement_name

    import re

    _NOISE_TOKENS = {
        "성상", "납", "카드뮴", "비소", "총수은", "대장균", "이미", "이취",
        "표시량", "함유", "유지", "추출물", "분말", "정제", "캡슐", "정",
        "mg", "mcg", "iu", "이하", "이상", "함량", "기준",
    }

    def _extract_canonical_from_row(row) -> Optional[str]:
        try:
            item_name = (row["item_name"] or "").strip()
        except IndexError:
            item_name = ""
        
        if any(k in item_name.replace(" ", "") for k in ["멀티비타민", "종합비타민"]):
            return "multivitamin"

        try:
            primary = (row["primary_function"] or "").strip()
        except IndexError:
            primary = ""
            
        try:
            base = (row["base_standard"] or "").strip()
        except IndexError:
            base = ""

        def _try(chunk):
            for tok in re.split(r'[\s,;\(\)/·\-]+', chunk):
                tok = tok.strip()
                if len(tok) < 2 or tok.lower() in _NOISE_TOKENS:
                    continue
                c = normalize_supplement_name(tok)
                if c:
                    return c
            return None

        for bname in re.findall(r'\[([^\]]+)\]', primary):
            r = _try(bname)
            if r:
                return r
        for dname in re.findall(r'[-•]\s*([^:：\n]+)\s*[:：]', primary):
            r = _try(dname.strip())
            if r:
                return r
        for line in base.splitlines():
            if "성상" in line:
                continue
            m = re.match(r'\s*[\d\)]*\s*([^:：\d\(]+)\s*[:：]', line)
            if m:
                r = _try(m.group(1).strip())
                if r:
                    return r
        return None

    if not text or len(text.strip()) < 2:
        return ProductCandidates()

    try:
        conn = _get_conn()

        # 1) 전체 텍스트 검색
        t = f"%{text.lower()}%"
        rows = conn.execute(
            "SELECT item_name, base_standard, primary_function FROM health_food "
            "WHERE LOWER(item_name) LIKE ? LIMIT 8",
            (t,),
        ).fetchall()

        # 2) 단어별 검색 (전체 실패 시) — 질문/동사 불용어 제외
        _STOP_WORDS = {
            "먹어도", "먹어", "먹는", "먹을", "먹고", "복용", "섭취", "드셔도",
            "되나", "되나요", "될까", "돼요", "괜찮나", "괜찮은가", "괜찮아",
            "해도", "해요", "할까", "가능한가", "가능해", "어때", "어떤가",
            "어떻게", "어떤지", "좋나", "좋은가", "좋아", "안되나", "안돼",
            "위험", "안전", "먹나", "먹음", "먹지", "해서", "하면", "하나",
            "나", "내", "내가", "저", "제가", "너", "당신", "우리", "이거",
            "그거", "저거", "식품", "건강식품", "영양제", "제품", "브랜드",
        }
        word_used = None
        if not rows:
            raw_words = [w.strip() for w in re.split(r'[\s\-_]+', text.lower()) if w.strip()]
            words = []
            for w in raw_words:
                cleaned = re.sub(r'(은|는|이|가|을|를|의|에|에서|으로|로|품)$', '', w)
                if len(cleaned) >= 2 and cleaned not in _STOP_WORDS:
                    words.append(cleaned)
            if len(words) > 1:
                # 2-1) 다중 단어 교집합(AND) 검색 우선 수행
                and_clauses = " AND ".join(["LOWER(item_name) LIKE ?" for _ in words])
                and_params = [f"%{w}%" for w in words]
                rows = conn.execute(
                    f"SELECT item_name, base_standard, primary_function FROM health_food "
                    f"WHERE {and_clauses} LIMIT 8",
                    and_params,
                ).fetchall()
            
            # 2-2) 개별 단어 검색 (AND 결과도 없을 때만) — 글자 수가 가장 긴 명사부터 매칭하여 브랜드 노이즈 최소화
            if not rows and words:
                words_sorted = sorted(words, key=len, reverse=True)
                for word in words_sorted:
                    wt = f"%{word}%"
                    rows = conn.execute(
                        "SELECT item_name, base_standard, primary_function FROM health_food "
                        "WHERE LOWER(item_name) LIKE ? LIMIT 8",
                        (wt,),
                    ).fetchall()
                    if rows:
                        word_used = word
                        break

        conn.close()

        if not rows:
            return ProductCandidates()

        product_names = [r["item_name"] for r in rows if r["item_name"]][:5]
        canonicals = []
        for row in rows:
            c = _extract_canonical_from_row(row)
            if c and c not in canonicals:
                canonicals.append(c)

        # 1. 사용자의 입력과 완전히 똑같은 이름의 제품이 있는지(Exact match) 최우선 확인
        exact_match = next((r for r in rows if r["item_name"] and r["item_name"].strip().lower() == text.strip().lower()), None)
        if exact_match:
            c = _extract_canonical_from_row(exact_match)
            if c:
                return ProductCandidates(
                    product_names=[exact_match["item_name"]],
                    canonical=c,
                    needs_clarification=False,
                )

        # 2. 검색된 여러 제품 중, 룰 엔진과 매핑되는 주성분(canonical)이 하나도 없다면?
        # 제품을 고르게 해봤자 어차피 모르는 성분이므로, 아예 빈 값을 던져 '미식별 예외 처리(unrecognized)'로 넘깁니다. (무한 루프 원천 차단)
        if len(canonicals) == 0:
            return ProductCandidates()

        # 3. 단일 canonical → 바로 반환
        if len(canonicals) == 1:
            return ProductCandidates(
                product_names=product_names,
                canonical=canonicals[0],
                needs_clarification=False,
            )

        # 4. 복수 canonical or 브랜드명만 입력(8개 히트) → 재질문
        if len(rows) >= 3 or len(canonicals) > 1:
            return ProductCandidates(
                product_names=product_names,
                canonical=None,
                needs_clarification=True,
            )

        return ProductCandidates(product_names=product_names, canonical=canonicals[0] if canonicals else None)

    except Exception as e:
        print(f"[mfds.db] search_product_candidates 오류: {e}")
        return ProductCandidates()


def get_db_stats() -> Dict[str, int]:
    """테이블별 저장 건수 반환 (동기화 확인용)."""
    tables = ["drug_approval", "health_food", "health_food_ingredient"]
    try:
        conn = _get_conn()
        stats = {}
        for tbl in tables:
            try:
                stats[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            except Exception:
                stats[tbl] = -1
        conn.close()
        return stats
    except Exception:
        return {tbl: -1 for tbl in tables}
