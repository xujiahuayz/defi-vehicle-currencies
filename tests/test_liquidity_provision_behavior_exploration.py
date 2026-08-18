from __future__ import annotations

import math
import gzip
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from scripts.analyze.run_liquidity_provision_behavior_exploration import (
    annual_stable_allocation,
    capital_concentration_summaries,
    capital_use_gap_summaries,
    candidate_capital_concentration_panel,
    candidate_share_gap_panel,
    daily_leader_alignment,
    daily_capital_use_gaps,
    route_capital_gap_asymmetry,
    route_capital_gap_candidate_specific,
    route_capital_gap_closing,
    route_capital_gap_closing_stable_interactions,
    route_capital_gap_concentration_horizon_panel,
    route_capital_gap_concentration_response,
    route_capital_gap_extensive_margin_panel,
    route_capital_gap_extensive_margins,
    route_capital_gap_horizon_panel,
    route_capital_gap_pool_entry_horizon_panel,
    route_capital_gap_pool_entry_response,
    route_capital_gap_pool_candidate_horizon_panel,
    route_capital_gap_rank_transition,
    route_capital_gap_rank_transition_panel,
    route_capital_gap_same_pool_reallocation,
    route_capital_gap_v3_fee_horizon_panel,
    route_capital_gap_v3_fee_incidence,
    route_capital_gap_v3_lp_action_horizon_panel,
    route_capital_gap_v3_lp_action_candidate_specific,
    route_capital_gap_v3_lp_action_response,
    stable_basket_gap_horizon_panel,
    stable_basket_gap_portfolio_rebalancing,
    supported_candidate_days,
    within_day_gap_associations,
)
from scripts.process.build_v3_lp_action_candidate_daily import (
    load_raw_uniswap_v3_lp_actions,
    v3_pool_candidate_links,
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


def test_rank_transition_reports_stable_capital_rank_catchup() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    capital = {"WETH": 100, "WBTC": 30, "USDC": 20, "USDT": 15, "DAI": 10}
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        route_counts = {
            "WETH": 30 + day_index % 3,
            "WBTC": 15 + day_index % 5,
            "USDC": 45 + day_index % 7,
            "USDT": 35 + day_index % 11,
            "DAI": 20 + day_index % 13,
        }
        for symbol in symbols:
            is_stable = symbol in {"DAI", "USDC", "USDT"}
            target_capital_share = (
                0.45 + 0.001 * (day_index % 9)
                if symbol == "WETH"
                else 0.10 + 0.002 * (day_index % 7)
            )
            if is_stable:
                target_capital_share += 0.03 * route_counts[symbol] / 100
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 120,
                    "route_exact_target_supported": True,
                    "v2_exact_target_supported": True,
                    "intermediate_route_count": route_counts[symbol],
                    "endpoint_route_count": 10,
                    "v2_deposited_capital_usd": capital[symbol],
                    "v2_candidate_pool_count": 1,
                    "v2_candidate_venue_count": 1,
                    "target_intermediary_episode_share": route_counts[symbol] / 150,
                    "target_v2_five_candidate_capital_share": target_capital_share,
                }
            )
    panel = route_capital_gap_rank_transition_panel(pd.DataFrame(rows))
    result = route_capital_gap_rank_transition(
        panel,
        min_observations=100,
        min_clusters=20,
    )
    stable_total = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_capital_rank_improvement")
    ].iloc[0]
    assert stable_total["record_type"] == "route_capital_gap_rank_transition"
    assert stable_total["coefficient"] > 0


