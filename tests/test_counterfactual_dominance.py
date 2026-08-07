from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.build_counterfactual_dominance import (
    add_topology_gas_adjustment,
    classify_state_support,
    counterfactual_days,
    dominance_level_summary,
)


class CounterfactualDominanceTests(unittest.TestCase):
    def test_level_summary_keeps_weighting_uncertainty_and_dollars(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2024-01-15", "2024-01-15", "2024-02-15", "2024-02-15"]
                ),
                "gross_direct_advantage_bps": [100.0, -100.0, 200.0, -200.0],
                "dominated_gross": [True, False, True, False],
                "all_in_direct_advantage_bps_iqr_lower": [25.0, -25.0, 25.0, -25.0],
                "all_in_direct_advantage_bps": [50.0, -50.0, 50.0, -50.0],
                "all_in_direct_advantage_bps_iqr_upper": [75.0, -75.0, 75.0, -75.0],
                "valuation_coherent_20pct": [True, True, True, True],
                "usd": [1_000.0, 1_000.0, 1_000.0, 1_000.0],
            }
        )

        summary = dominance_level_summary(frame)
        gross = summary[
            summary["economic_object"].eq("gross_output")
            & summary["value_support"].eq("all_routes")
            & summary["weighting"].eq("route")
        ].iloc[0]
        self.assertEqual(gross["routes"], 4)
        self.assertEqual(gross["dominated_routes"], 2)
        self.assertAlmostEqual(gross["pct_dominated"], 50.0)
        self.assertAlmostEqual(gross["aggregate_savings_usd_sampled_dates"], 30.0)
        self.assertAlmostEqual(gross["top_1pct_savings_share_pct"], 2 / 3 * 100)
        self.assertAlmostEqual(
            gross["pct_dominated_routes_below_1000_usd_notional"], 0.0
        )
        self.assertIn("confidence_interval_95_lower_pct", summary.columns)

    def test_gas_adjustment_uses_route_cells_and_reports_iqr_sensitivity(self) -> None:
        frame = pd.DataFrame(
            {
                "date": [pd.Timestamp("2025-01-15")],
                "direct_source": ["uniswap_v2"],
                "hop1_source": ["uniswap_v2"],
                "hop2_source": ["uniswap_v2"],
                "mid": ["stable-token"],
                "mid_type": ["stable"],
                "gross_direct_advantage_bps": [10.0],
                "usd": [1_000.0],
                "eth_usd": [2_000.0],
            }
        )
        receipt_panel = pd.DataFrame(
            {
                "year": [2025] * 4,
                "legs": [1, 1, 2, 2],
                "venue_sequence": [
                    "uniswap_v2",
                    "uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                ],
                "gas_vehicle": ["direct", "direct", "stable-token", "stable-token"],
                "mid_type": ["direct", "direct", "stable", "stable"],
                "gas_used": [100_000, 120_000, 200_000, 240_000],
                "status": [1, 1, 1, 1],
            }
        )
        with TemporaryDirectory() as temporary:
            gas_path = Path(temporary) / "gas.parquet"
            pd.DataFrame(
                {"date": [pd.Timestamp("2025-01-15")], "gas_gwei_median": [10.0]}
            ).to_parquet(gas_path, index=False)
            out = add_topology_gas_adjustment(
                frame,
                gas_panel=gas_path,
                route_gas_panel=receipt_panel,
            )
        self.assertEqual(out.loc[0, "direct_gas_support_level"], "year_venue_vehicle")
        self.assertEqual(out.loc[0, "vehicle_gas_support_level"], "year_venue_vehicle")
        self.assertGreater(
            out.loc[0, "all_in_direct_advantage_bps_iqr_upper"],
            out.loc[0, "all_in_direct_advantage_bps"],
        )
        self.assertGreater(
            out.loc[0, "all_in_direct_advantage_bps"],
            out.loc[0, "all_in_direct_advantage_bps_iqr_lower"],
        )

    def test_default_calendar_is_one_nearest_midmonth_day_per_month(self) -> None:
        available = ["20200101", "20200114", "20200116", "20200202", "20200220"]

        self.assertEqual(counterfactual_days(available), ["20200114", "20200220"])

    def test_explicit_days_preserve_order_and_remove_duplicates_before_limit(self) -> None:
        self.assertEqual(
            counterfactual_days([], explicit=["20220115", "20210115", "20220115"], limit=2),
            ["20220115", "20210115"],
        )

    def test_state_support_distinguishes_adjacent_bridged_and_liquidity_replay(self) -> None:
        frame = pd.DataFrame(
            {
                "hop1_prior_state_gap_hours": [1, 2, 1],
                "hop2_prior_state_gap_hours": [1, 1, 1],
                "direct_prior_state_gap_hours": [1, 1, 1],
                "hop1_liquidity_events_replayed": [0, 0, 0],
                "hop2_liquidity_events_replayed": [0, 0, 1],
                "direct_liquidity_events_replayed": [0, 0, 0],
            }
        )
        self.assertEqual(
            classify_state_support(frame).tolist(),
            [
                "adjacent_no_liquidity",
                "bridged_no_liquidity",
                "liquidity_replayed",
            ],
        )


if __name__ == "__main__":
    unittest.main()
