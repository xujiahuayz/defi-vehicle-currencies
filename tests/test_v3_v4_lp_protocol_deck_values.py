from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v3_v4_lp_protocol_deck_values import (
    render_v3_v4_lp_protocol_deck_values,
)


def _row(
    *,
    outcome: str,
    effect: float,
    standard_error: float,
    p_value: float,
) -> dict[str, object]:
    return {
        "analysis_status": "exploratory_protocol_contrast",
        "record_type": "v3_v4_lp_protocol_contrast",
        "horizon_days": 120,
        "outcome": outcome,
        "term": "v4_x_stable_gap",
        "effect_per_10pp_stable_gap_v4_minus_v3": effect,
        "standard_error_per_10pp_stable_gap_v4_minus_v3": standard_error,
        "p_value": p_value,
        "n_observations": 5198,
        "date_clusters": 522,
    }


def _complete_rows() -> list[dict[str, object]]:
    return [
        _row(
            outcome="future_log1p_total_lp_actions",
            effect=0.320,
            standard_error=0.013,
            p_value=0.001,
        ),
        _row(
            outcome="future_log1p_total_origin_count",
            effect=0.115,
            standard_error=0.010,
            p_value=0.001,
        ),
    ]


def test_v3_v4_lp_protocol_deck_values_render_headline() -> None:
    rendered = render_v3_v4_lp_protocol_deck_values(pd.DataFrame(_complete_rows()))

    assert "\\VThreeVFourLpProtocolRows" in rendered
    assert "\\VThreeVFourLpActionLongCoef}{$+0.320$ log pts}" in rendered
    assert "\\VThreeVFourLpOriginLongCoef}{$+0.115$ log pts}" in rendered


def test_v3_v4_lp_protocol_deck_values_reject_wrong_direction() -> None:
    rows = _complete_rows()
    rows[0]["effect_per_10pp_stable_gap_v4_minus_v3"] = -0.320
    with pytest.raises(ValueError, match="headline"):
        render_v3_v4_lp_protocol_deck_values(pd.DataFrame(rows))
