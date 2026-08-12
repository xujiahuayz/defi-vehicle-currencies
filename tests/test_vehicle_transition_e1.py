from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ddvc.asset_types import NATIVE, STABLE
from ddvc.analysis.vehicle_transition_e1 import (
    EXPECTED_E1_DESIGN_HASH,
    IDENTITY_TOLERANCE,
    INTEGRATION_SCOPES,
    build_e1_outputs,
    decompose_measure,
    load_registered_e1_design,
    pair_panel_for_measure,
    validate_e1_outputs,
)
from ddvc.endpoint_candidate_composition import (
    endpoint_candidate_composition_for_day,
    finalize_endpoint_candidate_composition,
)
from ddvc.endpoint_candidate_composition_release import (
    publish_endpoint_candidate_composition_release,
)
from ddvc.model_registry import canonical_hash
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, verify
from scripts.run_vehicle_transition_e1 import (
    OUTPUT_FILENAMES,
    publish_e1_release,
    resolve_e1_release,
    run_vehicle_transition_e1,
)


SPECIFICATION = REPO_ROOT / "docs" / "specification-lock.json"
MONTH_DAYS = ("01-01", "01-02", "01-03", "01-04")
PAIRS = (("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"))
WETH = next(address for address, symbol in NATIVE.items() if symbol == "WETH")
USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")


def _choices(*, one_sided_strict_value: bool = False, exclusive_pair: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in (2024, 2026):
        pairs = list(PAIRS)
        if exclusive_pair:
            pairs.append(("only-2024", "sink") if year == 2024 else ("only-2026", "sink"))
        for day_index, month_day in enumerate(MONTH_DAYS):
            for pair_index, (src, tgt) in enumerate(pairs):
                for scope_index, scope in enumerate(INTEGRATION_SCOPES):
                    denominator = 100 + 10 * pair_index + 2 * day_index + scope_index
                    stable = 20 + 4 * pair_index + day_index + scope_index
                    if year == 2026:
                        stable += 8 + 2 * (pair_index % 2) - (day_index % 2)
                    for candidate_type, mass in (
                        ("stable", stable),
                        ("native", denominator - stable),
                    ):
                        strict_value = float(mass) * 100.0 * (
                            1 + 0.03 * pair_index + 0.01 * day_index
                        )
                        if (
                            one_sided_strict_value
                            and year == 2026
                            and month_day == "01-04"
                            and (src, tgt) == PAIRS[0]
                            and scope == "single_venue"
                        ):
                            strict_value = 0.0
                        rows.append(
                            {
                                "src": src,
                                "tgt": tgt,
                                "date": f"{year}-{month_day}",
                                "integration_scope": scope,
                                "candidate_type": candidate_type,
                                "route_count": mass,
                                "within_20pct_routes": max(mass - 2, 0),
                                "within_20pct_value_usd": strict_value,
                            }
                        )
    return pd.DataFrame.from_records(rows)


def _calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.to_datetime(
            [
                f"{year}-{month_day}"
                for year in (2024, 2026)
                for month_day in MONTH_DAYS
            ]
        )
    )


def _contract():
    return load_registered_e1_design(SPECIFICATION)[1]


def test_registered_e1_build_fits_exact_three_coefficient_family_and_nine_decompositions() -> None:
    measures = _contract()
    outputs = build_e1_outputs(
        _choices(exclusive_pair=True),
        _calendar(),
        measures,
        endpoint_release_generation="endpoint-generation",
    )
    validate_e1_outputs(outputs, measures=measures)
    assert outputs.pair_panel["measure_id"].tolist() == [
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    ]
    assert len(outputs.pair_panel) == 3
    assert len(outputs.pair_decomposition) == 9
    assert len(outputs.pair_support) == 12
    assert outputs.pair_panel["p_value_holm"].ge(outputs.pair_panel["p_value"] - 1e-15).all()
    assert outputs.pair_panel["pair_clusters"].eq(len(PAIRS)).all()
    assert outputs.pair_panel["date_clusters"].eq(8).all()
    assert outputs.pair_decomposition["closure_error"].abs().le(IDENTITY_TOLERANCE).all()


