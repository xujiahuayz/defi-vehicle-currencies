from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ddvc.analysis.vehicle_rotation_composition import (
    vehicle_rotation_composition,
    vehicle_rotation_market_incidence_decomposition,
)
from scripts import run_vehicle_rotation_composition_e0 as runner


NATIVE = "0x0000000000000000000000000000000000000001"
STABLE = "0x0000000000000000000000000000000000000002"


def _choice(
    date: str,
    src: str,
    tgt: str,
    candidate_type: str,
    route_count: float,
    *,
    strict_count: float | None = None,
    value: float | None = None,
    scope: str = "single_venue",
    venue: str | None = None,
) -> dict[str, object]:
    if venue is None:
        venue = (
            "uniswap_v3>uniswap_v3"
            if scope == "single_venue"
            else "uniswap_v3>sushiswap_v2"
        )
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "candidate_address": NATIVE if candidate_type == "native" else STABLE,
        "candidate_type": candidate_type,
        "venue_sequence": venue,
        "integration_scope": scope,
        "route_count": route_count,
        "within_20pct_routes": route_count if strict_count is None else strict_count,
        "within_20pct_value_usd": route_count if value is None else value,
    }


def _cross_controls() -> list[dict[str, object]]:
    return [
        _choice("2024-01-01", "x", "y", "native", 10, scope="cross_venue"),
        _choice("2026-01-01", "x", "y", "native", 10, scope="cross_venue"),
    ]


def _four_term_choices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 80),
            _choice("2024-01-01", "a", "b", "stable", 20),
            _choice("2024-01-01", "e", "f", "native", 100),
            _choice("2026-01-01", "a", "b", "native", 50),
            _choice("2026-01-01", "a", "b", "stable", 50),
            _choice("2026-01-01", "c", "d", "stable", 100),
            *_cross_controls(),
        ]
    )


def _summary(
    decomposition: pd.DataFrame,
    metric: str,
    scope: str = "single_venue",
) -> pd.Series:
    return decomposition[
        decomposition["metric"].eq(metric)
        & decomposition["reporting_scope"].eq(scope)
    ].iloc[0]


def test_locked_four_term_identity_and_realised_composition_labels() -> None:
    pair_panel, decomposition, support = vehicle_rotation_composition(
        _four_term_choices()
    )
    count = _summary(decomposition, "count_share")
    assert count["baseline_stable_share"] == pytest.approx(0.1)
    assert count["comparison_stable_share"] == pytest.approx(0.75)
    assert count["total_change"] == pytest.approx(0.65)
    assert count["within_common"] == pytest.approx(0.15)
    assert count["common_pair_reweighting"] == pytest.approx(0.0)
    assert count["common_support_mass"] == pytest.approx(0.0)
    assert count["exclusive_pair_contribution"] == pytest.approx(0.5)
    assert count["identity_error"] == pytest.approx(0.0, abs=1e-12)
    assert count["formula_id"] == "midpoint_common_exclusive_support_v1"
    assert count["mechanism_status"] == "descriptive_realised_composition_noncausal"
    assert set(pair_panel["metric"]) == {
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    }
    membership = support[
        support["record_type"].eq("decomposition_pair_support")
        & support["metric"].eq("count_share")
        & support["reporting_scope"].eq("single_venue")
    ]
    assert dict(zip(membership["support_status"], membership["units"], strict=True)) == {
        "baseline_exclusive": 1,
        "common": 1,
        "comparison_exclusive": 1,
    }


def test_hand_calculated_fixture_activates_all_four_identity_terms() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 48),
            _choice("2024-01-01", "a", "b", "stable", 12),
            _choice("2024-01-01", "c", "d", "native", 16),
            _choice("2024-01-01", "c", "d", "stable", 24),
            _choice("2024-01-01", "e", "f", "native", 90),
            _choice("2024-01-01", "e", "f", "stable", 10),
            _choice("2026-01-01", "a", "b", "native", 15),
            _choice("2026-01-01", "a", "b", "stable", 15),
            _choice("2026-01-01", "c", "d", "native", 18),
            _choice("2026-01-01", "c", "d", "stable", 72),
            _choice("2026-01-01", "g", "h", "native", 3),
            _choice("2026-01-01", "g", "h", "stable", 27),
            *_cross_controls(),
        ]
    )
    _panel, decomposition, _support = vehicle_rotation_composition(choices)
    expected = {
        "baseline_stable_share": 0.23,
        "comparison_stable_share": 0.76,
        "total_change": 0.53,
        "within_common": 0.157625,
        "common_pair_reweighting": 0.079625,
        "common_support_mass": 0.01275,
        "exclusive_pair_contribution": 0.28,
        "identity_error": 0.0,
    }
    for metric in (
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    ):
        observed = _summary(decomposition, metric)
        for field, value in expected.items():
            assert observed[field] == pytest.approx(value, abs=1e-12)

    scaled = choices.sample(frac=1, random_state=9).reset_index(drop=True)
    for column in ("route_count", "within_20pct_routes", "within_20pct_value_usd"):
        scaled[column] *= 7
    _panel, scaled_decomposition, _support = vehicle_rotation_composition(scaled)
    for metric in (
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    ):
        observed = _summary(scaled_decomposition, metric)
        for field, value in expected.items():
            assert observed[field] == pytest.approx(value, abs=1e-12)


