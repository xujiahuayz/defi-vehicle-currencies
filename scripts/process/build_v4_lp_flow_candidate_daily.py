#!/usr/bin/env python3
"""Build screened Uniswap V4 candidate-side LP flow from modify-liquidity events.

Reads:
  data/raw/thegraph/uniswap_v4/uniswap_v4_modify_liquidities_*.jsonl.gz
  data/processed/token_price_daily.parquet
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v4_lp_flow_candidate_daily.parquet
  output/exhibits/v4_lp_flow_candidate_daily_support.jsonl

The output is a dollarized candidate-side flow panel. It values the candidate
token side of V4 modify-liquidity events using the audited canonical token-price
panel and screens physically impossible single candidate-side event values.

This is not a pool TVL stock, not a true LP-wallet inventory, and not a claim
about the whole two-sided pool. It is a comparable LP behavior measure: how much
candidate-token value LPs add/remove through V4 position modifications.
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

from ddvc.asset_types import NATIVE_ETH, VEHICLE_CANDIDATES, WETH
from ddvc.capital_validation import validated_capital_prices
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
UNISWAP_V4_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
OUTPUT = REPO_ROOT / "data/processed/v4_lp_flow_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_flow_candidate_daily_support.jsonl"
MAX_CANDIDATE_SIDE_EVENT_USD = 100_000_000.0
NATIVE_ETH_ADDRESS = NATIVE_ETH
WETH_ADDRESS = WETH

CODE_SOURCES = [
    "scripts/process/build_v4_lp_flow_candidate_daily.py",
    "scripts/process/build_v4_lp_action_candidate_daily.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
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
    expected = {
        address: symbol
        for address, symbol in VEHICLE_CANDIDATES.items()
        if address in observed
    }
    if not expected:
        raise ValueError("candidate-day panel has no canonical vehicle candidates")
    mapping = {
        address: (address, symbol)
        for address, symbol in expected.items()
    }
    mapping[NATIVE_ETH_ADDRESS] = (WETH_ADDRESS, VEHICLE_CANDIDATES[WETH_ADDRESS])
    return mapping


def _candidate_sides(
    event: dict[str, object],
    candidate_map: dict[str, tuple[str, str]],
) -> list[tuple[int, str, str, str]]:
    pool = event.get("pool") or {}
    sides: list[tuple[int, str, str, str]] = []
    for side_index, token_key in enumerate(("token0", "token1")):
        token = pool.get(token_key) or {}
        raw_address = str(token.get("id") or "").lower()
        candidate = candidate_map.get(raw_address)
        if candidate is None:
            continue
        candidate_address, candidate_symbol = candidate
        price_address = WETH_ADDRESS if raw_address == NATIVE_ETH_ADDRESS else candidate_address
        sides.append((side_index, candidate_address, candidate_symbol, price_address))
    return sides


def load_raw_uniswap_v4_lp_flows(
    *,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Value candidate-token sides of V4 modify-liquidity events by day."""

    prices = _price_lookup(price_path)
    counts: dict[tuple[pd.Timestamp, str, str], dict[str, object]] = defaultdict(
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
            "zero_liquidity_flow_usd": 0.0,
            "narrow_flow_usd": 0.0,
            "medium_flow_usd": 0.0,
            "wide_flow_usd": 0.0,
            "very_wide_flow_usd": 0.0,
            "full_range_flow_usd": 0.0,
            "unknown_flow_usd": 0.0,
            "add_events": 0,
            "remove_events": 0,
            "zero_liquidity_events": 0,
            "narrow_events": 0,
            "medium_events": 0,
            "wide_events": 0,
            "very_wide_events": 0,
            "full_range_events": 0,
            "unknown_events": 0,
            "origins": set(),
            "senders": set(),
        }
    )
    event_files = 0
    raw_events = 0
    matched_events = 0
    native_eth_assignments = 0
    global_counts = Counter()
    max_seen_usd = 0.0

    for path in sorted(event_dir.glob("uniswap_v4_modify_liquidities_*.jsonl.gz")):
        event_files += 1
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_events += 1
                event = json.loads(line)
                candidate_sides = _candidate_sides(event, candidate_map)
                if not candidate_sides:
                    continue
                matched_events += 1
                origin_date = _event_date(event)
                day = _event_day(event)
                origin = str(event.get("origin") or "").lower()
                sender = str(event.get("sender") or "").lower()
                liquidity_amount = _decimal(event.get("amount"))
                sign = (
                    "add"
                    if liquidity_amount > 0
                    else "remove"
                    if liquidity_amount < 0
                    else "zero_liquidity"
                )
                range_bucket = _range_bucket(event)
                range_key = _range_counter_key(range_bucket)
                pool = event.get("pool") or {}
                raw_token_addresses = {
                    str((pool.get("token0") or {}).get("id") or "").lower(),
                    str((pool.get("token1") or {}).get("id") or "").lower(),
                }
                for side_index, candidate_address, candidate_symbol, price_address in candidate_sides:
                    key = (origin_date, candidate_address, candidate_symbol)
                    bucket = counts[key]
                    bucket["candidate_side_assignments"] = (
                        int(bucket["candidate_side_assignments"]) + 1
                    )
                    global_counts["candidate_side_assignments"] += 1
                    bucket["origins"].add(origin)
                    bucket["senders"].add(sender)
                    if (
                        candidate_address == WETH_ADDRESS
                        and NATIVE_ETH_ADDRESS in raw_token_addresses
                    ):
                        native_eth_assignments += 1

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
                    bucket[f"{sign}_lp_flow_usd"] = (
                        float(bucket[f"{sign}_lp_flow_usd"]) + value
                    )
                    bucket[f"{range_key}_flow_usd"] = (
                        float(bucket[f"{range_key}_flow_usd"]) + value
                    )
                    bucket[f"{sign}_events"] = int(bucket[f"{sign}_events"]) + 1
                    bucket[f"{range_key}_events"] = int(bucket[f"{range_key}_events"]) + 1
                    global_counts["screened_candidate_side_assignments"] += 1

    rows: list[dict[str, object]] = []
    for (origin_date, candidate_address, candidate_symbol), bucket in counts.items():
        gross = float(bucket["gross_lp_flow_usd"])
        add = float(bucket["add_lp_flow_usd"])
        remove = float(bucket["remove_lp_flow_usd"])
        narrow_medium = float(bucket["narrow_flow_usd"]) + float(bucket["medium_flow_usd"])
        broad = (
            float(bucket["wide_flow_usd"])
            + float(bucket["very_wide_flow_usd"])
            + float(bucket["full_range_flow_usd"])
        )
        rows.append(
            {
                "origin_date": origin_date,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "v4_lp_flow_candidate_side_assignments": int(
                    bucket["candidate_side_assignments"]
                ),
                "v4_lp_flow_priced_assignments": int(
                    bucket["priced_candidate_side_assignments"]
                ),
                "v4_lp_flow_screened_assignments": int(
                    bucket["screened_candidate_side_assignments"]
                ),
                "v4_lp_flow_missing_price_assignments": int(
                    bucket["missing_price_assignments"]
                ),
                "v4_lp_flow_nonpositive_value_assignments": int(
                    bucket["nonpositive_value_assignments"]
                ),
                "v4_lp_flow_above_screen_assignments": int(
                    bucket["above_screen_assignments"]
                ),
                "v4_gross_lp_flow_usd_screened": gross,
                "v4_add_lp_flow_usd_screened": add,
                "v4_remove_lp_flow_usd_screened": remove,
                "v4_zero_liquidity_flow_usd_screened": float(
                    bucket["zero_liquidity_flow_usd"]
                ),
                "v4_net_add_lp_flow_usd_screened": add - remove,
                "v4_narrow_flow_usd_screened": float(bucket["narrow_flow_usd"]),
                "v4_medium_flow_usd_screened": float(bucket["medium_flow_usd"]),
                "v4_wide_flow_usd_screened": float(bucket["wide_flow_usd"]),
                "v4_very_wide_flow_usd_screened": float(bucket["very_wide_flow_usd"]),
                "v4_full_range_flow_usd_screened": float(bucket["full_range_flow_usd"]),
                "v4_unknown_range_flow_usd_screened": float(bucket["unknown_flow_usd"]),
                "v4_narrow_medium_flow_usd_screened": narrow_medium,
                "v4_broad_flow_usd_screened": broad,
                "v4_narrow_medium_flow_value_share": (
                    narrow_medium / gross if gross > 0 else np.nan
                ),
                "v4_broad_flow_value_share": broad / gross if gross > 0 else np.nan,
                "v4_add_flow_value_share": add / gross if gross > 0 else np.nan,
                "v4_remove_flow_value_share": remove / gross if gross > 0 else np.nan,
                "v4_add_flow_events_screened": int(bucket["add_events"]),
                "v4_remove_flow_events_screened": int(bucket["remove_events"]),
                "v4_zero_liquidity_flow_events_screened": int(
                    bucket["zero_liquidity_events"]
                ),
                "v4_narrow_flow_events_screened": int(bucket["narrow_events"]),
                "v4_medium_flow_events_screened": int(bucket["medium_events"]),
                "v4_wide_flow_events_screened": int(bucket["wide_events"]),
                "v4_very_wide_flow_events_screened": int(bucket["very_wide_events"]),
                "v4_full_range_flow_events_screened": int(bucket["full_range_events"]),
                "v4_unknown_range_flow_events_screened": int(bucket["unknown_events"]),
                "v4_lp_flow_origin_count": len(bucket["origins"]),
                "v4_lp_flow_sender_count": len(bucket["senders"]),
            }
        )
    flows = pd.DataFrame(rows)
    if not flows.empty:
        flows = flows.sort_values(
            ["origin_date", "candidate_symbol", "candidate_address"]
        ).reset_index(drop=True)
    support = {
        "record_type": "v4_lp_flow_support",
        "analysis_status": "exploratory_mechanism",
        "event_source": "uniswap_v4_graph_modify_liquidity_events",
        "event_dir": str(event_dir.relative_to(REPO_ROOT))
        if event_dir.is_relative_to(REPO_ROOT)
        else str(event_dir),
        "price_source": "canonical_repriced_route_legs_with_address_time_sanity",
        "event_files": int(event_files),
        "raw_modify_liquidity_events": int(raw_events),
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
        "first_origin_date": (
            str(flows["origin_date"].min().date()) if not flows.empty else None
        ),
        "last_origin_date": (
            str(flows["origin_date"].max().date()) if not flows.empty else None
        ),
        "native_eth_to_weth_assignments": int(native_eth_assignments),
        "native_eth_mapping": "native_eth_zero_address_to_weth_candidate_family",
        "quantity": (
            "screened candidate-token-side USD value of V4 modify-liquidity "
            "events; not whole-pool TVL, true LP inventory, or side-complete "
            "deposited capital stock"
        ),
    }
    return flows, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
) -> int:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    flows, support = load_raw_uniswap_v4_lp_flows(
        event_dir=event_dir,
        candidate_map=candidate_map,
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
        f"wrote {len(flows):,} V4 LP-flow candidate-day rows to "
        f"{output_label}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V4_EVENT_DIR)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
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
        price_path=args.price,
        max_candidate_side_event_usd=args.max_candidate_side_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
