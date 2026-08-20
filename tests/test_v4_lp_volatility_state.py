from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_v4_flash_lp_mechanism_exploration import CONTROLS
from scripts.analyze.run_v4_lp_volatility_state import (
    attach_volatility_state,
    fit_volatility_state,
    load_lagged_weth_volatility,
)


def test_lagged_weth_volatility_uses_prior_daily_prices(tmp_path) -> None:
    rows = []
    for day_index, day in enumerate(pd.date_range("2025-01-01", periods=4)):
        for minute in range(3):
            timestamp = int((day + pd.Timedelta(minutes=minute)).timestamp())
            rows.append(
                {
                    "bucket_start_utc": timestamp,
                    "available_at_utc": timestamp + 60,
                    "weth_usd": 100.0 + 2 * day_index + minute,
                    "validation_status": "valid",
                }
            )
    path = tmp_path / "weth.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    volatility = load_lagged_weth_volatility(path, windows=(2,))
    assert volatility["lagged_2d_weth_volatility"].iloc[:2].isna().all()
    assert np.isfinite(volatility["lagged_2d_weth_volatility"].iloc[2:]).all()
    assert volatility["minute_returns"].min() >= 2


def test_volatility_state_regression_and_contrasts_are_estimable() -> None:
    dates = pd.date_range("2025-01-01", periods=70, freq="D")
    rows = []
    volatility_rows = []
    for day_index, day in enumerate(dates):
        state = np.sin(day_index / 7)
        volatility_rows.append(
            {
                "origin_date": day,
                "lagged_30d_weth_volatility": 0.03 + 0.005 * state,
            }
        )
        for candidate_index, symbol in enumerate(("AAA", "BBB", "CCC")):
            signal = (
                0.05
                + 0.01 * candidate_index
                + 0.005 * ((day_index + candidate_index) % 5)
            )
            row = {
                "origin_date": day,
                "candidate_address": f"0x{candidate_index + 1:040x}",
                "candidate_symbol": symbol,
                "internal_tx_share": signal,
                **{
                    control: (
                        0.2 * (control_index + 1) * candidate_index
                        + 0.01 * ((day_index + control_index) % 11)
                        + 0.003
                        * candidate_index
                        * ((day_index + 2 * control_index) % 7)
                    )
                    for control_index, control in enumerate(CONTROLS)
                },
            }
            row["near_log1p_incumbent_actions"] = (
                1.0 + 2.0 * signal + 1.5 * signal * state + 0.001 * day_index**2
            )
            row["late_log1p_first_active_origins"] = (
                2.0 + 3.0 * signal + 2.0 * signal * state + 0.0015 * day_index**2
            )
            rows.append(row)
    panel = attach_volatility_state(
        pd.DataFrame(rows),
        pd.DataFrame(volatility_rows),
        state_window_days=30,
    )
    results = fit_volatility_state(
        panel,
        sample_variant="test",
        state_window_days=30,
        min_observations=100,
        min_clusters=30,
    )
    assert len(results) == 2
    assert results["interaction_per_10pp_per_1sd_volatility"].gt(0).all()
    assert results["interaction_holm_p_value"].between(0, 1).all()
    assert results["high_state_effect_per_10pp"].gt(
        results["low_state_effect_per_10pp"]
    ).all()
