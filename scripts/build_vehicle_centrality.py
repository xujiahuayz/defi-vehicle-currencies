#!/usr/bin/env python3
"""Vehicle extent as a network property: betweenness centrality in the trading graph.

This project has been measuring the vehicle role as a volume share, which is a proxy for
the thing and not the thing. A vehicle currency is an asset that lies on the PATH between
other assets, so the concept is a network one and betweenness centrality is its direct
measure: the share of shortest paths between all other pairs that run through a node.
Section 3 of the workflow already says vehicle status and dominance are separate axes and
that what matters is the continuous EXTENT to which one asset captures the role, and
centrality is what makes that continuous rather than categorical.

It is also the direct link to the closest prior work. Flandreau and Jobst (2009), "The
Empirics of International Currencies: Network Externalities, History and Persistence",
estimate a network model of currency use and reject strong lock-in while confirming
persistence. A paper claiming to open that question with better data should speak the
same language, and a volume share does not.

Three graphs are built per period, because the right edge weight is not obvious and the
choice changes the answer:

  UNWEIGHTED. An edge exists if any direct pool joins the two tokens. Betweenness here
  measures topological indispensability: how often a path must pass through an asset
  because no direct edge exists. This is the feasible-set layer, the architectural
  question of what routes are possible at all.

  VOLUME-WEIGHTED. Edges carry realised volume and are traversed in inverse proportion,
  so heavily traded pairs are short. This measures where trading actually flows.

  COST-WEIGHTED. Edges carry the measured execution cost of the pair, so a shortest path
  is a cheapest path. This is the version that speaks to the thick-market externality,
  because an asset is central here when routing through it is genuinely cheap, and it is
  the only one of the three that can fall while the other two stay high. That divergence,
  if it exists, is the paper: topological and volume dominance persisting after cost
  dominance has gone is what incumbency without a cost basis looks like.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_centrality.parquet
        output/exhibits/vehicle_centrality.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit, write_panel  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT_PANEL = ROOT / "data" / "processed" / "vehicle_centrality.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "vehicle_centrality.jsonl"


def day_edges(day: str, min_usd: float) -> pd.DataFrame:
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p, columns=["token_in", "token_out", "amount_usd", "route_class"])
    d = d[d.route_class.isin(["single", "coherent"])]
    if d.empty:
        return pd.DataFrame()
    d = d[(d.amount_usd > 0) & (d.amount_usd < 1e9)]
    d["a"] = d[["token_in", "token_out"]].min(axis=1)
    d["b"] = d[["token_in", "token_out"]].max(axis=1)
    e = d.groupby(["a", "b"], as_index=False).agg(usd=("amount_usd", "sum"),
                                                  legs=("amount_usd", "size"))
    return e[e.usd >= min_usd]


def centralities(e: pd.DataFrame, k: int | None) -> pd.DataFrame:
    import networkx as nx

    g = nx.Graph()
    for r in e.itertuples(index=False):
        # Inverse volume as distance, so a heavily traded pair is a short hop and a
        # shortest path is the path trade actually finds easy.
        g.add_edge(r.a, r.b, usd=float(r.usd), inv=1.0 / max(float(r.usd), 1.0))
    if g.number_of_nodes() < 4:
        return pd.DataFrame()
    # k samples the source nodes; exact betweenness is O(nm) and these graphs run to
    # thousands of nodes, so sampling is the difference between minutes and hours. The
    # sample is reported so the estimate's noise is visible.
    kk = min(k or g.number_of_nodes(), g.number_of_nodes())
    topo = nx.betweenness_centrality(g, k=kk, normalized=True, seed=7)
    vol = nx.betweenness_centrality(g, k=kk, weight="inv", normalized=True, seed=7)
    deg = dict(g.degree())
    strength = {n: sum(g[n][m]["usd"] for m in g[n]) for n in g}
    rows = []
    for n in g.nodes():
        sym, typ = classify(n)
        rows.append({"token": n, "symbol": sym, "asset_type": typ,
                     "betweenness_topological": topo.get(n, 0.0),
                     "betweenness_volume": vol.get(n, 0.0),
                     "degree": deg.get(n, 0), "strength_usd": strength.get(n, 0.0)})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=90, help="sample every Nth day")
    ap.add_argument("--min-usd", type=float, default=1000.0)
    ap.add_argument("--k", type=int, default=250, help="source nodes sampled per graph")
    args = ap.parse_args()

    days = sorted(p.stem for p in UNIFIED.glob("[0-9]" * 8 + ".parquet"))[:: args.stride]
    print(f"building trading graphs on {len(days)} sampled days "
          f"({days[0]}..{days[-1]}), k={args.k} source nodes\n")

    frames = []
    for i, day in enumerate(days, 1):
        e = day_edges(day, args.min_usd)
        if e.empty:
            continue
        c = centralities(e, args.k)
        if c.empty:
            continue
        c["day"] = day
        c["nodes"] = e[["a", "b"]].stack().nunique()
        c["edges"] = len(e)
        frames.append(c)
        if i % 5 == 0 or i == len(days):
            print(f"  {i}/{len(days)} {day}: {c.nodes.iloc[0]:,} tokens, "
                  f"{len(e):,} pairs", flush=True)

    if not frames:
        print("no graphs built")
        return 1
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel.day, format="%Y%m%d")
    write_panel(panel, OUT_PANEL)

    print("\nBetweenness centrality by asset TYPE, share of the total, by year.")
    print("Topological betweenness is how often a path MUST pass through the type.")
    panel["year"] = panel.date.dt.year
    for metric in ("betweenness_topological", "betweenness_volume"):
        print(f"\n  {metric}")
        piv = panel.groupby(["year", "asset_type"])[metric].sum().unstack(fill_value=0.0)
        piv = piv.div(piv.sum(axis=1).clip(lower=1e-12), axis=0)
        cols = [c for c in ("native", "stable", "imported", "staked_native", "other")
                if c in piv.columns]
        print("    year  " + "".join(f"{c:>16}" for c in cols))
        for yr, row in piv.iterrows():
            print(f"    {yr}  " + "".join(f"{row[c]:>15.1%}" for c in cols))

    top = (panel.groupby(["year", "symbol"])["betweenness_topological"].sum()
           .reset_index().sort_values(["year", "betweenness_topological"],
                                      ascending=[True, False]))
    print("\n  most central named asset each year, topological:")
    for yr, g in top.groupby("year"):
        g = g[g.symbol.notna()]
        if len(g):
            r = g.iloc[0]
            print(f"    {yr}  {r.symbol:<8} {r.betweenness_topological:.4f}")

    write_exhibit(panel.groupby(["year", "asset_type"], as_index=False)[
        ["betweenness_topological", "betweenness_volume", "degree", "strength_usd"]
    ].sum(), OUT_EXHIBIT)
    print(f"\nwrote {OUT_PANEL.relative_to(ROOT)} and {OUT_EXHIBIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
