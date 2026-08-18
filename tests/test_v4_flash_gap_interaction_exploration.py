from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_v4_flash_gap_interaction_exploration import (
    build_flash_gap_interaction_panel,
    fit_flash_gap_interactions,
)


def test_v4_flash_gap_interactions_are_estimable() -> None:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2025-01-01", periods=70, freq="D")
    candidates = [
        ("0x0000000000000000000000000000000000000001", "DAI"),
        ("0x0000000000000000000000000000000000000002", "USDC"),
        ("0x0000000000000000000000000000000000000003", "USDT"),
        ("0x0000000000000000000000000000000000000004", "FRAX"),
    ]
    stable_gap_rows = []
    mechanism_rows = []
    for candidate_index, (address, symbol) in enumerate(candidates):
        for day_index, day in enumerate(dates):
            day_wave = np.sin(day_index / 5.0)
            candidate_wave = np.cos((candidate_index + 1) * day_index / 9.0)
            gap = (
                0.10
                + 0.03 * candidate_index
                + 0.010 * day_wave
                + 0.002 * candidate_wave
                + 0.0006 * candidate_index * (day_index % 17)
                + rng.normal(0.0, 0.001)
            )
            flash = (
                0.05
                + 0.01 * candidate_index
                + 0.008 * np.cos(day_index / 6.0)
                + 0.002 * np.sin((candidate_index + 2) * day_index / 11.0)
                + 0.0005 * candidate_index * (day_index % 13)
                + rng.normal(0.0, 0.001)
            )
            interaction = gap * flash
            leg_assignments = np.log1p(
                10 + day_index + 3 * candidate_index + rng.normal(0.0, 0.2)
            )
            current_flow = np.log1p(
                100
                + 2 * day_index
                + 11 * candidate_index
                + candidate_index * (day_index % 9)
                + rng.normal(0.0, 0.5)
            )
            current_tvl = np.log1p(
                1_000
                + 10 * day_index
                + 50 * candidate_index
                + candidate_index * day_index
                + rng.normal(0.0, 2.0)
            )
            current_actions = np.log1p(
                5
                + candidate_index
                + 0.05 * day_index
                + 0.2 * np.sin((candidate_index + 1) * day_index / 7.0)
                + rng.normal(0.0, 0.05)
            )
            current_narrow = (
                0.55
                + 0.03 * np.sin(day_index / 8.0)
                - 0.02 * candidate_index
                + 0.002 * candidate_index * (day_index % 10)
                + rng.normal(0.0, 0.005)
            )
            stable_gap_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "is_stable": True,
                    "route_capital_gap_5": gap,
                }
            )
            mechanism_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "horizon_days": 7,
                    "internal_tx_share": flash,
                    "multi_leg_tx_share": 0.5 * flash,
                    "netting_reduction_share": 0.25 * flash,
                    "future_log1p_lp_actions": 1.0 + 8.0 * interaction,
                    "future_narrow_medium_action_share": 0.5 - 2.0 * interaction,
                    "future_wide_very_wide_action_share": 0.2 + 2.0 * interaction,
                    "future_log1p_gross_lp_flow_usd": 0.3 + interaction,
                    "future_log1p_add_lp_flow_usd": 0.2 + interaction,
                    "future_log1p_remove_lp_flow_usd": 0.1 + interaction,
                    "future_delta_log1p_tvl_usd": 0.4 + 3.0 * interaction,
                    "log1p_swap_leg_assignments": leg_assignments,
                    "log1p_current_gross_flow_usd": current_flow,
                    "log1p_current_tvl_usd": current_tvl,
                    "log1p_current_actions": current_actions,
                    "current_narrow_medium_share": current_narrow,
                }
            )

    panel = build_flash_gap_interaction_panel(
        pd.DataFrame(stable_gap_rows),
        pd.DataFrame(mechanism_rows),
    )
    assert len(panel) == len(mechanism_rows)

    results = fit_flash_gap_interactions(
        panel,
        horizons=(7,),
        predictors=("internal_tx_share",),
        outcomes=("future_log1p_lp_actions",),
        min_observations=20,
        min_clusters=10,
    )
    interaction = results[
        results["term"].eq("route_capital_gap_5_x_internal_tx_share")
    ].iloc[0]
    assert interaction["record_type"] == "v4_flash_gap_interaction_regression"
    assert np.isfinite(interaction["coefficient"])
    assert interaction["n_observations"] >= 250
