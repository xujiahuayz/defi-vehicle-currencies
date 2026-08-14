#!/usr/bin/env python3
"""Fetch and certify exact V3/V4 state events and materialize replay inputs."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
import gzip
import json
from pathlib import Path

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.ethereum_day_cuts import load_utc_day_block_bounds, utc_day_timestamps
from ddvc.ethereum_logs import block_ranges, fetch_exact_logs_with_capacity_bisection
from ddvc.fetch.sources import get_source
from ddvc.graph_event_order import v3_pool_static_path
from ddvc.paths import V2_AUDITED_TOKEN_DECIMALS_REGISTRY, DATA_DIR, REPO_ROOT, TICK_STATE_EVENT_RAW_ROOT, V3_INVENTORY_RAW_ROOT
from ddvc.provenance import portable_content_manifest_for_paths, portable_manifest_sha256, sidecar_path
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_thread_pool
from ddvc.source_records import V4_NATIVE_CURRENCY_DECIMALS, ZERO_ADDRESS
from ddvc.tick_state_events import (
    VENUE_GENERATION_TOPICS,
    VENUE_TOPICS,
    V4_EXACT_STATE_CHUNK_SIZE,
    certificate_identity_sha256,
    certify_materialization_support,
    certify_state_event_generation,
    certify_state_event_precedence,
    load_state_event_chunk,
    iter_v4_state_events,
    scientific_support_calendar_sha256,
    write_daily_v4_state_events,
    write_daily_initializations,
    write_state_event_chunk,
)
from ddvc.token_decimals import validate_token_decimals_registry
from ddvc.v3_inventory import inventory_first_consuming_event_paths, validate_inventory_ordered_manifest
from ddvc.v3_inventory_assembly import load_v3_first_consuming_events
from ddvc.v3_inventory_calendar import RAW_DAY_CUT_ROOT
from ddvc.v3_pool_registry import (
    V3_FACTORY_DEPLOYMENT_BLOCK,
    V3_POOL_REGISTRY,
    V3_POOL_REGISTRY_CERTIFICATE,
    load_certified_frozen_upper,
    load_registry,
)
from ddvc.v4_contract import UNISWAP_V4_POOL_MANAGER_ADDRESS, UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK


LOCK = DATA_DIR / "raw" / "ethereum" / ".tick-state-events.lock"
GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
DEFAULT_CHUNK_SIZE = V4_EXACT_STATE_CHUNK_SIZE


def _v3_genesis_clamped_day_cut(day: str) -> dict[str, object]:
    """Bind V3's deployment-to-UTC-close first day to cached exact evidence."""

    path = RAW_DAY_CUT_ROOT / f"{day}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    start_timestamp, end_timestamp = utc_day_timestamps(day)
    if (
        record.get("status") != "complete"
        or record.get("day") != day
        or int(record.get("target_timestamp", -1)) != end_timestamp
    ):
        raise ValueError(f"V3 genesis day lacks a current exact UTC closing cut: {day}")
    return {
        "status": "complete",
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "start_block": V3_FACTORY_DEPLOYMENT_BLOCK,
        "end_block": int(record["day_end_block"]),
        "end_block_timestamp": int(record["day_end_block_timestamp"]),
        "after_end_block": int(record["next_block"]),
        "after_end_block_timestamp": int(record["next_block_timestamp"]),
        "initial_lower_bracket": int(record["initial_lower_bracket"]),
        "initial_upper_bracket": int(record["resolved_upper_bracket"]),
        "protocol_genesis_clamped": True,
        "protocol_genesis_block": V3_FACTORY_DEPLOYMENT_BLOCK,
        "rpc_evidence": record["rpc_evidence"],
    }


def _venue_days(venue: str, requested_start: str, requested_end: str) -> list[str]:
    genesis = get_source(venue).genesis.strftime("%Y%m%d")
    start = max(genesis, requested_start.replace("-", ""))
    end = requested_end.replace("-", "")
    return calendar_days(start, end) if start <= end else []


def _venue_day_cuts(venue: str, days: list[str]) -> dict[str, dict[str, object]]:
    cuts: dict[str, dict[str, object]] = {}
    genesis = get_source(venue).genesis.strftime("%Y%m%d")
    for day in days:
        try:
            cuts[day] = load_utc_day_block_bounds(day)
        except RuntimeError:
            if venue != "uniswap_v3" or day != genesis:
                raise
            cuts[day] = _v3_genesis_clamped_day_cut(day)
    return cuts


def _ranges(start: int, end: int, chunk_size: int) -> list[tuple[int, int]]:
    return block_ranges(start, end, chunk_size)


