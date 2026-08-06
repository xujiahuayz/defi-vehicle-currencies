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
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.pricing.stableswap import StablePool, calibrate_amp, quote_exact_input
from ddvc.tables import write_exhibit

RAW = DATA_DIR / "raw" / "thegraph" / "curve"
OUT = OUTPUT_DIR / "exhibits" / "curve_quoter_validation.jsonl"
CODE_SOURCES = [
    "scripts/validate_curve_quoter.py",
    "src/ddvc/pricing/stableswap.py",
]


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


def summarise_errors(signed_errors_pct: list[float]) -> dict[str, float]:
    """Tail and direction diagnostics in percentage points of realised output."""
    signed = pd.Series(signed_errors_pct, dtype=float)
    absolute = signed.abs()
    return {
        "median_abs_err_pct": float(absolute.median()),
        "p25_abs_err_pct": float(absolute.quantile(0.25)),
        "p75_abs_err_pct": float(absolute.quantile(0.75)),
        "p90_abs_err_pct": float(absolute.quantile(0.90)),
        "p95_abs_err_pct": float(absolute.quantile(0.95)),
        "p99_abs_err_pct": float(absolute.quantile(0.99)),
        "max_abs_err_pct": float(absolute.max()),
        "within_1pct": float(100 * absolute.lt(1).mean()),
        "overquote_gt_10bps_pct": float(100 * signed.gt(0.10).mean()),
        "overquote_gt_25bps_pct": float(100 * signed.gt(0.25).mean()),
    }


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
    pooled_signed_errors: list[float] = []
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
        signed_errors: list[float] = []
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
                signed_errors.append(100 * (q - ao) / ao)
                scored += 1
        if not signed_errors:
            print(f"  {day}: no scorable pool-days")
            continue
        pooled_signed_errors.extend(signed_errors)
        rows.append({
            "day": day,
            "pools_fitted": fitted,
            "pools_excluded": excluded,
            "held_out_trades": scored,
            **summarise_errors(signed_errors),
            "median_amp": statistics.median(amps) if amps else None,
        })
        r = rows[-1]
        print(f"  {day}: {fitted:>4} pools fitted, {excluded:>3} excluded, "
              f"{scored:>6,} held-out trades | median |err| {r['median_abs_err_pct']:>8.3f}% "
              f"| p90 {r['p90_abs_err_pct']:>7.3f}% | p99 {r['p99_abs_err_pct']:>7.3f}% "
              f"| overquote >25 bps {r['overquote_gt_25bps_pct']:>5.1f}%")

    if not rows:
        return 1
    pooled = summarise_errors(pooled_signed_errors)
    print(
        f"\npooled {len(pooled_signed_errors):,} held-out trades: "
        f"median |error| {pooled['median_abs_err_pct']:.3f}%, "
        f"p90 {pooled['p90_abs_err_pct']:.3f}%, "
        f"p95 {pooled['p95_abs_err_pct']:.3f}%, "
        f"p99 {pooled['p99_abs_err_pct']:.3f}%, "
        f"max {pooled['max_abs_err_pct']:.2f}%; "
        f"overquote >25 bps {pooled['overquote_gt_25bps_pct']:.1f}%"
    )
    print("\nReading. A small error means the invariant is right AND daily balance")
    print("snapshots are adequate for Curve legs, because both would have to hold. A")
    print("large error cannot distinguish the two, so the next step would be per-block")
    print("balances via gateway time-travel queries before blaming the implementation.")
    write_exhibit(
        pd.DataFrame(rows),
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[RAW],
        notes="held-out Curve quote errors with upper-tail and signed-overquote diagnostics",
    )
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
