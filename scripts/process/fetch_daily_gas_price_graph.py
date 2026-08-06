#!/usr/bin/env python3
"""Exact per-day gas price from the subgraph, replacing an RPC workaround.

The previous route sampled `eth_getTransactionReceipt` over public RPC endpoints:
three receipts per day across 2,248 days, roughly 6,700 calls against shared
infrastructure. It rate-limited itself into a stall, and even when it completed a
three-receipt median is a poor estimate of a day's gas price.

The subgraph exposes `Transaction.gasPrice` directly, exactly, and it is already
the source for every other field in this project's raw layer. One page of swaps per
day yields hundreds of real transaction gas prices, so a daily median rests on a
proper sample rather than three draws, and no RPC endpoint is touched.

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
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit, write_panel

UNISWAP_V3 = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"
OUT_PANEL = DATA_DIR / "processed" / "daily_gas_price_graph.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "daily_gas_price_graph.jsonl"
CACHE = DATA_DIR / "interim" / "gas_price_graph"
CODE_SOURCES = ["scripts/process/fetch_daily_gas_price_graph.py"]

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


def fetch_day(client: GraphClient, day: str, per_day: int) -> dict:
    cached = CACHE / f"{day}.json"
    if cached.exists():
        import json
        return json.loads(cached.read_text())
    start, end = day_bounds(day)
    rows = client.query(QUERY, {"start": start, "end": end, "first": per_day})
    prices = []
    for s in (rows or {}).get("swaps", []) or []:
        gp = ((s.get("transaction") or {}).get("gasPrice"))
        if gp:
            try:
                prices.append(int(gp) / 1e9)
            except (TypeError, ValueError):
                continue
    rec = {"day": day, "n_tx": len(prices)}
    if prices:
        prices.sort()
        rec["gas_gwei_median"] = statistics.median(prices)
        rec["gas_gwei_p25"] = prices[len(prices) // 4]
        rec["gas_gwei_p75"] = prices[3 * len(prices) // 4]
    import json
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(rec))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="20210505", help="v3 subgraph begins at launch")
    ap.add_argument("--end", default=None)
    ap.add_argument("--per-day", type=int, default=500,
                    help="transactions sampled per day; a median over hundreds beats "
                         "the three receipts the RPC route managed")
    ap.add_argument("--workers", type=int, default=5,
                    help="one per live key, so rotation is not fighting itself")
    args = ap.parse_args()

    unified_dir = DATA_DIR / "unified"
    unified = sorted(p.stem for p in unified_dir.glob("[0-9]" * 8 + ".parquet"))
    days = [d for d in unified if d >= args.start and (args.end is None or d <= args.end)]
    print(f"{len(days):,} days to price from the subgraph "
          f"({args.per_day} tx/day, {len(graph_keys())} keys in pool)", flush=True)

    client = GraphClient(UNISWAP_V3, graph_keys())
    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch_day, client, d, args.per_day): d for d in days}
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
        notes=f"daily median from up to {args.per_day:,} V3 transaction gas prices",
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
