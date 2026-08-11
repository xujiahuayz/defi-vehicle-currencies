from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from ddvc.analysis_release import publish_analysis_release
from ddvc.model_registry import canonical_hash, validate_artifact_spec_ids
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp, verify
from scripts.run_vehicle_transition_e0 import COMPONENT_FAMILY, COMPONENT_STATUS, expected_spec_ids, run_vehicle_transition


def _workspace():
    return tempfile.TemporaryDirectory(prefix="vehicle-transition-e0-test-", dir=REPO_ROOT)


def _cleanup_manifest_mirror(directory: Path) -> None:
    relative = directory.relative_to(REPO_ROOT)
    shutil.rmtree(REPO_ROOT / "data" / "manifests" / relative, ignore_errors=True)


def _panel(directory: Path, *, days: int = 40) -> Path:
    intermediation_rows: list[dict[str, object]] = []
    for year in (2024, 2026):
        for index, date in enumerate(pd.date_range(f"{year}-01-01", periods=days, freq="D")):
            row: dict[str, object] = {"date": date}
            for scope_index, scope in enumerate(
                ("two_leg", "single_venue_two_leg", "cross_venue_two_leg")
            ):
                stable = 35.0 + 12.0 * (year == 2026) + (index % 7) + scope_index
                native = 80.0 - stable + (index % 5)
                row[f"cnt_{scope}_stable"] = stable
                row[f"cnt_{scope}_native"] = native
                row[f"usd_within_20pct_{scope}_stable"] = stable * (1.1 + (index % 3) / 100)
                row[f"usd_within_20pct_{scope}_native"] = native * (0.9 + (index % 4) / 100)
            intermediation_rows.append(row)
    path = directory / "intermediation.parquet"
    pd.DataFrame(intermediation_rows).to_parquet(path, index=False)
    stamp(path, code_sources=["tests/test_vehicle_transition_e0.py"], inputs=[])
    return path


def _release(directory: Path, inputs: tuple[Path, ...]):
    specification = directory / "specification.json"
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [
            {
                "id": "vehicle_transition",
                "status": "candidate_primary",
                "execution_gate": "open",
                "inputs": [path.relative_to(REPO_ROOT).as_posix() for path in inputs],
            }
        ],
    }
    payload["lock_hash"] = canonical_hash(payload)
    specification.write_text(json.dumps(payload), encoding="utf-8")
    return publish_analysis_release(
        specification_path=specification.relative_to(REPO_ROOT),
        pointer_path=(directory / "d3/current.json").relative_to(REPO_ROOT),
    )


def _environment(release) -> dict[str, str]:
    return {
        "DDVC_D3_CERTIFICATE": release.certificate_path.relative_to(REPO_ROOT).as_posix(),
        "DDVC_D3_GENERATION": release.generation,
    }


def test_vehicle_transition_runner_uses_exact_released_panels_and_spec_perimeter() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            panel = _panel(directory)
            release = _release(directory, (panel,))
            assert COMPONENT_STATUS == "smoke_only_incomplete_family"
            estimates = directory / "estimates.jsonl"
            support = directory / "support.jsonl"
            assert run_vehicle_transition(
                environment=_environment(release),
                intermediation_path=panel,
                estimate_output=estimates,
                support_output=support,
            ) == 0
            fitted = pd.read_json(estimates, lines=True)
            geometry = pd.read_json(support, lines=True)
            assert sorted(fitted["spec_id"].tolist()) == expected_spec_ids()
            assert fitted["spec_id"].str.contains("smoke").all()
            assert fitted["family"].eq(COMPONENT_FAMILY).all()
            assert len(fitted) == 12
            assert "spec_id" not in geometry
            assert geometry["family"].eq(COMPONENT_FAMILY).all()
            assert len(geometry) == 12
            assert not geometry["support_exit_review_required"].astype(bool).any()
            assert validate_artifact_spec_ids(estimates, role="result", declared=expected_spec_ids()) == set(expected_spec_ids())
            assert validate_artifact_spec_ids(support, role="support", declared=[]) == set()
            assert verify(estimates)["status"] == "ok"
            provenance = json.loads(sidecar_path(estimates).read_text(encoding="utf-8"))
            assert any(record["path"].endswith("certificate.json") for record in provenance["inputs"])
        finally:
            _cleanup_manifest_mirror(directory)


def test_vehicle_transition_runner_writes_only_red_support_when_endpoint_support_is_weak() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            panel = _panel(directory, days=10)
            release = _release(directory, (panel,))
            estimates = directory / "estimates.jsonl"
            support = directory / "support.jsonl"
            assert run_vehicle_transition(
                environment=_environment(release),
                intermediation_path=panel,
                estimate_output=estimates,
                support_output=support,
            ) == 2
            assert not estimates.exists()
            geometry = pd.read_json(support, lines=True)
            assert geometry["support_exit_review_required"].astype(bool).any()
        finally:
            _cleanup_manifest_mirror(directory)


def test_vehicle_transition_runner_rejects_missing_stale_and_out_of_release_d3_inputs() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            panel = _panel(directory)
            release = _release(directory, (panel,))
            outputs = {
                "estimate_output": directory / "estimates.jsonl",
                "support_output": directory / "support.jsonl",
            }
            with pytest.raises(RuntimeError, match="lacks its DDVC_D3"):
                run_vehicle_transition(
                    environment={},
                    intermediation_path=panel,
                    **outputs,
                )
            outside = directory / "outside.parquet"
            pd.DataFrame({"date": ["2024-01-01"]}).to_parquet(outside, index=False)
            stamp(outside, code_sources=["tests/test_vehicle_transition_e0.py"], inputs=[])
            with pytest.raises(ValueError, match="outside the bound D3 release"):
                run_vehicle_transition(
                    environment=_environment(release),
                    intermediation_path=outside,
                    **outputs,
                )
            panel.write_bytes(panel.read_bytes() + b"tamper")
            with pytest.raises((RuntimeError, ValueError), match="not current|does not reproduce"):
                run_vehicle_transition(
                    environment=_environment(release),
                    intermediation_path=panel,
                    **outputs,
                )
        finally:
            _cleanup_manifest_mirror(directory)
