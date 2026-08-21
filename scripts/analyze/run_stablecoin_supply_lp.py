#!/usr/bin/env python3
"""Relate lagged stablecoin-token supply to later liquidity provision.

The unit for capital growth is a stablecoin-token--endpoint pair month.  The unit
for first material formation is an at-risk stablecoin-token--endpoint pair month.
Worldwide circulating-supply growth is the primary predictor because Ethereum
circulation mechanically includes tokens deposited in Ethereum pools; the
Ethereum series is reported as a local-market sensitivity.

Capital-growth models absorb stablecoin-token--endpoint-pair and endpoint-by-month
fixed effects.  Formation models absorb stablecoin-token and endpoint-by-month
fixed effects.  Supply growth is measured through month t and outcomes occur
in t+1.  The estimates are descriptive correlations: issuance and liquidity
can both respond to anticipated stablecoin demand.

Writes
  data/processed/stablecoin_supply_lp_monthly.parquet
  output/exhibits/stablecoin_supply_lp_models.jsonl
  output/exhibits/stablecoin_supply_lp_support.jsonl

Run
  ./scripts/run scripts/analyze/run_stablecoin_supply_lp.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.asset_types import NON_USD_STABLE, STABLE
from ddvc.capital_contracts import MAX_POOL_CAPITAL_USD
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


SUPPLY_INPUT = DATA_DIR / "processed" / "stablecoin_supply_daily.parquet"
V2_CAPITAL_INPUT = DATA_DIR / "processed" / "pool_capital_daily.parquet"
V3_CAPITAL_INPUT = DATA_DIR / "processed" / "v3_pool_day_fees.parquet"
PANEL_OUTPUT = DATA_DIR / "processed" / "stablecoin_supply_lp_monthly.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits" / "stablecoin_supply_lp_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits" / "stablecoin_supply_lp_support.jsonl"

SAMPLE_START = pd.Timestamp("2020-01-01")
SAMPLE_END = pd.Timestamp("2026-06-01")
MAX_STALENESS_DAYS = 45
MATERIAL_CAPITAL_USD = 50_000.0
MIN_STABLECOIN_SUPPLY = 1_000_000.0
CAPITAL_SCALE_USD = 1_000_000.0

USD_STABLES = {
    address.casefold(): symbol
    for address, symbol in STABLE.items()
    if symbol not in NON_USD_STABLE
}
CODE_SOURCES = ["scripts/analyze/run_stablecoin_supply_lp.py"]
INPUTS = [
    "data/processed/stablecoin_supply_daily.parquet",
    "data/processed/pool_capital_daily.parquet",
    "data/processed/v3_pool_day_fees.parquet",
]


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _stable_sql_values() -> str:
    return ",".join(f"'{address}'" for address in USD_STABLES)


def load_observed_pool_months(
    *,
    v2_path: Path = V2_CAPITAL_INPUT,
    v3_path: Path = V3_CAPITAL_INPUT,
) -> pd.DataFrame:
    """Load the latest observed stable-linked capital state in each pool month."""

    for path in (v2_path, v3_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    stable_values = _stable_sql_values()
    query = f"""
    WITH v2 AS (
        SELECT
            date_trunc('month', strptime(CAST(day AS VARCHAR), '%Y%m%d'))::DATE
                AS origin_month,
            lower(venue) AS venue,
            lower(pool) AS pool,
            arg_max(lower(token0_address), day) AS token0_address,
            arg_max(lower(token1_address), day) AS token1_address,
            arg_max(capital_usd::DOUBLE, day) AS capital_usd,
            max(strptime(CAST(day AS VARCHAR), '%Y%m%d'))::DATE AS observed_date
        FROM read_parquet('{_sql_path(v2_path)}')
        WHERE capital_valid
          AND capital_usd BETWEEN 0 AND {float(MAX_POOL_CAPITAL_USD)}
          AND (
                lower(token0_address) IN ({stable_values})
             OR lower(token1_address) IN ({stable_values})
          )
        GROUP BY 1,2,3
    ),
    v3 AS (
        SELECT
            date_trunc('month', CAST(origin_date AS DATE))::DATE AS origin_month,
            'uniswap_v3' AS venue,
            lower(pool) AS pool,
            arg_max(lower(token0_address), CAST(origin_date AS DATE))
                AS token0_address,
            arg_max(lower(token1_address), CAST(origin_date AS DATE))
                AS token1_address,
            arg_max(tvl_usd::DOUBLE, CAST(origin_date AS DATE)) AS capital_usd,
            max(CAST(origin_date AS DATE))::DATE AS observed_date
        FROM read_parquet('{_sql_path(v3_path)}')
        WHERE tvl_usd BETWEEN 0 AND {float(MAX_POOL_CAPITAL_USD)}
          AND (
                lower(token0_address) IN ({stable_values})
             OR lower(token1_address) IN ({stable_values})
          )
        GROUP BY 1,2,3
    )
    SELECT * FROM v2
    UNION ALL
    SELECT * FROM v3
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
        raise ValueError("stable-linked pool capital months are empty")
    frame["origin_month"] = pd.to_datetime(frame["origin_month"]).dt.normalize()
    frame["observed_date"] = pd.to_datetime(frame["observed_date"]).dt.normalize()
    for column in ("venue", "pool", "token0_address", "token1_address"):
        frame[column] = frame[column].astype(str).str.casefold()
    frame["capital_usd"] = pd.to_numeric(frame["capital_usd"], errors="coerce")
    valid = (
        frame["origin_month"].between(SAMPLE_START, SAMPLE_END)
        & frame["capital_usd"].between(0, MAX_POOL_CAPITAL_USD)
        & frame["token0_address"].ne(frame["token1_address"])
    )
    frame = frame.loc[valid].reset_index(drop=True)
    if frame.duplicated(["venue", "pool", "origin_month"]).any():
        raise ValueError("observed capital has duplicate venue-pool-months")
    return frame


