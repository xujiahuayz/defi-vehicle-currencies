#!/usr/bin/env python3
"""Explore how V2 deposited capital is allocated across vehicle candidates.

The registered predictability exhibit asks whether deposited capital leads or
follows vehicle use at exact future horizons. This exploratory companion asks a
different, contemporaneous question: where provider capital sits while the
vehicle role is realised. The rows are descriptive associations, not causal
provider-flow estimates.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    common_calendar_day_mask,
    ols_clustered,
    year_endpoint_change,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_support.jsonl"

CODE_SOURCES = [
    "scripts/analyze/run_liquidity_provision_behavior_exploration.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = ["data/processed/liquidity_capital_v2_candidate_day.parquet"]
STABLE_SYMBOLS = frozenset({"DAI", "USDC", "USDT"})
WETH_SYMBOL = "WETH"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAG_DAYS = 30


def load_candidate_day(path: Path = CANDIDATE_DAY_INPUT) -> pd.DataFrame:
    """Load and validate the released five-candidate V2 day panel."""

    frame = pd.read_parquet(path)
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_day_supported",
        "v2_capital_day_supported",
        "intermediary_episode_share",
        "vehicle_excess_use_count_ratio",
        "intermediate_route_count",
        "endpoint_route_count",
        "v2_deposited_capital_usd",
        "v2_log1p_deposited_capital_usd",
        "v2_five_candidate_capital_share",
        "v2_candidate_pool_count",
        "v2_candidate_venue_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"candidate-day panel lacks columns: {missing}")
    frame = frame.copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"])
    frame["candidate_symbol"] = frame["candidate_symbol"].astype(str)
    return frame


def supported_candidate_days(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep rows where route and capital quantities are both defined."""

    sample = frame[
        frame["route_day_supported"].astype(bool)
        & frame["v2_capital_day_supported"].astype(bool)
    ].copy()
    numeric = [
        "intermediary_episode_share",
        "intermediate_route_count",
        "endpoint_route_count",
        "v2_deposited_capital_usd",
        "v2_log1p_deposited_capital_usd",
        "v2_five_candidate_capital_share",
        "v2_candidate_pool_count",
        "v2_candidate_venue_count",
    ]
    sample = sample.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if sample.empty:
        raise ValueError("supported V2 liquidity behavior sample is empty")
    candidates_per_day = sample.groupby("origin_date")["candidate_symbol"].nunique()
    if candidates_per_day.min() < 5:
        raise ValueError("supported V2 liquidity behavior sample lost candidates")
    sample["year"] = sample["origin_date"].dt.year.astype(int)
    sample["is_stable"] = sample["candidate_symbol"].isin(STABLE_SYMBOLS)
    sample["is_weth"] = sample["candidate_symbol"].eq(WETH_SYMBOL)
    return sample


def annual_stable_allocation(sample: pd.DataFrame) -> pd.DataFrame:
    """Compare stablecoin capital share with stablecoin route-use share by year."""

    rows: list[dict[str, object]] = []
    for year, group in sample.groupby("year", sort=True):
        capital_total = float(group["v2_deposited_capital_usd"].sum())
        route_total = float(group["intermediate_route_count"].sum())
        endpoint_total = float(group["endpoint_route_count"].sum())
        stable = group[group["is_stable"]]
        weth = group[group["is_weth"]]
        stable_capital = float(stable["v2_deposited_capital_usd"].sum())
        stable_routes = float(stable["intermediate_route_count"].sum())
        stable_endpoints = float(stable["endpoint_route_count"].sum())
        weth_capital = float(weth["v2_deposited_capital_usd"].sum())
        weth_routes = float(weth["intermediate_route_count"].sum())
        stable_capital_share = stable_capital / capital_total
        stable_intermediary_route_share = stable_routes / route_total if route_total else np.nan
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "annual_stable_allocation",
                "year": int(year),
                "days": int(group["origin_date"].nunique()),
                "candidate_day_rows": int(len(group)),
                "stable_capital_share": stable_capital_share,
                "stable_intermediary_route_share": stable_intermediary_route_share,
                "stable_endpoint_route_share": stable_endpoints / endpoint_total if endpoint_total else np.nan,
                "stable_route_to_capital_ratio": stable_intermediary_route_share / stable_capital_share if stable_capital_share else np.nan,
                "weth_capital_share": weth_capital / capital_total,
                "weth_intermediary_route_share": weth_routes / route_total if route_total else np.nan,
                "interpretation": "descriptive allocation across five V2 vehicle candidates",
            }
        )
    return pd.DataFrame(rows)


