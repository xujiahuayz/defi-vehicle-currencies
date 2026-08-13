from __future__ import annotations

import pandas as pd
import pytest

from ddvc.analysis.vehicle_rotation_composition import vehicle_rotation_composition


NATIVE = "0x0000000000000000000000000000000000000001"
STABLE = "0x0000000000000000000000000000000000000002"


def _choice(
    date: str,
    src: str,
    tgt: str,
    candidate_type: str,
    route_count: float,
    *,
    value: float | None = None,
    reach: str = "uniswap_v3>uniswap_v3",
    protocol: str = "uniswap>uniswap",
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "candidate_address": NATIVE if candidate_type == "native" else STABLE,
        "candidate_type": candidate_type,
        "venue_sequence": reach,
        "integration_scope": "single_venue" if reach.split(">", 1)[0] == reach.split(">", 1)[1] else "cross_venue",
        "protocol_sequence": protocol,
        "route_count": route_count,
        "within_20pct_value_usd": route_count if value is None else value,
    }


def test_exactly_decomposes_within_cell_entry_and_exit() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 80),
            _choice("2024-01-01", "a", "b", "stable", 20),
            _choice("2024-01-01", "e", "f", "native", 100),
            _choice("2026-01-01", "a", "b", "native", 50),
            _choice("2026-01-01", "a", "b", "stable", 50),
            _choice("2026-01-01", "c", "d", "stable", 100),
        ]
    )
    detail, decomposition, support = vehicle_rotation_composition(choices)
    count = decomposition[decomposition["metric"].eq("route_count")].iloc[0]
    assert count["baseline_stable_share"] == pytest.approx(0.1)
    assert count["comparison_stable_share"] == pytest.approx(0.75)
    assert count["total_change"] == pytest.approx(0.65)
    assert count["within_cell_contribution"] == pytest.approx(0.15)
    assert count["common_cell_reweighting_contribution"] == pytest.approx(0.0)
    assert count["entry_contribution"] == pytest.approx(0.5)
    assert count["exit_contribution"] == pytest.approx(0.0)
    assert count["identity_error"] == pytest.approx(0.0)
    assert count["estimand_scope"] == "fixed_pair_reach_design_pre_frontier"
    assert count["omitted_dimensions"] == "notional_bin|exact_search_efficiency_state"
    count_detail = detail[detail["metric"].eq("route_count")]
    assert set(count_detail["support_status"]) == {"common", "entry", "exit"}
    opportunity = support[
        support["record_type"].eq("opportunity_cell_support")
        & support["metric"].eq("route_count")
    ]
    assert dict(zip(opportunity["support_status"], opportunity["units"], strict=True)) == {
        "common": 1,
        "entry": 1,
        "exit": 1,
    }


def test_uses_comparison_year_calendar_support_and_excludes_leap_day() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 1),
            _choice("2024-02-29", "a", "b", "stable", 1000),
            _choice("2024-07-01", "a", "b", "stable", 1000),
            _choice("2026-01-01", "a", "b", "stable", 1),
            _choice("2026-06-30", "a", "b", "stable", 1),
        ]
    )
    _detail, decomposition, _support = vehicle_rotation_composition(choices)
    count = decomposition[decomposition["metric"].eq("route_count")].iloc[0]
    assert count["common_calendar_end"] == "06-30"
    assert count["baseline_stable_share"] == 0
    assert count["comparison_stable_share"] == 1


def test_reports_pair_candidate_and_reach_design_support_separately() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 2),
            _choice(
                "2026-01-01",
                "a",
                "b",
                "stable",
                3,
                reach="uniswap_v3>sushiswap_v2",
                protocol="uniswap>sushiswap",
            ),
        ]
    )
    _detail, _decomposition, support = vehicle_rotation_composition(choices)
    assert set(support["unit"]) == {
        "ordered_endpoint_reach_design_cell",
        "ordered_endpoint_reach_design_cell_year",
        "ordered_endpoint_pair",
        "candidate_address",
        "venue_reach_design",
    }
    pair = support[support["unit"].eq("ordered_endpoint_pair")]
    assert int(pair.loc[pair["support_status"].eq("common"), "units"].iloc[0]) == 1
    candidates = support[support["unit"].eq("candidate_address")]
    assert int(candidates.loc[candidates["support_status"].eq("entry"), "units"].iloc[0]) == 1
    assert int(candidates.loc[candidates["support_status"].eq("exit"), "units"].iloc[0]) == 1


def test_strict_value_decomposition_excludes_and_reports_zero_support_cells() -> None:
    choices = pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 2, value=0),
            _choice("2024-01-01", "c", "d", "stable", 2, value=4),
            _choice("2026-01-01", "a", "b", "stable", 2, value=0),
            _choice("2026-01-01", "c", "d", "stable", 2, value=6),
        ]
    )
    _detail, decomposition, support = vehicle_rotation_composition(choices)
    strict = decomposition[decomposition["metric"].eq("strict_value")].iloc[0]
    assert strict["zero_denominator_cell_years"] == 2
    assert strict["baseline_stable_share"] == 1
    assert strict["comparison_stable_share"] == 1
    zero = support[
        support["record_type"].eq("metric_zero_denominator_support")
        & support["metric"].eq("strict_value")
    ].iloc[0]
    assert zero["units"] == 2


def test_rejects_duplicate_release_keys_and_nonprimary_candidates() -> None:
    row = _choice("2024-01-01", "a", "b", "native", 1)
    comparison = _choice("2026-01-01", "a", "b", "stable", 1)
    with pytest.raises(ValueError, match="duplicate release keys"):
        vehicle_rotation_composition(pd.DataFrame([row, row, comparison]))
    invalid = dict(comparison)
    invalid["candidate_type"] = "other"
    with pytest.raises(ValueError, match="non-primary"):
        vehicle_rotation_composition(pd.DataFrame([row, invalid]))
