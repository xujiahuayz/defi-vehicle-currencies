"""Canonical identities for exploratory and confirmatory model runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ddvc.paths import REPO_ROOT
from ddvc.provenance import portable_content_sha256, verify


MODEL_RUN_ID_FIELDS = (
    "family_id",
    "lane",
    "d3_generation",
    "exploration_generation",
    "lock_hash",
    "plan_hash",
    "engine_hash",
)
LEGACY_MODEL_STATUSES = {
    "exploratory",
    "admissible",
    "diagnostic",
    "withheld",
    "retired",
}
MODEL_RUN_LANES = {"exploratory", "confirmatory"}
MODEL_RUN_LIFECYCLES = {"planned", "executed", "retired"}
MODEL_RUN_DISPOSITIONS = {
    "not_assessed",
    "admissible",
    "diagnostic",
    "withheld",
    "rejected",
}
MODEL_RUN_ARTIFACT_ROLES = {
    "result",
    "falsifier",
    "diagnostic",
    "support",
    "resampling",
}
REGISTERED_CLAIM_STATUSES = {
    "registered_primary",
    "registered_foundation",
    "registered_mechanism",
    "registered_companion",
}
REGISTERED_SPECIFICATION_KINDS = {
    "primary",
    "alternative",
    "falsifier",
    "diagnostic",
}


def canonical_hash(payload: Any) -> str:
    """Return the stable SHA-256 identity of a JSON-compatible contract."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def model_run_id(run: Mapping[str, Any]) -> str:
    """Bind a run to its lane, data, exploration, lock, plan, and engine."""
    return canonical_hash({key: run.get(key) for key in MODEL_RUN_ID_FIELDS})


def generation_id(certificate: Mapping[str, Any]) -> str:
    """Hash a release certificate without its self-declared generation field."""
    return canonical_hash(
        {key: value for key, value in certificate.items() if key != "generation"}
    )


def mandatory_check_ids(claim: Mapping[str, Any]) -> set[str]:
    """Expand every registered alternative leaf plus the falsifier."""
    checks = {"falsifier"}

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")
        else:
            checks.add(path)

    visit(claim.get("mandatory_alternatives") or {}, "mandatory_alternatives")
    return checks


def validate_registered_plan(claim: Mapping[str, Any]) -> tuple[bool, str]:
    """Require one exact E1 plan covering every alternative and falsifier."""
    specifications = claim.get("registered_specifications")
    if not isinstance(specifications, list) or not specifications:
        return False, "registered_specifications=missing"
    specification_ids = [
        str(specification.get("spec_id") or "")
        for specification in specifications
        if isinstance(specification, dict)
    ]
    incomplete = [
        str(specification.get("spec_id") or "missing")
        for specification in specifications
        if not isinstance(specification, dict)
        or not {"spec_id", "kind", "parameters", "covers"}.issubset(specification)
        or not isinstance(specification.get("parameters"), dict)
        or not isinstance(specification.get("covers"), list)
        or not all(
            isinstance(check_id, str) and check_id
            for check_id in specification.get("covers", [])
        )
    ]
    invalid_kinds = [
        str(specification.get("spec_id") or "missing")
        for specification in specifications
        if isinstance(specification, dict)
        and specification.get("kind") not in REGISTERED_SPECIFICATION_KINDS
    ]
    covered = {
        str(check_id)
        for specification in specifications
        if isinstance(specification, dict)
        for check_id in specification.get("covers", [])
    }
    required = mandatory_check_ids(claim)
    missing_coverage = sorted(required - covered)
    unexpected_coverage = sorted(covered - required)
    declared_plan_hash = str(claim.get("plan_hash") or "")
    actual_plan_hash = canonical_hash(specifications)
    has_primary = any(
        isinstance(specification, dict)
        and specification.get("kind") == "primary"
        for specification in specifications
    )
    passed = bool(
        len(specification_ids) == len(specifications)
        and len(specification_ids) == len(set(specification_ids))
        and all(specification_ids)
        and not incomplete
        and not invalid_kinds
        and not missing_coverage
        and not unexpected_coverage
        and declared_plan_hash == actual_plan_hash
        and has_primary
    )
    return passed, (
        f"specifications={len(specifications)}; "
        f"plan_hash={'ok' if declared_plan_hash == actual_plan_hash else 'mismatch'}; "
        f"primary={'ok' if has_primary else 'missing'}; "
        f"incomplete={incomplete or 'none'}; invalid_kinds={invalid_kinds or 'none'}; "
        f"missing_coverage={missing_coverage or 'none'}; "
        f"unexpected_coverage={unexpected_coverage or 'none'}"
    )
