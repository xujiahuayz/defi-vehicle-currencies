from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.tabulate.render_pair_composition_materiality import render_table


ROOT = Path(__file__).resolve().parents[1]
INPUT = (
    ROOT
    / "output/exhibits/vehicle_transition_pair_materiality_decomposition.jsonl"
)
TABLE = ROOT / "output/tables/pair_composition_materiality.tex"


def test_checked_in_materiality_table_matches_renderer() -> None:
    results = pd.read_json(INPUT, lines=True)
    rendered = render_table(results)
    assert TABLE.read_text(encoding="utf-8") == rendered


def test_materiality_table_is_compact_clear_and_complete() -> None:
    rendered = render_table(pd.read_json(INPUT, lines=True))
    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "Stablecoin share [\\%]" in rendered
    assert "Change [pp]" in rendered
    assert rendered.count("routes &") == 2
    assert rendered.count("value &") == 2
    assert (
        r"$\geq 10$ routes & 21.77 & 47.11 & $+25.34$ & $-0.24$"
        in rendered
    )
    assert (
        r"$\geq \$50{,}000$ value & 37.73 & 80.05 & $+42.32$ & $+0.61$"
        in rendered
    )
    assert "Note:" not in rendered
    assert r"\begin{minipage}" not in rendered
