#!/usr/bin/env python3
"""Fetch raw V3 Collect, Flash, and CollectProtocol logs in resumable block chunks."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
import json
from pathlib import Path
import re
import time

from ddvc.fetch.sources import get_source
from ddvc.ethereum_logs import fetch_exact_logs, write_exact_log_chunk
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import Throttled, rpc_post
from ddvc.runtime import exclusive_job, interruptible_thread_pool
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    block_ranges,
    canonical_inventory_start_block,
    decode_inventory_log,
    inventory_chunk_completed,
    inventory_chunk_paths,
    pool_addresses_from_graph,
)
from ddvc.state_data import available_state_days, read_tick_partition


RAW_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_events"
V3_GRAPH_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
STATIC_PATH = V3_GRAPH_ROOT / "uniswap_v3_pool_statics_20260630.jsonl.gz"
END_META_PATH = V3_GRAPH_ROOT / "uniswap_v3_meta_20260630.json"
DEFAULT_CHUNK_SIZE = 1_000
MAX_JOB_ATTEMPTS = 12
_URL = re.compile(r"https?://[^\s,)]+", flags=re.IGNORECASE)


def safe_retry_reason(error: BaseException, *, limit: int = 200) -> str:
    """Summarize a retry cause without printing an RPC endpoint or credential."""

    reason = " ".join(str(error).split()) or type(error).__name__
    return _URL.sub("<endpoint>", reason)[:limit]


def v3_pool_addresses(path: Path = STATIC_PATH) -> set[str]:
    return pool_addresses_from_graph(path)


def default_end_block(path: Path = END_META_PATH) -> int:
    metadata = json.loads(path.read_text())
    value = metadata.get("head_block_at_fetch") or metadata.get("max_block")
    if value is None:
        raise RuntimeError("research-end V3 raw metadata lacks a safe terminal block")
    return int(value)


def default_start_block() -> int:
    days = available_state_days("tick", "uniswap_v3")
    if not days:
        raise RuntimeError("canonical V3 state has no day from which to set the fetch perimeter")
    return canonical_inventory_start_block(
        read_tick_partition("uniswap_v3", days[0]).to_dict("records")
    )


def paths(lower: int, upper: int, root: Path = RAW_ROOT) -> tuple[Path, Path]:
    return inventory_chunk_paths(lower, upper, root)


def completed(lower: int, upper: int, root: Path = RAW_ROOT) -> bool:
    return inventory_chunk_completed(lower, upper, root)


def fetch_chunk(
    lower: int,
    upper: int,
    pools: set[str],
    root: Path = RAW_ROOT,
) -> dict[str, object]:
    raw_records = fetch_exact_logs(
        start_block=lower,
        end_block=upper,
        topics=[EVENT_TOPICS[name] for name in sorted(EVENT_TOPICS)],
        rpc_request=rpc_post,
    )
    keys: set[tuple[int, str, int]] = set()
    recognized = 0
    by_event = {name: 0 for name in EVENT_TOPICS}
    for raw_record in raw_records:
        decoded = decode_inventory_log(raw_record)
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
    metadata = {
        "from_block": lower,
        "to_block": upper,
        "event_topics": [EVENT_TOPICS[name] for name in sorted(EVENT_TOPICS)],
        "recognized_v3_logs": recognized,
        "unrecognized_logs": len(raw_records) - recognized,
        "recognized_by_event": by_event,
    }
    return write_exact_log_chunk(raw_path, meta_path, raw_records, metadata)


def run_fetch_jobs(
    jobs: list[tuple[int, int]],
    pools: set[str],
    *,
    workers: int,
    max_attempts: int,
    fetch=fetch_chunk,
) -> tuple[dict[str, int], list[tuple[int, int, str]]]:
    """Run a bounded queue, moving transiently throttled chunks to its tail."""

    queue = deque((lower, upper, 1) for lower, upper in jobs)
    failures: list[tuple[int, int, str]] = []
    totals = {"raw": 0, "recognized": 0}
    complete = 0
    with interruptible_thread_pool(max_workers=workers) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < workers:
                lower, upper, attempt = queue.popleft()
                future = executor.submit(fetch, lower, upper, pools)
                futures[future] = (lower, upper, attempt)
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                lower, upper, attempt = futures.pop(future)
                try:
                    result = future.result()
                except Throttled as error:
                    reason = safe_retry_reason(error)
                    if attempt < max_attempts:
                        queue.append((lower, upper, attempt + 1))
                        print(
                            f"  retrying throttled inventory chunk {lower}-{upper} "
                            f"at queue tail ({attempt + 1}/{max_attempts}); cause={reason}",
                            flush=True,
                        )
                    else:
                        failures.append((lower, upper, reason))
                    continue
                totals["raw"] += int(result["raw_logs"])
                totals["recognized"] += int(result["recognized_v3_logs"])
                complete += 1
                if complete % 100 == 0 or complete + len(failures) == len(jobs):
                    print(
                        f"  inventory logs [{complete:,}/{len(jobs):,}]; "
                        f"raw={totals['raw']:,}; V3={totals['recognized']:,}; "
                        f"queued_remaining={len(queue):,}; "
                        f"terminal_failures={len(failures):,}",
                        flush=True,
                    )
    return totals, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-block", type=int, default=None)
    parser.add_argument("--end-block", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-job-attempts", type=int, default=MAX_JOB_ATTEMPTS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    end = args.end_block if args.end_block is not None else default_end_block()
    start = args.start_block if args.start_block is not None else default_start_block()
    indexed_start = get_source("uniswap_v3").genesis_block
    if start > indexed_start:
        raise RuntimeError(
            f"inventory start block {start} is after indexed V3 genesis {indexed_start}"
        )
    ranges = block_ranges(int(start), end, args.chunk_size)
    pools = v3_pool_addresses()
    jobs = [item for item in ranges if args.force or not completed(*item)]
    print(
        f"V3 inventory log perimeter: {start:,}-{end:,}; {len(ranges):,} chunks; "
        f"cached={len(ranges) - len(jobs):,}; fetch={len(jobs):,}; pools={len(pools):,}",
        flush=True,
    )
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw V3 inventory-event fetch"):
        workers = max(1, min(args.workers, 4))
        max_attempts = max(1, args.max_job_attempts)
        _totals, failures = run_fetch_jobs(
            jobs,
            pools,
            workers=workers,
            max_attempts=max_attempts,
        )
        if failures:
            sample = ", ".join(
                f"{lower}-{upper}: {error}" for lower, upper, error in failures[:3]
            )
            raise RuntimeError(
                f"V3 inventory fetch exhausted {max_attempts} attempts for "
                f"{len(failures):,} chunks; first={sample}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