def test_route_capital_gap_candidate_specific_reports_symbol_slopes() -> None:
    rows = []
    symbols = ["WETH", "USDC", "USDT"]
    capital = {"WETH": 90, "USDC": 40, "USDT": 30}
    slopes = {"WETH": 0.05, "USDC": 0.20, "USDT": 0.08}
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=80, freq="D")):
        date = day.strftime("%Y-%m-%d")
        route_counts = {
            "WETH": 50 + day_index % 7,
            "USDC": 45 + day_index % 11,
            "USDT": 20 + day_index % 5,
        }
        for symbol in symbols:
            rows.append(
                {
                    "origin_date": pd.Timestamp(date),
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 120,
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
    frame["future_v2_five_candidate_capital_share_change"] = [
        slopes[symbol] * gap_value
        for symbol, gap_value in zip(frame["candidate_symbol"], gap, strict=True)
    ]
    frame["future_v2_log1p_deposited_capital_usd_change"] = frame[
        "future_v2_five_candidate_capital_share_change"
    ]

    panel = route_capital_gap_horizon_panel(frame)
    result = route_capital_gap_candidate_specific(
        panel,
        min_observations=100,
        min_clusters=20,
    )
    share_rows = result[
        result["outcome"].eq("future_v2_five_candidate_capital_share_change")
    ].set_index("candidate_symbol")

    assert share_rows.loc["USDC", "record_type"] == "route_capital_gap_candidate_specific"
    assert share_rows.loc["USDC", "coefficient"] > share_rows.loc["USDT", "coefficient"]
    assert share_rows.loc["USDT", "coefficient"] > share_rows.loc["WETH", "coefficient"]


def test_same_pool_horizon_panel_joins_future_pool_candidate_capital() -> None:
    share_gap = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2024-01-01"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.2,
                "is_stable": 1.0,
            },
            {
                "origin_date": pd.Timestamp("2024-01-31"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.1,
                "is_stable": 1.0,
            },
        ]
    )
    pool_rows = [
        {
            "day": 20240101,
            "candidate_address": "usdc",
            "pool_candidate_id": "pool|USDC",
            "candidate_capital_usd": 100.0,
            "capital_validation_status": "exact_state_current",
            "quantity_kind": "deposited_capital",
        },
        {
            "day": 20240131,
            "candidate_address": "usdc",
            "pool_candidate_id": "pool|USDC",
            "candidate_capital_usd": 120.0,
            "capital_validation_status": "exact_state_current",
            "quantity_kind": "deposited_capital",
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pool_candidates.parquet"
        pd.DataFrame(pool_rows).to_parquet(path, index=False)
        panel = route_capital_gap_pool_candidate_horizon_panel(
            share_gap,
            pool_candidate_path=path,
            horizons=(30,),
        )
    row = panel.iloc[0]
    assert row["horizon_days"] == 30
    assert row["future_log_pool_candidate_capital_change"] > 0


def test_same_pool_reallocation_reports_stable_total() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        date_effect = 0.001 * day_index
        for symbol_index, symbol in enumerate(symbols):
            is_stable = float(symbol in {"DAI", "USDC", "USDT"})
            for pool_index in range(4):
                gap = (
                    0.15 * math.sin(day_index / 17 + pool_index + symbol_index / 3)
                    + 0.02 * (pool_index - 1.5)
                    + 0.01 * symbol_index
                )
                pool_effect = 0.03 * pool_index + 0.02 * symbol_index
                rows.append(
                    {
                        "origin_date": day,
                        "pool_candidate_id": f"pool-{pool_index}|{symbol}",
                        "candidate_address": symbol.lower(),
                        "candidate_symbol": symbol,
                        "is_stable": is_stable,
                        "route_capital_gap_5": gap,
                        "horizon_days": 30,
                        "future_log_pool_candidate_capital_change": (
                            0.05 * gap
                            + 0.08 * gap * is_stable
                            + pool_effect
                            + date_effect
                        ),
                    }
                )
    result = route_capital_gap_same_pool_reallocation(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_total = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
    ].iloc[0]
    assert stable_total["record_type"] == "route_capital_gap_same_pool_reallocation"
    assert stable_total["coefficient"] > 0


def test_pool_entry_horizon_panel_splits_incumbent_and_entrant_capital() -> None:
    share_gap = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2024-01-01"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.25,
                "is_stable": 1.0,
            }
        ]
    )
    pool_rows = pd.DataFrame(
        [
            {
                "day": "20240101",
                "candidate_address": "usdc",
                "pool_candidate_id": "pool-a|usdc",
                "candidate_capital_usd": 100.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_current",
            },
            {
                "day": "20240131",
                "candidate_address": "usdc",
                "pool_candidate_id": "pool-a|usdc",
                "candidate_capital_usd": 150.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_current",
            },
            {
                "day": "20240131",
                "candidate_address": "usdc",
                "pool_candidate_id": "pool-b|usdc",
                "candidate_capital_usd": 25.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_current",
            },
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pool_candidates.parquet"
        pool_rows.to_parquet(path, index=False)
        panel = route_capital_gap_pool_entry_horizon_panel(
            share_gap,
            pool_candidate_path=path,
            horizons=(30,),
        )
    row = panel.iloc[0]
    assert row["future_incumbent_capital"] == pytest.approx(150.0)
    assert row["future_entrant_capital"] == pytest.approx(25.0)
    assert row["future_entrant_pools"] == pytest.approx(1.0)
    assert row["future_log_total_capital_change"] == pytest.approx(
        math.log10(1.0 + 175.0) - math.log10(1.0 + 100.0)
    )


def test_pool_entry_response_reports_stable_total() -> None:
    rows = []
    symbols = ("WETH", "USDC", "USDT")
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        for symbol_index, symbol in enumerate(symbols):
            stable = float(symbol in {"USDC", "USDT"})
            gap = 0.10 + 0.01 * (((day_index + 2 * symbol_index) % 7) - 3)
            if symbol == "WETH":
                incumbent = 0.60 * gap
                entrant = 0.30 * gap
                total = 0.70 * gap
            else:
                incumbent = -0.20 * gap
                entrant = -0.30 * gap
                total = -0.25 * gap
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 120,
                    "is_stable": stable,
                    "route_capital_gap_5": gap,
                    "future_log_incumbent_capital_change": incumbent,
                    "future_log1p_entrant_capital": entrant,
                    "future_log_total_capital_change": total,
                    "future_entrant_capital_share": 0.05 + entrant,
                }
            )
    result = route_capital_gap_pool_entry_response(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_total = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log_total_capital_change")
    ].iloc[0]
    assert stable_total["record_type"] == "route_capital_gap_pool_entry_response"
    assert stable_total["coefficient"] < 0


