from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_v4_lp_flow_protocol_contrast import (
    render_v3_v4_lp_flow_protocol_contrast,
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
        "activity_controls": (
            "origin_log1p_gross_lp_flow_usd+origin_log1p_add_lp_flow_usd+"
            "origin_log1p_remove_lp_flow_usd+origin_log1p_sender_days"
        ),
    }


def _complete_rows() -> list[dict[str, object]]:
    rows = []
    for horizon_index, horizon in enumerate((7, 30, 120), start=1):
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_log1p_gross_lp_flow_usd",
                effect=0.01 * horizon_index,
                standard_error=0.01,
                p_value=0.11,
            )
        )
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_log1p_add_lp_flow_usd",
                effect=-0.01 * horizon_index,
                standard_error=0.02,
                p_value=0.20,
            )
        )
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_log1p_remove_lp_flow_usd",
                effect=0.02 * horizon_index,
                standard_error=0.02,
                p_value=0.04,
            )
        )
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_narrow_medium_flow_value_share",
                effect=0.03 * horizon_index,
                standard_error=0.02,
                p_value=0.03,
            )
        )
        rows.append(
            _row(
                horizon_days=horizon,
                outcome="future_broad_flow_value_share",
                effect=-0.03 * horizon_index,
                standard_error=0.02,
                p_value=0.03,
            )
        )
    return rows


def test_v3_v4_lp_flow_protocol_contrast_table_renders_grid() -> None:
    rendered = render_v3_v4_lp_flow_protocol_contrast(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "Gross LP flow" in rendered
    assert "Add-side flow" in rendered
    assert "Remove-side flow" in rendered
    assert "Narrow/medium flow share" in rendered
    assert "Broad flow share" in rendered
    assert "$+0.060^{**}$" in rendered
    assert "$-0.090^{**}$" in rendered
    assert "5,198 / 522" in rendered


def test_v3_v4_lp_flow_protocol_contrast_table_rejects_incomplete_grid() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="incomplete"):
        render_v3_v4_lp_flow_protocol_contrast(pd.DataFrame(rows))
