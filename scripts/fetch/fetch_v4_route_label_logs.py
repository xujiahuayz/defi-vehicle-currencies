#!/usr/bin/env python3
"""Fetch only missing exact PoolManager Initialize/Swap block chunks.

The older tick-state census is read as coverage but is never rewritten.  New
chunks belong to this validation package under a separate raw-data directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from ddvc.ethereum_logs import (
    RAW_LOG_STORAGE_FORMAT,
    fetch_exact_logs_with_capacity_bisection,
    load_or_resolve_frozen_block,
    write_exact_log_chunk,
)
from ddvc.paths import DATA_DIR
from ddvc.v4_contract import (
    UNISWAP_V4_INITIALIZE_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_SWAP_TOPIC,
)


CHUNK_BLOCKS = 10_000
EXISTING_ROOT = DATA_DIR / "raw" / "ethereum" / "tick_state_events" / "chunks" / "uniswap_v4"
OUTPUT_ROOT = DATA_DIR / "raw" / "ethereum" / "v4_route_label_validation" / "chunks"
EXISTING_GENERATION = "exact_v4_poolmanager_state_event_census_v1"
OWNED_GENERATION = "exact_v4_route_label_initialize_swap_v1"
REQUIRED_TOPICS = {UNISWAP_V4_INITIALIZE_TOPIC, UNISWAP_V4_SWAP_TOPIC}


def _range_from_name(path: Path) -> tuple[int, int] | None:
    name = path.name
    if not name.startswith("blocks_") or not name.endswith(".parquet"):
        return None
    try:
        lower, upper = name.removeprefix("blocks_").removesuffix(".parquet").split("_", 1)
        return int(lower), int(upper)
    except ValueError:
        return None


def complete_ranges(root: Path, *, existing: bool) -> dict[tuple[int, int], Path]:
    """Return chunks with a passing compact completion marker."""

    chunks: dict[tuple[int, int], Path] = {}
    suffix = ".meta.json" if existing else ".complete.json"
    for path in sorted(root.glob("blocks_*.parquet")):
        perimeter = _range_from_name(path)
        if perimeter is None:
            continue
        marker = path.with_name(path.name.removesuffix(".parquet") + suffix)
        if not marker.is_file():
            continue
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        topics = {str(topic).lower() for topic in record.get("event_topics") or []}
        expected_generation = EXISTING_GENERATION if existing else OWNED_GENERATION
        topic_scope_ok = REQUIRED_TOPICS.issubset(topics) if existing else topics == REQUIRED_TOPICS
        if (
            record.get("status") != "complete"
            or int(record.get("start_block", -1)) != perimeter[0]
            or int(record.get("end_block", -1)) != perimeter[1]
            or record.get("generation") != expected_generation
            or not topic_scope_ok
            or str(record.get("address_filter") or "").lower()
            != UNISWAP_V4_POOL_MANAGER_ADDRESS
            or record.get("storage_format") != RAW_LOG_STORAGE_FORMAT
            or path.stat().st_size <= 0
        ):
            continue
        if perimeter in chunks:
            raise ValueError(f"duplicate completed exact-log chunk: {perimeter}")
        chunks[perimeter] = path
    return chunks


def expected_ranges(start_block: int, end_block: int) -> list[tuple[int, int]]:
    if start_block < 0 or end_block < start_block:
        raise ValueError("invalid V4 route-label fetch perimeter")
    lower = (start_block // CHUNK_BLOCKS) * CHUNK_BLOCKS
    ranges = []
    while lower <= end_block:
        upper = min(lower + CHUNK_BLOCKS - 1, end_block)
        ranges.append((lower, upper))
        lower += CHUNK_BLOCKS
    return ranges


def missing_ranges(
    start_block: int,
    end_block: int,
    *,
    existing_root: Path,
    output_root: Path,
) -> list[tuple[int, int]]:
    existing = complete_ranges(existing_root, existing=True)
    owned = complete_ranges(output_root, existing=False)
    overlap = sorted(set(existing) & set(owned))
    if overlap:
        raise ValueError(f"owned V4 chunks overlap the earlier census: {overlap[0]}")
    covered = {**existing, **owned}
    missing = []
    for lower, upper in expected_ranges(start_block, end_block):
        containing = [
            perimeter
            for perimeter in covered
            if perimeter[0] <= max(lower, start_block)
            and perimeter[1] >= upper
        ]
        if not containing:
            missing.append((lower, upper))
    return missing


def fetch_missing(
    start_block: int,
    end_block: int,
    *,
    existing_root: Path,
    output_root: Path,
    fetch: bool,
) -> list[dict[str, object]]:
    """Fetch absent aligned chunks without modifying the earlier census."""

    pending = missing_ranges(
        start_block,
        end_block,
        existing_root=existing_root,
        output_root=output_root,
    )
    if not pending or not fetch:
        return [
            {"start_block": lower, "end_block": upper, "status": "missing"}
            for lower, upper in pending
        ]
    output_root.mkdir(parents=True, exist_ok=True)
    frozen_path = output_root.parent / f"frozen_upper_{end_block}.json"
    frozen = load_or_resolve_frozen_block(
        end_block,
        path=frozen_path,
        schema_version=1,
        fetch=True,
    )
    rows = []
    for index, (lower, upper) in enumerate(pending, 1):
        started = time.monotonic()
        stem = f"blocks_{lower}_{upper}"
        raw_path = output_root / f"{stem}.parquet"
        marker_path = output_root / f"{stem}.complete.json"
        if raw_path.exists() or marker_path.exists():
            raise RuntimeError(f"incomplete or conflicting owned chunk exists: {stem}")
        records, evidence = fetch_exact_logs_with_capacity_bisection(
            start_block=lower,
            end_block=upper,
            topics=[UNISWAP_V4_INITIALIZE_TOPIC, UNISWAP_V4_SWAP_TOPIC],
            address=UNISWAP_V4_POOL_MANAGER_ADDRESS,
            frozen_upper=frozen,
        )
        endpoints = sorted(
            {
                str(item.get("endpoint") or "")
                for item in evidence
                if item.get("endpoint")
            }
        )
        marker = write_exact_log_chunk(
            raw_path,
            marker_path,
            records,
            {
                "schema_version": 1,
                "generation": OWNED_GENERATION,
                "start_block": lower,
                "end_block": upper,
                "event_topics": [UNISWAP_V4_INITIALIZE_TOPIC, UNISWAP_V4_SWAP_TOPIC],
                "address_filter": UNISWAP_V4_POOL_MANAGER_ADDRESS,
                "frozen_upper_block": int(frozen["block_number"]),
                "frozen_upper_hash": str(frozen["block_hash"]),
                "rpc_subqueries": len(evidence),
                "rpc_endpoints": endpoints,
            },
        )
        elapsed = time.monotonic() - started
        rows.append({**marker, "runtime_seconds": elapsed})
        print(
            f"  {index}/{len(pending)} {lower}:{upper}: "
            f"{len(records):,} logs in {elapsed:.1f}s",
            flush=True,
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-block", type=int, required=True)
    parser.add_argument("--end-block", type=int, required=True)
    parser.add_argument("--existing-root", type=Path, default=EXISTING_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    rows = fetch_missing(
        args.start_block,
        args.end_block,
        existing_root=args.existing_root,
        output_root=args.output_root,
        fetch=args.fetch,
    )
    if not args.fetch:
        for row in rows:
            print(f"missing {row['start_block']}:{row['end_block']}")
    print(f"missing/fetched chunks: {len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
