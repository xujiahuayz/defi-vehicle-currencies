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

  VALUE-WEIGHTED. Edges carry realised USD value only from clean route components whose
  source, every intermediary and sink reconcile within 20 percent. They are traversed in
  inverse proportion, so heavily traded pairs are short. This measures where supported
  economic value flows; raw value is retained only as a coverage diagnostic.

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

For each graph the panel separates direct connectivity from indirect path position.
Topological degree, count strength and raw-USD strength measure the number or activity of
the token's incident markets. Matching eigenvector centralities measure whether those
direct neighbors are themselves important. Matching betweenness measures path position.
All three are converted to within-day shares before constructing excess path position as
betweenness share minus direct-connectivity share and betweenness share minus eigenvector
share. The normalization makes the subtraction commensurable; subtracting raw centrality
statistics with unrelated scales is not an admissible measure.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_centrality.parquet
        output/exhibits/vehicle_centrality.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import canonical_token, classify
from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, repo_path
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.route_roles import ROUTE_KEYS, component_eligibility, component_value_support
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PANEL = DATA_DIR / "processed" / "vehicle_centrality.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "vehicle_centrality.jsonl"
LOCK = DATA_DIR / "processed" / ".vehicle_centrality.lock"
CODE_SOURCES = [
    "scripts/build_vehicle_centrality.py",
    "src/ddvc/asset_types.py",
]


def aggregate_day_edges(frame: pd.DataFrame) -> pd.DataFrame:
    """Build full-count and strict-value token-pair edges from clean route components."""

    required = {
        *ROUTE_KEYS,
        "token_in",
        "token_out",
        "amount_usd",
        "route_class",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"centrality input is missing columns: {', '.join(missing)}")
    data = frame[frame["route_class"].isin(["single", "coherent"])].copy()
    data["token_in"] = data["token_in"].map(canonical_token)
    data["token_out"] = data["token_out"].map(canonical_token)
    data = data[
        data["token_in"].notna()
        & data["token_out"].notna()
        & data["token_in"].ne(data["token_out"])
    ]
    if data.empty:
        return pd.DataFrame(columns=["a", "b", "usd", "raw_usd", "legs"])
    eligibility = component_eligibility(data)
    clean = data.merge(eligibility.eligible[list(ROUTE_KEYS)], on=list(ROUTE_KEYS), how="inner")
    if clean.empty:
        return pd.DataFrame(columns=["a", "b", "usd", "raw_usd", "legs"])
    support = component_value_support(clean)[[*ROUTE_KEYS, "within_20pct"]]
    clean = clean.merge(support, on=list(ROUTE_KEYS), how="left")
    values = pd.to_numeric(clean["amount_usd"], errors="coerce")
    finite_value = values.gt(0) & values.lt(1e9) & np.isfinite(values)
    clean["raw_usd"] = values.where(finite_value, 0.0)
    clean["usd"] = values.where(finite_value & clean["within_20pct"].fillna(False), 0.0)
    clean["a"] = clean[["token_in", "token_out"]].min(axis=1)
    clean["b"] = clean[["token_in", "token_out"]].max(axis=1)
    return clean.groupby(["a", "b"], as_index=False).agg(
        usd=("usd", "sum"),
        raw_usd=("raw_usd", "sum"),
        legs=("amount_usd", "size"),
    )


def day_edges(day: str) -> pd.DataFrame:
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return pd.DataFrame()
    return aggregate_day_edges(
        pd.read_parquet(
            p,
            columns=[
                *ROUTE_KEYS,
                "token_in",
                "token_out",
                "amount_usd",
                "route_class",
            ],
        )
    )


def centralities(
    e: pd.DataFrame,
    k: int | None,
    *,
    min_legs: int = 1,
    min_usd: float = 0.0,
) -> pd.DataFrame:
    import networkx as nx

    count_edges = e[pd.to_numeric(e["legs"], errors="coerce").ge(min_legs)]
    g = nx.Graph()
    for r in count_edges.itertuples(index=False):
        g.add_edge(
            r.a,
            r.b,
            legs=int(r.legs),
            inv_count=1.0 / max(float(r.legs), 1.0),
        )
    if g.number_of_nodes() < 4:
        return pd.DataFrame()
    value_edges = e[pd.to_numeric(e["usd"], errors="coerce").ge(min_usd)].copy()
    gv = nx.Graph()
    for r in value_edges.itertuples(index=False):
        gv.add_edge(
            r.a,
            r.b,
            usd=float(r.usd),
            inv=1.0 / max(float(r.usd), 1.0),
        )
    # k samples the source nodes; exact betweenness is O(nm) and these graphs run to
    # thousands of nodes, so sampling is the difference between minutes and hours. The
    # sample is reported so the estimate's noise is visible.
    kk = min(k or g.number_of_nodes(), g.number_of_nodes())
    topo = nx.betweenness_centrality(g, k=kk, normalized=True, seed=7)
    cnt = nx.betweenness_centrality(g, k=kk, weight="inv_count", normalized=True, seed=7)
    if gv.number_of_nodes() >= 4:
        value_k = min(k or gv.number_of_nodes(), gv.number_of_nodes())
        vol = nx.betweenness_centrality(
            gv, k=value_k, weight="inv", normalized=True, seed=7
        )
        eigen_value = largest_component_eigenvector(gv, weight="usd")
        strength = {n: sum(gv[n][m]["usd"] for m in gv[n]) for n in gv}
    else:
        vol = {}
        eigen_value = {}
        strength = {}
    deg = dict(g.degree())
    count_strength = {n: sum(g[n][m]["legs"] for m in g[n]) for n in g}
    eigen_topological = largest_component_eigenvector(g, weight=None)
    eigen_count = largest_component_eigenvector(g, weight="legs")
    rows = []
    for n in sorted(set(g.nodes()) | set(gv.nodes())):
        sym, typ = classify(n)
        rows.append({"token": n, "symbol": sym, "asset_type": typ,
                     "betweenness_topological": topo.get(n, 0.0),
                     "betweenness_volume": vol.get(n, 0.0),
                     "betweenness_count": cnt.get(n, 0.0),
                     "degree": deg.get(n, 0),
                     "degree_topological": deg.get(n, 0),
                     "strength_count": count_strength.get(n, 0.0),
                     "strength_usd": strength.get(n, 0.0),
                     "eigenvector_topological": eigen_topological.get(n, 0.0),
                     "eigenvector_count": eigen_count.get(n, 0.0),
                     "eigenvector_value": eigen_value.get(n, 0.0)})
    return add_network_position_shares(pd.DataFrame(rows))


