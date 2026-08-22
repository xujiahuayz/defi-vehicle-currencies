#!/usr/bin/env python3
"""Relate preweek relative bridge capital to first stablecoin route use.

The analysis builds a calendar-week risk set for ordered endpoint pairs that
recently routed through WETH and have not yet routed through DAI, USDC, or
USDT.  It retains zero-stable-depth weeks and pairs that never adopt.  Capital
is the full-range Uniswap v2 plus SushiSwap v2 reserve value available before
the week begins.  No capital crossing or future adoption defines eligibility.

The linear probability models separate any positive stable bridge from the
depth gradient among positive-support weeks.  They absorb ordered-pair and
calendar-week effects, control for pair age and prior WETH activity, and
cluster by pair and week.  Next-week capital is reverse-association evidence:
it can respond to adoption and therefore cannot identify a forward effect.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.bridge_adoption_risk_set import (
    adoption_support_rows,
    estimate_adoption_models,
    prepare_adoption_risk_panel,
)
from ddvc.paths import OUTPUT_DIR, PRIMARY_REPO_ROOT
from ddvc.tables import write_exhibit


CHOICES_INPUT = PRIMARY_REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
POOL_CAPITAL_INPUT = PRIMARY_REPO_ROOT / "data/processed/pool_capital_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_adoption_risk_set.jsonl"
CAPITAL_STATUS = "exact_state_prior_calendar"
MIN_PRIOR_NATIVE_ROUTES = 10
MIN_PRIOR_NATIVE_ACTIVE_DAYS = 3
STRICT_MIN_PRIOR_NATIVE_ROUTES = 50
STRICT_MIN_PRIOR_NATIVE_ACTIVE_DAYS = 5
PRIOR_ACTIVITY_WEEKS = 4


RISK_QUERY = r"""
WITH stable_candidates(candidate_symbol, candidate_address) AS (
  VALUES
    ('DAI','0x6b175474e89094c44da98b954eedeac495271d0f'),
    ('USDC','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
    ('USDT','0xdac17f958d2ee523a2206206994597c13d831ec7')
),
vehicle_candidates(vehicle_type, vehicle_address) AS (
    SELECT 'stable', candidate_address FROM stable_candidates
    UNION ALL
    SELECT 'native', '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
),
candidate_choice AS (
    SELECT
        CAST(date AS DATE) AS origin_date,
        lower(src) AS src,
        lower(tgt) AS tgt,
        candidate_type,
        sum(route_count)::DOUBLE AS route_count
    FROM read_parquet(?)
    WHERE candidate_type IN ('native', 'stable')
      AND route_count > 0
    GROUP BY 1, 2, 3, 4
),
choice_daily AS (
    SELECT
        origin_date,
        src,
        tgt,
        sum(CASE WHEN candidate_type = 'native' THEN route_count ELSE 0 END)::DOUBLE
            AS native_routes,
        sum(CASE WHEN candidate_type = 'stable' THEN route_count ELSE 0 END)::DOUBLE
            AS stable_routes
    FROM candidate_choice
    GROUP BY 1, 2, 3
),
choice_bounds AS (
    SELECT
        min(origin_date) AS first_date,
        max(origin_date) AS last_date,
        date_trunc('week', max(origin_date))::DATE - INTERVAL 7 DAY
            AS last_complete_week
    FROM choice_daily
),
pair_timing AS (
    SELECT
        src,
        tgt,
        min(origin_date) FILTER (WHERE native_routes > 0) AS first_native_date,
        min(origin_date) FILTER (WHERE stable_routes > 0) AS first_stable_date
    FROM choice_daily
    GROUP BY 1, 2
),
eligible_pairs AS (
    SELECT
        p.src,
        p.tgt,
        p.src || '|' || p.tgt AS pair_id,
        p.first_native_date,
        p.first_stable_date
    FROM pair_timing p
    WHERE p.first_native_date IS NOT NULL
      AND (p.first_stable_date IS NULL OR p.first_stable_date > p.first_native_date)
      AND p.src <> p.tgt
      AND p.src NOT IN (SELECT vehicle_address FROM vehicle_candidates)
      AND p.tgt NOT IN (SELECT vehicle_address FROM vehicle_candidates)
),
native_week AS (
    SELECT
        c.src,
        c.tgt,
        date_trunc('week', c.origin_date)::DATE AS native_week_start,
        sum(c.native_routes)::DOUBLE AS native_routes,
        count(DISTINCT c.origin_date) FILTER (WHERE c.native_routes > 0)::INTEGER
            AS native_active_days
    FROM choice_daily c
    JOIN eligible_pairs p USING(src, tgt)
    WHERE c.native_routes > 0
    GROUP BY 1, 2, 3
),
risk_contributions AS (
    SELECT
        n.src,
        n.tgt,
        n.native_week_start + offsets.week_offset * INTERVAL 7 DAY AS week_start,
        n.native_routes,
        n.native_active_days
    FROM native_week n
    CROSS JOIN range(1, ?) AS offsets(week_offset)
),
risk_week_base AS (
    SELECT
        p.pair_id,
        p.src,
        p.tgt,
        p.first_native_date,
        p.first_stable_date,
        CAST(r.week_start AS DATE) AS week_start,
        sum(r.native_routes)::DOUBLE AS prior_native_routes,
        sum(r.native_active_days)::INTEGER AS prior_native_active_days
    FROM risk_contributions r
    JOIN eligible_pairs p USING(src, tgt)
    CROSS JOIN choice_bounds b
    WHERE r.week_start <= b.last_complete_week
      AND (
          p.first_stable_date IS NULL
          OR r.week_start <= date_trunc('week', p.first_stable_date)
      )
    GROUP BY 1, 2, 3, 4, 5, 6
    HAVING sum(r.native_routes) >= ?
       AND sum(r.native_active_days) >= ?
),
capital_dates AS (
    SELECT
        min(week_start) AS first_week,
        max(week_start) + INTERVAL 7 DAY AS last_lead_week
    FROM risk_week_base
),
risk_weeks AS (
    SELECT r.*
    FROM risk_week_base r
    CROSS JOIN capital_dates d
    WHERE r.week_start >= d.first_week
),
needed_pair_weeks AS (
    SELECT pair_id, src, tgt, week_start AS measure_week FROM risk_weeks
    UNION
    SELECT pair_id, src, tgt, week_start + INTERVAL 7 DAY AS measure_week
    FROM risk_weeks
),
vehicle_leg_week AS (
    SELECT
        strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE AS measure_week,
        v.vehicle_type,
        v.vehicle_address,
        CASE
            WHEN lower(p.token0_address) = v.vehicle_address
                THEN lower(p.token1_address)
            ELSE lower(p.token0_address)
        END AS other_address,
        sum(p.capital_usd_lagged)::DOUBLE AS leg_capital_usd
    FROM read_parquet(?) p
    JOIN vehicle_candidates v
      ON lower(p.token0_address) = v.vehicle_address
      OR lower(p.token1_address) = v.vehicle_address
    CROSS JOIN capital_dates d
    WHERE p.quantity_kind = 'deposited_capital'
      AND p.capital_validation_status = ?
      AND p.capital_usd_lagged > 0
      AND strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE
          BETWEEN d.first_week AND d.last_lead_week
      AND dayofweek(strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE) = 1
    GROUP BY 1, 2, 3, 4
),
stable_bridge_week AS (
    SELECT
        n.pair_id,
        n.measure_week,
        max(least(l1.leg_capital_usd, l2.leg_capital_usd))::DOUBLE
            AS stable_weak_leg_usd
    FROM needed_pair_weeks n
    JOIN vehicle_leg_week l1
      ON l1.measure_week = n.measure_week
     AND l1.vehicle_type = 'stable'
     AND l1.other_address = n.src
    JOIN vehicle_leg_week l2
      ON l2.measure_week = n.measure_week
     AND l2.vehicle_type = 'stable'
     AND l2.vehicle_address = l1.vehicle_address
     AND l2.other_address = n.tgt
    GROUP BY 1, 2
),
weth_bridge_week AS (
    SELECT
        n.pair_id,
        n.measure_week,
        least(l1.leg_capital_usd, l2.leg_capital_usd)::DOUBLE
            AS weth_weak_leg_usd
    FROM needed_pair_weeks n
    JOIN vehicle_leg_week l1
      ON l1.measure_week = n.measure_week
     AND l1.vehicle_type = 'native'
     AND l1.other_address = n.src
    JOIN vehicle_leg_week l2
      ON l2.measure_week = n.measure_week
     AND l2.vehicle_type = 'native'
     AND l2.other_address = n.tgt
),
bridge_week AS (
    SELECT
        n.pair_id,
        n.measure_week,
        coalesce(s.stable_weak_leg_usd, 0)::DOUBLE AS stable_weak_leg_usd,
        w.weth_weak_leg_usd
    FROM needed_pair_weeks n
    LEFT JOIN stable_bridge_week s USING(pair_id, measure_week)
    LEFT JOIN weth_bridge_week w USING(pair_id, measure_week)
)
SELECT
    r.pair_id,
    r.src,
    r.tgt,
    r.week_start,
    r.first_native_date,
    r.first_stable_date,
    r.prior_native_routes,
    r.prior_native_active_days,
    current_depth.stable_weak_leg_usd,
    current_depth.weth_weak_leg_usd,
    CASE
        WHEN lead_depth.weth_weak_leg_usd IS NULL THEN NULL
        ELSE lead_depth.stable_weak_leg_usd
    END AS lead_stable_weak_leg_usd,
    lead_depth.weth_weak_leg_usd AS lead_weth_weak_leg_usd
FROM risk_weeks r
JOIN bridge_week current_depth
  ON current_depth.pair_id = r.pair_id
 AND current_depth.measure_week = r.week_start
LEFT JOIN bridge_week lead_depth
  ON lead_depth.pair_id = r.pair_id
 AND lead_depth.measure_week = r.week_start + INTERVAL 7 DAY
WHERE current_depth.weth_weak_leg_usd > 0
ORDER BY r.pair_id, r.week_start
"""


def load_risk_panel(
    *,
    choices_path: Path,
    pool_capital_path: Path,
    capital_status: str = CAPITAL_STATUS,
    min_prior_native_routes: int = MIN_PRIOR_NATIVE_ROUTES,
    min_prior_native_active_days: int = MIN_PRIOR_NATIVE_ACTIVE_DAYS,
    prior_activity_weeks: int = PRIOR_ACTIVITY_WEEKS,
) -> pd.DataFrame:
    """Construct the risk set without conditioning on a capital crossing."""

    if prior_activity_weeks < 1:
        raise ValueError("prior activity window must contain at least one week")
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=6")
        connection.execute("PRAGMA preserve_insertion_order=false")
        frame = connection.execute(
            RISK_QUERY,
            [
                str(choices_path),
                int(prior_activity_weeks + 1),
                int(min_prior_native_routes),
                int(min_prior_native_active_days),
                str(pool_capital_path),
                capital_status,
            ],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("bridge-adoption risk query returned no pair-weeks")
    return prepare_adoption_risk_panel(frame)


def run(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    output_path: Path = RESULT_OUTPUT,
    min_prior_native_routes: int = MIN_PRIOR_NATIVE_ROUTES,
    min_prior_native_active_days: int = MIN_PRIOR_NATIVE_ACTIVE_DAYS,
    strict_min_prior_native_routes: int = STRICT_MIN_PRIOR_NATIVE_ROUTES,
    strict_min_prior_native_active_days: int = STRICT_MIN_PRIOR_NATIVE_ACTIVE_DAYS,
    include_strict: bool = True,
) -> int:
    sample_specs = [
        (
            "primary_10_routes_3_days",
            min_prior_native_routes,
            min_prior_native_active_days,
        )
    ]
    if include_strict:
        sample_specs.append(
            (
                "strict_50_routes_5_days",
                strict_min_prior_native_routes,
                strict_min_prior_native_active_days,
            )
        )
    blocks: list[pd.DataFrame] = []
    for sample_id, minimum_routes, minimum_days in sample_specs:
        panel = load_risk_panel(
            choices_path=choices_path,
            pool_capital_path=pool_capital_path,
            min_prior_native_routes=minimum_routes,
            min_prior_native_active_days=minimum_days,
        )
        block = pd.concat(
            [
                adoption_support_rows(
                    panel,
                    min_prior_native_routes=minimum_routes,
                    min_prior_native_active_days=minimum_days,
                ),
                estimate_adoption_models(panel),
            ],
            ignore_index=True,
        )
        block.insert(0, "sample_id", sample_id)
        block.loc[
            block["record_type"].eq("bridge_adoption_risk_support"), "model_id"
        ] = f"{sample_id}_risk_set"
        blocks.append(block)
    results = pd.concat(blocks, ignore_index=True)
    write_exhibit(
        results,
        output_path,
        code_sources=[
            "scripts/analyze/run_bridge_adoption_risk_set.py",
            "src/ddvc/analysis/bridge_adoption_risk_set.py",
        ],
        inputs=[
            "data/processed/endpoint_candidate_choices.parquet",
            "data/processed/pool_capital_daily.parquet",
        ],
    )
    support = results[results["record_type"].eq("bridge_adoption_risk_support")]
    summaries = ", ".join(
        f"{row.sample_id}: {int(row.pair_weeks):,} pair-weeks/{int(row.pairs):,} pairs"
        for row in support.itertuples(index=False)
    )
    print(f"wrote {len(results):,} rows ({summaries})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument(
        "--min-prior-native-routes",
        type=int,
        default=MIN_PRIOR_NATIVE_ROUTES,
    )
    parser.add_argument(
        "--min-prior-native-active-days",
        type=int,
        default=MIN_PRIOR_NATIVE_ACTIVE_DAYS,
    )
    parser.add_argument(
        "--strict-min-prior-native-routes",
        type=int,
        default=STRICT_MIN_PRIOR_NATIVE_ROUTES,
    )
    parser.add_argument(
        "--strict-min-prior-native-active-days",
        type=int,
        default=STRICT_MIN_PRIOR_NATIVE_ACTIVE_DAYS,
    )
    parser.add_argument(
        "--primary-only",
        action="store_true",
        help="skip the stricter recent-activity sensitivity",
    )
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pool_capital_path=args.pool_capital,
        output_path=args.output,
        min_prior_native_routes=args.min_prior_native_routes,
        min_prior_native_active_days=args.min_prior_native_active_days,
        strict_min_prior_native_routes=args.strict_min_prior_native_routes,
        strict_min_prior_native_active_days=args.strict_min_prior_native_active_days,
        include_strict=not args.primary_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
