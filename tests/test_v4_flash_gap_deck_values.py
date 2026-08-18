from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v4_flash_gap_deck_values import (
    render_v4_flash_gap_deck_values,
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
        "analysis_status": "exploratory_mechanism",
        "record_type": "v4_flash_gap_interaction_regression",
        "horizon_days": 120,
        "flash_predictor": flash_predictor,
        "outcome": outcome,
        "term": f"route_capital_gap_5_x_{flash_predictor}",
        "coefficient": coefficient,
        "standard_error": standard_error,
        "p_value": p_value,
        "n_observations": 1209,
        "date_clusters": 403,
    }


def _complete_rows() -> list[dict[str, object]]:
    return [
        _row(
            flash_predictor="internal_tx_share",
            outcome="future_delta_log1p_tvl_usd",
            coefficient=29.17,
            standard_error=7.90,
            p_value=0.001,
        ),
        _row(
            flash_predictor="internal_tx_share",
            outcome="future_log1p_lp_actions",
            coefficient=8.17,
            standard_error=2.70,
            p_value=0.004,
        ),
        _row(
            flash_predictor="internal_tx_share",
            outcome="future_wide_very_wide_action_share",
            coefficient=6.19,
            standard_error=0.66,
            p_value=0.001,
        ),
        _row(
            flash_predictor="multi_leg_tx_share",
            outcome="future_wide_very_wide_action_share",
            coefficient=4.44,
            standard_error=0.38,
            p_value=0.001,
        ),
        _row(
            flash_predictor="netting_reduction_share",
            outcome="future_wide_very_wide_action_share",
            coefficient=-4.41,
            standard_error=1.13,
            p_value=0.001,
        ),
    ]


def test_v4_flash_gap_deck_values_render_interaction_headline() -> None:
    rendered = render_v4_flash_gap_deck_values(pd.DataFrame(_complete_rows()))

    assert "\\VFourFlashGapRows" in rendered
    assert "\\VFourFlashGapInternalTvlCoef}{$+0.292$ log pts}" in rendered
    assert "\\VFourFlashGapInternalWideCoef}{$+6.190$ pp}" in rendered
    assert "\\VFourFlashGapNettingWideCoef}{$-4.410$ pp}" in rendered


def test_v4_flash_gap_deck_values_reject_wrong_netting_direction() -> None:
    rows = _complete_rows()
    rows[-1]["coefficient"] = 4.41
    with pytest.raises(ValueError, match="headline"):
        render_v4_flash_gap_deck_values(pd.DataFrame(rows))
