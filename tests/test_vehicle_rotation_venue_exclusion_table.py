from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.tabulate.render_vehicle_rotation_venue_exclusion import render_table


ROOT = Path(__file__).resolve().parents[1]
RESULTS = (
    ROOT
    / "output/exhibits/vehicle_transition_venue_exclusion_decomposition.jsonl"
)
SUPPORT = ROOT / "output/exhibits/vehicle_transition_venue_exclusion_support.jsonl"
TABLE = ROOT / "output/tables/vehicle_rotation_venue_exclusion.tex"


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_json(RESULTS, lines=True), pd.read_json(SUPPORT, lines=True)


def test_checked_in_venue_exclusion_table_matches_renderer() -> None:
    results, support = _inputs()
    assert TABLE.read_text(encoding="utf-8") == render_table(results, support)


def test_venue_exclusion_table_reports_mass_and_all_components() -> None:
    results, support = _inputs()
    rendered = render_table(results, support)
    assert "Panel A. Route count" in rendered
    assert "Panel B. Routed value" in rendered
    assert rendered.count("Excluding Uniswap v4") == 2
    assert rendered.count("Excluding Uniswap v3") == 2
    assert rendered.count("Excluding Curve") == 2
    assert "All venues & $+25.48$ & $-0.13$" in rendered
    assert "Excluding Uniswap v4 & $+6.54$ & $-1.06$" in rendered
    assert "Excluding Uniswap v4 & $+31.34$ & $-1.44$" in rendered
    assert "Uniswap v2/v3 and SushiSwap v2 & $+21.74$ & $-0.69$" in rendered
    assert "Retained activity [\\%]" in rendered
    assert "Note:" not in rendered
    assert r"\begin{minipage}" not in rendered
