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


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
UNLABELLED = "0x" + "ab" * 20


def _contribution(
    component: str,
    src: str,
    tgt: str,
    contribution_pp: float,
    *,
    metric: str = "count_share",
    stable_baseline: float = 0.0,
    stable_comparison: float = 1.0,
    weight_baseline: float = 0.004,
    weight_comparison: float = 0.045,
    routes_baseline: float = 7_447.0,
    routes_comparison: float = 54_112.0,
) -> dict[str, object]:
    return {
        "metric": metric,
        "reporting_scope": "pooled",
        "baseline_year": 2024,
        "comparison_year": 2026,
        "src": src,
        "tgt": tgt,
        "stable_share_baseline": stable_baseline,
        "stable_share_comparison": stable_comparison,
        "pair_weight_baseline": weight_baseline,
        "pair_weight_comparison": weight_comparison,
        "denominator_baseline": routes_baseline,
        "denominator_comparison": routes_comparison,
        "contribution_component": component,
        "contribution_pp": contribution_pp,
        "aggregate_total_change": 0.25,
        "allocation_scope": "pair_level_excludes_common_support_mass",
        "mechanism_status": "descriptive_pair_contribution_noncausal",
    }


def _contributions() -> pd.DataFrame:
    """Reproduce the aggregate terms of `_row` from named and unlabelled pairs.

    `_row` sets within_common to -0.1 pp, common_pair_reweighting to +8.0 pp and
    exclusive_pair_contribution to +17.6 pp. The unlabelled rows carry the bulk
    of each margin so the renderer must report the margin total separately from
    the named example it prints.
    """
    value = "strict_intermediation_value_share"
    return pd.DataFrame(
        [
            _contribution("within_pair_choice", USDC, WETH, 0.05),
            _contribution("within_pair_choice", UNLABELLED, WETH, 0.40),
            _contribution("within_pair_choice", WETH, UNLABELLED, -0.55),
            _contribution("pair_composition_reweighting", USDT, WETH, 2.0),
            _contribution("pair_composition_reweighting", USDC, WETH, 1.5),
            _contribution("pair_composition_reweighting", UNLABELLED, WETH, 4.5),
            _contribution("comparison_exclusive_composition", USDT, USDC, 0.13),
            _contribution("comparison_exclusive_composition", UNLABELLED, WETH, 20.87),
            _contribution("baseline_exclusive_composition", UNLABELLED, USDC, -3.4),
            # The dollar-weighted allocation reaches the same margin totals from a
            # different spread of pairs, so breadth is never read off the count.
            _contribution("within_pair_choice", USDC, WETH, 0.30, metric=value),
            _contribution("within_pair_choice", UNLABELLED, WETH, 0.10, metric=value),
            _contribution("within_pair_choice", WETH, UNLABELLED, -0.50, metric=value),
            _contribution("pair_composition_reweighting", USDT, WETH, 6.0, metric=value),
            _contribution("pair_composition_reweighting", USDC, WETH, 3.0, metric=value),
            _contribution(
                "pair_composition_reweighting", UNLABELLED, WETH, -1.0, metric=value
            ),
            _contribution(
                "comparison_exclusive_composition", USDT, USDC, 1.0, metric=value
            ),
            _contribution(
                "comparison_exclusive_composition", UNLABELLED, WETH, 20.0, metric=value
            ),
            _contribution(
                "baseline_exclusive_composition", UNLABELLED, USDC, -3.4, metric=value
            ),
        ]
    )


def test_renderer_emits_complete_display_and_coordinate_macros() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
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


