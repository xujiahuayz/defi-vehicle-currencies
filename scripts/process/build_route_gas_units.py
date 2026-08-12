#!/usr/bin/env python3
"""Receipt-measured gas units by route topology, venue sequence and executor.

This instrument scans every released nonempty route day, selects transactions containing exactly one linear reconstructed route component, keeps its ordered venue sequence and intermediary type, fetches one block-bound receipt with reopenable RPC evidence per transaction, and reports total-gas distributions.

Receipt gas is transaction-level. Restricting to one reconstructed component removes visible route mixtures, but a router transaction may still perform token approvals, transfers or bookkeeping outside the AMM logs. Medians and interquartile ranges are therefore primary. The receipt's `to` field is retained as the top-level transaction callee. It is an executor address, not evidence about who authored the route, and it enters support diagnostics before any like-for-like comparison.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/route_gas_units.parquet
        output/exhibits/route_gas_units_summary.jsonl
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import as_completed
from pathlib import Path

import pandas as pd

from ddvc.data_release import (
    release_preinstall_validator,
    released_route_partitions,
)
from ddvc.ethereum_receipts import (
    RECEIPT_CACHE,
    fetch_receipt as fetch_ethereum_receipt,
    load_receipt_snapshot as load_ethereum_receipt_snapshot,
    parse_receipt,
    write_receipt_snapshot as write_ethereum_receipt_snapshot,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.provenance import cache_key
from ddvc.quoter import rpc_post
from ddvc.route_gas import (
    CANDIDATE_COLUMNS,
    REQUIRED_COLUMNS,
    SAMPLE_CELLS,
    candidate_transactions,
    deterministic_cell_sample,
)
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
    interruptible_thread_pool,
)
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
CACHE = RECEIPT_CACHE
CANDIDATE_CACHE_ROOT = SHARED_RUNTIME_DIR / "cache" / "route_gas_candidates"
RECEIPT_SNAPSHOT = DATA_DIR / "empirical" / "route_gas_receipt_selection.jsonl"
LOCK = SHARED_RUNTIME_DIR / "route-gas-units.lock"
OUT_PANEL = DATA_DIR / "processed" / "route_gas_units.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "route_gas_units_summary.jsonl"
CODE_SOURCES = [
    "scripts/process/build_route_gas_units.py",
    "src/ddvc/ethereum_receipts.py",
    "src/ddvc/route_gas.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/runtime.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/fetch/sources.py",
    "src/ddvc/quoter.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/release_calendar.py",
]
CANDIDATE_CODE_SOURCES = [
    "src/ddvc/route_gas.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/fetch/sources.py",
]
SUMMARY_CELLS = [*SAMPLE_CELLS, "mid_type"]
def worker_batches(
    days: list[str], workers: int, tasks_per_worker: int = 4
) -> list[list[str]]:
    """Bound process lifetime without relying on executor worker replacement."""
    if workers < 1 or tasks_per_worker < 1:
        raise ValueError("worker batch bounds must be positive")
    size = workers * tasks_per_worker
    return [days[start : start + size] for start in range(0, len(days), size)]


def _cached_day_sample(
    cache_dir: Path, day: str, per_cell: int
) -> tuple[int, pd.DataFrame] | None:
    panel_path = cache_dir / f"{day}.parquet"
    marker_path = cache_dir / f"{day}.complete.json"
    if not (panel_path.exists() and marker_path.exists()):
        return None
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("day") != day or marker.get("per_cell") != per_cell:
        return None
    panel = pd.read_parquet(panel_path)
    if list(panel.columns) != CANDIDATE_COLUMNS:
        return None
    if len(panel) != marker.get("sample_rows"):
        return None
    if panel["tx_hash"].duplicated().any():
        return None
    if not panel.empty and panel.groupby(SAMPLE_CELLS).size().max() > per_cell:
        return None
    candidate_count = marker.get("candidate_rows")
    if not isinstance(candidate_count, int) or candidate_count < len(panel):
        return None
    return candidate_count, panel


def sample_day(
    day: str, per_cell: int, cache_dir_text: str
) -> tuple[int, pd.DataFrame, bool]:
    """Read and cache one day's exact contribution to the global cell top-k."""
    cache_dir = Path(cache_dir_text)
    cached = _cached_day_sample(cache_dir, day, per_cell)
    if cached is not None:
        return *cached, True
    path = UNIFIED / f"{day}.parquet"
    if not path.exists():
        return 0, pd.DataFrame(columns=CANDIDATE_COLUMNS), False
    frame = pd.read_parquet(path, columns=REQUIRED_COLUMNS)
    candidates = candidate_transactions(frame, day)
    sample = deterministic_cell_sample(candidates, per_cell)
    cache_dir.mkdir(parents=True, exist_ok=True)
    panel_path = cache_dir / f"{day}.parquet"
    marker_path = cache_dir / f"{day}.complete.json"
    with atomic_output(panel_path) as temporary:
        sample.to_parquet(temporary, index=False)
    marker = {
        "candidate_rows": len(candidates),
        "day": day,
        "per_cell": per_cell,
        "sample_rows": len(sample),
    }
    with atomic_output(marker_path) as temporary:
        temporary.write_text(json.dumps(marker, sort_keys=True) + "\n")
    return len(candidates), sample, False


def fetch_receipt(tx_hash: str, block_number: int) -> dict:
    """Fetch and atomically cache one transaction receipt."""
    return fetch_ethereum_receipt(
        tx_hash,
        cache=CACHE,
        expected_block=block_number,
        require_block_hash=True,
        require_evidence=True,
        rpc_request=rpc_post,
    )


