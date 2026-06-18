"""
domain.thyroid.safety_rules_engine — data-driven safety 규칙 로더 + 매처

명세 rule_construction_v5 §7 (PR-A) — safety.py 의 31 개 분기를 safety_rules.json
하나의 자료 파일로 분리. SafetyEngine 은 이 모듈만 사용.

trigger 키 (AND 결합):
  supplement_canonical           : canonical 정확 일치
  supplement_canonical_any       : canonical ∈ list
  supplement_canonical_not       : canonical ≠ value
  diagnosis_any                  : dx_set ∩ list ≠ ∅
  risk_factor_any                : risk_set ∩ list ≠ ∅
  rule_risk_tags_any             : rule.risk_tags ∩ list ≠ ∅
  medication_any                 : med_set ∩ list ≠ ∅ (정확 매칭)
  medication_keywords_any        : list 의 키워드가 med_set 항목의 substring
  age_lt / age_gte               : 환자 나이 임계
  lab_lt                         : {key: threshold} — key 의 값이 threshold 미만
  rule_none                      : rule is None
  rule_evidence_level_in         : rule.evidence_level ∈ list
  any_of                         : sub-trigger 리스트, OR
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "data" / "safety_rules.json"


def _load_rules(path: Path = DEFAULT_RULES_PATH) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _set_intersects(a: Set[str], b: List[str]) -> bool:
    bset = {str(x).strip().lower() for x in b}
    return bool({x.lower() for x in a} & bset)


def _med_keyword_match(med_set: Set[str], keywords: List[str]) -> bool:
    """med_set 의 어떤 항목 안에라도 키워드 substring 이 있으면 True."""
    for item in med_set:
        for kw in keywords:
            if kw.lower() in item.lower():
                return True
    return False


def _eval_trigger(
    trigger: Dict[str, Any],
    *,
    canonical: str,
    dx_set: Set[str],
    risk_set: Set[str],
    med_set: Set[str],
    rule_risk_tags: Set[str],
    rule: Optional[Dict[str, Any]],
    age: Optional[int],
    lab_values: Dict[str, Any],
) -> bool:
    """trigger AND 평가. 모든 키가 통과해야 True. 빈 trigger 는 항상 True."""
    if not trigger:
        return True

    for key, val in trigger.items():
        if key == "supplement_canonical":
            if canonical != val:
                return False
        elif key == "supplement_canonical_any":
            if canonical not in val:
                return False
        elif key == "supplement_canonical_not":
            if canonical == val:
                return False
        elif key == "diagnosis_any":
            if not _set_intersects(dx_set, val):
                return False
        elif key == "risk_factor_any":
            if not _set_intersects(risk_set, val):
                return False
        elif key == "rule_risk_tags_any":
            if not _set_intersects(rule_risk_tags, val):
                return False
        elif key == "medication_any":
            if not _set_intersects(med_set, val):
                return False
        elif key == "medication_keywords_any":
            if not _med_keyword_match(med_set, val):
                return False
        elif key == "age_lt":
            if age is None or age >= val:
                return False
        elif key == "age_gte":
            if age is None or age < val:
                return False
        elif key == "lab_lt":
            # 모든 (lab_key, threshold) 가 만족해야 함 (AND)
            for lab_key, threshold in val.items():
                raw = lab_values.get(lab_key)
                try:
                    num = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    num = None
                if num is None or num >= threshold:
                    return False
        elif key == "lab_gt":
            # 모든 (lab_key, threshold) 가 만족해야 함 (AND) — 초과
            for lab_key, threshold in val.items():
                raw = lab_values.get(lab_key)
                try:
                    num = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    num = None
                if num is None or num <= threshold:
                    return False
        elif key == "rule_none":
            if val is True and rule is not None:
                return False
            if val is False and rule is None:
                return False
        elif key == "rule_evidence_level_in":
            if rule is None or rule.get("evidence_level") not in val:
                return False
        elif key == "any_of":
            sub_pass = False
            for sub in val:
                if _eval_trigger(
                    sub,
                    canonical=canonical,
                    dx_set=dx_set,
                    risk_set=risk_set,
                    med_set=med_set,
                    rule_risk_tags=rule_risk_tags,
                    rule=rule,
                    age=age,
                    lab_values=lab_values,
                ):
                    sub_pass = True
                    break
            if not sub_pass:
                return False
        else:
            # 알 수 없는 trigger 키 → 안전하게 매치 실패
            return False

    return True


def _format_message(
    template: str,
    *,
    supplement_name: str,
    canonical: str,
    lab_values: Dict[str, Any],
    supplement_ko_map: Optional[Dict[str, str]] = None,
) -> str:
    """{supplement_name} / {supplement_canonical} / {lab.X} / {supplement_ko} 대체."""
    out = template
    out = out.replace("{supplement_name}", supplement_name)
    out = out.replace("{supplement_canonical}", canonical)
    if supplement_ko_map and canonical in supplement_ko_map:
        out = out.replace("{supplement_ko}", supplement_ko_map[canonical])
    # lab.X 처리
    while "{lab." in out:
        start = out.index("{lab.")
        end = out.index("}", start)
        key = out[start + len("{lab."):end]
        val = lab_values.get(key, "")
        out = out[:start] + str(val) + out[end + 1:]
    return out


def evaluate_safety_rules(
    *,
    rules: List[Dict[str, Any]],
    supplement_name: str,
    canonical: str,
    dx_set: Set[str],
    risk_set: Set[str],
    med_set: Set[str],
    rule: Optional[Dict[str, Any]],
    age: Optional[int],
    lab_values: Dict[str, Any],
    is_doctor_mode: bool,
    existing_categories: Set[str],
) -> List[Dict[str, Any]]:
    """
    매칭된 rule 의 결과 dict 리스트 반환:
        [{category, severity, message, recommended_action}]
    호출부가 SafetyWarning 으로 변환.
    """
    rule_risk_tags: Set[str] = set(rule.get("risk_tags", [])) if rule else set()
    out: List[Dict[str, Any]] = []
    used_categories: Set[str] = set(existing_categories)

    for r in rules:
        # supplement 단축 키 (top-level) — trigger 의 supplement_canonical 과 동일 의미
        s_top = r.get("supplement_canonical")
        if s_top is not None and s_top != canonical:
            continue

        trig = r.get("trigger", {})
        if not _eval_trigger(
            trig,
            canonical=canonical,
            dx_set=dx_set,
            risk_set=risk_set,
            med_set=med_set,
            rule_risk_tags=rule_risk_tags,
            rule=rule,
            age=age,
            lab_values=lab_values,
        ):
            continue

        # dedup_category: 이미 같은 카테고리 경고가 있으면 skip
        dedup_cat = r.get("dedup_category")
        if dedup_cat and dedup_cat in used_categories:
            continue

        # 메시지 선택 (patient/doctor)
        msg_p = r.get("message_template_patient") or r.get("message_patient", "")
        msg_d = r.get("message_template_doctor") or r.get("message_doctor", "")
        act_p = r.get("action_template_patient") or r.get("recommended_action_patient", "")
        act_d = r.get("action_template_doctor") or r.get("recommended_action_doctor", "")

        supp_ko_map = r.get("supplement_ko_map")

        msg = _format_message(
            msg_d if is_doctor_mode else msg_p,
            supplement_name=supplement_name,
            canonical=canonical,
            lab_values=lab_values,
            supplement_ko_map=supp_ko_map,
        )
        act = _format_message(
            act_d if is_doctor_mode else act_p,
            supplement_name=supplement_name,
            canonical=canonical,
            lab_values=lab_values,
            supplement_ko_map=supp_ko_map,
        )

        category = r["category"]
        out.append({
            "rule_id": r["rule_id"],
            "category": category,
            "severity": r["severity"],
            "message": msg,
            "recommended_action": act,
        })
        used_categories.add(category)

    return out


# ── module-level singleton ─────────────────────────────────
_rules_cache: Optional[List[Dict[str, Any]]] = None


def get_rules() -> List[Dict[str, Any]]:
    global _rules_cache
    if _rules_cache is None:
        _rules_cache = _load_rules()
    return _rules_cache


def reload_rules() -> None:
    """테스트에서 강제 reload 가능."""
    global _rules_cache
    _rules_cache = None