def test_margin_examples_name_labelled_pairs_and_report_the_margin_total() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for macro, value in (
        ("MarginWithinPair", "USDC\\,$\\to$\\,WETH"),
        ("MarginWithinContribution", "$+0.05$ pp"),
        ("MarginWithinTotal", "$-0.1$ pp"),
        ("MarginReweightPair", "USDT\\,$\\to$\\,WETH"),
        ("MarginReweightContribution", "$+2.00$ pp"),
        ("MarginReweightTotal", "$+8.0$ pp"),
        ("MarginNewPairPair", "USDT\\,$\\to$\\,USDC"),
        ("MarginNewPairContribution", "$+0.13$ pp"),
        ("MarginNewPairTotal", "$+21.0$ pp"),
        ("MarginRetiredPairTotal", "$-3.4$ pp"),
        ("MarginReweightRoutesBase", "7,447"),
        ("MarginReweightRoutesEnd", "54,112"),
        ("MarginReweightWeightBase", "0.40\\%"),
        ("MarginReweightWeightEnd", "4.50\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered
    # An unlabelled endpoint is never printed, even when it dominates its margin.
    assert "0xab" not in rendered


def test_margin_examples_reject_contributions_that_miss_the_aggregate_term() -> None:
    contributions = _contributions()
    reweighting = contributions["contribution_component"].eq(
        "pair_composition_reweighting"
    )
    contributions.loc[reweighting, "contribution_pp"] *= 2
    with pytest.raises(ValueError, match="do not reconcile common_pair_reweighting"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_margin_examples_reject_a_causal_mechanism_label() -> None:
    contributions = _contributions()
    contributions["mechanism_status"] = "causal_pair_contribution"
    with pytest.raises(ValueError, match="causal mechanism label"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_margin_examples_require_a_labelled_positive_contributor() -> None:
    contributions = _contributions()
    within = contributions["contribution_component"].eq("within_pair_choice")
    contributions.loc[within, "src"] = UNLABELLED
    with pytest.raises(
        ValueError, match="within_pair_choice has no labelled positive contributor"
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


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
            mutation(_decomposition()), _fixed_effects(), _usdt_integration(), _contributions()
        )


def test_renderer_fails_closed_when_market_incidence_bridge_is_inconsistent() -> None:
    frame = _decomposition()
    market = frame["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
    frame.loc[market, "market_activity_reweighting"] += 0.01
    with pytest.raises(ValueError, match="total change"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions()
        )


def test_margin_breadth_counts_pairs_and_splits_gains_from_losses() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for macro, value in (
        # Two pairs gain and one loses within continuing pairs, so the -0.1 pp
        # margin total is an offset rather than an absence of movement.
        ("MarginWithinGainPairs", "2"),
        ("MarginWithinLossPairs", "1"),
        ("MarginWithinGrossUp", "$+0.5$ pp"),
        ("MarginWithinGrossDown", "$-0.6$ pp"),
        ("MarginReweightGainPairs", "3"),
        ("MarginReweightLossPairs", "0"),
        ("MarginReweightGrossUp", "$+8.0$ pp"),
        ("MarginReweightHalfPairs", "1"),
        ("MarginReweightNinetyPairs", "3"),
        ("MarginNewPairGainPairs", "2"),
        ("MarginNewPairTopShare", "99.4\\%"),
        ("MarginNewPairHalfPairs", "1"),
        # Dollar weighting reaches the same totals from a different spread.
        ("MarginWithinValueGainPairs", "2"),
        ("MarginWithinValueGrossUp", "$+0.4$ pp"),
        ("MarginWithinValueGrossDown", "$-0.5$ pp"),
        ("MarginReweightValueLossPairs", "1"),
        ("MarginReweightValueGrossUp", "$+9.0$ pp"),
        ("MarginReweightValueGrossDown", "$-1.0$ pp"),
        ("MarginNewPairValueTopShare", "95.2\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_margin_breadth_reconciles_the_value_margins_it_reports() -> None:
    contributions = _contributions()
    value_reweighting = contributions["metric"].eq(
        "strict_intermediation_value_share"
    ) & contributions["contribution_component"].eq("pair_composition_reweighting")
    contributions.loc[value_reweighting, "contribution_pp"] += 1.0
    with pytest.raises(
        ValueError,
        match="strict_intermediation_value_share pair_composition_reweighting",
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_margin_breadth_requires_the_dollar_weighted_allocation() -> None:
    contributions = _contributions()
    contributions = contributions[
        contributions["metric"].ne("strict_intermediation_value_share")
    ]
    with pytest.raises(ValueError, match="no pooled 2024--2026"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_renderer_fails_closed_on_wrong_matched_market_scope() -> None:
    fixed_effects = _fixed_effects()
    fixed_effects.loc[0, "estimand_scope"] = "wrong_scope"
    with pytest.raises(ValueError, match="comparison set"):
        render_pair_decomposition_deck_values(
            _decomposition(), fixed_effects, _usdt_integration(), _contributions()
        )
