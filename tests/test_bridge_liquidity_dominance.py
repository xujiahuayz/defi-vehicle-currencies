from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pandas as pd

from scripts.analyze.run_bridge_liquidity_dominance import (
    bridge_liquidity_depth_regressions,
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
        ]
    )
    rendered = render_bridge_liquidity_deck_values(estimates)
    assert "\\BridgeLiquidityTopShare" in rendered
    assert "\\BridgeLiquidityStableLogTotalCoef" in rendered
