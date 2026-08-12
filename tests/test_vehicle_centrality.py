from __future__ import annotations

import unittest

import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH
from scripts.build_vehicle_centrality import aggregate_day_edges, centralities


class VehicleCentralityTests(unittest.TestCase):
    def test_edge_build_unifies_native_and_wrapped_eth_and_separates_value_support(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "tx_hash": "native",
                    "component_id": 0,
                    "token_in": NATIVE_ETH,
                    "token_out": "a",
                    "amount_usd": 100.0,
                    "route_class": "single",
                },
                {
                    "tx_hash": "wrapped",
                    "component_id": 0,
                    "token_in": WETH,
                    "token_out": "a",
                    "amount_usd": 200.0,
                    "route_class": "single",
                },
                {
                    "tx_hash": "plumbing",
                    "component_id": 0,
                    "token_in": NATIVE_ETH,
                    "token_out": WETH,
                    "amount_usd": 1_000.0,
                    "route_class": "single",
                },
            ]
        )
        result = aggregate_day_edges(frame)
        self.assertEqual(len(result), 1)
        self.assertEqual({result.iloc[0]["a"], result.iloc[0]["b"]}, {WETH, "a"})
        self.assertEqual(result.iloc[0]["legs"], 2)
        self.assertAlmostEqual(result.iloc[0]["usd"], 300.0)
        self.assertAlmostEqual(result.iloc[0]["raw_usd"], 300.0)

    def test_direct_path_and_excess_positions_share_one_scale(self) -> None:
        edges = pd.DataFrame(
            [
                {"a": "a", "b": "b", "usd": 100.0, "legs": 10},
                {"a": "b", "b": "c", "usd": 500.0, "legs": 50},
                {"a": "c", "b": "d", "usd": 50.0, "legs": 5},
                {"a": "b", "b": "d", "usd": 25.0, "legs": 2},
            ]
        )
        result = centralities(edges, k=None).set_index("token")

        self.assertEqual(result.loc["b", "degree_topological"], 3)
        self.assertEqual(result.loc["b", "strength_count"], 62)
        self.assertAlmostEqual(result.loc["b", "strength_usd"], 625.0)
        self.assertTrue((result["degree"] == result["degree_topological"]).all())

        for dimension in ("topological", "count", "value"):
            direct = result[f"direct_{dimension}_share"]
            eigenvector = result[f"eigenvector_{dimension}_share"]
            betweenness = result[f"betweenness_{dimension}_share"]
            self.assertAlmostEqual(float(direct.sum()), 1.0)
            self.assertAlmostEqual(float(eigenvector.sum()), 1.0)
            self.assertAlmostEqual(float(betweenness.sum()), 1.0)
            pd.testing.assert_series_equal(
                result[f"excess_betweenness_over_direct_{dimension}"],
                betweenness - direct,
                check_names=False,
            )
            pd.testing.assert_series_equal(
                result[f"excess_betweenness_over_eigenvector_{dimension}"],
                betweenness - eigenvector,
                check_names=False,
            )
            self.assertAlmostEqual(
                float(result[f"excess_betweenness_over_direct_{dimension}"].sum()),
                0.0,
            )
            self.assertAlmostEqual(
                float(
                    result[
                        f"excess_betweenness_over_eigenvector_{dimension}"
                    ].sum()
                ),
                0.0,
            )

    def test_count_and_value_weighting_are_distinct(self) -> None:
        edges = pd.DataFrame(
            [
                {"a": "a", "b": "b", "usd": 10_000.0, "legs": 1},
                {"a": "b", "b": "c", "usd": 1.0, "legs": 100},
                {"a": "c", "b": "d", "usd": 1.0, "legs": 100},
                {"a": "a", "b": "d", "usd": 1.0, "legs": 100},
            ]
        )
        result = centralities(edges, k=None)
        self.assertFalse(
            result["direct_count_share"].equals(result["direct_value_share"])
        )
        self.assertFalse(
            result["eigenvector_count_share"].equals(
                result["eigenvector_value_share"]
            )
        )

    def test_eigenvector_perimeter_is_the_largest_connected_component(self) -> None:
        edges = pd.DataFrame(
            [
                {"a": "a", "b": "b", "usd": 10.0, "legs": 1},
                {"a": "b", "b": "c", "usd": 10.0, "legs": 1},
                {"a": "c", "b": "d", "usd": 10.0, "legs": 1},
                {"a": "x", "b": "y", "usd": 1_000.0, "legs": 1_000},
            ]
        )
        result = centralities(edges, k=None).set_index("token")
        for dimension in ("topological", "count", "value"):
            self.assertEqual(result.loc["x", f"eigenvector_{dimension}"], 0.0)
            self.assertEqual(result.loc["y", f"eigenvector_{dimension}"], 0.0)

    def test_count_support_threshold_does_not_filter_value_edges(self) -> None:
        edges = pd.DataFrame(
            [
                {"a": "a", "b": "b", "usd": 10_000.0, "legs": 1},
                {"a": "b", "b": "c", "usd": 10.0, "legs": 10},
                {"a": "c", "b": "d", "usd": 10.0, "legs": 10},
                {"a": "d", "b": "e", "usd": 10.0, "legs": 10},
                {"a": "b", "b": "e", "usd": 10.0, "legs": 10},
            ]
        )
        result = centralities(edges, k=None, min_legs=5).set_index("token")
        self.assertEqual(result.loc["a", "direct_count_share"], 0.0)
        self.assertGreater(result.loc["a", "direct_value_share"], 0.0)


if __name__ == "__main__":
    unittest.main()