def test_v3_fee_horizon_panel_joins_future_pool_day_fees() -> None:
    share_gap = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-01"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.2,
                "is_stable": 1.0,
            },
            {
                "origin_date": pd.Timestamp("2025-01-31"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.1,
                "is_stable": 1.0,
            },
        ]
    )
    fee_rows = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-01"),
                "pool": "pool",
                "token0_address": "usdc",
                "token1_address": "weth",
                "fees_usd": 100.0,
                "volume_usd": 10_000.0,
                "tvl_usd": 1_000_000.0,
            },
            {
                "origin_date": pd.Timestamp("2025-01-31"),
                "pool": "pool",
                "token0_address": "usdc",
                "token1_address": "weth",
                "fees_usd": 110.0,
                "volume_usd": 12_000.0,
                "tvl_usd": 1_000_000.0,
            },
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "fees.parquet"
        fee_rows.to_parquet(path, index=False)
        panel = route_capital_gap_v3_fee_horizon_panel(
            share_gap,
            fee_panel_path=path,
            horizons=(30,),
        )
    row = panel.iloc[0]
    assert row["horizon_days"] == 30
    assert row["future_log_fees_change"] > 0
    assert row["future_log_volume_change"] > 0
    assert row["future_log_fee_yield_bps_change"] > 0
    assert row["future_log_volume_turnover_change"] > 0


def test_v3_fee_incidence_reports_stable_total() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    for day_index, day in enumerate(pd.date_range("2025-01-01", periods=160, freq="D")):
        date_effect = 0.002 * day_index
        for symbol_index, symbol in enumerate(symbols):
            is_stable = float(symbol in {"DAI", "USDC", "USDT"})
            for pool_index in range(4):
                gap = (
                    0.12 * math.sin(day_index / 13 + pool_index + symbol_index / 4)
                    + 0.02 * (pool_index - 1.5)
                    + 0.01 * symbol_index
                )
                pool_effect = 0.04 * pool_index + 0.03 * symbol_index
                rows.append(
                    {
                        "origin_date": day,
                        "pool": f"pool-{pool_index}|{symbol}",
                        "candidate_address": symbol.lower(),
                        "candidate_symbol": symbol,
                        "is_stable": is_stable,
                        "route_capital_gap_5": gap,
                        "horizon_days": 30,
                        "future_log_fees_change": (
                            0.04 * gap
                            + 0.06 * gap * is_stable
                            + pool_effect
                            + date_effect
                        ),
                        "future_log_volume_change": (
                            0.03 * gap
                            + 0.05 * gap * is_stable
                            + pool_effect
                            + date_effect
                        ),
                        "future_log_fee_yield_bps_change": (
                            0.02 * gap
                            + 0.03 * gap * is_stable
                            + pool_effect
                            + date_effect
                        ),
                        "future_log_volume_turnover_change": (
                            0.01 * gap
                            + 0.02 * gap * is_stable
                            + pool_effect
                            + date_effect
                        ),
                    }
                )
    result = route_capital_gap_v3_fee_incidence(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_total = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log_fees_change")
    ].iloc[0]
    assert stable_total["record_type"] == "route_capital_gap_v3_fee_incidence"
    assert stable_total["coefficient"] > 0


