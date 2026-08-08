#!/usr/bin/env python3
"""Daily gas price from evenly spaced full historical blocks.

Three transaction receipts per day are too sparse, while the first 500 swaps after
midnight do not span the day and repeat a transaction's gas price when it contains
multiple swaps. The canonical estimator instead selects three evenly spaced blocks
from the active AMM stream and reads every transaction in each full block. V1 and
V2 supply the early calendar, then V3 supplies it after launch. This produces
hundreds of unique transaction gas prices per day in three RPC calls.

Gas units remain a separate receipt-measured route-topology estimand. A daily gas
price panel must not carry unsupported pooled constants for that second quantity.

Writes  data/processed/daily_gas_price_graph.parquet
        output/exhibits/daily_gas_price_graph.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.quoter import rpc_post
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job
from ddvc.tables import write_exhibit, write_panel

V3_START = "20210505"
RAW_V2 = DATA_DIR / "raw" / "thegraph" / "uniswap_v2"
RAW_V1 = DATA_DIR / "raw" / "thegraph" / "uniswap_v1"
RAW_V3 = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
OUT_PANEL = DATA_DIR / "processed" / "daily_gas_price_graph.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "daily_gas_price_graph.jsonl"
CACHE = SHARED_RUNTIME_DIR / "cache" / "gas_price_graph"
LOCK = SHARED_RUNTIME_DIR / "daily-gas-price-panel.lock"
CODE_SOURCES = [
    "scripts/process/fetch_daily_gas_price_graph.py",
    "src/ddvc/quoter.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/release_calendar.py",
]
BLOCK_SAMPLE_VERSION = "full_blocks_v1"
PANEL_COLUMNS = [
    "day",
    "source",
    "method",
    "n_tx",
    "n_blocks",
    "gas_gwei_median",
    "gas_gwei_p25",
    "gas_gwei_p75",
    "calendar_source",
    "sampling_version",
    "requested_blocks_per_day",
]


def _sample_blocks_from_file(
    path: Path, count: int, *, nested_transaction: bool
) -> list[int]:
    """Evenly spaced block identifiers from one venue-day stream."""
    if not path.exists() or count < 1:
        return []
    blocks: set[int] = set()
    with gzip.open(path, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            value = (
                (row.get("transaction") or {}).get("blockNumber")
                if nested_transaction
                else row.get("block")
            )
            try:
                blocks.add(int(value))
            except (TypeError, ValueError):
                continue
    ordered = sorted(blocks)
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    indices = {
        round(position * (len(ordered) - 1) / (count - 1))
        for position in range(count)
    }
    return [ordered[index] for index in sorted(indices)]


def sample_blocks_for_day(day: str, count: int) -> tuple[list[int], str | None]:
    """Evenly spaced blocks from V3, or the active V2/V1 predecessor stream."""
    candidates = (
        (
            "uniswap_v3",
            RAW_V3 / f"uniswap_v3_swaps_{day}.jsonl.gz",
            True,
        ),
    ) if day >= V3_START else (
        (
            "uniswap_v2",
            RAW_V2 / f"uniswap_v2_swaps_{day}.jsonl.gz",
            True,
        ),
        (
            "uniswap_v1",
            RAW_V1 / f"uniswap_v1_swaps_{day}.jsonl.gz",
            False,
        ),
    )
    for source_name, path, nested in candidates:
        blocks = _sample_blocks_from_file(
            path, count, nested_transaction=nested
        )
        if blocks:
            return blocks, source_name
    return [], None


def block_gas_prices(block: int) -> list[float]:
    """Every transaction gas price in one stored full block, expressed in gwei."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), True],
    }
    transactions = []
    for _attempt in range(3):
        response = rpc_post(
            payload,
            timeout=20,
            retries=2,
            sleep=0.02,
        )
        transactions = (
            ((response or {}).get("result") or {}).get("transactions") or []
        )
        if transactions:
            break
    prices = []
    for transaction in transactions:
        value = transaction.get("gasPrice")
        if value:
            try:
                prices.append(int(value, 16) / 1e9)
            except (TypeError, ValueError):
                continue
    return prices


