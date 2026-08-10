from __future__ import annotations

import json
import pickle
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
    chosen_quote_coverage_share,
    chosen_reproduction_share,
    chosen_output_error,
    positive_finite_amount,
)
from ddvc.pricing.path_frontier import PathQuote
from ddvc.provenance import cache_key, sidecar_path, verify
from scripts.build_transaction_state_frontier import (
    FRONTIER_DEPENDENCY_REGISTRY,
    OUTPUT_PROVENANCE_SOURCES,
    REPLAY_CAUSAL_FIELDS,
    SCORING_CACHE_SOURCES,
    assemble_cached_output,
    candidate_vehicles,
    checkpoint_day,
    chosen_path_validation_errors,
    intermediate_amount_gap_bps,
    latest_replay_checkpoint,
    load_cached_day,
    load_target_routes,
    load_replay_checkpoint,
    main,
    frontier_cache_identity,
    rejection_record,
    require_full_daily_target_release,
    replay_checkpoint_due,
    save_replay_checkpoint,
    select_days,
    strict_route_order,
    summarise,
    validate_audit_support,
    validate_daily_support,
    validation_error_diagnostics,
    write_cached_day,
)
from ddvc.pricing.tick_replay import TickReplayState
from ddvc.pricing.tick_state import TickPoolState
from ddvc.pricing.v2_replay import V2ReplayDay
from ddvc.realised import LINEAR_ROUTE_COLUMNS


