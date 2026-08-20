from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pandas as pd

from scripts.analyze.run_bridge_liquidity_dominance import (
    bridge_establishment_adoption_timing_from_events,
    bridge_establishment_depth_regressions,
    bridge_establishment_depth_summaries,
    bridge_establishment_period_summaries,
    bridge_liquidity_bottleneck_regressions,
    bridge_liquidity_depth_regressions,
    bridge_liquidity_entry_birth_panel,
    bridge_liquidity_entry_birth_regressions,
    bridge_liquidity_horse_race_regressions,
    bridge_liquidity_leave_one_candidate_regressions,
    bridge_liquidity_stable_issuer_regressions,
    bridge_liquidity_top_rank_summaries,
    load_bridge_establishment_event_panel,
    load_bridge_liquidity_panel,
)
from scripts.tabulate.build_bridge_liquidity_deck_values import (
    render_bridge_establishment_table,
    render_bridge_liquidity_deck_values,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def test_bridge_establishment_separates_support_from_route_adoption() -> None:
    choice_rows = []
    for date, native_routes, stable_routes in [
        ("2024-01-01", 4, 0),
        ("2024-01-05", 5, 0),
        ("2024-01-15", 6, 0),
        ("2024-01-25", 7, 0),
        ("2024-02-01", 8, 0),
        ("2024-02-10", 8, 2),
        ("2024-02-20", 7, 3),
        ("2024-04-01", 6, 4),
        ("2024-05-15", 5, 5),
        ("2024-06-30", 4, 6),
    ]:
        choice_rows.append(
            {
                "date": pd.Timestamp(date),
                "src": "src",
                "tgt": "tgt",
                "integration_scope": "single_venue",
                "candidate_type": "native",
                "candidate_symbol": "WETH",
                "candidate_address": WETH,
                "route_count": native_routes,
                "within_20pct_value_usd": 100.0 * native_routes,
            }
        )
        if stable_routes:
            choice_rows.append(
                {
                    "date": pd.Timestamp(date),
                    "src": "src",
                    "tgt": "tgt",
                    "integration_scope": "single_venue",
                    "candidate_type": "stable",
                    "candidate_symbol": "USDC",
                    "candidate_address": USDC,
                    "route_count": stable_routes,
                    "within_20pct_value_usd": 100.0 * stable_routes,
                }
            )
    pool_rows = []
    for date in pd.date_range("2024-02-01", periods=24, freq="D"):
        for token0, token1, pool, current_capital, lagged_capital in [
            ("src", USDC, "src-usdc", 1_000.0, 100.0),
            (USDC, "tgt", "usdc-tgt", 1_000.0, 100.0),
            ("src", WETH, "src-weth", 50.0, 200.0),
            (WETH, "tgt", "weth-tgt", 50.0, 200.0),
        ]:
            pool_rows.append(
                {
                    "day": int(date.strftime("%Y%m%d")),
                    "token0_address": token0,
                    "token1_address": token1,
                    "pool": pool,
                    "venue": "uniswap_v2",
                    "capital_usd": current_capital,
                    "capital_usd_lagged": lagged_capital,
                    "quantity_kind": "deposited_capital",
                    "capital_validation_status": "exact_state_prior_calendar",
                }
            )
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        choices_path = root / "choices.parquet"
        pool_path = root / "pool.parquet"
        pd.DataFrame(choice_rows).to_parquet(choices_path, index=False)
        pd.DataFrame(pool_rows).to_parquet(pool_path, index=False)
        event = load_bridge_establishment_event_panel(
            choices_path=choices_path,
            pool_capital_path=pool_path,
        )
    assert event["event_date"].nunique() == 1
    assert event["event_date"].iloc[0] == pd.Timestamp("2024-02-01")
    assert event["first_stable_route_date"].iloc[0] == pd.Timestamp("2024-02-10")
    assert event["event_stablecoins"].iloc[0] == "USDC"
    assert event["support_days_30"].iloc[0] == 24
    event_day = event[event["origin_date"].eq(pd.Timestamp("2024-02-01"))].iloc[0]
    assert event_day["stable_share"] == 0
    assert event_day["stable_bridge_min_capital_usd"] == 100.0
    assert event_day["native_bridge_min_capital_usd"] == 200.0
    assert event_day["stable_to_native_depth_ratio"] == 0.5
    adoption_day = event[event["origin_date"].eq(pd.Timestamp("2024-02-10"))].iloc[0]
    assert adoption_day["stable_share"] == 0.2
    summary = bridge_establishment_period_summaries(event)
    pre = summary[summary["period"].eq("pre_30")].iloc[0]
    post = summary[summary["period"].eq("post_0_29")].iloc[0]
    assert pre["stable_route_share"] == 0
    assert post["stable_route_share"] > 0


def test_bridge_establishment_timing_separates_presence_from_depth() -> None:
    rows = []
    for index in range(40):
        competitive = index >= 20
        within_30 = (index % 20) < (16 if competitive else 8)
        within_120 = (index % 20) < (18 if competitive else 10)
        if within_30:
            lag = 0 if index % 5 == 0 else 12
        elif within_120:
            lag = 75
        else:
            lag = None
        event_date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)
        rows.append(
            {
                "event_id": f"event-{index}",
                "ordered_pair": f"src-{index}|tgt-{index}",
                "event_date": event_date,
                "first_stable_route_date": (
                    event_date + pd.Timedelta(days=lag) if lag is not None else pd.NaT
                ),
                "stable_bridge_min_capital_usd": 20.0 if competitive else 5.0,
                "native_bridge_min_capital_usd": 100.0,
            }
        )
    result = bridge_establishment_adoption_timing_from_events(
        pd.DataFrame(rows),
        min_observations=20,
        min_clusters=5,
    )
    month = result[
        result["record_type"].eq("bridge_establishment_timing_summary")
        & result["model_id"].eq("within_30_days")
    ].iloc[0]
    assert month["adoption_events"] == 24
    assert month["adoption_share"] == 0.6
    shallow = result[
        result["record_type"].eq("bridge_establishment_timing_depth_summary")
        & result["model_id"].eq("within_30_days")
        & result["depth_group"].eq("below_0.1x")
    ].iloc[0]
    competitive = result[
        result["record_type"].eq("bridge_establishment_timing_depth_summary")
        & result["model_id"].eq("within_30_days")
        & result["depth_group"].eq("at_least_0.1x")
    ].iloc[0]
    assert shallow["adoption_share"] == 0.4
    assert competitive["adoption_share"] == 0.8
    regression = result[
        result["record_type"].eq("bridge_establishment_timing_regression")
        & result["model_id"].eq("adoption_within_30_on_competitive_depth")
    ].iloc[0]
    assert math.isclose(regression["coefficient"], 0.4)
    assert regression["standard_error"] > 0


