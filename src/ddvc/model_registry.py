"""Canonical identities for exploratory and confirmatory model runs."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ddvc.paths import REPO_ROOT
from ddvc.provenance import portable_content_sha256, verify


MODEL_RUN_ID_FIELDS = (
    "family_id",
    "claim_id",
    "lane",
    "selection_origin",
    "promoted_from_run_id",
    "decision_id",
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
FITTED_MODEL_ARTIFACT_ROLES = {
    "result",
    "falsifier",
    "diagnostic",
    "resampling",
}
DESIGN_SEED_CLAIM_STATUSES = {
    "candidate_primary",
    "candidate_foundation",
    "candidate_mechanism",
    "candidate_companion",
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
EXECUTION_GATE_OPEN = "open"
EXECUTION_BLOCKER_PATTERN = re.compile(r"blocked_[a-z0-9_]+")
EXPLORATORY_PLAN_IDENTITY_FIELDS = (
    "family_id",
    "claim_id",
    "d3_generation",
    "plan_path",
    "question",
    "search_dimensions",
    "search_dimension_spec_ids",
    "required_attack_ids",
    "attack_evidence",
    "runner",
    "arguments",
    "engine_sources",
    "estimator",
    "fixed_effects",
    "inference",
    "declared_artifacts",
    "note",
    "attempt",
    "retry_of_run_id",
)


@dataclass(frozen=True)
class ClaimExecutionPerimeter:
    """Stage-executable claims and every explicit exclusion."""

    stage: str
    executable_claims: tuple[dict[str, Any], ...]
    excluded_claims: tuple[dict[str, Any], ...]


def canonical_hash(payload: Any) -> str:
    """Return the stable SHA-256 identity of a JSON-compatible contract."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_statuses_for_stage(stage: str) -> frozenset[str]:
    """Return the only claim statuses executable at one research stage."""
    if stage == "design_seed":
        return frozenset(DESIGN_SEED_CLAIM_STATUSES)
    if stage == "confirmatory":
        return frozenset(REGISTERED_CLAIM_STATUSES)
    raise ValueError(f"invalid specification stage: {stage or 'missing'}")


def claim_execution_perimeter(specification: Mapping[str, Any]) -> ClaimExecutionPerimeter:
    """Classify every claim under one explicit stage and execution-gate policy."""
    stage = str(specification.get("stage") or "")
    executable_statuses = claim_statuses_for_stage(stage)
    claims = specification.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("specification lock has no claims")
    executable_claims: list[dict[str, Any]] = []
    excluded_claims: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    all_stage_statuses = DESIGN_SEED_CLAIM_STATUSES | REGISTERED_CLAIM_STATUSES
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("specification lock contains a non-object claim")
        claim_id = str(claim.get("id") or "")
        status = str(claim.get("status") or "")
        if not claim_id or not status:
            raise ValueError("specification lock contains a claim without an id or status")
        if claim_id in observed_ids:
            raise ValueError(f"specification lock contains a duplicate claim id: {claim_id}")
        observed_ids.add(claim_id)
        execution_gate = claim.get("execution_gate")
        if status in all_stage_statuses:
            if not isinstance(execution_gate, str) or not execution_gate:
                raise ValueError(f"stage claim must explicitly declare its execution gate: {claim_id}")
            if execution_gate != EXECUTION_GATE_OPEN and not EXECUTION_BLOCKER_PATTERN.fullmatch(execution_gate):
                raise ValueError(f"stage claim has an invalid execution gate: {claim_id}/{execution_gate}")
        if status in executable_statuses:
            if execution_gate == EXECUTION_GATE_OPEN:
                executable_claims.append(dict(claim))
                continue
            exclusion_reason = "execution_gate_not_open"
        else:
            if execution_gate is not None and not isinstance(execution_gate, str):
                raise ValueError(f"non-stage claim has a non-string execution gate: {claim_id}")
            exclusion_reason = f"status_not_executable_at_{stage}"
        excluded_claims.append(
            {
                "claim_id": claim_id,
                "status": status,
                "execution_gate": execution_gate,
                "exclusion_reason": exclusion_reason,
            }
        )
    return ClaimExecutionPerimeter(
        stage=stage,
        executable_claims=tuple(sorted(executable_claims, key=lambda claim: str(claim["id"]))),
        excluded_claims=tuple(sorted(excluded_claims, key=lambda record: record["claim_id"])),
    )


def _json_spec_ids(value: Any) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, dict):
        if "spec_id" in value:
            spec_id = value["spec_id"]
            if not isinstance(spec_id, str) or not spec_id:
                raise ValueError("artifact contains an invalid spec_id")
            identifiers.add(spec_id)
        for child in value.values():
            identifiers.update(_json_spec_ids(child))
    elif isinstance(value, list):
        for child in value:
            identifiers.update(_json_spec_ids(child))
    return identifiers


def artifact_fitted_spec_ids(path: Path) -> set[str]:
    """Read fitted specification identities from a structured result artifact."""
    suffixes = path.suffixes
    if path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        if "spec_id" not in parquet.schema_arrow.names:
            return set()
        identifiers = set()
        for value in parquet.read(columns=["spec_id"]).column("spec_id").to_pylist():
            if not isinstance(value, str) or not value:
                raise ValueError(f"artifact contains an invalid spec_id: {path}")
            identifiers.add(value)
        return identifiers
    if path.suffix == ".json" or suffixes[-2:] == [".json", ".gz"]:
        opener = gzip.open if path.suffix == ".gz" else Path.open
        with opener(path, "rt", encoding="utf-8") as handle:
            return _json_spec_ids(json.load(handle))
    if path.suffix == ".jsonl" or suffixes[-2:] == [".jsonl", ".gz"]:
        opener = gzip.open if path.suffix == ".gz" else Path.open
        identifiers: set[str] = set()
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    identifiers.update(_json_spec_ids(json.loads(line)))
        return identifiers
    raise ValueError(f"fitted artifact format does not expose spec_ids: {path}")


def validate_artifact_spec_ids(path: Path, *, role: str, declared: object) -> set[str]:
    """Require declared fitted coverage to equal structured artifact contents."""
    if not isinstance(declared, list) or any(not isinstance(value, str) or not value for value in declared):
        raise ValueError(f"artifact has invalid declared spec_ids: {path}")
    if len(declared) != len(set(declared)):
        raise ValueError(f"artifact repeats a declared spec_id: {path}")
    if role == "support":
        if declared:
            raise ValueError(f"support artifact cannot claim fitted spec_ids: {path}")
        try:
            actual = artifact_fitted_spec_ids(path)
        except ValueError as error:
            if "format does not expose" in str(error):
                return set()
            raise
        if actual:
            raise ValueError(f"support artifact contains fitted spec_ids: {path}")
        return set()
    if role not in FITTED_MODEL_ARTIFACT_ROLES:
        raise ValueError(f"artifact role is invalid: {role}")
    actual = artifact_fitted_spec_ids(path)
    if not actual or actual != set(declared):
        raise ValueError(f"declared spec_ids do not match fitted artifact contents: {path}")
    return actual


def model_run_id(run: Mapping[str, Any]) -> str:
    """Bind a run to its lane, data, exploration, lock, plan, and engine."""
    return canonical_hash({key: run.get(key) for key in MODEL_RUN_ID_FIELDS})


def exploratory_plan_identity(run: Mapping[str, Any]) -> dict[str, Any]:
    """Return every immutable field bound by an exploratory family plan hash."""
    return {field: run.get(field) for field in EXPLORATORY_PLAN_IDENTITY_FIELDS}


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