def daily_capital_use_gaps(sample: pd.DataFrame) -> pd.DataFrame:
    """Return daily route-share minus deposited-capital-share gaps."""

    rows: list[dict[str, object]] = []
    for date, group in sample.groupby("origin_date", sort=True):
        route_total = float(group["intermediate_route_count"].sum())
        capital_total = float(group["v2_deposited_capital_usd"].sum())
        if route_total <= 0 or capital_total <= 0:
            continue
        stable = group[group["is_stable"]]
        weth = group[group["is_weth"]]
        stable_route_share = float(stable["intermediate_route_count"].sum()) / route_total
        stable_capital_share = float(stable["v2_deposited_capital_usd"].sum()) / capital_total
        weth_route_share = float(weth["intermediate_route_count"].sum()) / route_total
        weth_capital_share = float(weth["v2_deposited_capital_usd"].sum()) / capital_total
        rows.append(
            {
                "origin_date": date,
                "year": int(pd.Timestamp(date).year),
                "stable_route_share": stable_route_share,
                "stable_capital_share": stable_capital_share,
                "stable_route_capital_gap": stable_route_share - stable_capital_share,
                "weth_route_share": weth_route_share,
                "weth_capital_share": weth_capital_share,
                "weth_route_capital_gap": weth_route_share - weth_capital_share,
            }
        )
    daily = pd.DataFrame(rows)
    if daily.empty:
        raise ValueError("daily capital-use gap panel is empty")
    return daily


