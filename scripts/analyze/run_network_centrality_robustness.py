#!/usr/bin/env python3
"""Measure currency position in the observed leg network and perturb its coverage.

The baseline is a directed, weighted token-leg graph on the fifteenth day of
each month.  It includes unambiguous single trades and legs in coherent routes;
edge weights are either leg counts or repriced leg value.
For directed eigenvector centrality we report incoming and outgoing scores and
their normalized geometric mean.  The conventional undirected eigenvector and
the paper's existing unweighted betweenness concept are retained as comparisons.

Coverage sensitivity removes one sampled date or one observed venue at a time.
It is intentionally concentrated on 2024 H1 and 2026 H1, the two periods in the
headline rotation.  The full half-year series is still estimated for every
available period.  A separate scope check removes stablecoin-to-stablecoin legs
to show how much of value-weighted centrality comes from the stablecoin core.

Reads   data/unified/YYYYMM15.parquet
Writes  output/exhibits/network_centrality_robustness.jsonl
        output/exhibits/network_centrality_robustness_support.jsonl
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import kendalltau

from ddvc.asset_types import NATIVE_ETH, WETH, classify
from ddvc.datasets import route_partitions, validate_before_install
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.realised import extract_realised_routes
from ddvc.tables import write_exhibit


OUT = OUTPUT_DIR / "exhibits" / "network_centrality_robustness.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "network_centrality_robustness_support.jsonl"
EXHIBIT_SYMBOLS = ("WETH", "USDC", "USDT", "DAI")
ROBUST_PERIODS = ("2024 H1", "2026 H1")
WEIGHTS = ("leg_count", "leg_value_usd")
SEED = 20260822
BETWEENNESS_SOURCES = 256
READ_COLUMNS = [
    "tx_hash",
    "component_id",
    "token_in",
    "token_out",
    "source",
    "route_class",
    "ambiguous",
    "amount_usd",
    "tin_role",
    "tout_role",
    "log_index",
    "timestamp_utc",
]


@dataclass(frozen=True)
class PeriodData:
    edges: pd.DataFrame
    positions: pd.DataFrame
    sampled_dates: tuple[str, ...]


def canonical_series(values: pd.Series) -> pd.Series:
    out = values.astype("string").str.lower()
    return out.mask(out.eq(NATIVE_ETH), WETH)


def period_label(day: str) -> str:
    month = int(day[4:6])
    return f"{day[:4]} H{1 if month <= 6 else 2}"


def sampled_paths(paths: list[Path]) -> list[Path]:
    return [path for path in paths if len(path.stem) == 8 and path.stem[6:] == "15"]


def reduce_period(paths: list[Path]) -> PeriodData:
    edge_frames: list[pd.DataFrame] = []
    position_frames: list[pd.DataFrame] = []
    for path in paths:
        all_legs = pd.read_parquet(path, columns=READ_COLUMNS)
        routes = extract_realised_routes(all_legs, require_positive_value=False)
        if not routes.empty:
            positions = routes[
                ["tx_hash", "component_id", "vehicle"]
            ].rename(columns={"vehicle": "token"})
            positions["day"] = path.stem
            position_frames.append(positions)

        legs = all_legs.loc[
            ~all_legs["ambiguous"].fillna(True)
            & all_legs["route_class"].isin(("single", "coherent"))
        ].copy()
        if legs.empty:
            continue
        legs["left"] = canonical_series(legs["token_in"])
        legs["right"] = canonical_series(legs["token_out"])
        legs = legs.loc[
            legs["left"].notna()
            & legs["right"].notna()
            & legs["left"].ne(legs["right"])
        ].copy()
        legs["amount_usd"] = pd.to_numeric(
            legs["amount_usd"], errors="coerce"
        ).where(lambda values: values.gt(0), 0.0)
        grouped = (
            legs.groupby(["source", "left", "right"], as_index=False, sort=False)
            .agg(
                leg_count=("tx_hash", "size"),
                leg_value_usd=("amount_usd", "sum"),
            )
            .assign(day=path.stem)
        )
        edge_frames.append(grouped)
    if not edge_frames:
        return PeriodData(pd.DataFrame(), pd.DataFrame(), tuple())
    edges = pd.concat(edge_frames, ignore_index=True)
    positions = (
        pd.concat(position_frames, ignore_index=True)
        if position_frames
        else pd.DataFrame(columns=["tx_hash", "component_id", "token", "day"])
    )
    return PeriodData(edges, positions, tuple(path.stem for path in paths))


def select_edges(
    edges: pd.DataFrame,
    *,
    omitted_date: str | None = None,
    omitted_venue: str | None = None,
) -> pd.DataFrame:
    selected = edges
    if omitted_date is not None:
        selected = selected.loc[selected["day"].ne(omitted_date)]
    if omitted_venue is not None:
        selected = selected.loc[selected["source"].ne(omitted_venue)]
    return selected


def without_stable_stable_edges(edges: pd.DataFrame) -> pd.DataFrame:
    left_stable = edges["left"].map(lambda token: classify(token)[1]).eq("stable")
    right_stable = edges["right"].map(lambda token: classify(token)[1]).eq("stable")
    return edges.loc[~(left_stable & right_stable)]


def weighted_graph(edges: pd.DataFrame, weight: str) -> nx.DiGraph:
    if weight not in WEIGHTS:
        raise ValueError(f"unknown edge weight: {weight}")
    grouped = edges.groupby(["left", "right"], as_index=False, sort=False)[
        weight
    ].sum()
    grouped = grouped.loc[pd.to_numeric(grouped[weight], errors="coerce").gt(0)]
    graph = nx.DiGraph()
    graph.add_weighted_edges_from(
        (
            str(row.left),
            str(row.right),
            float(getattr(row, weight)),
        )
        for row in grouped.itertuples(index=False)
    )
    return graph


def normalize(values: dict[str, float]) -> dict[str, float]:
    total = float(sum(max(0.0, float(value)) for value in values.values()))
    if total <= 0:
        return {node: 0.0 for node in values}
    return {node: max(0.0, float(value)) / total for node, value in values.items()}


def rank_values(values: dict[str, float]) -> dict[str, int]:
    ordered = sorted(values, key=lambda node: (-float(values[node]), node))
    return {node: rank for rank, node in enumerate(ordered, 1)}


def principal_eigenvector(graph: nx.Graph | nx.DiGraph) -> dict[str, float]:
    try:
        return nx.eigenvector_centrality(
            graph, max_iter=5_000, tol=1e-9, weight="weight"
        )
    except nx.PowerIterationFailedConvergence:
        return nx.eigenvector_centrality_numpy(
            graph, weight="weight", max_iter=20_000, tol=1e-10
        )


def eigenvector_scores(graph: nx.DiGraph) -> pd.DataFrame:
    """Return standard undirected and two directed weighted eigenvectors.

    The directed graph is generally reducible because some fringe assets trade
    in only one observed direction.  Directed scores therefore use the largest
    strongly connected component.  The four currencies of interest must all be
    present in it before results can be admitted.
    """

    if graph.number_of_nodes() < 3:
        return pd.DataFrame()
    component = max(nx.strongly_connected_components(graph), key=len)
    directed = graph.subgraph(component).copy()
    undirected = nx.Graph()
    for left, right, data in graph.edges(data=True):
        weight = float(data["weight"])
        if undirected.has_edge(left, right):
            undirected[left][right]["weight"] += weight
        else:
            undirected.add_edge(left, right, weight=weight)
    incoming = principal_eigenvector(directed)
    outgoing = principal_eigenvector(directed.reverse(copy=False))
    undirected_scores = principal_eigenvector(undirected)
    incoming = normalize(incoming)
    outgoing = normalize(outgoing)
    undirected_scores = normalize(undirected_scores)
    two_sided = normalize(
        {
            node: float(np.sqrt(incoming[node] * outgoing[node]))
            for node in directed
        }
    )
    all_nodes = sorted(graph.nodes)
    frame = pd.DataFrame({"token": all_nodes})
    for name, values in (
        ("eigenvector_in_share", incoming),
        ("eigenvector_out_share", outgoing),
        ("eigenvector_two_sided_share", two_sided),
        ("eigenvector_undirected_share", undirected_scores),
    ):
        frame[name] = frame["token"].map(values).fillna(0.0).astype(float)
        ranks = rank_values(values)
        frame[f"{name}_rank"] = frame["token"].map(ranks).astype("Int64")
    frame["directed_scc"] = frame["token"].isin(component)
    frame["graph_nodes"] = graph.number_of_nodes()
    frame["graph_edges"] = graph.number_of_edges()
    frame["directed_scc_nodes"] = len(component)
    return frame


def betweenness_scores(graph: nx.DiGraph, *, sources: int) -> dict[str, float]:
    undirected = graph.to_undirected()
    if undirected.number_of_nodes() < 3:
        return {}
    sample = min(sources, undirected.number_of_nodes())
    return nx.betweenness_centrality(
        undirected,
        k=sample if sample < undirected.number_of_nodes() else None,
        normalized=True,
        weight=None,
        endpoints=False,
        seed=SEED,
    )


def strength_shares(graph: nx.DiGraph) -> dict[str, float]:
    strength = {
        node: float(graph.in_degree(node, weight="weight"))
        + float(graph.out_degree(node, weight="weight"))
        for node in graph
    }
    return normalize(strength)


def currency_tokens(frame: pd.DataFrame) -> dict[str, str]:
    selected: dict[str, str] = {}
    for token in frame["token"].astype(str):
        symbol, _asset_type = classify(token)
        if symbol not in EXHIBIT_SYMBOLS:
            continue
        if symbol in selected and selected[symbol] != token:
            raise ValueError(f"multiple observed token addresses classify as {symbol}")
        selected[symbol] = token
    return selected


def route_metrics(positions: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    if positions.empty:
        return {}
    keys = ["day", "tx_hash", "component_id"]
    total_routes = int(positions[keys].drop_duplicates().shape[0])
    total_positions = int(len(positions))
    counts = positions["token"].value_counts()
    metrics: dict[str, dict[str, float | int]] = {}
    for token, count in counts.items():
        metrics[str(token)] = {
            "intermediary_positions": int(count),
            "intermediary_position_share": (
                float(count) / total_positions if total_positions else 0.0
            ),
            "routes_using_token": int(count),
            "route_participation_share": (
                float(count) / total_routes if total_routes else 0.0
            ),
            "intermediated_routes": total_routes,
        }
    return metrics


def scenario_rows(
    period: str,
    data: PeriodData,
    *,
    scenario: str,
    scenario_kind: str,
    omitted: str | None,
    edges: pd.DataFrame,
    include_betweenness: bool,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    route = route_metrics(data.positions) if scenario == "full" else {}
    result_rows: list[dict[str, object]] = []
    full_frames: dict[str, pd.DataFrame] = {}
    for weight in WEIGHTS:
        graph = weighted_graph(edges, weight)
        scores = eigenvector_scores(graph)
        if scores.empty:
            continue
        tokens = currency_tokens(scores)
        if not scores.loc[scores["token"].isin(tokens.values()), "directed_scc"].all():
            raise ValueError(
                f"{period} {scenario} {weight} puts a named currency outside the main SCC"
            )
        strength = strength_shares(graph)
        strength_rank = rank_values(strength)
        between = (
            betweenness_scores(graph, sources=BETWEENNESS_SOURCES)
            if include_betweenness and weight == "leg_count"
            else {}
        )
        between_rank = rank_values(between) if between else {}
        scores["strength_share"] = scores["token"].map(strength).fillna(0.0)
        scores["strength_share_rank"] = scores["token"].map(strength_rank).astype("Int64")
        scores["betweenness"] = scores["token"].map(between)
        scores["betweenness_rank"] = scores["token"].map(between_rank).astype("Int64")
        full_frames[weight] = scores
        for symbol in EXHIBIT_SYMBOLS:
            if symbol not in tokens:
                continue
            token = tokens[symbol]
            row = scores.loc[scores["token"].eq(token)].iloc[0]
            result_rows.append(
                {
                    "period": period,
                    "scenario": scenario,
                    "scenario_kind": scenario_kind,
                    "omitted": omitted,
                    "weight": weight,
                    "symbol": symbol,
                    "token": token,
                    "sampled_dates": len(data.sampled_dates),
                    "graph_nodes": int(row["graph_nodes"]),
                    "graph_edges": int(row["graph_edges"]),
                    "directed_scc_nodes": int(row["directed_scc_nodes"]),
                    "eigenvector_in_share": float(row["eigenvector_in_share"]),
                    "eigenvector_in_rank": int(row["eigenvector_in_share_rank"]),
                    "eigenvector_out_share": float(row["eigenvector_out_share"]),
                    "eigenvector_out_rank": int(row["eigenvector_out_share_rank"]),
                    "eigenvector_two_sided_share": float(
                        row["eigenvector_two_sided_share"]
                    ),
                    "eigenvector_two_sided_rank": int(
                        row["eigenvector_two_sided_share_rank"]
                    ),
                    "eigenvector_undirected_share": float(
                        row["eigenvector_undirected_share"]
                    ),
                    "eigenvector_undirected_rank": int(
                        row["eigenvector_undirected_share_rank"]
                    ),
                    "strength_share": float(row["strength_share"]),
                    "strength_rank": int(row["strength_share_rank"]),
                    "betweenness": (
                        float(row["betweenness"])
                        if pd.notna(row["betweenness"])
                        else None
                    ),
                    "betweenness_rank": (
                        int(row["betweenness_rank"])
                        if pd.notna(row["betweenness_rank"])
                        else None
                    ),
                    **route.get(token, {}),
                }
            )
    return pd.DataFrame(result_rows), full_frames


def rank_stability(
    baseline: pd.DataFrame,
    perturbed: pd.DataFrame,
    column: str,
    *,
    top_n: int = 10,
) -> tuple[float, float, int]:
    left = baseline.set_index("token")[column]
    right = perturbed.set_index("token")[column]
    common = left.index.intersection(right.index)
    if len(common) < 3:
        return float("nan"), float("nan"), len(common)
    correlation = kendalltau(left.loc[common], right.loc[common], nan_policy="omit").statistic
    left_top = set(left.nlargest(min(top_n, len(left))).index)
    right_top = set(right.nlargest(min(top_n, len(right))).index)
    union = left_top | right_top
    jaccard = len(left_top & right_top) / len(union) if union else float("nan")
    return float(correlation), float(jaccard), len(common)


def scenario_specs(data: PeriodData) -> list[tuple[str, str, str | None, pd.DataFrame]]:
    specs: list[tuple[str, str, str | None, pd.DataFrame]] = [
        ("full", "full", None, data.edges)
    ]
    for day in data.sampled_dates:
        specs.append(
            (
                f"leave_date_{day}",
                "leave_one_date_out",
                day,
                select_edges(data.edges, omitted_date=day),
            )
        )
    for venue in sorted(data.edges["source"].astype(str).unique()):
        specs.append(
            (
                f"leave_venue_{venue}",
                "leave_one_venue_out",
                venue,
                select_edges(data.edges, omitted_venue=venue),
            )
        )
    specs.append(
        (
            "exclude_stable_stable",
            "economic_scope",
            "stable_stable_legs",
            without_stable_stable_edges(data.edges),
        )
    )
    return specs


def analyze_period(
    period: str,
    data: PeriodData,
    *,
    robustness: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = scenario_specs(data) if robustness else [("full", "full", None, data.edges)]
    results: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    baseline_frames: dict[str, pd.DataFrame] | None = None
    for scenario, kind, omitted, edges in specs:
        print(f"  {period}: {scenario}", flush=True)
        rows, frames = scenario_rows(
            period,
            data,
            scenario=scenario,
            scenario_kind=kind,
            omitted=omitted,
            edges=edges,
            include_betweenness=True,
        )
        results.append(rows)
        if scenario == "full":
            baseline_frames = frames
            continue
        assert baseline_frames is not None
        for weight in WEIGHTS:
            for column in (
                "eigenvector_two_sided_share",
                "eigenvector_undirected_share",
                "strength_share",
                *( ("betweenness",) if weight == "leg_count" else () ),
            ):
                tau, jaccard, common_nodes = rank_stability(
                    baseline_frames[weight], frames[weight], column
                )
                support_rows.append(
                    {
                        "period": period,
                        "scenario": scenario,
                        "scenario_kind": kind,
                        "omitted": omitted,
                        "weight": weight,
                        "measure": column,
                        "kendall_tau_common_nodes": tau,
                        "top10_jaccard": jaccard,
                        "common_nodes": common_nodes,
                    }
                )
    return pd.concat(results, ignore_index=True), pd.DataFrame(support_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        action="append",
        help="optional half-year label such as '2024 H1'; repeat to select several",
    )
    parser.add_argument(
        "--robust-period",
        action="append",
        help="override the two half-years receiving leave-date and leave-venue checks",
    )
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT)
    args = parser.parse_args()

    release = route_partitions(READ_COLUMNS, nonempty=False)
    paths = sampled_paths(list(release.paths))
    selected_periods = set(args.period or ())
    if selected_periods:
        paths = [path for path in paths if period_label(path.stem) in selected_periods]
    if not paths:
        raise FileNotFoundError("no selected fifteenth-of-month route partitions")
    by_period: dict[str, list[Path]] = {}
    for path in paths:
        by_period.setdefault(period_label(path.stem), []).append(path)
    robust_periods = set(args.robust_period or ROBUST_PERIODS)

    result_frames: list[pd.DataFrame] = []
    support_frames: list[pd.DataFrame] = []
    for period, period_paths in sorted(by_period.items()):
        print(f"{period}: {len(period_paths)} sampled date(s)", flush=True)
        data = reduce_period(sorted(period_paths))
        if data.edges.empty:
            print(f"  {period}: no unambiguous sampled legs", flush=True)
            continue
        results, support = analyze_period(
            period, data, robustness=period in robust_periods
        )
        result_frames.append(results)
        if not support.empty:
            support_frames.append(support)
    if not result_frames:
        raise ValueError("selected periods contain no unambiguous leg graph")
    result = pd.concat(result_frames, ignore_index=True)
    support = (
        pd.concat(support_frames, ignore_index=True)
        if support_frames
        else pd.DataFrame(
            columns=[
                "period",
                "scenario",
                "scenario_kind",
                "omitted",
                "weight",
                "measure",
                "kendall_tau_common_nodes",
                "top10_jaccard",
                "common_nodes",
            ]
        )
    )
    validator = validate_before_install(release)
    write_exhibit(
        result,
        args.output,
        code_sources=["scripts/analyze/run_network_centrality_robustness.py"],
        inputs=paths,
        notes=(
            "half-year directed weighted unambiguous leg graphs on fifteenth-of-month dates; "
            "directed scores use the largest strongly connected component"
        ),
        preinstall_validator=validator,
    )
    write_exhibit(
        support,
        args.support_output,
        code_sources=["scripts/analyze/run_network_centrality_robustness.py"],
        inputs=paths,
        notes="leave-one-date and leave-one-venue rank stability against each full-period graph",
        preinstall_validator=validator,
    )
    print(
        f"wrote {args.output.relative_to(REPO_ROOT) if args.output.is_relative_to(REPO_ROOT) else args.output} "
        f"and {args.support_output.relative_to(REPO_ROOT) if args.support_output.is_relative_to(REPO_ROOT) else args.support_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
