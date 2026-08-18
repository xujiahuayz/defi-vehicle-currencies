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
    ]
    return "\n".join(lines) + "\n"


def run(
    *,
    estimates_path: Path = ESTIMATES,
    output_path: Path = DECK_VALUES,
) -> int:
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_bridge_liquidity_deck_values(estimates)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(estimates_path=args.estimates, output_path=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
