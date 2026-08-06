#!/usr/bin/env python3
"""Do cost-dominance windows survive the support screen?

This is the claim the paper rests on. The FX inertia literature's stated limit is that an
incumbent's cost advantage is a consequence of its incumbency, so the data never contain
the state in which a currency holds the vehicle role while being strictly cost-dominated.
This project reported that state as observable and common, 17.9% of intermediated routes
gross of gas and 30.0% all-in, and that figure is the reason the paper has an edge over
the FX literature at all.

It was measured before any of the corrections that followed: on the v2-only panel, with
no support restriction, when 44.5% to 82.0% of gaps implied an arbitrage cycle that pays
and the median gap at a 100,000 dollar trade was 4,655 basis points. The support screen
removes 70% to 86% of quotable routes and cuts median gaps to tens of basis points, so
the frequency has to be re-measured rather than carried forward.

Dominance here means the best available DIRECT route returns more than the best two-leg
route through the candidate, at the same reconstructed state, so it is the state in which
routing through an intermediary is strictly worse than not doing so. Reported by
candidate type, because the question is whether the INCUMBENT holds the role while
dominated, and reported with the surviving sample characterised, because a frequency
measured on 14% of the original routes is a different object unless the survivors look
like the population.

Writes  output/exhibits/dominance_windows_screened.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "dominance_windows_screened.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gas-bps", type=float, default=None,
                    help="flat all-in gas charge in bps; default derives it per size")
    args = ap.parse_args()

    import duckdb

    con = duckdb.connect()
    d = con.execute(f"""
        SELECT CAST(date AS DATE) AS d, trade_size_usd, vehicle,
               direct_cost_advantage AS adv, direct_source, hop1_source
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
    """).df()
    con.close()
    if d.empty:
        print("no comparable routes")
        return 1

    d["mid_type"] = d.vehicle.map({v: classify(v)[1] for v in d.vehicle.unique()})
    d["year"] = pd.to_datetime(d.d).dt.year
    # Gross dominance: the direct route simply returns more.
    d["dominated_gross"] = (d.adv > 0).astype(float)
    # All-in: the vehicle route pays one extra hop of gas, so it must beat the direct
    # route by more than that hop costs as a share of notional. Receipt-measured at
    # 74,096 extra units; the bps charge falls as 1/size because gas is fixed per route.
    gas_bps = d.trade_size_usd.map(lambda s: (args.gas_bps if args.gas_bps is not None
                                              else 74_096 * 13.67e-9 * 2500 * 10_000 / s))
    d["dominated_allin"] = (d.adv > -gas_bps / 10_000).astype(float)

    print(f"{len(d):,} routes on the screened panel, {d.year.min()}-{d.year.max()}\n")
    print(f"  {'candidate type':<14}{'routes':>10}{'dominated gross':>18}{'all-in':>10}")
    rows = []
    for t, g in d.groupby("mid_type"):
        rows.append({"scope": f"type:{t}", "routes": int(len(g)),
                     "dominated_gross": float(g.dominated_gross.mean()),
                     "dominated_allin": float(g.dominated_allin.mean())})
        print(f"  {t:<14}{len(g):>10,}{g.dominated_gross.mean():>17.1%}"
              f"{g.dominated_allin.mean():>10.1%}")
    rows.append({"scope": "ALL", "routes": int(len(d)),
                 "dominated_gross": float(d.dominated_gross.mean()),
                 "dominated_allin": float(d.dominated_allin.mean())})
    print(f"  {'ALL':<14}{len(d):>10,}{d.dominated_gross.mean():>17.1%}"
          f"{d.dominated_allin.mean():>10.1%}")
    print(f"\n  the pre-screen figures this replaces were 17.9% gross and 30.0% all-in")

    print(f"\n  {'trade size':>12}{'routes':>10}{'gross':>10}{'all-in':>10}")
    for s, g in d.groupby("trade_size_usd"):
        rows.append({"scope": f"size:{int(s)}", "routes": int(len(g)),
                     "dominated_gross": float(g.dominated_gross.mean()),
                     "dominated_allin": float(g.dominated_allin.mean())})
        print(f"  ${int(s):>11,}{len(g):>10,}{g.dominated_gross.mean():>9.1%}"
              f"{g.dominated_allin.mean():>10.1%}")

    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
