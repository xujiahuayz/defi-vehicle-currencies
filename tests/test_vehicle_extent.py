from __future__ import annotations

import unittest

import pandas as pd

from ddvc.asset_types import CURRENCY_TYPES, WETH
from ddvc.realised import extract_realised_routes
from ddvc.vehicle_extent import (
    aggregate_vehicle_extent,
    compute_vehicle_extent,
    restrict_routes_to_venues,
)
from scripts.build_vehicle_excess_use import (
    bounded_workers,
    stable_backing_year,
    token_excess_use_transition_tests,
)


def leg(
    tx: str,
    component: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    amount: float,
    route_class: str = "coherent",
    log_index: int | None = None,
) -> dict:
    return {
        "tx_hash": tx,
        "component_id": component,
        "route_class": route_class,
        "token_in": token_in,
        "token_out": token_out,
        "tin_role": tin_role,
        "tout_role": tout_role,
        "amount_usd": amount,
        "log_index": (
            log_index if log_index is not None else (0 if tin_role == "source" else 1)
        ),
    }


class VehicleExtentTests(unittest.TestCase):
    def test_route_counts_do_not_depend_on_usd_price_support(self) -> None:
        rows = [
            leg("missing", 0, "a", "k", "source", "intermediate", float("nan")),
            leg("missing", 0, "k", "b", "intermediate", "sink", float("nan")),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertEqual(out.loc["k", "intermediate_routes"], 1)
        self.assertEqual(out.loc["k", "intermediate_usd"], 0.0)
        self.assertEqual(out.loc["k", "intermediate_usd_within_2x"], 0.0)

    def test_vehicle_extent_workers_are_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)

    def test_primary_currency_types_exclude_only_the_residual_bucket(self) -> None:
        self.assertEqual(
            CURRENCY_TYPES,
            ("native", "staked_native", "stable", "imported"),
        )

    def test_direct_routes_enter_endpoint_demand_but_not_intermediation(self) -> None:
        rows = [
            leg("indirect", 0, "a", "k", "source", "intermediate", 100),
            leg("indirect", 0, "k", "b", "intermediate", "sink", 100),
            leg("direct", 0, "a", "b", "source", "sink", 300, "single"),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertAlmostEqual(out.loc["k", "intermediate_share"], 1.0)
        self.assertAlmostEqual(out.loc["k", "endpoint_share"], 0.0)
        self.assertFalse(bool(out.loc["k", "endpoint_supported"]))
        self.assertAlmostEqual(out.loc["a", "endpoint_share"], 0.5)
        self.assertAlmostEqual(out.loc["b", "endpoint_share"], 0.5)
        self.assertEqual(out.loc["k", "intermediate_routes"], 1)
        self.assertEqual(out.loc["a", "endpoint_routes"], 2)
        self.assertEqual(out.loc["b", "endpoint_routes"], 2)
        self.assertAlmostEqual(out.loc["k", "intermediate_count_share"], 1.0)

    def test_ratio_uses_endpoint_roles_not_all_leg_volume(self) -> None:
        rows = [
            leg("r1", 0, "a", "k", "source", "intermediate", 100),
            leg("r1", 0, "k", "b", "intermediate", "sink", 100),
            leg("r2", 0, "k", "x", "source", "sink", 100, "single"),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertAlmostEqual(out.loc["k", "intermediate_share"], 1.0)
        self.assertAlmostEqual(out.loc["k", "endpoint_share"], 0.25)
        self.assertAlmostEqual(
            out.loc["k", "vehicle_excess_use_ratio"], 4.0
        )
        self.assertAlmostEqual(
            out.loc["k", "vehicle_excess_use_count_ratio"], 4.0
        )

    def test_cycles_are_removed_from_both_sides(self) -> None:
        rows = [
            leg("good", 0, "a", "k", "source", "intermediate", 100),
            leg("good", 0, "k", "b", "intermediate", "sink", 100),
            leg("cycle", 0, "a", "k", "source", "intermediate", 1000),
            leg("cycle", 0, "k", "a", "intermediate", "sink", 1000),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows))
        self.assertTrue((out["routes_cyclic_excluded"] == 1).all())
        self.assertAlmostEqual(
            out.set_index("token").loc["k", "intermediate_usd"], 100
        )

    def test_multiple_endpoint_components_are_removed_from_both_sides(self) -> None:
        rows = [
            leg("good", 0, "a", "k", "source", "intermediate", 100),
            leg("good", 0, "k", "b", "intermediate", "sink", 100),
            leg("ambiguous", 0, "a", "m", "source", "intermediate", 10_000),
            leg("ambiguous", 0, "c", "m", "source", "intermediate", 10_000),
            leg("ambiguous", 0, "m", "b", "intermediate", "sink", 10_000),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows))
        self.assertTrue((out["routes_ambiguous_excluded"] == 1).all())
        self.assertNotIn("m", set(out["token"]))
        self.assertAlmostEqual(out.set_index("token").loc["k", "intermediate_usd"], 100)

    def test_extent_and_realised_routes_share_intermediary_value_contract(self) -> None:
        rows = [
            leg("linear", 0, "a", "k", "source", "intermediate", 100, log_index=0),
            leg("linear", 0, "k", "b", "intermediate", "sink", 110, log_index=1),
            leg("long", 0, "a", "k", "source", "intermediate", 200, log_index=0),
            leg("long", 0, "k", "m", "intermediate", "intermediate", 220, log_index=1),
            leg("long", 0, "m", "b", "intermediate", "sink", 240, log_index=2),
        ]
        frame = pd.DataFrame(rows)
        frame["source"] = "venue"
        frame["timestamp_utc"] = 7 * 3600
        extent = compute_vehicle_extent(frame).set_index("token")["intermediate_usd"]
        realised = extract_realised_routes(frame).groupby("vehicle")["usd"].sum()
        pd.testing.assert_series_equal(
            extent.reindex(realised.index), realised, check_names=False
        )

    def test_parallel_route_values_sum_branches_before_balancing_sides(self) -> None:
        rows = [
            leg("split", 0, "a", "k", "source", "intermediate", 60, log_index=0),
            leg("split", 0, "a", "k", "source", "intermediate", 40, log_index=1),
            leg("split", 0, "k", "b", "intermediate", "sink", 99, log_index=2),
        ]
        frame = pd.DataFrame(rows)
        frame["source"] = "venue"
        frame["timestamp_utc"] = 7 * 3600
        extent = compute_vehicle_extent(frame).set_index("token")
        realised = extract_realised_routes(frame).set_index("vehicle")
        self.assertAlmostEqual(extent.loc["a", "endpoint_usd"], 100.0)
        self.assertAlmostEqual(extent.loc["b", "endpoint_usd"], 99.0)
        self.assertAlmostEqual(extent.loc["k", "intermediate_usd"], 99.5)
        self.assertAlmostEqual(extent.loc["k", "intermediate_usd_within_20pct"], 99.5)
        self.assertAlmostEqual(realised.loc["k", "usd"], 99.5)

    def test_value_incoherence_is_quarantined_without_removing_route_counts(self) -> None:
        rows = [
            leg("broken", 0, "a", "k", "source", "intermediate", 100, log_index=0),
            leg("broken", 0, "k", "m", "intermediate", "intermediate", 1_000, log_index=1),
            leg("broken", 0, "m", "b", "intermediate", "sink", 100, log_index=2),
            leg("direct", 0, "a", "b", "source", "sink", 100, "single", log_index=0),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertEqual(out.loc["k", "intermediate_routes"], 1)
        self.assertEqual(out.loc["m", "intermediate_routes"], 1)
        self.assertAlmostEqual(out.loc["k", "intermediate_usd"], 550.0)
        self.assertEqual(out.loc["k", "intermediate_usd_within_2x"], 0.0)
        self.assertEqual(out.loc["m", "intermediate_usd_within_20pct"], 0.0)
        self.assertEqual(out.loc["k", "intermediate_routes_within_20pct"], 0)
        self.assertEqual(out.loc["m", "intermediate_routes_within_20pct"], 0)
        self.assertAlmostEqual(out.loc["a", "endpoint_usd_within_20pct"], 100.0)
        self.assertEqual(out.loc["a", "endpoint_routes_within_20pct"], 1)

    def test_value_and_count_shares_can_be_compared_on_identical_support(self) -> None:
        rows = [
            leg("small", 0, "a", "k", "source", "intermediate", 10, log_index=0),
            leg("small", 0, "k", "b", "intermediate", "sink", 10, log_index=1),
            leg("large", 0, "a", "m", "source", "intermediate", 90, log_index=0),
            leg("large", 0, "m", "b", "intermediate", "sink", 90, log_index=1),
            leg("broken", 0, "a", "k", "source", "intermediate", 10, log_index=0),
            leg("broken", 0, "k", "b", "intermediate", "sink", 100, log_index=1),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertAlmostEqual(out.loc["k", "intermediate_count_share"], 2 / 3)
        self.assertAlmostEqual(out.loc["k", "intermediate_count_share_within_20pct"], 0.5)
        self.assertAlmostEqual(out.loc["k", "intermediate_share_within_20pct"], 0.1)
        self.assertAlmostEqual(out.loc["m", "intermediate_count_share_within_20pct"], 0.5)
        self.assertAlmostEqual(out.loc["m", "intermediate_share_within_20pct"], 0.9)

    def test_branched_dag_is_economic_not_cyclic(self) -> None:
        rows = [
            leg("branch", 0, "a", "k1", "source", "intermediate", 60, log_index=0),
            leg("branch", 0, "a", "k2", "source", "intermediate", 40, log_index=1),
            leg("branch", 0, "k1", "b", "intermediate", "sink", 59, log_index=2),
            leg("branch", 0, "k2", "b", "intermediate", "sink", 39, log_index=3),
        ]
        frame = pd.DataFrame(rows)
        frame["source"] = "venue"
        frame["timestamp_utc"] = 7 * 3600
        extent = compute_vehicle_extent(frame).set_index("token")
        realised = extract_realised_routes(frame).set_index("vehicle")
        self.assertTrue((extent["routes_clean"] == 1).all())
        self.assertTrue((extent["routes_cyclic_excluded"] == 0).all())
        self.assertAlmostEqual(extent.loc["a", "endpoint_usd"], 100.0)
        self.assertAlmostEqual(extent.loc["b", "endpoint_usd"], 98.0)
        self.assertAlmostEqual(realised.loc["k1", "usd"], 59.5)
        self.assertAlmostEqual(realised.loc["k2", "usd"], 39.5)

    def test_ordered_round_trip_is_removed_when_roles_have_no_endpoints(self) -> None:
        rows = [
            leg("good", 0, "a", "k", "source", "intermediate", 100),
            leg("good", 0, "k", "b", "intermediate", "sink", 100),
            leg(
                "cycle",
                0,
                "a",
                "k",
                "intermediate",
                "intermediate",
                1000,
                log_index=0,
            ),
            leg(
                "cycle",
                0,
                "k",
                "a",
                "intermediate",
                "intermediate",
                1000,
                log_index=1,
            ),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows))
        self.assertTrue((out["routes_cyclic_excluded"] == 1).all())
        self.assertAlmostEqual(
            out.set_index("token").loc["k", "intermediate_usd"], 100
        )

    def test_log_order_does_not_override_unique_economic_endpoints(self) -> None:
        rows = [
            leg("interleaved", 0, "x", "y", "intermediate", "intermediate", 100, log_index=0),
            leg("interleaved", 0, "y", "b", "intermediate", "sink", 100, log_index=1),
            leg("interleaved", 0, "a", "x", "source", "intermediate", 100, log_index=2),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows))
        self.assertFalse(out.empty)
        self.assertTrue((out["routes_clean"] == 1).all())
        self.assertTrue((out["routes_cyclic_excluded"] == 0).all())
        self.assertTrue((out["routes_ambiguous_excluded"] == 0).all())

    def test_economic_path_with_internal_cycle_is_excluded(self) -> None:
        rows = [
            leg("good", 0, "a", "k", "source", "intermediate", 100, log_index=0),
            leg("good", 0, "k", "b", "intermediate", "sink", 100, log_index=1),
            leg("cycle-tail", 0, "a", "k", "source", "intermediate", 1_000, log_index=0),
            leg("cycle-tail", 0, "k", "m", "intermediate", "intermediate", 1_000, log_index=1),
            leg("cycle-tail", 0, "m", "k", "intermediate", "intermediate", 1_000, log_index=2),
            leg("cycle-tail", 0, "k", "b", "intermediate", "sink", 1_000, log_index=3),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows))
        self.assertTrue((out["routes_cyclic_excluded"] == 1).all())
        self.assertAlmostEqual(out.set_index("token").loc["k", "intermediate_usd"], 100)

    def test_native_eth_is_canonicalised_to_weth(self) -> None:
        zero = "0x0000000000000000000000000000000000000000"
        rows = [
            leg("r1", 0, "a", zero, "source", "intermediate", 100),
            leg("r1", 0, zero, "b", "intermediate", "sink", 100),
            leg("r2", 0, WETH, "x", "source", "sink", 100, "single"),
        ]
        out = compute_vehicle_extent(pd.DataFrame(rows)).set_index("token")
        self.assertIn(WETH, out.index)
        self.assertNotIn(zero, out.index)
        self.assertAlmostEqual(
            out.loc[WETH, "vehicle_excess_use_ratio"], 4.0
        )

    def test_venue_restriction_keeps_only_complete_components(self) -> None:
        rows = [
            {**leg("kept", 0, "a", "k", "source", "intermediate", 100), "source": "v2"},
            {**leg("kept", 0, "k", "b", "intermediate", "sink", 100), "source": "v2"},
            {**leg("mixed", 0, "a", "k", "source", "intermediate", 100), "source": "v2"},
            {**leg("mixed", 0, "k", "b", "intermediate", "sink", 100), "source": "curve"},
        ]
        out = restrict_routes_to_venues(pd.DataFrame(rows), {"v2"})
        self.assertEqual(set(out["tx_hash"]), {"kept"})

    def test_aggregation_normalises_within_each_period_scope(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
                "year": [2025, 2025],
                "scope": ["all", "all"],
                "asset_type": ["native", "stable"],
                "intermediate_usd": [75.0, 25.0],
                "endpoint_usd": [50.0, 50.0],
                "intermediate_routes": [3, 1],
                "endpoint_routes": [2, 2],
            }
        )
        out = aggregate_vehicle_extent(
            frame,
            ["year", "scope", "asset_type"],
            level="asset_type",
            period_keys=["year", "scope"],
        ).set_index("asset_type")
        self.assertAlmostEqual(out.loc["native", "vehicle_excess_use_ratio"], 1.5)
        self.assertAlmostEqual(out.loc["stable", "vehicle_excess_use_count_ratio"], 0.5)

    def test_backing_ratios_are_conditional_on_stable_currencies(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01"] * 3),
                "year": [2025] * 3,
                "asset_type": ["stable", "stable", "native"],
                "backing": ["fiat_reserve", "synthetic", "not_applicable"],
                "intermediate_usd": [75.0, 25.0, 900.0],
                "endpoint_usd": [50.0, 50.0, 100.0],
                "intermediate_routes": [3, 1, 9],
                "endpoint_routes": [2, 2, 1],
            }
        )
        out = stable_backing_year(frame).set_index("backing")
        self.assertEqual(set(out.index), {"fiat_reserve", "synthetic"})
        self.assertTrue(out["scope"].eq("stable_currencies").all())
        self.assertAlmostEqual(out.loc["fiat_reserve", "vehicle_excess_use_ratio"], 1.5)
        self.assertAlmostEqual(out.loc["synthetic", "vehicle_excess_use_count_ratio"], 0.5)

    def test_usdt_transition_nets_out_endpoint_demand(self) -> None:
        rows = []
        for year, usdt_intermediate in ((2024, 20.0), (2025, 30.0), (2026, 40.0)):
            for day in range(4):
                for symbol, asset_type, intermediate, endpoint in (
                    ("USDT", "stable", usdt_intermediate + day, 10.0 + day),
                    ("USDC", "stable", 40.0 - day / 2, 45.0 - day / 2),
                    ("WETH", "native", 60.0 - usdt_intermediate - day / 2, 45.0 - day / 2),
                ):
                    rows.append(
                        {
                            "date": pd.Timestamp(f"{year}-01-{day + 1:02d}"),
                            "symbol": symbol,
                            "asset_type": asset_type,
                            "intermediate_routes": intermediate,
                            "endpoint_routes": endpoint,
                            "intermediate_usd_within_20pct": intermediate,
                            "endpoint_usd_within_20pct": endpoint,
                        }
                    )
        result = token_excess_use_transition_tests(pd.DataFrame(rows), hac_lag=1)
        count_gap = result[
            result["weighting"].eq("episode")
            & result["transformation"].eq("share_gap")
        ].iloc[0]
        self.assertEqual(count_gap["observation_clock"], "daily")
        self.assertGreater(count_gap["comparison_period_mean"], count_gap["baseline_period_mean"])
        self.assertGreater(count_gap["change"], 0.15)
        value_log_ratio = result[
            result["weighting"].eq("value")
            & result["transformation"].eq("log_excess_ratio")
        ].iloc[0]
        self.assertGreater(value_log_ratio["change"], 0.5)
        self.assertEqual(count_gap["share_perimeter"], "prespecified_currency_types")

    def test_usdt_transition_runs_every_complete_week_anchor(self) -> None:
        rows = []
        for year, usdt_intermediate in ((2024, 20.0), (2025, 30.0), (2026, 40.0)):
            for day in range(1, 29):
                for symbol, asset_type, intermediate, endpoint in (
                    ("USDT", "stable", usdt_intermediate, 10.0),
                    ("USDC", "stable", 40.0, 45.0),
                    ("WETH", "native", 40.0, 45.0),
                ):
                    rows.append(
                        {
                            "date": pd.Timestamp(year, 1, 1) + pd.Timedelta(days=day - 1),
                            "symbol": symbol,
                            "asset_type": asset_type,
                            "intermediate_routes": intermediate,
                            "endpoint_routes": endpoint,
                            "intermediate_usd_within_20pct": intermediate,
                            "endpoint_usd_within_20pct": endpoint,
                        }
                    )
        result = token_excess_use_transition_tests(pd.DataFrame(rows), hac_lag=1)
        weekly = result[result["observation_clock"].eq("weekly")]
        self.assertEqual(set(weekly["anchor_offset_days"]), set(range(7)))
        self.assertTrue(weekly["period_days"].eq(7).all())
        self.assertEqual(weekly.groupby("anchor_offset_days").size().to_dict(), {anchor: 4 for anchor in range(7)})


if __name__ == "__main__":
    unittest.main()
