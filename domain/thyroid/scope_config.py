"""
domain.thyroid.scope_config — 질환 후순위 처리 설정 (§4.2)

DEFERRED_CONDITION_KEYS: 초기 버전에서 rationale note만 추가하는 질환 목록.
rule 로직은 유지하되, orchestrator에서 후순위 안내 문구를 rationale에 포함.
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════
# §4.2 후순위(DEFERRED) 질환 key
# rule 로직은 유지; orchestrator 에서 rationale note 추가
# ══════════════════════════════════════════════════════════
DEFERRED_CONDITION_KEYS: frozenset[str] = frozenset({
    "thyroid_cancer",
    "thyroidectomy_postop",
    "graves_orbitopathy",
    "goiter",
    "thyroid_nodule",
    "thyroid_nodule_benign",
    "autonomous_thyroid_nodule",
})


def is_deferred_condition(key: str) -> bool:
    """질환 key 가 초기 버전 후순위 목록에 포함되는지 반환."""
    return key in DEFERRED_CONDITION_KEYS
