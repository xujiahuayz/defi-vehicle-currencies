from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_lp_supply_returns import (
    comparison_sample,
    fit_lp_supply_models,
    load_daily_lp_panel,
    prepare_weekly_panel,
    support_records,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def test_load_daily_lp_panel_joins_flow_volume_capital_and_returns(
    tmp_path: Path,
) -> None:
    endpoint = "0x0000000000000000000000000000000000000001"
    flow_path = tmp_path / "flow.parquet"
    capital_path = tmp_path / "capital.parquet"
    price_path = tmp_path / "prices.parquet"
    pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-02"),
                "venue": "uniswap_v2",
                "pool": "0xpool",
                "v2_add_lp_flow_usd": 20.0,
                "v2_remove_lp_flow_usd": 5.0,
                "v2_gross_lp_flow_usd": 25.0,
                "v2_net_add_lp_flow_usd": 15.0,
                "v2_add_liquidity": 4.0,
                "v2_remove_liquidity": 1.0,
                "v2_gross_liquidity": 5.0,
                "v2_net_add_liquidity": 3.0,
                "v2_volume_usd": 1_000.0,
                "v2_fee_opportunity_usd": 3.0,
            }
        ]
    ).to_parquet(flow_path, index=False)
    pd.DataFrame(
        [
            {
                "day": "20250102",
                "venue": "uniswap_v2",
                "pool": "0xpool",
                "token0_address": endpoint,
                "token1_address": USDC,
                "capital_usd": 100_000.0,
                "reserve0": 10.0,
                "reserve1": 40.0,
                "capital_validation_status": "exact_state_current",
            }
        ]
    ).to_parquet(capital_path, index=False)
    pd.DataFrame(
        [
            {"day": "20250101", "token": endpoint, "price_usd": 1.0},
            {"day": "20250102", "token": endpoint, "price_usd": 1.1},
            {"day": "20250101", "token": USDC, "price_usd": 1.0},
            {"day": "20250102", "token": USDC, "price_usd": 1.0},
        ]
    ).to_parquet(price_path, index=False)

    row = load_daily_lp_panel(
        flow_path=flow_path,
        capital_path=capital_path,
        price_path=price_path,
    ).iloc[0]

    assert row["candidate_symbol"] == "USDC"
    assert row["candidate_type"] == "stable"
    assert row["endpoint_address"] == endpoint
    assert row["v2_net_add_lp_flow_usd"] == pytest.approx(15.0)
    assert row["v2_fee_opportunity_usd"] == pytest.approx(3.0)
    assert row["endpoint_log_return"] == pytest.approx(np.log(1.1))


def test_load_daily_lp_panel_prefers_embedded_prior_calendar_capital(
    tmp_path: Path,
) -> None:
    endpoint = "0x0000000000000000000000000000000000000001"
    flow_path = tmp_path / "flow.parquet"
    price_path = tmp_path / "prices.parquet"
    missing_external_capital = tmp_path / "not-needed.parquet"
    pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-02"),
                "venue": "uniswap_v2",
                "pool": "0xpool",
                "token0_address": endpoint,
                "token1_address": USDC,
                "v2_lagged_capital_usd": 90_000.0,
                "v2_lagged_sqrt_k": 18.0,
                "v2_exact_lag_valid": True,
                "v2_add_lp_flow_usd": 20.0,
                "v2_remove_lp_flow_usd": 5.0,
                "v2_gross_lp_flow_usd": 25.0,
                "v2_net_add_lp_flow_usd": 15.0,
                "v2_add_liquidity": 4.0,
                "v2_remove_liquidity": 1.0,
                "v2_gross_liquidity": 5.0,
                "v2_net_add_liquidity": 3.0,
                "v2_volume_usd": 1_000.0,
                "v2_fee_opportunity_usd": 3.0,
            }
        ]
    ).to_parquet(flow_path, index=False)
    pd.DataFrame(
        [
            {"day": "20250101", "token": endpoint, "price_usd": 1.0},
            {"day": "20250102", "token": endpoint, "price_usd": 1.1},
            {"day": "20250101", "token": USDC, "price_usd": 1.0},
            {"day": "20250102", "token": USDC, "price_usd": 1.0},
        ]
    ).to_parquet(price_path, index=False)

    row = load_daily_lp_panel(
        flow_path=flow_path,
        capital_path=missing_external_capital,
        price_path=price_path,
    ).iloc[0]

    assert row["capital_usd"] == pytest.approx(90_000.0)
    assert row["sqrt_k"] == pytest.approx(18.0)
    assert row["v2_net_add_lp_flow_usd"] == pytest.approx(15.0)


