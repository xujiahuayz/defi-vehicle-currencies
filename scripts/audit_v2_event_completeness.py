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

from ddvc.ethereum_day_cuts import (
    RAW_DAY_BOUND_ROOT,
    day_bound_path,
    fetch_block_timestamp,
    utc_day_block_bounds,
    validate_utc_day_block_bounds,
)
from ddvc.ethereum_logs import rpc_post_with_evidence
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
    RAW_V2_FACTORY_ROOT,
    V2_CORE_EVENTS,
    V2_EXACT_LOG_CHUNK_SIZE,
    V2_EVENT_SOURCE_CERTIFICATE,
    V2_EVENT_SOURCE_EXCEPTIONS,
    V2_EVENT_SOURCE_SCHEMA_VERSION,
    V2_EVENT_SOURCE_SUMMARY,
    V2_EVENT_VENUES,
    V2_FACTORIES,
    V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
    V2_POOL_PERIMETER,
    audit_calendar_sha256,
    compare_event_maps,
    factory_deployment_path,
    factory_pair_registry,
    factory_coverage_manifest_path,
    factory_registry_sha256,
    factory_root_ranges,
    factory_state_proof_path,
    fetch_v2_exact_log_chunk,
    fetch_factory_root_adaptive,
    frozen_upper_block_path,
    graph_core_events,
    load_or_build_factory_state_proof,
    load_or_resolve_frozen_upper_block,
    missing_v2_exact_log_ranges,
    raw_core_events,
    read_factory_coverage_records,
    read_v2_exact_logs,
    validate_v2_event_source_certificate,
    validate_factory_deployment_proof,
    validate_factory_coverage_manifest,
    v2_exact_log_ranges,
    write_factory_coverage_manifest,
)


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"
DEFAULT_EVENT_BLOCK_CHUNK_SIZE = V2_EXACT_LOG_CHUNK_SIZE
MAX_JOB_ATTEMPTS = 12
CODE_SOURCES = [
    "scripts/audit_v2_event_completeness.py",
    "src/ddvc/amounts.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/ethereum_blocks.py",
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
    return day_bound_path(day)


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


def _code_at_block(
    factory: str,
    block: int,
    evidence: list[dict[str, object]],
    *,
    block_hash: str | None = None,
) -> str:
    block_reference: object = (
        {"blockHash": block_hash, "requireCanonical": True}
        if block_hash is not None
        else hex(block)
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getCode",
        "params": [factory, block_reference],
    }
    envelope = rpc_post_with_evidence(payload, timeout=30, retries=3)
    response = envelope.response
    if isinstance(response, dict) and response.get("error") is not None:
        raise RuntimeError(f"eth_getCode failed at the frozen canonical block hash: {response['error']}")
    code = response.get("result") if isinstance(response, dict) else None
    if not isinstance(code, str) or not code.startswith("0x"):
        raise RuntimeError(f"eth_getCode lacks an exact result for {factory}/{block}")
    evidence.append(
        {
            "request": payload,
            "response": response,
            "response_sha256": hashlib.sha256(
                json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "rpc_endpoint": envelope.endpoint,
            "rpc_attempts": list(envelope.attempts),
        }
    )
    return code


def load_or_resolve_factory_deployment(
    venue: str,
    upper: int,
    upper_hash: str,
    *,
    fetch: bool = True,
) -> dict[str, object]:
    """Find the exact first block containing factory bytecode, with RPC evidence."""

    path = factory_deployment_path(venue, upper)
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        validate_factory_deployment_proof(cached, venue, upper, upper_hash)
        return cached
    if not fetch:
        raise RuntimeError(f"V2 event-source audit lacks factory deployment evidence for {venue}")
    factory = V2_FACTORIES[venue]
    evidence: list[dict[str, object]] = []
    upper_code = _code_at_block(factory, upper, evidence, block_hash=upper_hash)
    if upper_code in {"0x", "0x0"}:
        raise RuntimeError(f"registered {venue} factory has no code by block {upper}")
    frozen_upper = upper
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
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": factory,
        "deployment_block": upper,
        "upper_block": frozen_upper,
        "upper_block_hash": upper_hash,
        "runtime_code_sha256": hashlib.sha256(bytes.fromhex(upper_code.removeprefix("0x"))).hexdigest(),
        "rpc_evidence": evidence,
    }
    validate_factory_deployment_proof(record, venue, frozen_upper, upper_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


FetchJob = tuple[str, str, int, int]


def run_fetch_jobs(
    jobs: list[FetchJob],
    *,
    frozen_upper: dict[str, object],
    workers: int,
    max_attempts: int,
) -> None:
    queue = deque((*job, 1) for job in jobs)
    complete = 0
    failures: list[tuple[str, str, int, int, str]] = []
    with interruptible_thread_pool(max_workers=workers) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < workers:
                kind, label, start, end, attempt = queue.popleft()
                future = executor.submit(
                    fetch_v2_exact_log_chunk,
                    start,
                    end,
                    frozen_upper=frozen_upper,
                )
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


def fetch_factory_roots(
    venue: str,
    roots: list[tuple[int, int]],
    *,
    frozen_upper: dict[str, object],
    workers: int,
    max_attempts: int,
) -> list[tuple[int, int]]:
    """Run independent adaptive roots concurrently while keeping each split tree serial."""

    queue = deque((start, end, 1) for start, end in roots)
    leaves: list[tuple[int, int]] = []
    failures: list[tuple[int, int, str]] = []
    complete = 0
    with interruptible_thread_pool(max_workers=max(1, min(workers, 4))) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < max(1, min(workers, 4)):
                start, end, attempt = queue.popleft()
                future = executor.submit(
                    fetch_factory_root_adaptive,
                    venue,
                    start,
                    end,
                    frozen_upper=frozen_upper,
                )
                futures[future] = (start, end, attempt)
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                start, end, attempt = futures.pop(future)
                try:
                    leaves.extend(future.result())
                except Throttled as error:
                    if attempt < max_attempts:
                        queue.append((start, end, attempt + 1))
                    else:
                        failures.append((start, end, type(error).__name__))
                    continue
                complete += 1
                if complete % 100 == 0 or complete + len(failures) == len(roots):
                    print(
                        f"  {venue} factory roots [{complete:,}/{len(roots):,}]; "
                        f"leaves={len(leaves):,}; queued={len(queue):,}; "
                        f"terminal_failures={len(failures):,}",
                        flush=True,
                    )
    if failures:
        raise RuntimeError(
            f"{venue} factory fetch exhausted retries for {len(failures):,} roots; "
            f"first={failures[:3]}"
        )
    return sorted(leaves)


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        frame.to_parquet(temporary, index=False)


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
    event_block_chunk_size: int,
) -> tuple[int, int]:
    if event_block_chunk_size != V2_EXACT_LOG_CHUNK_SIZE:
        raise ValueError(
            "V2 exact-log cache uses one canonical 50-block chunk size"
        )
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
    frozen_upper = load_or_resolve_frozen_upper_block(
        maximum_block,
        fetch=fetch,
    )
    deployments = {
        venue: load_or_resolve_factory_deployment(
            venue,
            maximum_block,
            str(frozen_upper["block_hash"]),
            fetch=fetch,
        )
        for venue in V2_EVENT_VENUES
    }

    event_ranges: dict[str, list[tuple[int, int]]] = {}
    jobs: list[FetchJob] = []
    if force:
        print("  force rebuild requested; complete raw chunks remain immutable", flush=True)
    for day, bounds in day_bounds.items():
        ranges = v2_exact_log_ranges(
            int(bounds["start_block"]),
            int(bounds["end_block"]),
        )
        event_ranges[day] = ranges
    jobs.extend(
        ("event", "shared", start, end)
        for start, end in missing_v2_exact_log_ranges(
            (
                (int(bounds["start_block"]), int(bounds["end_block"]))
                for bounds in day_bounds.values()
            ),
            frozen_upper=frozen_upper,
        )
    )
    if jobs and not fetch:
        counts = Counter(job[0] for job in jobs)
        raise RuntimeError(
            f"V2 event-source audit has {len(jobs):,} incomplete raw chunks: {dict(counts)}"
        )
    if jobs:
        run_fetch_jobs(
            jobs,
            frozen_upper=frozen_upper,
            workers=max(1, min(workers, 4)),
            max_attempts=MAX_JOB_ATTEMPTS,
        )

    statics: dict[str, dict] = {}
    pairs_by_venue: dict[str, list] = {}
    factory_manifests: dict[str, dict[str, object]] = {}
    factory_state_proofs: dict[str, dict[str, object]] = {}
    factory_inputs: list[Path] = []
    all_pairs = []
    pool_owner: dict[str, str] = {}
    for venue, deployment in deployments.items():
        deployment_block = int(deployment["deployment_block"])
        manifest_path = factory_coverage_manifest_path(venue, maximum_block)
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_factory_coverage_manifest(
                manifest,
                venue=venue,
                deployment_block=deployment_block,
                frozen_upper=frozen_upper,
            )
        else:
            if not fetch:
                raise RuntimeError(f"V2 factory registry lacks exact coverage for {venue}")
            roots = factory_root_ranges(deployment_block, maximum_block)
            leaves = fetch_factory_roots(
                venue,
                roots,
                frozen_upper=frozen_upper,
                workers=workers,
                max_attempts=MAX_JOB_ATTEMPTS,
            )
            manifest = write_factory_coverage_manifest(
                venue,
                deployment_block,
                frozen_upper,
                leaves,
            )
        records, raw_inputs = read_factory_coverage_records(
            manifest,
            venue=venue,
            deployment_block=deployment_block,
            frozen_upper=frozen_upper,
        )
        venue_statics, venue_pairs = factory_pair_registry(venue, records, token_decimals)
        if not venue_pairs:
            raise RuntimeError(f"independent factory registry is empty for {venue}")
        state_proof = load_or_build_factory_state_proof(
            venue,
            venue_pairs,
            frozen_upper,
            fetch=fetch,
            workers=workers,
        )
        for pool in venue_statics:
            prior = pool_owner.get(pool)
            if prior is not None and prior != venue:
                raise RuntimeError(f"factory pool collision: {pool} in {prior} and {venue}")
            pool_owner[pool] = venue
        statics[venue] = venue_statics
        pairs_by_venue[venue] = venue_pairs
        factory_manifests[venue] = manifest
        factory_state_proofs[venue] = state_proof
        factory_inputs.extend(raw_inputs)
        factory_inputs.extend((manifest_path, factory_state_proof_path(venue, maximum_block)))
        all_pairs.extend(venue_pairs)

    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    raw_global_logs = 0
    event_inputs: dict[str, list[Path]] = {}
    for count, day in enumerate(audit_days, 1):
        if day in day_bounds:
            records, event_inputs[day] = read_v2_exact_logs(
                int(day_bounds[day]["start_block"]),
                int(day_bounds[day]["end_block"]),
                frozen_upper=frozen_upper,
            )
        else:
            records, event_inputs[day] = [], []
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
        "factory_registry_sha256": factory_registry_sha256(all_pairs),
        "factory_registry_upper_block": maximum_block,
        "factory_registry_upper_block_hash": frozen_upper["block_hash"],
        "factory_registry_upper_block_timestamp": frozen_upper["timestamp"],
        "frozen_upper_block_sha256": hashlib.sha256(
            frozen_upper_block_path(maximum_block).read_bytes()
        ).hexdigest(),
        "factory_deployment_proof_sha256_by_venue": {
            venue: hashlib.sha256(
                factory_deployment_path(venue, maximum_block).read_bytes()
            ).hexdigest()
            for venue in V2_EVENT_VENUES
        },
        "factory_coverage_manifest_sha256_by_venue": {
            venue: hashlib.sha256(
                factory_coverage_manifest_path(venue, maximum_block).read_bytes()
            ).hexdigest()
            for venue in V2_EVENT_VENUES
        },
        "factory_state_proof_sha256_by_venue": {
            venue: hashlib.sha256(
                factory_state_proof_path(venue, maximum_block).read_bytes()
            ).hexdigest()
            for venue in V2_EVENT_VENUES
        },
        "factory_state_sample_size_by_venue": {
            venue: int(factory_state_proofs[venue]["sample_size"])
            for venue in V2_EVENT_VENUES
        },
        "identity_fields": [
            "venue",
            "event_type",
            "block_number",
            "transaction_hash",
            "log_index",
            "pool",
        ],
        "quantity_contract": "exact_raw_token_deltas_and_swap_in_out_fields",
        "raw_factory_chunks": sum(int(manifest["leaf_count"]) for manifest in factory_manifests.values()),
        "raw_event_chunks": sum(len(ranges) for ranges in event_ranges.values()),
        "raw_global_event_logs": raw_global_logs,
        **totals,
        "interpretation": (
            "Exact global Ethereum topic logs certify every Mint, Burn, and Swap identity "
            "and raw token amount on the construction-audit calendar for every pair emitted "
            "by the two registered factories; these dates are not an estimation sample."
        ),
    }
    if certificate["status"] == "pass":
        validate_v2_event_source_certificate(summary, exception_frame, certificate, audit_days)
    V2_EVENT_SOURCE_CERTIFICATE.parent.mkdir(parents=True, exist_ok=True)
    write_json(V2_EVENT_SOURCE_CERTIFICATE, certificate)
    inputs: list[Path] = [UNIFIED_QUALITY_PANEL, TOKEN_DECIMALS]
    inputs.extend(_day_bound_path(day) for day in day_bounds)
    inputs.append(frozen_upper_block_path(maximum_block))
    inputs.extend(factory_deployment_path(venue, maximum_block) for venue in V2_EVENT_VENUES)
    inputs.extend(factory_inputs)
    for day in audit_days:
        for venue in _launched_venues(day):
            inputs.append(_meta_path(venue, day))
            inputs.extend(_graph_event_paths(venue, day))
        inputs.extend(event_inputs[day])
    notes = "exact 77-date V2-family Mint/Burn/Swap global-chain source certificate"
    for path, rows in (
        (V2_EVENT_SOURCE_SUMMARY, len(summary)),
        (V2_EVENT_SOURCE_EXCEPTIONS, len(exception_frame)),
        (V2_EVENT_SOURCE_CERTIFICATE, 1),
    ):
        stamp(path, code_sources=CODE_SOURCES, inputs=inputs, rows=rows, notes=notes)
    return len(summary), len(exception_frame)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true", help="audit complete cached RPC chunks only")
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild derived audit artifacts without overwriting complete raw chunks",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--event-block-chunk-size", type=int, default=DEFAULT_EVENT_BLOCK_CHUNK_SIZE)
    args = parser.parse_args()
    if args.event_block_chunk_size < 1:
        raise ValueError("event block chunk size must be positive")
    if args.event_block_chunk_size != V2_EXACT_LOG_CHUNK_SIZE:
        raise ValueError("--event-block-chunk-size must be 50 for shared V2 exact-log reuse")
    _preflight_graph_streams(transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL))
    with ExitStack() as stack:
        stack.enter_context(exclusive_job(RAW_MARKET_DATA_LOCK, job="V2 exact event-source audit"))
        stack.enter_context(exclusive_job(MARKET_STATE_LOCK, job="V2 exact event-source audit"))
        rows, exceptions = build(
            fetch=not args.no_fetch,
            force=args.force,
            workers=args.workers,
            event_block_chunk_size=args.event_block_chunk_size,
        )
    print(f"COMPLETE: V2 event-source rows={rows:,}; exceptions={exceptions:,}")
    return int(exceptions > 0)


if __name__ == "__main__":
    raise SystemExit(main())
