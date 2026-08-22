from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_eth_intraday_executable_route_chain import (
    add_trailing_return,
    attach_route_price_state,
    detect_decline_events,
    event_day_tasks,
)


def test_add_trailing_return_uses_declared_backward_window() -> None:
    prices = pd.DataFrame(
        {
            "available_at_utc": [0, 3600, 7200],
            "weth_usd": [100.0, 90.0, 99.0],
        }
    )
    result = add_trailing_return(
        prices, return_hours=1, tolerance_seconds=0
    )
    assert np.isnan(result.loc[0, "eth_log_return_6h"])
    assert np.isclose(result.loc[1, "eth_log_return_6h"], np.log(0.9))
    assert np.isclose(result.loc[2, "eth_log_return_6h"], np.log(1.1))


def test_decline_events_require_crossing_and_cooldown() -> None:
    base = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp())
    second = base + 49 * 3600
    state = pd.DataFrame(
        {
            "available_at_utc": [
                base,
                base + 60,
                second - 60,
                second,
            ],
            "eth_decline_6h": [0.09, 0.11, 0.09, 0.12],
        }
    )
    events = detect_decline_events(
        state,
        start="20200101",
        end="20221231",
        threshold=0.10,
        cooldown_hours=48,
        pre_hours=6,
        post_hours=24,
    )
    assert events["event_ts"].tolist() == [base + 60, second]


def test_event_day_tasks_cover_complete_nonoverlapping_windows() -> None:
    event_ts = int(pd.Timestamp("2021-01-02 02:00", tz="UTC").timestamp())
    events = pd.DataFrame(
        {
            "event_id": ["event"],
            "event_ts": [event_ts],
            "event_time_utc": [pd.to_datetime(event_ts, unit="s", utc=True)],
            "window_start_utc": [event_ts - 6 * 3600],
            "window_end_utc": [event_ts + 24 * 3600],
            "crossing_decline_6h": [0.10],
        }
    )
    tasks = event_day_tasks(events)
    assert [day for day, _windows in tasks] == [
        "20210101",
        "20210102",
        "20210103",
    ]
    assert all(len(windows) == 1 for _day, windows in tasks)


def test_route_price_state_never_uses_execution_minute_close() -> None:
    panel = pd.DataFrame({"timestamp_utc": [3700]})
    prices = pd.DataFrame(
        {
            "available_at_utc": [60, 100, 3660, 3700],
            "weth_usd": [100.0, 101.0, 90.0, 1.0],
        }
    )
    result = attach_route_price_state(
        panel,
        prices,
        return_hours=1,
        tolerance_seconds=60,
    )
    assert result.loc[0, "eth_price_available_at_utc"] == 3660
    assert result.loc[0, "eth_lag_price_available_at_utc"] == 60
    assert np.isclose(result.loc[0, "eth_log_return_6h"], np.log(0.9))
