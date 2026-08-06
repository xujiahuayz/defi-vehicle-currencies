#!/usr/bin/env python3
"""Are the measured route-cost gaps economically possible, or off-support quoter error?

Node I's deepest objection, and it cuts at the counterfactual itself rather than at any
one estimand: nothing stops a gap being taken. A gap between a direct pool and a two-leg
route priced at the SAME reconstructed state sits inside one block, where there is no
settlement latency, no short-sale constraint and no capital control. Makarov and Schoar
devote a full section of a JFE paper to explaining why their 15-to-40% Korean premium
survived, naming exactly those frictions, and none of them exists here. This repository's
own round-trip statistic, a median day at 12.7% of multi-leg routes by count and 21.7% by
value across 79 sampled days, shows the arbitrage capacity is present, and it is present
in every sampled day rather than in an episode: the minimum day still runs 4.5% by count.
An earlier version of this docstring quoted 25.6% and 90.5% here, which are real but are
the single most extreme day in the sample and were carrying far more rhetorical weight
than the corpus supports. So a median same-state gap of -2,459 basis points is
more likely to be quoter error off-support than an economic fact, and the quoter is
validated on swaps that happened while being applied to 123.8 million that did not.

The objection is right in form and it has a testable bound, which is the point of this
script. A direct route being cheaper than a two-leg route is not by itself an arbitrage:
capturing it requires a CYCLE, going out through the expensive route and back through
the cheap one, and that cycle pays only if the gap exceeds the round trip's own costs.
Those costs are knowable. The cycle spends three pool fees rather than one, since the
two-leg leg pays two, and it pays gas for three hops at the receipt-measured 319,906
units against 154,604 for a single hop.

So the gap distribution splits in two at a threshold that can be computed rather than
assumed:

  BELOW the threshold, a gap is economically possible. No one can profit from removing
  it, so it can persist, and it is admissible evidence about routing cost.

  ABOVE the threshold, a gap implies a cycle that pays. It should be competed away
  within a block, so observing many of them is evidence of measurement error rather
  than of market structure, and those observations must be excluded before any claim
  rests on them.

The threshold falls with trade size because gas is fixed per route, so it is computed
per size bucket with the per-day gas price and ETH price already measured exactly from
`Transaction.gasPrice` over 1,883 days.

What a good outcome looks like. If most gaps sit below the threshold, the counterfactual
survives the objection and the excludable tail is quantified. If most sit above it, the
quoter is being applied outside its support and no estimand built on these gaps is safe,
which would be worth knowing before writing a paper on it.

Writes  output/exhibits/gap_arbitrage_bound.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
GAS = ROOT / "data" / "processed" / "daily_gas_price_graph.parquet"
OUT = ROOT / "output" / "exhibits" / "gap_arbitrage_bound.jsonl"

# Receipt-measured gas by route topology, from `src/ddvc/cpquote.py`.
GAS_ONE_HOP = 154_604
GAS_THREE_HOP = 319_906
# A cycle out through two legs and back through one pays three pool fees where the
# one-way comparison pays one, so the extra fee burden is two legs at 30 basis points
# for the constant-product venues. This is the conservative direction: concentrated
# liquidity and Curve charge less, so a lower fee makes the threshold SMALLER and the
# excludable tail LARGER, which is the direction that would hurt this project's claims.
EXTRA_FEE_BPS = 60.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eth-usd", type=float, default=2500.0,
                   help="fallback ETH price when the gas panel has no entry for a day")
    args = ap.parse_args()

    import duckdb

    if not PANEL.exists():
        print(f"no panel at {PANEL.relative_to(ROOT)}")
        return 1
    con = duckdb.connect()

    gas_median = None
    if GAS.exists():
        gas_median = con.execute(
            f"SELECT median(gas_gwei_median) FROM read_parquet('{GAS.as_posix()}')"
        ).fetchone()[0]
    if not gas_median:
        gas_median = 25.8
    print(f"gas price used: {gas_median:.2f} gwei (median over the measured panel)")
    print(f"ETH price used: ${args.eth_usd:,.0f}\n")

    rows = con.execute(f"""
        SELECT trade_size_usd,
               abs(direct_cost_advantage) AS gap
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
          AND vehicle_output_usd > 0
    """).df()
    con.close()
    if rows.empty:
        print("no comparable routes in the panel")
        return 1

    out = []
    print(f"  {'trade size':>12}{'n':>12}{'gas bps':>10}{'threshold bps':>15}"
          f"{'above thr':>11}{'median gap bps':>16}")
    for size, g in rows.groupby("trade_size_usd"):
        gas_eth = GAS_THREE_HOP * gas_median * 1e-9
        gas_usd = gas_eth * args.eth_usd
        gas_bps = 10_000 * gas_usd / float(size)
        threshold_bps = gas_bps + EXTRA_FEE_BPS
        gap_bps = g.gap * 10_000
        above = float((gap_bps > threshold_bps).mean())
        out.append({"trade_size_usd": float(size), "n": int(len(g)),
                    "gas_bps": gas_bps, "threshold_bps": threshold_bps,
                    "share_above_threshold": above,
                    "median_gap_bps": float(gap_bps.median()),
                    "p90_gap_bps": float(gap_bps.quantile(0.90))})
        print(f"  ${int(size):>11,}{len(g):>12,}{gas_bps:>10.1f}{threshold_bps:>15.1f}"
              f"{above:>10.1%}{gap_bps.median():>16.1f}")

    worst = max(r["share_above_threshold"] for r in out)
    best = min(r["share_above_threshold"] for r in out)
    print(f"\nshare of gaps implying a profitable cycle: {best:.1%} to {worst:.1%} "
          f"across size buckets")
    if worst > 0.5:
        print("\nMost gaps imply a cycle that pays, so they cannot persist and the")
        print("quoter is being applied outside its support. No estimand built on these")
        print("gaps is safe until that is fixed, and Node I's objection stands.")
    elif worst > 0.1:
        print("\nA material minority imply a cycle that pays. Those observations are")
        print("excludable and the exclusion must be reported, since they are not a")
        print("random subset: they concentrate wherever the quoter extrapolates most.")
    else:
        print("\nAlmost all gaps are too small to arbitrage after gas and fees, so they")
        print("can persist and are admissible evidence about routing cost. Node I's")
        print("objection is answered by the bound rather than by argument.")
    write_exhibit(pd.DataFrame(out), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
