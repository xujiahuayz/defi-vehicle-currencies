#!/usr/bin/env python3
"""Estimate first vehicle choice after both vehicle families become feasible.

This is distinct from original endpoint-pair entry.  The cohort begins with
materially active entrants, then follows each pair to its first sampled date in
the monthly exact-state panel on which both a WETH path and a DAI/USDC/USDT path
are feasible for an observed route under the common support rules.  Every
eligible route on that first contestable date enters the route-level choice
models, with endpoint-pair and date clustered inference.

The result asks two questions.  First, do exact output and prior-calendar
weak-leg V2 capital explain stablecoin selection once a two-family opportunity
set exists?  Second, does the vehicle family used at pair entry retain the route
when that first genuine contest arrives?  Entry-to-contestability lags and both
route- and pair-weighted retention rates travel with the estimates.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import PRIMARY_REPO_ROOT, REPO_ROOT
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_contestable_vehicle_choice import (
    MAX_LINEAR_ADVANTAGE_BPS,
    QUOTED_STABLES,
    QUOTED_VEHICLES,
    QUOTED_LEG_MAX_PRICE_IMPACT,
    WETH,
)
from scripts.analyze.run_entry_day_vehicle_choice import (
    DEFAULT_MIN_ENTRY_VALUE_USD,
    END,
    MIN_ROUTE_INPUT_USD,
    POOL_CAPITAL,
    START,
    _fit_entry_model,
    attach_entry_capital,
    load_material_entries,
)


PRIMARY_DATA_DIR = PRIMARY_REPO_ROOT / "data"
FRONTIER = PRIMARY_DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
PANEL = REPO_ROOT / "data/processed/first_contestable_vehicle_choice.parquet"
OUTPUT = REPO_ROOT / "output/exhibits/first_contestable_vehicle_choice.jsonl"
SUPPORT = REPO_ROOT / "output/exhibits/first_contestable_vehicle_choice_support.jsonl"
CODE_SOURCES = [
    "scripts/analyze/run_first_contestable_vehicle_choice.py",
    "scripts/analyze/run_entry_day_vehicle_choice.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/exact_vehicle_frontier_monthly.parquet",
    "data/processed/pool_capital_daily.parquet",
]


def first_contestable_routes(
    frontier_path: Path,
    entries: pd.DataFrame,
) -> pd.DataFrame:
    """Return all exact routes on each pair's first sampled contestable date."""

    connection = duckdb.connect()
    try:
        connection.register("material_entries", entries)
        panel = connection.execute(
            """
            WITH exact_supported AS (
                SELECT
                    strptime(f.day, '%Y%m%d')::DATE AS exact_date,
                    f.day,
                    f.route_id,
                    lower(f.token_in) AS token_in,
                    lower(f.token_out) AS token_out,
                    lower(f.chosen_vehicle) AS chosen_vehicle,
                    f.chosen_vehicle_type,
                    f.input_usd,
                    f.output_usd,
                    f.within_20pct,
                    f.chosen_max_price_impact,
                    f.vehicle_families_contestable,
                    f.stable_minus_native_bps,
                    f.native_public_out,
                    lower(f.native_public_vehicle) AS native_public_vehicle,
                    f.native_public_venues,
                    f.stable_public_out,
                    lower(f.stable_public_vehicle) AS stable_public_vehicle,
                    f.stable_public_venues
                FROM read_parquet(?) f
                WHERE f.within_20pct
                  AND f.input_usd >= ?
                  AND f.output_usd > 0
                  AND f.chosen_max_price_impact <= ?
                  AND f.vehicle_families_contestable
                  AND f.native_public_out > 0
                  AND f.stable_public_out > 0
                  AND lower(f.native_public_vehicle) = ?
                  AND lower(f.stable_public_vehicle) IN (?, ?, ?)
                  AND lower(f.chosen_vehicle) IN (?, ?, ?, ?)
                  AND f.chosen_vehicle_type IN ('native', 'stable')
            ),
            joined AS (
                SELECT
                    e.day AS entry_day,
                    e.entry_date,
                    e.token_in,
                    e.token_out,
                    e.ordered_pair,
                    e.entry_primary_routes,
                    e.entry_native_routes,
                    e.entry_stable_routes,
                    e.entry_stable_share,
                    e.entry_stable,
                    e.entry_tie,
                    e.entry_exclusive,
                    e.entry_mixed,
                    e.entry_coherent_routes,
                    e.entry_coherent_value_usd,
                    x.exact_date,
                    x.day,
                    x.route_id,
                    x.chosen_vehicle,
                    x.chosen_vehicle_type,
                    x.input_usd,
                    x.output_usd,
                    x.within_20pct,
                    x.chosen_max_price_impact,
                    x.vehicle_families_contestable,
                    x.stable_minus_native_bps,
                    x.native_public_out,
                    x.native_public_vehicle,
                    x.native_public_venues,
                    x.stable_public_out,
                    x.stable_public_vehicle,
                    x.stable_public_venues,
                    min(x.exact_date) OVER (
                        PARTITION BY x.token_in, x.token_out
                    ) AS first_contestable_date
                FROM exact_supported x
                JOIN material_entries e
                  ON x.token_in = e.token_in
                 AND x.token_out = e.token_out
                WHERE x.exact_date >= e.entry_date
            )
            SELECT *
            FROM joined
            WHERE exact_date = first_contestable_date
            ORDER BY exact_date, token_in, token_out, route_id
            """,
            [
                str(frontier_path),
                MIN_ROUTE_INPUT_USD,
                QUOTED_LEG_MAX_PRICE_IMPACT,
                WETH,
                *sorted(QUOTED_STABLES),
                *sorted(QUOTED_VEHICLES),
            ],
        ).fetchdf()
    finally:
        connection.close()
    if panel.empty:
        raise ValueError("material entrants have no sampled exact contestable date")
    if panel["route_id"].duplicated().any():
        raise ValueError("first-contestable panel contains duplicated route ids")
    panel["ordered_pair"] = (
        panel["token_in"].astype(str) + ">" + panel["token_out"].astype(str)
    )
    panel["route_scope"] = (
        panel["native_public_venues"].astype(str)
        + "||"
        + panel["stable_public_venues"].astype(str)
    )
    panel["chosen_stable"] = panel["chosen_vehicle_type"].eq("stable").astype(float)
    panel["entry_to_contestability_days"] = (
        pd.to_datetime(panel["first_contestable_date"])
        - pd.to_datetime(panel["entry_date"])
    ).dt.days
    panel["entry_vehicle_retained"] = np.where(
        panel["entry_stable"].notna(),
        panel["chosen_stable"].eq(panel["entry_stable"]).astype(float),
        np.nan,
    )
    return panel.reset_index(drop=True)


