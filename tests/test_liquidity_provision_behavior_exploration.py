from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_liquidity_provision_behavior_exploration import (
    annual_stable_allocation,
    capital_use_gap_summaries,
    candidate_share_gap_panel,
    daily_leader_alignment,
    daily_capital_use_gaps,
    route_capital_gap_asymmetry,
    route_capital_gap_closing,
    route_capital_gap_closing_stable_interactions,
    route_capital_gap_horizon_panel,
    supported_candidate_days,
    within_day_gap_associations,
)


def _row(
    date: str,
    symbol: str,
    *,
    capital: float,
    intermediate_routes: int,
    endpoint_routes: int,
    excess: float,
    pool_count: int = 1,
    venue_count: int = 1,
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
        "v2_candidate_pool_count": pool_count,
        "v2_candidate_venue_count": venue_count,
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


def test_candidate_share_gap_panel_defines_within_day_route_capital_gap(sample) -> None:
    panel = candidate_share_gap_panel(sample)
    row = panel[
        panel["origin_date"].eq(pd.Timestamp("2024-01-01"))
        & panel["candidate_symbol"].eq("USDC")
    ].iloc[0]
    assert row["route_share_5"] == pytest.approx(30 / 100)
    assert row["capital_share_5"] == pytest.approx(20 / 150)
    assert row["endpoint_share_5"] == pytest.approx(20 / 100)
    assert row["route_capital_gap_5"] == pytest.approx((30 / 100) - (20 / 150))


def test_within_day_gap_association_reports_stable_indicator() -> None:
    rows = []
    for day in pd.date_range("2024-01-01", periods=220, freq="D"):
        date = day.strftime("%Y-%m-%d")
        rows.extend(
            [
                _row(
                    date,
                    "WETH",
                    capital=100,
                    intermediate_routes=25,
                    endpoint_routes=45,
                    excess=0.8,
                    pool_count=6,
                    venue_count=4,
                ),
                _row(
                    date,
                    "WBTC",
                    capital=20,
                    intermediate_routes=5,
                    endpoint_routes=15,
                    excess=0.5,
                    pool_count=3,
                    venue_count=1,
                ),
                _row(
                    date,
                    "USDC",
                    capital=10,
                    intermediate_routes=40,
                    endpoint_routes=15,
                    excess=3.0,
                    pool_count=2,
                    venue_count=2,
                ),
                _row(
                    date,
                    "USDT",
                    capital=10,
                    intermediate_routes=35,
                    endpoint_routes=15,
                    excess=4.0,
                    pool_count=2,
                    venue_count=3,
                ),
                _row(
                    date,
                    "DAI",
                    capital=10,
                    intermediate_routes=25,
                    endpoint_routes=10,
                    excess=1.0,
                    pool_count=1,
                    venue_count=2,
                ),
            ]
        )
    panel = candidate_share_gap_panel(supported_candidate_days(pd.DataFrame(rows)))
    result = within_day_gap_associations(panel)
    stable = result[result["predictor"].eq("is_stable")].iloc[0]
    assert stable["record_type"] == "within_day_route_capital_gap_association"
    assert stable["coefficient"] > 0


def test_route_capital_gap_closing_detects_future_capital_reallocation() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    capital = {"WETH": 100, "WBTC": 25, "USDC": 10, "USDT": 10, "DAI": 10}
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        date = day.strftime("%Y-%m-%d")
        route_counts = {
            "WETH": 25 + day_index % 3,
            "WBTC": 10 + day_index % 5,
            "USDC": 32 + day_index % 7,
            "USDT": 28 + day_index % 11,
            "DAI": 15 + day_index % 2,
        }
        for symbol in symbols:
            rows.append(
                {
                    "origin_date": pd.Timestamp(date),
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 30,
                    "route_exact_target_supported": True,
                    "v2_exact_target_supported": True,
                    "intermediate_route_count": route_counts[symbol],
                    "endpoint_route_count": 10,
                    "v2_deposited_capital_usd": capital[symbol],
                    "v2_candidate_pool_count": 1,
                    "v2_candidate_venue_count": 1,
                }
            )
    frame = pd.DataFrame(rows)
    by_day = frame.groupby(["origin_date", "horizon_days"], sort=True)
    route_share = frame["intermediate_route_count"] / by_day[
        "intermediate_route_count"
    ].transform("sum")
    capital_share = frame["v2_deposited_capital_usd"] / by_day[
        "v2_deposited_capital_usd"
    ].transform("sum")
    gap = route_share - capital_share
    frame["future_v2_five_candidate_capital_share_change"] = 0.08 * gap
    frame["future_v2_log1p_deposited_capital_usd_change"] = 0.50 * gap

    panel = route_capital_gap_horizon_panel(frame)
    result = route_capital_gap_closing(
        panel,
        min_observations=100,
        min_clusters=20,
    )
    month = result[
        result["outcome"].eq("future_v2_five_candidate_capital_share_change")
    ].iloc[0]
    assert month["record_type"] == "route_capital_gap_closing"
    assert month["coefficient"] > 0
    assert month["coefficient_per_10pp_gap_pp"] > 0


def test_route_capital_gap_closing_stable_interaction_reports_total_effect() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    capital = {"WETH": 100, "WBTC": 25, "USDC": 10, "USDT": 10, "DAI": 10}
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        date = day.strftime("%Y-%m-%d")
        route_counts = {
            "WETH": 25 + day_index % 3,
            "WBTC": 10 + day_index % 5,
            "USDC": 32 + day_index % 7,
            "USDT": 28 + day_index % 11,
            "DAI": 15 + day_index % 2,
        }
        for symbol in symbols:
            rows.append(
                {
                    "origin_date": pd.Timestamp(date),
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 30,
                    "route_exact_target_supported": True,
                    "v2_exact_target_supported": True,
                    "intermediate_route_count": route_counts[symbol],
                    "endpoint_route_count": 10,
                    "v2_deposited_capital_usd": capital[symbol],
                    "v2_candidate_pool_count": 1,
                    "v2_candidate_venue_count": 1,
                }
            )
    frame = pd.DataFrame(rows)
    by_day = frame.groupby(["origin_date", "horizon_days"], sort=True)
    route_share = frame["intermediate_route_count"] / by_day[
        "intermediate_route_count"
    ].transform("sum")
    capital_share = frame["v2_deposited_capital_usd"] / by_day[
        "v2_deposited_capital_usd"
    ].transform("sum")
    gap = route_share - capital_share
    is_stable = frame["candidate_symbol"].isin({"DAI", "USDC", "USDT"}).astype(float)
    frame["future_v2_five_candidate_capital_share_change"] = 0.04 * gap + 0.06 * gap * is_stable
    frame["future_v2_log1p_deposited_capital_usd_change"] = 0.25 * gap + 0.25 * gap * is_stable

    panel = route_capital_gap_horizon_panel(frame)
    result = route_capital_gap_closing_stable_interactions(
        panel,
        min_observations=100,
        min_clusters=20,
    )
    stable_total = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_v2_five_candidate_capital_share_change")
    ].iloc[0]
    interaction = result[
        result["predictor"].eq("route_capital_gap_5_x_stable")
        & result["outcome"].eq("future_v2_five_candidate_capital_share_change")
    ].iloc[0]
    assert stable_total["coefficient"] > interaction["coefficient"]
    assert stable_total["coefficient_per_10pp_gap_pp"] > 0


