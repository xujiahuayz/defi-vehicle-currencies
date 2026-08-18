from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v4_flash_gap_flow_interactions import (
    render_v4_flash_gap_flow_interactions,
)


def _row(
    *,
    flash_predictor: str,
    outcome: str,
    coefficient: float,
    standard_error: float,
    p_value: float,
) -> dict[str, object]:
    return {
        "horizon_days": 120,
        "flash_predictor": flash_predictor,
        "outcome": outcome,
        "term": f"route_capital_gap_5_x_{flash_predictor}",
        "coefficient": coefficient,
        "standard_error": standard_error,
        "p_value": p_value,
        "n_observations": 1209,
        "date_clusters": 403,
        "fixed_effects": "candidate_address+origin_date",
        "activity_controls": "controls",
    }


def _complete_rows() -> list[dict[str, object]]:
    predictors = (
        "internal_tx_share",
        "multi_leg_tx_share",
        "netting_reduction_share",
    )
    outcomes = (
        "future_log1p_gross_lp_flow_usd",
        "future_log1p_add_lp_flow_usd",
        "future_log1p_remove_lp_flow_usd",
    )
    rows = []
    for predictor_index, predictor in enumerate(predictors):
        for outcome_index, outcome in enumerate(outcomes):
            rows.append(
                _row(
                    flash_predictor=predictor,
                    outcome=outcome,
                    coefficient=10.0 * (predictor_index + 1) * (outcome_index + 1),
                    standard_error=1.0,
                    p_value=0.009 if predictor_index == 0 else 0.04,
                )
            )
    return rows


def test_v4_flash_gap_flow_table_scales_log_outcomes() -> None:
    rendered = render_v4_flash_gap_flow_interactions(pd.DataFrame(_complete_rows()))

    assert "Stable gap $\\times$ internal same-candidate share" in rendered
    assert "Gross LP flow (log pts)" in rendered
    assert "Remove-side LP flow (log pts)" in rendered
    assert "$+0.100^{***}$" in rendered
    assert "$+0.900^{**}$" in rendered
    assert "1,209 / 403" in rendered


def test_v4_flash_gap_flow_table_rejects_incomplete_grid() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="incomplete"):
        render_v4_flash_gap_flow_interactions(pd.DataFrame(rows))
