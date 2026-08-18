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
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "within_day_route_capital_gap_association",
            "outcome": "route_capital_gap_5",
            "predictor": "is_stable",
            "coefficient": 0.13,
            "standard_error": 0.01,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_closing",
            "horizon_days": 30,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "route_capital_gap_5",
            "coefficient": 0.06,
            "standard_error": 0.01,
            "coefficient_per_10pp_gap": 0.006,
            "standard_error_per_10pp_gap": 0.001,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_closing",
            "horizon_days": 120,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "route_capital_gap_5",
            "coefficient": 0.16,
            "standard_error": 0.01,
            "coefficient_per_10pp_gap": 0.016,
            "standard_error_per_10pp_gap": 0.001,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_closing_stable_interaction",
            "horizon_days": 30,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "stable_total_route_capital_gap_5",
            "coefficient": 0.10,
            "standard_error": 0.01,
            "coefficient_per_10pp_gap": 0.010,
            "standard_error_per_10pp_gap": 0.001,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_closing_stable_interaction",
            "horizon_days": 120,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "stable_total_route_capital_gap_5",
            "coefficient": 0.18,
            "standard_error": 0.01,
            "coefficient_per_10pp_gap": 0.018,
            "standard_error_per_10pp_gap": 0.001,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_asymmetry",
            "horizon_days": 30,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "stable_total_negative_route_capital_gap_5",
            "coefficient": 0.40,
            "standard_error": 0.08,
            "coefficient_per_10pp_gap": 0.040,
            "standard_error_per_10pp_gap": 0.008,
            "effect_per_10pp_stable_overcapitalization": -0.040,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_asymmetry",
            "horizon_days": 120,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "stable_total_negative_route_capital_gap_5",
            "coefficient": 0.70,
            "standard_error": 0.09,
            "coefficient_per_10pp_gap": 0.070,
            "standard_error_per_10pp_gap": 0.009,
            "effect_per_10pp_stable_overcapitalization": -0.070,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_extensive_margin",
            "horizon_days": 30,
            "outcome": "future_log_venue_count_change",
            "predictor": "stable_total_route_capital_gap_5",
            "coefficient": 0.05,
            "standard_error": 0.01,
            "coefficient_per_10pp_gap": 0.005,
            "standard_error_per_10pp_gap": 0.001,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_extensive_margin",
            "horizon_days": 120,
            "outcome": "future_log_venue_count_change",
            "predictor": "stable_total_route_capital_gap_5",
            "coefficient": 0.06,
            "standard_error": 0.02,
            "coefficient_per_10pp_gap": 0.006,
            "standard_error_per_10pp_gap": 0.002,
            "p_value": 0.001,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "route_capital_gap_extensive_margin",
            "horizon_days": 120,
            "outcome": "future_log_pool_count_change",
            "predictor": "stable_total_route_capital_gap_5",
            "coefficient": -0.20,
            "standard_error": 0.05,
            "coefficient_per_10pp_gap": -0.020,
            "standard_error_per_10pp_gap": 0.005,
            "p_value": 0.001,
        },
    ]
    rendered = render_liquidity_provision_behavior_deck_values(pd.DataFrame(rows))
    assert "\\LiqBehWethCapitalLeaderDays" in rendered
    assert "\\LiqBehStableRouteCapitalRatioEnd" in rendered
    assert "\\LiqBehStableGapChange" in rendered
    assert "\\LiqBehStableControlledGapCoef" in rendered
    assert "\\LiqBehGapCloseMonthCoef" in rendered
    assert "\\LiqBehStableGapCloseMonthCoef" in rendered
    assert "\\LiqBehStableOverhangMonthCoef" in rendered
    assert "\\LiqBehStableVenueMonthCoef" in rendered
    assert "\\LiqBehStablePoolLongCoef" in rendered
    assert "5.0\\times" in rendered
