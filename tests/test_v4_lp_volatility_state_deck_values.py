from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v4_lp_volatility_state_deck_values import (
    render_v4_lp_volatility_state_deck_values,
)


def _rows() -> list[dict[str, object]]:
    rows = []
    for outcome, interaction in (
        ("near_log1p_incumbent_actions", -0.078),
        ("late_log1p_first_active_origins", 0.318),
    ):
        rows.append(
            {
                "record_type": "v4_lp_volatility_state_regression",
                "sample_variant": "primary_nonzero_180",
                "state_window_days": 30,
                "outcome": outcome,
                "main_effect_per_10pp_at_mean_state": 0.16,
                "main_p_value": 0.001,
                "interaction_per_10pp_per_1sd_volatility": interaction,
                "interaction_standard_error": 0.04,
                "interaction_holm_p_value": 0.005,
                "low_state_effect_per_10pp": -0.158,
                "low_state_p_value": 0.001,
                "low_state_ci_upper": -0.08,
                "high_state_effect_per_10pp": 0.478,
                "high_state_p_value": 0.001,
                "high_state_ci_lower": 0.36,
                "n_observations": 1107,
                "date_clusters": 223,
            }
        )
    for index, candidate in enumerate(("DAI", "USDC", "USDT", "WBTC", "WETH")):
        rows.append(
            {
                "record_type": "v4_lp_volatility_state_leave_one_candidate_out",
                "excluded_candidate": candidate,
                "interaction_per_10pp_per_1sd_volatility": 0.09 + 0.02 * index,
                "interaction_p_value": 0.001,
            }
        )
    return rows


def test_volatility_state_deck_values_render_headline_and_robustness() -> None:
    rendered = render_v4_lp_volatility_state_deck_values(pd.DataFrame(_rows()))
    assert "\\VFourVolStateLateInteractionCoef}{$+0.318^{***}$}" in rendered
    assert "\\VFourVolStateLateHighCoef}{$+0.478^{***}$}" in rendered
    assert "\\VFourVolStateLeaveOneMinCoef}{$+0.090^{***}$}" in rendered


def test_volatility_state_deck_values_reject_reversed_entry_interaction() -> None:
    rows = _rows()
    rows[1]["interaction_per_10pp_per_1sd_volatility"] = -0.1
    with pytest.raises(ValueError, match="headline"):
        render_v4_lp_volatility_state_deck_values(pd.DataFrame(rows))
