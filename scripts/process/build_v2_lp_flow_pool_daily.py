#!/usr/bin/env python3
"""Build Uniswap V2 pool-day liquidity-supply flows and fee opportunities.

Reads:
  data/raw/thegraph/uniswap_v2/uniswap_v2_daily_*.jsonl.gz
  data/raw/thegraph/uniswap_v2/uniswap_v2_mints_*.jsonl.gz
  data/raw/thegraph/uniswap_v2/uniswap_v2_burns_*.jsonl.gz
  data/processed/pool_capital_daily.parquet
  data/processed/token_price_daily.parquet

Writes:
  data/processed/v2_lp_flow_pool_daily.parquet
  output/exhibits/v2_lp_flow_pool_daily_support.jsonl

The calendar comes from the retained Uniswap V2 pool-day records, so days with
no Mint or Burn event remain in the panel with zero flows.  USD flows use only
events for which both token sides have independently validated canonical daily
prices.  The raw ``liquidity`` field supplies a price-free quantity-flow
measure.  Neither measure includes fee accrual, reserve revaluation, or a
change inferred from the deposited-capital stock.

The Graph's ``needsComplete`` flag marks an event whose indexed payload may
require chain-order completion for exact reserve-state replay.  It remains a
visible source-support flag here, but it does not suppress positive Mint or
Burn amounts in this descriptive flow panel.

``sender``, ``to``, and the rarely populated ``origin`` field are retained only
as address-participation counts.  They do not identify beneficial LP owners.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.capital_data import POOL_CAPITAL_DAILY
from ddvc.capital_validation import (
    CAPITAL_PRICE_SOURCE,
    CAPITAL_PRICE_VALIDATION_STATUS,
    PRICE_MEDIAN_FACTOR,
    PRICE_ROLLING_DAYS,
    USD_STABLE_PRICE_BOUNDS,
    USD_STABLE_TOKENS,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v2"
OUTPUT = REPO_ROOT / "data/processed/v2_lp_flow_pool_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v2_lp_flow_pool_daily_support.jsonl"
UNISWAP_V2_PROTOCOL_FEE_ACTIVATION_UTC = "2025-12-27T20:33:11Z"
# Daily provider records cannot split the activation day. Keep 27 December at
# the old rate (which applied for most of that UTC day) and use 28 December as
# the first complete day under the new LP fee.
UNISWAP_V2_PROTOCOL_FEE_FIRST_FULL_DAY = pd.Timestamp("2025-12-28")
UNISWAP_V2_LP_FEE_RATE_BEFORE_SWITCH = 0.003
UNISWAP_V2_LP_FEE_RATE_AFTER_SWITCH = 0.0025
MAX_EVENT_USD = 250_000_000.0

CODE_SOURCES = [
    "scripts/process/build_v2_lp_flow_pool_daily.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v2",
    "data/processed/pool_capital_daily.parquet",
    "data/processed/token_price_daily.parquet",
]


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_float(value: object) -> float | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    result = float(abs(parsed))
    return result if np.isfinite(result) and result > 0 else None


def _event_date(event: dict[str, object]) -> pd.Timestamp:
    timestamp = int(
        event.get("timestamp")
        or (event.get("transaction") or {}).get("timestamp")
        or 0
    )
    if timestamp <= 0:
        raise ValueError("V2 LP event has no positive timestamp")
    return pd.Timestamp(datetime.fromtimestamp(timestamp, tz=timezone.utc).date())


def _event_key(event: dict[str, object]) -> str:
    event_id = str(event.get("id") or "")
    if event_id:
        return event_id
    transaction = event.get("transaction") or {}
    return f"{transaction.get('id') or ''}:{event.get('logIndex') or ''}"


def _pool_container(event: dict[str, object]) -> dict[str, object]:
    container = event.get("pair") or event.get("pool") or {}
    return container if isinstance(container, dict) else {}


def _pool_id(event: dict[str, object]) -> str:
    return str(
        _pool_container(event).get("id")
        or event.get("pairAddress")
        or event.get("pool")
        or ""
    ).lower()


def _raw_token_addresses(event: dict[str, object]) -> tuple[str, str]:
    container = _pool_container(event)
    token0 = container.get("token0") or {}
    token1 = container.get("token1") or {}
    return (
        str(token0.get("id") or "").lower(),
        str(token1.get("id") or "").lower(),
    )


def _needs_complete(event: dict[str, object]) -> bool:
    value = event.get("needsComplete")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def load_v2_pool_registry(
    path: Path = POOL_CAPITAL_DAILY,
) -> pd.DataFrame:
    """Return one conflict-free immutable identity per Uniswap V2 pool."""

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
            WHERE venue = 'uniswap_v2'
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
        raise ValueError("pool-capital panel has no Uniswap V2 identities")
    conflicts = registry[
        registry["token0_identities"].ne(1)
        | registry["token1_identities"].ne(1)
    ]
    if not conflicts.empty:
        raise ValueError("Uniswap V2 pool registry has conflicting token identities")
    return registry.drop(columns=["token0_identities", "token1_identities"])


def validated_event_prices(
    path: Path = TOKEN_PRICE_DAILY_PANEL,
) -> dict[tuple[str, str], float]:
    """Return all address-day prices passing the capital price-time screen."""

    prices = pd.read_parquet(
        path,
        columns=["day", "token", "price_usd", "price_source", "validation_status"],
    )
    if prices.empty:
        raise ValueError("canonical token-price panel is empty")
    prices = prices.copy()
    prices["day"] = prices["day"].astype(str)
    prices["token"] = prices["token"].astype(str).str.lower()
    prices["price_usd"] = pd.to_numeric(prices["price_usd"], errors="coerce")
    if prices.duplicated(["day", "token"]).any():
        raise ValueError("canonical token-price panel has duplicate address-days")
    prices = prices.sort_values(["token", "day"]).reset_index(drop=True)
    median = prices.groupby("token", sort=False)["price_usd"].transform(
        lambda values: values.rolling(
            PRICE_ROLLING_DAYS,
            min_periods=5,
        ).median()
    )
    price = prices["price_usd"]
    valid = (
        np.isfinite(price)
        & price.gt(0)
        & np.isfinite(median)
        & median.gt(0)
        & price.between(median / PRICE_MEDIAN_FACTOR, median * PRICE_MEDIAN_FACTOR)
        & prices["price_source"].eq("canonical_repriced_route_legs")
        & prices["validation_status"].eq(
            "minimum_observations_and_price_consensus_passed"
        )
    )
    usd_stable = prices["token"].isin(USD_STABLE_TOKENS)
    valid &= ~usd_stable | price.between(*USD_STABLE_PRICE_BOUNDS)
    usable = prices.loc[valid, ["day", "token", "price_usd"]]
    if usable.empty:
        raise ValueError("canonical token-price panel has no usable address-days")
    return {
        (str(row.day), str(row.token)): float(row.price_usd)
        for row in usable.itertuples(index=False)
    }


def load_raw_v2_pool_day_calendar(
    event_dir: Path = EVENT_DIR,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read the raw Uniswap V2 volume calendar, including zero-volume rows."""

    files = sorted(event_dir.glob("uniswap_v2_daily_*.jsonl.gz"))
    if not files:
        raise ValueError("no Uniswap V2 raw pool-day files found")
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
        raise ValueError("raw Uniswap V2 pool-day calendar is empty")
    calendar["origin_date"] = pd.to_datetime(calendar["origin_date"])
    calendar["v2_volume_usd"] = pd.to_numeric(
        calendar.pop("valid_volume_usd"), errors="coerce"
    ).fillna(0.0)
    calendar["v2_lp_fee_rate"] = np.where(
        calendar["origin_date"].lt(UNISWAP_V2_PROTOCOL_FEE_FIRST_FULL_DAY),
        UNISWAP_V2_LP_FEE_RATE_BEFORE_SWITCH,
        UNISWAP_V2_LP_FEE_RATE_AFTER_SWITCH,
    )
    calendar["v2_fee_opportunity_usd"] = (
        calendar["v2_lp_fee_rate"] * calendar["v2_volume_usd"]
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
    support = {
        "pool_day_files": len(files),
        "raw_pool_day_rows": int(calendar["raw_pool_day_rows"].sum()),
        "invalid_volume_rows": int(calendar["invalid_volume_rows"].sum()),
    }
    return calendar, support


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


def load_raw_uniswap_v2_lp_flows(
    *,
    event_dir: Path = EVENT_DIR,
    pool_registry: pd.DataFrame,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_event_usd: float = MAX_EVENT_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate true Mint/Burn event flows by Uniswap V2 pool-day."""

    required = {
        "pool",
        "token0_address",
        "token0_symbol",
        "token1_address",
        "token1_symbol",
    }
    missing = sorted(required - set(pool_registry.columns))
    if missing:
        raise ValueError(f"V2 pool registry lacks columns: {missing}")
    if max_event_usd <= 0:
        raise ValueError("maximum event USD must be positive")
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
    buckets: dict[tuple[pd.Timestamp, str], dict[str, object]] = defaultdict(
        _new_bucket
    )
    global_counts = Counter()
    event_files = 0
    max_seen_usd = 0.0

    for event_type, pattern in (
        ("add", "uniswap_v2_mints_*.jsonl.gz"),
        ("remove", "uniswap_v2_burns_*.jsonl.gz"),
    ):
        for path in sorted(event_dir.glob(pattern)):
            event_files += 1
            partition_day = path.stem.removesuffix(".jsonl").rsplit("_", 1)[-1]
            seen: set[str] = set()
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    global_counts["raw_events"] += 1
                    event = json.loads(line)
                    event_key = _event_key(event)
                    if event_key and event_key in seen:
                        global_counts["duplicate_events"] += 1
                        continue
                    if event_key:
                        seen.add(event_key)
                    pool = _pool_id(event)
                    identity = registry.get(pool)
                    if identity is None:
                        global_counts["pool_registry_misses"] += 1
                        continue
                    try:
                        origin_date = _event_date(event)
                    except (TypeError, ValueError, OverflowError):
                        global_counts["invalid_timestamp_events"] += 1
                        continue
                    day = origin_date.strftime("%Y%m%d")
                    if partition_day.isdigit() and partition_day != day:
                        global_counts["partition_day_mismatches"] += 1
                        continue
                    raw_token0, raw_token1 = _raw_token_addresses(event)
                    if raw_token0 and raw_token0 != identity[0]:
                        global_counts["identity_conflicts"] += 1
                        continue
                    if raw_token1 and raw_token1 != identity[2]:
                        global_counts["identity_conflicts"] += 1
                        continue

                    bucket = buckets[(origin_date, pool)]
                    bucket[f"raw_{event_type}_events"] = (
                        int(bucket[f"raw_{event_type}_events"]) + 1
                    )
                    global_counts[f"raw_{event_type}_events"] += 1
                    transaction = event.get("transaction") or {}
                    transaction_id = str(transaction.get("id") or "").lower()
                    sender = str(event.get("sender") or "").lower()
                    recipient = str(event.get("to") or "").lower()
                    origin = str(event.get("origin") or "").lower()
                    if transaction_id:
                        bucket["transactions"].add(transaction_id)
                    if sender:
                        bucket["senders"].add(sender)
                    if recipient:
                        bucket["recipients"].add(recipient)
                    if origin:
                        bucket["origins"].add(origin)

                    needs_complete = _needs_complete(event)
                    liquidity = _positive_float(event.get("liquidity"))
                    if liquidity is None:
                        bucket["missing_invalid_liquidity_events"] = (
                            int(bucket["missing_invalid_liquidity_events"]) + 1
                        )
                        global_counts["missing_invalid_liquidity_events"] += 1
                    else:
                        bucket[f"{event_type}_liquidity"] = (
                            float(bucket[f"{event_type}_liquidity"]) + liquidity
                        )
                        if needs_complete:
                            bucket[f"needs_complete_{event_type}_liquidity"] = (
                                float(
                                    bucket[
                                        f"needs_complete_{event_type}_liquidity"
                                    ]
                                )
                                + liquidity
                            )
                        global_counts["valid_liquidity_events"] += 1

                    if needs_complete:
                        bucket["needs_complete_events"] = (
                            int(bucket["needs_complete_events"]) + 1
                        )
                        global_counts["needs_complete_events"] += 1
                    amount0 = _positive_float(event.get("amount0"))
                    amount1 = _positive_float(event.get("amount1"))
                    if amount0 is None or amount1 is None:
                        bucket["nonpositive_amount_events"] = (
                            int(bucket["nonpositive_amount_events"]) + 1
                        )
                        global_counts["nonpositive_amount_events"] += 1
                        continue
                    price0 = prices.get((day, identity[0]))
                    price1 = prices.get((day, identity[2]))
                    value0 = amount0 * price0 if price0 is not None else None
                    value1 = amount1 * price1 if price1 is not None else None
                    if value0 is not None:
                        bucket[f"{event_type}_token0_usd"] = (
                            float(bucket[f"{event_type}_token0_usd"]) + value0
                        )
                    if value1 is not None:
                        bucket[f"{event_type}_token1_usd"] = (
                            float(bucket[f"{event_type}_token1_usd"]) + value1
                        )
                    if (price0 is None) ^ (price1 is None):
                        bucket["one_price_events"] = int(bucket["one_price_events"]) + 1
                        global_counts["one_price_events"] += 1
                        continue
                    if price0 is None or price1 is None:
                        bucket["missing_price_events"] = (
                            int(bucket["missing_price_events"]) + 1
                        )
                        global_counts["missing_price_events"] += 1
                        continue
                    total_value = float(value0 + value1)
                    max_seen_usd = max(max_seen_usd, total_value)
                    if not np.isfinite(total_value) or total_value <= 0:
                        bucket["nonpositive_amount_events"] = (
                            int(bucket["nonpositive_amount_events"]) + 1
                        )
                        global_counts["nonpositive_amount_events"] += 1
                        continue
                    if total_value > max_event_usd:
                        bucket["above_screen_events"] = (
                            int(bucket["above_screen_events"]) + 1
                        )
                        global_counts["above_screen_events"] += 1
                        continue
                    bucket[f"{event_type}_flow_usd"] = (
                        float(bucket[f"{event_type}_flow_usd"]) + total_value
                    )
                    bucket[f"full_price_{event_type}_events"] = (
                        int(bucket[f"full_price_{event_type}_events"]) + 1
                    )
                    global_counts["full_price_events"] += 1

    rows: list[dict[str, object]] = []
    for (origin_date, pool), bucket in buckets.items():
        add = float(bucket["add_flow_usd"])
        remove = float(bucket["remove_flow_usd"])
        add_liquidity = float(bucket["add_liquidity"])
        remove_liquidity = float(bucket["remove_liquidity"])
        needs_complete_add_liquidity = float(
            bucket["needs_complete_add_liquidity"]
        )
        needs_complete_remove_liquidity = float(
            bucket["needs_complete_remove_liquidity"]
        )
        raw_events = int(bucket["raw_add_events"]) + int(bucket["raw_remove_events"])
        full_price_events = int(bucket["full_price_add_events"]) + int(
            bucket["full_price_remove_events"]
        )
        eligible_events = raw_events
        if raw_events == 0:
            valuation_status = "no_lp_events"
        elif full_price_events == eligible_events and eligible_events > 0:
            valuation_status = "all_eligible_events_two_sided_canonical"
        elif full_price_events > 0:
            valuation_status = "partial_two_sided_canonical"
        else:
            valuation_status = "no_two_sided_canonical_flow"
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
                "v2_needs_complete_add_liquidity": needs_complete_add_liquidity,
                "v2_needs_complete_remove_liquidity": (
                    needs_complete_remove_liquidity
                ),
                "v2_one_price_events": int(bucket["one_price_events"]),
                "v2_missing_price_events": int(bucket["missing_price_events"]),
                "v2_nonpositive_amount_events": int(
                    bucket["nonpositive_amount_events"]
                ),
                "v2_above_screen_events": int(bucket["above_screen_events"]),
                "v2_needs_complete_events": int(
                    bucket["needs_complete_events"]
                ),
                "v2_missing_invalid_liquidity_events": int(
                    bucket["missing_invalid_liquidity_events"]
                ),
                "v2_transaction_count": len(bucket["transactions"]),
                "v2_sender_count": len(bucket["senders"]),
                "v2_recipient_count": len(bucket["recipients"]),
                "v2_origin_count": len(bucket["origins"]),
                "v2_full_price_event_share": (
                    full_price_events / eligible_events if eligible_events > 0 else np.nan
                ),
                "v2_flow_valuation_status": valuation_status,
                "v2_liquidity_support_status": (
                    "raw_liquidity_contains_needs_complete_source_flag"
                    if int(bucket["needs_complete_events"]) > 0
                    else "raw_liquidity_has_missing_or_invalid_events"
                    if int(bucket["missing_invalid_liquidity_events"]) > 0
                    else "raw_liquidity_fields_complete"
                ),
            }
        )
    flows = pd.DataFrame(rows)
    if not flows.empty:
        flows = flows.sort_values(["origin_date", "pool"]).reset_index(drop=True)
    support = {
        "event_files": int(event_files),
        "raw_mint_burn_events": int(global_counts["raw_events"]),
        "raw_add_events": int(global_counts["raw_add_events"]),
        "raw_remove_events": int(global_counts["raw_remove_events"]),
        "duplicate_events": int(global_counts["duplicate_events"]),
        "pool_registry_misses": int(global_counts["pool_registry_misses"]),
        "identity_conflicts": int(global_counts["identity_conflicts"]),
        "invalid_timestamp_events": int(global_counts["invalid_timestamp_events"]),
        "partition_day_mismatches": int(global_counts["partition_day_mismatches"]),
        "needs_complete_events": int(global_counts["needs_complete_events"]),
        "full_price_events": int(global_counts["full_price_events"]),
        "one_price_events": int(global_counts["one_price_events"]),
        "missing_price_events": int(global_counts["missing_price_events"]),
        "nonpositive_amount_events": int(global_counts["nonpositive_amount_events"]),
        "above_screen_events": int(global_counts["above_screen_events"]),
        "valid_liquidity_events": int(global_counts["valid_liquidity_events"]),
        "missing_invalid_liquidity_events": int(
            global_counts["missing_invalid_liquidity_events"]
        ),
        "max_event_usd": float(max_event_usd),
        "max_seen_event_usd": float(max_seen_usd),
        "event_pool_days": int(len(flows)),
    }
    return flows, support


FLOW_ZERO_COLUMNS = (
    "v2_raw_add_events",
    "v2_raw_remove_events",
    "v2_add_events_valued",
    "v2_remove_events_valued",
    "v2_add_lp_flow_usd",
    "v2_remove_lp_flow_usd",
    "v2_gross_lp_flow_usd",
    "v2_net_add_lp_flow_usd",
    "v2_add_token0_flow_usd_priced",
    "v2_remove_token0_flow_usd_priced",
    "v2_add_token1_flow_usd_priced",
    "v2_remove_token1_flow_usd_priced",
    "v2_add_liquidity",
    "v2_remove_liquidity",
    "v2_gross_liquidity",
    "v2_net_add_liquidity",
    "v2_needs_complete_add_liquidity",
    "v2_needs_complete_remove_liquidity",
    "v2_one_price_events",
    "v2_missing_price_events",
    "v2_nonpositive_amount_events",
    "v2_above_screen_events",
    "v2_needs_complete_events",
    "v2_missing_invalid_liquidity_events",
    "v2_transaction_count",
    "v2_sender_count",
    "v2_recipient_count",
    "v2_origin_count",
)


def assemble_v2_lp_flow_panel(
    calendar: pd.DataFrame,
    flows: pd.DataFrame,
    pool_registry: pd.DataFrame,
    *,
    capital_path: Path = POOL_CAPITAL_DAILY,
) -> pd.DataFrame:
    """Join event flows to the raw calendar and exact processed pool states."""

    panel = calendar.merge(flows, on=["origin_date", "pool"], how="outer")
    panel = panel.merge(pool_registry, on="pool", how="left", validate="many_to_one")
    if panel[["token0_address", "token1_address"]].isna().any(axis=None):
        raise ValueError("V2 LP-flow panel contains pools outside the exact registry")
    panel["venue"] = "uniswap_v2"
    panel["v2_lp_fee_rate"] = np.where(
        pd.to_datetime(panel["origin_date"]).lt(
            UNISWAP_V2_PROTOCOL_FEE_FIRST_FULL_DAY
        ),
        UNISWAP_V2_LP_FEE_RATE_BEFORE_SWITCH,
        UNISWAP_V2_LP_FEE_RATE_AFTER_SWITCH,
    )
    panel["v2_volume_usd"] = pd.to_numeric(
        panel["v2_volume_usd"], errors="coerce"
    ).fillna(0.0)
    panel["v2_fee_opportunity_usd"] = (
        panel["v2_lp_fee_rate"] * panel["v2_volume_usd"]
    )
    panel["raw_pool_day_rows"] = panel["raw_pool_day_rows"].fillna(0).astype(int)
    panel["invalid_volume_rows"] = panel["invalid_volume_rows"].fillna(0).astype(int)
    panel["v2_volume_support_status"] = panel[
        "v2_volume_support_status"
    ].fillna("event_only_no_provider_pool_day")
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
                WHERE venue = 'uniswap_v2'
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
            LEFT JOIN capital c
              ON b.day_key = c.day AND b.pool = c.pool
            ORDER BY b.origin_date, b.pool
            """,
            [str(capital_path)],
        ).fetchdf()
    finally:
        connection.close()
    return joined


def validate_v2_lp_flow_panel(panel: pd.DataFrame) -> None:
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
        "v2_flow_valuation_status",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"V2 LP-flow panel lacks columns: {missing}")
    if panel.empty or panel.duplicated(["origin_date", "pool"]).any():
        raise ValueError("V2 LP-flow panel is empty or not unique by pool-day")
    if not panel["venue"].eq("uniswap_v2").all():
        raise ValueError("V2 LP-flow panel contains another venue")
    for column in (
        "v2_volume_usd",
        "v2_fee_opportunity_usd",
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
    ):
        values = pd.to_numeric(panel[column], errors="coerce")
        if values.isna().any() or values.lt(0).any() or not np.isfinite(values).all():
            raise ValueError(f"V2 LP-flow panel has invalid {column}")
    if not np.allclose(
        panel["v2_gross_lp_flow_usd"],
        panel["v2_add_lp_flow_usd"] + panel["v2_remove_lp_flow_usd"],
    ):
        raise ValueError("V2 gross USD flow does not equal adds plus removes")
    if not np.allclose(
        panel["v2_net_add_lp_flow_usd"],
        panel["v2_add_lp_flow_usd"] - panel["v2_remove_lp_flow_usd"],
    ):
        raise ValueError("V2 net USD flow does not equal adds minus removes")
    if not np.allclose(
        panel["v2_fee_opportunity_usd"],
        panel["v2_lp_fee_rate"] * panel["v2_volume_usd"],
    ):
        raise ValueError("V2 fee opportunity does not equal the dated LP fee rate")


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = EVENT_DIR,
    capital_path: Path = POOL_CAPITAL_DAILY,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_event_usd: float = MAX_EVENT_USD,
) -> int:
    registry = load_v2_pool_registry(capital_path)
    calendar, calendar_support = load_raw_v2_pool_day_calendar(event_dir)
    flows, flow_support = load_raw_uniswap_v2_lp_flows(
        event_dir=event_dir,
        pool_registry=registry,
        price_path=price_path,
        max_event_usd=max_event_usd,
    )
    panel = assemble_v2_lp_flow_panel(
        calendar,
        flows,
        registry,
        capital_path=capital_path,
    )
    validate_v2_lp_flow_panel(panel)
    with atomic_output(output_path) as temporary:
        panel.to_parquet(temporary, index=False)
    eventless = panel["v2_raw_add_events"].add(panel["v2_raw_remove_events"]).eq(0)
    support = {
        "record_type": "v2_lp_flow_pool_daily_support",
        "analysis_status": "processed_liquidity_supply_input",
        "venue": "uniswap_v2",
        "lp_fee_rate_before_switch": UNISWAP_V2_LP_FEE_RATE_BEFORE_SWITCH,
        "lp_fee_rate_after_switch": UNISWAP_V2_LP_FEE_RATE_AFTER_SWITCH,
        "protocol_fee_activation_utc": UNISWAP_V2_PROTOCOL_FEE_ACTIVATION_UTC,
        "protocol_fee_first_full_day": str(
            UNISWAP_V2_PROTOCOL_FEE_FIRST_FULL_DAY.date()
        ),
        "activation_day_treatment": (
            "2025-12-27 retained at 30 bp because daily volume cannot be split; "
            "event study drops the 2025-12-22 through 2025-12-28 partial week"
        ),
        "price_source": CAPITAL_PRICE_SOURCE,
        "price_validation_status": CAPITAL_PRICE_VALIDATION_STATUS,
        "pool_day_rows": int(len(panel)),
        "pools": int(panel["pool"].nunique()),
        "first_origin_date": str(pd.to_datetime(panel["origin_date"]).min().date()),
        "last_origin_date": str(pd.to_datetime(panel["origin_date"]).max().date()),
        "eventless_pool_days": int(eventless.sum()),
        "capital_state_match_share": float(panel["v2_reserve0"].notna().mean()),
        "flow_quantity": (
            "actual Mint/Burn token flows with two-sided canonical USD valuation; "
            "raw liquidity units retained separately; excludes fee accrual, reserve "
            "revaluation, and capital-stock-implied changes"
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
    print(f"wrote {len(panel):,} Uniswap V2 LP-flow pool-days to {label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--capital", type=Path, default=POOL_CAPITAL_DAILY)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument("--max-event-usd", type=float, default=MAX_EVENT_USD)
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        capital_path=args.capital,
        price_path=args.price,
        max_event_usd=args.max_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
