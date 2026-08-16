"""The two-unchanged-passes gate must be earned by the registry, not declared.

These tests pin the property that makes the fingerprint stricter than the retired
`stable_passes` counter: it moves when a claim's status or a family's retirement
moves, and it does not move when evidence, prose or exhibits do.
"""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.model_registry import (
    findings_fingerprint,
    findings_registry_state,
    read_findings_fingerprints,
    validate_findings_fingerprints,
)

SPECIFICATION = {
    "stage": "design_seed",
    "lock_hash": "irrelevant-to-the-fingerprint",
    "claims": [
        {"id": "vehicle_transition", "status": "candidate_primary", "estimand": "a"},
        {"id": "routing_maturation_rival", "status": "candidate_mechanism"},
        {"id": "persistence_hysteresis", "status": "withheld"},
    ],
}
LEDGER = {
    "updated": "2026-08-16",
    "legacy_families": [
        {"id": "family_a", "claim_id": "vehicle_transition", "status": "admissible"},
        {"id": "family_b", "claim_id": "retired_thing", "status": "retired"},
    ],
    "runs": [],
}


def _row(pass_id: str, commit: str, fingerprint: str) -> dict:
    return {
        "pass_id": pass_id,
        "commit": commit,
        "fingerprint": fingerprint,
        "recorded_at": "2026-08-16T00:00:00Z",
    }


def test_state_carries_only_claim_status_and_retired_families() -> None:
    state = findings_registry_state(SPECIFICATION, LEDGER)
    assert state["claims"] == [
        ["persistence_hysteresis", "withheld"],
        ["routing_maturation_rival", "candidate_mechanism"],
        ["vehicle_transition", "candidate_primary"],
    ]
    assert state["retired"] == [["family_b", "retired_thing"]]


def test_evidence_and_prose_changes_do_not_move_the_fingerprint() -> None:
    baseline = findings_fingerprint(SPECIFICATION, LEDGER)
    noisy_specification = json.loads(json.dumps(SPECIFICATION))
    noisy_specification["lock_hash"] = "a-completely-different-hash"
    noisy_specification["claims"][0]["estimand"] = "rewritten estimand prose"
    noisy_specification["claims"][0]["outputs"] = ["output/exhibits/new.jsonl"]
    noisy_ledger = json.loads(json.dumps(LEDGER))
    noisy_ledger["updated"] = "2026-12-31"
    noisy_ledger["legacy_families"][0]["substantive_specifications"] = 99
    assert findings_fingerprint(noisy_specification, noisy_ledger) == baseline


def test_a_silent_status_change_moves_the_fingerprint() -> None:
    baseline = findings_fingerprint(SPECIFICATION, LEDGER)
    promoted = json.loads(json.dumps(SPECIFICATION))
    promoted["claims"][1]["status"] = "candidate_primary"
    assert findings_fingerprint(promoted, LEDGER) != baseline

    dropped = json.loads(json.dumps(SPECIFICATION))
    del dropped["claims"][2]
    assert findings_fingerprint(dropped, LEDGER) != baseline

    unretired = json.loads(json.dumps(LEDGER))
    unretired["legacy_families"][1]["status"] = "admissible"
    assert findings_fingerprint(SPECIFICATION, unretired) != baseline


def test_two_matching_passes_from_distinct_commits_pass() -> None:
    rows = [_row("2026-08-16", "aaaa", "f1"), _row("2026-08-17", "bbbb", "f1")]
    passed, detail = validate_findings_fingerprints(rows, current_fingerprint="f1")
    assert passed, detail


def test_one_pass_is_not_enough() -> None:
    passed, detail = validate_findings_fingerprints([_row("p1", "aaaa", "f1")])
    assert not passed
    assert "need=2" in detail


def test_two_rows_from_one_commit_are_one_pass() -> None:
    rows = [_row("p1", "aaaa", "f1"), _row("p2", "aaaa", "f1")]
    passed, detail = validate_findings_fingerprints(rows)
    assert not passed
    assert "not distinct" in detail


def test_a_changed_registry_between_passes_fails() -> None:
    rows = [_row("p1", "aaaa", "f1"), _row("p2", "bbbb", "f2")]
    passed, detail = validate_findings_fingerprints(rows)
    assert not passed
    assert "changed between passes" in detail


def test_a_change_after_the_last_pass_fails() -> None:
    rows = [_row("p1", "aaaa", "f1"), _row("p2", "bbbb", "f1")]
    passed, detail = validate_findings_fingerprints(rows, current_fingerprint="f2")
    assert not passed
    assert "changed after the last pass" in detail


def test_an_incomplete_row_fails_rather_than_being_skipped() -> None:
    rows = [_row("p1", "aaaa", "f1"), {"pass_id": "p2", "fingerprint": "f1"}]
    passed, detail = validate_findings_fingerprints(rows)
    assert not passed
    assert "missing=" in detail


def test_the_ledger_reader_refuses_a_malformed_row(tmp_path: Path) -> None:
    ledger = tmp_path / "findings-fingerprints.jsonl"
    ledger.write_text(
        json.dumps(_row("p1", "aaaa", "f1")) + "\n# a comment\nnot json\n",
        encoding="utf-8",
    )
    assert read_findings_fingerprints(ledger) == []
    ledger.write_text(
        json.dumps(_row("p1", "aaaa", "f1")) + "\n\n" + json.dumps(_row("p2", "bbbb", "f1")) + "\n",
        encoding="utf-8",
    )
    assert len(read_findings_fingerprints(ledger)) == 2


def test_the_live_registries_produce_a_stable_fingerprint() -> None:
    root = Path(__file__).resolve().parents[1]
    specification = json.loads((root / "docs" / "specification-lock.json").read_text())
    ledger = json.loads((root / "docs" / "model-ledger.json").read_text())
    assert findings_fingerprint(specification, ledger) == findings_fingerprint(
        specification, ledger
    )
    state = findings_registry_state(specification, ledger)
    assert state["claims"], "the live claim registry must not be empty"
