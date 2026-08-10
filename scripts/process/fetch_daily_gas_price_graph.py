#!/usr/bin/env python3
"""Daily gas price from neutral UTC-day Ethereum block samples.

Three transaction receipts per day are too sparse, while the first 500 swaps after
midnight do not span the day and repeat a transaction's gas price when it contains
multiple swaps. The canonical estimator instead selects fixed interior block
quantiles from exact UTC-day Ethereum block bounds and reads every transaction in
each full block. No DEX stream selects the clock or the sampled block.

Gas units remain a separate receipt-measured route-topology estimand. A daily gas
price panel must not carry unsupported pooled constants for that second quantity.

Writes  data/processed/daily_gas_price_graph.parquet
        output/exhibits/daily_gas_price_graph.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.data_release import require_node_d_release
from ddvc.ethereum_day_cuts import UTC_DAY_BLOCK_CALENDAR
from ddvc.fetch.raw import write_jsonl_gz
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.quoter import rpc_post
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job
from ddvc.tables import write_exhibit, write_panel

OUT_PANEL = DATA_DIR / "processed" / "daily_gas_price_graph.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "daily_gas_price_graph.jsonl"
OUT_BLOCK_EVIDENCE = DATA_DIR / "raw" / "ethereum" / "daily_gas_block_samples.jsonl.gz"
CACHE = SHARED_RUNTIME_DIR / "cache" / "gas_price_graph"
LOCK = SHARED_RUNTIME_DIR / "daily-gas-price-panel.lock"
CODE_SOURCES = [
    "scripts/process/fetch_daily_gas_price_graph.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/quoter.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/release_calendar.py",
]
BLOCK_SAMPLE_VERSION = "utc_day_interior_block_quantiles_v2"
PANEL_COLUMNS = [
    "day",
    "source",
    "method",
    "n_tx",
    "n_blocks",
    "gas_gwei_median",
    "gas_gwei_p25",
    "gas_gwei_p75",
    "day_start_block",
    "day_end_block",
    "sampled_blocks",
    "sampling_version",
    "requested_blocks_per_day",
]


def sample_blocks_from_bounds(start_block: int, end_block: int, count: int) -> list[int]:
    """Fixed interior block quantiles from one exact inclusive UTC-day perimeter."""
    start = int(start_block)
    end = int(end_block)
    if count < 1 or start < 0 or end < start or end - start + 1 < count:
        raise ValueError("UTC-day block perimeter cannot supply the requested sample")
    span = end - start
    blocks = [round(start + index * span / (count + 1)) for index in range(1, count + 1)]
    if len(set(blocks)) != count or blocks != sorted(blocks):
        raise ValueError("UTC-day block quantiles are not unique and ordered")
    return blocks


def load_day_calendar(path: Path = UTC_DAY_BLOCK_CALENDAR) -> dict[str, dict[str, int]]:
    if not path.is_file():
        raise RuntimeError("exact Ethereum UTC-day calendar has not been released")
    frame = pd.read_parquet(
        path,
        columns=["day", "start_timestamp", "end_timestamp", "start_block", "end_block"],
    )
    if frame.empty or frame["day"].duplicated().any():
        raise RuntimeError("exact Ethereum UTC-day calendar is empty or duplicated")
    return {
        str(row.day): {
            "start_timestamp": int(row.start_timestamp),
            "end_timestamp": int(row.end_timestamp),
            "start_block": int(row.start_block),
            "end_block": int(row.end_block),
        }
        for row in frame.itertuples(index=False)
    }


def block_gas_sample(block: int) -> dict[str, object] | None:
    """Every transaction gas price plus canonical identity for one full block."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), True],
    }
    for _attempt in range(3):
        response = rpc_post(
            payload,
            timeout=20,
            retries=2,
            sleep=0.02,
        )
        result = (response or {}).get("result") if isinstance(response, dict) else None
        transactions = result.get("transactions") if isinstance(result, dict) else None
        if not isinstance(transactions, list) or not transactions:
            continue
        try:
            returned_block = int(str(result["number"]), 16)
            block_hash = str(result["hash"]).lower()
            block_timestamp = int(str(result["timestamp"]), 16)
        except (KeyError, TypeError, ValueError):
            continue
        if returned_block != block or len(block_hash) != 66 or not block_hash.startswith("0x"):
            raise ValueError(f"Ethereum RPC returned the wrong canonical identity for block {block}")
        prices_wei = []
        for transaction in transactions:
            value = transaction.get("gasPrice") if isinstance(transaction, dict) else None
            if value is not None:
                try:
                    prices_wei.append(int(str(value), 16))
                except (TypeError, ValueError):
                    continue
        if prices_wei:
            return {
                "block_number": block,
                "block_hash": block_hash,
                "block_timestamp": block_timestamp,
                "transaction_count": len(transactions),
                "gas_prices_wei": prices_wei,
            }
    return None


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