def test_zero_exclusive_normalization_retains_identity() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 8),
            _choice("2024-01-01", "a", "b", "stable", 2),
            _choice("2026-01-01", "a", "b", "native", 5),
            _choice("2026-01-01", "a", "b", "stable", 5),
            *_cross_controls(),
        ]
    )
    _panel, decomposition, _support = vehicle_rotation_composition(choices)
    count = _summary(decomposition, "count_share")
    assert count["E_baseline"] == pytest.approx(0.0)
    assert count["E_comparison"] == pytest.approx(0.0)
    assert count["S_E_baseline"] == pytest.approx(0.0)
    assert count["S_E_comparison"] == pytest.approx(0.0)
    assert bool(count["zero_exclusive_baseline_normalized"])
    assert bool(count["zero_exclusive_comparison_normalized"])
    assert count["support_and_exclusive_joint"] == pytest.approx(0.0)
    assert count["identity_error"] == pytest.approx(0.0, abs=1e-12)


def test_uses_only_month_days_observed_in_both_endpoint_years() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 1),
            _choice("2024-01-02", "a", "b", "stable", 1000),
            _choice("2024-07-01", "a", "b", "stable", 1000),
            _choice("2026-01-01", "a", "b", "stable", 1),
            _choice("2026-06-30", "a", "b", "native", 1000),
            *_cross_controls(),
        ]
    )
    pair_panel, decomposition, _support = vehicle_rotation_composition(choices)
    count = _summary(decomposition, "count_share")
    assert count["common_month_days"] == 1
    assert count["common_calendar_end"] == "01-01"
    assert count["baseline_stable_share"] == 0
    assert count["comparison_stable_share"] == 1
    assert set(pair_panel["month_day"]) == {"01-01"}


def test_support_is_measure_specific_and_never_inherits_count_mass() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 10, strict_count=0, value=0),
            _choice("2026-01-01", "a", "b", "stable", 10, strict_count=5, value=50),
            _choice("2024-01-01", "c", "d", "native", 4, strict_count=4, value=40),
            _choice("2026-01-01", "c", "d", "native", 4, strict_count=4, value=40),
            *_cross_controls(),
        ]
    )
    pair_panel, decomposition, support = vehicle_rotation_composition(choices)
    count_pairs = set(
        pair_panel.loc[pair_panel["metric"].eq("count_share"), ["src", "tgt"]]
        .itertuples(index=False, name=None)
    )
    strict_pairs = set(
        pair_panel.loc[
            pair_panel["metric"].eq("matched_strict_count_share"), ["src", "tgt"]
        ].itertuples(index=False, name=None)
    )
    assert ("a", "b") in count_pairs
    assert ("a", "b") not in strict_pairs
    strict_membership = support[
        support["record_type"].eq("decomposition_pair_support")
        & support["metric"].eq("matched_strict_count_share")
        & support["reporting_scope"].eq("single_venue")
    ]
    assert int(
        strict_membership.loc[
            strict_membership["support_status"].eq("comparison_exclusive"), "units"
        ].iloc[0]
    ) == 1
    strict = _summary(decomposition, "matched_strict_count_share")
    assert strict["source_column"] == "within_20pct_routes"


def test_pair_membership_is_assigned_after_scope_pooling() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 5),
            _choice(
                "2026-01-01", "a", "b", "stable", 5, scope="cross_venue"
            ),
            _choice("2024-01-01", "c", "d", "native", 2),
            _choice("2026-01-01", "c", "d", "native", 2),
            _choice("2024-01-01", "e", "f", "native", 2, scope="cross_venue"),
            _choice("2026-01-01", "e", "f", "native", 2, scope="cross_venue"),
        ]
    )
    _panel, _decomposition, support = vehicle_rotation_composition(choices)

    def membership(scope: str, status: str) -> int:
        row = support[
            support["record_type"].eq("decomposition_pair_support")
            & support["metric"].eq("count_share")
            & support["reporting_scope"].eq(scope)
            & support["support_status"].eq(status)
        ]
        return int(row["units"].iloc[0])

    assert membership("pooled", "common") == 3
    assert membership("single_venue", "baseline_exclusive") == 1
    assert membership("cross_venue", "comparison_exclusive") == 1


