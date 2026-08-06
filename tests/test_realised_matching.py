from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import WETH
from ddvc.realised import (
    cost_panel_days,
    extract_linear_realised_routes,
    extract_realised_routes,
    match_observed_reach_path_efficiency,
    match_realised_to_cost_panel,
    match_within_vehicle_search_efficiency,
    read_cost_panel_day,
    read_search_cost_panel_day,
)
from scripts.measure_realised_dominance import (
    choice_regime_rival_tests,
    pool_summaries,
    summarise_matches,
)


def leg(
    tx: str,
    log_index: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    *,
    timestamp: int = 7 * 3600,
    usd: float = 4_000.0,
    amount_in: float | None = None,
    amount_out: float | None = None,
    source: str | None = None,
    component_id: int = 0,
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": component_id,
        "source": source or ("v2" if log_index == 0 else "v3"),
        "token_in": token_in.lower(),
        "token_out": token_out.lower(),
        "token_in_sym": token_in.upper(),
        "token_out_sym": token_out.upper(),
        "amount_in": usd if amount_in is None else amount_in,
        "amount_out": usd if amount_out is None else amount_out,
        "amount_usd": usd,
        "log_index": log_index,
        "route_class": "coherent",
        "tin_role": tin_role,
        "tout_role": tout_role,
        "timestamp_utc": timestamp,
    }


def search_panel(rows: object) -> pd.DataFrame:
    """Build synthetic search cells with explicit executable-path identities."""
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    for prefix in ("direct", "hop1", "hop2"):
        source = f"{prefix}_source"
        pool = f"{prefix}_pool"
        if source in frame and pool not in frame:
            frame[pool] = frame[source].map(
                lambda value: f"{value}-{prefix}-pool" if pd.notna(value) else None
            )
    return frame


