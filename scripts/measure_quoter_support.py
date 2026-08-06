"""Where is the quoter actually validated, in size-relative-to-depth terms?

The counterfactual quoters were each accepted after reproducing REALISED swaps: v2 at
0.0000% median error, v3 and v4 at 0.0000% in all four direction-by-tick-crossing cells,
Curve at 0.033%, Balancer at 0.0000%. Every one of those validations draws from the same
population, namely trades someone chose to make, which are by construction trades whose
pool was deep enough to serve them. The panel then applies those quoters to 123.8 million
hypothetical routes, including routes through pools no router would touch, and in that
region a quote is an extrapolation with no measured error.

The consequence is not speculative. Between 44.5% and 82.0% of the panel's route-cost
gaps imply an arbitrage cycle that pays after three pool fees and three-hop gas, and at a
100,000 dollar trade the MEDIAN gap is 4,655 basis points. A 46.5% same-block arbitrage
would be taken immediately by anyone with a flash loan and no capital, so those gaps
cannot be economic facts.

The fix has to be an EX-ANTE screen on the pool, not a filter on the gap. Filtering on the
gap conditions on the magnitude of a monotone function of the outcome, which is selection
on the dependent variable, and that is exactly the mistake that voided this project's
earlier defence against quote collapse. So the screen is stated in terms of a quantity
known before any quote is computed: the trade's size relative to the pool's depth.

This script measures where the validation population lives on that axis, so the panel's
support bound is DERIVED from the trades the quoters were checked against instead of
chosen. What comes out is a ratio, and the panel then declines to quote any route whose
size-to-depth exceeds it, reporting how much of the route universe that removes.

Reads   data/raw/thegraph/uniswap_v2/uniswap_v2_{swaps,hourly_reserves}_*.jsonl.gz
        data/raw/thegraph/uniswap_v4/uniswap_v4_swaps_*.jsonl.gz
Writes  output/exhibits/quoter_support_bounds.jsonl
        output/exhibits/v4_quote_support.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ddvc.fetch.raw import v4_quote_status
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit

RAW = DATA_DIR / "raw" / "thegraph" / "uniswap_v2"
V4_RAW = DATA_DIR / "raw" / "thegraph" / "uniswap_v4"
OUT = OUTPUT_DIR / "exhibits" / "quoter_support_bounds.jsonl"
V4_OUT = OUTPUT_DIR / "exhibits" / "v4_quote_support.jsonl"


def _rows(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def measure_day(day: str) -> list[float]:
    """Size-to-depth ratio for every realised v2 swap that can be matched to reserves."""
    depth: dict[tuple[str, int], tuple[float, float]] = {}
    for r in _rows(RAW / f"uniswap_v2_hourly_reserves_{day}.jsonl.gz"):
        pair = ((r.get("pair") or {}).get("id") or "").lower()
        try:
            h = int(r["hourStartUnix"])
            r0, r1 = float(r["reserve0"]), float(r["reserve1"])
        except (KeyError, TypeError, ValueError):
            continue
        if pair and r0 > 0 and r1 > 0:
            depth[(pair, h)] = (r0, r1)

    ratios: list[float] = []
    for s in _rows(RAW / f"uniswap_v2_swaps_{day}.jsonl.gz"):
        pair = ((s.get("pair") or {}).get("id") or "").lower()
        try:
            ts = int(s["timestamp"])
            a0in, a1in = float(s["amount0In"]), float(s["amount1In"])
        except (KeyError, TypeError, ValueError):
            continue
        d = depth.get((pair, ts - (ts % 3600)))
        if not d:
            continue
        # Whichever side was paid in, compare it against that side's reserve. This is
        # the quantity the constant-product quote is a function of, so it is the axis on
        # which extrapolation happens.
        if a0in > 0:
            amt, res = a0in, d[0]
        elif a1in > 0:
            amt, res = a1in, d[1]
        else:
            continue
        if res > 0 and amt > 0:
            r = amt / res
            # A constant-product trade CANNOT consume the whole input reserve, since
            # the required input diverges as the output side empties, so a ratio at or
            # above 1 is physically impossible and identifies a broken row rather than
            # a large trade. Without this screen the pooled distribution reached
            # 4.8e28 times the reserve and every quantile above the 95th was noise.
            # The cause is the null-symbol junk-token contamination this project has
            # hit repeatedly, where a token's reported amounts and its pool's reserves
            # are on different scales.
            if r < 1.0:
                ratios.append(r)
    return ratios


def measure_v4_support() -> pd.DataFrame:
    """Swap- and value-weighted coverage of the vanilla v4 quoter contract."""
    counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    volumes: defaultdict[tuple[str, str], float] = defaultdict(float)
    for path in sorted(V4_RAW.glob("uniswap_v4_swaps_*.jsonl.gz")):
        day = path.name[len("uniswap_v4_swaps_"):-len(".jsonl.gz")]
        year = day[:4]
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                status = v4_quote_status(row)
                counts[(year, status)] += 1
                try:
                    volume = abs(float(row.get("amountUSD") or 0))
                except (TypeError, ValueError):
                    volume = 0.0
                if math.isfinite(volume):
                    volumes[(year, status)] += volume

    rows = []
    years = sorted({year for year, _ in counts})
    for year in [*years, "ALL"]:
        scoped_counts: defaultdict[str, int] = defaultdict(int)
        scoped_volumes: defaultdict[str, float] = defaultdict(float)
        for (observed_year, status), count in counts.items():
            if year == "ALL" or year == observed_year:
                scoped_counts[status] += count
                scoped_volumes[status] += volumes[(observed_year, status)]
        total_count = sum(scoped_counts.values())
        total_volume = sum(scoped_volumes.values())
        for status in sorted(scoped_counts):
            rows.append(
                {
                    "year": year,
                    "status": status,
                    "supported": status == "vanilla_static_fee",
                    "swaps": scoped_counts[status],
                    "swap_share": scoped_counts[status] / total_count if total_count else None,
                    "volume_usd": scoped_volumes[status],
                    "volume_share": scoped_volumes[status] / total_volume if total_volume else None,
                }
            )
    return pd.DataFrame(rows)


def write_v4_support() -> None:
    support = measure_v4_support()
    if support.empty:
        raise RuntimeError("no v4 swaps available for support audit")
    invalid = support[
        support["year"].eq("ALL")
        & support["status"].isin({"incomplete_statics", "invalid_statics"})
    ]
    invalid_swaps = int(invalid["swaps"].sum())
    if invalid_swaps:
        statuses = ", ".join(
            f"{row.status}={int(row.swaps):,}"
            for row in invalid.itertuples(index=False)
        )
        raise RuntimeError(
            f"v4 support audit found {invalid_swaps:,} swaps with unusable statics: "
            f"{statuses}"
        )
    write_exhibit(
        support,
        V4_OUT,
        code_sources=["src/ddvc/fetch/raw.py"],
        inputs=[V4_RAW],
    )
    supported = support[(support["year"] == "ALL") & support["supported"]]
    swap_share = float(supported.iloc[0]["swap_share"]) if not supported.empty else 0.0
    volume_share = float(supported.iloc[0]["volume_share"]) if not supported.empty else 0.0
    print(
        f"v4 vanilla-static support: {swap_share:.1%} of swaps, "
        f"{volume_share:.1%} of reported volume"
    )
    print(f"wrote {V4_OUT.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--v4-only", action="store_true")
    args = ap.parse_args()

    if args.v4_only:
        write_v4_support()
        return 0

    days = sorted(p.name[len("uniswap_v2_swaps_"):-len(".jsonl.gz")]
                  for p in RAW.glob("uniswap_v2_swaps_*.jsonl.gz"))
    step = max(1, len(days) // args.days)
    picked = days[::step][: args.days]
    print(f"measuring the validation support on {len(picked)} days: "
          f"{picked[0]}..{picked[-1]}\n")

    rows = []
    pooled: list[float] = []
    for day in picked:
        rs = measure_day(day)
        if not rs:
            print(f"  {day}: no matchable swaps")
            continue
        rs.sort()
        pooled.extend(rs)
        q = lambda f: rs[min(len(rs) - 1, int(f * len(rs)))]  # noqa: E731
        rows.append({"day": day, "n": len(rs), "median": q(0.50),
                     "p90": q(0.90), "p99": q(0.99), "p999": q(0.999), "max": rs[-1]})
        r = rows[-1]
        print(f"  {day}: n={r['n']:>7,}  median {r['median']:.2e}  p90 {r['p90']:.2e}  "
              f"p99 {r['p99']:.2e}  p99.9 {r['p999']:.2e}  max {r['max']:.2e}")

    if not pooled:
        print("nothing measurable")
        return 1
    pooled.sort()
    q = lambda f: pooled[min(len(pooled) - 1, int(f * len(pooled)))]  # noqa: E731
    print(f"\npooled over {len(pooled):,} realised swaps that clear the physical bound, "
          f"size as a fraction of the input-side reserve:")
    for f in (0.5, 0.9, 0.95, 0.99, 0.999):
        print(f"  {f:>6.1%} of realised trades are below {q(f):.4f} of the reserve")
    print(f"  maximum observed {pooled[-1]:.4f}")

    print("\nReading. A constant-product quote for a trade at fraction x of the input")
    print("reserve moves the price by roughly x, so the tail of this distribution is")
    print("where the quoter stops being tested. A panel that quotes routes far beyond")
    print("the 99.9th percentile of what traders actually did is extrapolating, and the")
    print("arbitrage bound says that is where the impossible gaps come from.")
    print(f"\nRECOMMENDED SUPPORT BOUND: decline to quote a leg whose input amount")
    print(f"exceeds {q(0.999):.4f} of that pool's input-side reserve, the 99.9th")
    print(f"percentile of realised behaviour. That keeps essentially every trade anyone")
    print(f"actually made while refusing to price routes nobody would take.")

    write_exhibit(pd.DataFrame(rows + [{"day": "POOLED", "n": len(pooled),
                                        "median": q(0.5), "p90": q(0.9), "p99": q(0.99),
                                        "p999": q(0.999), "max": pooled[-1]}]), OUT, inputs=[RAW])
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)}")
    write_v4_support()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
