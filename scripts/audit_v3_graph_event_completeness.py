#!/usr/bin/env python3
"""Compare Graph V3 Mint/Swap entities with exact on-chain event identities."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.amounts import human_to_raw
from ddvc.calendar import nearest_day_per_month
from ddvc.paths import DATA_DIR, MARKET_STATE_LOCK, OUTPUT_DIR, RAW_MARKET_DATA_LOCK
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.state_data import STATE_ROOT, available_state_days, read_tick_partition
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    PoolStatic,
    iter_decoded_inventory_logs,
    inventory_chunk_paths,
)
from ddvc.v3_inventory_calendar import CALENDAR, load_day_calendar
from ddvc.v3_pool_registry import (
    V3_POOL_REGISTRY,
    V3_POOL_REGISTRY_CERTIFICATE,
    reopen_registry_evidence,
)
from scripts.build_v3_inventory_panel import (
    GRAPH_STATIC_PATH,
    RAW_INVENTORY_ROOT,
    inventory_perimeter,
    load_candidate_statics,
    ranges_by_day,
    require_complete_raw_chunks,
)


SUMMARY = DATA_DIR / "processed" / "v3_graph_core_event_audit.parquet"
EXCEPTIONS = DATA_DIR / "processed" / "v3_graph_core_event_exceptions.parquet"
PERIMETER_QUARANTINE = DATA_DIR / "processed" / "v3_inventory_perimeter_quarantine.parquet"
EXHIBIT = OUTPUT_DIR / "exhibits" / "v3_graph_core_event_audit.json"
CORE_EVENTS = {"mint", "swap"}
CODE_SOURCES = [
    "scripts/audit_v3_graph_event_completeness.py",
    "scripts/build_v3_inventory_panel.py",
    "scripts/fetch_v3_inventory_events.py",
    "src/ddvc/amounts.py",
    "src/ddvc/calendar.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/ethereum_blocks.py",
    "src/ddvc/ethereum_logs.py",
    "src/ddvc/provenance.py",
    "src/ddvc/runtime.py",
    "src/ddvc/state_data.py",
    "src/ddvc/v3_inventory.py",
    "src/ddvc/v3_inventory_calendar.py",
    "src/ddvc/v3_pool_registry.py",
    "src/ddvc/pricing/v3pools.py",
]
EventKey = tuple[str, int, str, int, str]
Amounts = tuple[int, int]

SUMMARY_SCHEMA = pa.schema(
    [
        pa.field("day", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("raw_events", pa.int64(), nullable=False),
        pa.field("graph_events", pa.int64(), nullable=False),
        pa.field("matched_identities", pa.int64(), nullable=False),
        pa.field("missing_from_graph", pa.int64(), nullable=False),
        pa.field("graph_only", pa.int64(), nullable=False),
        pa.field("graph_duplicate_identities", pa.int64(), nullable=False),
        pa.field("amount_mismatches", pa.int64(), nullable=False),
        pa.field("graph_omission_rate", pa.float64(), nullable=False),
    ]
)

EXCEPTION_SCHEMA = pa.schema(
    [
        pa.field("day", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("block_number", pa.int64(), nullable=False),
        pa.field("tx_hash", pa.string(), nullable=False),
        pa.field("log_index", pa.int64(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("raw_amount0", pa.string()),
        pa.field("raw_amount1", pa.string()),
        pa.field("graph_amount0", pa.string()),
        pa.field("graph_amount1", pa.string()),
    ]
)

PERIMETER_QUARANTINE_SCHEMA = pa.schema(
    [
        pa.field("pool", pa.string(), nullable=False),
        pa.field("reason", pa.string(), nullable=False),
        pa.field("first_block", pa.int64(), nullable=False),
        pa.field("last_block", pa.int64(), nullable=False),
        pa.field("logs", pa.int64(), nullable=False),
        *[
            pa.field(f"{event_type}_logs", pa.int64(), nullable=False)
            for event_type in sorted(EVENT_TOPICS)
        ],
    ]
)


def event_key(event_type: str, block: object, tx_hash: object, log_index: object, pool: object) -> EventKey:
    return (
        str(event_type),
        int(block),
        str(tx_hash).lower(),
        int(log_index),
        str(pool).lower(),
    )


def add_event(
    events: dict[EventKey, Amounts],
    duplicates: set[EventKey],
    key: EventKey,
    amounts: Amounts,
) -> None:
    if key in events:
        duplicates.add(key)
    else:
        events[key] = amounts


def graph_core_events(
    frame: pd.DataFrame,
    statics: dict[str, PoolStatic],
) -> tuple[dict[EventKey, Amounts], set[EventKey]]:
    """Map provider entities to exact causal identities and integer token units."""

    events: dict[EventKey, Amounts] = {}
    duplicates: set[EventKey] = set()
    pools = set(statics)
    for row in frame.itertuples(index=False):
        pool = str(row.pool).lower()
        if pool not in pools:
            continue
        record_type = str(row.record_type)
        source_stream = str(row.source_stream)
        if record_type == "swap":
            event_type = "swap"
        elif record_type == "liquidity" and source_stream == "mints":
            event_type = "mint"
        else:
            continue
        static = statics[pool]
        key = event_key(
            event_type,
            row.block_number,
            row.tx_hash,
            row.log_index,
            pool,
        )
        amount0 = human_to_raw(row.amount0, static.decimals0)
        amount1 = human_to_raw(row.amount1, static.decimals1)
        if amount0 is None or amount1 is None:
            raise ValueError(f"Graph V3 event {key} has an inexact token amount")
        amounts = (int(amount0), int(amount1))
        add_event(events, duplicates, key, amounts)
    return events, duplicates


def raw_core_events(
    ranges: list[tuple[int, int]],
    *,
    lower: int,
    upper: int,
    pools: set[str],
) -> dict[EventKey, Amounts]:
    events: dict[EventKey, Amounts] = {}
    duplicates: set[EventKey] = set()
    for block_lower, block_upper in ranges:
        path, _metadata = inventory_chunk_paths(
            block_lower,
            block_upper,
            RAW_INVENTORY_ROOT,
        )
        for event in iter_decoded_inventory_logs(
            path,
            lower=lower,
            upper=upper,
            pools=pools,
        ):
            event_type = str(event["event_type"])
            if event_type not in CORE_EVENTS:
                continue
            key = event_key(
                event_type,
                event["block_number"],
                event["tx_hash"],
                event["log_index"],
                event["pool"],
            )
            add_event(
                events,
                duplicates,
                key,
                (int(event["amount0_delta_raw"]), int(event["amount1_delta_raw"])),
            )
    if duplicates:
        raise ValueError(f"exact raw V3 audit has {len(duplicates):,} duplicate identities")
    return events


def exception_row(
    day: str,
    key: EventKey,
    status: str,
    raw: Amounts | None,
    graph: Amounts | None,
) -> dict[str, object]:
    event_type, block, tx_hash, log_index, pool = key
    return {
        "day": day,
        "event_type": event_type,
        "status": status,
        "block_number": block,
        "tx_hash": tx_hash,
        "log_index": log_index,
        "pool": pool,
        "raw_amount0": str(raw[0]) if raw is not None else None,
        "raw_amount1": str(raw[1]) if raw is not None else None,
        "graph_amount0": str(graph[0]) if graph is not None else None,
        "graph_amount1": str(graph[1]) if graph is not None else None,
    }


def compare_event_maps(
    day: str,
    raw: dict[EventKey, Amounts],
    graph: dict[EventKey, Amounts],
    graph_duplicates: set[EventKey],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    for event_type in sorted(CORE_EVENTS):
        raw_keys = {key for key in raw if key[0] == event_type}
        graph_keys = {key for key in graph if key[0] == event_type}
        matched = raw_keys & graph_keys
        missing = raw_keys - graph_keys
        graph_only = graph_keys - raw_keys
        duplicates = {key for key in graph_duplicates if key[0] == event_type}
        mismatches = {key for key in matched if raw[key] != graph[key]}
        summaries.append(
            {
                "day": day,
                "event_type": event_type,
                "raw_events": len(raw_keys),
                "graph_events": len(graph_keys),
                "matched_identities": len(matched),
                "missing_from_graph": len(missing),
                "graph_only": len(graph_only),
                "graph_duplicate_identities": len(duplicates),
                "amount_mismatches": len(mismatches),
                "graph_omission_rate": len(missing) / len(raw_keys) if raw_keys else 0.0,
            }
        )
        exceptions.extend(
            exception_row(day, key, "missing_from_graph", raw[key], None)
            for key in sorted(missing)
        )
        exceptions.extend(
            exception_row(day, key, "graph_only", None, graph[key])
            for key in sorted(graph_only)
        )
        exceptions.extend(
            exception_row(day, key, "amount_mismatch", raw[key], graph[key])
            for key in sorted(mismatches)
        )
        exceptions.extend(
            exception_row(day, key, "graph_duplicate_identity", raw.get(key), graph.get(key))
            for key in sorted(duplicates)
        )
    return summaries, exceptions


def write_table(rows: list[dict[str, object]], schema: pa.Schema, path: Path) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    with atomic_output(path) as temporary:
        pq.write_table(table, temporary, compression="zstd")


def build() -> tuple[int, int]:
    factory_pools, factory_certificate = reopen_registry_evidence()
    days, end_blocks = load_day_calendar()
    start, end = inventory_perimeter(days, end_blocks)
    ranges, perimeter_audit = require_complete_raw_chunks(start, end)
    quarantine_rows = perimeter_audit["quarantine_pool_ledger"]
    if not isinstance(quarantine_rows, list):
        raise TypeError("V3 perimeter audit returned a malformed quarantine ledger")
    write_table(quarantine_rows, PERIMETER_QUARANTINE_SCHEMA, PERIMETER_QUARANTINE)
    day_ranges = ranges_by_day(ranges, days, end_blocks)
    audit_days = nearest_day_per_month(available_state_days("tick", "uniswap_v3"))
    statics = load_candidate_statics()
    pools = set(statics)
    position = {day: index for index, day in enumerate(days)}
    summaries: list[dict[str, object]] = []
    exception_count = 0
    with atomic_output(EXCEPTIONS) as temporary:
        with pq.ParquetWriter(temporary, EXCEPTION_SCHEMA, compression="zstd") as writer:
            for count, day in enumerate(audit_days, 1):
                index = position[day]
                lower = start if index == 0 else end_blocks[index - 1] + 1
                upper = end_blocks[index]
                raw = raw_core_events(
                    day_ranges[day],
                    lower=lower,
                    upper=upper,
                    pools=pools,
                )
                graph, duplicates = graph_core_events(
                    read_tick_partition("uniswap_v3", day),
                    statics,
                )
                day_summary, day_exceptions = compare_event_maps(
                    day,
                    raw,
                    graph,
                    duplicates,
                )
                summaries.extend(day_summary)
                exception_count += len(day_exceptions)
                if day_exceptions:
                    writer.write_table(
                        pa.Table.from_pylist(day_exceptions, schema=EXCEPTION_SCHEMA)
                    )
                if count % 10 == 0 or count == len(audit_days):
                    print(
                        f"  V3 event-source audit [{count:,}/{len(audit_days):,}]; "
                        f"exceptions={exception_count:,}",
                        flush=True,
                    )
    write_table(summaries, SUMMARY_SCHEMA, SUMMARY)
    aggregate = Counter()
    for row in summaries:
        for key in (
            "raw_events",
            "graph_events",
            "matched_identities",
            "missing_from_graph",
            "graph_only",
            "graph_duplicate_identities",
            "amount_mismatches",
        ):
            aggregate[key] += int(row[key])
    payload = {
        "status": "diagnostic_only",
        "factory_registry_status": "pass",
        "factory_registry_pools": len(factory_pools),
        "factory_registry_sha256": factory_certificate["registry_sha256"],
        "raw_inventory_logs": perimeter_audit["raw_logs"],
        "canonical_pool_logs": perimeter_audit["canonical_pool_logs"],
        "quarantined_logs": perimeter_audit["quarantined_logs"],
        "quarantined_pools": perimeter_audit["quarantined_pools"],
        "quarantine_reasons": perimeter_audit["quarantine_reasons"],
        "canonical_by_event": perimeter_audit["canonical_by_event"],
        "quarantined_by_event": perimeter_audit["quarantined_by_event"],
        "audit_dates": len(audit_days),
        "first_day": audit_days[0],
        "last_day": audit_days[-1],
        **dict(aggregate),
        "graph_omission_rate": aggregate["missing_from_graph"] / aggregate["raw_events"]
        if aggregate["raw_events"]
        else 0.0,
        "interpretation": (
            "calendar-stratified audit dates validate source completeness only; they are "
            "not an estimation calendar, response horizon, or substitute for the full "
            "exact raw ledger"
        ),
    }
    with atomic_output(EXHIBIT) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    inputs = [
        RAW_INVENTORY_ROOT,
        GRAPH_STATIC_PATH,
        V3_POOL_REGISTRY,
        V3_POOL_REGISTRY_CERTIFICATE,
        CALENDAR,
        STATE_ROOT / "tick" / "uniswap_v3",
    ]
    notes = (
        "62 calendar-stratified V3-period audit dates; exact identities and signed token "
        "quantities"
    )
    stamp(SUMMARY, code_sources=CODE_SOURCES, inputs=inputs, rows=len(summaries), notes=notes)
    stamp(EXCEPTIONS, code_sources=CODE_SOURCES, inputs=inputs, rows=exception_count, notes=notes)
    stamp(
        PERIMETER_QUARANTINE,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        rows=len(quarantine_rows),
        notes="complete global-topic address quarantine against the certified PoolCreated census",
    )
    stamp(EXHIBIT, code_sources=CODE_SOURCES, inputs=inputs, rows=1, notes=notes)
    return len(summaries), exception_count


def main() -> int:
    with ExitStack() as stack:
        stack.enter_context(
            exclusive_job(RAW_MARKET_DATA_LOCK, job="V3 Graph/core-event source audit")
        )
        stack.enter_context(
            exclusive_job(MARKET_STATE_LOCK, job="V3 Graph/core-event source audit")
        )
        summaries, exceptions = build()
    print(f"COMPLETE: V3 source-audit rows={summaries:,}; exceptions={exceptions:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
