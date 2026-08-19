from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v3_v4_lp_flow_protocol_deck_values import (
    render_v3_v4_lp_flow_protocol_deck_values,
)


def _row(
    *,
    outcome: str,
    effect: float,
    standard_error: float,
    p_value: float,
) -> dict[str, object]:
    return {
        "activity_controls": "same-protocol current flow controls",
        "analysis_status": "exploratory_protocol_contrast",
        "date_clusters": 522,
        "effect_per_10pp_stable_gap_v4_minus_v3": effect,
        "fixed_effects": "candidate_date+protocol",
        "horizon_days": 120,
        "n_observations": 5198,
        "outcome": outcome,
        "p_value": p_value,
        "record_type": "v3_v4_lp_flow_protocol_contrast",
        "standard_error_per_10pp_stable_gap_v4_minus_v3": standard_error,
        "term": "v4_x_stable_gap",
    }


def _complete_rows() -> list[dict[str, object]]:
    return [
        _row(
            outcome="future_log1p_gross_lp_flow_usd",
            effect=0.027,
            standard_error=0.022,
            p_value=0.224,
        ),
        _row(
            outcome="future_log1p_add_lp_flow_usd",
            effect=0.011,
            standard_error=0.023,
            p_value=0.644,
        ),
        _row(
            outcome="future_log1p_remove_lp_flow_usd",
            effect=0.044,
            standard_error=0.022,
            p_value=0.044,
        ),
    ]


def test_v3_v4_lp_flow_protocol_deck_values_render_turnover_headline() -> None:
    rendered = render_v3_v4_lp_flow_protocol_deck_values(
        pd.DataFrame(_complete_rows())
    )

    assert "\\VThreeVFourLpFlowProtocolRows" in rendered
    assert "\\VThreeVFourLpFlowGrossLongCoef}{$+0.027$ log pts}" in rendered
    assert "\\VThreeVFourLpFlowAddLongCoef}{$+0.011$ log pts}" in rendered
    assert "\\VThreeVFourLpFlowRemoveLongCoef}{$+0.044$ log pts}" in rendered


def test_v3_v4_lp_flow_protocol_deck_values_reject_broad_add_flow() -> None:
    rows = _complete_rows()
    rows[1]["effect_per_10pp_stable_gap_v4_minus_v3"] = 0.120
    with pytest.raises(ValueError, match="headline"):
        render_v3_v4_lp_flow_protocol_deck_values(pd.DataFrame(rows))
