#!/usr/bin/env python3
"""Locate the V3 stable-facing LP-supply rotation in pool age and origin history.

The retained sample matches the V3 transaction-origin decomposition: Uniswap V3
spokes with exactly one WETH, DAI, USDC, or USDT side and a nonvehicle endpoint.
For 2024 H1 and 2026 H1, the analysis reports where additions occur over a
pool's observed lifetime and whether the supplying transaction origin is a
one-day/one-pool proxy, a repeated proxy in one pool, or a multipool proxy.

Pool age begins on the first date observed in the retained V3 pool-day panel;
it is a pool-formation measure, not a token-issuance date.  The follow-up panel
uses pools first observed early enough in each endpoint period to give both
years the same 30- or 90-day window.  Activity at a horizon means at least one
pool-day observation in the 15-day window beginning at that horizon.  Material
activity additionally requires TVL of at least $50,000.  Post-launch LP supply
is candidate-side add-only minus remove-only flow after days 0--7.

Decoded transaction origin remains a participation proxy.  The output cannot
identify a beneficial owner, project treasury, token issuer, or incentive
sponsor and therefore cannot by itself label a pool as an IDO or rug pull.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit


ORIGIN_INPUT = DATA_DIR / "processed/v3_lp_add_origin_pool_daily.parquet"
FLOW_INPUT = DATA_DIR / "processed/v3_lp_flow_pool_daily.parquet"
POOL_DAY_INPUT = DATA_DIR / "processed/v3_pool_day_fees.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_launch_supply.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_launch_supply_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = (WETH, DAI, USDC, USDT)

BASELINE_PERIOD = "2024H1"
COMPARISON_PERIOD = "2026H1"
PERIODS = {
    BASELINE_PERIOD: (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-07-01")),
    COMPARISON_PERIOD: (
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-07-01"),
    ),
}
POOL_AGE_BINS = (
    ("0-7", 0, 7),
    ("8-30", 8, 30),
    ("31-90", 31, 90),
    (">90", 91, None),
)
FOLLOWUP_HORIZONS = (30, 90)
FOLLOWUP_ACTIVITY_WINDOW_DAYS = 15
LAUNCH_WINDOW_END_DAY = 7
MATERIAL_TVL_USD = 50_000.0

CODE_SOURCES = ["scripts/analyze/run_v3_lp_launch_supply.py"]
INPUTS = [
    "data/processed/v3_lp_add_origin_pool_daily.parquet",
    "data/processed/v3_lp_flow_pool_daily.parquet",
    "data/processed/v3_pool_day_fees.parquet",
]

ORIGIN_REQUIRED_COLUMNS = {
    "origin_date",
    "pool",
    "origin",
    "candidate_address",
    "paired_token_address",
    "v3_add_action_events",
    "v3_add_action_transactions",
    "v3_add_flow_usd_screened",
}
FLOW_REQUIRED_COLUMNS = {
    "origin_date",
    "pool",
    "candidate_address",
    "paired_token_address",
    "v3_add_only_lp_flow_usd_screened",
    "v3_remove_only_lp_flow_usd_screened",
    "v3_net_add_remove_only_lp_flow_usd_screened",
}
POOL_DAY_REQUIRED_COLUMNS = {"origin_date", "pool", "tvl_usd"}


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _candidate_values() -> str:
    return ",".join(f"'{address}'" for address in CANDIDATES)


def _period_case(date_expression: str) -> str:
    return f"""
        CASE
            WHEN {date_expression} >= DATE '2024-01-01'
             AND {date_expression} < DATE '2024-07-01' THEN '{BASELINE_PERIOD}'
            WHEN {date_expression} >= DATE '2026-01-01'
             AND {date_expression} < DATE '2026-07-01' THEN '{COMPARISON_PERIOD}'
        END
    """


def _period_filter(date_expression: str) -> str:
    return f"""
        (({date_expression} >= DATE '2024-01-01'
          AND {date_expression} < DATE '2024-07-01')
         OR
         ({date_expression} >= DATE '2026-01-01'
          AND {date_expression} < DATE '2026-07-01'))
    """


def _pool_age_case(age_expression: str) -> str:
    return f"""
        CASE
            WHEN {age_expression} BETWEEN 0 AND 7 THEN '0-7'
            WHEN {age_expression} BETWEEN 8 AND 30 THEN '8-30'
            WHEN {age_expression} BETWEEN 31 AND 90 THEN '31-90'
            WHEN {age_expression} > 90 THEN '>90'
        END
    """


def _describe_columns(connection: duckdb.DuckDBPyConnection, path: Path) -> set[str]:
    schema = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')"
    ).fetchdf()
    return set(schema["column_name"].astype(str))


def _validate_inputs(
    connection: duckdb.DuckDBPyConnection,
    *,
    origin_path: Path,
    flow_path: Path,
    pool_day_path: Path,
) -> None:
    requirements = (
        (origin_path, ORIGIN_REQUIRED_COLUMNS, "V3 origin-addition"),
        (flow_path, FLOW_REQUIRED_COLUMNS, "V3 pool-flow"),
        (pool_day_path, POOL_DAY_REQUIRED_COLUMNS, "V3 pool-day"),
    )
    for path, required, label in requirements:
        if not path.is_file():
            raise FileNotFoundError(path)
        missing = sorted(required - _describe_columns(connection, path))
        if missing:
            raise ValueError(f"{label} input lacks columns: {missing}")


def _pool_inception_sql(pool_day_path: Path) -> str:
    return f"""
        SELECT
            lower(pool) AS pool,
            min(CAST(origin_date AS DATE)) AS first_observed_date,
            max(CAST(origin_date AS DATE)) AS last_observed_date
        FROM read_parquet('{_sql_path(pool_day_path)}')
        GROUP BY 1
    """


def pool_age_supply(
    connection: duckdb.DuckDBPyConnection,
    *,
    origin_path: Path,
    pool_day_path: Path,
) -> pd.DataFrame:
    """Aggregate H1 additions by vehicle side and observed pool age."""

    candidates = _candidate_values()
    date = "CAST(a.origin_date AS DATE)"
    age = f"date_diff('day', i.first_observed_date, {date})"
    query = f"""
    WITH inception AS ({_pool_inception_sql(pool_day_path)}),
    sample AS (
        SELECT
            {_period_case(date)} AS period,
            CASE WHEN lower(a.candidate_address) = '{WETH}'
                 THEN 'WETH' ELSE 'stable' END AS vehicle_type,
            {_pool_age_case(age)} AS pool_age_bin,
            lower(a.pool) AS pool,
            lower(a.origin) AS origin,
            a.v3_add_action_events::DOUBLE AS addition_action_events,
            a.v3_add_action_transactions::DOUBLE AS addition_transactions,
            a.v3_add_flow_usd_screened::DOUBLE
                AS screened_candidate_side_flow_usd
        FROM read_parquet('{_sql_path(origin_path)}') a
        JOIN inception i ON lower(a.pool) = i.pool
        WHERE {_period_filter(date)}
          AND lower(a.candidate_address) IN ({candidates})
          AND lower(a.paired_token_address) NOT IN ({candidates})
          AND a.origin <> ''
    ), aggregated AS (
        SELECT
            period,
            vehicle_type,
            pool_age_bin,
            count(DISTINCT pool)::BIGINT AS pools,
            count(DISTINCT origin)::BIGINT AS transaction_origin_proxies,
            sum(addition_action_events)::DOUBLE AS addition_action_events,
            sum(addition_transactions)::DOUBLE AS addition_transactions,
            sum(screened_candidate_side_flow_usd)::DOUBLE
                AS screened_candidate_side_flow_usd
        FROM sample
        GROUP BY 1,2,3
    )
    SELECT
        'v3_lp_supply_by_pool_age' AS record_type,
        a.*,
        a.addition_action_events
            / sum(a.addition_action_events) OVER (PARTITION BY a.period, a.vehicle_type)
            AS pool_age_share_of_vehicle_actions,
        a.screened_candidate_side_flow_usd
            / nullif(sum(a.screened_candidate_side_flow_usd)
                OVER (PARTITION BY a.period, a.vehicle_type), 0)
            AS pool_age_share_of_vehicle_flow,
        a.addition_action_events
            / sum(a.addition_action_events) OVER (PARTITION BY a.period, a.pool_age_bin)
            AS vehicle_share_of_age_bin_actions,
        a.screened_candidate_side_flow_usd
            / nullif(sum(a.screened_candidate_side_flow_usd)
                OVER (PARTITION BY a.period, a.pool_age_bin), 0)
            AS vehicle_share_of_age_bin_flow,
        'days since first retained V3 pool-day' AS pool_age_definition,
        'decoded transaction origin is a participation proxy' AS origin_identity_rule,
        'screened candidate-token-side USD value' AS flow_measure
    FROM aggregated a
    ORDER BY
        period,
        CASE vehicle_type WHEN 'WETH' THEN 1 ELSE 2 END,
        CASE pool_age_bin
            WHEN '0-7' THEN 1 WHEN '8-30' THEN 2
            WHEN '31-90' THEN 3 ELSE 4
        END
    """
    frame = connection.execute(query).fetchdf()
    if frame.empty:
        raise ValueError("V3 spoke additions produced no pool-age rows")
    return frame


def origin_persistence(
    connection: duckdb.DuckDBPyConnection,
    *,
    origin_path: Path,
) -> pd.DataFrame:
    """Characterize full-sample origin breadth for the two endpoint periods."""

    candidates = _candidate_values()
    date = "CAST(origin_date AS DATE)"
    query = f"""
    WITH all_spokes AS (
        SELECT
            {date} AS origin_date,
            lower(pool) AS pool,
            lower(origin) AS origin,
            CASE WHEN lower(candidate_address) = '{WETH}'
                 THEN 'WETH' ELSE 'stable' END AS vehicle_type,
            v3_add_action_events::DOUBLE AS addition_action_events,
            v3_add_flow_usd_screened::DOUBLE AS screened_candidate_side_flow_usd
        FROM read_parquet('{_sql_path(origin_path)}')
        WHERE lower(candidate_address) IN ({candidates})
          AND lower(paired_token_address) NOT IN ({candidates})
          AND origin <> ''
    ), lifetime AS (
        SELECT
            origin,
            count(DISTINCT origin_date)::BIGINT AS lifetime_active_days,
            count(DISTINCT pool)::BIGINT AS lifetime_distinct_pools,
            date_diff('day', min(origin_date), max(origin_date))::BIGINT
                AS lifetime_span_days
        FROM all_spokes
        GROUP BY 1
    ), endpoint_periods AS (
        SELECT
            {_period_case('origin_date')} AS period,
            *
        FROM all_spokes
        WHERE {_period_filter('origin_date')}
    ), period_presence AS (
        SELECT origin, count(DISTINCT period)::BIGINT AS endpoint_periods_active
        FROM endpoint_periods
        GROUP BY 1
    ), origin_period_vehicle AS (
        SELECT
            e.period,
            e.vehicle_type,
            e.origin,
            l.lifetime_active_days,
            l.lifetime_distinct_pools,
            l.lifetime_span_days,
            p.endpoint_periods_active,
            sum(e.addition_action_events)::DOUBLE AS addition_action_events,
            sum(e.screened_candidate_side_flow_usd)::DOUBLE
                AS screened_candidate_side_flow_usd
        FROM endpoint_periods e
        JOIN lifetime l USING (origin)
        JOIN period_presence p USING (origin)
        GROUP BY 1,2,3,4,5,6,7
    ), classified AS (
        SELECT
            *,
            CASE WHEN endpoint_periods_active = 2
                 THEN 'continuing' ELSE 'period-specific' END
                AS endpoint_period_membership,
            CASE
                WHEN lifetime_active_days = 1 AND lifetime_distinct_pools = 1
                    THEN 'one-day/one-pool'
                WHEN lifetime_distinct_pools = 1
                    THEN 'repeat-day/one-pool'
                ELSE 'multi-pool'
            END AS origin_history_class
        FROM origin_period_vehicle
    ), aggregated AS (
        SELECT
            period,
            vehicle_type,
            endpoint_period_membership,
            origin_history_class,
            count(*)::BIGINT AS transaction_origin_proxies,
            sum(addition_action_events)::DOUBLE AS addition_action_events,
            sum(screened_candidate_side_flow_usd)::DOUBLE
                AS screened_candidate_side_flow_usd,
            median(lifetime_active_days)::DOUBLE AS median_lifetime_active_days,
            median(lifetime_distinct_pools)::DOUBLE AS median_lifetime_distinct_pools,
            median(lifetime_span_days)::DOUBLE AS median_lifetime_span_days
        FROM classified
        GROUP BY 1,2,3,4
    )
    SELECT
        'v3_lp_origin_history' AS record_type,
        a.*,
        a.transaction_origin_proxies
            / sum(a.transaction_origin_proxies)
                OVER (PARTITION BY a.period, a.vehicle_type)
            AS origin_proxy_share,
        a.addition_action_events
            / sum(a.addition_action_events)
                OVER (PARTITION BY a.period, a.vehicle_type)
            AS addition_action_share,
        a.screened_candidate_side_flow_usd
            / nullif(sum(a.screened_candidate_side_flow_usd)
                OVER (PARTITION BY a.period, a.vehicle_type), 0)
            AS screened_flow_share,
        'full retained V3 spoke sample' AS origin_history_window,
        'presence in both 2024 H1 and 2026 H1' AS continuing_definition,
        'decoded transaction origin is a participation proxy' AS identity_rule
    FROM aggregated a
    ORDER BY
        period,
        CASE vehicle_type WHEN 'WETH' THEN 1 ELSE 2 END,
        CASE endpoint_period_membership WHEN 'continuing' THEN 1 ELSE 2 END,
        origin_history_class
    """
    frame = connection.execute(query).fetchdf()
    if frame.empty:
        raise ValueError("V3 spoke additions produced no origin-history rows")
    return frame


def launch_followup(
    connection: duckdb.DuckDBPyConnection,
    *,
    origin_path: Path,
    flow_path: Path,
    pool_day_path: Path,
    horizon_days: int,
) -> pd.DataFrame:
    """Measure activity survival and LP flow after the first seven pool days."""

    if horizon_days not in FOLLOWUP_HORIZONS:
        raise ValueError(f"unsupported V3 launch follow-up horizon: {horizon_days}")
    candidates = _candidate_values()
    last_window_day = horizon_days + FOLLOWUP_ACTIVITY_WINDOW_DAYS - 1
    cohort_end_dates = {
        period: end - pd.Timedelta(days=last_window_day)
        for period, (_start, end) in PERIODS.items()
    }
    baseline_end = cohort_end_dates[BASELINE_PERIOD]
    comparison_end = cohort_end_dates[COMPARISON_PERIOD]
    query = f"""
    WITH inception AS ({_pool_inception_sql(pool_day_path)}),
    launch_supply AS (
        SELECT
            {_period_case('i.first_observed_date')} AS period,
            lower(a.pool) AS pool,
            lower(a.candidate_address) AS candidate_address,
            CASE WHEN lower(a.candidate_address) = '{WETH}'
                 THEN 'WETH' ELSE 'stable' END AS vehicle_type,
            i.first_observed_date,
            sum(a.v3_add_action_events)::DOUBLE AS launch_addition_actions,
            sum(a.v3_add_action_transactions)::DOUBLE
                AS launch_addition_transactions,
            sum(a.v3_add_flow_usd_screened)::DOUBLE
                AS launch_screened_candidate_side_flow_usd
        FROM read_parquet('{_sql_path(origin_path)}') a
        JOIN inception i ON lower(a.pool) = i.pool
        WHERE (
                (i.first_observed_date >= DATE '2024-01-01'
                 AND i.first_observed_date < DATE '{baseline_end:%Y-%m-%d}')
             OR (i.first_observed_date >= DATE '2026-01-01'
                 AND i.first_observed_date < DATE '{comparison_end:%Y-%m-%d}')
              )
          AND CAST(a.origin_date AS DATE) BETWEEN i.first_observed_date
                                               AND i.first_observed_date
                                                   + {LAUNCH_WINDOW_END_DAY}
          AND lower(a.candidate_address) IN ({candidates})
          AND lower(a.paired_token_address) NOT IN ({candidates})
          AND a.origin <> ''
        GROUP BY 1,2,3,4,5
    ), survival AS (
        SELECT
            l.*,
            max(CASE
                WHEN CAST(p.origin_date AS DATE)
                     BETWEEN l.first_observed_date + {horizon_days}
                         AND l.first_observed_date + {last_window_day}
                THEN 1 ELSE 0 END)::INTEGER AS active_at_horizon,
            max(CASE
                WHEN CAST(p.origin_date AS DATE)
                     BETWEEN l.first_observed_date + {horizon_days}
                         AND l.first_observed_date + {last_window_day}
                 AND p.tvl_usd >= {MATERIAL_TVL_USD}
                THEN 1 ELSE 0 END)::INTEGER AS material_at_horizon
        FROM launch_supply l
        LEFT JOIN read_parquet('{_sql_path(pool_day_path)}') p
          ON lower(p.pool) = l.pool
        GROUP BY ALL
    ), post_launch_flow AS (
        SELECT
            l.period,
            l.pool,
            l.candidate_address,
            coalesce(sum(f.v3_add_only_lp_flow_usd_screened) FILTER (
                WHERE CAST(f.origin_date AS DATE)
                          > l.first_observed_date + {LAUNCH_WINDOW_END_DAY}
                  AND CAST(f.origin_date AS DATE)
                          <= l.first_observed_date + {horizon_days}
            ), 0)::DOUBLE AS post_launch_add_only_flow_usd,
            coalesce(sum(f.v3_remove_only_lp_flow_usd_screened) FILTER (
                WHERE CAST(f.origin_date AS DATE)
                          > l.first_observed_date + {LAUNCH_WINDOW_END_DAY}
                  AND CAST(f.origin_date AS DATE)
                          <= l.first_observed_date + {horizon_days}
            ), 0)::DOUBLE AS post_launch_remove_only_flow_usd,
            coalesce(sum(f.v3_net_add_remove_only_lp_flow_usd_screened) FILTER (
                WHERE CAST(f.origin_date AS DATE)
                          > l.first_observed_date + {LAUNCH_WINDOW_END_DAY}
                  AND CAST(f.origin_date AS DATE)
                          <= l.first_observed_date + {horizon_days}
            ), 0)::DOUBLE AS post_launch_net_flow_usd
        FROM launch_supply l
        LEFT JOIN read_parquet('{_sql_path(flow_path)}') f
          ON lower(f.pool) = l.pool
         AND lower(f.candidate_address) = l.candidate_address
        GROUP BY 1,2,3
    ), pool_level AS (
        SELECT s.*, f.* EXCLUDE (period, pool, candidate_address)
        FROM survival s
        LEFT JOIN post_launch_flow f USING (period, pool, candidate_address)
    )
    SELECT
        'v3_lp_launch_followup' AS record_type,
        period,
        vehicle_type,
        {horizon_days}::INTEGER AS horizon_days,
        {FOLLOWUP_ACTIVITY_WINDOW_DAYS}::INTEGER AS activity_window_days,
        count(*)::BIGINT AS launch_pools,
        sum(launch_addition_actions)::DOUBLE AS launch_addition_actions,
        sum(launch_addition_transactions)::DOUBLE AS launch_addition_transactions,
        sum(launch_screened_candidate_side_flow_usd)::DOUBLE
            AS launch_screened_candidate_side_flow_usd,
        avg(active_at_horizon)::DOUBLE AS active_pool_share,
        sum(launch_addition_actions * active_at_horizon)
            / sum(launch_addition_actions) AS action_weighted_active_pool_share,
        sum(launch_screened_candidate_side_flow_usd * active_at_horizon)
            / nullif(sum(launch_screened_candidate_side_flow_usd), 0)
            AS flow_weighted_active_pool_share,
        avg(material_at_horizon)::DOUBLE AS material_pool_share,
        sum(launch_addition_actions * material_at_horizon)
            / sum(launch_addition_actions) AS action_weighted_material_pool_share,
        sum(launch_screened_candidate_side_flow_usd * material_at_horizon)
            / nullif(sum(launch_screened_candidate_side_flow_usd), 0)
            AS flow_weighted_material_pool_share,
        sum(post_launch_add_only_flow_usd)::DOUBLE AS post_launch_add_only_flow_usd,
        sum(post_launch_remove_only_flow_usd)::DOUBLE
            AS post_launch_remove_only_flow_usd,
        sum(post_launch_net_flow_usd)::DOUBLE AS post_launch_net_flow_usd,
        sum(post_launch_net_flow_usd)
            / nullif(sum(launch_screened_candidate_side_flow_usd), 0)
            AS post_launch_net_to_launch_flow,
        avg((post_launch_net_flow_usd < 0)::INTEGER)::DOUBLE
            AS negative_post_launch_net_pool_share,
        median(post_launch_net_flow_usd)::DOUBLE AS median_pool_post_launch_net_flow_usd,
        CASE period
            WHEN '{BASELINE_PERIOD}' THEN DATE '{baseline_end:%Y-%m-%d}'
            ELSE DATE '{comparison_end:%Y-%m-%d}'
        END AS cohort_end_exclusive,
        'pool first observed in endpoint period; additions on pool days 0-7'
            AS launch_pool_definition,
        'any retained pool-day in the 15-day window beginning at the horizon'
            AS active_pool_definition,
        'active definition plus TVL at least $50,000' AS material_pool_definition,
        'candidate-side add-only minus remove-only USD flow after pool day 7'
            AS post_launch_flow_definition
    FROM pool_level
    GROUP BY 1,2,3
    ORDER BY period, CASE vehicle_type WHEN 'WETH' THEN 1 ELSE 2 END
    """
    frame = connection.execute(query).fetchdf()
    if frame.empty:
        raise ValueError(f"V3 spoke additions produced no {horizon_days}-day cohorts")
    return frame


def analysis_support(
    connection: duckdb.DuckDBPyConnection,
    *,
    origin_path: Path,
    pool_day_path: Path,
) -> pd.DataFrame:
    """Report input coverage and pool-inception join integrity."""

    candidates = _candidate_values()
    query = f"""
    WITH inception AS ({_pool_inception_sql(pool_day_path)}),
    scoped AS (
        SELECT
            lower(a.pool) AS pool,
            CAST(a.origin_date AS DATE) AS origin_date,
            i.first_observed_date
        FROM read_parquet('{_sql_path(origin_path)}') a
        LEFT JOIN inception i ON lower(a.pool) = i.pool
        WHERE lower(a.candidate_address) IN ({candidates})
          AND lower(a.paired_token_address) NOT IN ({candidates})
          AND a.origin <> ''
    )
    SELECT
        'v3_lp_launch_supply_support' AS record_type,
        count(*)::BIGINT AS full_sample_origin_pool_days,
        count(DISTINCT pool)::BIGINT AS full_sample_spoke_pools,
        min(origin_date) AS first_origin_date,
        max(origin_date) AS last_origin_date,
        count(*) FILTER (WHERE first_observed_date IS NULL)::BIGINT
            AS missing_pool_inception_rows,
        count(*) FILTER (
            WHERE first_observed_date IS NOT NULL
              AND origin_date < first_observed_date
        )::BIGINT AS negative_pool_age_rows,
        'Uniswap V3 spokes with exactly one WETH/DAI/USDC/USDT side'
            AS pool_scope,
        'decoded transaction origin is a participation proxy, not beneficial owner'
            AS identity_rule,
        'pool age is not a token issuance or project launch date' AS interpretation_limit
    FROM scoped
    """
    support = connection.execute(query).fetchdf()
    if int(support.iloc[0]["missing_pool_inception_rows"]) != 0:
        raise ValueError("V3 origin additions lack pool-day inception matches")
    if int(support.iloc[0]["negative_pool_age_rows"]) != 0:
        raise ValueError("V3 origin additions precede their observed pool inception")
    return support


def build_outputs(
    *,
    origin_path: Path,
    flow_path: Path,
    pool_day_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return analysis records and integrity support from the three retained panels."""

    connection = duckdb.connect()
    try:
        _validate_inputs(
            connection,
            origin_path=origin_path,
            flow_path=flow_path,
            pool_day_path=pool_day_path,
        )
        age = pool_age_supply(
            connection,
            origin_path=origin_path,
            pool_day_path=pool_day_path,
        )
        origins = origin_persistence(connection, origin_path=origin_path)
        followups = [
            launch_followup(
                connection,
                origin_path=origin_path,
                flow_path=flow_path,
                pool_day_path=pool_day_path,
                horizon_days=horizon,
            )
            for horizon in FOLLOWUP_HORIZONS
        ]
        support = analysis_support(
            connection,
            origin_path=origin_path,
            pool_day_path=pool_day_path,
        )
    finally:
        connection.close()
    output = pd.concat([age, origins, *followups], ignore_index=True, sort=False)
    numeric = output.select_dtypes(include=[np.number])
    if not np.isfinite(numeric.to_numpy(dtype=float, na_value=0.0)).all():
        raise ValueError("V3 launch-supply output contains nonfinite numeric values")
    return output, support


def run(
    *,
    origin_path: Path = ORIGIN_INPUT,
    flow_path: Path = FLOW_INPUT,
    pool_day_path: Path = POOL_DAY_INPUT,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    output, support = build_outputs(
        origin_path=origin_path,
        flow_path=flow_path,
        pool_day_path=pool_day_path,
    )
    write_exhibit(output, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(output):,} V3 launch-supply records and "
        f"{len(support):,} support row"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-panel", type=Path, default=ORIGIN_INPUT)
    parser.add_argument("--flow-panel", type=Path, default=FLOW_INPUT)
    parser.add_argument("--pool-day-panel", type=Path, default=POOL_DAY_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        origin_path=args.origin_panel,
        flow_path=args.flow_panel,
        pool_day_path=args.pool_day_panel,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