def capital_use_gap_summaries(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarise and test route-minus-capital gaps on the endpoint calendar."""

    rows: list[dict[str, object]] = []
    for year, group in daily.groupby("year", sort=True):
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "daily_route_capital_gap_year",
                "year": int(year),
                "days": int(group["origin_date"].nunique()),
                "stable_route_share_mean": float(group["stable_route_share"].mean()),
                "stable_capital_share_mean": float(group["stable_capital_share"].mean()),
                "stable_route_capital_gap_mean": float(
                    group["stable_route_capital_gap"].mean()
                ),
                "weth_route_share_mean": float(group["weth_route_share"].mean()),
                "weth_capital_share_mean": float(group["weth_capital_share"].mean()),
                "weth_route_capital_gap_mean": float(
                    group["weth_route_capital_gap"].mean()
                ),
                "interpretation": "daily route share minus deposited-capital share",
            }
        )
    endpoint = daily[daily["year"].between(BASELINE_YEAR, COMPARISON_YEAR)].copy()
    endpoint = endpoint.loc[
        common_calendar_day_mask(
            endpoint["origin_date"],
            endpoint["year"],
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
        )
    ]
    for gap_name, column in (
        ("stable_route_capital_gap", "stable_route_capital_gap"),
        ("weth_route_capital_gap", "weth_route_capital_gap"),
    ):
        estimate = year_endpoint_change(
            endpoint[column],
            endpoint["year"],
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
            hac_lag=HAC_LAG_DAYS,
            dates=endpoint["origin_date"],
        )
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "daily_route_capital_gap_change",
                "gap_name": gap_name,
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
                "calendar_support": "daily observations at month-day positions observed in both endpoint years",
                "interpretation": "matched-calendar change in route share minus deposited-capital share",
            }
        )
    return pd.DataFrame(rows)


def daily_leader_alignment(sample: pd.DataFrame) -> pd.DataFrame:
    """Summarise whether capital leaders and vehicle-use leaders are the same tokens."""

    records: list[dict[str, object]] = []
    for date, group in sample.groupby("origin_date", sort=True):
        ranked = group.sort_values("candidate_symbol")
        cap = ranked.loc[ranked["v2_deposited_capital_usd"].idxmax()]
        route = ranked.loc[ranked["intermediary_episode_share"].idxmax()]
        excess_sample = ranked.dropna(subset=["vehicle_excess_use_count_ratio"])
        if excess_sample.empty:
            continue
        excess = excess_sample.loc[excess_sample["vehicle_excess_use_count_ratio"].idxmax()]
        records.append(
            {
                "origin_date": date,
                "cap_leader": str(cap["candidate_symbol"]),
                "route_leader": str(route["candidate_symbol"]),
                "excess_leader": str(excess["candidate_symbol"]),
            }
        )
    leaders = pd.DataFrame(records)
    if leaders.empty:
        raise ValueError("no daily leaders can be computed")
    row = {
        "analysis_status": "exploratory_descriptive",
        "record_type": "daily_leader_alignment",
        "days": int(len(leaders)),
        "weth_capital_leader_share": float(leaders["cap_leader"].eq(WETH_SYMBOL).mean()),
        "stable_capital_leader_share": float(leaders["cap_leader"].isin(STABLE_SYMBOLS).mean()),
        "stable_route_leader_share": float(leaders["route_leader"].isin(STABLE_SYMBOLS).mean()),
        "stable_excess_leader_share": float(leaders["excess_leader"].isin(STABLE_SYMBOLS).mean()),
        "capital_leader_is_route_leader_share": float(
            leaders["cap_leader"].eq(leaders["route_leader"]).mean()
        ),
        "capital_leader_is_excess_leader_share": float(
            leaders["cap_leader"].eq(leaders["excess_leader"]).mean()
        ),
        "interpretation": "daily candidate leader comparison, not provider-flow timing",
    }
    return pd.DataFrame([row])


def candidate_profiles(sample: pd.DataFrame) -> pd.DataFrame:
    """Return candidate-level capital, pool, and vehicle-role profiles."""

    rows: list[dict[str, object]] = []
    leaders = []
    for date, group in sample.groupby("origin_date", sort=True):
        ranked = group.sort_values("candidate_symbol")
        leaders.append(
            {
                "origin_date": date,
                "cap_leader": ranked.loc[ranked["v2_deposited_capital_usd"].idxmax(), "candidate_symbol"],
                "route_leader": ranked.loc[ranked["intermediary_episode_share"].idxmax(), "candidate_symbol"],
                "excess_leader": ranked.dropna(subset=["vehicle_excess_use_count_ratio"]).loc[
                    ranked.dropna(subset=["vehicle_excess_use_count_ratio"])["vehicle_excess_use_count_ratio"].idxmax(),
                    "candidate_symbol",
                ],
            }
        )
    leader_frame = pd.DataFrame(leaders)
    for symbol, group in sample.groupby("candidate_symbol", sort=True):
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "candidate_profile",
                "candidate_symbol": str(symbol),
                "days": int(group["origin_date"].nunique()),
                "avg_capital_share": float(group["v2_five_candidate_capital_share"].mean()),
                "avg_intermediary_episode_share": float(group["intermediary_episode_share"].mean()),
                "avg_vehicle_excess_use_count_ratio": float(
                    group["vehicle_excess_use_count_ratio"].replace([np.inf, -np.inf], np.nan).mean()
                ),
                "avg_pool_count": float(group["v2_candidate_pool_count"].mean()),
                "avg_venue_count": float(group["v2_candidate_venue_count"].mean()),
                "capital_leader_days": int(leader_frame["cap_leader"].eq(symbol).sum()),
                "route_leader_days": int(leader_frame["route_leader"].eq(symbol).sum()),
                "excess_leader_days": int(leader_frame["excess_leader"].eq(symbol).sum()),
                "interpretation": "candidate-level descriptive profile",
            }
        )
    return pd.DataFrame(rows)


def level_associations(sample: pd.DataFrame) -> pd.DataFrame:
    """Estimate candidate-date FE level associations between capital and use."""

    rows: list[dict[str, object]] = []
    predictors = ["v2_log1p_deposited_capital_usd", "v2_candidate_venue_count"]
    outcomes = ["intermediary_episode_share", "vehicle_excess_use_count_ratio"]
    for outcome in outcomes:
        for predictor in predictors:
            data = sample[
                ["origin_date", "candidate_address", outcome, predictor]
            ].replace([np.inf, -np.inf], np.nan).dropna()
            residual = absorb_fixed_effects(
                data[[outcome, predictor]], data["candidate_address"], data["origin_date"]
            )
            fit = ols_clustered(
                residual[outcome],
                residual[[predictor]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=1000,
                min_clusters=30,
            )
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "level_association",
                    "outcome": outcome,
                    "predictor": predictor,
                    "coefficient": float(fit.beta[0]),
                    "standard_error": float(fit.standard_errors[0]),
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "interpretation": "contemporaneous association, not causal feedback",
                }
            )
    return pd.DataFrame(rows)


def support_rows(sample: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "support",
                "analysis_status": "exploratory_descriptive",
                "input": str(CANDIDATE_DAY_INPUT.relative_to(REPO_ROOT)),
                "candidate_day_rows": int(len(sample)),
                "days": int(sample["origin_date"].nunique()),
                "candidate_count": int(sample["candidate_symbol"].nunique()),
                "first_date": sample["origin_date"].min().strftime("%Y-%m-%d"),
                "last_date": sample["origin_date"].max().strftime("%Y-%m-%d"),
                "stable_symbols": ",".join(sorted(STABLE_SYMBOLS)),
                "quantity": "V2 deposited-capital stock, not provider flows",
            }
        ]
    )


def run(
    *,
    input_path: Path = CANDIDATE_DAY_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    sample = supported_candidate_days(load_candidate_day(input_path))
    daily_gaps = daily_capital_use_gaps(sample)
    result = pd.concat(
        [
            annual_stable_allocation(sample),
            capital_use_gap_summaries(daily_gaps),
            daily_leader_alignment(sample),
            candidate_profiles(sample),
            level_associations(sample),
        ],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support_rows(sample), support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(f"wrote {len(result)} liquidity-provision behavior rows and 1 support row")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(input_path=args.input, output_path=args.output, support_path=args.support)


if __name__ == "__main__":
    raise SystemExit(main())
