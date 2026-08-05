#!/usr/bin/env python3
"""Is the 41.3% dominance figure measured on a sample that looks like the population?

The paper's foundational claim is that 41.3% of realised multi-leg routes were strictly
dominated at the state they executed in, which is the state FX data can never contain.
That figure rests on 1,762 matched routes out of roughly 90,000 realised ones, so it is
measured on about 2% of the population and the selection is not random by construction.
Three things drive it: the panel prices the 200 most heavily bridged pairs per day, it
prices three fixed notionals, and the support screen refuses legs whose own price impact
exceeds 5%.

Each of those pushes in a knowable direction and the directions do not agree, so the net
sign has to be measured. Pricing only the busiest pairs selects toward pairs with deep
pools and many candidates, where a direct alternative is more likely to exist and to be
good, which should RAISE measured dominance. The support screen removes legs through thin
pools, which are the legs most likely to be dominated, which should LOWER it. The fixed
notional grid selects toward trades near those sizes and away from the long tail.

So this compares matched against unmatched realised routes on the attributes that are
observable for both, and reports whether the matched set is representative on each. What
it cannot do is verify the outcome on unmatched routes, since the counterfactual is
exactly what is missing there, so the conclusion is about representativeness on
covariates and is stated that way.

Reads   data/unified/YYYYMMDD.parquet, data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/matched_sample_characterisation.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "matched_sample_characterisation.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    import duckdb

    from measure_realised_dominance import realised_routes

    con = duckdb.connect()
    panel = con.execute(f"""
        SELECT DISTINCT CAST(date AS DATE) AS d, src, tgt, vehicle
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
    """).df()
    con.close()
    if panel.empty:
        print("no screened counterfactual costs")
        return 1
    panel["day"] = pd.to_datetime(panel.d).dt.strftime("%Y%m%d")
    days = sorted(panel.day.unique())

    all_rr = []
    for day in days:
        rr = realised_routes(day)
        if rr.empty:
            continue
        rr["day"] = day
        all_rr.append(rr)
    if not all_rr:
        print("no realised routes on priced days")
        return 1
    rr = pd.concat(all_rr, ignore_index=True)

    key = set(map(tuple, panel[["day", "src", "tgt", "vehicle"]].values))
    rr["matched"] = [tuple(x) in key for x in
                     rr[["day", "src", "tgt", "vehicle"]].values]
    rr["mid_type"] = rr.vehicle.map({v: classify(v)[1] for v in rr.vehicle.unique()})
    rr["log_usd"] = np.log(rr.usd.clip(lower=1))

    n_m = int(rr.matched.sum())
    print(f"{len(rr):,} realised multi-leg route-legs on {len(days)} priced days")
    print(f"  matched to a screened counterfactual: {n_m:,} ({n_m/len(rr):.1%})\n")

    rows = []
    print(f"  {'attribute':<30}{'matched':>14}{'unmatched':>14}{'ratio':>9}")

    def line(label: str, mv: float, uv: float) -> None:
        rows.append({"attribute": label, "matched": mv, "unmatched": uv,
                     "ratio": (mv / uv) if uv else float("nan")})
        r = (mv / uv) if uv else float("nan")
        print(f"  {label:<30}{mv:>14,.2f}{uv:>14,.2f}{r:>9.2f}")

    m, u = rr[rr.matched], rr[~rr.matched]
    line("median trade USD", float(m.usd.median()), float(u.usd.median()))
    line("mean trade USD", float(m.usd.mean()), float(u.usd.mean()))
    line("p90 trade USD", float(m.usd.quantile(0.9)), float(u.usd.quantile(0.9)))

    print(f"\n  {'vehicle type':<30}{'matched %':>14}{'unmatched %':>14}")
    for t in sorted(rr.mid_type.unique()):
        mv = float((m.mid_type == t).mean()) if len(m) else 0.0
        uv = float((u.mid_type == t).mean()) if len(u) else 0.0
        rows.append({"attribute": f"share {t}", "matched": mv, "unmatched": uv,
                     "ratio": (mv / uv) if uv else float("nan")})
        print(f"  {t:<30}{mv:>13.1%}{uv:>14.1%}")

    mp = m.groupby(["src", "tgt"]).size()
    up = u.groupby(["src", "tgt"]).size()
    print(f"\n  distinct pairs: matched {len(mp):,}, unmatched {len(up):,}")
    print(f"  routes per pair: matched {mp.mean():.1f}, unmatched {up.mean():.1f}")
    rows.append({"attribute": "routes per pair", "matched": float(mp.mean()),
                 "unmatched": float(up.mean()),
                 "ratio": float(mp.mean() / up.mean()) if len(up) else float("nan")})

    print("\nReading. The matched set is the busiest pairs at near-grid notionals with")
    print("legs inside the support, so it is not a random 2%. Any ratio far from 1")
    print("names an attribute on which the 41.3% figure cannot be generalised without")
    print("reweighting, and the outcome itself is unobservable on the unmatched side")
    print("because the counterfactual is exactly what is missing there.")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
