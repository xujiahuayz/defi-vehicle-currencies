from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.render_network_centrality_robustness import (
    TABLE_NOTE,
    render_table,
    render_values,
)


ROOT = Path(__file__).resolve().parents[1]
EXHIBITS = ROOT / "output" / "exhibits"
TABLES = ROOT / "output" / "tables"


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    results = pd.read_json(
        EXHIBITS / "network_centrality_robustness.jsonl", lines=True
    )
    support = pd.read_json(
        EXHIBITS / "network_centrality_robustness_support.jsonl", lines=True
    )
    return results, support


def test_checked_in_centrality_outputs_equal_renderer() -> None:
    results, support = _inputs()

    assert (TABLES / "network_centrality_robustness.tex").read_text(
        encoding="utf-8"
    ) == render_table(results, support)
    assert (EXHIBITS / "network_centrality_paper_values.tex").read_text(
        encoding="utf-8"
    ) == render_values(results, support)


def test_table_exposes_level_weight_coverage_and_stable_core_results() -> None:
    results, support = _inputs()
    table = render_table(results, support)

    assert "Count & WETH & 8.3 & 1 & 17.4 & 1" in table
    assert "USD value & WETH & 24.0 & 1 & 15.5 & 3" in table
    assert "USD value & USDC & 22.1 & 2 & 31.0 & 1" in table
    assert "USD value & USDT & 15.7 & 3 & 30.3 & 2" in table
    assert "Sampled date & 2024 H1 & 1 & 2 & 3 & 0.929" in table
    assert "Sampled date & 2026 H1 & 3 & 1 & 2 & 0.938" in table
    assert "Venue & 2024 H1 & 1--4 & 1--2 & 2--3 & 0.762" in table
    assert "Venue & 2026 H1 & 3--4 & 1--2 & 1--2 & 0.857" in table
    assert "WETH & 25.2 & 1" in table
    assert "USDC & 20.4 & 2" in table
    assert "USDT & 13.3 & 3" in table


def test_generated_values_expose_decisive_rank_changes() -> None:
    results, support = _inputs()
    values = render_values(results, support)

    assert r"\newcommand{\NetworkECValueWETHEndRank}{3}" in values
    assert r"\newcommand{\NetworkECValueUSDCEndRank}{1}" in values
    assert r"\newcommand{\NetworkECValueUSDTEndRank}{2}" in values
    assert r"\newcommand{\NetworkECCountWETHEndRank}{1}" in values
    assert r"\newcommand{\NetworkECNoStableCoreWETHRank}{1}" in values
    assert r"\newcommand{\NetworkECNoStableCoreUSDCRank}{2}" in values
    assert r"\newcommand{\NetworkECNoStableCoreUSDTRank}{3}" in values


def test_note_states_scope_without_a_uniform_robustness_inference() -> None:
    assert "depends on the edge weight" in TABLE_NOTE
    assert "stablecoin core" in TABLE_NOTE
    audience_text = TABLE_NOTE.lower()
    for banned in ("candidate", "screen", "claim", "diagnos", "workflow"):
        assert banned not in audience_text


def test_table_rejects_missing_omission_family() -> None:
    results, support = _inputs()
    support = support.loc[
        ~(
            support["period"].eq("2026 H1")
            & support["scenario_kind"].eq("leave_one_venue_out")
            & support["weight"].eq("leg_value_usd")
        )
    ]

    with pytest.raises(ValueError, match="lacks a requested omission family"):
        render_table(results, support)
