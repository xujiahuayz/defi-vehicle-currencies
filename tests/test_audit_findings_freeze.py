from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_findings_freeze import (
    collect_checks,
    validate_claim_build,
    validate_model_ledger,
    validate_specification_lock,
)


def _claim() -> dict:
    return {
        "id": "claim",
        "status": "registered_primary",
        "execution_gate": "open",
        "estimand": "difference",
        "sample": "sample",
        "unit": "day",
        "dependent_variable": "y",
        "inference": "clustered",
        "inputs": ["data/processed/input.parquet"],
        "outputs": ["output/exhibits/result.jsonl"],
    }


def _lock() -> dict:
    return {
        "schema_version": 1,
        "stage": "confirmatory",
        "locked_at": "2026-08-17T00:00:00+00:00",
        "d3_generation": "d3",
        "exploration_generation": "e0",
        "global_rules": {
            "audit_sampling": "validation only",
            "vehicle_status": "binary",
            "vehicle_dominance": "continuous",
            "cost_domination": "separate object",
            "abstract_question": "formation",
            "dynamic_horizons": "1, 7, 30, and 120 exact calendar days",
        },
        "claims": [_claim()],
    }


def test_specification_lock_accepts_direct_registered_contract() -> None:
    passed, detail = validate_specification_lock(_lock(), require_confirmatory=True)
    assert passed, detail


def test_specification_lock_rejects_duplicate_claims() -> None:
    payload = _lock()
    payload["claims"].append(dict(payload["claims"][0]))
    passed, _detail = validate_specification_lock(payload)
    assert not passed


def test_claim_build_requires_post_input_and_post_lock_output(tmp_path: Path) -> None:
    source = tmp_path / "data/processed/input.parquet"
    result = tmp_path / "output/exhibits/result.jsonl"
    source.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    source.write_text("input", encoding="utf-8")
    result.write_text("result", encoding="utf-8")
    passed, detail = validate_claim_build(_claim(), root=tmp_path, locked_at=0)
    assert passed, detail
    passed, _detail = validate_claim_build(
        _claim(), root=tmp_path, locked_at=datetime.now(timezone.utc).timestamp() + 1
    )
    assert not passed


def test_claim_build_reports_missing_paths(tmp_path: Path) -> None:
    passed, detail = validate_claim_build(_claim(), root=tmp_path, locked_at=0)
    assert not passed
    assert "data/processed/input.parquet" in detail
    assert "output/exhibits/result.jsonl" in detail


def test_model_ledger_is_optional_path_based_log(tmp_path: Path) -> None:
    artifact = tmp_path / "result.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    payload = {
        "schema_version": 2,
        "exploration": {"status": "complete"},
        "runs": [
            {
                "run_id": "run-1",
                "claim_id": "claim",
                "lane": "confirmatory",
                "lifecycle": "executed",
                "disposition": "admitted",
                "artifacts": [{"path": "result.jsonl"}],
            }
        ],
    }
    passed, detail = validate_model_ledger(
        payload,
        claim_ids={"claim"},
        require_confirmatory=True,
        root=tmp_path,
    )
    assert passed, detail


def test_collect_checks_reads_only_declared_claim_files(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    lock = _lock()
    lock["locked_at"] = "2000-01-01T00:00:00+00:00"
    (tmp_path / "docs/specification-lock.json").write_text(
        json.dumps(lock), encoding="utf-8"
    )
    source = tmp_path / "data/processed/input.parquet"
    result = tmp_path / "output/exhibits/result.jsonl"
    source.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    source.write_text("input", encoding="utf-8")
    result.write_text("result", encoding="utf-8")
    assert all(passed for _name, passed, _detail in collect_checks(root=tmp_path))
