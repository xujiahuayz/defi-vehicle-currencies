from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v4_flash_lp_deck_values import (
    render_v4_flash_lp_deck_values,
)


def _row(
    *,
    predictor: str,
    outcome: str,
    effect: float,
    p_value: float = 0.001,
) -> dict[str, object]:
    return {
        "analysis_status": "exploratory_mechanism",
        "record_type": "v4_flash_lp_mechanism_regression",
        "horizon_days": 120,
        "predictor": predictor,
        "outcome": outcome,
        "effect_per_10pp_predictor": effect,
        "standard_error": 0.01,
        "p_value": p_value,
        "n_observations": 2015,
        "date_clusters": 403,
    }


def _complete_rows() -> list[dict[str, object]]:
    return [
        _row(
            predictor="internal_tx_share",
            outcome="future_log1p_gross_lp_flow_usd",
            effect=0.035,
            p_value=0.08,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_delta_log1p_tvl_usd",
            effect=0.265,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_log1p_lp_actions",
            effect=0.071,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_narrow_medium_action_share",
            effect=-0.024,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_wide_very_wide_action_share",
            effect=0.029,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_narrow_medium_flow_value_share",
            effect=0.014,
        ),
        _row(
            predictor="internal_tx_share",
            outcome="future_broad_flow_value_share",
            effect=-0.014,
        ),
        _row(
            predictor="multi_leg_tx_share",
            outcome="future_narrow_medium_action_share",
            effect=-0.019,
        ),
        _row(
            predictor="multi_leg_tx_share",
            outcome="future_wide_very_wide_action_share",
            effect=0.018,
        ),
        _row(
            predictor="multi_leg_tx_share",
            outcome="future_narrow_medium_flow_value_share",
            effect=0.012,
        ),
        _row(
            predictor="multi_leg_tx_share",
            outcome="future_broad_flow_value_share",
            effect=-0.012,
        ),
        _row(
            predictor="netting_reduction_share",
            outcome="future_narrow_medium_flow_value_share",
            effect=0.012,
        ),
        _row(
            predictor="netting_reduction_share",
            outcome="future_broad_flow_value_share",
            effect=-0.012,
        ),
    ]


def test_v4_flash_lp_deck_values_render_range_reallocation() -> None:
    rendered = render_v4_flash_lp_deck_values(pd.DataFrame(_complete_rows()))

    assert "\\VFourFlashInternalNarrowLongCoef" in rendered
    assert "\\VFourFlashInternalTvlLongCoef" in rendered
    assert "\\VFourFlashInternalActionsLongCoef" in rendered
    assert "$+0.265^{***}$" in rendered
    assert "$+0.071^{***}$" in rendered
    assert "\\VFourFlashInternalWideLongCoef" in rendered
    assert "\\VFourFlashInternalFlowNarrowLongCoef" in rendered
    assert "\\VFourFlashNettingFlowBroadLongCoef" in rendered
    assert "\\VFourFlashMultilegWideLongCoef" in rendered
    assert "$-2.40$ pp" in rendered
    assert "$+2.90$ pp" in rendered
    assert "$+1.40$ pp" in rendered


def test_v4_flash_lp_deck_values_reject_missing_wide_result() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one row"):
        render_v4_flash_lp_deck_values(pd.DataFrame(rows))


def test_v4_flash_lp_deck_values_reject_wrong_range_direction() -> None:
    rows = _complete_rows()
    rows[1]["effect_per_10pp_predictor"] = -0.029
    with pytest.raises(ValueError, match="headline no longer holds"):
        render_v4_flash_lp_deck_values(pd.DataFrame(rows))
