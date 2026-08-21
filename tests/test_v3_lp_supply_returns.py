from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_v3_lp_supply_returns import (
    comparison_sample,
    fit_v3_lp_supply_models,
    load_weekly_v3_lp_panel,
    prepare_weekly_panel,
    support_records,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def test_weekly_loader_balances_quiet_weeks_and_uses_full_price_calendar(
    tmp_path: Path,
) -> None:
    endpoint = "0x0000000000000000000000000000000000000001"
    flow_path = tmp_path / "flow.parquet"
    fee_path = tmp_path / "fee.parquet"
    price_path = tmp_path / "price.parquet"
    pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-06"),
                "pool": "0xpool",
                "candidate_address": USDC,
                "v3_add_only_lp_flow_usd_screened": 20.0,
                "v3_remove_only_lp_flow_usd_screened": 5.0,
                "v3_net_add_remove_only_lp_flow_usd_screened": 15.0,
                "v3_add_action_events": 2,
                "v3_remove_action_events": 1,
                "v3_add_only_action_transactions": 1,
                "v3_remove_only_action_transactions": 1,
                "v3_reposition_action_transactions": 1,
            }
        ]
    ).to_parquet(flow_path, index=False)
    pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp("2025-01-06"),
                "pool": "0xpool",
                "token0_address": endpoint,
                "token1_address": USDC,
                "gross_fees_usd": 3.0,
                "fees_usd": 3.0,
                "volume_usd": 1_000.0,
                "tvl_usd": 100_000.0,
            },
            {
                "origin_date": pd.Timestamp("2025-01-20"),
                "pool": "0xpool",
                "token0_address": endpoint,
                "token1_address": USDC,
                "gross_fees_usd": 6.0,
                "fees_usd": 6.0,
                "volume_usd": 2_000.0,
                "tvl_usd": 120_000.0,
            },
            {
                "origin_date": pd.Timestamp("2025-01-20"),
                "pool": "0xstable-native-core",
                "token0_address": WETH,
                "token1_address": USDC,
                "gross_fees_usd": 9.0,
                "fees_usd": 9.0,
                "volume_usd": 3_000.0,
                "tvl_usd": 150_000.0,
            },
        ]
    ).to_parquet(fee_path, index=False)
    prices = []
    for index, day in enumerate(pd.date_range("2025-01-01", "2025-01-26")):
        prices.extend(
            [
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": endpoint,
                    "price_usd": 1.01**index,
                },
                {"day": day.strftime("%Y%m%d"), "token": USDC, "price_usd": 1.0},
            ]
        )
    pd.DataFrame(prices).to_parquet(price_path, index=False)

    panel = load_weekly_v3_lp_panel(
        flow_path=flow_path,
        fee_path=fee_path,
        price_path=price_path,
    )

    assert list(panel["origin_week"]) == list(
        pd.to_datetime(["2025-01-06", "2025-01-13", "2025-01-20"])
    )
    assert set(panel["pool"]) == {"0xpool"}
    quiet = panel.loc[panel["origin_week"].eq(pd.Timestamp("2025-01-13"))].iloc[0]
    assert quiet["gross_fees_usd"] == 0.0
    assert quiet["net_add_flow_usd"] == 0.0
    assert quiet["pool_update_days"] == 0
    assert quiet["tvl_usd"] == pytest.approx(100_000.0)
    assert quiet["last_tvl_update_week"] == pd.Timestamp("2025-01-06")
    assert quiet["return_days"] == 7


