from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_lp_network_reach import (
    attach_leave_focal_reach,
    fit_reach_models,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ENDPOINT_X = "0x1111111111111111111111111111111111111111"
ENDPOINT_Y = "0x2222222222222222222222222222222222222222"
ENDPOINT_Z = "0x3333333333333333333333333333333333333333"


def _frontier() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    executable = {
        "20260115": {ENDPOINT_X, ENDPOINT_Y},
        "20260215": {ENDPOINT_Y, ENDPOINT_Z},
    }
    for day, reached in executable.items():
        for endpoint in (ENDPOINT_X, ENDPOINT_Y, ENDPOINT_Z):
            active = endpoint in reached
            rows.append(
                {
                    "day": day,
                    "candidate_address": WETH,
                    "endpoint_address": endpoint,
                    "endpoint_scope": "noncandidate_spoke",
                    "notional_usd": 10_000.0,
                    "executable": active,
                    "all_in_cost_bps": 12.0 if active else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _lp_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "venue_family": "uniswap_v2",
                "origin_week": pd.Timestamp("2026-02-02"),
                "pool_id": "uniswap_v2|pool-x",
                "endpoint_week_id": "x|20260202",
                "candidate_address": WETH,
                "endpoint_address": ENDPOINT_X,
                "next_add_flow_usd": 20.0,
                "next_remove_flow_usd": 5.0,
                "next_net_add_flow_usd": 15.0,
                "next_log1p_add_flow_ratio": 0.2,
                "next_asinh_net_flow_ratio": 0.1,
            },
            {
                "venue_family": "uniswap_v2",
                "origin_week": pd.Timestamp("2026-03-02"),
                "pool_id": "uniswap_v2|pool-x",
                "endpoint_week_id": "x|20260302",
                "candidate_address": WETH,
                "endpoint_address": ENDPOINT_X,
                "next_add_flow_usd": 30.0,
                "next_remove_flow_usd": 10.0,
                "next_net_add_flow_usd": 20.0,
                "next_log1p_add_flow_ratio": 0.3,
                "next_asinh_net_flow_ratio": 0.2,
            },
        ]
    )


def test_reach_is_strictly_lagged_and_removes_the_whole_focal_relation() -> None:
    panel = attach_leave_focal_reach(_frontier(), _lp_rows())
    first = panel.loc[panel["origin_week"].eq(pd.Timestamp("2026-02-02"))].iloc[0]
    second = panel.loc[panel["origin_week"].eq(pd.Timestamp("2026-03-02"))].iloc[0]

    assert first["reach_day"] == pd.Timestamp("2026-01-15")
    assert first["external_priced_endpoints"] == 2
    assert first["external_executable_endpoints"] == 1
    assert first["external_coverage_share"] == 0.5
    assert second["reach_day"] == pd.Timestamp("2026-02-15")
    assert second["external_executable_endpoints"] == 2
    assert second["external_coverage_share"] == 1.0
    assert (panel["reach_day"] < panel["origin_week"]).all()


def test_reach_model_uses_later_provider_flows_with_pool_and_endpoint_week_fes() -> None:
    rng = np.random.default_rng(20260822)
    rows: list[dict[str, object]] = []
    weeks = pd.date_range("2025-01-06", periods=12, freq="7D")
    for endpoint_index in range(6):
        endpoint = f"endpoint-{endpoint_index}"
        for candidate_index, candidate in enumerate(("weth", "usdc")):
            pool = f"pool-{endpoint_index}-{candidate}"
            pool_effect = rng.normal(0, 0.02)
            for week_index, week in enumerate(weeks):
                reach = (
                    2.0
                    + 0.5 * candidate_index
                    + 0.08 * week_index
                    + 0.04 * candidate_index * week_index
                )
                fee = rng.normal(0.6, 0.08)
                risk = rng.normal(0.8, 0.08)
                lag_add = rng.normal(0.03, 0.004)
                lag_remove = rng.normal(0.02, 0.004)
                stock = rng.normal(12.0, 0.08)
                age = np.log1p(week_index + 2 + candidate_index)
                common = 0.03 * np.sin((endpoint_index + week_index) / 4)
                net = (
                    0.25 * reach
                    + 0.15 * fee
                    - 0.10 * risk
                    + pool_effect
                    + common
                    + rng.normal(0, 0.02)
                )
                additions = (
                    0.18 * reach
                    + 0.12 * fee
                    - 0.06 * risk
                    + pool_effect
                    + common
                    + rng.normal(0, 0.02)
                )
                rows.append(
                    {
                        "venue_family": "uniswap_v2",
                        "notional_usd": 10_000.0,
                        "origin_week": week,
                        "pool_id": pool,
                        "endpoint_week_id": f"{endpoint}|{week:%Y%m%d}",
                        "reach_age_days": 12,
                        "log1p_external_executable_endpoints": reach,
                        "log1p_external_priced_endpoints": 5.0,
                        "fee_yield_per_10bps": fee,
                        "prior_price_risk_bps": risk,
                        "trailing_log1p_add_flow_ratio": lag_add,
                        "trailing_log1p_remove_flow_ratio": lag_remove,
                        "log_prior_pool_capital": stock,
                        "log1p_pool_age": age,
                        "next_asinh_net_supply_kusd": net,
                        "next_log1p_capital_additions_kusd": additions,
                    }
                )
    result = fit_reach_models(
        pd.DataFrame(rows),
        min_observations=40,
        min_pool_clusters=6,
        min_week_clusters=8,
    )

    primary = result[
        result["predictor"].eq("log1p_external_executable_endpoints")
    ]
    assert set(primary["outcome"]) == {
        "next_asinh_net_supply_kusd",
        "next_log1p_capital_additions_kusd",
    }
    assert primary["coefficient"].gt(0).all()
    assert primary["p_value_holm_reach_family"].notna().all()
    assert result["route_variables"].eq("none").all()
