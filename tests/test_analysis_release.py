from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import ddvc.analysis_release as analysis_release
from ddvc.analysis_release import (
    ANALYSIS_RELEASE_FILENAMES,
    ANALYSIS_RELEASE_POINTER_KIND,
    ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
    publish_analysis_release,
    resolve_analysis_release,
    resolve_current_analysis_release,
)
from ddvc.artifact_release import resolve_artifact_release
from ddvc.model_registry import canonical_hash, generation_id
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp


def _workspace():
    return tempfile.TemporaryDirectory(prefix="d3-release-test-", dir=REPO_ROOT)


def _cleanup_manifest_mirror(directory: Path) -> None:
    relative = directory.relative_to(REPO_ROOT)
    shutil.rmtree(REPO_ROOT / "data" / "manifests" / relative, ignore_errors=True)


def _write_specification(path: Path, inputs: list[str]) -> None:
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [
            {"id": "lead", "status": "candidate_primary", "execution_gate": "open", "inputs": inputs},
            {
                "id": "companion",
                "status": "candidate_companion",
                "execution_gate": "blocked_external_reference_variance",
                "inputs": ["data/raw/blocked-provider.json"],
            },
            {"id": "withheld", "status": "withheld"},
            {"id": "support", "status": "supporting"},
            {"id": "old", "status": "retired", "inputs": ["data/raw/ignored.json"]},
        ],
    }
    payload["lock_hash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _released_inputs(directory: Path) -> tuple[Path, Path]:
    first = directory / "first.parquet"
    second = directory / "second.json"
    pd.DataFrame({"day": ["20260101", "20260102"], "value": [1.0, 2.0]}).to_parquet(first, index=False)
    second.write_text(json.dumps({"status": "pass", "rows": 2}), encoding="utf-8")
    for path in (first, second):
        stamp(path, code_sources=["tests/test_analysis_release.py"], inputs=[])
    return first, second


def test_d3_release_reopens_exact_union_and_publishes_pointer_last() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            inputs = [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()]
            _write_specification(specification, inputs)
            pointer = directory / "release" / "current.json"
            release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
            )
            assert release.pointer_path == pointer
            assert release.certificate["claim_input_count"] == 2
            assert release.certificate["executable_claim_ids"] == ["lead"]
            assert release.certificate["excluded_claim_count"] == 4
            assert release.certificate["excluded_claims"] == [
                {
                    "claim_id": "companion",
                    "status": "candidate_companion",
                    "execution_gate": "blocked_external_reference_variance",
                    "exclusion_reason": "execution_gate_not_open",
                },
                {
                    "claim_id": "old",
                    "status": "retired",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
                {
                    "claim_id": "support",
                    "status": "supporting",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
                {
                    "claim_id": "withheld",
                    "status": "withheld",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
            ]
            assert release.certificate["generation"] == generation_id(release.certificate)
            assert [record["path"] for record in release.certificate["claim_inputs"]] == sorted(inputs)
            assert all(record["provenance_sha256"] for record in release.certificate["claim_inputs"])
            reopened = resolve_current_analysis_release(pointer_path=pointer.relative_to(REPO_ROOT))
            assert reopened.generation == release.generation
            direct = resolve_analysis_release(certificate_path=release.certificate_path.relative_to(REPO_ROOT))
            assert direct.certificate == release.certificate
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_release_fails_only_when_an_execution_open_claim_is_incomplete() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            specification = directory / "specification.json"
            _write_specification(specification, [])
            with pytest.raises(ValueError, match="execution-open claim has no analysis inputs: lead"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_rejects_a_stage_claim_with_no_explicit_execution_gate() -> None:
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [{"id": "lead", "status": "candidate_primary", "inputs": ["data/processed/input.parquet"]}],
    }
    with pytest.raises(ValueError, match="must explicitly declare its execution gate: lead"):
        analysis_release._active_claim_input_perimeter(payload)


def test_real_specification_excludes_closed_and_non_stage_claims_from_d3() -> None:
    specification = json.loads((REPO_ROOT / "docs/specification-lock.json").read_text(encoding="utf-8"))
    assert analysis_release._validate_specification_identity(specification) == specification["lock_hash"]
    stage_statuses = {
        "candidate_primary",
        "candidate_foundation",
        "candidate_mechanism",
        "candidate_companion",
    }
    stage_claims = [claim for claim in specification["claims"] if claim["status"] in stage_statuses]
    assert all(claim.get("execution_gate") for claim in stage_claims)
    perimeter = analysis_release._active_claim_input_perimeter(specification)
    expected_executable = tuple(
        sorted(claim["id"] for claim in stage_claims if claim["execution_gate"] == "open")
    )
    assert perimeter.executable_claim_ids == expected_executable
    assert {
        "direct_cost_dominance",
        "routing_maturation_rival",
        "vehicle_transition",
    }.issubset(perimeter.executable_claim_ids)
    expected_excluded = {
        claim["id"]: {
            "claim_id": claim["id"],
            "status": claim["status"],
            "execution_gate": claim.get("execution_gate"),
            "exclusion_reason": (
                "execution_gate_not_open"
                if claim["status"] in stage_statuses
                else "status_not_executable_at_design_seed"
            ),
        }
        for claim in specification["claims"]
        if claim["id"] not in expected_executable
    }
    assert {record["claim_id"]: record for record in perimeter.excluded_claims} == expected_excluded
    executable_paths = set(perimeter.paths)
    for claim in specification["claims"]:
        if claim["id"] in expected_excluded:
            assert executable_paths.isdisjoint(claim.get("inputs", []))


def test_d3_release_rejects_raw_missing_and_stale_claim_inputs() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, _second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(specification, ["data/raw/provider.json"])
            with pytest.raises(ValueError, match="raw provider input"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
            missing = directory / "missing.parquet"
            _write_specification(specification, [missing.relative_to(REPO_ROOT).as_posix()])
            with pytest.raises(FileNotFoundError, match="claim input is absent"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
            _write_specification(specification, [first.relative_to(REPO_ROOT).as_posix()])
            first.write_bytes(first.read_bytes() + b"tamper")
            with pytest.raises(RuntimeError, match="claim input is not current"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_reader_rejects_input_and_provenance_tampering_after_release() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(
                specification,
                [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()],
            )
            release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
            )
            provenance = json.loads(sidecar_path(first).read_text(encoding="utf-8"))
            provenance["artefact"] = "different.parquet"
            sidecar_path(first).write_text(json.dumps(provenance), encoding="utf-8")
            with pytest.raises((RuntimeError, ValueError), match="current|provenance"):
                resolve_analysis_release(certificate_path=release.certificate_path.relative_to(REPO_ROOT))
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_pointer_crash_preserves_the_previous_release(monkeypatch: pytest.MonkeyPatch) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(specification, [first.relative_to(REPO_ROOT).as_posix()])
            pointer = directory / "release/current.json"
            first_release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
            )
            pointer_before = pointer.read_bytes()
            _write_specification(
                specification,
                [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()],
            )

            def crash_before_pointer(*_args, **_kwargs):
                raise RuntimeError("injected D3 pointer crash")

            monkeypatch.setattr(analysis_release, "write_json", crash_before_pointer)
            with pytest.raises(RuntimeError, match="injected D3 pointer crash"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                )
            assert pointer.read_bytes() == pointer_before
            selected = resolve_artifact_release(
                pointer,
                kind=ANALYSIS_RELEASE_POINTER_KIND,
                schema_version=ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
                filenames=ANALYSIS_RELEASE_FILENAMES,
                require_current_provenance=False,
            )
            assert selected.artifacts["certificate"] == first_release.certificate_path
        finally:
            _cleanup_manifest_mirror(directory)
