from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH
from ddvc.analysis.transaction_frontier import (
    MAX_CHOSEN_REPRODUCTION_ERROR,
    MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
    MIN_CHOSEN_REPRODUCTION,
    RealisedPath,
    chosen_reproduction_share,
    chosen_output_error,
    positive_finite_amount,
)
from ddvc.pricing.path_frontier import PathQuote
from scripts.build_transaction_state_frontier import (
    assemble_cached_output,
    candidate_vehicles,
    checkpoint_day,
    intermediate_amount_gap_bps,
    latest_replay_checkpoint,
    load_cached_day,
    load_target_routes,
    load_replay_checkpoint,
    rejection_record,
    replay_checkpoint_due,
    save_replay_checkpoint,
    select_days,
    strict_route_order,
    summarise,
    validation_error_diagnostics,
    write_cached_day,
)
from ddvc.pricing.tick_replay import TickReplayState
from ddvc.pricing.v2_replay import V2ReplayDay
from ddvc.realised import LINEAR_ROUTE_COLUMNS


class TransactionStateFrontierScriptTests(unittest.TestCase):
    def test_strict_route_order_requires_one_block(self) -> None:
        events = [
            {"block": 12, "log_index": 8},
            {"block": 12, "log_index": 13},
        ]
        self.assertEqual(strict_route_order(events), (12, 8))
        self.assertIsNone(strict_route_order([{**events[0], "block": None}, events[1]]))
        with self.assertRaisesRegex(ValueError, "disagree"):
            strict_route_order([events[0], {**events[1], "block": 13}])

    def test_candidate_set_canonicalises_native_forms_once(self) -> None:
        vehicles = candidate_vehicles()
        self.assertIn(WETH, vehicles)
        self.assertNotIn(NATIVE_ETH, vehicles)
        self.assertEqual(len(vehicles), len(set(vehicles)))

    def test_explicit_day_selection_is_exact_and_normalised(self) -> None:
        selected = select_days(
            ["20220615", "20240615"],
            explicit=["2022-06-15"],
            audit_calendar=False,
        )
        self.assertEqual(selected, ["20220615"])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            select_days(
                ["20220615"],
                explicit=["20230615"],
                audit_calendar=False,
            )

    def test_full_daily_selection_is_distinct_from_the_audit_calendar(self) -> None:
        available = ["20250101", "20250102", "20250103"]
        self.assertEqual(
            select_days(
                available,
                explicit=None,
                audit_calendar=False,
                daily_calendar=True,
            ),
            available,
        )
        with self.assertRaisesRegex(ValueError, "explicit, audit, or full daily"):
            select_days(
                available,
                explicit=None,
                audit_calendar=False,
                daily_calendar=False,
            )

    def test_audit_and_daily_outputs_have_distinct_names(self) -> None:
        source = Path("scripts/build_transaction_state_frontier.py").read_text()
        self.assertIn("transaction_state_frontier_audit.parquet", source)
        self.assertIn("transaction_state_frontier_daily.parquet", source)
        self.assertNotIn(
            '"transaction_state_frontier.parquet"',
            source,
        )

    def test_zero_realised_output_has_no_relative_validation_error(self) -> None:
        route = RealisedPath("a", "b", "k", 1.0, 0.0, ("v2", "v2"), ("ak", "kb"))
        chosen = PathQuote(
            vehicle="k",
            amount_out=1.0,
            venues=("v2", "v2"),
            pools=("ak", "kb"),
            price_impacts=(0.0, 0.0),
        )
        self.assertIsNone(chosen_output_error(route, chosen))
        self.assertFalse(positive_finite_amount(route.amount_out))

    def test_intermediate_flow_contract_is_in_token_units(self) -> None:
        self.assertEqual(intermediate_amount_gap_bps(100.0, 100.0), 0.0)
        self.assertAlmostEqual(intermediate_amount_gap_bps(100.0, 99.0), -100.0)
        self.assertIsNone(intermediate_amount_gap_bps(0.0, 1.0))

    def test_chosen_reproduction_gate_has_one_canonical_owner(self) -> None:
        self.assertEqual(MIN_CHOSEN_REPRODUCTION, 0.99)
        self.assertEqual(MAX_CHOSEN_REPRODUCTION_ERROR_BPS, 1.0)
        self.assertEqual(MAX_CHOSEN_REPRODUCTION_ERROR, 0.0001)
        self.assertAlmostEqual(chosen_reproduction_share(101, 1), 100 / 101)
        self.assertEqual(chosen_reproduction_share(0, 0), 0.0)

    def test_summary_keeps_all_and_valuation_coherent_samples_separate(self) -> None:
        panel = pd.DataFrame(
            {
                "day": ["20220615", "20220615", "20240615"],
                "within_20pct": [True, False, True],
                "input_usd": [100.0, 200.0, 300.0],
                "chosen_validation_error_bps": [1.0, -2.0, 3.0],
                "within_reach_search_regret_bps": [0.0, 5.0, 10.0],
                "public_reach_same_vehicle_regret_bps": [1.0, 6.0, 11.0],
                "public_path_regret_bps": [2.0, 20.0, 12.0],
                "reach_increment_bps": [1.0, 1.0, 1.0],
                "path_choice_increment_bps": [1.0, 14.0, 1.0],
                "direct_omission_bps": [None, 4.0, 0.0],
                "public_gain_usd": [0.02, 0.40, 0.36],
            }
        )
        summary = summarise(panel)
        pooled = summary[summary["day"].eq("pooled")].set_index("sample")
        self.assertEqual(int(pooled.loc["all", "routes"]), 3)
        self.assertEqual(int(pooled.loc["within_20pct", "routes"]), 2)
        self.assertAlmostEqual(
            float(pooled.loc["all", "public_path_regret_positive_share"]),
            1.0,
        )
        self.assertAlmostEqual(
            float(pooled.loc["all", "public_path_regret_over_1bps_share"]),
            1.0,
        )
        self.assertAlmostEqual(
            float(pooled.loc["all", "path_choice_increment_over_1bps_share"]),
            1 / 3,
        )

    def test_replay_checkpoint_round_trips_exact_state(self) -> None:
        replay = TickReplayState()
        replay.ticks_by_venue = {"uniswap_v3": {"pool": {-10: 5, 10: -5}}}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.pkl"
            save_replay_checkpoint(path, replay)
            restored = load_replay_checkpoint(path)
        self.assertEqual(restored.ticks_by_venue, replay.ticks_by_venue)

    def test_validation_diagnostics_keep_rejected_tail_visible(self) -> None:
        diagnostics = validation_error_diagnostics([0.0, -10.0, 200.0, -500.0])
        self.assertEqual(diagnostics["quote_available"], 4)
        self.assertEqual(diagnostics["output_mismatch"], 3)
        self.assertEqual(diagnostics["validation_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["mismatch_abs_min_bps"], 10.0)
        self.assertEqual(diagnostics["mismatch_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["validation_within_tolerance_share"], 0.25)

    def test_latest_checkpoint_never_jumps_past_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for day in ("20220101", "20230101", "20240101"):
                (root / f"pre_{day}.pkl").touch()
            selected = latest_replay_checkpoint(root, "20230615")
        assert selected is not None
        self.assertEqual(checkpoint_day(selected), "20230101")

    def test_daily_frontier_checkpoints_only_at_bounded_intervals(self) -> None:
        selected = {"20200101", "20200102"}
        self.assertTrue(
            replay_checkpoint_due(
                day="20200101", index=1, selected_days=selected, daily_mode=True
            )
        )
        self.assertFalse(
            replay_checkpoint_due(
                day="20200102", index=2, selected_days=selected, daily_mode=True
            )
        )
        self.assertTrue(
            replay_checkpoint_due(
                day="20200102", index=2, selected_days=selected, daily_mode=False
            )
        )
        self.assertTrue(
            replay_checkpoint_due(
                day="20200629", index=181, selected_days=selected, daily_mode=True
            )
        )

    def test_day_cache_installs_support_marker_after_panel(self) -> None:
        panel = pd.DataFrame({"route_id": ["one"], "public_path_regret_bps": [1.0]})
        rejections = pd.DataFrame(
            {"route_id": ["two"], "reason": ["chosen_output_mismatch"]}
        )
        support = {"day": "20230415", "scored_routes": 1, "rejected_routes": 1}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_cached_day(root, "20230415", panel, rejections, support)
            cached = load_cached_day(root, "20230415")
        assert cached is not None
        cached_panel, cached_rejections, cached_support = cached
        pd.testing.assert_frame_equal(cached_panel, panel)
        pd.testing.assert_frame_equal(cached_rejections, rejections)
        self.assertEqual(cached_support, support)

    def test_empty_day_cache_needs_no_zero_column_parquet(self) -> None:
        support = {"day": "20200214", "scored_routes": 0, "rejected_routes": 0}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_cached_day(
                root, "20200214", pd.DataFrame(), pd.DataFrame(), support
            )
            self.assertFalse((root / "20200214.parquet").exists())
            self.assertFalse((root / "20200214.rejections.parquet").exists())
            cached = load_cached_day(root, "20200214")
        assert cached is not None
        cached_panel, cached_rejections, cached_support = cached
        self.assertTrue(cached_panel.empty)
        self.assertTrue(cached_rejections.empty)
        self.assertEqual(cached_support, support)

    def test_rejection_record_preserves_route_and_causal_identity(self) -> None:
        row = rejection_record(
            "20250310",
            {
                "route_id": "route",
                "tx_hash": "0xABC",
                "component_id": 2,
                "timestamp_utc": 100,
                "src": "a",
                "tgt": "b",
                "vehicle": WETH,
                "input_usd": 125.0,
                "output_usd": 124.0,
                "realised_amount_in": 1.0,
                "realised_amount_out": 2.0,
                "within_20pct": True,
                "cross_venue": True,
            },
            "chosen_output_mismatch",
            causal_order=(20, 7),
            venues=("uniswap_v3", "uniswap_v4"),
            pools=("pool-a", "pool-b"),
            chosen_quote_out=3.0,
            signed_validation_error_bps=5_000.0,
        )
        self.assertEqual(row["tx_hash"], "0xabc")
        self.assertEqual((row["block_number"], row["first_log_index"]), (20, 7))
        self.assertEqual(row["realised_pools"], "pool-a|pool-b")
        self.assertEqual(row["signed_validation_error_bps"], 5_000.0)

    def test_full_daily_assembly_streams_validated_day_shards(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for day in ("20250101", "20250102"):
                pd.DataFrame({"day": [day], "route_id": [f"route-{day}"]}).to_parquet(
                    root / f"{day}.parquet", index=False
                )
            output = root / "daily.parquet"
            canonical_input = root / "source.parquet"
            with patch("scripts.build_transaction_state_frontier.stamp") as stamp_mock:
                rows = assemble_cached_output(
                    root,
                    [
                        {"day": "20250101", "scored_routes": 1},
                        {"day": "20250102", "scored_routes": 1},
                    ],
                    suffix=".parquet",
                    count_column="scored_routes",
                    output=output,
                    inputs=[canonical_input],
                    notes="test",
                )
                assembled = pd.read_parquet(output)
        self.assertEqual(rows, 2)
        self.assertEqual(len(assembled), 2)
        stamp_mock.assert_called_once()
        self.assertEqual(stamp_mock.call_args.kwargs["inputs"], [canonical_input])
        self.assertIn("resumable day cache", stamp_mock.call_args.kwargs["notes"])

    def test_empty_day_preserves_calendar_support(self) -> None:
        empty_replay = V2ReplayDay({}, {}, {}, {}, {}, {})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame(columns=LINEAR_ROUTE_COLUMNS).to_parquet(
                root / "20200214.parquet",
                index=False,
            )
            with patch("scripts.build_transaction_state_frontier.UNIFIED", root):
                targets, rejections, support = load_target_routes(
                    "20200214", [], empty_replay
                )
        self.assertEqual(targets, [])
        self.assertEqual(rejections, [])
        self.assertEqual(support["all_exact_two_leg_routes"], 0)
        self.assertEqual(support["exact_venue_two_leg_routes"], 0)


if __name__ == "__main__":
    unittest.main()
