from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v3_v4_tvl_protocol_deck_values import (
    render_v3_v4_tvl_protocol_deck_values,
)


def _row(*, outcome: str, effect: float, p_value: float = 0.001) -> dict[str, object]:
    return {
        "analysis_status": "exploratory_protocol_contrast",
        "horizon_days": 120,
        "outcome": outcome,
        "effect_per_10pp_stable_gap_v4_minus_v3": effect,
        "standard_error_per_10pp_stable_gap_v4_minus_v3": 0.02,
        "p_value": p_value,
        "n_observations": 1_856,
        "date_clusters": 188,
    }


def _complete_rows() -> list[dict[str, object]]:
    return [
        _row(outcome="future_delta_log1p_tvl", effect=0.637),
        _row(outcome="future_delta_log1p_pool_count", effect=0.275),
    ]


def test_v3_v4_tvl_protocol_deck_values_render_headline() -> None:
    rendered = render_v3_v4_tvl_protocol_deck_values(pd.DataFrame(_complete_rows()))

    assert "\\VThreeVFourTvlGrowthLongCoef" in rendered
    assert "\\VThreeVFourPoolFootprintLongCoef" in rendered
    assert "$+0.637$ log pts" in rendered
    assert "1{,}856" in rendered


def test_v3_v4_tvl_protocol_deck_values_reject_wrong_direction() -> None:
    rows = _complete_rows()
    rows[0]["effect_per_10pp_stable_gap_v4_minus_v3"] = -0.637
    with pytest.raises(ValueError, match="headline no longer holds"):
        render_v3_v4_tvl_protocol_deck_values(pd.DataFrame(rows))