def test_decomposition_is_row_order_and_common_scale_invariant() -> None:
    choices = _four_term_choices()
    _panel, baseline, _support = vehicle_rotation_composition(choices)
    scaled = choices.sample(frac=1, random_state=19).reset_index(drop=True)
    for column in ("route_count", "within_20pct_routes", "within_20pct_value_usd"):
        scaled[column] *= 17
    _scaled_panel, observed, _scaled_support = vehicle_rotation_composition(scaled)
    columns = [
        "metric",
        "reporting_scope",
        "total_change",
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
        "identity_error",
    ]
    pd.testing.assert_frame_equal(
        baseline[columns], observed[columns], check_exact=False, atol=1e-12, rtol=1e-12
    )


def test_rejects_duplicate_release_keys_and_nonprimary_candidates() -> None:
    row = _choice("2024-01-01", "a", "b", "native", 1)
    comparison = _choice("2026-01-01", "a", "b", "stable", 1)
    with pytest.raises(ValueError, match="duplicate release keys"):
        vehicle_rotation_composition(pd.DataFrame([row, row, comparison]))
    invalid = dict(comparison)
    invalid["candidate_type"] = "other"
    with pytest.raises(ValueError, match="non-primary"):
        vehicle_rotation_composition(pd.DataFrame([row, invalid]))


def test_runner_requires_exact_d3_bound_endpoint_generation_and_receipt(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "data/processed/endpoint/current.json"
    relative = pointer.relative_to(tmp_path).as_posix()
    context = SimpleNamespace(
        d3_input_records={
            relative: {
                "path": relative,
                "release_generation": "a" * 64,
                "semantic_validation": {
                    "generation_id": "a" * 64,
                    "validator_fingerprint": "b" * 64,
                },
            }
        }
    )
    receipt = runner._expected_release_in_d3(context, pointer, root=tmp_path)
    assert receipt.generation_id == "a" * 64
    assert receipt.validator_fingerprint == "b" * 64
    context.d3_input_records[relative]["release_generation"] = "c" * 64
    with pytest.raises(ValueError, match="generation and receipt disagree"):
        runner._expected_release_in_d3(context, pointer, root=tmp_path)


def test_market_incidence_bridge_is_exact_and_support_is_classified() -> None:
    annual = pd.DataFrame(
        [
            (2024, "a", "b", 100, 50, 40, 10),
            (2026, "a", "b", 300, 100, 60, 40),
            (2024, "c", "d", 50, 40, 10, 30),
            (2026, "c", "d", 100, 20, 10, 10),
            (2024, "e", "f", 100, 20, 10, 10),
            (2026, "e", "f", 50, 0, 0, 0),
            (2026, "g", "h", 100, 20, 2, 18),
            (2024, "i", "j", 100, 0, 0, 0),
            (2026, "i", "j", 100, 10, 8, 2),
        ],
        columns=[
            "year",
            "src",
            "tgt",
            "market_route_count",
            "primary_choice_route_count",
            "native_choice_route_count",
            "stable_choice_route_count",
        ],
    )
    summary, support = vehicle_rotation_market_incidence_decomposition(annual)
    row = summary.iloc[0]
    assert row["identity_error"] == pytest.approx(0.0, abs=1e-12)
    assert row["total_change"] == pytest.approx(
        row["market_pair_support_bridge"]
        + row["vehicle_role_support_bridge"]
        + row["market_activity_reweighting"]
        + row["vehicle_incidence_reweighting"]
        + row["within_pair_stable_share"]
    )
    for term in (
        "market_pair_support_bridge",
        "vehicle_role_support_bridge",
        "market_activity_reweighting",
        "vehicle_incidence_reweighting",
        "within_pair_stable_share",
    ):
        assert abs(row[term]) > 1e-6
    comparison = support[support["endpoint_year"].eq(2026)].set_index(
        "support_status"
    )
    assert comparison.loc["market_pair_support_turnover", "primary_choice_mass"] == 20
    assert (
        comparison.loc[
            "vehicle_role_support_turnover_established_market", "primary_choice_mass"
        ]
        == 10
    )
    assert comparison.loc["common_vehicle_role", "primary_choice_mass"] == 120

    scaled = annual.sample(frac=1, random_state=14).reset_index(drop=True)
    for column in (
        "market_route_count",
        "primary_choice_route_count",
        "native_choice_route_count",
        "stable_choice_route_count",
    ):
        scaled[column] *= 9
    scaled_summary, scaled_support = vehicle_rotation_market_incidence_decomposition(
        scaled
    )
    pd.testing.assert_frame_equal(summary, scaled_summary, atol=1e-12, rtol=1e-12)
    pd.testing.assert_series_equal(
        support["primary_choice_mass_share"],
        scaled_support["primary_choice_mass_share"],
        check_names=False,
        atol=1e-12,
        rtol=1e-12,
    )
