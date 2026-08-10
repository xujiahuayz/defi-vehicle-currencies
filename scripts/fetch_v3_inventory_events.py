#!/usr/bin/env python3
"""Fetch raw V3 Collect, Flash, and CollectProtocol logs in resumable block chunks."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re

from ddvc.fetch.sources import get_source
from ddvc.ethereum_logs import (
    EXACT_LOG_BLOCK_CAP,
    exact_log_block_ranges,
    fetch_exact_logs_with_evidence,
    file_sha256,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import Throttled
from ddvc.runtime import atomic_output, exclusive_job, interruptible_thread_pool
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    INVENTORY_RAW_EVIDENCE_KIND,
    INVENTORY_RAW_GENERATION,
    INVENTORY_RAW_MARKER_SCHEMA_VERSION,
    block_ranges,
    canonical_inventory_start_block,
    decode_inventory_log,
    inventory_chunk_completed,
    inventory_chunk_evidence_path,
    inventory_chunk_paths,
)
from ddvc.v3_pool_registry import load_certified_frozen_upper
from ddvc.state_data import available_state_days, read_tick_partition


RAW_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_events"
V3_GRAPH_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
END_META_PATH = V3_GRAPH_ROOT / "uniswap_v3_meta_20260630.json"
DEFAULT_CHUNK_SIZE = 1_000
MAX_JOB_ATTEMPTS = 12
_URL = re.compile(r"https?://[^\s,)]+", flags=re.IGNORECASE)


def safe_retry_reason(error: BaseException, *, limit: int = 200) -> str:
    """Summarize a retry cause without printing an RPC endpoint or credential."""

    reason = " ".join(str(error).split()) or type(error).__name__
    return _URL.sub("<endpoint>", reason)[:limit]


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


def completed(
    lower: int,
    upper: int,
    frozen_upper: dict[str, object],
    root: Path = RAW_ROOT,
) -> bool:
    return inventory_chunk_completed(
        lower,
        upper,
        root,
        frozen_upper=frozen_upper,
    )


def quarantine_invalid_chunk(
    lower: int,
    upper: int,
    *,
    frozen_upper: dict[str, object],
    root: Path,
) -> Path | None:
    """Move an unauditable chunk aside without overwriting or deleting its evidence."""

    raw_path, marker_path = paths(lower, upper, root)
    evidence_path = inventory_chunk_evidence_path(lower, upper, root)
    existing = [path for path in (raw_path, marker_path, evidence_path) if path.exists()]
    if not existing:
        return None
    if completed(lower, upper, frozen_upper, root):
        return None
    quarantine_root = root.parent / f"{root.name}_legacy_unauditable"
    destination = quarantine_root / f"blocks_{lower:08d}_{upper:08d}"
    temporary = quarantine_root / f".blocks_{lower:08d}_{upper:08d}.tmp"
    if destination.exists() or temporary.exists():
        raise RuntimeError(
            f"V3 inventory quarantine target already exists: {destination.name}"
        )
    hashes = {path.name: file_sha256(path) for path in existing if path.is_file()}
    temporary.mkdir(parents=True)
    for path in existing:
        path.replace(temporary / path.name)
    write_json(
        temporary / "quarantine.json",
        {
            "status": "quarantined",
            "reason": "missing_or_invalid_anchored_rpc_evidence",
            "from_block": lower,
            "to_block": upper,
            "quarantined_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_root": root.name,
            "files": sorted(path.name for path in existing),
            "file_sha256": hashes,
            "required_schema_version": INVENTORY_RAW_MARKER_SCHEMA_VERSION,
            "required_generation": INVENTORY_RAW_GENERATION,
            "frozen_upper_block": int(frozen_upper["block_number"]),
            "frozen_upper_block_hash": frozen_upper["block_hash"],
        },
    )
    temporary.replace(destination)
    return destination


def fetch_chunk(
    lower: int,
    upper: int,
    frozen_upper: dict[str, object],
    root: Path = RAW_ROOT,
    rpc_request=None,
) -> dict[str, object]:
    if completed(lower, upper, frozen_upper, root):
        _raw_path, marker_path = paths(lower, upper, root)
        return json.loads(marker_path.read_text(encoding="utf-8"))
    quarantine_invalid_chunk(
        lower,
        upper,
        frozen_upper=frozen_upper,
        root=root,
    )
    topics = [EVENT_TOPICS[name] for name in sorted(EVENT_TOPICS)]
    rpc_ranges = exact_log_block_ranges(lower, upper)
    raw_records: list[dict[str, object]] = []
    rpc_evidence: list[dict[str, object]] = []
    for rpc_lower, rpc_upper in rpc_ranges:
        records, evidence = fetch_exact_logs_with_evidence(
            start_block=rpc_lower,
            end_block=rpc_upper,
            topics=topics,
            frozen_upper=frozen_upper,
            rpc_request=rpc_request,
        )
        raw_records.extend(records)
        rpc_evidence.append(
            {
                "start_block": rpc_lower,
                "end_block": rpc_upper,
                "event_topics": topics,
                "address_filter": None,
                "rpc_request": evidence["request"],
                "rpc_response": evidence["response"],
                "rpc_endpoint": evidence["endpoint"],
                "rpc_attempts": evidence["attempts"],
                "response_sha256": evidence["response_sha256"],
                "frozen_upper_request": evidence["frozen_upper_request"],
                "frozen_upper_response": evidence["frozen_upper_response"],
                "frozen_upper_response_sha256": evidence[
                    "frozen_upper_response_sha256"
                ],
            }
        )
    raw_records.sort(
        key=lambda record: (
            int(record["block_number"]),
            int(record["transaction_index"]),
            int(record["log_index"]),
            str(record["address"]),
        )
    )
    keys: set[tuple[int, str, int]] = set()
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
        by_event[str(decoded["event_type"])] += 1
    raw_path, meta_path = paths(lower, upper, root)
    evidence_path = inventory_chunk_evidence_path(lower, upper, root)
    evidence_payload = {
        "status": "complete",
        "kind": INVENTORY_RAW_EVIDENCE_KIND,
        "schema_version": INVENTORY_RAW_MARKER_SCHEMA_VERSION,
        "inventory_raw_generation": INVENTORY_RAW_GENERATION,
        "from_block": lower,
        "to_block": upper,
        "event_topics": topics,
        "raw_logs": len(raw_records),
        "frozen_upper_block": int(frozen_upper["block_number"]),
        "frozen_upper_block_hash": frozen_upper["block_hash"],
        "frozen_upper_identity_sha256": frozen_upper["header_identity_sha256"],
        "rpc_subrange_evidence": rpc_evidence,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(evidence_path) as temporary:
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            json.dump(evidence_payload, handle, sort_keys=True, separators=(",", ":"))
    metadata = {
        "from_block": lower,
        "to_block": upper,
        "event_topics": topics,
        "schema_version": INVENTORY_RAW_MARKER_SCHEMA_VERSION,
        "inventory_raw_generation": INVENTORY_RAW_GENERATION,
        "rpc_block_cap": EXACT_LOG_BLOCK_CAP,
        "rpc_subranges": len(rpc_ranges),
        "rpc_evidence_file": evidence_path.name,
        "rpc_evidence_sha256": file_sha256(evidence_path),
        "frozen_upper_block": int(frozen_upper["block_number"]),
        "frozen_upper_block_hash": frozen_upper["block_hash"],
        "frozen_upper_identity_sha256": frozen_upper["header_identity_sha256"],
        "raw_by_event": by_event,
    }
    return write_exact_log_chunk(raw_path, meta_path, raw_records, metadata)


def run_fetch_jobs(
    jobs: list[tuple[int, int]],
    frozen_upper: dict[str, object],
    *,
    workers: int,
    max_attempts: int,
    fetch=fetch_chunk,
) -> tuple[dict[str, int], list[tuple[int, int, str]]]:
    """Run a bounded queue, moving transiently throttled chunks to its tail."""

    queue = deque((lower, upper, 1) for lower, upper in jobs)
    failures: list[tuple[int, int, str]] = []
    totals = {"raw": 0}
    complete = 0
    with interruptible_thread_pool(max_workers=workers) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < workers:
                lower, upper, attempt = queue.popleft()
                future = executor.submit(fetch, lower, upper, frozen_upper)
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
                complete += 1
                if complete % 100 == 0 or complete + len(failures) == len(jobs):
                    print(
                        f"  inventory logs [{complete:,}/{len(jobs):,}]; "
                        f"raw={totals['raw']:,}; "
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
    parser.add_argument(
        "--shard",
        action="store_true",
        help="permit one explicit disjoint subrange for distributed raw fetching",
    )
    args = parser.parse_args()
    if args.shard and (args.start_block is None or args.end_block is None):
        raise ValueError("--shard requires explicit --start-block and --end-block")
    terminal = default_end_block()
    frozen_upper, _factory_certificate = load_certified_frozen_upper()
    if int(frozen_upper["block_number"]) != terminal:
        raise RuntimeError("certified V3 factory terminal differs from the inventory terminal")
    end = args.end_block if args.end_block is not None else terminal
    start = args.start_block if args.start_block is not None else default_start_block()
    indexed_start = get_source("uniswap_v3").genesis_block
    if start > indexed_start and not args.shard:
        raise RuntimeError(
            f"inventory start block {start} is after indexed V3 genesis {indexed_start}"
        )
    if end > terminal:
        raise RuntimeError("inventory shard ends after the canonical research perimeter")
    ranges = block_ranges(int(start), end, args.chunk_size)
    jobs = [item for item in ranges if not completed(*item, frozen_upper)]
    print(
        f"V3 inventory log perimeter: {start:,}-{end:,}; {len(ranges):,} chunks; "
        f"cached={len(ranges) - len(jobs):,}; fetch={len(jobs):,}",
        flush=True,
    )
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw V3 inventory-event fetch"):
        workers = max(1, min(args.workers, 4))
        max_attempts = max(1, args.max_job_attempts)
        _totals, failures = run_fetch_jobs(
            jobs,
            frozen_upper,
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
