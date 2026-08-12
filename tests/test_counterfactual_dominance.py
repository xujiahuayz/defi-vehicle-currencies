from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from scripts.build_counterfactual_dominance import (
    add_topology_gas_adjustment,
    add_valuation_support,
    classify_state_support,
    common_mark_direct_advantage_bps,
    counterfactual_days,
    dominance_level_summary,
    gross_panel_inputs,
    OUT_RECEIPT_ALLOCATION_SUPPORT,
    receipt_allocation_support,
    receipt_allocation_support_summary,
    state_support_summary,
    target_price_usd,
    _write_gross_release,
)
from ddvc.prices import attach_strictly_prior_weth_usd


class CounterfactualDominanceTests(unittest.TestCase):
    def test_receipt_allocation_support_exposes_multi_component_count_value_and_era(self) -> None:
        routes = pd.DataFrame({"tx_hash": ["0xsingle", "0xmulti", "0xmulti"], "input_usd": [100.0, 200.0, 300.0]})
        unified = pd.DataFrame({"tx_hash": ["0xsingle", "0xmulti", "0xmulti"], "component_id": [0, 0, 1], "n_components": [1, 2, 2]})
        admitted, daily = receipt_allocation_support("20250102", routes, unified)
        self.assertEqual(set(admitted), {"0xsingle"})
        self.assertEqual(daily["excluded_multi_component_transactions"], 1)
        self.assertEqual(daily["excluded_multi_component_routes"], 2)
        self.assertEqual(daily["excluded_multi_component_route_notional_usd"], 500.0)
        summary = receipt_allocation_support_summary(pd.DataFrame([daily]))
        pooled = summary[summary["scope"].eq("pooled")].iloc[0]
        annual = summary[summary["scope"].eq("annual")].iloc[0]
        self.assertEqual(annual["year"], 2025)
        self.assertAlmostEqual(pooled["excluded_multi_component_route_share"], 2 / 3)
        self.assertAlmostEqual(pooled["excluded_multi_component_notional_share"], 5 / 6)
        route_release = SimpleNamespace(provenance_inputs=(Path("route-ledger"),))
        state_release = SimpleNamespace(provenance_inputs=(Path("state-ledger"),))
        self.assertIn(
            OUT_RECEIPT_ALLOCATION_SUPPORT,
            gross_panel_inputs(route_release, {"uniswap_v2": state_release}),
        )

    def test_single_component_transaction_cannot_own_duplicate_gross_routes(self) -> None:
        routes = pd.DataFrame({"tx_hash": ["0xsingle", "0xsingle"], "input_usd": [100.0, 100.0]})
        unified = pd.DataFrame({"tx_hash": ["0xsingle"], "component_id": [0], "n_components": [1]})
        with self.assertRaisesRegex(ValueError, "cannot own multiple gross route rows"):
            receipt_allocation_support("20250102", routes, unified)

    def test_gross_release_rechecks_unique_receipt_ownership_before_write(self) -> None:
        duplicate = pd.DataFrame({"tx": ["0xabc", "0xABC"], "receipt_allocation_scope": ["single_reconstructed_component_transaction"] * 2})
        with patch("scripts.build_counterfactual_dominance.write_panel") as writer, self.assertRaisesRegex(ValueError, "cannot be allocated"):
            _write_gross_release(duplicate)
        writer.assert_not_called()

    def test_canonical_gross_writer_cannot_bypass_registered_owner(self) -> None:
        class CurrentRoute:
            provenance_inputs = (Path("route-ledger"),)
            content_identity_sha256 = "a" * 64

            @staticmethod
            def assert_current() -> None:
                return None

        class CurrentState:
            provenance_inputs = (Path("state-ledger"),)
            content_identity_sha256 = "b" * 64

            @staticmethod
            def assert_current() -> None:
                return None

        frame = pd.DataFrame(
            {
                "tx": ["0xabc"],
                "receipt_allocation_scope": [
                    "single_reconstructed_component_transaction"
                ],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "requires publication capability"):
            _write_gross_release(
                frame,
                route_release=CurrentRoute(),
                state_releases={"uniswap_v2": CurrentState()},
            )

    def test_intraday_weth_mark_is_strictly_prior_and_fresh(self) -> None:
        targets = pd.DataFrame({"timestamp_utc": [1_000, 1_060]})
        marks = pd.DataFrame(
            {
                "bucket_start_utc": [880, 940],
                "bucket_end_utc": [940, 1_000],
                "available_at_utc": [940, 1_000],
                "weth_usd": [2_000.0, 2_010.0],
                "price_source": ["coinbase_exchange_eth_usd_spot_1m_close"] * 2,
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
                "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower": [25.0, -25.0, 25.0, -25.0],
                "daily_denominator_sensitivity_all_in_direct_advantage_bps": [50.0, -50.0, 50.0, -50.0],
                "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper": [75.0, -75.0, 75.0, -75.0],
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
                "timestamp_utc": [1_700_000_099],
                "eth_usd_daily_sensitivity": [2_000.0],
            }
        )
        intraday_prices = pd.DataFrame(
            {
                "bucket_start_utc": [1_699_999_980],
                "bucket_end_utc": [1_700_000_040],
                "available_at_utc": [1_700_000_040],
                "weth_usd": [2_010.0],
                "price_source": ["coinbase_exchange_eth_usd_spot_1m_close"],
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
                    "block_timestamp_utc": [1_700_000_100],
                    "status": [1],
                    "gas_used": [150_000],
                    "execution_gas_cost_wei": ["1500000000000000"],
                    "blob_gas_used": [None],
                    "blob_gas_price_wei": [None],
                    "blob_gas_cost_wei": ["0"],
                    "receipt_total_gas_cost_wei": ["1500000000000000"],
                    "receipt_gas_cost_scope": ["execution_plus_blob_receipt_fields"],
                    "off_receipt_payment_status": ["private_bundle_or_direct_block_beneficiary_payments_unobserved"],
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
        self.assertEqual(out.loc[0, "execution_gas_cost_wei"], "1500000000000000")
        self.assertEqual(out.loc[0, "receipt_total_gas_cost_wei"], "1500000000000000")
        self.assertEqual(out.loc[0, "timestamp_utc"], 1_700_000_100)
        self.assertEqual(out.loc[0, "provider_route_timestamp_utc"], 1_700_000_099)
        self.assertEqual(out.loc[0, "provider_block_timestamp_disagreement_seconds"], -1)
        self.assertEqual(out.loc[0, "eth_usd"], 2_010.0)
        self.assertEqual(out.loc[0, "eth_usd_mark_lag_seconds"], 60)
        self.assertEqual(out.loc[0, "receipt_total_gas_cost_usd"], 3.015)
        self.assertEqual(
            out.loc[0, "canonical_all_in_bps_release_status"],
            "withheld_missing_transaction_time_endpoint_usd",
        )
        self.assertEqual(
            out.loc[0, "daily_denominator_sensitivity_status"],
            "noncanonical_address_day_output_mark_with_provider_route_notional",
        )
        self.assertGreater(
            out.loc[0, "daily_denominator_sensitivity_all_in_direct_advantage_bps"],
            out.loc[0, "daily_denominator_sensitivity_same_block_base_fee_direct_advantage_bps"],
        )
        self.assertGreater(
            out.loc[0, "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper"],
            out.loc[0, "daily_denominator_sensitivity_all_in_direct_advantage_bps"],
        )
        self.assertGreater(
            out.loc[0, "daily_denominator_sensitivity_all_in_direct_advantage_bps"],
            out.loc[0, "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower"],
        )
        all_in_bps_columns = [column for column in out if "all_in" in column and "bps" in column]
        self.assertTrue(all(column.startswith(("daily_denominator_sensitivity_", "canonical_")) for column in all_in_bps_columns))

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

    def test_state_support_display_columns_match_summary_schema(self) -> None:
        frame = pd.DataFrame(
            {
                "date": [pd.Timestamp("2025-01-01")],
                "state_support": ["adjacent_no_liquidity"],
                "valuation_coherent_20pct": [True],
                "dominated_gross": [True],
                "best_direct_outside_realised_venue_set": [False],
                "direct_output_improvement_bps": [5.0],
                "daily_denominator_sensitivity_all_in_direct_advantage_bps": [1.0],
                "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower": [0.5],
                "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper": [1.5],
            }
        )
        support = state_support_summary(frame)
        display_columns = [
            "state_support",
            "routes",
            "pct_dominated_gross",
            "pct_dominated_valuation_coherent_20pct",
            "daily_denominator_sensitivity_pct_dominated_topology_gas_adjusted",
            "daily_denominator_sensitivity_pct_dominated_gas_iqr_lower",
            "daily_denominator_sensitivity_pct_dominated_gas_iqr_upper",
        ]
        self.assertEqual(support.loc[support["scope"].eq("pooled"), display_columns].shape, (1, len(display_columns)))


if __name__ == "__main__":
    unittest.main()
