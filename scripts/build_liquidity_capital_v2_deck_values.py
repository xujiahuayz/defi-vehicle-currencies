#!/usr/bin/env python3
"""Build presentation macros from the V2 capital-predictability adjudication."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_certified_presentation_source
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits" / "liquidity_capital_v2_predictability.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits" / "liquidity_capital_v2_deck_values.tex"
CODE_SOURCES = ["scripts/build_liquidity_capital_v2_deck_values.py"]
PRIMARY_HORIZONS = (1, 7, 30)
LONG_HORIZON = 120
DISPLAY_PAIR = "intermediary_episode_share__log_deposited_capital"
MEASURE_PAIRS = (
    "intermediary_episode_share__log_deposited_capital",
    "intermediary_episode_share__five_candidate_capital_share",
    "vehicle_excess_use_count_ratio__log_deposited_capital",
    "vehicle_excess_use_count_ratio__five_candidate_capital_share",
)
DIRECTIONS = ("route_to_capital", "capital_to_route")
REQUIRED_COLUMNS = {
    "perimeter",
    "horizon_days",
    "primary_horizon",
    "direction",
    "measure_pair_id",
    "capital_measure",
    "coefficient",
    "standard_error",
    "p_value",
    "p_value_holm",
    "month_block_bootstrap_p_value",
    "candidate_clusters",
    "calendar_span_days",
    "fixed_effects",
    "interpretation",
    "analysis_role",
    "reciprocal_pair_pass",
    "claim_decision_pass",
}


def _signed_pp(value: float, decimals: int = 2) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ pp"
    return f"${points:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 2) -> str:
    return f"${100 * value:.{decimals}f}$ pp"


def _signed_logpct_per_point(value: float) -> str:
    # A log-point coefficient on a share in [0, 1], rescaled to one share point
    # and expressed in percent, equals the coefficient numerically.
    if abs(value) < 0.005:
        return "$0.00$\\%"
    return f"${value:+.2f}$\\%"


def _unsigned_logpct_per_point(value: float) -> str:
    return f"${value:.2f}$\\%"


def _decimal(value: float) -> str:
    return f"${value:.2f}$"


def _integer(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def _full_calendar(estimates: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED_COLUMNS - set(estimates.columns))
    if missing:
        raise ValueError(f"predictability exhibit missing columns: {', '.join(missing)}")
    full = estimates[estimates["perimeter"].eq("full_v2_calendar")].copy()
    if full.empty:
        raise ValueError("predictability exhibit has no full-calendar rows")
    if not full["fixed_effects"].eq("candidate_and_origin_date").all():
        raise ValueError("predictability rows use unexpected fixed effects")
    if not full["interpretation"].eq(
        "temporally_ordered_predictability_not_causal_feedback"
    ).all():
        raise ValueError("predictability rows carry a causal interpretation label")
    if not full["candidate_clusters"].eq(5).all():
        raise ValueError("predictability rows do not use the five-candidate panel")
    return full


def _adjudicated(full: pd.DataFrame) -> pd.DataFrame:
    primary = full[full["primary_horizon"]]
    expected = len(MEASURE_PAIRS) * len(DIRECTIONS) * len(PRIMARY_HORIZONS)
    if len(primary) != expected:
        raise ValueError(
            f"expected {expected} adjudicated cells; found {len(primary)}"
        )
    for pair_id in MEASURE_PAIRS:
        for horizon in PRIMARY_HORIZONS:
            cell = primary[
                primary["measure_pair_id"].eq(pair_id)
                & primary["horizon_days"].eq(horizon)
            ]
            if set(cell["direction"]) != set(DIRECTIONS):
                raise ValueError(
                    f"adjudicated pair is incomplete: {pair_id}, {horizon}"
                )
    numeric = ["coefficient", "standard_error", "p_value_holm"]
    if not all(
        math.isfinite(float(value))
        for column in numeric
        for value in primary[column]
    ):
        raise ValueError("adjudicated cells contain a non-finite estimate")
    if primary["claim_decision_pass"].astype(bool).any() or primary[
        "reciprocal_pair_pass"
    ].astype(bool).any():
        raise ValueError(
            "a reciprocal predictability pair now passes; rewrite the deck frame "
            "before regenerating its values"
        )
    if float(primary["p_value_holm"].min()) < 0.05:
        raise ValueError(
            "an adjudicated cell is Holm-significant; rewrite the deck frame "
            "before regenerating its values"
        )
    return primary


def _long_horizon(full: pd.DataFrame) -> pd.Series:
    long_rows = full[full["horizon_days"].eq(LONG_HORIZON)]
    expected = len(MEASURE_PAIRS) * len(DIRECTIONS)
    if len(long_rows) != expected:
        raise ValueError(
            f"expected {expected} long-horizon cells; found {len(long_rows)}"
        )
    if not long_rows["analysis_role"].eq("long_horizon_sensitivity").all():
        raise ValueError("long-horizon rows are not labelled as sensitivity")
    episode = long_rows[
        long_rows["direction"].eq("capital_to_route")
        & long_rows["measure_pair_id"].str.startswith("intermediary_episode_share__")
    ]
    if len(episode) != 2:
        raise ValueError("long-horizon capital-to-route episode cells are incomplete")
    negative_significant = episode["coefficient"].lt(0) & episode["p_value"].lt(0.05)
    if not negative_significant.all():
        raise ValueError(
            "the long-horizon negative capital-to-route pattern no longer holds "
            "under both capital measures; rewrite the deck frame"
        )
    displayed = episode[episode["measure_pair_id"].eq(DISPLAY_PAIR)]
    if len(displayed) != 1:
        raise ValueError("the displayed long-horizon cell is missing")
    return displayed.iloc[0]


def _cell(primary: pd.DataFrame, direction: str, horizon: int) -> pd.Series:
    selected = primary[
        primary["measure_pair_id"].eq(DISPLAY_PAIR)
        & primary["direction"].eq(direction)
        & primary["horizon_days"].eq(horizon)
    ]
    if len(selected) != 1:
        raise ValueError(f"displayed cell is missing: {direction}, {horizon}")
    return selected.iloc[0]


def render_liquidity_capital_v2_deck_values(estimates: pd.DataFrame) -> str:
    """Render empirical cells while keeping evidence identity out of the PDF."""

    full = _full_calendar(estimates)
    primary = _adjudicated(full)
    long_cell = _long_horizon(full)
    cap_route_day = _cell(primary, "capital_to_route", 1)
    cap_route_month = _cell(primary, "capital_to_route", 30)
    route_cap_day = _cell(primary, "route_to_capital", 1)
    route_cap_month = _cell(primary, "route_to_capital", 30)
    span_days = int(primary["calendar_span_days"].max())
    lines = [
        "% Generated by scripts/build_liquidity_capital_v2_deck_values.py; do not edit.",
        f"\\newcommand{{\\LiqPredCapRouteDayCoef}}{{{_signed_pp(float(cap_route_day['coefficient']))}}}",
        f"\\newcommand{{\\LiqPredCapRouteDaySE}}{{{_unsigned_pp(float(cap_route_day['standard_error']))}}}",
        f"\\newcommand{{\\LiqPredCapRouteMonthCoef}}{{{_signed_pp(float(cap_route_month['coefficient']))}}}",
        f"\\newcommand{{\\LiqPredCapRouteMonthSE}}{{{_unsigned_pp(float(cap_route_month['standard_error']))}}}",
        f"\\newcommand{{\\LiqPredRouteCapDayCoef}}{{{_signed_logpct_per_point(float(route_cap_day['coefficient']))}}}",
        f"\\newcommand{{\\LiqPredRouteCapDaySE}}{{{_unsigned_logpct_per_point(float(route_cap_day['standard_error']))}}}",
        f"\\newcommand{{\\LiqPredRouteCapMonthCoef}}{{{_signed_logpct_per_point(float(route_cap_month['coefficient']))}}}",
        f"\\newcommand{{\\LiqPredRouteCapMonthSE}}{{{_unsigned_logpct_per_point(float(route_cap_month['standard_error']))}}}",
        f"\\newcommand{{\\LiqPredLongCapRouteCoef}}{{{_signed_pp(float(long_cell['coefficient']))}}}",
        f"\\newcommand{{\\LiqPredLongCapRouteSE}}{{{_unsigned_pp(float(long_cell['standard_error']))}}}",
        f"\\newcommand{{\\LiqPredMinHolm}}{{{_decimal(float(primary['p_value_holm'].min()))}}}",
        f"\\newcommand{{\\LiqPredSpanDays}}{{{_integer(span_days)}}}",
    ]
    return "\n".join(lines) + "\n"


def run(*, estimates_path: Path = ESTIMATES, output_path: Path = DECK_VALUES) -> int:
    provenance_path = require_certified_presentation_source(estimates_path)
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_liquidity_capital_v2_deck_values(estimates)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    stamp(
        output_path,
        code_sources=CODE_SOURCES,
        inputs=[estimates_path, provenance_path],
        rows=len(estimates),
        notes=(
            "Presentation macros for the V2 deposited-capital predictability "
            "adjudication; evidence status and identities remain source-only."
        ),
    )
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
