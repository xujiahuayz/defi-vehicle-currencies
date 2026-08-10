from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.build_counterfactual_dominance import (
    add_topology_gas_adjustment,
    add_valuation_support,
    classify_state_support,
    common_mark_direct_advantage_bps,
    counterfactual_days,
    dominance_level_summary,
    target_price_usd,
)
from ddvc.prices import attach_strictly_prior_weth_usd


class CounterfactualDominanceTests(unittest.TestCase):
    def test_intraday_weth_mark_is_strictly_prior_and_fresh(self) -> None:
        targets = pd.DataFrame({"timestamp_utc": [1_000, 1_060]})
        marks = pd.DataFrame(
            {
                "available_at_utc": [940, 1_000],
                "weth_usd": [2_000.0, 2_010.0],
                "price_source": ["independent_cex_minute"] * 2,
                "validation_status": ["valid"] * 2,
            }
        )

        result = attach_strictly_prior_weth_usd(targets, marks)

        self.assertEqual(result["eth_usd"].tolist(), [2_000.0, 2_010.0])
        self.assertEqual(result["eth_usd_mark_lag_seconds"].tolist(), [60, 60])
        stale = targets.iloc[[1]].assign(timestamp_utc=1_400)
        with self.assertRaisesRegex(RuntimeError, "strictly prior mark"):
            attach_strictly_prior_weth_usd(stale, marks)

    def test_missing_or_invalid_target_price_is_unsupported_not_a_crash(self) -> None:
        prices = {"good": ("GOOD", 2.0), "zero": ("ZERO", 0.0)}
        self.assertEqual(target_price_usd(prices, "good"), 2.0)
        self.assertIsNone(target_price_usd(prices, "missing"))
        self.assertIsNone(target_price_usd(prices, "zero"))

    def test_dollar_advantage_uses_one_mark_for_both_same_token_outputs(self) -> None:
        advantage = common_mark_direct_advantage_bps(
            Decimal("101"),
            Decimal("100"),
            output_price_usd=2.0,
            input_notional_usd=200.0,
        )
        self.assertEqual(advantage, 100.0)
        self.assertIsNone(
            common_mark_direct_advantage_bps(
                Decimal("101"),
                Decimal("100"),
                output_price_usd=0.0,
                input_notional_usd=200.0,
            )
        )
        self.assertIsNone(
            common_mark_direct_advantage_bps(
                Decimal("101"),
                Decimal("100"),
                output_price_usd=2.0,
                input_notional_usd=float("nan"),
            )
        )

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
                "valuation_coherent_2x": [True, True, True, True],
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
        self.assertEqual(
            set(summary["value_support"]),
            {"all_routes", "within_2x", "within_20pct"},
        )

    def test_valuation_support_requires_route_and_common_mark_coherence(self) -> None:
        frame = pd.DataFrame(
            {
                "component_output_to_input_value_ratio": [1.0, 1.0, 3.0],
                "common_to_component_output_mark_ratio": [1.0, 1.5, 1.0],
            }
        )

        result = add_valuation_support(frame)

        self.assertEqual(result["route_value_coherent_20pct"].tolist(), [True, True, False])
        self.assertEqual(result["common_mark_coherent_20pct"].tolist(), [True, False, True])
        self.assertEqual(result["valuation_coherent_20pct"].tolist(), [True, False, False])
        self.assertEqual(result["valuation_coherent_2x"].tolist(), [True, True, False])

    def test_gas_adjustment_uses_route_cells_and_reports_iqr_sensitivity(self) -> None:
        frame = pd.DataFrame(
            {
                "date": [pd.Timestamp("2025-01-15")],
                "tx": ["0xabc"],
                "block": [21_000_000],
                "direct_source": ["uniswap_v2"],
                "hop1_source": ["uniswap_v2"],
                "hop2_source": ["uniswap_v2"],
                "mid": ["stable-token"],
                "mid_type": ["stable"],
                "gross_direct_advantage_bps": [10.0],
                "usd": [1_000.0],
                "timestamp_utc": [1_700_000_100],
                "eth_usd_daily_sensitivity": [2_000.0],
            }
        )
        intraday_prices = pd.DataFrame(
            {
                "available_at_utc": [1_700_000_040],
                "weth_usd": [2_010.0],
                "price_source": ["independent_cex_minute"],
                "validation_status": ["valid"],
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
                {
                    "tx_hash": ["0xabc"],
                    "block_number": [21_000_000],
                    "block_hash": ["0x" + "ab" * 32],
                    "status": [1],
                    "gas_used": [150_000],
                    "realised_gas_cost_wei": ["1500000000000000"],
                    "effective_gas_price_wei": [10_000_000_000],
                    "gas_gwei": [10.0],
                    "gas_price_supported": [True],
                    "gas_price_support_reason": ["receipt_effective_gas_price"],
                    "base_fee_per_gas_wei": [8_000_000_000],
                    "base_fee_gwei": [8.0],
                    "base_fee_supported": [True],
                    "base_fee_support_reason": ["same_block_base_fee_per_gas"],
                }
            ).to_parquet(gas_path, index=False)
            out = add_topology_gas_adjustment(
                frame,
                gas_panel=gas_path,
                route_gas_panel=receipt_panel,
                intraday_price_panel=intraday_prices,
            )
        self.assertEqual(out.loc[0, "direct_gas_support_level"], "year_venue_vehicle")
        self.assertEqual(out.loc[0, "vehicle_gas_support_level"], "year_venue_vehicle")
        self.assertEqual(out.loc[0, "effective_gas_price_wei"], 10_000_000_000)
        self.assertEqual(out.loc[0, "gas_used"], 150_000)
        self.assertEqual(out.loc[0, "realised_gas_cost_wei"], "1500000000000000")
        self.assertEqual(out.loc[0, "eth_usd"], 2_010.0)
        self.assertEqual(out.loc[0, "eth_usd_mark_lag_seconds"], 60)
        self.assertGreater(
            out.loc[0, "all_in_direct_advantage_bps"],
            out.loc[0, "same_block_base_fee_direct_advantage_bps"],
        )
        self.assertGreater(
            out.loc[0, "all_in_direct_advantage_bps_iqr_upper"],
            out.loc[0, "all_in_direct_advantage_bps"],
        )
        self.assertGreater(
            out.loc[0, "all_in_direct_advantage_bps"],
            out.loc[0, "all_in_direct_advantage_bps_iqr_lower"],
        )

    def test_default_calendar_is_every_available_day(self) -> None:
        available = ["20200101", "20200114", "20200116", "20200202", "20200220"]

        self.assertEqual(counterfactual_days(available), available)

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
