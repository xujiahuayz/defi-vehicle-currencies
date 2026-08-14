from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_vehicle_transition_pair_deck_values import (
    render_pair_decomposition_deck_values,
)


ROOT = Path(__file__).resolve().parents[1]
SIGNED_TEXT_MACRO = re.compile(
    r"\\newcommand\{\\(?P<name>[^}]+)\}\{(?P<value>[+-]\d)"
)


def test_audience_facing_deck_macros_use_math_signs() -> None:
    defects: list[str] = []
    for path in sorted((ROOT / "output" / "exhibits").glob("*_deck_values.tex")):
        for match in SIGNED_TEXT_MACRO.finditer(path.read_text(encoding="utf-8")):
            if "Raw" not in match.group("name"):
                defects.append(f"{path.name}:{match.group('name')}")
    assert defects == []


def _row(metric: str, scope: str, scale: float = 1.0) -> dict[str, object]:
    base = 0.20
    terms = {
        "within_common": -0.001,
        "common_pair_reweighting": 0.08 * scale,
        "common_support_mass": -0.005,
        "exclusive_pair_contribution": 0.176,
    }
    total = sum(terms.values())
    return {
        "metric": metric,
        "reporting_scope": scope,
        "baseline_year": 2024,
        "comparison_year": 2026,
        "common_calendar_end": "06-30",
        "common_month_days": 181,
        "formula_id": "midpoint_common_exclusive_support_v1",
        "mechanism_status": "descriptive_realised_composition_noncausal",
        "baseline_stable_share": base,
        "comparison_stable_share": base + total,
        "total_change": total,
        "support_and_exclusive_joint": (
            terms["common_support_mass"] + terms["exclusive_pair_contribution"]
        ),
        "identity_error": 0.0,
        **terms,
    }


def _decomposition() -> pd.DataFrame:
    rows = [
            _row(metric, scope, scale=1 + index / 10)
            for metric in ("count_share", "strict_intermediation_value_share")
            for index, scope in enumerate(("pooled", "single_venue", "cross_venue"))
    ]
    market_terms = {
        "market_pair_support_bridge": 0.10,
        "vehicle_role_support_bridge": -0.004,
        "market_activity_reweighting": 0.08,
        "vehicle_incidence_reweighting": 0.07,
        "within_pair_stable_share": 0.014,
    }
    common_role = sum(
        market_terms[column]
        for column in (
            "market_activity_reweighting",
            "vehicle_incidence_reweighting",
            "within_pair_stable_share",
        )
    )
    established = market_terms["vehicle_role_support_bridge"] + common_role
    total = sum(market_terms.values())
    rows.append(
        {
            "metric": "count_share",
            "reporting_scope": "pooled",
            "baseline_year": 2024,
            "comparison_year": 2026,
            "formula_id": "shapley_market_incidence_stable_bridge_v1",
            "mechanism_status": (
                "descriptive_observed_activity_and_realised_incidence_noncausal"
            ),
            "baseline_stable_share": 0.20,
            "comparison_stable_share": 0.20 + total,
            "total_change": total,
            "established_market_baseline_stable_share": 0.25,
            "established_market_comparison_stable_share": 0.25 + established,
            "established_market_total_change": established,
            "common_role_total_change": common_role,
            "identity_error": 0.0,
            **market_terms,
        }
    )
    return pd.DataFrame(rows)


def _fixed_effects() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "count_share",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "estimator_id": (
                    "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
                ),
                "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
                "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
                "estimand_scope": "common_pair_month_day_realised_integration_scope",
                "coefficient": 0.00224,
                "standard_error": 0.00764,
                "confidence_interval_lower": -0.01278,
                "confidence_interval_upper": 0.01726,
                "p_value_holm": 1.0,
                "observations": 188_520,
                "fixed_effect_cells": 94_260,
                "ordered_pair_clusters": 5_432,
                "calendar_date_clusters": 362,
            },
            {
                "metric": "strict_intermediation_value_share",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "estimator_id": (
                    "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
                ),
                "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
                "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
                "estimand_scope": "common_pair_month_day_realised_integration_scope",
                "coefficient": -0.01346,
                "standard_error": 0.02188,
                "confidence_interval_lower": -0.05649,
                "confidence_interval_upper": 0.02957,
                "p_value_holm": 1.0,
                "observations": 182_834,
                "fixed_effect_cells": 91_417,
                "ordered_pair_clusters": 5_278,
                "calendar_date_clusters": 362,
            },
        ]
    )


