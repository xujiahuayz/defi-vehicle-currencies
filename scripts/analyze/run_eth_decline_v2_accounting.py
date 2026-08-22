#!/usr/bin/env python3
"""Decompose stable-relative V2 depth changes around ETH price moves.

For each calendar date, the analysis selects material constant-product pools
that face DAI, USDC, USDT, or WETH and retains endpoints with both a stable and
a WETH family.  That pre-move pool set is held fixed over one-, three-, and
seven-day horizons.  Pools formed after the anchor date therefore cannot enter
the comparison.

Pool dollar capital obeys the identity ``V = Q * U``, where ``Q = sqrt(k)``
and ``U = V / Q``.  A symmetric Shapley decomposition attributes each family-
level log capital change to invariant quantity and unit value.  The latter
combines token-price revaluation with the reserve adjustment that arbitrage
induces; the former is a supply-side state but is not pure provider supply,
because swap fees and token donations can also change ``sqrt(k)``.

The reported regressions compare stable-family changes with WETH-family
changes for the same endpoint.  Endpoint and anchor-month effects are absorbed,
and inference uses date-level Newey--West score covariance to accommodate the
marketwide price regressor and overlapping horizons.  These are accounting and
predictive results, not causal estimates of provider behaviour or market
efficiency.

Writes
  output/exhibits/eth_decline_v2_accounting.jsonl
  output/exhibits/eth_decline_v2_accounting_support.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.asset_types import STABLE
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit


V2_INPUT = DATA_DIR / "processed/v2_lp_flow_pool_daily.parquet"
SUSHI_INPUT = DATA_DIR / "processed/sushiswap_v2_lp_flow_pool_daily.parquet"
PRICE_INPUT = DATA_DIR / "processed/token_price_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/eth_decline_v2_accounting.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/eth_decline_v2_accounting_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = (WETH, DAI, USDC, USDT)
STABLE_CANDIDATES = (DAI, USDC, USDT)
KNOWN_STABLES = frozenset(address.casefold() for address in STABLE)

HORIZONS = (1, 3, 7)
MATERIAL_CAPITAL_USD = 50_000.0
HAC_LAG_DAYS = 7
VALUATION_BENCHMARK_PER_10PP = 0.05

CODE_SOURCES = ["scripts/analyze/run_eth_decline_v2_accounting.py"]
INPUTS = [
    "data/processed/v2_lp_flow_pool_daily.parquet",
    "data/processed/sushiswap_v2_lp_flow_pool_daily.parquet",
    "data/processed/token_price_daily.parquet",
]

OUTCOMES = (
    "stable_minus_weth_log_capital_change",
    "stable_minus_weth_log_quantity_component",
    "stable_minus_weth_log_unit_value_component",
)


def _sql_addresses(addresses: Sequence[str]) -> str:
    """Return a quoted SQL literal list for checked hexadecimal constants."""

    values = []
    for address in addresses:
        normalized = str(address).casefold()
        if len(normalized) != 42 or not normalized.startswith("0x"):
            raise ValueError(f"invalid Ethereum address constant: {address}")
        int(normalized[2:], 16)
        values.append(f"'{normalized}'")
    return ", ".join(values)


def load_weth_prices(path: Path = PRICE_INPUT) -> pd.DataFrame:
    """Load the validated canonical WETH daily price series."""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = duckdb.connect()
    try:
        columns = {
            str(row[0])
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        }
        required = {"day", "token", "price_usd"}
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"daily price input lacks columns: {missing}")
        filters = ["lower(token) = ?", "price_usd > 0"]
        parameters: list[object] = [str(path), WETH]
        if "price_source" in columns:
            filters.append("price_source = 'canonical_repriced_route_legs'")
        if "validation_status" in columns:
            filters.append(
                "validation_status = "
                "'minimum_observations_and_price_consensus_passed'"
            )
        frame = connection.execute(
            f"""
            SELECT
                strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
                price_usd::DOUBLE AS price_usd
            FROM read_parquet(?)
            WHERE {' AND '.join(filters)}
            ORDER BY origin_date
            """,
            parameters,
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("canonical WETH daily price series is empty")
    return frame


def load_fixed_pool_matches(
    panel_paths: Sequence[Path],
    *,
    horizons: Sequence[int] = HORIZONS,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Load pre-move eligible pools and their fixed-set future states."""

    paths = [Path(path) for path in panel_paths]
    if not paths:
        raise ValueError("at least one V2 state panel is required")
    missing_paths = [str(path) for path in paths if not path.is_file()]
    if missing_paths:
        raise FileNotFoundError(", ".join(missing_paths))
    horizon_values = sorted({int(value) for value in horizons})
    if not horizon_values or any(value <= 0 for value in horizon_values):
        raise ValueError("accounting horizons must be positive days")
    if material_capital_usd <= 0:
        raise ValueError("material capital threshold must be positive")

    candidate_sql = _sql_addresses(CANDIDATES)
    stable_sql = _sql_addresses(STABLE_CANDIDATES)
    horizon_sql = ", ".join(f"({value})" for value in horizon_values)
    sources = " UNION ALL ".join(
        """
        SELECT
            origin_date::DATE AS state_date,
            lower(venue) AS venue,
            lower(pool) AS pool,
            lower(token0_address) AS token0_address,
            lower(token1_address) AS token1_address,
            v2_capital_usd::DOUBLE AS capital_usd,
            v2_sqrt_k::DOUBLE AS sqrt_k,
            v2_capital_valid::BOOLEAN AS capital_valid
        FROM read_parquet(?)
        """
        for _ in paths
    )
    query = f"""
    WITH raw_states AS (
        {sources}
    ), candidate_states AS (
        SELECT
            state_date,
            venue,
            pool,
            CASE
                WHEN token0_address = '{WETH}' OR token1_address = '{WETH}'
                    THEN 'native'
                WHEN token0_address IN ({stable_sql})
                  OR token1_address IN ({stable_sql})
                    THEN 'stable'
            END AS vehicle_family,
            CASE
                WHEN token0_address IN ({candidate_sql}) THEN token1_address
                ELSE token0_address
            END AS endpoint,
            capital_usd,
            sqrt_k
        FROM raw_states
        WHERE capital_valid
          AND capital_usd > 0
          AND sqrt_k > 0
          AND (
              CAST(token0_address IN ({candidate_sql}) AS INTEGER)
            + CAST(token1_address IN ({candidate_sql}) AS INTEGER)
          ) = 1
    ), eligible_anchor AS (
        SELECT venue, endpoint, state_date
        FROM candidate_states
        WHERE capital_usd >= ?
        GROUP BY venue, endpoint, state_date
        HAVING count(DISTINCT vehicle_family) = 2
    ), anchor_pools AS (
        SELECT state.*
        FROM candidate_states AS state
        INNER JOIN eligible_anchor AS eligible
            USING (venue, endpoint, state_date)
        WHERE state.capital_usd >= ?
    ), horizons(horizon_days) AS (
        VALUES {horizon_sql}
    )
    SELECT
        anchor.venue,
        anchor.endpoint,
        anchor.state_date AS anchor_date,
        horizon.horizon_days,
        anchor.pool,
        anchor.vehicle_family,
        anchor.capital_usd AS capital_usd_0,
        anchor.sqrt_k AS sqrt_k_0,
        future.state_date AS future_date,
        future.capital_usd AS capital_usd_1,
        future.sqrt_k AS sqrt_k_1,
        future.pool IS NOT NULL AS future_observed
    FROM anchor_pools AS anchor
    CROSS JOIN horizons AS horizon
    LEFT JOIN candidate_states AS future
      ON future.venue = anchor.venue
     AND future.pool = anchor.pool
     AND future.state_date = anchor.state_date + horizon.horizon_days
    ORDER BY anchor.venue, anchor.endpoint, anchor.state_date,
             horizon.horizon_days, anchor.vehicle_family, anchor.pool
    """
    connection = duckdb.connect()
    try:
        frame = connection.execute(
            query,
            [*(str(path) for path in paths), material_capital_usd, material_capital_usd],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("fixed-pool V2 accounting match is empty")
    key = ["venue", "pool", "anchor_date", "horizon_days"]
    if frame.duplicated(key).any():
        raise ValueError("fixed-pool V2 accounting match contains duplicate pool states")
    return frame


def _family_accounting(fixed: pd.DataFrame) -> pd.DataFrame:
    """Apply the exact family-level Shapley identity to matched pools."""

    data = fixed.copy()
    data["unit_value_0"] = data["capital_usd_0"] / data["sqrt_k_0"]
    data["unit_value_1"] = data["capital_usd_1"] / data["sqrt_k_1"]
    data["quantity_1_at_unit_0"] = data["sqrt_k_1"] * data["unit_value_0"]
    data["quantity_0_at_unit_1"] = data["sqrt_k_0"] * data["unit_value_1"]
    keys = [
        "venue",
        "endpoint",
        "anchor_date",
        "future_date",
        "horizon_days",
        "vehicle_family",
    ]
    family = (
        data.groupby(keys, as_index=False, sort=True)
        .agg(
            pools=("pool", "nunique"),
            capital_usd_0=("capital_usd_0", "sum"),
            capital_usd_1=("capital_usd_1", "sum"),
            quantity_1_at_unit_0=("quantity_1_at_unit_0", "sum"),
            quantity_0_at_unit_1=("quantity_0_at_unit_1", "sum"),
        )
        .reset_index(drop=True)
    )
    positive = family[
        [
            "capital_usd_0",
            "capital_usd_1",
            "quantity_1_at_unit_0",
            "quantity_0_at_unit_1",
        ]
    ].gt(0).all(axis=1)
    if not positive.all():
        raise ValueError("Shapley accounting inputs must be positive")
    v00 = family["capital_usd_0"]
    v11 = family["capital_usd_1"]
    v10 = family["quantity_1_at_unit_0"]
    v01 = family["quantity_0_at_unit_1"]
    family["log_capital_change"] = np.log(v11 / v00)
    family["log_quantity_component"] = 0.5 * (
        np.log(v10 / v00) + np.log(v11 / v01)
    )
    family["log_unit_value_component"] = 0.5 * (
        np.log(v01 / v00) + np.log(v11 / v10)
    )
    family["identity_error"] = family["log_capital_change"] - (
        family["log_quantity_component"]
        + family["log_unit_value_component"]
    )
    if family["identity_error"].abs().max() > 1e-10:
        raise ValueError("Shapley accounting identity failed")
    return family


def prepare_accounting_panel(
    matches: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    known_stables: frozenset[str] = KNOWN_STABLES,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build complete fixed-pool endpoint intervals and attach ETH moves."""

    required = {
        "venue",
        "endpoint",
        "anchor_date",
        "horizon_days",
        "pool",
        "vehicle_family",
        "capital_usd_0",
        "sqrt_k_0",
        "future_date",
        "capital_usd_1",
        "sqrt_k_1",
        "future_observed",
    }
    missing = sorted(required - set(matches.columns))
    if missing:
        raise ValueError(f"fixed-pool matches lack columns: {missing}")
    price_required = {"origin_date", "price_usd"}
    price_missing = sorted(price_required - set(prices.columns))
    if price_missing:
        raise ValueError(f"WETH prices lack columns: {price_missing}")

    data = matches.copy()
    data["anchor_date"] = pd.to_datetime(data["anchor_date"]).dt.normalize()
    data["future_date"] = pd.to_datetime(data["future_date"]).dt.normalize()
    data["endpoint"] = data["endpoint"].astype(str).str.casefold()
    data["vehicle_family"] = data["vehicle_family"].astype(str)
    if not set(data["vehicle_family"]).issubset({"native", "stable"}):
        raise ValueError("fixed-pool matches contain an unknown vehicle family")
    group_keys = ["venue", "endpoint", "anchor_date", "horizon_days"]
    complete = data.groupby(group_keys)["future_observed"].transform("all")
    candidate_intervals = int(data[group_keys].drop_duplicates().shape[0])
    complete_intervals = int(data.loc[complete, group_keys].drop_duplicates().shape[0])
    data = data.loc[complete].copy()
    numeric = ["capital_usd_0", "capital_usd_1", "sqrt_k_0", "sqrt_k_1"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[*numeric, "future_date"]
    )
    data = data[data[numeric].gt(0).all(axis=1)].copy()
    if data.empty:
        raise ValueError("no complete fixed-pool intervals remain")
    family = _family_accounting(data)

    index = ["venue", "endpoint", "anchor_date", "future_date", "horizon_days"]
    if family.duplicated([*index, "vehicle_family"]).any():
        raise ValueError("family accounting rows are duplicated")
    measures = [
        "pools",
        "capital_usd_0",
        "capital_usd_1",
        "log_capital_change",
        "log_quantity_component",
        "log_unit_value_component",
        "identity_error",
    ]
    wide = family.pivot(index=index, columns="vehicle_family", values=measures)
    if not {"native", "stable"}.issubset(wide.columns.get_level_values(1)):
        raise ValueError("complete intervals do not retain both vehicle families")
    wide.columns = [f"{family_name}_{measure}" for measure, family_name in wide.columns]
    panel = wide.reset_index()
    panel["stable_minus_weth_log_capital_change"] = (
        panel["stable_log_capital_change"] - panel["native_log_capital_change"]
    )
    panel["stable_minus_weth_log_quantity_component"] = (
        panel["stable_log_quantity_component"]
        - panel["native_log_quantity_component"]
    )
    panel["stable_minus_weth_log_unit_value_component"] = (
        panel["stable_log_unit_value_component"]
        - panel["native_log_unit_value_component"]
    )
    panel["relative_identity_error"] = (
        panel["stable_minus_weth_log_capital_change"]
        - panel["stable_minus_weth_log_quantity_component"]
        - panel["stable_minus_weth_log_unit_value_component"]
    )
    if panel["relative_identity_error"].abs().max() > 2e-10:
        raise ValueError("stable-relative accounting identity failed")

    price = prices[["origin_date", "price_usd"]].copy()
    price["origin_date"] = pd.to_datetime(price["origin_date"]).dt.normalize()
    price["price_usd"] = pd.to_numeric(price["price_usd"], errors="coerce")
    price = price.dropna().drop_duplicates("origin_date")
    if price["price_usd"].le(0).any():
        raise ValueError("WETH prices must be positive")
    anchor_price = price.rename(
        columns={"origin_date": "anchor_date", "price_usd": "weth_price_0"}
    )
    future_price = price.rename(
        columns={"origin_date": "future_date", "price_usd": "weth_price_1"}
    )
    panel = panel.merge(anchor_price, on="anchor_date", how="inner", validate="many_to_one")
    panel = panel.merge(future_price, on="future_date", how="inner", validate="many_to_one")
    panel["eth_log_return"] = np.log(panel["weth_price_1"] / panel["weth_price_0"])
    panel["eth_decline_per_10pp"] = -panel["eth_log_return"] / 0.10
    panel["endpoint_is_stable"] = panel["endpoint"].isin(known_stables)
    panel["endpoint_fixed_effect"] = panel["venue"] + "|" + panel["endpoint"]
    panel["anchor_month"] = panel["anchor_date"].dt.to_period("M").astype(str)
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["eth_decline_per_10pp", *OUTCOMES]
    )
    if panel.empty or panel.duplicated(group_keys).any():
        raise ValueError("accounting panel is empty or duplicated")
    support = {
        "candidate_endpoint_intervals": candidate_intervals,
        "complete_endpoint_intervals_before_price_match": complete_intervals,
        "complete_followup_share": complete_intervals / candidate_intervals,
        "price_matched_endpoint_intervals": int(len(panel)),
        "maximum_relative_identity_error": float(
            panel["relative_identity_error"].abs().max()
        ),
    }
    return panel.sort_values(group_keys).reset_index(drop=True), support


def fit_accounting_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 250,
    min_endpoints: int = 20,
    min_dates: int = 60,
    hac_lag_days: int = HAC_LAG_DAYS,
) -> pd.DataFrame:
    """Estimate ETH-price slopes for the three exact accounting components."""

    rows: list[dict[str, object]] = []
    primary = panel.loc[~panel["endpoint_is_stable"].astype(bool)].copy()
    venue_groups = [("pooled_v2", primary)] + [
        (str(venue), group.copy()) for venue, group in primary.groupby("venue")
    ]
    for venue, venue_data in venue_groups:
        for horizon, horizon_data in venue_data.groupby("horizon_days", sort=True):
            for outcome in OUTCOMES:
                columns = [
                    outcome,
                    "eth_decline_per_10pp",
                    "endpoint_fixed_effect",
                    "anchor_month",
                    "anchor_date",
                ]
                data = horizon_data[columns].dropna().copy()
                endpoint_size = data.groupby("endpoint_fixed_effect")[
                    "endpoint_fixed_effect"
                ].transform("size")
                data = data.loc[endpoint_size.gt(1)].copy()
                endpoints = int(data["endpoint_fixed_effect"].nunique())
                dates = int(data["anchor_date"].nunique())
                if len(data) < min_observations or endpoints < min_endpoints or dates < min_dates:
                    continue
                fixed_effects = (data["endpoint_fixed_effect"], data["anchor_month"])
                residual = absorb_fixed_effects(
                    data[[outcome, "eth_decline_per_10pp"]], *fixed_effects
                )
                fit = ols_clustered(
                    residual[outcome],
                    residual[["eth_decline_per_10pp"]],
                    data["anchor_date"],
                    add_constant=False,
                    absorbed_groups=fixed_effects,
                    min_observations=min_observations,
                    min_clusters=min_dates,
                    cluster_hac_lag=hac_lag_days,
                )
                coefficient = float(fit.beta[0])
                standard_error = float(fit.standard_errors[0])
                if not np.isfinite(coefficient) or not np.isfinite(standard_error):
                    raise ValueError(f"nonfinite accounting estimate: {venue}, {horizon}, {outcome}")
                benchmark = (
                    VALUATION_BENCHMARK_PER_10PP
                    if outcome.endswith("unit_value_component")
                    else 0.0
                )
                degrees_freedom = fit.n_clusters - 1
                benchmark_t = (
                    (coefficient - benchmark) / standard_error
                    if standard_error > 0
                    else np.nan
                )
                benchmark_p = (
                    float(2 * stats.t.sf(abs(benchmark_t), degrees_freedom))
                    if np.isfinite(benchmark_t) and degrees_freedom > 0
                    else np.nan
                )
                rows.append(
                    {
                        "record_type": "eth_decline_v2_accounting_regression",
                        "analysis_status": "focused_accounting_test",
                        "venue": venue,
                        "horizon_days": int(horizon),
                        "sample": "nonstable_endpoints_with_material_stable_and_weth_pools_at_anchor",
                        "outcome": outcome,
                        "predictor": "eth_decline_per_10pp",
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(fit.t_statistics[0]),
                        "p_value": float(fit.p_values[0]),
                        "holm_p_value": np.nan,
                        "benchmark": benchmark,
                        "benchmark_interpretation": (
                            "constant_product_arbitrage_valuation_slope"
                            if benchmark
                            else "zero"
                        ),
                        "difference_from_benchmark": coefficient - benchmark,
                        "benchmark_t_statistic": benchmark_t,
                        "benchmark_p_value": benchmark_p,
                        "coefficient_log_points_per_10pp_eth_decline": coefficient,
                        "coefficient_approx_percentage_points": 100.0 * coefficient,
                        "observations": int(fit.n_observations),
                        "endpoints": endpoints,
                        "dates": dates,
                        "fixed_effects": "venue_x_endpoint+anchor_year_month",
                        "covariance": f"anchor_date_score_hac_bartlett_lag_{hac_lag_days}_days",
                        "pool_set": "material_anchor_pools_held_fixed_complete_followup",
                        "quantity_interpretation": "sqrt_k_invariant_lp_actions_plus_fee_accumulation",
                        "unit_value_interpretation": "token_price_revaluation_plus_arbitrage_reserve_adjustment",
                        "causal_interpretation": False,
                        "within_r_squared": float(fit.r_squared),
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("no V2 accounting model meets the declared support thresholds")
    result["holm_p_value"] = holm_adjusted_pvalues(result["p_value"])
    return result


def support_records(
    panel: pd.DataFrame,
    extraction_support: dict[str, object],
    *,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Document sample coverage and component means on ETH-decline intervals."""

    rows: list[dict[str, object]] = [
        {
            "record_type": "eth_decline_v2_accounting_design_support",
            **extraction_support,
            "material_anchor_pool_capital_usd": material_capital_usd,
            "horizons_days": "+".join(str(value) for value in HORIZONS),
            "candidate_vehicles": "WETH_vs_DAI_USDC_USDT",
            "fixed_pool_rule": "pool_must_exist_and_be_material_at_anchor_new_entries_excluded",
            "followup_rule": "all_selected_anchor_pools_require_positive_valid_future_state",
            "capital_identity": "V_equals_sqrt_k_times_V_over_sqrt_k",
            "decomposition": "symmetric_shapley_log_change",
            "mechanical_valuation_benchmark_per_10pp_eth_decline": VALUATION_BENCHMARK_PER_10PP,
            "quantity_caveat": "sqrt_k_changes_with_lp_actions_swap_fees_and_donations",
            "stable_core_in_primary_models": False,
        }
    ]
    for venue, venue_data in panel.groupby("venue", sort=True):
        for horizon, data in venue_data.groupby("horizon_days", sort=True):
            nonstable = data.loc[~data["endpoint_is_stable"].astype(bool)].copy()
            decline = nonstable.loc[nonstable["eth_log_return"].lt(0)]
            large_decline = nonstable.loc[nonstable["eth_log_return"].le(np.log(0.95))]
            rows.append(
                {
                    "record_type": "eth_decline_v2_accounting_sample_support",
                    "venue": venue,
                    "horizon_days": int(horizon),
                    "endpoint_intervals": int(len(nonstable)),
                    "endpoints": int(nonstable["endpoint"].nunique()),
                    "dates": int(nonstable["anchor_date"].nunique()),
                    "anchor_pools": int(
                        nonstable["native_pools"].sum() + nonstable["stable_pools"].sum()
                    ),
                    "first_anchor_date": nonstable["anchor_date"].min().strftime("%Y-%m-%d"),
                    "last_anchor_date": nonstable["anchor_date"].max().strftime("%Y-%m-%d"),
                    "stable_endpoint_interval_share_excluded_from_primary": float(
                        data["endpoint_is_stable"].mean()
                    ),
                    "eth_decline_interval_share": float(nonstable["eth_log_return"].lt(0).mean()),
                    "eth_decline_at_least_5pct_intervals": int(len(large_decline)),
                    "median_native_anchor_capital_usd": float(
                        nonstable["native_capital_usd_0"].median()
                    ),
                    "median_stable_anchor_capital_usd": float(
                        nonstable["stable_capital_usd_0"].median()
                    ),
                    "mean_relative_capital_change_on_declines": float(
                        decline["stable_minus_weth_log_capital_change"].mean()
                    ),
                    "mean_relative_quantity_component_on_declines": float(
                        decline["stable_minus_weth_log_quantity_component"].mean()
                    ),
                    "mean_relative_unit_value_component_on_declines": float(
                        decline["stable_minus_weth_log_unit_value_component"].mean()
                    ),
                    "mean_relative_capital_change_on_5pct_declines": float(
                        large_decline["stable_minus_weth_log_capital_change"].mean()
                    ),
                    "mean_relative_quantity_component_on_5pct_declines": float(
                        large_decline["stable_minus_weth_log_quantity_component"].mean()
                    ),
                    "mean_relative_unit_value_component_on_5pct_declines": float(
                        large_decline["stable_minus_weth_log_unit_value_component"].mean()
                    ),
                    "maximum_relative_identity_error": float(
                        nonstable["relative_identity_error"].abs().max()
                    ),
                }
            )
    return pd.DataFrame(rows)


def run(
    *,
    v2_path: Path = V2_INPUT,
    sushi_path: Path = SUSHI_INPUT,
    price_path: Path = PRICE_INPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    matches = load_fixed_pool_matches([v2_path, sushi_path])
    panel, extraction_support = prepare_accounting_panel(
        matches, load_weth_prices(price_path)
    )
    results = fit_accounting_models(panel)
    support = support_records(panel, extraction_support)
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results):,} estimates from {len(panel):,} complete "
        f"endpoint intervals across {panel['endpoint'].nunique():,} endpoints"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-panel", type=Path, default=V2_INPUT)
    parser.add_argument("--sushi-panel", type=Path, default=SUSHI_INPUT)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        v2_path=args.v2_panel,
        sushi_path=args.sushi_panel,
        price_path=args.prices,
        result_output=args.result_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
