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


def _macro(rendered: str, name: str) -> str:
    """The rendered body of one macro, so a test can compare two of them."""
    match = re.search(rf"\\newcommand\{{\\{name}\}}\{{(?P<value>[^}}]*)\}}", rendered)
    assert match is not None, f"missing macro {name}"
    return match.group("value")


def _points(rendered_value: str) -> float:
    """Percentage points out of a rendered ``$+1.2$ pp`` cell."""
    return float(rendered_value.replace("$", "").replace(" pp", ""))


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
    scope: str = "pooled",
    stable_baseline: float = 0.0,
    stable_comparison: float = 1.0,
    weight_baseline: float = 0.004,
    weight_comparison: float = 0.045,
    routes_baseline: float = 7_447.0,
    routes_comparison: float = 54_112.0,
    mass_share: float = 0.5,
) -> dict[str, object]:
    return {
        "metric": metric,
        "reporting_scope": scope,
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
        "aggregate_mass_share_midpoint": mass_share,
        "aggregate_total_change": 0.25,
        "allocation_scope": "pair_level_excludes_common_support_mass",
        "mechanism_status": "descriptive_pair_contribution_noncausal",
    }


# Per scope and metric: the open (choosable) share of the reweighting margin,
# the two WETH-endpoint contributions, and the two new-pair contributions. The
# reweighting entries sum to that scope's `_row` term (+8.0, +8.8, +9.6 pp under
# the 1.0/1.1/1.2 scaling), and the eligible share differs by scope in opposite
# directions across the two metrics, so a renderer that reported the pooled
# split under a scope macro would fail every scope assertion below.
#
# Each cohort of corridors traded in only one year is built from the same
# identity the renderer proves: a margin is that cohort's exclusive activity mass
# times its weighted stablecoin routing rate, with the WETH-endpoint corridors
# carrying a rate of exactly one. The mass differs by scope so a renderer that
# read the pooled cohort under a scope macro would fail, and the retiring cohort
# keeps its `$-3.4$ pp` total in every cell, split -1.0 locked and -2.4 open.
_COHORT_MASS = {"pooled": 0.5, "single_venue": 0.4, "cross_venue": 0.6}
_EXIT_LOCKED_PP = -1.0
_EXIT_OPEN_PP = -2.4
_SCOPE_CONTRIBUTIONS = {
    ("pooled", "count_share"): (4.5, 2.0, 1.5, 0.13, 20.87),
    ("pooled", "strict_intermediation_value_share"): (-1.0, 6.0, 3.0, 1.0, 20.0),
    ("single_venue", "count_share"): (6.8, 1.2, 0.8, 5.0, 16.0),
    ("single_venue", "strict_intermediation_value_share"): (0.8, 5.0, 3.0, 5.0, 16.0),
    ("cross_venue", "count_share"): (1.6, 5.0, 3.0, 15.0, 6.0),
    ("cross_venue", "strict_intermediation_value_share"): (3.6, 4.0, 2.0, 15.0, 6.0),
}


