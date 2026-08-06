#!/usr/bin/env python3
"""How long does the vehicle role survive once it stops being the cheapest route?

This is the estimand Node I proposed after rejecting the level comparison, and it is the
one this project's data can answer where FX data cannot. The FX inertia literature's
stated limit is that an incumbent's cost advantage is a consequence of its incumbency, so
the counterfactual is never observed. Here it is: 41.3% of realised multi-leg routes were
strictly dominated by an available direct pool at the state they executed in.

That frequency is a fact about a moment. The question with economic content is what
happens NEXT. If routing leaves the incumbent the instant it stops being cheapest, the
role is a pure cost-minimisation outcome and there is no incumbency to speak of. If
routing persists through dominance, the duration of that persistence is the object the
inertia literature has always wanted and never had, and it is priced in two units a
referee can hold: dollars foregone by continuing, and days until the role turns over.

The asymmetry is what separates hysteresis from persistence, and it is why the design
needs both directions. Persistence alone is consistent with slow information or with
switching frictions that apply equally in both directions. Hysteresis means the incumbent
keeps the role while dominated for LONGER than a challenger takes to gain it when the
edge runs the other way. So the test is not whether persistence exists but whether the
survival curve differs by direction of the edge, and that comparison needs both arms
measured on the same pairs.

WHAT THIS SCRIPT DOES NOT YET DO, stated because a partial design should not read as a
complete one. It measures the persistence side on the pairs the screened panel covers. It
does not yet run the displacement arm, because that requires identifying the moment a
challenger's edge opens on a pair the incumbent still holds, and the panel's fixed-size
grid makes edge-opening dates coarse. It also inherits the matched-sample selection from
the realised-dominance measurement, where 1,762 of roughly 90,000 realised routes matched.

Reads   data/unified/YYYYMMDD.parquet, data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/survival_after_dominance.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from ddvc.asset_types import classify
from ddvc.realised import realised_routes
from ddvc.tables import write_exhibit

UNIFIED = ROOT / "data" / "unified"
PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "survival_after_dominance.jsonl"


def realised_shares(day: str) -> pd.DataFrame:
    """Share of each pair's multi-leg volume routed through each interior token."""
    routes = realised_routes(day, UNIFIED)
    if routes.empty:
        return pd.DataFrame()
    totals = routes.groupby(["src", "tgt"]).usd.transform("sum")
    routes["share"] = routes.usd / totals.clip(lower=1e-9)
    return routes.groupby(["day", "src", "tgt", "vehicle"], as_index=False).agg(
        usd=("usd", "sum"), share=("share", "sum"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-days", type=int, default=40)
    args = ap.parse_args()

    import duckdb

    con = duckdb.connect()
    panel = con.execute(f"""
        SELECT CAST(date AS DATE) AS d, src, tgt, vehicle,
               avg(direct_cost_advantage) AS adv
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
        GROUP BY 1,2,3,4
    """).df()
    con.close()
    if panel.empty:
        print("no screened counterfactual costs")
        return 1
    panel["day"] = pd.to_datetime(panel.d).dt.strftime("%Y%m%d")
    days = sorted(panel.day.unique())[: args.max_days]
    print(f"screened panel covers {len(days)} days: {days[0]}..{days[-1]}")
    if len(days) < 5:
        print("\nToo few priced days for an event-time design. The persistence question")
        print("needs a run of consecutive days so a role can be watched turning over,")
        print("and this measures nothing until the full rebuild lands. Reporting the")
        print("cross-section it CAN support instead of a survival curve it cannot.")

    shares = pd.concat([realised_shares(d) for d in days], ignore_index=True) \
        if days else pd.DataFrame()
    if shares.empty:
        print("no realised multi-leg routing on the priced days")
        return 1

    m = shares.merge(panel[["day", "src", "tgt", "vehicle", "adv"]],
                     on=["day", "src", "tgt", "vehicle"], how="inner")
    if m.empty:
        print("no realised route matched a priced counterfactual")
        return 1
    m["mid_type"] = m.vehicle.map({v: classify(v)[1] for v in m.vehicle.unique()})
    m["dominated"] = m.adv > 0

    print(f"\n{len(m):,} pair-day-vehicle observations where a realised route matched "
          f"a priced counterfactual\n")
    print("  Share of a pair's multi-leg volume still routed through a vehicle,")
    print("  split by whether that vehicle was dominated that day:")
    print(f"  {'candidate':<12}{'dominated':>11}{'obs':>8}{'mean share':>12}{'median':>9}")
    rows = []
    for (t, dom), g in m.groupby(["mid_type", "dominated"]):
        rows.append({"mid_type": t, "dominated": bool(dom), "obs": int(len(g)),
                     "mean_share": float(g.share.mean()),
                     "median_share": float(g.share.median()),
                     "usd": float(g.usd.sum())})
        print(f"  {t:<12}{str(bool(dom)):>11}{len(g):>8,}{g.share.mean():>12.1%}"
              f"{g.share.median():>9.1%}")

    print("\n  Dollars still routed through a DOMINATED vehicle, which is the foregone")
    print("  amount the persistence question prices:")
    for t, g in m[m.dominated].groupby("mid_type"):
        print(f"    {t:<12} ${g.usd.sum():>14,.0f} across {len(g):,} pair-days")

    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
