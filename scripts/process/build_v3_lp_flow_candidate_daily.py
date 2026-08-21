#!/usr/bin/env python3
"""Build screened Uniswap V3 candidate-side LP flow from mint/burn events.

Reads:
  data/raw/thegraph/uniswap_v3/uniswap_v3_mints_*.jsonl.gz
  data/raw/thegraph/uniswap_v3/uniswap_v3_burns_*.jsonl.gz
  data/processed/token_price_daily.parquet
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v3_lp_flow_candidate_daily.parquet
  output/exhibits/v3_lp_flow_candidate_daily_support.jsonl

The output is a dollarized candidate-side flow panel. It values the candidate
token side of V3 mint and burn events using the audited canonical token-price
panel and screens physically impossible single candidate-side event values.

This is not a pool TVL stock, not a true LP-wallet inventory, and not active
executable liquidity inside the current tick. It is the V3 analogue of the V4
candidate-side modify-liquidity flow panel: how much candidate-token value LPs
add/remove through concentrated-liquidity position changes.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.capital_validation import validated_capital_prices
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
V3_POOL_DAY_FEES_INPUT = REPO_ROOT / "data/processed/v3_pool_day_fees.parquet"
UNISWAP_V3_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v3"
OUTPUT = REPO_ROOT / "data/processed/v3_lp_flow_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_flow_candidate_daily_support.jsonl"
MAX_CANDIDATE_SIDE_EVENT_USD = 100_000_000.0

CODE_SOURCES = [
    "scripts/process/build_v3_lp_flow_candidate_daily.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v3",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/token_price_daily.parquet",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _event_date(event: dict[str, object]) -> pd.Timestamp:
    timestamp = int(
        event.get("timestamp")
        or (event.get("transaction") or {}).get("timestamp")
        or 0
    )
    return pd.Timestamp(datetime.fromtimestamp(timestamp, tz=timezone.utc).date())


def _event_day(event: dict[str, object]) -> str:
    return _event_date(event).strftime("%Y%m%d")


def _range_bucket(event: dict[str, object]) -> str:
    try:
        width = int(event.get("tickUpper")) - int(event.get("tickLower"))
    except (TypeError, ValueError):
        return "unknown"
    if width >= 1_774_440:
        return "full_range"
    if width >= 200_000:
        return "very_wide"
    if width >= 10_000:
        return "wide"
    if width >= 1_000:
        return "medium"
    return "narrow"


def _range_counter_key(range_bucket: str) -> str:
    if range_bucket == "full_range":
        return "full_range"
    return range_bucket


def _price_lookup(price_path: Path = TOKEN_PRICE_DAILY_PANEL) -> dict[tuple[str, str], float]:
    prices = validated_capital_prices(price_path)
    return {
        (str(row.day), str(row.token).lower()): float(row.price_usd)
        for row in prices.itertuples(index=False)
    }


def vehicle_candidate_map(path: Path = CANDIDATE_DAY_INPUT) -> dict[str, tuple[str, str]]:
    """Return raw token-address to canonical candidate address and symbol."""

    frame = pd.read_parquet(path, columns=["candidate_address", "candidate_symbol"])
    observed = {
        str(row.candidate_address).lower(): str(row.candidate_symbol)
        for row in frame.drop_duplicates().itertuples(index=False)
    }
    mapping = {
        address: (address, symbol)
        for address, symbol in VEHICLE_CANDIDATES.items()
        if address in observed
    }
    if not mapping:
        raise ValueError("candidate-day panel has no canonical vehicle candidates")
    return mapping


def v3_pool_candidate_sides(
    *,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    candidate_map: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """Map V3 pools to candidate token sides using the pool-day fee registry."""

    if not candidate_map:
        raise ValueError("candidate map is empty")
    candidate_addresses = sorted(candidate_map)
    connection = duckdb.connect()
    try:
        connection.register(
            "candidate_addresses",
            pd.DataFrame({"candidate_address": candidate_addresses}),
        )
        sides = connection.execute(
            """
            SELECT DISTINCT lower(pool) AS pool,
                   0::INTEGER AS side_index,
                   lower(token0_address) AS candidate_address,
                   token0_symbol AS candidate_symbol
            FROM read_parquet(?)
            WHERE lower(token0_address) IN (SELECT * FROM candidate_addresses)
            UNION
            SELECT DISTINCT lower(pool) AS pool,
                   1::INTEGER AS side_index,
                   lower(token1_address) AS candidate_address,
                   token1_symbol AS candidate_symbol
            FROM read_parquet(?)
            WHERE lower(token1_address) IN (SELECT * FROM candidate_addresses)
            """,
            [str(fee_panel_path), str(fee_panel_path)],
        ).fetchdf()
    finally:
        connection.close()
    if sides.empty:
        raise ValueError("no Uniswap V3 pool sides match vehicle candidates")
    sides["candidate_address"] = sides["candidate_address"].astype(str).str.lower()
    sides["candidate_symbol"] = sides["candidate_address"].map(
        {address: symbol for address, (_address, symbol) in candidate_map.items()}
    )
    if sides["candidate_symbol"].isna().any():
        raise ValueError("pool-side registry produced an unknown candidate")
    return sides.sort_values(
        ["pool", "side_index", "candidate_address"]
    ).reset_index(drop=True)


def _pool_side_map(
    pool_candidate_sides: pd.DataFrame | None,
) -> dict[str, list[tuple[int, str, str, str]]]:
    if pool_candidate_sides is None:
        return {}
    required = {"pool", "side_index", "candidate_address", "candidate_symbol"}
    missing = sorted(required - set(pool_candidate_sides.columns))
    if missing:
        raise ValueError(f"pool-candidate sides lack columns: {missing}")
    result: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    for row in pool_candidate_sides.itertuples(index=False):
        candidate_address = str(row.candidate_address).lower()
        result[str(row.pool).lower()].append(
            (
                int(row.side_index),
                candidate_address,
                str(row.candidate_symbol),
                candidate_address,
            )
        )
    return result


def _candidate_sides(
    event: dict[str, object],
    candidate_map: dict[str, tuple[str, str]],
    pool_sides: dict[str, list[tuple[int, str, str, str]]],
) -> list[tuple[int, str, str, str]]:
    pool = event.get("pool") or {}
    pool_id = str(pool.get("id") or "").lower()
    if pool_id in pool_sides:
        return pool_sides[pool_id]
    sides: list[tuple[int, str, str, str]] = []
    for side_index, token_key in enumerate(("token0", "token1")):
        token = pool.get(token_key) or {}
        raw_address = str(token.get("id") or "").lower()
        candidate = candidate_map.get(raw_address)
        if candidate is None:
            continue
        candidate_address, candidate_symbol = candidate
        sides.append((side_index, candidate_address, candidate_symbol, raw_address))
    return sides


def load_raw_uniswap_v3_lp_flows(
    *,
    event_dir: Path = UNISWAP_V3_EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
    pool_candidate_sides: pd.DataFrame | None = None,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
    retain_pool: bool = False,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Value candidate-token sides of V3 mint/burn events by day.

    ``retain_pool`` keeps the pool address in the aggregation key for analyses
    of provider supply.  The default preserves the historical candidate-day
    output consumed by the protocol-comparison analyses.
    """

    prices = _price_lookup(price_path)
    pool_sides = _pool_side_map(pool_candidate_sides)
    counts: dict[tuple[object, ...], dict[str, object]] = defaultdict(
        lambda: {
            "candidate_side_assignments": 0,
            "priced_candidate_side_assignments": 0,
            "screened_candidate_side_assignments": 0,
            "missing_price_assignments": 0,
            "nonpositive_value_assignments": 0,
            "above_screen_assignments": 0,
            "gross_lp_flow_usd": 0.0,
            "add_lp_flow_usd": 0.0,
            "remove_lp_flow_usd": 0.0,
            "narrow_flow_usd": 0.0,
            "medium_flow_usd": 0.0,
            "wide_flow_usd": 0.0,
            "very_wide_flow_usd": 0.0,
            "full_range_flow_usd": 0.0,
            "unknown_flow_usd": 0.0,
            "add_events": 0,
            "remove_events": 0,
            "add_actions": 0,
            "remove_actions": 0,
            "zero_liquidity_add_actions": 0,
            "zero_liquidity_remove_actions": 0,
            "negative_liquidity_add_actions": 0,
            "negative_liquidity_remove_actions": 0,
            "nonfinite_liquidity_add_actions": 0,
            "nonfinite_liquidity_remove_actions": 0,
            "narrow_events": 0,
            "medium_events": 0,
            "wide_events": 0,
            "very_wide_events": 0,
            "full_range_events": 0,
            "unknown_events": 0,
            "origins": set(),
            "senders": set(),
            "add_transactions": set(),
            "remove_transactions": set(),
            "add_transaction_flow_usd": defaultdict(float),
            "remove_transaction_flow_usd": defaultdict(float),
        }
    )
    event_files = 0
    raw_events = 0
    matched_events = 0
    global_counts = Counter()
    max_seen_usd = 0.0

    for event_type, pattern in (
        ("add", "uniswap_v3_mints_*.jsonl.gz"),
        ("remove", "uniswap_v3_burns_*.jsonl.gz"),
    ):
        for path in sorted(event_dir.glob(pattern)):
            event_files += 1
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw_events += 1
                    event = json.loads(line)
                    candidate_sides = _candidate_sides(
                        event,
                        candidate_map,
                        pool_sides,
                    )
                    if not candidate_sides:
                        continue
                    matched_events += 1
                    origin_date = _event_date(event)
                    day = _event_day(event)
                    origin = str(event.get("origin") or event.get("owner") or "").lower()
                    sender = str(
                        event.get("sender")
                        or event.get("owner")
                        or event.get("origin")
                        or ""
                    ).lower()
                    transaction_id = str(
                        (event.get("transaction") or {}).get("id")
                        or ""
                    ).lower()
                    range_bucket = _range_bucket(event)
                    range_key = _range_counter_key(range_bucket)
                    liquidity_amount = float(_decimal(event.get("amount")))
                    positive_liquidity_action = (
                        np.isfinite(liquidity_amount) and liquidity_amount > 0
                    )
                    negative_liquidity_action = (
                        np.isfinite(liquidity_amount) and liquidity_amount < 0
                    )
                    nonfinite_liquidity_action = not np.isfinite(liquidity_amount)
                    for (
                        side_index,
                        candidate_address,
                        candidate_symbol,
                        price_address,
                    ) in candidate_sides:
                        pool_id = str((event.get("pool") or {}).get("id") or "").lower()
                        if retain_pool and not pool_id:
                            global_counts["missing_pool_assignments"] += 1
                            continue
                        key = (
                            (origin_date, pool_id, candidate_address, candidate_symbol)
                            if retain_pool
                            else (origin_date, candidate_address, candidate_symbol)
                        )
                        bucket = counts[key]
                        bucket["candidate_side_assignments"] = (
                            int(bucket["candidate_side_assignments"]) + 1
                        )
                        if positive_liquidity_action:
                            bucket[f"{event_type}_actions"] = (
                                int(bucket[f"{event_type}_actions"]) + 1
                            )
                            global_counts[f"positive_liquidity_{event_type}_actions"] += 1
                            if transaction_id:
                                bucket[f"{event_type}_transactions"].add(
                                    transaction_id
                                )
                            else:
                                global_counts[
                                    "positive_liquidity_missing_transaction_assignments"
                                ] += 1
                        elif nonfinite_liquidity_action:
                            bucket[f"nonfinite_liquidity_{event_type}_actions"] = (
                                int(
                                    bucket[
                                        f"nonfinite_liquidity_{event_type}_actions"
                                    ]
                                )
                                + 1
                            )
                            global_counts[
                                f"nonfinite_liquidity_{event_type}_actions"
                            ] += 1
                        elif negative_liquidity_action:
                            bucket[f"negative_liquidity_{event_type}_actions"] = (
                                int(
                                    bucket[
                                        f"negative_liquidity_{event_type}_actions"
                                    ]
                                )
                                + 1
                            )
                            global_counts[
                                f"negative_liquidity_{event_type}_actions"
                            ] += 1
                        else:
                            bucket[f"zero_liquidity_{event_type}_actions"] = (
                                int(bucket[f"zero_liquidity_{event_type}_actions"]) + 1
                            )
                            global_counts[f"zero_liquidity_{event_type}_actions"] += 1
                        global_counts["candidate_side_assignments"] += 1
                        bucket["origins"].add(origin)
                        bucket["senders"].add(sender)
                        if not positive_liquidity_action:
                            continue

                        price = prices.get((day, price_address))
                        if price is None:
                            bucket["missing_price_assignments"] = (
                                int(bucket["missing_price_assignments"]) + 1
                            )
                            global_counts["missing_price_assignments"] += 1
                            continue
                        amount = abs(float(_decimal(event.get(f"amount{side_index}"))))
                        value = amount * price
                        if not np.isfinite(value) or value <= 0:
                            bucket["nonpositive_value_assignments"] = (
                                int(bucket["nonpositive_value_assignments"]) + 1
                            )
                            global_counts["nonpositive_value_assignments"] += 1
                            continue
                        bucket["priced_candidate_side_assignments"] = (
                            int(bucket["priced_candidate_side_assignments"]) + 1
                        )
                        global_counts["priced_candidate_side_assignments"] += 1
                        max_seen_usd = max(max_seen_usd, float(value))
                        if value > max_candidate_side_event_usd:
                            bucket["above_screen_assignments"] = (
                                int(bucket["above_screen_assignments"]) + 1
                            )
                            global_counts["above_screen_assignments"] += 1
                            continue

                        bucket["screened_candidate_side_assignments"] = (
                            int(bucket["screened_candidate_side_assignments"]) + 1
                        )
                        bucket["gross_lp_flow_usd"] = float(bucket["gross_lp_flow_usd"]) + value
                        bucket[f"{event_type}_lp_flow_usd"] = (
                            float(bucket[f"{event_type}_lp_flow_usd"]) + value
                        )
                        if positive_liquidity_action and transaction_id:
                            bucket[f"{event_type}_transaction_flow_usd"][
                                transaction_id
                            ] += value
                        bucket[f"{range_key}_flow_usd"] = (
                            float(bucket[f"{range_key}_flow_usd"]) + value
                        )
                        bucket[f"{event_type}_events"] = int(bucket[f"{event_type}_events"]) + 1
                        bucket[f"{range_key}_events"] = int(bucket[f"{range_key}_events"]) + 1
                        global_counts["screened_candidate_side_assignments"] += 1

    rows: list[dict[str, object]] = []
    for key, bucket in counts.items():
        if retain_pool:
            origin_date, pool_id, candidate_address, candidate_symbol = key
        else:
            origin_date, candidate_address, candidate_symbol = key
            pool_id = None
        gross = float(bucket["gross_lp_flow_usd"])
        add = float(bucket["add_lp_flow_usd"])
        remove = float(bucket["remove_lp_flow_usd"])
        narrow_medium = float(bucket["narrow_flow_usd"]) + float(bucket["medium_flow_usd"])
        broad = (
            float(bucket["wide_flow_usd"])
            + float(bucket["very_wide_flow_usd"])
            + float(bucket["full_range_flow_usd"])
        )
        add_transactions = set(bucket["add_transactions"])
        remove_transactions = set(bucket["remove_transactions"])
        reposition_transactions = add_transactions & remove_transactions
        add_transaction_flow = dict(bucket["add_transaction_flow_usd"])
        remove_transaction_flow = dict(bucket["remove_transaction_flow_usd"])
        add_only_flow = sum(
            value
            for transaction, value in add_transaction_flow.items()
            if transaction not in remove_transactions
        )
        remove_only_flow = sum(
            value
            for transaction, value in remove_transaction_flow.items()
            if transaction not in add_transactions
        )
        reposition_add_flow = sum(
            add_transaction_flow.get(transaction, 0.0)
            for transaction in reposition_transactions
        )
        reposition_remove_flow = sum(
            remove_transaction_flow.get(transaction, 0.0)
            for transaction in reposition_transactions
        )
        row = {
                "origin_date": origin_date,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "v3_lp_flow_candidate_side_assignments": int(
                    bucket["candidate_side_assignments"]
                ),
                "v3_lp_flow_priced_assignments": int(
                    bucket["priced_candidate_side_assignments"]
                ),
                "v3_lp_flow_screened_assignments": int(
                    bucket["screened_candidate_side_assignments"]
                ),
                "v3_lp_flow_missing_price_assignments": int(
                    bucket["missing_price_assignments"]
                ),
                "v3_lp_flow_nonpositive_value_assignments": int(
                    bucket["nonpositive_value_assignments"]
                ),
                "v3_lp_flow_above_screen_assignments": int(
                    bucket["above_screen_assignments"]
                ),
                "v3_gross_lp_flow_usd_screened": gross,
                "v3_add_lp_flow_usd_screened": add,
                "v3_remove_lp_flow_usd_screened": remove,
                "v3_net_add_lp_flow_usd_screened": add - remove,
                "v3_add_only_lp_flow_usd_screened": add_only_flow,
                "v3_remove_only_lp_flow_usd_screened": remove_only_flow,
                "v3_net_add_remove_only_lp_flow_usd_screened": (
                    add_only_flow - remove_only_flow
                ),
                "v3_reposition_add_lp_flow_usd_screened": reposition_add_flow,
                "v3_reposition_remove_lp_flow_usd_screened": (
                    reposition_remove_flow
                ),
                "v3_narrow_flow_usd_screened": float(bucket["narrow_flow_usd"]),
                "v3_medium_flow_usd_screened": float(bucket["medium_flow_usd"]),
                "v3_wide_flow_usd_screened": float(bucket["wide_flow_usd"]),
                "v3_very_wide_flow_usd_screened": float(bucket["very_wide_flow_usd"]),
                "v3_full_range_flow_usd_screened": float(bucket["full_range_flow_usd"]),
                "v3_unknown_range_flow_usd_screened": float(bucket["unknown_flow_usd"]),
                "v3_narrow_medium_flow_usd_screened": narrow_medium,
                "v3_broad_flow_usd_screened": broad,
                "v3_narrow_medium_flow_value_share": (
                    narrow_medium / gross if gross > 0 else np.nan
                ),
                "v3_broad_flow_value_share": broad / gross if gross > 0 else np.nan,
                "v3_add_flow_value_share": add / gross if gross > 0 else np.nan,
                "v3_remove_flow_value_share": remove / gross if gross > 0 else np.nan,
                "v3_add_flow_events_screened": int(bucket["add_events"]),
                "v3_remove_flow_events_screened": int(bucket["remove_events"]),
                "v3_add_action_events": int(bucket["add_actions"]),
                "v3_remove_action_events": int(bucket["remove_actions"]),
                "v3_gross_action_events": int(bucket["add_actions"])
                + int(bucket["remove_actions"]),
                "v3_net_add_action_events": int(bucket["add_actions"])
                - int(bucket["remove_actions"]),
                "v3_add_action_transactions": len(add_transactions),
                "v3_remove_action_transactions": len(remove_transactions),
                "v3_reposition_action_transactions": len(reposition_transactions),
                "v3_add_only_action_transactions": len(
                    add_transactions - remove_transactions
                ),
                "v3_remove_only_action_transactions": len(
                    remove_transactions - add_transactions
                ),
                "v3_zero_liquidity_add_events": int(
                    bucket["zero_liquidity_add_actions"]
                ),
                "v3_zero_liquidity_remove_events": int(
                    bucket["zero_liquidity_remove_actions"]
                ),
                "v3_negative_liquidity_add_events": int(
                    bucket["negative_liquidity_add_actions"]
                ),
                "v3_negative_liquidity_remove_events": int(
                    bucket["negative_liquidity_remove_actions"]
                ),
                "v3_nonfinite_liquidity_add_events": int(
                    bucket["nonfinite_liquidity_add_actions"]
                ),
                "v3_nonfinite_liquidity_remove_events": int(
                    bucket["nonfinite_liquidity_remove_actions"]
                ),
                "v3_narrow_flow_events_screened": int(bucket["narrow_events"]),
                "v3_medium_flow_events_screened": int(bucket["medium_events"]),
                "v3_wide_flow_events_screened": int(bucket["wide_events"]),
                "v3_very_wide_flow_events_screened": int(bucket["very_wide_events"]),
                "v3_full_range_flow_events_screened": int(bucket["full_range_events"]),
                "v3_unknown_flow_events_screened": int(bucket["unknown_events"]),
                "v3_lp_flow_origin_count": len(bucket["origins"]),
                "v3_lp_flow_sender_count": len(bucket["senders"]),
            }
        if retain_pool:
            row["pool"] = pool_id
        else:
            for pool_only_column in (
                "v3_add_only_lp_flow_usd_screened",
                "v3_remove_only_lp_flow_usd_screened",
                "v3_net_add_remove_only_lp_flow_usd_screened",
                "v3_reposition_add_lp_flow_usd_screened",
                "v3_reposition_remove_lp_flow_usd_screened",
                "v3_add_action_transactions",
                "v3_remove_action_transactions",
                "v3_reposition_action_transactions",
                "v3_add_only_action_transactions",
                "v3_remove_only_action_transactions",
            ):
                row.pop(pool_only_column)
        rows.append(row)
    flows = pd.DataFrame(rows)
    if not flows.empty:
        sort_columns = ["origin_date"]
        if retain_pool:
            sort_columns.append("pool")
        sort_columns.extend(["candidate_symbol", "candidate_address"])
        flows = flows.sort_values(
            sort_columns
        ).reset_index(drop=True)
    support = {
        "record_type": "v3_lp_flow_support",
        "analysis_status": "exploratory_mechanism",
        "event_source": "uniswap_v3_graph_mint_burn_events",
        "event_dir": str(event_dir.relative_to(REPO_ROOT))
        if event_dir.is_relative_to(REPO_ROOT)
        else str(event_dir),
        "price_source": "canonical_repriced_route_legs_with_address_time_sanity",
        "event_files": int(event_files),
        "raw_mint_burn_events": int(raw_events),
        "matched_candidate_events": int(matched_events),
        "candidate_side_assignments": int(global_counts["candidate_side_assignments"]),
        "priced_candidate_side_assignments": int(
            global_counts["priced_candidate_side_assignments"]
        ),
        "screened_candidate_side_assignments": int(
            global_counts["screened_candidate_side_assignments"]
        ),
        "missing_price_assignments": int(global_counts["missing_price_assignments"]),
        "nonpositive_value_assignments": int(
            global_counts["nonpositive_value_assignments"]
        ),
        "above_screen_assignments": int(global_counts["above_screen_assignments"]),
        "max_candidate_side_event_usd": float(max_candidate_side_event_usd),
        "max_seen_candidate_side_event_usd": float(max_seen_usd),
        "candidate_day_flow_rows": int(len(flows)),
        "candidate_addresses": int(
            flows["candidate_address"].nunique() if not flows.empty else 0
        ),
        "pool_candidate_sides": int(
            len(pool_candidate_sides) if pool_candidate_sides is not None else 0
        ),
        "aggregation_unit": "pool_candidate_day" if retain_pool else "candidate_day",
        "missing_pool_assignments": int(global_counts["missing_pool_assignments"]),
        "positive_liquidity_add_actions": int(
            global_counts["positive_liquidity_add_actions"]
        ),
        "positive_liquidity_remove_actions": int(
            global_counts["positive_liquidity_remove_actions"]
        ),
        "zero_liquidity_add_events": int(
            global_counts["zero_liquidity_add_actions"]
        ),
        "zero_liquidity_remove_events": int(
            global_counts["zero_liquidity_remove_actions"]
        ),
        "negative_liquidity_add_events": int(
            global_counts["negative_liquidity_add_actions"]
        ),
        "negative_liquidity_remove_events": int(
            global_counts["negative_liquidity_remove_actions"]
        ),
        "nonfinite_liquidity_add_events": int(
            global_counts["nonfinite_liquidity_add_actions"]
        ),
        "nonfinite_liquidity_remove_events": int(
            global_counts["nonfinite_liquidity_remove_actions"]
        ),
        "positive_liquidity_missing_transaction_assignments": int(
            global_counts["positive_liquidity_missing_transaction_assignments"]
        ),
        "first_origin_date": (
            str(flows["origin_date"].min().date()) if not flows.empty else None
        ),
        "last_origin_date": (
            str(flows["origin_date"].max().date()) if not flows.empty else None
        ),
        "quantity": (
            "screened candidate-token-side USD value of V3 mint/burn events; "
            "not whole-pool TVL, true LP inventory, or active executable depth"
        ),
    }
    return flows, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V3_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
) -> int:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    pool_sides = v3_pool_candidate_sides(
        fee_panel_path=fee_panel_path,
        candidate_map=candidate_map,
    )
    flows, support = load_raw_uniswap_v3_lp_flows(
        event_dir=event_dir,
        candidate_map=candidate_map,
        pool_candidate_sides=pool_sides,
        price_path=price_path,
        max_candidate_side_event_usd=max_candidate_side_event_usd,
    )
    with atomic_output(output_path) as temporary:
        flows.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    output_label = (
        output_path.relative_to(REPO_ROOT)
        if output_path.is_relative_to(REPO_ROOT)
        else output_path
    )
    print(
        f"wrote {len(flows):,} V3 LP-flow candidate-day rows to "
        f"{output_label}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V3_EVENT_DIR)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--fee-panel", type=Path, default=V3_POOL_DAY_FEES_INPUT)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument(
        "--max-candidate-side-event-usd",
        type=float,
        default=MAX_CANDIDATE_SIDE_EVENT_USD,
    )
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        candidate_day_path=args.candidate_day,
        fee_panel_path=args.fee_panel,
        price_path=args.price,
        max_candidate_side_event_usd=args.max_candidate_side_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
