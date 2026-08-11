from __future__ import annotations

import copy
from decimal import Decimal
import json
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddvc.analysis.dominance_cost_pair_probe import (
    _finite_json,
    _ledger_manifest,
    _serialized_p_value,
    SupportThresholds,
    SUPPORT_COLUMNS,
    _covariance_status,
    _state_records,
    load_panel,
    load_support,
    prepare_frame,
    prepare_support,
    publish_probe,
    reconcile_panel_support,
    resolve_probe_input,
    run_probe,
)
from ddvc.analysis.dominance_cost_contract import COMPARATOR_VEHICLES
from ddvc.analysis.dominance_cost_release import (
    DOMINANCE_COST_RELEASE_FILENAMES,
    DOMINANCE_COST_RELEASE_KIND,
    DOMINANCE_COST_RELEASE_SCHEMA_VERSION,
)
from ddvc.analysis.regression import ClusteredOLSResult
from ddvc.analysis.routing_technology import ROUTING_ERA_CUTOFFS, routing_era_case_sql, routing_era_for_date
from ddvc.artifact_release import canonical_json_sha256, file_sha256, generation_id


def _raw_row(*, available: int = 5) -> dict[str, object]:
    comparator = 1_000.0
    edge = 25.0
    ratio = edge / 20_000.0
    return {
        "date": "2025-01-01",
        "reserve_hour_utc": 12,
        "src": "0x01",
        "tgt": "0x02",
        "trade_size_usd": 10_000.0,
        "comparator": next(address for address, symbol in COMPARATOR_VEHICLES.items() if symbol == "USDC"),
        "comparator_symbol": "USDC",
        "weth_output_usd": comparator * (1 + ratio) / (1 - ratio),
        "comparator_output_usd": comparator,
        "available_candidate_count": available,
        "weth_hop1_source": "uniswap_v3",
        "weth_hop2_source": "uniswap_v2",
        "comparator_hop1_source": "uniswap_v4",
        "comparator_hop2_source": "uniswap_v2",
        "weth_symmetric_output_edge_bps": edge,
    }


