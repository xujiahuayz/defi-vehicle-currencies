from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.realised import (
    cost_panel_days,
    extract_realised_routes,
    match_realised_to_cost_panel,
    read_cost_panel_day,
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
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": usd,
        "log_index": log_index,
        "route_class": "coherent",
        "tin_role": tin_role,
        "tout_role": tout_role,
        "timestamp_utc": timestamp,
    }


class RealisedMatchingTests(unittest.TestCase):
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
                    "src": "A",
                    "tgt": "B",
                    "vehicle": "K",
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
                    "src": "A",
                    "tgt": "B",
                    "vehicle": "K",
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
            "src": "A",
            "tgt": "B",
            "vehicle": "K",
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
