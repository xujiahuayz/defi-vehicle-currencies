#!/usr/bin/env python3
"""Is the native intermediation advantage substantive, or an enumeration artefact?

The headline estimate says a direct pool is 38 percentage points less likely to beat a
native-intermediated route, holding pair, window and trade size fixed. Before that can
lead a paper it has to survive the screen this project's workflow requires: a result
that is mechanically true by construction is exposition, not a finding.

The specific threat is that the panel quotes EVERY vehicle candidate for every
pair-window, including candidates sitting in pools no router would ever route through.
If the imported asset frequently has a near-empty pool, routes through it are terrible
for a reason that has nothing to do with the vehicle role, and the native coefficient
would partly measure "we enumerated alternatives that do not really exist".

Three screens, each using data already in the panel:

  BY TRADE SIZE. Depth binds harder on larger trades, so if the advantage is a depth
  story it must GROW with notional. A flat profile across sizes would instead suggest
  something size-independent, which points away from depth and toward the fee or the
  hop count.

  NATIVE AGAINST THE STABLE NUMERAIRE ONLY. Dropping the imported asset removes the
  most likely thin candidate. Stablecoins are deep, liquid and widely paired, so if the
  native asset still beats a stable numeraire in a head-to-head the effect cannot be
  attributed to enumerating implausible alternatives.

  ECONOMICALLY LIVE ROUTES ONLY. Restricting to routes whose quoted output is a
  plausible fraction of notional removes candidates whose pools are so thin that the
  quote collapses. What survives is a comparison among routes a router might actually
  have taken.

A depth mechanism surviving these is not a confound to remove. Thick-market
externality is the mechanism of the vehicle-currency literature, so "native wins
because its network is thicker" IS the claim. The screens exist to show that, rather
than to assume it.

Writes  output/exhibits/dominance_mechanicalness_screen.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

OUT = ROOT / "output" / "exhibits" / "dominance_mechanicalness_screen.jsonl"


def estimate(sub: pd.DataFrame, label: str) -> dict | None:
    """Absorb the fixed effect effect on a restricted sample, clustering by pair."""
    import pyfixest as pf

    mix = sub.groupby("fe_id").native.agg(["mean", "size"])
    ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
    s = sub[sub.fe_id.isin(ident)]
    if s.empty or s.native.nunique() < 2 or s.pair_id.nunique() < 2:
        return None
    fit = pf.feols("dominated ~ native | fe_id", data=s, vcov={"CRV1": "pair_id"})
    row = fit.tidy().loc["native"]
    coef, se = float(row["Estimate"]), float(row["Std. Error"])
    return {"screen": label, "n": int(len(s)), "identifying_groups": int(len(ident)),
            "clusters": int(s.pair_id.nunique()), "coef": coef, "se": se,
            "p": float(row["Pr(>|t|)"]), "mde_80": 2.80 * se,
            "dominated_rate": float(s.dominated.mean())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", type=int, default=12,
                    help="control-window width in HOURS")
    args = ap.parse_args()

    from scripts import run_vehicle_dominance_hdfe as hdfe

    df = hdfe.load(args.window, 100.0)
    df["mid_type"] = df.vehicle.map({v: classify(v)[1] for v in df.vehicle.unique()})
    df["native"] = (df.mid_type == "native").astype(float)
    print(f"base sample {len(df):,} routes, window {args.window}h")
    print(f"vehicle mix: {df.mid_type.value_counts().to_dict()}\n")

    rows = []
    base = estimate(df, "baseline, all candidates")
    if base:
        rows.append(base)

    print("SCREEN 1 — by trade size. A depth story must strengthen with notional.")
    for size in sorted(df.trade_size_usd.unique()):
        r = estimate(df[df.trade_size_usd == size], f"trade size ${int(size):,}")
        if r:
            rows.append(r)

    print("\nSCREEN 2 — native against the stable numeraire only, dropping imported.")
    ns = df[df.mid_type.isin(["native", "stable"])]
    r = estimate(ns, "native vs stable only")
    if r:
        rows.append(r)
    print("         and native against imported only, for contrast.")
    ni = df[df.mid_type.isin(["native", "imported"])]
    r = estimate(ni, "native vs imported only")
    if r:
        rows.append(r)

    print("\nSCREEN 3 — economically live routes only, by how far the quote falls short.")
    # `adv` is the direct route's advantage as a fraction of direct output, so a very
    # negative value means the vehicle route returned far more, which is where a
    # collapsed direct quote would sit. Trim both tails progressively.
    for cut in (0.5, 0.2, 0.05):
        live = df[df.adv.abs() <= cut]
        r = estimate(live, f"|advantage| <= {cut:.0%}")
        if r:
            rows.append(r)

    print(f"\n  {'screen':<34}{'n':>12}{'ident.':>9}{'clust':>7}"
          f"{'coef':>10}{'se':>8}{'p':>7}{'MDE80':>8}{'dom.rate':>10}")
    for r in rows:
        print(f"  {r['screen']:<34}{r['n']:>12,}{r['identifying_groups']:>9,}"
              f"{r['clusters']:>7,}{r['coef']:>10.4f}{r['se']:>8.4f}"
              f"{r['p']:>7.3f}{r['mde_80']:>8.4f}{r['dominated_rate']:>10.1%}")

    if rows:
        write_exhibit(pd.DataFrame(rows), OUT)
        print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
