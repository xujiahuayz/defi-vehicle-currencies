from __future__ import annotations

import datetime as dt

import pytest

from ddvc.market_coverage import annual_market_coverage


def _row(year: int, values: dict[str, float]) -> list[object]:
    timestamp = int(dt.datetime(year, 1, 2, tzinfo=dt.timezone.utc).timestamp())
    return [timestamp, values]


def test_annual_market_coverage_separates_selected_families_from_total_volume() -> None:
    breakdown = [
        _row(year, {"Uniswap V2": 70.0, "Another DEX": 30.0})
        for year in range(2020, 2027)
    ]
    rows = annual_market_coverage(breakdown)
    assert len(rows) == 7
    assert all(row["coverage_share"] == pytest.approx(0.7) for row in rows)
    assert rows[-1]["period"] == "H1"


def test_annual_market_coverage_rejects_duplicate_days() -> None:
    breakdown = [
        _row(year, {"Uniswap V2": 1.0}) for year in range(2020, 2027)
    ]
    breakdown.append(breakdown[0])
    with pytest.raises(ValueError, match="duplicate DeFiLlama date"):
        annual_market_coverage(breakdown)
