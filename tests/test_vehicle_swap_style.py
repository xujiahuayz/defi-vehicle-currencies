from __future__ import annotations

import unittest

import pandas as pd

from scripts.build_vehicle_swap_style import annual_summary, reduce_routes


class VehicleSwapStyleTests(unittest.TestCase):
    def test_matched_support_and_morphology_are_distinct(self) -> None:
        routes = pd.DataFrame(
            [
                {"tx_hash": "a", "component_id": 0, "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "legs": 2, "cross_venue": False, "within_20pct": True, "usd": 10.0},
                {"tx_hash": "b", "component_id": 0, "vehicle": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "legs": 3, "cross_venue": True, "within_20pct": True, "usd": 90.0},
                {"tx_hash": "d", "component_id": 0, "vehicle": "0xdac17f958d2ee523a2206206994597c13d831ec7", "legs": 2, "cross_venue": True, "within_20pct": True, "usd": 900.0},
                {"tx_hash": "c", "component_id": 0, "vehicle": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "legs": 2, "cross_venue": False, "within_20pct": False, "usd": 1_000.0},
            ]
        )
        result = reduce_routes(routes, "20250101")
        native = result[result["asset_type"].eq("native")].iloc[0]
        stable = result[result["asset_type"].eq("stable")]
        self.assertEqual(native["morphology"], "sequential")
        self.assertEqual(native["episodes_strict"], 1)
        self.assertEqual(stable["episodes_all"].sum(), 3)
        self.assertEqual(stable["episodes_strict"].sum(), 2)
        self.assertEqual(set(stable["morphology"]), {"branched_split_join", "sequential"})
        self.assertLess(result["strict_value_capped_p90_usd"].sum(), result["strict_value_usd"].sum())

    def test_annual_summary_equal_weights_days(self) -> None:
        panel = pd.DataFrame(
            [
                {"date": date, "asset_type": asset_type, "morphology": "sequential", "integration": "single_venue", "complexity": "two_leg", "episodes_all": count, "episodes_strict": count, "strict_value_usd": value, "strict_value_capped_p90_usd": value, "strict_value_capped_p95_usd": value, "strict_value_capped_p99_usd": value}
                for date, asset_type, count, value in (
                    ("2024-01-01", "native", 9, 90),
                    ("2024-01-01", "stable", 1, 10),
                    ("2024-01-02", "native", 1, 10),
                    ("2024-01-02", "stable", 9, 90),
                )
            ]
        )
        result = annual_summary(panel)
        stable = result[result["dimension"].eq("all") & result["asset_type"].eq("stable")].iloc[0]
        self.assertAlmostEqual(stable["episodes_strict_share"], 0.5)
        self.assertAlmostEqual(stable["strict_value_usd_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
