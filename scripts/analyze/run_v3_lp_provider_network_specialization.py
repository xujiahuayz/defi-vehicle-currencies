#!/usr/bin/env python3
"""Measure whether V3 pool formation draws on vehicle-network LP experience.

For each Uniswap V3 endpoint--vehicle pool, the event is the first week in which reported
TVL reaches a material threshold.  Transaction origins adding liquidity during
that week are linked to their own earlier positive-liquidity V3 mints.  Prior
experience is strictly lagged and excludes both the focal pool and every pool
paired with the focal endpoint.  The resulting quantity is vehicle-network
specialization outside the relationship being formed, not a mechanical history
of activity in the same endpoint pair.

The declared primary family contains four $50,000-threshold, 90-day-lookback,
formation-week specifications: outside-network experience as an indicator and
as endpoint breadth, followed by stable-core experience as an indicator and as
pool breadth.  Holm adjustment controls that four-model family.  The following
week and alternate thresholds/lookbacks are sensitivities.

Every model compares WETH, DAI, USDC, and USDT, absorbs origin-event and
vehicle-by-calendar-quarter fixed effects, and clusters by both focal pool and
transaction origin.  The association is descriptive: transaction origin is a
participation proxy, and the observed pool opportunity set is not a provider
choice set.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


ORIGIN_INPUT = DATA_DIR / "processed/v3_lp_add_origin_pool_daily.parquet"
FEE_INPUT = DATA_DIR / "processed/v3_pool_day_fees.parquet"
EVENT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_provider_specialization_events.parquet"
SUMMARY_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_provider_specialization_summary.jsonl"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_provider_specialization_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_provider_specialization_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = {WETH: "WETH", DAI: "DAI", USDC: "USDC", USDT: "USDT"}
USD_STABLES = {DAI, USDC, USDT}
VENUE_SCOPE = "Uniswap V3"
VEHICLE_SCOPE = "WETH, DAI, USDC, USDT"
PRIMARY_FAMILY_ID = "v3_provider_specialization_50000_90d_formation_m1_m4"
PRIMARY_MODEL_IDS = {
    "m1_prior_vehicle_network_indicator",
    "m2_log_prior_vehicle_network_endpoints",
    "m3_stable_spoke_prior_same_token_core_indicator",
    "m4_stable_spoke_log_prior_same_token_core_pools",
}

MAIN_MATERIAL_TVL_USD = 50_000.0
SENSITIVITY_TVL_USD = (10_000.0, 100_000.0)
LOOKBACK_DAYS = (30, 90)
SAMPLE_END = pd.Timestamp("2026-06-30")

CODE_SOURCES = ["scripts/analyze/run_v3_lp_provider_network_specialization.py"]
INPUTS = [
    "data/processed/v3_lp_add_origin_pool_daily.parquet",
    "data/processed/v3_pool_day_fees.parquet",
]


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _candidate_sql_values() -> str:
    return ",".join(f"'{address}'" for address in CANDIDATES)


def first_material_pool_events(
    fee_path: Path,
    *,
    material_tvl_usd: float,
    sample_end: pd.Timestamp = SAMPLE_END,
) -> pd.DataFrame:
    """Return first-material weeks for endpoint--vehicle V3 spoke pools."""

    if material_tvl_usd <= 0:
        raise ValueError("material TVL threshold must be positive")
    candidates = _candidate_sql_values()
    query = f"""
    WITH daily AS (
        SELECT
            CAST(origin_date AS DATE) AS origin_date,
            lower(pool) AS pool,
            lower(token0_address) AS token0_address,
            lower(token1_address) AS token1_address,
            tvl_usd::DOUBLE AS tvl_usd
        FROM read_parquet('{_sql_path(fee_path)}')
        WHERE CAST(origin_date AS DATE) <= DATE '{sample_end:%Y-%m-%d}'
          AND tvl_usd >= 0
    ),
    spoke AS (
        SELECT
            *,
            CASE WHEN token0_address IN ({candidates})
                 THEN token0_address ELSE token1_address END AS candidate_address,
            CASE WHEN token0_address IN ({candidates})
                 THEN token1_address ELSE token0_address END AS endpoint_address
        FROM daily
        WHERE ((token0_address IN ({candidates}))::INTEGER
             + (token1_address IN ({candidates}))::INTEGER) = 1
    ),
    registry AS (
        SELECT
            pool,
            min(candidate_address) AS candidate_address,
            min(endpoint_address) AS endpoint_address,
            count(DISTINCT candidate_address) AS candidate_identities,
            count(DISTINCT endpoint_address) AS endpoint_identities
        FROM spoke
        GROUP BY 1
    ),
    first_material AS (
        SELECT
            s.pool,
            r.candidate_address,
            r.endpoint_address,
            min(s.origin_date) FILTER (WHERE s.tvl_usd >= {material_tvl_usd})
                AS first_material_date,
            max(s.tvl_usd)::DOUBLE AS maximum_tvl_usd
        FROM spoke s
        JOIN registry r USING (pool)
        WHERE r.candidate_identities = 1 AND r.endpoint_identities = 1
        GROUP BY 1,2,3
    )
    SELECT
        pool,
        candidate_address,
        CASE candidate_address
            WHEN '{WETH}' THEN 'WETH'
            WHEN '{DAI}' THEN 'DAI'
            WHEN '{USDC}' THEN 'USDC'
            WHEN '{USDT}' THEN 'USDT'
        END AS candidate_symbol,
        CASE WHEN candidate_address = '{WETH}' THEN 'WETH' ELSE 'stable' END
            AS vehicle_type,
        endpoint_address,
        first_material_date,
        date_trunc('week', first_material_date)::DATE AS event_week,
        maximum_tvl_usd,
        {material_tvl_usd}::DOUBLE AS material_tvl_usd
    FROM first_material
    WHERE first_material_date IS NOT NULL
      AND date_trunc('week', first_material_date)::DATE + INTERVAL '6 days'
          <= DATE '{sample_end:%Y-%m-%d}'
    ORDER BY event_week, pool
    """
    connection = duckdb.connect()
    try:
        events = connection.execute(query).fetchdf()
    finally:
        connection.close()
    if events.empty:
        raise ValueError("V3 fee panel produced no first-material spoke-pool events")
    events["first_material_date"] = pd.to_datetime(events["first_material_date"])
    events["event_week"] = pd.to_datetime(events["event_week"])
    if events["pool"].duplicated().any():
        raise ValueError("first-material V3 pool events are not unique by pool")
    return events


def build_specialization_choice_panel(
    origin_path: Path,
    events: pd.DataFrame,
    *,
    lookback_days: int,
    supply_week_offset: int = 0,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Stack four candidate histories for origins supplying focal event weeks."""

    if lookback_days <= 0:
        raise ValueError("provider-network lookback must be positive")
    if supply_week_offset < 0:
        raise ValueError("supply-week offset must be nonnegative")
    required = {
        "pool",
        "candidate_address",
        "candidate_symbol",
        "vehicle_type",
        "endpoint_address",
        "event_week",
        "material_tvl_usd",
    }
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"first-material events lack columns: {missing}")
    connection = duckdb.connect()
    try:
        connection.register("events", events)
        connection.register(
            "vehicle_candidates",
            pd.DataFrame(
                {
                    "history_candidate_address": list(CANDIDATES),
                    "history_candidate_symbol": list(CANDIDATES.values()),
                }
            ),
        )
        stable_values = ",".join(f"'{address}'" for address in USD_STABLES)
        query = f"""
        WITH focal AS (
            SELECT
                e.pool,
                e.candidate_address,
                e.candidate_symbol,
                e.vehicle_type,
                e.endpoint_address,
                CAST(e.event_week AS DATE) AS event_week,
                CAST(e.event_week AS DATE)
                    + INTERVAL '{7 * supply_week_offset} days' AS supply_week,
                {supply_week_offset}::INTEGER AS supply_week_offset,
                e.material_tvl_usd,
                p.origin,
                sum(p.v3_add_action_events)::DOUBLE AS focal_add_actions,
                sum(p.v3_add_action_transactions)::DOUBLE
                    AS focal_add_transactions,
                sum(p.v3_add_flow_usd_screened)::DOUBLE
                    AS focal_add_flow_usd
            FROM events e
            JOIN read_parquet('{_sql_path(origin_path)}') p
              ON lower(p.pool) = lower(e.pool)
             AND lower(p.candidate_address) = lower(e.candidate_address)
             AND CAST(p.origin_date AS DATE) >= CAST(e.event_week AS DATE)
                 + INTERVAL '{7 * supply_week_offset} days'
             AND CAST(p.origin_date AS DATE)
                 < CAST(e.event_week AS DATE)
                    + INTERVAL '{7 * (supply_week_offset + 1)} days'
            WHERE p.origin <> '' AND p.v3_add_action_events > 0
            GROUP BY 1,2,3,4,5,6,7,8,9,10
        ),
        choice AS (
            SELECT f.*, c.*
            FROM focal f CROSS JOIN vehicle_candidates c
        ),
        history AS (
            SELECT
                c.*,
                count(DISTINCT h.pool)::INTEGER AS prior_distinct_pools,
                count(DISTINCT h.paired_token_address)::INTEGER
                    AS prior_distinct_endpoints,
                coalesce(sum(h.v3_add_action_events), 0)::DOUBLE
                    AS prior_add_actions,
                coalesce(sum(h.v3_add_action_transactions), 0)::DOUBLE
                    AS prior_add_transactions,
                coalesce(sum(h.v3_add_flow_usd_screened), 0)::DOUBLE
                    AS prior_add_flow_usd,
                count(DISTINCT h.pool) FILTER (
                    WHERE c.history_candidate_address IN ({stable_values})
                      AND lower(h.paired_token_address) IN ({stable_values})
                )::INTEGER AS prior_stable_core_distinct_pools,
                count(DISTINCT h.paired_token_address) FILTER (
                    WHERE c.history_candidate_address IN ({stable_values})
                      AND lower(h.paired_token_address) IN ({stable_values})
                )::INTEGER AS prior_stable_core_distinct_counterparties,
                coalesce(sum(h.v3_add_action_events) FILTER (
                    WHERE c.history_candidate_address IN ({stable_values})
                      AND lower(h.paired_token_address) IN ({stable_values})
                ), 0)::DOUBLE AS prior_stable_core_add_actions,
                coalesce(sum(h.v3_add_flow_usd_screened) FILTER (
                    WHERE c.history_candidate_address IN ({stable_values})
                      AND lower(h.paired_token_address) IN ({stable_values})
                ), 0)::DOUBLE AS prior_stable_core_add_flow_usd,
                count(DISTINCT h.pool) FILTER (
                    WHERE NOT (
                        c.history_candidate_address IN ({stable_values})
                        AND lower(h.paired_token_address) IN ({stable_values})
                    )
                )::INTEGER AS prior_noncore_spoke_distinct_pools,
                coalesce(sum(h.v3_add_action_events) FILTER (
                    WHERE NOT (
                        c.history_candidate_address IN ({stable_values})
                        AND lower(h.paired_token_address) IN ({stable_values})
                    )
                ), 0)::DOUBLE AS prior_noncore_spoke_add_actions
            FROM choice c
            LEFT JOIN read_parquet('{_sql_path(origin_path)}') h
              ON lower(h.origin) = lower(c.origin)
             AND lower(h.candidate_address) = lower(c.history_candidate_address)
             AND CAST(h.origin_date AS DATE)
                 >= c.supply_week - INTERVAL '{lookback_days} days'
             AND CAST(h.origin_date AS DATE) < c.supply_week
             AND lower(h.pool) <> lower(c.pool)
             AND lower(h.paired_token_address) <> lower(c.endpoint_address)
             AND h.v3_add_action_events > 0
            GROUP BY ALL
        )
        SELECT * FROM history
        ORDER BY event_week, pool, origin, history_candidate_address
        """
        panel = connection.execute(query).fetchdf()
    finally:
        connection.close()
    if panel.empty:
        raise ValueError("V3 first-material events have no observed LP-add origins")
    panel["event_week"] = pd.to_datetime(panel["event_week"])
    panel["supply_week"] = pd.to_datetime(panel["supply_week"])
    panel["is_actual_vehicle"] = panel["history_candidate_address"].eq(
        panel["candidate_address"]
    ).astype(int)
    panel["prior_same_vehicle_any"] = panel["prior_distinct_pools"].gt(0).astype(int)
    panel["prior_stable_core_any"] = (
        panel["prior_stable_core_distinct_pools"].gt(0).astype(int)
    )
    panel["prior_noncore_spoke_any"] = (
        panel["prior_noncore_spoke_distinct_pools"].gt(0).astype(int)
    )
    panel["log1p_prior_distinct_endpoints"] = np.log1p(
        panel["prior_distinct_endpoints"].astype(float)
    )
    panel["log1p_prior_add_actions"] = np.log1p(
        panel["prior_add_actions"].astype(float)
    )
    panel["log1p_prior_stable_core_pools"] = np.log1p(
        panel["prior_stable_core_distinct_pools"].astype(float)
    )
    panel["event_origin_id"] = (
        panel["pool"]
        + "|"
        + panel["supply_week_offset"].astype(str)
        + "|"
        + panel["origin"]
    )
    panel["candidate_quarter_id"] = (
        panel["history_candidate_address"]
        + "|"
        + panel["supply_week"].dt.to_period("Q").astype(str)
    )
    panel["lookback_days"] = int(lookback_days)
    expected_rows = panel["event_origin_id"].nunique() * len(CANDIDATES)
    if len(panel) != expected_rows:
        raise ValueError("V3 specialization choice sets do not contain four vehicles")
    support = {
        "first_material_events": int(len(events)),
        "events_with_observed_add_origins": int(panel["pool"].nunique()),
        "event_origin_observations": int(panel["event_origin_id"].nunique()),
        "distinct_transaction_origin_proxies": int(panel["origin"].nunique()),
        "stacked_choice_rows": int(len(panel)),
        "supply_week_offset": int(supply_week_offset),
    }
    return panel, support


