#!/usr/bin/env python3
"""Hourly timestamp-to-block index, measured rather than assumed.

Why blocks. Pool depth and the gas price change every block, so the chain's own
clock is the state-transition clock, and a control window denominated in blocks
says exactly what it conditions on. Calendar windows do not: a month drifts
between 28 and 31 days, and pandas refuses several multiples of a week as
non-fixed frequencies, so a calendar ladder silently changes width across a
sample.

Why measured. Block time is not a constant. It ran near 13 seconds under
proof-of-work and became a 12-second target after the September 2022 merge, and
it varied with difficulty before that. Converting a timestamp to a block by
dividing by an assumed interval therefore accumulates error across a six-year
sample, so this reads the actual block numbers observed in each hour.

What it does NOT fix. The index makes block windows expressible; it does not make
the underlying state finer. Uniswap v2 reserves in this dataset are hourly, so a
window narrower than roughly 300 blocks contains at most one v2 state and buys
nothing. Uniswap v3 carries `sqrtPriceX96` on every swap, so v3 state genuinely is
per-block and a finer window is meaningful there. Any ladder should say which of
the two it is resolving.

Reads   data/raw/thegraph/uniswap_v2/uniswap_v2_swaps_*.jsonl.gz
        data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz
Writes  data/processed/block_time_index.parquet   (one row per observed hour)
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_panel  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph"
OUT = ROOT / "data" / "processed" / "block_time_index.parquet"
SOURCES = ("uniswap_v2", "uniswap_v3")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    # hour_start_unix -> (min block, max block) seen in that hour
    lo: dict[int, int] = {}
    hi: dict[int, int] = {}
    files = []
    for src in SOURCES:
        files += sorted((RAW / src).glob(f"{src}_swaps_*.jsonl.gz"))
    if args.limit:
        files = files[: args.limit]
    print(f"scanning {len(files):,} swap files for block timestamps", flush=True)

    bad = 0
    for i, f in enumerate(files, 1):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                tx = r.get("transaction") or {}
                try:
                    blk = int(tx.get("blockNumber") or 0)
                    ts = int(tx.get("timestamp") or r.get("timestamp") or 0)
                except (TypeError, ValueError):
                    bad += 1
                    continue
                if blk <= 0 or ts <= 0:
                    bad += 1
                    continue
                h = ts - (ts % 3600)
                if h not in lo or blk < lo[h]:
                    lo[h] = blk
                if h not in hi or blk > hi[h]:
                    hi[h] = blk
        if i % 200 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] {len(lo):,} hours indexed", flush=True)

    df = pd.DataFrame({"hour_start_unix": sorted(lo)})
    df["block_first"] = df.hour_start_unix.map(lo)
    df["block_last"] = df.hour_start_unix.map(hi)
    df["timestamp"] = pd.to_datetime(df.hour_start_unix, unit="s")
    df = df.sort_values("hour_start_unix").reset_index(drop=True)
    df["blocks_in_hour"] = df.block_last - df.block_first + 1

    write_panel(df, OUT)
    print(f"\n{len(df):,} hours indexed, {bad:,} rows unusable")
    print(f"  {df.timestamp.min().date()} to {df.timestamp.max().date()}")
    print(f"  blocks per hour: median {df.blocks_in_hour.median():.0f}, "
          f"p5 {df.blocks_in_hour.quantile(0.05):.0f}, "
          f"p95 {df.blocks_in_hour.quantile(0.95):.0f}")
    y = df.set_index("timestamp").blocks_in_hour.resample("YS").median()
    print("\n  median blocks per hour by year (the merge retargeted block time in 2022-09):")
    for idx, v in y.items():
        print(f"    {idx.year}  {v:>6.0f}   ~{3600/max(v,1):.2f}s per block")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
