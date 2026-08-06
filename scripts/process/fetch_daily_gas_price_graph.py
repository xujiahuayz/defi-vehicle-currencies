#!/usr/bin/env python3
"""Daily gas price from high-density historical transaction samples.

The previous route sampled `eth_getTransactionReceipt` over public RPC endpoints:
three receipts per day across 2,248 days, roughly 6,700 calls against shared
infrastructure. It rate-limited itself into a stall, and even when it completed a
three-receipt median is a poor estimate of a day's gas price.

The V3 subgraph exposes `Transaction.gasPrice` directly, exactly. One page of
swaps per day therefore yields hundreds of transaction gas prices without RPC.
The V2 subgraph does not expose that field. Before V3 launch, V2 swap files select
three blocks across each UTC day, with the active V1 stream supplying the calendar
on early days when V2 has no swaps. `eth_getBlockByNumber(..., true)` then returns
the full transaction objects and their gas prices. This gives hundreds of
observations per day in three calls, closing the 394-day hole left by a V3-only
calendar without falling back to three individual receipts.

What this deliberately does NOT take from the subgraph. `Transaction.gasUsed`
returns `0` on current subgraph versions, so gas UNITS still come from receipts.
That is the right division anyway: gas price is a market quantity that moves daily,
while gas units are a structural property of a route's topology, measured once at
154,604 units for one leg, 228,701 for two and 319,906 for three. A per-day fetch
of a constant would be waste.

Key rotation matters here. Of the eleven keys in `GRAPH_API_KEYS`, five are live
and six return "payment required"; `GraphClient` rotates past the dead ones, so the
pool must be passed whole rather than filtered by hand.

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

from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.quoter import rpc_post
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit, write_panel

V2_SOURCE = get_source("uniswap_v2")
V3_SOURCE = get_source("uniswap_v3")
V3_START = "20210505"
RAW_V2 = DATA_DIR / "raw" / "thegraph" / "uniswap_v2"
RAW_V1 = DATA_DIR / "raw" / "thegraph" / "uniswap_v1"
OUT_PANEL = DATA_DIR / "processed" / "daily_gas_price_graph.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "daily_gas_price_graph.jsonl"
CACHE = DATA_DIR / "interim" / "gas_price_graph"
CODE_SOURCES = [
    "scripts/process/fetch_daily_gas_price_graph.py",
    "src/ddvc/fetch/graph.py",
    "src/ddvc/fetch/sources.py",
    "src/ddvc/quoter.py",
]

QUERY = """
query($start: Int!, $end: Int!, $first: Int!) {
  swaps(first: $first, orderBy: timestamp, orderDirection: asc,
        where: {timestamp_gte: $start, timestamp_lt: $end}) {
    timestamp
    transaction { gasPrice }
  }
}
"""


def day_bounds(day: str) -> tuple[int, int]:
    t0 = pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}", tz="UTC")
    return int(t0.timestamp()), int((t0 + pd.Timedelta(days=1)).timestamp())


def source_name_for_day(day: str) -> str:
    """Data source that supplies transaction gas prices on this day."""
    return "ethereum_block" if day < V3_START else "uniswap_v3"


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


def pre_v3_sample_blocks(day: str, count: int) -> tuple[list[int], str | None]:
    """Pre-V3 block calendar, preferring V2 and falling back to active V1."""
    candidates = (
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
    """Every legacy gas price in one stored full block, expressed in gwei."""
    response = rpc_post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBlockByNumber",
            "params": [hex(block), True],
        },
        timeout=20,
        retries=2,
        sleep=0.02,
    )
    transactions = ((response or {}).get("result") or {}).get("transactions") or []
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
    """Stable daily summary schema shared by block and subgraph routes."""
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


def fetch_day(
    clients: dict[str, GraphClient],
    day: str,
    per_day: int,
    blocks_per_day: int = 3,
) -> dict:
    cached = CACHE / f"{day}.json"
    if cached.exists():
        rec = json.loads(cached.read_text())
        if rec.get("gas_gwei_median") is not None:
            rec["source"] = source_name_for_day(day)
            rec.setdefault(
                "method", "block_transactions" if day < V3_START else "subgraph"
            )
            if day < V3_START and not rec.get("calendar_source"):
                _blocks, calendar_source = pre_v3_sample_blocks(day, 1)
                rec["calendar_source"] = calendar_source
            return rec
    source_name = source_name_for_day(day)
    if source_name == "ethereum_block":
        blocks, calendar_source = pre_v3_sample_blocks(day, blocks_per_day)
        prices = []
        for block in blocks:
            prices.extend(block_gas_prices(block))
        if not prices:
            raise RuntimeError(f"no transaction gas prices resolved for {day}")
        rec = summarise_prices(
            day,
            source_name,
            "block_transactions",
            prices,
            n_blocks=len(blocks),
        )
        rec["calendar_source"] = calendar_source
        CACHE.mkdir(parents=True, exist_ok=True)
        with atomic_output(cached) as temporary:
            temporary.write_text(json.dumps(rec))
        return rec
    start, end = day_bounds(day)
    rows = clients[source_name].query(
        QUERY, {"start": start, "end": end, "first": per_day}
    )
    prices = []
    for s in (rows or {}).get("swaps", []) or []:
        gp = ((s.get("transaction") or {}).get("gasPrice"))
        if gp:
            try:
                prices.append(int(gp) / 1e9)
            except (TypeError, ValueError):
                continue
    if not prices:
        raise RuntimeError(f"no transaction gas prices resolved for {day}")
    rec = summarise_prices(day, source_name, "subgraph", prices)
    CACHE.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(rec))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--start",
        default=V2_SOURCE.genesis.strftime("%Y%m%d"),
        help="first V2 market-data day",
    )
    ap.add_argument("--end", default=None)
    ap.add_argument("--per-day", type=int, default=500,
                    help="transactions sampled per day; a median over hundreds beats "
                         "the three receipts the RPC route managed")
    ap.add_argument(
        "--blocks-per-day",
        type=int,
        default=3,
        help="full blocks sampled on each pre-V3 day",
    )
    ap.add_argument("--workers", type=int, default=5,
                    help="one per live key, so rotation is not fighting itself")
    args = ap.parse_args()
    if args.per_day < 1:
        ap.error("--per-day must be positive")
    if args.workers < 1:
        ap.error("--workers must be positive")
    if args.blocks_per_day < 1:
        ap.error("--blocks-per-day must be positive")

    unified_dir = DATA_DIR / "unified"
    unified = sorted(p.stem for p in unified_dir.glob("[0-9]" * 8 + ".parquet"))
    days = [d for d in unified if d >= args.start and (args.end is None or d <= args.end)]
    keys = graph_keys()
    print(
        f"{len(days):,} days to price from V2-calendar blocks and the V3 subgraph "
        f"({args.blocks_per_day} blocks/pre-V3 day, {args.per_day} V3 tx/day, "
        f"{len(keys)} keys in pool)",
        flush=True,
    )

    clients = {}
    if any(day >= V3_START for day in days):
        clients[V3_SOURCE.name] = GraphClient(
            V3_SOURCE.subgraph_id, keys, graph_path=V3_SOURCE.graph_path
        )
    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(
                fetch_day,
                clients,
                day,
                args.per_day,
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

    df = pd.DataFrame(rows)
    df = df[df.get("gas_gwei_median").notna()] if "gas_gwei_median" in df else df
    if df.empty:
        print("no gas prices resolved")
        return 1
    df["date"] = pd.to_datetime(df.day, format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)

    write_panel(
        df,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[CACHE, unified_dir],
        notes=f"daily gas-price median from {args.blocks_per_day} full blocks before V3 and up to {args.per_day:,} V3 subgraph transactions after launch",
    )
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
    print("\nannual median gas price (gwei), exact per-transaction, no RPC:")
    for idx, r in y.iterrows():
        print(f"  {idx.year}   {r.gas_gwei_median:>8.2f}   "
              f"[p25 {r.gas_gwei_p25:>7.2f}, p75 {r.gas_gwei_p75:>8.2f}]")
    print(f"\nwrote {OUT_PANEL.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