def largest_component_eigenvector(
    graph: object,
    *,
    weight: str | None,
) -> dict[str, float]:
    """Deterministic eigenvector centrality on the market-wide connected component."""

    import networkx as nx

    if graph.number_of_nodes() == 0:
        return {}
    components = list(nx.connected_components(graph))
    nodes = max(components, key=lambda component: (len(component), min(component)))
    component = graph.subgraph(nodes)
    if component.number_of_nodes() == 1:
        centrality = {next(iter(nodes)): 1.0}
    elif component.number_of_nodes() == 2:
        centrality = {node: 2**-0.5 for node in nodes}
    else:
        centrality = nx.eigenvector_centrality_numpy(component, weight=weight)
    result = {node: 0.0 for node in graph.nodes()}
    result.update({node: abs(float(value)) for node, value in centrality.items()})
    return result


def _unit_share(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0).clip(lower=0.0)
    total = float(numeric.sum())
    if not np.isfinite(total) or total <= 0:
        return pd.Series(0.0, index=values.index, dtype=float)
    return numeric / total


def add_network_position_shares(frame: pd.DataFrame) -> pd.DataFrame:
    """Put direct, eigenvector and path positions on a common within-day scale."""

    out = frame.copy()
    dimensions = {
        "topological": (
            "degree_topological",
            "eigenvector_topological",
            "betweenness_topological",
        ),
        "count": ("strength_count", "eigenvector_count", "betweenness_count"),
        "value": ("strength_usd", "eigenvector_value", "betweenness_volume"),
    }
    for dimension, (direct, eigenvector, betweenness) in dimensions.items():
        direct_share = f"direct_{dimension}_share"
        eigenvector_share = f"eigenvector_{dimension}_share"
        betweenness_share = f"betweenness_{dimension}_share"
        out[direct_share] = _unit_share(out[direct])
        out[eigenvector_share] = _unit_share(out[eigenvector])
        out[betweenness_share] = _unit_share(out[betweenness])
        out[f"excess_betweenness_over_direct_{dimension}"] = (
            out[betweenness_share] - out[direct_share]
        )
        out[f"excess_betweenness_over_eigenvector_{dimension}"] = (
            out[betweenness_share] - out[eigenvector_share]
        )
    return out


def annual_asset_type_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight daily network positions, with absent type-days represented by zero."""

    data = panel.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["year"] = data["date"].dt.year
    share_columns = [
        column
        for column in data.columns
        if column.endswith("_share") or column.startswith("excess_betweenness_")
    ]
    daily = data.groupby(["year", "day", "asset_type"], as_index=False)[
        share_columns
    ].sum()
    years = sorted(daily["year"].unique())
    types = sorted(data["asset_type"].unique())
    frames = []
    for year in years:
        days = sorted(daily.loc[daily["year"].eq(year), "day"].unique())
        perimeter = pd.MultiIndex.from_product(
            [[year], days, types], names=["year", "day", "asset_type"]
        )
        frames.append(
            daily[daily["year"].eq(year)]
            .set_index(["year", "day", "asset_type"])
            .reindex(perimeter, fill_value=0.0)
            .reset_index()
        )
    complete = pd.concat(frames, ignore_index=True)
    summary = complete.groupby(["year", "asset_type"], as_index=False)[
        share_columns
    ].mean()
    counts = (
        complete.groupby(["year", "asset_type"], as_index=False)["day"]
        .nunique()
        .rename(columns={"day": "sampled_days"})
    )
    return summary.merge(counts, on=["year", "asset_type"], how="inner")


def _one_day(
    day: str,
    min_usd: float,
    k: int | None,
    min_legs: int = 1,
) -> pd.DataFrame | None:
    e = day_edges(day)
    if e.empty:
        return None
    c = centralities(e, k, min_legs=min_legs, min_usd=min_usd)
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
    ap.add_argument(
        "--min-legs",
        type=int,
        default=1,
        help="minimum clean leg count for topological and count edges",
    )
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
                                                 k=args.k, min_legs=args.min_legs), days), 1):
                if c is None or c.empty:
                    continue
                frames.append(c)
                if i % 5 == 0 or i == len(days):
                    print(f"  {i}/{len(days)} {c.day.iloc[0]}: "
                          f"{c.nodes.iloc[0]:,} tokens, {c.edges.iloc[0]:,} pairs",
                          flush=True)
    else:
        for i, day in enumerate(days, 1):
            c = _one_day(day, args.min_usd, args.k, args.min_legs)
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
        annual_asset_type_summary(panel),
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
