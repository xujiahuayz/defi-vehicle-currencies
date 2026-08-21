#!/usr/bin/env python3
"""How much of multi-leg routing is self-returning, across days and not on one day?

This exists because a number measured here drifted. A single day was measured
at unusually high round-trip shares, and that pair then propagated
into eleven places across `docs/` and `scripts/`, including the justification for excluding
round trips, the argument for count-weighting over value-weighting, and a retired
fixed-clock diagnostic where it carried the claim that arbitrage capacity is present. Two
of those copies kept the qualifier "on the day inspected" and the rest dropped
it, so a single-day extreme read as a corpus constant. Java caught it from her own memory
of an early check.

The figure was never wrong, which is what made it durable: anyone re-checking it against
its stated source would reproduce it exactly. The full eligible panel now contains 2,449
days. Its medians are 12.8% by count and 21.0% by value; the value-share extreme is 97.7%
on 2023-10-13.

So the fix is not a corrected constant, since a corrected constant drifts the same way. It
is a script that reports the DISTRIBUTION across days and writes it as an exhibit, so any
claim about round-trip contamination cites a range with a denominator attached.

The screen itself is unaffected. A route whose first input token equals its last output
token is outside the endpoint-to-endpoint conversion unit. This population can contain
cyclic arbitrage, wash activity and other self-returning paths; the endpoint rule does not
classify each route. What the magnitude governs is how much rhetorical weight the
contamination argument can carry, which is where the drift did its damage.

Reads   data/unified/YYYYMMDD.parquet
Writes  output/exhibits/round_trip_share_by_day.jsonl
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

from ddvc.tables import write_exhibit  # noqa: E402
from ddvc.datasets import route_partitions  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT = ROOT / "output" / "exhibits" / "round_trip_share_by_day.jsonl"
COLS = ["tx_hash", "component_id", "token_in", "token_out", "amount_usd", "log_index", "route_class"]
# A day with too few multi-leg routes gives a share dominated by sampling noise, and a
# noisy day at the tail is exactly what produced the drift this script exists to prevent.
MIN_MULTI_LEG = 200


def measure_day(path: Path) -> dict[str, float] | None:
    try:
        d = pd.read_parquet(path, columns=COLS)
    except Exception:
        return None
    d = d[d.route_class.isin(["single", "coherent"])]
    # The upper notional bound removes the null-symbol junk-token repricing failure that
    # has contaminated value-weighted measures elsewhere in this project. It moves the
    # pooled figure by 0.3pp, so it is a hygiene screen and not a lever on the answer.
    d = d[(d.amount_usd > 0) & (d.amount_usd < 1e9)]
    if d.empty:
        return None
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    g = d.groupby(["tx_hash", "component_id"], sort=False)
    first, last, n = g.token_in.first(), g.token_out.last(), g.size()
    # One route's notional is the largest leg, since summing legs would count the same
    # dollar once per hop and inflate long routes mechanically.
    usd = g.amount_usd.max()
    multi = n.values > 1
    trip = (first.values == last.values) & multi
    if int(multi.sum()) < MIN_MULTI_LEG:
        return None
    denom = float(usd[multi].sum())
    return {"day": path.stem, "routes": int(len(n)), "multi_leg": int(multi.sum()),
            "round_trips": int(trip.sum()),
            "share_by_count": float(trip.sum() / multi.sum()),
            "share_by_value": float(usd[trip].sum() / denom) if denom > 0 else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--days",
        type=int,
        default=0,
        help="number of evenly spaced days; 0 uses every available day",
    )
    ap.add_argument("--workers", type=int, default=8)
    # The day the drifted figure came from. A stride sample need not contain it, and then
    # "the worst day in the sample" quietly means something different from the day every
    # doc cites, so it is pinned in rather than left to the stride.
    ap.add_argument("--include", nargs="*", default=["20251206"],
                    help="days to force into the sample regardless of the stride")
    args = ap.parse_args()

    release = route_partitions(COLS, nonempty=False)
    files = list(release.paths)
    if args.days < 0:
        ap.error("--days must be nonnegative")
    if args.workers < 1:
        ap.error("--workers must be positive")
    if args.days == 0 or args.days >= len(files):
        picked = files
    else:
        step = max(1, len(files) // args.days)
        picked = files[::step][: args.days]
    for day in args.include:
        extra = UNIFIED / f"{day}.parquet"
        if extra.exists() and extra not in picked:
            picked.append(extra)
    scope = "all" if len(picked) == len(files) else "sampled"
    print(
        f"measuring {len(picked):,} {scope} days across {len(files):,} available "
        f"with {args.workers} workers\n",
        flush=True,
    )

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(measure_day, picked), 1):
            if row:
                rows.append(row)
            if index % 250 == 0:
                print(f"  {index:,}/{len(picked):,}", flush=True)
    if not rows:
        print("no day cleared the minimum multi-leg count")
        return 1
    df = pd.DataFrame(rows).sort_values("day")

    print(f"{len(df)} days with at least {MIN_MULTI_LEG} multi-leg routes, "
          f"{df.day.min()} to {df.day.max()}")
    print("\nround trips as a share of MULTI-LEG routes, distribution ACROSS DAYS")
    print(f"  {'':>10}{'min':>9}{'p25':>9}{'median':>9}{'p75':>9}{'p95':>9}{'max':>9}")
    for col, label in (("share_by_count", "by count"), ("share_by_value", "by value")):
        q = df[col].quantile([0, 0.25, 0.5, 0.75, 0.95, 1.0]).values
        print(f"  {label:>10}" + "".join(f"{v:>8.1%}" for v in q))

    worst = df.loc[df.share_by_value.idxmax()]
    print(f"\nworst day by value: {worst.day} at {worst.share_by_value:.1%} by value "
          f"and {worst.share_by_count:.1%} by count")
    print("Quote the median with its denominator. Quote the worst day only as the extreme")
    print("case that motivated the screen, and name the date when doing so.")

    write_exhibit(df, OUT)
    release.assert_current()
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