def test_bridge_establishment_continuous_depth_tracks_route_allocation() -> None:
    rows = []
    base_ratios = [0.05, 0.25, 0.75, 1.5, 3.0] * 4
    for period_index, period in enumerate(("post_0_29", "post_30_119")):
        for event_index in range(35):
            event_effect = 0.002 * (event_index % 5)
            for observation_index, base_ratio in enumerate(base_ratios):
                ratio = base_ratio * (1.0 + 0.05 * (event_index % 7))
                native_depth = 100.0
                stable_depth = ratio * native_depth
                depth_share = stable_depth / (stable_depth + native_depth)
                stable_share = 0.08 + 0.60 * depth_share + event_effect
                total_routes = 100.0
                total_value = 1_000.0
                rows.append(
                    {
                        "period": period,
                        "event_id": f"{period_index}-{event_index}",
                        "ordered_pair": f"src{event_index}|tgt{event_index}",
                        "origin_date": pd.Timestamp("2024-01-01")
                        + pd.Timedelta(days=period_index * 300 + observation_index),
                        "event_time": observation_index + 30 * period_index,
                        "stable_bridge_min_capital_usd": stable_depth,
                        "native_bridge_min_capital_usd": native_depth,
                        "stable_bridge_depth_share": depth_share,
                        "stable_to_native_depth_ratio": ratio,
                        "stable_share": stable_share,
                        "stable_value_share": stable_share,
                        "stable_routes": stable_share * total_routes,
                        "total_routes": total_routes,
                        "stable_value_usd": stable_share * total_value,
                        "total_value_usd": total_value,
                    }
                )
    panel = pd.DataFrame(rows)
    summaries = bridge_establishment_depth_summaries(panel)
    low = summaries[
        summaries["period"].eq("post_0_29")
        & summaries["depth_bin"].eq("below_0.1x")
    ].iloc[0]
    high = summaries[
        summaries["period"].eq("post_0_29")
        & summaries["depth_bin"].eq("at_least_2x")
    ].iloc[0]
    assert high["stable_route_share"] > low["stable_route_share"]

    regressions = bridge_establishment_depth_regressions(
        panel,
        min_observations=30,
        min_clusters=3,
    )
    slope = regressions[
        regressions["period"].eq("post_0_29")
        & regressions["model_id"].eq("stable_route_share_on_relative_depth")
    ].iloc[0]
    assert slope["coefficient"] > 0
    threshold = regressions[
        regressions["period"].eq("post_0_29")
        & regressions["model_id"].eq(
            "stable_route_share_when_depth_at_least_2x_native"
        )
    ].iloc[0]
    assert 0 < threshold["native_retained_share"] < 1