def _quarantined_release(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    build_identity = "1" * 64
    staged = tmp_path / "staged"
    staged.mkdir()
    panel = staged / DOMINANCE_COST_RELEASE_FILENAMES["panel"]
    support = staged / DOMINANCE_COST_RELEASE_FILENAMES["support"]
    pq.write_table(pa.Table.from_pylist([_raw_row()]), panel)
    support_rows = []
    for address, symbol in COMPARATOR_VEHICLES.items():
        for notional in (1_000.0, 10_000.0, 100_000.0):
            positive = int(symbol == "USDC" and notional == 10_000.0)
            support_rows.append(
                {
                    "date": "2025-01-01",
                    "comparator": address,
                    "comparator_symbol": symbol,
                    "trade_size_usd": Decimal(str(notional)),
                    "candidate_pair_attempted": positive,
                    "both_indirect_available": positive,
                    "positive_finite_indirect_outputs": positive,
                    "direct_available": 0,
                    "positive_finite_direct_output": 0,
                }
            )
    pq.write_table(pa.Table.from_pylist(support_rows), support)
    hashes = {"panel": file_sha256(panel), "support": file_sha256(support)}
    generation = generation_id(hashes, build_identity)
    target = root / "generations" / generation
    target.mkdir(parents=True)
    panel.replace(target / panel.name)
    support.replace(target / support.name)
    pointer = {
        "schema_version": DOMINANCE_COST_RELEASE_SCHEMA_VERSION,
        "kind": DOMINANCE_COST_RELEASE_KIND,
        "generation_id": generation,
        "build_identity_sha256": build_identity,
        "artifacts": {
            name: {"filename": filename, "sha256": hashes[name], "provenance_sha256": "2" * 64}
            for name, filename in DOMINANCE_COST_RELEASE_FILENAMES.items()
        },
    }
    path = root / "current.json"
    path.write_text(json.dumps(pointer), encoding="utf-8")
    return path


def _synthetic_frame() -> pd.DataFrame:
    rows = []
    comparators = {"USDC": -20.0, "USDT": -5.0, "DAI": 30.0, "WBTC": 90.0}
    dates = [f"2024-01-{day:02d}" for day in range(1, 21)] + [f"2025-01-{day:02d}" for day in range(1, 21)]
    for date_index, date in enumerate(dates):
        for endpoint_pair in range(1, 41):
            for comparator, base in comparators.items():
                address = next(address for address, symbol in COMPARATOR_VEHICLES.items() if symbol == comparator)
                for notional_index, notional in enumerate((1_000.0, 10_000.0, 100_000.0)):
                    base_attempt = 1 + (date_index * 40 + endpoint_pair) * 3 + notional_index
                    first_pair = comparator in {"USDC", "USDT"}
                    edge = base + 0.25 * date_index - 0.1 * endpoint_pair - 0.00005 * notional
                    output = 1_000.0
                    ratio = edge / 20_000.0
                    rows.append(
                        {
                            "date": date,
                            "reserve_hour_utc": (date_index + endpoint_pair) % 24,
                            "endpoint_pair": endpoint_pair,
                            "attempt_id": base_attempt if first_pair else base_attempt + 100_000,
                            "comparator_support_mask": 3 if first_pair else 12,
                            "comparator": address,
                            "comparator_symbol": comparator,
                            "trade_size_usd": notional,
                            "available_candidate_count": 5 if endpoint_pair < 8 else 3,
                            "architecture": "both_tick",
                            "weth_output_usd": output * (1 + ratio) / (1 - ratio),
                            "comparator_output_usd": output,
                            "weth_symmetric_output_edge_bps": edge,
                        }
                    )
    return prepare_frame(pd.DataFrame(rows))


def _synthetic_support() -> pd.DataFrame:
    rows = []
    dates = [f"2024-01-{day:02d}" for day in range(1, 21)] + [f"2025-01-{day:02d}" for day in range(1, 21)]
    for date in dates:
        for address, symbol in COMPARATOR_VEHICLES.items():
            for notional in (1_000.0, 10_000.0, 100_000.0):
                rows.append(
                    {
                        "date": date,
                        "comparator": address,
                        "comparator_symbol": symbol,
                        "trade_size_usd": notional,
                        "candidate_pair_attempted": 50,
                        "both_indirect_available": 45,
                        "positive_finite_indirect_outputs": 40,
                        "direct_available": 30,
                        "positive_finite_direct_output": 25,
                    }
                )
    return prepare_support(pd.DataFrame(rows), expected_dates=dates)


def _synthetic_identity(seed: str) -> dict[str, object]:
    return {"panel_sha256": seed * 64, "support_sha256": "7" * 64, "provenance_status": "synthetic"}


def _reseal(report: dict[str, object], ledger: list[dict[str, object]]) -> None:
    report["ledger_manifest"] = _ledger_manifest(ledger)
    payload = {key: value for key, value in report.items() if key != "result_sha256"}
    report["result_sha256"] = canonical_json_sha256({"report": payload, "ledger": ledger})


def test_quarantine_resolution_binds_hashes_and_maps_five_to_four_plus(tmp_path: Path) -> None:
    pointer = _quarantined_release(tmp_path)
    with pytest.raises(FileNotFoundError, match="lacks provenance"):
        resolve_probe_input(pointer, allow_quarantined=False)
    resolved = resolve_probe_input(pointer, allow_quarantined=True)
    panel = resolved["artifacts"]["panel"]
    support = resolved["artifacts"]["support"]
    frame = load_panel(panel)
    support_frame = load_support(support, expected_dates=("2025-01-01",))
    reconcile_panel_support(frame, support_frame)
    assert resolved["provenance_status"] == "quarantined_missing_provenance"
    assert frame["available_candidate_count"].astype(str).tolist() == ["4_plus"]
    assert frame["architecture"].astype(str).tolist() == ["both_tick"]


def test_non_positive_definite_covariance_is_explicit() -> None:
    fit = ClusteredOLSResult(
        beta=np.array([1.0, 2.0]),
        covariance=np.array([[1.0, 2.0], [2.0, 1.0]]),
        n_observations=100,
        n_clusters=10,
        absorbed_degrees_of_freedom=0,
    )
    status = _covariance_status(fit)
    assert status["finite"] is True
    assert status["positive_definite"] is False
    assert status["minimum_eigenvalue"] == pytest.approx(-1.0)


def test_synthetic_probe_is_deterministic_and_retains_support_failures(tmp_path: Path) -> None:
    identity = _synthetic_identity("3")
    thresholds = SupportThresholds(reference_endpoint_pairs=30)
    first_report, first_ledger = run_probe(_synthetic_frame(), _synthetic_support(), identity, thresholds=thresholds)
    second_report, second_ledger = run_probe(_synthetic_frame(), _synthetic_support(), identity, thresholds=thresholds)
    assert first_report == second_report
    assert first_ledger == second_ledger
    assert any(record.get("status") == "support_fail" for record in first_ledger)
    assert any(record.get("available_candidate_count") == "4_plus" for record in first_ledger)
    first_pointer = publish_probe(first_report, first_ledger, tmp_path / "provisional-first")
    second_pointer = publish_probe(second_report, second_ledger, tmp_path / "provisional-second")
    assert first_pointer["result_sha256"] == second_pointer["result_sha256"]
    assert first_pointer["files"] == second_pointer["files"]
    assert first_report["old_estimand_bridge"]["direct_numeric_comparison_valid"] is False
    assert sum(record["record_type"] == "architecture_breadth_era_state" for record in first_ledger) == 144
    assert first_report["support_attrition"]["conditioning_stage"] == "positive_finite_indirect_outputs"


def test_state_reference_support_requires_noon_and_publisher_rejects_mutation(tmp_path: Path) -> None:
    frame = _synthetic_frame()
    frame["reserve_hour_utc"] = 11
    records = _state_records(
        frame,
        SupportThresholds(observations=1, dates=1, endpoint_pairs=1, reference_observations=1, reference_dates=1, reference_endpoint_pairs=1),
    )
    assert records
    assert all(record["status"] == "support_fail" for record in records)
    assert all("reference_observations" in record["failed_thresholds"] for record in records)
    report, ledger = run_probe(_synthetic_frame(), _synthetic_support(), _synthetic_identity("4"))
    mutated = dict(report)
    mutated["headline_boundary"] = "mutated"
    with pytest.raises(ValueError, match="result hash disagrees"):
        publish_probe(mutated, ledger, tmp_path / "provisional-mutated")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("comparator_symbol", "UNKNOWN", "comparator_symbol"),
        ("trade_size_usd", 2_000.0, "trade_size_usd"),
        ("architecture", "unknown", "architecture"),
        ("available_candidate_count", 0, "available_candidate_count"),
        ("available_candidate_count", 2.5, "available_candidate_count"),
        ("reserve_hour_utc", 24, "reserve_hour_utc"),
        ("reserve_hour_utc", 12.5, "reserve_hour_utc"),
    ],
)
def test_prepare_frame_rejects_out_of_domain_values(field: str, value: object, message: str) -> None:
    row = _synthetic_frame().iloc[[0]].copy()
    row[field] = value
    with pytest.raises(ValueError, match=message):
        prepare_frame(row)


