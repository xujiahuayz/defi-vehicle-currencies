from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v4_flash_lp_mechanism import (
    render_v4_flash_lp_mechanism,
)


def _row(
    *,
    predictor: str,
    outcome: str,
    coefficient: float,
    standard_error: float,
    p_value: float,
) -> dict[str, object]:
    return {
        "horizon_days": 120,
        "predictor": predictor,
        "outcome": outcome,
        "coefficient": coefficient,
        "standard_error": standard_error,
        "p_value": p_value,
        "n_observations": 2015,
        "date_clusters": 403,
        "fixed_effects": "candidate+origin_date",
        "controls": "controls",
    }


def _complete_rows() -> list[dict[str, object]]:
    predictors = (
        "internal_tx_share",
        "multi_leg_tx_share",
        "netting_reduction_share",
    )
    outcomes = (
        "future_log1p_gross_lp_flow_usd",
        "future_delta_log1p_tvl_usd",
        "future_log1p_lp_actions",
        "future_narrow_medium_flow_value_share",
        "future_broad_flow_value_share",
        "future_narrow_medium_action_share",
        "future_wide_very_wide_action_share",
    )
    rows = []
    for predictor_index, predictor in enumerate(predictors):
        for outcome_index, outcome in enumerate(outcomes):
            rows.append(
                _row(
                    predictor=predictor,
                    outcome=outcome,
                    coefficient=0.1 * (predictor_index + 1) * (outcome_index + 1),
                    standard_error=0.01 * (outcome_index + 1),
                    p_value=0.009 if outcome_index == 0 else 0.04,
                )
            )
    return rows


def test_v4_flash_lp_mechanism_table_scales_coefficients() -> None:
    rendered = render_v4_flash_lp_mechanism(pd.DataFrame(_complete_rows()))

    assert "Internal same-asset share" in rendered
    assert "Multi-leg transaction share" in rendered
    assert "Gross-to-net reduction share" in rendered
    assert "Future LP flow (log pts)" in rendered
    assert "Flow narrow/medium (pp)" in rendered
    assert "Flow broad (pp)" in rendered
    assert "Action narrow/medium (pp)" in rendered
    assert "Action wide/very-wide (pp)" in rendered
    assert "$+0.010^{***}$" in rendered
    assert "$+7.000^{**}$" in rendered
    assert "2,015 / 403" in rendered


def test_v4_flash_lp_mechanism_table_rejects_incomplete_grid() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="incomplete"):
        render_v4_flash_lp_mechanism(pd.DataFrame(rows))
