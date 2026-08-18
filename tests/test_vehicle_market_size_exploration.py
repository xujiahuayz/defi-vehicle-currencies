from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_vehicle_market_size_exploration import (
    build_vehicle_market_size_exploration,
    daily_thin_thick_shares,
    prepare_pair_support,
)


def fixture() -> pd.DataFrame:
    rows = []
    for year in (2024, 2025, 2026):
        for day in range(1, 4):
            date = pd.Timestamp(year=year, month=1, day=day)
            rows.extend(
                [
                    {
                        "date": date,
                        "market_route_count": 2,
                        "primary_choice_route_count": 10,
                        "native_choice_route_count": 8 if year == 2024 else 5,
                        "stable_choice_route_count": 2 if year == 2024 else 5,
                        "native_within_20pct_value_usd": 80.0,
                        "stable_within_20pct_value_usd": 20.0 if year == 2024 else 50.0,
                    },
                    {
                        "date": date,
                        "market_route_count": 150,
                        "primary_choice_route_count": 100,
                        "native_choice_route_count": 40 if year == 2024 else 20,
                        "stable_choice_route_count": 60 if year == 2024 else 80,
                        "native_within_20pct_value_usd": 40.0,
                        "stable_within_20pct_value_usd": 60.0 if year == 2024 else 80.0,
                    },
                ]
            )
    return pd.DataFrame(rows)


def test_prepare_pair_support_labels_realised_size_bins() -> None:
    prepared = prepare_pair_support(fixture())
    assert set(prepared["size_bin"]) == {"thin_1_5", "thick_gt100"}
    assert set(prepared["activity_bin"]) == {"two_to_five", "gt_hundred"}


def test_daily_thin_thick_shares_reports_active_minus_thin_gap() -> None:
    daily = daily_thin_thick_shares(prepare_pair_support(fixture()))
    row = daily[daily["year"].eq(2026)].iloc[0]
    assert row["thin_1_5"] == 0.5
    assert row["thick_gt100"] == 0.8
    assert row["thick_minus_thin"] == pytest.approx(0.3)


def test_market_size_exploration_includes_endpoint_changes() -> None:
    result = build_vehicle_market_size_exploration(fixture())
    changes = result[result["record_type"].eq("daily_market_size_change")]
    assert set(changes["estimand"]) == {"thin_1_5", "thick_gt100", "thick_minus_thin"}
    thin = changes[changes["estimand"].eq("thin_1_5")].iloc[0]
    assert thin["change"] > 0
    assert thin["comparison_mean"] == 0.5