def record_from_samples(
    day: str,
    bounds: dict[str, int],
    blocks: list[int],
    samples: list[dict[str, object]],
    blocks_per_day: int,
) -> dict:
    try:
        sample_blocks = [int(sample["block_number"]) for sample in samples]
        valid_hashes = all(
            len(str(sample["block_hash"])) == 66
            and str(sample["block_hash"]).startswith("0x")
            for sample in samples
        )
        valid_times = all(
            bounds["start_timestamp"] <= int(sample["block_timestamp"]) < bounds["end_timestamp"]
            for sample in samples
        )
        valid_counts = all(
            int(sample["transaction_count"]) >= len(sample["gas_prices_wei"]) > 0
            for sample in samples
        )
        prices = [
            int(value) / 1e9
            for sample in samples
            for value in sample["gas_prices_wei"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed full-block gas evidence for {day}") from exc
    if (
        sample_blocks != blocks
        or len(samples) != blocks_per_day
        or not valid_hashes
        or not valid_times
        or not valid_counts
        or not prices
    ):
        raise ValueError(f"full-block gas evidence fails its sample identity for {day}")
    rec = summarise_prices(
        day,
        "ethereum_block",
        "utc_day_block_quantile_transactions",
        prices,
        n_blocks=len(samples),
    )
    rec["day_start_block"] = bounds["start_block"]
    rec["day_end_block"] = bounds["end_block"]
    rec["sampled_blocks"] = blocks
    rec["sampling_version"] = BLOCK_SAMPLE_VERSION
    rec["requested_blocks_per_day"] = blocks_per_day
    rec["block_samples"] = samples
    return rec


def fetch_day(
    day: str,
    blocks_per_day: int = 3,
    *,
    calendar: dict[str, dict[str, int]] | None = None,
) -> dict:
    day_calendar = calendar or load_day_calendar()
    if day not in day_calendar:
        raise RuntimeError(f"exact Ethereum UTC calendar lacks {day}")
    bounds = day_calendar[day]
    blocks = sample_blocks_from_bounds(
        bounds["start_block"],
        bounds["end_block"],
        blocks_per_day,
    )
    cached = CACHE / f"{day}.json"
    if cached.exists():
        rec = json.loads(cached.read_text())
        reusable_block_sample = (
            rec.get("sampling_version") == BLOCK_SAMPLE_VERSION
            and int(rec.get("requested_blocks_per_day") or 0) == blocks_per_day
            and rec.get("sampled_blocks") == blocks
            and int(rec.get("day_start_block", -1)) == bounds["start_block"]
            and int(rec.get("day_end_block", -1)) == bounds["end_block"]
            and isinstance(rec.get("block_samples"), list)
            and len(rec["block_samples"]) == blocks_per_day
        )
        if reusable_block_sample:
            return record_from_samples(
                day,
                bounds,
                blocks,
                rec["block_samples"],
                blocks_per_day,
            )
    samples = []
    for block in blocks:
        sample = block_gas_sample(block)
        if sample is not None:
            samples.append(sample)
    if len(samples) != len(blocks):
        raise RuntimeError(
            f"only {len(samples)}/{len(blocks)} sampled blocks resolved for {day}"
        )
    rec = record_from_samples(day, bounds, blocks, samples, blocks_per_day)
    CACHE.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(rec, sort_keys=True))
    return rec


def write_block_evidence(rows: list[dict]) -> None:
    records = [
        {
            "day": row["day"],
            "day_start_block": row["day_start_block"],
            "day_end_block": row["day_end_block"],
            "sampled_blocks": row["sampled_blocks"],
            "sampling_version": row["sampling_version"],
            "block_samples": row["block_samples"],
        }
        for row in sorted(rows, key=lambda item: item["day"])
    ]
    write_jsonl_gz(OUT_BLOCK_EVIDENCE, records)


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

    unified = released_route_days(UNIFIED_QUALITY_PANEL, nonempty=True)
    days = [
        day
        for day in unified
        if (args.start is None or day >= args.start)
        and (args.end is None or day <= args.end)
    ]
    calendar = load_day_calendar()
    if any(day not in calendar for day in days):
        missing = sum(day not in calendar for day in days)
        raise RuntimeError(f"exact Ethereum UTC calendar misses {missing:,} requested gas days")
    print(
        f"{len(days):,} days to price from neutral UTC-day full blocks "
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
                calendar=calendar,
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
    write_block_evidence(rows)

    write_panel(
        df,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[
            OUT_BLOCK_EVIDENCE,
            UTC_DAY_BLOCK_CALENDAR,
            UNIFIED_QUALITY_PANEL,
        ],
        notes=f"daily gas-price median from {args.blocks_per_day} neutral UTC-day interior block quantiles",
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
