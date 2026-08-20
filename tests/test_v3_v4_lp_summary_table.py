from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_v4_lp_summary import (
    ROWS,
    render_v3_v4_lp_summary,
)


def _frames() -> dict[str, pd.DataFrame]:
    records: dict[str, list[dict[str, object]]] = {
        "actions": [],
        "flows": [],
        "stocks": [],
    }
    for index, (family, outcome, horizon, _label, _unit) in enumerate(ROWS, start=1):
        records[family].append(
            {
                "horizon_days": horizon,
                "outcome": outcome,
                "term": "v4_x_stable_gap",
                "effect_per_10pp_stable_gap_v4_minus_v3": 0.01 * index,
                "standard_error_per_10pp_stable_gap_v4_minus_v3": 0.001 * index,
                "p_value": 0.005,
                "n_observations": 1000 + index,
                "date_clusters": 100 + index,
            }
        )
    return {name: pd.DataFrame(rows) for name, rows in records.items()}


def test_v3_v4_lp_summary_renders_selected_margins() -> None:
    frames = _frames()
    rendered = render_v3_v4_lp_summary(
        frames["actions"], frames["flows"], frames["stocks"]
    )
    assert "LP actions [log points]" in rendered
    assert "Narrow/medium flow share [pp]" in rendered
    assert "Reported liquidity [log points]" in rendered
    assert rendered.count("^{***}") == len(ROWS)


def test_v3_v4_lp_summary_rejects_missing_margin() -> None:
    frames = _frames()
    frames["stocks"] = frames["stocks"].iloc[:-1].copy()
    with pytest.raises(ValueError, match="expected one"):
        render_v3_v4_lp_summary(
            frames["actions"], frames["flows"], frames["stocks"]
        )