def carry_pool_capital_monthly(
    observed: pd.DataFrame,
    *,
    sample_end: pd.Timestamp = SAMPLE_END,
    max_staleness_days: int = MAX_STALENESS_DAYS,
) -> pd.DataFrame:
    """Carry a pool's latest observed stock for at most 45 days."""

    if max_staleness_days < 1:
        raise ValueError("capital staleness bound must be positive")
    required = {
        "origin_month",
        "venue",
        "pool",
        "token0_address",
        "token1_address",
        "capital_usd",
        "observed_date",
    }
    missing = sorted(required - set(observed.columns))
    if missing:
        raise ValueError(f"pool-month capital lacks columns: {missing}")
    rows: list[pd.DataFrame] = []
    for (venue, pool), group in observed.groupby(["venue", "pool"], sort=False):
        group = group.sort_values("origin_month").set_index("origin_month")
        if group[["token0_address", "token1_address"]].nunique().max() > 1:
            raise ValueError(f"pool identity changes across months: {venue}/{pool}")
        calendar = pd.date_range(
            group.index.min(), pd.Timestamp(sample_end), freq="MS"
        )
        expanded = group.reindex(calendar)
        expanded["venue"] = venue
        expanded["pool"] = pool
        for column in (
            "token0_address",
            "token1_address",
            "capital_usd",
            "observed_date",
        ):
            expanded[column] = expanded[column].ffill()
        expanded.index.name = "origin_month"
        expanded = expanded.reset_index()
        expanded["staleness_days"] = (
            expanded["origin_month"]
            + pd.offsets.MonthEnd(0)
            - pd.to_datetime(expanded["observed_date"])
        ).dt.days
        expanded = expanded[
            expanded["staleness_days"].between(0, max_staleness_days)
        ]
        rows.append(expanded)
    panel = pd.concat(rows, ignore_index=True)
    if panel.duplicated(["venue", "pool", "origin_month"]).any():
        raise ValueError("carried capital has duplicate venue-pool-months")
    return panel.sort_values(["venue", "pool", "origin_month"]).reset_index(drop=True)


def assign_stable_roles(pool_months: pd.DataFrame) -> pd.DataFrame:
    """Give each stable token in a pool its own stablecoin-token--endpoint observation."""

    frames: list[pd.DataFrame] = []
    for stablecoin_side, endpoint_side in (
        ("token0_address", "token1_address"),
        ("token1_address", "token0_address"),
    ):
        side = pool_months[pool_months[stablecoin_side].isin(USD_STABLES)].copy()
        side["stablecoin_address"] = side[stablecoin_side]
        side["stablecoin_symbol"] = side[stablecoin_side].map(USD_STABLES)
        side["endpoint_address"] = side[endpoint_side]
        side["scope"] = np.where(
            side["endpoint_address"].isin(USD_STABLES), "stable_core", "stable_spoke"
        )
        frames.append(side)
    roles = pd.concat(frames, ignore_index=True)
    roles = roles[roles["stablecoin_address"].ne(roles["endpoint_address"])].copy()
    if roles.empty:
        raise ValueError("stable-linked capital has no stablecoin roles")
    key = ["venue", "pool", "origin_month", "stablecoin_address"]
    if roles.duplicated(key).any():
        raise ValueError("stable-role capital has duplicate pool-stablecoin-months")
    return roles.reset_index(drop=True)


