#!/usr/bin/env python3
"""Fetch raw V3 Collect, Flash, and CollectProtocol logs in resumable block chunks."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time

from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import Throttled, rpc_post
from ddvc.runtime import exclusive_job, interruptible_thread_pool
from ddvc.v3_inventory import EVENT_TOPICS, decode_inventory_log


RAW_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_events"
V3_GRAPH_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
STATIC_PATH = V3_GRAPH_ROOT / "uniswap_v3_pool_statics_20260630.jsonl.gz"
END_META_PATH = V3_GRAPH_ROOT / "uniswap_v3_meta_20260630.json"
DEFAULT_CHUNK_SIZE = 1_000
MAX_THROTTLE_RETRIES = 8


def v3_pool_addresses(path: Path = STATIC_PATH) -> set[str]:
    pools: set[str] = set()
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if line.strip():
                pool = str(json.loads(line).get("id") or "").lower()
                if pool:
                    pools.add(pool)
    if not pools:
        raise RuntimeError("V3 immutable pool registry is empty")
    return pools


def default_end_block(path: Path = END_META_PATH) -> int:
    metadata = json.loads(path.read_text())
    value = metadata.get("max_block")
    if value is None:
        raise RuntimeError("research-end V3 raw metadata lacks a maximum block")
    return int(value)


def block_ranges(start: int, end: int, chunk_size: int) -> list[tuple[int, int]]:
    if start < 0 or end < start or chunk_size <= 0:
        raise ValueError("invalid block-range perimeter")
    ranges: list[tuple[int, int]] = []
    lower = start
    while lower <= end:
        upper = min(((lower // chunk_size) + 1) * chunk_size - 1, end)
        ranges.append((lower, upper))
        lower = upper + 1
    return ranges


def paths(lower: int, upper: int, root: Path = RAW_ROOT) -> tuple[Path, Path]:
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return root / f"{stem}.jsonl.gz", root / f"{stem}.meta.json"


def completed(lower: int, upper: int, root: Path = RAW_ROOT) -> bool:
    raw, meta = paths(lower, upper, root)
    if not raw.is_file() or not meta.is_file():
        return False
    try:
        record = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        record.get("status") == "complete"
        and int(record.get("from_block", -1)) == lower
        and int(record.get("to_block", -1)) == upper
        and set(record.get("event_topics") or []) == set(EVENT_TOPICS.values())
    )


def fetch_chunk(
    lower: int,
    upper: int,
    pools: set[str],
    root: Path = RAW_ROOT,
) -> dict[str, object]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [{
            "fromBlock": hex(lower),
            "toBlock": hex(upper),
            "topics": [[EVENT_TOPICS[name] for name in sorted(EVENT_TOPICS)]],
        }],
    }
    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        try:
            response = rpc_post(
                payload,
                timeout=90,
                retries=3,
                retry_json_errors=True,
            )
            break
        except Throttled:
            if attempt == MAX_THROTTLE_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 30))
    logs = response.get("result") if isinstance(response, dict) else None
    if not isinstance(logs, list):
        raise RuntimeError(f"V3 inventory log response lacks a result list: {lower}-{upper}")
    keys: set[tuple[int, str, int]] = set()
    recognized = 0
    by_event = {name: 0 for name in EVENT_TOPICS}
    for log in logs:
        decoded = decode_inventory_log(log)
        block = int(decoded["block_number"])
        if not lower <= block <= upper:
            raise ValueError(f"log outside requested block range: {block} not in {lower}-{upper}")
        key = (block, str(decoded["tx_hash"]), int(decoded["log_index"]))
        if key in keys:
            raise ValueError(f"duplicate V3 inventory log in block chunk: {key}")
        keys.add(key)
        if decoded["pool"] in pools:
            recognized += 1
            by_event[str(decoded["event_type"])] += 1
    raw_path, meta_path = paths(lower, upper, root)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_gz(raw_path, logs)
    metadata = {
        "status": "complete",
        "from_block": lower,
        "to_block": upper,
        "event_topics": [EVENT_TOPICS[name] for name in sorted(EVENT_TOPICS)],
        "raw_logs": len(logs),
        "recognized_v3_logs": recognized,
        "unrecognized_logs": len(logs) - recognized,
        "recognized_by_event": by_event,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(meta_path, metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-block", type=int, default=get_source("uniswap_v3").genesis_block)
    parser.add_argument("--end-block", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    end = args.end_block if args.end_block is not None else default_end_block()
    ranges = block_ranges(int(args.start_block), end, args.chunk_size)
    pools = v3_pool_addresses()
    jobs = [item for item in ranges if args.force or not completed(*item)]
    print(
        f"V3 inventory log perimeter: {len(ranges):,} chunks; "
        f"cached={len(ranges) - len(jobs):,}; fetch={len(jobs):,}; pools={len(pools):,}",
        flush=True,
    )
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw V3 inventory-event fetch"):
        with interruptible_thread_pool(max_workers=max(1, min(args.workers, 4))) as executor:
            futures = {
                executor.submit(fetch_chunk, lower, upper, pools): (lower, upper)
                for lower, upper in jobs
            }
            totals = {"raw": 0, "recognized": 0}
            for index, future in enumerate(as_completed(futures), 1):
                result = future.result()
                totals["raw"] += int(result["raw_logs"])
                totals["recognized"] += int(result["recognized_v3_logs"])
                if index % 100 == 0 or index == len(futures):
                    print(
                        f"  inventory logs [{index:,}/{len(futures):,}]; "
                        f"raw={totals['raw']:,}; V3={totals['recognized']:,}",
                        flush=True,
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
