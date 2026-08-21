from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.build_pair_turnover_lifecycle_values import (
    render_pair_turnover_lifecycle_values,
)


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "output/exhibits/vehicle_transition_pair_lifecycle.jsonl"
DECOMPOSITION = (
    ROOT / "output/exhibits/vehicle_transition_pair_decomposition.jsonl"
)
VALUES = ROOT / "output/exhibits/vehicle_transition_pair_lifecycle_values.tex"


def _render() -> str:
    return render_pair_turnover_lifecycle_values(
        pd.read_json(LIFECYCLE, lines=True),
        pd.read_json(DECOMPOSITION, lines=True),
    )


def test_checked_in_pair_lifecycle_values_equal_renderer() -> None:
    assert VALUES.read_text(encoding="utf-8") == _render()


def test_pair_lifecycle_values_surface_entry_and_exact_offsets() -> None:
    rendered = _render()
    expected = (
        r"\newcommand{\PairLifecycleCountEntry}{$+20.1$ pp}",
        r"\newcommand{\PairLifecycleCountReactivationTable}{$+0.20$ pp}",
        r"\newcommand{\PairLifecycleCountRoleTurnoverTable}{$-0.77$ pp}",
        r"\newcommand{\PairLifecycleCountExitTable}{$-1.73$ pp}",
        r"\newcommand{\PairLifecycleCountOffset}{$-2.3$ pp}",
        r"\newcommand{\PairLifecycleCountNetTable}{$+17.79$ pp}",
        r"\newcommand{\PairLifecycleCountEntryShare}{78.9\%}",
        r"\newcommand{\PairLifecycleValueEntry}{$+21.9$ pp}",
        r"\newcommand{\PairLifecycleValueReactivationTable}{$+0.04$ pp}",
        r"\newcommand{\PairLifecycleValueRoleTurnoverTable}{$-1.72$ pp}",
        r"\newcommand{\PairLifecycleValueExitTable}{$-1.10$ pp}",
        r"\newcommand{\PairLifecycleValueOffset}{$-2.8$ pp}",
        r"\newcommand{\PairLifecycleValueNetTable}{$+19.16$ pp}",
        r"\newcommand{\PairLifecycleValueEntryShare}{51.2\%}",
    )
    for macro in expected:
        assert macro in rendered


def test_pair_lifecycle_values_reject_nonadditive_groups() -> None:
    lifecycle = pd.read_json(LIFECYCLE, lines=True)
    mask = (
        lifecycle["metric"].eq("count_share")
        & lifecycle["aggregation_level"].eq("lifecycle_group")
        & lifecycle["lifecycle_category"].eq("endpoint_pair_reactivated")
    )
    lifecycle.loc[mask, "contribution_pp"] += 1.0
    with pytest.raises(ValueError, match="do not add"):
        render_pair_turnover_lifecycle_values(
            lifecycle,
            pd.read_json(DECOMPOSITION, lines=True),
        )
