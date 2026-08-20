#!/usr/bin/env python3
"""Compare realised intermediary use with position in the atomic-pair graph.

The graph is built from coherent pool trades observed on the fifteenth day of
each month. Nodes are canonical token addresses and an undirected edge means
that the atomic pair traded on at least one sampled date in the year. The
network measure is approximate unweighted betweenness with a fixed source
sample. It measures shortest-path position in the observed atomic-pair graph;
it does not measure deposited depth, executable cost, or trader choice.

Reads   data/unified/YYYYMM15.parquet
Writes  output/exhibits/network_betweenness.jsonl

The tracked exhibit retains only the named currencies used by the paper and
deck. Ranks are still computed against every node in each annual graph.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH, classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.realised import realised_routes
from ddvc.tables import write_exhibit


UNIFIED = DATA_DIR / "unified"
OUT = OUTPUT_DIR / "exhibits" / "network_betweenness.jsonl"
EXHIBIT_SYMBOLS = ("WETH", "USDC", "USDT")
SEED = 20260821
READ_COLUMNS = [
    "tx_hash",
    "component_id",
    "token_in",
    "token_out",
    "route_class",
]


def canonical_series(values: pd.Series) -> pd.Series:
    out = values.astype("string").str.lower()
    return out.mask(out.eq(NATIVE_ETH), WETH)


def sampled_paths(*, limit: int | None = None) -> list[Path]:
    paths = sorted(UNIFIED.glob("????????.parquet"))
    paths = [path for path in paths if path.stem[6:] == "15"]
    return paths[:limit] if limit else paths


def reduce_year(paths: list[Path]) -> tuple[Counter[tuple[str, str]], Counter[str], Counter[str], int]:
    edges: Counter[tuple[str, str]] = Counter()
    episodes: Counter[str] = Counter()
    route_presence: Counter[str] = Counter()
    route_count = 0
    for path in paths:
        legs = pd.read_parquet(path, columns=READ_COLUMNS)
        legs = legs.loc[legs["route_class"].eq("coherent")].copy()
        if not legs.empty:
            legs["left"] = canonical_series(legs["token_in"])
            legs["right"] = canonical_series(legs["token_out"])
            legs = legs[
                legs["left"].notna()
                & legs["right"].notna()
                & legs["left"].ne(legs["right"])
            ]
            left = legs[["left", "right"]].min(axis=1)
            right = legs[["left", "right"]].max(axis=1)
            edges.update(zip(left.astype(str), right.astype(str), strict=True))

        routes = realised_routes(
            path.stem,
            path.parent,
            require_positive_value=False,
        )
        if routes.empty:
            continue
        episodes.update(routes["vehicle"].astype(str))
        present = routes[
            ["tx_hash", "component_id", "vehicle"]
        ].drop_duplicates()
        route_presence.update(present["vehicle"].astype(str))
        route_count += int(
            routes[["tx_hash", "component_id"]].drop_duplicates().shape[0]
        )
    return edges, episodes, route_presence, route_count


def annual_rows(
    year: int,
    paths: list[Path],
    *,
    source_sample: int,
) -> list[dict[str, object]]:
    edge_counts, episode_counts, route_counts, total_routes = reduce_year(paths)
    graph = nx.Graph()
    graph.add_edges_from(edge_counts)
    if graph.number_of_nodes() < 3:
        return []
    sources = min(source_sample, graph.number_of_nodes())
    betweenness = nx.betweenness_centrality(
        graph,
        k=sources if sources < graph.number_of_nodes() else None,
        normalized=True,
        weight=None,
        endpoints=False,
        seed=SEED,
    )
    degree = nx.degree_centrality(graph)
    total_episodes = sum(episode_counts.values())
    rows = []
    for token in graph.nodes:
        symbol, asset_type = classify(token)
        rows.append(
            {
                "year": year,
                "sampled_dates": len(paths),
                "token": token,
                "symbol": symbol,
                "asset_type": asset_type,
                "graph_nodes": graph.number_of_nodes(),
                "graph_edges": graph.number_of_edges(),
                "betweenness": float(betweenness[token]),
                "degree_centrality": float(degree[token]),
                "intermediary_positions": int(episode_counts[token]),
                "intermediary_position_share": (
                    episode_counts[token] / total_episodes if total_episodes else 0.0
                ),
                "routes_using_token": int(route_counts[token]),
                "route_participation_share": (
                    route_counts[token] / total_routes if total_routes else 0.0
                ),
                "intermediated_routes": total_routes,
                "betweenness_source_sample": sources,
                "seed": SEED,
            }
        )
    frame = pd.DataFrame(rows)
    for column in (
        "betweenness",
        "degree_centrality",
        "intermediary_position_share",
        "route_participation_share",
    ):
        frame[f"{column}_rank"] = frame[column].rank(
            method="min", ascending=False
        ).astype(int)
    return frame.to_dict("records")


def exhibit_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the reader-facing rows after ranks are computed on the full graph."""
    selected = frame.loc[frame["symbol"].isin(EXHIBIT_SYMBOLS)].copy()
    expected = len(EXHIBIT_SYMBOLS) * frame["year"].nunique()
    if len(selected) != expected:
        counts = selected.groupby(["year", "symbol"]).size().to_dict()
        raise ValueError(
            f"expected one row per year and named currency ({expected}); "
            f"found {len(selected)}: {counts}"
        )
    return selected.sort_values(["year", "symbol"]).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sample", type=int, default=256)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.source_sample < 2:
        raise ValueError("source sample must be at least two")

    paths = sampled_paths(limit=args.limit)
    if not paths:
        raise FileNotFoundError(f"no fifteenth-of-month route files under {UNIFIED}")
    by_year: dict[int, list[Path]] = defaultdict(list)
    for path in paths:
        by_year[int(path.stem[:4])].append(path)

    rows: list[dict[str, object]] = []
    for year, year_paths in sorted(by_year.items()):
        print(f"{year}: {len(year_paths)} sampled date(s)", flush=True)
        rows.extend(
            annual_rows(
                year,
                year_paths,
                source_sample=args.source_sample,
            )
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        print("sampled dates contain no eligible atomic-pair graph")
        return 0
    if args.limit:
        leaders = frame.sort_values(
            ["year", "intermediary_position_share"],
            ascending=[True, False],
        ).groupby("year", as_index=False).head(10)
        print(leaders[["year", "symbol", "token", "betweenness", "intermediary_position_share", "route_participation_share"]].to_string(index=False))
        print("smoke run complete; canonical output unchanged")
        return 0

    exhibit = exhibit_rows(frame)
    write_exhibit(
        exhibit,
        OUT,
        code_sources=["scripts/analyze/run_network_betweenness.py"],
        inputs=paths,
        notes=(
            "unweighted approximate betweenness in the observed atomic-pair graph "
            "on fifteenth-of-month route dates; realised use retains all route lengths"
        ),
    )
    print(
        f"wrote {OUT.relative_to(REPO_ROOT)} "
        f"({len(exhibit):,} named-currency years; ranks use the full graph)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
