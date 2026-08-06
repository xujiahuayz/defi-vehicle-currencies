from __future__ import annotations

import unittest

import pandas as pd

from ddvc.asset_types import CURRENCY_TYPES, WETH
from ddvc.vehicle_extent import (
    aggregate_vehicle_extent,
    compute_vehicle_extent,
    restrict_routes_to_venues,
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


if __name__ == "__main__":
    unittest.main()
