#!/usr/bin/env python3
"""When a trader ACTUALLY routed through an intermediary, was that route dominated?

This is the paper's foundational claim and the previous measurement of it answered a
different question. The FX inertia literature's stated limit is that an incumbent's cost
advantage is a consequence of its incumbency, so FX data never contain the state in which
a currency HOLDS the vehicle role while being strictly cost-dominated. Holding the role
means being used. Enumerating every candidate a router could have chosen and asking how
often a direct pool beats it answers a different and much easier question, and it returns
70.1% because most enumerated two-hop routes are ones nobody took.

So the measurement joins realised routing to counterfactual cost. For each multi-leg swap
that actually happened, identify the interior token it went through, then ask whether the
best direct pool at that same reconstructed state would have returned more. A yes is the
state the FX literature cannot observe: the incumbent was used while strictly worse.

Round trips are excluded, since a route whose first input equals its last output is
atomic arbitrage or a wash trade and moved no value, and this project has already been
inverted once by leaving them in, where they were 25.6% of multi-leg routes by count and
90.5% by value.

Reads   data/unified/YYYYMMDD.parquet          realised routes
        data/empirical/route_cost_panel_v2.parquet   counterfactual costs
Writes  output/exhibits/realised_dominance.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "realised_dominance.jsonl"


def realised_routes(day: str) -> pd.DataFrame:
    """Multi-leg routes that actually executed, with their interior token."""
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p, columns=["tx_hash", "component_id", "token_in", "token_out",
                                    "amount_usd", "log_index", "route_class"])
    d = d[d.route_class.isin(["single", "coherent"])]
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    out = []
    for (_tx, _c), g in d.groupby(["tx_hash", "component_id"], sort=False):
        if len(g) < 2:
            continue
        tin = g.token_in.tolist()
        tout = g.token_out.tolist()
        if tin[0] == tout[-1]:
            continue                      # round trip: no value moved
        for interior in {t for t in tout[:-1] if t}:
            out.append({"src": tin[0], "tgt": tout[-1], "vehicle": interior,
                        "usd": float(g.amount_usd.max())})
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=6)
    args = ap.parse_args()

    import duckdb

    con = duckdb.connect()
    panel = con.execute(f"""
        SELECT CAST(date AS DATE) AS d, src, tgt, vehicle, trade_size_usd,
               direct_cost_advantage AS adv
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
    """).df()
    con.close()
    if panel.empty:
        print("no screened counterfactual costs available")
        return 1
    # Format explicitly. Taking str() of a date column yields "2023-06-01 00:00:00",
    # so stripping hyphens leaves a time component and every unified-file lookup missed.
    panel["daystr"] = pd.to_datetime(panel.d).dt.strftime("%Y%m%d")
    days = sorted(panel.daystr.unique())
    print(f"screened panel covers {len(days)} days: {days[0]}..{days[-1]}")

    rows = []
    all_matched, all_pop = [], []
    for day in days[: args.days]:
        rr = realised_routes(day)
        if rr.empty:
            continue
        all_pop.append(rr)
        pk = panel[panel.daystr == day]
        # Match each realised route to the counterfactual at the nearest quoted size,
        # since the panel prices fixed notionals and realised trades are continuous.
        merged = rr.merge(pk[["src", "tgt", "vehicle", "trade_size_usd", "adv"]],
                          on=["src", "tgt", "vehicle"], how="inner")
        if merged.empty:
            continue
        merged["size_gap"] = (merged.trade_size_usd - merged.usd).abs()
        merged = merged.sort_values("size_gap").drop_duplicates(
            subset=["src", "tgt", "vehicle", "usd"], keep="first")
        merged["mid_type"] = merged.vehicle.map(
            {v: classify(v)[1] for v in merged.vehicle.unique()})
        merged["dominated"] = (merged.adv > 0).astype(float)
        all_matched.append(merged)
        rows.append({"day": day, "realised_multileg": int(len(rr)),
                     "matched": int(len(merged)),
                     "dominated": float(merged.dominated.mean()),
                     "value_weighted": float(
                         (merged.dominated * merged.usd).sum() / max(merged.usd.sum(), 1))})
        r = rows[-1]
        print(f"  {day}: {r['realised_multileg']:>7,} realised multi-leg routes, "
              f"{r['matched']:>6,} matched to a counterfactual | "
              f"dominated {r['dominated']:>6.1%} by count, "
              f"{r['value_weighted']:>6.1%} by value")

    if not rows:
        print("\nNo realised route matched a screened counterfactual. That is itself the")
        print("finding to chase: the support screen may be removing exactly the routes")
        print("traders used, which would make the screened panel unrepresentative.")
        return 1
    tot_m = sum(r["matched"] for r in rows)
    w = sum(r["dominated"] * r["matched"] for r in rows) / max(tot_m, 1)
    print(f"\npooled over {tot_m:,} matched realised routes: {w:.1%} were dominated at "
          f"the state they executed in")
    print("  the pre-screen, enumerate-every-candidate figure was 70.1%, and the")
    print("  original v2-only realised figure was 17.9%")
    # REWEIGHT to the population's vehicle-type composition. The matched sample is not
    # a random 2%: it is 64.1% stable-intermediated where the realised population is
    # 67.7% native-intermediated, an inversion, and dominance rates differ sharply by
    # candidate type. Quoting the raw matched mean as a population figure would be a
    # statement about large trades on busy pairs through stablecoins.
    if all_matched:
        M = pd.concat(all_matched, ignore_index=True)
        P = pd.concat(all_pop, ignore_index=True)
        M["mid_type"] = M.vehicle.map({v: classify(v)[1] for v in M.vehicle.unique()})
        P["mid_type"] = P.vehicle.map({v: classify(v)[1] for v in P.vehicle.unique()})
        pop_w = P.mid_type.value_counts(normalize=True)
        by_t = M.groupby("mid_type").dominated.mean()
        common = [t for t in by_t.index if t in pop_w.index]
        if common:
            num = sum(by_t[t] * pop_w[t] for t in common)
            den = sum(pop_w[t] for t in common)
            print(f"\n  dominance by candidate type in the matched sample:")
            for t in common:
                print(f"    {t:<14}{by_t[t]:>7.1%}   population weight {pop_w[t]:>6.1%}"
                      f"   matched weight {(M.mid_type == t).mean():>6.1%}")
            print(f"\n  raw matched mean          {w:.1%}")
            print(f"  reweighted to population  {num / den:.1%}   "
                  f"(covers {den:.1%} of realised routing)")
            rows.append({"day": "REWEIGHTED", "realised_multileg": int(len(P)),
                         "matched": int(len(M)), "dominated": float(num / den),
                         "value_weighted": float("nan")})
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
