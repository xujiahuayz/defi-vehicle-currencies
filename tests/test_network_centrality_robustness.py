from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest

from scripts.analyze.run_network_centrality_robustness import (
    eigenvector_scores,
    period_label,
    rank_stability,
    route_metrics,
    without_stable_stable_edges,
    weighted_graph,
)


def test_period_label_splits_calendar_half_years() -> None:
    assert period_label("20240115") == "2024 H1"
    assert period_label("20240715") == "2024 H2"


def test_route_metrics_allow_more_than_one_intermediary_per_route() -> None:
    positions = pd.DataFrame(
        [
            {
                "day": "20240115",
                "tx_hash": "0x1",
                "component_id": 0,
                "token": "0xb",
            },
            {
                "day": "20240115",
                "tx_hash": "0x2",
                "component_id": 0,
                "token": "0xd",
            },
            {
                "day": "20240115",
                "tx_hash": "0x2",
                "component_id": 0,
                "token": "0xb",
            },
        ]
    )
    metrics = route_metrics(positions)

    assert len(positions) == 3
    assert metrics["0xb"]["intermediary_positions"] == 2
    assert metrics["0xb"]["route_participation_share"] == pytest.approx(1.0)
    assert metrics["0xd"]["intermediary_position_share"] == pytest.approx(1 / 3)


def test_weighted_graph_aggregates_directed_edges() -> None:
    edges = pd.DataFrame(
        {
            "left": ["a", "a", "b"],
            "right": ["b", "b", "a"],
            "leg_count": [2, 3, 4],
            "leg_value_usd": [20.0, 30.0, 40.0],
        }
    )

    graph = weighted_graph(edges, "leg_count")

    assert graph["a"]["b"]["weight"] == 5
    assert graph["b"]["a"]["weight"] == 4


def test_stable_core_scope_removes_only_stable_to_stable_edges() -> None:
    usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    edges = pd.DataFrame(
        {
            "left": [usdc, usdc, weth],
            "right": [usdt, weth, usdt],
            "leg_count": [1, 2, 3],
            "leg_value_usd": [10.0, 20.0, 30.0],
        }
    )

    selected = without_stable_stable_edges(edges)

    assert list(zip(selected["left"], selected["right"], strict=True)) == [
        (usdc, weth),
        (weth, usdt),
    ]


def test_eigenvector_scores_are_normalized_and_keep_direction() -> None:
    graph = nx.DiGraph()
    graph.add_weighted_edges_from(
        [
            ("a", "b", 8.0),
            ("b", "a", 2.0),
            ("b", "c", 5.0),
            ("c", "b", 1.0),
            ("c", "a", 3.0),
            ("a", "c", 1.0),
        ]
    )

    scores = eigenvector_scores(graph)

    assert scores["directed_scc"].all()
    assert scores["eigenvector_in_share"].sum() == pytest.approx(1.0)
    assert scores["eigenvector_out_share"].sum() == pytest.approx(1.0)
    assert scores["eigenvector_two_sided_share"].sum() == pytest.approx(1.0)
    assert scores["eigenvector_undirected_share"].sum() == pytest.approx(1.0)
    assert not scores["eigenvector_in_share"].equals(scores["eigenvector_out_share"])


def test_rank_stability_detects_identical_and_changed_top_sets() -> None:
    baseline = pd.DataFrame(
        {"token": ["a", "b", "c"], "score": [3.0, 2.0, 1.0]}
    )
    same = baseline.copy()
    reversed_frame = pd.DataFrame(
        {"token": ["a", "b", "c"], "score": [1.0, 2.0, 3.0]}
    )

    tau, jaccard, common = rank_stability(baseline, same, "score", top_n=1)
    reversed_tau, reversed_jaccard, _ = rank_stability(
        baseline, reversed_frame, "score", top_n=1
    )

    assert tau == pytest.approx(1.0)
    assert jaccard == pytest.approx(1.0)
    assert common == 3
    assert reversed_tau == pytest.approx(-1.0)
    assert reversed_jaccard == pytest.approx(0.0)
