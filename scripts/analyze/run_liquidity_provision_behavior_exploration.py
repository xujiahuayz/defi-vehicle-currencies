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

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    common_calendar_day_mask,
    linear_contrast,
    ols_clustered,
    year_endpoint_change,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
EXACT_HORIZON_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_exact_horizons.parquet"
POOL_CANDIDATE_CAPITAL_INPUT = REPO_ROOT / "data/processed/pool_candidate_capital_daily.parquet"
V3_POOL_DAY_FEES_INPUT = REPO_ROOT / "data/processed/v3_pool_day_fees.parquet"
V3_LP_ACTION_INPUT = REPO_ROOT / "data/processed/v3_lp_action_candidate_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_provision_behavior_support.jsonl"

CODE_SOURCES = [
    "scripts/analyze/run_liquidity_provision_behavior_exploration.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
    "data/processed/liquidity_capital_v2_exact_horizons.parquet",
    "data/processed/pool_candidate_capital_daily.parquet",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/v3_lp_action_candidate_daily.parquet",
]
STABLE_SYMBOLS = frozenset({"DAI", "USDC", "USDT"})
WETH_SYMBOL = "WETH"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAG_DAYS = 30
WITHIN_DAY_GAP_PREDICTORS = (
    "is_stable",
    "endpoint_share_5",
    "v2_candidate_venue_count",
    "log_pool_count",
)
GAP_CLOSING_INTERACTION_PREDICTORS = (
    "route_capital_gap_5",
    "route_capital_gap_5_x_stable",
)
GAP_ASYMMETRY_PREDICTORS = (
    "positive_route_capital_gap_5",
    "negative_route_capital_gap_5",
    "positive_route_capital_gap_5_x_stable",
    "negative_route_capital_gap_5_x_stable",
)
V3_LP_ACTION_HORIZONS = (7, 30, 120)


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


def load_exact_horizons(path: Path = EXACT_HORIZON_INPUT) -> pd.DataFrame:
    """Load exact-horizon capital and route outcomes for gap-closing screens."""

    frame = pd.read_parquet(path)
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "horizon_days",
        "route_exact_target_supported",
        "v2_exact_target_supported",
        "intermediate_route_count",
        "endpoint_route_count",
        "v2_deposited_capital_usd",
        "v2_candidate_pool_count",
        "v2_candidate_venue_count",
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"exact-horizon panel lacks columns: {missing}")
    frame = frame.copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"])
    frame["candidate_symbol"] = frame["candidate_symbol"].astype(str)
    frame["horizon_days"] = frame["horizon_days"].astype(int)
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


def candidate_share_gap_panel(sample: pd.DataFrame) -> pd.DataFrame:
    """Return candidate-day route and capital shares inside the five-candidate set."""

    panel = sample.copy()
    panel["is_stable"] = panel["candidate_symbol"].isin(STABLE_SYMBOLS).astype(float)
    by_day = panel.groupby("origin_date", sort=True)
    panel["route_total_5"] = by_day["intermediate_route_count"].transform("sum").astype(float)
    panel["endpoint_total_5"] = by_day["endpoint_route_count"].transform("sum").astype(float)
    panel["capital_total_5"] = by_day["v2_deposited_capital_usd"].transform("sum").astype(float)
    panel = panel[
        panel["route_total_5"].gt(0)
        & panel["endpoint_total_5"].gt(0)
        & panel["capital_total_5"].gt(0)
    ].copy()
    panel["route_share_5"] = (
        panel["intermediate_route_count"].astype(float) / panel["route_total_5"]
    )
    panel["endpoint_share_5"] = (
        panel["endpoint_route_count"].astype(float) / panel["endpoint_total_5"]
    )
    panel["capital_share_5"] = (
        panel["v2_deposited_capital_usd"].astype(float) / panel["capital_total_5"]
    )
    panel["route_capital_gap_5"] = panel["route_share_5"] - panel["capital_share_5"]
    panel["log_pool_count"] = np.log1p(panel["v2_candidate_pool_count"].astype(float))
    required = [
        "route_capital_gap_5",
        "is_stable",
        "endpoint_share_5",
        "v2_candidate_venue_count",
        "log_pool_count",
    ]
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if panel.empty:
        raise ValueError("candidate route-capital gap panel is empty")
    return panel


def route_capital_gap_horizon_panel(exact_horizons: pd.DataFrame) -> pd.DataFrame:
    """Attach origin route-minus-capital gaps to exact future capital outcomes."""

    sample = exact_horizons[
        exact_horizons["route_exact_target_supported"].astype(bool)
        & exact_horizons["v2_exact_target_supported"].astype(bool)
    ].copy()
    sample["is_stable"] = sample["candidate_symbol"].isin(STABLE_SYMBOLS).astype(float)
    by_origin_horizon = sample.groupby(["origin_date", "horizon_days"], sort=True)
    sample["route_total_5"] = by_origin_horizon["intermediate_route_count"].transform(
        "sum"
    ).astype(float)
    sample["capital_total_5"] = by_origin_horizon["v2_deposited_capital_usd"].transform(
        "sum"
    ).astype(float)
    sample = sample[
        sample["route_total_5"].gt(0.0)
        & sample["capital_total_5"].gt(0.0)
    ].copy()
    sample["route_share_5"] = (
        sample["intermediate_route_count"].astype(float) / sample["route_total_5"]
    )
    sample["capital_share_5"] = (
        sample["v2_deposited_capital_usd"].astype(float) / sample["capital_total_5"]
    )
    sample["route_capital_gap_5"] = sample["route_share_5"] - sample["capital_share_5"]
    required = [
        "route_capital_gap_5",
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    ]
    sample = sample.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if sample.empty:
        raise ValueError("route-capital gap exact-horizon panel is empty")
    return sample


def route_capital_gap_rank_transition_panel(exact_horizons: pd.DataFrame) -> pd.DataFrame:
    """Attach origin route-capital gaps to future route and capital rank changes."""

    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "horizon_days",
        "route_exact_target_supported",
        "v2_exact_target_supported",
        "intermediate_route_count",
        "v2_deposited_capital_usd",
        "target_intermediary_episode_share",
        "target_v2_five_candidate_capital_share",
    }
    missing = sorted(required - set(exact_horizons.columns))
    if missing:
        raise ValueError(f"exact-horizon panel lacks rank-transition columns: {missing}")
    sample = exact_horizons[
        exact_horizons["route_exact_target_supported"].astype(bool)
        & exact_horizons["v2_exact_target_supported"].astype(bool)
    ].copy()
    sample["origin_date"] = pd.to_datetime(sample["origin_date"], errors="raise")
    sample["horizon_days"] = sample["horizon_days"].astype(int)
    sample["is_stable"] = sample["candidate_symbol"].isin(STABLE_SYMBOLS).astype(float)
    by_origin_horizon = sample.groupby(["origin_date", "horizon_days"], sort=True)
    sample["route_total_5"] = by_origin_horizon["intermediate_route_count"].transform(
        "sum"
    ).astype(float)
    sample["capital_total_5"] = by_origin_horizon["v2_deposited_capital_usd"].transform(
        "sum"
    ).astype(float)
    sample = sample[
        sample["route_total_5"].gt(0.0)
        & sample["capital_total_5"].gt(0.0)
    ].copy()
    sample["route_share_5"] = (
        sample["intermediate_route_count"].astype(float) / sample["route_total_5"]
    )
    sample["capital_share_5"] = (
        sample["v2_deposited_capital_usd"].astype(float) / sample["capital_total_5"]
    )
    sample["route_capital_gap_5"] = sample["route_share_5"] - sample["capital_share_5"]
    rank_group = sample.groupby(["origin_date", "horizon_days"], sort=True)
    sample["origin_capital_rank"] = rank_group["capital_share_5"].rank(
        ascending=False,
        method="average",
    )
    sample["origin_route_rank"] = rank_group["route_share_5"].rank(
        ascending=False,
        method="average",
    )
    sample["future_capital_rank"] = rank_group[
        "target_v2_five_candidate_capital_share"
    ].rank(
        ascending=False,
        method="average",
    )
    sample["future_route_rank"] = rank_group["target_intermediary_episode_share"].rank(
        ascending=False,
        method="average",
    )
    sample["future_capital_rank_improvement"] = (
        sample["origin_capital_rank"] - sample["future_capital_rank"]
    )
    sample["future_route_rank_improvement"] = (
        sample["origin_route_rank"] - sample["future_route_rank"]
    )
    required_values = [
        "route_capital_gap_5",
        "future_capital_rank_improvement",
        "future_route_rank_improvement",
    ]
    sample = sample.replace([np.inf, -np.inf], np.nan).dropna(subset=required_values)
    if sample.empty:
        raise ValueError("route-capital rank-transition panel is empty")
    return sample


