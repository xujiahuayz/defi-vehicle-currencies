#!/usr/bin/env python3
"""Build deck macros from the V4 flash-accounting LP mechanism exhibit."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits/v4_flash_lp_mechanism_exploration.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits/v4_flash_lp_deck_values.tex"
HORIZON_DAYS = 120


def _signed_pp(value: float, decimals: int = 2) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ pp"
    return f"${points:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 2) -> str:
    return f"${100 * value:.{decimals}f}$ pp"


def _integer(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _signed_log_points(value: float, p_value: float) -> str:
    return f"${value:+.3f}{_stars(p_value)}$"


def _log_point_se(value: float) -> str:
    return f"${value:.3f}$"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _row(
    estimates: pd.DataFrame,
    *,
    predictor: str,
    outcome: str,
) -> pd.Series:
    return _single(
        estimates,
        horizon_days=HORIZON_DAYS,
        predictor=predictor,
        outcome=outcome,
    )


def render_v4_flash_lp_deck_values(estimates: pd.DataFrame) -> str:
    required = {
        "analysis_status",
        "record_type",
        "horizon_days",
        "predictor",
        "outcome",
        "effect_per_10pp_predictor",
        "standard_error",
        "p_value",
        "n_observations",
        "date_clusters",
    }
    missing = sorted(required - set(estimates.columns))
    if missing:
        raise ValueError(f"V4 flash-LP exhibit missing columns: {missing}")
    if not estimates["analysis_status"].eq("exploratory_mechanism").all():
        raise ValueError("V4 flash-LP rows are not labelled exploratory_mechanism")
    internal_narrow = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_narrow_medium_action_share",
    )
    internal_wide = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_wide_very_wide_action_share",
    )
    internal_flow_narrow = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_narrow_medium_flow_value_share",
    )
    internal_flow_broad = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_broad_flow_value_share",
    )
    multileg_narrow = _row(
        estimates,
        predictor="multi_leg_tx_share",
        outcome="future_narrow_medium_action_share",
    )
    multileg_wide = _row(
        estimates,
        predictor="multi_leg_tx_share",
        outcome="future_wide_very_wide_action_share",
    )
    multileg_flow_narrow = _row(
        estimates,
        predictor="multi_leg_tx_share",
        outcome="future_narrow_medium_flow_value_share",
    )
    multileg_flow_broad = _row(
        estimates,
        predictor="multi_leg_tx_share",
        outcome="future_broad_flow_value_share",
    )
    netting_flow_narrow = _row(
        estimates,
        predictor="netting_reduction_share",
        outcome="future_narrow_medium_flow_value_share",
    )
    netting_flow_broad = _row(
        estimates,
        predictor="netting_reduction_share",
        outcome="future_broad_flow_value_share",
    )
    internal_lp_flow = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_log1p_gross_lp_flow_usd",
    )
    internal_tvl = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_delta_log1p_tvl_usd",
    )
    internal_actions = _row(
        estimates,
        predictor="internal_tx_share",
        outcome="future_log1p_lp_actions",
    )
    if not (
        float(internal_narrow["effect_per_10pp_predictor"]) < 0
        and float(internal_wide["effect_per_10pp_predictor"]) > 0
        and float(internal_flow_narrow["effect_per_10pp_predictor"]) > 0
        and float(internal_flow_broad["effect_per_10pp_predictor"]) < 0
        and float(multileg_narrow["effect_per_10pp_predictor"]) < 0
        and float(multileg_wide["effect_per_10pp_predictor"]) > 0
        and float(multileg_flow_narrow["effect_per_10pp_predictor"]) > 0
        and float(multileg_flow_broad["effect_per_10pp_predictor"]) < 0
        and float(netting_flow_narrow["effect_per_10pp_predictor"]) > 0
        and float(netting_flow_broad["effect_per_10pp_predictor"]) < 0
        and float(internal_tvl["effect_per_10pp_predictor"]) > 0
        and float(internal_actions["effect_per_10pp_predictor"]) > 0
        and float(internal_narrow["p_value"]) < 0.01
        and float(internal_wide["p_value"]) < 0.01
        and float(internal_flow_narrow["p_value"]) < 0.01
        and float(internal_flow_broad["p_value"]) < 0.01
        and float(multileg_narrow["p_value"]) < 0.01
        and float(multileg_wide["p_value"]) < 0.01
        and float(multileg_flow_narrow["p_value"]) < 0.01
        and float(multileg_flow_broad["p_value"]) < 0.01
        and float(netting_flow_narrow["p_value"]) < 0.01
        and float(netting_flow_broad["p_value"]) < 0.01
        and float(internal_tvl["p_value"]) < 0.01
        and float(internal_actions["p_value"]) < 0.01
        and int(internal_wide["n_observations"]) > 1_000
    ):
        raise ValueError("V4 flash-LP range-allocation headline no longer holds")
    lines = [
        "% Generated by scripts/tabulate/build_v4_flash_lp_deck_values.py; do not edit.",
        f"\\newcommand{{\\VFourFlashLpRows}}{{{_integer(int(internal_wide['n_observations']))}}}",
        f"\\newcommand{{\\VFourFlashLpDateClusters}}{{{_integer(int(internal_wide['date_clusters']))}}}",
        f"\\newcommand{{\\VFourFlashInternalLpFlowLongCoef}}{{{_signed_log_points(float(internal_lp_flow['effect_per_10pp_predictor']), float(internal_lp_flow['p_value']))}}}",
        f"\\newcommand{{\\VFourFlashInternalLpFlowLongSE}}{{{_log_point_se(0.1 * float(internal_lp_flow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalTvlLongCoef}}{{{_signed_log_points(float(internal_tvl['effect_per_10pp_predictor']), float(internal_tvl['p_value']))}}}",
        f"\\newcommand{{\\VFourFlashInternalTvlLongSE}}{{{_log_point_se(0.1 * float(internal_tvl['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalActionsLongCoef}}{{{_signed_log_points(float(internal_actions['effect_per_10pp_predictor']), float(internal_actions['p_value']))}}}",
        f"\\newcommand{{\\VFourFlashInternalActionsLongSE}}{{{_log_point_se(0.1 * float(internal_actions['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalNarrowLongCoef}}{{{_signed_pp(float(internal_narrow['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashInternalNarrowLongSE}}{{{_unsigned_pp(0.1 * float(internal_narrow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalWideLongCoef}}{{{_signed_pp(float(internal_wide['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashInternalWideLongSE}}{{{_unsigned_pp(0.1 * float(internal_wide['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalFlowNarrowLongCoef}}{{{_signed_pp(float(internal_flow_narrow['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashInternalFlowNarrowLongSE}}{{{_unsigned_pp(0.1 * float(internal_flow_narrow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashInternalFlowBroadLongCoef}}{{{_signed_pp(float(internal_flow_broad['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashInternalFlowBroadLongSE}}{{{_unsigned_pp(0.1 * float(internal_flow_broad['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegNarrowLongCoef}}{{{_signed_pp(float(multileg_narrow['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegNarrowLongSE}}{{{_unsigned_pp(0.1 * float(multileg_narrow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegWideLongCoef}}{{{_signed_pp(float(multileg_wide['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegWideLongSE}}{{{_unsigned_pp(0.1 * float(multileg_wide['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegFlowNarrowLongCoef}}{{{_signed_pp(float(multileg_flow_narrow['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegFlowNarrowLongSE}}{{{_unsigned_pp(0.1 * float(multileg_flow_narrow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegFlowBroadLongCoef}}{{{_signed_pp(float(multileg_flow_broad['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashMultilegFlowBroadLongSE}}{{{_unsigned_pp(0.1 * float(multileg_flow_broad['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashNettingFlowNarrowLongCoef}}{{{_signed_pp(float(netting_flow_narrow['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashNettingFlowNarrowLongSE}}{{{_unsigned_pp(0.1 * float(netting_flow_narrow['standard_error']))}}}",
        f"\\newcommand{{\\VFourFlashNettingFlowBroadLongCoef}}{{{_signed_pp(float(netting_flow_broad['effect_per_10pp_predictor']))}}}",
        f"\\newcommand{{\\VFourFlashNettingFlowBroadLongSE}}{{{_unsigned_pp(0.1 * float(netting_flow_broad['standard_error']))}}}",
    ]
    return "\n".join(lines) + "\n"


def run(*, estimates_path: Path = ESTIMATES, output_path: Path = DECK_VALUES) -> int:
    require_presentation_source(estimates_path)
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_v4_flash_lp_deck_values(estimates)
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
