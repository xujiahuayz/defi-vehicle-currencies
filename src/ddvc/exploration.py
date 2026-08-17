"""Executable E0 exploration with complete run logging and exact triage closure."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ddvc.analysis_release import AnalysisRelease, resolve_analysis_release, resolve_repo_path
from ddvc.artifact_release import file_sha256, publish_artifact_release, resolve_artifact_release
from ddvc.fetch.raw import write_json
from ddvc.model_registry import (
    FITTED_MODEL_ARTIFACT_ROLES,
    MODEL_RUN_ARTIFACT_ROLES,
    canonical_hash,
    claim_execution_perimeter,
    exploratory_plan_identity,
    generation_id,
    model_run_id,
    validate_artifact_spec_ids,
)
from ddvc.paths import REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.provenance import (
    describe_input,
    portable_content_sha256,
    sidecar_path,
    verify,
)
from ddvc.runtime import atomic_output, exclusive_job


EXPLORATION_PLAN_SCHEMA_VERSION = 4
EXPLORATION_TRIAGE_SCHEMA_VERSION = 1
EXPLORATION_CERTIFICATE_SCHEMA_VERSION = 1
EXPLORATION_CERTIFICATE_KIND = "e0_exploration"
EXPLORATION_POINTER_SCHEMA_VERSION = 1
EXPLORATION_POINTER_KIND = "e0_exploration_bundle"
EXPLORATION_FILENAMES = {"certificate": "certificate.json"}
EXPLORATION_LEDGER = REPO_ROOT / "docs" / "model-ledger.json"
EXPLORATION_CURRENT = REPO_ROOT / "data" / "processed" / "e0_exploration_release" / "current.json"
EXPLORATION_PLAN_TEMPLATE = REPO_ROOT / "docs" / "e0-exploration-plan.template.json"
EXPLORATION_SPECIFICATION_LOCK = REPO_ROOT / "docs" / "specification-lock.json"
EXPLORATION_CLAIM_BINDINGS = {"specification_claim", "open_discovery"}
EXPLORATION_EXECUTION_STATUSES = {"executable", "deferred"}
OPEN_DISCOVERY_DIMENSIONS = {"anomaly", "open_question"}
EXPLORATION_LOCK = SHARED_RUNTIME_DIR / "e0-exploration.lock"
EXPLORATION_CODE_SOURCES = (
    "src/ddvc/artifact_release.py",
    "src/ddvc/analysis_release.py",
    "src/ddvc/exploration.py",
    "src/ddvc/model_registry.py",
    "src/ddvc/provenance.py",
    "scripts/run_exploration.py",
)
EXPLORATION_DIMENSIONS = {
    "distribution",
    "anomaly",
    "support",
    "functional_form",
    "heterogeneity",
    "mechanism",
    "rival_explanation",
    "open_question",
}
TRIAGE_OUTCOMES = {
    "promote",
    "retain_auxiliary",
    "park_next_paper",
    "reject",
}
TRIAGE_ASSESSMENT_FIELDS = {
    "novelty",
    "economic_magnitude",
    "robustness",
    "identification_credibility",
    "centrality_to_vehicle_dominance",
    "jfe_fit",
}


@dataclass(frozen=True)
class ExplorationRelease:
    """One E0 certificate that closes exactly one D3-bound run perimeter."""

    generation: str
    certificate_path: Path
    certificate: dict[str, Any]
    root: Path


@dataclass(frozen=True)
class ExplorationPlan:
    """One executable plan bound to the canonical family perimeter and D3."""

    contracts: tuple[dict[str, Any], ...]
    plan_relative: str
    plan_sha256: str
    template_relative: str
    template_sha256: str
    specification_relative: str
    specification_sha256: str
    expected_family_ids: tuple[str, ...]
    family_perimeter_sha256: str


CommandRunner = Callable[[list[str], Path, dict[str, str]], int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_ledger(path: Path) -> dict[str, Any]:
    ledger = _read_json_object(path, label="model ledger")
    if ledger.get("schema_version") != 2:
        raise ValueError("model ledger schema is not current")
    if not isinstance(ledger.get("legacy_families"), list) or not ledger["legacy_families"]:
        raise ValueError("model ledger has no preserved legacy-family perimeter")
    if not isinstance(ledger.get("runs"), list):
        raise ValueError("model ledger run inventory is not a list")
    if not isinstance(ledger.get("exploration"), dict):
        raise ValueError("model ledger exploration state is not an object")
    return ledger


def _relative_artifact_identity(path: Path) -> dict[str, Any]:
    provenance_path = sidecar_path(path)
    return {
        "exists": path.is_file(),
        "content_sha256": portable_content_sha256(path) if path.is_file() else None,
        "provenance_sha256": file_sha256(provenance_path) if provenance_path.is_file() else None,
    }


def _engine_hash(root: Path, sources: list[str]) -> str:
    records: list[dict[str, str]] = []
    for source in sorted(set(sources)):
        normalized, path = resolve_repo_path(source, root=root, label="exploration engine source")
        if not path.is_file():
            raise FileNotFoundError(f"exploration engine source is absent: {normalized}")
        records.append({"path": normalized, "sha256": file_sha256(path)})
    if not records:
        raise ValueError("exploration family has no engine sources")
    return canonical_hash(records)


def _normalize_attack_ids(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} has no required attack ids")
    if any(
        not isinstance(attack_id, str)
        or not attack_id
        or attack_id != attack_id.strip()
        or attack_id != attack_id.lower()
        or not attack_id[0].isalpha()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in attack_id)
        for attack_id in value
    ):
        raise ValueError(f"{label} has invalid required attack ids")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} repeats a required attack id")
    return list(value)


def _normalize_attack_evidence(
    value: object,
    *,
    family_id: str,
    required_attack_ids: list[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != set(required_attack_ids):
        missing = sorted(set(required_attack_ids) - set(value or {})) if isinstance(value, dict) else sorted(required_attack_ids)
        unexpected = sorted(set(value or {}) - set(required_attack_ids)) if isinstance(value, dict) else []
        raise ValueError(
            f"exploration family attack evidence is not exact: {family_id}: "
            f"missing={missing or 'none'}; unexpected={unexpected or 'none'}"
        )
    artifacts_by_path = {artifact["path"]: artifact for artifact in artifacts}
    normalized: dict[str, dict[str, Any]] = {}
    for attack_id in required_attack_ids:
        evidence = value[attack_id]
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"exploration attack evidence is empty: {family_id}/{attack_id}")
        if not set(evidence).issubset({"artifact_path", "spec_ids"}):
            raise ValueError(f"exploration attack evidence has unknown fields: {family_id}/{attack_id}")
        artifact_path = str(evidence.get("artifact_path") or "")
        artifact = artifacts_by_path.get(artifact_path)
        if artifact is None:
            raise ValueError(
                f"exploration attack evidence cites an unknown artifact: {family_id}/{attack_id}/{artifact_path or 'missing'}"
            )
        if artifact["role"] == "support":
            if set(evidence) != {"artifact_path"}:
                raise ValueError(f"exploration support attack evidence cannot cite fitted spec ids: {family_id}/{attack_id}")
            normalized[attack_id] = {"artifact_path": artifact_path}
            continue
        spec_ids = evidence.get("spec_ids")
        if (
            not isinstance(spec_ids, list)
            or not spec_ids
            or any(not isinstance(spec_id, str) or not spec_id for spec_id in spec_ids)
            or len(spec_ids) != len(set(spec_ids))
        ):
            raise ValueError(f"exploration fitted attack evidence lacks exact spec ids: {family_id}/{attack_id}")
        unknown = sorted(set(spec_ids) - set(artifact["spec_ids"]))
        if unknown:
            raise ValueError(
                f"exploration attack evidence cites unknown fitted spec ids: {family_id}/{attack_id}: {unknown}"
            )
        normalized[attack_id] = {"artifact_path": artifact_path, "spec_ids": list(spec_ids)}
    return normalized


def _plan_family_contract(family: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    required_text = (
        "family_id",
        "claim_id",
        "question",
        "runner",
        "estimator",
        "fixed_effects",
        "inference",
        "note",
    )
    missing = [field for field in required_text if not str(family.get(field) or "").strip()]
    if missing:
        raise ValueError(f"exploration family lacks required fields: {missing}")
    runner_relative, runner_path = resolve_repo_path(str(family["runner"]), root=root, label="exploration runner")
    if runner_path.suffix != ".py" or not runner_relative.startswith("scripts/") or not runner_path.is_file():
        raise ValueError(f"exploration runner must be an existing repository script: {runner_relative}")
    arguments = family.get("arguments")
    if not isinstance(arguments, list) or any(not isinstance(value, str) for value in arguments):
        raise ValueError(f"exploration arguments must be a string list: {family['family_id']}")
    dimensions = family.get("search_dimensions")
    if (
        not isinstance(dimensions, list)
        or not dimensions
        or any(value not in EXPLORATION_DIMENSIONS for value in dimensions)
    ):
        raise ValueError(f"exploration family has invalid search dimensions: {family['family_id']}")
    if len(dimensions) != len(set(dimensions)):
        raise ValueError(f"exploration family repeats a search dimension: {family['family_id']}")
    artifacts = family.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError(f"exploration family has no declared artifacts: {family['family_id']}")
    normalized_artifacts: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError(f"exploration artifact is not an object: {family['family_id']}")
        relative, _path = resolve_repo_path(str(artifact.get("path") or ""), root=root, label="exploration artifact")
        role = str(artifact.get("role") or "")
        spec_ids = artifact.get("spec_ids")
        if role not in MODEL_RUN_ARTIFACT_ROLES:
            raise ValueError(f"exploration artifact has an invalid role: {family['family_id']}/{relative}")
        if not isinstance(spec_ids, list) or any(not isinstance(value, str) or not value for value in spec_ids):
            raise ValueError(f"exploration artifact has invalid specification ids: {family['family_id']}/{relative}")
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError(f"exploration artifact repeats a specification id: {family['family_id']}/{relative}")
        if role == "support" and spec_ids:
            raise ValueError(f"exploration support artifact claims fitted coverage: {family['family_id']}/{relative}")
        if role != "support" and not spec_ids:
            raise ValueError(f"exploration fitted artifact lacks specification ids: {family['family_id']}/{relative}")
        normalized_artifacts.append({"path": relative, "role": role, "spec_ids": list(spec_ids)})
    paths = [record["path"] for record in normalized_artifacts]
    if len(paths) != len(set(paths)):
        raise ValueError(f"exploration family reuses one artifact path: {family['family_id']}")
    required_attack_ids = _normalize_attack_ids(
        family.get("required_attack_ids"),
        label=f"exploration family {family['family_id']}",
    )
    attack_evidence = _normalize_attack_evidence(
        family.get("attack_evidence"),
        family_id=str(family["family_id"]),
        required_attack_ids=required_attack_ids,
        artifacts=normalized_artifacts,
    )
    fitted_spec_ids = {
        spec_id
        for artifact in normalized_artifacts
        if artifact["role"] in FITTED_MODEL_ARTIFACT_ROLES
        for spec_id in artifact["spec_ids"]
    }
    coverage = family.get("search_dimension_spec_ids")
    if not isinstance(coverage, dict) or set(coverage) != set(dimensions):
        missing_dimensions = sorted(set(dimensions) - set(coverage or {})) if isinstance(coverage, dict) else sorted(dimensions)
        unexpected_dimensions = sorted(set(coverage or {}) - set(dimensions)) if isinstance(coverage, dict) else []
        raise ValueError(
            f"exploration family search-dimension coverage is not exact: {family['family_id']}: "
            f"missing={missing_dimensions or 'none'}; unexpected={unexpected_dimensions or 'none'}"
        )
    normalized_coverage: dict[str, list[str]] = {}
    for dimension in dimensions:
        spec_ids = coverage[dimension]
        if (
            not isinstance(spec_ids, list)
            or not spec_ids
            or any(not isinstance(value, str) or not value for value in spec_ids)
            or len(spec_ids) != len(set(spec_ids))
        ):
            raise ValueError(
                f"exploration search dimension lacks exact fitted coverage: {family['family_id']}/{dimension}"
            )
        unknown = sorted(set(spec_ids) - fitted_spec_ids)
        if unknown:
            raise ValueError(
                f"exploration search dimension cites non-fitted specification ids: "
                f"{family['family_id']}/{dimension}: {unknown}"
            )
        normalized_coverage[dimension] = list(spec_ids)
    engine_sources = family.get("engine_sources")
    if not isinstance(engine_sources, list) or any(not isinstance(value, str) for value in engine_sources):
        raise ValueError(f"exploration engine_sources must be a string list: {family['family_id']}")
    sources = [runner_relative, *engine_sources]
    if len(sources) != len(set(sources)):
        raise ValueError(f"exploration family repeats an engine source: {family['family_id']}")
    contract = {
        "family_id": str(family["family_id"]),
        "claim_id": str(family["claim_id"]),
        "question": str(family["question"]),
        "search_dimensions": list(dimensions),
        "search_dimension_spec_ids": normalized_coverage,
        "required_attack_ids": required_attack_ids,
        "attack_evidence": attack_evidence,
        "runner": runner_relative,
        "arguments": list(arguments),
        "engine_sources": sources,
        "estimator": str(family["estimator"]),
        "fixed_effects": str(family["fixed_effects"]),
        "inference": str(family["inference"]),
        "artifacts": normalized_artifacts,
        "note": str(family["note"]),
    }
    return contract


def _load_plan_template(
    path: Path,
    *,
    template_relative: str,
    specification_path: Path = EXPLORATION_SPECIFICATION_LOCK,
) -> list[dict[str, Any]]:
    """Return the executable family perimeter after reconciling it with the claim lock.

    The template declares every designed family, including the ones whose claim
    is execution-blocked, so that a blocker is recorded rather than silently
    deleted. Only the executable families gate an exploration run.
    """
    template = _read_json_object(path, label="E0 exploration plan template")
    if (
        template.get("schema_version") != EXPLORATION_PLAN_SCHEMA_VERSION
        or template.get("kind") != "e0_exploration_plan_template"
    ):
        raise ValueError("E0 exploration plan template schema is not current")
    families = template.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("E0 exploration plan template has no family perimeter")
    specification = _read_json_object(specification_path, label="specification lock")
    perimeter = claim_execution_perimeter(specification)
    lock_gates = {
        str(claim.get("id") or ""): claim.get("execution_gate")
        for claim in specification.get("claims") or []
        if isinstance(claim, dict)
    }
    executable_claim_ids = {str(claim["id"]) for claim in perimeter.executable_claims}
    declared: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    covered_claim_ids: set[str] = set()
    for family in families:
        if not isinstance(family, dict):
            raise ValueError("E0 exploration plan template contains a non-object family")
        family_id = str(family.get("family_id") or "").strip()
        claim_id = str(family.get("claim_id") or "").strip()
        question = str(family.get("question") or "").strip()
        binding = str(family.get("claim_binding") or "").strip()
        execution_status = str(family.get("execution_status") or "").strip()
        adjudication = str(family.get("perimeter_adjudication") or "").strip()
        execution_gate = family.get("execution_gate")
        dimensions = family.get("search_dimensions")
        required_attack_ids = _normalize_attack_ids(
            family.get("required_attack_ids"),
            label=f"E0 exploration plan template family {family_id or 'missing'}",
        )
        if not family_id or not claim_id or not question or not adjudication:
            raise ValueError("E0 exploration plan template has an incomplete family identity")
        if binding not in EXPLORATION_CLAIM_BINDINGS:
            raise ValueError(f"E0 exploration plan template has an invalid claim binding: {family_id}")
        if execution_status not in EXPLORATION_EXECUTION_STATUSES:
            raise ValueError(f"E0 exploration plan template has an invalid execution status: {family_id}")
        if (
            not isinstance(dimensions, list)
            or not dimensions
            or any(value not in EXPLORATION_DIMENSIONS for value in dimensions)
            or len(dimensions) != len(set(dimensions))
        ):
            raise ValueError(f"E0 exploration plan template has invalid dimensions: {family_id}")
        if binding == "specification_claim":
            if claim_id not in lock_gates:
                raise ValueError(
                    f"E0 exploration plan template names a claim absent from the lock: {family_id}/{claim_id}"
                )
            if execution_gate != lock_gates[claim_id]:
                raise ValueError(
                    "E0 exploration plan template contradicts the claim execution gate: "
                    f"{family_id}/{claim_id}"
                )
            expected_status = "executable" if claim_id in executable_claim_ids else "deferred"
            if execution_status != expected_status:
                raise ValueError(
                    "E0 exploration plan template misstates the claim execution status: "
                    f"{family_id}/{claim_id} declares {execution_status}, lock requires {expected_status}"
                )
            if execution_status == "executable":
                covered_claim_ids.add(claim_id)
        else:
            if claim_id in lock_gates:
                raise ValueError(
                    f"E0 open-discovery family must not name a locked claim: {family_id}/{claim_id}"
                )
            if execution_gate is not None or execution_status != "executable":
                raise ValueError(f"E0 open-discovery family has an invalid execution state: {family_id}")
            if not OPEN_DISCOVERY_DIMENSIONS.issubset(set(dimensions)):
                raise ValueError(f"E0 open-discovery family does not search for anomalies: {family_id}")
        identity = {
            "family_id": family_id,
            "claim_id": claim_id,
            "question": question,
            "search_dimensions": list(dimensions),
            "required_attack_ids": required_attack_ids,
        }
        declared.append(identity)
        if execution_status == "executable":
            normalized.append(identity)
    family_ids = [family["family_id"] for family in declared]
    if len(family_ids) != len(set(family_ids)):
        raise ValueError("E0 exploration plan template contains duplicate family ids")
    claim_ids = [family["claim_id"] for family in declared]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("E0 exploration plan template repeats a claim-family identity")
    uncovered = sorted(executable_claim_ids - covered_claim_ids)
    if uncovered:
        raise ValueError(
            f"E0 exploration plan template leaves an executable claim unexplored: {uncovered}"
        )
    if not normalized:
        raise ValueError("E0 exploration plan template has no executable family perimeter")
    if not template_relative:
        raise ValueError("E0 exploration plan template path is empty")
    return normalized


def _load_plan(
    path: Path,
    *,
    plan_relative: str,
    template_path: Path,
    template_relative: str,
    root: Path,
    d3_generation: str,
    specification_path: Path = EXPLORATION_SPECIFICATION_LOCK,
    specification_relative: str = "docs/specification-lock.json",
    bound_template_families: list[dict[str, Any]] | None = None,
    bound_specification_sha256: str | None = None,
) -> ExplorationPlan:
    plan = _read_json_object(path, label="E0 exploration plan")
    if plan.get("schema_version") != EXPLORATION_PLAN_SCHEMA_VERSION:
        raise ValueError("E0 exploration plan schema is not current")
    if plan.get("d3_generation") != d3_generation:
        raise ValueError("E0 exploration plan targets a different D3 generation")
    families = plan.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("E0 exploration plan has no fitted families")
    contracts = [_plan_family_contract(family, root=root) for family in families if isinstance(family, dict)]
    if len(contracts) != len(families):
        raise ValueError("E0 exploration plan contains a non-object family")
    family_ids = [contract["family_id"] for contract in contracts]
    if len(family_ids) != len(set(family_ids)):
        raise ValueError("E0 exploration plan contains duplicate family ids")
    artifact_paths = [artifact["path"] for contract in contracts for artifact in contract["artifacts"]]
    if len(artifact_paths) != len(set(artifact_paths)):
        raise ValueError("E0 exploration plan assigns one artifact path to multiple runs")
    for contract in contracts:
        contract["d3_generation"] = d3_generation
        contract["plan_path"] = plan_relative
    template_families = bound_template_families
    if template_families is None:
        template_families = _load_plan_template(
            template_path,
            template_relative=template_relative,
            specification_path=specification_path,
        )
    expected = {family["family_id"]: family for family in template_families}
    actual = {
        contract["family_id"]: {
            key: contract[key]
            for key in ("family_id", "claim_id", "question", "search_dimensions", "required_attack_ids")
        }
        for contract in contracts
    }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        changed = sorted(
            family_id
            for family_id in set(actual) & set(expected)
            if actual[family_id] != expected[family_id]
        )
        raise ValueError(
            "E0 exploration plan does not match the canonical family perimeter: "
            f"missing={missing or 'none'}; unexpected={unexpected or 'none'}; "
            f"changed={changed or 'none'}"
        )
    expected_family_ids = tuple(sorted(expected))
    return ExplorationPlan(
        contracts=tuple(contracts),
        plan_relative=plan_relative,
        plan_sha256=file_sha256(path),
        template_relative=template_relative,
        template_sha256=file_sha256(template_path),
        specification_relative=specification_relative,
        specification_sha256=(
            bound_specification_sha256
            if bound_specification_sha256 is not None
            else file_sha256(specification_path)
        ),
        expected_family_ids=expected_family_ids,
        family_perimeter_sha256=canonical_hash(template_families),
    )


def _default_command_runner(command: list[str], cwd: Path, env: dict[str, str]) -> int:
    process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        return process.wait()
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise


def _planned_identity(run: Mapping[str, Any]) -> dict[str, Any]:
    return exploratory_plan_identity(run)


def _planned_run(
    contract: Mapping[str, Any],
    *,
    d3_generation: str,
    root: Path,
    attempt: int = 1,
    retry_of_run_id: str | None = None,
) -> dict[str, Any]:
    if attempt < 1 or (attempt == 1) != (retry_of_run_id is None):
        raise ValueError("E0 execution attempt identity is inconsistent")
    run: dict[str, Any] = {
        "family_id": contract["family_id"],
        "run_id": "pending",
        "claim_id": contract["claim_id"],
        "lane": "exploratory",
        "lifecycle": "planned",
        "disposition": "not_assessed",
        "selection_origin": None,
        "promoted_from_run_id": None,
        "decision_id": None,
        "d3_generation": d3_generation,
        "exploration_generation": None,
        "lock_hash": None,
        "plan_hash": "pending",
        "engine_hash": _engine_hash(root, list(contract["engine_sources"])),
        "engine_sources": list(contract["engine_sources"]),
        "plan_path": contract["plan_path"],
        "runner": contract["runner"],
        "arguments": list(contract["arguments"]),
        "estimator": contract["estimator"],
        "fixed_effects": contract["fixed_effects"],
        "inference": contract["inference"],
        "artifacts": [],
        "declared_artifacts": [dict(artifact) for artifact in contract["artifacts"]],
        "note": contract["note"],
        "question": contract["question"],
        "search_dimensions": contract["search_dimensions"],
        "search_dimension_spec_ids": contract["search_dimension_spec_ids"],
        "required_attack_ids": contract["required_attack_ids"],
        "attack_evidence": contract["attack_evidence"],
        "attempt": attempt,
        "retry_of_run_id": retry_of_run_id,
    }
    run["plan_hash"] = canonical_hash(_planned_identity(run))
    run["run_id"] = model_run_id(run)
    return run


def _contract_identity(run: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable family contract without its execution-attempt identity."""

    identity = _planned_identity(run)
    identity.pop("attempt", None)
    identity.pop("retry_of_run_id", None)
    return identity


