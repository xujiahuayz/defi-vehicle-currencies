from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.render_capital_price_transmission import (
    render_capital_price_transmission,
)


ROOT = Path(__file__).resolve().parents[1]


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    choice = pd.read_json(
        ROOT / "output/exhibits/contestable_vehicle_choice.jsonl", lines=True
    )
    crossing = pd.read_json(
        ROOT / "output/exhibits/price_rank_crossing.jsonl", lines=True
    )
    return choice, crossing


def test_compact_transmission_table_uses_registered_models() -> None:
    choice, crossing = _inputs()
    rendered = render_capital_price_transmission(choice, crossing)

    assert "Panel A. Route retention inside established endpoint pairs" in rendered
    assert "$+10.13^{***}$" in rendered
    assert "$+2.77^{***}$" in rendered
    assert "Panel B. Route allocation when exact-price leadership changes" in rendered
    assert "$+3.70^{**}$" in rendered
    assert "$-28.98^{***}$" in rendered
    assert "17,778" in rendered
    assert "Crossing-event fixed effects & No & Yes" in rendered


def test_compact_transmission_table_rejects_mismatched_choice_sample() -> None:
    choice, crossing = _inputs()
    mask = (
        choice["record_type"].eq("contestable_vehicle_choice_regression")
        & choice["model_id"].eq("exclusive_retention_price_v2_capital")
    )
    choice.loc[mask, "observations"] = 1

    with pytest.raises(ValueError, match="same observations"):
        render_capital_price_transmission(choice, crossing)