def _daily_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, day in enumerate(pd.date_range("2025-01-06", periods=42, freq="D")):
        week = index // 7
        add = 2.0 if week == 4 else 0.0
        remove = 1.0 if week == 4 else 0.0
        endpoint_return = 0.02 if index % 2 else -0.01
        rows.append(
            {
                "origin_date": day,
                "venue": "uniswap_v2",
                "pool": "0xpool",
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
                "candidate_type": "stable",
                "endpoint_address": "0xendpoint",
                "capital_usd": 1_000.0,
                "sqrt_k": 500.0,
                "v2_add_lp_flow_usd": add,
                "v2_remove_lp_flow_usd": remove,
                "v2_gross_lp_flow_usd": add + remove,
                "v2_net_add_lp_flow_usd": add - remove,
                "v2_add_liquidity": add / 2.0,
                "v2_remove_liquidity": remove / 2.0,
                "v2_gross_liquidity": (add + remove) / 2.0,
                "v2_net_add_liquidity": (add - remove) / 2.0,
                "v2_fee_opportunity_usd": 10.0,
                "endpoint_log_return": endpoint_return,
                "candidate_log_return": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_weekly_panel_uses_prior_four_weeks_and_next_week_flow() -> None:
    panel = prepare_weekly_panel(_daily_rows())

    row = panel.loc[panel["origin_week"].eq(pd.Timestamp("2025-01-27"))].iloc[0]
    assert row["trailing_return_days"] == 28
    assert row["trailing_fee_opportunity_usd"] == pytest.approx(280.0)
    assert row["trailing_fee_yield_bps"] == pytest.approx(2_800.0)
    assert row["next_add_flow_usd"] == pytest.approx(14.0)
    assert row["next_remove_flow_usd"] == pytest.approx(7.0)
    assert row["next_net_flow_ratio"] == pytest.approx(0.007)
    assert row["next_asinh_net_flow_ratio"] == pytest.approx(np.arcsinh(0.007))
    assert row["consecutive_trailing_weeks"]
    assert row["consecutive_next_week"]


def _model_panel() -> pd.DataFrame:
    rng = np.random.default_rng(1948)
    rows: list[dict[str, object]] = []
    weeks = pd.date_range("2022-01-03", periods=40, freq="7D")
    for endpoint_index in range(35):
        endpoint = f"endpoint_{endpoint_index}"
        for stable, candidate in ((0.0, "WETH"), (1.0, "USDC")):
            pool = f"pool_{endpoint_index}_{candidate}"
            pool_effect = rng.normal(0.0, 0.03)
            age_offset = 1 + endpoint_index % 9 + int(stable) * 2
            for week_index, week in enumerate(weeks):
                fee = 0.5 + 0.03 * (endpoint_index % 5) + rng.normal(0, 0.08)
                divergence = 0.7 + 0.05 * (week_index % 6) + rng.normal(0, 0.07)
                volatility = 1.2 + 0.7 * divergence + rng.normal(0, 0.06)
                log_capital = np.log(160_000.0 + 2_000 * endpoint_index) + rng.normal(
                    0, 0.03
                )
                log_age = np.log1p(week_index + age_offset)
                stable_fee = stable * fee
                stable_divergence = stable * divergence
                stable_volatility = stable * volatility
                trailing_add = (
                    0.02
                    + 0.004 * ((endpoint_index + week_index) % 5)
                    + stable * 0.002 * ((week_index + 1) % 3)
                    + rng.normal(0, 0.001)
                )
                trailing_remove = (
                    0.015
                    + 0.003 * ((2 * endpoint_index + week_index) % 5)
                    + stable * 0.0015 * ((week_index + 2) % 4)
                    + rng.normal(0, 0.001)
                )
                endpoint_week_effect = 0.02 * np.sin((endpoint_index + week_index) / 5)
                net = (
                    0.45 * fee
                    - 0.80 * divergence
                    + 0.20 * stable_fee
                    - 0.35 * stable_divergence
                    + 0.04 * log_capital
                    + 0.02 * log_age
                    + pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                additions = (
                    0.35 * fee
                    - 0.45 * divergence
                    + 0.12 * stable_fee
                    - 0.20 * stable_divergence
                    + pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                removals = (
                    -0.20 * fee
                    + 0.40 * divergence
                    - 0.08 * stable_fee
                    + 0.18 * stable_divergence
                    - pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                rows.append(
                    {
                        "origin_week": week,
                        "venue": "uniswap_v2",
                        "pool": pool,
                        "pool_id": f"uniswap_v2|{pool}",
                        "endpoint_address": endpoint,
                        "endpoint_week_id": f"{endpoint}|{week:%Y%m%d}",
                        "candidate_type": "stable" if stable else "native",
                        "stable_indicator": stable,
                        "capital_usd": float(np.exp(log_capital)),
                        "log_capital_usd": log_capital,
                        "pool_age_weeks": week_index + age_offset,
                        "log1p_pool_age_weeks": log_age,
                        "trailing_fee_yield_bps": 10.0 * fee,
                        "fee_yield_per_10bps": fee,
                        "trailing_divergence_loss_bps": divergence,
                        "trailing_relative_volatility": 0.10 * volatility,
                        "trailing_relative_volatility_per_10pp": volatility,
                        "stable_x_fee_yield": stable_fee,
                        "stable_x_divergence_loss": stable_divergence,
                        "stable_x_relative_volatility": stable_volatility,
                        "trailing_add_flow_ratio": trailing_add,
                        "trailing_remove_flow_ratio": trailing_remove,
                        "trailing_log1p_add_flow_ratio": np.log1p(trailing_add),
                        "trailing_log1p_remove_flow_ratio": np.log1p(
                            trailing_remove
                        ),
                        "next_asinh_net_flow_ratio": net,
                        "next_asinh_net_liquidity_ratio": net + rng.normal(0, 0.015),
                        "next_log1p_add_flow_ratio": additions,
                        "next_log1p_remove_flow_ratio": removals,
                        "next_net_flow_ratio": float(np.sinh(net)),
                        "next_net_liquidity_ratio": float(np.sinh(net)),
                    }
                )
    return pd.DataFrame(rows)


def test_lp_supply_models_recover_fee_and_risk_response() -> None:
    result = fit_lp_supply_models(
        _model_panel(),
        min_observations=100,
        min_pool_clusters=20,
        min_week_clusters=20,
    )
    main = result[result["model_id"].eq("m1_next_week_net_supply")]
    fee = main.loc[main["predictor"].eq("fee_yield_per_10bps")].iloc[0]
    risk = main.loc[
        main["predictor"].eq("trailing_divergence_loss_bps")
    ].iloc[0]

    assert fee["coefficient"] > 0.25
    assert risk["coefficient"] < -0.50
    assert np.isfinite(fee["standard_error"])
    assert fee["fixed_effects"] == "endpoint_x_week+pool"
    assert set(result["capital_threshold_usd"]) == {10_000.0, 50_000.0, 100_000.0}


def test_comparison_and_support_require_both_vehicle_families() -> None:
    panel = _model_panel()
    first_cell = panel["endpoint_week_id"].iloc[0]
    incomplete = panel[
        ~(
            panel["endpoint_week_id"].eq(first_cell)
            & panel["candidate_type"].eq("stable")
        )
    ]
    sample = comparison_sample(incomplete, 50_000.0)
    assert first_cell not in set(sample["endpoint_week_id"])

    support = support_records(panel)
    main = support[support["capital_threshold_usd"].eq(50_000.0)].iloc[0]
    assert main["endpoints"] == 35
    assert main["route_variables"] == "none"
