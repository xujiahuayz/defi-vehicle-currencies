#!/usr/bin/env python3
"""Report whether the registered results are ready for the paper and deck.

The gate is intentionally small.  Reproducibility in this repository means that
the specification names each input and output, a script owns the transformation,
and the outputs were rebuilt after both their inputs and the confirmatory lock.
It does not require content hashes, fingerprint registries, or release certificates.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION_LOCK = ROOT / "docs/specification-lock.json"
MODEL_LEDGER = ROOT / "docs/model-ledger.json"

REQUIRED_CLAIM_FIELDS = {
    "id",
    "status",
    "estimand",
    "sample",
    "unit",
    "dependent_variable",
    "inference",
    "inputs",
    "outputs",
}
REGISTERED_STATUSES = {
    "registered_primary",
    "registered_foundation",
    "registered_mechanism",
    "registered_companion",
}
REQUIRED_GLOBAL_RULES = {
    "audit_sampling",
    "vehicle_status",
    "vehicle_dominance",
    "cost_domination",
    "abstract_question",
    "dynamic_horizons",
}
EXECUTABLE_STATUSES = REGISTERED_STATUSES | {
    "candidate_primary",
    "candidate_foundation",
    "candidate_mechanism",
    "candidate_companion",
}


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _active_claims(payload: dict) -> list[dict]:
    return [
        claim
        for claim in payload.get("claims", [])
        if isinstance(claim, dict)
        and claim.get("status") in EXECUTABLE_STATUSES
        and claim.get("execution_gate") == "open"
    ]


def validate_specification_lock(
    payload: dict,
    *,
    require_confirmatory: bool = False,
) -> tuple[bool, str]:
    """Check the human-readable lock structure without computing identities."""

    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        return False, "claims missing"
    ids = [str(claim.get("id") or "") for claim in claims if isinstance(claim, dict)]
    active = _active_claims(payload)
    incomplete = [
        str(claim.get("id") or "missing")
        for claim in active
        if not isinstance(claim, dict) or REQUIRED_CLAIM_FIELDS - set(claim)
    ]
    stage = str(payload.get("stage") or "")
    global_rules = payload.get("global_rules") or {}
    missing_global_rules = sorted(
        rule for rule in REQUIRED_GLOBAL_RULES if not str(global_rules.get(rule) or "").strip()
    )
    confirmatory_fields = bool(str(payload.get("locked_at") or "").strip())
    passed = bool(
        payload.get("schema_version") == 1
        and len(ids) == len(claims)
        and all(ids)
        and len(ids) == len(set(ids))
        and not incomplete
        and not missing_global_rules
        and active
        and stage in {"design_seed", "confirmatory"}
        and (not require_confirmatory or (stage == "confirmatory" and confirmatory_fields))
    )
    return passed, (
        f"stage={stage or 'missing'}; claims={len(claims)}; active={len(active)}; "
        f"incomplete={incomplete or 'none'}; "
        f"missing_global_rules={missing_global_rules or 'none'}; "
        f"confirmatory_lock={'ok' if confirmatory_fields else 'missing'}"
    )


def validate_model_ledger(
    payload: dict,
    *,
    claim_ids: set[str],
    lock_payload: dict | None = None,
    require_confirmatory: bool = False,
    root: Path = ROOT,
    verifier=None,
    verify_artifacts: bool = True,
) -> tuple[bool, str]:
    """Validate the optional run log using paths and states, never digests.

    The ledger remains useful as a research notebook, but the live freeze gate no
    longer depends on its former certificate and fingerprint fields.
    """

    del lock_payload, verifier
    runs = payload.get("runs")
    exploration = payload.get("exploration")
    if payload.get("schema_version") != 2 or not isinstance(runs, list):
        return False, "schema or runs invalid"
    if not isinstance(exploration, dict) or exploration.get("status") not in {
        "not_started",
        "in_progress",
        "complete",
    }:
        return False, "exploration state invalid"
    run_ids = [str(run.get("run_id") or "") for run in runs if isinstance(run, dict)]
    malformed = [
        index
        for index, run in enumerate(runs)
        if not isinstance(run, dict)
        or not run.get("run_id")
        or not run.get("claim_id")
        or not run.get("lane")
        or not run.get("lifecycle")
    ]
    missing_artifacts: list[str] = []
    if verify_artifacts:
        for run in runs:
            if not isinstance(run, dict) or run.get("lifecycle") != "executed":
                continue
            for artifact in run.get("artifacts", []):
                if not isinstance(artifact, dict) or not artifact.get("path"):
                    continue
                relative = str(artifact["path"])
                if not (root / relative).exists():
                    missing_artifacts.append(relative)
    confirmed = {
        str(run.get("claim_id"))
        for run in runs
        if isinstance(run, dict)
        and run.get("lane") == "confirmatory"
        and run.get("lifecycle") == "executed"
        and run.get("disposition") not in {"rejected", "retired"}
    }
    missing_confirmatory = sorted(claim_ids - confirmed) if require_confirmatory else []
    passed = bool(
        len(run_ids) == len(runs)
        and len(run_ids) == len(set(run_ids))
        and not malformed
        and not missing_artifacts
        and not missing_confirmatory
    )
    return passed, (
        f"runs={len(runs)}; malformed={malformed or 'none'}; "
        f"missing_artifacts={sorted(set(missing_artifacts)) or 'none'}; "
        f"missing_confirmatory={missing_confirmatory or 'none'}"
    )


def _locked_timestamp(payload: dict) -> float:
    value = str(payload.get("locked_at") or "")
    if not value:
        return 0.0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _claim_files(claim: dict, field: str, *, root: Path) -> list[Path]:
    return [root / str(relative) for relative in claim.get(field, [])]


def validate_claim_build(claim: dict, *, root: Path, locked_at: float) -> tuple[bool, str]:
    """Require declared files and a post-lock, post-input rebuild."""

    inputs = _claim_files(claim, "inputs", root=root)
    outputs = _claim_files(claim, "outputs", root=root)
    missing_inputs = [path.relative_to(root).as_posix() for path in inputs if not path.exists()]
    missing_outputs = [path.relative_to(root).as_posix() for path in outputs if not path.exists()]
    if missing_inputs or missing_outputs or not inputs or not outputs:
        return False, (
            f"missing_inputs={missing_inputs or 'none'}; "
            f"missing_outputs={missing_outputs or 'none'}"
        )
    newest_input = max(path.stat().st_mtime for path in inputs)
    oldest_output = min(path.stat().st_mtime for path in outputs)
    passed = oldest_output >= max(newest_input, locked_at)
    return passed, (
        f"inputs={len(inputs)}; outputs={len(outputs)}; "
        f"rebuilt_after_inputs={'yes' if oldest_output >= newest_input else 'no'}; "
        f"rebuilt_after_lock={'yes' if oldest_output >= locked_at else 'no'}"
    )


def collect_checks(*, root: Path = ROOT) -> list[tuple[str, bool, str]]:
    lock_path = root / SPECIFICATION_LOCK.relative_to(ROOT)
    try:
        lock = _load_json(lock_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [("specification lock", False, type(error).__name__)]

    lock_ok, lock_detail = validate_specification_lock(lock, require_confirmatory=True)
    checks = [("specification lock", lock_ok, lock_detail)]
    locked_at = _locked_timestamp(lock)
    for claim in _active_claims(lock):
        passed, detail = validate_claim_build(claim, root=root, locked_at=locked_at)
        checks.append((f"claim {claim['id']}", passed, detail))
    return checks


def main() -> int:
    checks = collect_checks()
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'BLOCKED'}  {name}: {detail}")
    blocked = sum(not passed for _name, passed, _detail in checks)
    print(f"\nworkflow: {'READY' if blocked == 0 else f'BLOCKED ({blocked})'}")
    return int(blocked > 0)


if __name__ == "__main__":
    raise SystemExit(main())
