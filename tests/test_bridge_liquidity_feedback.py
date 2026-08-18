from __future__ import annotations

import math

import pandas as pd

from scripts.analyze.run_bridge_liquidity_feedback import (
    bridge_liquidity_feedback_regressions,
    build_bridge_liquidity_feedback_panel,
)
from scripts.tabulate.build_bridge_liquidity_feedback_deck_values import (
    render_bridge_liquidity_feedback_deck_values,
)


def test_bridge_liquidity_feedback_panel_uses_exact_future_horizon() -> None:
    rows = []
    for offset, log_depth in [(0, 5.0), (7, 5.4)]:
        rows.append(
            {
                "src": "src",
                "tgt": "tgt",
                "candidate_address": "cand",
                "integration_scope": "single_venue",
                "origin_date": pd.Timestamp("2024-01-01")
                + pd.Timedelta(days=offset),
                "route_share_five": 0.25 + 0.01 * offset,
                "selected_five": 1.0,
                "log_bridge_min_capital": log_depth,
                "bridge_min_capital_usd": math.exp(log_depth) - 1.0,
                "five_route_total": 10.0,
                "choice_group_id": f"g{offset}",
                "ordered_pair": "src|tgt",
            }
        )
    panel = build_bridge_liquidity_feedback_panel(
        pd.DataFrame(rows),
        horizons=(7,),
    )
    assert len(panel) == 1
    assert panel.iloc[0]["horizon_days"] == 7
    assert round(panel.iloc[0]["future_delta_log_bridge_min_capital"], 6) == 0.4


def test_bridge_liquidity_feedback_regression_reports_positive_links() -> None:
    rows = []
    candidates = ["weth", "usdc", "dai"]
    for day_index in range(180):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=day_index)
        for candidate_index, candidate in enumerate(candidates):
            depth = (
                5.0
                + 0.35 * candidate_index
                + math.sin(day_index / 10 + candidate_index)
                + 0.02 * (day_index % 5)
            )
            route_share = (
                0.15
                + 0.035 * depth
                + 0.02 * candidate_index
                + 0.004 * math.cos(day_index / 8)
                + 0.01 * math.sin(day_index / 13 + 2 * candidate_index)
            )
            rows.append(
                {
                    "horizon_days": 30,
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{day_index % 45}",
                    "five_route_total": 20.0 + day_index % 4,
                    "route_share_five": route_share,
                    "log_bridge_min_capital": depth,
                    "future_delta_log_bridge_min_capital": (
                        0.18 * route_share - 0.01 * depth + 0.0005 * day_index
                    ),
                    "future_delta_route_share_five": (
                        0.018 * depth - 0.05 * route_share + 0.0003 * day_index
                    ),
                }
            )
    result = bridge_liquidity_feedback_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    route_to_depth = result[
        result["model_id"].eq("future_bridge_depth_growth")
        & result["regressor"].eq("route_share_five")
    ].iloc[0]
    depth_to_route = result[
        result["model_id"].eq("future_route_share_growth")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    assert route_to_depth["coefficient"] > 0
    assert depth_to_route["coefficient"] > 0


def test_bridge_liquidity_feedback_values_render_guarded_macros() -> None:
    estimates = pd.DataFrame(
        [
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "horizon_days": 30,
                "candidate_rows": 50_000,
                "ordered_pairs": 500,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "horizon_days": 120,
                "candidate_rows": 18_000,
                "ordered_pairs": 340,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_regression",
                "model_id": "future_bridge_depth_growth",
                "horizon_days": 30,
                "outcome": "future_delta_log_bridge_min_capital",
                "regressor": "route_share_five",
                "coefficient": 0.19,
                "standard_error": 0.05,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_regression",
                "model_id": "future_bridge_depth_growth",
                "horizon_days": 120,
                "outcome": "future_delta_log_bridge_min_capital",
                "regressor": "route_share_five",
                "coefficient": 0.97,
                "standard_error": 0.13,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_regression",
                "model_id": "future_route_share_growth",
                "horizon_days": 30,
                "outcome": "future_delta_route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.013,
                "standard_error": 0.002,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_regression",
                "model_id": "future_route_share_growth",
                "horizon_days": 120,
                "outcome": "future_delta_route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.016,
                "standard_error": 0.003,
                "p_value": 0.001,
            },
        ]
    )
    rendered = render_bridge_liquidity_feedback_deck_values(estimates)
    assert "\\BridgeFeedbackRouteToDepthLongLog" in rendered
    assert "\\BridgeFeedbackDepthToRouteMonthCoef" in rendered
