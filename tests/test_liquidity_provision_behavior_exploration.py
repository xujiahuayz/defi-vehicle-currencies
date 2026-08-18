from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_liquidity_provision_behavior_exploration import (
    annual_stable_allocation,
    capital_use_gap_summaries,
    daily_leader_alignment,
    daily_capital_use_gaps,
    supported_candidate_days,
)


def _row(
    date: str,
    symbol: str,
    *,
    capital: float,
    intermediate_routes: int,
    endpoint_routes: int,
    excess: float,
) -> dict[str, object]:
    total_capital = {"WETH": 100.0, "WBTC": 10.0, "USDC": 20.0, "USDT": 10.0, "DAI": 10.0}
    return {
        "origin_date": pd.Timestamp(date),
        "candidate_address": symbol.lower(),
        "candidate_symbol": symbol,
        "route_day_supported": True,
        "v2_capital_day_supported": True,
        "intermediary_episode_share": intermediate_routes / 100,
        "vehicle_excess_use_count_ratio": excess,
        "intermediate_route_count": intermediate_routes,
        "endpoint_route_count": endpoint_routes,
        "v2_deposited_capital_usd": capital,
        "v2_log1p_deposited_capital_usd": 1.0,
        "v2_five_candidate_capital_share": capital / total_capital.get(symbol, 1.0),
        "v2_candidate_pool_count": 1,
        "v2_candidate_venue_count": 1,
    }


@pytest.fixture
def sample() -> pd.DataFrame:
    rows = []
    for date in ("2024-01-01", "2026-01-01"):
        rows.extend(
            [
                _row(date, "WETH", capital=100, intermediate_routes=40, endpoint_routes=50, excess=0.8),
                _row(date, "WBTC", capital=10, intermediate_routes=5, endpoint_routes=10, excess=0.5),
                _row(date, "USDC", capital=20, intermediate_routes=30, endpoint_routes=20, excess=3.0),
                _row(date, "USDT", capital=10, intermediate_routes=20, endpoint_routes=10, excess=4.0),
                _row(date, "DAI", capital=10, intermediate_routes=5, endpoint_routes=10, excess=1.0),
            ]
        )
    return supported_candidate_days(pd.DataFrame(rows))


def test_annual_stable_allocation_separates_capital_from_route_use(sample) -> None:
    annual = annual_stable_allocation(sample)
    row = annual[annual["year"].eq(2024)].iloc[0]
    assert row["stable_capital_share"] == pytest.approx(40 / 150)
    assert row["stable_intermediary_route_share"] == pytest.approx(55 / 100)
    assert row["stable_route_to_capital_ratio"] == pytest.approx((55 / 100) / (40 / 150))


def test_daily_leader_alignment_distinguishes_capital_and_excess_leaders(sample) -> None:
    leaders = daily_leader_alignment(sample).iloc[0]
    assert leaders["weth_capital_leader_share"] == pytest.approx(1.0)
    assert leaders["stable_excess_leader_share"] == pytest.approx(1.0)
    assert leaders["capital_leader_is_excess_leader_share"] == pytest.approx(0.0)


def test_daily_capital_use_gap_separates_route_and_capital_shares(sample) -> None:
    daily = daily_capital_use_gaps(sample)
    row = daily[daily["origin_date"].eq(pd.Timestamp("2024-01-01"))].iloc[0]
    assert row["stable_route_capital_gap"] == pytest.approx((55 / 100) - (40 / 150))
    summaries = capital_use_gap_summaries(daily)
    assert {
        "daily_route_capital_gap_year",
        "daily_route_capital_gap_change",
    }.issubset(set(summaries["record_type"]))
