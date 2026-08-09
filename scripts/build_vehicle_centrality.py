#!/usr/bin/env python3
"""Vehicle extent as a network property: betweenness centrality in the trading graph.

DEMOTED TO A ROBUSTNESS EXHIBIT BY NODE C ROUND 2, 2026-08-06. Read
docs/node-c-definitions-round2.md section 1 before using anything this script writes as
a primary measure. Three findings from that pass bind here.

First, the justification below did not survive checking, and the paper it appealed to
argues the other way. Flandreau and Jobst was absent from the corpus when that sentence
was written, so it was cited from memory of a summary. The author-deposited precursor is
now here, CEPR Discussion Paper 5529 of March 2006 behind the Economic Journal article of
2009, 41 pages at `literature/text/2009-FlandreauJobst2009Empirics-working-paper-*.txt`,
and it does not support this statistic. Over that extract `grep -aoic` returns 0 for
centrality, 0 for betweenness, 0 for eigenvector and 0 for shortest path. Their own term
is "strategic externalities", 14 occurrences against 0 for "network externalities". Their
network is a binary exchange matrix of which currencies were quoted in which foreign
exchange markets, their externality is a liquidity and popularity feedback estimated at a
parameter product of 0.463, giving "persistence but no lock-in effects", and the quantity
they read off the network is the number of foreign markets quoting a currency. That is
DEGREE. So the one prior paper measuring the international currency role on a network uses
the same statistic `asset_types.py` uses to define the native asset, which is the
circularity in the third finding below and not a defence against it. Nothing may be
attributed to the published 2009 version, which could not be retrieved.

Second, no corpus paper uses this class of statistic. Across 53 papers and 1,974 pages,
`grep -aci` returns zero files for `centrality`, zero for `betweenness`, zero for
`eigenvector`, zero for `closeness centrality` and zero for `shortest path`. The eight
papers that operationalise a currency's international role all use a use share netted
against a benchmark of fundamental demand. Krugman (1980, p. 519) has the vehicle
entering "into more transactions than A's role in world payments would by itself
justify"; Gopinath and Stein (2021) report the dollar's invoicing share as "4.7 times the
share of U.S. goods in imports" against 1.2 for the euro; Somogyi (2026) takes "the
difference between interdealer volume and my implied measure of fundamental trading
demand".

Third, betweenness on THIS graph is close to a restatement of degree, and degree is the
property by which asset_types.py defines the native asset. Measured on the 18 days in
data/processed/vehicle_centrality.parquet: Spearman +0.958 between WETH's betweenness
share and its degree share, +0.948 between the betweenness HHI and the degree HHI, and
the betweenness leader equals the degree leader on 18 of 18 days. Between 87.8% and 96.8%
of nodes carry exactly zero betweenness. Switching to current-flow betweenness, which is
the correct statistic for a flow problem, changes nothing: same leader on both days
tested, and a correlation with degree of +0.62 and +0.70. Eigenvector centrality is the
one that moves the answer, putting USDC first and WETH third on 2026-03-06.

What this script still earns its place doing is showing that the topological reading of
the role behaves differently from the excess-use reading, with the degree correlation
reported next to it so a reader can see how much of it is listing convention.

Three graphs are built per period, because the right edge weight is not obvious and the
choice changes the answer:

  UNWEIGHTED. An edge exists if any direct pool joins the two tokens. Betweenness here
  measures topological indispensability: how often a path must pass through an asset
  because no direct edge exists. This is the feasible-set layer, the architectural
  question of what routes are possible at all.

  VOLUME-WEIGHTED. Edges carry realised volume and are traversed in inverse proportion,
  so heavily traded pairs are short. This measures where value flows.

  COUNT-WEIGHTED. Edges carry the NUMBER of trades and are traversed in inverse
  proportion, so frequently used pairs are short. Java's addition, and it is arguably the
  better measure of the vehicle role, which is about how often traders route through an
  asset and not how much value they move. It is also the more robust of the two here,
  because this project has already been inverted once by value weighting: canonical
  endpoint round trips run 12.7% of multi-leg routes by COUNT against 21.7% by VALUE on the median day,
  and on the worst day observed 25.9% against 91.3%, so contamination concentrates
  precisely where volume weighting puts its weight, and its dispersion across days is far
  wider on value than on count. A single large transfer
  can make a pair look like a highway; a thousand small ones mean it is one.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_centrality.parquet
        output/exhibits/vehicle_centrality.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ddvc.asset_types import classify
from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, repo_path
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PANEL = DATA_DIR / "processed" / "vehicle_centrality.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "vehicle_centrality.jsonl"
LOCK = DATA_DIR / "processed" / ".vehicle_centrality.lock"
CODE_SOURCES = [
    "scripts/build_vehicle_centrality.py",
    "src/ddvc/asset_types.py",
]


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
        g.add_edge(r.a, r.b, usd=float(r.usd), legs=int(r.legs),
                   inv=1.0 / max(float(r.usd), 1.0),
                   inv_count=1.0 / max(float(r.legs), 1.0))
    if g.number_of_nodes() < 4:
        return pd.DataFrame()
    # k samples the source nodes; exact betweenness is O(nm) and these graphs run to
    # thousands of nodes, so sampling is the difference between minutes and hours. The
    # sample is reported so the estimate's noise is visible.
    kk = min(k or g.number_of_nodes(), g.number_of_nodes())
    topo = nx.betweenness_centrality(g, k=kk, normalized=True, seed=7)
    vol = nx.betweenness_centrality(g, k=kk, weight="inv", normalized=True, seed=7)
    cnt = nx.betweenness_centrality(g, k=kk, weight="inv_count", normalized=True, seed=7)
    deg = dict(g.degree())
    strength = {n: sum(g[n][m]["usd"] for m in g[n]) for n in g}
    rows = []
    for n in g.nodes():
        sym, typ = classify(n)
        rows.append({"token": n, "symbol": sym, "asset_type": typ,
                     "betweenness_topological": topo.get(n, 0.0),
                     "betweenness_volume": vol.get(n, 0.0),
                     "betweenness_count": cnt.get(n, 0.0),
                     "degree": deg.get(n, 0), "strength_usd": strength.get(n, 0.0)})
    return pd.DataFrame(rows)


def _one_day(day: str, min_usd: float, k: int | None) -> pd.DataFrame | None:
    e = day_edges(day, min_usd)
    if e.empty:
        return None
    c = centralities(e, k)
    if c.empty:
        return None
    c["day"] = day
    c["nodes"] = e[["a", "b"]].stack().nunique()
    c["edges"] = len(e)
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=90, help="sample every Nth day")
    ap.add_argument("--min-usd", type=float, default=1000.0)
    ap.add_argument("--k", type=int, default=250, help="source nodes sampled per graph")
    ap.add_argument("--jobs", type=int, default=1,
                    help="days built in parallel; reading a day's unified parquet "
                         "dominates the cost and is independent across days")
    ap.add_argument("--out", type=Path, default=OUT_PANEL,
                    help="panel path, so a denser sample can be built without "
                         "replacing the one other nodes already read")
    ap.add_argument("--panel-only", action="store_true")
    args = ap.parse_args()
    args.out = repo_path(args.out)
    require_node_d_release(routes=True)
    jobs = bounded_workers(args.jobs)

    days = sorted(p.stem for p in UNIFIED.glob("[0-9]" * 8 + ".parquet"))[:: args.stride]
    print(f"building trading graphs on {len(days)} sampled days "
          f"({days[0]}..{days[-1]}), k={args.k} source nodes\n")

    frames = []
    if jobs > 1:
        from functools import partial
        with interruptible_process_pool(jobs) as ex:
            for i, c in enumerate(ex.map(partial(_one_day, min_usd=args.min_usd,
                                                 k=args.k), days), 1):
                if c is None or c.empty:
                    continue
                frames.append(c)
                if i % 5 == 0 or i == len(days):
                    print(f"  {i}/{len(days)} {c.day.iloc[0]}: "
                          f"{c.nodes.iloc[0]:,} tokens, {c.edges.iloc[0]:,} pairs",
                          flush=True)
    else:
        for i, day in enumerate(days, 1):
            c = _one_day(day, args.min_usd, args.k)
            if c is None or c.empty:
                continue
            frames.append(c)
            if i % 5 == 0 or i == len(days):
                print(f"  {i}/{len(days)} {day}: {c.nodes.iloc[0]:,} tokens, "
                      f"{c.edges.iloc[0]:,} pairs", flush=True)

    if not frames:
        print("no graphs built")
        return 1
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel.day, format="%Y%m%d")
    write_panel(
        panel,
        args.out,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="network robustness panel on the canonical directed-route layer",
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {args.out.relative_to(REPO_ROOT)}")
        return 0

    print("\nBetweenness centrality by asset TYPE, share of the total, by year.")
    print("Topological betweenness is how often a path MUST pass through the type.")
    panel["year"] = panel.date.dt.year
    for metric in ("betweenness_topological", "betweenness_count",
                   "betweenness_volume"):
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

    write_exhibit(
        panel.groupby(["year", "asset_type"], as_index=False)[
            [
                "betweenness_topological",
                "betweenness_count",
                "betweenness_volume",
                "degree",
                "strength_usd",
            ]
        ].sum(),
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[args.out],
        notes="network robustness summary; not the primary dominance construct",
    )
    print(
        f"\nwrote {args.out.relative_to(REPO_ROOT)} and "
        f"{OUT_EXHIBIT.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle-centrality panel"):
        sys.exit(main())