def test_publisher_rejects_self_consistent_malformed_report(tmp_path: Path) -> None:
    report, ledger = run_probe(_synthetic_frame(), _synthetic_support(), _synthetic_identity("5"))
    malformed = dict(report)
    malformed["status"] = "admissible"
    payload = {key: value for key, value in malformed.items() if key != "result_sha256"}
    malformed["result_sha256"] = canonical_json_sha256({"report": payload, "ledger": ledger})
    with pytest.raises(ValueError, match="report contract"):
        publish_probe(malformed, ledger, tmp_path / "provisional-malformed")


def test_publisher_rejects_self_consistent_truncated_ledger(tmp_path: Path) -> None:
    report, ledger = run_probe(_synthetic_frame(), _synthetic_support(), _synthetic_identity("6"))
    truncated = ledger[1:]
    malformed = dict(report)
    malformed["ledger_manifest"] = _ledger_manifest(truncated)
    payload = {key: value for key, value in malformed.items() if key != "result_sha256"}
    malformed["result_sha256"] = canonical_json_sha256({"report": payload, "ledger": truncated})
    with pytest.raises(ValueError, match="coverage is incomplete"):
        publish_probe(malformed, truncated, tmp_path / "provisional-truncated")


def test_publisher_rejects_resealed_truncated_fit_vector_in_report_and_ledger(tmp_path: Path) -> None:
    report, ledger = run_probe(_synthetic_frame(), _synthetic_support(), _synthetic_identity("8"))
    malformed = copy.deepcopy(report)
    malformed_ledger = copy.deepcopy(ledger)
    malformed["comparator_models"]["USDC"]["models"]["m0_raw"]["coefficients"].pop()
    model = next(record for record in malformed_ledger if record["record_type"] == "comparator_model" and record["comparator"] == "USDC" and record["model"] == "m0_raw")
    model["estimate"]["coefficients"].pop()
    _reseal(malformed, malformed_ledger)
    with pytest.raises(ValueError, match="vectors are truncated"):
        publish_probe(malformed, malformed_ledger, tmp_path / "provisional-truncated-fit")


