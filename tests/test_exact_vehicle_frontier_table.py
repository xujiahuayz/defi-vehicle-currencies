from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.tabulate.render_exact_vehicle_frontier import (
    render_exact_vehicle_frontier,
    render_values,
)


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "output/exhibits/exact_vehicle_frontier_monthly.jsonl"


def test_exact_frontier_table_and_values_are_bound_to_the_result() -> None:
    results = pd.read_json(RESULTS, lines=True)
    table = render_exact_vehicle_frontier(results)
    values = render_values(results)
    assert "Same vehicle, all exact venues" in table
    assert "Full-set minus realised stablecoin share" in table
    assert "Panel A. Coverage and quote validation" in table
    assert "Mapped chosen paths reproduced within 1 bp" in table
    assert "\\ExactFrontierSameVehicleShare" in values
    assert "\\ExactFrontierStableChange" in values
    assert "\\ExactFrontierExtremeRoutes" in values
    assert "\\ExactFrontierMinimumInput}{\\$100}" in values
    assert "\\ExactFrontierGainThreshold}{1 bp}" in values
    assert "\\ExactFrontierImpactLimit}{5\\%}" in values
