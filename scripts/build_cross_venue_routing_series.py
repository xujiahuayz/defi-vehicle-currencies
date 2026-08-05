#!/usr/bin/env python3
"""Full-panel daily series of route composition across the consolidated venue layer.

Answers one descriptive question on every day of the sample: of the routes that
pass through an intermediary at all, what share span more than one venue?

Motivation. A single-venue study of vehicle-currency formation is not merely
incomplete. If routers increasingly split a single economic trade across
venues, then the venue is the wrong unit of analysis and the intermediating
asset is the right one. An eight-day sample suggested the cross-venue share
quadruples over the sample; this computes it on all ~2,277 days so the claim
can be stated with a full series behind it.

Definitions used here, narrow by design so nothing depends on the
still-open vehicle-asset definitions:
  route       one reconstructed input-to-output path, keyed (tx_hash, component_id)
  multi-leg   a route whose legs number more than one
  cross-venue a multi-leg route whose legs touch more than one `source`
  economic    a multi-leg route whose first input token differs from its last
              output token

WHY THE ECONOMIC FILTER EXISTS. A route that starts and ends in the same token
(A -> K -> A) moves no value between two parties: it is atomic arbitrage or wash
trading. Measured on 2025-12-06, such round trips were 25.6% of multi-leg routes
by count and 90.5% by dollar value, and including them drove the cross-venue
value share to 9.6% while the count share sat at 60.6%. Excluding them puts the
value share at 88.8%. So the entire apparent 2025-Q4 reversal in the
value-weighted series was round-trip flow in the denominator. One contributing
case: six separate transactions each running WETH -> (junk token) -> WETH on one
venue, each repriced to exactly $9,113,892.

This is the same threat the reference repo's `ddc.integrity` module addresses
with citations (Cong, Li, Tang and Yang 2023 on wash trading; Daian et al. 2020
and Heimbach et al. 2024 on MEV and non-atomic arbitrage, the latter measuring
over a quarter of Ethereum DEX volume as likely non-atomic arbitrage). That
module's conclusion applies here directly: volume-weighted measures are more
exposed to inflation than count-based ones, so the count series is reported as
primary and the value series as secondary.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/cross_venue_routing_daily.parquet
        output/exhibits/cross_venue_routing_series.parquet

Run     .venv/bin/python scripts/build_cross_venue_routing_series.py [--workers N]
Rebuild is idempotent: delete the outputs and rerun to regenerate byte-identically.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UNIFIED = ROOT / "data" / "unified"
OUT_PARQUET = ROOT / "data" / "processed" / "cross_venue_routing_daily.parquet"
OUT_CSV = ROOT / "output" / "exhibits" / "cross_venue_routing_series.parquet"

COLS = ["tx_hash", "component_id", "source", "amount_usd", "route_class",
        "token_in", "token_out"]


def one_day(path: Path) -> dict | None:
    """Reduce a single day of swap legs to route-composition counts."""
    try:
        df = pd.read_parquet(path, columns=COLS)
    except Exception as exc:  # a malformed day should not kill the panel
        return {"date": path.stem, "error": str(exc)[:120]}
    if df.empty:
        return {"date": path.stem, "legs": 0, "routes": 0}

    g = df.groupby(["tx_hash", "component_id"], sort=False)
    legs = g.size()
    venues = g["source"].nunique()
    usd = g["amount_usd"].max()  # route notional, not the sum of its legs
    first_in = g["token_in"].first()
    last_out = g["token_out"].last()

    multi = legs > 1
    round_trip = multi & (first_in == last_out)   # atomic arbitrage / wash
    econ = multi & ~round_trip                   # genuine A -> K -> B exchange
    cross_all = multi & (venues > 1)             # unfiltered, kept for the audit
    cross = econ & (venues > 1)                  # headline

    def share(num, den):
        d = den.sum()
        return float(num.sum() / d) if d else float("nan")

    def ushare(num, den):
        d = usd[den].sum()
        return float(usd[num].sum() / d) if d else float("nan")

    return {
        "date": pd.to_datetime(path.stem, format="%Y%m%d"),
        "legs": int(len(df)),
        "routes": int(len(legs)),
        "single_leg_routes": int((~multi).sum()),
        "multi_leg_routes": int(multi.sum()),
        "round_trip_routes": int(round_trip.sum()),
        "economic_multileg_routes": int(econ.sum()),
        "cross_venue_routes": int(cross.sum()),
        # headline: of ECONOMIC intermediated routes, what share spans venues
        "cross_venue_share": share(cross, econ),
        "cross_venue_usd_share": ushare(cross, econ),
        # audit trail: the same statistic WITHOUT the economic filter, so the
        # contamination is visible in the panel rather than only in a comment
        "cross_venue_share_unfiltered": share(cross_all, multi),
        "cross_venue_usd_share_unfiltered": ushare(cross_all, multi),
        "round_trip_share_of_multileg": share(round_trip, multi),
        "round_trip_usd_share_of_multileg": ushare(round_trip, multi),
        "economic_multileg_usd": float(usd[econ].sum()),
        "cross_venue_usd": float(usd[cross].sum()),
        "total_usd": float(usd.sum()),
        "venues_active": int(df["source"].nunique()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="first N days only, for a smoke test")
    args = ap.parse_args()

    days = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        days = days[: args.limit]
    if not days:
        sys.exit(f"no unified day files under {UNIFIED}")
    print(f"reducing {len(days):,} days with {args.workers} workers", flush=True)

    rows, errors = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one_day, d): d for d in days}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r is None:
                continue
            (errors if "error" in r else rows).append(r)
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)

    if errors:
        print(f"\n{len(errors)} day(s) failed to read:")
        for e in errors[:10]:
            print("  ", e["date"], e["error"])

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = df[df["routes"] > 0].copy()

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_parquet(OUT_CSV, index=False)

    # monthly view, which is what a figure would plot
    m = df.set_index("date").resample("MS").agg(
        econ=("economic_multileg_routes", "sum"),
        cvr=("cross_venue_routes", "sum"),
        rt=("round_trip_routes", "sum"),
        multi=("multi_leg_routes", "sum"),
        routes=("routes", "sum"),
        venues_active=("venues_active", "max"),
        cross_venue_usd=("cross_venue_usd", "sum"),
        econ_usd=("economic_multileg_usd", "sum"),
    )
    m["cross_venue_share_of_multileg"] = m.cvr / m.econ
    m["cross_venue_usd_share"] = m.cross_venue_usd / m.econ_usd
    m["round_trip_share"] = m.rt / m.multi

    print(f"\ndays retained: {len(df):,}   {df.date.min().date()} to {df.date.max().date()}")
    print(f"total legs: {df.legs.sum():,}   total routes: {df.routes.sum():,}")
    print("\nannual means of the headline share (count-weighted, then value-weighted):")
    a = m.resample("YS").agg({"cross_venue_share_of_multileg": "mean",
                              "cross_venue_usd_share": "mean",
                              "round_trip_share": "mean",
                              "venues_active": "max"})
    print("  year   count   value   (round trips excluded, share of multileg shown)")
    for idx, row in a.iterrows():
        print(f"  {idx.year}   {row.cross_venue_share_of_multileg:6.1%}"
              f"  {row.cross_venue_usd_share:6.1%}"
              f"   rt={row.round_trip_share:5.1%}"
              f"   venues {int(row.venues_active)}")
    print(f"\nwrote {OUT_PARQUET.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
