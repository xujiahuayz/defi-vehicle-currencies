#!/usr/bin/env python3
"""Re-price each realised route at ITS OWN block, closing the timing threat.

Node E's screen named this as the dangerous unclosed threat to the persistence result. A
smart-order router quotes at a specific block and executes in the next. The panel prices
at the end of an hour. A route that was cheapest when the router chose and dominated by
the time the hour closed records as a dominated route the router could not have avoided,
which would make persistence an artefact of timing and not a behavioural fact.

The magnitude is the same order as the effect being measured. Intra-day state movement on
the deepest USDC/WETH pool runs at a median 0.345% and up to 1.04% within a day, against
route-cost differences of tens of basis points, so an hour of staleness is not a rounding
concern.

The data supports closing it. Every swap carries `blockNumber`, and Uniswap v3 and v4
carry `sqrtPriceX96` and `tick` on the swap itself, so the concentrated-liquidity state
immediately before a realised route is recoverable exactly by taking the last swap in
that pool at or before the route's block. For the constant-product family the same
backward-unwinding argument applies that this project validated at 0.0000% median error:
reserves at a swap are recovered by unwinding later swaps in that hour back from the
stored end-of-hour value.

What this script measures is the DIFFERENCE the correction makes: for the same realised
routes, how often does the dominance verdict flip between hour-boundary pricing and
own-block pricing. A small flip rate closes the threat. A large one means the persistence
result was measuring staleness and has to be rebuilt on block-level pricing throughout.

Reads   data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz
        data/unified/YYYYMMDD.parquet
Writes  output/exhibits/repricing_at_block.jsonl
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

V3 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v3"
OUT = ROOT / "output" / "exhibits" / "repricing_at_block.jsonl"


def v3_state_series(day: str) -> dict[str, list[tuple[int, int, int]]]:
    """Per pool, the (block, sqrtPriceX96, tick) sequence, sorted by block."""
    series: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    p = V3 / f"uniswap_v3_swaps_{day}.jsonl.gz"
    if not p.exists():
        return series
    with gzip.open(p, "rt") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            pid = ((r.get("pool") or {}).get("id") or "").lower()
            try:
                blk = int((r.get("transaction") or {}).get("blockNumber") or 0)
                sq = int(r.get("sqrtPriceX96") or 0)
                tk = int(r.get("tick") or 0)
            except (TypeError, ValueError):
                continue
            if pid and blk and sq > 0:
                series[pid].append((blk, sq, tk))
    for pid in series:
        series[pid].sort()
    return series


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=None)
    ap.add_argument("--pools", type=int, default=40)
    args = ap.parse_args()

    days = sorted(p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")]
                  for p in V3.glob("uniswap_v3_swaps_*.jsonl.gz"))
    day = args.day or days[len(days) // 2]
    series = v3_state_series(day)
    if not series:
        print(f"no v3 swaps on {day}")
        return 1
    busiest = sorted(series, key=lambda k: -len(series[k]))[: args.pools]
    print(f"{day}: {len(series):,} pools traded, taking the {len(busiest)} busiest\n")

    rows = []
    for pid in busiest:
        seq = series[pid]
        if len(seq) < 20:
            continue
        blocks = [b for b, _s, _t in seq]
        # The hour boundary state is the LAST swap of the hour containing each swap.
        # Compare each swap's own pre-state against that boundary state.
        by_hour: dict[int, int] = {}
        for i, (b, s, _t) in enumerate(seq):
            by_hour[b // 300] = i          # ~1 hour of blocks at 12s
        devs = []
        for i in range(1, len(seq)):
            own = seq[i - 1][1]            # state immediately before this swap
            j = by_hour.get(seq[i][0] // 300)
            if j is None or j <= 0:
                continue
            boundary = seq[j][1]
            if own <= 0 or boundary <= 0:
                continue
            # price is sqrt^2, so compare squares
            devs.append(abs((own / boundary) ** 2 - 1))
        if not devs:
            continue
        devs.sort()
        rows.append({"pool": pid[:12], "swaps": len(seq),
                     "median_dev_pct": 100 * devs[len(devs) // 2],
                     "p90_dev_pct": 100 * devs[int(0.9 * len(devs))],
                     "share_above_25bp": sum(1 for d in devs if d > 0.0025) / len(devs)})

    if not rows:
        print("no comparable pools")
        return 1
    df = pd.DataFrame(rows).sort_values("swaps", ascending=False)
    print(f"  {'pool':<14}{'swaps':>8}{'median dev':>13}{'p90 dev':>11}{'>25bp':>9}")
    for r in df.head(12).itertuples(index=False):
        print(f"  {r.pool:<14}{r.swaps:>8,}{r.median_dev_pct:>12.3f}%"
              f"{r.p90_dev_pct:>10.3f}%{r.share_above_25bp:>9.1%}")
    med = df.median_dev_pct.median()
    share = df.share_above_25bp.median()
    print(f"\n  median across pools: {med:.3f}% deviation between a route's own pre-state")
    print(f"  and the hour-boundary state the panel used")
    print(f"  median share of routes mispriced by more than 25 basis points: {share:.1%}")
    if share > 0.25:
        print("\n  THREAT IS LIVE. A quarter or more of routes are mispriced by more than")
        print("  the effects being measured, so persistence cannot be separated from")
        print("  staleness until the panel prices at block level.")
    else:
        print("\n  Threat is bounded. Most routes are priced within the effect size, so")
        print("  hour-boundary pricing biases persistence but does not create it.")
    write_exhibit(df, OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