def summarise_prices(
    day: str,
    source_name: str,
    method: str,
    prices: list[float],
    *,
    n_blocks: int | None = None,
) -> dict:
    """Stable daily summary of full-block transaction gas prices."""
    rec = {
        "day": day,
        "source": source_name,
        "method": method,
        "n_tx": len(prices),
    }
    if n_blocks is not None:
        rec["n_blocks"] = n_blocks
    if prices:
        prices.sort()
        rec["gas_gwei_median"] = statistics.median(prices)
        rec["gas_gwei_p25"] = prices[len(prices) // 4]
        rec["gas_gwei_p75"] = prices[3 * len(prices) // 4]
    return rec


def daily_panel_frame(rows: list[dict]) -> pd.DataFrame:
    """Build the analytic frame with a stable schema independent of task completion order."""
    return pd.DataFrame.from_records(rows, columns=PANEL_COLUMNS)


def fetch_day(
    day: str,
    blocks_per_day: int = 3,
) -> dict:
    cached = CACHE / f"{day}.json"
    if cached.exists():
        rec = json.loads(cached.read_text())
        reusable_block_sample = (
            rec.get("gas_gwei_median") is not None
            and rec.get("method") == "block_transactions"
            and int(rec.get("n_blocks") or 0) > 0
            and int(rec.get("requested_blocks_per_day") or 3) == blocks_per_day
        )
        if reusable_block_sample:
            rec["source"] = "ethereum_block"
            rec["sampling_version"] = BLOCK_SAMPLE_VERSION
            rec["requested_blocks_per_day"] = blocks_per_day
            if not rec.get("calendar_source"):
                _blocks, calendar_source = sample_blocks_for_day(day, 1)
                rec["calendar_source"] = calendar_source
            with atomic_output(cached) as temporary:
                temporary.write_text(json.dumps(rec, sort_keys=True))
            return rec
    blocks, calendar_source = sample_blocks_for_day(day, blocks_per_day)
    prices = []
    resolved_blocks = 0
    for block in blocks:
        block_prices = block_gas_prices(block)
        if block_prices:
            prices.extend(block_prices)
            resolved_blocks += 1
    required_blocks = min(2, len(blocks))
    if not prices or resolved_blocks < required_blocks:
        raise RuntimeError(
            f"only {resolved_blocks}/{len(blocks)} sampled blocks resolved for {day}"
        )
    rec = summarise_prices(
        day,
        "ethereum_block",
        "block_transactions",
        prices,
        n_blocks=resolved_blocks,
    )
    rec["calendar_source"] = calendar_source
    rec["sampling_version"] = BLOCK_SAMPLE_VERSION
    rec["requested_blocks_per_day"] = blocks_per_day
    CACHE.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(rec, sort_keys=True))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument(
        "--blocks-per-day",
        type=int,
        default=3,
        help="full blocks sampled on each day",
    )
    ap.add_argument("--workers", type=int, default=5,
                    help="bounded concurrent historical-block requests")
    ap.add_argument("--panel-only", action="store_true")
    args = ap.parse_args()
    require_node_d_release(routes=True)
    workers = bounded_workers(args.workers)
    if args.blocks_per_day < 1:
        ap.error("--blocks-per-day must be positive")

    unified_dir = DATA_DIR / "unified"
    unified = released_route_days(UNIFIED_QUALITY_PANEL, nonempty=True)
    days = [
        day
        for day in unified
        if (args.start is None or day >= args.start)
        and (args.end is None or day <= args.end)
    ]
    print(
        f"{len(days):,} days to price from evenly spaced full blocks "
        f"({args.blocks_per_day} blocks/day)",
        flush=True,
    )
    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(
                fetch_day,
                day,
                args.blocks_per_day,
            ): day
            for day in days
        }
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                rows.append(fut.result())
            except Exception as exc:
                failed += 1
                if failed <= 5:
                    print(f"  {futs[fut]}: {type(exc).__name__} {str(exc)[:90]}", flush=True)
            if i % 100 == 0 or i == len(days):
                print(f"  {i}/{len(days)}  ({failed} failed)", flush=True)

    df = daily_panel_frame(rows)
    df = df[df.get("gas_gwei_median").notna()] if "gas_gwei_median" in df else df
    if df.empty:
        print("no gas prices resolved")
        return 1
    if failed:
        print(f"refusing a partial daily gas panel with {failed} unresolved days")
        return 2
    df["date"] = pd.to_datetime(df.day, format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)
    if df["day"].duplicated().any() or set(df["day"]) != set(days):
        raise RuntimeError("daily gas panel does not match the requested calendar")

    write_panel(
        df,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[
            CACHE,
            unified_dir,
            UNIFIED_QUALITY_PANEL,
            RAW_V1,
            RAW_V2,
            RAW_V3,
        ],
        notes=f"daily gas-price median from {args.blocks_per_day} evenly spaced full blocks",
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {OUT_PANEL.relative_to(REPO_ROOT)}")
        return 0
    write_exhibit(
        df.drop(columns=["day"]),
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes="human-readable daily gas-price evidence",
    )

    print(f"\nresolved {len(df):,} days, {failed} failed, "
          f"median sample {df.n_tx.median():.0f} tx/day")
    y = df.set_index("date").resample("YS").median(numeric_only=True)
    print("\nannual median gas price (gwei), full-block transaction samples:")
    for idx, r in y.iterrows():
        print(f"  {idx.year}   {r.gas_gwei_median:>8.2f}   "
              f"[p25 {r.gas_gwei_p25:>7.2f}, p75 {r.gas_gwei_p75:>8.2f}]")
    print(f"\nwrote {OUT_PANEL.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="daily gas-price panel"):
        raise SystemExit(main())