def _contributions() -> pd.DataFrame:
    """Reproduce the aggregate terms of `_row` from named and unlabelled pairs.

    `_row` sets within_common to -0.1 pp, exclusive_pair_contribution to
    +17.6 pp, and common_pair_reweighting to +8.0 pp pooled, rising with the
    per-scope scaling. The unlabelled rows carry the bulk of each margin so the
    renderer must report the margin total separately from the named example it
    prints.

    Five ordered pairs trade in both years. Three have no WETH endpoint and can
    move their own stablecoin share; two have a WETH endpoint, so native WETH is
    ineligible as their intermediary, their stablecoin share is one in both
    years, and their within-pair contribution is exactly zero. The fixture
    respects that identity because the data do, in every scope.

    The dollar-weighted allocation reaches each margin total from a different
    spread of pairs, so breadth and eligibility are never read off the count.
    """
    value = "strict_intermediation_value_share"
    within = {
        "count_share": (0.05, 0.40, -0.55),
        value: (0.30, 0.10, -0.50),
    }

    def locked(component: str, src: str, tgt: str, pp: float, **kwargs) -> dict:
        return _contribution(
            component,
            src,
            tgt,
            pp,
            stable_baseline=1.0,
            stable_comparison=1.0,
            **kwargs,
        )

    rows: list[dict[str, object]] = []
    for (scope, metric), split in _SCOPE_CONTRIBUTIONS.items():
        open_reweight, locked_usdt, locked_usdc, new_named, new_unlabelled = split
        first, second, third = within[metric]
        rows.extend(
            [
                _contribution(
                    "within_pair_choice", USDC, USDT, first, metric=metric, scope=scope
                ),
                _contribution(
                    "within_pair_choice",
                    UNLABELLED,
                    USDT,
                    second,
                    metric=metric,
                    scope=scope,
                ),
                _contribution(
                    "within_pair_choice",
                    USDT,
                    UNLABELLED,
                    third,
                    metric=metric,
                    scope=scope,
                ),
                locked("within_pair_choice", USDT, WETH, 0.0, metric=metric, scope=scope),
                locked("within_pair_choice", USDC, WETH, 0.0, metric=metric, scope=scope),
                _contribution(
                    "pair_composition_reweighting",
                    USDC,
                    USDT,
                    0.0,
                    metric=metric,
                    scope=scope,
                ),
                _contribution(
                    "pair_composition_reweighting",
                    UNLABELLED,
                    USDT,
                    open_reweight,
                    metric=metric,
                    scope=scope,
                ),
                _contribution(
                    "pair_composition_reweighting",
                    USDT,
                    UNLABELLED,
                    0.0,
                    metric=metric,
                    scope=scope,
                ),
                locked(
                    "pair_composition_reweighting",
                    USDT,
                    WETH,
                    locked_usdt,
                    metric=metric,
                    scope=scope,
                ),
                locked(
                    "pair_composition_reweighting",
                    USDC,
                    WETH,
                    locked_usdc,
                    metric=metric,
                    scope=scope,
                ),
                *_cohort(
                    "comparison_exclusive_composition",
                    metric=metric,
                    scope=scope,
                    named=(USDT, USDC, new_named),
                    locked_pp=new_unlabelled,
                ),
                *_cohort(
                    "baseline_exclusive_composition",
                    metric=metric,
                    scope=scope,
                    named=(UNLABELLED, USDC, _EXIT_OPEN_PP),
                    locked_pp=_EXIT_LOCKED_PP,
                ),
            ]
        )
    return pd.DataFrame(rows)


def _cohort(
    component: str,
    *,
    metric: str,
    scope: str,
    named: tuple[str, str, float],
    locked_pp: float,
) -> list[dict[str, object]]:
    """One exclusive-support cohort that satisfies the cohort identity.

    The cohort's two weights close on one and each corridor's contribution is its
    weight times its stablecoin routing rate times the cohort's exclusive
    activity mass, exactly as the ledger builds them. The WETH-endpoint corridor
    routes at one by construction; the open corridor's rate is whatever the
    remaining contribution implies.
    """
    entering = component == "comparison_exclusive_composition"
    mass = _COHORT_MASS[scope]
    source, target, open_pp = named
    locked_weight = abs(locked_pp) / (100 * mass)
    open_weight = 1.0 - locked_weight
    open_share = abs(open_pp) / (100 * mass * open_weight)
    weights = (
        {"weight_comparison": locked_weight, "weight_baseline": 0.0}
        if entering
        else {"weight_baseline": locked_weight, "weight_comparison": 0.0}
    )
    shares = (
        {"stable_comparison": 1.0, "stable_baseline": 0.0}
        if entering
        else {"stable_baseline": 1.0, "stable_comparison": 0.0}
    )
    return [
        _contribution(
            component,
            source,
            target,
            open_pp,
            metric=metric,
            scope=scope,
            mass_share=mass,
            **(
                {
                    "weight_comparison": open_weight,
                    "weight_baseline": 0.0,
                    "stable_comparison": open_share,
                    "stable_baseline": 0.0,
                }
                if entering
                else {
                    "weight_baseline": open_weight,
                    "weight_comparison": 0.0,
                    "stable_baseline": open_share,
                    "stable_comparison": 0.0,
                }
            ),
        ),
        _contribution(
            component,
            UNLABELLED,
            WETH,
            locked_pp,
            metric=metric,
            scope=scope,
            mass_share=mass,
            **weights,
            **shares,
        ),
    ]


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
        ("MarginWithinPair", "USDC\\,$\\to$\\,USDT"),
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


