#!/usr/bin/env python3
"""Build paper/deck macros from the liquidity-provision behavior exhibit."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_exploration.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_deck_values.tex"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026


def _pct(value: float, decimals: int = 1) -> str:
    return f"{100 * value:.{decimals}f}\\%"


def _ratio(value: float, decimals: int = 1) -> str:
    return f"${value:.{decimals}f}\\times$"


def _integer(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def _signed_pp(value: float, decimals: int = 2) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ pp"
    return f"${points:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 2) -> str:
    return f"${100 * value:.{decimals}f}$ pp"


def _signed_decimal(value: float, decimals: int = 2) -> str:
    if abs(value) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$"
    return f"${value:+.{decimals}f}$"


def _unsigned_decimal(value: float, decimals: int = 2) -> str:
    return f"${value:.{decimals}f}$"


def _signed_percent(value: float, decimals: int = 2) -> str:
    percent = 100 * value
    if abs(percent) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}\\%$"
    return f"${percent:+.{decimals}f}\\%$"


def _unsigned_percent(value: float, decimals: int = 2) -> str:
    return f"${100 * value:.{decimals}f}\\%$"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def render_liquidity_provision_behavior_deck_values(estimates: pd.DataFrame) -> str:
    required = {"analysis_status", "record_type"}
    missing = sorted(required - set(estimates.columns))
    if missing:
        raise ValueError(f"liquidity behavior exhibit missing columns: {missing}")
    if not estimates["analysis_status"].eq("exploratory_descriptive").all():
        raise ValueError("liquidity behavior rows are not labelled exploratory_descriptive")
    annual = estimates[estimates["record_type"].eq("annual_stable_allocation")]
    leaders = _single(estimates, record_type="daily_leader_alignment")
    base = _single(annual, year=BASELINE_YEAR)
    end = _single(annual, year=COMPARISON_YEAR)
    if not (
        float(end["stable_intermediary_route_share"]) > float(base["stable_intermediary_route_share"])
        and float(end["stable_capital_share"]) < float(base["stable_capital_share"])
        and float(leaders["weth_capital_leader_share"]) > 0.99
        and float(leaders["stable_excess_leader_share"]) > 0.75
    ):
        raise ValueError("liquidity behavior headline no longer holds; rewrite the slide")
    episode = _single(
        estimates,
        record_type="level_association",
        outcome="intermediary_episode_share",
        predictor="v2_log1p_deposited_capital_usd",
    )
    excess = _single(
        estimates,
        record_type="level_association",
        outcome="vehicle_excess_use_count_ratio",
        predictor="v2_log1p_deposited_capital_usd",
    )
    if float(episode["coefficient"]) <= 0 or float(excess["coefficient"]) <= 0:
        raise ValueError("capital-use level associations are no longer positive")
    stable_gap_change = _single(
        estimates,
        record_type="daily_route_capital_gap_change",
        gap_name="stable_route_capital_gap",
    )
    weth_gap_change = _single(
        estimates,
        record_type="daily_route_capital_gap_change",
        gap_name="weth_route_capital_gap",
    )
    if not (
        float(stable_gap_change["change"]) > 0
        and float(weth_gap_change["change"]) < 0
    ):
        raise ValueError("daily route-capital gap changes no longer split stable/WETH")
    stable_controlled_gap = _single(
        estimates,
        record_type="within_day_route_capital_gap_association",
        outcome="route_capital_gap_5",
        predictor="is_stable",
    )
    if not (
        float(stable_controlled_gap["coefficient"]) > 0
        and float(stable_controlled_gap["p_value"]) < 0.01
    ):
        raise ValueError("controlled stable route-capital gap premium no longer holds")
    gap_close_month = _single(
        estimates,
        record_type="route_capital_gap_closing",
        horizon_days=30,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="route_capital_gap_5",
    )
    gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_closing",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="route_capital_gap_5",
    )
    if not (
        float(gap_close_month["coefficient"]) > 0
        and float(gap_close_long["coefficient"]) > 0
        and float(gap_close_month["p_value"]) < 0.01
        and float(gap_close_long["p_value"]) < 0.01
    ):
        raise ValueError("route-capital gap-closing pattern no longer holds")
    stable_gap_close_month = _single(
        estimates,
        record_type="route_capital_gap_closing_stable_interaction",
        horizon_days=30,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="stable_total_route_capital_gap_5",
    )
    stable_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_closing_stable_interaction",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="stable_total_route_capital_gap_5",
    )
    stable_overhang_month = _single(
        estimates,
        record_type="route_capital_gap_asymmetry",
        horizon_days=30,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="stable_total_negative_route_capital_gap_5",
    )
    stable_overhang_long = _single(
        estimates,
        record_type="route_capital_gap_asymmetry",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        predictor="stable_total_negative_route_capital_gap_5",
    )
    stable_venue_month = _single(
        estimates,
        record_type="route_capital_gap_extensive_margin",
        horizon_days=30,
        outcome="future_log_venue_count_change",
        predictor="stable_total_route_capital_gap_5",
    )
    stable_venue_long = _single(
        estimates,
        record_type="route_capital_gap_extensive_margin",
        horizon_days=120,
        outcome="future_log_venue_count_change",
        predictor="stable_total_route_capital_gap_5",
    )
    stable_pool_long = _single(
        estimates,
        record_type="route_capital_gap_extensive_margin",
        horizon_days=120,
        outcome="future_log_pool_count_change",
        predictor="stable_total_route_capital_gap_5",
    )
    same_pool_long = _single(
        estimates,
        record_type="route_capital_gap_same_pool_reallocation",
        horizon_days=120,
        outcome="future_log_pool_candidate_capital_change",
        predictor="route_capital_gap_5",
    )
    stable_same_pool_long = _single(
        estimates,
        record_type="route_capital_gap_same_pool_reallocation",
        horizon_days=120,
        outcome="future_log_pool_candidate_capital_change",
        predictor="stable_total_route_capital_gap_5",
    )
    basket_stable_month = _single(
        estimates,
        record_type="stable_basket_gap_portfolio_rebalancing",
        model_id="activity_controls",
        horizon_days=30,
        outcome="future_stable_capital_share_change",
        predictor="stable_route_capital_gap",
    )
    basket_stable_long = _single(
        estimates,
        record_type="stable_basket_gap_portfolio_rebalancing",
        model_id="activity_controls",
        horizon_days=120,
        outcome="future_stable_capital_share_change",
        predictor="stable_route_capital_gap",
    )
    basket_weth_long = _single(
        estimates,
        record_type="stable_basket_gap_portfolio_rebalancing",
        model_id="activity_controls",
        horizon_days=120,
        outcome="future_weth_capital_share_change",
        predictor="stable_route_capital_gap",
    )
    basket_wbtc_long = _single(
        estimates,
        record_type="stable_basket_gap_portfolio_rebalancing",
        model_id="activity_controls",
        horizon_days=120,
        outcome="future_wbtc_capital_share_change",
        predictor="stable_route_capital_gap",
    )
    stable_fee_long = _single(
        estimates,
        record_type="route_capital_gap_v3_fee_incidence",
        horizon_days=120,
        outcome="future_log_fees_change",
        predictor="stable_total_route_capital_gap_5",
    )
    stable_volume_long = _single(
        estimates,
        record_type="route_capital_gap_v3_fee_incidence",
        horizon_days=120,
        outcome="future_log_volume_change",
        predictor="stable_total_route_capital_gap_5",
    )
    usdc_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_candidate_specific",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        candidate_symbol="USDC",
    )
    dai_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_candidate_specific",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        candidate_symbol="DAI",
    )
    usdt_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_candidate_specific",
        horizon_days=120,
        outcome="future_v2_five_candidate_capital_share_change",
        candidate_symbol="USDT",
    )
    usdc_log_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_candidate_specific",
        horizon_days=120,
        outcome="future_v2_log1p_deposited_capital_usd_change",
        candidate_symbol="USDC",
    )
    usdt_log_gap_close_long = _single(
        estimates,
        record_type="route_capital_gap_candidate_specific",
        horizon_days=120,
        outcome="future_v2_log1p_deposited_capital_usd_change",
        candidate_symbol="USDT",
    )
    if not (
        float(stable_gap_close_month["coefficient"]) > float(gap_close_month["coefficient"])
        and float(stable_gap_close_long["coefficient"]) > 0
        and float(stable_gap_close_month["p_value"]) < 0.01
        and float(stable_gap_close_long["p_value"]) < 0.01
    ):
        raise ValueError("stable-specific route-capital gap closing no longer holds")
    if not (
        float(stable_overhang_month["coefficient"]) > 0
        and float(stable_overhang_long["coefficient"]) > 0
        and float(stable_overhang_month["p_value"]) < 0.01
        and float(stable_overhang_long["p_value"]) < 0.01
        and float(stable_overhang_month["effect_per_10pp_stable_overcapitalization"]) < 0
        and float(stable_overhang_long["effect_per_10pp_stable_overcapitalization"]) < 0
    ):
        raise ValueError("stable over-capitalization asymmetry no longer holds")
    if not (
        float(stable_venue_month["coefficient"]) > 0
        and float(stable_venue_long["coefficient"]) > 0
        and float(stable_pool_long["coefficient"]) < 0
        and float(stable_venue_month["p_value"]) < 0.05
        and float(stable_venue_long["p_value"]) < 0.05
        and float(stable_pool_long["p_value"]) < 0.01
    ):
        raise ValueError("stable extensive-margin pattern no longer holds")
    if not (
        float(same_pool_long["coefficient"]) > 0
        and float(same_pool_long["p_value"]) < 0.01
        and float(stable_same_pool_long["p_value"]) > 0.10
        and abs(float(stable_same_pool_long["coefficient"]))
        < abs(float(same_pool_long["coefficient"]))
    ):
        raise ValueError("same-pool capital-chase contrast no longer holds")
    if not (
        float(basket_stable_month["coefficient"]) > 0
        and float(basket_stable_month["p_value"]) < 0.05
        and float(basket_stable_long["coefficient"]) > 0
        and float(basket_stable_long["p_value"]) < 0.01
        and float(basket_weth_long["coefficient"]) < 0
        and float(basket_weth_long["p_value"]) < 0.01
        and abs(float(basket_wbtc_long["coefficient_per_10pp_gap"])) < 0.005
        and float(basket_wbtc_long["p_value"]) > 0.10
    ):
        raise ValueError("stable-basket portfolio rebalancing pattern no longer holds")
    if not (
        float(stable_fee_long["p_value"]) > 0.10
        and float(stable_volume_long["p_value"]) > 0.10
        and abs(float(stable_fee_long["coefficient_per_10pp_gap"])) < 0.02
        and abs(float(stable_volume_long["coefficient_per_10pp_gap"])) < 0.03
    ):
        raise ValueError("stable V3 fee-incidence non-result no longer holds")
    if not (
        float(usdc_gap_close_long["coefficient"]) > float(usdt_gap_close_long["coefficient"])
        and float(dai_gap_close_long["coefficient"]) > float(usdc_gap_close_long["coefficient"])
        and float(usdc_gap_close_long["p_value"]) < 0.01
        and float(dai_gap_close_long["p_value"]) < 0.01
        and float(usdt_gap_close_long["p_value"]) > 0.10
        and float(usdc_log_gap_close_long["coefficient"]) > float(usdt_log_gap_close_long["coefficient"])
        and float(usdc_log_gap_close_long["p_value"]) < 0.01
        and float(usdt_log_gap_close_long["p_value"]) < 0.05
    ):
        raise ValueError("USDC/USDT candidate-specific gap-closing contrast no longer holds")
    lines = [
        "% Generated by scripts/tabulate/build_liquidity_provision_behavior_deck_values.py; do not edit.",
        f"\\newcommand{{\\LiqBehPanelDays}}{{{_integer(int(leaders['days']))}}}",
        f"\\newcommand{{\\LiqBehWethCapitalLeaderDays}}{{{_pct(float(leaders['weth_capital_leader_share']))}}}",
        f"\\newcommand{{\\LiqBehStableExcessLeaderDays}}{{{_pct(float(leaders['stable_excess_leader_share']))}}}",
        f"\\newcommand{{\\LiqBehStableCapitalShareBase}}{{{_pct(float(base['stable_capital_share']))}}}",
        f"\\newcommand{{\\LiqBehStableCapitalShareEnd}}{{{_pct(float(end['stable_capital_share']))}}}",
        f"\\newcommand{{\\LiqBehStableRouteShareBase}}{{{_pct(float(base['stable_intermediary_route_share']))}}}",
        f"\\newcommand{{\\LiqBehStableRouteShareEnd}}{{{_pct(float(end['stable_intermediary_route_share']))}}}",
        f"\\newcommand{{\\LiqBehStableRouteCapitalRatioEnd}}{{{_ratio(float(end['stable_route_to_capital_ratio']))}}}",
        f"\\newcommand{{\\LiqBehLogCapitalEpisodeCoef}}{{{_signed_pp(float(episode['coefficient']))}}}",
        f"\\newcommand{{\\LiqBehLogCapitalEpisodeSE}}{{{_unsigned_pp(float(episode['standard_error']))}}}",
        f"\\newcommand{{\\LiqBehLogCapitalExcessCoef}}{{{_signed_decimal(float(excess['coefficient']))}}}",
        f"\\newcommand{{\\LiqBehLogCapitalExcessSE}}{{{_unsigned_decimal(float(excess['standard_error']))}}}",
        f"\\newcommand{{\\LiqBehStableGapChange}}{{{_signed_pp(float(stable_gap_change['change']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehStableGapChangeSE}}{{{_unsigned_pp(float(stable_gap_change['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehWethGapChange}}{{{_signed_pp(float(weth_gap_change['change']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehWethGapChangeSE}}{{{_unsigned_pp(float(weth_gap_change['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehStableControlledGapCoef}}{{{_signed_pp(float(stable_controlled_gap['coefficient']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehStableControlledGapSE}}{{{_unsigned_pp(float(stable_controlled_gap['standard_error']), decimals=1)}}}",
        f"\\newcommand{{\\LiqBehGapCloseMonthCoef}}{{{_signed_pp(float(gap_close_month['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehGapCloseMonthSE}}{{{_unsigned_pp(float(gap_close_month['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehGapCloseLongCoef}}{{{_signed_pp(float(gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehGapCloseLongSE}}{{{_unsigned_pp(float(gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableGapCloseMonthCoef}}{{{_signed_pp(float(stable_gap_close_month['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableGapCloseMonthSE}}{{{_unsigned_pp(float(stable_gap_close_month['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableGapCloseLongCoef}}{{{_signed_pp(float(stable_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableGapCloseLongSE}}{{{_unsigned_pp(float(stable_gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableOverhangMonthCoef}}{{{_signed_pp(float(stable_overhang_month['effect_per_10pp_stable_overcapitalization']))}}}",
        f"\\newcommand{{\\LiqBehStableOverhangMonthSE}}{{{_unsigned_pp(float(stable_overhang_month['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableOverhangLongCoef}}{{{_signed_pp(float(stable_overhang_long['effect_per_10pp_stable_overcapitalization']))}}}",
        f"\\newcommand{{\\LiqBehStableOverhangLongSE}}{{{_unsigned_pp(float(stable_overhang_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVenueMonthCoef}}{{{_signed_percent(float(stable_venue_month['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVenueMonthSE}}{{{_unsigned_percent(float(stable_venue_month['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVenueLongCoef}}{{{_signed_percent(float(stable_venue_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVenueLongSE}}{{{_unsigned_percent(float(stable_venue_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStablePoolLongCoef}}{{{_signed_percent(float(stable_pool_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStablePoolLongSE}}{{{_unsigned_percent(float(stable_pool_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehSamePoolLongCoef}}{{{_signed_percent(float(same_pool_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehSamePoolLongSE}}{{{_unsigned_percent(float(same_pool_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableSamePoolLongCoef}}{{{_signed_percent(float(stable_same_pool_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableSamePoolLongSE}}{{{_unsigned_percent(float(stable_same_pool_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableBasketGapMonthCoef}}{{{_signed_pp(float(basket_stable_month['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableBasketGapMonthSE}}{{{_unsigned_pp(float(basket_stable_month['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableBasketGapLongCoef}}{{{_signed_pp(float(basket_stable_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableBasketGapLongSE}}{{{_unsigned_pp(float(basket_stable_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehWethBasketGapLongCoef}}{{{_signed_pp(float(basket_weth_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehWethBasketGapLongSE}}{{{_unsigned_pp(float(basket_weth_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehWbtcBasketGapLongCoef}}{{{_signed_pp(float(basket_wbtc_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehWbtcBasketGapLongSE}}{{{_unsigned_pp(float(basket_wbtc_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehFeeIncidenceRows}}{{{_integer(int(stable_fee_long['n_observations']))}}}",
        f"\\newcommand{{\\LiqBehFeeIncidencePools}}{{{_integer(int(stable_fee_long['pool_count']))}}}",
        f"\\newcommand{{\\LiqBehStableFeeLongCoef}}{{{_signed_percent(float(stable_fee_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableFeeLongSE}}{{{_unsigned_percent(float(stable_fee_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVolumeLongCoef}}{{{_signed_percent(float(stable_volume_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehStableVolumeLongSE}}{{{_unsigned_percent(float(stable_volume_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdcGapCloseLongCoef}}{{{_signed_pp(float(usdc_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdcGapCloseLongSE}}{{{_unsigned_pp(float(usdc_gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehDaiGapCloseLongCoef}}{{{_signed_pp(float(dai_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehDaiGapCloseLongSE}}{{{_unsigned_pp(float(dai_gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdtGapCloseLongCoef}}{{{_signed_pp(float(usdt_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdtGapCloseLongSE}}{{{_unsigned_pp(float(usdt_gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdcLogGapCloseLongCoef}}{{{_signed_percent(float(usdc_log_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdcLogGapCloseLongSE}}{{{_unsigned_percent(float(usdc_log_gap_close_long['standard_error_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdtLogGapCloseLongCoef}}{{{_signed_percent(float(usdt_log_gap_close_long['coefficient_per_10pp_gap']))}}}",
        f"\\newcommand{{\\LiqBehUsdtLogGapCloseLongSE}}{{{_unsigned_percent(float(usdt_log_gap_close_long['standard_error_per_10pp_gap']))}}}",
    ]
    return "\n".join(lines) + "\n"


def run(*, estimates_path: Path = ESTIMATES, output_path: Path = DECK_VALUES) -> int:
    require_presentation_source(estimates_path)
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_liquidity_provision_behavior_deck_values(estimates)
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