def _write_v3_event(path: Path, *, pool: str, timestamp: int, origin: str) -> None:
    event = {
        "id": f"{pool}-{timestamp}",
        "timestamp": str(timestamp),
        "pool": {"id": pool},
        "owner": origin,
        "origin": origin,
        "amount": "1",
        "amount0": "1",
        "amount1": "1",
        "tickLower": "0",
        "tickUpper": "1",
        "logIndex": "0",
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_v3_lp_action_loader_counts_candidate_mint_and_burn_events() -> None:
    fee_rows = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-01"),
                "pool": "pool-a",
                "token0_address": "usdc",
                "token0_symbol": "USDC",
                "token1_address": "weth",
                "token1_symbol": "WETH",
                "fees_usd": 10.0,
                "volume_usd": 100.0,
                "tvl_usd": 1_000.0,
            }
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        event_dir = root / "events"
        event_dir.mkdir()
        fee_path = root / "fees.parquet"
        fee_rows.to_parquet(fee_path, index=False)
        _write_v3_event(
            event_dir / "uniswap_v3_mints_20250101.jsonl.gz",
            pool="pool-a",
            timestamp=1_735_689_600,
            origin="lp-1",
        )
        _write_v3_event(
            event_dir / "uniswap_v3_burns_20250101.jsonl.gz",
            pool="pool-a",
            timestamp=1_735_689_600,
            origin="lp-2",
        )
        links = v3_pool_candidate_links(
            fee_panel_path=fee_path,
            candidate_addresses={"usdc"},
        )
        actions, support = load_raw_uniswap_v3_lp_actions(
            event_dir=event_dir,
            pool_candidates=links,
        )
    row = actions.iloc[0]
    assert row["candidate_symbol"] == "USDC"
    assert row["v3_mint_events"] == 1
    assert row["v3_burn_events"] == 1
    assert row["v3_mint_origin_count"] == 1
    assert support["matched_candidate_event_assignments"] == 2


def test_v3_lp_action_horizon_panel_sums_future_actions() -> None:
    share_gap = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-01"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.2,
                "is_stable": 1.0,
            },
            {
                "origin_date": pd.Timestamp("2025-01-02"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "route_capital_gap_5": 0.1,
                "is_stable": 1.0,
            },
        ]
    )
    actions = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-02"),
                "candidate_address": "usdc",
                "candidate_symbol": "USDC",
                "v3_mint_events": 2,
                "v3_burn_events": 1,
                "v3_total_lp_actions": 3,
                "v3_net_mint_events": 1,
                "v3_mint_origin_count": 2,
                "v3_burn_origin_count": 1,
            }
        ]
    )
    panel = route_capital_gap_v3_lp_action_horizon_panel(
        share_gap,
        actions=actions,
        horizons=(1,),
    )
    row = panel[panel["origin_date"].eq(pd.Timestamp("2025-01-01"))].iloc[0]
    assert row["future_v3_mint_events"] == 2
    assert row["future_v3_burn_events"] == 1
    assert row["future_v3_total_origin_count"] == 3
    assert row["future_log1p_v3_total_origin_count"] > 0
    assert row["future_v3_net_mint_event_balance"] > 0


def test_v3_lp_action_response_reports_stable_total() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    for day_index, day in enumerate(pd.date_range("2025-01-01", periods=180, freq="D")):
        date_effect = 0.001 * day_index
        for symbol_index, symbol in enumerate(symbols):
            is_stable = float(symbol in {"DAI", "USDC", "USDT"})
            gap = (
                0.10 * math.sin(day_index / 11 + symbol_index / 3)
                + 0.02 * (symbol_index - 2)
            )
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "is_stable": is_stable,
                    "route_capital_gap_5": gap,
                    "horizon_days": 30,
                    "future_log1p_v3_mint_events": (
                        0.03 * gap
                        + 0.08 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_burn_events": (
                        0.01 * gap
                        + 0.02 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_total_lp_actions": (
                        0.02 * gap
                        + 0.05 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_v3_net_mint_event_balance": (
                        0.01 * gap
                        + 0.04 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_mint_origin_count": (
                        0.04 * gap
                        + 0.08 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_burn_origin_count": (
                        0.02 * gap
                        + 0.06 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_total_origin_count": (
                        0.03 * gap
                        + 0.07 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                }
            )
    result = route_capital_gap_v3_lp_action_response(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_mint = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log1p_v3_mint_events")
    ].iloc[0]
    assert stable_mint["record_type"] == "route_capital_gap_v3_lp_action"
    assert stable_mint["coefficient"] > 0
    stable_origin = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log1p_v3_total_origin_count")
    ].iloc[0]
    assert stable_origin["coefficient"] > 0


