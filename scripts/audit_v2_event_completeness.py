#!/usr/bin/env python3
"""Certify V2 Mint/Burn/Swap Graph completeness against global Ethereum logs.

The pool perimeter is independent of the Graph event streams under audit. Every
pair emitted by the registered Uniswap V2 and SushiSwap V2 factories is recovered
from complete PairCreated histories. Core-event queries then use topics only, with
no address filter; registered pairs are attributed to venues after raw retrieval.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, wait
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.ethereum_day_cuts import (
    fetch_block_timestamp,
    utc_day_block_bounds,
    validate_utc_day_block_bounds,
)
from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    fetch_exact_logs,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_json
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, MARKET_STATE_LOCK, RAW_MARKET_DATA_LOCK
from ddvc.pricing.v3pools import load_token_decimals
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.quoter import Throttled, rpc_post
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.runtime import atomic_output, exclusive_job, interruptible_thread_pool
from ddvc.v2_event_completeness import (
    PAIR_CREATED_TOPIC,
    RAW_DAY_BOUND_ROOT,
    RAW_V2_EVENT_ROOT,
    RAW_V2_FACTORY_ROOT,
    V2_CORE_EVENTS,
    V2_EVENT_BY_TOPIC,
    V2_EVENT_SOURCE_CERTIFICATE,
    V2_EVENT_SOURCE_EXCEPTIONS,
    V2_EVENT_SOURCE_SCHEMA_VERSION,
    V2_EVENT_SOURCE_SUMMARY,
    V2_EVENT_TOPICS,
    V2_EVENT_VENUES,
    V2_FACTORIES,
    V2_POOL_PERIMETER,
    audit_calendar_sha256,
    compare_event_maps,
    factory_pair_registry,
    graph_core_events,
    raw_core_events,
    validate_v2_event_source_certificate,
)


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"
DEFAULT_FACTORY_CHUNK_SIZE = 50_000
DEFAULT_EVENT_BLOCK_CHUNK_SIZE = 2_000
MAX_JOB_ATTEMPTS = 12
CODE_SOURCES = [
    "scripts/audit_v2_event_completeness.py",
    "src/ddvc/amounts.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/ethereum_logs.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/fetch/sources.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/provenance.py",
    "src/ddvc/quoter.py",
    "src/ddvc/release_calendar.py",
    "src/ddvc/runtime.py",
    "src/ddvc/v2_event_completeness.py",
]
SUMMARY_COLUMNS = [
    "day",
    "venue",
    "event_type",
    "launch_status",
    "raw_events",
    "graph_events",
    "matched_identities",
    "missing_from_graph",
    "graph_only",
    "graph_duplicate_identities",
    "amount_mismatches",
    "passed",
]
AMOUNT_FIELDS = (
    "amount0_delta_raw",
    "amount1_delta_raw",
    "amount0_in_raw",
    "amount1_in_raw",
    "amount0_out_raw",
    "amount1_out_raw",
)
EXCEPTION_COLUMNS = [
    "day",
    "venue",
    "event_type",
    "status",
    "block_number",
    "tx_hash",
    "log_index",
    "pool",
    *(f"{prefix}_{field}" for prefix in ("raw", "graph") for field in AMOUNT_FIELDS),
]


def _meta_path(venue: str, day: str) -> Path:
    return GRAPH_ROOT / venue / f"{venue}_meta_{day}.json"


def _graph_event_paths(venue: str, day: str) -> list[Path]:
    return [
        GRAPH_ROOT / venue / f"{venue}_{stream}_{day}.jsonl.gz"
        for stream in ("swaps", "mints", "burns")
    ]


def _day_bound_path(day: str) -> Path:
    return RAW_DAY_BOUND_ROOT / f"{day}.json"


def _factory_deployment_path(venue: str) -> Path:
    return RAW_V2_FACTORY_ROOT / venue / "deployment.json"


def _launched_venues(day: str) -> tuple[str, ...]:
    return tuple(
        venue
        for venue in V2_EVENT_VENUES
        if day >= get_source(venue).genesis.strftime("%Y%m%d")
    )


def _day_upper(day: str) -> int:
    values: list[int] = []
    for venue in _launched_venues(day):
        path = _meta_path(venue, day)
        if not path.is_file():
            raise FileNotFoundError(path)
        metadata = json.loads(path.read_text(encoding="utf-8"))
        value = metadata.get("head_block_at_fetch")
        if value is None:
            raise ValueError(f"{venue}/{day} raw metadata lacks head_block_at_fetch")
        values.append(int(value))
    if not values:
        raise ValueError(f"no V2-family venue had launched by {day}")
    return max(values)


def load_or_resolve_day_bounds(day: str, *, fetch: bool = True) -> dict[str, object]:
    """Persist exact adjacent UTC-boundary block evidence and validate every reuse."""

    path = _day_bound_path(day)
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("status") == "complete":
                validate_utc_day_block_bounds(cached, day)
                return cached
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if not fetch:
        raise RuntimeError(f"V2 event-source audit lacks a current UTC block cut for {day}")
    evidence: list[dict[str, object]] = []
    timestamps: dict[int, int] = {}

    def timestamp_for_block(block: int) -> int:
        if block not in timestamps:
            timestamps[block] = fetch_block_timestamp(block, evidence)
        return timestamps[block]

    record = {
        "status": "complete",
        **utc_day_block_bounds(day, 0, _day_upper(day), timestamp_for_block),
        "rpc_evidence": evidence,
    }
    validate_utc_day_block_bounds(record, day)
    RAW_DAY_BOUND_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


def _code_at_block(factory: str, block: int, evidence: list[dict[str, object]]) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getCode",
        "params": [factory, hex(block)],
    }
    response = rpc_post(payload, timeout=30, retries=3, retry_json_errors=True)
    code = response.get("result") if isinstance(response, dict) else None
    if not isinstance(code, str) or not code.startswith("0x"):
        raise RuntimeError(f"eth_getCode lacks an exact result for {factory}/{block}")
    evidence.append({"request": payload, "response": {"result": code}})
    return code


def _validate_factory_deployment(record: dict[str, object], venue: str) -> int:
    factory = V2_FACTORIES[venue]
    block = int(record.get("deployment_block", -1))
    if record.get("status") != "complete" or record.get("factory") != factory or block < 1:
        raise ValueError(f"stale {venue} factory deployment evidence")
    evidence = record.get("rpc_evidence")
    if not isinstance(evidence, list):
        raise ValueError(f"{venue} factory deployment evidence is absent")
    observed: dict[int, str] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        request = item.get("request")
        response = item.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        if request.get("method") != "eth_getCode":
            continue
        params = request.get("params")
        if not isinstance(params, list) or len(params) != 2 or params[0] != factory:
            continue
        observed[int(str(params[1]), 16)] = str(response.get("result") or "")
    if observed.get(block - 1) not in {"0x", "0x0"}:
        raise ValueError(f"{venue} pre-deployment factory code is not empty")
    if observed.get(block) in {None, "", "0x", "0x0"}:
        raise ValueError(f"{venue} deployment-block factory code is empty")
    return block


def load_or_resolve_factory_deployment(
    venue: str,
    upper: int,
    *,
    fetch: bool = True,
) -> dict[str, object]:
    """Find the exact first block containing factory bytecode, with RPC evidence."""

    path = _factory_deployment_path(venue)
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            _validate_factory_deployment(cached, venue)
            return cached
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if not fetch:
        raise RuntimeError(f"V2 event-source audit lacks factory deployment evidence for {venue}")
    factory = V2_FACTORIES[venue]
    evidence: list[dict[str, object]] = []
    if _code_at_block(factory, upper, evidence) in {"0x", "0x0"}:
        raise RuntimeError(f"registered {venue} factory has no code by block {upper}")
    lower = 0
    while lower + 1 < upper:
        middle = (lower + upper) // 2
        if _code_at_block(factory, middle, evidence) in {"0x", "0x0"}:
            lower = middle
        else:
            upper = middle
    _code_at_block(factory, upper - 1, evidence)
    _code_at_block(factory, upper, evidence)
    record = {
        "status": "complete",
        "venue": venue,
        "factory": factory,
        "deployment_block": upper,
        "rpc_evidence": evidence,
    }
    _validate_factory_deployment(record, venue)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


def factory_chunk_paths(venue: str, start_block: int, end_block: int) -> tuple[Path, Path]:
    directory = RAW_V2_FACTORY_ROOT / venue
    stem = f"blocks_{start_block:08d}_{end_block:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def event_chunk_paths(day: str, start_block: int, end_block: int) -> tuple[Path, Path]:
    directory = RAW_V2_EVENT_ROOT / day
    stem = f"blocks_{start_block:08d}_{end_block:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def _chunk_completed(
    raw_path: Path,
    marker_path: Path,
    *,
    kind: str,
    start_block: int,
    end_block: int,
    address: str | None,
    topics: set[str],
) -> bool:
    if not raw_path.is_file() or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        table = pq.ParquetFile(raw_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        marker.get("status") == "complete"
        and marker.get("kind") == kind
        and int(marker.get("start_block", -1)) == start_block
        and int(marker.get("end_block", -1)) == end_block
        and marker.get("address_filter") == address
        and set(marker.get("event_topics") or []) == topics
        and marker.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(marker.get("raw_logs", -1)) == table.metadata.num_rows
        and table.schema_arrow == RAW_LOG_SCHEMA
    )


def factory_chunk_completed(venue: str, start_block: int, end_block: int) -> bool:
    raw, marker = factory_chunk_paths(venue, start_block, end_block)
    return _chunk_completed(
        raw,
        marker,
        kind="factory_pair_created",
        start_block=start_block,
        end_block=end_block,
        address=V2_FACTORIES[venue],
        topics={PAIR_CREATED_TOPIC},
    )


def event_chunk_completed(day: str, start_block: int, end_block: int) -> bool:
    raw, marker = event_chunk_paths(day, start_block, end_block)
    return _chunk_completed(
        raw,
        marker,
        kind="global_v2_core_events",
        start_block=start_block,
        end_block=end_block,
        address=None,
        topics=set(V2_EVENT_TOPICS.values()),
    )


def _fetch_logs(
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None,
) -> list[dict[str, object]]:
    return fetch_exact_logs(
        start_block=start_block,
        end_block=end_block,
        topics=topics,
        address=address,
        rpc_request=rpc_post,
    )


def _write_chunk(
    raw_path: Path,
    marker_path: Path,
    records: list[dict[str, object]],
    marker: dict[str, object],
) -> dict[str, object]:
    return write_exact_log_chunk(raw_path, marker_path, records, marker)


def fetch_factory_chunk(venue: str, start_block: int, end_block: int) -> dict[str, object]:
    records = _fetch_logs(
        start_block=start_block,
        end_block=end_block,
        topics=[PAIR_CREATED_TOPIC],
        address=V2_FACTORIES[venue],
    )
    raw, marker = factory_chunk_paths(venue, start_block, end_block)
    return _write_chunk(
        raw,
        marker,
        records,
        {
            "kind": "factory_pair_created",
            "venue": venue,
            "start_block": start_block,
            "end_block": end_block,
            "address_filter": V2_FACTORIES[venue],
            "event_topics": [PAIR_CREATED_TOPIC],
        },
    )


def fetch_event_chunk(day: str, start_block: int, end_block: int) -> dict[str, object]:
    records = _fetch_logs(
        start_block=start_block,
        end_block=end_block,
        topics=[V2_EVENT_TOPICS[name] for name in V2_CORE_EVENTS],
        address=None,
    )
    raw, marker = event_chunk_paths(day, start_block, end_block)
    return _write_chunk(
        raw,
        marker,
        records,
        {
            "kind": "global_v2_core_events",
            "day": day,
            "start_block": start_block,
            "end_block": end_block,
            "address_filter": None,
            "query_scope": "global_topic_only_no_address_filter",
            "event_topics": [V2_EVENT_TOPICS[name] for name in V2_CORE_EVENTS],
            "raw_by_event": dict(
                Counter(V2_EVENT_BY_TOPIC[str(record["topics"][0])] for record in records)
            ),
        },
    )


FetchJob = tuple[str, str, int, int]


def run_fetch_jobs(jobs: list[FetchJob], *, workers: int, max_attempts: int) -> None:
    queue = deque((*job, 1) for job in jobs)
    complete = 0
    failures: list[tuple[str, str, int, int, str]] = []
    with interruptible_thread_pool(max_workers=workers) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < workers:
                kind, label, start, end, attempt = queue.popleft()
                function = fetch_factory_chunk if kind == "factory" else fetch_event_chunk
                future = executor.submit(function, label, start, end)
                futures[future] = (kind, label, start, end, attempt)
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                kind, label, start, end, attempt = futures.pop(future)
                try:
                    future.result()
                except Throttled as error:
                    if attempt < max_attempts:
                        queue.append((kind, label, start, end, attempt + 1))
                    else:
                        failures.append((kind, label, start, end, type(error).__name__))
                    continue
                complete += 1
                if complete % 100 == 0 or complete + len(failures) == len(jobs):
                    print(
                        f"  exact Ethereum chunks [{complete:,}/{len(jobs):,}]; "
                        f"queued={len(queue):,}; terminal_failures={len(failures):,}",
                        flush=True,
                    )
    if failures:
        raise RuntimeError(
            f"exact Ethereum log fetch exhausted retries for {len(failures):,} chunks; "
            f"first={failures[:3]}"
        )


def _read_chunk_records(path: Path) -> list[dict[str, object]]:
    return pq.read_table(path).to_pylist()


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        frame.to_parquet(temporary, index=False)


def _registry_sha256(pairs: list[object]) -> str:
    rows = [
        {
            "venue": pair.venue,
            "factory": pair.factory,
            "pool": pair.pool,
            "token0": pair.token0,
            "token1": pair.token1,
            "creation_block": pair.creation_block,
            "creation_tx_hash": pair.creation_tx_hash,
            "creation_log_index": pair.creation_log_index,
            "ordinal": pair.ordinal,
        }
        for pair in pairs
    ]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _preflight_graph_streams(audit_days: list[str]) -> None:
    missing: list[Path] = []
    for day in audit_days:
        for venue in _launched_venues(day):
            missing.extend(path for path in _graph_event_paths(venue, day) if not path.is_file())
    if missing:
        by_stream = Counter(path.name.split("_")[-2] for path in missing)
        raise RuntimeError(
            f"V2 event-source audit lacks {len(missing):,} Graph event files before RPC fetch; "
            f"by_stream={dict(by_stream)}; first={missing[0].name}"
        )


def build(
    *,
    fetch: bool,
    force: bool,
    workers: int,
    factory_chunk_size: int,
    event_block_chunk_size: int,
) -> tuple[int, int]:
    require_current_artifacts(
        [UNIFIED_QUALITY_PANEL, TOKEN_DECIMALS],
        consumer="V2 exact event-source audit",
    )
    audit_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
    _preflight_graph_streams(audit_days)
    token_decimals = load_token_decimals(TOKEN_DECIMALS)
    day_bounds = {
        day: load_or_resolve_day_bounds(day, fetch=fetch)
        for day in audit_days
        if _launched_venues(day)
    }
    maximum_block = max(int(record["end_block"]) for record in day_bounds.values())
    deployments = {
        venue: load_or_resolve_factory_deployment(venue, maximum_block, fetch=fetch)
        for venue in V2_EVENT_VENUES
    }

    factory_ranges: dict[str, list[tuple[int, int]]] = {}
    event_ranges: dict[str, list[tuple[int, int]]] = {}
    jobs: list[FetchJob] = []
    for venue, deployment in deployments.items():
        ranges = list(
            block_ranges(
                int(deployment["deployment_block"]),
                maximum_block,
                factory_chunk_size,
            )
        )
        factory_ranges[venue] = ranges
        jobs.extend(
            ("factory", venue, start, end)
            for start, end in ranges
            if force or not factory_chunk_completed(venue, start, end)
        )
    for day, bounds in day_bounds.items():
        ranges = list(
            block_ranges(
                int(bounds["start_block"]),
                int(bounds["end_block"]),
                event_block_chunk_size,
            )
        )
        event_ranges[day] = ranges
        jobs.extend(
            ("event", day, start, end)
            for start, end in ranges
            if force or not event_chunk_completed(day, start, end)
        )
    if jobs and not fetch:
        counts = Counter(job[0] for job in jobs)
        raise RuntimeError(
            f"V2 event-source audit has {len(jobs):,} incomplete raw chunks: {dict(counts)}"
        )
    if jobs:
        run_fetch_jobs(
            jobs,
            workers=max(1, min(workers, 4)),
            max_attempts=MAX_JOB_ATTEMPTS,
        )

    statics: dict[str, dict] = {}
    pairs_by_venue: dict[str, list] = {}
    all_pairs = []
    pool_owner: dict[str, str] = {}
    for venue, ranges in factory_ranges.items():
        records: list[dict[str, object]] = []
        for start, end in ranges:
            if not factory_chunk_completed(venue, start, end):
                raise RuntimeError(f"factory registry chunk lost completeness: {venue}/{start}:{end}")
            raw, _marker = factory_chunk_paths(venue, start, end)
            records.extend(_read_chunk_records(raw))
        venue_statics, venue_pairs = factory_pair_registry(venue, records, token_decimals)
        if not venue_pairs:
            raise RuntimeError(f"independent factory registry is empty for {venue}")
        for pool in venue_statics:
            prior = pool_owner.get(pool)
            if prior is not None and prior != venue:
                raise RuntimeError(f"factory pool collision: {pool} in {prior} and {venue}")
            pool_owner[pool] = venue
        statics[venue] = venue_statics
        pairs_by_venue[venue] = venue_pairs
        all_pairs.extend(venue_pairs)

    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    raw_global_logs = 0
    for count, day in enumerate(audit_days, 1):
        records: list[dict[str, object]] = []
        for start, end in event_ranges.get(day, []):
            if not event_chunk_completed(day, start, end):
                raise RuntimeError(f"global event chunk lost completeness: {day}/{start}:{end}")
            raw, _marker = event_chunk_paths(day, start, end)
            records.extend(_read_chunk_records(raw))
        raw_global_logs += len(records)
        for venue in V2_EVENT_VENUES:
            if venue not in _launched_venues(day):
                day_summary, day_exceptions = compare_event_maps(
                    day,
                    venue,
                    {},
                    {},
                    set(),
                    launch_status="pre_genesis",
                )
            else:
                raw = raw_core_events(
                    venue,
                    records,
                    expected_pools=set(statics[venue]),
                    expected_creation_blocks={
                        pair.pool: pair.creation_block for pair in pairs_by_venue[venue]
                    },
                    ignore_unregistered=True,
                )
                graph, duplicates = graph_core_events(
                    GRAPH_ROOT,
                    venue,
                    day,
                    statics[venue],
                )
                day_summary, day_exceptions = compare_event_maps(
                    day,
                    venue,
                    raw,
                    graph,
                    duplicates,
                )
            summaries.extend(day_summary)
            exceptions.extend(day_exceptions)
        if count % 10 == 0 or count == len(audit_days):
            print(
                f"  V2 exact event comparisons [{count:,}/{len(audit_days):,}]; "
                f"exceptions={len(exceptions):,}",
                flush=True,
            )

    summary = pd.DataFrame(summaries, columns=SUMMARY_COLUMNS)
    exception_frame = pd.DataFrame(exceptions, columns=EXCEPTION_COLUMNS)
    _write_parquet(summary, V2_EVENT_SOURCE_SUMMARY)
    _write_parquet(exception_frame, V2_EVENT_SOURCE_EXCEPTIONS)
    totals = summary[
        [
            "raw_events",
            "graph_events",
            "matched_identities",
            "missing_from_graph",
            "graph_only",
            "graph_duplicate_identities",
            "amount_mismatches",
        ]
    ].sum().astype(int).to_dict()
    certificate = {
        "schema_version": V2_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass" if not exceptions and bool(summary["passed"].all()) else "fail",
        "audit_calendar_sha256": audit_calendar_sha256(audit_days),
        "audit_dates": len(audit_days),
        "first_day": audit_days[0],
        "last_day": audit_days[-1],
        "summary_rows": len(summary),
        "exception_rows": len(exception_frame),
        "venues": list(V2_EVENT_VENUES),
        "event_types": list(V2_CORE_EVENTS),
        "pool_perimeter": V2_POOL_PERIMETER,
        "registry_source": "complete_factory_PairCreated_histories",
        "global_event_query": "topic_only_without_address_filter",
        "factory_pairs": len(all_pairs),
        "factory_pairs_by_venue": {
            venue: len(pairs_by_venue[venue]) for venue in V2_EVENT_VENUES
        },
        "factory_registry_sha256": _registry_sha256(all_pairs),
        "identity_fields": [
            "venue",
            "event_type",
            "block_number",
            "transaction_hash",
            "log_index",
            "pool",
        ],
        "quantity_contract": "exact_raw_token_deltas_and_swap_in_out_fields",
        "raw_factory_chunks": sum(len(ranges) for ranges in factory_ranges.values()),
        "raw_event_chunks": sum(len(ranges) for ranges in event_ranges.values()),
        "raw_global_event_logs": raw_global_logs,
        **totals,
        "interpretation": (
            "Exact global Ethereum topic logs certify every Mint, Burn, and Swap identity "
            "and raw token amount on the construction-audit calendar for every pair emitted "
            "by the two registered factories; these dates are not an estimation sample."
        ),
    }
    V2_EVENT_SOURCE_CERTIFICATE.parent.mkdir(parents=True, exist_ok=True)
    write_json(V2_EVENT_SOURCE_CERTIFICATE, certificate)
    inputs: list[Path] = [UNIFIED_QUALITY_PANEL, TOKEN_DECIMALS]
    inputs.extend(_day_bound_path(day) for day in day_bounds)
    inputs.extend(_factory_deployment_path(venue) for venue in V2_EVENT_VENUES)
    for venue, ranges in factory_ranges.items():
        for start, end in ranges:
            inputs.extend(factory_chunk_paths(venue, start, end))
    for day in audit_days:
        for venue in _launched_venues(day):
            inputs.append(_meta_path(venue, day))
            inputs.extend(_graph_event_paths(venue, day))
        for start, end in event_ranges.get(day, []):
            inputs.extend(event_chunk_paths(day, start, end))
    notes = "exact 77-date V2-family Mint/Burn/Swap global-chain source certificate"
    for path, rows in (
        (V2_EVENT_SOURCE_SUMMARY, len(summary)),
        (V2_EVENT_SOURCE_EXCEPTIONS, len(exception_frame)),
        (V2_EVENT_SOURCE_CERTIFICATE, 1),
    ):
        stamp(path, code_sources=CODE_SOURCES, inputs=inputs, rows=rows, notes=notes)
    if certificate["status"] == "pass":
        validate_v2_event_source_certificate(summary, exception_frame, certificate, audit_days)
    return len(summary), len(exception_frame)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true", help="audit complete cached RPC chunks only")
    parser.add_argument("--force", action="store_true", help="refetch every exact RPC chunk")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--factory-chunk-size", type=int, default=DEFAULT_FACTORY_CHUNK_SIZE)
    parser.add_argument("--event-block-chunk-size", type=int, default=DEFAULT_EVENT_BLOCK_CHUNK_SIZE)
    args = parser.parse_args()
    if args.factory_chunk_size < 1 or args.event_block_chunk_size < 1:
        raise ValueError("block chunk sizes must be positive")
    _preflight_graph_streams(transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL))
    with ExitStack() as stack:
        stack.enter_context(exclusive_job(RAW_MARKET_DATA_LOCK, job="V2 exact event-source audit"))
        stack.enter_context(exclusive_job(MARKET_STATE_LOCK, job="V2 exact event-source audit"))
        rows, exceptions = build(
            fetch=not args.no_fetch,
            force=args.force,
            workers=args.workers,
            factory_chunk_size=args.factory_chunk_size,
            event_block_chunk_size=args.event_block_chunk_size,
        )
    print(f"COMPLETE: V2 event-source rows={rows:,}; exceptions={exceptions:,}")
    return int(exceptions > 0)


if __name__ == "__main__":
    raise SystemExit(main())
