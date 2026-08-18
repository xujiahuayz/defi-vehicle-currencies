#!/usr/bin/env python3
"""Explore whether stable vehicle use is confined to low-activity markets.

The market-formation results show that vehicle regimes are made at entry and at
the transition edge. This companion screen checks a narrower threat to that
interpretation: the result should not read as if stablecoins only matter in
one-off or dust markets. Rows are descriptive, not causal opportunity-set
effects, because realised market-route counts and first-day entrant size are
themselves outcomes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import common_calendar_day_mask, year_endpoint_change
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


PAIR_SUPPORT_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_pair_support.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_market_size_exploration.jsonl"
CODE_SOURCES = [
    "scripts/analyze/run_vehicle_market_size_exploration.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = ["data/processed/endpoint_candidate_pair_support.parquet"]
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAG_DAYS = 30


def load_pair_support(path: Path = PAIR_SUPPORT_INPUT) -> pd.DataFrame:
    """Load the released pair-support panel columns used by this screen."""

    columns = [
        "date",
        "market_route_count",
        "primary_choice_route_count",
        "native_choice_route_count",
        "stable_choice_route_count",
        "native_within_20pct_value_usd",
        "stable_within_20pct_value_usd",
        "pair_entry_on_day",
    ]
    frame = pd.read_parquet(path, columns=columns)
    return prepare_pair_support(frame)


def prepare_pair_support(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and label pair-day rows with realised activity bins."""

    required = {
        "date",
        "market_route_count",
        "primary_choice_route_count",
        "native_choice_route_count",
        "stable_choice_route_count",
        "native_within_20pct_value_usd",
        "stable_within_20pct_value_usd",
        "pair_entry_on_day",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"pair-support panel lacks columns: {missing}")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"])
    numeric = sorted(required - {"date", "pair_entry_on_day"})
    for column in numeric:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["pair_entry_on_day"] = out["pair_entry_on_day"].astype(bool)
    out = out[
        out["primary_choice_route_count"].gt(0)
        & (out["native_choice_route_count"] + out["stable_choice_route_count"]).gt(0)
    ].copy()
    if out.empty:
        raise ValueError("market-size screen has no supported pair-day rows")
    out["year"] = out["date"].dt.year.astype(int)
    out["size_bin"] = np.select(
        [
            out["market_route_count"].le(5),
            out["market_route_count"].between(6, 100, inclusive="both"),
            out["market_route_count"].gt(100),
        ],
        ["thin_1_5", "middle_6_100", "thick_gt100"],
        default="unsupported",
    )
    out["activity_bin"] = np.select(
        [
            out["market_route_count"].eq(1),
            out["market_route_count"].between(2, 5, inclusive="both"),
            out["market_route_count"].between(6, 20, inclusive="both"),
            out["market_route_count"].between(21, 100, inclusive="both"),
            out["market_route_count"].gt(100),
        ],
        [
            "singleton",
            "two_to_five",
            "six_to_twenty",
            "twenty_one_to_hundred",
            "gt_hundred",
        ],
        default="unsupported",
    )
    return out[out["size_bin"].ne("unsupported")].copy()


def market_size_bin_summaries(pair_support: pd.DataFrame) -> pd.DataFrame:
    """Summarise stable shares within realised market-activity bins."""

    grouped = pair_support.groupby(
        ["year", "size_bin", "activity_bin"], as_index=False, sort=True
    ).agg(
        pair_days=("date", "size"),
        primary_choice_routes=("primary_choice_route_count", "sum"),
        native_choice_routes=("native_choice_route_count", "sum"),
        stable_choice_routes=("stable_choice_route_count", "sum"),
        native_within_20pct_value_usd=("native_within_20pct_value_usd", "sum"),
        stable_within_20pct_value_usd=("stable_within_20pct_value_usd", "sum"),
    )
    grouped["stable_count_share"] = grouped["stable_choice_routes"] / (
        grouped["native_choice_routes"] + grouped["stable_choice_routes"]
    )
    grouped["stable_value_share"] = grouped["stable_within_20pct_value_usd"] / (
        grouped["native_within_20pct_value_usd"]
        + grouped["stable_within_20pct_value_usd"]
    ).replace({0.0: np.nan})
    grouped.insert(0, "analysis_status", "exploratory_descriptive")
    grouped.insert(1, "record_type", "market_size_bin_summary")
    grouped["interpretation"] = (
        "route-weighted stable share by realised pair-day route count bin"
    )
    return grouped


