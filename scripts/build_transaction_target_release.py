#!/usr/bin/env python3
"""Build immutable provider target ledgers after independent chain-log validation on the current audit calendar."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd
import pyarrow.parquet as pq

from ddvc.data_release import require_node_d_release
from ddvc.ethereum_blocks import fetch_block_header, iter_block_header_snapshot, write_block_header_snapshot
from ddvc.ethereum_day_cuts import day_bound_path, load_utc_day_block_bounds
from ddvc.ethereum_logs import exact_log_block_ranges, fetch_exact_logs_with_evidence, file_sha256, write_exact_log_chunk
from ddvc.paths import DATA_DIR, REPO_ROOT, V3_INVENTORY_RAW_ROOT
from ddvc.pricing.tick_replay import TickReplayEvent, load_tick_day_events
from ddvc.pricing.v2_replay import V2ReplayDay, V2_VENUES, load_v2_replay_day
from ddvc.provenance import cache_key, sidecar_path
from ddvc.realised import LINEAR_ROUTE_COLUMNS
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days, transaction_frontier_audit_days
from ddvc.runtime import exclusive_job, interruptible_thread_pool
from ddvc.source_records import transaction_id
from ddvc.state_data import STATE_ROOT, cp_partition_path, tick_partition_path
from ddvc.transaction_targets import (
    EXACT_VENUES,
    TARGET_RELEASE_ROOT,
    ChainSwapEvent,
    ProviderSwapEvent,
    TargetEvidenceError,
    build_provider_target_ledger,
    calendar_sha256,
    daily_validation_contract,
    decode_v2_chain_swap,
    decode_v3_chain_swap,
    decode_v4_chain_swap,
    exact_target_leg_identities,
    provider_event_from_tick,
    provider_event_from_v2,
    publish_target_release,
    resolve_target_release,
    target_generation_root,
    validate_target_day,
    validate_v4_exact_log_chunk,
    validation_contract,
    write_target_day,
)
from ddvc.v2_event_completeness import V2_EXACT_LOG_CACHE_ROOT, frozen_upper_block_path, read_v2_event_source_certificate, read_v2_exact_logs, resolve_v2_event_source_release
from ddvc.v3_event_completeness import block_perimeter_sha256, certified_header_snapshot_path, read_v3_event_source_release, resolve_v3_event_source_release
from ddvc.v3_inventory import EVENT_TOPICS as V3_EVENT_TOPICS, inventory_chunk_triplet, load_inventory_chunk_records
from ddvc.v3_pool_registry import load_certified_frozen_upper
from ddvc.v4_quarantine import V4_STATIC_QUARANTINE_PANEL, load_v4_static_quarantine
from ddvc.v4_contract import UNISWAP_V4_POOL_MANAGER_ADDRESS, UNISWAP_V4_SWAP_TOPIC


UNIFIED = DATA_DIR / "unified"
V4_TARGET_LOG_ROOT = DATA_DIR / "raw" / "ethereum" / "v4_transaction_target_swaps"
TARGET_HEADER_ROOT = DATA_DIR / "raw" / "ethereum" / "transaction_target_block_headers"
LOCK = DATA_DIR / "processed" / ".transaction_target_release.lock"
BUILD_SOURCES = [
    "scripts/build_transaction_target_release.py",
    "src/ddvc/amounts.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/ethereum_blocks.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/ethereum_logs.py",
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/v2_replay.py",
    "src/ddvc/realised.py",
    "src/ddvc/release_calendar.py",
    "src/ddvc/source_records.py",
    "src/ddvc/transaction_targets.py",
    "src/ddvc/v2_event_completeness.py",
    "src/ddvc/v3_event_completeness.py",
    "src/ddvc/v3_inventory.py",
    "src/ddvc/v4_contract.py",
    "src/ddvc/v4_quarantine.py",
]


def portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def file_lineage(paths: Iterable[Path]) -> dict[str, str]:
    files = sorted({Path(path) for path in paths if Path(path).is_file()})
    return {portable_path(path): file_sha256(path) for path in files}


def release_dependencies() -> list[Path]:
    v2_release = resolve_v2_event_source_release()
    v3_release = resolve_v3_event_source_release()
    paths = [
        UNIFIED_QUALITY_PANEL,
        sidecar_path(UNIFIED_QUALITY_PANEL),
        V4_STATIC_QUARANTINE_PANEL,
        sidecar_path(V4_STATIC_QUARANTINE_PANEL),
        *v2_release.artifact_paths,
        *v3_release.artifact_paths,
        V3_INVENTORY_RAW_ROOT / "ordered_chunks.complete.json",
    ]
    return [Path(path) for path in paths]


def target_generation_id(scope: str, audit_days: list[str], full_days: list[str], dependencies: list[Path]) -> str:
    identity = {
        "scope": scope,
        "audit_calendar_sha256": calendar_sha256(audit_days),
        "full_calendar_sha256": calendar_sha256(full_days),
        "dependency_cache_key": cache_key(BUILD_SOURCES, inputs=dependencies, length=64),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_provider_day(day: str, quarantined_v4_pools: set[str]) -> tuple[pd.DataFrame, dict[tuple[str, str, int], ProviderSwapEvent], dict[tuple[str, str, int], ProviderSwapEvent], list[Path]]:
    unified = UNIFIED / f"{day}.parquet"
    legs = pd.read_parquet(unified, columns=LINEAR_ROUTE_COLUMNS)
    identities = exact_target_leg_identities(legs)
    v2_replay = load_v2_replay_day(STATE_ROOT, day, venues=V2_VENUES)
    tick_events = load_tick_day_events(STATE_ROOT, day, venues=("uniswap_v3", "uniswap_v4"))
    v2_events: dict[tuple[str, str, int], ProviderSwapEvent] = {}
    for key in sorted(identity for identity in identities if identity[0] in V2_VENUES):
        source = v2_replay.swaps_by_identity.get(key)
        if source is None:
            raise TargetEvidenceError(f"canonical V2 state lacks target swap identity: {key}")
        v2_events[key] = provider_event_from_v2(source)
    tick_by_identity: dict[tuple[str, str, int], TickReplayEvent] = {}
    for event in tick_events:
        if event.kind != "swap":
            continue
        tx_hash = transaction_id(event.row)
        if not tx_hash:
            continue
        key = (event.venue, str(tx_hash).lower(), int(event.order[1]))
        if key in identities:
            prior = tick_by_identity.get(key)
            if prior is not None and prior.row != event.row:
                raise TargetEvidenceError(f"canonical tick state has conflicting target identity: {key}")
            tick_by_identity[key] = event
    tick_provider = {
        key: provider_event_from_tick(event, v4_quarantined_pools=quarantined_v4_pools)
        for key, event in tick_by_identity.items()
    }
    observed = set(v2_events) | set(tick_provider)
    if observed != identities:
        raise TargetEvidenceError(f"provider target perimeter is incomplete on {day}: missing={sorted(identities - observed)[:3]}, extra={sorted(observed - identities)[:3]}")
    inputs = [
        unified,
        *(cp_partition_path(venue, day, root=STATE_ROOT) for venue in V2_VENUES),
        *(tick_partition_path(venue, day, root=STATE_ROOT) for venue in ("uniswap_v3", "uniswap_v4")),
    ]
    return legs, v2_events, tick_provider, [path for path in inputs if path.is_file()]


def provider_ledger_day(day: str, quarantined_v4_pools: set[str]) -> tuple[pd.DataFrame, dict[str, object], dict[tuple[str, str, int], ProviderSwapEvent], dict[tuple[str, str, int], ProviderSwapEvent], list[Path]]:
    legs, v2_events, tick_events, inputs = load_provider_day(day, quarantined_v4_pools)
    frame, support = build_provider_target_ledger(day, legs, v2_events=v2_events, tick_events=tick_events, chain_events=None)
    return frame, support, v2_events, tick_events, inputs


def target_header_path(audit_days: list[str], blocks: Iterable[int]) -> Path:
    return TARGET_HEADER_ROOT / f"{calendar_sha256(audit_days)}-{block_perimeter_sha256(blocks)}.jsonl"


def ensure_target_header_snapshot(blocks: Iterable[int], audit_days: list[str], *, seed_paths: Iterable[Path], fetch_missing: bool, workers: int) -> Path:
    expected = sorted({int(block) for block in blocks})
    if not expected:
        raise TargetEvidenceError("audit target release has no admitted route-leg blocks")
    path = target_header_path(audit_days, expected)
    if path.is_file():
        observed = [int(row["block_number"]) for row in iter_block_header_snapshot(path, require_evidence=True)]
        if observed != expected:
            raise TargetEvidenceError("target block-header snapshot has a stale perimeter")
        return path
    expected_set = set(expected)
    headers: dict[int, dict[str, object]] = {}
    for seed in seed_paths:
        if not seed.is_file():
            continue
        for row in iter_block_header_snapshot(seed, require_evidence=True):
            block = int(row["block_number"])
            if block not in expected_set:
                continue
            prior = headers.get(block)
            if prior is not None and prior != row:
                raise TargetEvidenceError(f"retained block-header evidence conflicts at block {block}")
            headers[block] = row
    missing = sorted(expected_set - set(headers))
    if missing and not fetch_missing:
        raise FileNotFoundError(f"target block-header evidence is missing for {len(missing):,} blocks; rerun with --fetch-header-evidence")
    if missing:
        with interruptible_thread_pool(max_workers=max(1, min(int(workers), 8))) as executor:
            futures = {executor.submit(fetch_block_header, block, require_evidence=True): block for block in missing}
            for index, future in enumerate(as_completed(futures), 1):
                block = futures[future]
                headers[block] = future.result()
                if index % 1_000 == 0 or index == len(futures):
                    print(f"  exact target block headers [{index:,}/{len(futures):,}]", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_block_header_snapshot((headers[block] for block in expected), path, require_evidence=True, presorted=True)
    observed = [int(row["block_number"]) for row in iter_block_header_snapshot(path, require_evidence=True)]
    if observed != expected:
        raise TargetEvidenceError("installed target block-header snapshot has a stale perimeter")
    return path


def v4_chunk_paths(lower: int, upper: int, *, root: Path = V4_TARGET_LOG_ROOT) -> tuple[Path, Path]:
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return root / f"{stem}.parquet", root / f"{stem}.meta.json"


def _fetch_v4_chunk(lower: int, upper: int, frozen_upper: Mapping[str, object], root: Path) -> tuple[int, int]:
    raw, marker = v4_chunk_paths(lower, upper, root=root)
    records, evidence = fetch_exact_logs_with_evidence(start_block=lower, end_block=upper, topics=[UNISWAP_V4_SWAP_TOPIC], address=UNISWAP_V4_POOL_MANAGER_ADDRESS, frozen_upper=dict(frozen_upper))
    write_exact_log_chunk(raw, marker, records, {"schema_version": 1, "kind": "uniswap_v4_poolmanager_target_swaps", "start_block": lower, "end_block": upper, "address_filter": UNISWAP_V4_POOL_MANAGER_ADDRESS, "event_topics": [UNISWAP_V4_SWAP_TOPIC], **evidence})
    validate_v4_exact_log_chunk(raw, marker, start_block=lower, end_block=upper, frozen_upper=frozen_upper)
    return lower, upper


def ensure_v4_day_logs(day: str, frozen_upper: Mapping[str, object], *, fetch_missing: bool, workers: int, root: Path = V4_TARGET_LOG_ROOT) -> tuple[list[dict[str, object]], list[Path]]:
    bounds = load_utc_day_block_bounds(day)
    start = int(bounds["start_block"])
    end = int(bounds["end_block"])
    ranges = exact_log_block_ranges(start, end)
    missing = [(lower, upper) for lower, upper in ranges if not all(path.is_file() for path in v4_chunk_paths(lower, upper, root=root))]
    if missing and not fetch_missing:
        raise FileNotFoundError(f"V4 exact target-log evidence is missing for {len(missing):,} chunks on {day}; rerun with --fetch-v4-evidence")
    if missing:
        with interruptible_thread_pool(max_workers=max(1, min(int(workers), 6))) as executor:
            futures = {executor.submit(_fetch_v4_chunk, lower, upper, frozen_upper, root): (lower, upper) for lower, upper in missing}
            for index, future in enumerate(as_completed(futures), 1):
                future.result()
                if index % 250 == 0 or index == len(futures):
                    print(f"  exact V4 log chunks for {day} [{index:,}/{len(futures):,}]", flush=True)
    records: list[dict[str, object]] = []
    inputs: list[Path] = []
    for lower, upper in ranges:
        raw, marker = v4_chunk_paths(lower, upper, root=root)
        records.extend(validate_v4_exact_log_chunk(raw, marker, start_block=lower, end_block=upper, frozen_upper=frozen_upper))
        inputs.extend((raw, marker))
    return records, inputs


def v3_inventory_ranges() -> list[tuple[int, int]]:
    path = V3_INVENTORY_RAW_ROOT / "ordered_chunks.complete.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    chunks = record.get("chunks")
    if record.get("status") != "complete" or not isinstance(chunks, list) or not chunks:
        raise TargetEvidenceError("V3 exact-log ordered manifest is absent or stale")
    ranges = [(int(chunk["lower"]), int(chunk["upper"])) for chunk in chunks]
    if ranges != sorted(ranges) or any(left[1] + 1 != right[0] for left, right in zip(ranges, ranges[1:])):
        raise TargetEvidenceError("V3 exact-log ordered manifest is not contiguous")
    return ranges


def exact_chain_events_for_day(day: str, providers: Mapping[tuple[str, str, int], ProviderSwapEvent], block_timestamps: Mapping[int, int], *, frozen_v2: Mapping[str, object], frozen_v3: Mapping[str, object], v3_ranges: list[tuple[int, int]], fetch_v4: bool, workers: int) -> tuple[dict[tuple[str, str, int], ChainSwapEvent], list[Path]]:
    supported = {key: event for key, event in providers.items() if event.quote_supported}
    bounds = load_utc_day_block_bounds(day)
    lower, upper = int(bounds["start_block"]), int(bounds["end_block"])
    chain: dict[tuple[str, str, int], ChainSwapEvent] = {}
    inputs = [day_bound_path(day)]

    v2_expected = {key: event for key, event in supported.items() if key[0] in V2_VENUES}
    if v2_expected:
        records, paths = read_v2_exact_logs(lower, upper, frozen_upper=dict(frozen_v2), root=V2_EXACT_LOG_CACHE_ROOT)
        raw = {(str(record["transaction_hash"]).lower(), int(record["log_index"]), str(record["address"]).lower()): record for record in records}
        for key, provider in v2_expected.items():
            record = raw.get((provider.tx_hash, provider.log_index, provider.pool))
            if record is None:
                raise TargetEvidenceError(f"V2 exact logs lack target identity: {key}")
            chain[key] = decode_v2_chain_swap(provider.venue, record, block_timestamps=block_timestamps)
        inputs.extend(paths)

    v3_expected = {key: event for key, event in supported.items() if key[0] == "uniswap_v3"}
    if v3_expected:
        expected_raw = {(event.tx_hash, event.log_index, event.pool): key for key, event in v3_expected.items()}
        for chunk_lower, chunk_upper in v3_ranges:
            if chunk_upper < lower or chunk_lower > upper:
                continue
            records, _marker, _schema = load_inventory_chunk_records(chunk_lower, chunk_upper, V3_INVENTORY_RAW_ROOT, frozen_upper=dict(frozen_v3), event_topics={V3_EVENT_TOPICS["swap"]})
            for record in records:
                raw_key = (str(record["transaction_hash"]).lower(), int(record["log_index"]), str(record["address"]).lower())
                target_key = expected_raw.get(raw_key)
                if target_key is not None:
                    if target_key in chain:
                        raise TargetEvidenceError(f"V3 exact logs duplicate target identity: {target_key}")
                    chain[target_key] = decode_v3_chain_swap(record, block_timestamps=block_timestamps)
            inputs.extend(inventory_chunk_triplet(chunk_lower, chunk_upper, V3_INVENTORY_RAW_ROOT))

    v4_expected = {key: event for key, event in supported.items() if key[0] == "uniswap_v4"}
    if v4_expected:
        records, paths = ensure_v4_day_logs(day, frozen_v3, fetch_missing=fetch_v4, workers=workers)
        expected_v4 = {(event.tx_hash, event.log_index, event.pool): key for key, event in v4_expected.items()}
        for record in records:
            decoded = decode_v4_chain_swap(record, block_timestamps=block_timestamps)
            target_key = expected_v4.get((decoded.tx_hash, decoded.log_index, decoded.pool))
            if target_key is not None:
                if target_key in chain:
                    raise TargetEvidenceError(f"V4 exact logs duplicate target identity: {target_key}")
                chain[target_key] = decoded
        inputs.extend(paths)

    if set(chain) != set(supported):
        raise TargetEvidenceError(f"exact chain-log target perimeter is incomplete on {day}: missing={sorted(set(supported) - set(chain))[:3]}, extra={sorted(set(chain) - set(supported))[:3]}")
    return chain, inputs


def build_audit_release(audit_days: list[str], full_days: list[str], generation: str, dependencies: list[Path], *, fetch_v4: bool, fetch_headers: bool, workers: int) -> None:
    quarantined = load_v4_static_quarantine()
    directory = target_generation_root(generation)
    target_blocks: set[int] = set()
    for index, day in enumerate(audit_days, 1):
        frame, _support, _v2, _tick, _inputs = provider_ledger_day(day, quarantined)
        admitted = frame[frame["target_admitted"].astype(bool)] if not frame.empty else frame
        target_blocks.update(pd.to_numeric(admitted["leg1_block_number"], errors="raise").astype(int).tolist())
        target_blocks.update(pd.to_numeric(admitted["leg2_block_number"], errors="raise").astype(int).tolist())
        if index % 12 == 0 or index == len(audit_days):
            print(f"  audit target-block perimeter [{index:,}/{len(audit_days):,}] unique_blocks={len(target_blocks):,}", flush=True)

    _v3_summary, _v3_exceptions, _v3_quarantine, v3_certificate = read_v3_event_source_release()
    v3_seed = certified_header_snapshot_path(audit_days, v3_certificate)
    header_snapshot = ensure_target_header_snapshot(target_blocks, audit_days, seed_paths=[v3_seed], fetch_missing=fetch_headers, workers=workers)
    timestamps = {int(row["block_number"]): int(row["timestamp"]) for row in iter_block_header_snapshot(header_snapshot, require_evidence=True)}
    _v2_summary, _v2_exceptions, v2_certificate = read_v2_event_source_certificate()
    frozen_v2_path = frozen_upper_block_path(int(v2_certificate["factory_registry_upper_block"]))
    frozen_v2 = json.loads(frozen_v2_path.read_text(encoding="utf-8"))
    frozen_v3, _factory_certificate = load_certified_frozen_upper()
    ranges = v3_inventory_ranges()
    markers: list[Path] = []
    verified = 0
    for index, day in enumerate(audit_days, 1):
        marker = directory / "days" / f"{day}.json"
        if marker.is_file():
            record = validate_target_day(marker, scope="audit", generation=generation)
            markers.append(marker)
            verified += int(record["support"]["verified_chain_log_legs"])
            continue
        legs, v2_events, tick_events, provider_inputs = load_provider_day(day, quarantined)
        providers = {**v2_events, **tick_events}
        chain_events, evidence_inputs = exact_chain_events_for_day(day, providers, timestamps, frozen_v2=frozen_v2, frozen_v3=frozen_v3, v3_ranges=ranges, fetch_v4=fetch_v4, workers=workers)
        frame, support = build_provider_target_ledger(day, legs, v2_events=v2_events, tick_events=tick_events, chain_events=chain_events)
        verified += int(support["verified_chain_log_legs"])
        marker = write_target_day(directory, day, frame, support, scope="audit", generation=generation, lineage=file_lineage([*provider_inputs, *evidence_inputs, header_snapshot]))
        markers.append(marker)
        if index % 6 == 0 or index == len(audit_days):
            released_rows = sum(int(json.loads(path.read_text())["rows"]) for path in markers)
            print(f"  audit target ledgers [{index:,}/{len(audit_days):,}] routes={released_rows:,} verified_legs={verified:,}", flush=True)
    validation = validation_contract(verified_legs=verified, evidence_failures=0, audit_calendar=audit_days, full_calendar=full_days)
    release = publish_target_release(directory, markers, scope="audit", generation=generation, validation=validation, full_calendar=full_days, code_sources=BUILD_SOURCES, inputs=[*dependencies, header_snapshot, frozen_v2_path, v3_seed], root=TARGET_RELEASE_ROOT)
    print(f"PASS: audit target release dates={len(release.calendar):,}; verified_legs={verified:,}; zero-failure 95% upper bound={float(validation['per_leg_mismatch_upper_bound']):.6%}; day coverage={float(validation['day_coverage_share']):.2%}", flush=True)


def build_daily_release(audit_days: list[str], full_days: list[str], generation: str, dependencies: list[Path]) -> None:
    audit_release = resolve_target_release("audit", expected_days=audit_days)
    validation = daily_validation_contract(audit_release, full_calendar=full_days)
    quarantined = load_v4_static_quarantine()
    directory = target_generation_root(generation)
    markers: list[Path] = []
    rows = 0
    for index, day in enumerate(full_days, 1):
        marker = directory / "days" / f"{day}.json"
        if marker.is_file():
            record = validate_target_day(marker, scope="daily", generation=generation)
            markers.append(marker)
            rows += int(record["rows"])
            continue
        frame, support, _v2_events, _tick_events, inputs = provider_ledger_day(day, quarantined)
        marker = write_target_day(directory, day, frame, support, scope="daily", generation=generation, lineage=file_lineage(inputs))
        markers.append(marker)
        rows += len(frame)
        if index % 30 == 0 or index == len(full_days):
            print(f"  daily target ledgers [{index:,}/{len(full_days):,}] routes={rows:,}", flush=True)
    release = publish_target_release(directory, markers, scope="daily", generation=generation, validation=validation, full_calendar=full_days, code_sources=BUILD_SOURCES, inputs=[*dependencies, audit_release.pointer_path, audit_release.manifest_path], root=TARGET_RELEASE_ROOT)
    print(f"PASS: provider-derived daily target release dates={len(release.calendar):,}; routes={rows:,}; conditioned audit dates={int(validation['validation_dates']):,}; day coverage={float(validation['day_coverage_share']):.2%}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--audit-calendar", action="store_true", help="build the current fixed-calendar chain-log validation release")
    scope.add_argument("--daily-calendar", action="store_true", help="build the full provider-derived target release after the audit passes")
    parser.add_argument("--fetch-v4-evidence", action="store_true", help="fetch missing exact V4 PoolManager Swap-log chunks for audit dates")
    parser.add_argument("--fetch-header-evidence", action="store_true", help="fetch missing exact target-block headers for audit dates")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    try:
        require_node_d_release(routes=True, market_state=True)
        full_days = released_route_days(UNIFIED_QUALITY_PANEL, nonempty=False)
        audit_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
        dependencies = release_dependencies()
        selected_scope = "audit" if args.audit_calendar else "daily"
        generation = target_generation_id(selected_scope, audit_days, full_days, dependencies)
        with exclusive_job(LOCK):
            if selected_scope == "audit":
                build_audit_release(audit_days, full_days, generation, dependencies, fetch_v4=args.fetch_v4_evidence, fetch_headers=args.fetch_header_evidence, workers=args.workers)
            else:
                build_daily_release(audit_days, full_days, generation, dependencies)
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TargetEvidenceError, TypeError, ValueError) as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
