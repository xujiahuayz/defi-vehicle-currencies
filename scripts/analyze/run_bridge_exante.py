#!/usr/bin/env python3
"""Date bridge formation from lagged capital and measure later route use.

For each ordered endpoint pair that previously routed through WETH and has not
yet used a stablecoin route, the event is the first date on which DAI, USDC, or
USDT has at least USD 10,000 of prior-calendar deposited capital on both legs.
Neither later capital nor later route use enters the event date.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.bridge_exante import (
    adoption_and_retention_summaries,
    paired_share_change_regressions,
    prepare_exante_bridge_panel,
    relative_depth_regressions,
)
from ddvc.paths import OUTPUT_DIR, PRIMARY_REPO_ROOT
from ddvc.tables import write_exhibit


CHOICES_INPUT = PRIMARY_REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
POOL_CAPITAL_INPUT = PRIMARY_REPO_ROOT / "data/processed/pool_capital_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_exante.jsonl"
CAPITAL_STATUS = "exact_state_prior_calendar"
MIN_STABLE_WEAK_LEG_USD = 10_000.0
MIN_ACTIVE_DAYS = 3


EVENT_QUERY = r"""
WITH stable_candidates(candidate_symbol, candidate_address) AS (
  VALUES
    ('DAI','0x6b175474e89094c44da98b954eedeac495271d0f'),
    ('USDC','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
    ('USDT','0xdac17f958d2ee523a2206206994597c13d831ec7')
),
candidate_choice AS (
    SELECT
        CAST(date AS DATE) AS origin_date,
        lower(src) AS src,
        lower(tgt) AS tgt,
        integration_scope,
        lower(candidate_address) AS candidate_address,
        candidate_type,
        sum(route_count)::DOUBLE AS route_count,
        sum(coalesce(within_20pct_value_usd, 0))::DOUBLE AS route_value_usd
    FROM read_parquet(?)
    WHERE candidate_type IN ('native', 'stable')
    GROUP BY 1, 2, 3, 4, 5, 6
),
choice_daily AS (
    SELECT
        origin_date,
        src,
        tgt,
        integration_scope,
        sum(CASE WHEN candidate_type = 'native' THEN route_count ELSE 0 END)::DOUBLE
            AS native_routes,
        sum(CASE WHEN candidate_type = 'stable' THEN route_count ELSE 0 END)::DOUBLE
            AS stable_routes,
        sum(CASE WHEN candidate_type = 'native' THEN route_value_usd ELSE 0 END)::DOUBLE
            AS native_value_usd,
        sum(CASE WHEN candidate_type = 'stable' THEN route_value_usd ELSE 0 END)::DOUBLE
            AS stable_value_usd
    FROM candidate_choice
    GROUP BY 1, 2, 3, 4
),
choice_bounds AS (
    SELECT min(origin_date) AS first_date, max(origin_date) AS last_date
    FROM choice_daily
),
pair_scopes AS (
    SELECT
        src,
        tgt,
        integration_scope,
        min(origin_date) AS first_active_date,
        max(origin_date) AS last_active_date
    FROM choice_daily
    GROUP BY 1, 2, 3
    HAVING sum(native_routes) > 0
),
threshold_stable_leg_day AS (
    SELECT
        strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE AS support_date,
        s.candidate_symbol,
        s.candidate_address,
        CASE
            WHEN lower(p.token0_address) = s.candidate_address
                THEN lower(p.token1_address)
            ELSE lower(p.token0_address)
        END AS other_address,
        sum(p.capital_usd_lagged)::DOUBLE AS leg_capital_usd
    FROM read_parquet(?) p
    JOIN stable_candidates s
      ON lower(p.token0_address) = s.candidate_address
      OR lower(p.token1_address) = s.candidate_address
    WHERE p.quantity_kind = 'deposited_capital'
      AND p.capital_validation_status = ?
      AND p.capital_usd_lagged > 0
    GROUP BY 1, 2, 3, 4
    HAVING sum(p.capital_usd_lagged) >= ?
),
threshold_stable_bridge_day AS (
    SELECT
        p.src,
        p.tgt,
        p.integration_scope,
        l1.candidate_symbol,
        l1.candidate_address,
        l1.support_date,
        least(l1.leg_capital_usd, l2.leg_capital_usd)::DOUBLE
            AS stable_weak_leg_usd
    FROM pair_scopes p
    JOIN threshold_stable_leg_day l1
      ON l1.other_address = p.src
    JOIN threshold_stable_leg_day l2
      ON l2.support_date = l1.support_date
     AND l2.candidate_address = l1.candidate_address
     AND l2.other_address = p.tgt
),
weth_leg_day AS (
    SELECT
        strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS support_date,
        CASE
            WHEN lower(token0_address) =
                '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
                THEN lower(token1_address)
            ELSE lower(token0_address)
        END AS other_address,
        sum(capital_usd_lagged)::DOUBLE AS leg_capital_usd
    FROM read_parquet(?)
    WHERE quantity_kind = 'deposited_capital'
      AND capital_validation_status = ?
      AND capital_usd_lagged > 0
      AND (
          lower(token0_address) =
              '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
          OR lower(token1_address) =
              '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
      )
    GROUP BY 1, 2
),
first_event_date AS (
    SELECT
        q.src,
        q.tgt,
        q.integration_scope,
        min(q.support_date) AS event_date
    FROM threshold_stable_bridge_day q
    JOIN pair_scopes p USING(src, tgt, integration_scope)
    WHERE q.support_date > p.first_active_date
    GROUP BY 1, 2, 3
),
first_event_candidates AS (
    SELECT
        e.src,
        e.tgt,
        e.integration_scope,
        e.event_date,
        q.candidate_symbol,
        q.candidate_address,
        q.stable_weak_leg_usd
    FROM first_event_date e
    JOIN threshold_stable_bridge_day q
      ON q.src = e.src
     AND q.tgt = e.tgt
     AND q.integration_scope = e.integration_scope
     AND q.support_date = e.event_date
),
first_events AS (
    SELECT
        src,
        tgt,
        integration_scope,
        event_date,
        string_agg(candidate_symbol, ',' ORDER BY candidate_symbol)
            AS event_stablecoins,
        string_agg(candidate_address, ',' ORDER BY candidate_address)
            AS event_stablecoin_addresses,
        max(stable_weak_leg_usd)::DOUBLE AS event_stable_weak_leg_usd
    FROM first_event_candidates
    GROUP BY 1, 2, 3, 4
),
first_supported_route AS (
    SELECT
        e.src,
        e.tgt,
        e.integration_scope,
        e.event_date,
        min(c.origin_date) AS first_supported_stable_route_date
    FROM first_events e
    LEFT JOIN first_event_candidates f
      ON f.src = e.src
     AND f.tgt = e.tgt
     AND f.integration_scope = e.integration_scope
     AND f.event_date = e.event_date
    LEFT JOIN candidate_choice c
      ON c.src = e.src
     AND c.tgt = e.tgt
     AND c.integration_scope = e.integration_scope
     AND c.candidate_address = f.candidate_address
     AND c.origin_date >= e.event_date
     AND c.route_count > 0
    GROUP BY 1, 2, 3, 4
),
first_any_stable_route AS (
    SELECT
        src,
        tgt,
        integration_scope,
        min(origin_date) AS first_any_stable_route_date
    FROM choice_daily
    WHERE stable_routes > 0
    GROUP BY 1, 2, 3
),
event_support AS (
    SELECT
        e.*,
        r.first_supported_stable_route_date,
        a.first_any_stable_route_date,
        count(DISTINCT c.origin_date) FILTER (
            WHERE c.origin_date BETWEEN e.event_date - INTERVAL 30 DAY
                                    AND e.event_date - INTERVAL 1 DAY
        )::INTEGER AS pre_active_days,
        coalesce(sum(c.native_routes) FILTER (
            WHERE c.origin_date BETWEEN e.event_date - INTERVAL 30 DAY
                                    AND e.event_date - INTERVAL 1 DAY
        ), 0)::DOUBLE AS pre_native_routes,
        coalesce(sum(c.stable_routes) FILTER (
            WHERE c.origin_date BETWEEN e.event_date - INTERVAL 30 DAY
                                    AND e.event_date - INTERVAL 1 DAY
        ), 0)::DOUBLE AS pre_stable_routes,
        count(DISTINCT c.origin_date) FILTER (
            WHERE c.origin_date BETWEEN e.event_date
                                    AND e.event_date + INTERVAL 29 DAY
        )::INTEGER AS post30_active_days,
        count(DISTINCT c.origin_date) FILTER (
            WHERE c.origin_date BETWEEN e.event_date + INTERVAL 30 DAY
                                    AND e.event_date + INTERVAL 119 DAY
        )::INTEGER AS later_active_days
    FROM first_events e
    JOIN first_supported_route r USING(src, tgt, integration_scope, event_date)
    LEFT JOIN first_any_stable_route a USING(src, tgt, integration_scope)
    LEFT JOIN choice_daily c
      ON c.src = e.src
     AND c.tgt = e.tgt
     AND c.integration_scope = e.integration_scope
     AND c.origin_date BETWEEN e.event_date - INTERVAL 30 DAY
                           AND e.event_date + INTERVAL 119 DAY
    GROUP BY ALL
),
eligible_events AS (
    SELECT e.*
    FROM event_support e
    CROSS JOIN choice_bounds b
    WHERE e.event_date >= b.first_date + INTERVAL 30 DAY
      AND e.event_date <= b.last_date - INTERVAL 119 DAY
      AND e.pre_active_days >= ?
      AND e.pre_native_routes > 0
      AND e.pre_stable_routes = 0
      AND (
          e.first_any_stable_route_date IS NULL
          OR e.first_any_stable_route_date >= e.event_date
      )
      AND e.post30_active_days >= ?
      AND e.later_active_days >= ?
),
stable_leg_day AS (
    SELECT
        strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE AS support_date,
        s.candidate_symbol,
        s.candidate_address,
        CASE
            WHEN lower(p.token0_address) = s.candidate_address
                THEN lower(p.token1_address)
            ELSE lower(p.token0_address)
        END AS other_address,
        sum(p.capital_usd_lagged)::DOUBLE AS leg_capital_usd
    FROM read_parquet(?) p
    JOIN stable_candidates s
      ON lower(p.token0_address) = s.candidate_address
      OR lower(p.token1_address) = s.candidate_address
    WHERE p.quantity_kind = 'deposited_capital'
      AND p.capital_validation_status = ?
      AND p.capital_usd_lagged > 0
    GROUP BY 1, 2, 3, 4
),
event_stable_depth AS (
    SELECT
        e.src,
        e.tgt,
        e.integration_scope,
        e.event_date,
        l1.support_date,
        max(least(l1.leg_capital_usd, l2.leg_capital_usd))::DOUBLE
            AS stable_weak_leg_usd
    FROM eligible_events e
    JOIN first_event_candidates f
      ON f.src = e.src
     AND f.tgt = e.tgt
     AND f.integration_scope = e.integration_scope
     AND f.event_date = e.event_date
    JOIN stable_leg_day l1
      ON l1.candidate_address = f.candidate_address
     AND l1.other_address = e.src
     AND l1.support_date BETWEEN e.event_date - INTERVAL 30 DAY
                             AND e.event_date + INTERVAL 119 DAY
    JOIN stable_leg_day l2
      ON l2.candidate_address = l1.candidate_address
     AND l2.other_address = e.tgt
     AND l2.support_date = l1.support_date
    GROUP BY 1, 2, 3, 4, 5
),
event_weth_depth AS (
    SELECT
        e.src,
        e.tgt,
        e.integration_scope,
        e.event_date,
        l1.support_date,
        least(l1.leg_capital_usd, l2.leg_capital_usd)::DOUBLE
            AS weth_weak_leg_usd
    FROM eligible_events e
    JOIN weth_leg_day l1
      ON l1.other_address = e.src
     AND l1.support_date BETWEEN e.event_date - INTERVAL 30 DAY
                            AND e.event_date + INTERVAL 119 DAY
    JOIN weth_leg_day l2
      ON l2.support_date = l1.support_date
     AND l2.other_address = e.tgt
)
SELECT
    e.src || '|' || e.tgt || '|' || e.integration_scope AS event_id,
    e.src || '|' || e.tgt AS ordered_pair,
    e.src,
    e.tgt,
    e.integration_scope,
    e.event_date,
    c.origin_date,
    date_diff('day', e.event_date, c.origin_date)::INTEGER AS event_time,
    e.event_stablecoins,
    e.event_stablecoin_addresses,
    e.event_stable_weak_leg_usd,
    e.first_supported_stable_route_date,
    e.pre_active_days,
    e.post30_active_days,
    e.later_active_days,
    c.native_routes,
    c.stable_routes,
    c.native_value_usd,
    c.stable_value_usd,
    coalesce(d.stable_weak_leg_usd, 0)::DOUBLE
        AS stable_bridge_min_capital_usd,
    coalesce(w.weth_weak_leg_usd, 0)::DOUBLE
        AS native_bridge_min_capital_usd
FROM eligible_events e
JOIN choice_daily c
  ON c.src = e.src
 AND c.tgt = e.tgt
 AND c.integration_scope = e.integration_scope
 AND c.origin_date BETWEEN e.event_date - INTERVAL 30 DAY
                       AND e.event_date + INTERVAL 119 DAY
LEFT JOIN event_stable_depth d
  ON d.src = e.src
 AND d.tgt = e.tgt
 AND d.integration_scope = e.integration_scope
 AND d.event_date = e.event_date
 AND d.support_date = c.origin_date
LEFT JOIN event_weth_depth w
  ON w.src = e.src
 AND w.tgt = e.tgt
 AND w.integration_scope = e.integration_scope
 AND w.event_date = e.event_date
 AND w.support_date = c.origin_date
WHERE c.native_routes + c.stable_routes > 0
ORDER BY event_id, c.origin_date
"""


def load_event_panel(
    *,
    choices_path: Path,
    pool_capital_path: Path,
    capital_status: str = CAPITAL_STATUS,
    min_stable_weak_leg_usd: float = MIN_STABLE_WEAK_LEG_USD,
    min_active_days: int = MIN_ACTIVE_DAYS,
) -> pd.DataFrame:
    """Load events dated solely from prior-calendar deposited capital."""

    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=4")
        connection.execute("PRAGMA preserve_insertion_order=false")
        frame = connection.execute(
            EVENT_QUERY,
            [
                str(choices_path),
                str(pool_capital_path),
                capital_status,
                float(min_stable_weak_leg_usd),
                str(pool_capital_path),
                capital_status,
                int(min_active_days),
                int(min_active_days),
                int(min_active_days),
                str(pool_capital_path),
                capital_status,
            ],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("lagged-capital bridge event panel is empty")
    return prepare_exante_bridge_panel(frame)


def event_support_rows(
    panel: pd.DataFrame,
    *,
    min_stable_weak_leg_usd: float = MIN_STABLE_WEAK_LEG_USD,
) -> pd.DataFrame:
    """Record the event definition and full-sample coverage."""

    return pd.DataFrame(
        [
            {
                "record_type": "exante_bridge_support",
                "model_id": "lagged_capital_threshold",
                "events": int(panel["event_id"].nunique()),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "first_event_date": panel["event_date"].min().date().isoformat(),
                "last_event_date": panel["event_date"].max().date().isoformat(),
                "min_stable_weak_leg_usd": float(min_stable_weak_leg_usd),
                "capital_timing": "prior calendar day",
                "precondition": "earlier WETH route use and no earlier observed stablecoin route",
            }
        ]
    )


def run(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    output_path: Path = RESULT_OUTPUT,
    min_stable_weak_leg_usd: float = MIN_STABLE_WEAK_LEG_USD,
) -> int:
    panel = load_event_panel(
        choices_path=choices_path,
        pool_capital_path=pool_capital_path,
        min_stable_weak_leg_usd=min_stable_weak_leg_usd,
    )
    results = pd.concat(
        [
            event_support_rows(
                panel,
                min_stable_weak_leg_usd=min_stable_weak_leg_usd,
            ),
            adoption_and_retention_summaries(panel),
            paired_share_change_regressions(panel),
            relative_depth_regressions(panel),
        ],
        ignore_index=True,
    )
    write_exhibit(
        results,
        output_path,
        code_sources=[
            "scripts/analyze/run_bridge_exante.py",
            "src/ddvc/analysis/bridge_exante.py",
        ],
        inputs=[
            "data/processed/endpoint_candidate_choices.parquet",
            "data/processed/pool_capital_daily.parquet",
        ],
    )
    print(
        f"wrote {len(results):,} rows for "
        f"{panel['event_id'].nunique():,} lagged-capital bridge events"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument(
        "--min-stable-weak-leg-usd",
        type=float,
        default=MIN_STABLE_WEAK_LEG_USD,
    )
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pool_capital_path=args.pool_capital,
        output_path=args.output,
        min_stable_weak_leg_usd=args.min_stable_weak_leg_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