def write_receipt_snapshot(receipts: list[dict], path: Path = RECEIPT_SNAPSHOT) -> Path:
    """Install the exact selected receipt inputs in deterministic transaction order."""
    return write_ethereum_receipt_snapshot(receipts, path, require_evidence=True)


def load_receipt_snapshot(path: Path = RECEIPT_SNAPSHOT) -> dict[str, dict]:
    """Reusable immutable-chain receipts from the previous selected sample."""
    return load_ethereum_receipt_snapshot(path, require_evidence=True)


def _main_unlocked() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", nargs="+")
    parser.add_argument("--per-cell", type=int, default=25)
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="bounded candidate-extraction processes and receipt-fetch threads",
    )
    parser.add_argument("--panel-only", action="store_true")
    args = parser.parse_args()
    if args.per_cell < 1:
        parser.error("--per-cell must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")
    args.workers = bounded_workers(args.workers)

    full_route_release = released_route_partitions(REQUIRED_COLUMNS, nonempty=True)
    days = list(dict.fromkeys(args.days or full_route_release.days))
    route_release = full_route_release.select_days(days)
    generation = cache_key(
        CANDIDATE_CODE_SOURCES,
        inputs=list(route_release.provenance_anchors),
    )
    candidate_cache = CANDIDATE_CACHE_ROOT / generation / f"per_cell_{args.per_cell}"
    parts = []
    candidate_count = 0
    cache_hits = 0
    completed = 0
    for batch in worker_batches(days, args.workers):
        with interruptible_process_pool(args.workers) as pool:
            futures = [
                pool.submit(sample_day, day, args.per_cell, str(candidate_cache))
                for day in batch
            ]
            for future in as_completed(futures):
                count, sample_part, cached = future.result()
                candidate_count += count
                cache_hits += int(cached)
                completed += 1
                if not sample_part.empty:
                    parts.append(sample_part)
                if completed % 12 == 0 or completed == len(days):
                    print(
                        f"  candidate days {completed}/{len(days)} | "
                        f"rows {candidate_count:,} | cached {cache_hits}",
                        flush=True,
                    )
    if not parts:
        print("no exact one-component route transactions")
        return 1
    sample = deterministic_cell_sample(
        pd.concat(parts, ignore_index=True), args.per_cell
    )
    print(
        f"selected {len(sample):,} of {candidate_count:,} candidates across "
        f"{sample[SAMPLE_CELLS].drop_duplicates().shape[0]:,} cells",
        flush=True,
    )

    stored_receipts = load_receipt_snapshot()
    selected_requests = [
        (str(row.tx_hash).lower(), int(row.block_number))
        for row in sample.itertuples(index=False)
    ]
    receipts = [
        stored_receipts[tx_hash]
        for tx_hash, block_number in selected_requests
        if tx_hash in stored_receipts
        and int(stored_receipts[tx_hash]["block_number"]) == block_number
    ]
    missing_requests = [
        (tx_hash, block_number)
        for tx_hash, block_number in selected_requests
        if tx_hash not in stored_receipts
        or int(stored_receipts[tx_hash]["block_number"]) != block_number
    ]
    print(
        f"reused {len(receipts):,} immutable receipts; fetching {len(missing_requests):,}",
        flush=True,
    )
    failed = []
    with interruptible_thread_pool(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_receipt, tx_hash, block_number): tx_hash
            for tx_hash, block_number in missing_requests
        }
        for index, future in enumerate(as_completed(futures), 1):
            tx_hash = futures[future]
            try:
                receipts.append(future.result())
            except Exception as exc:
                failed.append((tx_hash, type(exc).__name__))
            if index % 100 == 0 or index == len(futures):
                print(
                    f"  receipts {index}/{len(futures)} | failed {len(failed)}",
                    flush=True,
                )
    if not receipts:
        print("no receipts resolved")
        return 1
    if failed:
        print(
            f"refusing a selected sample with {len(failed)} unresolved receipts; rerun to fill the deterministic cache"
        )
        return 2
    panel = sample.merge(
        pd.DataFrame(receipts), on="tx_hash", how="inner", validate="one_to_one"
    )
    if len(panel) != len(sample):
        raise RuntimeError("receipt merge changed the deterministic sample size")
    if not panel["status"].eq(1).all():
        raise RuntimeError("a reconstructed swap transaction has a failed receipt")
    if not panel["gas_used"].gt(0).all():
        raise RuntimeError("a selected receipt has non-positive gas usage")
    receipt_snapshot = write_receipt_snapshot(receipts)
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[*route_release.provenance_anchors, receipt_snapshot],
        notes=f"hash-ranked cap of {args.per_cell} exact one-component transactions per year-topology-venue-intermediary cell",
        preinstall_validator=release_preinstall_validator(route_release),
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {OUT_PANEL.relative_to(REPO_ROOT)}")
        return 0
    summary = panel.groupby(SUMMARY_CELLS, as_index=False).agg(
        mid_symbol=("mid_symbol", "first"),
        transactions=("gas_used", "size"),
        executors=("tx_to", "nunique"),
        median_gas_used=("gas_used", "median"),
        p25_gas_used=("gas_used", lambda values: values.quantile(0.25)),
        p75_gas_used=("gas_used", lambda values: values.quantile(0.75)),
        median_notional_usd=("route_notional_usd", "median"),
    )
    write_exhibit(
        summary,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes="receipt-measured gas units; transaction-level medians and interquartile ranges",
    )
    print(
        f"\nwrote {OUT_PANEL.relative_to(REPO_ROOT)} with {len(panel):,} receipts "
        f"and {OUT_EXHIBIT.relative_to(REPO_ROOT)} with {len(summary):,} cells"
    )
    return 0


def main() -> int:
    with exclusive_job(LOCK, job="route gas units"):
        return _main_unlocked()


if __name__ == "__main__":
    raise SystemExit(main())
