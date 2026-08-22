from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.render_capital_price_transmission import (
    render_capital_price_transmission,
)


ROOT = Path(__file__).resolve().parents[1]


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    choice = pd.read_json(
        ROOT / "output/exhibits/contestable_vehicle_choice.jsonl", lines=True
    )
    crossing = pd.read_json(
        ROOT / "output/exhibits/price_rank_crossing.jsonl", lines=True
    )
    executability = pd.read_json(
        ROOT / "output/exhibits/eth_stress_executability.jsonl", lines=True
    )
    return choice, crossing, executability


def test_compact_transmission_table_uses_registered_models() -> None:
    choice, crossing, executability = _inputs()
    rendered = render_capital_price_transmission(choice, crossing, executability)

    assert "Panel A. Full-range capital and size-specific exact output" in rendered
    assert "$+19.10^{***}$" in rendered
    assert "$(2.90)$" in rendered
    assert "24,313" in rendered
    assert "Ordered endpoint pairs & \\multicolumn{2}{c}{915}" in rendered
    assert "Pair and calendar-month fixed effects" in rendered
    assert "Panel B. Route retention inside established endpoint pairs" in rendered
    assert "$+10.13^{***}$" in rendered
    assert "$+2.77^{***}$" in rendered
    assert "Panel C. Route allocation when exact-price leadership changes" in rendered
    assert "$+3.70^{**}$" in rendered
    assert "$-28.98^{***}$" in rendered
    assert "17,778" in rendered
    assert "Crossing-event fixed effects & No & Yes" in rendered


def test_compact_transmission_table_rejects_mismatched_choice_sample() -> None:
    choice, crossing, executability = _inputs()
    mask = (
        choice["record_type"].eq("contestable_vehicle_choice_regression")
        & choice["model_id"].eq("exclusive_retention_price_v2_capital")
    )
    choice.loc[mask, "observations"] = 1

    with pytest.raises(ValueError, match="same observations"):
        render_capital_price_transmission(choice, crossing, executability)


def test_compact_transmission_table_rejects_wrong_capital_to_output_effects() -> None:
    choice, crossing, executability = _inputs()
    mask = (
        executability["record_type"].eq("eth_stress_executability_regression")
        & executability["model_id"].eq(
            "m4_output_advantage_conditioned_on_depth"
        )
        & executability["predictor"].eq("stable_v2_capital_advantage_10pp")
    )
    executability.loc[mask, "fixed_effects"] = "ordered_pair+calendar_date"

    with pytest.raises(ValueError, match="pair and calendar-month effects"):
        render_capital_price_transmission(choice, crossing, executability)
