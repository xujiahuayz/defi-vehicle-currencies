#!/usr/bin/env python3
"""Build screened V4 candidate-linked pool TVL from raw provider daily rows.

Reads:
  data/raw/thegraph/uniswap_v4/uniswap_v4_daily_*.jsonl.gz
  data/raw/thegraph/uniswap_v4/uniswap_v4_modify_liquidities_*.jsonl.gz
  data/raw/thegraph/uniswap_v4/uniswap_v4_swaps_*.jsonl.gz
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v4_candidate_linked_pool_tvl_daily.parquet
  output/exhibits/v4_candidate_linked_pool_tvl_daily_support.jsonl

This is a candidate-linked V4 pool-TVL measure, not side-specific deposited
capital. V4 provider daily rows report pool-level ``tvlUSD``. For a pool that
contains a vehicle candidate, the same full-pool TVL is linked to that candidate;
candidate-candidate pools therefore contribute to both candidate series. Rows are
usable only when pool identity is address-resolved and provider TVL/volume clears
the physical screens below.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
UNISWAP_V4_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
OUTPUT = REPO_ROOT / "data/processed/v4_candidate_linked_pool_tvl_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_candidate_linked_pool_tvl_daily_support.jsonl"

NATIVE_ETH_ADDRESS = "0x0000000000000000000000000000000000000000"
WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

TVL_USD_UPPER_BOUND = 10_000_000_000.0
VOLUME_USD_UPPER_BOUND = 5_000_000_000.0

CODE_SOURCES = ["scripts/process/build_v4_candidate_linked_pool_tvl_daily.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


@dataclass(frozen=True)
class TokenIdentity:
    address: str
    symbol: str
    decimals: str


@dataclass(frozen=True)
class DailyPoolRow:
    day: str
    pool: str
    tvl_usd: float
    volume_usd: float
    token0: TokenIdentity
    token1: TokenIdentity


def finite_float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if math.isfinite(result) else float("nan")


def vehicle_candidate_map(path: Path = CANDIDATE_DAY_INPUT) -> dict[str, tuple[str, str]]:
    """Return raw token-address to canonical candidate address and symbol."""

    frame = pd.read_parquet(path, columns=["candidate_address", "candidate_symbol"])
    mapping: dict[str, tuple[str, str]] = {}
    for row in frame.drop_duplicates().itertuples(index=False):
        address = str(row.candidate_address).lower()
        mapping[address] = (address, str(row.candidate_symbol))
    if WETH_ADDRESS in mapping:
        mapping[NATIVE_ETH_ADDRESS] = mapping[WETH_ADDRESS]
    if not mapping:
        raise ValueError("candidate-day panel has no candidate addresses")
    return mapping


def symbol_candidate_map(candidate_map: Mapping[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    result = {symbol: (address, symbol) for address, symbol in candidate_map.values()}
    if WETH_ADDRESS in candidate_map:
        result["ETH"] = candidate_map[WETH_ADDRESS]
    return result


def token_identity(pool: Mapping[str, object], side: str) -> TokenIdentity:
    token = pool.get(side) or {}
    if not isinstance(token, Mapping):
        token = {}
    return TokenIdentity(
        address=str(token.get("id") or "").lower(),
        symbol=str(token.get("symbol") or ""),
        decimals=str(token.get("decimals") or ""),
    )


def event_pool_identity(event: Mapping[str, object]) -> tuple[str, tuple[TokenIdentity, TokenIdentity]] | None:
    pool = event.get("pool") or {}
    if not isinstance(pool, Mapping):
        return None
    pool_id = str(pool.get("id") or "").lower()
    if not pool_id:
        return None
    token0 = token_identity(pool, "token0")
    token1 = token_identity(pool, "token1")
    if not token0.address or not token1.address:
        return None
    return pool_id, (token0, token1)


def token_address_pair(tokens: tuple[TokenIdentity, TokenIdentity]) -> tuple[str, str]:
    return tokens[0].address, tokens[1].address


def daily_pool_rows(event_dir: Path = UNISWAP_V4_EVENT_DIR) -> Iterable[DailyPoolRow]:
    for path in sorted(event_dir.glob("uniswap_v4_daily_*.jsonl.gz")):
        day = path.name.removesuffix(".jsonl.gz").rsplit("_", 1)[-1]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                pool = record.get("pool") or {}
                if not isinstance(pool, Mapping):
                    continue
                pool_id = str(pool.get("id") or record.get("id") or "").lower()
                if not pool_id:
                    continue
                yield DailyPoolRow(
                    day=day,
                    pool=pool_id,
                    tvl_usd=finite_float(record.get("tvlUSD")),
                    volume_usd=finite_float(record.get("volumeUSD")),
                    token0=token_identity(pool, "token0"),
                    token1=token_identity(pool, "token1"),
                )


def daily_candidate_sides(
    row: DailyPoolRow,
    *,
    candidate_map: Mapping[str, tuple[str, str]],
    symbol_map: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    candidates: dict[str, tuple[str, str]] = {}
    for token in (row.token0, row.token1):
        candidate = candidate_map.get(token.address) if token.address else symbol_map.get(token.symbol)
        if candidate is not None:
            candidates[candidate[0]] = candidate
    return candidates


def event_candidate_sides(
    tokens: tuple[TokenIdentity, TokenIdentity],
    *,
    candidate_map: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    candidates: dict[str, tuple[str, str]] = {}
    for token in tokens:
        candidate = candidate_map.get(token.address)
        if candidate is not None:
            candidates[candidate[0]] = candidate
    return candidates


def build_event_identity_map(
    *,
    event_dir: Path,
    target_pools: set[str],
) -> tuple[dict[str, tuple[TokenIdentity, TokenIdentity]], set[str], dict[str, int]]:
    """Resolve V4 pool IDs to ordered token addresses from event streams."""

    identity: dict[str, tuple[TokenIdentity, TokenIdentity]] = {}
    conflicted: set[str] = set()
    counts: Counter[str] = Counter()
    for stream in ("modify_liquidities", "swaps"):
        for path in sorted(event_dir.glob(f"uniswap_v4_{stream}_*.jsonl.gz")):
            counts[f"{stream}_files"] += 1
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    counts[f"{stream}_events"] += 1
                    event = json.loads(line)
                    parsed = event_pool_identity(event)
                    if parsed is None:
                        continue
                    pool_id, tokens = parsed
                    if pool_id not in target_pools:
                        continue
                    prior = identity.get(pool_id)
                    if prior is not None and token_address_pair(prior) != token_address_pair(tokens):
                        conflicted.add(pool_id)
                        counts["identity_conflict_events"] += 1
                        continue
                    identity[pool_id] = tokens
                    counts[f"{stream}_resolved_events"] += 1
    for pool in conflicted:
        identity.pop(pool, None)
    counts["event_identity_resolved_pools"] = len(identity)
    counts["event_identity_conflicted_pools"] = len(conflicted)
    return identity, conflicted, dict(counts)


def capital_measurement_status(
    *,
    identity_source: str,
    tvl_usd: float,
    volume_usd: float,
) -> tuple[bool, str]:
    if identity_source != "event_address_resolved":
        return False, f"unsupported_{identity_source}"
    if not math.isfinite(tvl_usd):
        return False, "screen_fail_invalid_tvl"
    if tvl_usd <= 0:
        return False, "screen_fail_nonpositive_tvl"
    if tvl_usd > TVL_USD_UPPER_BOUND:
        return False, "screen_fail_tvl_above_physical_bound"
    if math.isfinite(volume_usd) and (volume_usd < 0 or volume_usd > VOLUME_USD_UPPER_BOUND):
        return False, "screen_fail_volume_outside_physical_bound"
    return True, "screen_pass_event_address_resolved"


def build_candidate_linked_tvl(
    *,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> tuple[pd.DataFrame, dict[str, object]]:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    sym_map = symbol_candidate_map(candidate_map)
    raw_daily_rows = list(daily_pool_rows(event_dir))
    candidate_like_rows = [
        row
        for row in raw_daily_rows
        if daily_candidate_sides(row, candidate_map=candidate_map, symbol_map=sym_map)
    ]
    target_pools = {row.pool for row in candidate_like_rows}
    event_identity, conflicted_pools, event_support = build_event_identity_map(
        event_dir=event_dir,
        target_pools=target_pools,
    )

    rows: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    identity_counts: Counter[str] = Counter()
    for row in candidate_like_rows:
        event_tokens = event_identity.get(row.pool)
        if event_tokens is not None:
            candidates = event_candidate_sides(event_tokens, candidate_map=candidate_map)
            identity_source = "event_address_resolved"
        elif row.pool in conflicted_pools:
            candidates = daily_candidate_sides(row, candidate_map=candidate_map, symbol_map=sym_map)
            identity_source = "identity_conflict"
        elif row.token0.address or row.token1.address:
            candidates = daily_candidate_sides(row, candidate_map=candidate_map, symbol_map=sym_map)
            identity_source = "daily_address_or_symbol_resolved"
        else:
            candidates = daily_candidate_sides(row, candidate_map=candidate_map, symbol_map=sym_map)
            identity_source = "symbol_only_identity"
        if not candidates:
            status_counts["unmapped_after_identity_resolution"] += 1
            continue
        valid, status = capital_measurement_status(
            identity_source=identity_source,
            tvl_usd=row.tvl_usd,
            volume_usd=row.volume_usd,
        )
        identity_counts[identity_source] += 1
        status_counts[status] += len(candidates)
        for candidate_address, candidate_symbol in sorted(candidates.values(), key=lambda item: item[1]):
            rows.append(
                {
                    "origin_date": pd.Timestamp(row.day),
                    "day": row.day,
                    "pool": row.pool,
                    "candidate_address": candidate_address,
                    "candidate_symbol": candidate_symbol,
                    "pool_candidate_id": f"uniswap_v4|{row.pool}|{candidate_address}",
                    "venue": "uniswap_v4",
                    "pool_tvl_usd_reported": row.tvl_usd if math.isfinite(row.tvl_usd) else None,
                    "pool_volume_usd_reported": row.volume_usd if math.isfinite(row.volume_usd) else None,
                    "candidate_linked_pool_tvl_usd": row.tvl_usd if valid else None,
                    "candidate_linked_pool_volume_usd": (
                        row.volume_usd
                        if valid and math.isfinite(row.volume_usd) and row.volume_usd >= 0
                        else None
                    ),
                    "capital_measurement_status": status,
                    "capital_valid": valid,
                    "identity_source": identity_source,
                    "quantity_kind": "provider_reported_pool_tvl_candidate_linked",
                    "allocation_kind": "full_pool_tvl_linked_to_each_candidate_side",
                    "tvl_upper_bound_usd": TVL_USD_UPPER_BOUND,
                    "volume_upper_bound_usd": VOLUME_USD_UPPER_BOUND,
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["origin_date", "candidate_symbol", "pool"]).reset_index(drop=True)

    valid_frame = result[result["capital_valid"]] if not result.empty else result
    support = {
        "record_type": "v4_candidate_linked_pool_tvl_support",
        "analysis_status": "exploratory_candidate_linked_provider_tvl",
        "event_source": "uniswap_v4_graph_daily_rows_joined_to_graph_event_pool_identities",
        "raw_daily_rows": int(len(raw_daily_rows)),
        "candidate_like_daily_rows": int(len(candidate_like_rows)),
        "candidate_linked_rows": int(len(result)),
        "valid_candidate_linked_rows": int(len(valid_frame)),
        "candidate_addresses": int(result["candidate_address"].nunique() if not result.empty else 0),
        "candidate_symbols": int(result["candidate_symbol"].nunique() if not result.empty else 0),
        "target_pools": int(len(target_pools)),
        "identity_counts": dict(identity_counts),
        "capital_measurement_status_counts": dict(status_counts),
        "tvl_upper_bound_usd": TVL_USD_UPPER_BOUND,
        "volume_upper_bound_usd": VOLUME_USD_UPPER_BOUND,
        "event_identity": event_support,
        "quantity": (
            "full-pool provider tvlUSD linked to vehicle-candidate token sides; "
            "not side-specific deposited capital or provider-level LP inventory"
        ),
    }
    return result, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    panel, support = build_candidate_linked_tvl(
        event_dir=event_dir,
        candidate_day_path=candidate_day_path,
    )
    with atomic_output(output_path) as temporary:
        panel.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(panel):,} V4 candidate-linked TVL rows to "
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