def _usdt_integration() -> pd.DataFrame:
    rows = []
    for weighting, support, total, within, between in (
        ("episode", "all_routes", 0.095, 0.089, 0.006),
        ("value", "within_20pct", 0.313, 0.268, 0.045),
    ):
        rows.append(
            {
                "record_type": "midpoint_decomposition",
                "focal_symbol": "USDT",
                "comparison_components": "native+USDC+USDT",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "weighting": weighting,
                "value_support": support,
                "total_usdt_share_change": total,
                "within_scope_change": within,
                "between_scope_composition_change": between,
                "within_scope_share_of_change": within / total,
                "between_scope_share_of_change": between / total,
                "identity_residual": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_renderer_emits_complete_display_and_coordinate_macros() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration()
    )
    for macro in (
        "PairPooledBase",
        "PairPooledEnd",
        "PairPooledTotal",
        "PairPooledReweight",
        "PairPooledSupportMass",
        "PairPooledExclusive",
        "PairPooledWithin",
        "PairPooledBaseRawPct",
        "PairPooledEndRawPct",
        "PairPooledReweightRawPP",
        "PairPooledSupportMassRawPP",
        "PairPooledExclusiveRawPP",
        "PairPooledWithinRawPP",
        "PairSingleTotal",
        "PairSingleWithin",
        "PairCrossTotal",
        "PairCrossWithin",
        "PairValueTotal",
        "PairValueWithin",
        "PairValueReweight",
        "PairValueSupportMass",
        "PairValueExclusive",
        "MarketBridgeBase",
        "MarketBridgeEnd",
        "MarketBridgeTotal",
        "MarketSupportBridge",
        "VehicleRoleSupportBridge",
        "MarketActivityReweight",
        "VehicleIncidenceReweight",
        "WithinPairStableShare",
        "ObservedBothYearsBase",
        "ObservedBothYearsEnd",
        "ObservedBothYearsTotal",
        "CommonRoleTotal",
        "PairActivityTotal",
        "VehicleUseNet",
        "PairAndVehicleTotal",
        "PairAndVehicleShare",
        "MarketBridgeBaseRawPct",
        "MarketSupportBridgeRawPP",
        "VehicleRoleSupportBridgeRawPP",
        "MarketActivityReweightRawPP",
        "VehicleIncidenceReweightRawPP",
        "WithinPairStableShareRawPP",
        "PairActivityTotalRawPP",
        "VehicleUseNetRawPP",
        "PairAndVehicleTotalRawPP",
        "MatchedMarketCountChange",
        "MatchedMarketCountSE",
        "MatchedMarketCountCILower",
        "MatchedMarketCountCIUpper",
        "MatchedMarketCountChangeRawPP",
        "MatchedMarketCountCILowerRawPP",
        "MatchedMarketCountCIUpperRawPP",
        "MatchedMarketValueChange",
        "MatchedMarketValueSE",
        "MatchedMarketValueCILower",
        "MatchedMarketValueCIUpper",
        "USDTVenueMixCountShare",
        "USDTVenueWithinCountShare",
        "USDTVenueMixValueShare",
        "USDTVenueWithinValueShare",
    ):
        assert f"\\newcommand{{\\{macro}}}" in rendered
    assert "\\newcommand{\\PairPooledWithin}{$-0.1$ pp}" in rendered
    assert "\\newcommand{\\PairPooledExclusive}{$+17.6$ pp}" in rendered
    assert "\\newcommand{\\PairActivityTotal}{$+18.0$ pp}" in rendered
    assert "\\newcommand{\\VehicleUseNet}{$+6.6$ pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleTotal}{$+24.6$ pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleShare}{94.6\\%}" in rendered
    assert "\\newcommand{\\MatchedMarketCountChange}{$+0.2$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountSE}{$0.8$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountCILower}{$-1.3$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountCIUpper}{$+1.7$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueChange}{$-1.3$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueSE}{$2.2$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueCILower}{$-5.6$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueCIUpper}{$+3.0$ pp}" in rendered
    assert "\\newcommand{\\USDTVenueMixCountShare}{6.3\\%}" in rendered
    assert "\\newcommand{\\USDTVenueWithinCountShare}{93.7\\%}" in rendered
    assert "\\newcommand{\\USDTVenueMixValueShare}{14.4\\%}" in rendered
    assert "\\newcommand{\\USDTVenueWithinValueShare}{85.6\\%}" in rendered
    assert "generation" not in rendered.lower()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(frame.index[-1]), "exactly one"),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "exactly one",
        ),
        (
            lambda frame: frame.assign(
                identity_error=frame["identity_error"].where(frame.index != 0, 1e-6)
            ),
            "identity error",
        ),
        (
            lambda frame: frame.assign(
                support_and_exclusive_joint=frame["support_and_exclusive_joint"].where(
                    frame.index != 0, 0.0
                )
            ),
            "joint support term",
        ),
    ],
)
def test_renderer_fails_closed_on_incomplete_or_inconsistent_accounting(
    mutation, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        render_pair_decomposition_deck_values(
            mutation(_decomposition()), _fixed_effects(), _usdt_integration()
        )


def test_renderer_fails_closed_when_market_incidence_bridge_is_inconsistent() -> None:
    frame = _decomposition()
    market = frame["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
    frame.loc[market, "market_activity_reweighting"] += 0.01
    with pytest.raises(ValueError, match="total change"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration()
        )


def test_renderer_fails_closed_on_wrong_matched_market_scope() -> None:
    fixed_effects = _fixed_effects()
    fixed_effects.loc[0, "estimand_scope"] = "wrong_scope"
    with pytest.raises(ValueError, match="comparison set"):
        render_pair_decomposition_deck_values(
            _decomposition(), fixed_effects, _usdt_integration()
        )