def test_v3_lp_action_candidate_specific_reports_issuer_responses() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    action_slopes = {
        "WETH": -0.1,
        "WBTC": 0.1,
        "USDC": 0.8,
        "USDT": 1.8,
        "DAI": 1.2,
    }
    net_slopes = {
        "WETH": 0.0,
        "WBTC": 0.0,
        "USDC": 0.08,
        "USDT": -0.10,
        "DAI": 0.12,
    }
    for day_index, day in enumerate(pd.date_range("2025-01-01", periods=180, freq="D")):
        date_effect = 0.001 * day_index
        for symbol_index, symbol in enumerate(symbols):
            gap = (
                0.10 * math.sin(day_index / 11 + symbol_index / 3)
                + 0.02 * (symbol_index - 2)
            )
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "route_capital_gap_5": gap,
                    "horizon_days": 30,
                    "future_log1p_v3_mint_events": (
                        action_slopes[symbol] * gap + date_effect + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_burn_events": (
                        0.9 * action_slopes[symbol] * gap
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_total_lp_actions": (
                        action_slopes[symbol] * gap + date_effect + 0.02 * symbol_index
                    ),
                    "future_v3_net_mint_event_balance": (
                        net_slopes[symbol] * gap + date_effect + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_mint_origin_count": (
                        action_slopes[symbol] * gap + date_effect + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_burn_origin_count": (
                        0.9 * action_slopes[symbol] * gap
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log1p_v3_total_origin_count": (
                        action_slopes[symbol] * gap + date_effect + 0.02 * symbol_index
                    ),
                }
            )
    result = route_capital_gap_v3_lp_action_candidate_specific(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    usdt_actions = result[
        result["candidate_symbol"].eq("USDT")
        & result["outcome"].eq("future_log1p_v3_total_lp_actions")
    ].iloc[0]
    usdc_actions = result[
        result["candidate_symbol"].eq("USDC")
        & result["outcome"].eq("future_log1p_v3_total_lp_actions")
    ].iloc[0]
    usdt_net = result[
        result["candidate_symbol"].eq("USDT")
        & result["outcome"].eq("future_v3_net_mint_event_balance")
    ].iloc[0]
    usdt_origin = result[
        result["candidate_symbol"].eq("USDT")
        & result["outcome"].eq("future_log1p_v3_total_origin_count")
    ].iloc[0]
    usdc_origin = result[
        result["candidate_symbol"].eq("USDC")
        & result["outcome"].eq("future_log1p_v3_total_origin_count")
    ].iloc[0]
    assert usdt_actions["record_type"] == "route_capital_gap_v3_lp_action_candidate_specific"
    assert usdt_actions["coefficient"] > usdc_actions["coefficient"]
    assert usdt_origin["coefficient"] > usdc_origin["coefficient"]
    assert usdt_net["coefficient"] < 0


def test_capital_concentration_panel_summarizes_top_pool_shares(sample) -> None:
    share_gap = candidate_share_gap_panel(sample)
    rows = []
    for day in ("20240101", "20260101"):
        rows.extend(
            [
                {
                    "day": int(day),
                    "candidate_address": "weth",
                    "candidate_symbol_raw": "WETH",
                    "pool": "weth-a",
                    "venue": "uniswap_v2",
                    "candidate_capital_usd": 80.0,
                    "quantity_kind": "deposited_capital",
                    "capital_validation_status": "exact_state_current",
                },
                {
                    "day": int(day),
                    "candidate_address": "weth",
                    "candidate_symbol_raw": "WETH",
                    "pool": "weth-b",
                    "venue": "sushiswap_v2",
                    "candidate_capital_usd": 20.0,
                    "quantity_kind": "deposited_capital",
                    "capital_validation_status": "exact_state_current",
                },
                {
                    "day": int(day),
                    "candidate_address": "usdc",
                    "candidate_symbol_raw": "USDC",
                    "pool": "usdc-a",
                    "venue": "uniswap_v2",
                    "candidate_capital_usd": 18.0,
                    "quantity_kind": "deposited_capital",
                    "capital_validation_status": "exact_state_current",
                },
                {
                    "day": int(day),
                    "candidate_address": "usdc",
                    "candidate_symbol_raw": "USDC",
                    "pool": "usdc-b",
                    "venue": "sushiswap_v2",
                    "candidate_capital_usd": 2.0,
                    "quantity_kind": "deposited_capital",
                    "capital_validation_status": "exact_state_current",
                },
            ]
        )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pool_candidates.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        panel = candidate_capital_concentration_panel(
            share_gap,
            pool_candidate_path=path,
        )
    usdc = panel[panel["candidate_symbol"].eq("USDC")].iloc[0]
    assert usdc["top_pool_share"] == pytest.approx(0.9)
    assert usdc["pool_hhi"] == pytest.approx(0.82)
    summaries = capital_concentration_summaries(panel)
    stable = summaries[
        summaries["record_type"].eq("capital_concentration_year")
        & summaries["candidate_group"].eq("stable_candidates")
    ].iloc[0]
    assert stable["capital_weighted_top_pool_share"] == pytest.approx(0.9)


def test_route_capital_gap_concentration_response_reports_stable_total() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=180, freq="D")):
        date_effect = 0.001 * day_index
        for symbol_index, symbol in enumerate(symbols):
            is_stable = float(symbol in {"DAI", "USDC", "USDT"})
            gap = (
                0.10 * math.sin(day_index / 11 + symbol_index / 3)
                + 0.02 * (symbol_index - 2)
            )
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "is_stable": is_stable,
                    "route_capital_gap_5": gap,
                    "horizon_days": 120,
                    "future_top_pool_share_change": (
                        -0.01 * gap
                        + 0.07 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_pool_hhi_change": (
                        -0.01 * gap
                        + 0.08 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_log_effective_pool_count_change": (
                        0.01 * gap
                        - 0.07 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                    "future_pool_count_change": (
                        0.01 * gap
                        + 0.03 * gap * is_stable
                        + date_effect
                        + 0.02 * symbol_index
                    ),
                }
            )
    result = route_capital_gap_concentration_response(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_hhi = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_pool_hhi_change")
    ].iloc[0]
    stable_effective = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log_effective_pool_count_change")
    ].iloc[0]
    assert stable_hhi["record_type"] == "route_capital_gap_concentration_response"
    assert stable_hhi["coefficient"] > 0
    assert stable_effective["coefficient"] < 0


