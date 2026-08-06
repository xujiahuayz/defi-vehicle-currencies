#!/usr/bin/env python3
"""Which asset lies on the CHEAPEST paths, and does that differ from the busiest?

The centrality panel measures two graphs, topological and volume-weighted, and both say
the native asset remains the node paths must cross while its share erodes. Neither speaks
to the thick-market externality directly, because an asset can be topologically
indispensable simply because no alternative edge exists, and it can be volume-central
simply because it is popular. The mechanism in the vehicle-currency literature is about
COST: an incumbent keeps the role because routing through it is cheap.

So the third graph weights each edge by what it actually costs to trade that pair, and a
shortest path becomes a cheapest path. Betweenness on that graph is the share of cheapest
paths running through an asset, which is the closest measurable analogue of the role the
theory describes.

The divergence is the point. Topological and volume dominance persisting AFTER cost
dominance has gone is what incumbency without a cost basis looks like, and it is a
sharper test than any level comparison, because it asks whether the asset is still on the
cheap paths and not merely whether routing through it is cheaper on average.

Edge cost comes from REALISED trades and not from the counterfactual quoter. For each
pair and period the cost is the median absolute deviation between a trade's realised
execution price and the period's volume-weighted price on that pair, which is a direct
measure of what a trader gave up in price impact and fees. This keeps the whole
construction inside observed behaviour, so it inherits none of the support, timing or
arbitrage-bound problems that constrain the counterfactual estimands.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/cost_weighted_centrality.parquet
        output/exhibits/cost_weighted_centrality.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit, write_panel  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT_PANEL = ROOT / "data" / "processed" / "cost_weighted_centrality.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "cost_weighted_centrality.jsonl"


def day_edge_costs(day: str, min_trades: int) -> pd.DataFrame:
    """Per pair, realised execution dispersion as the edge's cost in basis points."""
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p, columns=["token_in", "token_out", "amount_in", "amount_out",
                                    "amount_usd", "route_class"])
    d = d[d.route_class.isin(["single", "coherent"])]
    d = d[(d.amount_in > 0) & (d.amount_out > 0) & (d.amount_usd > 0)
          & (d.amount_usd < 1e9)]
    if d.empty:
        return pd.DataFrame()
    # Orient each leg so the pair key is unordered and the price is comparable within it.
    lo = d[["token_in", "token_out"]].min(axis=1)
    hi = d[["token_in", "token_out"]].max(axis=1)
    forward = d.token_in.values == lo.values
    px = np.where(forward, d.amount_out / d.amount_in, d.amount_in / d.amount_out)
    e = pd.DataFrame({"a": lo.values, "b": hi.values, "px": px,
                      "usd": d.amount_usd.values})
    e = e[np.isfinite(e.px) & (e.px > 0)]
    if e.empty:
        return pd.DataFrame()

    out = []
    for (a, b), g in e.groupby(["a", "b"]):
        if len(g) < min_trades:
            continue
        # Volume-weighted reference price for the period, then the median absolute
        # deviation from it. A pair where every trade clears near the same price is
        # cheap to cross; a pair where realised prices scatter is expensive.
        ref = float((g.px * g.usd).sum() / g.usd.sum())
        if ref <= 0:
            continue
        dev = (g.px / ref - 1.0).abs()
        cost_bps = float(dev.median() * 10_000)
        if not np.isfinite(cost_bps) or cost_bps <= 0 or cost_bps > 5_000:
            continue
        out.append({"a": a, "b": b, "cost_bps": cost_bps,
                    "usd": float(g.usd.sum()), "trades": int(len(g))})
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=120)
    ap.add_argument("--min-trades", type=int, default=8)
    ap.add_argument("--k", type=int, default=150)
    args = ap.parse_args()

    import networkx as nx

    days = sorted(p.stem for p in UNIFIED.glob("[0-9]" * 8 + ".parquet"))[:: args.stride]
    print(f"building cost-weighted graphs on {len(days)} days "
          f"({days[0]}..{days[-1]})\n")

    frames = []
    for i, day in enumerate(days, 1):
        e = day_edge_costs(day, args.min_trades)
        if e.empty or len(e) < 8:
            continue
        g = nx.Graph()
        for r in e.itertuples(index=False):
            # Distance IS the cost, so a shortest path is a cheapest path.
            g.add_edge(r.a, r.b, cost=float(r.cost_bps))
        if g.number_of_nodes() < 4:
            continue
        kk = min(args.k, g.number_of_nodes())
        bc = nx.betweenness_centrality(g, k=kk, weight="cost", normalized=True, seed=7)
        rows = []
        for n, v in bc.items():
            sym, typ = classify(n)
            rows.append({"day": day, "token": n, "symbol": sym, "asset_type": typ,
                         "betweenness_cost": v})
        frames.append(pd.DataFrame(rows))
        if i % 4 == 0 or i == len(days):
            print(f"  {i}/{len(days)} {day}: {g.number_of_nodes():,} tokens, "
                  f"{g.number_of_edges():,} pairs, median edge cost "
                  f"{e.cost_bps.median():.1f} bps", flush=True)

    if not frames:
        print("no graphs built")
        return 1
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel.day, format="%Y%m%d")
    panel["year"] = panel.date.dt.year
    write_panel(panel, OUT_PANEL)

    print("\nShare of COST-weighted betweenness by asset type, which is the share of")
    print("CHEAPEST paths running through each type:")
    piv = panel.groupby(["year", "asset_type"]).betweenness_cost.sum().unstack(fill_value=0.0)
    piv = piv.div(piv.sum(axis=1).clip(lower=1e-12), axis=0)
    cols = [c for c in ("native", "stable", "imported", "staked_native", "other")
            if c in piv.columns]
    print("  year  " + "".join(f"{c:>15}" for c in cols))
    for yr, row in piv.iterrows():
        print(f"  {yr}  " + "".join(f"{row[c]:>14.1%}" for c in cols))

    top = (panel.groupby(["year", "symbol"]).betweenness_cost.sum().reset_index()
           .sort_values(["year", "betweenness_cost"], ascending=[True, False]))
    print("\n  asset on the most cheapest-paths each year:")
    for yr, g in top.groupby("year"):
        g = g[g.symbol.notna()]
        if len(g):
            print(f"    {yr}  {g.iloc[0].symbol}")

    write_exhibit(panel.groupby(["year", "asset_type"], as_index=False)
                  .betweenness_cost.sum(), OUT_EXHIBIT)
    print(f"\nwrote {OUT_PANEL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
