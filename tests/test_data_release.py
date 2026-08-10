from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.data_release import (
    _exact_key_gate,
    audit_cross_venue_order_conflicts,
    require_market_state_release,
    require_v2_event_source_release,
)
from ddvc.v4_quarantine import audit_v4_pool_static_conflicts


class DataReleaseTests(unittest.TestCase):
    def test_full_market_state_release_adds_event_certificate_after_prerelease(self) -> None:
        from unittest.mock import patch

        with (
            patch("ddvc.data_release.require_market_state_prerelease") as prerelease,
            patch("ddvc.data_release.require_v2_event_source_release") as event_source,
        ):
            require_market_state_release()
        prerelease.assert_called_once_with()
        event_source.assert_called_once_with()

    def test_v2_event_release_gate_requires_current_artifacts_and_exact_calendar(self) -> None:
        from unittest.mock import patch

        summary = pd.DataFrame()
        exceptions = pd.DataFrame()
        certificate = {"status": "pass"}
        with (
            patch("ddvc.data_release.require_current_artifacts") as current,
            patch(
                "ddvc.data_release.read_v2_event_source_certificate",
                return_value=(summary, exceptions, certificate),
            ),
            patch(
                "ddvc.data_release.transaction_frontier_audit_days",
                return_value=["20250115"],
            ),
            patch("ddvc.data_release.validate_v2_event_source_certificate") as validate,
            patch("ddvc.data_release.validate_v2_event_source_evidence_bundle") as validate_evidence,
        ):
            require_v2_event_source_release()
        current.assert_called_once()
        validate.assert_called_once_with(
            summary,
            exceptions,
            certificate,
            ["20250115"],
        )
        validate_evidence.assert_called_once_with(certificate)

    def test_v4_static_audit_returns_complete_pool_level_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v4.parquet"
            pd.DataFrame(
                [
                    {
                        "pool": "stable",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": True,
                        "token0_raw": "0xa",
                        "token1_raw": "0xb",
                        "decimals0": 18,
                        "decimals1": 6,
                        "fee_pips": 500,
                        "tick_spacing": 10,
                        "hooks": "0x0",
                        "day": "20250101",
                    },
                    {
                        "pool": "drift",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": False,
                        "token0_raw": "0xa",
                        "token1_raw": "0xc",
                        "decimals0": 18,
                        "decimals1": 18,
                        "fee_pips": 3000,
                        "tick_spacing": 60,
                        "hooks": "0x0",
                        "day": "20250101",
                    },
                    {
                        "pool": "drift",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": True,
                        "token0_raw": "0xa",
                        "token1_raw": "0xc",
                        "decimals0": 18,
                        "decimals1": 0,
                        "fee_pips": 3000,
                        "tick_spacing": 60,
                        "hooks": "0x0",
                        "day": "20250102",
                    },
                ]
            ).to_parquet(path, index=False)
            quarantine = audit_v4_pool_static_conflicts([path])
        self.assertEqual(quarantine["pool"].tolist(), ["drift"])
        self.assertEqual(int(quarantine.iloc[0]["static_variants"]), 2)
        self.assertEqual(int(quarantine.iloc[0]["swap_rows"]), 2)

    def test_cross_venue_order_audit_rejects_one_block_log_claimed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for venue, tx_hash in (("uniswap_v3", "0xv3"), ("uniswap_v4", "0xv4")):
                path = root / f"{venue}.parquet"
                pd.DataFrame(
                    [{
                        "venue": venue,
                        "tx_hash": tx_hash,
                        "block_number": 100,
                        "log_index": 7,
                        "usable": True,
                    }]
                ).to_parquet(path, index=False)
                paths[venue] = [path]
            count, samples = audit_cross_venue_order_conflicts(paths)
        self.assertEqual(count, 1)
        self.assertEqual(samples[0]["venues"], ["uniswap_v3", "uniswap_v4"])

    def test_cross_venue_order_audit_ignores_quarantined_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for venue, usable in (("uniswap_v3", True), ("uniswap_v4", False)):
                path = root / f"{venue}.parquet"
                pd.DataFrame(
                    [{
                        "venue": venue,
                        "tx_hash": venue,
                        "block_number": 100,
                        "log_index": 7,
                        "usable": usable,
                    }]
                ).to_parquet(path, index=False)
                paths[venue] = [path]
            count, samples = audit_cross_venue_order_conflicts(paths)
        self.assertEqual((count, samples), (0, []))

    def test_exact_key_gate_accepts_only_the_complete_perimeter(self) -> None:
        expected = [("family", "venue", "20250101"), ("family", "venue", "20250102")]
        _exact_key_gate(label="test", actual=reversed(expected), expected=expected)
        with self.assertRaisesRegex(RuntimeError, "missing=.*20250102"):
            _exact_key_gate(label="test", actual=expected[:1], expected=expected)

    def test_analysis_panel_builders_call_the_shared_release_gate(self) -> None:
        expected = {
            "scripts/build_intermediation_by_type.py": "require_node_d_release(routes=True)",
            "scripts/build_cross_venue_routing_series.py": "require_node_d_release(routes=True)",
            "scripts/build_vehicle_excess_use.py": "require_node_d_release(routes=True)",
            "scripts/build_vehicle_centrality.py": "require_node_d_release(routes=True)",
            "scripts/build_ethereum_day_calendar.py": "require_node_d_release(routes=True)",
            "scripts/process/fetch_daily_gas_price_graph.py": "require_node_d_release(routes=True)",
            "scripts/process/build_route_gas_units.py": "require_node_d_release(routes=True)",
            "scripts/process/build_route_transaction_gas.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/run_route_cost_panel.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_transaction_state_frontier.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_routing_maturation_panel.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_counterfactual_dominance.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_rent_incidence_panel.py": "require_node_d_release(market_state=True)",
            "scripts/build_v2_token_panel.py": "require_market_state_prerelease()",
            "scripts/run_rent_incidence.py": "require_node_d_release(routes=True, market_state=True)",
        }
        for filename, call in expected.items():
            with self.subTest(filename=filename):
                self.assertIn(call, Path(filename).read_text(encoding="utf-8"))

    def test_release_orchestration_does_not_invalidate_analysis_results(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_vehicle_centrality.py",
            "scripts/build_ethereum_day_calendar.py",
            "scripts/build_counterfactual_dominance.py",
            "scripts/build_transaction_state_frontier.py",
            "scripts/build_routing_maturation_panel.py",
            "scripts/build_v2_token_panel.py",
            "scripts/build_rent_incidence_panel.py",
            "scripts/run_rent_incidence.py",
            "scripts/process/fetch_daily_gas_price_graph.py",
            "scripts/process/build_route_gas_units.py",
            "scripts/process/build_route_transaction_gas.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertNotIn('"src/ddvc/data_release.py"', source)

    def test_mixed_construction_and_analysis_runners_have_panel_only_mode(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_vehicle_centrality.py",
            "scripts/build_counterfactual_dominance.py",
            "scripts/process/fetch_daily_gas_price_graph.py",
            "scripts/process/build_route_gas_units.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn('"--panel-only"', source)
                self.assertIn("if args.panel_only:", source)

    def test_bounded_diagnostics_cannot_replace_canonical_panels(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_v2_token_panel.py",
            "scripts/build_counterfactual_dominance.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("canonical outputs unchanged", source)

    def test_dependent_consumers_require_current_analysis_inputs(self) -> None:
        filenames = [
            "scripts/build_transaction_state_frontier.py",
            "scripts/build_routing_maturation_panel.py",
            "scripts/build_counterfactual_dominance.py",
            "scripts/run_rent_incidence.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("require_current_artifacts(", source)


if __name__ == "__main__":
    unittest.main()
