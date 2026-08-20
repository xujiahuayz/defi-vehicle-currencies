from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v4_lp_volatility_state import (
    OUTCOMES,
    render_v4_lp_volatility_state,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "record_type": "v4_lp_volatility_state_regression",
            "sample_variant": "primary_nonzero_180",
            "state_window_days": 30,
            "outcome": outcome,
            "main_effect_per_10pp_at_mean_state": 0.16,
            "main_standard_error": 0.03,
            "main_p_value": 0.001,
            "interaction_per_10pp_per_1sd_volatility": effect,
            "interaction_standard_error": 0.04,
            "interaction_holm_p_value": 0.005,
            "n_observations": 1107,
            "date_clusters": 223,
            "fixed_effects": "candidate+origin_date",
            "controls": "activity+capital",
            "state_controls": "candidate-specific+origin-control-specific volatility slopes",
        }
        for outcome, effect in zip(OUTCOMES, (-0.078, 0.318), strict=True)
    ]


def test_volatility_state_table_renders_interaction_family() -> None:
    rendered = render_v4_lp_volatility_state(pd.DataFrame(_rows()))
    assert "lagged 30-day WETH volatility" in rendered
    assert "$-0.078^{***}$" in rendered
    assert "$+0.318^{***}$" in rendered
    assert "1,107 / 223" in rendered


def test_volatility_state_table_rejects_missing_outcome() -> None:
    with pytest.raises(ValueError, match="primary outcome"):
        render_v4_lp_volatility_state(pd.DataFrame(_rows()[:-1]))
