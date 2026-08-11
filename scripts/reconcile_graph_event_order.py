#!/usr/bin/env python3
"""Reconcile Graph event order against exact global Ethereum logs."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from concurrent.futures import as_completed
import json
from pathlib import Path

import pyarrow.parquet as pq

from ddvc.ethereum_day_cuts import fetch_block_timestamp
from ddvc.ethereum_receipts import RECEIPT_CACHE, fetch_receipt
from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    fetch_exact_logs,
    write_exact_log_chunk,
)
from ddvc.graph_event_order import (
    ProviderEventsAbsentError,
    correction_root_for_graph,
    event_topics,
    load_graph_events,
    load_pool_templates,
    match_event_orders,
    receipt_proves_event_absence,
    supplement_action,
    supplement_source_row,
    write_correction_generation,
)
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import Throttled, rpc_post
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_thread_pool
from ddvc.v2_event_completeness import (
    V2_EXACT_LOG_CHUNK_SIZE,
    fetch_v2_exact_log_chunk,
    read_v2_exact_logs,
    v2_exact_log_chunk_complete,
    v2_exact_log_chunk_paths,
    v2_exact_log_ranges,
)
from ddvc.v2_event_contract import V2_EVENT_VENUES, V2_RECONCILIATION_SCOPE


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
CORRECTION_ROOT = correction_root_for_graph(GRAPH_ROOT)
DEFAULT_CHUNK_SIZE = V2_EXACT_LOG_CHUNK_SIZE
MAX_ATTEMPTS = 12


def exact_chunk_paths(venue: str, day: str, lower: int, upper: int) -> tuple[Path, Path]:
    if venue in V2_EVENT_VENUES:
        return v2_exact_log_chunk_paths(lower, upper)
    directory = CORRECTION_ROOT / venue / day
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def exact_chunk_complete(
    venue: str,
    day: str,
    lower: int,
    upper: int,
    *,
    frozen_upper: dict[str, object] | None = None,
) -> bool:
    if venue in V2_EVENT_VENUES:
        if frozen_upper is None:
            raise ValueError("V2 shared exact logs require a frozen upper block")
        return v2_exact_log_chunk_complete(lower, upper, frozen_upper=frozen_upper)
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


def fetch_chunk(
    venue: str,
    day: str,
    lower: int,
    upper: int,
    *,
    frozen_upper: dict[str, object] | None = None,
) -> dict[str, object]:
    if venue in V2_EVENT_VENUES:
        if frozen_upper is None:
            raise ValueError("V2 shared exact logs require a frozen upper block")
        return fetch_v2_exact_log_chunk(
            lower,
            upper,
            frozen_upper=frozen_upper,
        )
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
    frozen_upper: dict[str, object] | None,
    workers: int,
    force: bool,
) -> None:
    pending = [
        item
        for item in ranges
        if (force and venue not in V2_EVENT_VENUES)
        or not exact_chunk_complete(venue, day, *item, frozen_upper=frozen_upper)
    ]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not pending:
            return
        failed: list[tuple[int, int]] = []
        with interruptible_thread_pool(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_chunk, venue, day, lower, upper, frozen_upper=frozen_upper): (lower, upper)
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
    frozen_upper: dict[str, object] | None = None,
    workers: int,
    chunk_size: int,
    force: bool,
    start_block: int | None = None,
    end_block: int | None = None,
    expected_pools: set[str] | None = None,
    audited_token_decimals: Mapping[str, int] | None = None,
    pool_templates: Mapping[str, dict] | None = None,
    raw_root: Path = GRAPH_ROOT,
    reconciliation_scope: str = "complete_graph_observed_block_span",
    authority_inputs: list[Path] | None = None,
) -> dict[str, int]:
    if venue in V2_EVENT_VENUES and reconciliation_scope != V2_RECONCILIATION_SCOPE:
        raise ValueError(
            "V2 reconciliation requires the full UTC-day factory-pool perimeter"
        )
    if (start_block is None) != (end_block is None):
        raise ValueError("event reconciliation requires both explicit block bounds")
    graph_events = load_graph_events(
        raw_root,
        venue,
        day,
        audited_token_decimals=audited_token_decimals,
        allow_empty=start_block is not None,
    )
    if not graph_events and not expected_pools:
        raise ValueError(
            "empty provider day requires a nonempty explicit pool perimeter"
        )
    if start_block is None:
        if not graph_events:
            raise ValueError("event reconciliation needs explicit bounds for an empty provider day")
        lower = min(event.block_number for event in graph_events)
        upper = max(event.block_number for event in graph_events)
    else:
        lower = int(start_block)
        upper = int(end_block)
        outside = [
            event
            for event in graph_events
            if event.block_number < lower or event.block_number > upper
        ]
        if outside:
            raise ValueError(
                f"provider events fall outside the certified block bounds: {venue}/{day}"
            )
    if lower < 0 or upper < lower:
        raise ValueError("event reconciliation block bounds are invalid")
    if venue in V2_EVENT_VENUES:
        if chunk_size != V2_EXACT_LOG_CHUNK_SIZE:
            raise ValueError("V2 event reconciliation requires shared 50-block chunks")
        ranges = v2_exact_log_ranges(lower, upper)
    else:
        ranges = block_ranges(lower, upper, chunk_size)
    fetch_missing_chunks(
        venue,
        day,
        ranges,
        frozen_upper=frozen_upper,
        workers=workers,
        force=force,
    )
    if venue in V2_EVENT_VENUES:
        if frozen_upper is None:
            raise ValueError("V2 shared exact logs require a frozen upper block")
        exact_records, exact_paths = read_v2_exact_logs(lower, upper, frozen_upper=frozen_upper)
    else:
        exact_paths = []
        exact_records = []
        for start, end in ranges:
            if not exact_chunk_complete(venue, day, start, end, frozen_upper=frozen_upper):
                raise RuntimeError(f"exact event-order chunk incomplete: {venue}/{day}/{start}:{end}")
            raw, marker = exact_chunk_paths(venue, day, start, end)
            exact_paths.extend((raw, marker))
            exact_records.extend(pq.read_table(raw).to_pylist())
    transaction_receipt_evidence: list[dict[str, object]] = []
    try:
        corrections, missing_events, audit = match_event_orders(
            graph_events,
            exact_records,
            venue,
            expected_pools=expected_pools,
        )
    except ProviderEventsAbsentError as error:
        absent_transactions = {
            event.tx_hash: event.block_number for event in error.events
        }
        transaction_receipt_evidence = [
            fetch_receipt(
                tx_hash,
                cache=RECEIPT_CACHE,
                expected_block=block_number,
                require_block_hash=True,
                include_logs=True,
                require_evidence=True,
            )
            for tx_hash, block_number in sorted(absent_transactions.items())
        ]
        receipts_by_tx = {
            str(receipt["tx_hash"]): receipt for receipt in transaction_receipt_evidence
        }
        if any(
            not receipt_proves_event_absence(
                receipts_by_tx[event.tx_hash],
                venue=venue,
                stream=event.stream,
                tx_hash=event.tx_hash,
                pool=event.pool,
                block_number=event.block_number,
            )
            for event in error.events
        ):
            raise error
        corrections, missing_events, audit = match_event_orders(
            graph_events,
            exact_records,
            venue,
            receipt_statuses={
                tx_hash: int(receipt["status"])
                for tx_hash, receipt in receipts_by_tx.items()
            },
            expected_pools=expected_pools,
        )
    templates = dict(pool_templates) if pool_templates is not None else load_pool_templates(raw_root, venue, day)
    timestamp_evidence: list[dict[str, object]] = []
    timestamps: dict[int, int] = {}
    supplements: list[dict[str, object]] = []
    for event in missing_events:
        template = templates.get(event.pool)
        if template is None:
            raise RuntimeError(
                f"exact event supplement lacks canonical pool statics: {venue}/{event.pool}"
            )
        timestamp = timestamps.get(event.block_number)
        if timestamp is None:
            timestamp = fetch_block_timestamp(event.block_number, timestamp_evidence)
            timestamps[event.block_number] = timestamp
        supplements.append(
            supplement_action(
                event,
                supplement_source_row(event, template, timestamp),
            )
        )
    write_correction_generation(
        root=correction_root_for_graph(raw_root),
        raw_root=raw_root,
        venue=venue,
        day=day,
        corrections=corrections,
        supplements=supplements,
        block_timestamp_evidence=timestamp_evidence,
        exact_log_paths=exact_paths,
        audit=audit,
        start_block=lower,
        end_block=upper,
        transaction_receipt_evidence=transaction_receipt_evidence,
        scope=reconciliation_scope,
        expected_pools=expected_pools,
        audited_token_decimals=audited_token_decimals,
        authority_inputs=authority_inputs,
    )
    print(
        f"COMPLETE: {venue}/{day} graph={audit['graph_events']:,}; "
        f"exact={audit['exact_events_in_reconciliation_pool_perimeter']:,}; "
        f"order_corrections={audit['correction_rows']:,}; "
        f"duplicates={audit['provider_duplicate_rows']:,}; "
        f"payload_corrections={audit['payload_mismatches']:,}; "
        f"completed_liquidity={audit['incomplete_liquidity_status_repairs']:,}; "
        f"exact_absence_exclusions={audit['exclusion_rows']:,}; "
        f"supplements={audit['supplement_rows']:,}",
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
    if args.venue in V2_EVENT_VENUES:
        parser.error(
            "V2 reconciliation is owned by audit_v2_event_completeness.py so every day uses the certified full-day factory perimeter"
        )
    days = sorted({str(day).replace("-", "") for day in args.day})
    if any(len(day) != 8 or not day.isdigit() for day in days):
        parser.error("--day must be YYYYMMDD or YYYY-MM-DD")
    workers = bounded_workers(args.workers, maximum=4)
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="Graph event-order reconciliation"):
        for day in days:
            reconcile_day(
                args.venue,
                day,
                frozen_upper=None,
                workers=workers,
                chunk_size=args.chunk_size,
                force=args.force,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
