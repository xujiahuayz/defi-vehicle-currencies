#!/usr/bin/env python3
"""Decompose the stable-to-stable endpoint channel by intermediary identity."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.asset_types import STABLE
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CHOICES_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/stable_stable_vehicle_decomposition.jsonl"
ROBUSTNESS_OUTPUT = OUTPUT_DIR / "exhibits/stable_stable_vehicle_robustness.jsonl"
CODE_SOURCES = [
    "scripts/analyze/run_stable_stable_vehicle_decomposition.py",
    "src/ddvc/asset_types.py",
]
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
INTERMEDIARY_GROUPS = ("native", "usdt", "usdc", "dai", "other_stable")
METRICS = {
    "route_count": "count_share",
    "within_20pct_value_usd": "strict_intermediation_value_share",
}


def load_stable_stable_cells(path: Path = CHOICES_INPUT) -> pd.DataFrame:
    """Load stable-endpoint routes with their full-day comparison denominators."""

    stable_tokens = pd.DataFrame(
        [{"address": address.lower()} for address in STABLE]
    )
    with duckdb.connect() as connection:
        connection.register("stable_tokens", stable_tokens)
        escaped = str(path).replace("'", "''")
        return connection.execute(
            f"""
            WITH eligible AS (
                SELECT
                    CAST(date AS DATE) AS date,
                    YEAR(date)::INTEGER AS year,
                    STRFTIME(date, '%m-%d') AS month_day,
                    candidate_symbol,
                    candidate_type,
                    route_count,
                    within_20pct_value_usd,
                    src,
                    tgt
                FROM READ_PARQUET('{escaped}')
                WHERE YEAR(date) IN ({BASELINE_YEAR}, {COMPARISON_YEAR})
                  AND STRFTIME(date, '%m-%d') <= '06-30'
                  AND candidate_type IN ('native', 'stable')
            ),
            daily_totals AS (
                SELECT
                    date,
                    SUM(route_count)::DOUBLE AS daily_total_route_count,
                    SUM(within_20pct_value_usd)::DOUBLE
                        AS daily_total_within_20pct_value_usd
                FROM eligible
                GROUP BY date
            ),
            stable_endpoints AS (
                SELECT
                    e.date,
                    e.year,
                    e.month_day,
                    e.candidate_symbol,
                    e.candidate_type,
                    SUM(e.route_count)::DOUBLE AS route_count,
                    SUM(e.within_20pct_value_usd)::DOUBLE AS within_20pct_value_usd
                FROM eligible AS e
                JOIN stable_tokens AS src_stable ON LOWER(e.src) = src_stable.address
                JOIN stable_tokens AS tgt_stable ON LOWER(e.tgt) = tgt_stable.address
                GROUP BY ALL
            )
            SELECT s.*, t.daily_total_route_count,
                   t.daily_total_within_20pct_value_usd
            FROM stable_endpoints AS s
            JOIN daily_totals AS t USING(date)
            ORDER BY s.date, s.candidate_type, s.candidate_symbol
            """
        ).fetchdf()


def _intermediary_group(candidate_type: object, candidate_symbol: object) -> str:
    if candidate_type == "native":
        return "native"
    symbol = str(candidate_symbol).upper()
    return symbol.lower() if symbol in {"USDT", "USDC", "DAI"} else "other_stable"


def stable_stable_vehicle_decomposition(
    cells: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return exact issuer contributions and day-concentration checks."""

    required = {
        "date",
        "year",
        "month_day",
        "candidate_symbol",
        "candidate_type",
        "route_count",
        "within_20pct_value_usd",
        "daily_total_route_count",
        "daily_total_within_20pct_value_usd",
    }
    missing = sorted(required - set(cells.columns))
    if missing:
        raise ValueError(f"stable-to-stable cells lack columns: {missing}")
    data = cells.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    if not data["year"].isin((BASELINE_YEAR, COMPARISON_YEAR)).all():
        raise ValueError("stable-to-stable cells contain an unexpected year")
    if not data["candidate_type"].isin(("native", "stable")).all():
        raise ValueError("stable-to-stable cells contain an unexpected candidate type")
    numeric = [*METRICS, "daily_total_route_count", "daily_total_within_20pct_value_usd"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"stable-to-stable cells contain invalid {column}")
    for column in ("daily_total_route_count", "daily_total_within_20pct_value_usd"):
        if data.groupby("date", observed=True)[column].nunique().ne(1).any():
            raise ValueError(f"stable-to-stable daily denominator {column} is not invariant")
        if data[column].le(0).any():
            raise ValueError(f"stable-to-stable daily denominator {column} is nonpositive")

    calendars = {
        year: set(data.loc[data["year"].eq(year), "month_day"])
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    }
    common_days = sorted(calendars[BASELINE_YEAR] & calendars[COMPARISON_YEAR])
    if not common_days:
        raise ValueError("stable-to-stable cells have no common calendar days")
    data = data[data["month_day"].isin(common_days)].copy()
    data["intermediary_group"] = [
        _intermediary_group(candidate_type, candidate_symbol)
        for candidate_type, candidate_symbol in zip(
            data["candidate_type"], data["candidate_symbol"], strict=True
        )
    ]

    contribution_records: list[dict[str, object]] = []
    robustness_records: list[dict[str, object]] = []
    dates = sorted(data["date"].unique())
    complete_index = pd.MultiIndex.from_product(
        [dates, INTERMEDIARY_GROUPS], names=["date", "intermediary_group"]
    )
    for value_column, metric in METRICS.items():
        denominator_column = (
            "daily_total_route_count"
            if value_column == "route_count"
            else "daily_total_within_20pct_value_usd"
        )
        daily = (
            data.groupby(["date", "year", "intermediary_group"], as_index=False)
            .agg(
                intermediary_mass=(value_column, "sum"),
                daily_total=(denominator_column, "first"),
            )
        )
        complete = (
            daily.set_index(["date", "intermediary_group"])[
                ["year", "intermediary_mass", "daily_total"]
            ]
            .reindex(complete_index)
            .reset_index()
        )
        complete["year"] = complete["date"].dt.year.astype(int)
        daily_denominators = data.groupby("date", observed=True)[denominator_column].first()
        complete["daily_total"] = complete["date"].map(daily_denominators)
        complete["intermediary_mass"] = complete["intermediary_mass"].fillna(0.0)
        complete["daily_contribution"] = (
            complete["intermediary_mass"] / complete["daily_total"]
        )
        means = complete.groupby(["year", "intermediary_group"], observed=True).agg(
            stable_share_contribution=("daily_contribution", "mean"),
            raw_mass=("intermediary_mass", "sum"),
            active_days=("intermediary_mass", lambda values: int(values.gt(0).sum())),
        )
        stable_channel_daily = (
            complete[
                complete["intermediary_group"].ne("native")
            ].groupby(["year", "date"], observed=True)
            .agg(
                stable_contribution=("daily_contribution", "sum"),
                stable_mass=("intermediary_mass", "sum"),
                daily_total=("daily_total", "first"),
            )
            .reset_index()
        )
        stable_channel_means = stable_channel_daily.groupby("year", observed=True)[
            "stable_contribution"
        ].mean()

        for intermediary_group in INTERMEDIARY_GROUPS:
            base = means.loc[(BASELINE_YEAR, intermediary_group)]
            end = means.loc[(COMPARISON_YEAR, intermediary_group)]
            change = float(end["stable_share_contribution"] - base["stable_share_contribution"])
            contribution_records.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "metric": metric,
                    "intermediary_group": intermediary_group,
                    "baseline_year": BASELINE_YEAR,
                    "comparison_year": COMPARISON_YEAR,
                    "common_calendar_days": len(common_days),
                    "stable_share_contribution_baseline": float(
                        base["stable_share_contribution"]
                    ),
                    "stable_share_contribution_comparison": float(
                        end["stable_share_contribution"]
                    ),
                    "stable_share_contribution_change": change,
                    "raw_mass_baseline": float(base["raw_mass"]),
                    "raw_mass_comparison": float(end["raw_mass"]),
                    "active_days_baseline": int(base["active_days"]),
                    "active_days_comparison": int(end["active_days"]),
                    "stable_channel_change_share": (
                        change
                        / float(
                            stable_channel_means.loc[COMPARISON_YEAR]
                            - stable_channel_means.loc[BASELINE_YEAR]
                        )
                        if intermediary_group != "native"
                        else None
                    ),
                    "estimand": (
                        "equal-weighted common-calendar contribution of the named "
                        "intermediary group inside stable-to-stable endpoint routes"
                    ),
                    "interpretation": (
                        "descriptive intermediary-identity concentration; route activity "
                        "and the endpoint set are endogenous"
                    ),
                }
            )

        for year in (BASELINE_YEAR, COMPARISON_YEAR):
            year_daily = stable_channel_daily[
                stable_channel_daily["year"].eq(year)
            ].sort_values("stable_contribution", ascending=False)
            trim_count = max(1, math.floor(0.10 * len(year_daily)))
            robustness_records.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "metric": metric,
                    "year": year,
                    "common_calendar_days": len(common_days),
                    "active_days": int(year_daily["stable_mass"].gt(0).sum()),
                    "equal_day_mean_stable_contribution": float(
                        year_daily["stable_contribution"].mean()
                    ),
                    "median_day_stable_contribution": float(
                        year_daily["stable_contribution"].median()
                    ),
                    "top_decile_trimmed_mean_stable_contribution": float(
                        year_daily.iloc[trim_count:]["stable_contribution"].mean()
                    ),
                    "pooled_mass_stable_contribution": float(
                        year_daily["stable_mass"].sum()
                        / year_daily["daily_total"].sum()
                    ),
                    "trimmed_days": trim_count,
                    "interpretation": (
                        "day-concentration and pooled-mass sensitivity for the stable "
                        "intermediary contribution inside stable-to-stable endpoints"
                    ),
                }
            )

        stable_rows = [
            row
            for row in contribution_records
            if row["metric"] == metric and row["intermediary_group"] != "native"
        ]
        for suffix, year in (
            ("baseline", BASELINE_YEAR),
            ("comparison", COMPARISON_YEAR),
        ):
            observed = sum(
                float(row[f"stable_share_contribution_{suffix}"])
                for row in stable_rows
            )
            expected = float(stable_channel_means.loc[year])
            if not np.isclose(observed, expected, atol=1e-10):
                raise ValueError(f"{metric}/{year} stable issuer contributions do not reconcile")

    return (
        pd.DataFrame.from_records(contribution_records),
        pd.DataFrame.from_records(robustness_records),
    )


def run_stable_stable_vehicle_decomposition(
    *,
    choices_path: Path = CHOICES_INPUT,
    result_path: Path = RESULT_OUTPUT,
    robustness_path: Path = ROBUSTNESS_OUTPUT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cells = load_stable_stable_cells(choices_path)
    results, robustness = stable_stable_vehicle_decomposition(cells)
    write_exhibit(
        results,
        result_path,
        code_sources=CODE_SOURCES,
        inputs=[choices_path],
        notes=(
            "Exact common-calendar intermediary-identity decomposition inside "
            "stable-to-stable endpoint routes."
        ),
    )
    write_exhibit(
        robustness,
        robustness_path,
        code_sources=CODE_SOURCES,
        inputs=[choices_path, result_path],
        notes=(
            "Day-concentration, top-decile trim, and pooled-mass sensitivities for "
            "the stable intermediary contribution inside stable-to-stable routes."
        ),
    )
    return results, robustness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--results", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--robustness", type=Path, default=ROBUSTNESS_OUTPUT)
    args = parser.parse_args()
    results, robustness = run_stable_stable_vehicle_decomposition(
        choices_path=args.choices,
        result_path=args.results,
        robustness_path=args.robustness,
    )
    print(results.to_string(index=False))
    print(robustness.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
