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


def support_rows(sample: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
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
    exact_horizon_path: Path = EXACT_HORIZON_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    sample = supported_candidate_days(load_candidate_day(input_path))
    exact_panel = route_capital_gap_horizon_panel(load_exact_horizons(exact_horizon_path))
    daily_gaps = daily_capital_use_gaps(sample)
    share_gap_panel = candidate_share_gap_panel(sample)
    extensive_margin_panel = route_capital_gap_extensive_margin_panel(sample)
    stable_basket_panel = stable_basket_gap_horizon_panel(sample)
    same_pool_panel = route_capital_gap_pool_candidate_horizon_panel(share_gap_panel)
    fee_incidence_panel = route_capital_gap_v3_fee_horizon_panel(share_gap_panel)
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
            stable_basket_gap_portfolio_rebalancing(stable_basket_panel),
            route_capital_gap_extensive_margins(extensive_margin_panel),
            route_capital_gap_same_pool_reallocation(same_pool_panel),
            route_capital_gap_v3_fee_incidence(fee_incidence_panel),
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
