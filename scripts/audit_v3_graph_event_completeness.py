#!/usr/bin/env python3
"""Certify canonical V3 core events against the anchored exact chain ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pandas as pd
import pyarrow as pa

from ddvc.artifact_release import file_sha256
from ddvc.paths import MARKET_STATE_LOCK, RAW_MARKET_DATA_LOCK, V3_INVENTORY_RAW_ROOT
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.runtime import exclusive_job
from ddvc.state_data import (
    RAW_ROOT,
    STATE_ROOT,
    read_tick_partition,
    read_tick_quality,
    tick_partition_path,
    tick_quality_path,
)
from ddvc.v3_event_completeness import (
    COUNT_FIELDS,
    V3_CORE_EVENTS,
    V3_COMPARISON_LEDGER,
    V3_EVENT_SOURCE_SCHEMA_VERSION,
    V3_IDENTITY_FIELDS,
    V3_PAYLOAD_FIELDS,
    V3_POOL_PERIMETER,
    V3_RECONCILIATION_SCOPE,
    audit_calendar_sha256,
    block_perimeter_sha256,
    canonical_event_map,
    compare_event_maps,
    correction_generation_inputs,
    correction_generation_records,
    correction_generation_sha256,
    ensure_block_header_snapshot,
    exact_event_map,
    header_snapshot_path,
    load_block_timestamps,
    pool_authorities,
    pool_perimeter_sha256,
    publish_v3_event_source_release,
    read_v3_event_source_release,
    resolve_v3_event_source_release,
    validate_v3_event_source_certificate,
    validate_v3_event_source_evidence_bundle,
    v3_audit_days,
)
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    inventory_chunk_paths,
    inventory_ordered_manifest_path,
    iter_decoded_inventory_logs,
)
from ddvc.v3_inventory_calendar import CALENDAR, load_day_calendar
from ddvc.v3_pool_registry import (
    V3_POOL_REGISTRY,
    V3_POOL_REGISTRY_CERTIFICATE,
    load_registry,
    registry_sha256,
    reopen_registry_evidence,
)
from scripts.build_v3_inventory_panel import (
    GRAPH_STATIC_PATH,
    inventory_perimeter,
    load_full_consumer_statics,
    ranges_by_day,
    require_complete_raw_chunks,
)


CODE_SOURCES = [
    "scripts/audit_v3_graph_event_completeness.py",
    "scripts/build_v3_inventory_panel.py",
    "scripts/fetch_v3_inventory_events.py",
    "src/ddvc/amounts.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/ethereum_blocks.py",
    "src/ddvc/ethereum_logs.py",
    "src/ddvc/graph_event_order.py",
    "src/ddvc/provenance.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/release_calendar.py",
    "src/ddvc/runtime.py",
    "src/ddvc/state_data.py",
    "src/ddvc/v3_event_completeness.py",
    "src/ddvc/v3_inventory.py",
    "src/ddvc/v3_inventory_calendar.py",
    "src/ddvc/v3_pool_registry.py",
]

SUMMARY_SCHEMA = pa.schema(
    [
        pa.field("day", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        *[pa.field(field, pa.int64(), nullable=False) for field in COUNT_FIELDS],
        pa.field("passed", pa.bool_(), nullable=False),
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
        pa.field("exact_payload_json", pa.string()),
        pa.field("canonical_payload_json", pa.string()),
        pa.field("duplicate_rows", pa.int64(), nullable=False),
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


def _frame(rows: list[dict[str, object]], schema: pa.Schema) -> pd.DataFrame:
    return pa.Table.from_pylist(rows, schema=schema).to_pandas()


def _decoded_events_for_day(
    day: str,
    *,
    start: int,
    days: list[str],
    end_blocks: list[int],
    day_ranges: dict[str, list[tuple[int, int]]],
    pools: set[str],
) -> Iterator[dict[str, object]]:
    position = days.index(day)
    lower = start if position == 0 else end_blocks[position - 1] + 1
    upper = end_blocks[position]
    return (
        event
        for block_lower, block_upper in day_ranges[day]
        for event in iter_decoded_inventory_logs(
            inventory_chunk_paths(
                block_lower, block_upper, V3_INVENTORY_RAW_ROOT
            )[0],
            lower=lower,
            upper=upper,
            pools=pools,
        )
        if event["event_type"] in V3_CORE_EVENTS
    )


def require_audit_state_inputs(
    audit_days: list[str], *, state_root: Path = STATE_ROOT
) -> None:
    """Fail cheaply before raw-inventory scans when canonical audit inputs are absent."""
    missing: list[Path] = []
    for day in audit_days:
        for path in (
            tick_partition_path("uniswap_v3", day, root=state_root),
            tick_quality_path("uniswap_v3", day, root=state_root),
        ):
            if not path.is_file():
                missing.append(path)
    if missing:
        sample = ", ".join(path.name for path in missing[:4])
        raise FileNotFoundError(
            f"V3 event-source preflight lacks {len(missing):,} current market-state "
            f"input(s); first={sample}. Materialize them with "
            "`./scripts/run scripts/build_market_state.py --family tick "
            "--venue uniswap_v3 --audit-calendar` before launching this audit."
        )
    failed: list[str] = []
    stale: list[str] = []
    for day in audit_days:
        quality = read_tick_quality(
            RAW_ROOT, "uniswap_v3", day, root=state_root
        )
        if quality is None:
            stale.append(day)
        elif not quality.passed:
            failed.append(day)
    if stale or failed:
        raise ValueError(
            "V3 event-source preflight rejects non-current or failed market-state "
            f"inputs: stale={len(stale):,}, failed={len(failed):,}; "
            f"first_stale={stale[:3]}, first_failed={failed[:3]}. Resolve the "
            "upstream state data contract before launching this audit."
        )


def build(*, header_workers: int = 4) -> tuple[int, int]:
    audit_days = v3_audit_days(UNIFIED_QUALITY_PANEL)
    require_audit_state_inputs(audit_days)
    print(
        f"PHASE 1/4: validating the exact raw V3 inventory ({len(audit_days):,} audit dates)",
        flush=True,
    )
    factory_all, factory_certificate = reopen_registry_evidence()
    factory_pools = load_registry()
    if registry_sha256(factory_all) != factory_certificate.get("registry_sha256"):
        raise ValueError("V3 reopened factory registry certificate digest disagrees")
    authorities = pool_authorities(factory_pools, load_full_consumer_statics())
    days, end_blocks = load_day_calendar()
    start, end = inventory_perimeter(days, end_blocks)
    ranges, perimeter = require_complete_raw_chunks(
        start,
        end,
        progress=lambda done, total: print(
            f"  raw-inventory classification [{done:,}/{total:,}]", flush=True
        ),
    )
    quarantine_rows = perimeter.get("quarantine_pool_ledger")
    if not isinstance(quarantine_rows, list):
        raise TypeError("V3 perimeter audit returned a malformed quarantine ledger")
    missing_days = sorted(set(audit_days) - set(days))
    if missing_days:
        raise ValueError(f"V3 audit calendar lies outside exact day cuts: {missing_days[:3]}")
    day_ranges = ranges_by_day(ranges, days, end_blocks)
    pools = set(authorities)

    event_blocks: set[int] = set()
    print("PHASE 2/4: deriving the audit-date event-block perimeter", flush=True)
    for count, day in enumerate(audit_days, 1):
        decoded = _decoded_events_for_day(
            day,
            start=start,
            days=days,
            end_blocks=end_blocks,
            day_ranges=day_ranges,
            pools=pools,
        )
        event_blocks.update(int(event["block_number"]) for event in decoded)
        if count % 10 == 0 or count == len(audit_days):
            print(
                f"  V3 event-block perimeter [{count:,}/{len(audit_days):,}]; "
                f"blocks={len(event_blocks):,}",
                flush=True,
            )
    snapshot = ensure_block_header_snapshot(
        event_blocks,
        header_snapshot_path(audit_days, event_blocks),
        workers=header_workers,
    )
    timestamps = load_block_timestamps(snapshot)

    summaries: list[dict[str, object]] = []
    print("PHASE 3/4: reconciling exact and canonical audit-date events", flush=True)
    for count, day in enumerate(audit_days, 1):
        decoded = _decoded_events_for_day(
            day,
            start=start,
            days=days,
            end_blocks=end_blocks,
            day_ranges=day_ranges,
            pools=pools,
        )
        exact = exact_event_map(decoded, authorities, timestamps)
        canonical, occurrences = canonical_event_map(
            read_tick_partition("uniswap_v3", day), authorities
        )
        day_summary, day_exceptions = compare_event_maps(
            day, exact, canonical, occurrences
        )
        if day_exceptions:
            failure_counts = Counter(row["status"] for row in day_exceptions)
            raise ValueError(
                f"V3 event-source comparison failed on {day}: "
                f"{dict(sorted(failure_counts.items()))}; first={day_exceptions[0]}"
            )
        summaries.extend(day_summary)
        if count % 10 == 0 or count == len(audit_days):
            print(
                f"  V3 event-source comparison [{count:,}/{len(audit_days):,}]; "
                f"events={sum(row['exact_events'] for row in summaries):,}",
                flush=True,
            )

    summary = _frame(summaries, SUMMARY_SCHEMA)
    exceptions = _frame([], EXCEPTION_SCHEMA)
    quarantine = _frame(quarantine_rows, PERIMETER_QUARANTINE_SCHEMA)
    corrections = correction_generation_records(RAW_ROOT, audit_days)
    certificate: dict[str, object] = {
        "schema_version": V3_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": audit_calendar_sha256(audit_days),
        "audit_dates": len(audit_days),
        "first_day": audit_days[0],
        "last_day": audit_days[-1],
        "summary_rows": len(summary),
        "exception_rows": len(exceptions),
        "event_types": list(V3_CORE_EVENTS),
        "pool_perimeter": V3_POOL_PERIMETER,
        "comparison_ledger": V3_COMPARISON_LEDGER,
        "reconciliation_scope": V3_RECONCILIATION_SCOPE,
        "identity_fields": list(V3_IDENTITY_FIELDS),
        "payload_fields": list(V3_PAYLOAD_FIELDS),
        "factory_registry_sha256": registry_sha256(factory_all),
        "pool_count": len(authorities),
        "pool_perimeter_sha256": pool_perimeter_sha256(authorities),
        "ordered_raw_manifest_sha256": file_sha256(
            inventory_ordered_manifest_path(V3_INVENTORY_RAW_ROOT)
        ),
        "raw_inventory_logs": int(perimeter["raw_logs"]),
        "quarantine_rows": len(quarantine),
        "block_perimeter_sha256": block_perimeter_sha256(event_blocks),
        "block_header_snapshot_sha256": file_sha256(snapshot),
        "correction_generations": corrections,
        "correction_generations_sha256": correction_generation_sha256(corrections),
        **{field: int(summary[field].sum()) for field in COUNT_FIELDS},
    }
    validate_v3_event_source_certificate(
        summary, exceptions, quarantine, certificate, audit_days
    )
    validate_v3_event_source_evidence_bundle(
        certificate, summary=summary, quarantine=quarantine
    )
    inputs: list[str | Path] = [
        V3_INVENTORY_RAW_ROOT,
        inventory_ordered_manifest_path(V3_INVENTORY_RAW_ROOT),
        GRAPH_STATIC_PATH,
        V3_POOL_REGISTRY,
        V3_POOL_REGISTRY_CERTIFICATE,
        CALENDAR,
        UNIFIED_QUALITY_PANEL,
        STATE_ROOT / "tick" / "uniswap_v3",
        snapshot,
        *correction_generation_inputs(RAW_ROOT, audit_days),
    ]
    release = publish_v3_event_source_release(
        summary,
        exceptions,
        quarantine,
        certificate,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=(
            "full UTC-day exact-event reconciliation on the shared transaction-frontier "
            "audit calendar and full canonical V3 market-state consumer-pool perimeter"
        ),
    )
    reopened = read_v3_event_source_release(resolve_v3_event_source_release())
    validate_v3_event_source_certificate(*reopened, audit_days)
    validate_v3_event_source_evidence_bundle(
        reopened[3], summary=reopened[0], quarantine=reopened[2]
    )
    print("PHASE 4/4: published and reopened the certified release", flush=True)
    return len(summary), int(summary["exact_events"].sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header-workers", type=int, default=4)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="check current canonical audit inputs without scanning the raw inventory",
    )
    args = parser.parse_args()
    if not 1 <= args.header_workers <= 8:
        parser.error("--header-workers must lie between 1 and 8")
    audit_days = v3_audit_days(UNIFIED_QUALITY_PANEL)
    require_audit_state_inputs(audit_days)
    if args.preflight_only:
        print(f"PASS: V3 event-source preflight dates={len(audit_days):,}")
        return 0
    with ExitStack() as stack:
        stack.enter_context(
            exclusive_job(RAW_MARKET_DATA_LOCK, job="V3 exact event-source certificate")
        )
        stack.enter_context(
            exclusive_job(MARKET_STATE_LOCK, job="V3 exact event-source certificate")
        )
        rows, events = build(header_workers=args.header_workers)
    print(f"PASS: V3 event-source certificate rows={rows:,}; events={events:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