class RealisedMatchingTests(unittest.TestCase):
    def test_linear_extraction_values_execution_and_preserves_venue_reach(self) -> None:
        legs = []
        for index in range(3):
            legs.extend(
                [
                    leg(
                        f"linear-{index}",
                        0,
                        "A",
                        "K",
                        "source",
                        "intermediate",
                        usd=1_000.0,
                        amount_in=1_000.0,
                        amount_out=995.0,
                        source="uniswap_v3",
                    ),
                    leg(
                        f"linear-{index}",
                        1,
                        "K",
                        "B",
                        "intermediate",
                        "sink",
                        usd=995.0,
                        amount_in=995.0,
                        amount_out=990.0,
                        source="uniswap_v2",
                    ),
                ]
            )
        out = extract_linear_realised_routes(pd.DataFrame(legs))
        self.assertEqual(len(out), 3)
        self.assertTrue((out["input_usd"] - 1_000.0).abs().lt(1e-9).all())
        self.assertTrue((out["output_usd"] - 995.0).abs().lt(1e-9).all())
        self.assertTrue((out["realised_output_rate"] - 0.995).abs().lt(1e-12).all())
        self.assertTrue(out["venue_set"].eq("uniswap_v2|uniswap_v3").all())

    def test_linear_extraction_keeps_route_components_separate_within_transaction(self) -> None:
        legs = pd.DataFrame(
            [
                leg(
                    "multi-route-tx",
                    0,
                    "A",
                    "K",
                    "source",
                    "intermediate",
                    component_id=0,
                ),
                leg(
                    "multi-route-tx",
                    1,
                    "K",
                    "B",
                    "intermediate",
                    "sink",
                    component_id=0,
                ),
                leg(
                    "multi-route-tx",
                    2,
                    "A",
                    "M",
                    "source",
                    "intermediate",
                    component_id=1,
                ),
                leg(
                    "multi-route-tx",
                    3,
                    "M",
                    "B",
                    "intermediate",
                    "sink",
                    component_id=1,
                ),
                leg("price-support", 0, "A", "N", "source", "intermediate"),
                leg("price-support", 1, "N", "B", "intermediate", "sink"),
            ]
        )
        out = extract_linear_realised_routes(legs)
        same_transaction = out[out["tx_hash"].eq("multi-route-tx")]
        self.assertEqual(len(same_transaction), 2)
        self.assertEqual(set(same_transaction["component_id"]), {0, 1})
        self.assertEqual(same_transaction["route_id"].nunique(), 2)

    def test_linear_extraction_excludes_routes_with_more_than_one_intermediary(self) -> None:
        legs = pd.DataFrame(
            [
                leg("long", 0, "A", "K", "source", "intermediate"),
                leg("long", 1, "K", "M", "intermediate", "intermediate"),
                leg("long", 2, "M", "B", "intermediate", "sink"),
            ]
        )
        self.assertTrue(extract_linear_realised_routes(legs).empty)

    def test_extraction_uses_roles_and_preserves_transaction_identity(self) -> None:
        legs = pd.DataFrame(
            [
                leg("tx1", 0, "A", "K", "source", "intermediate"),
                leg("tx1", 1, "K", "B", "intermediate", "sink"),
                leg("tx2", 0, "A", "K", "source", "intermediate"),
                leg("tx2", 1, "K", "B", "intermediate", "sink"),
                leg("cycle", 0, "A", "K", "source", "intermediate"),
                leg("cycle", 1, "K", "A", "intermediate", "sink"),
            ]
        )
        out = extract_realised_routes(legs)
        self.assertEqual(set(out["tx_hash"]), {"tx1", "tx2"})
        self.assertEqual(out["route_id"].nunique(), 2)
        self.assertTrue(out["hour"].eq(7).all())
        self.assertTrue(out["cross_venue"].all())

    def test_extraction_handles_multiple_intermediaries_and_rejects_ambiguous_endpoints(self) -> None:
        legs = pd.DataFrame(
            [
                leg("long", 0, "A", "K", "source", "intermediate"),
                leg("long", 1, "K", "M", "intermediate", "intermediate"),
                leg("long", 2, "M", "B", "intermediate", "sink"),
                leg("ambiguous", 0, "A", "K", "source", "intermediate"),
                leg("ambiguous", 1, "C", "K", "source", "intermediate"),
                leg("ambiguous", 2, "K", "B", "intermediate", "sink"),
            ]
        )
        out = extract_realised_routes(legs)
        self.assertEqual(set(out["tx_hash"]), {"long"})
        self.assertEqual(set(out["vehicle"]), {"k", "m"})
        self.assertTrue(out["legs"].eq(3).all())

    def test_extraction_assigns_each_intermediary_its_own_adjacent_value(self) -> None:
        out = extract_realised_routes(
            pd.DataFrame(
                [
                    leg("long", 0, "A", "K", "source", "intermediate", usd=100.0),
                    leg("long", 1, "K", "M", "intermediate", "intermediate", usd=110.0),
                    leg("long", 2, "M", "B", "intermediate", "sink", usd=10_000.0),
                ]
            )
        ).set_index("vehicle")
        self.assertAlmostEqual(out.loc["k", "usd"], 105.0)
        self.assertAlmostEqual(out.loc["m", "usd"], 5_055.0)

    def test_extraction_unifies_native_eth_with_wrapped_native(self) -> None:
        native_eth = "0x0000000000000000000000000000000000000000"
        out = extract_realised_routes(
            pd.DataFrame(
                [
                    leg("native", 0, "A", native_eth, "source", "intermediate"),
                    leg("native", 1, native_eth, "B", "intermediate", "sink"),
                ]
            )
        )
        self.assertEqual(out.iloc[0]["vehicle"], WETH)

    def test_match_is_exact_hour_and_uses_log_nearest_size(self) -> None:
        routes = extract_realised_routes(
            pd.DataFrame(
                [
                    leg("tx1", 0, "A", "K", "source", "intermediate"),
                    leg("tx1", 1, "K", "B", "intermediate", "sink"),
                ]
            )
        )
        routes.insert(0, "day", "20250101")
        panel = pd.DataFrame(
            [
                {
                    "date": "2025-01-01",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": size,
                    "direct_available": True,
                    "vehicle_available": True,
                    "direct_cost_advantage": 0.02,
                }
                for size in (1_000.0, 10_000.0)
            ]
        )
        matched = match_realised_to_cost_panel(routes, panel)
        self.assertEqual(float(matched.iloc[0]["trade_size_usd"]), 10_000.0)
        self.assertEqual(matched.iloc[0]["match_status"], "chosen_with_direct")
        self.assertTrue(bool(matched.iloc[0]["dominated"]))
        panel["reserve_hour_utc"] = 8
        unmatched = match_realised_to_cost_panel(routes, panel)
        self.assertEqual(unmatched.iloc[0]["match_status"], "no_cost_cell")

    def test_match_separates_forced_routes(self) -> None:
        routes = extract_realised_routes(
            pd.DataFrame(
                [
                    leg("tx1", 0, "A", "K", "source", "intermediate"),
                    leg("tx1", 1, "K", "B", "intermediate", "sink"),
                ]
            )
        )
        routes.insert(0, "day", "20250101")
        panel = pd.DataFrame(
            [
                {
                    "date": "2025-01-01",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": 5_000.0,
                    "direct_available": False,
                    "vehicle_available": True,
                    "direct_cost_advantage": None,
                }
            ]
        )
        matched = match_realised_to_cost_panel(routes, panel)
        self.assertEqual(matched.iloc[0]["match_status"], "forced_no_direct")
        self.assertTrue(pd.isna(matched.iloc[0]["dominated"]))

    def test_duplicate_cost_cells_are_rejected(self) -> None:
        routes = extract_realised_routes(
            pd.DataFrame(
                [
                    leg("tx1", 0, "A", "K", "source", "intermediate"),
                    leg("tx1", 1, "K", "B", "intermediate", "sink"),
                ]
            )
        )
        routes.insert(0, "day", "20250101")
        row = {
            "date": "2025-01-01",
            "reserve_hour_utc": 7,
            "src": "a",
            "tgt": "b",
            "vehicle": "k",
            "trade_size_usd": 5_000.0,
            "direct_available": True,
            "vehicle_available": True,
            "direct_cost_advantage": 0.0,
        }
        with self.assertRaisesRegex(ValueError, "duplicate quote cells"):
            match_realised_to_cost_panel(routes, pd.DataFrame([row, row]))

    def test_cost_panel_reader_materialises_only_requested_day(self) -> None:
        import duckdb

        rows = search_panel(
            [
                {
                    "date": day,
                    "reserve_hour_utc": 7,
                    "src": "A",
                    "tgt": "B",
                    "vehicle": "K",
                    "trade_size_usd": 5_000.0,
                    "direct_available": True,
                    "vehicle_available": True,
                    "direct_cost_advantage": 0.0,
                }
                for day in ("2025-01-01", "2025-01-02")
            ]
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cost.parquet"
            rows.to_parquet(path, index=False)
            connection = duckdb.connect()
            self.assertEqual(cost_panel_days(connection, path), ["20250101", "20250102"])
            day = read_cost_panel_day(connection, path, "20250102")
            connection.close()
        self.assertEqual(len(day), 1)
        self.assertEqual(str(day.iloc[0]["date"]), "2025-01-02 00:00:00")

    def test_search_cost_panel_reader_materialises_frontier_columns(self) -> None:
        import duckdb

        rows = search_panel(
            [
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": 1_000.0,
                    "direct_available": True,
                    "direct_output_usd": 980.0,
                    "direct_source": "uniswap_v2",
                    "vehicle_available": True,
                    "vehicle_output_usd": 990.0,
                    "hop1_source": "uniswap_v2",
                    "hop2_source": "uniswap_v3",
                }
            ]
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cost.parquet"
            rows.to_parquet(path, index=False)
            connection = duckdb.connect()
            day = read_search_cost_panel_day(connection, path, "20250102")
            connection.close()
        self.assertEqual(len(day), 1)
        self.assertEqual(float(day.iloc[0]["vehicle_output_usd"]), 990.0)
        self.assertEqual(day.iloc[0]["direct_pool"], "uniswap_v2-direct-pool")

    def test_search_efficiency_interpolates_log_size_inside_observed_reach(self) -> None:
        routes = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 10 ** 3.5,
                    "output_usd": 0.90 * 10 ** 3.5,
                    "realised_output_rate": 0.90,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v3",
                }
            ]
        )
        panel = search_panel(
            [
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": size,
                    "vehicle_available": True,
                    "vehicle_output_usd": rate * size,
                    "hop1_source": "uniswap_v2",
                    "hop2_source": "uniswap_v3",
                }
                for size, rate in ((1_000.0, 0.98), (10_000.0, 0.90))
            ]
        )
        out = match_within_vehicle_search_efficiency(routes, panel).iloc[0]
        self.assertEqual(out["search_match_status"], "within_observed_venue_reach")
        self.assertFalse(bool(out["search_frontier_path_switch"]))
        self.assertAlmostEqual(float(out["interpolated_frontier_output_rate"]), 0.94)
        self.assertAlmostEqual(float(out["search_shortfall"]), 1.0 - 0.90 / 0.94)
        self.assertAlmostEqual(float(out["lower_size_ratio"]), 10 ** -0.5)
        self.assertAlmostEqual(float(out["upper_size_ratio"]), 10 ** 0.5)

    def test_search_efficiency_quarantines_a_same_vehicle_path_switch(self) -> None:
        routes = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 10**3.5,
                    "output_usd": 0.90 * 10**3.5,
                    "realised_output_rate": 0.90,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v3",
                }
            ]
        )
        panel = search_panel(
            [
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": size,
                    "vehicle_available": True,
                    "vehicle_output_usd": rate * size,
                    "hop1_source": "uniswap_v2",
                    "hop1_pool": hop1,
                    "hop2_source": "uniswap_v3",
                    "hop2_pool": hop2,
                }
                for size, rate, hop1, hop2 in (
                    (1_000.0, 0.98, "pool-a1", "pool-k1"),
                    (10_000.0, 0.90, "pool-a2", "pool-k2"),
                )
            ]
        )
        out = match_within_vehicle_search_efficiency(routes, panel).iloc[0]
        self.assertEqual(
            out["search_match_status"],
            "frontier_switches_between_quote_sizes",
        )
        self.assertTrue(bool(out["search_frontier_path_switch"]))
        self.assertTrue(pd.isna(out["search_shortfall"]))

    def test_search_efficiency_separates_support_failures(self) -> None:
        base = {
            "day": "20250102",
            "hour": 7,
            "src": "a",
            "tgt": "b",
            "vehicle": "k",
            "output_usd": 900.0,
            "realised_output_rate": 0.90,
            "realised_hop1_source": "uniswap_v2",
            "realised_hop2_source": "uniswap_v3",
        }
        routes = pd.DataFrame(
            [
                {**base, "route_id": "outside-reach", "input_usd": 3_000.0},
                {**base, "route_id": "outside-grid", "input_usd": 100.0},
                {**base, "route_id": "no-cell", "day": "20250103", "input_usd": 3_000.0},
                {**base, "route_id": "unsupported", "vehicle": "m", "input_usd": 3_000.0},
            ]
        )
        panel_rows = []
        for vehicle, available, source in (
            ("k", True, "curve"),
            ("m", False, "uniswap_v2"),
        ):
            for size in (1_000.0, 10_000.0):
                panel_rows.append(
                    {
                        "date": "2025-01-02",
                        "reserve_hour_utc": 7,
                        "src": "a",
                        "tgt": "b",
                        "vehicle": vehicle,
                        "trade_size_usd": size,
                        "vehicle_available": available,
                        "vehicle_output_usd": 0.0 if not available else 0.95 * size,
                        "hop1_source": source,
                        "hop2_source": source,
                    }
                )
        out = match_within_vehicle_search_efficiency(routes, search_panel(panel_rows)).set_index(
            "route_id"
        )
        self.assertEqual(out.loc["outside-reach", "search_match_status"], "frontier_outside_observed_venue_reach")
        self.assertEqual(out.loc["outside-grid", "search_match_status"], "outside_quote_size_grid")
        self.assertEqual(out.loc["no-cell", "search_match_status"], "no_cost_cell")
        self.assertEqual(out.loc["unsupported", "search_match_status"], "vehicle_frontier_unsupported")
        self.assertTrue(pd.isna(out.loc["outside-reach", "search_shortfall"]))

    def test_search_efficiency_rejects_duplicate_cost_cells(self) -> None:
        route = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 1_000.0,
                    "output_usd": 990.0,
                    "realised_output_rate": 0.99,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v2",
                }
            ]
        )
        row = {
            "date": "2025-01-02",
            "reserve_hour_utc": 7,
            "src": "a",
            "tgt": "b",
            "vehicle": "k",
            "trade_size_usd": 1_000.0,
            "vehicle_available": True,
            "vehicle_output_usd": 990.0,
            "hop1_source": "uniswap_v2",
            "hop2_source": "uniswap_v2",
        }
        with self.assertRaisesRegex(ValueError, "duplicate quote cells"):
            match_within_vehicle_search_efficiency(route, search_panel([row, row]))

    def test_path_efficiency_quarantines_a_frontier_path_switch(self) -> None:
        route = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 10 ** 3.5,
                    "output_usd": 0.90 * 10 ** 3.5,
                    "realised_output_rate": 0.90,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v3",
                }
            ]
        )
        rows = []
        for size, direct_rate, alternative_rate in (
            (1_000.0, 0.96, 0.97),
            (10_000.0, 0.94, 0.93),
        ):
            for vehicle, rate, source in (
                ("k", 0.92, "uniswap_v2"),
                ("m", alternative_rate, "uniswap_v3"),
                ("n", 0.99, "curve"),
            ):
                rows.append(
                    {
                        "date": "2025-01-02",
                        "reserve_hour_utc": 7,
                        "src": "a",
                        "tgt": "b",
                        "vehicle": vehicle,
                        "trade_size_usd": size,
                        "direct_available": True,
                        "direct_output_usd": direct_rate * size,
                        "direct_source": "uniswap_v2",
                        "vehicle_available": True,
                        "vehicle_output_usd": rate * size,
                        "hop1_source": source,
                        "hop2_source": source,
                    }
                )
        out = match_observed_reach_path_efficiency(route, search_panel(rows)).iloc[0]
        self.assertEqual(
            out["path_match_status"], "frontier_switches_between_quote_sizes"
        )
        self.assertTrue(bool(out["path_frontier_switch"]))
        self.assertEqual(out["lower_frontier_vehicle"], "m")
        self.assertEqual(out["upper_frontier_path_type"], "direct")
        self.assertAlmostEqual(
            float(out["interpolated_path_frontier_output_rate"]), 0.955
        )
        self.assertTrue(pd.isna(out["path_shortfall"]))

    def test_path_efficiency_interpolates_only_when_the_frontier_path_is_stable(self) -> None:
        route = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 10**3.5,
                    "output_usd": 0.90 * 10**3.5,
                    "realised_output_rate": 0.90,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v3",
                }
            ]
        )
        rows = []
        for size, direct_rate, alternative_rate in (
            (1_000.0, 0.96, 0.97),
            (10_000.0, 0.94, 0.95),
        ):
            for vehicle, rate, source in (
                ("k", 0.92, "uniswap_v2"),
                ("m", alternative_rate, "uniswap_v3"),
            ):
                rows.append(
                    {
                        "date": "2025-01-02",
                        "reserve_hour_utc": 7,
                        "src": "a",
                        "tgt": "b",
                        "vehicle": vehicle,
                        "trade_size_usd": size,
                        "direct_available": True,
                        "direct_output_usd": direct_rate * size,
                        "direct_source": "uniswap_v2",
                        "vehicle_available": True,
                        "vehicle_output_usd": rate * size,
                        "hop1_source": source,
                        "hop2_source": source,
                    }
                )
        out = match_observed_reach_path_efficiency(route, search_panel(rows)).iloc[0]
        self.assertEqual(out["path_match_status"], "within_observed_venue_reach")
        self.assertFalse(bool(out["path_frontier_switch"]))
        self.assertEqual(out["lower_frontier_vehicle"], "m")
        self.assertEqual(out["upper_frontier_vehicle"], "m")
        self.assertAlmostEqual(
            float(out["interpolated_path_frontier_output_rate"]), 0.96
        )
        self.assertAlmostEqual(float(out["path_shortfall"]), 1.0 - 0.90 / 0.96)

    def test_path_efficiency_rejects_inconsistent_direct_frontier(self) -> None:
        route = pd.DataFrame(
            [
                {
                    "route_id": "r1",
                    "day": "20250102",
                    "hour": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "input_usd": 1_000.0,
                    "output_usd": 990.0,
                    "realised_output_rate": 0.99,
                    "realised_hop1_source": "uniswap_v2",
                    "realised_hop2_source": "uniswap_v2",
                }
            ]
        )
        rows = []
        for vehicle, direct_output in (("k", 990.0), ("m", 980.0)):
            rows.append(
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": vehicle,
                    "trade_size_usd": 1_000.0,
                    "direct_available": True,
                    "direct_output_usd": direct_output,
                    "direct_source": "uniswap_v2",
                    "vehicle_available": True,
                    "vehicle_output_usd": 980.0,
                    "hop1_source": "uniswap_v2",
                    "hop2_source": "uniswap_v2",
                }
            )
        with self.assertRaisesRegex(ValueError, "direct frontier differs"):
            match_observed_reach_path_efficiency(route, search_panel(rows))

    def test_path_efficiency_separates_grid_reach_and_missing_cells(self) -> None:
        base = {
            "hour": 7,
            "src": "a",
            "tgt": "b",
            "vehicle": "k",
            "output_usd": 900.0,
            "realised_output_rate": 0.90,
            "realised_hop1_source": "uniswap_v2",
            "realised_hop2_source": "uniswap_v2",
        }
        routes = pd.DataFrame(
            [
                {**base, "route_id": "outside-grid", "day": "20250102", "input_usd": 100.0},
                {**base, "route_id": "outside-reach", "day": "20250102", "input_usd": 3_000.0},
                {**base, "route_id": "no-cell", "day": "20250103", "input_usd": 3_000.0},
            ]
        )
        rows = []
        for size in (1_000.0, 10_000.0):
            rows.append(
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": size,
                    "direct_available": True,
                    "direct_output_usd": 0.98 * size,
                    "direct_source": "curve",
                    "vehicle_available": True,
                    "vehicle_output_usd": 0.97 * size,
                    "hop1_source": "curve",
                    "hop2_source": "curve",
                }
            )
        out = match_observed_reach_path_efficiency(routes, search_panel(rows)).set_index(
            "route_id"
        )
        self.assertEqual(out.loc["outside-grid", "path_match_status"], "outside_quote_size_grid")
        self.assertEqual(out.loc["outside-reach", "path_match_status"], "frontier_unsupported_within_observed_reach")
        self.assertEqual(out.loc["no-cell", "path_match_status"], "no_cost_cell")

    def test_summary_keeps_forced_routes_out_of_dominance_denominator(self) -> None:
        matches = pd.DataFrame(
            [
                {
                    "route_id": "chosen-1",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "quoted_to_realised_size": 1.0,
                    "match_status": "chosen_with_direct",
                    "usd": 100.0,
                    "dominated": True,
                    "within_2x": True,
                    "within_20pct": True,
                },
                {
                    "route_id": "chosen-2",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "quoted_to_realised_size": 1.0,
                    "match_status": "chosen_with_direct",
                    "usd": 300.0,
                    "dominated": False,
                    "within_2x": True,
                    "within_20pct": True,
                },
                {
                    "route_id": "forced",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "quoted_to_realised_size": 1.0,
                    "match_status": "forced_no_direct",
                    "usd": 900.0,
                    "dominated": pd.NA,
                    "within_2x": True,
                    "within_20pct": True,
                },
            ]
        )
        pooled = pool_summaries(summarise_matches(matches, "20250101"), "ALL")
        chosen = pooled[pooled["match_status"].eq("chosen_with_direct")].iloc[0]
        forced = pooled[pooled["match_status"].eq("forced_no_direct")].iloc[0]
        self.assertEqual(chosen["dominated_share"], 0.5)
        self.assertEqual(chosen["dominated_usd_share"], 0.25)
        self.assertTrue(pd.isna(forced["dominated_share"]))

    def test_summary_reports_nested_notional_support(self) -> None:
        matches = pd.DataFrame(
            [
                {
                    "route_id": "close",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "quoted_to_realised_size": 1.1,
                    "match_status": "chosen_with_direct",
                    "dominated": True,
                    "usd": 100.0,
                    "within_2x": True,
                    "within_20pct": True,
                },
                {
                    "route_id": "far",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "quoted_to_realised_size": 3.0,
                    "match_status": "chosen_with_direct",
                    "dominated": False,
                    "usd": 100.0,
                    "within_2x": False,
                    "within_20pct": False,
                },
            ]
        )
        pooled = pool_summaries(summarise_matches(matches, "20250101"), "ALL")
        by_scope = pooled.set_index(["size_scope", "value_support"])
        self.assertEqual(by_scope.loc[("all_routes", "all_routes"), "routes"], 2)
        self.assertEqual(by_scope.loc[("within_20pct", "all_routes"), "routes"], 1)
        self.assertEqual(by_scope.loc[("all_routes", "within_20pct"), "routes"], 1)
        self.assertEqual(by_scope.loc[("within_20pct", "within_20pct"), "routes"], 1)

    def test_choice_regime_rival_keeps_supported_regimes_separate(self) -> None:
        rows = []
        for year, stable_routes in ((2023, 60.0), (2024, 40.0), (2026, 70.0)):
            for day in range(2):
                for size_scope in ("all_routes", "within_20pct"):
                    for match_status in ("forced_no_direct", "chosen_with_direct"):
                        rows.extend(
                            [
                                {
                                    "period": f"{year}010{day + 1}",
                                    "size_scope": size_scope,
                                    "value_support": "within_20pct",
                                    "mid_type": "stable",
                                    "match_status": match_status,
                                    "routes": stable_routes,
                                    "usd": stable_routes,
                                },
                                {
                                    "period": f"{year}010{day + 1}",
                                    "size_scope": size_scope,
                                    "value_support": "within_20pct",
                                    "mid_type": "native",
                                    "match_status": match_status,
                                    "routes": 100.0 - stable_routes,
                                    "usd": 100.0 - stable_routes,
                                },
                            ]
                        )
        result = choice_regime_rival_tests(pd.DataFrame(rows), hac_lag=1)
        self.assertEqual(set(result["size_scope"]), {"all_routes", "within_20pct"})
        self.assertEqual(set(result["value_support"]), {"within_20pct"})
        self.assertEqual(
            set(zip(result["baseline_year"], result["comparison_year"])),
            {(2023, 2024), (2024, 2026)},
        )
        self.assertEqual(set(result["match_status"]), {"forced_no_direct", "chosen_with_direct"})


if __name__ == "__main__":
    unittest.main()