def aggregate_relationship_capital(roles: pd.DataFrame) -> pd.DataFrame:
    relationships = (
        roles.groupby(
            [
                "origin_month",
                "stablecoin_address",
                "stablecoin_symbol",
                "endpoint_address",
                "scope",
            ],
            as_index=False,
        )
        .agg(
            capital_usd=("capital_usd", "sum"),
            pools=("pool", "nunique"),
            venues=("venue", "nunique"),
            max_staleness_days=("staleness_days", "max"),
        )
        .sort_values(["stablecoin_address", "endpoint_address", "origin_month"])
        .reset_index(drop=True)
    )
    relationships["pair_id"] = (
        relationships["stablecoin_address"]
        + "|"
        + relationships["endpoint_address"]
    )
    return relationships


def monthly_supply_panel(
    daily: pd.DataFrame,
    *,
    min_supply: float = MIN_STABLECOIN_SUPPLY,
) -> pd.DataFrame:
    """Take month-end source values and form backward-looking growth."""

    required = {
        "date",
        "token_address",
        "token_symbol",
        "global_circulating",
        "ethereum_circulating",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"stablecoin-supply daily panel lacks columns: {missing}")
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["origin_month"] = frame["date"].dt.to_period("M").dt.to_timestamp()
    frame = (
        frame.sort_values("date")
        .groupby(["token_address", "token_symbol", "origin_month"], as_index=False)
        .tail(1)
        .sort_values(["token_address", "origin_month"])
        .reset_index(drop=True)
    )
    grouped = frame.groupby("token_address", sort=False)
    frame["previous_month"] = grouped["origin_month"].shift(1)
    for measure in ("global_circulating", "ethereum_circulating"):
        frame[f"previous_{measure}"] = grouped[measure].shift(1)
        frame[f"log_{measure}"] = np.log(frame[measure].where(frame[measure] > 0))
        frame[f"{measure}_growth"] = (
            frame[f"log_{measure}"]
            - grouped[f"log_{measure}"].shift(1)
        )
    frame["consecutive_supply_month"] = frame["previous_month"].eq(
        frame["origin_month"] - pd.offsets.MonthBegin(1)
    )
    frame["stablecoin_month_id"] = (
        frame["token_address"].astype(str)
        + "|"
        + frame["origin_month"].dt.strftime("%Y%m")
    )
    valid = (
        frame["origin_month"].between(SAMPLE_START, SAMPLE_END)
        & frame["consecutive_supply_month"]
        & frame["global_circulating"].ge(min_supply)
        & frame["previous_global_circulating"].ge(min_supply)
    )
    return frame.loc[valid].reset_index(drop=True)