def event_level_summary(choice_panel: pd.DataFrame) -> pd.DataFrame:
    """Collapse actual-vehicle histories to one row per pool-formation event."""

    actual = choice_panel.loc[choice_panel["is_actual_vehicle"].eq(1)].copy()
    alternatives = (
        choice_panel.loc[choice_panel["is_actual_vehicle"].eq(0)]
        .groupby("event_origin_id", as_index=False)
        .agg(
            alternative_log1p_endpoints=(
                "log1p_prior_distinct_endpoints",
                "mean",
            ),
            alternative_any_rate=("prior_same_vehicle_any", "mean"),
        )
    )
    actual = actual.merge(alternatives, on="event_origin_id", validate="one_to_one")
    actual["actual_minus_alternative_log1p_endpoints"] = (
        actual["log1p_prior_distinct_endpoints"]
        - actual["alternative_log1p_endpoints"]
    )
    actual["experienced_focal_flow_usd"] = (
        actual["focal_add_flow_usd"] * actual["prior_same_vehicle_any"]
    )
    actual["stable_core_experienced_focal_flow_usd"] = (
        actual["focal_add_flow_usd"] * actual["prior_stable_core_any"]
    )
    actual["noncore_spoke_experienced_focal_flow_usd"] = (
        actual["focal_add_flow_usd"] * actual["prior_noncore_spoke_any"]
    )
    events = (
        actual.groupby(
            [
                "pool",
                "candidate_address",
                "candidate_symbol",
                "vehicle_type",
                "endpoint_address",
                "event_week",
                "supply_week",
                "supply_week_offset",
                "material_tvl_usd",
                "lookback_days",
            ],
            as_index=False,
        )
        .agg(
            focal_origin_count=("origin", "nunique"),
            focal_add_actions=("focal_add_actions", "sum"),
            focal_add_flow_usd=("focal_add_flow_usd", "sum"),
            experienced_origin_share=("prior_same_vehicle_any", "mean"),
            stable_core_experienced_origin_share=(
                "prior_stable_core_any",
                "mean",
            ),
            noncore_spoke_experienced_origin_share=(
                "prior_noncore_spoke_any",
                "mean",
            ),
            experienced_focal_flow_usd=("experienced_focal_flow_usd", "sum"),
            stable_core_experienced_focal_flow_usd=(
                "stable_core_experienced_focal_flow_usd",
                "sum",
            ),
            noncore_spoke_experienced_focal_flow_usd=(
                "noncore_spoke_experienced_focal_flow_usd",
                "sum",
            ),
            median_prior_distinct_endpoints=("prior_distinct_endpoints", "median"),
            mean_actual_minus_alternative_log1p_endpoints=(
                "actual_minus_alternative_log1p_endpoints",
                "mean",
            ),
        )
    )
    events["experienced_focal_flow_share"] = np.divide(
        events["experienced_focal_flow_usd"],
        events["focal_add_flow_usd"],
        out=np.full(len(events), np.nan),
        where=events["focal_add_flow_usd"].to_numpy() > 0,
    )
    events["stable_core_experienced_focal_flow_share"] = np.divide(
        events["stable_core_experienced_focal_flow_usd"],
        events["focal_add_flow_usd"],
        out=np.full(len(events), np.nan),
        where=events["focal_add_flow_usd"].to_numpy() > 0,
    )
    events["noncore_spoke_experienced_focal_flow_share"] = np.divide(
        events["noncore_spoke_experienced_focal_flow_usd"],
        events["focal_add_flow_usd"],
        out=np.full(len(events), np.nan),
        where=events["focal_add_flow_usd"].to_numpy() > 0,
    )
    return events


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    """Report event-equal formation shares and the stable-minus-WETH contrast."""

    rows: list[dict[str, object]] = []
    for (threshold, lookback, supply_week_offset), family in events.groupby(
        ["material_tvl_usd", "lookback_days", "supply_week_offset"], sort=True
    ):
        for vehicle_type, sample in family.groupby("vehicle_type", sort=True):
            rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_summary",
                    "comparison": vehicle_type,
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": int(supply_week_offset),
                    "events": int(len(sample)),
                    "focal_origin_observations": int(sample["focal_origin_count"].sum()),
                    "mean_event_experienced_origin_share": float(
                        sample["experienced_origin_share"].mean()
                    ),
                    "median_event_experienced_origin_share": float(
                        sample["experienced_origin_share"].median()
                    ),
                    "mean_event_experienced_flow_share": float(
                        sample["experienced_focal_flow_share"].mean()
                    ),
                    "mean_event_actual_minus_alternative_log1p_endpoints": float(
                        sample[
                            "mean_actual_minus_alternative_log1p_endpoints"
                        ].mean()
                    ),
                }
            )
        stable_only = family.loc[family["vehicle_type"].eq("stable")]
        rows.append(
            {
                "record_type": "v3_lp_stable_core_to_spoke_summary",
                "comparison": "stable_spoke_origins",
                "material_tvl_usd": float(threshold),
                "lookback_days": int(lookback),
                "supply_week_offset": int(supply_week_offset),
                "events": int(len(stable_only)),
                "focal_origin_observations": int(
                    stable_only["focal_origin_count"].sum()
                ),
                "mean_event_prior_stable_core_origin_share": float(
                    stable_only["stable_core_experienced_origin_share"].mean()
                ),
                "mean_event_prior_noncore_spoke_origin_share": float(
                    stable_only["noncore_spoke_experienced_origin_share"].mean()
                ),
                "mean_event_prior_stable_core_flow_share": float(
                    stable_only["stable_core_experienced_focal_flow_share"].mean()
                ),
                "mean_event_prior_noncore_spoke_flow_share": float(
                    stable_only["noncore_spoke_experienced_focal_flow_share"].mean()
                ),
            }
        )
        annual = family.assign(event_year=family["event_week"].dt.year)
        for (vehicle_type, event_year), period in annual.groupby(
            ["vehicle_type", "event_year"], sort=True
        ):
            rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_by_year",
                    "comparison": vehicle_type,
                    "event_year": int(event_year),
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": int(supply_week_offset),
                    "events": int(len(period)),
                    "focal_origin_observations": int(
                        period["focal_origin_count"].sum()
                    ),
                    "mean_event_prior_same_vehicle_origin_share": float(
                        period["experienced_origin_share"].mean()
                    ),
                    "mean_event_prior_stable_core_origin_share": float(
                        period["stable_core_experienced_origin_share"].mean()
                    )
                    if vehicle_type == "stable"
                    else np.nan,
                    "mean_event_prior_noncore_spoke_origin_share": float(
                        period["noncore_spoke_experienced_origin_share"].mean()
                    )
                    if vehicle_type == "stable"
                    else np.nan,
                    "mean_event_prior_same_vehicle_flow_share": float(
                        period["experienced_focal_flow_share"].mean()
                    ),
                }
            )
        for event_year, period in annual.groupby("event_year", sort=True):
            stable_period = period.loc[period["vehicle_type"].eq("stable")]
            weth_period = period.loc[period["vehicle_type"].eq("WETH")]
            if stable_period.empty or weth_period.empty:
                continue
            for outcome in (
                "experienced_origin_share",
                "experienced_focal_flow_share",
            ):
                stable_mean = float(stable_period[outcome].mean())
                weth_mean = float(weth_period[outcome].mean())
                rows.append(
                    {
                        "record_type": (
                            "v3_lp_stable_minus_WETH_familiarity_by_year"
                        ),
                        "comparison": "stable_minus_WETH",
                        "outcome": outcome,
                        "event_year": int(event_year),
                        "material_tvl_usd": float(threshold),
                        "lookback_days": int(lookback),
                        "supply_week_offset": int(supply_week_offset),
                        "stable_events": int(len(stable_period)),
                        "WETH_events": int(len(weth_period)),
                        "stable_mean": stable_mean,
                        "WETH_mean": weth_mean,
                        "difference": stable_mean - weth_mean,
                    }
                )
        stable = family.loc[family["vehicle_type"].eq("stable")]
        weth = family.loc[family["vehicle_type"].eq("WETH")]
        for outcome in (
            "experienced_origin_share",
            "experienced_focal_flow_share",
            "mean_actual_minus_alternative_log1p_endpoints",
        ):
            stable_values = stable[outcome].dropna().to_numpy(dtype=float)
            weth_values = weth[outcome].dropna().to_numpy(dtype=float)
            if len(stable_values) >= 2 and len(weth_values) >= 2:
                test = stats.ttest_ind(
                    stable_values,
                    weth_values,
                    equal_var=False,
                    nan_policy="omit",
                )
                stable_mean = float(np.mean(stable_values))
                weth_mean = float(np.mean(weth_values))
                difference = stable_mean - weth_mean
                test_statistic = float(test.statistic)
                p_value = float(test.pvalue)
            else:
                stable_mean = (
                    float(np.mean(stable_values)) if len(stable_values) else np.nan
                )
                weth_mean = float(np.mean(weth_values)) if len(weth_values) else np.nan
                difference = stable_mean - weth_mean
                test_statistic = np.nan
                p_value = np.nan
            rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_contrast",
                    "comparison": "stable_minus_WETH",
                    "outcome": outcome,
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": int(supply_week_offset),
                    "stable_events": int(len(stable_values)),
                    "WETH_events": int(len(weth_values)),
                    "stable_mean": stable_mean,
                    "WETH_mean": weth_mean,
                    "difference": difference,
                    "welch_t": test_statistic,
                    "p_value": p_value,
                }
            )
    return pd.DataFrame(rows)