def attach_oriented_variables(panel: pd.DataFrame, capital_path: Path) -> pd.DataFrame:
    """Attach capital and orient price/depth toward the vehicle used at entry."""

    data = attach_entry_capital(panel, capital_path)
    gap = pd.to_numeric(data["stable_minus_native_bps"], errors="coerce")
    native_relative_to_stable = np.divide(
        -10_000.0 * gap,
        10_000.0 + gap,
        out=np.full(len(data), np.nan),
        where=(10_000.0 + gap).abs().gt(1e-12),
    )
    entry_advantage_bps = np.where(
        data["entry_stable"].eq(1.0), gap, native_relative_to_stable
    )
    data["entry_vehicle_output_advantage_100bp"] = (
        np.clip(
            entry_advantage_bps,
            -MAX_LINEAR_ADVANTAGE_BPS,
            MAX_LINEAR_ADVANTAGE_BPS,
        )
        / 100.0
    )
    entry_capital_share = np.where(
        data["entry_stable"].eq(1.0),
        data["stable_v2_capital_share"],
        1.0 - data["stable_v2_capital_share"],
    )
    data["entry_vehicle_v2_capital_share_10pp"] = (
        entry_capital_share - 0.5
    ) / 0.10
    return data


def choice_results(panel: pd.DataFrame) -> pd.DataFrame:
    """Estimate stable selection and entry-family retention on common samples."""

    complete = panel[panel["both_v2_bridge_capitals_positive"]].copy()
    clear_entry = complete[complete["entry_stable"].notna()].copy()
    rows = [
        _fit_entry_model(
            panel,
            model_id="price_only_all_first_contestable",
            predictors=("stable_output_advantage_100bp",),
            sample="all_first_sampled_exact_contestable_routes",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            complete,
            model_id="c1_price_only_common_capital_sample",
            predictors=("stable_output_advantage_100bp",),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            complete,
            model_id="c2_capital_only_common_sample",
            predictors=("stable_v2_capital_share_10pp",),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            complete,
            model_id="c3_price_and_capital_common_sample",
            predictors=(
                "stable_output_advantage_100bp",
                "stable_v2_capital_share_10pp",
            ),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r1_entry_retention_price_only",
            predictors=("entry_vehicle_output_advantage_100bp",),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r2_entry_retention_capital_only",
            predictors=("entry_vehicle_v2_capital_share_10pp",),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r3_entry_retention_price_and_capital",
            predictors=(
                "entry_vehicle_output_advantage_100bp",
                "entry_vehicle_v2_capital_share_10pp",
            ),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
        ),
    ]
    return pd.concat(rows, ignore_index=True, sort=False)


