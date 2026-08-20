from __future__ import annotations

import math

import pandas as pd

from scripts.analyze.run_exact_vehicle_frontier import (
    _clustered_mean,
    _holm,
    monthly_days,
    summarize,
    vehicle_class,
)


def test_monthly_calendar_is_bounded_and_complete() -> None:
    days = monthly_days()
    assert len(days) == 73
    assert days[0] == "20200615"
    assert days[-1] == "20260615"
    assert all(day.endswith("15") for day in days)


def test_vehicle_classes_keep_direct_native_and_stable_distinct() -> None:
    assert vehicle_class(None) == "direct"
    assert vehicle_class("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2") == "native"
    assert vehicle_class("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48") == "stable"


def test_holm_preserves_missing_inference_and_adjusts_finite_tests() -> None:
    adjusted = _holm([0.01, float("nan"), 0.04])
    assert adjusted[0] == 0.02
    assert math.isnan(adjusted[1])
    assert adjusted[2] == 0.04


def test_clustered_mean_requires_more_than_one_date() -> None:
    estimate, standard_error, p_value = _clustered_mean(
        pd.Series([1.0, 0.0]), pd.Series(["20210115", "20210115"])
    )
    assert math.isnan(estimate)
    assert math.isnan(standard_error)
    assert math.isnan(p_value)


def test_summary_reports_vehicle_reallocation_separately_from_route_gain() -> None:
    panel = pd.DataFrame(
        [
            {
                "day": "20210115",
                "year": 2021,
                "input_usd": 100.0,
                "within_20pct": True,
                "chosen_vehicle_type": "native",
                "public_vehicle_type": "stable",
                "public_path_regret_bps": 10.0,
                "direct_improvement_bps": 0.0,
                "within_reach_regret_bps": 2.0,
                "reach_increment_bps": 4.0,
                "vehicle_choice_increment_bps": 6.0,
                "public_gain_usd": 0.1,
            },
            {
                "day": "20210215",
                "year": 2021,
                "input_usd": 300.0,
                "within_20pct": True,
                "chosen_vehicle_type": "stable",
                "public_vehicle_type": "stable",
                "public_path_regret_bps": 0.0,
                "direct_improvement_bps": 0.0,
                "within_reach_regret_bps": 0.0,
                "reach_increment_bps": 0.0,
                "vehicle_choice_increment_bps": 0.0,
                "public_gain_usd": 0.0,
            },
        ]
    )
    result = summarize(panel)
    pooled = result[
        result["record_type"].eq("frontier_summary")
        & result["scope"].eq("pooled")
        & result["label"].eq("all")
    ].iloc[0]
    assert pooled["gain_over_1bp_share"] == 0.5
    assert pooled["reach_increment_over_1bp_share"] == 0.5
    assert pooled["vehicle_choice_increment_over_1bp_share"] == 0.5
    route = result[
        result["record_type"].eq("stable_share_inference")
        & result["scope"].eq("all")
        & result["label"].eq("route")
    ].iloc[0]
    value = result[
        result["record_type"].eq("stable_share_inference")
        & result["scope"].eq("all")
        & result["label"].eq("input_value")
    ].iloc[0]
    assert route["change_pp"] == 50.0
    assert value["change_pp"] == 25.0