def test_bridge_liquidity_panel_uses_prior_two_leg_capital() -> None:
    choices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "candidate_address": WETH,
                "candidate_symbol": "WETH",
                "integration_scope": "single_venue",
                "route_count": 8,
            },
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
                "integration_scope": "single_venue",
                "route_count": 2,
            },
        ]
    )
    pool = pd.DataFrame(
        [
            {
                "day": 20240102,
                "token0_address": "src",
                "token1_address": WETH,
                "pool": "src-weth",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 100.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": WETH,
                "token1_address": "tgt",
                "pool": "weth-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 25.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": "src",
                "token1_address": USDC,
                "pool": "src-usdc",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 9.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": USDC,
                "token1_address": "tgt",
                "pool": "usdc-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 16.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        choices_path = root / "choices.parquet"
        pool_path = root / "pool.parquet"
        choices.to_parquet(choices_path, index=False)
        pool.to_parquet(pool_path, index=False)
        panel = load_bridge_liquidity_panel(
            choices_path=choices_path,
            pool_capital_path=pool_path,
        )
    weth = panel[panel["candidate_symbol"].eq("WETH")].iloc[0]
    usdc = panel[panel["candidate_symbol"].eq("USDC")].iloc[0]
    assert weth["bridge_min_capital_usd"] == 25.0
    assert weth["bridge_geom_capital_usd"] == 50.0
    assert weth["route_share_five"] == 0.8
    assert usdc["bridge_min_capital_usd"] == 9.0
    assert panel["supported_candidates"].min() == 2
    assert "log_global_route_count_day_leaveout" in panel.columns
    assert "log_global_route_count_lag30" in panel.columns


def test_bridge_liquidity_panel_can_keep_zero_bridge_candidates() -> None:
    choices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "candidate_address": WETH,
                "candidate_symbol": "WETH",
                "integration_scope": "single_venue",
                "route_count": 8,
            },
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
                "integration_scope": "single_venue",
                "route_count": 2,
            },
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "candidate_address": DAI,
                "candidate_symbol": "DAI",
                "integration_scope": "single_venue",
                "route_count": 1,
            },
        ]
    )
    pool = pd.DataFrame(
        [
            {
                "day": 20240102,
                "token0_address": "src",
                "token1_address": WETH,
                "pool": "src-weth",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 100.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": WETH,
                "token1_address": "tgt",
                "pool": "weth-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 25.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": "src",
                "token1_address": USDC,
                "pool": "src-usdc",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 9.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": USDC,
                "token1_address": "tgt",
                "pool": "usdc-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 1_000.0,
                "capital_usd_lagged": 16.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        choices_path = root / "choices.parquet"
        pool_path = root / "pool.parquet"
        choices.to_parquet(choices_path, index=False)
        pool.to_parquet(pool_path, index=False)
        supported = load_bridge_liquidity_panel(
            choices_path=choices_path,
            pool_capital_path=pool_path,
        )
        broad = load_bridge_liquidity_panel(
            choices_path=choices_path,
            pool_capital_path=pool_path,
            include_zero_bridge_candidates=True,
        )
    assert len(supported) == 2
    assert len(broad) == 5
    dai = broad[broad["candidate_address"].eq(DAI)].iloc[0]
    assert dai["bridge_min_capital_usd"] == 0
    assert dai["log_bridge_min_capital"] == 0
    assert dai["supported_candidates"] == 2


def test_bridge_liquidity_rank_summary_names_top_candidate_share() -> None:
    panel = pd.DataFrame(
        [
            {
                "choice_group_id": "g1",
                "origin_date": pd.Timestamp("2024-01-01"),
                "year": 2024,
                "ordered_pair": "a|b",
                "candidate_symbol": "WETH",
                "route_count": 8.0,
                "five_route_total": 10.0,
                "bridge_min_capital_usd": 100.0,
                "selected_five": 1.0,
                "is_stable": 0.0,
                "supported_candidates": 2.0,
            },
            {
                "choice_group_id": "g1",
                "origin_date": pd.Timestamp("2024-01-01"),
                "year": 2024,
                "ordered_pair": "a|b",
                "candidate_symbol": "USDC",
                "route_count": 2.0,
                "five_route_total": 10.0,
                "bridge_min_capital_usd": 10.0,
                "selected_five": 1.0,
                "is_stable": 1.0,
                "supported_candidates": 2.0,
            },
        ]
    )
    result = bridge_liquidity_top_rank_summaries(panel)
    pooled = result[result["sample"].eq("pooled")].iloc[0]
    assert pooled["top_bridge_route_share"] == 0.8
    assert pooled["choice_groups"] == 1


def test_bridge_liquidity_depth_regression_reports_positive_slope() -> None:
    rows = []
    candidates = [(WETH, 0.0), (USDC, 1.0), (DAI, 1.0)]
    for group_index in range(160):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=group_index)
        group_effect = 0.001 * group_index
        for candidate_index, (candidate, is_stable) in enumerate(candidates):
            log_depth = (
                5.0
                + 0.4 * candidate_index
                + math.sin(group_index / 9 + 0.7 * candidate_index)
                + 0.03 * ((group_index * (candidate_index + 1)) % 5)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 40}",
                    "five_route_total": 10.0 + group_index % 3,
                    "route_share_five": (
                        0.05 * log_depth
                        + 0.03 * log_depth * is_stable
                        + group_effect
                        + 0.02 * candidate_index
                    ),
                    "selected_five": float(
                        log_depth + 0.002 * group_index + 0.2 * is_stable > 5.9
                    ),
                    "log_bridge_min_capital": log_depth,
                    "log_bridge_min_capital_x_stable": log_depth * is_stable,
                }
            )
    result = bridge_liquidity_depth_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    row = result[
        result["model_id"].eq("route_share_log_min_depth")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    assert row["coefficient"] > 0
    stable_total = result[
        result["model_id"].eq("route_share_log_min_depth_stable_interaction")
        & result["regressor"].eq("stable_total_log_bridge_min_capital")
    ].iloc[0]
    assert stable_total["coefficient"] > row["coefficient"]


def test_bridge_liquidity_horse_race_keeps_local_depth_slope() -> None:
    rows = []
    candidates = [(WETH, 0.0), (USDC, 1.0), (DAI, 1.0)]
    for group_index in range(180):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=group_index)
        group_effect = 0.0007 * group_index
        for candidate_index, (candidate, is_stable) in enumerate(candidates):
            log_depth = (
                4.5
                + 0.6 * candidate_index
                + math.sin(group_index / 11 + 0.8 * candidate_index)
                + 0.02 * ((group_index * (candidate_index + 2)) % 7)
            )
            global_reach = (
                2.0
                + 0.01 * group_index
                + 0.5 * candidate_index
                + math.cos(group_index / 13 + candidate_index)
            )
            lag_route_reach = (
                1.5
                + 0.03 * ((group_index * (candidate_index + 3)) % 17)
                + 0.4 * math.sin(group_index / 17 + 0.3 * candidate_index)
            )
            lag_pair_reach = (
                1.0
                + 0.02 * ((group_index + 2 * candidate_index) % 13)
                + 0.3 * math.cos(group_index / 19 + 0.5 * candidate_index)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 45}",
                    "five_route_total": 20.0 + group_index % 4,
                    "route_share_five": (
                        0.055 * log_depth
                        + 0.018 * global_reach
                        + 0.010 * lag_route_reach
                        + group_effect
                        + 0.01 * candidate_index
                    ),
                    "selected_five": float(
                        log_depth + 0.15 * global_reach + 0.1 * is_stable > 5.8
                    ),
                    "is_stable": is_stable,
                    "log_bridge_min_capital": log_depth,
                    "log_global_route_count_day_leaveout": global_reach + 0.2,
                    "log_global_route_count_lag30": lag_route_reach,
                    "log_global_pair_count_lag30": lag_pair_reach,
                }
            )
    result = bridge_liquidity_horse_race_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    row = result[
        result["model_id"].eq("route_share_depth_global_reach_candidate_fe")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    assert row["coefficient"] > 0


def test_bridge_liquidity_entry_birth_panel_filters_first_observed_pairs() -> None:
    panel = pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "choice_group_id": "g1",
                "ordered_pair": "src|tgt",
                "candidate_address": WETH,
            },
            {
                "origin_date": pd.Timestamp("2024-01-03"),
                "src": "src2",
                "tgt": "tgt2",
                "choice_group_id": "g2",
                "ordered_pair": "src2|tgt2",
                "candidate_address": USDC,
            },
        ]
    )
    support = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src",
                "tgt": "tgt",
                "pair_entry_on_day": True,
                "primary_choice_route_count": 1,
            },
            {
                "date": pd.Timestamp("2024-01-03"),
                "src": "src2",
                "tgt": "tgt2",
                "pair_entry_on_day": False,
                "primary_choice_route_count": 1,
            },
        ]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "pair_support.parquet"
        support.to_parquet(path, index=False)
        entry = bridge_liquidity_entry_birth_panel(panel, pair_support_path=path)
    assert entry["choice_group_id"].tolist() == ["g1"]


