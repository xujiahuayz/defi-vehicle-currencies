from __future__ import annotations

import pandas as pd
import pytest

from scripts.build_vehicle_transition_pair_deck_values import (
    render_pair_decomposition_deck_values,
)


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


def test_renderer_emits_complete_display_and_coordinate_macros() -> None:
    rendered = render_pair_decomposition_deck_values(_decomposition())
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
    ):
        assert f"\\newcommand{{\\{macro}}}" in rendered
    assert "\\newcommand{\\PairPooledWithin}{-0.1\\,pp}" in rendered
    assert "\\newcommand{\\PairPooledExclusive}{+17.6\\,pp}" in rendered
    assert "\\newcommand{\\PairActivityTotal}{+18.0\\,pp}" in rendered
    assert "\\newcommand{\\VehicleUseNet}{+6.6\\,pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleTotal}{+24.6\\,pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleShare}{94.6\\%}" in rendered
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
        render_pair_decomposition_deck_values(mutation(_decomposition()))


def test_renderer_fails_closed_when_market_incidence_bridge_is_inconsistent() -> None:
    frame = _decomposition()
    market = frame["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
    frame.loc[market, "market_activity_reweighting"] += 0.01
    with pytest.raises(ValueError, match="total change"):
        render_pair_decomposition_deck_values(frame)
