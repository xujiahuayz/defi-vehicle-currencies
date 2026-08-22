from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.analyze.run_lp_stable_demand_stress import (
    FOCAL_DECLINE,
    FOCAL_VOLATILITY,
    VENUE_DESIGNS,
    build_weekly_eth_stress,
    fit_stress_models,
    prepare_venue_sample,
)


class StableDemandStressTest(unittest.TestCase):
    def test_weekly_stress_uses_complete_consecutive_returns(self) -> None:
        dates = pd.date_range("2024-01-07", periods=15, freq="D")
        prices = pd.DataFrame(
            {
                "origin_date": dates,
                "price_usd": 2_000.0 * np.exp(np.arange(len(dates)) * 0.01),
            }
        )
        result = build_weekly_eth_stress(prices)
        self.assertEqual(result["origin_week"].tolist(), [pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-15")])
        self.assertTrue(result["eth_return_days"].eq(7).all())
        self.assertTrue(np.allclose(result["eth_return"], 0.07))
        self.assertTrue(result["eth_realized_volatility"].gt(0).all())

    def test_prepare_venue_sample_requires_both_vehicle_families(self) -> None:
        stress = pd.DataFrame(
            {
                "origin_week": [pd.Timestamp("2024-01-08")],
                "eth_return_days": [7],
                "eth_realized_volatility": [0.5],
                "eth_realized_volatility_per_10pp": [5.0],
                "eth_return": [-0.1],
                "eth_return_per_10pp": [-1.0],
            }
        )
        rows = []
        for endpoint, families in (("0xaaa", ("native", "stable")), ("0xbbb", ("stable",))):
            for index, family in enumerate(families):
                rows.append(
                    {
                        "origin_week": pd.Timestamp("2024-01-08"),
                        "candidate_type": family,
                        "endpoint_address": endpoint,
                        "pool_id": f"pool-{endpoint}-{index}",
                        "endpoint_week_id": f"{endpoint}|20240108",
                        "capital_usd": 100_000.0,
                        "pool_age_weeks": 10.0,
                        "fee_yield_per_10bps": 1.0,
                        "trailing_relative_volatility_per_10pp": 2.0,
                        "trailing_log1p_add_flow_ratio": 0.1,
                        "trailing_log1p_remove_flow_ratio": 0.1,
                        "next_log1p_add_flow_ratio": 0.2,
                        "next_log1p_remove_flow_ratio": 0.1,
                        "next_asinh_net_flow_ratio": 0.0,
                        "next_asinh_net_liquidity_ratio": 0.0,
                    }
                )
        result = prepare_venue_sample(pd.DataFrame(rows), stress, VENUE_DESIGNS[0])
        self.assertEqual(set(result["endpoint_address"]), {"0xaaa"})
        self.assertEqual(set(result["candidate_type"]), {"native", "stable"})
        self.assertEqual(len(result), 2)

    @staticmethod
    def _synthetic_venue(venue: str, seed: int) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        weeks = pd.date_range("2023-01-02", periods=32, freq="7D")
        volatility = 4.0 + np.sin(np.arange(len(weeks)) / 3.0)
        returns = 0.8 * np.cos(np.arange(len(weeks)) / 4.0)
        rows = []
        for endpoint_index in range(16):
            endpoint = f"0x{endpoint_index:040x}"
            for stable in (0.0, 1.0):
                pool = f"{venue}|{endpoint_index}|{int(stable)}"
                pool_effect = rng.normal(0, 0.05)
                for week_index, week in enumerate(weeks):
                    fee = rng.normal(1.0, 0.15)
                    pair_risk = rng.normal(2.0 + stable * 0.2, 0.2)
                    earlier_add = rng.normal(0.15, 0.02)
                    earlier_remove = rng.normal(0.12, 0.02)
                    noise_add = rng.normal(0, 0.03)
                    noise_net = rng.normal(0, 0.03)
                    stable_volatility = stable * volatility[week_index]
                    stable_return = stable * returns[week_index]
                    capital = 100_000.0 * np.exp(
                        0.01 * week_index * stable + rng.normal(0, 0.01)
                    )
                    age = week_index + 1.0 + stable * (week_index % 3) / 4.0
                    rows.append(
                        {
                            "origin_week": week,
                            "candidate_type": "stable" if stable else "native",
                            "stable_indicator": stable,
                            "endpoint_address": endpoint,
                            "pool_id": pool,
                            "endpoint_week_id": f"{endpoint}|{week:%Y%m%d}",
                            "pool_capital_usd": capital,
                            "pool_age_weeks": age,
                            "log_pool_capital_usd": np.log(capital),
                            "log1p_pool_age_weeks": np.log1p(age),
                            "fee_yield_per_10bps": fee,
                            "trailing_relative_volatility_per_10pp": pair_risk,
                            "trailing_log1p_add_flow_ratio": earlier_add,
                            "trailing_log1p_remove_flow_ratio": earlier_remove,
                            "eth_realized_volatility_per_10pp": volatility[week_index],
                            "eth_return_per_10pp": returns[week_index],
                            "next_log1p_add_flow_ratio": (
                                1.0
                                + pool_effect
                                + 0.10 * stable_volatility
                                - 0.18 * stable_return
                                + noise_add
                            ),
                            "next_log1p_remove_flow_ratio": (
                                0.8
                                + pool_effect
                                + 0.03 * stable_volatility
                                - 0.08 * stable_return
                                + rng.normal(0, 0.03)
                            ),
                            "next_asinh_net_flow_ratio": (
                                pool_effect
                                + 0.06 * stable_volatility
                                - 0.12 * stable_return
                                + noise_net
                            ),
                            "next_asinh_net_liquidity_ratio": (
                                pool_effect
                                + 0.05 * stable_volatility
                                - 0.10 * stable_return
                                + rng.normal(0, 0.03)
                            ),
                        }
                    )
        return pd.DataFrame(rows)

    def test_model_family_reports_decline_sign_and_holm_adjustment(self) -> None:
        models = fit_stress_models(
            {
                "uniswap_v2": self._synthetic_venue("uniswap_v2", 1),
                "uniswap_v3": self._synthetic_venue("uniswap_v3", 2),
            },
            min_observations=100,
            min_pool_clusters=10,
            min_week_clusters=10,
        )
        focal = models[models["focal_family_member"]]
        self.assertEqual(
            set(focal["predictor"]), {FOCAL_VOLATILITY, FOCAL_DECLINE}
        )
        self.assertEqual(
            focal.groupby("multiplicity_family").size().to_dict(),
            {
                "primary_additions": 4,
                "secondary_withdrawals": 4,
                "secondary_net_supply": 4,
                "secondary_v2_quantity_net_supply": 2,
            },
        )
        self.assertTrue(focal["holm_p_value"].notna().all())
        additions = focal[focal["outcome_name"].eq("additions")]
        self.assertTrue(additions["coefficient"].gt(0).all())


if __name__ == "__main__":
    unittest.main()