def test_bridge_liquidity_entry_birth_regression_reports_depth_slope() -> None:
    rows = []
    candidates = [(WETH, 0.0), (USDC, 1.0), (DAI, 1.0)]
    for group_index in range(140):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=group_index)
        group_effect = 0.0005 * group_index
        for candidate_index, (candidate, is_stable) in enumerate(candidates):
            log_depth = (
                0.4 * candidate_index
                + math.sin(group_index / 12 + 0.7 * candidate_index)
                + 0.03 * ((group_index * (candidate_index + 2)) % 5)
            )
            if candidate_index == 0 and group_index % 3 == 0:
                log_depth = 0.0
            lag_route_reach = (
                1.4
                + 0.02 * ((group_index * (candidate_index + 3)) % 17)
                + 0.3 * math.sin(group_index / 17 + 0.3 * candidate_index)
            )
            lag_pair_reach = (
                1.0
                + 0.02 * ((group_index + 2 * candidate_index) % 13)
                + 0.2 * math.cos(group_index / 19 + 0.5 * candidate_index)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 35}",
                    "five_route_total": 12.0 + group_index % 4,
                    "route_share_five": (
                        0.060 * log_depth
                        + 0.012 * lag_route_reach
                        + group_effect
                        + 0.010 * is_stable
                    ),
                    "selected_five": float(
                        log_depth + 0.1 * lag_route_reach + 0.1 * is_stable > 0.6
                    ),
                    "is_stable": is_stable,
                    "log_bridge_min_capital": log_depth,
                    "log_global_route_count_lag30": lag_route_reach,
                    "log_global_pair_count_lag30": lag_pair_reach,
                }
            )
    result = bridge_liquidity_entry_birth_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    route_depth = result[
        result["model_id"].eq("entry_route_share_depth_reach_candidate_fe")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    selection_depth = result[
        result["model_id"].eq("entry_selection_depth_reach_candidate_fe")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    assert route_depth["coefficient"] > 0
    assert selection_depth["coefficient"] > 0


def test_bridge_liquidity_bottleneck_penalizes_unbalanced_legs() -> None:
    rows = []
    candidates = [(WETH, 0.0), (USDC, 1.0), (DAI, 1.0)]
    for group_index in range(190):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=group_index)
        group_effect = 0.0006 * group_index
        for candidate_index, (candidate, is_stable) in enumerate(candidates):
            log_min = (
                4.4
                + 0.45 * candidate_index
                + math.sin(group_index / 10 + 0.7 * candidate_index)
                + 0.02 * ((group_index * (candidate_index + 3)) % 7)
            )
            imbalance = (
                0.2
                + 0.08 * ((group_index + 2 * candidate_index) % 9)
                + 0.15 * abs(math.cos(group_index / 15 + candidate_index))
            )
            log_max = log_min + imbalance
            log_geom = 0.5 * (log_min + log_max)
            global_reach = (
                1.8
                + 0.012 * group_index
                + 0.4 * candidate_index
                + math.cos(group_index / 12 + candidate_index)
            )
            lag_route_reach = (
                1.2
                + 0.02 * ((group_index * (candidate_index + 4)) % 17)
                + 0.3 * math.sin(group_index / 18 + 0.4 * candidate_index)
            )
            lag_pair_reach = (
                0.9
                + 0.02 * ((group_index + candidate_index) % 13)
                + 0.2 * math.cos(group_index / 20 + 0.5 * candidate_index)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 47}",
                    "five_route_total": 18.0 + group_index % 5,
                    "route_share_five": (
                        0.060 * log_min
                        - 0.025 * log_max
                        + 0.018 * global_reach
                        + group_effect
                        + 0.008 * is_stable
                    ),
                    "log_bridge_min_capital": log_min,
                    "log_bridge_max_capital": log_max,
                    "log_bridge_geom_capital": log_geom,
                    "log_bridge_imbalance": imbalance,
                    "log_global_route_count_day_leaveout": global_reach,
                    "log_global_route_count_lag30": lag_route_reach,
                    "log_global_pair_count_lag30": lag_pair_reach,
                }
            )
    result = bridge_liquidity_bottleneck_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    weak_leg = result[
        result["model_id"].eq("route_share_min_max_depth_reach_candidate_fe")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    imbalance_penalty = result[
        result["model_id"].eq("route_share_geom_imbalance_reach_candidate_fe")
        & result["regressor"].eq("log_bridge_imbalance")
    ].iloc[0]
    assert weak_leg["coefficient"] > 0
    assert imbalance_penalty["coefficient"] < 0


def test_bridge_liquidity_leave_one_keeps_local_depth_slope() -> None:
    rows = []
    candidates = [
        ("WETH", WETH, 0.0),
        ("USDC", USDC, 1.0),
        ("DAI", DAI, 1.0),
        ("WBTC", WBTC, 0.0),
    ]
    for group_index in range(220):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=group_index)
        group_effect = 0.0005 * group_index
        for candidate_index, (symbol, candidate, is_stable) in enumerate(candidates):
            log_depth = (
                4.2
                + 0.35 * candidate_index
                + math.sin(group_index / 12 + 0.6 * candidate_index)
                + 0.02 * ((group_index * (candidate_index + 4)) % 9)
            )
            global_reach = (
                2.1
                + 0.008 * group_index
                + 0.35 * candidate_index
                + math.cos(group_index / 15 + candidate_index)
            )
            lag_route_reach = (
                1.4
                + 0.025 * ((group_index * (candidate_index + 5)) % 19)
                + 0.35 * math.sin(group_index / 18 + 0.4 * candidate_index)
            )
            lag_pair_reach = (
                1.0
                + 0.02 * ((group_index + 3 * candidate_index) % 11)
                + 0.25 * math.cos(group_index / 20 + 0.5 * candidate_index)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_symbol": symbol,
                    "candidate_address": candidate,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 55}",
                    "five_route_total": 25.0 + group_index % 5,
                    "route_share_five": (
                        0.06 * log_depth
                        + 0.012 * global_reach
                        + 0.008 * lag_route_reach
                        + group_effect
                        + 0.006 * candidate_index
                    ),
                    "is_stable": is_stable,
                    "log_bridge_min_capital": log_depth,
                    "log_global_route_count_day_leaveout": global_reach,
                    "log_global_route_count_lag30": lag_route_reach,
                    "log_global_pair_count_lag30": lag_pair_reach,
                }
            )
    result = bridge_liquidity_leave_one_candidate_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    depth = result[
        result["regressor"].eq("log_bridge_min_capital")
        & result["model_id"].eq("route_share_depth_global_reach_candidate_fe")
    ]
    assert sorted(depth["dropped_candidate_symbol"].unique()) == [
        "DAI",
        "USDC",
        "WBTC",
        "WETH",
    ]
    assert depth["coefficient"].gt(0).all()