def test_extensive_margin_panel_attaches_future_pool_and_venue_counts() -> None:
    rows = []
    for date, pool_shift, venue_shift in (
        ("2024-01-01", 0, 0),
        ("2024-01-31", 1, 1),
    ):
        rows.extend(
            [
                _row(
                    date,
                    "WETH",
                    capital=100,
                    intermediate_routes=40,
                    endpoint_routes=50,
                    excess=0.8,
                    pool_count=5 + pool_shift,
                    venue_count=2,
                ),
                _row(
                    date,
                    "WBTC",
                    capital=10,
                    intermediate_routes=5,
                    endpoint_routes=10,
                    excess=0.5,
                    pool_count=2,
                    venue_count=1,
                ),
                _row(
                    date,
                    "USDC",
                    capital=20,
                    intermediate_routes=30,
                    endpoint_routes=20,
                    excess=3.0,
                    pool_count=3 + pool_shift,
                    venue_count=1 + venue_shift,
                ),
                _row(
                    date,
                    "USDT",
                    capital=10,
                    intermediate_routes=20,
                    endpoint_routes=10,
                    excess=4.0,
                    pool_count=3,
                    venue_count=1 + venue_shift,
                ),
                _row(
                    date,
                    "DAI",
                    capital=10,
                    intermediate_routes=5,
                    endpoint_routes=10,
                    excess=1.0,
                    pool_count=1,
                    venue_count=1,
                ),
            ]
        )
    panel = route_capital_gap_extensive_margin_panel(
        supported_candidate_days(pd.DataFrame(rows)),
        horizons=(30,),
    )
    usdc = panel[panel["candidate_symbol"].eq("USDC")].iloc[0]
    assert usdc["horizon_days"] == 30
    assert usdc["future_log_pool_count_change"] > 0
    assert usdc["future_log_venue_count_change"] > 0