def entry_market_size_summaries(pair_support: pd.DataFrame) -> pd.DataFrame:
    """Summarise entrant stable shares by first-day realised market size.

    The unit is an ordered source-destination pair on its first observed day in
    the matched January-June endpoint window. First-day size is a realised
    outcome, so these rows rule out a dust-only interpretation but do not assign
    entrants to exogenous size bins.
    """

    sample = pair_support[
        pair_support["pair_entry_on_day"]
        & pair_support["year"].isin([BASELINE_YEAR, COMPARISON_YEAR])
        & pair_support["date"].dt.strftime("%m-%d").le("06-30")
    ].copy()
    if sample.empty:
        raise ValueError("entry market-size screen has no entering pair rows")
    grouped = sample.groupby(["year", "size_bin"], as_index=False, sort=True).agg(
        pairs=("date", "size"),
        primary_choice_routes=("primary_choice_route_count", "sum"),
        native_choice_routes=("native_choice_route_count", "sum"),
        stable_choice_routes=("stable_choice_route_count", "sum"),
    )
    grouped["entry_route_mass_share"] = grouped["primary_choice_routes"] / grouped.groupby(
        "year"
    )["primary_choice_routes"].transform("sum")
    grouped["stable_count_share"] = grouped["stable_choice_routes"] / (
        grouped["native_choice_routes"] + grouped["stable_choice_routes"]
    )
    dominant = (
        sample.assign(
            stable_dominant_pair=sample["stable_choice_route_count"]
            > sample["native_choice_route_count"]
        )
        .groupby(["year", "size_bin"], as_index=False, sort=True)[
            "stable_dominant_pair"
        ]
        .mean()
        .rename(columns={"stable_dominant_pair": "stable_dominant_pair_share"})
    )
    grouped = grouped.merge(dominant, on=["year", "size_bin"], how="left", validate="one_to_one")
    grouped.insert(0, "analysis_status", "exploratory_descriptive")
    grouped.insert(1, "record_type", "entry_market_size_summary")
    grouped["entry_year"] = grouped["year"].astype(int)
    grouped["interpretation"] = (
        "stable share at first observed ordered-pair day by first-day realised "
        "market size; descriptive entrant screen, not causal size assignment"
    )
    return grouped


def daily_thin_thick_shares(pair_support: pd.DataFrame) -> pd.DataFrame:
    """Return daily stable shares for <=5-route and >100-route pair-days."""

    sample = pair_support[pair_support["size_bin"].isin(["thin_1_5", "thick_gt100"])]
    grouped = sample.groupby(["date", "year", "size_bin"], as_index=False).agg(
        pair_days=("date", "size"),
        primary_choice_routes=("primary_choice_route_count", "sum"),
        native_choice_routes=("native_choice_route_count", "sum"),
        stable_choice_routes=("stable_choice_route_count", "sum"),
    )
    grouped["stable_count_share"] = grouped["stable_choice_routes"] / (
        grouped["native_choice_routes"] + grouped["stable_choice_routes"]
    )
    wide = grouped.pivot(
        index=["date", "year"],
        columns="size_bin",
        values="stable_count_share",
    ).reset_index()
    required = {"thin_1_5", "thick_gt100"}
    missing = sorted(required - set(wide.columns))
    if missing:
        raise ValueError(f"missing daily market-size share columns: {missing}")
    wide["thick_minus_thin"] = wide["thick_gt100"] - wide["thin_1_5"]
    return wide


def daily_size_gap_changes(daily: pd.DataFrame) -> pd.DataFrame:
    """Estimate endpoint-year changes on a matched calendar with HAC errors."""

    endpoint = daily[daily["year"].between(BASELINE_YEAR, COMPARISON_YEAR)].copy()
    endpoint = endpoint.loc[
        common_calendar_day_mask(
            endpoint["date"],
            endpoint["year"],
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
        )
    ]
    rows: list[dict[str, object]] = []
    for estimand, label in (
        ("thin_1_5", "thin pair-days, <=5 realised routes"),
        ("thick_gt100", "active pair-days, >100 realised routes"),
        ("thick_minus_thin", "active-minus-thin stable-share gap"),
    ):
        estimate = year_endpoint_change(
            endpoint[estimand],
            endpoint["year"],
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
            hac_lag=HAC_LAG_DAYS,
            dates=endpoint["date"],
        )
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "daily_market_size_change",
                "estimand": estimand,
                "label": label,
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "baseline_mean": estimate.baseline_mean,
                "comparison_mean": estimate.comparison_mean,
                "change": estimate.change,
                "change_pp": 100.0 * estimate.change,
                "standard_error": estimate.standard_error,
                "standard_error_pp": 100.0 * estimate.standard_error,
                "t_statistic": estimate.t_statistic,
                "p_value": estimate.p_value,
                "observations": estimate.n_observations,
                "degrees_freedom": estimate.degrees_freedom,
                "covariance": f"newey_west_actual_calendar_day_lag_{HAC_LAG_DAYS}",
                "calendar_support": (
                    "daily observations at month-day positions observed in both endpoint years"
                ),
                "interpretation": (
                    "descriptive realised-market-size screen; size bin is not an instrument"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_vehicle_market_size_exploration(pair_support: pd.DataFrame) -> pd.DataFrame:
    """Build all market-size exhibit rows."""

    prepared = prepare_pair_support(pair_support)
    rows = [
        market_size_bin_summaries(prepared),
        entry_market_size_summaries(prepared),
        daily_size_gap_changes(daily_thin_thick_shares(prepared)),
    ]
    return pd.concat(rows, ignore_index=True, sort=False)


def run(
    *,
    input_path: Path = PAIR_SUPPORT_INPUT,
    output_path: Path = RESULT_OUTPUT,
) -> int:
    pair_support = load_pair_support(input_path)
    result = build_vehicle_market_size_exploration(pair_support)
    write_exhibit(
        result,
        output_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes=(
            "Exploratory descriptive screen of stable vehicle use by realised "
            "ordered-pair-day route-count bins and first-day entrant size."
        ),
    )
    print(f"wrote {output_path} ({len(result):,} rows)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PAIR_SUPPORT_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    args = parser.parse_args()
    return run(input_path=args.input, output_path=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
