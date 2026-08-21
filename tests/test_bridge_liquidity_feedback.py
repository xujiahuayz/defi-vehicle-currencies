from __future__ import annotations

import math

import pandas as pd

from scripts.analyze.run_bridge_liquidity_feedback import (
    bridge_liquidity_feedback_regressions,
    build_bridge_liquidity_feedback_panel,
)


def test_bridge_liquidity_feedback_panel_uses_exact_future_horizon() -> None:
    rows = []
    for offset, log_depth in [(0, 5.0), (29, 9.9), (30, 5.4)]:
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
                "is_stable": 1.0,
                "five_route_total": 10.0,
                "choice_group_id": f"g{offset}",
                "ordered_pair": "src|tgt",
            }
        )
    panel = build_bridge_liquidity_feedback_panel(
        pd.DataFrame(rows),
        horizons=(30,),
    )
    assert len(panel) == 2
    forward = panel[panel["timing"].eq("forward")].iloc[0]
    reversed_window = panel[panel["timing"].eq("time_reversed")].iloc[0]
    assert forward["horizon_days"] == 30
    assert forward["depth_outcome"] == 5.4
    assert forward["initial_depth"] == 5.0
    assert forward["route_share_predictor"] == 0.25
    assert reversed_window["depth_outcome"] == 5.0
    assert reversed_window["initial_depth"] == 5.4
    assert reversed_window["route_share_predictor"] == 0.55


def test_bridge_liquidity_feedback_regression_uses_levels_fe_and_two_weights() -> None:
    rows = []
    candidates = ["weth", "usdc", "dai"]
    for pair_index in range(40):
        for day_index in range(12):
            day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=day_index)
            for candidate_index, candidate in enumerate(candidates):
                stable_candidate = float(candidate != "weth")
                bridge = f"pair{pair_index}|{candidate}|single_venue"
                depth = (
                    4.0
                    + 0.15 * candidate_index
                    + 0.03 * pair_index
                    + 0.12 * math.sin((day_index + pair_index) / 3)
                )
                route_share = (
                    0.18
                    + 0.025 * candidate_index
                    + 0.002 * pair_index
                    + 0.03 * math.cos((2 * day_index + pair_index) / 5)
                )
                noise = 0.002 * math.sin(pair_index + day_index + candidate_index)
                rows.append(
                    {
                        "timing": "forward",
                        "horizon_days": 30,
                        "stable_candidate": stable_candidate,
                        "candidate_pair_scope": bridge,
                        "analysis_date": day,
                        "ordered_pair": f"pair{pair_index}",
                        "weight_group_id": f"pair{pair_index}|{day:%Y%m%d}",
                        "weight_activity": 20.0 + pair_index % 4,
                        "initial_depth": depth,
                        "initial_route_share": route_share,
                        "route_share_predictor": route_share,
                        "depth_predictor": depth,
                        "depth_outcome": (
                            0.72 * depth + 0.30 * route_share + noise
                        ),
                        "route_share_outcome": (
                            0.68 * route_share + 0.04 * depth + noise
                        ),
                    }
                )
    result = bridge_liquidity_feedback_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=5,
    )
    route_to_depth = result[
        result["model_id"].eq("future_bridge_depth_level")
        & result["regressor"].eq("route_share_predictor")
        & result["weight_scheme"].eq("activity")
    ].iloc[0]
    depth_to_route = result[
        result["model_id"].eq("future_route_share_level")
        & result["regressor"].eq("depth_predictor")
        & result["weight_scheme"].eq("activity")
    ].iloc[0]
    assert route_to_depth["coefficient"] > 0
    assert depth_to_route["coefficient"] > 0
    assert set(result["weight_scheme"]) == {"pair", "activity"}
    assert set(result["fixed_effects"]) == {"local_bridge+analysis_date"}
    assert result["initial_level_controls"].str.startswith(
        "cubic_standardized_"
    ).all()
    assert not result["outcome"].str.contains("delta").any()
