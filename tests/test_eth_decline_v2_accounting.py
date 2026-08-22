from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.analyze.run_eth_decline_v2_accounting import (
    fit_accounting_models,
    load_fixed_pool_matches,
    prepare_accounting_panel,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
ENDPOINT = "0x1111111111111111111111111111111111111111"


def _state(
    date: str,
    pool: str,
    vehicle: str,
    *,
    capital: float,
    quantity: float,
    endpoint: str = ENDPOINT,
) -> dict[str, object]:
    return {
        "origin_date": pd.Timestamp(date),
        "pool": pool,
        "token0_address": vehicle,
        "token1_address": endpoint,
        "venue": "uniswap_v2",
        "v2_capital_usd": capital,
        "v2_sqrt_k": quantity,
        "v2_capital_valid": True,
    }


class EthDeclineV2AccountingTest(unittest.TestCase):
    def test_loader_holds_anchor_pool_set_fixed(self) -> None:
        states = pd.DataFrame(
            [
                _state("2024-01-01", "native", WETH, capital=100_000, quantity=10),
                _state("2024-01-01", "stable", USDC, capital=120_000, quantity=12),
                _state("2024-01-02", "native", WETH, capital=95_000, quantity=10),
                _state("2024-01-02", "stable", USDC, capital=125_000, quantity=12),
                _state("2024-01-02", "new", USDC, capital=500_000, quantity=50),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.parquet"
            states.to_parquet(path, index=False)
            matched = load_fixed_pool_matches([path], horizons=(1,))
        first_anchor = matched.loc[
            matched["anchor_date"].eq(pd.Timestamp("2024-01-01"))
        ]
        self.assertEqual(set(first_anchor["pool"]), {"native", "stable"})
        self.assertTrue(first_anchor["future_observed"].all())
        self.assertNotIn("new", first_anchor["pool"].tolist())

    def test_shapley_components_sum_to_relative_capital_change(self) -> None:
        matches = pd.DataFrame(
            [
                {
                    "venue": "uniswap_v2",
                    "endpoint": ENDPOINT,
                    "anchor_date": pd.Timestamp("2024-01-01"),
                    "horizon_days": 1,
                    "pool": "stable",
                    "vehicle_family": "stable",
                    "capital_usd_0": 200.0,
                    "sqrt_k_0": 20.0,
                    "future_date": pd.Timestamp("2024-01-02"),
                    "capital_usd_1": 220.0,
                    "sqrt_k_1": 22.0,
                    "future_observed": True,
                },
                {
                    "venue": "uniswap_v2",
                    "endpoint": ENDPOINT,
                    "anchor_date": pd.Timestamp("2024-01-01"),
                    "horizon_days": 1,
                    "pool": "native",
                    "vehicle_family": "native",
                    "capital_usd_0": 100.0,
                    "sqrt_k_0": 10.0,
                    "future_date": pd.Timestamp("2024-01-02"),
                    "capital_usd_1": 90.0,
                    "sqrt_k_1": 10.0,
                    "future_observed": True,
                },
            ]
        )
        prices = pd.DataFrame(
            {
                "origin_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "price_usd": [2_000.0, 1_800.0],
            }
        )
        panel, support = prepare_accounting_panel(
            matches, prices, known_stables=frozenset()
        )
        row = panel.iloc[0]
        expected_quantity = np.log(1.1)
        expected_value = -np.log(0.9)
        self.assertAlmostEqual(
            float(row["stable_minus_weth_log_quantity_component"]),
            expected_quantity,
        )
        self.assertAlmostEqual(
            float(row["stable_minus_weth_log_unit_value_component"]),
            expected_value,
        )
        self.assertAlmostEqual(
            float(row["stable_minus_weth_log_capital_change"]),
            expected_quantity + expected_value,
        )
        self.assertLess(float(row["relative_identity_error"]), 1e-12)
        self.assertEqual(support["candidate_endpoint_intervals"], 1)

    def test_incomplete_future_pool_set_is_removed(self) -> None:
        complete_endpoint = ENDPOINT
        incomplete_endpoint = "0x2222222222222222222222222222222222222222"
        rows = []
        for endpoint, future_native in (
            (complete_endpoint, True),
            (incomplete_endpoint, False),
        ):
            rows.append(
                {
                    "venue": "uniswap_v2",
                    "endpoint": endpoint,
                    "anchor_date": pd.Timestamp("2024-01-01"),
                    "horizon_days": 1,
                    "pool": f"stable-{endpoint}",
                    "vehicle_family": "stable",
                    "capital_usd_0": 100.0,
                    "sqrt_k_0": 10.0,
                    "future_date": pd.Timestamp("2024-01-02"),
                    "capital_usd_1": 100.0,
                    "sqrt_k_1": 10.0,
                    "future_observed": True,
                }
            )
            rows.append(
                {
                    "venue": "uniswap_v2",
                    "endpoint": endpoint,
                    "anchor_date": pd.Timestamp("2024-01-01"),
                    "horizon_days": 1,
                    "pool": f"native-{endpoint}",
                    "vehicle_family": "native",
                    "capital_usd_0": 100.0,
                    "sqrt_k_0": 10.0,
                    "future_date": (
                        pd.Timestamp("2024-01-02") if future_native else pd.NaT
                    ),
                    "capital_usd_1": 100.0 if future_native else np.nan,
                    "sqrt_k_1": 10.0 if future_native else np.nan,
                    "future_observed": future_native,
                }
            )
        prices = pd.DataFrame(
            {
                "origin_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "price_usd": [2_000.0, 1_900.0],
            }
        )
        panel, support = prepare_accounting_panel(
            pd.DataFrame(rows), prices, known_stables=frozenset()
        )
        self.assertEqual(panel["endpoint"].tolist(), [complete_endpoint])
        self.assertEqual(support["candidate_endpoint_intervals"], 2)
        self.assertEqual(support["complete_endpoint_intervals_before_price_match"], 1)

    def test_regressions_recover_accounting_slopes(self) -> None:
        rng = np.random.default_rng(412)
        dates = pd.date_range("2022-01-01", periods=150, freq="D")
        decline = np.sin(np.arange(len(dates)) / 8.0)
        rows: list[dict[str, object]] = []
        for endpoint_index in range(24):
            endpoint = f"endpoint-{endpoint_index}"
            quantity_effect = rng.normal(0, 0.05)
            value_effect = rng.normal(0, 0.05)
            for date_index, date in enumerate(dates):
                quantity = (
                    -0.03 * decline[date_index]
                    + quantity_effect
                    + rng.normal(0, 0.003)
                )
                unit_value = (
                    0.05 * decline[date_index]
                    + value_effect
                    + rng.normal(0, 0.003)
                )
                rows.append(
                    {
                        "venue": "uniswap_v2",
                        "endpoint": endpoint,
                        "horizon_days": 1,
                        "anchor_date": date,
                        "endpoint_is_stable": False,
                        "endpoint_fixed_effect": f"uniswap_v2|{endpoint}",
                        "anchor_month": date.to_period("M").strftime("%Y-%m"),
                        "eth_decline_per_10pp": decline[date_index],
                        "stable_minus_weth_log_quantity_component": quantity,
                        "stable_minus_weth_log_unit_value_component": unit_value,
                        "stable_minus_weth_log_capital_change": quantity + unit_value,
                    }
                )
        result = fit_accounting_models(
            pd.DataFrame(rows),
            min_observations=500,
            min_endpoints=10,
            min_dates=60,
            hac_lag_days=3,
        )
        pooled = result[result["venue"].eq("pooled_v2")].set_index("outcome")
        self.assertAlmostEqual(
            float(
                pooled.loc[
                    "stable_minus_weth_log_quantity_component", "coefficient"
                ]
            ),
            -0.03,
            delta=0.003,
        )
        self.assertAlmostEqual(
            float(
                pooled.loc[
                    "stable_minus_weth_log_unit_value_component", "coefficient"
                ]
            ),
            0.05,
            delta=0.003,
        )
        self.assertAlmostEqual(
            float(
                pooled.loc[
                    "stable_minus_weth_log_capital_change", "coefficient"
                ]
            ),
            0.02,
            delta=0.004,
        )


if __name__ == "__main__":
    unittest.main()
