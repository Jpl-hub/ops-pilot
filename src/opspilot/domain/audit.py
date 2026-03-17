from __future__ import annotations

from typing import Any


def build_audit(
    *,
    key_numbers: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    calculations: list[dict[str, Any]],
    min_evidence: int,
) -> dict[str, Any]:
    evidence_coverage = len(evidence)
    numeric_consistency = bool(key_numbers) and all(
        item.get("value") is not None for item in key_numbers
    )
    policy = "pass" if evidence_coverage >= min_evidence else "degraded"
    insufficient = evidence_coverage < min_evidence
    return {
        "numeric_consistency": numeric_consistency,
        "evidence_coverage": {
            "count": evidence_coverage,
            "meets_threshold": evidence_coverage >= min_evidence,
        },
        "policy": policy,
        "insufficient_evidence": insufficient,
        "calculation_steps": len(calculations),
    }
