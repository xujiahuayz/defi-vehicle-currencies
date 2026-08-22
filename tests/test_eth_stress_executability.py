from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.analyze.run_eth_stress_executability import (
    build_trailing_eth_state,
    fit_chain_models,
    prepare_executability_panel,
)


class EthStressExecutabilityTest(unittest.TestCase):
    def test_eth_state_uses_only_prices_strictly_before_date(self) -> None:
        dates = pd.date_range("2024-01-01", periods=45, freq="D")
        prices = pd.DataFrame(
            {
                "origin_date": dates,
                "price_usd": 2_000.0 * np.exp(0.01 * np.arange(len(dates))),
            }
        )
        baseline = build_trailing_eth_state(prices, window_days=30)
        target = baseline.iloc[0]
        self.assertEqual(target["date"], pd.Timestamp("2024-02-01"))
        self.assertAlmostEqual(float(target["trailing_eth_return"]), 0.30)

        changed = prices.copy()
        changed.loc[changed["origin_date"].eq(target["date"]), "price_usd"] *= 10
        repeated = build_trailing_eth_state(changed, window_days=30)
        repeated_target = repeated.loc[repeated["date"].eq(target["date"])].iloc[0]
        self.assertAlmostEqual(
            float(repeated_target["trailing_eth_return"]),
            float(target["trailing_eth_return"]),
        )

    def test_common_panel_keeps_positive_capital_and_exact_identity(self) -> None:
        date = pd.Timestamp("2024-02-15")
        frontier = pd.DataFrame(
            [
                {
                    "day": "20240215",
                    "date": date,
                    "route_id": "keep",
                    "token_in": "0xa",
                    "token_out": "0xb",
                    "stable_public_vehicle": "0xs",
                    "native_public_vehicle": "0xn",
                    "symmetric_common_support": True,
                    "chosen_stable": True,
                    "stable_output_advantage_100bp": 0.4,
                    "log_input_usd": np.log(1_000.0),
                    "input_usd": 1_000.0,
                    "ordered_pair": "0xa>0xb",
                },
                {
                    "day": "20240215",
                    "date": date,
                    "route_id": "drop-zero",
                    "token_in": "0xc",
                    "token_out": "0xd",
                    "stable_public_vehicle": "0xs",
                    "native_public_vehicle": "0xn",
                    "symmetric_common_support": True,
                    "chosen_stable": False,
                    "stable_output_advantage_100bp": -0.3,
                    "log_input_usd": np.log(1_000.0),
                    "input_usd": 1_000.0,
                    "ordered_pair": "0xc>0xd",
                },
            ]
        )
        capital = pd.DataFrame(
            [
                {
                    "day": "20240215",
                    "token_in": "0xa",
                    "token_out": "0xb",
                    "stable_public_vehicle": "0xs",
                    "native_public_vehicle": "0xn",
                    "stable_v2_bridge_capital_usd": 200.0,
                    "native_v2_bridge_capital_usd": 100.0,
                },
                {
                    "day": "20240215",
                    "token_in": "0xc",
                    "token_out": "0xd",
                    "stable_public_vehicle": "0xs",
                    "native_public_vehicle": "0xn",
                    "stable_v2_bridge_capital_usd": 0.0,
                    "native_v2_bridge_capital_usd": 100.0,
                },
            ]
        )
        stress = pd.DataFrame(
            {
                "date": [date],
                "prior_return_days": [30.0],
                "trailing_eth_return": [-0.10],
                "trailing_eth_volatility": [0.50],
                "eth_decline_per_10pp": [1.0],
                "eth_volatility_per_10pp": [5.0],
            }
        )
        result = prepare_executability_panel(frontier, capital, stress)
        self.assertEqual(result["route_id"].tolist(), ["keep"])
        self.assertAlmostEqual(
            float(result.iloc[0]["stable_minus_weth_log_v2_depth"]),
            np.log(2.0),
        )
        self.assertAlmostEqual(
            float(result.iloc[0]["stable_v2_capital_share"]), 2 / 3
        )

    @staticmethod
    def _synthetic_panel() -> pd.DataFrame:
        rng = np.random.default_rng(88)
        dates = pd.date_range("2022-01-15", periods=36, freq="MS") + pd.Timedelta(
            days=14
        )
        decline = np.sin(np.arange(len(dates)) / 3.0)
        volatility = 4.0 + np.cos(np.arange(len(dates)) / 5.0)
        rows = []
        for pair_index in range(24):
            pair = f"pair-{pair_index}"
            pair_effect = rng.normal(0, 0.15)
            for date_index, date in enumerate(dates):
                for route_index in range(2):
                    log_input = rng.normal(7.0, 0.3)
                    capital_advantage = (
                        0.18 * decline[date_index]
                        + pair_effect
                        + rng.normal(0, 0.15)
                    )
                    depth = (
                        0.25 * decline[date_index]
                        + 0.04 * volatility[date_index]
                        + pair_effect
                        + rng.normal(0, 0.10)
                    )
                    output = (
                        0.35 * decline[date_index]
                        + 0.45 * capital_advantage
                        + 0.03 * log_input
                        + rng.normal(0, 0.15)
                    )
                    latent_choice = (
                        0.20 * decline[date_index]
                        + 0.35 * output
                        + 0.20 * capital_advantage
                        + pair_effect
                        + rng.normal(0, 0.7)
                    )
                    rows.append(
                        {
                            "route_id": f"{pair}|{date:%Y%m%d}|{route_index}",
                            "ordered_pair": pair,
                            "date": date,
                            "calendar_month": str(date.month),
                            "calendar_time_years": (
                                date - pd.Timestamp("2018-01-01")
                            ).days
                            / 365.25,
                            "eth_decline_per_10pp": decline[date_index],
                            "eth_volatility_per_10pp": volatility[date_index],
                            "log_input_usd": log_input,
                            "stable_v2_capital_advantage_10pp": capital_advantage,
                            "stable_minus_weth_log_v2_depth": depth,
                            "stable_output_advantage_100bp": output,
                            "chosen_stable": float(latent_choice > 0),
                        }
                    )
        return pd.DataFrame(rows)

    def test_model_families_cover_three_stages_and_conditioned_links(self) -> None:
        results = fit_chain_models(
            self._synthetic_panel(),
            min_observations=200,
            min_pair_clusters=10,
            min_date_clusters=20,
        )
        focal = results[results["focal_decline_coefficient"]]
        self.assertEqual(len(results), 23)
        self.assertEqual(
            focal.groupby("multiplicity_family").size().to_dict(),
            {
                "primary_mark_to_market_execution_routing_chain": 3,
                "secondary_conditioned_transmission": 2,
            },
        )
        self.assertTrue(focal["holm_p_value"].notna().all())
        primary = focal[
            focal["multiplicity_family"].eq(
                "primary_mark_to_market_execution_routing_chain"
            )
        ]
        self.assertTrue(primary["coefficient"].gt(0).all())


if __name__ == "__main__":
    unittest.main()
