#!/usr/bin/env python3
"""Do the fetched v2 mints and burns explain the pool-hours we currently drop?

The v2 reconstruction unwinds an hour's swaps backwards from the subgraph's
end-of-hour reserves to recover the state before each trade. That is exact only
when swaps were the ONLY thing that moved reserves during the hour. A mint, burn or
direct transfer breaks it, and `cpquote.hour_is_clean` detects the break from
reserve continuity alone, which is why roughly 3.2% of comparable pool-hours are
excluded. Detection was never the problem; correction was, because the liquidity
events were not in the dataset.

They are now, for 2,279 of 2,279 days. This script tests the claim that motivated
fetching them, rather than assuming it: for each flagged pool-hour, does the net
amount0/amount1 of that hour's mints and burns account for the observed continuity
gap? If it does, the hour is recoverable and the exclusion can be lifted. If it does
not, something else moves reserves, most likely a direct token transfer into the
pair or a fee-on-transfer token, and the hour should stay excluded.

Why this matters beyond coverage. The excluded hours are not a random sample:
liquidity events concentrate in actively managed and newly launched pools, which are
exactly the pools where routing decisions are most contested. Dropping them is a
selection concern, so recovering them removes a threat rather than adding rows.

Reads   data/raw/thegraph/uniswap_v2/uniswap_v2_{hourly_reserves,swaps,mints,burns}_*
Writes  output/exhibits/v2_liquidity_hour_recovery.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph" / "uniswap_v2"
OUT = ROOT / "output" / "exhibits" / "v2_liquidity_hour_recovery.jsonl"


def _load(day: str, stream: str) -> list[dict]:
    p = RAW / f"uniswap_v2_{stream}_{day}.jsonl.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt") as fh:
        return [json.loads(line) for line in fh]


def analyse_day(day: str, tol: float) -> dict:
    reserves = _load(day, "hourly_reserves")
    if not reserves:
        return {"day": day, "status": "no reserves"}

    # end-of-hour reserves by (pair, hour)
    end: dict[tuple[str, int], tuple[Decimal, Decimal]] = {}
    for r in reserves:
        pair = ((r.get("pair") or {}).get("id") or "").lower()
        try:
            h = int(r["hourStartUnix"])
            r0, r1 = Decimal(r["reserve0"]), Decimal(r["reserve1"])
        except (KeyError, TypeError, ValueError):
            continue
        if pair and r0 > 0 and r1 > 0:
            end[(pair, h)] = (r0, r1)

    # net swap deltas per (pair, hour)
    swap_delta: dict[tuple[str, int], list[Decimal]] = defaultdict(
        lambda: [Decimal(0), Decimal(0)])
    for s in _load(day, "swaps"):
        pair = ((s.get("pair") or {}).get("id") or "").lower()
        try:
            ts = int(s["timestamp"])
            d0 = Decimal(s["amount0In"]) - Decimal(s["amount0Out"])
            d1 = Decimal(s["amount1In"]) - Decimal(s["amount1Out"])
        except (KeyError, TypeError, ValueError):
            continue
        if not pair:
            continue
        h = ts - (ts % 3600)
        acc = swap_delta[(pair, h)]
        acc[0] += d0
        acc[1] += d1

    # net liquidity deltas per (pair, hour): a mint adds, a burn removes
    liq_delta: dict[tuple[str, int], list[Decimal]] = defaultdict(
        lambda: [Decimal(0), Decimal(0)])
    liq_events: dict[tuple[str, int], int] = defaultdict(int)
    for stream, sign in (("mints", 1), ("burns", -1)):
        for e in _load(day, stream):
            pair = ((e.get("pair") or {}).get("id") or "").lower()
            try:
                ts = int(e["timestamp"])
                a0, a1 = Decimal(e["amount0"]), Decimal(e["amount1"])
            except (KeyError, TypeError, ValueError):
                continue
            if not pair:
                continue
            h = ts - (ts % 3600)
            acc = liq_delta[(pair, h)]
            acc[0] += sign * a0
            acc[1] += sign * a1
            liq_events[(pair, h)] += 1

    # For each hour with a previous hour to compare against, is the gap between
    # (end_prev + swaps) and end explained by liquidity events?
    flagged = explained = unexplained = clean = 0
    for (pair, h), (r0, r1) in end.items():
        prev = end.get((pair, h - 3600))
        if prev is None:
            continue
        p0, p1 = prev
        s0, s1 = swap_delta.get((pair, h), [Decimal(0), Decimal(0)])
        gap0 = r0 - (p0 + s0)
        gap1 = r1 - (p1 + s1)
        rel0 = abs(float(gap0 / p0)) if p0 else 0.0
        rel1 = abs(float(gap1 / p1)) if p1 else 0.0
        if rel0 < tol and rel1 < tol:
            clean += 1
            continue
        flagged += 1
        l0, l1 = liq_delta.get((pair, h), [Decimal(0), Decimal(0)])
        res0 = abs(float((gap0 - l0) / p0)) if p0 else 0.0
        res1 = abs(float((gap1 - l1) / p1)) if p1 else 0.0
        if res0 < tol and res1 < tol:
            explained += 1
        else:
            unexplained += 1

    total = clean + flagged
    return {"day": day, "status": "ok", "pool_hours": total, "clean": clean,
            "flagged": flagged,
            "explained_by_liquidity": explained, "still_unexplained": unexplained,
            "flagged_share": (flagged / total) if total else 0.0,
            "recovered_share_of_flagged": (explained / flagged) if flagged else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", nargs="+",
                    default=["20210615", "20220615", "20230615", "20240115", "20250615"])
    ap.add_argument("--tol", type=float, default=1e-6,
                    help="relative continuity tolerance; the quoter uses 1e-9, but a "
                         "looser value here separates real breaks from float noise")
    args = ap.parse_args()

    rows = [analyse_day(d, args.tol) for d in args.days]
    for r in rows:
        if r.get("status") != "ok":
            print(f"  {r['day']}: {r.get('status')}")
            continue
        print(f"  {r['day']}: {r['pool_hours']:>7,} comparable pool-hours | "
              f"flagged {r['flagged']:>6,} ({r['flagged_share']:.2%}) | "
              f"explained by liquidity events {r['explained_by_liquidity']:>6,} "
              f"({r['recovered_share_of_flagged']:.1%} of flagged) | "
              f"still unexplained {r['still_unexplained']:,}")

    ok = [r for r in rows if r.get("status") == "ok"]
    if ok:
        tot_f = sum(r["flagged"] for r in ok)
        tot_e = sum(r["explained_by_liquidity"] for r in ok)
        tot_h = sum(r["pool_hours"] for r in ok)
        print(f"\nacross {len(ok)} days: {tot_h:,} pool-hours, {tot_f:,} flagged "
              f"({tot_f/max(tot_h,1):.2%}), {tot_e:,} recoverable "
              f"({tot_e/max(tot_f,1):.1%} of flagged)")
        print("\nReading: a high recovered share means the liquidity fetch removes the "
              "selection concern, since the dropped hours were dropped for a reason we "
              "can now correct. A low share means something other than mints and burns "
              "moves reserves, most likely direct transfers or fee-on-transfer tokens, "
              "and those hours should stay excluded.")
        write_exhibit(pd.DataFrame(ok), OUT)
        print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