def test_endpoint_eligibility_splits_the_two_composition_margins() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for macro, value in (
        # Two of five continuing pairs have a WETH endpoint, and their weight in
        # routed activity rises, so they move the aggregate through composition
        # alone: +3.5 pp of the +8.0 pp reweighting margin.
        ("LockedPairs", "2"),
        ("LockedCommonPairs", "5"),
        ("LockedPairShare", "40.0\\%"),
        ("LockedWeightBase", "0.8\\%"),
        ("LockedWeightEnd", "9.0\\%"),
        ("LockedReweight", "$+3.5$ pp"),
        ("OpenReweight", "$+4.5$ pp"),
        ("LockedReweightShare", "43.8\\%"),
        ("LockedNewPair", "$+20.9$ pp"),
        ("OpenNewPair", "$+0.1$ pp"),
        # Dollar weighting sends the split the other way: the eligible corridors
        # supply more than the whole margin because the rest of it is negative.
        ("LockedValueReweight", "$+9.0$ pp"),
        ("OpenValueReweight", "$-1.0$ pp"),
        ("LockedValueReweightShare", "112.5\\%"),
        ("LockedValueNewPairShare", "95.2\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_endpoint_eligibility_is_taken_inside_each_integration_scope() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for macro, value in (
        # Each scope carries its own reweighting total and its own eligible
        # share of it. By count the eligible corridors dominate across venues
        # and not within one; by value the ordering reverses. Neither number is
        # the pooled 43.8% / 112.5% split, so a scope macro cannot be silently
        # fed the pooled allocation.
        ("PairSingleReweight", "$+8.8$ pp"),
        ("LockedSingleReweight", "$+2.0$ pp"),
        ("LockedSingleReweightShare", "22.7\\%"),
        ("PairCrossReweight", "$+9.6$ pp"),
        ("LockedCrossReweight", "$+8.0$ pp"),
        ("LockedCrossReweightShare", "83.3\\%"),
        ("PairValueSingleReweight", "$+8.8$ pp"),
        ("LockedValueSingleReweightShare", "90.9\\%"),
        ("PairValueCrossReweight", "$+9.6$ pp"),
        ("LockedValueCrossReweightShare", "62.5\\%"),
        # The new-pair margin splits by scope too.
        ("LockedSingleNewPairShare", "76.2\\%"),
        ("LockedCrossNewPairShare", "28.6\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_scope_new_pair_total_is_the_gross_entry_margin() -> None:
    """The entry margin has no decomposition term of its own.

    ``exclusive_pair_contribution`` nets the pairs that stopped trading against
    the ones that started, while the eligibility split is taken of the gross
    entry margin alone. A scope total read from that term would understate the
    margin its own eligible share is a share of, so the renderer takes the total
    from the split's own components and only the reweighting total from the row.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for suffix in ("Single", "Cross"):
        for infix in ("", "Value"):
            locked = _macro(rendered, f"Locked{infix}{suffix}NewPair")
            opened = _macro(rendered, f"Open{infix}{suffix}NewPair")
            total = _macro(rendered, f"Pair{infix}{suffix}NewPair")
            assert _points(locked) + _points(opened) == pytest.approx(_points(total))
            # The fixture's netted exclusive term is +17.6 pp against a gross
            # entry margin of +21.0 pp, so the two cannot be confused silently.
            assert total != "$+17.6$ pp"
    # The reweighting total still comes from the scope's own decomposition row,
    # against which the producer reconciles the split.
    assert _macro(rendered, "PairSingleReweight") == "$+8.8$ pp"


def test_support_cohorts_reads_the_netted_term_as_corridor_replacement() -> None:
    """One exclusive activity mass, two cohorts, and the routing rate of each.

    The netted exclusive-pair term is the mass times the gap between the two
    cohorts' rates, so the renderer must publish all three and they must close.
    The exiting cohort's margin is negative, which is exactly the case the
    positive-margin eligibility guard refuses to interpret.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions()
    )
    for infix in ("", "Value"):
        for suffix, scope in (("", "pooled"), ("Single", "single_venue"), ("Cross", "cross_venue")):
            mass = _COHORT_MASS[scope]
            exit_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Exit"))
            enter_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Enter"))
            net_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Net"))
            assert exit_pp == pytest.approx(-3.4)
            assert enter_pp == pytest.approx(21.0)
            assert exit_pp + enter_pp == pytest.approx(net_pp)
            # The netted term, never the gross entry margin.
            assert net_pp == pytest.approx(17.6)
            assert _macro(rendered, f"Cohort{infix}{suffix}Mass") == f"{100 * mass:.1f}\\%"
            # Each cohort's margin is its own mass times its own routing rate.
            for prefix, pp in (("Exit", exit_pp), ("Enter", enter_pp)):
                rate = _macro(rendered, f"Cohort{infix}{suffix}{prefix}Share")
                assert abs(pp) == pytest.approx(
                    mass * float(rate.replace("\\%", "")), abs=0.05
                )
    # The retiring cohort routes at 6.8% pooled against the arriving cohort's
    # 42.0%; strip the WETH-endpoint corridors and both rates fall, which is the
    # whole point of publishing the open rate beside the cohort rate.
    assert _macro(rendered, "CohortExitShare") == "6.8\\%"
    assert _macro(rendered, "CohortEnterShare") == "42.0\\%"
    assert _macro(rendered, "CohortExitOpenShare") == "4.9\\%"
    assert _macro(rendered, "CohortEnterOpenShare") == "0.4\\%"
    assert _macro(rendered, "CohortEnterOpenWeight") == "58.3\\%"
    # A scope's cohorts are read inside that scope, never off the pooled rows.
    assert _macro(rendered, "CohortCrossEnterOpenShare") == "27.8\\%"


def test_support_cohorts_rejects_a_margin_that_is_not_mass_times_routing() -> None:
    contributions = _contributions()
    # Only the open corridor moves, so the WETH-endpoint identity still holds and
    # the failure is the cohort arithmetic rather than its structure.
    entering = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    ) & contributions["tgt"].eq(USDC)
    contributions.loc[entering, "stable_share_comparison"] *= 0.5
    with pytest.raises(ValueError, match="activity mass times its routing rate"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_support_cohorts_rejects_cohorts_that_carry_different_activity_mass() -> None:
    """Without a common mass the two rates are not comparable, only their sum is."""
    contributions = _contributions()
    entering = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    )
    contributions.loc[entering, "aggregate_mass_share_midpoint"] = 0.25
    with pytest.raises(ValueError, match="different activity mass"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_support_cohorts_rejects_an_eligibility_split_that_straddles_zero() -> None:
    """A share of a margin whose parts disagree in sign is not a share of it."""
    contributions = _contributions()
    retiring = contributions["contribution_component"].eq(
        "baseline_exclusive_composition"
    )
    locked = retiring & contributions["tgt"].eq(WETH)
    contributions.loc[locked, "contribution_pp"] = 2.0
    contributions.loc[retiring & ~locked, "contribution_pp"] = -5.4
    with pytest.raises(ValueError, match="straddles zero"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_support_cohorts_rejects_a_switching_weth_endpoint_cohort_corridor() -> None:
    contributions = _contributions()
    locked = contributions["contribution_component"].eq(
        "baseline_exclusive_composition"
    ) & contributions["tgt"].eq(WETH)
    contributions.loc[locked, "stable_share_baseline"] = 0.5
    with pytest.raises(ValueError, match="eligibility identity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_endpoint_eligibility_rejects_a_scope_split_against_another_scope() -> None:
    """A scope's allocation must reconcile that scope's own aggregate term."""
    contributions = _contributions()
    cross_reweighting = (
        contributions["reporting_scope"].eq("cross_venue")
        & contributions["metric"].eq("count_share")
        & contributions["contribution_component"].eq("pair_composition_reweighting")
        & contributions["src"].eq(UNLABELLED)
    )
    contributions.loc[cross_reweighting, "contribution_pp"] -= 1.6
    with pytest.raises(
        ValueError, match="cross_venue eligibility split does not reconcile"
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_endpoint_eligibility_requires_the_scope_specific_allocation() -> None:
    contributions = _contributions()
    contributions = contributions[contributions["reporting_scope"].ne("cross_venue")]
    with pytest.raises(ValueError, match="no cross_venue 2024--2026"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_endpoint_eligibility_rejects_a_switching_weth_endpoint_pair() -> None:
    contributions = _contributions()
    locked = contributions["contribution_component"].eq("within_pair_choice") & (
        contributions["tgt"].eq(WETH)
    )
    contributions.loc[locked, "stable_share_baseline"] = 0.5
    with pytest.raises(ValueError, match="eligibility identity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions
        )


def test_endpoint_eligibility_rejects_within_pair_movement_on_an_eligible_pair() -> None:
    contributions = _contributions()
    within = contributions["contribution_component"].eq("within_pair_choice")
    # Move the movement onto an eligible pair rather than inventing it, so the
    # margin still reconciles and only the eligibility guard can reject it.
    contributions.loc[within & contributions["tgt"].eq(WETH), "contribution_pp"] = 0.01
    contributions.loc[within & contributions["src"].eq(USDC) & contributions["tgt"].eq(
        USDT
    ), "contribution_pp"] -= 0.02
    with pytest.raises(ValueError, match="eligibility identity forbids"):
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
