from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_stable_stable_vehicle_decomposition import (
    stable_stable_vehicle_decomposition,
)


def _cells() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    candidates = (
        ("native", "WETH", 1.0),
        ("stable", "USDT", 2.0),
        ("stable", "USDC", 3.0),
        ("stable", "DAI", 4.0),
        ("stable", "USDe", 5.0),
    )
    for year, multiplier in ((2024, 1.0), (2026, 2.0)):
        for day in ("01-01", "01-02"):
            for candidate_type, candidate_symbol, mass in candidates:
                rows.append(
                    {
                        "date": pd.Timestamp(f"{year}-{day}"),
                        "year": year,
                        "month_day": day,
                        "candidate_symbol": candidate_symbol,
                        "candidate_type": candidate_type,
                        "route_count": mass * multiplier,
                        "within_20pct_value_usd": 10.0 * mass * multiplier,
                        "daily_total_route_count": 100.0,
                        "daily_total_within_20pct_value_usd": 1000.0,
                    }
                )
    return pd.DataFrame(rows)


def test_stable_stable_vehicle_decomposition_reconciles_issuer_groups() -> None:
    results, robustness = stable_stable_vehicle_decomposition(_cells())
    assert len(results) == 10
    assert len(robustness) == 4
    for _metric, rows in results.groupby("metric"):
        stable = rows[rows["intermediary_group"].ne("native")]
        assert stable["stable_share_contribution_baseline"].sum() == pytest.approx(0.14)
        assert stable["stable_share_contribution_comparison"].sum() == pytest.approx(0.28)
        assert stable["stable_channel_change_share"].sum() == pytest.approx(1.0)
    assert set(results["common_calendar_days"]) == {2}


def test_stable_stable_vehicle_decomposition_uses_common_days() -> None:
    cells = _cells()
    extra = cells.iloc[[0]].copy()
    extra["date"] = pd.Timestamp("2024-01-03")
    extra["month_day"] = "01-03"
    results, robustness = stable_stable_vehicle_decomposition(
        pd.concat([cells, extra], ignore_index=True)
    )
    assert set(results["common_calendar_days"]) == {2}
    assert set(robustness["common_calendar_days"]) == {2}


def test_stable_stable_vehicle_decomposition_rejects_denominator_drift() -> None:
    cells = _cells()
    cells.loc[0, "daily_total_route_count"] = 99.0
    with pytest.raises(ValueError, match="not invariant"):
        stable_stable_vehicle_decomposition(cells)
