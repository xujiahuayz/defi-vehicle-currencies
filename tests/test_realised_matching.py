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
    match_realised_to_cost_panel,
    match_within_vehicle_search_efficiency,
    read_cost_panel_day,
    read_search_cost_panel_day,
)
from scripts.measure_realised_dominance import pool_summaries, summarise_matches


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
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
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

        rows = pd.DataFrame(
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

        rows = pd.DataFrame(
            [
                {
                    "date": "2025-01-02",
                    "reserve_hour_utc": 7,
                    "src": "a",
                    "tgt": "b",
                    "vehicle": "k",
                    "trade_size_usd": 1_000.0,
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
        panel = pd.DataFrame(
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
        self.assertAlmostEqual(float(out["frontier_output_rate"]), 0.94)
        self.assertAlmostEqual(float(out["search_shortfall"]), 1.0 - 0.90 / 0.94)
        self.assertAlmostEqual(float(out["lower_size_ratio"]), 10 ** -0.5)
        self.assertAlmostEqual(float(out["upper_size_ratio"]), 10 ** 0.5)

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
        out = match_within_vehicle_search_efficiency(routes, pd.DataFrame(panel_rows)).set_index(
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
            match_within_vehicle_search_efficiency(route, pd.DataFrame([row, row]))

    def test_summary_keeps_forced_routes_out_of_dominance_denominator(self) -> None:
        matches = pd.DataFrame(
            [
                {
                    "route_id": "chosen-1",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "match_status": "chosen_with_direct",
                    "usd": 100.0,
                    "dominated": True,
                },
                {
                    "route_id": "chosen-2",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "match_status": "chosen_with_direct",
                    "usd": 300.0,
                    "dominated": False,
                },
                {
                    "route_id": "forced",
                    "vehicle": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "match_status": "forced_no_direct",
                    "usd": 900.0,
                    "dominated": pd.NA,
                },
            ]
        )
        pooled = pool_summaries(summarise_matches(matches, "20250101"), "ALL")
        chosen = pooled[pooled["match_status"].eq("chosen_with_direct")].iloc[0]
        forced = pooled[pooled["match_status"].eq("forced_no_direct")].iloc[0]
        self.assertEqual(chosen["dominated_share"], 0.5)
        self.assertEqual(chosen["dominated_usd_share"], 0.25)
        self.assertTrue(pd.isna(forced["dominated_share"]))


if __name__ == "__main__":
    unittest.main()