def fit_choice_models(choice_panel: pd.DataFrame) -> pd.DataFrame:
    """Fit the compact within-origin/event vehicle-specialization models."""

    rows: list[dict[str, object]] = []
    for (threshold, lookback, supply_week_offset), sample in choice_panel.groupby(
        ["material_tvl_usd", "lookback_days", "supply_week_offset"], sort=True
    ):
        for model_id, predictor in (
            ("m1_prior_vehicle_network_indicator", "prior_same_vehicle_any"),
            (
                "m2_log_prior_vehicle_network_endpoints",
                "log1p_prior_distinct_endpoints",
            ),
        ):
            work = sample[
                [
                    "is_actual_vehicle",
                    predictor,
                    "event_origin_id",
                    "candidate_quarter_id",
                    "pool",
                    "origin",
                ]
            ].dropna()
            within = absorb_fixed_effects(
                work[["is_actual_vehicle", predictor]],
                work["event_origin_id"],
                work["candidate_quarter_id"],
            )
            fit = ols_clustered(
                within["is_actual_vehicle"],
                within[[predictor]],
                work["pool"],
                add_constant=False,
                absorbed_groups=(
                    work["event_origin_id"],
                    work["candidate_quarter_id"],
                ),
                additional_clusters=(work["origin"],),
                min_observations=100,
                min_clusters=30,
            )
            pool_clusters, origin_clusters = fit.cluster_counts
            rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_model",
                    "model_id": model_id,
                    "predictor": predictor,
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": int(supply_week_offset),
                    "coefficient": float(fit.beta[0]),
                    "standard_error": float(fit.standard_errors[0]),
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "observations": int(fit.n_observations),
                    "event_clusters": int(pool_clusters),
                    "pool_clusters": int(pool_clusters),
                    "transaction_origin_clusters": int(origin_clusters),
                    "inference": "two_way_pool_and_transaction_origin_clustered",
                    "event_origin_fixed_effects": int(work["event_origin_id"].nunique()),
                    "candidate_quarter_fixed_effects": int(
                        work["candidate_quarter_id"].nunique()
                    ),
                    "outcome_mean": float(work["is_actual_vehicle"].mean()),
                    "interpretation_boundary": (
                        "association between prior outside-endpoint vehicle-network "
                        "experience and the vehicle identity of a focal pool supplied; "
                        "the pool opportunity set is not a provider choice set"
                    ),
                }
            )
        stable_choice = sample.loc[
            sample["vehicle_type"].eq("stable")
            & sample["history_candidate_address"].isin(USD_STABLES)
        ]
        for model_id, predictor in (
            (
                "m3_stable_spoke_prior_same_token_core_indicator",
                "prior_stable_core_any",
            ),
            (
                "m4_stable_spoke_log_prior_same_token_core_pools",
                "log1p_prior_stable_core_pools",
            ),
        ):
            work = stable_choice[
                [
                    "is_actual_vehicle",
                    predictor,
                    "event_origin_id",
                    "candidate_quarter_id",
                    "pool",
                    "origin",
                ]
            ].dropna()
            within = absorb_fixed_effects(
                work[["is_actual_vehicle", predictor]],
                work["event_origin_id"],
                work["candidate_quarter_id"],
            )
            fit = ols_clustered(
                within["is_actual_vehicle"],
                within[[predictor]],
                work["pool"],
                add_constant=False,
                absorbed_groups=(
                    work["event_origin_id"],
                    work["candidate_quarter_id"],
                ),
                additional_clusters=(work["origin"],),
                min_observations=100,
                min_clusters=30,
            )
            pool_clusters, origin_clusters = fit.cluster_counts
            rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_model",
                    "model_id": model_id,
                    "predictor": predictor,
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": int(supply_week_offset),
                    "coefficient": float(fit.beta[0]),
                    "standard_error": float(fit.standard_errors[0]),
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "observations": int(fit.n_observations),
                    "event_clusters": int(pool_clusters),
                    "pool_clusters": int(pool_clusters),
                    "transaction_origin_clusters": int(origin_clusters),
                    "inference": "two_way_pool_and_transaction_origin_clustered",
                    "event_origin_fixed_effects": int(
                        work["event_origin_id"].nunique()
                    ),
                    "candidate_quarter_fixed_effects": int(
                        work["candidate_quarter_id"].nunique()
                    ),
                    "outcome_mean": float(work["is_actual_vehicle"].mean()),
                    "interpretation_boundary": (
                        "token-specific stable-core experience before supplying a "
                        "new stable spoke; transaction origin is not beneficial owner"
                    ),
                }
            )
    models = pd.DataFrame(rows)
    primary = (
        models["material_tvl_usd"].eq(MAIN_MATERIAL_TVL_USD)
        & models["lookback_days"].eq(90)
        & models["supply_week_offset"].eq(0)
        & models["model_id"].isin(PRIMARY_MODEL_IDS)
    )
    if int(primary.sum()) != len(PRIMARY_MODEL_IDS) or set(
        models.loc[primary, "model_id"]
    ) != PRIMARY_MODEL_IDS:
        raise ValueError("declared V3 provider-specialization primary family is incomplete")
    models["specification_role"] = np.where(primary, "primary", "sensitivity")
    models["family_id"] = np.where(primary, PRIMARY_FAMILY_ID, "sensitivity")
    models["family_size"] = np.where(primary, len(PRIMARY_MODEL_IDS), np.nan)
    models["holm_adjusted_p_value"] = np.nan
    models.loc[primary, "holm_adjusted_p_value"] = holm_adjusted_pvalues(
        models.loc[primary, "p_value"]
    )
    models["venue_scope"] = VENUE_SCOPE
    models["vehicle_scope"] = VEHICLE_SCOPE
    return models


