from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_stable_stress_event import (
    prepare_stable_route_days,
    stress_window_contrasts,
    stress_window_summaries,
)
from scripts.tabulate.build_stable_stress_event_deck_values import (
    render_stable_stress_event_deck_values,
)


def _row(date: str, symbol: str, routes: int) -> dict[str, object]:
    return {
        "origin_date": pd.Timestamp(date),
        "candidate_symbol": symbol,
        "route_day_supported": True,
        "intermediate_route_count": routes,
    }


def test_stress_windows_keep_usdc_identity_under_activity_spike() -> None:
    rows: list[dict[str, object]] = []
    for date in pd.date_range("2023-02-08", "2023-03-09", freq="D"):
        rows.extend(
            [
                _row(date.strftime("%Y-%m-%d"), "USDC", 70),
                _row(date.strftime("%Y-%m-%d"), "USDT", 20),
                _row(date.strftime("%Y-%m-%d"), "DAI", 10),
                _row(date.strftime("%Y-%m-%d"), "WETH", 999),
            ]
        )
    for date in pd.date_range("2023-03-10", "2023-03-13", freq="D"):
        rows.extend(
            [
                _row(date.strftime("%Y-%m-%d"), "USDC", 140),
                _row(date.strftime("%Y-%m-%d"), "USDT", 40),
                _row(date.strftime("%Y-%m-%d"), "DAI", 20),
            ]
        )
    for date in pd.date_range("2023-03-14", "2023-04-12", freq="D"):
        rows.extend(
            [
                _row(date.strftime("%Y-%m-%d"), "USDC", 60),
                _row(date.strftime("%Y-%m-%d"), "USDT", 30),
                _row(date.strftime("%Y-%m-%d"), "DAI", 10),
            ]
        )
    stable = prepare_stable_route_days(pd.DataFrame(rows))
    assert set(stable["candidate_symbol"]) == {"USDC", "USDT", "DAI"}
    summaries = stress_window_summaries(stable)
    contrasts = stress_window_contrasts(summaries)
    usdc_change = contrasts[
        contrasts["contrast"].eq("stress_minus_pre_usdc_share")
    ].iloc[0]
    activity = contrasts[
        contrasts["contrast"].eq("stress_mean_daily_stable_routes_vs_pre")
    ].iloc[0]
    assert usdc_change["estimate"] == pytest.approx(0.0)
    assert activity["estimate"] == pytest.approx(1.0)


def test_stable_stress_deck_values_are_guarded() -> None:
    rows = [
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_window",
            "stress_window": "pre_30d",
            "candidate_symbol": "USDC",
            "stable_route_share": 0.68,
            "mean_daily_stable_routes": 100,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_window",
            "stress_window": "stress_4d",
            "candidate_symbol": "USDC",
            "stable_route_share": 0.679,
            "mean_daily_stable_routes": 180,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_window",
            "stress_window": "post_30d",
            "candidate_symbol": "USDT",
            "stable_route_share": 0.25,
            "mean_daily_stable_routes": 120,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "stress_minus_pre_usdc_share",
            "estimate": -0.001,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "stress_mean_daily_stable_routes_vs_pre",
            "estimate": 0.80,
        },
    ]
    rendered = render_stable_stress_event_deck_values(pd.DataFrame(rows))
    assert "\\StressEventStressUsdcShare" in rendered
    assert "\\StressEventStableActivityRise" in rendered
    assert "80.0\\%" in rendered