def _weekly_base() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    first_week = pd.Timestamp("2025-01-06")
    for week in range(6):
        origin_week = first_week + pd.Timedelta(days=7 * week)
        add = 14.0 if week == 4 else 0.0
        remove = 7.0 if week == 4 else 0.0
        rows.append(
            {
                "origin_week": origin_week,
                "venue": "uniswap_v3",
                "pool": "0xpool",
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
                "candidate_type": "stable",
                "endpoint_address": "0xendpoint",
                "first_week": first_week,
                "last_tvl_update_week": (
                    origin_week if week < 4 else first_week + pd.Timedelta(days=21)
                ),
                "tvl_usd": 1_000.0,
                "gross_fees_usd": 70.0,
                "volume_usd": 1_000.0,
                "pool_update_days": 0 if week in {4, 5} else 7,
                "add_flow_usd": add,
                "remove_flow_usd": remove,
                "net_add_flow_usd": add - remove,
                "add_actions": 7 if add else 0,
                "remove_actions": 7 if remove else 0,
                "add_only_transactions": 7 if add else 0,
                "remove_only_transactions": 7 if remove else 0,
                "same_tx_reposition_transactions": 0,
                "relative_return_sq_sum": 7 * 0.01**2,
                "cp_divergence_proxy_bps_sum": 7 * 0.125,
                "return_days": 7,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_weekly_panel_keeps_quiet_next_week_and_strict_timing() -> None:
    panel = prepare_weekly_panel(_weekly_base())

    row = panel.loc[panel["origin_week"].eq(pd.Timestamp("2025-01-27"))].iloc[0]
    assert row["trailing_return_days"] == 28
    assert row["trailing_gross_fees_usd"] == pytest.approx(280.0)
    assert row["trailing_fee_yield_bps"] == pytest.approx(2_800.0)
    assert row["next_add_flow_usd"] == pytest.approx(14.0)
    assert row["next_remove_flow_usd"] == pytest.approx(7.0)
    assert row["next_net_flow_ratio"] == pytest.approx(0.007)
    assert row["next_asinh_net_add_remove_only_flow_kusd"] == pytest.approx(
        np.arcsinh(0.007)
    )
    assert row["next_log1p_add_only_transactions"] == pytest.approx(np.log1p(7.0))
    quiet_outcome = panel.loc[
        panel["origin_week"].eq(pd.Timestamp("2025-02-03"))
    ].iloc[0]
    assert quiet_outcome["next_net_add_flow_usd"] == 0.0


def _model_panel() -> pd.DataFrame:
    rng = np.random.default_rng(1969)
    rows: list[dict[str, object]] = []
    weeks = pd.date_range("2025-01-06", periods=32, freq="7D")
    for endpoint_index in range(35):
        endpoint = f"endpoint_{endpoint_index}"
        for stable, candidate in ((0.0, "WETH"), (1.0, "USDC")):
            pool = f"pool_{endpoint_index}_{candidate}"
            pool_effect = rng.normal(0.0, 0.03)
            for week_index, week in enumerate(weeks):
                fee = 0.6 + 0.04 * (endpoint_index % 5) + rng.normal(0, 0.08)
                risk = 0.8 + 0.06 * (week_index % 6) + rng.normal(0, 0.07)
                volatility = 1.1 + 0.7 * risk + rng.normal(0, 0.06)
                log_tvl = np.log(160_000.0 + 2_000 * endpoint_index) + rng.normal(
                    0, 0.03
                )
                log_age = np.log1p(week_index + 1 + int(stable))
                trailing_add = 0.02 + rng.normal(0, 0.002)
                trailing_remove = 0.015 + rng.normal(0, 0.002)
                endpoint_week_effect = 0.02 * np.sin((endpoint_index + week_index) / 5)
                net = (
                    0.45 * fee
                    - 0.75 * risk
                    + 0.20 * stable * fee
                    - 0.30 * stable * risk
                    + pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                additions = (
                    0.35 * fee
                    - 0.40 * risk
                    + 0.15 * stable * fee
                    - 0.15 * stable * risk
                    + pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                removals = (
                    -0.20 * fee
                    + 0.35 * risk
                    - 0.08 * stable * fee
                    + 0.15 * stable * risk
                    - pool_effect
                    + endpoint_week_effect
                    + rng.normal(0, 0.025)
                )
                rows.append(
                    {
                        "origin_week": week,
                        "pool": pool,
                        "pool_id": f"uniswap_v3|{pool}",
                        "endpoint_address": endpoint,
                        "endpoint_week_id": f"{endpoint}|{week:%Y%m%d}",
                        "candidate_type": "stable" if stable else "native",
                        "stable_indicator": stable,
                        "tvl_usd": float(np.exp(log_tvl)),
                        "tvl_staleness_weeks": 0.0,
                        "log_tvl_usd": log_tvl,
                        "log1p_observed_pool_age_weeks": log_age,
                        "trailing_fee_yield_bps": 10.0 * fee,
                        "fee_yield_per_10bps": fee,
                        "trailing_cp_divergence_proxy_bps": risk,
                        "trailing_relative_volatility": 0.10 * volatility,
                        "trailing_relative_volatility_per_10pp": volatility,
                        "stable_x_fee_yield": stable * fee,
                        "stable_x_cp_divergence_proxy": stable * risk,
                        "stable_x_relative_volatility": stable * volatility,
                        "trailing_add_flow_ratio": trailing_add,
                        "trailing_remove_flow_ratio": trailing_remove,
                        "trailing_log1p_add_flow_ratio": np.log1p(trailing_add),
                        "trailing_log1p_remove_flow_ratio": np.log1p(trailing_remove),
                        "next_asinh_net_add_remove_only_flow_kusd": net,
                        "next_asinh_net_flow_ratio": net + rng.normal(0, 0.01),
                        "next_log1p_add_only_flow_kusd": additions,
                        "next_log1p_remove_only_flow_kusd": removals,
                        "next_log1p_add_only_transactions": additions
                        + rng.normal(0, 0.02),
                        "next_log1p_remove_only_transactions": removals
                        + rng.normal(0, 0.02),
                        "next_net_flow_ratio": float(np.sinh(net)),
                    }
                )
    return pd.DataFrame(rows)


def test_models_recover_fee_and_risk_supply_response() -> None:
    result = fit_v3_lp_supply_models(
        _model_panel(),
        min_observations=100,
        min_pool_clusters=20,
        min_week_clusters=20,
    )
    main = result[
        result["model_id"].eq("m1_next_week_net_add_remove_only_flow")
    ]
    fee = main.loc[main["predictor"].eq("fee_yield_per_10bps")].iloc[0]
    risk = main.loc[
        main["predictor"].eq("trailing_cp_divergence_proxy_bps")
    ].iloc[0]

    assert fee["coefficient"] > 0.25
    assert risk["coefficient"] < -0.50
    assert np.isfinite(fee["standard_error"])
    assert fee["fixed_effects"] == "endpoint_x_week+pool"
    assert set(result["tvl_threshold_usd"]) == {10_000.0, 50_000.0, 100_000.0}


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
    main = support[support["tvl_threshold_usd"].eq(50_000.0)].iloc[0]
    assert main["endpoints"] == 35
    assert main["trade_allocation_variables"] == "none"
