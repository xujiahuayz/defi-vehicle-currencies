from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import STABLE, WETH
from scripts.build_intermediation_by_type import (
    annual_composition,
    bounded_workers,
    integration_rival_tests,
    one_day,
)

USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")


def leg(
    tx: str,
    source: str,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    log_index: int,
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": 100.0,
        "log_index": log_index,
        "route_class": "coherent",
        "tin_role": tin_role,
        "tout_role": tout_role,
        "timestamp_utc": 1_700_000_000,
    }


class IntermediationByTypeTests(unittest.TestCase):
    def test_route_type_composition_is_split_by_cross_venue_status(self) -> None:
        rows = [
            leg("native", "v2", "A", WETH, "source", "intermediate", 0),
            leg("native", "v2", WETH, "B", "intermediate", "sink", 1),
            leg("stable", "v2", "A", USDC, "source", "intermediate", 0),
            leg("stable", "v3", USDC, "B", "intermediate", "sink", 1),
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        self.assertEqual(result["routes_intermediated"], 2)
        self.assertEqual(result["cnt_single_venue_native"], 1)
        self.assertEqual(result["cnt_cross_venue_stable"], 1)
        annual = annual_composition(pd.DataFrame([result]))
        single_native = annual[
            annual["integration_scope"].eq("single_venue")
            & annual["asset_type"].eq("native")
        ].iloc[0]
        cross_stable = annual[
            annual["integration_scope"].eq("cross_venue")
            & annual["asset_type"].eq("stable")
        ].iloc[0]
        self.assertEqual(single_native["episode_share"], 1.0)
        self.assertEqual(cross_stable["episode_share"], 1.0)

    def test_workers_are_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)

    def test_integration_rival_keeps_count_and_value_results_separate(self) -> None:
        rows = []
        for year, stable_count, stable_value in (
            (2024, 20.0, 40.0),
            (2025, 40.0, 45.0),
            (2026, 60.0, 42.0),
        ):
            for day in range(4):
                row: dict[str, object] = {"date": f"{year}-01-{day + 1:02d}"}
                for scope in ("", "single_venue_", "cross_venue_"):
                    row[f"cnt_{scope}stable"] = stable_count + day
                    row[f"cnt_{scope}native"] = 100.0 - stable_count
                    row[f"usd_{scope}stable"] = stable_value + day
                    row[f"usd_{scope}native"] = 100.0 - stable_value
                rows.append(row)
        result = integration_rival_tests(pd.DataFrame(rows), hac_lag=1)
        self.assertEqual(set(result["weighting"]), {"episode", "value"})
        single_episode = result[
            result["integration_scope"].eq("single_venue")
            & result["weighting"].eq("episode")
        ].iloc[0]
        single_value = result[
            result["integration_scope"].eq("single_venue")
            & result["weighting"].eq("value")
        ].iloc[0]
        self.assertGreater(single_episode["change"], single_value["change"])


if __name__ == "__main__":
    unittest.main()