def _v2_scoped_token_metadata() -> tuple[dict[str, tuple[str, int]], list[Path]]:
    if not V2_AUDITED_TOKEN_DECIMALS_REGISTRY.is_file():
        raise FileNotFoundError(f"certified V2-scoped token-decimals prerequisite is absent: {V2_AUDITED_TOKEN_DECIMALS_REGISTRY}; build and certify the exact-anchor V2 decimals registry before the first tick-state subset release")
    values, _registry = validate_token_decimals_registry(V2_AUDITED_TOKEN_DECIMALS_REGISTRY)
    inputs = [V2_AUDITED_TOKEN_DECIMALS_REGISTRY]
    marker = sidecar_path(V2_AUDITED_TOKEN_DECIMALS_REGISTRY)
    if marker.is_file():
        inputs.append(marker)
    metadata = {token: ("", decimals) for token, decimals in values.items()}
    metadata[ZERO_ADDRESS] = ("ETH", V4_NATIVE_CURRENCY_DECIMALS)
    return metadata, inputs


def _optional_v3_graph_symbols(path: Path | None, exact_tokens: set[str]) -> dict[str, str]:
    """Read optional provider symbols without accepting provider identity or decimals."""

    if path is None:
        return {}
    symbols: dict[str, str] = {}
    conflicting: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            for token_row in (row.get("token0"), row.get("token1")):
                if not isinstance(token_row, dict):
                    continue
                token = str(token_row.get("id") or "").lower()
                symbol = str(token_row.get("symbol") or "")
                if token not in exact_tokens or not symbol or token in conflicting:
                    continue
                prior = symbols.get(token)
                if prior is None:
                    symbols[token] = symbol
                elif prior != symbol:
                    symbols.pop(token, None)
                    conflicting.add(token)
    return symbols


def _v3_inputs() -> tuple[dict, dict[str, tuple[str, int]], list[Path]]:
    registry_rows = load_registry()
    registry = {row.pool: row for row in registry_rows}
    exact_metadata, exact_inputs = _v2_scoped_token_metadata()
    graph_static = v3_pool_static_path(GRAPH_ROOT)
    symbols = _optional_v3_graph_symbols(graph_static, set(exact_metadata))
    metadata = {token: (symbols.get(token, symbol), decimals) for token, (symbol, decimals) in exact_metadata.items()}
    graph_inputs = [graph_static] if graph_static is not None else []
    return registry, metadata, [V3_POOL_REGISTRY, V3_POOL_REGISTRY_CERTIFICATE, *graph_inputs, *exact_inputs]


def _completed(venue: str, lower: int, upper: int, frozen_upper: dict[str, object], root: Path) -> bool:
    try:
        load_state_event_chunk(venue, lower, upper, frozen_upper=frozen_upper, root=root)
        return True
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _fetch_one(venue: str, lower: int, upper: int, frozen_upper: dict[str, object], root: Path) -> tuple[int, int, int]:
    address = UNISWAP_V4_POOL_MANAGER_ADDRESS if venue == "uniswap_v4" else None
    records, evidence = fetch_exact_logs_with_capacity_bisection(
        start_block=lower,
        end_block=upper,
        topics=list(VENUE_GENERATION_TOPICS[venue]),
        address=address,
        frozen_upper=frozen_upper,
    )
    write_state_event_chunk(venue, lower, upper, records, evidence, frozen_upper=frozen_upper, root=root)
    return lower, upper, len(records)


def _targeted_range(value: str) -> tuple[int, int]:
    try:
        lower_text, upper_text = value.split(":", 1)
        lower, upper = int(lower_text), int(upper_text)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("targeted state-event ranges use LOWER:UPPER") from error
    if lower < 0 or upper < lower:
        raise argparse.ArgumentTypeError("targeted state-event range is negative or reversed")
    return lower, upper


