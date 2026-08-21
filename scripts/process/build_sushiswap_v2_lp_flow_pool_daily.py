#!/usr/bin/env python3
"""Build the SushiSwap V2 pool-day LP-flow comparison panel.

The output mirrors ``v2_lp_flow_pool_daily.parquet`` so the protocol-fee
experiment can compare the same Mint/Burn outcomes across Uniswap V2 and
SushiSwap V2.  Eventless raw pool-days remain in the panel with zero flows.
Mint/Burn amounts are valued only when both token sides have validated
canonical prices.  Raw LP-token ``liquidity`` is retained separately.

The Graph's ``needsComplete`` field is a source warning for exact reserve-state
replay.  Positive Mint/Burn amounts carrying that flag remain in this
descriptive flow panel and are counted explicitly.

Reads
    data/raw/thegraph/sushiswap_v2/sushiswap_v2_{daily,mints,burns}_*.jsonl.gz
    data/processed/pool_capital_daily.parquet
    data/processed/token_price_daily.parquet
Writes
    data/processed/sushiswap_v2_lp_flow_pool_daily.parquet
    output/exhibits/sushiswap_v2_lp_flow_pool_daily_support.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.capital_data import POOL_CAPITAL_DAILY
from ddvc.capital_validation import CAPITAL_PRICE_SOURCE, CAPITAL_PRICE_VALIDATION_STATUS
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v2_lp_flow_pool_daily import (
    FLOW_ZERO_COLUMNS,
    MAX_EVENT_USD,
    _event_date,
    _event_key,
    _needs_complete,
    _pool_id,
    _positive_float,
    _raw_token_addresses,
    validated_event_prices,
)


VENUE = "sushiswap_v2"
EVENT_DIR = DATA_DIR / "raw/thegraph/sushiswap_v2"
OUTPUT = DATA_DIR / "processed/sushiswap_v2_lp_flow_pool_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/sushiswap_v2_lp_flow_pool_daily_support.jsonl"
SUSHISWAP_V2_LP_FEE_RATE = 0.0025

CODE_SOURCES = [
    "scripts/process/build_sushiswap_v2_lp_flow_pool_daily.py",
    "scripts/process/build_v2_lp_flow_pool_daily.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/sushiswap_v2",
    "data/processed/pool_capital_daily.parquet",
    "data/processed/token_price_daily.parquet",
]


def load_sushiswap_v2_pool_registry(
    path: Path = POOL_CAPITAL_DAILY,
) -> pd.DataFrame:
    """Return one conflict-free immutable identity per SushiSwap V2 pool."""

    connection = duckdb.connect()
    try:
        registry = connection.execute(
            """
            SELECT
                lower(pool) AS pool,
                min(lower(token0_address)) AS token0_address,
                min(token0_symbol) AS token0_symbol,
                min(lower(token1_address)) AS token1_address,
                min(token1_symbol) AS token1_symbol,
                count(DISTINCT lower(token0_address)) AS token0_identities,
                count(DISTINCT lower(token1_address)) AS token1_identities
            FROM read_parquet(?)
            WHERE venue = 'sushiswap_v2'
              AND token0_address IS NOT NULL
              AND token1_address IS NOT NULL
            GROUP BY lower(pool)
            ORDER BY lower(pool)
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()
    if registry.empty:
        raise ValueError("pool-capital panel has no SushiSwap V2 identities")
    conflict = registry[registry["token0_identities"].ne(1) | registry["token1_identities"].ne(1)]
    if not conflict.empty:
        raise ValueError("SushiSwap V2 registry has conflicting token identities")
    return registry.drop(columns=["token0_identities", "token1_identities"])