def test_measure_support_is_not_inherited_from_count_panel() -> None:
    measures = {measure.measure_id: measure for measure in _contract()}
    choices = _choices(one_sided_strict_value=True)
    count, count_support = pair_panel_for_measure(choices, measures["count_share"])
    strict, strict_support = pair_panel_for_measure(
        choices,
        measures["strict_intermediation_value_share"],
    )
    assert len(strict) == len(count) - 2
    assert strict_support["common_support_cells"] == count_support["common_support_cells"] - 1
    rejected = strict[
        strict["src"].eq(PAIRS[0][0])
        & strict["tgt"].eq(PAIRS[0][1])
        & strict["month_day"].eq("01-04")
        & strict["integration_scope"].eq("single_venue")
    ]
    assert rejected.empty


def test_four_term_decomposition_handles_zero_exclusive_mass_and_exact_closure() -> None:
    measure = _contract()[0]
    without_exclusive, support = decompose_measure(
        _choices(),
        _calendar(),
        measure,
        integration_scope="pooled",
        endpoint_release_generation="endpoint-generation",
    )
    assert support["baseline_zero_exclusive_mass"] is True
    assert support["comparison_zero_exclusive_mass"] is True
    assert abs(without_exclusive["exclusive_pair_contribution"]) <= 1e-15
    assert abs(without_exclusive["reconstructed_delta"] - without_exclusive["delta_total"]) <= IDENTITY_TOLERANCE
    with_exclusive, support = decompose_measure(
        _choices(exclusive_pair=True),
        _calendar(),
        measure,
        integration_scope="pooled",
        endpoint_release_generation="endpoint-generation",
    )
    assert support["baseline_exclusive_pair_count"] == 1
    assert support["comparison_exclusive_pair_count"] == 1
    assert abs(with_exclusive["reconstructed_delta"] - with_exclusive["delta_total"]) <= IDENTITY_TOLERANCE


def test_registered_design_rejects_coherently_rehashed_nested_drift(tmp_path: Path) -> None:
    payload = json.loads(SPECIFICATION.read_text(encoding="utf-8"))
    claim = next(claim for claim in payload["claims"] if claim["id"] == "vehicle_transition")
    claim["e1_design"]["pair_panel"]["clusters"] = ["calendar_date"]
    claim["e1_design_hash"] = canonical_hash(claim["e1_design"])
    payload["lock_hash"] = canonical_hash({key: value for key, value in payload.items() if key != "lock_hash"})
    changed = tmp_path / "specification.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="design hash"):
        load_registered_e1_design(changed)


def test_three_outputs_publish_as_one_provenance_bound_marker_release(tmp_path: Path) -> None:
    measures = _contract()
    outputs = build_e1_outputs(
        _choices(exclusive_pair=True),
        _calendar(),
        measures,
        endpoint_release_generation="endpoint-generation",
    )
    pointer = tmp_path / "release" / "current.json"
    release = publish_e1_release(
        outputs,
        measures=measures,
        inputs=[SPECIFICATION],
        pointer_path=pointer,
    )
    assert set(release.artifacts) == set(OUTPUT_FILENAMES)
    assert pointer.is_file()
    assert resolve_e1_release(pointer).generation_id == release.generation_id
    for name, path in release.artifacts.items():
        assert path.name == OUTPUT_FILENAMES[name]
        assert verify(path)["status"] == "ok"
        provenance = json.loads(sidecar_path(path).read_text(encoding="utf-8"))
        assert provenance["inputs"][0]["path"].endswith("docs/specification-lock.json")


def test_output_validator_rejects_holm_and_decomposition_tampering() -> None:
    measures = _contract()
    outputs = build_e1_outputs(
        _choices(exclusive_pair=True),
        _calendar(),
        measures,
        endpoint_release_generation="endpoint-generation",
    )
    tampered_pair = outputs.pair_panel.copy()
    tampered_pair.loc[0, "p_value_holm"] = tampered_pair.loc[0, "p_value"] / 2
    with pytest.raises(ValueError, match="Holm"):
        validate_e1_outputs(
            type(outputs)(tampered_pair, outputs.pair_decomposition, outputs.pair_support),
            measures=measures,
        )
    tampered_decomposition = outputs.pair_decomposition.copy()
    tampered_decomposition.loc[0, "within_common"] += 1e-6
    with pytest.raises(ValueError, match="close"):
        validate_e1_outputs(
            type(outputs)(outputs.pair_panel, tampered_decomposition, outputs.pair_support),
            measures=measures,
        )


