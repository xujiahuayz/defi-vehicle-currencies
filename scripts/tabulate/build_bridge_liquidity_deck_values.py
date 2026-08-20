#!/usr/bin/env python3
"""Build paper/deck macros for the bridge-liquidity dominance screen."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits/bridge_liquidity_dominance.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits/bridge_liquidity_deck_values.tex"
TABLE_OUTPUT = OUTPUT_DIR / "tables/bridge_establishment_regressions.tex"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _integer(value: float) -> str:
    return f"{value:,.0f}".replace(",", "{,}")


def _pct(value: float, decimals: int = 1) -> str:
    return f"{100.0 * value:.{decimals}f}\\%"


def _signed_pp(value: float, decimals: int = 2) -> str:
    return f"${100.0 * value:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 2) -> str:
    return f"${abs(100.0 * value):.{decimals}f}$ pp"


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _estimate_cell(row: pd.Series, *, scale: float = 1.0) -> str:
    coefficient = scale * float(row["coefficient"])
    standard_error = scale * float(row["standard_error"])
    return (
        f"\\shortstack{{${coefficient:+.2f}{_stars(float(row['p_value']))}$"
        f"\\\\$({standard_error:.2f})$}}"
    )


def _level_cell(row: pd.Series, *, complement: bool = False) -> str:
    coefficient = float(row["coefficient"])
    if complement:
        coefficient = 1.0 - coefficient
    standard_error = float(row["standard_error"])
    return f"\\shortstack{{${100.0 * coefficient:.1f}$\\\\$({100.0 * standard_error:.1f})$}}"


def render_bridge_liquidity_deck_values(estimates: pd.DataFrame) -> str:
    required = {"claim_status", "record_type"}
    missing = sorted(required - set(estimates.columns))
    if missing:
        raise ValueError(f"bridge-liquidity exhibit lacks columns: {missing}")
    if not estimates["claim_status"].eq("provisional_exploratory").all():
        raise ValueError("bridge-liquidity rows are not provisional_exploratory")
    pooled = _single(
        estimates,
        record_type="bridge_liquidity_top_rank_summary",
        sample="pooled",
    )
    base = _single(
        estimates,
        record_type="bridge_liquidity_top_rank_summary",
        sample="2024",
    )
    end = _single(
        estimates,
        record_type="bridge_liquidity_top_rank_summary",
        sample="2026",
    )
    route_depth = _single(
        estimates,
        record_type="bridge_liquidity_depth_regression",
        model_id="route_share_log_min_depth",
        outcome="route_share_five",
        regressor="log_bridge_min_capital",
    )
    route_depth_stable_total = _single(
        estimates,
        record_type="bridge_liquidity_depth_regression",
        model_id="route_share_log_min_depth_stable_interaction",
        outcome="route_share_five",
        regressor="stable_total_log_bridge_min_capital",
    )
    selection_depth = _single(
        estimates,
        record_type="bridge_liquidity_depth_regression",
        model_id="selection_log_min_depth",
        outcome="selected_five",
        regressor="log_bridge_min_capital",
    )
    horse_depth = _single(
        estimates,
        record_type="bridge_liquidity_horse_race_regression",
        model_id="route_share_depth_global_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_bridge_min_capital",
    )
    horse_global_day = _single(
        estimates,
        record_type="bridge_liquidity_horse_race_regression",
        model_id="route_share_depth_global_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_global_route_count_day_leaveout",
    )
    entry_birth_depth = _single(
        estimates,
        record_type="bridge_liquidity_entry_birth_regression",
        model_id="entry_route_share_depth_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_bridge_min_capital",
    )
    entry_birth_selection = _single(
        estimates,
        record_type="bridge_liquidity_entry_birth_regression",
        model_id="entry_selection_depth_reach_candidate_fe",
        outcome="selected_five",
        regressor="log_bridge_min_capital",
    )
    entry_birth_lag_route_reach = _single(
        estimates,
        record_type="bridge_liquidity_entry_birth_regression",
        model_id="entry_route_share_depth_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_global_route_count_lag30",
    )
    bottleneck_min = _single(
        estimates,
        record_type="bridge_liquidity_bottleneck_regression",
        model_id="route_share_min_max_depth_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_bridge_min_capital",
    )
    bottleneck_max = _single(
        estimates,
        record_type="bridge_liquidity_bottleneck_regression",
        model_id="route_share_min_max_depth_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_bridge_max_capital",
    )
    bridge_imbalance = _single(
        estimates,
        record_type="bridge_liquidity_bottleneck_regression",
        model_id="route_share_geom_imbalance_reach_candidate_fe",
        outcome="route_share_five",
        regressor="log_bridge_imbalance",
    )
    leave_one_depth = estimates[
        estimates["record_type"].eq("bridge_liquidity_leave_one_candidate_regression")
        & estimates["model_id"].eq("route_share_depth_global_reach_candidate_fe")
        & estimates["outcome"].eq("route_share_five")
        & estimates["regressor"].eq("log_bridge_min_capital")
    ].copy()
    if leave_one_depth["dropped_candidate_symbol"].nunique() < 5:
        raise ValueError("bridge-liquidity leave-one screen is incomplete")
    leave_one_min = leave_one_depth.loc[
        leave_one_depth["coefficient"].astype(float).idxmin()
    ]
    stable_issuer_support = _single(
        estimates,
        record_type="bridge_liquidity_stable_issuer_support",
        model_id="stable_issuer_bridge_race_support",
    )
    stable_issuer_usdc_2026 = _single(
        estimates,
        record_type="bridge_liquidity_stable_issuer_regression",
        model_id="stable_issuer_2026_depth_reach_fe",
        outcome="route_share_stable_supported",
        regressor="is_usdc_x_2026",
    )
    stable_issuer_usdt_2026 = _single(
        estimates,
        record_type="bridge_liquidity_stable_issuer_regression",
        model_id="stable_issuer_2026_depth_reach_fe",
        outcome="route_share_stable_supported",
        regressor="is_usdt_x_2026",
    )
    stable_issuer_depth = _single(
        estimates,
        record_type="bridge_liquidity_stable_issuer_regression",
        model_id="stable_issuer_2026_depth_reach_fe",
        outcome="route_share_stable_supported",
        regressor="log_bridge_min_capital",
    )
    establishment_pre = _single(
        estimates,
        record_type="bridge_establishment_period_summary",
        period="pre_30",
    )
    establishment_post = _single(
        estimates,
        record_type="bridge_establishment_period_summary",
        period="post_0_29",
    )
    establishment_count = _single(
        estimates,
        record_type="bridge_establishment_event_regression",
        model_id="stable_share_after_bridge_establishment",
        regressor="post_0_29",
    )
    establishment_value = _single(
        estimates,
        record_type="bridge_establishment_event_regression",
        model_id="stable_value_share_after_bridge_establishment",
        regressor="post_0_29",
    )
    establishment_native = _single(
        estimates,
        record_type="bridge_establishment_event_regression",
        model_id="native_routes_after_bridge_establishment",
        regressor="post_0_29",
    )
    timing_same_day = _single(
        estimates,
        record_type="bridge_establishment_timing_summary",
        model_id="same_day",
    )
    timing_month = _single(
        estimates,
        record_type="bridge_establishment_timing_summary",
        model_id="within_30_days",
    )
    timing_long = _single(
        estimates,
        record_type="bridge_establishment_timing_summary",
        model_id="within_120_days",
    )
    timing_shallow_month = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_30_days",
        depth_group="below_0.1x",
    )
    timing_competitive_month = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_30_days",
        depth_group="at_least_0.1x",
    )
    timing_month_difference = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth",
    )
    timing_month_controlled = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth_controls",
    )
    timing_month_no_stable_endpoint = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth_no_stable_endpoint",
    )
    adoption_capital_pre = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_pre_route_week",
    )
    adoption_capital_post = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_post_route_week",
    )
    adoption_capital_matched_pre = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_minus_weth_pre_route_week_unwinsorized",
    )
    adoption_capital_matched_post = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_minus_weth_post_route_week_unwinsorized",
    )
    adoption_capital_matched_difference = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_minus_weth_pre_minus_post_unwinsorized",
    )
    adoption_capital_matched_winsor = _single(
        estimates,
        record_type="bridge_adoption_capital_contrast",
        model_id="stablecoin_minus_weth_pre_minus_post_winsorized_5_95",
    )
    depth_slope_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_on_relative_depth",
        period="post_0_29",
    )
    depth_slope_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_on_relative_depth",
        period="post_30_119",
    )
    depth_equal_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_native",
        period="post_0_29",
    )
    depth_equal_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_native",
        period="post_30_119",
    )
    depth_double_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_2x_native",
        period="post_0_29",
    )
    depth_double_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_2x_native",
        period="post_30_119",
    )
    depth_thin_first = _single(
        estimates,
        record_type="bridge_establishment_depth_summary",
        period="post_0_29",
        depth_bin="below_0.1x",
    )
    depth_thin_later = _single(
        estimates,
        record_type="bridge_establishment_depth_summary",
        period="post_30_119",
        depth_bin="below_0.1x",
    )
    depth_first_events = depth_slope_first.get("events")
    if pd.isna(depth_first_events):
        # Retain compatibility with compact renderer fixtures that predate the
        # event-support field. Current empirical output always supplies it.
        depth_first_events = establishment_count["events"]
    if not (
        float(pooled["top_bridge_route_share"]) > 0.75
        and float(end["top_bridge_route_share"]) > float(base["top_bridge_route_share"])
        and float(route_depth["coefficient"]) > 0
        and float(route_depth["p_value"]) < 0.01
        and float(route_depth_stable_total["coefficient"]) > float(route_depth["coefficient"])
        and float(route_depth_stable_total["p_value"]) < 0.01
        and float(selection_depth["coefficient"]) > 0
        and float(horse_depth["coefficient"]) > 0
        and float(horse_depth["p_value"]) < 0.01
        and float(horse_global_day["coefficient"]) > 0
        and float(horse_global_day["p_value"]) < 0.01
        and float(entry_birth_depth["coefficient"]) > 0
        and float(entry_birth_depth["p_value"]) < 0.01
        and float(entry_birth_depth["n_observations"]) > 500
        and float(entry_birth_selection["coefficient"]) > 0
        and float(entry_birth_selection["p_value"]) < 0.01
        and float(bottleneck_min["coefficient"]) > 0
        and float(bottleneck_min["p_value"]) < 0.01
        and float(bottleneck_max["p_value"]) > 0.05
        and float(bridge_imbalance["coefficient"]) < 0
        and float(bridge_imbalance["p_value"]) < 0.01
        and leave_one_depth["coefficient"].astype(float).gt(0).all()
        and leave_one_depth["p_value"].astype(float).lt(0.01).all()
        and float(stable_issuer_support["choice_groups"]) > 1000
        and float(stable_issuer_usdc_2026["coefficient"]) > 0
        and float(stable_issuer_usdc_2026["p_value"]) < 0.05
        and float(stable_issuer_usdt_2026["coefficient"]) > 0
        and float(stable_issuer_usdt_2026["p_value"]) < 0.01
        and float(stable_issuer_depth["coefficient"]) > 0
        and float(stable_issuer_depth["p_value"]) < 0.01
        and float(establishment_pre["stable_route_share"]) == 0
        and float(establishment_post["stable_route_share"]) > 0
        and float(establishment_count["coefficient"]) > 0
        and float(establishment_count["p_value"]) < 0.01
        and float(establishment_value["coefficient"]) > 0
        and float(establishment_value["p_value"]) < 0.05
        and float(establishment_native["coefficient"]) < 0
        and float(establishment_native["p_value"]) < 0.01
        and float(timing_same_day["adoption_share"])
        < float(timing_month["adoption_share"])
        <= float(timing_long["adoption_share"])
        and float(timing_competitive_month["adoption_share"])
        > float(timing_shallow_month["adoption_share"])
        and float(timing_month_difference["coefficient"]) > 0
        and float(timing_month_difference["p_value"]) < 0.01
        and float(timing_month_controlled["coefficient"]) > 0
        and float(timing_month_controlled["p_value"]) < 0.01
        and float(timing_month_no_stable_endpoint["coefficient"]) > 0
        and float(timing_month_no_stable_endpoint["p_value"]) < 0.01
        and float(adoption_capital_pre["coefficient"]) > 0
        and float(adoption_capital_pre["p_value"]) < 0.01
        and float(adoption_capital_post["coefficient"]) < 0
        and float(adoption_capital_post["p_value"]) < 0.05
        and float(adoption_capital_matched_pre["coefficient"]) > 0
        and float(adoption_capital_matched_pre["p_value"]) < 0.01
        and float(adoption_capital_matched_post["coefficient"]) < 0
        and float(adoption_capital_matched_post["p_value"]) < 0.05
        and float(adoption_capital_matched_difference["coefficient"]) > 0
        and float(adoption_capital_matched_difference["p_value"]) < 0.01
        and float(adoption_capital_matched_winsor["coefficient"]) > 0
        and float(adoption_capital_matched_winsor["p_value"]) < 0.01
        and float(depth_slope_first["coefficient"]) > 0
        and float(depth_slope_first["p_value"]) < 0.01
        and float(depth_slope_later["coefficient"]) > 0
        and float(depth_slope_later["p_value"]) < 0.01
        and float(depth_thin_first["stable_route_share"]) < 0.05
        and float(depth_thin_later["stable_route_share"]) < 0.05
        and float(depth_equal_first["coefficient"]) > 0.50
        and float(depth_equal_later["coefficient"]) > 0.50
        and float(depth_double_first["coefficient"]) > 0.65
        and float(depth_double_later["coefficient"]) > 0.65
    ):
        raise ValueError("bridge-liquidity dominance pattern no longer holds")
    lines = [
        "% Generated by scripts/tabulate/build_bridge_liquidity_deck_values.py; do not edit.",
        f"\\newcommand{{\\BridgeLiquidityRows}}{{{_integer(float(pooled['candidate_rows']))}}}",
        f"\\newcommand{{\\BridgeLiquidityGroups}}{{{_integer(float(pooled['choice_groups']))}}}",
        f"\\newcommand{{\\BridgeLiquidityPairs}}{{{_integer(float(pooled['ordered_pairs']))}}}",
        f"\\newcommand{{\\BridgeLiquidityDays}}{{{_integer(float(pooled['days']))}}}",
        f"\\newcommand{{\\BridgeLiquidityTopShare}}{{{_pct(float(pooled['top_bridge_route_share']))}}}",
        f"\\newcommand{{\\BridgeLiquidityTopShareBase}}{{{_pct(float(base['top_bridge_route_share']))}}}",
        f"\\newcommand{{\\BridgeLiquidityTopShareEnd}}{{{_pct(float(end['top_bridge_route_share']))}}}",
        f"\\newcommand{{\\BridgeLiquidityTopSelected}}{{{_pct(float(pooled['top_bridge_selected_rate']))}}}",
        f"\\newcommand{{\\BridgeLiquidityTopStableRate}}{{{_pct(float(pooled['top_bridge_stable_rate']))}}}",
        f"\\newcommand{{\\BridgeLiquidityLogCoef}}{{{_signed_pp(float(route_depth['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityLogSE}}{{{_unsigned_pp(float(route_depth['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableLogTotalCoef}}{{{_signed_pp(float(route_depth_stable_total['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableLogTotalSE}}{{{_unsigned_pp(float(route_depth_stable_total['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquiditySelectionLogCoef}}{{{_signed_pp(float(selection_depth['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquiditySelectionLogSE}}{{{_unsigned_pp(float(selection_depth['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityHorseRaceDepthCoef}}{{{_signed_pp(float(horse_depth['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityHorseRaceDepthSE}}{{{_unsigned_pp(float(horse_depth['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityHorseRaceGlobalDayCoef}}{{{_signed_pp(float(horse_global_day['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityHorseRaceGlobalDaySE}}{{{_unsigned_pp(float(horse_global_day['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthRows}}{{{_integer(float(entry_birth_depth['n_observations']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthGroups}}{{{_integer(float(entry_birth_depth['choice_groups']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthDepthCoef}}{{{_signed_pp(float(entry_birth_depth['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthDepthSE}}{{{_unsigned_pp(float(entry_birth_depth['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthSelectionCoef}}{{{_signed_pp(float(entry_birth_selection['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthSelectionSE}}{{{_unsigned_pp(float(entry_birth_selection['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthLagReachCoef}}{{{_signed_pp(float(entry_birth_lag_route_reach['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityEntryBirthLagReachSE}}{{{_unsigned_pp(float(entry_birth_lag_route_reach['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityBottleneckMinCoef}}{{{_signed_pp(float(bottleneck_min['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityBottleneckMinSE}}{{{_unsigned_pp(float(bottleneck_min['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityBottleneckMaxCoef}}{{{_signed_pp(float(bottleneck_max['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityBottleneckMaxSE}}{{{_unsigned_pp(float(bottleneck_max['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityImbalanceCoef}}{{{_signed_pp(float(bridge_imbalance['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityImbalanceSE}}{{{_unsigned_pp(float(bridge_imbalance['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityLeaveOneCount}}{{{_integer(float(leave_one_depth['dropped_candidate_symbol'].nunique()))}}}",
        f"\\newcommand{{\\BridgeLiquidityLeaveOneMinCoef}}{{{_signed_pp(float(leave_one_min['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityLeaveOneMinSE}}{{{_unsigned_pp(float(leave_one_min['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerGroups}}{{{_integer(float(stable_issuer_support['choice_groups']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerPairs}}{{{_integer(float(stable_issuer_support['ordered_pairs']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerUsdcTwentySixCoef}}{{{_signed_pp(float(stable_issuer_usdc_2026['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerUsdcTwentySixSE}}{{{_unsigned_pp(float(stable_issuer_usdc_2026['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerUsdtTwentySixCoef}}{{{_signed_pp(float(stable_issuer_usdt_2026['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerUsdtTwentySixSE}}{{{_unsigned_pp(float(stable_issuer_usdt_2026['standard_error']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerDepthCoef}}{{{_signed_pp(float(stable_issuer_depth['coefficient']))}}}",
        f"\\newcommand{{\\BridgeLiquidityStableIssuerDepthSE}}{{{_unsigned_pp(float(stable_issuer_depth['standard_error']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentEvents}}{{{_integer(float(establishment_count['events']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentPostCountShare}}{{{_pct(float(establishment_post['stable_route_share']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentPostNativeCountShare}}{{{_pct(float(establishment_post['native_route_share']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentPostValueShare}}{{{_pct(float(establishment_post['stable_value_share']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentCountCoef}}{{{_signed_pp(float(establishment_count['coefficient']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentCountSE}}{{{_unsigned_pp(float(establishment_count['standard_error']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentValueCoef}}{{{_signed_pp(float(establishment_value['coefficient']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentValueSE}}{{{_unsigned_pp(float(establishment_value['standard_error']))}}}",
        f"\\newcommand{{\\BridgeEstablishmentNativeLogCoef}}{{${float(establishment_native['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeEstablishmentNativeLogSE}}{{${abs(float(establishment_native['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeTimingEvents}}{{{_integer(float(timing_month['events']))}}}",
        f"\\newcommand{{\\BridgeTimingComparableEvents}}{{{_integer(float(timing_month_difference['n_observations']))}}}",
        f"\\newcommand{{\\BridgeTimingSameDayShare}}{{{_pct(float(timing_same_day['adoption_share']))}}}",
        f"\\newcommand{{\\BridgeTimingMonthShare}}{{{_pct(float(timing_month['adoption_share']))}}}",
        f"\\newcommand{{\\BridgeTimingLongShare}}{{{_pct(float(timing_long['adoption_share']))}}}",
        f"\\newcommand{{\\BridgeTimingShallowMonthShare}}{{{_pct(float(timing_shallow_month['adoption_share']))}}}",
        f"\\newcommand{{\\BridgeTimingCompetitiveMonthShare}}{{{_pct(float(timing_competitive_month['adoption_share']))}}}",
        f"\\newcommand{{\\BridgeTimingCompetitiveDiff}}{{{_signed_pp(float(timing_month_difference['coefficient']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeTimingCompetitiveSE}}{{{_unsigned_pp(float(timing_month_difference['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeTimingControlledDiff}}{{{_signed_pp(float(timing_month_controlled['coefficient']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeTimingControlledSE}}{{{_unsigned_pp(float(timing_month_controlled['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeTimingNoStableEndpointDiff}}{{{_signed_pp(float(timing_month_no_stable_endpoint['coefficient']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeTimingNoStableEndpointSE}}{{{_unsigned_pp(float(timing_month_no_stable_endpoint['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalEvents}}{{{_integer(float(adoption_capital_pre['events']))}}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPreCoef}}{{${float(adoption_capital_pre['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPreSE}}{{${abs(float(adoption_capital_pre['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPostCoef}}{{${float(adoption_capital_post['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPostSE}}{{${abs(float(adoption_capital_post['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPreMedian}}{{${float(adoption_capital_pre['median']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPrePositiveShare}}{{{_pct(float(adoption_capital_pre['positive_share']))}}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPreWinsorMean}}{{${float(adoption_capital_pre['winsorized_5_95_mean']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalPreTopTenShare}}{{{_pct(float(adoption_capital_pre['top_ten_positive_change_share']))}}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedPreCoef}}{{${float(adoption_capital_matched_pre['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedPreSE}}{{${abs(float(adoption_capital_matched_pre['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedPostCoef}}{{${float(adoption_capital_matched_post['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedPostSE}}{{${abs(float(adoption_capital_matched_post['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedDifferenceCoef}}{{${float(adoption_capital_matched_difference['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedDifferenceSE}}{{${abs(float(adoption_capital_matched_difference['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedWinsorCoef}}{{${float(adoption_capital_matched_winsor['coefficient']):+.2f}$}}",
        f"\\newcommand{{\\BridgeAdoptionCapitalMatchedWinsorSE}}{{${abs(float(adoption_capital_matched_winsor['standard_error'])):.2f}$}}",
        f"\\newcommand{{\\BridgeDepthDoseFirstCoef}}{{{_signed_pp(0.01 * float(depth_slope_first['coefficient']))}}}",
        f"\\newcommand{{\\BridgeDepthDoseFirstSE}}{{{_unsigned_pp(0.01 * float(depth_slope_first['standard_error']))}}}",
        f"\\newcommand{{\\BridgeDepthDoseFirstRows}}{{{_integer(float(depth_slope_first['n_observations']))}}}",
        f"\\newcommand{{\\BridgeDepthDoseFirstEvents}}{{{_integer(float(depth_first_events))}}}",
        f"\\newcommand{{\\BridgeDepthDoseLaterCoef}}{{{_signed_pp(0.01 * float(depth_slope_later['coefficient']))}}}",
        f"\\newcommand{{\\BridgeDepthDoseLaterSE}}{{{_unsigned_pp(0.01 * float(depth_slope_later['standard_error']))}}}",
        f"\\newcommand{{\\BridgeDepthThinFirstShare}}{{{_pct(float(depth_thin_first['stable_route_share']))}}}",
        f"\\newcommand{{\\BridgeDepthThinFirstDays}}{{{_integer(float(depth_thin_first['active_pair_days']))}}}",
        f"\\newcommand{{\\BridgeDepthEqualFirstShare}}{{{_pct(float(depth_equal_first['coefficient']))}}}",
        f"\\newcommand{{\\BridgeDepthEqualFirstSE}}{{${100.0 * float(depth_equal_first['standard_error']):.1f}$ pp}}",
        f"\\newcommand{{\\BridgeDepthEqualFirstNativeShare}}{{{_pct(1.0 - float(depth_equal_first['coefficient']))}}}",
        f"\\newcommand{{\\BridgeDepthEqualFirstDays}}{{{_integer(float(depth_equal_first['n_observations']))}}}",
        f"\\newcommand{{\\BridgeDepthDoubleFirstShare}}{{{_pct(float(depth_double_first['coefficient']))}}}",
        f"\\newcommand{{\\BridgeDepthDoubleFirstSE}}{{${100.0 * float(depth_double_first['standard_error']):.1f}$ pp}}",
        f"\\newcommand{{\\BridgeDepthDoubleFirstDays}}{{{_integer(float(depth_double_first['n_observations']))}}}",
    ]
    return "\n".join(lines) + "\n"


def render_bridge_establishment_table(estimates: pd.DataFrame) -> str:
    """Render bridge establishment and continuous depth competitiveness."""

    models = (
        ("Stable route share [pp]", "stable_share_after_bridge_establishment", 100.0),
        (
            "Stable supported-value share [pp]",
            "stable_value_share_after_bridge_establishment",
            100.0,
        ),
        (
            "$\\log(1+\\text{native routes per active day})$",
            "native_routes_after_bridge_establishment",
            1.0,
        ),
        (
            "$\\log(1+\\text{total routes per active day})$",
            "total_routes_after_bridge_establishment",
            1.0,
        ),
        (
            "$\\log(1+\\text{native supported value per active day})$",
            "native_value_after_bridge_establishment",
            1.0,
        ),
        (
            "$\\log(1+\\text{total supported value per active day})$",
            "total_value_after_bridge_establishment",
            1.0,
        ),
    )
    event_rows = []
    for label, model_id, scale in models:
        first = _single(
            estimates,
            record_type="bridge_establishment_event_regression",
            model_id=model_id,
            regressor="post_0_29",
        )
        later = _single(
            estimates,
            record_type="bridge_establishment_event_regression",
            model_id=model_id,
            regressor="post_30_119",
        )
        event_rows.append(
            f"{label} & {_estimate_cell(first, scale=scale)} & "
            f"{_estimate_cell(later, scale=scale)} \\\\"
        )
    first_support = _single(
        estimates,
        record_type="bridge_establishment_event_regression",
        model_id="stable_share_after_bridge_establishment",
        regressor="post_0_29",
    )
    later_support = _single(
        estimates,
        record_type="bridge_establishment_event_regression",
        model_id="stable_share_after_bridge_establishment",
        regressor="post_30_119",
    )
    slope_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_on_relative_depth",
        period="post_0_29",
    )
    slope_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_on_relative_depth",
        period="post_30_119",
    )
    equal_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_native",
        period="post_0_29",
    )
    equal_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_native",
        period="post_30_119",
    )
    double_first = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_2x_native",
        period="post_0_29",
    )
    double_later = _single(
        estimates,
        record_type="bridge_establishment_depth_regression",
        model_id="stable_route_share_when_depth_at_least_2x_native",
        period="post_30_119",
    )
    thin_first = _single(
        estimates,
        record_type="bridge_establishment_depth_summary",
        period="post_0_29",
        depth_bin="below_0.1x",
    )
    thin_later = _single(
        estimates,
        record_type="bridge_establishment_depth_summary",
        period="post_30_119",
        depth_bin="below_0.1x",
    )
    timing_shallow_first = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_30_days",
        depth_group="below_0.1x",
    )
    timing_shallow_later = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_120_days",
        depth_group="below_0.1x",
    )
    timing_competitive_first = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_30_days",
        depth_group="at_least_0.1x",
    )
    timing_competitive_later = _single(
        estimates,
        record_type="bridge_establishment_timing_depth_summary",
        model_id="within_120_days",
        depth_group="at_least_0.1x",
    )
    timing_difference_first = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth",
    )
    timing_difference_later = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_120_on_competitive_depth",
    )
    timing_controlled_first = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth_controls",
    )
    timing_controlled_later = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_120_on_competitive_depth_controls",
    )
    timing_no_stable_endpoint_first = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_30_on_competitive_depth_no_stable_endpoint",
    )
    timing_no_stable_endpoint_later = _single(
        estimates,
        record_type="bridge_establishment_timing_regression",
        model_id="adoption_within_120_on_competitive_depth_no_stable_endpoint",
    )
    depth_rows = [
        "Relative-depth slope [pp per +1 pp] & "
        f"{_estimate_cell(slope_first)} & "
        f"{_estimate_cell(slope_later)} \\\\",
        "Stable route share, depth $<0.1\\times$ WETH [\\%] & "
        f"{100.0 * float(thin_first['stable_route_share']):.1f} & "
        f"{100.0 * float(thin_later['stable_route_share']):.1f} \\\\",
        "Stable route share, depth $\\geq$ WETH [\\%] & "
        f"{_level_cell(equal_first)} & {_level_cell(equal_later)} \\\\",
        "Stable route share, depth $\\geq 2\\times$ WETH [\\%] & "
        f"{_level_cell(double_first)} & {_level_cell(double_later)} \\\\",
        "Active ordered-ultimate-pair days & "
        f"{_integer(float(slope_first['n_observations']))} & "
        f"{_integer(float(slope_later['n_observations']))} \\\\",
    ]
    timing_rows = [
        "Stable route observed, depth $<0.1\\times$ WETH [\\%] & "
        f"{100.0 * float(timing_shallow_first['adoption_share']):.1f} & "
        f"{100.0 * float(timing_shallow_later['adoption_share']):.1f} \\\\",
        "Stable route observed, depth $\\geq0.1\\times$ WETH [\\%] & "
        f"{100.0 * float(timing_competitive_first['adoption_share']):.1f} & "
        f"{100.0 * float(timing_competitive_later['adoption_share']):.1f} \\\\",
        "Difference [pp] & "
        f"{_estimate_cell(timing_difference_first, scale=100.0)} & "
        f"{_estimate_cell(timing_difference_later, scale=100.0)} \\\\",
        "Difference with controls [pp] & "
        f"{_estimate_cell(timing_controlled_first, scale=100.0)} & "
        f"{_estimate_cell(timing_controlled_later, scale=100.0)} \\\\",
        "Difference, no stablecoin endpoint [pp] & "
        f"{_estimate_cell(timing_no_stable_endpoint_first, scale=100.0)} & "
        f"{_estimate_cell(timing_no_stable_endpoint_later, scale=100.0)} \\\\",
    ]
    return "\n".join(
        [
            "% Generated by scripts/tabulate/build_bridge_liquidity_deck_values.py; do not edit.",
            "\\begin{tabularx}{\\linewidth}{@{}Xcc@{}}",
            "\\toprule",
            "Outcome & First 30 days & Days 30--119 \\\\",
            "\\midrule",
            "\\multicolumn{3}{@{}l}{\\textit{Panel A. Changes around first persistent stable support}} \\\\",
            *event_rows,
            "\\midrule",
            f"Bridge events & {_integer(float(first_support['events']))} & "
            f"{_integer(float(later_support['events']))} \\\\ ",
            "\\addlinespace[0.35em]",
            "\\multicolumn{3}{@{}l}{\\textit{Panel B. Stable-bridge competitiveness relative to WETH}} \\\\",
            *depth_rows,
            "\\addlinespace[0.35em]",
            "\\multicolumn{3}{@{}l}{\\textit{Panel C. Stable-route adoption after persistent support}} \\\\",
            "Outcome & First 30 days & First 120 days \\\\",
            *timing_rows,
            "\\bottomrule",
            "\\end{tabularx}",
            "",
        ]
    )


def run(
    *,
    estimates_path: Path = ESTIMATES,
    output_path: Path = DECK_VALUES,
    table_path: Path = TABLE_OUTPUT,
) -> int:
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_bridge_liquidity_deck_values(estimates)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    table = render_bridge_establishment_table(estimates)
    with atomic_output(table_path) as temporary:
        temporary.write_text(table, encoding="utf-8")
    print(f"wrote {output_path} and {table_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    parser.add_argument("--table", type=Path, default=TABLE_OUTPUT)
    args = parser.parse_args()
    return run(
        estimates_path=args.estimates,
        output_path=args.output,
        table_path=args.table,
    )


if __name__ == "__main__":
    raise SystemExit(main())
