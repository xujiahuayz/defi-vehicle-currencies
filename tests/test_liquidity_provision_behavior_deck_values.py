from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_liquidity_provision_behavior_deck_values import (
    render_liquidity_provision_behavior_deck_values,
)


def test_liquidity_behavior_values_render_from_guarded_rows() -> None:
    rows = [
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_leader_alignment",
            "days": 100,
            "weth_capital_leader_share": 1.0,
            "stable_excess_leader_share": 0.8,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "annual_stable_allocation",
            "year": 2024,
            "stable_capital_share": 0.2,
            "stable_intermediary_route_share": 0.3,
            "stable_route_to_capital_ratio": 1.5,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "annual_stable_allocation",
            "year": 2026,
            "stable_capital_share": 0.1,
            "stable_intermediary_route_share": 0.5,
            "stable_route_to_capital_ratio": 5.0,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "level_association",
            "outcome": "intermediary_episode_share",
            "predictor": "v2_log1p_deposited_capital_usd",
            "coefficient": 0.01,
            "standard_error": 0.002,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "level_association",
            "outcome": "vehicle_excess_use_count_ratio",
            "predictor": "v2_log1p_deposited_capital_usd",
            "coefficient": 0.5,
            "standard_error": 0.04,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_route_capital_gap_change",
            "gap_name": "stable_route_capital_gap",
            "change": 0.33,
            "standard_error": 0.01,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_route_capital_gap_change",
            "gap_name": "weth_route_capital_gap",
            "change": -0.36,
            "standard_error": 0.02,
        },
    ]
    rendered = render_liquidity_provision_behavior_deck_values(pd.DataFrame(rows))
    assert "\\LiqBehWethCapitalLeaderDays" in rendered
    assert "\\LiqBehStableRouteCapitalRatioEnd" in rendered
    assert "\\LiqBehStableGapChange" in rendered
    assert "5.0\\times" in rendered
