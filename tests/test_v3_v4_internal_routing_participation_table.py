from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_v3_v4_internal_routing_participation import (
    CALENDAR_VARIANTS,
    OUTCOMES,
    PRIMARY,
    STATE,
    render_v3_v4_internal_routing_participation,
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for variant in (PRIMARY, *CALENDAR_VARIANTS):
        for index, outcome in enumerate(OUTCOMES, start=1):
            rows.append(
                {
                    "record_type": "v3_v4_internal_routing_participation_regression",
                    "sample_variant": variant,
                    "outcome": outcome,
                    "v3_slope_per_10pp": -0.01 * index,
                    "v3_standard_error_per_10pp": 0.01,
                    "v4_slope_per_10pp": 0.02 * index,
                    "v4_standard_error_per_10pp": 0.01,
                    "v4_minus_v3_per_10pp": 0.03 * index,
                    "v4_minus_v3_standard_error_per_10pp": 0.01,
                    "v4_minus_v3_holm_p_value": 0.04,
                    "candidate_days": 1107,
                    "date_clusters": 223,
                }
            )
    for index, outcome in enumerate(OUTCOMES, start=1):
        rows.append(
            {
                "record_type": "v3_v4_internal_routing_volatility_regression",
                "sample_variant": STATE,
                "outcome": outcome,
                "v3_state_interaction_per_10pp_per_1sd": 0.01 * index,
                "v3_state_interaction_standard_error": 0.01,
                "v4_state_interaction_per_10pp_per_1sd": 0.03 * index,
                "v4_state_interaction_standard_error": 0.01,
                "v4_minus_v3_state_interaction_per_10pp_per_1sd": 0.02 * index,
                "v4_minus_v3_state_interaction_standard_error": 0.01,
                "v4_minus_v3_state_interaction_holm_p_value": 0.08,
            }
        )
    return rows


def test_v3_v4_internal_routing_table_renders_protocol_and_state_panels() -> None:
    rendered = render_v3_v4_internal_routing_participation(pd.DataFrame(_rows()))
    assert "Panel A. Mature common calendar" in rendered
    assert "Panel B. Interaction with persistent volatility" in rendered
    assert "Panel C. V4 minus V3 with 90-day history" in rendered
    assert "$+0.060^{**}$" in rendered
    assert "$+0.040^{*}$" in rendered
    assert "1,107 / 223" in rendered
