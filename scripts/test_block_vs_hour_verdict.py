#!/usr/bin/env python3
"""Does hour-boundary pricing change the DOMINANCE VERDICT, or only the price level?

`scripts/reprice_realised_at_block.py` measured how far a pool's own pre-state sits from
the hour-boundary state the panel priced at, found a median 86.2% of routes moving more
than 25 basis points, and the persistence result was withdrawn on that number. The number
is right and the inference from it is not tested, which is what this script fixes.

The reason is that a dominance verdict is a COMPARISON, and both sides of it are priced at
the same state. When the market moves between a route's own block and the close of its
hour, the direct pool and both vehicle legs move together, and what a common component
does to the DIFFERENCE between the two routes is nothing. The earlier diagnostic measured
the price level of one pool at a time, so it cannot distinguish a market-wide move that
cancels in the comparison from a relative move that does not. Withdrawing a result on a
level statistic when the estimand is a difference is a real risk of throwing away a true
finding, which Java has objected to in this project before.

The test here is the triangle. For tokens A, B and an intermediary K, with a direct pool
AB and legs AK and KB, define

    m = log P(A->B)  -  [ log P(A->K) + log P(K->B) ]

which is positive exactly when the direct pool returns more B per unit of A than the
two-leg route does, in the zero-size limit where the marginal price is the pool price.
The sign of m IS the dominance verdict. Compute m at each realised swap's own block and
again at its hour-boundary state, and count how often the sign disagrees.

Two properties make this exact rather than approximate. Token decimals enter each leg as a
constant, and around a closed triangle those constants sum to zero, so working in raw
sqrtPriceX96 units needs no decimals resolution and inherits none of its errors. And
`sqrtPriceX96` is carried on the swap event itself, so the state immediately after any
swap is observed and not reconstructed.

What it cannot see. This is the marginal price, so it holds for small trades and omits the
size-dependent part of execution cost, which is depth. A verdict that is robust here can
still flip at $100,000 through a thin pool. So a low flip rate bounds the timing threat for
small trades and does not discharge it for large ones, and the script says which it found.

Reads   data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz
Writes  output/exhibits/block_vs_hour_verdict.jsonl
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

V3 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v3"
OUT = ROOT / "output" / "exhibits" / "block_vs_hour_verdict.jsonl"
# Roughly one hour at 12 second blocks. The panel's hour boundary is a wall-clock hour and
# this is a block-count proxy for it; the swap timestamp is also carried, so the hour is
# taken from the timestamp and this constant is not used for bucketing.
Q96 = 1 << 96


def load_day(day: str):
    """Per pool: its ordered token pair, and the (block, hour, sqrtPrice) sequence."""
    tokens: dict[str, tuple[str, str]] = {}
    series: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    p = V3 / f"uniswap_v3_swaps_{day}.jsonl.gz"
    if not p.exists():
        return tokens, series
    with gzip.open(p, "rt") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            pool = r.get("pool") or {}
            pid = (pool.get("id") or "").lower()
            t0 = ((pool.get("token0") or {}).get("id") or "").lower()
            t1 = ((pool.get("token1") or {}).get("id") or "").lower()
            try:
                blk = int((r.get("transaction") or {}).get("blockNumber") or 0)
                ts = int(r.get("timestamp") or 0)
                sq = int(r.get("sqrtPriceX96") or 0)
            except (TypeError, ValueError):
                continue
            if not (pid and t0 and t1 and blk and ts and sq > 0):
                continue
            tokens[pid] = (t0, t1)
            # Work in logs from the start. The squared ratio overflows float for pools
            # whose decimals differ by 18, and the log is what every comparison needs.
            series[pid].append((blk, ts // 3600, 2.0 * math.log(sq / Q96)))
    for pid in series:
        series[pid].sort()
    return tokens, series


class PoolView:
    """State lookups for one pool: last observation at or before a block, and per hour."""

    def __init__(self, seq: list[tuple[int, int, float]]) -> None:
        self.blocks = [b for b, _h, _p in seq]
        self.logp = [p for _b, _h, p in seq]
        # The panel prices at the state that stands at the close of the hour, so the
        # boundary state is the LAST observation within that hour.
        self.by_hour: dict[int, float] = {}
        for _b, h, p in seq:
            self.by_hour[h] = p

    def at_block(self, blk: int) -> float | None:
        i = bisect.bisect_right(self.blocks, blk) - 1
        return self.logp[i] if i >= 0 else None

    def at_hour(self, hour: int) -> float | None:
        return self.by_hour.get(hour)


def oriented(logp: float, t0: str, t1: str, u: str, v: str) -> float | None:
    """log(units of v per unit of u), from a pool quoted as token0 -> token1."""
    if t0 == u and t1 == v:
        return logp
    if t0 == v and t1 == u:
        return -logp
    return None


def measure_day(day: str, max_triangles: int, min_swaps: int) -> list[dict]:
    tokens, series = load_day(day)
    if not series:
        return []
    views = {pid: PoolView(seq) for pid, seq in series.items() if len(seq) >= min_swaps}
    # One pool per unordered token pair, the busiest, so a triangle is unambiguous.
    by_pair: dict[tuple[str, str], str] = {}
    for pid in views:
        t0, t1 = tokens[pid]
        key = (t0, t1) if t0 < t1 else (t1, t0)
        if key not in by_pair or len(series[pid]) > len(series[by_pair[key]]):
            by_pair[key] = pid
    # Adjacency, to find intermediaries joining both endpoints.
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in by_pair:
        adj[a].add(b)
        adj[b].add(a)

    pairs = sorted(by_pair, key=lambda k: -len(series[by_pair[k]]))
    rows: list[dict] = []
    for a, b in pairs:
        if len(rows) >= max_triangles:
            break
        direct = by_pair[(a, b)]
        for k in sorted(adj[a] & adj[b]):
            if k in (a, b):
                continue
            leg1 = by_pair.get((a, k) if a < k else (k, a))
            leg2 = by_pair.get((k, b) if k < b else (b, k))
            if not leg1 or not leg2 or leg1 == direct or leg2 == direct:
                continue
            vd, v1, v2 = views[direct], views[leg1], views[leg2]
            flips = same = 0
            gaps_own: list[float] = []
            deltas: list[float] = []
            # Each realised swap in the direct pool stands for a route the router priced
            # at that block, which is the population the persistence result is about.
            for blk, hour, _p in series[direct]:
                parts_own, parts_hr = [], []
                ok = True
                for pool, (u, v) in ((direct, (a, b)), (leg1, (a, k)), (leg2, (k, b))):
                    vw = views[pool]
                    t0, t1 = tokens[pool]
                    lo, lh = vw.at_block(blk), vw.at_hour(hour)
                    if lo is None or lh is None:
                        ok = False
                        break
                    o = oriented(lo, t0, t1, u, v)
                    h = oriented(lh, t0, t1, u, v)
                    if o is None or h is None:
                        ok = False
                        break
                    parts_own.append(o)
                    parts_hr.append(h)
                if not ok:
                    continue
                m_own = parts_own[0] - (parts_own[1] + parts_own[2])
                m_hr = parts_hr[0] - (parts_hr[1] + parts_hr[2])
                if m_own == 0 or m_hr == 0:
                    continue
                if (m_own > 0) == (m_hr > 0):
                    same += 1
                else:
                    flips += 1
                gaps_own.append(abs(m_own) * 10_000)
                deltas.append(abs(m_own - m_hr) * 10_000)
            n = flips + same
            if n < min_swaps:
                continue
            gaps_own.sort()
            deltas.sort()
            rows.append({
                "day": day, "direct_pool": direct[:10], "vehicle": k[:10],
                "n_routes": n, "flip_rate": flips / n,
                "median_gap_bps": gaps_own[len(gaps_own) // 2],
                "median_delta_bps": deltas[len(deltas) // 2],
                "p90_delta_bps": deltas[int(0.9 * len(deltas))],
            })
            break                                   # one triangle per direct pool
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--triangles", type=int, default=60, help="triangles per day")
    ap.add_argument("--min-swaps", type=int, default=30)
    args = ap.parse_args()

    days = sorted(p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")]
                  for p in V3.glob("uniswap_v3_swaps_*.jsonl.gz"))
    if not days:
        print(f"no v3 swap files under {V3.relative_to(ROOT)}")
        return 1
    step = max(1, len(days) // args.days)
    picked = days[::step][: args.days]
    print(f"testing {len(picked)} days: {picked[0]}..{picked[-1]}\n", flush=True)

    rows: list[dict] = []
    for day in picked:
        got = measure_day(day, args.triangles, args.min_swaps)
        rows.extend(got)
        if got:
            fr = sum(r["flip_rate"] * r["n_routes"] for r in got) / sum(r["n_routes"] for r in got)
            print(f"  {day}: {len(got):>3} triangles, "
                  f"{sum(r['n_routes'] for r in got):>7,} routes, flip rate {fr:>6.2%}",
                  flush=True)
        else:
            print(f"  {day}: no triangle cleared the thresholds", flush=True)

    if not rows:
        print("\nnothing measurable")
        return 1
    df = pd.DataFrame(rows)
    n_tot = int(df.n_routes.sum())
    flip = float((df.flip_rate * df.n_routes).sum() / n_tot)
    print(f"\n{len(df)} triangles over {n_tot:,} realised routes")
    print(f"  verdict flip rate, own block against hour boundary : {flip:.2%}")
    print(f"  median triangle gap at own block                   : "
          f"{df.median_gap_bps.median():.1f} bps")
    print(f"  median change in the gap from repricing            : "
          f"{df.median_delta_bps.median():.1f} bps")
    print(f"  90th percentile change in the gap                  : "
          f"{df.p90_delta_bps.median():.1f} bps")

    print("\nReading. The earlier diagnostic measured a pool's own price against the")
    print("hour-boundary price and found most routes moving more than 25 bps. That is a")
    print("LEVEL. This is the DIFFERENCE the verdict depends on, where a common move")
    print("cancels across the three legs.")
    if flip > 0.25:
        print("\nThe verdict itself is unstable. Hour-boundary pricing cannot support the")
        print("persistence result and block-level pricing is required, as assumed.")
    elif flip > 0.05:
        print("\nThe verdict is mostly stable but the flip rate is material. Persistence")
        print("survives with the flip rate reported as measurement error, and any claim")
        print("resting on gaps near zero has to be restricted away from the boundary.")
    else:
        print("\nThe verdict is stable. The level movement that withdrew the persistence")
        print("result is common across the legs of a route and cancels in the comparison,")
        print("so withdrawing on the level statistic was too strong and the result can be")
        print("reinstated with this flip rate reported as its timing error.")
    write_exhibit(df, OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