def test_route_capital_gap_extensive_margins_report_stable_total() -> None:
    rows = []
    symbols = ["WETH", "WBTC", "USDC", "USDT", "DAI"]
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        for symbol_index, symbol in enumerate(symbols):
            is_stable = float(symbol in {"DAI", "USDC", "USDT"})
            gap = (
                ((symbol_index - 2) / 10)
                + ((day_index % 7) - 3) / 100
                + ((day_index % (symbol_index + 2)) / 100)
            )
            noise = ((day_index * (symbol_index + 1)) % 11) / 10000
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": symbol.lower(),
                    "candidate_symbol": symbol,
                    "horizon_days": 30,
                    "is_stable": is_stable,
                    "route_capital_gap_5": gap,
                    "future_log_pool_count_change": 0.02 * gap
                    - 0.10 * gap * is_stable
                    + noise,
                    "future_log_venue_count_change": -0.02 * gap
                    + 0.08 * gap * is_stable
                    + noise,
                }
            )
    result = route_capital_gap_extensive_margins(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable_venue = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log_venue_count_change")
    ].iloc[0]
    stable_pool = result[
        result["predictor"].eq("stable_total_route_capital_gap_5")
        & result["outcome"].eq("future_log_pool_count_change")
    ].iloc[0]
    assert stable_venue["record_type"] == "route_capital_gap_extensive_margin"
    assert stable_venue["coefficient_per_10pp_gap_percent"] > 0
    assert stable_pool["coefficient_per_10pp_gap_percent"] < 0


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


def test_stable_basket_gap_horizon_panel_builds_future_portfolio_changes() -> None:
    rows = []
    for date in ("2024-01-01", "2024-01-02"):
        rows.extend(
            [
                _row(date, "WETH", capital=100, intermediate_routes=40, endpoint_routes=50, excess=0.8),
                _row(date, "WBTC", capital=10, intermediate_routes=5, endpoint_routes=10, excess=0.5),
                _row(date, "USDC", capital=20, intermediate_routes=30, endpoint_routes=20, excess=3.0),
                _row(date, "USDT", capital=10, intermediate_routes=20, endpoint_routes=10, excess=4.0),
                _row(date, "DAI", capital=10, intermediate_routes=5, endpoint_routes=10, excess=1.0),
            ]
        )
    panel = stable_basket_gap_horizon_panel(
        supported_candidate_days(pd.DataFrame(rows)),
        horizons=(1,),
    )
    assert "stable_route_capital_gap" in panel
    assert "future_stable_capital_share_change" in panel
    assert "future_weth_capital_share_change" in panel


def test_stable_basket_portfolio_rebalancing_reports_weth_offset() -> None:
    rows = []
    for day_index, day in enumerate(pd.date_range("2024-01-01", periods=220, freq="D")):
        gap = ((day_index % 11) - 5) / 100
        rows.append(
            {
                "origin_date": day,
                "horizon_days": 30,
                "stable_route_capital_gap": gap,
                "future_stable_capital_share_change": 0.20 * gap,
                "future_weth_capital_share_change": -0.18 * gap,
                "future_wbtc_capital_share_change": -0.02 * gap,
                "log_total_routes": 5.0 + 0.01 * (day_index % 7),
                "log_total_capital": 8.0 + 0.01 * (day_index % 5),
            }
        )
    result = stable_basket_gap_portfolio_rebalancing(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=20,
    )
    stable = result[
        result["model_id"].eq("activity_controls")
        & result["outcome"].eq("future_stable_capital_share_change")
        & result["predictor"].eq("stable_route_capital_gap")
    ].iloc[0]
    weth = result[
        result["model_id"].eq("activity_controls")
        & result["outcome"].eq("future_weth_capital_share_change")
        & result["predictor"].eq("stable_route_capital_gap")
    ].iloc[0]
    assert stable["record_type"] == "stable_basket_gap_portfolio_rebalancing"
    assert stable["coefficient_per_10pp_gap_pp"] > 0
    assert weth["coefficient_per_10pp_gap_pp"] < 0
