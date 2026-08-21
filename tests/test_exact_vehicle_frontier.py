from __future__ import annotations

import math

import pandas as pd

from scripts.analyze.run_exact_vehicle_frontier import (
    _path_fields,
    _clustered_mean,
    _holm,
    best_family_path,
    monthly_days,
    summarize,
    summarize_support,
    vehicle_class,
)
from ddvc.pricing.path_frontier import LegQuote, PathQuote


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


def test_family_quote_is_independent_of_the_executed_vehicle() -> None:
    outputs = {
        ("a", "native"): 80.0,
        ("native", "b"): 70.0,
        ("a", "stable1"): 90.0,
        ("stable1", "b"): 91.0,
        ("a", "stable2"): 95.0,
        ("stable2", "b"): 92.0,
    }

    def quote_legs(token_in: str, token_out: str, amount_in: float):
        amount_out = outputs.get((token_in, token_out))
        if amount_out is None:
            return []
        return [LegQuote(amount_out, "venue", "pool", 0.01)]

    native = best_family_path(
        "a", "b", ("native",), 100.0, quote_legs=quote_legs
    )
    stable = best_family_path(
        "a", "b", ("stable1", "stable2"), 100.0, quote_legs=quote_legs
    )
    assert native is not None and native.vehicle == "native"
    assert stable is not None and stable.vehicle == "stable2"
    assert stable.amount_out == 92.0


def test_family_quote_fields_include_maximum_leg_price_impact() -> None:
    quote = PathQuote(
        amount_out=95.0,
        vehicle="stable",
        venues=("uniswap_v2", "uniswap_v3"),
        pools=("pool-a", "pool-b"),
        price_impacts=(0.01, 0.035),
    )
    fields = _path_fields("stable", quote)
    assert fields["stable_public_max_leg_price_impact"] == 0.035
    assert _path_fields("stable", None)[
        "stable_public_max_leg_price_impact"
    ] is None


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
                "chosen_max_price_impact": 0.01,
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
                "chosen_max_price_impact": 0.01,
            },
            {
                "day": "20210315",
                "year": 2021,
                "input_usd": 100.0,
                "within_20pct": True,
                "chosen_vehicle_type": "native",
                "public_vehicle_type": "stable",
                "public_path_regret_bps": 0.5,
                "direct_improvement_bps": 0.0,
                "within_reach_regret_bps": 0.0,
                "reach_increment_bps": 0.0,
                "vehicle_choice_increment_bps": 0.5,
                "public_gain_usd": 0.005,
                "chosen_max_price_impact": 0.01,
            },
        ]
    )
    result = summarize(panel)
    pooled = result[
        result["record_type"].eq("frontier_summary")
        & result["scope"].eq("pooled")
        & result["label"].eq("all")
    ].iloc[0]
    assert pooled["gain_over_1bp_share"] == 1 / 3
    assert pooled["public_stable_share"] == 2 / 3
    assert pooled["reach_increment_over_1bp_share"] == 1 / 3
    assert pooled["vehicle_choice_increment_over_1bp_share"] == 1 / 3
    common = result[
        result["record_type"].eq("frontier_summary")
        & result["scope"].eq("pooled")
        & result["label"].eq("common_support")
    ].iloc[0]
    assert common["routes"] == 3
    assert "aggregate_gain_usd" not in result.columns
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
    assert math.isclose(route["change_pp"], 100 / 3)
    assert value["change_pp"] == 20.0


def test_support_summary_keeps_market_reach_and_reproduction_distinct() -> None:
    support = pd.DataFrame(
        [
            {
                "day": "20210115",
                "linear_routes": 100,
                "exact_venue_routes": 80,
                "mapped_routes": 75,
                "scored_routes": 70,
            },
            {
                "day": "20220115",
                "linear_routes": 200,
                "exact_venue_routes": 100,
                "mapped_routes": 90,
                "scored_routes": 81,
            },
        ]
    )
    pooled = summarize_support(support).query("label == 'pooled'").iloc[0]
    assert pooled["exact_venue_share"] == 0.6
    assert pooled["mapping_share"] == 165 / 180
    assert pooled["chosen_reproduction_share"] == 151 / 165