def run(
    *,
    origin_path: Path = ORIGIN_INPUT,
    fee_path: Path = FEE_INPUT,
    event_output: Path = EVENT_OUTPUT,
    summary_output: Path = SUMMARY_OUTPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    for path in (origin_path, fee_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    thresholds = (MAIN_MATERIAL_TVL_USD, *SENSITIVITY_TVL_USD)
    event_frames: list[pd.DataFrame] = []
    choice_frames: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    main_events: pd.DataFrame | None = None
    for threshold in thresholds:
        first_events = first_material_pool_events(
            fee_path,
            material_tvl_usd=threshold,
        )
        if threshold == MAIN_MATERIAL_TVL_USD:
            main_events = first_events
        for lookback in LOOKBACK_DAYS:
            choice, support = build_specialization_choice_panel(
                origin_path,
                first_events,
                lookback_days=lookback,
                supply_week_offset=0,
            )
            choice_frames.append(choice)
            event_frames.append(event_level_summary(choice))
            support_rows.append(
                {
                    "record_type": "v3_lp_provider_specialization_support",
                    "material_tvl_usd": float(threshold),
                    "lookback_days": int(lookback),
                    "supply_week_offset": 0,
                    **support,
                    "history_exclusion": (
                        "strictly before event week; excludes focal pool and all "
                        "pools paired with the focal endpoint"
                    ),
                    "identity_rule": (
                        "decoded transaction origin is a participation proxy, not a "
                        "wallet-owner or beneficial-owner identity"
                    ),
                    "venue_scope": VENUE_SCOPE,
                    "vehicle_scope": VEHICLE_SCOPE,
                }
            )
    if main_events is None:
        raise RuntimeError("main V3 first-material event set was not built")
    next_week_choice, next_week_support = build_specialization_choice_panel(
        origin_path,
        main_events,
        lookback_days=90,
        supply_week_offset=1,
    )
    choice_frames.append(next_week_choice)
    event_frames.append(event_level_summary(next_week_choice))
    support_rows.append(
        {
            "record_type": "v3_lp_provider_specialization_support",
            "material_tvl_usd": MAIN_MATERIAL_TVL_USD,
            "lookback_days": 90,
            "supply_week_offset": 1,
            **next_week_support,
            "history_exclusion": (
                "strictly before supply week; excludes focal pool and all pools "
                "paired with the focal endpoint"
            ),
            "identity_rule": (
                "decoded transaction origin is a participation proxy, not a "
                "wallet-owner or beneficial-owner identity"
            ),
            "venue_scope": VENUE_SCOPE,
            "vehicle_scope": VEHICLE_SCOPE,
        }
    )
    event_panel = pd.concat(event_frames, ignore_index=True)
    choice_panel = pd.concat(choice_frames, ignore_index=True)
    summaries = summarize_events(event_panel)
    models = fit_choice_models(choice_panel)
    event_panel["venue_scope"] = VENUE_SCOPE
    event_panel["vehicle_scope"] = VEHICLE_SCOPE
    summaries["venue_scope"] = VENUE_SCOPE
    summaries["vehicle_scope"] = VEHICLE_SCOPE
    write_panel(
        event_panel,
        event_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        summaries,
        summary_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        models,
        model_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        pd.DataFrame(support_rows),
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(event_panel):,} V3 focal pool-week rows and "
        f"{len(models):,} specialization estimates"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-panel", type=Path, default=ORIGIN_INPUT)
    parser.add_argument("--fee-panel", type=Path, default=FEE_INPUT)
    parser.add_argument("--event-output", type=Path, default=EVENT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        origin_path=args.origin_panel,
        fee_path=args.fee_panel,
        event_output=args.event_output,
        summary_output=args.summary_output,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
