#!/usr/bin/env python3
"""Receipt-measured gas units by route topology, venue sequence and executor.

The paper currently carries three pooled constants for one-, two- and three-leg
routes, but the script that produced them did not survive. That is not reproducible
and it cannot support venue-specific all-in route costs. This instrument selects
transactions containing exactly one linear reconstructed route component, keeps
its ordered venue sequence and intermediary type, fetches one stored receipt per
transaction, and reports the distribution of total gas used.

Receipt gas is transaction-level. Restricting to one reconstructed component
removes visible route mixtures, but a router transaction may still perform token
approvals, transfers or bookkeeping outside the AMM logs. Medians and interquartile
ranges are therefore primary. The receipt's `to` field is retained as the top-level
transaction callee. It is an executor address, not evidence about who authored the
route, and it enters support diagnostics before any like-for-like comparison.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/route_gas_units.parquet
        output/exhibits/route_gas_units_summary.jsonl
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.calendar import nearest_monthly_days
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import cache_key
from ddvc.quoter import rpc_post
from ddvc.route_gas import (
    CANDIDATE_COLUMNS,
    REQUIRED_COLUMNS,
    SAMPLE_CELLS,
    candidate_transactions,
    deterministic_cell_sample,
)
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
CACHE = DATA_DIR / "interim" / "route_gas_receipts"
CANDIDATE_CACHE_ROOT = DATA_DIR / "empirical" / "_route_gas_candidate_cache"
LOCK = DATA_DIR / "empirical" / ".route_gas_units.lock"
OUT_PANEL = DATA_DIR / "processed" / "route_gas_units.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "route_gas_units_summary.jsonl"
CODE_SOURCES = [
    "scripts/process/build_route_gas_units.py",
    "src/ddvc/route_gas.py",
    "src/ddvc/calendar.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/fetch/sources.py",
    "src/ddvc/quoter.py",
]
CANDIDATE_CODE_SOURCES = [
    "src/ddvc/route_gas.py",
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


def parse_receipt(tx_hash: str, response: object) -> dict | None:
    """Normalised successful JSON-RPC receipt, or None when unusable."""
    if not isinstance(response, dict) or response.get("error"):
        return None
    result = response.get("result") or {}
    try:
        gas_used = int(result["gasUsed"], 16)
        status = int(result.get("status", "0x1"), 16)
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "tx_hash": tx_hash.lower(),
        "gas_used": gas_used,
        "status": status,
        "tx_to": str(result.get("to") or "").lower() or None,
        "tx_from": str(result.get("from") or "").lower() or None,
        "effective_gas_price_wei": (
            int(result["effectiveGasPrice"], 16)
            if result.get("effectiveGasPrice")
            else None
        ),
    }


def fetch_receipt(tx_hash: str) -> dict:
    """Fetch and atomically cache one transaction receipt."""
    cached = CACHE / f"{tx_hash.lower()}.json"
    if cached.exists():
        row = json.loads(cached.read_text())
        if (
            row.get("tx_hash") == tx_hash.lower()
            and isinstance(row.get("gas_used"), int)
            and row["gas_used"] > 0
            and "tx_to" in row
        ):
            return row
    response = rpc_post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        },
        timeout=20,
        retries=2,
        sleep=0.02,
        retry_json_errors=True,
    )
    row = parse_receipt(tx_hash, response)
    if row is None:
        raise RuntimeError("receipt response is missing gasUsed")
    CACHE.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True))
    return row


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
    args = parser.parse_args()
    if args.per_cell < 1:
        parser.error("--per-cell must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")

    days = list(
        dict.fromkeys(
            args.days
            or nearest_monthly_days(
                path.stem for path in UNIFIED.glob("[0-9]" * 8 + ".parquet")
            )
        )
    )
    generation = cache_key(CANDIDATE_CODE_SOURCES, inputs=[UNIFIED])
    candidate_cache = CANDIDATE_CACHE_ROOT / generation / f"per_cell_{args.per_cell}"
    parts = []
    candidate_count = 0
    cache_hits = 0
    completed = 0
    for batch in worker_batches(days, args.workers):
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
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

    receipts = []
    failed = []
    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        futures = {
            pool.submit(fetch_receipt, tx_hash): tx_hash
            for tx_hash in sample["tx_hash"]
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
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
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
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED, CACHE],
        notes=f"hash-ranked cap of {args.per_cell} exact one-component transactions per year-topology-venue-intermediary cell",
    )
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
