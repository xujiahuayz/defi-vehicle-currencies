#!/usr/bin/env python3
"""Relate ex ante LP returns and relative-price risk to later V2 capital supply.

The unit is an endpoint--candidate Uniswap V2 pool week.  Outcomes are next-week
mint, burn, and net-mint capital from decoded Uniswap V2 LP events, scaled by
capital measured before those flows occur.  Predictors use
only the preceding four calendar weeks: fee opportunity, endpoint--candidate
relative-price risk, deposited capital, and pool age.

The comparison keeps endpoint-by-week and pool fixed effects and clusters by
pool and week.  It never uses realised route choice as an outcome or regressor.
The estimates describe how LP supply follows lagged rents and risk; neither
fees nor volatility is an exogenous shock.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, linear_contrast, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


FLOW_INPUT = DATA_DIR / "processed/v2_lp_flow_pool_daily.parquet"
CAPITAL_INPUT = DATA_DIR / "processed/pool_capital_daily.parquet"
PRICE_INPUT = DATA_DIR / "processed/token_price_daily.parquet"
PANEL_OUTPUT = OUTPUT_DIR / "exhibits/lp_supply_returns_weekly.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/lp_supply_returns_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/lp_supply_returns_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = {WETH: "WETH", DAI: "DAI", USDC: "USDC", USDT: "USDT"}

MAIN_CAPITAL_THRESHOLD = 50_000.0
SENSITIVITY_THRESHOLDS = (10_000.0, 100_000.0)
TRAILING_WEEKS = 4
MIN_TRAILING_RETURN_DAYS = 20

CODE_SOURCES = ["scripts/analyze/run_lp_supply_returns.py"]
INPUTS = [
    "data/processed/v2_lp_flow_pool_daily.parquet",
    "data/processed/pool_capital_daily.parquet",
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
        "m1_next_week_net_supply",
        "next_asinh_net_flow_ratio",
        "trailing_divergence_loss_bps",
        "stable_x_divergence_loss",
    ),
    ModelSpec(
        "m2_next_week_additions",
        "next_log1p_add_flow_ratio",
        "trailing_divergence_loss_bps",
        "stable_x_divergence_loss",
    ),
    ModelSpec(
        "m3_next_week_withdrawals",
        "next_log1p_remove_flow_ratio",
        "trailing_divergence_loss_bps",
        "stable_x_divergence_loss",
    ),
    ModelSpec(
        "m4_next_week_net_supply_volatility",
        "next_asinh_net_flow_ratio",
        "trailing_relative_volatility_per_10pp",
        "stable_x_relative_volatility",
    ),
    ModelSpec(
        "m5_next_week_net_supply_quantity",
        "next_asinh_net_liquidity_ratio",
        "trailing_divergence_loss_bps",
        "stable_x_divergence_loss",
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


def _volume_expression(columns: set[str]) -> str:
    for name in ("v2_volume_usd", "volume_usd", "reported_volume_usd"):
        if name in columns:
            return f"coalesce(f.{name}, 0.0)"
    raise ValueError(
        "V2 LP-flow panel lacks daily pool volume; rebuild it with eventless "
        "pool-days and v2_volume_usd before estimating fee opportunity"
    )


def _fee_expression(columns: set[str], volume_expression: str) -> str:
    for name in ("v2_fee_opportunity_usd", "fee_opportunity_usd"):
        if name in columns:
            return f"coalesce(f.{name}, 0.0)"
    # The Ethereum V2 protocol fee switch executed at 2025-12-27 20:33:11 UTC.
    # Daily volume cannot split that date, so it stays at the old rate and
    # 2025-12-28 is the first complete day assigned the 25 bp LP fee.
    return (
        "CASE WHEN CAST(f.origin_date AS DATE) < DATE '2025-12-28' "
        "THEN 0.003 ELSE 0.0025 END * "
        f"({volume_expression})"
    )


def load_daily_lp_panel(
    *,
    flow_path: Path = FLOW_INPUT,
    capital_path: Path = CAPITAL_INPUT,
    price_path: Path = PRICE_INPUT,
) -> pd.DataFrame:
    """Join decoded LP flows to the complete capital and price calendar."""

    for path in (flow_path, capital_path, price_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    columns = _parquet_columns(flow_path)
    price_columns = _parquet_columns(price_path)
    required = {
        "origin_date",
        "venue",
        "pool",
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_net_add_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
        "v2_net_add_liquidity",
    }
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"V2 LP-flow panel lacks columns: {missing}")
    volume_expression = _volume_expression(columns)
    fee_expression = _fee_expression(columns, volume_expression)
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
    capital = _sql_path(capital_path)
    flow = _sql_path(flow_path)
    prices = _sql_path(price_path)
    query = f"""
    WITH capital_base AS (
        SELECT
            strptime(CAST(c.day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
            c.venue,
            lower(c.pool) AS pool,
            lower(c.token0_address) AS token0_address,
            lower(c.token1_address) AS token1_address,
            c.capital_usd::DOUBLE AS capital_usd,
            sqrt(c.reserve0 * c.reserve1)::DOUBLE AS sqrt_k,
            CASE
                WHEN lower(c.token0_address) IN ({candidate_values})
                    THEN lower(c.token0_address)
                ELSE lower(c.token1_address)
            END AS candidate_address,
            CASE
                WHEN lower(c.token0_address) IN ({candidate_values})
                    THEN lower(c.token1_address)
                ELSE lower(c.token0_address)
            END AS endpoint_address
        FROM read_parquet('{capital}') c
        JOIN (
            SELECT DISTINCT lower(venue) AS venue, lower(pool) AS pool
            FROM read_parquet('{flow}')
        ) r
          ON r.venue = c.venue
         AND r.pool = lower(c.pool)
        WHERE c.capital_validation_status = 'exact_state_current'
          AND c.capital_usd > 0
          AND c.venue = 'uniswap_v2'
          AND (
                (lower(c.token0_address) IN ({candidate_values}))::INTEGER
              + (lower(c.token1_address) IN ({candidate_values}))::INTEGER
          ) = 1
    ),
    capital AS (
        SELECT
            *,
            CASE {candidate_case} END AS candidate_symbol,
            CASE WHEN candidate_address = '{WETH}'
                 THEN 'native' ELSE 'stable' END AS candidate_type
        FROM capital_base
    ),
    flow AS (
        SELECT
            CAST(origin_date AS DATE) AS origin_date,
            lower(venue) AS venue,
            lower(pool) AS pool,
            sum(v2_add_lp_flow_usd)::DOUBLE AS v2_add_lp_flow_usd,
            sum(v2_remove_lp_flow_usd)::DOUBLE AS v2_remove_lp_flow_usd,
            sum(v2_gross_lp_flow_usd)::DOUBLE AS v2_gross_lp_flow_usd,
            sum(v2_net_add_lp_flow_usd)::DOUBLE AS v2_net_add_lp_flow_usd,
            sum(v2_add_liquidity)::DOUBLE AS v2_add_liquidity,
            sum(v2_remove_liquidity)::DOUBLE AS v2_remove_liquidity,
            sum(v2_gross_liquidity)::DOUBLE AS v2_gross_liquidity,
            sum(v2_net_add_liquidity)::DOUBLE AS v2_net_add_liquidity,
            max({volume_expression})::DOUBLE AS v2_volume_usd,
            max({fee_expression})::DOUBLE AS v2_fee_opportunity_usd
        FROM read_parquet('{flow}') f
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
        FROM read_parquet('{prices}')
        WHERE {price_filter_sql}
    ),
    token_return AS (
        SELECT
            origin_date,
            token,
            log_price - lag_log_price AS log_return
        FROM price_level
        WHERE date_diff('day', lag_date, origin_date) = 1
    )
    SELECT
        c.origin_date,
        c.venue,
        c.pool,
        c.candidate_address,
        c.candidate_symbol,
        c.candidate_type,
        c.endpoint_address,
        c.capital_usd,
        c.sqrt_k,
        coalesce(f.v2_add_lp_flow_usd, 0.0)::DOUBLE AS v2_add_lp_flow_usd,
        coalesce(f.v2_remove_lp_flow_usd, 0.0)::DOUBLE AS v2_remove_lp_flow_usd,
        coalesce(f.v2_gross_lp_flow_usd, 0.0)::DOUBLE AS v2_gross_lp_flow_usd,
        coalesce(f.v2_net_add_lp_flow_usd, 0.0)::DOUBLE
            AS v2_net_add_lp_flow_usd,
        coalesce(f.v2_add_liquidity, 0.0)::DOUBLE AS v2_add_liquidity,
        coalesce(f.v2_remove_liquidity, 0.0)::DOUBLE AS v2_remove_liquidity,
        coalesce(f.v2_gross_liquidity, 0.0)::DOUBLE AS v2_gross_liquidity,
        coalesce(f.v2_net_add_liquidity, 0.0)::DOUBLE AS v2_net_add_liquidity,
        coalesce(f.v2_volume_usd, 0.0)::DOUBLE AS v2_volume_usd,
        coalesce(f.v2_fee_opportunity_usd, 0.0)::DOUBLE
            AS v2_fee_opportunity_usd,
        e.log_return::DOUBLE AS endpoint_log_return,
        v.log_return::DOUBLE AS candidate_log_return
    FROM capital c
    LEFT JOIN flow f
      ON f.origin_date = c.origin_date
     AND f.venue = c.venue
     AND f.pool = c.pool
    LEFT JOIN token_return e
      ON e.origin_date = c.origin_date
     AND e.token = c.endpoint_address
    LEFT JOIN token_return v
      ON v.origin_date = c.origin_date
     AND v.token = c.candidate_address
    ORDER BY c.venue, c.pool, c.origin_date
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
        raise ValueError("LP-supply daily panel is empty")
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    if frame.duplicated(["venue", "pool", "origin_date"]).any():
        raise ValueError("LP-supply daily panel has duplicate venue-pool-days")
    return frame


def prepare_weekly_panel(
    daily: pd.DataFrame,
    *,
    trailing_weeks: int = TRAILING_WEEKS,
    min_trailing_return_days: int = MIN_TRAILING_RETURN_DAYS,
) -> pd.DataFrame:
    """Build strictly lagged weekly predictors and next-week LP-flow outcomes."""

    required = {
        "origin_date",
        "venue",
        "pool",
        "candidate_address",
        "candidate_symbol",
        "candidate_type",
        "endpoint_address",
        "capital_usd",
        "sqrt_k",
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_net_add_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
        "v2_net_add_liquidity",
        "v2_fee_opportunity_usd",
        "endpoint_log_return",
        "candidate_log_return",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"LP-supply daily input lacks columns: {missing}")
    if trailing_weeks < 2:
        raise ValueError("LP-supply trailing window requires at least two weeks")
    frame = daily.copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    frame = frame.sort_values(["venue", "pool", "origin_date"]).reset_index(drop=True)
    if frame.duplicated(["venue", "pool", "origin_date"]).any():
        raise ValueError("LP-supply daily input has duplicate venue-pool-days")
    frame["origin_week"] = frame["origin_date"] - pd.to_timedelta(
        frame["origin_date"].dt.weekday, unit="D"
    )
    frame["relative_return"] = (
        pd.to_numeric(frame["endpoint_log_return"], errors="coerce")
        - pd.to_numeric(frame["candidate_log_return"], errors="coerce")
    )
    frame["relative_return_sq"] = frame["relative_return"].pow(2)
    frame["daily_divergence_loss_bps"] = (
        1.0 - 1.0 / np.cosh(frame["relative_return"] / 2.0)
    ) * 10_000.0
    group_keys = [
        "venue",
        "pool",
        "candidate_address",
        "candidate_symbol",
        "candidate_type",
        "endpoint_address",
        "origin_week",
    ]
    weekly = (
        frame.groupby(group_keys, as_index=False, sort=True)
        .agg(
            capital_usd=("capital_usd", "last"),
            sqrt_k=("sqrt_k", "last"),
            mean_capital_usd=("capital_usd", "mean"),
            add_flow_usd=("v2_add_lp_flow_usd", "sum"),
            remove_flow_usd=("v2_remove_lp_flow_usd", "sum"),
            gross_flow_usd=("v2_gross_lp_flow_usd", "sum"),
            net_add_flow_usd=("v2_net_add_lp_flow_usd", "sum"),
            add_liquidity=("v2_add_liquidity", "sum"),
            remove_liquidity=("v2_remove_liquidity", "sum"),
            gross_liquidity=("v2_gross_liquidity", "sum"),
            net_add_liquidity=("v2_net_add_liquidity", "sum"),
            fee_opportunity_usd=("v2_fee_opportunity_usd", "sum"),
            relative_return_sq_sum=("relative_return_sq", "sum"),
            divergence_loss_bps_sum=("daily_divergence_loss_bps", "sum"),
            return_days=("relative_return", "count"),
            capital_days=("capital_usd", "count"),
        )
        .sort_values(["venue", "pool", "origin_week"])
        .reset_index(drop=True)
    )
    rolling = weekly.groupby(["venue", "pool"], sort=False)
    for source, target in (
        ("fee_opportunity_usd", "trailing_fee_opportunity_usd"),
        ("add_flow_usd", "trailing_add_flow_usd"),
        ("remove_flow_usd", "trailing_remove_flow_usd"),
        ("mean_capital_usd", "trailing_mean_capital_usd"),
        ("relative_return_sq_sum", "trailing_relative_return_sq_sum"),
        ("divergence_loss_bps_sum", "trailing_divergence_loss_bps_sum"),
        ("return_days", "trailing_return_days"),
    ):
        weekly[target] = (
            rolling[source]
            .rolling(trailing_weeks, min_periods=trailing_weeks)
            .sum()
            .reset_index(level=[0, 1], drop=True)
        )
    weekly["trailing_mean_capital_usd"] /= float(trailing_weeks)
    weekly["trailing_start_week"] = rolling["origin_week"].shift(trailing_weeks - 1)
    expected_start = weekly["origin_week"] - pd.to_timedelta(
        7 * (trailing_weeks - 1), unit="D"
    )
    weekly["consecutive_trailing_weeks"] = weekly["trailing_start_week"].eq(
        expected_start
    )
    weekly["trailing_fee_yield_bps"] = 10_000.0 * (
        weekly["trailing_fee_opportunity_usd"]
        / weekly["trailing_mean_capital_usd"]
    )
    weekly["trailing_add_flow_ratio"] = (
        weekly["trailing_add_flow_usd"] / weekly["trailing_mean_capital_usd"]
    )
    weekly["trailing_remove_flow_ratio"] = (
        weekly["trailing_remove_flow_usd"] / weekly["trailing_mean_capital_usd"]
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
    weekly["trailing_divergence_loss_bps"] = (
        weekly["trailing_divergence_loss_bps_sum"]
        / weekly["trailing_return_days"]
    )
    first_week = weekly.groupby(["venue", "pool"])["origin_week"].transform("min")
    weekly["pool_age_weeks"] = (
        (weekly["origin_week"] - first_week).dt.days / 7.0
    ).clip(lower=0)
    for source, target in (
        ("origin_week", "next_origin_week"),
        ("add_flow_usd", "next_add_flow_usd"),
        ("remove_flow_usd", "next_remove_flow_usd"),
        ("gross_flow_usd", "next_gross_flow_usd"),
        ("net_add_flow_usd", "next_net_add_flow_usd"),
        ("add_liquidity", "next_add_liquidity"),
        ("remove_liquidity", "next_remove_liquidity"),
        ("gross_liquidity", "next_gross_liquidity"),
        ("net_add_liquidity", "next_net_add_liquidity"),
    ):
        weekly[target] = rolling[source].shift(-1)
    weekly["consecutive_next_week"] = weekly["next_origin_week"].eq(
        weekly["origin_week"] + pd.Timedelta(days=7)
    )
    denominator = weekly["capital_usd"].where(weekly["capital_usd"] > 0)
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
    quantity_denominator = weekly["sqrt_k"].where(weekly["sqrt_k"] > 0)
    weekly["next_net_liquidity_ratio"] = (
        weekly["next_net_add_liquidity"] / quantity_denominator
    )
    weekly["next_asinh_net_liquidity_ratio"] = np.arcsinh(
        weekly["next_net_liquidity_ratio"]
    )
    weekly["stable_indicator"] = weekly["candidate_type"].eq("stable").astype(float)
    weekly["fee_yield_per_10bps"] = weekly["trailing_fee_yield_bps"] / 10.0
    weekly["trailing_relative_volatility_per_10pp"] = (
        weekly["trailing_relative_volatility"] / 0.10
    )
    weekly["stable_x_fee_yield"] = (
        weekly["stable_indicator"] * weekly["fee_yield_per_10bps"]
    )
    weekly["stable_x_divergence_loss"] = (
        weekly["stable_indicator"] * weekly["trailing_divergence_loss_bps"]
    )
    weekly["stable_x_relative_volatility"] = (
        weekly["stable_indicator"]
        * weekly["trailing_relative_volatility_per_10pp"]
    )
    weekly["log_capital_usd"] = np.log(weekly["capital_usd"])
    weekly["log1p_pool_age_weeks"] = np.log1p(weekly["pool_age_weeks"])
    weekly["pool_id"] = weekly["venue"].astype(str) + "|" + weekly["pool"].astype(str)
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
        raise ValueError("LP-supply weekly panel has no valid four-week histories")
    return weekly


def comparison_sample(panel: pd.DataFrame, capital_threshold: float) -> pd.DataFrame:
    """Keep endpoint-weeks with material native and stable candidate pools."""

    if capital_threshold <= 0:
        raise ValueError("LP-supply capital threshold must be positive")
    data = panel[panel["capital_usd"].ge(capital_threshold)].copy()
    cells = data.groupby("endpoint_week_id")["candidate_type"].agg(set)
    eligible = cells[cells.map(lambda values: {"native", "stable"}.issubset(values))].index
    data = data[data["endpoint_week_id"].isin(eligible)].reset_index(drop=True)
    if data.empty:
        raise ValueError(
            f"LP-supply comparison is empty at ${capital_threshold:,.0f}"
        )
    return data


def _fit_spec(
    data: pd.DataFrame,
    spec: ModelSpec,
    *,
    capital_threshold: float,
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
        "log_capital_usd",
        "log1p_pool_age_weeks",
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
    for column in (
        spec.outcome,
        "fee_yield_per_10bps",
        spec.risk_predictor,
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_capital_usd",
        "log1p_pool_age_weeks",
    ):
        lower, upper = model[column].quantile([0.01, 0.99])
        if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
            model[column] = model[column].clip(lower=float(lower), upper=float(upper))
    # Recompute interactions after trimming their continuous components so the
    # coefficient remains the stable-pool slope difference it is labelled as.
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
                "record_type": "lp_supply_return_coefficient",
                "model_id": spec.model_id,
                "capital_threshold_usd": float(capital_threshold),
                "outcome": spec.outcome,
                "predictor": predictor,
                "coefficient": float(coefficient),
                "standard_error": float(standard_error),
                "t_statistic": float(t_statistic),
                "p_value": float(p_value),
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
                "lagged_flow_controls": "prior_four_week_add_and_remove_flow_scaled_by_mean_capital",
                "winsorization": "continuous_model_variables_1st_99th_percentiles",
                "interpretation": "predictive_lp_supply_response_not_exogenous_return_shock",
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
                "record_type": "lp_supply_return_linear_combination",
                "model_id": spec.model_id,
                "capital_threshold_usd": float(capital_threshold),
                "outcome": spec.outcome,
                "predictor": label,
                "coefficient": contrast.estimate,
                "standard_error": contrast.standard_error,
                "t_statistic": contrast.t_statistic,
                "p_value": contrast.p_value,
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
                "lagged_flow_controls": "prior_four_week_add_and_remove_flow_scaled_by_mean_capital",
                "winsorization": "continuous_model_variables_1st_99th_percentiles",
                "interpretation": "stable_pool_total_slope_baseline_plus_interaction",
            }
        )
    return rows


def fit_lp_supply_models(
    panel: pd.DataFrame,
    *,
    main_capital_threshold: float = MAIN_CAPITAL_THRESHOLD,
    sensitivity_thresholds: tuple[float, ...] = SENSITIVITY_THRESHOLDS,
    min_observations: int = 250,
    min_pool_clusters: int = 30,
    min_week_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate the registered main models and two capital sensitivities."""

    rows: list[dict[str, object]] = []
    main = comparison_sample(panel, main_capital_threshold)
    for spec in MAIN_MODEL_SPECS:
        rows.extend(
            _fit_spec(
                main,
                spec,
                capital_threshold=main_capital_threshold,
                min_observations=min_observations,
                min_pool_clusters=min_pool_clusters,
                min_week_clusters=min_week_clusters,
            )
        )
    primary = MAIN_MODEL_SPECS[0]
    for threshold in sensitivity_thresholds:
        sensitivity = comparison_sample(panel, threshold)
        spec = ModelSpec(
            f"m1_next_week_net_supply_threshold_{int(threshold)}",
            primary.outcome,
            primary.risk_predictor,
            primary.stable_risk_predictor,
        )
        rows.extend(
            _fit_spec(
                sensitivity,
                spec,
                capital_threshold=threshold,
                min_observations=min_observations,
                min_pool_clusters=min_pool_clusters,
                min_week_clusters=min_week_clusters,
            )
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("LP-supply model output is empty")
    return result


def support_records(
    panel: pd.DataFrame,
    *,
    thresholds: tuple[float, ...] = (
        SENSITIVITY_THRESHOLDS[0],
        MAIN_CAPITAL_THRESHOLD,
        SENSITIVITY_THRESHOLDS[1],
    ),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for threshold in thresholds:
        data = comparison_sample(panel, threshold)
        rows.append(
            {
                "record_type": "lp_supply_return_support",
                "venue": "uniswap_v2",
                "capital_threshold_usd": float(threshold),
                "observations": int(len(data)),
                "endpoint_weeks": int(data["endpoint_week_id"].nunique()),
                "endpoints": int(data["endpoint_address"].nunique()),
                "pools": int(data["pool_id"].nunique()),
                "weeks": int(data["origin_week"].nunique()),
                "first_week": data["origin_week"].min().strftime("%Y-%m-%d"),
                "last_week": data["origin_week"].max().strftime("%Y-%m-%d"),
                "stable_pool_week_share": float(data["stable_indicator"].mean()),
                "median_capital_usd": float(data["capital_usd"].median()),
                "median_trailing_fee_yield_bps": float(
                    data["trailing_fee_yield_bps"].median()
                ),
                "median_trailing_divergence_loss_bps": float(
                    data["trailing_divergence_loss_bps"].median()
                ),
                "median_trailing_add_flow_ratio": float(
                    data["trailing_add_flow_ratio"].median()
                ),
                "median_trailing_remove_flow_ratio": float(
                    data["trailing_remove_flow_ratio"].median()
                ),
                "median_next_net_flow_ratio": float(
                    data["next_net_flow_ratio"].median()
                ),
                "median_next_net_liquidity_ratio": float(
                    data["next_net_liquidity_ratio"].median()
                ),
                "outcomes": "next_week_add_remove_and_net_lp_capital_flow",
                "predictors": "prior_four_week_fee_opportunity_and_relative_price_risk",
                "route_variables": "none",
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    flow_path: Path = FLOW_INPUT,
    capital_path: Path = CAPITAL_INPUT,
    price_path: Path = PRICE_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    daily = load_daily_lp_panel(
        flow_path=flow_path,
        capital_path=capital_path,
        price_path=price_path,
    )
    panel = prepare_weekly_panel(daily)
    models = fit_lp_supply_models(panel)
    support = support_records(panel)
    write_panel(
        panel,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes=(
            "Weekly V2 LP-supply panel with four-week lagged fee and risk "
            "predictors and next-week decoded provider-flow outcomes."
        ),
    )
    write_exhibit(models, model_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(panel):,} LP-supply pool-weeks, "
        f"{len(models):,} coefficient rows, and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", type=Path, default=FLOW_INPUT)
    parser.add_argument("--capital", type=Path, default=CAPITAL_INPUT)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        flow_path=args.flow,
        capital_path=args.capital,
        price_path=args.prices,
        panel_output=args.panel_output,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
