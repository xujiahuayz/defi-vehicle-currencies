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
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import classify
from ddvc.realised import (
    cost_panel_days,
    match_realised_to_cost_panel,
    read_cost_panel_day,
    realised_routes,
)
from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[1]

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "matched_sample_characterisation.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    import duckdb

    with TemporaryDirectory(prefix="ddvc-matched-sample-") as temporary:
        con = duckdb.connect()
        written = 0
        try:
            days = cost_panel_days(con, PANEL)
            if not days:
                print("no screened counterfactual costs")
                return 1
            for day in days:
                rr = realised_routes(day)
                if rr.empty:
                    continue
                matched = match_realised_to_cost_panel(
                    rr, read_cost_panel_day(con, PANEL, day)
                )
                matched["matched"] = matched["match_status"].eq("chosen_with_direct")
                matched["mid_type"] = matched.vehicle.map(
                    {value: classify(value)[1] for value in matched.vehicle.unique()}
                )
                matched[["matched", "usd", "mid_type", "src", "tgt"]].to_parquet(
                    Path(temporary) / f"{day}.parquet", index=False
                )
                written += len(matched)
            if not written:
                print("no realised routes on priced days")
                return 1
            glob = (Path(temporary) / "*.parquet").as_posix()
            counts = con.execute(
                f"SELECT CAST(matched AS BOOLEAN) matched, count(*) n FROM read_parquet('{glob}') GROUP BY 1"
            ).df()
            stats = con.execute(
                f"""
                SELECT CAST(matched AS BOOLEAN) matched, median(usd) median_usd,
                       avg(usd) mean_usd, quantile_cont(usd, 0.9) p90_usd
                FROM read_parquet('{glob}') GROUP BY 1
                """
            ).df()
            shares = con.execute(
                f"""
                SELECT CAST(matched AS BOOLEAN) matched, mid_type,
                       count(*)::DOUBLE / sum(count(*)) OVER (PARTITION BY matched) share
                FROM read_parquet('{glob}') GROUP BY 1, 2
                """
            ).df()
            pair_stats = con.execute(
                f"""
                WITH pair_counts AS (
                    SELECT CAST(matched AS BOOLEAN) matched, src, tgt, count(*) routes
                    FROM read_parquet('{glob}') GROUP BY 1, 2, 3
                )
                SELECT matched, count(*) distinct_pairs, avg(routes) routes_per_pair
                FROM pair_counts GROUP BY 1
                """
            ).df()
        finally:
            con.close()

    by_match = counts.set_index("matched")["n"].to_dict()
    total = int(sum(by_match.values()))
    n_m = int(by_match.get(True, 0))
    print(f"{total:,} realised vehicle routes on {len(days)} priced days")
    print(f"  exact-hour chosen-with-direct matches: {n_m:,} ({n_m/total:.1%})\n")

    rows = []
    print(f"  {'attribute':<30}{'matched':>14}{'unmatched':>14}{'ratio':>9}")

    def line(label: str, mv: float, uv: float) -> None:
        rows.append({"attribute": label, "matched": mv, "unmatched": uv,
                     "ratio": (mv / uv) if uv else float("nan")})
        r = (mv / uv) if uv else float("nan")
        print(f"  {label:<30}{mv:>14,.2f}{uv:>14,.2f}{r:>9.2f}")

    by_stats = stats.set_index("matched")
    def statistic(matched: bool, column: str) -> float:
        return float(by_stats.loc[matched, column]) if matched in by_stats.index else float("nan")

    line("median trade USD", statistic(True, "median_usd"), statistic(False, "median_usd"))
    line("mean trade USD", statistic(True, "mean_usd"), statistic(False, "mean_usd"))
    line("p90 trade USD", statistic(True, "p90_usd"), statistic(False, "p90_usd"))

    print(f"\n  {'vehicle type':<30}{'matched %':>14}{'unmatched %':>14}")
    share_map = shares.set_index(["matched", "mid_type"])["share"].to_dict()
    for t in sorted(shares.mid_type.unique()):
        mv = float(share_map.get((True, t), 0.0))
        uv = float(share_map.get((False, t), 0.0))
        rows.append({"attribute": f"share {t}", "matched": mv, "unmatched": uv,
                     "ratio": (mv / uv) if uv else float("nan")})
        print(f"  {t:<30}{mv:>13.1%}{uv:>14.1%}")

    by_pair = pair_stats.set_index("matched")
    matched_pairs = int(by_pair.loc[True, "distinct_pairs"]) if True in by_pair.index else 0
    unmatched_pairs = int(by_pair.loc[False, "distinct_pairs"]) if False in by_pair.index else 0
    matched_rpp = float(by_pair.loc[True, "routes_per_pair"]) if True in by_pair.index else float("nan")
    unmatched_rpp = float(by_pair.loc[False, "routes_per_pair"]) if False in by_pair.index else float("nan")
    print(f"\n  distinct pairs: matched {matched_pairs:,}, unmatched {unmatched_pairs:,}")
    print(f"  routes per pair: matched {matched_rpp:.1f}, unmatched {unmatched_rpp:.1f}")
    rows.append({"attribute": "routes per pair", "matched": matched_rpp,
                 "unmatched": unmatched_rpp,
                 "ratio": matched_rpp / unmatched_rpp if unmatched_rpp else float("nan")})

    print("\nReading. The matched set is the busiest pairs at near-grid notionals with")
    print("legs inside the support, so it is not a random 2%. Any ratio far from 1")
    print("names an attribute on which the chosen-with-direct estimate cannot be generalised")
    print("without a design correction; the outcome is unobservable on the unmatched side")
    print("because the counterfactual is exactly what is missing there.")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