def route_capital_gap_rank_transition(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps forecast future capital and route ranks."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_capital_rank_improvement",
        "future_route_rank_improvement",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_rank_transition",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "rank_definition": (
                            "one is the largest route or capital share among the five "
                            "vehicle candidates; positive values mean moving closer to "
                            "the top rank"
                        ),
                        "interpretation": (
                            "temporally ordered candidate-rank association, not causal "
                            "provider-flow timing"
                        ),
                    }
                )
            try:
                stable_total = linear_contrast(fit, [1.0, 1.0])
            except ValueError:
                continue
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_rank_transition",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "rank_definition": (
                        "one is the largest route or capital share among the five "
                        "vehicle candidates; positive values mean moving closer to "
                        "the top rank"
                    ),
                    "interpretation": (
                        "stable-candidate rank association, not causal provider-flow "
                        "timing"
                    ),
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_extensive_margin_panel(
    sample: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 7, 30, 120),
) -> pd.DataFrame:
    """Attach origin route-minus-capital gaps to future pool/venue counts."""

    panel = candidate_share_gap_panel(sample)
    panel["log_venue_count"] = np.log1p(panel["v2_candidate_venue_count"].astype(float))
    current = panel[
        [
            "origin_date",
            "candidate_address",
            "candidate_symbol",
            "route_capital_gap_5",
            "is_stable",
            "log_pool_count",
            "log_venue_count",
        ]
    ].copy()
    rows: list[pd.DataFrame] = []
    target_columns = [
        "origin_date",
        "candidate_address",
        "log_pool_count",
        "log_venue_count",
    ]
    for horizon in horizons:
        target = panel[target_columns].copy()
        target["origin_date"] = target["origin_date"] - pd.Timedelta(days=horizon)
        joined = current.merge(
            target,
            on=["origin_date", "candidate_address"],
            how="inner",
            suffixes=("", "_target"),
            validate="one_to_one",
        )
        if joined.empty:
            continue
        joined["horizon_days"] = int(horizon)
        joined["future_log_pool_count_change"] = (
            joined["log_pool_count_target"] - joined["log_pool_count"]
        )
        joined["future_log_venue_count_change"] = (
            joined["log_venue_count_target"] - joined["log_venue_count"]
        )
        rows.append(joined)
    if not rows:
        raise ValueError("route-capital extensive-margin panel is empty")
    out = pd.concat(rows, ignore_index=True, sort=False)
    required = [
        "route_capital_gap_5",
        "is_stable",
        "future_log_pool_count_change",
        "future_log_venue_count_change",
    ]
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if out.empty:
        raise ValueError("route-capital extensive-margin panel lost all rows")
    return out


def route_capital_gap_extensive_margins(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps predict future pool or venue reach."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_log_pool_count_change",
        "future_log_venue_count_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_extensive_margin",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_percent": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_percent": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "temporally ordered pool-or-venue reach association, "
                            "not causal provider-flow timing"
                        ),
                    }
                )
            try:
                stable_total = linear_contrast(fit, [1.0, 1.0])
            except ValueError:
                continue
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_extensive_margin",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "coefficient_per_10pp_gap_percent": 10.0
                    * stable_total.estimate,
                    "standard_error_per_10pp_gap_percent": 10.0
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": (
                        "stable-candidate total pool-or-venue reach association, "
                        "not causal provider-flow timing"
                    ),
                }
            )
    return pd.DataFrame(rows)


