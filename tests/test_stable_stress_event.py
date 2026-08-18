from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_stable_stress_event import (
    prepare_stress_candidate_days,
    prepare_stable_route_days,
    stress_lp_contrasts,
    stress_lp_window_summaries,
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


def _capital_row(
    date: str,
    symbol: str,
    routes: int,
    capital: float,
) -> dict[str, object]:
    return {
        "origin_date": pd.Timestamp(date),
        "candidate_symbol": symbol,
        "route_day_supported": True,
        "v2_capital_day_supported": True,
        "intermediate_route_count": routes,
        "v2_deposited_capital_usd": capital,
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


def test_stress_lp_contrasts_separate_route_spike_from_capital_shift() -> None:
    rows: list[dict[str, object]] = []
    for date in pd.date_range("2023-02-08", "2023-03-09", freq="D"):
        day = date.strftime("%Y-%m-%d")
        rows.extend(
            [
                _capital_row(day, "DAI", 10, 10.0),
                _capital_row(day, "USDC", 70, 20.0),
                _capital_row(day, "USDT", 20, 10.0),
                _capital_row(day, "WBTC", 0, 10.0),
                _capital_row(day, "WETH", 100, 50.0),
            ]
        )
    for date in pd.date_range("2023-03-10", "2023-03-13", freq="D"):
        day = date.strftime("%Y-%m-%d")
        rows.extend(
            [
                _capital_row(day, "DAI", 20, 8.0),
                _capital_row(day, "USDC", 140, 16.0),
                _capital_row(day, "USDT", 40, 8.0),
                _capital_row(day, "WBTC", 0, 10.0),
                _capital_row(day, "WETH", 100, 58.0),
            ]
        )
    for date in pd.date_range("2023-03-14", "2023-04-12", freq="D"):
        day = date.strftime("%Y-%m-%d")
        rows.extend(
            [
                _capital_row(day, "DAI", 10, 8.0),
                _capital_row(day, "USDC", 60, 15.0),
                _capital_row(day, "USDT", 30, 8.0),
                _capital_row(day, "WBTC", 0, 10.0),
                _capital_row(day, "WETH", 100, 59.0),
            ]
        )
    candidate_days = prepare_stress_candidate_days(pd.DataFrame(rows))
    summaries = stress_lp_window_summaries(candidate_days)
    contrasts = stress_lp_contrasts(summaries)
    stable_route = contrasts[
        contrasts["contrast"].eq("stress_minus_pre_stable_route_share_5")
    ].iloc[0]
    stable_capital = contrasts[
        contrasts["contrast"].eq("stress_minus_pre_stable_capital_share_5")
    ].iloc[0]
    weth_capital = contrasts[
        contrasts["contrast"].eq("post_minus_pre_weth_capital_share_5")
    ].iloc[0]
    assert stable_route["estimate"] > 0
    assert stable_capital["estimate"] < 0
    assert weth_capital["estimate"] > 0


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
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stress_lp_contrast",
            "contrast": "stress_minus_pre_stable_route_share_5",
            "estimate": 0.10,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stress_lp_contrast",
            "contrast": "stress_minus_pre_stable_capital_share_5",
            "estimate": -0.02,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stress_lp_contrast",
            "contrast": "post_minus_pre_stable_capital_share_5",
            "estimate": -0.03,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stress_lp_contrast",
            "contrast": "post_minus_pre_weth_capital_share_5",
            "estimate": 0.03,
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stress_lp_contrast",
            "contrast": "post_minus_pre_usdc_capital_share_5",
            "estimate": -0.04,
        },
    ]
    rendered = render_stable_stress_event_deck_values(pd.DataFrame(rows))
    assert "\\StressEventStressUsdcShare" in rendered
    assert "\\StressEventStableActivityRise" in rendered
    assert "\\StressEventStableCapitalShareChange" in rendered
    assert "80.0\\%" in rendered
