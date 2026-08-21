#!/usr/bin/env python3
"""Relate lagged V3 gross fee opportunity and price risk to provider supply.

The unit is an endpoint--candidate Uniswap V3 pool week.  Outcomes are the
following week's candidate-side mint and burn value after separating same-pool
same-transaction burn--mint repositioning, with transaction counts as a
coverage-robust check.  Predictors use only weeks t-3 through t:
pool fee yield, endpoint--candidate relative-price risk, earlier LP flows, TVL,
and observed pool age.

Endpoint-by-week and pool fixed effects compare stablecoin and WETH pools for
the same endpoint while absorbing persistent pool differences.  The estimates
are predictive supply responses.  Pool-level fees divided by TVL are an LP
opportunity proxy, and the constant-product divergence-loss measure is only a
common risk proxy for concentrated positions.  No trade allocation or route
choice enters the analysis.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, linear_contrast, ols_clustered
from ddvc.capital_contracts import MAX_POOL_CAPITAL_USD
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


FLOW_INPUT = DATA_DIR / "processed/v3_lp_flow_pool_daily.parquet"
FEE_INPUT = DATA_DIR / "processed/v3_pool_day_fees.parquet"
PRICE_INPUT = DATA_DIR / "processed/token_price_daily.parquet"
PANEL_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_supply_returns_weekly.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_supply_returns_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_supply_returns_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = {WETH: "WETH", DAI: "DAI", USDC: "USDC", USDT: "USDT"}

MAIN_TVL_THRESHOLD = 50_000.0
SENSITIVITY_THRESHOLDS = (10_000.0, 100_000.0)
TRAILING_WEEKS = 4
MIN_TRAILING_RETURN_DAYS = 20
PRE_PROTOCOL_FEE_END = pd.Timestamp("2025-12-21")
MAX_TVL_STALENESS_WEEKS = 4

CODE_SOURCES = ["scripts/analyze/run_v3_lp_supply_returns.py"]
INPUTS = [
    "data/processed/v3_lp_flow_pool_daily.parquet",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/token_price_daily.parquet",
]


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    outcome: str
    risk_predictor: str
    stable_risk_predictor: str


MAIN_MODEL_SPECS = (
    ModelSpec(
        "m1_next_week_net_add_remove_only_flow",
        "next_asinh_net_add_remove_only_flow_kusd",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
    ModelSpec(
        "m2_next_week_add_only_flow",
        "next_log1p_add_only_flow_kusd",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
    ModelSpec(
        "m3_next_week_remove_only_flow",
        "next_log1p_remove_only_flow_kusd",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
    ModelSpec(
        "m4_next_week_net_flow_tvl_scaled",
        "next_asinh_net_flow_ratio",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
    ModelSpec(
        "m5_next_week_net_flow_relative_volatility",
        "next_asinh_net_add_remove_only_flow_kusd",
        "trailing_relative_volatility_per_10pp",
        "stable_x_relative_volatility",
    ),
    ModelSpec(
        "m6_next_week_add_only_transactions",
        "next_log1p_add_only_transactions",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
    ModelSpec(
        "m7_next_week_remove_only_transactions",
        "next_log1p_remove_only_transactions",
        "trailing_cp_divergence_proxy_bps",
        "stable_x_cp_divergence_proxy",
    ),
)


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _parquet_columns(path: Path) -> set[str]:
    connection = duckdb.connect()
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        }
    finally:
        connection.close()


def load_weekly_v3_lp_panel(
    *,
    flow_path: Path = FLOW_INPUT,
    fee_path: Path = FEE_INPUT,
    price_path: Path = PRICE_INPUT,
) -> pd.DataFrame:
    """Build a balanced pool-week base and pair-week risk from retained data."""

    for path in (flow_path, fee_path, price_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    flow_columns = _parquet_columns(flow_path)
    required_flow = {
        "origin_date",
        "pool",
        "candidate_address",
        "v3_add_only_lp_flow_usd_screened",
        "v3_remove_only_lp_flow_usd_screened",
        "v3_net_add_remove_only_lp_flow_usd_screened",
        "v3_add_action_events",
        "v3_remove_action_events",
        "v3_add_only_action_transactions",
        "v3_remove_only_action_transactions",
        "v3_reposition_action_transactions",
    }
    missing_flow = sorted(required_flow - flow_columns)
    if missing_flow:
        raise ValueError(f"V3 pool-day LP-flow panel lacks columns: {missing_flow}")
    fee_columns = _parquet_columns(fee_path)
    required_fee = {
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "gross_fees_usd",
        "volume_usd",
        "tvl_usd",
    }
    missing_fee = sorted(required_fee - fee_columns)
    if missing_fee:
        raise ValueError(f"V3 fee panel lacks columns: {missing_fee}")
    price_columns = _parquet_columns(price_path)
    price_filters = ["price_usd > 0"]
    if "price_source" in price_columns:
        price_filters.append("price_source = 'canonical_repriced_route_legs'")
    if "validation_status" in price_columns:
        price_filters.append(
            "validation_status = 'minimum_observations_and_price_consensus_passed'"
        )
    price_filter_sql = " AND ".join(price_filters)
    candidate_values = ",".join(f"'{address}'" for address in CANDIDATES)
    candidate_case = " ".join(
        f"WHEN candidate_address = '{address}' THEN '{symbol}'"
        for address, symbol in CANDIDATES.items()
    )
    query = f"""
    WITH fee_base AS (
        SELECT
            CAST(origin_date AS DATE) AS origin_date,
            lower(pool) AS pool,
            lower(token0_address) AS token0_address,
            lower(token1_address) AS token1_address,
            gross_fees_usd::DOUBLE AS gross_fees_usd,
            volume_usd::DOUBLE AS volume_usd,
            tvl_usd::DOUBLE AS tvl_usd,
            CASE
                WHEN lower(token0_address) IN ({candidate_values})
                    THEN lower(token0_address)
                ELSE lower(token1_address)
            END AS candidate_address,
            CASE
                WHEN lower(token0_address) IN ({candidate_values})
                    THEN lower(token1_address)
                ELSE lower(token0_address)
            END AS endpoint_address
        FROM read_parquet('{_sql_path(fee_path)}')
        WHERE tvl_usd >= 0
          AND CAST(origin_date AS DATE) <= DATE '{PRE_PROTOCOL_FEE_END:%Y-%m-%d}'
          AND (
                (lower(token0_address) IN ({candidate_values}))::INTEGER
              + (lower(token1_address) IN ({candidate_values}))::INTEGER
          ) = 1
    ),
    fee AS (
        SELECT
            *,
            CASE {candidate_case} END AS candidate_symbol,
            CASE WHEN candidate_address = '{WETH}'
                 THEN 'native' ELSE 'stable' END AS candidate_type
        FROM fee_base
    ),
    registry AS (
        SELECT
            pool,
            min(candidate_address) AS candidate_address,
            min(candidate_symbol) AS candidate_symbol,
            min(candidate_type) AS candidate_type,
            min(endpoint_address) AS endpoint_address,
            min(date_trunc('week', origin_date)::DATE) AS first_week
        FROM fee
        GROUP BY pool
        HAVING count(DISTINCT candidate_address) = 1
           AND count(DISTINCT endpoint_address) = 1
    ),
    bounds AS (
        SELECT max(date_trunc('week', origin_date)::DATE) AS last_week
        FROM fee
    ),
    skeleton AS (
        SELECT
            r.*,
            series.origin_week::DATE AS origin_week
        FROM registry r
        CROSS JOIN bounds b
        CROSS JOIN LATERAL generate_series(
            r.first_week, b.last_week, INTERVAL '7 days'
        ) AS series(origin_week)
    ),
    weekly_fee AS (
        SELECT
            date_trunc('week', origin_date)::DATE AS origin_week,
            pool,
            sum(gross_fees_usd)::DOUBLE AS gross_fees_usd,
            sum(volume_usd)::DOUBLE AS volume_usd,
            arg_max(tvl_usd, origin_date)::DOUBLE AS updated_tvl_usd,
            count(*)::INTEGER AS pool_update_days
        FROM fee
        GROUP BY 1,2
    ),
    weekly_flow AS (
        SELECT
            date_trunc('week', CAST(origin_date AS DATE))::DATE AS origin_week,
            lower(pool) AS pool,
            lower(candidate_address) AS candidate_address,
            sum(v3_add_only_lp_flow_usd_screened)::DOUBLE AS add_flow_usd,
            sum(v3_remove_only_lp_flow_usd_screened)::DOUBLE AS remove_flow_usd,
            sum(v3_net_add_remove_only_lp_flow_usd_screened)::DOUBLE
                AS net_add_flow_usd,
            sum(v3_add_action_events)::DOUBLE AS add_actions,
            sum(v3_remove_action_events)::DOUBLE AS remove_actions,
            sum(v3_add_only_action_transactions)::DOUBLE AS add_only_transactions,
            sum(v3_remove_only_action_transactions)::DOUBLE
                AS remove_only_transactions,
            sum(v3_reposition_action_transactions)::DOUBLE AS reposition_transactions
        FROM read_parquet('{_sql_path(flow_path)}')
        WHERE CAST(origin_date AS DATE) <= DATE '{PRE_PROTOCOL_FEE_END:%Y-%m-%d}'
        GROUP BY 1,2,3
    ),
    price_level AS (
        SELECT
            strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
            lower(token) AS token,
            ln(price_usd)::DOUBLE AS log_price,
            lag(ln(price_usd)) OVER (
                PARTITION BY lower(token)
                ORDER BY strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE
            )::DOUBLE AS lag_log_price,
            lag(strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE) OVER (
                PARTITION BY lower(token)
                ORDER BY strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE
            ) AS lag_date
        FROM read_parquet('{_sql_path(price_path)}')
        WHERE {price_filter_sql}
    ),
    token_return AS (
        SELECT origin_date, token, log_price - lag_log_price AS log_return
        FROM price_level
        WHERE date_diff('day', lag_date, origin_date) = 1
    ),
    pair_return AS (
        SELECT
            pairs.endpoint_address,
            pairs.candidate_address,
            e.origin_date,
            e.log_return - c.log_return AS relative_return
        FROM (
            SELECT DISTINCT endpoint_address, candidate_address FROM registry
        ) pairs
        JOIN token_return e ON e.token = pairs.endpoint_address
        JOIN token_return c
          ON c.token = pairs.candidate_address
         AND c.origin_date = e.origin_date
        WHERE e.origin_date <= DATE '{PRE_PROTOCOL_FEE_END:%Y-%m-%d}'
    ),
    pair_risk AS (
        SELECT
            endpoint_address,
            candidate_address,
            date_trunc('week', origin_date)::DATE AS origin_week,
            sum(relative_return * relative_return)::DOUBLE
                AS relative_return_sq_sum,
            sum(
                (1.0 - 1.0 / cosh(relative_return / 2.0)) * 10000.0
            )::DOUBLE AS cp_divergence_proxy_bps_sum,
            count(*)::INTEGER AS return_days
        FROM pair_return
        GROUP BY 1,2,3
    ),
    joined AS (
        SELECT
            s.*,
            w.updated_tvl_usd,
            coalesce(w.gross_fees_usd, 0.0)::DOUBLE AS gross_fees_usd,
            coalesce(w.volume_usd, 0.0)::DOUBLE AS volume_usd,
            coalesce(w.pool_update_days, 0)::INTEGER AS pool_update_days,
            coalesce(l.add_flow_usd, 0.0)::DOUBLE AS add_flow_usd,
            coalesce(l.remove_flow_usd, 0.0)::DOUBLE AS remove_flow_usd,
            coalesce(l.net_add_flow_usd, 0.0)::DOUBLE AS net_add_flow_usd,
            coalesce(l.add_actions, 0.0)::DOUBLE AS add_actions,
            coalesce(l.remove_actions, 0.0)::DOUBLE AS remove_actions,
            coalesce(l.add_only_transactions, 0.0)::DOUBLE
                AS add_only_transactions,
            coalesce(l.remove_only_transactions, 0.0)::DOUBLE
                AS remove_only_transactions,
            coalesce(l.reposition_transactions, 0.0)::DOUBLE
                AS same_tx_reposition_transactions,
            r.relative_return_sq_sum,
            r.cp_divergence_proxy_bps_sum,
            r.return_days
        FROM skeleton s
        LEFT JOIN weekly_fee w
          ON w.pool = s.pool AND w.origin_week = s.origin_week
        LEFT JOIN weekly_flow l
          ON l.pool = s.pool
         AND l.candidate_address = s.candidate_address
         AND l.origin_week = s.origin_week
        LEFT JOIN pair_risk r
          ON r.endpoint_address = s.endpoint_address
         AND r.candidate_address = s.candidate_address
         AND r.origin_week = s.origin_week
    )
    SELECT
        origin_week,
        'uniswap_v3' AS venue,
        pool,
        candidate_address,
        candidate_symbol,
        candidate_type,
        endpoint_address,
        first_week,
        last_value(updated_tvl_usd IGNORE NULLS) OVER (
            PARTITION BY pool ORDER BY origin_week
        )::DOUBLE AS tvl_usd,
        last_value(
            CASE WHEN updated_tvl_usd IS NOT NULL THEN origin_week END
            IGNORE NULLS
        ) OVER (
            PARTITION BY pool ORDER BY origin_week
        )::DATE AS last_tvl_update_week,
        gross_fees_usd,
        volume_usd,
        pool_update_days,
        add_flow_usd,
        remove_flow_usd,
        net_add_flow_usd,
        add_actions,
        remove_actions,
        add_only_transactions,
        remove_only_transactions,
        same_tx_reposition_transactions,
        relative_return_sq_sum,
        cp_divergence_proxy_bps_sum,
        return_days
    FROM joined
    ORDER BY pool, origin_week
    """
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        connection.execute("PRAGMA memory_limit='32GB'")
        connection.execute("PRAGMA preserve_insertion_order=false")
        frame = connection.execute(query).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("V3 LP-supply weekly base is empty")
    frame["origin_week"] = pd.to_datetime(frame["origin_week"]).dt.normalize()
    frame["first_week"] = pd.to_datetime(frame["first_week"]).dt.normalize()
    if frame.duplicated(["pool", "origin_week"]).any():
        raise ValueError("V3 LP-supply weekly base has duplicate pool-weeks")
    return frame


def prepare_weekly_panel(
    weekly_base: pd.DataFrame,
    *,
    trailing_weeks: int = TRAILING_WEEKS,
    min_trailing_return_days: int = MIN_TRAILING_RETURN_DAYS,
) -> pd.DataFrame:
    """Add four-week lagged predictors and next-week supply outcomes."""

    required = {
        "origin_week",
        "venue",
        "pool",
        "candidate_address",
        "candidate_symbol",
        "candidate_type",
        "endpoint_address",
        "first_week",
        "last_tvl_update_week",
        "gross_fees_usd",
        "tvl_usd",
        "add_flow_usd",
        "remove_flow_usd",
        "net_add_flow_usd",
        "add_only_transactions",
        "remove_only_transactions",
        "same_tx_reposition_transactions",
        "relative_return_sq_sum",
        "cp_divergence_proxy_bps_sum",
        "return_days",
    }
    missing = sorted(required - set(weekly_base.columns))
    if missing:
        raise ValueError(f"V3 LP-supply weekly input lacks columns: {missing}")
    if trailing_weeks < 2:
        raise ValueError("V3 LP-supply trailing window requires at least two weeks")
    weekly = weekly_base.copy()
    weekly["origin_week"] = pd.to_datetime(weekly["origin_week"]).dt.normalize()
    weekly = weekly.sort_values(["pool", "origin_week"]).reset_index(drop=True)
    if weekly.duplicated(["pool", "origin_week"]).any():
        raise ValueError("V3 LP-supply weekly base has duplicate pool-weeks")
    rolling = weekly.groupby("pool", sort=False)
    for source, target in (
        ("gross_fees_usd", "trailing_gross_fees_usd"),
        ("add_flow_usd", "trailing_add_flow_usd"),
        ("remove_flow_usd", "trailing_remove_flow_usd"),
        ("tvl_usd", "trailing_mean_tvl_usd"),
        ("relative_return_sq_sum", "trailing_relative_return_sq_sum"),
        (
            "cp_divergence_proxy_bps_sum",
            "trailing_cp_divergence_proxy_bps_sum",
        ),
        ("return_days", "trailing_return_days"),
    ):
        weekly[target] = (
            rolling[source]
            .rolling(trailing_weeks, min_periods=trailing_weeks)
            .sum()
            .reset_index(level=0, drop=True)
        )
    weekly["trailing_mean_tvl_usd"] /= float(trailing_weeks)
    weekly["trailing_start_week"] = rolling["origin_week"].shift(
        trailing_weeks - 1
    )
    weekly["consecutive_trailing_weeks"] = weekly["trailing_start_week"].eq(
        weekly["origin_week"]
        - pd.to_timedelta(7 * (trailing_weeks - 1), unit="D")
    )
    weekly["trailing_fee_yield_bps"] = 10_000.0 * (
        weekly["trailing_gross_fees_usd"] / weekly["trailing_mean_tvl_usd"]
    )
    weekly["trailing_add_flow_ratio"] = (
        weekly["trailing_add_flow_usd"] / weekly["trailing_mean_tvl_usd"]
    )
    weekly["trailing_remove_flow_ratio"] = (
        weekly["trailing_remove_flow_usd"] / weekly["trailing_mean_tvl_usd"]
    )
    weekly["trailing_log1p_add_flow_ratio"] = np.log1p(
        weekly["trailing_add_flow_ratio"].clip(lower=0)
    )
    weekly["trailing_log1p_remove_flow_ratio"] = np.log1p(
        weekly["trailing_remove_flow_ratio"].clip(lower=0)
    )
    weekly["trailing_relative_volatility"] = np.sqrt(
        365.0
        * weekly["trailing_relative_return_sq_sum"]
        / weekly["trailing_return_days"]
    )
    weekly["trailing_cp_divergence_proxy_bps"] = (
        weekly["trailing_cp_divergence_proxy_bps_sum"]
        / weekly["trailing_return_days"]
    )
    weekly["observed_pool_age_weeks"] = (
        (weekly["origin_week"] - pd.to_datetime(weekly["first_week"])).dt.days
        / 7.0
    ).clip(lower=0)
    weekly["tvl_staleness_weeks"] = (
        (
            weekly["origin_week"]
            - pd.to_datetime(weekly["last_tvl_update_week"])
        ).dt.days
        / 7.0
    )
    for source, target in (
        ("origin_week", "next_origin_week"),
        ("add_flow_usd", "next_add_flow_usd"),
        ("remove_flow_usd", "next_remove_flow_usd"),
        ("net_add_flow_usd", "next_net_add_flow_usd"),
        ("add_only_transactions", "next_add_only_transactions"),
        ("remove_only_transactions", "next_remove_only_transactions"),
        (
            "same_tx_reposition_transactions",
            "next_same_tx_reposition_transactions",
        ),
    ):
        weekly[target] = rolling[source].shift(-1)
    weekly["consecutive_next_week"] = weekly["next_origin_week"].eq(
        weekly["origin_week"] + pd.Timedelta(days=7)
    )
    denominator = weekly["tvl_usd"].where(weekly["tvl_usd"] > 0)
    weekly["next_add_flow_ratio"] = weekly["next_add_flow_usd"] / denominator
    weekly["next_remove_flow_ratio"] = weekly["next_remove_flow_usd"] / denominator
    weekly["next_net_flow_ratio"] = weekly["next_net_add_flow_usd"] / denominator
    weekly["next_log1p_add_flow_ratio"] = np.log1p(
        weekly["next_add_flow_ratio"].clip(lower=0)
    )
    weekly["next_log1p_remove_flow_ratio"] = np.log1p(
        weekly["next_remove_flow_ratio"].clip(lower=0)
    )
    weekly["next_asinh_net_flow_ratio"] = np.arcsinh(
        weekly["next_net_flow_ratio"]
    )
    weekly["next_asinh_net_add_remove_only_flow_kusd"] = np.arcsinh(
        weekly["next_net_add_flow_usd"] / 1_000.0
    )
    weekly["next_log1p_add_only_flow_kusd"] = np.log1p(
        weekly["next_add_flow_usd"] / 1_000.0
    )
    weekly["next_log1p_remove_only_flow_kusd"] = np.log1p(
        weekly["next_remove_flow_usd"] / 1_000.0
    )
    weekly["next_log1p_add_only_transactions"] = np.log1p(
        weekly["next_add_only_transactions"]
    )
    weekly["next_log1p_remove_only_transactions"] = np.log1p(
        weekly["next_remove_only_transactions"]
    )
    weekly["stable_indicator"] = weekly["candidate_type"].eq("stable").astype(float)
    weekly["fee_yield_per_10bps"] = weekly["trailing_fee_yield_bps"] / 10.0
    weekly["trailing_relative_volatility_per_10pp"] = (
        weekly["trailing_relative_volatility"] / 0.10
    )
    weekly["stable_x_fee_yield"] = (
        weekly["stable_indicator"] * weekly["fee_yield_per_10bps"]
    )
    weekly["stable_x_cp_divergence_proxy"] = (
        weekly["stable_indicator"] * weekly["trailing_cp_divergence_proxy_bps"]
    )
    weekly["stable_x_relative_volatility"] = (
        weekly["stable_indicator"]
        * weekly["trailing_relative_volatility_per_10pp"]
    )
    weekly["log_tvl_usd"] = np.log(weekly["tvl_usd"])
    weekly["log1p_observed_pool_age_weeks"] = np.log1p(
        weekly["observed_pool_age_weeks"]
    )
    weekly["pool_id"] = "uniswap_v3|" + weekly["pool"].astype(str)
    weekly["endpoint_week_id"] = (
        weekly["endpoint_address"].astype(str)
        + "|"
        + weekly["origin_week"].dt.strftime("%Y%m%d")
    )
    valid = (
        weekly["consecutive_trailing_weeks"]
        & weekly["consecutive_next_week"]
        & weekly["trailing_return_days"].ge(min_trailing_return_days)
    )
    weekly = weekly.loc[valid].replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
    if weekly.empty:
        raise ValueError("V3 LP-supply weekly panel has no valid histories")
    return weekly


def comparison_sample(
    panel: pd.DataFrame,
    tvl_threshold: float,
    *,
    max_tvl_staleness_weeks: int = MAX_TVL_STALENESS_WEEKS,
) -> pd.DataFrame:
    """Keep endpoint-weeks with material native and stable V3 pools."""

    if tvl_threshold <= 0:
        raise ValueError("V3 LP-supply TVL threshold must be positive")
    data = panel[
        panel["tvl_usd"].ge(tvl_threshold)
        & panel["tvl_usd"].le(MAX_POOL_CAPITAL_USD)
        & panel["tvl_staleness_weeks"].le(max_tvl_staleness_weeks)
    ].copy()
    cells = data.groupby("endpoint_week_id")["candidate_type"].agg(set)
    eligible = cells[cells.map(lambda values: {"native", "stable"}.issubset(values))].index
    data = data[data["endpoint_week_id"].isin(eligible)].reset_index(drop=True)
    if data.empty:
        raise ValueError(f"V3 LP-supply comparison is empty at ${tvl_threshold:,.0f}")
    return data


def _fit_spec(
    data: pd.DataFrame,
    spec: ModelSpec,
    *,
    tvl_threshold: float,
    min_observations: int,
    min_pool_clusters: int,
    min_week_clusters: int,
) -> list[dict[str, object]]:
    predictors = [
        "fee_yield_per_10bps",
        spec.risk_predictor,
        "stable_x_fee_yield",
        spec.stable_risk_predictor,
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_tvl_usd",
        "log1p_observed_pool_age_weeks",
    ]
    columns = [
        spec.outcome,
        *predictors,
        "stable_indicator",
        "endpoint_week_id",
        "pool_id",
        "origin_week",
        "endpoint_address",
    ]
    model = data[columns].dropna().reset_index(drop=True)
    continuous = [
        spec.outcome,
        "fee_yield_per_10bps",
        spec.risk_predictor,
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_tvl_usd",
        "log1p_observed_pool_age_weeks",
    ]
    for column in continuous:
        lower, upper = model[column].quantile([0.01, 0.99])
        if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
            model[column] = model[column].clip(lower=float(lower), upper=float(upper))
    model["stable_x_fee_yield"] = (
        model["stable_indicator"] * model["fee_yield_per_10bps"]
    )
    model[spec.stable_risk_predictor] = (
        model["stable_indicator"] * model[spec.risk_predictor]
    )
    if len(model) < min_observations:
        raise ValueError(f"{spec.model_id} has too few observations")
    if model["pool_id"].nunique() < min_pool_clusters:
        raise ValueError(f"{spec.model_id} has too few pool clusters")
    if model["origin_week"].nunique() < min_week_clusters:
        raise ValueError(f"{spec.model_id} has too few week clusters")
    fixed_effects = (model["endpoint_week_id"], model["pool_id"])
    outcome = absorb_fixed_effects(model[spec.outcome], *fixed_effects)
    design = absorb_fixed_effects(model[predictors], *fixed_effects)
    fit = ols_clustered(
        outcome,
        design,
        model["pool_id"],
        add_constant=False,
        absorbed_groups=fixed_effects,
        additional_clusters=(model["origin_week"],),
        min_observations=min_observations,
        min_clusters=min(min_pool_clusters, min_week_clusters),
    )
    common = {
        "model_id": spec.model_id,
        "tvl_threshold_usd": float(tvl_threshold),
        "outcome": spec.outcome,
        "observations": int(fit.n_observations),
        "pool_clusters": int(model["pool_id"].nunique()),
        "week_clusters": int(model["origin_week"].nunique()),
        "endpoint_clusters": int(model["endpoint_address"].nunique()),
        "r_squared_within": float(fit.r_squared),
        "adjusted_r_squared_within": float(fit.adjusted_r_squared),
        "fixed_effects": "endpoint_x_week+pool",
        "covariance": "pool_and_week_cluster_cr1",
        "predictor_timing": "weeks_t_minus_3_through_t",
        "outcome_timing": "week_t_plus_1",
        "lagged_flow_controls": "prior_four_week_add_and_remove_flow_scaled_by_mean_tvl",
        "winsorization": "continuous_model_variables_1st_99th_percentiles",
        "interpretation": "predictive_lp_supply_response_not_exogenous_return_shock",
        "flow_measure": "candidate_side_usd_from_add_only_or_remove_only_transactions",
        "estimand": "within_pool_response_slope_and_stable_minus_native_slope_difference",
        "fee_measure": "gross_pool_fee_yield_before_v3_protocol_fee_activation",
    }
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, t_statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "v3_lp_supply_return_coefficient",
                "predictor": predictor,
                "coefficient": float(coefficient),
                "standard_error": float(standard_error),
                "t_statistic": float(t_statistic),
                "p_value": float(p_value),
                **common,
            }
        )
    for baseline, interaction, label in (
        (
            "fee_yield_per_10bps",
            "stable_x_fee_yield",
            "stable_total_fee_yield_per_10bps",
        ),
        (
            spec.risk_predictor,
            spec.stable_risk_predictor,
            f"stable_total_{spec.risk_predictor}",
        ),
    ):
        weights = np.zeros(len(predictors), dtype=float)
        weights[predictors.index(baseline)] = 1.0
        weights[predictors.index(interaction)] = 1.0
        contrast = linear_contrast(fit, weights)
        rows.append(
            {
                "record_type": "v3_lp_supply_return_linear_combination",
                "predictor": label,
                "coefficient": contrast.estimate,
                "standard_error": contrast.standard_error,
                "t_statistic": contrast.t_statistic,
                "p_value": contrast.p_value,
                **common,
            }
        )
    return rows


def fit_v3_lp_supply_models(
    panel: pd.DataFrame,
    *,
    main_tvl_threshold: float = MAIN_TVL_THRESHOLD,
    sensitivity_thresholds: tuple[float, ...] = SENSITIVITY_THRESHOLDS,
    min_observations: int = 250,
    min_pool_clusters: int = 30,
    min_week_clusters: int = 20,
) -> pd.DataFrame:
    """Estimate the focused V3 supply models and TVL sensitivities."""

    rows: list[dict[str, object]] = []
    main = comparison_sample(panel, main_tvl_threshold)
    for spec in MAIN_MODEL_SPECS:
        rows.extend(
            _fit_spec(
                main,
                spec,
                tvl_threshold=main_tvl_threshold,
                min_observations=min_observations,
                min_pool_clusters=min_pool_clusters,
                min_week_clusters=min_week_clusters,
            )
        )
    primary = MAIN_MODEL_SPECS[0]
    for threshold in sensitivity_thresholds:
        rows.extend(
            _fit_spec(
                comparison_sample(panel, threshold),
                ModelSpec(
                    f"m1_next_week_net_add_remove_only_flow_threshold_{int(threshold)}",
                    primary.outcome,
                    primary.risk_predictor,
                    primary.stable_risk_predictor,
                ),
                tvl_threshold=threshold,
                min_observations=min_observations,
                min_pool_clusters=min_pool_clusters,
                min_week_clusters=min_week_clusters,
            )
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("V3 LP-supply model output is empty")
    return result


def support_records(
    panel: pd.DataFrame,
    *,
    thresholds: tuple[float, ...] = (
        SENSITIVITY_THRESHOLDS[0],
        MAIN_TVL_THRESHOLD,
        SENSITIVITY_THRESHOLDS[1],
    ),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for threshold in thresholds:
        data = comparison_sample(panel, threshold)
        rows.append(
            {
                "record_type": "v3_lp_supply_return_support",
                "venue": "uniswap_v3",
                "tvl_threshold_usd": float(threshold),
                "observations": int(len(data)),
                "endpoint_weeks": int(data["endpoint_week_id"].nunique()),
                "endpoints": int(data["endpoint_address"].nunique()),
                "pools": int(data["pool_id"].nunique()),
                "weeks": int(data["origin_week"].nunique()),
                "first_week": data["origin_week"].min().strftime("%Y-%m-%d"),
                "last_week": data["origin_week"].max().strftime("%Y-%m-%d"),
                "stable_pool_week_share": float(data["stable_indicator"].mean()),
                "median_tvl_usd": float(data["tvl_usd"].median()),
                "median_tvl_staleness_weeks": float(
                    data["tvl_staleness_weeks"].median()
                ),
                "median_trailing_fee_yield_bps": float(
                    data["trailing_fee_yield_bps"].median()
                ),
                "median_trailing_cp_divergence_proxy_bps": float(
                    data["trailing_cp_divergence_proxy_bps"].median()
                ),
                "median_next_net_flow_ratio": float(
                    data["next_net_flow_ratio"].median()
                ),
                "outcomes": (
                    "next_week_candidate_side_add_only_remove_only_flow_and_"
                    "same_class_transaction_counts"
                ),
                "predictors": (
                    "prior_four_week_gross_pool_fee_yield_and_pair_specific_"
                    "relative_price_risk"
                ),
                "trade_allocation_variables": "none",
                "fee_measurement": (
                    "gross_pool_fees_over_mean_last_reported_weekly_tvl_"
                    "before_protocol_fee_activation_not_position_level_return"
                ),
                "risk_measurement": "relative_price_volatility_and_full_range_cp_divergence_proxy",
                "tvl_screen": f"zero_lt_last_reported_tvl_le_{MAX_POOL_CAPITAL_USD:.0f}",
                "calendar_support": (
                    "balanced_pool_week_calendar_zero_filled_flows_and_fees_"
                    "with_pair_risk_from_complete_price_days"
                ),
                "maximum_tvl_staleness_weeks": MAX_TVL_STALENESS_WEEKS,
                "sample_end": PRE_PROTOCOL_FEE_END.strftime("%Y-%m-%d"),
                "sample_end_reason": "last_full_week_before_v3_protocol_fee_activation",
            }
        )
    return pd.DataFrame(rows)


def input_quality_record(fee_path: Path = FEE_INPUT) -> pd.DataFrame:
    """Report candidate-linked TVL rows admitted or excluded by the hard bound."""

    candidate_values = ",".join(f"'{address}'" for address in CANDIDATES)
    connection = duckdb.connect()
    try:
        row = connection.execute(
            f"""
            SELECT
                count(*) AS candidate_pool_days,
                count(*) FILTER (WHERE tvl_usd <= 0 OR tvl_usd IS NULL)
                    AS nonpositive_or_missing_tvl_days,
                count(*) FILTER (WHERE tvl_usd > {MAX_POOL_CAPITAL_USD})
                    AS above_capital_bound_days,
                count(*) FILTER (
                    WHERE tvl_usd > 0 AND tvl_usd <= {MAX_POOL_CAPITAL_USD}
                ) AS admitted_tvl_days,
                max(tvl_usd) AS maximum_reported_tvl_usd
            FROM read_parquet(?)
            WHERE (
                    (lower(token0_address) IN ({candidate_values}))::INTEGER
                  + (lower(token1_address) IN ({candidate_values}))::INTEGER
                  ) = 1
            """,
            [str(fee_path)],
        ).fetchone()
    finally:
        connection.close()
    return pd.DataFrame(
        [
            {
                "record_type": "v3_lp_supply_input_quality",
                "candidate_pool_days": int(row[0]),
                "nonpositive_or_missing_tvl_days": int(row[1]),
                "above_capital_bound_days": int(row[2]),
                "admitted_tvl_days": int(row[3]),
                "maximum_reported_tvl_usd": float(row[4]),
                "tvl_bound_usd": float(MAX_POOL_CAPITAL_USD),
                "tvl_measure": "last_reported_update_day_stock",
            }
        ]
    )


def run(
    *,
    flow_path: Path = FLOW_INPUT,
    fee_path: Path = FEE_INPUT,
    price_path: Path = PRICE_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    weekly_base = load_weekly_v3_lp_panel(
        flow_path=flow_path,
        fee_path=fee_path,
        price_path=price_path,
    )
    panel = prepare_weekly_panel(weekly_base)
    models = fit_v3_lp_supply_models(panel)
    support = pd.concat(
        [support_records(panel), input_quality_record(fee_path)],
        ignore_index=True,
        sort=False,
    )
    write_panel(
        panel,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes=(
            "Weekly Uniswap V3 pool panel with four-week lagged fee and "
            "relative-price-risk predictors and next-week provider flows."
        ),
    )
    write_exhibit(models, model_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(panel):,} V3 LP-supply pool-weeks, "
        f"{len(models):,} coefficient rows, and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", type=Path, default=FLOW_INPUT)
    parser.add_argument("--fees", type=Path, default=FEE_INPUT)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        flow_path=args.flow,
        fee_path=args.fees,
        price_path=args.prices,
        panel_output=args.panel_output,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
