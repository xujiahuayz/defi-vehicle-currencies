from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_v3_v4_lp_protocol_contrast import (
    fit_v3_v4_lp_protocol_contrast,
    stack_v3_v4_lp_protocol_panel,
)


def _candidate_rows() -> list[tuple[str, str, bool]]:
    return [
        ("0x0000000000000000000000000000000000000001", "DAI", True),
        ("0x0000000000000000000000000000000000000002", "USDC", True),
        ("0x0000000000000000000000000000000000000003", "USDT", True),
        ("0x0000000000000000000000000000000000000004", "WETH", False),
    ]


def test_v3_v4_lp_protocol_contrast_is_estimable_on_stacked_panel() -> None:
    rng = np.random.default_rng(11)
    dates = pd.date_range("2025-01-01", periods=70, freq="D")
    v3_rows = []
    v4_rows = []
    active_rows = []
    for candidate_index, (address, symbol, stable) in enumerate(_candidate_rows()):
        for day_index, day in enumerate(dates):
            gap = (
                0.08
                + 0.02 * candidate_index
                + 0.01 * np.sin(day_index / 8.0)
                + 0.002 * candidate_index * (day_index % 11)
                + rng.normal(0.0, 0.001)
            )
            stable_gap = gap if stable else 0.0
            candidate_date_level = 0.5 + 0.01 * day_index + 0.05 * candidate_index
            origin_actions_v3 = (
                0.10
                + 0.02 * candidate_index
                + 0.001 * day_index
                + 0.01 * np.sin((candidate_index + 1) * day_index / 7.0)
                + rng.normal(0.0, 0.003)
            )
            origin_origins_v3 = (
                0.08
                + 0.01 * candidate_index
                + 0.002 * day_index
                + 0.01 * np.cos((candidate_index + 2) * day_index / 9.0)
                + rng.normal(0.0, 0.003)
            )
            origin_actions_v4 = (
                0.12
                + 0.02 * candidate_index
                + 0.003 * day_index
                + 0.01 * np.cos((candidate_index + 1) * day_index / 11.0)
                + rng.normal(0.0, 0.003)
            )
            origin_origins_v4 = (
                0.09
                + 0.01 * candidate_index
                + 0.004 * day_index
                + 0.01 * np.sin((candidate_index + 3) * day_index / 13.0)
                + rng.normal(0.0, 0.003)
            )
            v3_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "is_stable": stable,
                    "route_capital_gap_5": gap,
                    "horizon_days": 30,
                    "future_log1p_v3_total_lp_actions": (
                        candidate_date_level
                        + 0.2 * origin_actions_v3
                        + 0.1 * origin_origins_v3
                        + rng.normal(0.0, 0.01)
                    ),
                    "future_log1p_v3_total_origin_count": (
                        0.8 * candidate_date_level
                        + 0.1 * origin_actions_v3
                        + 0.2 * origin_origins_v3
                        + rng.normal(0.0, 0.01)
                    ),
                    "origin_log1p_v3_total_lp_actions": origin_actions_v3,
                    "origin_log1p_v3_total_origin_count": origin_origins_v3,
                }
            )
            v4_rows.append(
                {
                    "origin_date": day,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "is_stable": stable,
                    "route_capital_gap_5": gap,
                    "horizon_days": 30,
                    "future_log1p_v4_total_lp_actions": (
                        candidate_date_level
                        + 0.15
                        + 3.5 * stable_gap
                        + 0.2 * origin_actions_v4
                        + 0.1 * origin_origins_v4
                        + rng.normal(0.0, 0.01)
                    ),
                    "future_log1p_v4_total_origin_count": (
                        0.8 * candidate_date_level
                        + 0.08
                        + 2.0 * stable_gap
                        + 0.1 * origin_actions_v4
                        + 0.2 * origin_origins_v4
                        + rng.normal(0.0, 0.01)
                    ),
                    "origin_log1p_v4_total_lp_actions": origin_actions_v4,
                    "origin_log1p_v4_total_origin_count": origin_origins_v4,
                }
            )
            active_rows.append({"origin_date": day, "candidate_address": address})

    panel = stack_v3_v4_lp_protocol_panel(
        pd.DataFrame(v3_rows),
        pd.DataFrame(v4_rows),
        pd.DataFrame(active_rows),
    )
    assert len(panel) == 2 * len(v3_rows)

    results = fit_v3_v4_lp_protocol_contrast(
        panel,
        horizons=(30,),
        outcomes=("future_log1p_total_lp_actions",),
        min_observations=100,
        min_clusters=30,
    )
    contrast = results[results["term"].eq("v4_x_stable_gap")].iloc[0]
    assert contrast["record_type"] == "v3_v4_lp_protocol_contrast"
    assert contrast["coefficient"] > 0
    assert np.isfinite(contrast["standard_error"])
    assert contrast["n_observations"] == 2 * len(v3_rows)