def support_results(entries: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Report contestability coverage, lags, and entry-family survival."""

    pair = (
        panel.groupby("ordered_pair", as_index=False, sort=True)
        .agg(
            entry_stable=("entry_stable", "first"),
            first_contestable_stable_share=("chosen_stable", "mean"),
            routes=("route_id", "size"),
            entry_to_contestability_days=("entry_to_contestability_days", "first"),
        )
    )
    pair["first_contestable_stable"] = np.where(
        pair["first_contestable_stable_share"].gt(0.5),
        1.0,
        np.where(pair["first_contestable_stable_share"].lt(0.5), 0.0, np.nan),
    )
    pair["entry_vehicle_retained"] = np.where(
        pair["entry_stable"].notna() & pair["first_contestable_stable"].notna(),
        pair["entry_stable"].eq(pair["first_contestable_stable"]).astype(float),
        np.nan,
    )
    clear_routes = panel[panel["entry_vehicle_retained"].notna()]
    complete = panel[panel["both_v2_bridge_capitals_positive"]]
    lag = pair["entry_to_contestability_days"]
    return pd.DataFrame(
        [
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "material_entry_cohort",
                "entry_pairs": int(len(entries)),
                "entry_dates": int(entries["day"].nunique()),
                "pairs_reaching_sampled_contestability": int(len(pair)),
                "contestability_coverage_share": float(len(pair) / len(entries)),
                "minimum_entry_value_usd": float(
                    entries["entry_coherent_value_usd"].min()
                ),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "first_sampled_exact_contestable_routes",
                "routes": int(len(panel)),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "dates": int(panel["day"].nunique()),
                "stable_choice_share": float(panel["chosen_stable"].mean()),
                "both_positive_prior_v2_capital_share": float(
                    panel["both_v2_bridge_capitals_positive"].mean()
                ),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "entry_to_first_sampled_contestability_lag",
                "pairs": int(len(pair)),
                "median_days": float(lag.median()),
                "p25_days": float(lag.quantile(0.25)),
                "p75_days": float(lag.quantile(0.75)),
                "p90_days": float(lag.quantile(0.90)),
                "within_120_days_share": float(lag.le(120).mean()),
                "monthly_sampling": True,
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "entry_vehicle_survival",
                "route_weighted_retention_share": float(
                    clear_routes["entry_vehicle_retained"].mean()
                ),
                "route_weighted_routes": int(len(clear_routes)),
                "equal_pair_retention_share": float(
                    pair["entry_vehicle_retained"].mean()
                ),
                "equal_pair_pairs": int(pair["entry_vehicle_retained"].notna().sum()),
                "pair_ties_excluded": int(pair["first_contestable_stable"].isna().sum()),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "positive_both_family_prior_v2_capital",
                "routes": int(len(complete)),
                "ordered_pairs": int(complete["ordered_pair"].nunique()),
                "dates": int(complete["day"].nunique()),
            },
        ]
    )


def run(
    *,
    frontier_path: Path = FRONTIER,
    capital_path: Path = POOL_CAPITAL,
    panel_path: Path = PANEL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
    minimum_entry_value_usd: float = DEFAULT_MIN_ENTRY_VALUE_USD,
    start: str = START,
    end: str = END,
) -> int:
    entries = load_material_entries(
        PRIMARY_DATA_DIR / "processed/endpoint_candidate_pair_support.parquet",
        minimum_entry_value_usd=minimum_entry_value_usd,
        start=start,
        end=end,
    )
    exact = first_contestable_routes(frontier_path, entries)
    panel = attach_oriented_variables(exact, capital_path)
    results = choice_results(panel)
    support = support_results(entries, panel)
    write_panel(panel, panel_path, code_sources=CODE_SOURCES)
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(results.to_string(index=False), flush=True)
    print(support.to_string(index=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--panel", type=Path, default=PANEL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument(
        "--minimum-entry-value-usd",
        type=float,
        default=DEFAULT_MIN_ENTRY_VALUE_USD,
    )
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    args = parser.parse_args()
    return run(
        frontier_path=args.frontier,
        capital_path=args.capital,
        panel_path=args.panel,
        output_path=args.output,
        support_path=args.support,
        minimum_entry_value_usd=args.minimum_entry_value_usd,
        start=args.start.replace("-", ""),
        end=args.end.replace("-", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