def load_raw_sushiswap_v2_pool_day_calendar(
    event_dir: Path = EVENT_DIR,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read every retained SushiSwap V2 pool-day, including zero-volume rows."""

    files = sorted(event_dir.glob("sushiswap_v2_daily_*.jsonl.gz"))
    if not files:
        raise ValueError("no SushiSwap V2 raw pool-day files found")
    connection = duckdb.connect()
    try:
        calendar = connection.execute(
            """
            WITH raw AS (
                SELECT
                    CAST(to_timestamp(TRY_CAST(date AS BIGINT)) AS DATE) AS origin_date,
                    lower(pairAddress) AS pool,
                    TRY_CAST(dailyVolumeUSD AS DOUBLE) AS raw_volume_usd
                FROM read_json_auto(?, format='newline_delimited', union_by_name=true)
            )
            SELECT
                origin_date,
                pool,
                max(raw_volume_usd) FILTER (
                    WHERE isfinite(raw_volume_usd) AND raw_volume_usd >= 0
                ) AS valid_volume_usd,
                count(*) AS raw_pool_day_rows,
                count(*) FILTER (
                    WHERE raw_volume_usd IS NULL
                       OR NOT isfinite(raw_volume_usd)
                       OR raw_volume_usd < 0
                ) AS invalid_volume_rows
            FROM raw
            WHERE origin_date IS NOT NULL AND pool IS NOT NULL AND pool <> ''
            GROUP BY origin_date, pool
            ORDER BY origin_date, pool
            """,
            [[str(path) for path in files]],
        ).fetchdf()
    finally:
        connection.close()
    if calendar.empty:
        raise ValueError("raw SushiSwap V2 pool-day calendar is empty")
    calendar["origin_date"] = pd.to_datetime(calendar["origin_date"])
    calendar["v2_volume_usd"] = pd.to_numeric(
        calendar.pop("valid_volume_usd"), errors="coerce"
    ).fillna(0.0)
    calendar["v2_fee_opportunity_usd"] = (
        SUSHISWAP_V2_LP_FEE_RATE * calendar["v2_volume_usd"]
    )
    calendar["v2_volume_support_status"] = np.where(
        calendar["invalid_volume_rows"].eq(0),
        "provider_pool_day_volume_valid",
        np.where(
            calendar["v2_volume_usd"].gt(0),
            "provider_pool_day_volume_partially_valid",
            "provider_pool_day_volume_missing_or_invalid",
        ),
    )
    return calendar, {
        "pool_day_files": len(files),
        "raw_pool_day_rows": int(calendar["raw_pool_day_rows"].sum()),
        "invalid_volume_rows": int(calendar["invalid_volume_rows"].sum()),
    }


def _new_bucket() -> dict[str, object]:
    return {
        "raw_add_events": 0,
        "raw_remove_events": 0,
        "full_price_add_events": 0,
        "full_price_remove_events": 0,
        "one_price_events": 0,
        "missing_price_events": 0,
        "nonpositive_amount_events": 0,
        "above_screen_events": 0,
        "needs_complete_events": 0,
        "add_flow_usd": 0.0,
        "remove_flow_usd": 0.0,
        "add_token0_usd": 0.0,
        "remove_token0_usd": 0.0,
        "add_token1_usd": 0.0,
        "remove_token1_usd": 0.0,
        "add_liquidity": 0.0,
        "remove_liquidity": 0.0,
        "needs_complete_add_liquidity": 0.0,
        "needs_complete_remove_liquidity": 0.0,
        "missing_invalid_liquidity_events": 0,
        "transactions": set(),
        "senders": set(),
        "recipients": set(),
        "origins": set(),
    }


def load_raw_sushiswap_v2_lp_flows(
    *,
    event_dir: Path = EVENT_DIR,
    pool_registry: pd.DataFrame,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_event_usd: float = MAX_EVENT_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate SushiSwap V2 Mint/Burn amounts by pool-day."""

    required = {
        "pool",
        "token0_address",
        "token0_symbol",
        "token1_address",
        "token1_symbol",
    }
    missing = sorted(required - set(pool_registry.columns))
    if missing:
        raise ValueError(f"SushiSwap V2 registry lacks columns: {missing}")
    registry = {
        str(row.pool).lower(): (
            str(row.token0_address).lower(),
            str(row.token0_symbol),
            str(row.token1_address).lower(),
            str(row.token1_symbol),
        )
        for row in pool_registry.itertuples(index=False)
    }
    prices = validated_event_prices(price_path)
    buckets: dict[tuple[pd.Timestamp, str], dict[str, object]] = defaultdict(_new_bucket)
    counts = Counter()
    event_files = 0
    max_seen_usd = 0.0

    for event_type, pattern in (
        ("add", "sushiswap_v2_mints_*.jsonl.gz"),
        ("remove", "sushiswap_v2_burns_*.jsonl.gz"),
    ):
        for path in sorted(event_dir.glob(pattern)):
            event_files += 1
            partition_day = path.stem.removesuffix(".jsonl").rsplit("_", 1)[-1]
            seen: set[str] = set()
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    counts["raw_events"] += 1
                    event = json.loads(line)
                    event_key = _event_key(event)
                    if event_key and event_key in seen:
                        counts["duplicate_events"] += 1
                        continue
                    if event_key:
                        seen.add(event_key)
                    pool = _pool_id(event)
                    identity = registry.get(pool)
                    if identity is None:
                        counts["pool_registry_misses"] += 1
                        continue
                    try:
                        origin_date = _event_date(event)
                    except (TypeError, ValueError, OverflowError):
                        counts["invalid_timestamp_events"] += 1
                        continue
                    day = origin_date.strftime("%Y%m%d")
                    if partition_day.isdigit() and partition_day != day:
                        counts["partition_day_mismatches"] += 1
                        continue
                    raw_token0, raw_token1 = _raw_token_addresses(event)
                    if (raw_token0 and raw_token0 != identity[0]) or (
                        raw_token1 and raw_token1 != identity[2]
                    ):
                        counts["identity_conflicts"] += 1
                        continue

                    bucket = buckets[(origin_date, pool)]
                    bucket[f"raw_{event_type}_events"] = int(
                        bucket[f"raw_{event_type}_events"]
                    ) + 1
                    counts[f"raw_{event_type}_events"] += 1
                    transaction = event.get("transaction") or {}
                    for field, target in (
                        (str(transaction.get("id") or "").lower(), "transactions"),
                        (str(event.get("sender") or "").lower(), "senders"),
                        (str(event.get("to") or "").lower(), "recipients"),
                        (str(event.get("origin") or "").lower(), "origins"),
                    ):
                        if field:
                            bucket[target].add(field)

                    needs_complete = _needs_complete(event)
                    liquidity = _positive_float(event.get("liquidity"))
                    if liquidity is None:
                        bucket["missing_invalid_liquidity_events"] = int(
                            bucket["missing_invalid_liquidity_events"]
                        ) + 1
                        counts["missing_invalid_liquidity_events"] += 1
                    else:
                        bucket[f"{event_type}_liquidity"] = float(
                            bucket[f"{event_type}_liquidity"]
                        ) + liquidity
                        if needs_complete:
                            key = f"needs_complete_{event_type}_liquidity"
                            bucket[key] = float(bucket[key]) + liquidity
                        counts["valid_liquidity_events"] += 1
                    if needs_complete:
                        bucket["needs_complete_events"] = int(
                            bucket["needs_complete_events"]
                        ) + 1
                        counts["needs_complete_events"] += 1

                    amount0 = _positive_float(event.get("amount0"))
                    amount1 = _positive_float(event.get("amount1"))
                    if amount0 is None or amount1 is None:
                        bucket["nonpositive_amount_events"] = int(
                            bucket["nonpositive_amount_events"]
                        ) + 1
                        counts["nonpositive_amount_events"] += 1
                        continue
                    price0 = prices.get((day, identity[0]))
                    price1 = prices.get((day, identity[2]))
                    value0 = amount0 * price0 if price0 is not None else None
                    value1 = amount1 * price1 if price1 is not None else None
                    if value0 is not None:
                        key = f"{event_type}_token0_usd"
                        bucket[key] = float(bucket[key]) + value0
                    if value1 is not None:
                        key = f"{event_type}_token1_usd"
                        bucket[key] = float(bucket[key]) + value1
                    if (price0 is None) ^ (price1 is None):
                        bucket["one_price_events"] = int(bucket["one_price_events"]) + 1
                        counts["one_price_events"] += 1
                        continue
                    if price0 is None or price1 is None:
                        bucket["missing_price_events"] = int(bucket["missing_price_events"]) + 1
                        counts["missing_price_events"] += 1
                        continue
                    total_value = float(value0 + value1)
                    max_seen_usd = max(max_seen_usd, total_value)
                    if not np.isfinite(total_value) or total_value <= 0:
                        bucket["nonpositive_amount_events"] = int(
                            bucket["nonpositive_amount_events"]
                        ) + 1
                        counts["nonpositive_amount_events"] += 1
                        continue
                    if total_value > max_event_usd:
                        bucket["above_screen_events"] = int(bucket["above_screen_events"]) + 1
                        counts["above_screen_events"] += 1
                        continue
                    bucket[f"{event_type}_flow_usd"] = float(
                        bucket[f"{event_type}_flow_usd"]
                    ) + total_value
                    bucket[f"full_price_{event_type}_events"] = int(
                        bucket[f"full_price_{event_type}_events"]
                    ) + 1
                    counts["full_price_events"] += 1

    rows: list[dict[str, object]] = []
    for (origin_date, pool), bucket in buckets.items():
        add = float(bucket["add_flow_usd"])
        remove = float(bucket["remove_flow_usd"])
        add_liquidity = float(bucket["add_liquidity"])
        remove_liquidity = float(bucket["remove_liquidity"])
        raw_events = int(bucket["raw_add_events"]) + int(bucket["raw_remove_events"])
        valued_events = int(bucket["full_price_add_events"]) + int(
            bucket["full_price_remove_events"]
        )
        status = (
            "all_eligible_events_two_sided_canonical"
            if raw_events > 0 and valued_events == raw_events
            else "partial_two_sided_canonical"
            if valued_events > 0
            else "no_two_sided_canonical_flow"
        )
        rows.append(
            {
                "origin_date": origin_date,
                "pool": pool,
                "v2_raw_add_events": int(bucket["raw_add_events"]),
                "v2_raw_remove_events": int(bucket["raw_remove_events"]),
                "v2_add_events_valued": int(bucket["full_price_add_events"]),
                "v2_remove_events_valued": int(bucket["full_price_remove_events"]),
                "v2_add_lp_flow_usd": add,
                "v2_remove_lp_flow_usd": remove,
                "v2_gross_lp_flow_usd": add + remove,
                "v2_net_add_lp_flow_usd": add - remove,
                "v2_add_token0_flow_usd_priced": float(bucket["add_token0_usd"]),
                "v2_remove_token0_flow_usd_priced": float(bucket["remove_token0_usd"]),
                "v2_add_token1_flow_usd_priced": float(bucket["add_token1_usd"]),
                "v2_remove_token1_flow_usd_priced": float(bucket["remove_token1_usd"]),
                "v2_add_liquidity": add_liquidity,
                "v2_remove_liquidity": remove_liquidity,
                "v2_gross_liquidity": add_liquidity + remove_liquidity,
                "v2_net_add_liquidity": add_liquidity - remove_liquidity,
                "v2_needs_complete_add_liquidity": float(
                    bucket["needs_complete_add_liquidity"]
                ),
                "v2_needs_complete_remove_liquidity": float(
                    bucket["needs_complete_remove_liquidity"]
                ),
                "v2_one_price_events": int(bucket["one_price_events"]),
                "v2_missing_price_events": int(bucket["missing_price_events"]),
                "v2_nonpositive_amount_events": int(bucket["nonpositive_amount_events"]),
                "v2_above_screen_events": int(bucket["above_screen_events"]),
                "v2_needs_complete_events": int(bucket["needs_complete_events"]),
                "v2_missing_invalid_liquidity_events": int(
                    bucket["missing_invalid_liquidity_events"]
                ),
                "v2_transaction_count": len(bucket["transactions"]),
                "v2_sender_count": len(bucket["senders"]),
                "v2_recipient_count": len(bucket["recipients"]),
                "v2_origin_count": len(bucket["origins"]),
                "v2_full_price_event_share": valued_events / raw_events,
                "v2_flow_valuation_status": status,
                "v2_liquidity_support_status": (
                    "raw_liquidity_contains_needs_complete_source_flag"
                    if int(bucket["needs_complete_events"]) > 0
                    else "raw_liquidity_has_missing_or_invalid_events"
                    if int(bucket["missing_invalid_liquidity_events"]) > 0
                    else "raw_liquidity_fields_complete"
                ),
            }
        )
    flows = pd.DataFrame(rows).sort_values(["origin_date", "pool"]).reset_index(drop=True)
    return flows, {
        "event_files": int(event_files),
        "raw_mint_burn_events": int(counts["raw_events"]),
        "raw_add_events": int(counts["raw_add_events"]),
        "raw_remove_events": int(counts["raw_remove_events"]),
        "duplicate_events": int(counts["duplicate_events"]),
        "pool_registry_misses": int(counts["pool_registry_misses"]),
        "identity_conflicts": int(counts["identity_conflicts"]),
        "invalid_timestamp_events": int(counts["invalid_timestamp_events"]),
        "partition_day_mismatches": int(counts["partition_day_mismatches"]),
        "needs_complete_events": int(counts["needs_complete_events"]),
        "full_price_events": int(counts["full_price_events"]),
        "one_price_events": int(counts["one_price_events"]),
        "missing_price_events": int(counts["missing_price_events"]),
        "nonpositive_amount_events": int(counts["nonpositive_amount_events"]),
        "above_screen_events": int(counts["above_screen_events"]),
        "valid_liquidity_events": int(counts["valid_liquidity_events"]),
        "missing_invalid_liquidity_events": int(
            counts["missing_invalid_liquidity_events"]
        ),
        "max_event_usd": float(max_event_usd),
        "max_seen_event_usd": float(max_seen_usd),
        "event_pool_days": int(len(flows)),
    }


def assemble_sushiswap_v2_lp_flow_panel(
    calendar: pd.DataFrame,
    flows: pd.DataFrame,
    registry: pd.DataFrame,
    *,
    capital_path: Path = POOL_CAPITAL_DAILY,
) -> pd.DataFrame:
    """Join SushiSwap event flows to its complete pool-day and capital calendar."""

    panel = calendar.merge(flows, on=["origin_date", "pool"], how="outer")
    panel = panel.merge(registry, on="pool", how="left", validate="many_to_one")
    if panel[["token0_address", "token1_address"]].isna().any(axis=None):
        raise ValueError("SushiSwap V2 flow panel contains an unregistered pool")
    panel["venue"] = VENUE
    panel["v2_lp_fee_rate"] = SUSHISWAP_V2_LP_FEE_RATE
    panel["v2_volume_usd"] = pd.to_numeric(panel["v2_volume_usd"], errors="coerce").fillna(0)
    panel["v2_fee_opportunity_usd"] = SUSHISWAP_V2_LP_FEE_RATE * panel["v2_volume_usd"]
    panel["raw_pool_day_rows"] = panel["raw_pool_day_rows"].fillna(0).astype(int)
    panel["invalid_volume_rows"] = panel["invalid_volume_rows"].fillna(0).astype(int)
    panel["v2_volume_support_status"] = panel["v2_volume_support_status"].fillna(
        "event_only_no_provider_pool_day"
    )
    for column in FLOW_ZERO_COLUMNS:
        panel[column] = pd.to_numeric(panel[column], errors="coerce").fillna(0)
    eventless = panel["v2_raw_add_events"].add(panel["v2_raw_remove_events"]).eq(0)
    panel.loc[eventless, "v2_flow_valuation_status"] = "no_lp_events"
    panel.loc[eventless, "v2_liquidity_support_status"] = "no_lp_events"
    panel.loc[eventless, "v2_full_price_event_share"] = np.nan

    base = panel.copy()
    base["day_key"] = pd.to_datetime(base["origin_date"]).dt.strftime("%Y%m%d")
    connection = duckdb.connect()
    try:
        connection.register("base", base)
        joined = connection.execute(
            """
            WITH capital AS (
                SELECT
                    day,
                    lower(pool) AS pool,
                    reserve0,
                    reserve1,
                    capital_usd,
                    capital_usd_lagged,
                    capital_valid,
                    exact_lag_valid,
                    capital_source,
                    price_source,
                    capital_validation_status,
                    identity_validation_status,
                    token_mechanics_status,
                    failure_reason,
                    sqrt(reserve0 * reserve1) AS sqrt_k,
                    lag(sqrt(reserve0 * reserve1)) OVER (
                        PARTITION BY lower(pool) ORDER BY day
                    ) AS lagged_sqrt_k
                FROM read_parquet(?)
                WHERE venue = 'sushiswap_v2'
            )
            SELECT
                b.* EXCLUDE (day_key),
                c.reserve0 AS v2_reserve0,
                c.reserve1 AS v2_reserve1,
                c.sqrt_k AS v2_sqrt_k,
                CASE WHEN c.exact_lag_valid THEN c.lagged_sqrt_k END AS v2_lagged_sqrt_k,
                c.capital_usd AS v2_capital_usd,
                c.capital_usd_lagged AS v2_lagged_capital_usd,
                coalesce(c.capital_valid, false) AS v2_capital_valid,
                coalesce(c.exact_lag_valid, false) AS v2_exact_lag_valid,
                c.capital_source AS v2_capital_source,
                c.price_source AS v2_capital_price_source,
                c.capital_validation_status AS v2_capital_validation_status,
                c.identity_validation_status AS v2_identity_validation_status,
                c.token_mechanics_status AS v2_token_mechanics_status,
                c.failure_reason AS v2_capital_failure_reason
            FROM base b
            LEFT JOIN capital c ON b.day_key = c.day AND b.pool = c.pool
            ORDER BY b.origin_date, b.pool
            """,
            [str(capital_path)],
        ).fetchdf()
    finally:
        connection.close()
    return joined


def validate_sushiswap_v2_lp_flow_panel(panel: pd.DataFrame) -> None:
    required = {
        "venue",
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "v2_volume_usd",
        "v2_fee_opportunity_usd",
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_net_add_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
        "v2_net_add_liquidity",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"SushiSwap V2 LP-flow panel lacks columns: {missing}")
    if panel.empty or panel.duplicated(["origin_date", "pool"]).any():
        raise ValueError("SushiSwap V2 LP-flow panel is empty or has duplicate pool-days")
    if not panel["venue"].eq(VENUE).all():
        raise ValueError("SushiSwap V2 LP-flow panel contains another venue")
    for left, right, target in (
        ("v2_add_lp_flow_usd", "v2_remove_lp_flow_usd", "v2_gross_lp_flow_usd"),
        ("v2_add_liquidity", "v2_remove_liquidity", "v2_gross_liquidity"),
    ):
        if not np.allclose(panel[target], panel[left] + panel[right]):
            raise ValueError(f"{target} does not equal additions plus removals")
    if not np.allclose(
        panel["v2_fee_opportunity_usd"],
        SUSHISWAP_V2_LP_FEE_RATE * panel["v2_volume_usd"],
    ):
        raise ValueError("SushiSwap V2 fee opportunity is not 25 bp of volume")


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = EVENT_DIR,
    capital_path: Path = POOL_CAPITAL_DAILY,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_event_usd: float = MAX_EVENT_USD,
) -> int:
    registry = load_sushiswap_v2_pool_registry(capital_path)
    calendar, calendar_support = load_raw_sushiswap_v2_pool_day_calendar(event_dir)
    flows, flow_support = load_raw_sushiswap_v2_lp_flows(
        event_dir=event_dir,
        pool_registry=registry,
        price_path=price_path,
        max_event_usd=max_event_usd,
    )
    panel = assemble_sushiswap_v2_lp_flow_panel(
        calendar, flows, registry, capital_path=capital_path
    )
    validate_sushiswap_v2_lp_flow_panel(panel)
    with atomic_output(output_path) as temporary:
        panel.to_parquet(temporary, index=False)
    eventless = panel["v2_raw_add_events"].add(panel["v2_raw_remove_events"]).eq(0)
    support = {
        "record_type": "sushiswap_v2_lp_flow_pool_daily_support",
        "analysis_status": "processed_liquidity_supply_comparison_input",
        "venue": VENUE,
        "lp_fee_rate": SUSHISWAP_V2_LP_FEE_RATE,
        "price_source": CAPITAL_PRICE_SOURCE,
        "price_validation_status": CAPITAL_PRICE_VALIDATION_STATUS,
        "pool_day_rows": int(len(panel)),
        "pools": int(panel["pool"].nunique()),
        "first_origin_date": str(pd.to_datetime(panel["origin_date"]).min().date()),
        "last_origin_date": str(pd.to_datetime(panel["origin_date"]).max().date()),
        "eventless_pool_days": int(eventless.sum()),
        "capital_state_match_share": float(panel["v2_reserve0"].notna().mean()),
        "flow_quantity": (
            "Mint/Burn token amounts with two-sided canonical USD valuation; raw "
            "LP-token quantity retained separately"
        ),
        "identity_boundary": (
            "sender, recipient, and origin are address-participation proxies, not "
            "verified beneficial LP owners"
        ),
        **calendar_support,
        **flow_support,
    }
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    label = (
        output_path.relative_to(REPO_ROOT)
        if output_path.is_relative_to(REPO_ROOT)
        else output_path
    )
    print(f"wrote {len(panel):,} SushiSwap V2 LP-flow pool-days to {label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--capital", type=Path, default=POOL_CAPITAL_DAILY)
    parser.add_argument("--prices", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument("--max-event-usd", type=float, default=MAX_EVENT_USD)
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        capital_path=args.capital,
        price_path=args.prices,
        max_event_usd=args.max_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
