from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import STABLE, WETH
from scripts.build_intermediation_by_type import (
    annual_composition,
    bounded_workers,
    complexity_rival_tests,
    integration_rival_windows,
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
    usd: float = 100.0,
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": usd,
        "log_index": log_index,
        "route_class": "coherent",
        "tin_role": tin_role,
        "tout_role": tout_role,
        "timestamp_utc": 1_700_000_000,
    }


class IntermediationByTypeTests(unittest.TestCase):
    def test_route_counts_do_not_depend_on_usd_price_support(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(
                [
                    leg(
                        "missing",
                        "v2",
                        "A",
                        USDC,
                        "source",
                        "intermediate",
                        0,
                        float("nan"),
                    ),
                    leg(
                        "missing",
                        "v3",
                        USDC,
                        "B",
                        "intermediate",
                        "sink",
                        1,
                        float("nan"),
                    ),
                ]
            ).to_parquet(path, index=False)
            result = one_day(path)
        self.assertEqual(result["cnt_stable"], 1)
        self.assertEqual(result["usd_stable"], 0.0)
        self.assertEqual(result["usd_within_2x_stable"], 0.0)

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

    def test_route_type_composition_is_split_by_complexity_and_integration(self) -> None:
        rows = [
            leg("two-leg", "v2", "A", USDC, "source", "intermediate", 0),
            leg("two-leg", "v2", USDC, "B", "intermediate", "sink", 1),
            leg("complex", "v2", "A", USDC, "source", "intermediate", 0),
            leg("complex", "v3", USDC, "C", "intermediate", "intermediate", 1),
            leg("complex", "v3", "C", "B", "intermediate", "sink", 2),
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        self.assertEqual(result["cnt_single_venue_two_leg_stable"], 1)
        self.assertEqual(result["cnt_cross_venue_more_than_two_legs_stable"], 1)

    def test_value_composition_keeps_raw_and_nested_coherence_support(self) -> None:
        rows = [
            leg("good", "v2", "A", USDC, "source", "intermediate", 0, 100.0),
            leg("good", "v3", USDC, "B", "intermediate", "sink", 1, 95.0),
            leg("bad", "v2", "A", USDC, "source", "intermediate", 0, 100.0),
            leg("bad", "v3", USDC, "B", "intermediate", "sink", 1, 20.0),
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        self.assertEqual(result["cnt_stable"], 2)
        self.assertEqual(result["usd_stable"], 157.5)
        self.assertEqual(result["usd_within_2x_stable"], 97.5)
        self.assertEqual(result["usd_within_20pct_stable"], 97.5)

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
            & result["transformation"].eq("share_level")
        ].iloc[0]
        single_value = result[
            result["integration_scope"].eq("single_venue")
            & result["weighting"].eq("value")
            & result["transformation"].eq("share_level")
        ].iloc[0]
        self.assertGreater(single_episode["change"], single_value["change"])
        self.assertEqual(set(result["transformation"]), {"share_level", "log_odds"})
        self.assertTrue(result["p_value_holm"].notna().all())

    def test_integration_rival_windows_preserve_both_transition_phases(self) -> None:
        rows = []
        for year, stable_count in ((2023, 60.0), (2024, 40.0), (2026, 70.0)):
            for day in range(2):
                row: dict[str, object] = {"date": f"{year}-01-{day + 1:02d}"}
                for scope in ("", "single_venue_", "cross_venue_"):
                    row[f"cnt_{scope}stable"] = stable_count
                    row[f"cnt_{scope}native"] = 100.0 - stable_count
                    row[f"usd_{scope}stable"] = stable_count
                    row[f"usd_{scope}native"] = 100.0 - stable_count
                rows.append(row)
        result = integration_rival_windows(pd.DataFrame(rows), hac_lag=1)
        self.assertEqual(
            set(zip(result["baseline_year"], result["comparison_year"])),
            {(2023, 2024), (2024, 2026)},
        )
        self.assertEqual(len(result), 24)

    def test_complexity_rival_keeps_combined_route_regimes_separate(self) -> None:
        rows = []
        for year, stable_count in ((2024, 20.0), (2025, 40.0), (2026, 60.0)):
            for day in range(4):
                row: dict[str, object] = {"date": f"{year}-01-{day + 1:02d}"}
                for scope in (
                    "two_leg",
                    "more_than_two_legs",
                    "single_venue_two_leg",
                    "cross_venue_two_leg",
                    "single_venue_more_than_two_legs",
                    "cross_venue_more_than_two_legs",
                ):
                    row[f"cnt_{scope}_stable"] = stable_count + day
                    row[f"cnt_{scope}_native"] = 100.0 - stable_count
                    row[f"usd_{scope}_stable"] = stable_count / 2 + day
                    row[f"usd_{scope}_native"] = 100.0 - stable_count / 2
                rows.append(row)
        result = complexity_rival_tests(pd.DataFrame(rows), hac_lag=1)
        self.assertEqual(result["routing_scope"].nunique(), 6)
        self.assertEqual(set(result["weighting"]), {"episode", "value"})


if __name__ == "__main__":
    unittest.main()
