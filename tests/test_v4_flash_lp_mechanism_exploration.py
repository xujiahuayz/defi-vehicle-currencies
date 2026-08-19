from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_v4_flash_lp_mechanism_exploration import (
    build_mechanism_panel,
    fit_mechanism_regressions,
)


def test_v4_flash_lp_mechanism_panel_and_regression_are_estimable() -> None:
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    candidates = [
        ("0x0000000000000000000000000000000000000001", "AAA"),
        ("0x0000000000000000000000000000000000000002", "BBB"),
        ("0x0000000000000000000000000000000000000003", "CCC"),
    ]
    flash_rows = []
    flow_rows = []
    action_rows = []
    tvl_rows = []
    for candidate_index, (address, symbol) in enumerate(candidates):
        for day_index, day in enumerate(dates):
            signal = (
                0.05
                + 0.01 * candidate_index
                + 0.002 * (day_index % 11)
                + 0.001 * candidate_index * (day_index % 7)
            )
            flash_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "candidate_tx_count": 10 + day_index,
                    "swap_leg_assignments": 20 + day_index + candidate_index,
                    "multi_leg_tx_count": 2 + candidate_index,
                    "internal_tx_count": 1 + candidate_index,
                    "netting_reduction_tx_count": 1,
                    "multi_leg_tx_share": 0.5 * signal,
                    "internal_tx_share": signal,
                    "netting_reduction_share": 0.25 * signal,
                }
            )
            flow_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "v4_gross_lp_flow_usd_screened": np.exp(4 + 4 * signal) - 1,
                    "v4_add_lp_flow_usd_screened": np.exp(3 + 3 * signal) - 1,
                    "v4_remove_lp_flow_usd_screened": np.exp(2 + 2 * signal) - 1,
                    "v4_narrow_medium_flow_usd_screened": np.exp(3 + 5 * signal) - 1,
                    "v4_broad_flow_usd_screened": np.exp(3 - 2 * signal) - 1,
                    "v4_lp_flow_screened_assignments": 3 + candidate_index,
                }
            )
            action_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "v4_total_lp_actions": 5 + day_index % 7,
                    "v4_add_events": 3,
                    "v4_remove_events": 2,
                    "v4_narrow_range_events": 1 + candidate_index,
                    "v4_medium_range_events": 2,
                    "v4_wide_range_events": 1,
                    "v4_very_wide_range_events": 0,
                    "v4_full_range_events": 0,
                    "v4_total_origin_count": 2,
                }
            )
            tvl_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "capital_valid": True,
                    "candidate_linked_pool_tvl_usd": 1_000 + 100 * day_index + 50 * candidate_index,
                    "candidate_linked_pool_volume_usd": 100,
                    "pool": f"pool-{candidate_index}",
                }
            )

    panel = build_mechanism_panel(
        pd.DataFrame(flash_rows),
        pd.DataFrame(flow_rows),
        pd.DataFrame(action_rows),
        pd.DataFrame(tvl_rows),
        horizons=(7,),
    )
    assert panel["horizon_days"].eq(7).all()
    assert "future_log1p_gross_lp_flow_usd" in panel.columns
    assert "future_wide_very_wide_action_share" in panel.columns

    results = fit_mechanism_regressions(
        panel,
        horizons=(7,),
        predictors=("internal_tx_share",),
        outcomes=("future_log1p_gross_lp_flow_usd",),
        controls=("log1p_swap_leg_assignments",),
        min_observations=20,
        min_clusters=10,
    )
    row = results.iloc[0]
    assert row["record_type"] == "v4_flash_lp_mechanism_regression"
    assert np.isfinite(row["coefficient"])
    assert row["date_clusters"] >= 10