def prepare_capital_growth_panel(
    relationships: pd.DataFrame,
    supply: pd.DataFrame,
    *,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Attach t issuance to t-to-t+1 capital changes for continuing links."""

    panel = relationships.sort_values(["pair_id", "origin_month"]).copy()
    grouped = panel.groupby("pair_id", sort=False)
    panel["next_month"] = grouped["origin_month"].shift(-1)
    panel["next_capital_usd"] = grouped["capital_usd"].shift(-1)
    panel["consecutive_next_month"] = panel["next_month"].eq(
        panel["origin_month"] + pd.offsets.MonthBegin(1)
    )
    supply_columns = [
        "origin_month",
        "token_address",
        "global_circulating",
        "ethereum_circulating",
        "log_global_circulating",
        "log_ethereum_circulating",
        "global_circulating_growth",
        "ethereum_circulating_growth",
        "stablecoin_month_id",
    ]
    panel = panel.merge(
        supply[supply_columns],
        left_on=["origin_month", "stablecoin_address"],
        right_on=["origin_month", "token_address"],
        how="inner",
        validate="many_to_one",
    )
    panel = panel[
        panel["consecutive_next_month"]
        & panel["capital_usd"].ge(material_capital_usd)
        & panel["next_capital_usd"].notna()
    ].copy()
    panel["next_log_capital_change"] = np.log1p(
        panel["next_capital_usd"] / CAPITAL_SCALE_USD
    ) - np.log1p(panel["capital_usd"] / CAPITAL_SCALE_USD)
    panel["current_log_capital"] = np.log1p(
        panel["capital_usd"] / CAPITAL_SCALE_USD
    )
    panel["core_indicator"] = panel["scope"].eq("stable_core").astype(float)
    panel["endpoint_month_id"] = (
        panel["endpoint_address"]
        + "|"
        + panel["origin_month"].dt.strftime("%Y%m")
    )
    return panel.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def prepare_formation_panel(
    relationships: pd.DataFrame,
    supply: pd.DataFrame,
    *,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Build the monthly risk set for first material stablecoin-token--endpoint links."""

    material = relationships[relationships["capital_usd"].ge(material_capital_usd)]
    first_material = (
        material.groupby(["stablecoin_address", "endpoint_address"], as_index=False)
        ["origin_month"]
        .min()
        .rename(columns={"origin_month": "first_material_month"})
    )
    material_endpoints = set(material["endpoint_address"])
    eligible_endpoints = (
        relationships[relationships["endpoint_address"].isin(material_endpoints)]
        .groupby("endpoint_address", as_index=False)["origin_month"]
        .min()
        .rename(columns={"origin_month": "endpoint_first_observed_month"})
    )
    if eligible_endpoints.empty:
        raise ValueError("no material stable-linked endpoints for formation risk set")
    supply_grid = supply[
        [
            "origin_month",
            "token_address",
            "token_symbol",
            "global_circulating",
            "ethereum_circulating",
            "log_global_circulating",
            "log_ethereum_circulating",
            "global_circulating_growth",
            "ethereum_circulating_growth",
            "stablecoin_month_id",
        ]
    ].rename(
        columns={"token_address": "stablecoin_address", "token_symbol": "stablecoin_symbol"}
    )
    grid = supply_grid.merge(eligible_endpoints, how="cross")
    grid = grid[
        grid["stablecoin_address"].ne(grid["endpoint_address"])
        & grid["origin_month"].ge(grid["endpoint_first_observed_month"])
        & grid["origin_month"].lt(SAMPLE_END)
    ].copy()
    current = relationships[
        ["origin_month", "stablecoin_address", "endpoint_address", "capital_usd"]
    ]
    grid = grid.merge(
        current,
        on=["origin_month", "stablecoin_address", "endpoint_address"],
        how="left",
        validate="one_to_one",
    )
    grid["capital_usd"] = grid["capital_usd"].fillna(0.0)
    grid = grid.merge(
        first_material,
        on=["stablecoin_address", "endpoint_address"],
        how="left",
        validate="many_to_one",
    )
    at_risk = grid["first_material_month"].isna() | grid["origin_month"].lt(
        grid["first_material_month"]
    )
    grid = grid[at_risk].copy()
    grid["forms_next_month"] = grid["first_material_month"].eq(
        grid["origin_month"] + pd.offsets.MonthBegin(1)
    ).astype(float)
    grid["scope"] = np.where(
        grid["endpoint_address"].isin(USD_STABLES), "stable_core", "stable_spoke"
    )
    grid["core_indicator"] = grid["scope"].eq("stable_core").astype(float)
    grid["current_log_capital"] = np.log1p(
        grid["capital_usd"] / CAPITAL_SCALE_USD
    )
    grid["pair_id"] = grid["stablecoin_address"] + "|" + grid["endpoint_address"]
    grid["endpoint_month_id"] = (
        grid["endpoint_address"]
        + "|"
        + grid["origin_month"].dt.strftime("%Y%m")
    )
    return grid.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def prepare_stablecoin_scope_panel(
    relationships: pd.DataFrame,
    supply: pd.DataFrame,
    *,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Aggregate capital stocks and new material links by stablecoin and scope."""

    capital = (
        relationships.groupby(
            ["origin_month", "stablecoin_address", "stablecoin_symbol", "scope"],
            as_index=False,
        )
        .agg(
            capital_usd=("capital_usd", "sum"),
            material_links=(
                "capital_usd",
                lambda values: int((values >= material_capital_usd).sum()),
            ),
        )
    )
    first_material = (
        relationships[relationships["capital_usd"].ge(material_capital_usd)]
        .groupby(
            ["stablecoin_address", "stablecoin_symbol", "endpoint_address", "scope"],
            as_index=False,
        )["origin_month"]
        .min()
    )
    formations = (
        first_material.groupby(
            ["origin_month", "stablecoin_address", "stablecoin_symbol", "scope"],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "new_material_links"})
    )
    supply_columns = [
        "origin_month",
        "token_address",
        "token_symbol",
        "global_circulating",
        "ethereum_circulating",
        "log_global_circulating",
        "log_ethereum_circulating",
        "global_circulating_growth",
        "ethereum_circulating_growth",
        "stablecoin_month_id",
    ]
    grid = supply[supply_columns].rename(
        columns={"token_address": "stablecoin_address", "token_symbol": "stablecoin_symbol"}
    )
    grid = grid.merge(
        pd.DataFrame({"scope": ["stable_core", "stable_spoke"]}), how="cross"
    )
    grid = grid.merge(
        capital,
        on=["origin_month", "stablecoin_address", "stablecoin_symbol", "scope"],
        how="left",
        validate="one_to_one",
    ).merge(
        formations,
        on=["origin_month", "stablecoin_address", "stablecoin_symbol", "scope"],
        how="left",
        validate="one_to_one",
    )
    grid[["capital_usd", "material_links", "new_material_links"]] = grid[
        ["capital_usd", "material_links", "new_material_links"]
    ].fillna(0.0)
    grid = grid.sort_values(["stablecoin_address", "scope", "origin_month"])
    grouped = grid.groupby(["stablecoin_address", "scope"], sort=False)
    grid["next_month"] = grouped["origin_month"].shift(-1)
    grid["next_capital_usd"] = grouped["capital_usd"].shift(-1)
    grid["next_new_material_links"] = grouped["new_material_links"].shift(-1)
    grid = grid[
        grid["next_month"].eq(grid["origin_month"] + pd.offsets.MonthBegin(1))
    ].copy()
    grid["next_log_capital_change"] = np.log1p(
        grid["next_capital_usd"] / CAPITAL_SCALE_USD
    ) - np.log1p(grid["capital_usd"] / CAPITAL_SCALE_USD)
    grid["next_log1p_new_material_links"] = np.log1p(
        grid["next_new_material_links"]
    )
    grid["current_log_capital"] = np.log1p(
        grid["capital_usd"] / CAPITAL_SCALE_USD
    )
    grid["core_indicator"] = grid["scope"].eq("stable_core").astype(float)
    grid["stablecoin_scope_id"] = grid["stablecoin_address"] + "|" + grid["scope"]
    grid["month_id"] = grid["origin_month"].dt.strftime("%Y%m")
    return grid.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def _winsorize(series: pd.Series) -> pd.Series:
    finite = series[np.isfinite(series)]
    if finite.nunique() < 3:
        return series
    lower, upper = finite.quantile([0.01, 0.99])
    return series.clip(lower=float(lower), upper=float(upper))


def _fit_one_model(
    panel: pd.DataFrame,
    *,
    outcome: str,
    model_family: str,
    scope: str,
    supply_measure: str,
) -> list[dict[str, object]]:
    data = panel if scope == "all" else panel[panel["scope"].eq(scope)]
    growth = f"{supply_measure}_circulating_growth"
    level = f"log_{supply_measure}_circulating"
    columns = [
        outcome,
        growth,
        level,
        "current_log_capital",
        "core_indicator",
        "stablecoin_address",
        "endpoint_address",
        "pair_id",
        "endpoint_month_id",
        "stablecoin_month_id",
        "origin_month",
    ]
    data = data[columns].dropna().reset_index(drop=True)
    data[growth] = _winsorize(data[growth])
    if model_family == "capital_growth":
        data[outcome] = _winsorize(data[outcome])
    data["supply_growth_per_10pct"] = data[growth] / 0.10
    data["growth_x_core"] = (
        data["supply_growth_per_10pct"] * data["core_indicator"]
    )
    predictors = [
        "supply_growth_per_10pct",
        level,
        "current_log_capital",
    ]
    if scope == "all":
        predictors.insert(1, "growth_x_core")

    # Endpoint-by-month effects need more than one stablecoin in the cell.  Cells
    # without within-endpoint stablecoin variation add no identifying information.
    cell_support = data.groupby("endpoint_month_id")["stablecoin_address"].nunique()
    data = data[data["endpoint_month_id"].isin(cell_support[cell_support >= 2].index)]
    if model_family == "capital_growth":
        pair_support = data.groupby("pair_id")["origin_month"].nunique()
        data = data[data["pair_id"].isin(pair_support[pair_support >= 2].index)]
        fixed_effects = (data["pair_id"], data["endpoint_month_id"])
        primary_cluster = data["pair_id"]
        additional_cluster = data["stablecoin_month_id"]
        fixed_effect_label = "stablecoin_endpoint_pair+endpoint_x_month"
        covariance_label = "stablecoin_endpoint_pair_and_stablecoin_month_cluster_cr1"
    else:
        fixed_effects = (data["stablecoin_address"], data["endpoint_month_id"])
        primary_cluster = data["endpoint_address"]
        additional_cluster = data["stablecoin_month_id"]
        fixed_effect_label = "stablecoin+endpoint_x_month"
        covariance_label = "endpoint_and_stablecoin_month_cluster_cr1"
    if len(data) < 100:
        return []
    outcome_residual = absorb_fixed_effects(data[outcome], *fixed_effects)
    design_residual = absorb_fixed_effects(data[predictors], *fixed_effects)
    fit = ols_clustered(
        outcome_residual,
        design_residual,
        primary_cluster,
        add_constant=False,
        absorbed_groups=fixed_effects,
        additional_clusters=(additional_cluster,),
        min_observations=100,
        min_clusters=10,
    )
    model_id = f"{model_family}_{scope}_{supply_measure}_supply"
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "stablecoin_supply_lp_coefficient",
                "model_id": model_id,
                "model_family": model_family,
                "scope": scope,
                "supply_measure": supply_measure,
                "outcome": outcome,
                "predictor": predictor,
                "coefficient": float(coefficient),
                "coefficient_pp": (
                    float(coefficient) * 100.0
                    if model_family == "formation"
                    else None
                ),
                "standard_error": float(standard_error),
                "standard_error_pp": (
                    float(standard_error) * 100.0
                    if model_family == "formation"
                    else None
                ),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "stablecoins": int(data["stablecoin_address"].nunique()),
                "endpoints": int(data["endpoint_address"].nunique()),
                "stablecoin_endpoint_pairs": int(data["pair_id"].nunique()),
                "months": int(data["origin_month"].nunique()),
                "primary_clusters": int(pd.Series(primary_cluster).nunique()),
                "stablecoin_month_clusters": int(data["stablecoin_month_id"].nunique()),
                "fixed_effects": fixed_effect_label,
                "covariance": covariance_label,
                "predictor_timing": "stablecoin_supply_growth_from_t_minus_1_to_t",
                "outcome_timing": "lp_capital_or_first_material_link_in_t_plus_1",
                "winsorization": "supply_growth_and_continuous_capital_growth_1st_99th_percentiles",
                "interpretation": "predictive_association_not_exogenous_issuance_shift",
            }
        )
    return rows


def _fit_stablecoin_scope_model(
    panel: pd.DataFrame,
    *,
    outcome: str,
    model_family: str,
    supply_measure: str,
) -> list[dict[str, object]]:
    growth = f"{supply_measure}_circulating_growth"
    level = f"log_{supply_measure}_circulating"
    columns = [
        outcome,
        growth,
        level,
        "current_log_capital",
        "core_indicator",
        "stablecoin_address",
        "stablecoin_scope_id",
        "month_id",
        "origin_month",
    ]
    data = panel[columns].dropna().reset_index(drop=True)
    if model_family == "stablecoin_scope_capital_growth":
        data = data[data["current_log_capital"].gt(np.log1p(MATERIAL_CAPITAL_USD / CAPITAL_SCALE_USD))]
        data[outcome] = _winsorize(data[outcome])
    data[growth] = _winsorize(data[growth])
    data["supply_growth_per_10pct"] = data[growth] / 0.10
    data["growth_x_core"] = (
        data["supply_growth_per_10pct"] * data["core_indicator"]
    )
    predictors = [
        "supply_growth_per_10pct",
        "growth_x_core",
        level,
        "current_log_capital",
    ]
    if len(data) < 100:
        return []
    fixed_effects = (data["stablecoin_scope_id"], data["month_id"])
    outcome_residual = absorb_fixed_effects(data[outcome], *fixed_effects)
    design_residual = absorb_fixed_effects(data[predictors], *fixed_effects)
    fit = ols_clustered(
        outcome_residual,
        design_residual,
        data["stablecoin_address"],
        add_constant=False,
        absorbed_groups=fixed_effects,
        additional_clusters=(data["month_id"],),
        min_observations=100,
        min_clusters=10,
    )
    model_id = f"{model_family}_{supply_measure}_supply"
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "stablecoin_supply_lp_coefficient",
                "model_id": model_id,
                "model_family": model_family,
                "scope": "stablecoin_core_and_spoke_aggregates",
                "supply_measure": supply_measure,
                "outcome": outcome,
                "predictor": predictor,
                "coefficient": float(coefficient),
                "standard_error": float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "stablecoins": int(data["stablecoin_address"].nunique()),
                "endpoints": None,
                "stablecoin_endpoint_pairs": None,
                "months": int(data["origin_month"].nunique()),
                "primary_clusters": int(data["stablecoin_address"].nunique()),
                "month_clusters": int(data["month_id"].nunique()),
                "fixed_effects": "stablecoin_x_scope+month",
                "covariance": "stablecoin_and_month_cluster_cr1",
                "predictor_timing": "stablecoin_supply_growth_from_t_minus_1_to_t",
                "outcome_timing": "aggregate_lp_capital_or_new_material_links_in_t_plus_1",
                "winsorization": "supply_growth_and_continuous_capital_growth_1st_99th_percentiles",
                "interpretation": "predictive_association_not_exogenous_issuance_shift",
            }
        )
    return rows


def fit_models(
    capital_growth: pd.DataFrame,
    formation: pd.DataFrame,
    stablecoin_scope: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for supply_measure in ("global", "ethereum"):
        for scope in ("all", "stable_core", "stable_spoke"):
            rows.extend(
                _fit_one_model(
                    capital_growth,
                    outcome="next_log_capital_change",
                    model_family="capital_growth",
                    scope=scope,
                    supply_measure=supply_measure,
                )
            )
            rows.extend(
                _fit_one_model(
                    formation,
                    outcome="forms_next_month",
                    model_family="formation",
                    scope=scope,
                    supply_measure=supply_measure,
                )
            )
        rows.extend(
            _fit_stablecoin_scope_model(
                stablecoin_scope,
                outcome="next_log_capital_change",
                model_family="stablecoin_scope_capital_growth",
                supply_measure=supply_measure,
            )
        )
        rows.extend(
            _fit_stablecoin_scope_model(
                stablecoin_scope,
                outcome="next_log1p_new_material_links",
                model_family="stablecoin_scope_formation_count",
                supply_measure=supply_measure,
            )
        )
    result = add_declared_family_adjustment(pd.DataFrame(rows))
    if result.empty:
        raise ValueError("stablecoin-supply LP models have no estimable samples")
    return result


def _holm_adjust(p_values: pd.Series) -> pd.Series:
    """Holm-adjust one declared family while preserving the original index."""

    if p_values.empty or p_values.isna().any():
        raise ValueError("Holm adjustment requires finite p-values")
    ordered = p_values.sort_values()
    total = len(ordered)
    adjusted = pd.Series(index=ordered.index, dtype=float)
    running = 0.0
    for rank, (index, value) in enumerate(ordered.items()):
        running = max(running, min(1.0, (total - rank) * float(value)))
        adjusted.loc[index] = running
    return adjusted.reindex(p_values.index)


def add_declared_family_adjustment(models: pd.DataFrame) -> pd.DataFrame:
    """Adjust the four primary worldwide-supply core/spoke tests."""

    result = models.copy()
    result["multiplicity_family"] = None
    result["family_hypotheses"] = None
    result["p_value_holm"] = np.nan
    primary = (
        result["model_family"].isin({"capital_growth", "formation"})
        & result["scope"].isin({"stable_core", "stable_spoke"})
        & result["supply_measure"].eq("global")
        & result["predictor"].eq("supply_growth_per_10pct")
    )
    if int(primary.sum()) != 4:
        raise ValueError("declared stablecoin-supply family must contain four tests")
    family = "global_supply_growth_x_core_spoke_x_capital_formation"
    result.loc[primary, "multiplicity_family"] = family
    result.loc[primary, "family_hypotheses"] = 4
    result.loc[primary, "p_value_holm"] = _holm_adjust(
        result.loc[primary, "p_value"]
    )
    return result


def support_records(
    supply: pd.DataFrame,
    roles: pd.DataFrame,
    relationships: pd.DataFrame,
    capital_growth: pd.DataFrame,
    formation: pd.DataFrame,
    stablecoin_scope: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "record_type": "stablecoin_supply_lp_support",
            "sample": "supply",
            "observations": int(len(supply)),
            "stablecoins": int(supply["token_address"].nunique()),
            "endpoints": None,
            "pairs": None,
            "months": int(supply["origin_month"].nunique()),
            "first_month": supply["origin_month"].min().strftime("%Y-%m-%d"),
            "last_month": supply["origin_month"].max().strftime("%Y-%m-%d"),
        },
        {
            "record_type": "stablecoin_supply_lp_support",
            "sample": "capital_growth",
            "observations": int(len(capital_growth)),
            "stablecoins": int(capital_growth["stablecoin_address"].nunique()),
            "endpoints": int(capital_growth["endpoint_address"].nunique()),
            "pairs": int(capital_growth["pair_id"].nunique()),
            "months": int(capital_growth["origin_month"].nunique()),
            "first_month": capital_growth["origin_month"].min().strftime("%Y-%m-%d"),
            "last_month": capital_growth["origin_month"].max().strftime("%Y-%m-%d"),
        },
        {
            "record_type": "stablecoin_supply_lp_support",
            "sample": "formation_risk_set",
            "observations": int(len(formation)),
            "stablecoins": int(formation["stablecoin_address"].nunique()),
            "endpoints": int(formation["endpoint_address"].nunique()),
            "pairs": int(formation["pair_id"].nunique()),
            "months": int(formation["origin_month"].nunique()),
            "first_month": formation["origin_month"].min().strftime("%Y-%m-%d"),
            "last_month": formation["origin_month"].max().strftime("%Y-%m-%d"),
            "first_material_links": int(formation["forms_next_month"].sum()),
        },
        {
            "record_type": "stablecoin_supply_lp_support",
            "sample": "stablecoin_scope_aggregate",
            "observations": int(len(stablecoin_scope)),
            "stablecoins": int(stablecoin_scope["stablecoin_address"].nunique()),
            "endpoints": None,
            "pairs": None,
            "months": int(stablecoin_scope["origin_month"].nunique()),
            "first_month": stablecoin_scope["origin_month"].min().strftime("%Y-%m-%d"),
            "last_month": stablecoin_scope["origin_month"].max().strftime("%Y-%m-%d"),
            "first_material_links": int(stablecoin_scope["next_new_material_links"].sum()),
        },
    ]
    for scope, group in relationships.groupby("scope"):
        stablecoin_capital = group.groupby("stablecoin_symbol")["capital_usd"].sum()
        shares = stablecoin_capital / stablecoin_capital.sum()
        rows.append(
            {
                "record_type": "stablecoin_supply_lp_concentration",
                "sample": "relationship_capital",
                "scope": scope,
                "observations": int(len(group)),
                "stablecoins": int(group["stablecoin_address"].nunique()),
                "endpoints": int(group["endpoint_address"].nunique()),
                "pairs": int(group["pair_id"].nunique()),
                "top_stablecoin": str(shares.idxmax()),
                "top_stablecoin_capital_share": float(shares.max()),
                "stablecoin_hhi": float(np.square(shares).sum()),
                "capital_stock_sum_usd": float(stablecoin_capital.sum()),
                "counting_note": "stable_core_pool_capital_appears_once_for_each_stablecoin_side",
            }
        )
    role_capital = roles.groupby("venue")["capital_usd"].sum()
    for venue, value in role_capital.items():
        rows.append(
            {
                "record_type": "stablecoin_supply_lp_concentration",
                "sample": "venue_capital",
                "venue": venue,
                "capital_stock_sum_usd": float(value),
                "capital_share": float(value / role_capital.sum()),
            }
        )
    formations = formation[formation["forms_next_month"].eq(1)]
    for (scope, stablecoin), group in formations.groupby(["scope", "stablecoin_symbol"]):
        rows.append(
            {
                "record_type": "stablecoin_supply_lp_formation_count",
                "scope": scope,
                "stablecoin_symbol": stablecoin,
                "first_material_links": int(len(group)),
                "endpoints": int(group["endpoint_address"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    supply_path: Path = SUPPLY_INPUT,
    v2_path: Path = V2_CAPITAL_INPUT,
    v3_path: Path = V3_CAPITAL_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    if not supply_path.is_file():
        raise FileNotFoundError(supply_path)
    observed = load_observed_pool_months(v2_path=v2_path, v3_path=v3_path)
    pool_months = carry_pool_capital_monthly(observed)
    roles = assign_stable_roles(pool_months)
    relationships = aggregate_relationship_capital(roles)
    supply = monthly_supply_panel(pd.read_parquet(supply_path))
    capital_growth = prepare_capital_growth_panel(relationships, supply)
    formation = prepare_formation_panel(relationships, supply)
    stablecoin_scope = prepare_stablecoin_scope_panel(relationships, supply)
    models = fit_models(capital_growth, formation, stablecoin_scope)
    support = support_records(
        supply, roles, relationships, capital_growth, formation, stablecoin_scope
    )
    write_panel(
        capital_growth,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes="Stablecoin-token--endpoint monthly capital growth with lagged worldwide and Ethereum stablecoin circulation.",
    )
    write_exhibit(models, model_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(capital_growth):,} continuing relationship-months, "
        f"{len(formation):,} formation-risk months, and {len(models):,} model rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supply", type=Path, default=SUPPLY_INPUT)
    parser.add_argument("--v2-capital", type=Path, default=V2_CAPITAL_INPUT)
    parser.add_argument("--v3-capital", type=Path, default=V3_CAPITAL_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        supply_path=args.supply,
        v2_path=args.v2_capital,
        v3_path=args.v3_capital,
        panel_output=args.panel_output,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
