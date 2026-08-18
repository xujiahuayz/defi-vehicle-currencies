from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pandas as pd

from scripts.analyze.run_bridge_liquidity_dominance import (
    bridge_liquidity_depth_regressions,
    bridge_liquidity_horse_race_regressions,
    bridge_liquidity_leave_one_candidate_regressions,
    bridge_liquidity_stable_issuer_regressions,
    bridge_liquidity_top_rank_summaries,
    load_bridge_liquidity_panel,
)
from scripts.tabulate.build_bridge_liquidity_deck_values import (
    render_bridge_liquidity_deck_values,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


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
                "capital_usd": 100.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": WETH,
                "token1_address": "tgt",
                "pool": "weth-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 25.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": "src",
                "token1_address": USDC,
                "pool": "src-usdc",
                "venue": "uniswap_v2",
                "capital_usd": 9.0,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            },
            {
                "day": 20240102,
                "token0_address": USDC,
                "token1_address": "tgt",
                "pool": "usdc-tgt",
                "venue": "uniswap_v2",
                "capital_usd": 16.0,
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
    rendered = render_bridge_liquidity_deck_values(estimates)
    assert "\\BridgeLiquidityTopShare" in rendered
    assert "\\BridgeLiquidityStableLogTotalCoef" in rendered
    assert "\\BridgeLiquidityHorseRaceDepthCoef" in rendered
    assert "\\BridgeLiquidityLeaveOneMinCoef" in rendered
    assert "\\BridgeLiquidityStableIssuerUsdtTwentySixCoef" in rendered