def test_bridge_liquidity_stable_issuer_race_reports_2026_premia() -> None:
    rows = []
    candidates = [
        ("DAI", DAI),
        ("USDC", USDC),
        ("USDT", USDT),
    ]
    for group_index in range(220):
        year = 2024 if group_index < 110 else 2026
        day = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(
            days=group_index % 110
        )
        for candidate_index, (symbol, candidate) in enumerate(candidates):
            is_usdc = float(symbol == "USDC")
            is_usdt = float(symbol == "USDT")
            is_2026 = float(year == 2026)
            log_depth = (
                3.8
                + 0.3 * candidate_index
                + math.sin(group_index / 10 + 0.5 * candidate_index)
                + 0.01 * ((group_index * (candidate_index + 2)) % 7)
            )
            global_reach = (
                2.0
                + 0.006 * group_index
                + 0.2 * candidate_index
                + math.cos(group_index / 16 + candidate_index)
            )
            lag_route_reach = (
                1.3
                + 0.02 * ((group_index * (candidate_index + 3)) % 13)
                + 0.25 * math.sin(group_index / 18 + 0.4 * candidate_index)
            )
            lag_pair_reach = (
                0.8
                + 0.02 * ((group_index + candidate_index) % 9)
                + 0.2 * math.cos(group_index / 19 + 0.5 * candidate_index)
            )
            rows.append(
                {
                    "choice_group_id": f"g{group_index}",
                    "candidate_symbol": symbol,
                    "candidate_address": candidate,
                    "year": year,
                    "origin_date": day,
                    "ordered_pair": f"pair{group_index % 50}",
                    "route_count": max(
                        0.1,
                        12
                        + 3.5 * log_depth
                        + 20 * is_usdc * is_2026
                        + 28 * is_usdt * is_2026,
                    ),
                    "log_bridge_min_capital": log_depth,
                    "log_global_route_count_day_leaveout": global_reach,
                    "log_global_route_count_lag30": lag_route_reach,
                    "log_global_pair_count_lag30": lag_pair_reach,
                }
            )
    result = bridge_liquidity_stable_issuer_regressions(
        pd.DataFrame(rows),
        min_observations=100,
        min_clusters=10,
    )
    assert "bridge_liquidity_stable_issuer_support" in set(result["record_type"])
    usdt = result[
        result["model_id"].eq("stable_issuer_2026_depth_reach_fe")
        & result["regressor"].eq("is_usdt_x_2026")
    ].iloc[0]
    depth = result[
        result["model_id"].eq("stable_issuer_2026_depth_reach_fe")
        & result["regressor"].eq("log_bridge_min_capital")
    ].iloc[0]
    assert usdt["coefficient"] > 0
    assert depth["coefficient"] > 0


