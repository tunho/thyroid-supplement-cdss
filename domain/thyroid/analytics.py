"""
domain.thyroid.analytics — 의사 variability 분석 모듈

audit/*.jsonl → 영양제별 결정 분포, 의사 간 불일치 집계.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

_DEFAULT_AUDIT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "audit"


def load_audit_records(audit_dir: Path = _DEFAULT_AUDIT_DIR) -> list[dict]:
    records = []
    if not audit_dir.exists():
        return []
    for f in sorted(audit_dir.glob("decisions_*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return records


def summarize_by_supplement(records: list[dict]) -> dict[str, Any]:
    summary: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in records:
        supp = r.get("supplement", "unknown")
        decision = r.get("decision", "unknown")
        summary[supp][decision] += 1
    return {k: dict(v) for k, v in summary.items()}


def summarize_variability(records: list[dict]) -> dict[str, Any]:
    groups: dict[tuple, list[str]] = defaultdict(list)
    for r in records:
        req = r.get("request_summary", {})
        dx = req.get("conditions", "")
        if isinstance(dx, list):
            dx = ",".join(str(x) for x in dx)
        key = (r.get("supplement", ""), dx)
        groups[key].append(r.get("decision", ""))

    result = {}
    for (supp, dx), decisions in groups.items():
        if len(decisions) < 2:
            continue
        unique = set(decisions)
        if len(unique) < 2:
            continue
        result[f"{supp}|{dx}"] = {
            "total": len(decisions),
            "decisions": {d: decisions.count(d) for d in unique},
            "variability_score": round(
                1 - max(decisions.count(d) for d in unique) / len(decisions), 3
            ),
        }
    return result


def summarize_by_physician_profile(records: list[dict]) -> dict[str, Any]:
    """
    의사 성향(risk_tolerance × supplement) 별 결정 분포.
    variability 분석의 핵심 — 동일 영양제에 대해 성향별 결정이 얼마나 다른가.
    """
    groups: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in records:
        prof = r.get("physician_profile", {})
        tol = prof.get("risk_tolerance", "unknown")
        supp = r.get("supplement", "unknown")
        decision = r.get("decision", "unknown")
        key = f"{supp}|{tol}"
        groups[key][decision] += 1
    return {k: dict(v) for k, v in groups.items()}


def export_csv(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp", "supplement", "decision", "confidence",
        "applied_rules", "safety_warning_count", "evidence_count",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
