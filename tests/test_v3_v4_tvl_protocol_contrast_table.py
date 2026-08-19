from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_v4_tvl_protocol_contrast import (
    render_v3_v4_tvl_protocol_contrast,
)


def _row(*, horizon: int, outcome: str, effect: float) -> dict[str, object]:
    return {
        "horizon_days": horizon,
        "outcome": outcome,
        "term": "v4_x_stable_gap",
        "effect_per_10pp_stable_gap_v4_minus_v3": effect,
        "standard_error_per_10pp_stable_gap_v4_minus_v3": 0.02,
        "p_value": 0.004,
        "n_observations": 1_856,
        "date_clusters": 188,
        "fixed_effects": "candidate-date+protocol",
        "controls": "origin_log1p_tvl+origin_log1p_pool_count",
    }


def _complete_rows() -> list[dict[str, object]]:
    rows = []
    for horizon in (7, 30, 120):
        rows.append(
            _row(
                horizon=horizon,
                outcome="future_delta_log1p_tvl",
                effect=0.1 * horizon / 30,
            )
        )
        rows.append(
            _row(
                horizon=horizon,
                outcome="future_delta_log1p_pool_count",
                effect=0.05 * horizon / 30,
            )
        )
    return rows


def test_v3_v4_tvl_protocol_table_renders_common_support_grid() -> None:
    rendered = render_v3_v4_tvl_protocol_contrast(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "Reported TVL growth" in rendered
    assert "Pool-footprint growth" in rendered
    assert "120 days" in rendered
    assert "$+0.400^{***}$" in rendered
    assert "1,856 / 188" in rendered


def test_v3_v4_tvl_protocol_table_rejects_missing_cell() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        render_v3_v4_tvl_protocol_contrast(pd.DataFrame(_complete_rows()[:-1]))
