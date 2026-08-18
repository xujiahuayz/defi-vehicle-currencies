from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH
from scripts.process.build_cross_venue_routing_series import (
    BALANCED_VENUES,
    bounded_workers,
    one_day,
    routing_incidence_change_tests,
    routing_technology_windows,
)


class CrossVenueRoutingSeriesTests(unittest.TestCase):
    def test_technology_windows_exclude_event_day_and_preserve_both_scopes(self) -> None:
        panel = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "economic_routes": [20, 20, 999, 20, 20],
                "economic_multileg_routes": [10, 10, 999, 5, 5],
                "intermediated_routes": [10, 10, 999, 5, 5],
                "economic_multileg_swap_legs": [20, 20, 999, 15, 15],
                "economic_multileg_venue_count": [10, 20, 999, 10, 10],
                "economic_multileg_over_two_routes": [0, 0, 999, 5, 5],
                "cross_venue_routes": [0, 10, 999, 5, 5],
                "balanced_economic_routes": [20, 20, 999, 20, 20],
                "balanced_economic_multileg_routes": [10, 10, 999, 5, 5],
                "balanced_intermediated_routes": [10, 10, 999, 5, 5],
                "balanced_economic_multileg_swap_legs": [20, 20, 999, 15, 15],
                "balanced_economic_multileg_venue_count": [10, 20, 999, 10, 10],
                "balanced_economic_multileg_over_two_routes": [0, 0, 999, 5, 5],
                "balanced_cross_venue_routes": [0, 10, 999, 5, 5],
            }
        )
        result = routing_technology_windows(
            panel,
            events=(("test", "2021-01-03", "source"),),
            window_days=2,
        )
        self.assertEqual(len(result), 4)
        full = result[result["scope"].eq("full")].set_index("period")
        self.assertEqual(full.loc["pre", "economic_multileg_routes"], 20)
        self.assertEqual(full.loc["post", "economic_multileg_routes"], 10)
        self.assertEqual(full.loc["pre", "cross_venue_share"], 0.5)
        self.assertEqual(full.loc["post", "over_two_legs_share"], 1.0)

    def test_incidence_change_separates_full_and_balanced_perimeters(self) -> None:
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2022-01-01", "2022-01-02", "2026-01-01", "2026-01-02"]
                ),
                "economic_routes": [10, 10, 10, 10],
                "economic_multileg_routes": [4, 6, 2, 2],
                "economic_multileg_share": [0.4, 0.6, 0.2, 0.2],
                "intermediated_routes": [4, 6, 2, 2],
                "intermediated_share": [0.4, 0.6, 0.2, 0.2],
                "balanced_economic_routes": [10, 10, 8, 8],
                "balanced_economic_multileg_routes": [4, 6, 1, 1],
                "balanced_economic_multileg_share": [0.4, 0.6, 0.125, 0.125],
                "balanced_intermediated_routes": [4, 6, 1, 1],
                "balanced_intermediated_share": [0.4, 0.6, 0.125, 0.125],
            }
        )
        result = routing_incidence_change_tests(panel, hac_lag=0).set_index("scope")
        self.assertAlmostEqual(result.loc["full", "change"], -0.3)
        self.assertAlmostEqual(result.loc["balanced", "change"], -0.375)
        self.assertAlmostEqual(result.loc["full", "comparison_ratio_of_totals"], 0.2)
        self.assertAlmostEqual(result.loc["balanced", "comparison_ratio_of_totals"], 0.125)
        self.assertAlmostEqual(result.loc["balanced", "balanced_route_coverage_comparison"], 0.8)
        self.assertAlmostEqual(result.loc["balanced", "entrant_touching_incidence_comparison"], 0.5)

    def test_clean_routes_are_ordered_and_ambiguous_components_are_excluded(self) -> None:
        rows = [
            {
                "tx_hash": "cross",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "K",
                "token_out": "B",
                "tin_role": "intermediate",
                "tout_role": "sink",
                "log_index": 2,
            },
            {
                "tx_hash": "cross",
                "component_id": 0,
                "source": "v3",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "A",
                "token_out": "K",
                "tin_role": "source",
                "tout_role": "intermediate",
                "log_index": 1,
            },
            {
                "tx_hash": "ambiguous",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 999.0,
                "route_class": "tricky_bridged",
                "token_in": "X",
                "token_out": "Y",
                "tin_role": "source",
                "tout_role": "sink",
                "log_index": 0,
            },
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["legs"], 2)
        self.assertEqual(result["routes"], 1)
        self.assertEqual(result["economic_multileg_routes"], 1)
        self.assertEqual(result["economic_multileg_swap_legs"], 2)
        self.assertEqual(result["economic_multileg_venue_count"], 2)
        self.assertEqual(result["economic_multileg_over_two_routes"], 0)
        self.assertEqual(result["economic_multileg_mean_legs"], 2.0)
        self.assertEqual(result["economic_multileg_mean_venues"], 2.0)
        self.assertEqual(result["cross_venue_routes"], 1)
        self.assertEqual(result["intermediated_routes"], 1)
        self.assertEqual(result["direct_split_routes"], 0)
        self.assertEqual(result["round_trip_routes"], 0)

    def test_parallel_direct_pool_split_is_not_indirect_intermediation(self) -> None:
        rows = [
            {
                "tx_hash": "split",
                "component_id": 0,
                "source": source,
                "amount_usd": amount,
                "route_class": "coherent",
                "token_in": "A",
                "token_out": "B",
                "tin_role": "source",
                "tout_role": "sink",
                "log_index": index,
            }
            for index, (source, amount) in enumerate((("v2", 60.0), ("v3", 40.0)))
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["economic_multileg_routes"], 1)
        self.assertEqual(result["direct_split_routes"], 1)
        self.assertEqual(result["intermediated_routes"], 0)
        self.assertEqual(result["cross_venue_routes"], 0)
        self.assertEqual(result["cross_venue_share_unfiltered"], 1.0)

    def test_value_shares_report_nested_flow_coherence_support(self) -> None:
        rows = [
            {
                "tx_hash": "mismatch",
                "component_id": 0,
                "source": source,
                "amount_usd": amount,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "tin_role": "source" if index == 0 else "intermediate",
                "tout_role": "intermediate" if index == 0 else "sink",
                "log_index": index,
            }
            for index, (source, amount, token_in, token_out) in enumerate(
                (("v2", 100.0, "A", "K"), ("v3", 50.0, "K", "B"))
            )
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["intermediated_usd"], 75.0)
        self.assertEqual(result["intermediated_usd_within_2x"], 75.0)
        self.assertEqual(result["intermediated_usd_within_20pct"], 0.0)
        self.assertTrue(pd.isna(result["cross_venue_usd_share_within_20pct"]))

    def test_round_trip_is_excluded_from_headline_but_retained_as_diagnostic(self) -> None:
        rows = [
            {
                "tx_hash": "cycle",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "A",
                "token_out": "K",
                "tin_role": "intermediate",
                "tout_role": "intermediate",
                "log_index": 1,
            },
            {
                "tx_hash": "cycle",
                "component_id": 0,
                "source": "v3",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "K",
                "token_out": "A",
                "tin_role": "intermediate",
                "tout_role": "intermediate",
                "log_index": 2,
            },
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["round_trip_routes"], 1)
        self.assertEqual(result["economic_routes"], 0)
        self.assertEqual(result["economic_multileg_routes"], 0)
        self.assertEqual(result["cross_venue_routes"], 0)

    def test_multiple_endpoint_component_is_ambiguous_not_economic(self) -> None:
        rows = [
            {
                "tx_hash": "ambiguous",
                "component_id": 0,
                "source": source,
                "amount_usd": amount,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "tin_role": tin_role,
                "tout_role": tout_role,
                "log_index": log_index,
            }
            for source, amount, token_in, token_out, tin_role, tout_role, log_index in [
                ("v2", 60.0, "A", "K", "source", "intermediate", 1),
                ("v3", 40.0, "C", "K", "source", "intermediate", 2),
                ("v3", 99.0, "K", "B", "intermediate", "sink", 3),
            ]
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["routes"], 1)
        self.assertEqual(result["ambiguous_routes"], 1)
        self.assertEqual(result["economic_routes"], 0)
        self.assertEqual(result["economic_multileg_routes"], 0)

    def test_native_and_wrapped_eth_are_one_economic_endpoint(self) -> None:
        rows = [
            {
                "tx_hash": "wrap-cycle",
                "component_id": 0,
                "source": source,
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "tin_role": "intermediate",
                "tout_role": "intermediate",
                "log_index": log_index,
            }
            for source, token_in, token_out, log_index in [
                ("uniswap_v4", NATIVE_ETH, "K", 1),
                ("uniswap_v3", "K", WETH, 2),
            ]
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["round_trip_routes"], 1)
        self.assertEqual(result["economic_routes"], 0)
        self.assertEqual(result["economic_multileg_routes"], 0)

    def test_route_complexity_is_aggregated_over_economic_routes(self) -> None:
        rows = [
            {
                "tx_hash": "complex",
                "component_id": 0,
                "source": source,
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "tin_role": "source" if log_index == 1 else "intermediate",
                "tout_role": "sink" if log_index == 3 else "intermediate",
                "log_index": log_index,
            }
            for log_index, source, token_in, token_out in [
                (1, "v2", "A", "K1"),
                (2, "v2", "K1", "K2"),
                (3, "v3", "K2", "B"),
            ]
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["economic_multileg_routes"], 1)
        self.assertEqual(result["economic_multileg_swap_legs"], 3)
        self.assertEqual(result["economic_multileg_venue_count"], 2)
        self.assertEqual(result["economic_multileg_over_two_routes"], 1)
        self.assertEqual(result["economic_multileg_over_two_share"], 1.0)

    def test_worker_count_is_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)

    def test_balanced_perimeter_keeps_only_wholly_observed_routes(self) -> None:
        old_a, old_b = sorted(BALANCED_VENUES)[:2]
        rows = [
            {
                "tx_hash": tx,
                "component_id": 0,
                "source": source,
                "amount_usd": amount,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "tin_role": "intermediate" if tx == "cycle" else ("source" if log_index == 1 else "intermediate"),
                "tout_role": "intermediate" if tx == "cycle" else ("sink" if log_index == 2 or tx == "direct" else "intermediate"),
                "log_index": log_index,
            }
            for tx, source, amount, token_in, token_out, log_index in [
                ("old", old_a, 100.0, "A", "K", 1),
                ("old", old_b, 100.0, "K", "B", 2),
                ("new", old_a, 200.0, "C", "M", 1),
                ("new", "uniswap_v4", 200.0, "M", "D", 2),
                ("direct", old_a, 50.0, "E", "F", 1),
                ("cycle", old_a, 80.0, "G", "H", 1),
                ("cycle", old_b, 80.0, "H", "G", 2),
            ]
        ]
        rows[-3]["route_class"] = "single"
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["economic_multileg_routes"], 2)
        self.assertEqual(result["economic_routes"], 3)
        self.assertEqual(result["balanced_routes"], 3)
        self.assertEqual(result["balanced_single_leg_routes"], 1)
        self.assertEqual(result["balanced_multi_leg_routes"], 2)
        self.assertEqual(result["balanced_round_trip_routes"], 1)
        self.assertEqual(result["balanced_economic_routes"], 2)
        self.assertEqual(result["balanced_economic_multileg_routes"], 1)
        self.assertEqual(result["balanced_economic_multileg_share"], 0.5)
        self.assertEqual(result["balanced_cross_venue_routes"], 1)
        self.assertEqual(result["balanced_cross_venue_share"], 1.0)
        self.assertEqual(result["balanced_economic_multileg_usd"], 100.0)


if __name__ == "__main__":
    unittest.main()