@pytest.mark.parametrize("mutation", ("pooled", "sample_n", "attrition"))
def test_publisher_rejects_resealed_report_summary_mutations(tmp_path: Path, mutation: str) -> None:
    report, ledger = run_probe(_synthetic_frame(), _synthetic_support(), _synthetic_identity("9"))
    malformed = copy.deepcopy(report)
    if mutation == "pooled":
        malformed["pooled_models"]["year"]["coefficients"][0] += 1
    elif mutation == "sample_n":
        malformed["sample"]["n"] += 1
    else:
        malformed["support_attrition"]["overall"]["counts"]["candidate_pair_attempted"] += 1
    _reseal(malformed, ledger)
    with pytest.raises(ValueError):
        publish_probe(malformed, ledger, tmp_path / f"provisional-mutated-{mutation}")


@pytest.mark.parametrize("kind", ("boolean", "float"))
def test_prepare_support_rejects_noninteger_count_storage(kind: str) -> None:
    support = _synthetic_support()
    raw = support[list(SUPPORT_COLUMNS)].copy()
    dates = tuple(raw["date"].astype(str).unique())
    if kind == "boolean":
        raw["candidate_pair_attempted"] = raw["candidate_pair_attempted"].gt(0)
    else:
        raw["candidate_pair_attempted"] = raw["candidate_pair_attempted"].astype(float)
    with pytest.raises(ValueError, match="integer counts"):
        prepare_support(raw, expected_dates=dates)


def test_prepare_support_rejects_nonstring_date_and_whole_date_omission() -> None:
    support = _synthetic_support()
    raw = support[list(SUPPORT_COLUMNS)].copy()
    dates = tuple(raw["date"].astype(str).unique())
    nonstring = raw.copy()
    nonstring["date"] = pd.to_datetime(nonstring["date"])
    with pytest.raises(ValueError, match="string values for date"):
        prepare_support(nonstring, expected_dates=dates)
    missing = raw[raw["date"].ne(dates[0])].copy()
    with pytest.raises(ValueError, match="full date-comparator-notional lattice"):
        prepare_support(missing, expected_dates=dates)


@pytest.mark.parametrize("kind", ("boolean", "float", "timestamp"))
def test_load_support_rejects_noncanonical_arrow_types(tmp_path: Path, kind: str) -> None:
    pointer = _quarantined_release(tmp_path)
    resolved = resolve_probe_input(pointer, allow_quarantined=True)
    source = pq.read_table(resolved["artifacts"]["support"])
    if kind == "timestamp":
        position = source.schema.get_field_index("date")
        replacement = pa.array(pd.to_datetime(source["date"].to_pylist()), type=pa.timestamp("ns"))
    else:
        position = source.schema.get_field_index("candidate_pair_attempted")
        arrow_type = pa.bool_() if kind == "boolean" else pa.float64()
        replacement = source["candidate_pair_attempted"].cast(arrow_type)
    malformed = source.set_column(position, source.column_names[position], replacement)
    path = tmp_path / f"support-{kind}.parquet"
    pq.write_table(malformed, path)
    with pytest.raises(ValueError, match="Arrow type"):
        load_support(path, expected_dates=("2025-01-01",))


def test_support_reconciliation_rejects_selection_mismatch() -> None:
    support = _synthetic_support()
    support.loc[support.index[0], "positive_finite_indirect_outputs"] -= 1
    with pytest.raises(ValueError, match="does not reconcile"):
        reconcile_panel_support(_synthetic_frame(), support)


def test_prepare_frame_rejects_comparator_address_symbol_mismatch() -> None:
    frame = _synthetic_frame().iloc[[0]].copy()
    frame["comparator"] = next(address for address, symbol in COMPARATOR_VEHICLES.items() if symbol == "DAI")
    with pytest.raises(ValueError, match="address-symbol"):
        prepare_frame(frame)


def test_numeric_payload_canonicalization_discards_only_blas_noise() -> None:
    assert _finite_json(1.23456789012341) == _finite_json(1.23456789012349)
    assert _finite_json(1.2345678) != _finite_json(1.2345688)
    assert _finite_json(-0.0) == 0.0
    assert _serialized_p_value(1.7e-32) == 0.0
    assert _serialized_p_value(1.1e-12) == 1.1e-12


def test_routing_registry_propagates_to_python_and_sql_classifiers() -> None:
    dates = ["2021-09-15", *[date for date, _era, _source in ROUTING_ERA_CUTOFFS], "2022-11-18"]
    expected = [routing_era_for_date(date) for date in dates]
    relation = pa.Table.from_pydict({"position": list(range(len(dates))), "date": dates})
    connection = duckdb.connect()
    try:
        connection.register("dates", relation)
        actual = [row[0] for row in connection.execute(f"SELECT {routing_era_case_sql('date')} FROM dates ORDER BY position").fetchall()]
    finally:
        connection.close()
    assert actual == expected
