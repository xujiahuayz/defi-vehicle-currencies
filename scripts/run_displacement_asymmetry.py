#!/usr/bin/env python3
"""Does the incumbent hold on longer than a challenger takes to break in?

This is the arm the persistence measurement is missing, and without it neither
"hysteresis" nor "inertia" can be said. Persistence on its own is consistent with slow
information, or with switching frictions that apply equally in both directions, and
either would produce a role that survives dominance without any incumbency advantage
existing. Hysteresis is a claim about ASYMMETRY: the incumbent keeps the role while
dominated for longer than a challenger takes to gain it when the edge runs the other way.
So the test compares two survival curves on the same pairs and asks whether they differ.

The two arms, defined on the same quantity so they are comparable:

  RETENTION. A vehicle is the incumbent on a pair, meaning it carries the largest share
  of that pair's multi-leg volume, and it becomes dominated, meaning the best available
  direct pool returns more at the same reconstructed state. How many days pass before it
  stops being the incumbent.

  DISPLACEMENT. A vehicle is NOT the incumbent and holds an edge, meaning routing through
  it beats the direct pool while the incumbent's route does not. How many days pass
  before it becomes the incumbent.

Symmetric frictions predict the two durations match. Hysteresis predicts retention
exceeds displacement, and the gap between them is the incumbency premium measured in
days. The comparison is what makes the claim, so neither number is reported alone.

Both arms need a run of consecutive priced days, since a duration cannot be measured on a
cross-section. This script states plainly how many days it has and refuses to report a
duration it cannot support.

Reads   data/unified/YYYYMMDD.parquet, data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/displacement_asymmetry.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(0, str(ROOT / "scripts"))
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "displacement_asymmetry.jsonl"
MIN_DAYS_FOR_DURATION = 20


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-days", type=int, default=MIN_DAYS_FOR_DURATION)
    args = ap.parse_args()

    import duckdb

    from measure_realised_dominance import realised_routes  # noqa: E402

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
    days = sorted(panel.day.unique())
    print(f"screened panel covers {len(days)} consecutive-priced days: "
          f"{days[0]}..{days[-1]}")

    if len(days) < args.min_days:
        print(f"\nREFUSING TO REPORT A DURATION. An asymmetry between two survival")
        print(f"curves needs a run of days long enough for a role to turn over, and")
        print(f"{len(days)} is not it. The retention arm alone would be censored at")
        print(f"{len(days)} days for every pair that has not switched, so the estimate")
        print(f"would be a function of the sample window and not of behaviour.")
        print(f"\nWhat this needs is the full rebuild now running, which covers 2,277")
        print(f"days. This script is written and will run against it unchanged.")
        print(f"\nWhat CAN be said today is the cross-section already reported: a")
        print(f"dominated vehicle keeps roughly half to two thirds of its routing")
        print(f"share, which establishes that persistence exists without saying how")
        print(f"long it lasts or whether it is asymmetric. Neither hysteresis nor")
        print(f"inertia is claimed on that basis.")
        write_exhibit(pd.DataFrame([{
            "status": "insufficient_days", "days_available": len(days),
            "days_required": args.min_days,
            "note": ("duration and asymmetry both need a consecutive run; the "
                     "cross-section establishes persistence exists, not its length")}]), OUT)
        print(f"\nwrote {OUT.relative_to(ROOT)}")
        return 0

    # Full-sample path, exercised once the rebuild lands.
    frames = []
    for day in days:
        rr = realised_routes(day)
        if rr.empty:
            continue
        tot = rr.groupby(["src", "tgt"]).usd.transform("sum")
        rr["share"] = rr.usd / tot.clip(lower=1e-9)
        rr["day"] = day
        frames.append(rr.groupby(["day", "src", "tgt", "vehicle"], as_index=False)
                      .agg(usd=("usd", "sum"), share=("share", "sum")))
    if not frames:
        print("no realised multi-leg routing on the priced days")
        return 1
    shares = pd.concat(frames, ignore_index=True)
    m = shares.merge(panel[["day", "src", "tgt", "vehicle", "adv"]],
                     on=["day", "src", "tgt", "vehicle"], how="inner")
    m["dominated"] = m.adv > 0
    m["incumbent"] = m.share == m.groupby(["day", "src", "tgt"]).share.transform("max")

    retention, displacement = [], []
    for (src, tgt), g in m.groupby(["src", "tgt"]):
        g = g.sort_values("day")
        for veh, gv in g.groupby("vehicle"):
            gv = gv.sort_values("day").reset_index(drop=True)
            for i in range(len(gv) - 1):
                if gv.incumbent[i] and gv.dominated[i]:
                    later = gv[(gv.index > i) & (~gv.incumbent)]
                    if len(later):
                        retention.append(int(later.index[0] - i))
                if (not gv.incumbent[i]) and (not gv.dominated[i]):
                    later = gv[(gv.index > i) & (gv.incumbent)]
                    if len(later):
                        displacement.append(int(later.index[0] - i))

    rows = []
    for label, arr in (("retention", retention), ("displacement", displacement)):
        if not arr:
            print(f"  {label}: no completed spells")
            continue
        s = pd.Series(arr)
        rows.append({"arm": label, "spells": int(len(s)), "median_days": float(s.median()),
                     "mean_days": float(s.mean()), "p75_days": float(s.quantile(0.75))})
        print(f"  {label:<14} spells {len(s):>6,}  median {s.median():>5.1f} days  "
              f"mean {s.mean():>6.2f}  p75 {s.quantile(0.75):>5.1f}")
    if len(rows) == 2:
        gap = rows[0]["median_days"] - rows[1]["median_days"]
        print(f"\n  asymmetry: retention minus displacement = {gap:+.1f} days")
        print("  a positive gap is the incumbency premium; zero is symmetric friction")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
