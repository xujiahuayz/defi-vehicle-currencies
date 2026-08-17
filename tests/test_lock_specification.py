from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ddvc.model_registry import canonical_hash
from ddvc.provenance import portable_content_sha256
from scripts.audit_findings_freeze import validate_specification_lock
from scripts.lock_specification import build_confirmatory_lock, validate_design_seed


def _seed() -> dict:
    payload = json.loads(Path("docs/specification-lock.json").read_text(encoding="utf-8"))
    if payload.get("stage") == "design_seed":
        return payload
    seed = copy.deepcopy(payload)
    seed.pop("design_seed_identity")
    seed.pop("adjudications")
    seed.update(
        locked_at=None,
        stage="design_seed",
        analytical_choices_status="provisional_design_seed",
        d3_generation=None,
        d3_certificate=None,
        exploration_generation=None,
        exploration_certificate=None,
    )
    inverse_status = {
        "registered_primary": "candidate_primary",
        "registered_foundation": "candidate_foundation",
        "registered_mechanism": "candidate_mechanism",
        "registered_companion": "candidate_companion",
    }
    for claim in seed["claims"]:
        claim["status"] = inverse_status.get(claim["status"], claim["status"])
        if claim["id"] == "liquidity_rent_incidence":
            claim["status"] = "candidate_companion"
        claim.pop("withheld_reason", None)
        claim.pop("registered_specifications", None)
        claim.pop("plan_hash", None)
    seed["lock_hash"] = canonical_hash(
        {key: value for key, value in seed.items() if key != "lock_hash"}
    )
    assert seed["lock_hash"] == payload["design_seed_identity"]["lock_hash"]
    return seed


def test_lock_owner_refuses_a_corrupted_design_seed() -> None:
    seed = _seed()
    seed["global_rules"].pop("vehicle_dominance")
    with pytest.raises(ValueError, match="findings-freeze validator"):
        validate_design_seed(seed)


def test_lock_owner_machine_issues_a_valid_confirmatory_lock() -> None:
    seed = _seed()
    validate_design_seed(seed)
    locked = build_confirmatory_lock(
        copy.deepcopy(seed),
        seed_file_sha256=portable_content_sha256("docs/specification-lock.json"),
        d3_generation="d3-generation",
        d3_certificate="data/processed/d3/certificate.json",
        exploration_generation="e0-generation",
        exploration_certificate="data/processed/e0/certificate.json",
    )
    passed, detail = validate_specification_lock(locked, require_confirmatory=True)
    assert passed, detail
    assert locked["locked_at"]
    assert locked["adjudications"][0]["citations"]
    rent = next(claim for claim in locked["claims"] if claim["id"] == "liquidity_rent_incidence")
    assert rent["status"] == "withheld"
    assert all(
        claim.get("registered_specifications")
        for claim in locked["claims"]
        if claim.get("execution_gate") == "open"
    )