def _canonical_fetch_ranges(requested: list[tuple[int, int]], canonical: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Admit only ordered, nonoverlapping members of the frozen canonical partition."""

    normalized = [(int(lower), int(upper)) for lower, upper in requested]
    if not normalized or normalized != sorted(normalized) or len(normalized) != len(set(normalized)) or any(index and lower <= normalized[index - 1][1] for index, (lower, _upper) in enumerate(normalized)):
        raise ValueError("targeted state-event ranges must be sorted, unique, and nonoverlapping")
    canonical_members = set(canonical)
    if any(bounds not in canonical_members for bounds in normalized):
        raise ValueError("targeted state-event range is not a canonical chunk of the frozen generation perimeter")
    return normalized


def _fetch_ranges(
    venue: str,
    ranges: list[tuple[int, int]],
    *,
    frozen_upper: dict[str, object],
    root: Path,
    workers: int,
) -> None:
    """Fetch absent named chunks and reopen every member before returning."""

    if not ranges or ranges != sorted(ranges) or len(ranges) != len(set(ranges)) or any(index and lower <= ranges[index - 1][1] for index, (lower, _upper) in enumerate(ranges)):
        raise ValueError("state-event fetch range selection must be sorted, unique, and nonoverlapping")
    if any(lower < 0 or upper < lower or upper > int(frozen_upper["block_number"]) for lower, upper in ranges):
        raise ValueError("state-event fetch range lies outside the frozen chain perimeter")
    pending = [bounds for bounds in ranges if not _completed(venue, *bounds, frozen_upper, root)]
    queue = deque(pending)
    worker_count = bounded_workers(workers)
    completed = 0
    with interruptible_thread_pool(worker_count) as pool:
        futures = {}
        while queue or futures:
            while queue and len(futures) < worker_count:
                lower, upper = queue.popleft()
                futures[pool.submit(_fetch_one, venue, lower, upper, frozen_upper, root)] = (lower, upper)
            done, _outstanding = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                lower, upper = futures.pop(future)
                _lower, _upper, rows = future.result()
                if (_lower, _upper) != (lower, upper):
                    raise RuntimeError("state-event worker returned the wrong block range")
                completed += 1
                print(f"state-event chunks {completed:,}/{len(pending):,}: {lower}-{upper}, rows={rows:,}", flush=True)
    invalid = [bounds for bounds in ranges if not _completed(venue, *bounds, frozen_upper, root)]
    if invalid:
        raise RuntimeError(f"targeted state-event fetch did not reopen {len(invalid)} chunk(s), first={invalid[0]}")


def _run_owned(args: argparse.Namespace) -> int:
    venue = args.venue
    frozen_upper, factory_certificate = load_certified_frozen_upper()
    if venue == "uniswap_v4" and (args.start_block is not None or args.end_block is not None or args.chunk_size != DEFAULT_CHUNK_SIZE):
        raise ValueError("V4 exact-state generation is bound to the canonical deployment-to-frozen-upper 10,000-block perimeter; start, end, and chunk-size overrides are forbidden")
    if args.fetch_only and (args.start_block is not None or args.end_block is not None or args.chunk_size != DEFAULT_CHUNK_SIZE):
        raise ValueError("targeted fetch-only ranges are bound to the canonical deployment-to-frozen-upper chunk perimeter; start, end, and chunk-size overrides are forbidden")
    default_start = V3_FACTORY_DEPLOYMENT_BLOCK if venue == "uniswap_v3" else UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK
    start = args.start_block if args.start_block is not None else default_start
    end = args.end_block if args.end_block is not None else int(frozen_upper["block_number"])
    root = args.root
    ranges = _ranges(start, end, args.chunk_size)
    if args.fetch_only:
        _fetch_ranges(
            venue,
            _canonical_fetch_ranges(args.fetch_only, ranges),
            frozen_upper=frozen_upper,
            root=root,
            workers=args.workers,
        )
        return 0
    if venue == "uniswap_v3":
        registry, metadata, metadata_inputs = _v3_inputs()
    else:
        registry = {}
        metadata, metadata_inputs = _v2_scoped_token_metadata()
    if args.fetch:
        _fetch_ranges(venue, ranges, frozen_upper=frozen_upper, root=root, workers=args.workers)
    days = _venue_days(venue, args.start_day, args.end_day)
    day_cuts = _venue_day_cuts(venue, days)
    support_end_day: str | None = None
    support_end_block: int | None = None
    generation_ranges = ranges
    if venue == "uniswap_v4":
        completion = [_completed(venue, *bounds, frozen_upper, root) for bounds in ranges]
        prefix_length = next((index for index, complete in enumerate(completion) if not complete), len(ranges))
        if prefix_length == 0:
            raise RuntimeError("V4 exact-state release has no complete prefix chunk")
        prefix_upper = ranges[prefix_length - 1][1]
        explicit = args.support_end_day is not None or args.support_end_block is not None
        if explicit and (args.support_end_day is None or args.support_end_block is None):
            raise ValueError("V4 support end day and block must be supplied together")
        if explicit:
            support_end_day = str(args.support_end_day).replace("-", "")
            support_end_block = int(args.support_end_block)
        else:
            supported_cuts = [
                (day, int(cut["end_block"]))
                for day, cut in sorted(day_cuts.items())
                if int(cut["end_block"]) <= prefix_upper
            ]
            if not supported_cuts:
                raise RuntimeError("V4 complete prefix does not cover one full research UTC day")
            support_end_day, support_end_block = supported_cuts[-1]
        cut = day_cuts.get(support_end_day)
        if cut is None or int(cut["end_block"]) != support_end_block or support_end_block > prefix_upper:
            raise ValueError("V4 support end must equal a fully covered research UTC-day boundary")
        support_range_index = next(index for index, (_lower, upper) in enumerate(ranges) if support_end_block <= upper)
        if not all(completion[: support_range_index + 1]):
            raise RuntimeError("V4 support end crosses an incomplete exact-state chunk")
        generation_ranges = ranges[: support_range_index + 1]
    initialization_evidence, certificate = certify_state_event_generation(
        venue,
        generation_ranges,
        frozen_upper=frozen_upper,
        raw_root=root,
        support_end_block=support_end_block,
        requested_ranges=ranges if venue == "uniswap_v4" else None,
    )
    decoded = initialization_evidence
    if venue == "uniswap_v4":
        certificate = {
            **{key: value for key, value in certificate.items() if key != "certificate_identity_sha256"},
            "support_end_day": support_end_day,
            "scientific_support_calendar_sha256": scientific_support_calendar_sha256(days, str(support_end_day)),
        }
        certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
    if venue == "uniswap_v3":
        manifest_path = V3_INVENTORY_RAW_ROOT / "ordered_chunks.complete.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        inventory_ranges = [(int(row["lower"]), int(row["upper"])) for row in manifest["chunks"]]
        validate_inventory_ordered_manifest(
            V3_INVENTORY_RAW_ROOT,
            inventory_ranges,
            chunk_size=int(manifest["chunk_size"]),
            frozen_upper=frozen_upper,
            factory_certificate=factory_certificate,
            reopen_chunks=False,
        )
        state_events, state_event_summary = load_v3_first_consuming_events(
            V3_INVENTORY_RAW_ROOT,
            ordered_manifest=manifest,
            frozen_upper=frozen_upper,
            factory_certificate=factory_certificate,
        )
        certificate = {
            **{key: value for key, value in certificate.items() if key != "certificate_identity_sha256"},
            "precedence_source_generation": state_event_summary["generation"],
            "precedence_source_certificate_identity_sha256": state_event_summary["certificate_identity_sha256"],
            "precedence_source_data_portable_sha256": state_event_summary["data_portable_sha256"],
            "precedence_source_ordered_manifest_identity_sha256": state_event_summary["source_ordered_manifest_identity_sha256"],
        }
        decoded, certificate = certify_state_event_precedence(certificate, initialization_evidence, state_events, registry_pools=registry)
        state_event_data_path, state_event_marker_path = inventory_first_consuming_event_paths(V3_INVENTORY_RAW_ROOT)
        metadata_inputs.extend([manifest_path, state_event_data_path, state_event_marker_path])
    metadata_manifest = portable_content_manifest_for_paths(REPO_ROOT, [path for path in metadata_inputs if path is not None])
    certificate["metadata_source_manifest"] = metadata_manifest
    certificate["metadata_source_manifest_sha256"] = portable_manifest_sha256(metadata_manifest)
    if venue == "uniswap_v4":
        certificate["native_currency_decimals"] = V4_NATIVE_CURRENCY_DECIMALS
        certificate["token_metadata_scope"] = "exact_anchor_v2_registry_plus_native_currency_only"
    else:
        certificate["token_metadata_scope"] = "exact_anchor_v2_registry_only"
    certificate = certify_materialization_support(certificate, decoded, metadata)
    write_daily_initializations(
        venue,
        decoded,
        day_cuts=day_cuts,
        token_metadata=metadata,
        raw_root=GRAPH_ROOT,
        generation_certificate=certificate,
    )
    if venue == "uniswap_v4":
        write_daily_v4_state_events(
            iter_v4_state_events(generation_ranges, frozen_upper=frozen_upper, raw_root=root, support_end_block=support_end_block),
            decoded,
            day_cuts=day_cuts,
            token_metadata=metadata,
            raw_root=GRAPH_ROOT,
            generation_certificate=certificate,
        )
    print(json.dumps(certificate, sort_keys=True))
    return 0


def run(args: argparse.Namespace) -> int:
    with exclusive_job(LOCK, job=f"{args.venue} exact state-event generation and release"):
        return _run_owned(args)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("venue", choices=sorted(VENUE_TOPICS))
    cli.add_argument("--fetch", action="store_true", help="fetch absent state-event chunks before certification")
    cli.add_argument("--fetch-only", action="append", type=_targeted_range, default=[], metavar="LOWER:UPPER", help="fetch or reopen only this exact chunk and exit before census or materialization; repeatable")
    cli.add_argument("--start-block", type=int)
    cli.add_argument("--end-block", type=int)
    cli.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    cli.add_argument("--workers", type=int, default=4)
    cli.add_argument("--root", type=Path, default=TICK_STATE_EVENT_RAW_ROOT)
    cli.add_argument("--start-day", default=RESEARCH_SAMPLE_START)
    cli.add_argument("--end-day", default=RESEARCH_SAMPLE_END)
    cli.add_argument("--support-end-day", help="last fully supported V4 UTC day")
    cli.add_argument("--support-end-block", type=int, help="exact end block of the last fully supported V4 UTC day")
    return cli


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(run(arguments))
