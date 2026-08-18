from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_v4_lp_protocol_contrast import (
    render_v3_v4_lp_protocol_contrast,
)


def _row(
    *,
    horizon_days: int,
    outcome: str,
    effect: float,
    standard_error: float,
    p_value: float,
) -> dict[str, object]:
    return {
        "horizon_days": horizon_days,
        "outcome": outcome,
        "term": "v4_x_stable_gap",
        "effect_per_10pp_stable_gap_v4_minus_v3": effect,
        "standard_error_per_10pp_stable_gap_v4_minus_v3": standard_error,
        "p_value": p_value,
        "n_observations": 5198,
        "date_clusters": 522,
        "fixed_effects": "candidate_date+protocol",
        "activity_controls": "origin_log1p_total_lp_actions+origin_log1p_total_origin_count",
    }


def _complete_rows() -> list[dict[str, object]]:
    rows = []
    for horizon_index, horizon in enumerate((7, 30, 120), start=1):
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_log1p_total_lp_actions",
                effect=0.1 * horizon_index,
                standard_error=0.01,
                p_value=0.009,
            )
        )
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_log1p_total_origin_count",
                effect=0.05 * horizon_index,
                standard_error=0.02,
                p_value=0.04,
            )
        )
    return rows


def test_v3_v4_lp_protocol_contrast_table_renders_grid() -> None:
    rendered = render_v3_v4_lp_protocol_contrast(pd.DataFrame(_complete_rows()))

    assert "LP actions" in rendered
    assert "Active origins" in rendered
    assert "$+0.300^{***}$" in rendered
    assert "$+0.150^{**}$" in rendered
    assert "5,198 / 522" in rendered


def test_v3_v4_lp_protocol_contrast_table_rejects_incomplete_grid() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="incomplete"):
        render_v3_v4_lp_protocol_contrast(pd.DataFrame(rows))
