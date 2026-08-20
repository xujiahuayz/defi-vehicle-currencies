from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v4_lp_origin_timing_deck_values import (
    render_v4_lp_origin_timing_deck_values,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "sample_variant": "primary_nonzero_180",
            "predictor": "internal_tx_share",
            "outcome": outcome,
            "effect_per_10pp_predictor": effect,
            "standard_error_per_10pp_predictor": 0.02,
            "holm_p_value": 0.005,
            "n_observations": 1107,
            "date_clusters": 223,
        }
        for outcome, effect in (
            ("near_log1p_incumbent_actions", 0.086),
            ("late_log1p_first_active_origins", 0.153),
            ("late_log1p_incumbent_actions", 0.076),
        )
    ]


def test_origin_timing_deck_values_render_registered_results() -> None:
    rendered = render_v4_lp_origin_timing_deck_values(pd.DataFrame(_rows()))
    assert "\\VFourOriginNearIncumbentCoef}{$+0.086^{***}$}" in rendered
    assert "\\VFourOriginLateEntryCoef}{$+0.153^{***}$}" in rendered
    assert "\\VFourOriginTimingRows}{1{,}107}" in rendered


def test_origin_timing_deck_values_reject_failed_holm_result() -> None:
    rows = _rows()
    rows[1]["holm_p_value"] = 0.2
    with pytest.raises(ValueError, match="Holm"):
        render_v4_lp_origin_timing_deck_values(pd.DataFrame(rows))