def _endpoint_pointer(tmp_path: Path) -> Path:
    daily = []
    for year in (2024, 2026):
        for day_index, month_day in enumerate(MONTH_DAYS):
            date = pd.Timestamp(f"{year}-{month_day}", tz="UTC")
            timestamp = int(date.timestamp())
            legs: list[dict[str, object]] = []
            for pair_index in range(len(PAIRS)):
                src = f"0x{100 + 2 * pair_index:040x}"
                tgt = f"0x{101 + 2 * pair_index:040x}"
                for scope_index, scope in enumerate(INTEGRATION_SCOPES):
                    stable_routes = 6 + pair_index + day_index + (3 if year == 2026 else 0)
                    native_routes = 12 + pair_index - (1 if year == 2026 else 0)
                    for candidate_type, candidate, route_count in (
                        ("stable", USDC, stable_routes),
                        ("native", WETH, native_routes),
                    ):
                        for route_index in range(route_count):
                            tx_hash = (
                                f"{year}-{day_index}-{pair_index}-{scope_index}-"
                                f"{candidate_type}-{route_index}"
                            )
                            amount = 100.0 + 3 * pair_index + day_index
                            legs.extend(
                                [
                                    {
                                        "tx_hash": tx_hash,
                                        "component_id": 0,
                                        "route_class": "coherent",
                                        "source": "uniswap_v2",
                                        "token_in": src,
                                        "token_out": candidate,
                                        "amount_usd": amount,
                                        "log_index": 0,
                                        "tin_role": "source",
                                        "tout_role": "sink",
                                        "timestamp_utc": timestamp,
                                    },
                                    {
                                        "tx_hash": tx_hash,
                                        "component_id": 0,
                                        "route_class": "coherent",
                                        "source": (
                                            "uniswap_v2"
                                            if scope == "single_venue"
                                            else "sushiswap_v2"
                                        ),
                                        "token_in": candidate,
                                        "token_out": tgt,
                                        "amount_usd": amount,
                                        "log_index": 1,
                                        "tin_role": "source",
                                        "tout_role": "sink",
                                        "timestamp_utc": timestamp,
                                    },
                                ]
                            )
            daily.append(
                endpoint_candidate_composition_for_day(
                    pd.DataFrame.from_records(legs),
                    f"{year}{month_day.replace('-', '')}",
                )
            )
    bundle = finalize_endpoint_candidate_composition(daily)
    pointer = tmp_path / "endpoint-release" / "current.json"
    tables = {
        "choices": bundle.choices,
        "choice_audit": bundle.choice_audit,
        "pair_support": bundle.pair_support,
        "exclusions": bundle.exclusions,
    }
    publish_endpoint_candidate_composition_release(
        writers={
            name: (lambda path, frame=frame: frame.to_parquet(path, index=False))
            for name, frame in tables.items()
        },
        row_counts={name: len(frame) for name, frame in tables.items()},
        code_sources=["tests/test_vehicle_transition_e1.py"],
        inputs=[SPECIFICATION],
        notes="synthetic exact four-table E1 input",
        preinstall_validator=lambda _path: None,
        pointer_path=pointer,
    )
    return pointer


def test_runner_consumes_one_four_table_pointer_and_reopens_one_atomic_output_release(
    tmp_path: Path,
) -> None:
    endpoint_pointer = _endpoint_pointer(tmp_path)
    output_pointer = tmp_path / "e1-release" / "current.json"
    release = run_vehicle_transition_e1(
        release_pointer=endpoint_pointer,
        specification_path=SPECIFICATION,
        output_pointer=output_pointer,
    )
    assert release.pointer_path == output_pointer
    assert resolve_e1_release(output_pointer).generation_id == release.generation_id
    assert len(pd.read_json(release.artifacts["pair_panel"], lines=True)) == 3
    assert len(pd.read_json(release.artifacts["pair_decomposition"], lines=True)) == 9
    assert len(pd.read_json(release.artifacts["pair_support"], lines=True)) == 12