def test_bridge_liquidity_deck_values_render_guarded_macros() -> None:
    estimates = pd.DataFrame(
        [
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_top_rank_summary",
                "sample": "pooled",
                "candidate_rows": 100,
                "choice_groups": 40,
                "ordered_pairs": 20,
                "days": 10,
                "top_bridge_route_share": 0.84,
                "top_bridge_selected_rate": 0.96,
                "top_bridge_stable_rate": 0.57,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_top_rank_summary",
                "sample": "2024",
                "top_bridge_route_share": 0.75,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_top_rank_summary",
                "sample": "2026",
                "top_bridge_route_share": 0.86,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_depth_regression",
                "model_id": "route_share_log_min_depth",
                "outcome": "route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.066,
                "standard_error": 0.012,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_depth_regression",
                "model_id": "route_share_log_min_depth_stable_interaction",
                "outcome": "route_share_five",
                "regressor": "stable_total_log_bridge_min_capital",
                "coefficient": 0.077,
                "standard_error": 0.015,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_depth_regression",
                "model_id": "selection_log_min_depth",
                "outcome": "selected_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.025,
                "standard_error": 0.012,
                "p_value": 0.04,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_horse_race_regression",
                "model_id": "route_share_depth_global_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.067,
                "standard_error": 0.012,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_horse_race_regression",
                "model_id": "route_share_depth_global_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_global_route_count_day_leaveout",
                "coefficient": 0.09,
                "standard_error": 0.028,
                "p_value": 0.004,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_entry_birth_regression",
                "model_id": "entry_route_share_depth_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.054,
                "standard_error": 0.005,
                "p_value": 0.001,
                "n_observations": 835,
                "choice_groups": 167,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_entry_birth_regression",
                "model_id": "entry_selection_depth_reach_candidate_fe",
                "outcome": "selected_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.053,
                "standard_error": 0.006,
                "p_value": 0.001,
                "n_observations": 835,
                "choice_groups": 167,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_entry_birth_regression",
                "model_id": "entry_route_share_depth_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_global_route_count_lag30",
                "coefficient": 0.094,
                "standard_error": 0.058,
                "p_value": 0.11,
                "n_observations": 835,
                "choice_groups": 167,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_bottleneck_regression",
                "model_id": "route_share_min_max_depth_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.065,
                "standard_error": 0.012,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_bottleneck_regression",
                "model_id": "route_share_min_max_depth_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_bridge_max_capital",
                "coefficient": -0.038,
                "standard_error": 0.022,
                "p_value": 0.08,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_bottleneck_regression",
                "model_id": "route_share_geom_imbalance_reach_candidate_fe",
                "outcome": "route_share_five",
                "regressor": "log_bridge_imbalance",
                "coefficient": -0.054,
                "standard_error": 0.011,
                "p_value": 0.001,
            },
            *[
                {
                    "claim_status": "provisional_exploratory",
                    "record_type": "bridge_liquidity_leave_one_candidate_regression",
                    "model_id": "route_share_depth_global_reach_candidate_fe",
                    "dropped_candidate_symbol": symbol,
                    "outcome": "route_share_five",
                    "regressor": "log_bridge_min_capital",
                    "coefficient": coefficient,
                    "standard_error": 0.013,
                    "p_value": 0.001,
                }
                for symbol, coefficient in [
                    ("WETH", 0.061),
                    ("USDC", 0.058),
                    ("USDT", 0.064),
                    ("DAI", 0.056),
                    ("WBTC", 0.060),
                ]
            ],
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_stable_issuer_support",
                "model_id": "stable_issuer_bridge_race_support",
                "choice_groups": 2000,
                "ordered_pairs": 300,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_stable_issuer_regression",
                "model_id": "stable_issuer_2026_depth_reach_fe",
                "outcome": "route_share_stable_supported",
                "regressor": "is_usdc_x_2026",
                "coefficient": 0.35,
                "standard_error": 0.17,
                "p_value": 0.04,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_stable_issuer_regression",
                "model_id": "stable_issuer_2026_depth_reach_fe",
                "outcome": "route_share_stable_supported",
                "regressor": "is_usdt_x_2026",
                "coefficient": 0.55,
                "standard_error": 0.13,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_stable_issuer_regression",
                "model_id": "stable_issuer_2026_depth_reach_fe",
                "outcome": "route_share_stable_supported",
                "regressor": "log_bridge_min_capital",
                "coefficient": 0.06,
                "standard_error": 0.02,
                "p_value": 0.001,
            },
        ]
    )
    event_rows = [
        {
            "claim_status": "provisional_exploratory",
            "record_type": "bridge_establishment_period_summary",
            "period": period,
            "stable_route_share": stable_share,
            "native_route_share": 1.0 - stable_share,
            "stable_value_share": value_share,
        }
        for period, stable_share, value_share in [
            ("pre_30", 0.0, 0.0),
            ("post_0_29", 0.074, 0.023),
            ("post_30_119", 0.062, 0.023),
        ]
    ]
    model_values = {
        "stable_share_after_bridge_establishment": (0.079, 0.019, 0.0001),
        "stable_value_share_after_bridge_establishment": (0.031, 0.015, 0.04),
        "native_routes_after_bridge_establishment": (-0.20, 0.04, 0.0001),
        "total_routes_after_bridge_establishment": (-0.10, 0.04, 0.02),
        "native_value_after_bridge_establishment": (-0.17, 0.11, 0.13),
        "total_value_after_bridge_establishment": (0.06, 0.10, 0.56),
    }
    for model_id, (coefficient, standard_error, p_value) in model_values.items():
        for regressor, scale in [("post_0_29", 1.0), ("post_30_119", 1.2)]:
            event_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "record_type": "bridge_establishment_event_regression",
                    "model_id": model_id,
                    "regressor": regressor,
                    "coefficient": scale * coefficient,
                    "standard_error": scale * standard_error,
                    "p_value": p_value,
                    "events": 865 if regressor == "post_0_29" else 818,
                }
            )
    for model_id, adoption_share, adoption_events in [
        ("same_day", 0.091, 79),
        ("within_30_days", 0.543, 470),
        ("within_120_days", 0.634, 548),
    ]:
        event_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_establishment_timing_summary",
                "model_id": model_id,
                "events": 865,
                "adoption_events": adoption_events,
                "adoption_share": adoption_share,
            }
        )
    for model_id, shallow_share, competitive_share in [
        ("within_30_days", 0.442, 0.851),
        ("within_120_days", 0.545, 0.907),
    ]:
        for depth_group, events, adoption_share in [
            ("below_0.1x", 638, shallow_share),
            ("at_least_0.1x", 215, competitive_share),
        ]:
            event_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "record_type": "bridge_establishment_timing_depth_summary",
                    "model_id": model_id,
                    "depth_group": depth_group,
                    "events": events,
                    "adoption_share": adoption_share,
                }
            )
    for model_id, coefficient, standard_error in [
        ("adoption_within_30_on_competitive_depth", 0.409, 0.048),
        ("adoption_within_120_on_competitive_depth", 0.362, 0.046),
    ]:
        event_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_establishment_timing_regression",
                "model_id": model_id,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "p_value": 0.001,
                "n_observations": 853,
            }
        )
    for period, stable_share, active_pair_days in [
        ("post_0_29", 0.024, 7752),
        ("post_30_119", 0.024, 11153),
    ]:
        event_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_establishment_depth_summary",
                "period": period,
                "depth_bin": "below_0.1x",
                "stable_route_share": stable_share,
                "active_pair_days": active_pair_days,
            }
        )
    depth_models = [
        (
            "stable_route_share_on_relative_depth",
            "post_0_29",
            0.64,
            0.07,
            0.001,
            11327,
        ),
        (
            "stable_route_share_on_relative_depth",
            "post_30_119",
            0.75,
            0.05,
            0.001,
            17027,
        ),
        (
            "stable_route_share_when_depth_at_least_native",
            "post_0_29",
            0.53,
            0.05,
            0.001,
            671,
        ),
        (
            "stable_route_share_when_depth_at_least_native",
            "post_30_119",
            0.61,
            0.13,
            0.001,
            1211,
        ),
        (
            "stable_route_share_when_depth_at_least_2x_native",
            "post_0_29",
            0.70,
            0.02,
            0.001,
            383,
        ),
        (
            "stable_route_share_when_depth_at_least_2x_native",
            "post_30_119",
            0.71,
            0.09,
            0.001,
            856,
        ),
    ]
    for model_id, period, coefficient, standard_error, p_value, observations in depth_models:
        event_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_establishment_depth_regression",
                "model_id": model_id,
                "period": period,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "p_value": p_value,
                "n_observations": observations,
                "events": 855 if period == "post_0_29" else 737,
            }
        )
    estimates = pd.concat([estimates, pd.DataFrame(event_rows)], ignore_index=True)
    rendered = render_bridge_liquidity_deck_values(estimates)
    table = render_bridge_establishment_table(estimates)
    assert "\\BridgeLiquidityTopShare" in rendered
    assert "\\BridgeLiquidityStableLogTotalCoef" in rendered
    assert "\\BridgeLiquidityHorseRaceDepthCoef" in rendered
    assert "\\BridgeLiquidityEntryBirthDepthCoef" in rendered
    assert "\\BridgeLiquidityEntryBirthRows" in rendered
    assert "\\BridgeLiquidityBottleneckMinCoef" in rendered
    assert "\\BridgeLiquidityImbalanceCoef" in rendered
    assert "\\BridgeLiquidityLeaveOneMinCoef" in rendered
    assert "\\BridgeLiquidityStableIssuerUsdtTwentySixCoef" in rendered
    assert "\\BridgeEstablishmentCountCoef" in rendered
    assert "\\BridgeTimingMonthShare" in rendered
    assert "\\newcommand{\\BridgeTimingComparableEvents}{853}" in rendered
    assert "\\BridgeDepthDoseFirstCoef" in rendered
    assert "\\BridgeDepthEqualFirstShare" in rendered
    assert "\\newcommand{\\BridgeDepthDoseFirstRows}{11{,}327}" in rendered
    assert "\\newcommand{\\BridgeDepthDoseFirstEvents}{855}" in rendered
    assert "Stable route share [pp]" in table
    assert "Bridge events" in table
    assert "Stable-bridge competitiveness relative to WETH" in table
    assert "Stable-route adoption after persistent support" in table
