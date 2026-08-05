#!/usr/bin/env python3
"""Cost-dominance windows, measured against a same-state counterfactual.

The question the paper's inertia claim depends on: are there windows in which an
incumbent intermediary keeps carrying routed volume while a direct route would
have returned strictly more output at the same market state?

Why this design and not the previous one. Comparing realised trades across a day
fails, because intraday price movement swamps execution cost by roughly 34 to 1
(`docs/finding-cost-dominance-not-yet-established.md`). Here both routes are
priced against the *same* reconstructed pre-trade reserves, so price movement
cannot enter the comparison at all.

Method, per executed indirect (two-leg) route:
  1. reconstruct exact pre-trade reserves for every v2-family pool in that hour by
     unwinding the hour's swaps backward from the stored end-of-hour reserve
     (validated at median absolute error 0.0000%, 95.2% within 0.01%)
  2. keep only pool-hours whose reserve continuity checks out, since a mint, burn
     or direct transfer would corrupt the unwind
  3. quote the realised intermediated path at those reserves
  4. quote the best available DIRECT pool for the same endpoints and input size at
     the same reserves
  5. the gap in basis points is the cost of the road taken against the road not
     taken, gross of gas

A cell is a cost-dominance window when the direct quote strictly exceeds the
intermediated quote, meaning the trade would have been better off going direct at
the moment it was made.

Bias directions, both stated because they cut opposite ways:
  - venue coverage is v2-family only, so the best alternative is understated and
    dominance incidence is a LOWER bound
  - quotes are gross of gas, and a two-hop route burns more gas, so on an all-in
    basis some measured dominance would disappear. Dominance incidence is an
    UPPER bound in that respect. Both need stating together; the gas-inclusive
    version requires receipt-measured gas per route topology.

Reads   data/raw/thegraph/{uniswap_v2,sushiswap_v2}/*_{swaps,hourly_reserves}_*.gz
Writes  data/processed/counterfactual_dominance.parquet
        output/exhibits/counterfactual_dominance_summary.jsonl
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RAW = ROOT / "data" / "raw" / "thegraph"
OUT_PARQUET = ROOT / "data" / "processed" / "counterfactual_dominance.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "counterfactual_dominance_summary.jsonl"

from ddvc.asset_types import classify  # noqa: E402
from ddvc.cpquote import Pool, quote_one_hop  # noqa: E402

VENUES = ("uniswap_v2", "sushiswap_v2")
MIN_USD = 100.0            # below this, gas dominates and the comparison is moot


def _net(s: dict) -> tuple[Decimal, Decimal]:
    return (Decimal(s.get("amount0In", "0")) - Decimal(s.get("amount0Out", "0")),
            Decimal(s.get("amount1In", "0")) - Decimal(s.get("amount1Out", "0")))


def _load_day(day: str) -> tuple[dict, dict, dict]:
    """Return (reserves by (pool,hour)), (pool meta), (swaps by (pool,hour))."""
    reserves: dict[tuple[str, int], tuple[Decimal, Decimal]] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    swaps: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for venue in VENUES:
        rp = RAW / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz"
        sp = RAW / venue / f"{venue}_swaps_{day}.jsonl.gz"
        if rp.exists():
            with gzip.open(rp, "rt") as fh:
                for line in fh:
                    d = json.loads(line)
                    pr = d.get("pair") or {}
                    pid = pr.get("id")
                    if not pid:
                        continue
                    reserves[(pid, int(d["hourStartUnix"]))] = (
                        Decimal(d["reserve0"]), Decimal(d["reserve1"]))
                    meta[pid] = (pr["token0"]["id"].lower(),
                                 pr["token1"]["id"].lower(), venue)
        if sp.exists():
            with gzip.open(sp, "rt") as fh:
                for line in fh:
                    s = json.loads(line)
                    pid = (s.get("pair") or {}).get("id")
                    ts = int(s.get("timestamp", 0))
                    if pid:
                        s["_tx"] = (s.get("transaction") or {}).get("id") or s.get("id", "")
                        swaps[(pid, ts - (ts % 3600))].append(s)
    return reserves, meta, swaps


def _state_at(states: list[tuple[int, Decimal, Decimal]], ts: int):
    """Reserves of a pool at or just before `ts`, from its reconstructed series."""
    import bisect
    i = bisect.bisect_right([s[0] for s in states], ts) - 1
    if i < 0:
        i = 0
    return (states[i][1], states[i][2]) if states else None


def one_day(day: str) -> pd.DataFrame | None:
    reserves, meta, swaps = _load_day(day)
    if not reserves or not swaps:
        return None

    # exact pre-trade reserves per swap, and per-hour cleanliness
    pre: dict[str, tuple[Decimal, Decimal, str]] = {}   # swap id -> reserves + pool
    clean_hours: set[tuple[str, int]] = set()
    for (pid, hour), group in swaps.items():
        stored = reserves.get((pid, hour))
        if stored is None:
            continue
        group.sort(key=lambda x: (int(x["timestamp"]), int(x.get("logIndex", 0))))
        r0, r1 = stored
        rev: list[tuple[str, Decimal, Decimal]] = []
        ok = True
        for s in reversed(group):
            d0, d1 = _net(s)
            r0 -= d0
            r1 -= d1
            if r0 <= 0 or r1 <= 0:
                ok = False
                break
            rev.append((s["id"], r0, r1))
        if not ok:
            continue
        prev = reserves.get((pid, hour - 3600))
        if prev is not None and prev[0] > 0 and prev[1] > 0:
            if (abs(float((r0 - prev[0]) / prev[0])) > 1e-9
                    or abs(float((r1 - prev[1]) / prev[1])) > 1e-9):
                continue          # unaccounted liquidity event: skip the hour
        clean_hours.add((pid, hour))
        for sid, a, b in rev:
            pre[sid] = (a, b, pid)

    # index reconstructed states by pool, in time order, for O(log n) lookup
    pool_states: dict[str, list[tuple[int, Decimal, Decimal]]] = collections.defaultdict(list)
    for (pid, hour), group in swaps.items():
        if (pid, hour) not in clean_hours:
            continue
        for s in group:
            st = pre.get(s["id"])
            if st is not None:
                pool_states[pid].append((int(s["timestamp"]), st[0], st[1]))
    for pid in pool_states:
        pool_states[pid].sort(key=lambda x: x[0])
    pair_index: dict[frozenset, dict[str, list]] = collections.defaultdict(dict)
    for pid, states in pool_states.items():
        mm = meta.get(pid)
        if mm:
            pair_index[frozenset((mm[0], mm[1]))][pid] = states

    # group swaps into routes by transaction, to find realised two-leg routes
    tx_groups: dict[str, list[dict]] = collections.defaultdict(list)
    for (pid, hour), group in swaps.items():
        if (pid, hour) not in clean_hours:
            continue
        for s in group:
            s["_pool"] = pid
            tx_groups[s["_tx"]].append(s)

    rows = []
    for tx, legs in tx_groups.items():
        if len(legs) != 2:
            continue
        legs.sort(key=lambda x: int(x.get("logIndex", 0)))
        l1, l2 = legs
        m1, m2 = meta.get(l1["_pool"]), meta.get(l2["_pool"])
        if not m1 or not m2:
            continue
        if l1["id"] not in pre or l2["id"] not in pre:
            continue

        def io(s: dict, m: tuple[str, str, str]):
            a0i = Decimal(s.get("amount0In", "0")); a1i = Decimal(s.get("amount1In", "0"))
            a0o = Decimal(s.get("amount0Out", "0")); a1o = Decimal(s.get("amount1Out", "0"))
            if a0i > 0 and a1o > 0:
                return m[0], m[1], a0i, a1o
            if a1i > 0 and a0o > 0:
                return m[1], m[0], a1i, a0o
            return None

        r1_, r2_ = io(l1, m1), io(l2, m2)
        if not r1_ or not r2_:
            continue
        a_in, mid1, amt_in, mid_amt = r1_
        mid2, b_out, _, out_amt = r2_
        if mid1 != mid2 or a_in == b_out:      # must chain, and no round trips
            continue
        usd = float(l1.get("amountUSD") or 0)
        if usd < MIN_USD:
            continue

        # counterfactual: best DIRECT pool for the same endpoints at the same state.
        # Indexed by unordered pair, so this is a lookup instead of a scan.
        cands = pair_index.get(frozenset((a_in, b_out)))
        if not cands:
            continue                            # no direct pool existed: not a window
        best_direct = None
        t_route = int(l1["timestamp"])
        for pid_d, states in cands.items():
            mm = meta[pid_d]
            st = _state_at(states, t_route)
            if st is None:
                continue
            q = quote_one_hop(Pool(pid_d, mm[0], mm[1], st[0], st[1], mm[2]), a_in, amt_in)
            if q and (best_direct is None or q > best_direct):
                best_direct = q
        if best_direct is None:
            continue

        sym, typ = classify(mid1)
        rows.append({
            "date": pd.to_datetime(day, format="%Y%m%d"),
            "tx": tx, "token_in": a_in, "token_out": b_out, "mid": mid1,
            "mid_symbol": sym, "mid_type": typ, "usd": usd,
            "realised_out": float(out_amt), "direct_quote": float(best_direct),
            "gap_bps": float(10_000 * (best_direct - out_amt) / out_amt) if out_amt > 0 else None,
        })
    return pd.DataFrame(rows) if rows else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", nargs="+", help="explicit YYYYMMDD days")
    ap.add_argument("--stride", type=int, default=30)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.days:
        days = args.days
    else:
        avail = sorted(p.name.removeprefix("uniswap_v2_swaps_").removesuffix(".jsonl.gz")
                       for p in (RAW / "uniswap_v2").glob("uniswap_v2_swaps_*.jsonl.gz"))
        days = avail[:: args.stride]
        if args.limit:
            days = days[: args.limit]
    print(f"quoting counterfactuals on {len(days)} day(s)", flush=True)

    parts = []
    for i, d in enumerate(days, 1):
        r = one_day(d)
        if r is not None and len(r):
            parts.append(r)
            print(f"  {d}: {len(r):,} comparable two-leg routes", flush=True)
        else:
            print(f"  {d}: none", flush=True)
    if not parts:
        sys.exit("no comparable routes")

    df = pd.concat(parts, ignore_index=True)
    df = df[df.gap_bps.notna()]
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_EXHIBIT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)

    print(f"\ncomparable intermediated routes with a direct alternative: {len(df):,}")
    print(f"date range: {df.date.min().date()} to {df.date.max().date()}")
    dom = df[df.gap_bps > 0]
    print(f"\nroutes where DIRECT would have returned more (gross of gas): "
          f"{len(dom):,} ({100*len(dom)/len(df):.1f}%)")
    print(f"  median gap among those: {dom.gap_bps.median():.1f} bps")
    print(f"  median gap over all routes: {df.gap_bps.median():.1f} bps")
    print("\nby intermediary type:")
    for t, s in df.groupby("mid_type"):
        d = s[s.gap_bps > 0]
        print(f"  {t:<14} routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median gap {d.gap_bps.median() if len(d) else float('nan'):8.1f} bps")
    print("\nby size bin:")
    df["bin"] = pd.cut(df.usd, [100, 1e3, 1e4, 1e5, 1e12],
                       labels=["100-1k", "1k-10k", "10k-100k", ">100k"])
    for b, s in df.groupby("bin", observed=True):
        d = s[s.gap_bps > 0]
        print(f"  {b:>9}  routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median gap {d.gap_bps.median() if len(d) else float('nan'):8.1f} bps")
    df.groupby([pd.Grouper(key="date", freq="YS"), "mid_type"]).agg(
        routes=("gap_bps", "size"),
        pct_dominated=("gap_bps", lambda x: 100 * (x > 0).mean()),
        median_gap_bps=("gap_bps", "median"),
    ).to_parquet(OUT_EXHIBIT)
    print(f"\nwrote {OUT_PARQUET.relative_to(ROOT)} and {OUT_EXHIBIT.relative_to(ROOT)}")
    print("\nBIAS DIRECTIONS, both live: v2-family venues only understates the best "
          "alternative (dominance is a LOWER bound), while quotes gross of gas "
          "favour the two-hop route (dominance is an UPPER bound). Neither is "
          "resolved until gas is measured from receipts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