def test_route_capital_gap_asymmetry_reports_stable_overhang_effect() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    capital = {"WETH": 100, "WBTC": 25, "USDC": 40, "USDT": 35, "DAI": 30}
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        date = day.strftime("%Y-%m-%d")
        route_counts = {
            "WETH": 30 + day_index % 3,
            "WBTC": 15 + day_index % 5,
            "USDC": 16 + day_index % 7,
            "USDT": 14 + day_index % 11,
            "DAI": 10 + day_index % 2,
        }
        for symbol in symbols:
            rows.append(
                {
                    "origin_date": pd.Timestamp(date),
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 30,
                    "route_exact_target_supported": True,
                    "v2_exact_target_supported": True,
                    "intermediate_route_count": route_counts[symbol],
                    "endpoint_route_count": 10,
                    "v2_deposited_capital_usd": capital[symbol],
                    "v2_candidate_pool_count": 1,
                    "v2_candidate_venue_count": 1,
                }
            )
    frame = pd.DataFrame(rows)
    by_day = frame.groupby(["origin_date", "horizon_days"], sort=True)
    route_share = frame["intermediate_route_count"] / by_day[
        "intermediate_route_count"
    ].transform("sum")
    capital_share = frame["v2_deposited_capital_usd"] / by_day[
        "v2_deposited_capital_usd"
    ].transform("sum")
    gap = route_share - capital_share
    stable = frame["candidate_symbol"].isin({"DAI", "USDC", "USDT"}).astype(float)
    negative_gap = gap.clip(upper=0.0)
    frame["future_v2_five_candidate_capital_share_change"] = (
        0.02 * gap + 0.50 * negative_gap * stable
    )
    frame["future_v2_log1p_deposited_capital_usd_change"] = (
        0.10 * gap + 1.50 * negative_gap * stable
    )

    panel = route_capital_gap_horizon_panel(frame)
    result = route_capital_gap_asymmetry(
        panel,
        min_observations=100,
        min_clusters=20,
    )
    overhang = result[
        result["predictor"].eq("stable_total_negative_route_capital_gap_5")
        & result["outcome"].eq("future_v2_five_candidate_capital_share_change")
    ].iloc[0]
    assert overhang["record_type"] == "route_capital_gap_asymmetry"
    assert overhang["coefficient"] > 0
    assert overhang["effect_per_10pp_stable_overcapitalization_pp"] < 0