def _artifact_records(
    contract: Mapping[str, Any],
    *,
    d3: AnalysisRelease,
    root: Path,
    before: Mapping[str, Mapping[str, Any]],
    verifier: Callable[[str | Path], dict[str, object]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for declared in contract["artifacts"]:
        relative, path = resolve_repo_path(declared["path"], root=root, label="exploration artifact")
        if not path.is_file():
            raise FileNotFoundError(f"exploration run did not produce its declared artifact: {relative}")
        provenance_path = sidecar_path(path)
        if not provenance_path.is_file():
            raise FileNotFoundError(f"exploration artifact lacks provenance: {relative}")
        current_identity = _relative_artifact_identity(path)
        if before.get(relative) == current_identity:
            raise RuntimeError(f"exploration run reused an unchanged artifact: {relative}")
        verdict = verifier(path)
        if verdict.get("status") != "ok":
            raise RuntimeError(f"exploration artifact is not current: {relative}: {verdict.get('status')}")
        provenance = _read_json_object(provenance_path, label="exploration artifact provenance")
        if provenance.get("artefact") != describe_input(path).get("path"):
            raise ValueError(f"exploration provenance identifies a different artifact: {relative}")
        provenance_sources = provenance.get("code_sources")
        if not isinstance(provenance_sources, list) or not set(contract["engine_sources"]).issubset(provenance_sources):
            raise ValueError(f"exploration provenance omits a declared engine source: {relative}")
        d3_input_identity = describe_input(d3.certificate_path).get("path")
        provenance_inputs = provenance.get("inputs")
        if not isinstance(provenance_inputs, list) or d3_input_identity not in {
            record.get("path") for record in provenance_inputs if isinstance(record, dict)
        }:
            raise ValueError(f"exploration provenance is not bound to the D3 certificate: {relative}")
        validate_artifact_spec_ids(path, role=str(declared["role"]), declared=declared["spec_ids"])
        records.append(
            {
                "path": relative,
                "role": declared["role"],
                "sha256": portable_content_sha256(path),
                "provenance_path": provenance_path.relative_to(root).as_posix(),
                "spec_ids": declared["spec_ids"],
            }
        )
    return records


def _replace_run(ledger: dict[str, Any], run: Mapping[str, Any]) -> None:
    run_id = str(run["run_id"])
    indexes = [index for index, value in enumerate(ledger["runs"]) if isinstance(value, dict) and value.get("run_id") == run_id]
    if len(indexes) != 1:
        raise RuntimeError(f"model ledger lost the unique planned run record: {run_id}")
    ledger["runs"][indexes[0]] = dict(run)


def _start_ledger_exploration(
    ledger: dict[str, Any],
    *,
    d3: AnalysisRelease,
    d3_certificate_relative: str,
    plan: ExplorationPlan,
) -> None:
    exploration = ledger["exploration"]
    status = str(exploration.get("status") or "")
    if status == "not_started":
        if ledger.get("current_analysis_generation") or ledger["runs"]:
            raise RuntimeError("not-started E0 ledger contains current-generation state")
        ledger["current_analysis_generation"] = d3.generation
        ledger["exploration"] = {
            "status": "in_progress",
            "d3_generation": d3.generation,
            "d3_certificate": d3_certificate_relative,
            "plan_path": plan.plan_relative,
            "plan_sha256": plan.plan_sha256,
            "template_path": plan.template_relative,
            "template_sha256": plan.template_sha256,
            "specification_path": plan.specification_relative,
            "specification_sha256": plan.specification_sha256,
            "expected_family_ids": list(plan.expected_family_ids),
            "family_perimeter_sha256": plan.family_perimeter_sha256,
            "generation": None,
            "certificate": None,
            "started_at": _utc_now(),
            "completed_at": None,
        }
        return
    if status != "in_progress":
        raise RuntimeError(f"E0 cannot execute from ledger state: {status or 'missing'}")
    if (
        ledger.get("current_analysis_generation") != d3.generation
        or exploration.get("d3_generation") != d3.generation
        or exploration.get("d3_certificate") != d3_certificate_relative
        or exploration.get("plan_path") != plan.plan_relative
        or exploration.get("plan_sha256") != plan.plan_sha256
        or exploration.get("template_path") != plan.template_relative
        or exploration.get("template_sha256") != plan.template_sha256
        or exploration.get("specification_path") != plan.specification_relative
        or exploration.get("specification_sha256") != plan.specification_sha256
        or exploration.get("expected_family_ids") != list(plan.expected_family_ids)
        or exploration.get("family_perimeter_sha256") != plan.family_perimeter_sha256
        or exploration.get("generation") is not None
        or exploration.get("certificate") is not None
    ):
        raise RuntimeError("in-progress E0 ledger is bound to a different D3 release")


def execute_exploration_plan(
    plan_path: str | Path,
    *,
    d3_certificate_path: str | Path,
    root: Path = REPO_ROOT,
    ledger_path: str | Path = "docs/model-ledger.json",
    template_path: str | Path = "docs/e0-exploration-plan.template.json",
    specification_path: str | Path = "docs/specification-lock.json",
    lock_path: Path = EXPLORATION_LOCK,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    command_runner: CommandRunner = _default_command_runner,
) -> list[str]:
    """Execute each E0 family under one D3 generation and log it before and after fitting."""

    plan_relative, resolved_plan = resolve_repo_path(plan_path, root=root, label="E0 exploration plan")
    if not resolved_plan.is_file():
        raise FileNotFoundError(f"E0 exploration plan is absent: {plan_relative}")
    ledger_relative, resolved_ledger = resolve_repo_path(ledger_path, root=root, label="model ledger")
    d3_relative, _resolved_d3 = resolve_repo_path(d3_certificate_path, root=root, label="D3 certificate")
    d3 = resolve_analysis_release(certificate_path=d3_relative, root=root, verifier=verifier)
    template_relative, resolved_template = resolve_repo_path(
        template_path,
        root=root,
        label="E0 exploration plan template",
    )
    if not resolved_template.is_file():
        raise FileNotFoundError(f"E0 exploration plan template is absent: {template_relative}")
    specification_relative, resolved_specification = resolve_repo_path(
        specification_path,
        root=root,
        label="specification lock",
    )
    if not resolved_specification.is_file():
        raise FileNotFoundError(f"specification lock is absent: {specification_relative}")
    plan = _load_plan(
        resolved_plan,
        plan_relative=plan_relative,
        template_path=resolved_template,
        template_relative=template_relative,
        root=root,
        d3_generation=d3.generation,
        specification_path=resolved_specification,
        specification_relative=specification_relative,
    )
    completed: list[str] = []
    with exclusive_job(lock_path, job="E0 exploration"):
        ledger = _load_ledger(resolved_ledger)
        _start_ledger_exploration(
            ledger,
            d3=d3,
            d3_certificate_relative=d3_relative,
            plan=plan,
        )
        _write_json_atomic(resolved_ledger, ledger)
        artifact_owners: dict[str, list[dict[str, Any]]] = {}
        for run in ledger["runs"]:
            if not isinstance(run, dict):
                continue
            paths = {
                str(value.get("path") or "")
                for field in ("artifacts", "declared_artifacts")
                for value in run.get(field, [])
                if isinstance(value, dict) and value.get("path")
            }
            for path in paths:
                artifact_owners.setdefault(path, []).append(run)
        for contract in plan.contracts:
            family_runs = [
                run
                for run in ledger["runs"]
                if isinstance(run, dict) and run.get("family_id") == contract["family_id"]
            ]
            executed_family_runs = [run for run in family_runs if run.get("lifecycle") == "executed"]
            if len(executed_family_runs) > 1:
                raise RuntimeError(f"E0 family has multiple executed attempts: {contract['family_id']}")
            planned_family_runs = [run for run in family_runs if run.get("lifecycle") == "planned"]
            if len(planned_family_runs) > 1:
                raise RuntimeError(f"E0 family has multiple open attempts: {contract['family_id']}")
            retired_family_runs = [run for run in family_runs if run.get("lifecycle") == "retired"]
            if any(run.get("lifecycle") not in {"planned", "executed", "retired"} for run in family_runs):
                raise RuntimeError(f"E0 family has an invalid execution lifecycle: {contract['family_id']}")
            if planned_family_runs:
                current = planned_family_runs[0]
                planned = _planned_run(
                    contract,
                    d3_generation=d3.generation,
                    root=root,
                    attempt=int(current.get("attempt") or 0),
                    retry_of_run_id=current.get("retry_of_run_id"),
                )
            elif executed_family_runs:
                current = executed_family_runs[0]
                planned = _planned_run(
                    contract,
                    d3_generation=d3.generation,
                    root=root,
                    attempt=int(current.get("attempt") or 0),
                    retry_of_run_id=current.get("retry_of_run_id"),
                )
            else:
                attempts = [int(run.get("attempt") or 0) for run in retired_family_runs]
                if any(attempt < 1 for attempt in attempts) or len(attempts) != len(set(attempts)):
                    raise RuntimeError(f"E0 family has invalid retired attempt identities: {contract['family_id']}")
                prior = max(retired_family_runs, key=lambda run: int(run["attempt"])) if retired_family_runs else None
                planned = _planned_run(
                    contract,
                    d3_generation=d3.generation,
                    root=root,
                    attempt=(max(attempts) + 1) if attempts else 1,
                    retry_of_run_id=str(prior["run_id"]) if prior is not None else None,
                )
            if any(_contract_identity(run) != _contract_identity(planned) for run in family_runs):
                raise RuntimeError(f"E0 family execution reuses a different complete plan: {contract['family_id']}")
            matching = [run for run in family_runs if run.get("run_id") == planned["run_id"]]
            if matching:
                existing = matching[0]
                if (
                    _planned_identity(existing) != _planned_identity(planned)
                    or existing.get("plan_hash") != planned["plan_hash"]
                ):
                    raise RuntimeError(f"E0 run identity reuses a different complete plan: {planned['run_id']}")
                if existing.get("lifecycle") == "executed":
                    for artifact in existing.get("artifacts", []):
                        if not isinstance(artifact, dict):
                            raise ValueError(f"E0 executed run has a malformed artifact: {existing['run_id']}")
                        _validate_artifact_record(
                            artifact,
                            root=root,
                            verifier=verifier,
                            required_sources=list(existing.get("engine_sources") or []),
                            d3_certificate_path=d3.certificate_path,
                        )
                    completed.append(str(existing["run_id"]))
                    continue
                if existing.get("lifecycle") != "planned":
                    raise RuntimeError(f"E0 plan previously terminated; change its explicit plan before retry: {planned['run_id']}")
                _replace_run(ledger, planned)
            else:
                conflicts = sorted(
                    artifact["path"]
                    for artifact in contract["artifacts"]
                    if any(
                        owner.get("lifecycle") != "retired"
                        or owner.get("family_id") != contract["family_id"]
                        for owner in artifact_owners.get(artifact["path"], [])
                    )
                )
                if conflicts:
                    raise RuntimeError(f"E0 plan reuses artifacts owned by another run: {conflicts}")
                ledger["runs"].append(planned)
                for artifact in contract["artifacts"]:
                    artifact_owners.setdefault(artifact["path"], []).append(planned)
            _write_json_atomic(resolved_ledger, ledger)
            before = {
                artifact["path"]: _relative_artifact_identity(root / artifact["path"])
                for artifact in contract["artifacts"]
            }
            environment = dict(os.environ)
            python_path = os.pathsep.join(
                [
                    str(root / "src"),
                    str(root),
                    str(root / "scripts"),
                    environment.get("PYTHONPATH", ""),
                ]
            ).rstrip(os.pathsep)
            environment["PYTHONPATH"] = python_path
            environment["PYTHONSAFEPATH"] = "1"
            environment["DDVC_D3_CERTIFICATE"] = d3_relative
            environment["DDVC_D3_GENERATION"] = d3.generation
            command = [sys.executable, "-P", str(root / contract["runner"]), *contract["arguments"]]
            try:
                return_code = command_runner(command, root, environment)
            except BaseException:
                interrupted = dict(planned)
                interrupted["execution_note"] = "Execution interrupted before a terminal fit record."
                _replace_run(ledger, interrupted)
                _write_json_atomic(resolved_ledger, ledger)
                raise
            if return_code != 0:
                failed = dict(planned)
                failed["lifecycle"] = "retired"
                failed["disposition"] = "rejected"
                failed["execution_note"] = f"Runner exited with status {return_code}; no fitted artifact is admitted."
                _replace_run(ledger, failed)
                _write_json_atomic(resolved_ledger, ledger)
                raise RuntimeError(f"E0 exploration runner failed: {contract['family_id']}: exit={return_code}")
            try:
                artifacts = _artifact_records(contract, d3=d3, root=root, before=before, verifier=verifier)
            except BaseException as error:
                failed = dict(planned)
                failed["lifecycle"] = "retired"
                failed["disposition"] = "rejected"
                failed["execution_note"] = f"Artifact release failed closed: {type(error).__name__}: {error}"
                _replace_run(ledger, failed)
                _write_json_atomic(resolved_ledger, ledger)
                raise
            executed = dict(planned)
            executed["lifecycle"] = "executed"
            executed["artifacts"] = artifacts
            _replace_run(ledger, executed)
            _write_json_atomic(resolved_ledger, ledger)
            completed.append(str(executed["run_id"]))
    return completed


def _validate_artifact_record(
    artifact: Mapping[str, Any],
    *,
    root: Path,
    verifier: Callable[[str | Path], dict[str, object]],
    required_sources: list[str] | None = None,
    d3_certificate_path: Path | None = None,
) -> None:
    relative, path = resolve_repo_path(str(artifact.get("path") or ""), root=root, label="logged exploration artifact")
    provenance_relative, provenance_path = resolve_repo_path(
        str(artifact.get("provenance_path") or ""),
        root=root,
        label="logged exploration provenance",
    )
    if provenance_path != sidecar_path(path):
        raise ValueError(f"logged exploration provenance path is not canonical: {relative}/{provenance_relative}")
    if not path.is_file() or not provenance_path.is_file():
        raise FileNotFoundError(f"logged exploration artifact or provenance is absent: {relative}")
    if artifact.get("role") not in MODEL_RUN_ARTIFACT_ROLES:
        raise ValueError(f"logged exploration artifact role is invalid: {relative}")
    spec_ids = artifact.get("spec_ids")
    validate_artifact_spec_ids(path, role=str(artifact.get("role") or ""), declared=spec_ids)
    if portable_content_sha256(path) != artifact.get("sha256"):
        raise ValueError(f"logged exploration artifact content changed: {relative}")
    if verifier(path).get("status") != "ok":
        raise RuntimeError(f"logged exploration artifact is not current: {relative}")
    provenance = _read_json_object(provenance_path, label="logged exploration provenance")
    if provenance.get("artefact") != describe_input(path).get("path"):
        raise ValueError(f"logged exploration provenance identifies a different artifact: {relative}")
    if required_sources is not None:
        provenance_sources = provenance.get("code_sources")
        if not isinstance(provenance_sources, list) or not set(required_sources).issubset(provenance_sources):
            raise ValueError(f"logged exploration provenance omits a declared engine source: {relative}")
    if d3_certificate_path is not None:
        d3_input_identity = describe_input(d3_certificate_path).get("path")
        provenance_inputs = provenance.get("inputs")
        if not isinstance(provenance_inputs, list) or d3_input_identity not in {
            record.get("path") for record in provenance_inputs if isinstance(record, dict)
        }:
            raise ValueError(f"logged exploration provenance is not bound to D3: {relative}")


def _executed_exploratory_runs(
    ledger: Mapping[str, Any],
    *,
    root: Path,
    verifier: Callable[[str | Path], dict[str, object]],
) -> list[dict[str, Any]]:
    runs = _terminal_exploratory_runs(ledger)
    executed = [dict(run) for run in runs if run.get("lifecycle") == "executed"]
    if not executed:
        raise RuntimeError("E0 cannot close without an executed fitted family")
    run_ids = [str(run.get("run_id") or "") for run in executed]
    if len(run_ids) != len(set(run_ids)) or any(run.get("run_id") != model_run_id(run) for run in executed):
        raise ValueError("E0 executed-run identity is not unique and current")
    d3_relative, d3_certificate = resolve_repo_path(
        str((ledger.get("exploration") or {}).get("d3_certificate") or ""),
        root=root,
        label="E0 ledger D3 certificate",
    )
    if not d3_certificate.is_file():
        raise FileNotFoundError(f"E0 ledger D3 certificate is absent: {d3_relative}")
    for run in executed:
        if run.get("d3_generation") != ledger.get("current_analysis_generation"):
            raise ValueError(f"E0 run cites a different D3 generation: {run.get('run_id')}")
        if run.get("disposition") == "admissible" or run.get("lock_hash") is not None or run.get("exploration_generation") is not None:
            raise ValueError(f"E0 run crosses the exploratory/confirmatory boundary: {run.get('run_id')}")
        engine_sources = run.get("engine_sources")
        if not isinstance(engine_sources, list) or any(not isinstance(value, str) for value in engine_sources) or _engine_hash(root, engine_sources) != run.get("engine_hash"):
            raise ValueError(f"E0 run engine identity is stale: {run.get('run_id')}")
        if run.get("plan_hash") != canonical_hash(_planned_identity(run)):
            raise ValueError(f"E0 run plan identity is stale: {run.get('run_id')}")
        artifacts = run.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(f"E0 executed run has no artifacts: {run.get('run_id')}")
        declared_artifacts = run.get("declared_artifacts")
        realized_contract = [
            {
                "path": artifact.get("path"),
                "role": artifact.get("role"),
                "spec_ids": artifact.get("spec_ids"),
            }
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]
        if not isinstance(declared_artifacts, list) or realized_contract != declared_artifacts:
            raise ValueError(f"E0 run artifacts differ from its exact plan: {run.get('run_id')}")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ValueError(f"E0 run has a malformed artifact: {run.get('run_id')}")
            _validate_artifact_record(
                artifact,
                root=root,
                verifier=verifier,
                required_sources=engine_sources,
                d3_certificate_path=d3_certificate,
            )
    return sorted(executed, key=lambda run: str(run["run_id"]))


def _terminal_exploratory_runs(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = ledger.get("runs", [])
    if not isinstance(values, list) or any(not isinstance(run, dict) for run in values):
        raise ValueError("E0 run perimeter contains a non-object record")
    runs = [dict(run) for run in values if run.get("lane") == "exploratory"]
    invalid = {
        str(run.get("run_id") or "missing"): str(run.get("lifecycle") or "missing")
        for run in runs
        if run.get("lifecycle") not in {"executed", "retired"}
    }
    if invalid:
        raise RuntimeError(f"E0 cannot close with non-terminal exploratory lifecycles: {invalid}")
    return runs


def _retired_exploratory_runs(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    retired = sorted(
        [
            dict(run)
            for run in _terminal_exploratory_runs(ledger)
            if run.get("lifecycle") == "retired"
        ],
        key=lambda run: str(run.get("run_id") or ""),
    )
    run_ids = [str(run.get("run_id") or "") for run in retired]
    if (
        len(run_ids) != len(set(run_ids))
        or any(run.get("run_id") != model_run_id(run) for run in retired)
        or any(run.get("plan_hash") != canonical_hash(_planned_identity(run)) for run in retired)
        or any(run.get("disposition") != "rejected" for run in retired)
    ):
        raise ValueError("E0 retired-run identity or disposition is invalid")
    return retired


def _reopen_ledger_plan(
    exploration: Mapping[str, Any],
    *,
    d3_generation: str,
    root: Path,
) -> ExplorationPlan:
    plan_relative, plan_path = resolve_repo_path(
        str(exploration.get("plan_path") or ""),
        root=root,
        label="ledger E0 exploration plan",
    )
    template_relative, template_path = resolve_repo_path(
        str(exploration.get("template_path") or ""),
        root=root,
        label="ledger E0 exploration plan template",
    )
    specification_relative, specification_path = resolve_repo_path(
        str(exploration.get("specification_path") or ""),
        root=root,
        label="ledger E0 specification lock",
    )
    bound_specification_sha256 = str(exploration.get("specification_sha256") or "")
    current_specification_sha256 = file_sha256(specification_path)
    bound_template_families = None
    if current_specification_sha256 != bound_specification_sha256:
        specification = _read_json_object(specification_path, label="E0 specification lock")
        seed_identity = specification.get("design_seed_identity")
        if not (
            exploration.get("status") == "complete"
            and specification.get("stage") == "confirmatory"
            and isinstance(seed_identity, dict)
            and seed_identity.get("file_sha256") == bound_specification_sha256
        ):
            raise ValueError("E0 specification identity changed after execution")
        template = _read_json_object(template_path, label="E0 exploration plan template")
        families = template.get("families")
        if not isinstance(families, list):
            raise ValueError("E0 exploration plan template has no family perimeter")
        bound_template_families = [
            {
                "family_id": str(family.get("family_id") or "").strip(),
                "claim_id": str(family.get("claim_id") or "").strip(),
                "question": str(family.get("question") or "").strip(),
                "search_dimensions": list(family.get("search_dimensions") or []),
                "required_attack_ids": _normalize_attack_ids(
                    family.get("required_attack_ids"),
                    label=f"bound E0 family {family.get('family_id') or 'missing'}",
                ),
            }
            for family in families
            if isinstance(family, dict) and family.get("execution_status") == "executable"
        ]
    plan = _load_plan(
        plan_path,
        plan_relative=plan_relative,
        template_path=template_path,
        template_relative=template_relative,
        root=root,
        d3_generation=d3_generation,
        specification_path=specification_path,
        specification_relative=specification_relative,
        bound_template_families=bound_template_families,
        bound_specification_sha256=(
            bound_specification_sha256
            if bound_template_families is not None
            else None
        ),
    )
    expected = {
        "plan_sha256": plan.plan_sha256,
        "template_sha256": plan.template_sha256,
        "specification_sha256": plan.specification_sha256,
        "expected_family_ids": list(plan.expected_family_ids),
        "family_perimeter_sha256": plan.family_perimeter_sha256,
    }
    changed = [field for field, value in expected.items() if exploration.get(field) != value]
    if changed:
        raise ValueError(f"E0 exploration plan identity changed after execution: {changed}")
    return plan


def _require_complete_family_perimeter(
    runs: list[dict[str, Any]],
    retired_runs: list[dict[str, Any]],
    *,
    plan: ExplorationPlan,
) -> None:
    family_ids = [str(run.get("family_id") or "") for run in runs]
    observed = set(family_ids)
    expected = set(plan.expected_family_ids)
    duplicate = sorted({family_id for family_id in family_ids if family_ids.count(family_id) > 1})
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    retired_unexpected = sorted(
        {
            str(run.get("family_id") or "")
            for run in retired_runs
        }
        - expected
    )
    if duplicate or missing or unexpected or retired_unexpected:
        raise RuntimeError(
            "E0 executed runs do not close the canonical family perimeter: "
            f"missing={missing or 'none'}; unexpected={unexpected or 'none'}; "
            f"duplicate={duplicate or 'none'}; "
            f"retired_unexpected={retired_unexpected or 'none'}"
        )
    contracts = {contract["family_id"]: contract for contract in plan.contracts}
    for run in [*runs, *retired_runs]:
        contract = contracts[str(run["family_id"])]
        if (
            run.get("required_attack_ids") != contract["required_attack_ids"]
            or run.get("attack_evidence") != contract["attack_evidence"]
        ):
            raise ValueError(f"E0 run attack evidence differs from its exact plan: {run.get('run_id')}")


def _validate_triage_decisions(
    payload: Mapping[str, Any],
    *,
    run_ids: set[str],
    retired_run_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if payload.get("schema_version") != EXPLORATION_TRIAGE_SCHEMA_VERSION:
        raise ValueError("E0 triage schema is not current")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("E0 triage decisions are not a list")
    decision_run_ids = [str(decision.get("run_id") or "") for decision in decisions if isinstance(decision, dict)]
    if len(decision_run_ids) != len(decisions) or len(decision_run_ids) != len(set(decision_run_ids)):
        raise ValueError("E0 triage contains malformed or duplicate run ids")
    decision_ids = [str(decision.get("decision_id") or "") for decision in decisions if isinstance(decision, dict)]
    if not all(decision_ids) or len(decision_ids) != len(decisions) or len(decision_ids) != len(set(decision_ids)):
        raise ValueError("E0 triage contains malformed or duplicate decision ids")
    if set(decision_run_ids) != run_ids:
        raise ValueError(f"E0 triage perimeter does not close: missing={sorted(run_ids - set(decision_run_ids))}; unexpected={sorted(set(decision_run_ids) - run_ids)}")
    normalized: list[dict[str, Any]] = []
    retired_run_ids = retired_run_ids or set()
    for decision in decisions:
        outcome = str(decision.get("outcome") or "")
        rationale = str(decision.get("rationale") or "").strip()
        assessment = decision.get("assessment")
        if outcome not in TRIAGE_OUTCOMES or not rationale:
            raise ValueError(f"E0 triage outcome or rationale is invalid: {decision.get('run_id')}")
        if str(decision.get("run_id") or "") in retired_run_ids and outcome != "reject":
            raise ValueError(f"a retired E0 execution must be triaged as rejected: {decision.get('run_id')}")
        if not isinstance(assessment, dict) or set(assessment) != TRIAGE_ASSESSMENT_FIELDS or any(not str(assessment[field]).strip() for field in TRIAGE_ASSESSMENT_FIELDS):
            raise ValueError(f"E0 triage lacks the six-axis assessment: {decision.get('run_id')}")
        if outcome == "promote":
            nodes = decision.get("required_reopen_nodes")
            if not str(decision.get("proposed_claim_id") or "").strip() or not isinstance(nodes, list) or "E1" not in nodes or any(node not in {"B", "C", "D", "E1"} for node in nodes):
                raise ValueError(f"promoted E0 discovery lacks its E1 registration route: {decision.get('run_id')}")
        elif outcome == "retain_auxiliary" and not str(decision.get("companion_role") or "").strip():
            raise ValueError(f"auxiliary E0 result lacks a companion role: {decision.get('run_id')}")
        elif outcome == "park_next_paper" and not str(decision.get("proposed_question") or "").strip():
            raise ValueError(f"parked E0 result lacks a next-paper question: {decision.get('run_id')}")
        elif outcome == "reject" and not str(decision.get("rejection_reason") or "").strip():
            raise ValueError(f"rejected E0 result lacks a reason: {decision.get('run_id')}")
        normalized.append(dict(decision))
    return sorted(normalized, key=lambda decision: str(decision["run_id"]))


def _build_exploration_certificate(
    *,
    d3: AnalysisRelease,
    d3_relative: str,
    runs: list[dict[str, Any]],
    retired_runs: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    plan: ExplorationPlan,
) -> dict[str, Any]:
    run_records = [{"run_id": run["run_id"], "record_sha256": canonical_hash(run)} for run in runs]
    retired_records = [{"run_id": run["run_id"], "record_sha256": canonical_hash(run)} for run in retired_runs]
    executed_ids = {str(record["run_id"]) for record in run_records}
    executed_decisions = [decision for decision in decisions if str(decision["run_id"]) in executed_ids]
    retired_decisions = [decision for decision in decisions if str(decision["run_id"]) not in executed_ids]
    certificate: dict[str, Any] = {
        "schema_version": EXPLORATION_CERTIFICATE_SCHEMA_VERSION,
        "kind": EXPLORATION_CERTIFICATE_KIND,
        "status": "pass",
        "d3_generation": d3.generation,
        "d3_certificate": d3_relative,
        "d3_certificate_sha256": file_sha256(d3.certificate_path),
        "plan_path": plan.plan_relative,
        "plan_sha256": plan.plan_sha256,
        "template_path": plan.template_relative,
        "template_sha256": plan.template_sha256,
        "expected_family_ids": list(plan.expected_family_ids),
        "family_perimeter_sha256": plan.family_perimeter_sha256,
        "exploratory_run_ids": [record["run_id"] for record in run_records],
        "exploratory_run_records": run_records,
        "exploratory_run_perimeter_sha256": canonical_hash(run_records),
        "retired_run_ids": [record["run_id"] for record in retired_records],
        "retired_run_records": retired_records,
        "all_exploratory_run_ids": sorted([record["run_id"] for record in [*run_records, *retired_records]]),
        "all_exploratory_run_perimeter_sha256": canonical_hash([*run_records, *retired_records]),
        "triage_decisions": executed_decisions,
        "retired_run_decisions": retired_decisions,
        "triage_perimeter_sha256": canonical_hash(decisions),
        "promotion_rule": "A promoted exploratory result remains non-admissible until E1 registers a distinct plan and F executes a distinct confirmatory run.",
    }
    certificate["generation"] = generation_id(certificate)
    return certificate


def _publish_exploration_certificate(
    certificate: Mapping[str, Any],
    *,
    pointer: Path,
    inputs: list[Path],
    code_sources: tuple[str, ...],
) -> Path:
    def write_certificate(path: Path) -> None:
        path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def validate_staged(paths: Mapping[str, Path]) -> None:
        if _read_json_object(paths["certificate"], label="staged E0 certificate") != certificate:
            raise ValueError("staged E0 certificate does not round-trip exactly")

    bundle = publish_artifact_release(
        pointer_path=pointer,
        kind=EXPLORATION_POINTER_KIND,
        schema_version=EXPLORATION_POINTER_SCHEMA_VERSION,
        filenames=EXPLORATION_FILENAMES,
        writers={"certificate": write_certificate},
        row_counts={"certificate": len(certificate["all_exploratory_run_ids"])},
        code_sources=list(code_sources),
        inputs=inputs,
        notes=f"E0 exploration release {certificate['generation']}",
        validate_staged=validate_staged,
        write_pointer=write_json,
    )
    return bundle.artifacts["certificate"]


def close_exploration(
    triage_path: str | Path,
    *,
    d3_certificate_path: str | Path,
    root: Path = REPO_ROOT,
    ledger_path: str | Path = "docs/model-ledger.json",
    pointer_path: str | Path = "data/processed/e0_exploration_release/current.json",
    lock_path: Path = EXPLORATION_LOCK,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = EXPLORATION_CODE_SOURCES,
) -> ExplorationRelease:
    """Close E0 only after exact run, artifact, and triage algebra passes."""

    triage_relative, resolved_triage = resolve_repo_path(triage_path, root=root, label="E0 triage")
    if not resolved_triage.is_file():
        raise FileNotFoundError(f"E0 triage is absent: {triage_relative}")
    _ledger_relative, resolved_ledger = resolve_repo_path(ledger_path, root=root, label="model ledger")
    d3_relative, _resolved_d3 = resolve_repo_path(d3_certificate_path, root=root, label="D3 certificate")
    _pointer_relative, resolved_pointer = resolve_repo_path(pointer_path, root=root, label="E0 release pointer")
    d3 = resolve_analysis_release(certificate_path=d3_relative, root=root, verifier=verifier)
    with exclusive_job(lock_path, job="E0 exploration closure"):
        ledger = _load_ledger(resolved_ledger)
        exploration = ledger["exploration"]
        if (
            ledger.get("current_analysis_generation") != d3.generation
            or exploration.get("d3_generation") != d3.generation
            or exploration.get("d3_certificate") != d3_relative
            or exploration.get("status") not in {"in_progress", "complete"}
        ):
            raise RuntimeError("E0 ledger does not target the reopened D3 release")
        runs = _executed_exploratory_runs(ledger, root=root, verifier=verifier)
        retired_runs = _retired_exploratory_runs(ledger)
        plan = _reopen_ledger_plan(
            exploration,
            d3_generation=d3.generation,
            root=root,
        )
        _require_complete_family_perimeter(runs, retired_runs, plan=plan)
        triage = _read_json_object(resolved_triage, label="E0 triage")
        retired_ids = {str(run["run_id"]) for run in retired_runs}
        decisions = _validate_triage_decisions(
            triage,
            run_ids={str(run["run_id"]) for run in [*runs, *retired_runs]},
            retired_run_ids=retired_ids,
        )
        certificate = _build_exploration_certificate(
            d3=d3,
            d3_relative=d3_relative,
            runs=runs,
            retired_runs=retired_runs,
            decisions=decisions,
            plan=plan,
        )
        if exploration.get("status") == "complete":
            certificate_relative = str(exploration.get("certificate") or "")
            if exploration.get("generation") != certificate["generation"] or not certificate_relative:
                raise RuntimeError("completed E0 ledger disagrees with the reconstructed certificate")
            existing = resolve_exploration_release(
                certificate_path=certificate_relative,
                ledger_path=str(Path(ledger_path)),
                root=root,
                verifier=verifier,
            )
            if existing.certificate != certificate:
                raise RuntimeError("completed E0 triage or ledger differs from its certificate")
            selected = resolve_artifact_release(
                resolved_pointer,
                kind=EXPLORATION_POINTER_KIND,
                schema_version=EXPLORATION_POINTER_SCHEMA_VERSION,
                filenames=EXPLORATION_FILENAMES,
                require_current_provenance=True,
            )
            if selected.artifacts["certificate"] != existing.certificate_path:
                raise RuntimeError("completed E0 pointer selects a different certificate")
            return existing
        inputs = [
            d3.certificate_path,
            root / plan.plan_relative,
            root / plan.template_relative,
            *[root / artifact["path"] for run in runs for artifact in run["artifacts"]],
            *[root / artifact["provenance_path"] for run in runs for artifact in run["artifacts"]],
        ]
        resolved_certificate = _publish_exploration_certificate(
            certificate,
            pointer=resolved_pointer,
            inputs=inputs,
            code_sources=code_sources,
        )
        certificate_relative = resolved_certificate.relative_to(root).as_posix()
        ledger["exploration"] = {
            **exploration,
            "status": "complete",
            "generation": certificate["generation"],
            "certificate": certificate_relative,
            "completed_at": _utc_now(),
        }
        _write_json_atomic(resolved_ledger, ledger)
    return resolve_exploration_release(
        certificate_path=certificate_relative,
        ledger_path=str(Path(ledger_path)),
        root=root,
        verifier=verifier,
    )


def resolve_exploration_release(
    *,
    certificate_path: str | Path,
    ledger_path: str | Path = "docs/model-ledger.json",
    root: Path = REPO_ROOT,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
) -> ExplorationRelease:
    """Reopen E0 against the current D3 release, ledger records, and artifacts."""

    certificate_relative, path = resolve_repo_path(certificate_path, root=root, label="E0 certificate")
    _ledger_relative, resolved_ledger = resolve_repo_path(ledger_path, root=root, label="model ledger")
    if not path.is_file():
        raise FileNotFoundError(f"E0 exploration certificate is absent: {path}")
    certificate = _read_json_object(path, label="E0 exploration certificate")
    if (
        certificate.get("schema_version") != EXPLORATION_CERTIFICATE_SCHEMA_VERSION
        or certificate.get("kind") != EXPLORATION_CERTIFICATE_KIND
        or certificate.get("status") != "pass"
        or certificate.get("generation") != generation_id(certificate)
    ):
        raise ValueError("E0 exploration certificate is stale or malformed")
    d3_relative = str(certificate.get("d3_certificate") or "")
    d3 = resolve_analysis_release(certificate_path=d3_relative, root=root, verifier=verifier)
    if d3.generation != certificate.get("d3_generation") or file_sha256(d3.certificate_path) != certificate.get("d3_certificate_sha256"):
        raise ValueError("E0 exploration certificate cites a different D3 release")
    ledger = _load_ledger(resolved_ledger)
    exploration = ledger["exploration"]
    if (
        exploration.get("status") != "complete"
        or exploration.get("generation") != certificate.get("generation")
        or exploration.get("certificate") != certificate_relative
        or ledger.get("current_analysis_generation") != d3.generation
    ):
        raise ValueError("E0 exploration certificate disagrees with the model ledger state")
    runs = _executed_exploratory_runs(ledger, root=root, verifier=verifier)
    retired_runs = _retired_exploratory_runs(ledger)
    plan = _reopen_ledger_plan(
        exploration,
        d3_generation=d3.generation,
        root=root,
    )
    _require_complete_family_perimeter(runs, retired_runs, plan=plan)
    certificate_decisions = [
        *(certificate.get("triage_decisions") or []),
        *(certificate.get("retired_run_decisions") or []),
    ]
    retired_ids = {str(run["run_id"]) for run in retired_runs}
    decisions = _validate_triage_decisions(
        {"schema_version": EXPLORATION_TRIAGE_SCHEMA_VERSION, "decisions": certificate_decisions},
        run_ids={str(run["run_id"]) for run in [*runs, *retired_runs]},
        retired_run_ids=retired_ids,
    )
    expected = _build_exploration_certificate(
        d3=d3,
        d3_relative=d3_relative,
        runs=runs,
        retired_runs=retired_runs,
        decisions=decisions,
        plan=plan,
    )
    if expected != certificate:
        raise ValueError("E0 exploration certificate does not reproduce from the current run ledger")
    return ExplorationRelease(str(certificate["generation"]), path, certificate, root)