def candidate_capital_concentration_panel(
    share_gap_panel: pd.DataFrame,
    *,
    pool_candidate_path: Path = POOL_CANDIDATE_CAPITAL_INPUT,
) -> pd.DataFrame:
    """Attach pool-level capital concentration to candidate-day gaps."""

    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
        "v2_deposited_capital_usd",
    }
    missing = sorted(required - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks concentration columns: {missing}")
    connection = duckdb.connect()
    try:
        concentration = connection.execute(
            """
            WITH pool_day AS (
                SELECT
                    strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
                    lower(candidate_address) AS candidate_address,
                    count(DISTINCT pool)::DOUBLE AS pool_count,
                    count(DISTINCT venue)::DOUBLE AS venue_count,
                    sum(candidate_capital_usd)::DOUBLE AS pool_candidate_capital_usd,
                    max(candidate_capital_usd)::DOUBLE AS top_pool_capital_usd,
                    sum(candidate_capital_usd * candidate_capital_usd)::DOUBLE
                        AS squared_capital_usd
                FROM read_parquet(?)
                WHERE quantity_kind = 'deposited_capital'
                  AND capital_validation_status = 'exact_state_current'
                  AND candidate_capital_usd > 0
                GROUP BY 1, 2
            )
            SELECT
                origin_date,
                candidate_address,
                pool_count,
                venue_count,
                pool_candidate_capital_usd,
                top_pool_capital_usd
                    / nullif(pool_candidate_capital_usd, 0) AS top_pool_share,
                squared_capital_usd
                    / nullif(pool_candidate_capital_usd * pool_candidate_capital_usd, 0)
                    AS pool_hhi,
                1.0 / (
                    squared_capital_usd
                    / nullif(pool_candidate_capital_usd * pool_candidate_capital_usd, 0)
                ) AS effective_pool_count
            FROM pool_day
            """,
            [str(pool_candidate_path)],
        ).fetchdf()
    finally:
        connection.close()
    if concentration.empty:
        raise ValueError("pool-candidate capital concentration panel is empty")
    concentration["origin_date"] = pd.to_datetime(
        concentration["origin_date"]
    ).dt.normalize()
    concentration["candidate_address"] = (
        concentration["candidate_address"].astype(str).str.lower()
    )
    base = share_gap_panel[list(required)].copy()
    base["origin_date"] = pd.to_datetime(base["origin_date"]).dt.normalize()
    base["candidate_address"] = base["candidate_address"].astype(str).str.lower()
    panel = base.merge(
        concentration,
        on=["origin_date", "candidate_address"],
        how="inner",
        validate="one_to_one",
    )
    numeric = [
        "route_capital_gap_5",
        "v2_deposited_capital_usd",
        "pool_count",
        "venue_count",
        "top_pool_share",
        "pool_hhi",
        "effective_pool_count",
    ]
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if panel.empty:
        raise ValueError("pool-candidate concentration panel lost all rows")
    return panel


def capital_concentration_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize stable versus non-stable pool-capital concentration by year."""

    rows: list[dict[str, object]] = []
    sample = panel.copy()
    sample["year"] = pd.to_datetime(sample["origin_date"]).dt.year.astype(int)
    for (year, is_stable), group in sample.groupby(["year", "is_stable"], sort=True):
        weight = group["v2_deposited_capital_usd"].astype(float)
        if float(weight.sum()) <= 0:
            continue
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "capital_concentration_year",
                "year": int(year),
                "candidate_group": "stable_candidates"
                if float(is_stable) == 1.0
                else "nonstable_candidates",
                "candidate_day_rows": int(len(group)),
                "days": int(group["origin_date"].nunique()),
                "capital_share": float(weight.sum() / sample.loc[sample["year"].eq(year), "v2_deposited_capital_usd"].sum()),
                "capital_weighted_top_pool_share": float(
                    np.average(group["top_pool_share"].astype(float), weights=weight)
                ),
                "capital_weighted_pool_hhi": float(
                    np.average(group["pool_hhi"].astype(float), weights=weight)
                ),
                "mean_top_pool_share": float(group["top_pool_share"].mean()),
                "mean_pool_hhi": float(group["pool_hhi"].mean()),
                "mean_effective_pool_count": float(
                    group["effective_pool_count"].mean()
                ),
                "median_effective_pool_count": float(
                    group["effective_pool_count"].median()
                ),
                "mean_pool_count": float(group["pool_count"].mean()),
                "median_pool_count": float(group["pool_count"].median()),
                "interpretation": (
                    "pool-level deposited-capital concentration, not provider "
                    "ownership or LP return concentration"
                ),
            }
        )
    return pd.DataFrame(rows)


def route_capital_gap_concentration_horizon_panel(
    concentration_panel: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (30, 120),
) -> pd.DataFrame:
    """Attach current route-capital gaps to future concentration changes."""

    current = concentration_panel[
        [
            "origin_date",
            "candidate_address",
            "candidate_symbol",
            "is_stable",
            "route_capital_gap_5",
            "top_pool_share",
            "pool_hhi",
            "effective_pool_count",
            "pool_count",
        ]
    ].copy()
    rows: list[pd.DataFrame] = []
    target_columns = [
        "origin_date",
        "candidate_address",
        "top_pool_share",
        "pool_hhi",
        "effective_pool_count",
        "pool_count",
    ]
    for horizon in horizons:
        target = concentration_panel[target_columns].copy()
        target["origin_date"] = target["origin_date"] - pd.Timedelta(days=horizon)
        joined = current.merge(
            target,
            on=["origin_date", "candidate_address"],
            how="inner",
            suffixes=("", "_target"),
            validate="one_to_one",
        )
        if joined.empty:
            continue
        joined["horizon_days"] = int(horizon)
        joined["future_top_pool_share_change"] = (
            joined["top_pool_share_target"] - joined["top_pool_share"]
        )
        joined["future_pool_hhi_change"] = (
            joined["pool_hhi_target"] - joined["pool_hhi"]
        )
        joined["future_log_effective_pool_count_change"] = (
            np.log(joined["effective_pool_count_target"].astype(float))
            - np.log(joined["effective_pool_count"].astype(float))
        )
        joined["future_pool_count_change"] = (
            joined["pool_count_target"] - joined["pool_count"]
        )
        rows.append(joined)
    if not rows:
        raise ValueError("route-capital concentration horizon panel is empty")
    out = pd.concat(rows, ignore_index=True, sort=False)
    required = [
        "route_capital_gap_5",
        "is_stable",
        "future_top_pool_share_change",
        "future_pool_hhi_change",
        "future_log_effective_pool_count_change",
        "future_pool_count_change",
    ]
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if out.empty:
        raise ValueError("route-capital concentration horizon panel lost all rows")
    return out


def route_capital_gap_concentration_response(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps predict future capital concentration."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_top_pool_share_change",
        "future_pool_hhi_change",
        "future_log_effective_pool_count_change",
        "future_pool_count_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_concentration_response",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_percent": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_percent": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "temporally ordered pool-capital concentration "
                            "association, not causal provider-flow timing"
                        ),
                    }
                )
            stable_total = linear_contrast(fit, [1.0, 1.0])
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_concentration_response",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "coefficient_per_10pp_gap_percent": 10.0
                    * stable_total.estimate,
                    "standard_error_per_10pp_gap_percent": 10.0
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": (
                        "stable-candidate pool-capital concentration association, "
                        "not causal provider-flow timing"
                    ),
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_pool_candidate_horizon_panel(
    share_gap_panel: pd.DataFrame,
    *,
    pool_candidate_path: Path = POOL_CANDIDATE_CAPITAL_INPUT,
    horizons: tuple[int, ...] = (30, 120),
) -> pd.DataFrame:
    """Attach candidate route-capital gaps to future same-pool capital changes."""

    if not horizons:
        raise ValueError("at least one same-pool horizon is required")
    required_columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
    ]
    required = set(required_columns)
    missing = sorted(required - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks pool-chase columns: {missing}")
    gaps = share_gap_panel[required_columns].copy()
    gaps["origin_date"] = pd.to_datetime(gaps["origin_date"]).dt.normalize()
    gaps["candidate_address"] = gaps["candidate_address"].astype(str).str.lower()
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        connection.register("candidate_gaps", gaps)
        horizon_selects = []
        for horizon in horizons:
            horizon_selects.append(
                f"""
                SELECT
                    j.origin_date,
                    j.candidate_address,
                    j.candidate_symbol,
                    j.is_stable,
                    j.pool_candidate_id,
                    j.route_capital_gap_5,
                    {int(horizon)}::INTEGER AS horizon_days,
                    t.log_pool_candidate_capital_usd
                        - j.log_pool_candidate_capital_usd
                        AS future_log_pool_candidate_capital_change
                FROM joined j
                JOIN joined t
                  ON t.pool_candidate_id = j.pool_candidate_id
                 AND t.origin_date = j.origin_date + INTERVAL {int(horizon)} DAY
                """
            )
        query = f"""
            WITH pool_candidates AS (
                SELECT
                    strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
                    lower(candidate_address) AS candidate_address,
                    pool_candidate_id,
                    candidate_capital_usd::DOUBLE AS pool_candidate_capital_usd,
                    log(1 + candidate_capital_usd::DOUBLE)
                        AS log_pool_candidate_capital_usd
                FROM read_parquet(?)
                WHERE capital_validation_status = 'exact_state_current'
                  AND quantity_kind = 'deposited_capital'
                  AND candidate_capital_usd IS NOT NULL
                  AND candidate_capital_usd > 0
            ),
            joined AS (
                SELECT
                    p.origin_date,
                    p.candidate_address,
                    g.candidate_symbol,
                    g.is_stable,
                    p.pool_candidate_id,
                    p.log_pool_candidate_capital_usd,
                    g.route_capital_gap_5
                FROM pool_candidates p
                JOIN candidate_gaps g
                  ON g.origin_date = p.origin_date
                 AND g.candidate_address = p.candidate_address
            )
            {" UNION ALL ".join(horizon_selects)}
        """
        out = connection.execute(query, [str(pool_candidate_path)]).fetchdf()
    finally:
        connection.close()
    if out.empty:
        raise ValueError("same-pool route-capital horizon panel is empty")
    out["origin_date"] = pd.to_datetime(out["origin_date"])
    out["candidate_address"] = out["candidate_address"].astype(str)
    out["candidate_symbol"] = out["candidate_symbol"].astype(str)
    out["is_stable"] = out["is_stable"].astype(float)
    return out.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "route_capital_gap_5",
            "future_log_pool_candidate_capital_change",
        ]
    )


def route_capital_gap_same_pool_reallocation(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps predict same-pool capital changes."""

    rows: list[dict[str, object]] = []
    for horizon, group in panel.groupby("horizon_days", sort=True):
        data = (
            group[
                [
                    "origin_date",
                    "pool_candidate_id",
                    "is_stable",
                    "route_capital_gap_5",
                    "future_log_pool_candidate_capital_change",
                ]
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        data["route_capital_gap_5_x_stable"] = (
            data["route_capital_gap_5"].astype(float)
            * data["is_stable"].astype(float)
        )
        residual = absorb_fixed_effects(
            data[
                [
                    "future_log_pool_candidate_capital_change",
                    "route_capital_gap_5",
                    "route_capital_gap_5_x_stable",
                ]
            ],
            data["pool_candidate_id"],
            data["origin_date"],
        )
        fit = ols_clustered(
            residual["future_log_pool_candidate_capital_change"],
            residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
            data["origin_date"],
            add_constant=False,
            absorbed_groups=(data["pool_candidate_id"], data["origin_date"]),
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for predictor, coefficient, standard_error, t_statistic, p_value in zip(
            ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            coefficient = float(coefficient)
            standard_error = float(standard_error)
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_same_pool_reallocation",
                    "horizon_days": int(horizon),
                    "outcome": "future_log_pool_candidate_capital_change",
                    "predictor": predictor,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(t_statistic),
                    "p_value": float(p_value),
                    "coefficient_per_10pp_gap": 0.10 * coefficient,
                    "standard_error_per_10pp_gap": 0.10 * standard_error,
                    "coefficient_per_10pp_gap_percent": 10.0 * coefficient,
                    "standard_error_per_10pp_gap_percent": 10.0 * standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "pool_candidate_id+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": (
                        "same-pool deposited-capital association, not causal "
                        "provider-flow timing"
                    ),
                }
            )
        stable_total = linear_contrast(fit, [1.0, 1.0])
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "route_capital_gap_same_pool_reallocation",
                "horizon_days": int(horizon),
                "outcome": "future_log_pool_candidate_capital_change",
                "predictor": "stable_total_route_capital_gap_5",
                "coefficient": stable_total.estimate,
                "standard_error": stable_total.standard_error,
                "t_statistic": stable_total.t_statistic,
                "p_value": stable_total.p_value,
                "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                "standard_error_per_10pp_gap": 0.10 * stable_total.standard_error,
                "coefficient_per_10pp_gap_percent": 10.0 * stable_total.estimate,
                "standard_error_per_10pp_gap_percent": 10.0
                * stable_total.standard_error,
                "n_observations": int(fit.n_observations),
                "date_clusters": int(fit.n_clusters),
                "fixed_effects": "pool_candidate_id+origin_date",
                "covariance": "origin_date_clustered",
                "interpretation": (
                    "stable-candidate same-pool deposited-capital association, "
                    "not causal provider-flow timing"
                ),
            }
        )
    return pd.DataFrame(rows)


def route_capital_gap_pool_entry_horizon_panel(
    share_gap_panel: pd.DataFrame,
    *,
    pool_candidate_path: Path = POOL_CANDIDATE_CAPITAL_INPUT,
    horizons: tuple[int, ...] = (30, 120),
) -> pd.DataFrame:
    """Split future candidate capital into incumbent-pool and entrant-pool pieces."""

    if not horizons:
        raise ValueError("at least one pool-entry horizon is required")
    required_columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
    ]
    missing = sorted(set(required_columns) - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks pool-entry columns: {missing}")
    gaps = share_gap_panel[required_columns].copy()
    gaps["origin_date"] = pd.to_datetime(gaps["origin_date"]).dt.normalize()
    gaps["candidate_address"] = gaps["candidate_address"].astype(str).str.lower()
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        connection.register("candidate_gaps", gaps)
        horizon_selects = []
        for horizon in horizons:
            horizon_selects.append(
                f"""
                SELECT
                    i.origin_date,
                    i.candidate_address,
                    i.candidate_symbol,
                    i.is_stable,
                    i.route_capital_gap_5,
                    {int(horizon)}::INTEGER AS horizon_days,
                    i.origin_incumbent_capital,
                    i.future_incumbent_capital,
                    coalesce(e.future_entrant_capital, 0)::DOUBLE
                        AS future_entrant_capital,
                    coalesce(e.future_entrant_pools, 0)::DOUBLE
                        AS future_entrant_pools,
                    log(1 + i.future_incumbent_capital)
                        - log(1 + i.origin_incumbent_capital)
                        AS future_log_incumbent_capital_change,
                    log(1 + coalesce(e.future_entrant_capital, 0))
                        AS future_log1p_entrant_capital,
                    log(
                        1 + i.future_incumbent_capital
                          + coalesce(e.future_entrant_capital, 0)
                    ) - log(1 + i.origin_incumbent_capital)
                        AS future_log_total_capital_change,
                    coalesce(e.future_entrant_capital, 0)
                        / nullif(
                            i.future_incumbent_capital
                            + coalesce(e.future_entrant_capital, 0),
                            0
                        ) AS future_entrant_capital_share
                FROM incumbent_{int(horizon)} i
                LEFT JOIN entrant_{int(horizon)} e
                  ON e.origin_date = i.origin_date
                 AND e.candidate_address = i.candidate_address
                """
            )
        horizon_ctes = []
        for horizon in horizons:
            horizon_ctes.append(
                f"""
                origin_{int(horizon)} AS (
                    SELECT
                        g.origin_date,
                        g.candidate_address,
                        g.candidate_symbol,
                        g.is_stable,
                        g.route_capital_gap_5,
                        p.pool_candidate_id,
                        p.capital AS origin_capital
                    FROM candidate_gaps g
                    JOIN pool_candidates p
                      ON p.origin_date = g.origin_date
                     AND p.candidate_address = g.candidate_address
                ),
                target_{int(horizon)} AS (
                    SELECT
                        g.origin_date,
                        g.candidate_address,
                        p.pool_candidate_id,
                        p.capital AS target_capital
                    FROM candidate_gaps g
                    JOIN pool_candidates p
                      ON p.origin_date = g.origin_date + INTERVAL {int(horizon)} DAY
                     AND p.candidate_address = g.candidate_address
                ),
                incumbent_{int(horizon)} AS (
                    SELECT
                        o.origin_date,
                        o.candidate_address,
                        o.candidate_symbol,
                        o.is_stable,
                        o.route_capital_gap_5,
                        sum(o.origin_capital)::DOUBLE AS origin_incumbent_capital,
                        sum(coalesce(t.target_capital, 0))::DOUBLE
                            AS future_incumbent_capital
                    FROM origin_{int(horizon)} o
                    LEFT JOIN target_{int(horizon)} t
                      ON t.origin_date = o.origin_date
                     AND t.candidate_address = o.candidate_address
                     AND t.pool_candidate_id = o.pool_candidate_id
                    GROUP BY 1, 2, 3, 4, 5
                ),
                entrant_{int(horizon)} AS (
                    SELECT
                        t.origin_date,
                        t.candidate_address,
                        sum(t.target_capital)::DOUBLE AS future_entrant_capital,
                        count(*)::DOUBLE AS future_entrant_pools
                    FROM target_{int(horizon)} t
                    LEFT JOIN origin_{int(horizon)} o
                      ON o.origin_date = t.origin_date
                     AND o.candidate_address = t.candidate_address
                     AND o.pool_candidate_id = t.pool_candidate_id
                    WHERE o.pool_candidate_id IS NULL
                    GROUP BY 1, 2
                )
                """
            )
        query = f"""
            WITH pool_candidates AS (
                SELECT
                    strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
                    lower(candidate_address) AS candidate_address,
                    pool_candidate_id,
                    candidate_capital_usd::DOUBLE AS capital
                FROM read_parquet(?)
                WHERE quantity_kind = 'deposited_capital'
                  AND capital_validation_status = 'exact_state_current'
                  AND candidate_capital_usd IS NOT NULL
                  AND candidate_capital_usd > 0
            ),
            {", ".join(horizon_ctes)}
            {" UNION ALL ".join(horizon_selects)}
        """
        out = connection.execute(query, [str(pool_candidate_path)]).fetchdf()
    finally:
        connection.close()
    if out.empty:
        raise ValueError("route-capital pool-entry horizon panel is empty")
    out["origin_date"] = pd.to_datetime(out["origin_date"])
    out["candidate_address"] = out["candidate_address"].astype(str)
    out["candidate_symbol"] = out["candidate_symbol"].astype(str)
    out["is_stable"] = out["is_stable"].astype(float)
    required = [
        "route_capital_gap_5",
        "future_log_incumbent_capital_change",
        "future_log1p_entrant_capital",
        "future_log_total_capital_change",
        "future_entrant_capital_share",
    ]
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if out.empty:
        raise ValueError("route-capital pool-entry horizon panel lost all rows")
    return out


def route_capital_gap_pool_entry_response(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps predict incumbent or entrant pool capital."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_log_incumbent_capital_change",
        "future_log1p_entrant_capital",
        "future_log_total_capital_change",
        "future_entrant_capital_share",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_pool_entry_response",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "future exact-state incumbent or entrant pool-capital "
                            "association, not causal provider-flow timing"
                        ),
                    }
                )
            stable_total = linear_contrast(fit, [1.0, 1.0])
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_pool_entry_response",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": (
                        "stable-candidate total exact-state pool-capital response, "
                        "not causal provider-flow timing"
                    ),
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_v3_fee_horizon_panel(
    share_gap_panel: pd.DataFrame,
    *,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    horizons: tuple[int, ...] = (30, 120),
) -> pd.DataFrame:
    """Attach candidate route-capital gaps to future same-pool V3 fee outcomes."""

    if not horizons:
        raise ValueError("at least one V3 fee horizon is required")
    required_columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
    ]
    required = set(required_columns)
    missing = sorted(required - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks V3 fee columns: {missing}")
    gaps = share_gap_panel[required_columns].copy()
    gaps["origin_date"] = pd.to_datetime(gaps["origin_date"]).dt.normalize()
    gaps["candidate_address"] = gaps["candidate_address"].astype(str).str.lower()

    horizon_selects = []
    for horizon in horizons:
        horizon_selects.append(
            f"""
            SELECT
                j.origin_date,
                j.pool,
                j.candidate_address,
                j.candidate_symbol,
                j.is_stable,
                j.route_capital_gap_5,
                {int(horizon)}::INTEGER AS horizon_days,
                t.log_fees_usd - j.log_fees_usd AS future_log_fees_change,
                t.log_volume_usd - j.log_volume_usd AS future_log_volume_change
            FROM joined j
            JOIN joined t
              ON t.pool = j.pool
             AND t.candidate_address = j.candidate_address
             AND t.origin_date = j.origin_date + INTERVAL {int(horizon)} DAY
            """
        )
    query = f"""
        WITH fee_rows AS (
            SELECT
                CAST(origin_date AS DATE) AS origin_date,
                lower(pool) AS pool,
                lower(token0_address) AS token0,
                lower(token1_address) AS token1,
                fees_usd,
                volume_usd,
                tvl_usd
            FROM read_parquet(?)
            WHERE tvl_usd > 0
              AND fees_usd IS NOT NULL
              AND volume_usd IS NOT NULL
        ),
        pool_candidates AS (
            SELECT origin_date, pool, token0 AS candidate_address, fees_usd, volume_usd
            FROM fee_rows
            UNION ALL
            SELECT origin_date, pool, token1 AS candidate_address, fees_usd, volume_usd
            FROM fee_rows
        ),
        joined AS (
            SELECT
                p.origin_date,
                p.pool,
                p.candidate_address,
                g.candidate_symbol,
                g.is_stable,
                g.route_capital_gap_5,
                log(1 + p.fees_usd) AS log_fees_usd,
                log(1 + p.volume_usd) AS log_volume_usd
            FROM pool_candidates p
            JOIN candidate_gaps g
              ON g.origin_date = p.origin_date
             AND g.candidate_address = p.candidate_address
        )
        {" UNION ALL ".join(horizon_selects)}
    """
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        connection.register("candidate_gaps", gaps)
        out = connection.execute(
            query,
            [str(fee_panel_path)],
        ).fetchdf()
    finally:
        connection.close()
    if out.empty:
        raise ValueError("V3 fee-incidence horizon panel is empty")
    out["origin_date"] = pd.to_datetime(out["origin_date"])
    out["candidate_address"] = out["candidate_address"].astype(str)
    out["candidate_symbol"] = out["candidate_symbol"].astype(str)
    out["is_stable"] = out["is_stable"].astype(float)
    return out.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "route_capital_gap_5",
            "future_log_fees_change",
            "future_log_volume_change",
        ]
    )


