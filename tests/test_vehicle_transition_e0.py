from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ddvc.analysis_release import publish_analysis_release
from ddvc.artifact_release import SemanticValidationReceipt
from ddvc.model_registry import canonical_hash, validate_artifact_spec_ids
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp, verify
from scripts import run_vehicle_transition_e0 as runner
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
            # Tampering the panel also stales the certificate that recorded it, so the
            # run can fail closed at either boundary. Both are refusals; neither is a
            # partial run, which is what this assertion is protecting.
            with pytest.raises(
                (RuntimeError, ValueError),
                match="not current|does not reproduce|certificate.json=stale",
            ):
                run_vehicle_transition(
                    environment=_environment(release),
                    intermediation_path=panel,
                    **outputs,
                )
        finally:
            _cleanup_manifest_mirror(directory)


def _choice_rows(days: int = 40) -> pd.DataFrame:
    """A minimal endpoint-candidate choice panel with two dated backing regimes."""

    rows: list[dict[str, object]] = []
    for year, fiat, synthetic in ((2024, 20.0, 1.0), (2026, 45.0, 7.0)):
        for index, day in enumerate(pd.date_range(f"{year}-03-01", periods=days, freq="D")):
            for scope in ("single_venue", "cross_venue"):
                for address, symbol, candidate_type, regime, routes in (
                    ("0x01", "WETH", "native", "not_applicable", 100.0 + index),
                    ("0x02", "USDC", "stable", "fiat_reserve", fiat + (index % 3)),
                    ("0x03", "USDe", "stable", "synthetic", synthetic),
                ):
                    rows.append(
                        {
                            "date": day,
                            "candidate_address": address,
                            "candidate_symbol": symbol,
                            "candidate_type": candidate_type,
                            "backing_regime": regime,
                            "integration_scope": scope,
                            "route_count": routes,
                            "within_20pct_value_usd": routes * 1.5,
                        }
                    )
    return pd.DataFrame(rows)


@contextmanager
def _leased(_context, _inputs, *, root, consumer):
    yield [root / "data/processed/intermediation_by_type_daily.parquet"]


def _wire_backing_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, choices: pd.DataFrame):
    """Bind the dated-backing component to synthetic inputs and capture its writes."""

    receipt = SemanticValidationReceipt("a" * 64, "b" * 64)
    release = SimpleNamespace(
        generation_id=receipt.generation_id,
        artifacts={"choices": tmp_path / "choices.parquet"},
        bundle=SimpleNamespace(
            lineage_paths=(tmp_path / "endpoint/current.json",),
            assert_current=lambda: None,
        ),
    )

    @contextmanager
    def current_release(_pointer, *, expected_semantic_receipt):
        assert expected_semantic_receipt == receipt
        yield release

    writes: list[tuple[str, pd.DataFrame, Path]] = []
    monkeypatch.setattr(runner, "model_artifact_context", lambda **_kwargs: object())
    monkeypatch.setattr(
        runner, "expected_release_receipt_in_d3", lambda *_args, **_kwargs: receipt
    )
    monkeypatch.setattr(runner, "require_released_model_inputs", _leased)
    monkeypatch.setattr(
        runner, "current_endpoint_candidate_composition_release", current_release
    )
    monkeypatch.setattr(runner.pd, "read_parquet", lambda _path: choices)
    monkeypatch.setattr(
        runner,
        "vehicle_transition_tests",
        lambda _panel, **_kwargs: _pooled_transition_estimates(),
    )
    monkeypatch.setattr(
        runner,
        "write_model_exhibit",
        lambda frame, path, *, role, **_kwargs: writes.append((role, frame.copy(), path)),
    )
    return writes


def _pooled_transition_estimates() -> pd.DataFrame:
    rows = [
        {
            "routing_scope": scope,
            "weighting": weighting,
            "value_support": value_support,
            "transformation": transformation,
            "change": 0.1,
            "days": 40,
        }
        for scope in ("two_leg", "single_venue_two_leg", "cross_venue_two_leg")
        for weighting, value_support in (("episode", "all_routes"), ("value", "within_20pct"))
        for transformation in ("share_level", "log_odds")
    ]
    return pd.DataFrame(rows)


def test_dated_backing_component_publishes_attack_evidence_with_its_own_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = _wire_backing_runner(monkeypatch, tmp_path, _choice_rows())
    assert runner.run_dated_backing_regimes(minimum_endpoint_days=5) == 0
    roles = [role for role, _frame, _path in writes]
    assert roles == ["support", "result"]
    support = writes[0][1]
    estimates = writes[1][1]
    assert set(support["record_type"]) == {
        "support",
        "regime_change_ledger",
        "additive_decomposition",
        "universe_reconciliation",
    }
    assert support["attack_id"].eq(runner.BACKING_ATTACK_ID).all()
    assert estimates["attack_id"].eq(runner.BACKING_ATTACK_ID).all()
    assert estimates["family"].eq(runner.BACKING_COMPONENT_FAMILY).all()
    assert estimates["spec_id"].is_unique
    assert estimates["spec_id"].str.startswith("vehicle-transition-e0-dated-backing").all()
    # Every fitted regime term must sum back to the pooled term on the same universe.
    checks = support[support["record_type"].eq("additive_decomposition")]
    assert checks["checked"].all()
    assert runner.BACKING_ATTACK_ID in runner.COMPONENT_ATTACK_COVERAGE


def test_dated_backing_component_publishes_support_then_refuses_broken_additivity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = _wire_backing_runner(monkeypatch, tmp_path, _choice_rows())
    real_tests = runner.backing_regime_tests

    def tampered(daily, support, **kwargs):
        estimates = real_tests(daily, support, **kwargs)
        target = estimates["stratum_role"].eq("regime") & estimates["transformation"].eq(
            "share_level"
        )
        estimates.loc[estimates[target].index[0], "change"] += 0.05
        return estimates

    monkeypatch.setattr(runner, "backing_regime_tests", tampered)
    with pytest.raises(ValueError, match="do not sum to the pooled change"):
        runner.run_dated_backing_regimes(minimum_endpoint_days=5)
    # The failed check is published as support before the refusal, so the next
    # worker inherits the evidence rather than an empty directory.
    assert [role for role, _frame, _path in writes] == ["support"]
    checks = writes[0][1]
    checks = checks[checks["record_type"].eq("additive_decomposition")]
    assert (checks["absolute_difference"].astype(float) > checks["tolerance"]).any()
