#!/usr/bin/env python3
"""Build daily Uniswap V4 modify-liquidity action counts for vehicle candidates.

Reads:
  data/raw/thegraph/uniswap_v4/uniswap_v4_modify_liquidities_*.jsonl.gz
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v4_lp_action_candidate_daily.parquet
  output/exhibits/v4_lp_action_candidate_daily_support.jsonl

The output is an event-count panel. It is not a dollar-valued LP flow, inventory,
provider return, active concentrated-liquidity depth, or true LP-wallet panel.
Uniswap V4 reports native ETH with the zero address; this builder maps that
native reserve token to the WETH candidate family for five-candidate comparisons.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
UNISWAP_V4_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
OUTPUT = REPO_ROOT / "data/processed/v4_lp_action_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_action_candidate_daily_support.jsonl"

NATIVE_ETH_ADDRESS = "0x0000000000000000000000000000000000000000"
WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI_ADDRESS = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT_ADDRESS = "0xdac17f958d2ee523a2206206994597c13d831ec7"
WBTC_ADDRESS = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
DAI_ADDRESS = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

CODE_SOURCES = ["scripts/process/build_v4_lp_action_candidate_daily.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def vehicle_candidate_map(path: Path = CANDIDATE_DAY_INPUT) -> dict[str, tuple[str, str]]:
    """Return raw token-address to canonical candidate address and symbol."""

    frame = pd.read_parquet(path, columns=["candidate_address", "candidate_symbol"])
    mapping: dict[str, tuple[str, str]] = {}
    for row in frame.drop_duplicates().itertuples(index=False):
        address = str(row.candidate_address).lower()
        symbol = str(row.candidate_symbol)
        mapping[address] = (address, symbol)
    if not mapping:
        raise ValueError("candidate-day panel has no candidate addresses")
    if WETH_ADDRESS in mapping:
        mapping[NATIVE_ETH_ADDRESS] = mapping[WETH_ADDRESS]
    return mapping


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
        return "full_range_events"
    return f"{range_bucket}_range_events"


def _candidate_sides(
    event: dict[str, object],
    candidate_map: dict[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    pool = event.get("pool") or {}
    candidates: dict[str, tuple[str, str]] = {}
    for token_key in ("token0", "token1"):
        token = pool.get(token_key) or {}
        raw_address = str(token.get("id") or "").lower()
        candidate = candidate_map.get(raw_address)
        if candidate is not None:
            candidates[candidate[0]] = candidate
    return list(candidates.values())


def load_raw_uniswap_v4_lp_actions(
    *,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Count raw V4 modify-liquidity events by day and candidate token side."""

    counts: dict[tuple[pd.Timestamp, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "add_events": 0,
            "remove_events": 0,
            "zero_liquidity_events": 0,
            "add_origins": set(),
            "remove_origins": set(),
            "zero_origins": set(),
            "all_origins": set(),
            "all_senders": set(),
            "narrow_range_events": 0,
            "medium_range_events": 0,
            "wide_range_events": 0,
            "very_wide_range_events": 0,
            "full_range_events": 0,
            "unknown_range_events": 0,
        }
    )
    event_files = 0
    raw_events = 0
    matched_candidate_events = 0
    native_eth_assignments = 0
    raw_sign_counts = {"add": 0, "remove": 0, "zero": 0}
    raw_range_counts = {
        "narrow": 0,
        "medium": 0,
        "wide": 0,
        "very_wide": 0,
        "full_range": 0,
        "unknown": 0,
    }
    for path in sorted(event_dir.glob("uniswap_v4_modify_liquidities_*.jsonl.gz")):
        event_files += 1
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_events += 1
                event = json.loads(line)
                candidate_sides = _candidate_sides(event, candidate_map)
                amount = _decimal(event.get("amount"))
                sign = "add" if amount > 0 else "remove" if amount < 0 else "zero"
                raw_sign_counts[sign] += 1
                range_bucket = _range_bucket(event)
                raw_range_counts[range_bucket] += 1
                if not candidate_sides:
                    continue
                date = _event_date(event)
                origin = str(event.get("origin") or "").lower()
                sender = str(event.get("sender") or "").lower()
                pool = event.get("pool") or {}
                raw_token_addresses = {
                    str((pool.get("token0") or {}).get("id") or "").lower(),
                    str((pool.get("token1") or {}).get("id") or "").lower(),
                }
                for candidate_address, candidate_symbol in candidate_sides:
                    key = (date, candidate_address, candidate_symbol)
                    bucket = counts[key]
                    if sign == "add":
                        bucket["add_events"] = int(bucket["add_events"]) + 1
                        bucket["add_origins"].add(origin)
                    elif sign == "remove":
                        bucket["remove_events"] = int(bucket["remove_events"]) + 1
                        bucket["remove_origins"].add(origin)
                    else:
                        bucket["zero_liquidity_events"] = (
                            int(bucket["zero_liquidity_events"]) + 1
                        )
                        bucket["zero_origins"].add(origin)
                    bucket["all_origins"].add(origin)
                    bucket["all_senders"].add(sender)
                    range_key = _range_counter_key(range_bucket)
                    bucket[range_key] = int(bucket[range_key]) + 1
                    matched_candidate_events += 1
                    if (
                        candidate_address == WETH_ADDRESS
                        and NATIVE_ETH_ADDRESS in raw_token_addresses
                    ):
                        native_eth_assignments += 1

    rows: list[dict[str, object]] = []
    for (origin_date, candidate_address, candidate_symbol), bucket in counts.items():
        add_events = int(bucket["add_events"])
        remove_events = int(bucket["remove_events"])
        zero_events = int(bucket["zero_liquidity_events"])
        total_actions = add_events + remove_events + zero_events
        rows.append(
            {
                "origin_date": origin_date,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "v4_add_events": add_events,
                "v4_remove_events": remove_events,
                "v4_zero_liquidity_events": zero_events,
                "v4_total_lp_actions": total_actions,
                "v4_net_add_events": add_events - remove_events,
                "v4_add_origin_count": len(bucket["add_origins"]),
                "v4_remove_origin_count": len(bucket["remove_origins"]),
                "v4_zero_origin_count": len(bucket["zero_origins"]),
                "v4_total_origin_count": len(bucket["all_origins"]),
                "v4_sender_count": len(bucket["all_senders"]),
                "v4_narrow_range_events": int(bucket["narrow_range_events"]),
                "v4_medium_range_events": int(bucket["medium_range_events"]),
                "v4_wide_range_events": int(bucket["wide_range_events"]),
                "v4_very_wide_range_events": int(bucket["very_wide_range_events"]),
                "v4_full_range_events": int(bucket["full_range_events"]),
                "v4_unknown_range_events": int(bucket["unknown_range_events"]),
            }
        )
    actions = pd.DataFrame(rows)
    if not actions.empty:
        actions = actions.sort_values(
            ["origin_date", "candidate_symbol", "candidate_address"]
        ).reset_index(drop=True)
    support = {
        "record_type": "v4_lp_action_support",
        "analysis_status": "exploratory_descriptive",
        "event_source": "uniswap_v4_graph_modify_liquidity_events",
        "event_dir": str(event_dir.relative_to(REPO_ROOT))
        if event_dir.is_relative_to(REPO_ROOT)
        else str(event_dir),
        "event_files": int(event_files),
        "raw_modify_liquidity_events": int(raw_events),
        "matched_candidate_event_assignments": int(matched_candidate_events),
        "native_eth_to_weth_assignments": int(native_eth_assignments),
        "candidate_day_action_rows": int(len(actions)),
        "candidate_addresses": int(
            actions["candidate_address"].nunique() if not actions.empty else 0
        ),
        "raw_add_events": int(raw_sign_counts["add"]),
        "raw_remove_events": int(raw_sign_counts["remove"]),
        "raw_zero_liquidity_events": int(raw_sign_counts["zero"]),
        "raw_narrow_range_events": int(raw_range_counts["narrow"]),
        "raw_medium_range_events": int(raw_range_counts["medium"]),
        "raw_wide_range_events": int(raw_range_counts["wide"]),
        "raw_very_wide_range_events": int(raw_range_counts["very_wide"]),
        "raw_full_range_events": int(raw_range_counts["full_range"]),
        "raw_unknown_range_events": int(raw_range_counts["unknown"]),
        "native_eth_mapping": "native_eth_zero_address_to_weth_candidate_family",
        "quantity": (
            "modify-liquidity event counts, origin-days, sender-days, and range "
            "buckets; not dollar-valued provider flows or true LP identities"
        ),
    }
    return actions, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    actions, support = load_raw_uniswap_v4_lp_actions(
        event_dir=event_dir,
        candidate_map=candidate_map,
    )
    with atomic_output(output_path) as temporary:
        actions.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(actions):,} V4 LP-action candidate-day rows to "
        f"{output_path.relative_to(REPO_ROOT)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V4_EVENT_DIR)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        candidate_day_path=args.candidate_day,
    )


if __name__ == "__main__":
    raise SystemExit(main())
