#!/usr/bin/env python3
"""Reconcile Graph event order against exact global Ethereum logs."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
import json
from pathlib import Path

import pyarrow.parquet as pq

from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    fetch_exact_logs,
    write_exact_log_chunk,
)
from ddvc.graph_event_order import (
    correction_root_for_graph,
    event_topics,
    load_graph_events,
    match_event_orders,
    write_correction_generation,
)
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import Throttled, rpc_post
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_thread_pool


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
CORRECTION_ROOT = correction_root_for_graph(GRAPH_ROOT)
DEFAULT_CHUNK_SIZE = 1_000
MAX_ATTEMPTS = 12


def exact_chunk_paths(venue: str, day: str, lower: int, upper: int) -> tuple[Path, Path]:
    directory = CORRECTION_ROOT / venue / day
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def exact_chunk_complete(venue: str, day: str, lower: int, upper: int) -> bool:
    raw, marker = exact_chunk_paths(venue, day, lower, upper)
    if not raw.is_file() or not marker.is_file():
        return False
    try:
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        parquet = pq.ParquetFile(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        metadata.get("status") == "complete"
        and metadata.get("kind") == "global_graph_order_events"
        and metadata.get("venue") == venue
        and metadata.get("day") == day
        and int(metadata.get("start_block", -1)) == lower
        and int(metadata.get("end_block", -1)) == upper
        and metadata.get("address_filter") is None
        and set(metadata.get("event_topics") or []) == set(event_topics(venue))
        and metadata.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(metadata.get("raw_logs", -1)) == parquet.metadata.num_rows
        and parquet.schema_arrow == RAW_LOG_SCHEMA
    )


def fetch_chunk(venue: str, day: str, lower: int, upper: int) -> dict[str, object]:
    topics = event_topics(venue)
    records = fetch_exact_logs(
        start_block=lower,
        end_block=upper,
        topics=topics,
        rpc_request=rpc_post,
    )
    raw, marker = exact_chunk_paths(venue, day, lower, upper)
    return write_exact_log_chunk(
        raw,
        marker,
        records,
        {
            "kind": "global_graph_order_events",
            "venue": venue,
            "day": day,
            "start_block": lower,
            "end_block": upper,
            "address_filter": None,
            "query_scope": "complete_graph_observed_block_span_global_topic_only",
            "event_topics": topics,
        },
    )


def fetch_missing_chunks(
    venue: str,
    day: str,
    ranges: list[tuple[int, int]],
    *,
    workers: int,
    force: bool,
) -> None:
    pending = [
        item
        for item in ranges
        if force or not exact_chunk_complete(venue, day, *item)
    ]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not pending:
            return
        failed: list[tuple[int, int]] = []
        with interruptible_thread_pool(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_chunk, venue, day, lower, upper): (lower, upper)
                for lower, upper in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    future.result()
                except Throttled:
                    failed.append(item)
        print(
            f"  {venue}/{day} exact logs round {attempt}: "
            f"complete={len(pending) - len(failed):,}/{len(pending):,}; "
            f"retry={len(failed):,}",
            flush=True,
        )
        pending = sorted(failed)
    if pending:
        raise RuntimeError(
            f"exact event-order fetch exhausted retries for {venue}/{day}: {pending[:3]}"
        )


def reconcile_day(
    venue: str,
    day: str,
    *,
    workers: int,
    chunk_size: int,
    force: bool,
) -> dict[str, int]:
    graph_events = load_graph_events(GRAPH_ROOT, venue, day)
    lower = min(event.block_number for event in graph_events)
    upper = max(event.block_number for event in graph_events)
    ranges = block_ranges(lower, upper, chunk_size)
    fetch_missing_chunks(
        venue,
        day,
        ranges,
        workers=workers,
        force=force,
    )
    exact_paths: list[Path] = []
    exact_records: list[dict[str, object]] = []
    for start, end in ranges:
        if not exact_chunk_complete(venue, day, start, end):
            raise RuntimeError(f"exact event-order chunk incomplete: {venue}/{day}/{start}:{end}")
        raw, marker = exact_chunk_paths(venue, day, start, end)
        exact_paths.extend((raw, marker))
        exact_records.extend(pq.read_table(raw).to_pylist())
    corrections, audit = match_event_orders(graph_events, exact_records, venue)
    write_correction_generation(
        root=CORRECTION_ROOT,
        raw_root=GRAPH_ROOT,
        venue=venue,
        day=day,
        corrections=corrections,
        exact_log_paths=exact_paths,
        audit=audit,
        start_block=lower,
        end_block=upper,
    )
    print(
        f"COMPLETE: {venue}/{day} graph={audit['graph_events']:,}; "
        f"exact={audit['exact_events_in_graph_pool_perimeter']:,}; "
        f"order_corrections={audit['correction_rows']:,}",
        flush=True,
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--day", action="append", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error("--chunk-size must be positive")
    days = sorted({str(day).replace("-", "") for day in args.day})
    if any(len(day) != 8 or not day.isdigit() for day in days):
        parser.error("--day must be YYYYMMDD or YYYY-MM-DD")
    workers = bounded_workers(args.workers, maximum=4)
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="Graph event-order reconciliation"):
        for day in days:
            reconcile_day(
                args.venue,
                day,
                workers=workers,
                chunk_size=args.chunk_size,
                force=args.force,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