class TransactionStateFrontierScriptTests(unittest.TestCase):
    def test_full_daily_target_release_is_explicitly_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "streamed, immutable receipt-anchored target-route ledger",
        ):
            require_full_daily_target_release()

    def test_full_daily_mode_stops_before_every_downstream_gate(self) -> None:
        with (
            patch(
                "sys.argv",
                ["build_transaction_state_frontier.py", "--daily-calendar"],
            ),
            patch(
                "scripts.build_transaction_state_frontier.require_node_d_release"
            ) as node_gate,
            patch(
                "scripts.build_transaction_state_frontier.require_current_artifacts"
            ) as artifact_gate,
            patch(
                "scripts.build_transaction_state_frontier.available_days"
            ) as calendar_load,
        ):
            self.assertEqual(main(), 1)
        node_gate.assert_not_called()
        artifact_gate.assert_not_called()
        calendar_load.assert_not_called()

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
        self.assertEqual(chosen_quote_coverage_share(200, 150), 0.75)
        self.assertEqual(chosen_quote_coverage_share(0, 0), 0.0)

    def test_daily_gate_requires_exact_audit_calendar_and_reproduction(self) -> None:
        support = pd.DataFrame(
            {
                "day": ["20250115", "20250215"],
                "within_20pct_chosen_quote_eligible_routes": [100, 100],
                "within_20pct_chosen_quote_available": [100, 100],
                "within_20pct_chosen_output_mismatch": [0, 1],
            }
        )
        self.assertEqual(
            validate_audit_support(support, ["20250115", "20250215"]),
            (0.995, 1.0, 0.995),
        )
        with self.assertRaisesRegex(ValueError, "calendar does not match"):
            validate_audit_support(support, ["20250115", "20250315"])
        below_gate = support.copy()
        below_gate.loc[1, "within_20pct_chosen_output_mismatch"] = 3
        with self.assertRaisesRegex(ValueError, "below the 99% gate"):
            validate_audit_support(below_gate, ["20250115", "20250215"])

    def test_daily_gate_rejects_duplicate_audit_days(self) -> None:
        support = pd.DataFrame(
            {
                "day": ["20250115", "20250115"],
                "within_20pct_chosen_quote_eligible_routes": [100, 100],
                "within_20pct_chosen_quote_available": [100, 100],
                "within_20pct_chosen_output_mismatch": [0, 0],
            }
        )
        with self.assertRaisesRegex(ValueError, "duplicate days"):
            validate_audit_support(support, ["20250115"])

    def test_daily_release_gate_runs_before_canonical_assembly(self) -> None:
        support = pd.DataFrame(
            {
                "day": ["20250101", "20250102"],
                "within_20pct_chosen_quote_eligible_routes": [100, 100],
                "within_20pct_chosen_quote_available": [100, 100],
                "within_20pct_chosen_output_mismatch": [0, 3],
            }
        )
        with self.assertRaisesRegex(ValueError, "full-daily frontier.*below"):
            validate_daily_support(support, ["20250101", "20250102"])

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
        replay.states_by_venue = {
            "uniswap_v3": {
                "pool": TickPoolState(
                    "pool", "token-a", "token-b", "A", "B", 18, 6,
                    2**96, 0, 3_000, 60, 1, 2,
                )
            }
        }
        replay.pool_index = {frozenset(("stale-a", "stale-b")): [("bad", "pool")]}
        replay.quote_indexes_by_venue = {"uniswap_v3": {"pool": object()}}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pre_20230415.pkl"
            save_replay_checkpoint(
                path, replay, engine_key="engine", pre_day="20230415"
            )
            with path.open("rb") as handle:
                payload = pickle.load(handle)
            restored = load_replay_checkpoint(
                path, engine_key="engine", pre_day="20230415"
            )
        self.assertEqual(set(payload["causal_state"]), set(REPLAY_CAUSAL_FIELDS))
        self.assertNotIn("pool_index", payload["causal_state"])
        self.assertNotIn("quote_indexes_by_venue", payload["causal_state"])
        self.assertEqual(restored.ticks_by_venue, replay.ticks_by_venue)
        self.assertEqual(
            restored.pool_index,
            {frozenset(("token-a", "token-b")): [("uniswap_v3", "pool")]},
        )
        self.assertEqual(restored.quote_indexes_by_venue, {})

    def test_replay_checkpoint_rejects_legacy_engine_and_pre_day(self) -> None:
        replay = TickReplayState()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pre_20230415.pkl"
            save_replay_checkpoint(
                path, replay, engine_key="engine", pre_day="20230415"
            )
            with self.assertRaisesRegex(ValueError, "engine mismatch"):
                load_replay_checkpoint(
                    path, engine_key="other", pre_day="20230415"
                )
            with self.assertRaisesRegex(ValueError, "pre-day mismatch"):
                load_replay_checkpoint(
                    path, engine_key="engine", pre_day="20230416"
                )
            legacy = root / "pre_20230416.pkl"
            with legacy.open("wb") as handle:
                pickle.dump(replay, handle)
            with self.assertRaisesRegex(ValueError, "legacy or invalid"):
                load_replay_checkpoint(
                    legacy, engine_key="engine", pre_day="20230416"
                )

    def test_frontier_dependency_groups_separate_scoring_from_publication(self) -> None:
        scoring_changes = {
            "src/ddvc/route_cost.py",
            "src/ddvc/calendar.py",
            "src/ddvc/v4_quarantine.py",
        }
        non_scoring_changes = {
            "src/ddvc/data_release.py",
            "src/ddvc/runtime.py",
            "src/ddvc/tables.py",
            "src/ddvc/panel_assembly.py",
        }
        registered = [
            source
            for sources in FRONTIER_DEPENDENCY_REGISTRY.values()
            for source in sources
        ]
        self.assertEqual(len(registered), len(set(registered)))
        self.assertEqual(
            SCORING_CACHE_SOURCES,
            list(FRONTIER_DEPENDENCY_REGISTRY["scoring"]),
        )
        self.assertEqual(
            OUTPUT_PROVENANCE_SOURCES,
            [
                *FRONTIER_DEPENDENCY_REGISTRY["scoring"],
                *FRONTIER_DEPENDENCY_REGISTRY["publication"],
            ],
        )
        self.assertTrue(scoring_changes <= set(SCORING_CACHE_SOURCES))
        self.assertNotIn("src/ddvc/data_release.py", registered)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in [*registered, "src/ddvc/data_release.py"]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"SOURCE = {relative!r}\n", encoding="utf-8")
            with patch("ddvc.provenance.ROOT", root):
                baseline_scoring = frontier_cache_identity([])[0]
                baseline_output = cache_key(OUTPUT_PROVENANCE_SOURCES)
                for relative in sorted(scoring_changes):
                    path = root / relative
                    original = path.read_text(encoding="utf-8")
                    path.write_text(original + "CHANGED = True\n", encoding="utf-8")
                    self.assertNotEqual(
                        frontier_cache_identity([])[0], baseline_scoring
                    )
                    path.write_text(original, encoding="utf-8")
                for relative in sorted(non_scoring_changes):
                    path = root / relative
                    original = path.read_text(encoding="utf-8")
                    path.write_text(original + "CHANGED = True\n", encoding="utf-8")
                    self.assertEqual(
                        frontier_cache_identity([])[0], baseline_scoring
                    )
                    if relative == "src/ddvc/data_release.py":
                        self.assertEqual(
                            cache_key(OUTPUT_PROVENANCE_SOURCES), baseline_output
                        )
                    else:
                        self.assertNotEqual(
                            cache_key(OUTPUT_PROVENANCE_SOURCES), baseline_output
                        )
                    path.write_text(original, encoding="utf-8")

    def test_validation_diagnostics_keep_rejected_tail_visible(self) -> None:
        diagnostics = validation_error_diagnostics([0.0, -10.0, 200.0, -500.0])
        self.assertEqual(diagnostics["quote_available"], 4)
        self.assertEqual(diagnostics["output_mismatch"], 3)
        self.assertEqual(diagnostics["validation_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["mismatch_abs_min_bps"], 10.0)
        self.assertEqual(diagnostics["mismatch_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["validation_within_tolerance_share"], 0.25)

    def test_leg_validation_catches_compensating_path_errors(self) -> None:
        validation = chosen_path_validation_errors(
            realised_leg1_output=100.0,
            realised_path_output=100.0,
            quoted_leg1_output=101.0,
            quoted_leg2_output=99.0,
            quoted_path_output=100.0,
        )
        assert validation is not None
        self.assertEqual(validation["chosen_validation_error_bps"], 0.0)
        self.assertAlmostEqual(
            validation["chosen_validation_max_abs_error_bps"], 100.0
        )

    def test_latest_checkpoint_never_jumps_past_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for day in ("20220101", "20230101", "20240101"):
                (root / f"pre_{day}.pkl").touch()
            selected = latest_replay_checkpoint(root, "20230615")
        assert selected is not None
        self.assertEqual(checkpoint_day(selected), "20230101")

    def test_daily_frontier_checkpoints_only_at_bounded_intervals(self) -> None:
        self.assertTrue(replay_checkpoint_due(index=1))
        self.assertFalse(replay_checkpoint_due(index=2))
        self.assertFalse(replay_checkpoint_due(index=180))
        self.assertTrue(replay_checkpoint_due(index=181))

    def test_day_cache_installs_support_marker_after_panel(self) -> None:
        panel = pd.DataFrame(
            {
                "day": ["20230415"],
                "route_id": ["one"],
                "public_path_regret_bps": [1.0],
            }
        )
        rejections = pd.DataFrame(
            {
                "day": ["20230415"],
                "route_id": ["two"],
                "reason": ["chosen_output_mismatch"],
            }
        )
        support = {"day": "20230415", "scored_routes": 1, "rejected_routes": 1}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_cached_day(
                root,
                "20230415",
                panel,
                rejections,
                support,
                engine_key="engine",
                input_key="input",
            )
            marker = json.loads((root / "20230415.support.json").read_text())
            cached = load_cached_day(
                root,
                "20230415",
                engine_key="engine",
                input_key="input",
            )
        assert cached is not None
        cached_panel, cached_rejections, cached_support = cached
        pd.testing.assert_frame_equal(cached_panel, panel)
        pd.testing.assert_frame_equal(cached_rejections, rejections)
        self.assertEqual(cached_support, support)
        self.assertEqual(marker["engine_key"], "engine")
        self.assertEqual(marker["input_key"], "input")
        self.assertEqual(marker["day_start"], "20230415")
        self.assertEqual(marker["day_end"], "20230415")
        self.assertEqual(marker["shards"]["panel"]["route_key_count"], 1)
        self.assertEqual(len(marker["shards"]["panel"]["content_sha256"]), 64)
        self.assertEqual(len(marker["shards"]["panel"]["schema_sha256"]), 64)

    def test_day_cache_rejects_wrong_identity_and_changed_content(self) -> None:
        panel = pd.DataFrame(
            {"day": ["20230415"], "route_id": ["one"], "value": [1.0]}
        )
        support = {"day": "20230415", "scored_routes": 1, "rejected_routes": 0}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_cached_day(
                root,
                "20230415",
                panel,
                pd.DataFrame(),
                support,
                engine_key="engine",
                input_key="input",
            )
            with self.assertRaisesRegex(ValueError, "engine mismatch"):
                load_cached_day(
                    root,
                    "20230415",
                    engine_key="other",
                    input_key="input",
                )
            with self.assertRaisesRegex(ValueError, "input mismatch"):
                load_cached_day(
                    root,
                    "20230415",
                    engine_key="engine",
                    input_key="other",
                )
            panel.assign(value=2.0).to_parquet(
                root / "20230415.parquet", index=False
            )
            with self.assertRaisesRegex(ValueError, "content contract mismatch"):
                load_cached_day(
                    root,
                    "20230415",
                    engine_key="engine",
                    input_key="input",
                )

    def test_day_cache_rejects_wrong_bounds_and_duplicate_route_keys(self) -> None:
        support = {"day": "20230415", "scored_routes": 2, "rejected_routes": 0}
        for frame, message in (
            (
                pd.DataFrame(
                    {
                        "day": ["20230415", "20230416"],
                        "route_id": ["one", "two"],
                    }
                ),
                "day bounds disagree",
            ),
            (
                pd.DataFrame(
                    {
                        "day": ["20230415", "20230415"],
                        "route_id": ["one", "one"],
                    }
                ),
                "duplicate route keys",
            ),
        ):
            with self.subTest(message=message), TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaisesRegex(ValueError, message):
                    write_cached_day(
                        root,
                        "20230415",
                        frame,
                        pd.DataFrame(),
                        support,
                        engine_key="engine",
                        input_key="input",
                    )
                self.assertFalse((root / "20230415.support.json").exists())

    def test_empty_day_cache_needs_no_zero_column_parquet(self) -> None:
        support = {"day": "20200214", "scored_routes": 0, "rejected_routes": 0}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_cached_day(
                root,
                "20200214",
                pd.DataFrame(),
                pd.DataFrame(),
                support,
                engine_key="engine",
                input_key="input",
            )
            self.assertFalse((root / "20200214.parquet").exists())
            self.assertFalse((root / "20200214.rejections.parquet").exists())
            cached = load_cached_day(
                root,
                "20200214",
                engine_key="engine",
                input_key="input",
            )
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
                write_cached_day(
                    root,
                    day,
                    pd.DataFrame(
                        {"day": [day], "route_id": [f"route-{day}"]}
                    ),
                    pd.DataFrame(),
                    {"day": day, "scored_routes": 1, "rejected_routes": 0},
                    engine_key="engine",
                    input_key="input",
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
                    engine_key="engine",
                    input_key="input",
                )
                assembled = pd.read_parquet(output)
                stamped_inputs = stamp_mock.call_args.kwargs["inputs"]
                manifest_path = stamped_inputs[1]
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(rows, 2)
        self.assertEqual(len(assembled), 2)
        stamp_mock.assert_called_once()
        self.assertEqual(stamped_inputs[0], canonical_input)
        self.assertEqual(manifest_path.name, "daily.parquet.ordered-shards.json")
        self.assertEqual(
            [path.name for path in stamped_inputs[2:]],
            ["20250101.support.json", "20250102.support.json"],
        )
        self.assertIn("resumable day cache", stamp_mock.call_args.kwargs["notes"])
        self.assertEqual(len(manifest["ordered_shard_manifest_root"]), 64)
        self.assertEqual([entry["day"] for entry in manifest["entries"]], ["20250101", "20250102"])

    def test_marker_mutation_makes_assembled_release_stale(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            day_cache = root / "cache"
            for day in ("20250101", "20250102"):
                write_cached_day(
                    day_cache,
                    day,
                    pd.DataFrame({"day": [day], "route_id": [f"route-{day}"]}),
                    pd.DataFrame(),
                    {"day": day, "scored_routes": 1, "rejected_routes": 0},
                    engine_key="engine",
                    input_key="input",
                )
            output = root / "daily.parquet"
            with (
                patch("ddvc.provenance.ROOT", root),
                patch("ddvc.provenance.MANIFESTS", root / "manifests"),
            ):
                assemble_cached_output(
                    day_cache,
                    [
                        {"day": "20250101", "scored_routes": 1},
                        {"day": "20250102", "scored_routes": 1},
                    ],
                    suffix=".parquet",
                    count_column="scored_routes",
                    output=output,
                    inputs=[],
                    notes="test",
                    engine_key="engine",
                    input_key="input",
                )
                self.assertEqual(verify(output)["status"], "ok")
                record = json.loads(sidecar_path(output).read_text(encoding="utf-8"))
                marker = day_cache / "20250101.support.json"
                marker.write_text(marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
                verdict = verify(output)
            self.assertTrue(
                any(
                    str(item["path"]).endswith("daily.parquet.ordered-shards.json")
                    for item in record["inputs"]
                )
            )
            self.assertEqual(verdict["status"], "stale")
            self.assertIn("cache/20250101.support.json", verdict["changed_inputs"])

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