def route_capital_gap_v3_fee_incidence(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps forecast same-pool V3 fees or volume."""

    rows: list[dict[str, object]] = []
    outcomes = ("future_log_fees_change", "future_log_volume_change")
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "pool",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["pool"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["pool"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_v3_fee_incidence",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_percent": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_percent": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "pool_count": int(data["pool"].nunique()),
                        "fixed_effects": "pool+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "same-pool V3 fee and volume association, not causal "
                            "rent incidence"
                        ),
                    }
                )
            stable_total = linear_contrast(fit, [1.0, 1.0])
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_v3_fee_incidence",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "coefficient_per_10pp_gap_percent": 10.0 * stable_total.estimate,
                    "standard_error_per_10pp_gap_percent": 10.0
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "pool_count": int(data["pool"].nunique()),
                    "fixed_effects": "pool+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": (
                        "stable-candidate same-pool V3 fee and volume association, "
                        "not causal rent incidence"
                    ),
                }
            )
    return pd.DataFrame(rows)


def load_v3_lp_actions(path: Path = V3_LP_ACTION_INPUT) -> pd.DataFrame:
    """Load the processed Uniswap V3 mint/burn action-count panel."""

    frame = pd.read_parquet(path)
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "v3_mint_events",
        "v3_burn_events",
        "v3_total_lp_actions",
        "v3_net_mint_events",
        "v3_mint_origin_count",
        "v3_burn_origin_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V3 LP-action panel lacks columns: {missing}")
    frame = frame.copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    frame["candidate_address"] = frame["candidate_address"].astype(str).str.lower()
    frame["candidate_symbol"] = frame["candidate_symbol"].astype(str)
    return frame


def route_capital_gap_v3_lp_action_horizon_panel(
    share_gap_panel: pd.DataFrame,
    *,
    actions: pd.DataFrame,
    horizons: tuple[int, ...] = V3_LP_ACTION_HORIZONS,
) -> pd.DataFrame:
    """Attach future Uniswap V3 mint/burn action counts to route-capital gaps."""

    if not horizons:
        raise ValueError("at least one V3 LP-action horizon is required")
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
    }
    missing = sorted(required - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks V3 LP-action columns: {missing}")
    base = share_gap_panel[list(required)].copy()
    base["origin_date"] = pd.to_datetime(base["origin_date"]).dt.normalize()
    base["candidate_address"] = base["candidate_address"].astype(str).str.lower()
    base["candidate_symbol"] = base["candidate_symbol"].astype(str)
    action_columns = [
        "v3_mint_events",
        "v3_burn_events",
        "v3_total_lp_actions",
        "v3_net_mint_events",
        "v3_mint_origin_count",
        "v3_burn_origin_count",
    ]
    if actions.empty:
        action_frame = pd.DataFrame(
            columns=["origin_date", "candidate_address", *action_columns]
        )
    else:
        action_frame = actions.copy()
        action_frame["origin_date"] = pd.to_datetime(
            action_frame["origin_date"]
        ).dt.normalize()
        action_frame["candidate_address"] = (
            action_frame["candidate_address"].astype(str).str.lower()
        )
        action_frame = (
            action_frame.groupby(
                ["origin_date", "candidate_address"], as_index=False, sort=True
            )[action_columns]
            .sum()
        )

    horizon_rows: list[pd.DataFrame] = []
    max_horizon = max(horizons)
    for candidate_address, candidate_base in base.groupby(
        "candidate_address", sort=True
    ):
        candidate_base = candidate_base.sort_values("origin_date").copy()
        start = candidate_base["origin_date"].min()
        end = candidate_base["origin_date"].max() + pd.Timedelta(days=max_horizon)
        calendar = pd.DataFrame(
            {
                "origin_date": pd.date_range(start, end, freq="D"),
                "candidate_address": candidate_address,
            }
        )
        calendar = calendar.merge(
            action_frame[action_frame["candidate_address"].eq(candidate_address)],
            on=["origin_date", "candidate_address"],
            how="left",
        )
        calendar[action_columns] = calendar[action_columns].fillna(0.0)
        for column in action_columns:
            calendar[f"{column}_cumulative"] = calendar[column].cumsum()
        cumulative = calendar[
            ["origin_date", *[f"{column}_cumulative" for column in action_columns]]
        ]
        origin = candidate_base.merge(
            cumulative,
            on="origin_date",
            how="left",
            validate="one_to_one",
        )
        for horizon in horizons:
            target = cumulative.copy()
            target["origin_date"] = target["origin_date"] - pd.Timedelta(
                days=horizon
            )
            joined = origin.merge(
                target,
                on="origin_date",
                how="inner",
                suffixes=("", "_target"),
                validate="one_to_one",
            )
            if joined.empty:
                continue
            joined["horizon_days"] = int(horizon)
            for column in action_columns:
                joined[f"future_{column}"] = (
                    joined[f"{column}_cumulative_target"]
                    - joined[f"{column}_cumulative"]
                )
            horizon_rows.append(joined)
    if not horizon_rows:
        raise ValueError("V3 LP-action horizon panel is empty")
    panel = pd.concat(horizon_rows, ignore_index=True, sort=False)
    panel["future_log1p_v3_mint_events"] = np.log1p(
        panel["future_v3_mint_events"].astype(float)
    )
    panel["future_log1p_v3_burn_events"] = np.log1p(
        panel["future_v3_burn_events"].astype(float)
    )
    panel["future_log1p_v3_total_lp_actions"] = np.log1p(
        panel["future_v3_total_lp_actions"].astype(float)
    )
    panel["future_v3_net_mint_event_balance"] = (
        panel["future_v3_net_mint_events"].astype(float)
        / panel["future_v3_total_lp_actions"].astype(float).add(1.0)
    )
    return panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "route_capital_gap_5",
            "is_stable",
            "future_log1p_v3_mint_events",
            "future_log1p_v3_burn_events",
            "future_log1p_v3_total_lp_actions",
            "future_v3_net_mint_event_balance",
        ]
    )


def route_capital_gap_v3_lp_action_response(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gaps predict later V3 mint/burn actions."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_log1p_v3_mint_events",
        "future_log1p_v3_burn_events",
        "future_log1p_v3_total_lp_actions",
        "future_v3_net_mint_event_balance",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "is_stable",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["is_stable"].astype(float)
            )
            residual = absorb_fixed_effects(
                data[
                    [
                        outcome,
                        "route_capital_gap_5",
                        "route_capital_gap_5_x_stable",
                    ]
                ],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5", "route_capital_gap_5_x_stable"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                ("route_capital_gap_5", "route_capital_gap_5_x_stable"),
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_v3_lp_action",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "event_source": "uniswap_v3_graph_mint_burn_events",
                        "interpretation": (
                            "future V3 mint/burn event-count association, not "
                            "dollar-valued provider flow or causal LP response"
                        ),
                    }
                )
            stable_total = linear_contrast(fit, [1.0, 1.0])
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_v3_lp_action",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "event_source": "uniswap_v3_graph_mint_burn_events",
                    "interpretation": (
                        "stable-candidate future V3 mint/burn event-count "
                        "association, not dollar-valued provider flow or causal "
                        "LP response"
                    ),
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_v3_lp_action_candidate_specific(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate candidate-specific V3 LP-action responses to route-capital gaps."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_log1p_v3_mint_events",
        "future_log1p_v3_burn_events",
        "future_log1p_v3_total_lp_actions",
        "future_v3_net_mint_event_balance",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        symbols = sorted(
            str(symbol)
            for symbol in group["candidate_symbol"].dropna().unique()
        )
        if not symbols:
            continue
        predictors = [
            f"route_capital_gap_5_x_{symbol.lower()}" for symbol in symbols
        ]
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "candidate_symbol",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            for symbol, predictor in zip(symbols, predictors, strict=True):
                data[predictor] = np.where(
                    data["candidate_symbol"].eq(symbol),
                    data["route_capital_gap_5"].astype(float),
                    0.0,
                )
            residual = absorb_fixed_effects(
                data[[outcome, *predictors]],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[predictors],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for (
                symbol,
                predictor,
                coefficient,
                standard_error,
                t_statistic,
                p_value,
            ) in zip(
                symbols,
                predictors,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": (
                            "route_capital_gap_v3_lp_action_candidate_specific"
                        ),
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "candidate_symbol": symbol,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "event_source": "uniswap_v3_graph_mint_burn_events",
                        "interpretation": (
                            "candidate-specific future V3 mint/burn event-count "
                            "association, not dollar-valued provider flow or causal "
                            "LP response"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def within_day_gap_associations(panel: pd.DataFrame) -> pd.DataFrame:
    """Estimate whether stable candidates carry extra use relative to capital."""

    data = panel[["origin_date", "route_capital_gap_5", *WITHIN_DAY_GAP_PREDICTORS]].copy()
    residual = absorb_fixed_effects(
        data[["route_capital_gap_5", *WITHIN_DAY_GAP_PREDICTORS]],
        data["origin_date"],
    )
    fit = ols_clustered(
        residual["route_capital_gap_5"],
        residual[list(WITHIN_DAY_GAP_PREDICTORS)],
        data["origin_date"],
        add_constant=False,
        absorbed_groups=(data["origin_date"],),
        min_observations=1000,
        min_clusters=30,
    )
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, t_statistic, p_value in zip(
        WITHIN_DAY_GAP_PREDICTORS,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "within_day_route_capital_gap_association",
                "outcome": "route_capital_gap_5",
                "predictor": predictor,
                "coefficient": float(coefficient),
                "coefficient_pp": 100.0 * float(coefficient),
                "standard_error": float(standard_error),
                "standard_error_pp": 100.0 * float(standard_error),
                "t_statistic": float(t_statistic),
                "p_value": float(p_value),
                "n_observations": int(fit.n_observations),
                "date_clusters": int(fit.n_clusters),
                "fixed_effects": "origin_date",
                "controls": "+".join(
                    predictor
                    for predictor in WITHIN_DAY_GAP_PREDICTORS
                    if predictor != "is_stable"
                ),
                "interpretation": "within-day five-candidate route-minus-capital association, not provider-flow timing",
            }
        )
    return pd.DataFrame(rows)


def route_capital_gap_closing(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route over-use relative to capital predicts later capital."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            residual = absorb_fixed_effects(
                data[[outcome, "route_capital_gap_5"]],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["route_capital_gap_5"]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            coefficient = float(fit.beta[0])
            standard_error = float(fit.standard_errors[0])
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_closing",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "route_capital_gap_5",
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "coefficient_per_10pp_gap": 0.10 * coefficient,
                    "standard_error_per_10pp_gap": 0.10 * standard_error,
                    "coefficient_per_10pp_gap_pp": 10.0 * coefficient,
                    "standard_error_per_10pp_gap_pp": 10.0 * standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": "temporally ordered gap-closing association, not causal provider-flow timing",
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_closing_stable_interactions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route-capital gap closing is stronger for stable candidates."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "candidate_symbol",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["route_capital_gap_5_x_stable"] = (
                data["route_capital_gap_5"].astype(float)
                * data["candidate_symbol"].isin(STABLE_SYMBOLS).astype(float)
            )
            residual = absorb_fixed_effects(
                data[[outcome, *GAP_CLOSING_INTERACTION_PREDICTORS]],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[list(GAP_CLOSING_INTERACTION_PREDICTORS)],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                GAP_CLOSING_INTERACTION_PREDICTORS,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_closing_stable_interaction",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_pp": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_pp": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": "temporally ordered stable-specific gap-closing association, not causal provider-flow timing",
                    }
                )
            try:
                stable_total = linear_contrast(fit, [1.0, 1.0])
            except ValueError:
                continue
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "route_capital_gap_closing_stable_interaction",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "predictor": "stable_total_route_capital_gap_5",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_per_10pp_gap": 0.10 * stable_total.estimate,
                    "standard_error_per_10pp_gap": 0.10 * stable_total.standard_error,
                    "coefficient_per_10pp_gap_pp": 10.0 * stable_total.estimate,
                    "standard_error_per_10pp_gap_pp": 10.0 * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate_address+origin_date",
                    "covariance": "origin_date_clustered",
                    "interpretation": "temporally ordered stable-candidate total gap-closing association, not causal provider-flow timing",
                }
            )
    return pd.DataFrame(rows)


def route_capital_gap_candidate_specific(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate gap-closing slopes separately for each vehicle candidate."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        candidate_symbols = sorted(group["candidate_symbol"].dropna().astype(str).unique())
        predictors = [
            f"route_capital_gap_5_x_{symbol.lower()}" for symbol in candidate_symbols
        ]
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "candidate_symbol",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            data["candidate_symbol"] = data["candidate_symbol"].astype(str)
            for symbol, predictor in zip(candidate_symbols, predictors, strict=True):
                data[predictor] = (
                    data["route_capital_gap_5"].astype(float)
                    * data["candidate_symbol"].eq(symbol).astype(float)
                )
            residual = absorb_fixed_effects(
                data[[outcome, *predictors]],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[predictors],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for symbol, predictor, coefficient, standard_error, t_statistic, p_value in zip(
                candidate_symbols,
                predictors,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_candidate_specific",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "candidate_symbol": symbol,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_pp": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_pp": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "candidate-specific temporally ordered gap-closing "
                            "association, not causal provider-flow timing"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def route_capital_gap_asymmetry(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether capital adjustment differs for shortages and overhangs."""

    rows: list[dict[str, object]] = []
    outcomes = (
        "future_v2_five_candidate_capital_share_change",
        "future_v2_log1p_deposited_capital_usd_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for outcome in outcomes:
            data = (
                group[
                    [
                        "origin_date",
                        "candidate_address",
                        "candidate_symbol",
                        "route_capital_gap_5",
                        outcome,
                    ]
                ]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            stable = data["candidate_symbol"].isin(STABLE_SYMBOLS).astype(float)
            data["positive_route_capital_gap_5"] = data[
                "route_capital_gap_5"
            ].clip(lower=0.0)
            data["negative_route_capital_gap_5"] = data[
                "route_capital_gap_5"
            ].clip(upper=0.0)
            data["positive_route_capital_gap_5_x_stable"] = (
                data["positive_route_capital_gap_5"] * stable
            )
            data["negative_route_capital_gap_5_x_stable"] = (
                data["negative_route_capital_gap_5"] * stable
            )
            residual = absorb_fixed_effects(
                data[[outcome, *GAP_ASYMMETRY_PREDICTORS]],
                data["candidate_address"],
                data["origin_date"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[list(GAP_ASYMMETRY_PREDICTORS)],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                GAP_ASYMMETRY_PREDICTORS,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_asymmetry",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "coefficient_per_10pp_gap": 0.10 * coefficient,
                        "standard_error_per_10pp_gap": 0.10 * standard_error,
                        "coefficient_per_10pp_gap_pp": 10.0 * coefficient,
                        "standard_error_per_10pp_gap_pp": 10.0 * standard_error,
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "piecewise temporally ordered gap-adjustment association, "
                            "not causal provider-flow timing"
                        ),
                    }
                )
            contrasts = {
                "stable_total_positive_route_capital_gap_5": [1.0, 0.0, 1.0, 0.0],
                "stable_total_negative_route_capital_gap_5": [0.0, 1.0, 0.0, 1.0],
            }
            for predictor, weights in contrasts.items():
                try:
                    contrast = linear_contrast(fit, weights)
                except ValueError:
                    continue
                rows.append(
                    {
                        "analysis_status": "exploratory_descriptive",
                        "record_type": "route_capital_gap_asymmetry",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": contrast.estimate,
                        "standard_error": contrast.standard_error,
                        "t_statistic": contrast.t_statistic,
                        "p_value": contrast.p_value,
                        "coefficient_per_10pp_gap": 0.10 * contrast.estimate,
                        "standard_error_per_10pp_gap": 0.10
                        * contrast.standard_error,
                        "coefficient_per_10pp_gap_pp": 10.0 * contrast.estimate,
                        "standard_error_per_10pp_gap_pp": 10.0
                        * contrast.standard_error,
                        "effect_per_10pp_stable_overcapitalization": (
                            -0.10 * contrast.estimate
                            if predictor
                            == "stable_total_negative_route_capital_gap_5"
                            else np.nan
                        ),
                        "effect_per_10pp_stable_overcapitalization_pp": (
                            -10.0 * contrast.estimate
                            if predictor
                            == "stable_total_negative_route_capital_gap_5"
                            else np.nan
                        ),
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_address+origin_date",
                        "covariance": "origin_date_clustered",
                        "interpretation": (
                            "stable-candidate piecewise gap-adjustment total, "
                            "not causal provider-flow timing"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def stable_basket_gap_horizon_panel(
    sample: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (30, 120),
) -> pd.DataFrame:
    """Attach stable-basket route-minus-capital gaps to future capital shares."""

    if not horizons:
        raise ValueError("at least one stable-basket horizon is required")
    rows: list[dict[str, object]] = []
    for date, group in sample.groupby("origin_date", sort=True):
        route_total = float(group["intermediate_route_count"].sum())
        capital_total = float(group["v2_deposited_capital_usd"].sum())
        if route_total <= 0 or capital_total <= 0:
            continue
        stable = group[group["candidate_symbol"].isin(STABLE_SYMBOLS)]
        weth = group[group["candidate_symbol"].eq(WETH_SYMBOL)]
        wbtc = group[group["candidate_symbol"].eq("WBTC")]
        stable_route_share = float(stable["intermediate_route_count"].sum()) / route_total
        stable_capital_share = float(stable["v2_deposited_capital_usd"].sum()) / capital_total
        rows.append(
            {
                "origin_date": date,
                "stable_route_share": stable_route_share,
                "stable_capital_share": stable_capital_share,
                "weth_capital_share": float(weth["v2_deposited_capital_usd"].sum())
                / capital_total,
                "wbtc_capital_share": float(wbtc["v2_deposited_capital_usd"].sum())
                / capital_total,
                "stable_route_capital_gap": stable_route_share - stable_capital_share,
                "log_total_routes": np.log1p(route_total),
                "log_total_capital": np.log1p(capital_total),
            }
        )
    daily = pd.DataFrame(rows).sort_values("origin_date").reset_index(drop=True)
    if daily.empty:
        raise ValueError("stable-basket daily panel is empty")
    horizon_rows: list[pd.DataFrame] = []
    target_columns = [
        "origin_date",
        "stable_capital_share",
        "weth_capital_share",
        "wbtc_capital_share",
    ]
    for horizon in horizons:
        target = daily[target_columns].copy()
        target["origin_date"] = target["origin_date"] - pd.Timedelta(days=horizon)
        joined = daily.merge(
            target,
            on="origin_date",
            how="inner",
            suffixes=("", "_target"),
            validate="one_to_one",
        )
        if joined.empty:
            continue
        joined["horizon_days"] = int(horizon)
        for asset in ("stable", "weth", "wbtc"):
            joined[f"future_{asset}_capital_share_change"] = (
                joined[f"{asset}_capital_share_target"]
                - joined[f"{asset}_capital_share"]
            )
        horizon_rows.append(joined)
    if not horizon_rows:
        raise ValueError("stable-basket horizon panel is empty")
    panel = pd.concat(horizon_rows, ignore_index=True, sort=False)
    required = [
        "stable_route_capital_gap",
        "future_stable_capital_share_change",
        "future_weth_capital_share_change",
        "future_wbtc_capital_share_change",
        "log_total_routes",
        "log_total_capital",
    ]
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    if panel.empty:
        raise ValueError("stable-basket horizon panel lost all rows")
    return panel


def stable_basket_gap_portfolio_rebalancing(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether stable-basket route demand predicts portfolio rebalancing."""

    rows: list[dict[str, object]] = []
    models = {
        "gap_only": ("stable_route_capital_gap",),
        "activity_controls": (
            "stable_route_capital_gap",
            "log_total_routes",
            "log_total_capital",
        ),
    }
    outcomes = (
        "future_stable_capital_share_change",
        "future_weth_capital_share_change",
        "future_wbtc_capital_share_change",
    )
    for horizon, group in panel.groupby("horizon_days", sort=True):
        for model_id, predictors in models.items():
            for outcome in outcomes:
                data = (
                    group[["origin_date", outcome, *predictors]]
                    .replace([np.inf, -np.inf], np.nan)
                    .dropna()
                    .copy()
                )
                fit = ols_clustered(
                    data[outcome],
                    data[list(predictors)],
                    data["origin_date"],
                    add_constant=True,
                    min_observations=min_observations,
                    min_clusters=min_clusters,
                    cluster_hac_lag=HAC_LAG_DAYS,
                )
                for index, predictor in enumerate(predictors, start=1):
                    coefficient = float(fit.beta[index])
                    standard_error = float(fit.standard_errors[index])
                    rows.append(
                        {
                            "analysis_status": "exploratory_descriptive",
                            "record_type": "stable_basket_gap_portfolio_rebalancing",
                            "model_id": model_id,
                            "horizon_days": int(horizon),
                            "outcome": outcome,
                            "predictor": predictor,
                            "coefficient": coefficient,
                            "standard_error": standard_error,
                            "t_statistic": float(fit.t_statistics[index]),
                            "p_value": float(fit.p_values[index]),
                            "coefficient_per_10pp_gap": (
                                0.10 * coefficient
                                if predictor == "stable_route_capital_gap"
                                else np.nan
                            ),
                            "standard_error_per_10pp_gap": (
                                0.10 * standard_error
                                if predictor == "stable_route_capital_gap"
                                else np.nan
                            ),
                            "coefficient_per_10pp_gap_pp": (
                                10.0 * coefficient
                                if predictor == "stable_route_capital_gap"
                                else np.nan
                            ),
                            "standard_error_per_10pp_gap_pp": (
                                10.0 * standard_error
                                if predictor == "stable_route_capital_gap"
                                else np.nan
                            ),
                            "n_observations": int(fit.n_observations),
                            "date_clusters": int(fit.n_clusters),
                            "covariance": (
                                "newey_west_actual_calendar_day_lag_"
                                f"{HAC_LAG_DAYS}"
                            ),
                            "interpretation": (
                                "stable-basket portfolio rebalancing association, "
                                "not causal provider-flow timing"
                            ),
                        }
                    )
    return pd.DataFrame(rows)


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


def support_rows(
    sample: pd.DataFrame,
    *,
    v3_lp_actions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "record_type": "support",
            "analysis_status": "exploratory_descriptive",
            "input": str(CANDIDATE_DAY_INPUT.relative_to(REPO_ROOT)),
            "exact_horizon_input": str(EXACT_HORIZON_INPUT.relative_to(REPO_ROOT)),
            "pool_candidate_capital_input": str(
                POOL_CANDIDATE_CAPITAL_INPUT.relative_to(REPO_ROOT)
            ),
            "v3_pool_day_fee_input": str(
                V3_POOL_DAY_FEES_INPUT.relative_to(REPO_ROOT)
            ),
            "v3_lp_action_candidate_input": str(
                V3_LP_ACTION_INPUT.relative_to(REPO_ROOT)
            ),
            "candidate_day_rows": int(len(sample)),
            "days": int(sample["origin_date"].nunique()),
            "candidate_count": int(sample["candidate_symbol"].nunique()),
            "first_date": sample["origin_date"].min().strftime("%Y-%m-%d"),
            "last_date": sample["origin_date"].max().strftime("%Y-%m-%d"),
            "stable_symbols": ",".join(sorted(STABLE_SYMBOLS)),
            "quantity": (
                "V2 deposited-capital stock plus Uniswap V3 mint/burn event "
                "counts; no dollar-valued provider flows"
            ),
        }
    ]
    if v3_lp_actions is not None:
        rows.append(
            {
                "record_type": "v3_lp_action_input_support",
                "analysis_status": "exploratory_descriptive",
                "input": str(V3_LP_ACTION_INPUT.relative_to(REPO_ROOT)),
                "candidate_day_action_rows": int(len(v3_lp_actions)),
                "days": int(v3_lp_actions["origin_date"].nunique())
                if not v3_lp_actions.empty
                else 0,
                "candidate_count": int(v3_lp_actions["candidate_address"].nunique())
                if not v3_lp_actions.empty
                else 0,
                "first_date": v3_lp_actions["origin_date"].min().strftime("%Y-%m-%d")
                if not v3_lp_actions.empty
                else None,
                "last_date": v3_lp_actions["origin_date"].max().strftime("%Y-%m-%d")
                if not v3_lp_actions.empty
                else None,
                "quantity": (
                    "processed Uniswap V3 mint/burn event counts by vehicle "
                    "candidate and day, not dollar-valued provider flows"
                ),
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    input_path: Path = CANDIDATE_DAY_INPUT,
    exact_horizon_path: Path = EXACT_HORIZON_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    sample = supported_candidate_days(load_candidate_day(input_path))
    exact_horizons = load_exact_horizons(exact_horizon_path)
    exact_panel = route_capital_gap_horizon_panel(exact_horizons)
    rank_transition_panel = route_capital_gap_rank_transition_panel(exact_horizons)
    daily_gaps = daily_capital_use_gaps(sample)
    share_gap_panel = candidate_share_gap_panel(sample)
    extensive_margin_panel = route_capital_gap_extensive_margin_panel(sample)
    concentration_panel = candidate_capital_concentration_panel(share_gap_panel)
    concentration_horizon_panel = route_capital_gap_concentration_horizon_panel(
        concentration_panel
    )
    stable_basket_panel = stable_basket_gap_horizon_panel(sample)
    same_pool_panel = route_capital_gap_pool_candidate_horizon_panel(share_gap_panel)
    pool_entry_panel = route_capital_gap_pool_entry_horizon_panel(share_gap_panel)
    fee_incidence_panel = route_capital_gap_v3_fee_horizon_panel(share_gap_panel)
    v3_lp_actions = load_v3_lp_actions()
    v3_lp_action_panel = route_capital_gap_v3_lp_action_horizon_panel(
        share_gap_panel,
        actions=v3_lp_actions,
    )
    result = pd.concat(
        [
            annual_stable_allocation(sample),
            capital_use_gap_summaries(daily_gaps),
            daily_leader_alignment(sample),
            candidate_profiles(sample),
            level_associations(sample),
            within_day_gap_associations(share_gap_panel),
            route_capital_gap_closing(exact_panel),
            route_capital_gap_closing_stable_interactions(exact_panel),
            route_capital_gap_candidate_specific(exact_panel),
            route_capital_gap_asymmetry(exact_panel),
            route_capital_gap_rank_transition(rank_transition_panel),
            stable_basket_gap_portfolio_rebalancing(stable_basket_panel),
            route_capital_gap_extensive_margins(extensive_margin_panel),
            capital_concentration_summaries(concentration_panel),
            route_capital_gap_concentration_response(concentration_horizon_panel),
            route_capital_gap_same_pool_reallocation(same_pool_panel),
            route_capital_gap_pool_entry_response(pool_entry_panel),
            route_capital_gap_v3_fee_incidence(fee_incidence_panel),
            route_capital_gap_v3_lp_action_response(v3_lp_action_panel),
            route_capital_gap_v3_lp_action_candidate_specific(v3_lp_action_panel),
        ],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    support = support_rows(sample, v3_lp_actions=v3_lp_actions)
    write_exhibit(
        support,
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(result):,} liquidity-provision behavior rows and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--exact-horizon", type=Path, default=EXACT_HORIZON_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        input_path=args.input,
        exact_horizon_path=args.exact_horizon,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
