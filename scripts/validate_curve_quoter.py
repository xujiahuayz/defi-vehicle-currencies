#!/usr/bin/env python3
"""Does the StableSwap quoter reproduce realised Curve swaps, and at what cost in granularity?

Two questions at once, because they cannot be separated with the data available.

First, is the invariant implementation right. The v2, v3 and v4 quoters were accepted
only after reproducing realised swaps to a median absolute error of 0.0000%, and Curve
must clear the same bar before its quotes enter the route-cost panel.

Second, what does daily granularity cost. Curve balances arrive as daily snapshots
while the v2 family is hourly and the concentrated-liquidity venues are per-swap. Since
mixing state measured at different instants is the defect that made an "hour" compare
pools up to 23 hours apart elsewhere in this project, the size of that error has to be
measured rather than assumed. StableSwap is nearly flat near par, so a stable pool's
quote may be insensitive to intra-day balance drift; if it is not, Curve legs need
per-block balances through gateway time-travel queries instead.

The amplification coefficient is calibrated per pool-day from that day's own trades,
then the fit is scored on trades it was not fitted to, so a good error is evidence
about the pricing path rather than about the fit's flexibility.

Writes  output/exhibits/curve_quoter_validation.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.pricing.stableswap import StablePool, calibrate_amp, quote_exact_input  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph" / "curve"
OUT = ROOT / "output" / "exhibits" / "curve_quoter_validation.jsonl"


def _rows(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def days_with_balances(limit: int | None) -> list[str]:
    out = []
    for p in sorted(RAW.glob("curve_daily_*.jsonl.gz")):
        day = p.name[len("curve_daily_"):-len(".jsonl.gz")]
        for r in _rows(p):
            if "inputTokenBalances" in r:
                out.append(day)
            break
        if limit and len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--min-swaps", type=int, default=8,
                    help="pool-days with fewer trades cannot be fitted and scored apart")
    args = ap.parse_args()

    days = days_with_balances(None)
    if not days:
        print("no re-fetched Curve days carry balances yet")
        return 1
    step = max(1, len(days) // args.days)
    picked = days[::step][: args.days]
    print(f"{len(days)} Curve days carry balances; validating on {len(picked)}: "
          f"{picked[0]}..{picked[-1]}\n")

    rows = []
    for day in picked:
        pools: dict[str, dict] = {}
        for r in _rows(RAW / f"curve_daily_{day}.jsonl.gz"):
            p = r.get("pool") or {}
            pid = (p.get("id") or "").lower()
            bals = r.get("inputTokenBalances")
            toks = p.get("inputTokens") or []
            if not pid or not bals or len(bals) != len(toks):
                continue
            try:
                pools[pid] = {
                    "tokens": tuple((t.get("id") or "").lower() for t in toks),
                    "decimals": tuple(int(t.get("decimals")) for t in toks),
                    "balances": tuple(int(b) for b in bals),
                }
            except (TypeError, ValueError):
                continue

        trades: dict[str, list] = defaultdict(list)
        for s in _rows(RAW / f"curve_swaps_{day}.jsonl.gz"):
            pid = ((s.get("pool") or {}).get("id") or "").lower()
            if pid not in pools:
                continue
            try:
                ti = (s["tokenIn"]["id"] or "").lower()
                to = (s["tokenOut"]["id"] or "").lower()
                ai, ao = int(s["amountIn"]), int(s["amountOut"])
            except (KeyError, TypeError, ValueError):
                continue
            if ai > 0 and ao > 0:
                trades[pid].append((ti, to, ai, ao))

        fitted = scored = excluded = 0
        errs: list[float] = []
        amps: list[int] = []
        for pid, obs in trades.items():
            if len(obs) < args.min_swaps:
                continue
            meta = pools[pid]
            half = len(obs) // 2
            fit = calibrate_amp(meta["balances"], meta["decimals"], meta["tokens"],
                                obs[:half])
            if fit is None:
                excluded += 1
                continue
            amp, _ = fit
            fitted += 1
            amps.append(amp)
            pool = StablePool(pool_id=pid, tokens=meta["tokens"],
                              balances=meta["balances"], decimals=meta["decimals"],
                              amp=amp)
            for ti, to, ai, ao in obs[half:]:
                q = quote_exact_input(pool, ti, to, ai)
                if q is None:
                    continue
                errs.append(100 * abs(q - ao) / ao)
                scored += 1
        if not errs:
            print(f"  {day}: no scorable pool-days")
            continue
        errs.sort()
        rows.append({"day": day, "pools_fitted": fitted, "pools_excluded": excluded,
                     "held_out_trades": scored,
                     "median_abs_err_pct": errs[len(errs) // 2],
                     "p25_abs_err_pct": errs[len(errs) // 4],
                     "p75_abs_err_pct": errs[3 * len(errs) // 4],
                     "within_1pct": 100 * sum(1 for e in errs if e < 1) / len(errs),
                     "median_amp": statistics.median(amps) if amps else None})
        r = rows[-1]
        print(f"  {day}: {fitted:>4} pools fitted, {excluded:>3} excluded, "
              f"{scored:>6,} held-out trades | median |err| {r['median_abs_err_pct']:>8.3f}% "
              f"| within 1% {r['within_1pct']:>5.1f}% | median A {r['median_amp']}")

    if not rows:
        return 1
    allmed = statistics.median([r["median_abs_err_pct"] for r in rows])
    w1 = statistics.median([r["within_1pct"] for r in rows])
    print(f"\nacross days: median of daily median errors {allmed:.3f}%, "
          f"median within-1% share {w1:.1f}%")
    print("\nReading. A small error means the invariant is right AND daily balance")
    print("snapshots are adequate for Curve legs, because both would have to hold. A")
    print("large error cannot distinguish the two, so the next step would be per-block")
    print("balances via gateway time-travel queries before blaming the implementation.")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
