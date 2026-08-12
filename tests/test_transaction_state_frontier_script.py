from __future__ import annotations

import json
import pickle
import unittest
from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import PropertyMock, patch

import pandas as pd

from ddvc.artifact_release import bind_file_lineage
from ddvc.asset_types import NATIVE_ETH, WETH
from ddvc.analysis.transaction_frontier import (
    CHOSEN_REPRODUCTION_DASHBOARD_REFERENCE,
    MAX_CHOSEN_REPRODUCTION_ERROR,
    MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
    RealisedPath,
    chosen_quote_coverage_share,
    chosen_reproduction_share,
    chosen_output_error,
    positive_finite_amount,
)
from ddvc.pricing.path_frontier import PathQuote
from ddvc.pricing.v3pools import compute_pool_address
from ddvc.provenance import cache_key, sidecar_path, verify
from ddvc.transaction_targets import ProviderSwapEvent, TargetRelease
from scripts.build_transaction_state_frontier import (
    DAILY_PARENT_MEMORY_RESERVE_BYTES,
    DAILY_WORKER_MEMORY_BUDGET_BYTES,
    FRONTIER_DEPENDENCY_REGISTRY,
    OUTPUT_PROVENANCE_SOURCES,
    REPLAY_CAUSAL_FIELDS,
    REPLAY_CHECKPOINT_BOUNDARY,
    ReplayShardResult,
    ReplayShardTask,
    SCORING_CACHE_SOURCES,
    DailySegmentTask,
    assemble_cached_output,
    candidate_vehicles,
    checkpoint_day,
    chosen_path_validation_errors,
    daily_worker_count,
    intermediate_amount_gap_bps,
    latest_replay_checkpoint,
    load_cached_day,
    load_target_routes,
    load_replay_checkpoint,
    main,
    frontier_cache_identity,
    materialize_segment_checkpoints,
    plan_daily_segments,
    rejection_record,
    require_full_daily_target_release,
    replay_checkpoint_due,
    sparse_replay_history_lease,
    publish_full_daily_frontier,
    replay_ordered_event_shards,
    run_daily_segments,
    save_replay_checkpoint,
    score_daily_segment,
    select_days,
    strict_route_order,
    summarise,
    validate_audit_support,
    validate_daily_support,
    validation_error_diagnostics,
    write_cached_day,
)
from ddvc.pricing.tick_replay import TickReplayEvent, TickReplayState
from ddvc.pricing.tick_state import TickPoolState
from ddvc.pricing.v2_replay import V2ReplayDay
from ddvc.realised import LINEAR_ROUTE_COLUMNS


class InlineExecutor:
    """Synchronous future executor for deterministic process-orchestration tests."""

    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future


@contextmanager
def inline_process_pool(_workers: int):
    yield InlineExecutor()


class StableTargetContext:
    """Pickle-safe exact-source lease for isolated orchestration tests."""

    def assert_current(self) -> None:
        return None


class DriftingTargetContext:
    def __init__(self, fail_on: int):
        self.fail_on = fail_on
        self.calls = 0

    def assert_current(self) -> None:
        self.calls += 1
        if self.calls >= self.fail_on:
            raise RuntimeError("injected exact-source drift")


class TransactionStateFrontierScriptTests(unittest.TestCase):
    def test_sparse_replay_binds_intervening_tick_history(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                (venue, day): root / f"{venue}-{day}.json"
                for venue in ("uniswap_v3", "uniswap_v4")
                for day in ("20210504", "20210505", "20210506")
            }
            for path in paths.values():
                path.write_text("source\n", encoding="utf-8")
            with patch(
                "scripts.build_transaction_state_frontier.state_partition_lineage",
                side_effect=lambda _root, _family, venue, day, **_kwargs: bind_file_lineage(
                    [paths[(venue, day)]]
                ),
            ):
                lease = sparse_replay_history_lease(["20210506"], raw_root=root)
            paths[("uniswap_v3", "20210505")].write_text(
                "changed\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "leased source file changed"):
                lease.assert_current()

    def test_full_daily_publication_uses_sealed_sources_and_generic_owner(self) -> None:
        support = [
            {
                "day": "20250101",
                "within_20pct_chosen_quote_eligible_routes": 1,
                "within_20pct_chosen_quote_available": 1,
                "within_20pct_chosen_output_mismatch": 0,
                "scored_routes": 1,
                "rejected_routes": 0,
            }
        ]
        target = DriftingTargetContext(fail_on=99)
        target.content_identity_sha256 = "a" * 64
        replay = type("Replay", (), {"assert_current": lambda self: None})()
        with (
            patch(
                "scripts.build_transaction_state_frontier.assemble_cached_output",
                return_value=1,
            ),
            patch("scripts.build_transaction_state_frontier.current_target_release", return_value=nullcontext()) as target_lease,
            patch("scripts.build_transaction_state_frontier.current_file_lineage", return_value=nullcontext()) as replay_lease,
            patch("scripts.build_transaction_state_frontier.publish_frontier_release") as publish,
        ):
            publish_full_daily_frontier(
                support,
                selected=["20250101"],
                day_cache=Path("cache"),
                inputs=[],
                engine_key="engine",
                input_key="input",
                target_release=target,
                replay_history=replay,
                source_identity="a" * 64,
            )
        target_lease.assert_called_once_with(target)
        replay_lease.assert_called_once_with(replay)
        publish.assert_called_once()
    def test_full_daily_target_release_has_one_certified_resolver(self) -> None:
        released = object()
        with patch("scripts.build_transaction_state_frontier.resolve_target_release", return_value=released) as resolve:
            self.assertIs(require_full_daily_target_release(["20250101"]), released)
        resolve.assert_called_once_with("daily", expected_days=["20250101"])

    def test_full_daily_mode_stops_at_missing_certified_target_release(self) -> None:
        with (
            patch(
                "sys.argv",
                ["build_transaction_state_frontier.py", "--daily-calendar"],
            ),
            patch(
                "scripts.build_transaction_state_frontier.require_node_d_release"
            ) as node_gate,
            patch(
                "scripts.build_transaction_state_frontier.current_artifacts",
                return_value=nullcontext(),
            ) as artifact_gate,
            patch(
                "scripts.build_transaction_state_frontier.available_days"
            , return_value=["20250101"]) as calendar_load,
            patch(
                "scripts.build_transaction_state_frontier.require_full_daily_target_release",
                side_effect=FileNotFoundError("missing target release"),
            ) as target_gate,
        ):
            self.assertEqual(main(), 1)
        node_gate.assert_called_once_with(routes=True)
        artifact_gate.assert_called_once()
        calendar_load.assert_called_once_with(nonempty=False)
        target_gate.assert_called_once_with(["20250101"])

    def test_strict_route_order_requires_one_block(self) -> None:
        def event(block: int, log_index: int) -> ProviderSwapEvent:
            return ProviderSwapEvent("uniswap_v2", "0xtx", block, log_index, 100, "pool", "a", "b", 0, 0, 1, -1, True)

        events = [event(12, 8), event(12, 13)]
        self.assertEqual(strict_route_order(events), (12, 8))
        with self.assertRaisesRegex(ValueError, "disagree"):
            strict_route_order([events[0], event(13, 13)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            strict_route_order([events[0], event(12, 8)])

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
        release_source = Path("src/ddvc/frontier_release.py").read_text()
        self.assertIn("transaction_state_frontier_audit.parquet", source)
        self.assertIn("transaction_state_frontier_daily.parquet", release_source)
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

    def test_chosen_reproduction_reference_has_one_canonical_owner(self) -> None:
        self.assertEqual(CHOSEN_REPRODUCTION_DASHBOARD_REFERENCE, 0.99)
        self.assertEqual(MAX_CHOSEN_REPRODUCTION_ERROR_BPS, 1.0)
        self.assertEqual(MAX_CHOSEN_REPRODUCTION_ERROR, 0.0001)
        self.assertAlmostEqual(chosen_reproduction_share(101, 1), 100 / 101)
        self.assertEqual(chosen_reproduction_share(0, 0), 0.0)
        self.assertEqual(chosen_quote_coverage_share(200, 150), 0.75)
        self.assertEqual(chosen_quote_coverage_share(0, 0), 0.0)

    def test_daily_gate_requires_exact_audit_calendar_and_reports_reproduction(self) -> None:
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
        below_reference = support.copy()
        below_reference.loc[1, "within_20pct_chosen_output_mismatch"] = 3
        self.assertEqual(
            validate_audit_support(below_reference, ["20250115", "20250215"]),
            (0.985, 1.0, 0.985),
        )

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

    def test_daily_release_validation_reports_sub_reference_reproduction(self) -> None:
        support = pd.DataFrame(
            {
                "day": ["20250101", "20250102"],
                "within_20pct_chosen_quote_eligible_routes": [100, 100],
                "within_20pct_chosen_quote_available": [100, 100],
                "within_20pct_chosen_output_mismatch": [0, 3],
            }
        )
        self.assertEqual(
            validate_daily_support(support, ["20250101", "20250102"]),
            (0.985, 1.0, 0.985),
        )

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
        replay.scientifically_unsupported_venues = {"uniswap_v4"}
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
        causal_state = pickle.loads(payload["causal_state_pickle"])
        self.assertEqual(set(causal_state), set(REPLAY_CAUSAL_FIELDS))
        self.assertNotIn("pool_index", causal_state)
        self.assertNotIn("quote_indexes_by_venue", causal_state)
        self.assertEqual(len(payload["causal_state_sha256"]), 64)
        self.assertEqual(payload["causal_boundary"], REPLAY_CHECKPOINT_BOUNDARY)
        self.assertEqual(restored.ticks_by_venue, replay.ticks_by_venue)
        self.assertEqual(
            restored.pool_index,
            {frozenset(("token-a", "token-b")): [("uniswap_v3", "pool")]},
        )
        self.assertEqual(restored.quote_indexes_by_venue, {})
        self.assertEqual(restored.scientifically_unsupported_venues, {"uniswap_v4"})
        with self.assertRaisesRegex(ValueError, "reopen closed scientific support"):
            restored.apply(TickReplayEvent((20, 1), "uniswap_v4", "initialize", {"transaction": {"blockNumber": "20"}, "logIndex": "1", "pool": {"id": "pool"}}))

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

    def test_replay_checkpoint_is_immutable_and_content_checked(self) -> None:
        replay = TickReplayState(token_decimals={"token": 18})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pre_20230415.pkl"
            save_replay_checkpoint(path, replay, engine_key="engine", pre_day="20230415")
            with self.assertRaisesRegex(FileExistsError, "immutable"):
                save_replay_checkpoint(path, replay, engine_key="engine", pre_day="20230415")
            payload = pickle.loads(path.read_bytes())
            payload["causal_state_pickle"] += b"corrupt"
            path.write_bytes(pickle.dumps(payload))
            with self.assertRaisesRegex(ValueError, "content mismatch"):
                load_replay_checkpoint(path, engine_key="engine", pre_day="20230415")

    def test_daily_workers_are_memory_and_cpu_bounded(self) -> None:
        m3_memory = DAILY_PARENT_MEMORY_RESERVE_BYTES + 2 * DAILY_WORKER_MEMORY_BUDGET_BYTES
        studio_memory = 64 * 1024**3
        self.assertEqual(daily_worker_count(None, total_memory_bytes=m3_memory, cpu_count=14), 2)
        self.assertEqual(daily_worker_count(4, total_memory_bytes=m3_memory, cpu_count=14), 2)
        self.assertEqual(daily_worker_count(None, total_memory_bytes=studio_memory, cpu_count=16), 4)
        self.assertEqual(daily_worker_count(2, total_memory_bytes=studio_memory, cpu_count=16), 2)
        with self.assertRaisesRegex(ValueError, "positive"):
            daily_worker_count(0, total_memory_bytes=studio_memory, cpu_count=16)

    def test_daily_segment_plan_has_no_overlap_or_gap(self) -> None:
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=8)]
        segments = plan_daily_segments(days, workers=3, checkpoint_dir=Path("checkpoints"))
        self.assertEqual([len(segment.days) for segment in segments], [3, 3, 2])
        self.assertEqual([day for segment in segments for day in segment.days], days)
        self.assertEqual([checkpoint_day(segment.checkpoint_path) for segment in segments], ["20210504", "20210507", "20210510"])
        with self.assertRaisesRegex(ValueError, "gap"):
            plan_daily_segments([days[0], days[2]], workers=2, checkpoint_dir=Path("checkpoints"))

    def test_daily_segment_plan_balances_certified_scoring_load(self) -> None:
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=8)]
        weights = {day: (1 if index < 4 else 10) for index, day in enumerate(days)}
        segments = plan_daily_segments(days, workers=2, checkpoint_dir=Path("checkpoints"), scoring_weights=weights)
        self.assertEqual([len(segment.days) for segment in segments], [6, 2])
        self.assertEqual([segment.scoring_weight for segment in segments], [24, 20])

    def test_segment_checkpoints_hold_exact_causal_start_and_are_reused(self) -> None:
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=4)]
        with TemporaryDirectory() as directory:
            checkpoint_dir = Path(directory)
            segments = plan_daily_segments(days, workers=2, checkpoint_dir=checkpoint_dir)

            def events(_root: Path, day: str, **_kwargs) -> list[TickReplayEvent]:
                return [TickReplayEvent((days.index(day) + 1, 0), "uniswap_v3", "swap", {"pool": {}}, 0)]

            class TrackingReplay(TickReplayState):
                def apply(self, event: TickReplayEvent) -> None:
                    self.token_decimals[f"seen-{days[event.order[0] - 1]}"] = 1

            with (
                patch("scripts.build_transaction_state_frontier.new_tick_replay", side_effect=lambda: TrackingReplay(token_decimals={})),
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", side_effect=events),
            ):
                first = materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=Path("state"))
                second = materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=Path("state"))
            first_state = load_replay_checkpoint(segments[0].checkpoint_path, engine_key="engine", pre_day=days[0])
            second_state = load_replay_checkpoint(segments[1].checkpoint_path, engine_key="engine", pre_day=days[2])
        self.assertEqual(first, (2, 2))
        self.assertEqual(second, (0, 0))
        self.assertEqual(first_state.token_decimals, {})
        self.assertEqual(second_state.token_decimals, {f"seen-{days[0]}": 1, f"seen-{days[1]}": 1})

    def test_parallel_checkpoint_partial_resume_skips_prior_days_and_preserves_causal_state(self) -> None:
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=6)]
        events_by_day = {
            day: [TickReplayEvent((index + 1, 0), "uniswap_v3", "liquidity", {"pool": {"id": "pool"}, "tickLower": str(index), "tickUpper": str(index + 1), "amount": str(index + 2)}, 1)]
            for index, day in enumerate(days)
        }
        loaded_days: list[str] = []

        def events(_root: Path, day: str, **_kwargs) -> list[TickReplayEvent]:
            loaded_days.append(day)
            return events_by_day[day]

        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_dir = root / "checkpoints"
            segments = plan_daily_segments(days, workers=3, checkpoint_dir=checkpoint_dir)
            with (
                patch("scripts.build_transaction_state_frontier.new_tick_replay", return_value=TickReplayState(token_decimals={}, quarantined_pools={"uniswap_v4": set()}, initialization_status_by_venue={"uniswap_v3": {"pool": "quote_supported"}})),
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", side_effect=events),
            ):
                self.assertEqual(materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=root / "state"), (4, 3))
            final_path = segments[-1].checkpoint_path
            expected = load_replay_checkpoint(final_path, engine_key="engine", pre_day=days[4])
            final_path.unlink()
            loaded_days.clear()
            with (
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", side_effect=events),
                patch("scripts.build_transaction_state_frontier.new_tick_replay", side_effect=AssertionError("partial resume must not create an empty replay")),
            ):
                self.assertEqual(materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=root / "state"), (2, 1))
            resumed = load_replay_checkpoint(final_path, engine_key="engine", pre_day=days[4])
            self.assertEqual(loaded_days, days[2:4])
            for field in REPLAY_CAUSAL_FIELDS:
                self.assertEqual(getattr(resumed, field), getattr(expected, field), field)
            middle_path = segments[1].checkpoint_path
            expected_middle = load_replay_checkpoint(middle_path, engine_key="engine", pre_day=days[2])
            later_checkpoint_bytes = final_path.read_bytes()
            middle_path.unlink()
            loaded_days.clear()
            with (
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", side_effect=events),
                patch("scripts.build_transaction_state_frontier.new_tick_replay", side_effect=AssertionError("an earlier checkpoint must resume before its own boundary")),
            ):
                self.assertEqual(materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=root / "state"), (2, 1))
            restored_middle = load_replay_checkpoint(middle_path, engine_key="engine", pre_day=days[2])
            self.assertEqual(loaded_days, days[:2])
            self.assertEqual(final_path.read_bytes(), later_checkpoint_bytes)
            for field in REPLAY_CAUSAL_FIELDS:
                self.assertEqual(getattr(restored_middle, field), getattr(expected_middle, field), field)

    def test_parallel_checkpoint_materializer_matches_sequential_replay(self) -> None:
        usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        token_x = "0xb000000000000000000000000000000000000001"
        dai = "0x6b175474e89094c44da98b954eedeac495271d0f"
        frax = "0x853d955acef822db058eb8505911ed77f175b99e"
        lusd = "0x5f98805a4e8be255a32880fdec7f6728c6568ba0"
        v3_pool = compute_pool_address(usdc, token_x, 3_000)
        linked_v3_pool = compute_pool_address(dai, token_x, 500)
        v4_pool = "0x" + "4" * 64
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=5)]

        def swap(venue: str, pool: str, token0: str, token1: str, *, block: int, log_index: int, tick: int = 0, tick_spacing: int = 60) -> TickReplayEvent:
            decimals0, decimals1 = (6, 18) if (token0, token1) == (usdc, token_x) else (18, 18)
            sqrt_price_x96 = int((1 << 96) * (10 ** ((decimals1 - decimals0) / 2)))
            row = {
                "id": f"0x{block:x}#{log_index}",
                "transaction": {"id": f"0x{block:x}", "blockNumber": str(block), "timestamp": str(block)},
                "timestamp": str(block),
                "logIndex": str(log_index),
                "amount0": "1",
                "amount1": "-1",
                "sqrtPriceX96": str(sqrt_price_x96),
                "tick": str(tick),
                "pool": {
                    "id": pool,
                    "feeTier": 3_000 if venue == "uniswap_v3" else 500,
                    "tickSpacing": tick_spacing if venue == "uniswap_v4" else 60,
                    "hooks": "0x0000000000000000000000000000000000000000",
                    "token0": {"id": token0, "symbol": "T0", "decimals": decimals0},
                    "token1": {"id": token1, "symbol": "T1", "decimals": decimals1},
                },
            }
            return TickReplayEvent((block, log_index), venue, "swap", row)

        def liquidity(venue: str, pool: str, *, block: int, log_index: int, amount: int) -> TickReplayEvent:
            return TickReplayEvent((block, log_index), venue, "liquidity", {"pool": {"id": pool}, "tickLower": "-10", "tickUpper": "10", "amount": str(amount)}, 1)

        def initialize(event: TickReplayEvent, *, log_index: int) -> TickReplayEvent:
            row = {**event.row, "id": f"0x9#{log_index}", "transaction": {"id": "0x9", "blockNumber": "9"}, "logIndex": str(log_index)}
            return TickReplayEvent((9, log_index), event.venue, "initialize", row)

        first_v3_swap = swap("uniswap_v3", v3_pool, usdc, token_x, block=10, log_index=2)
        linked_v3_swap = swap("uniswap_v3", linked_v3_pool, dai, token_x, block=10, log_index=10)
        first_v4_swap = swap("uniswap_v4", v4_pool, lusd, frax, block=10, log_index=21, tick_spacing=10)

        events_by_day = {
            days[0]: [
                initialize(first_v3_swap, log_index=0),
                initialize(linked_v3_swap, log_index=1),
                initialize(first_v4_swap, log_index=2),
                liquidity("uniswap_v3", v3_pool, block=10, log_index=1, amount=1_000),
                *[swap("uniswap_v3", v3_pool, usdc, token_x, block=10, log_index=index) for index in range(2, 8)],
                *[swap("uniswap_v3", linked_v3_pool, dai, token_x, block=10, log_index=index) for index in range(10, 16)],
                liquidity("uniswap_v4", v4_pool, block=10, log_index=20, amount=2_000),
                swap("uniswap_v4", v4_pool, lusd, frax, block=10, log_index=21, tick_spacing=10),
            ],
            days[1]: [],
            days[2]: [
                liquidity("uniswap_v3", v3_pool, block=30, log_index=1, amount=500),
                *[swap("uniswap_v3", v3_pool, usdc, token_x, block=30, log_index=index, tick=index) for index in range(2, 8)],
                *[swap("uniswap_v3", linked_v3_pool, dai, token_x, block=30, log_index=index, tick=index) for index in range(8, 14)],
                liquidity("uniswap_v4", v4_pool, block=30, log_index=20, amount=300),
                swap("uniswap_v4", v4_pool, lusd, frax, block=30, log_index=21, tick_spacing=60),
            ],
            days[3]: [],
            days[4]: [],
        }
        base = TickReplayState(token_decimals={}, quarantined_pools={"uniswap_v4": set()})
        expected: dict[str, dict[str, object]] = {}
        boundaries = {days[0], days[2], days[4]}
        sequential = pickle.loads(pickle.dumps(base))
        for day in days:
            if day in boundaries:
                expected[day] = {field: pickle.loads(pickle.dumps(getattr(sequential, field))) for field in REPLAY_CAUSAL_FIELDS}
            sequential.apply_all(events_by_day[day])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_dir = root / "parallel"
            segments = plan_daily_segments(days, workers=3, checkpoint_dir=checkpoint_dir)
            with (
                patch("scripts.build_transaction_state_frontier.new_tick_replay", return_value=base),
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", side_effect=lambda _root, day, **_kwargs: events_by_day[day]),
                patch("scripts.build_transaction_state_frontier.interruptible_process_pool", side_effect=inline_process_pool),
            ):
                result = materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=root / "state", raw_root=root / "raw", workers=3)
            observed = {day: load_replay_checkpoint(checkpoint_dir / f"pre_{day}.pkl", engine_key="engine", pre_day=day) for day in sorted(boundaries)}
        self.assertEqual(result, (4, 3))
        for day, replay in observed.items():
            for field in REPLAY_CAUSAL_FIELDS:
                self.assertEqual(getattr(replay, field), expected[day][field], f"{day} {field}")
        self.assertNotIn(v3_pool, observed[days[2]].swap_samples)
        self.assertIn(v3_pool, observed[days[2]].states_by_venue.get("uniswap_v3", {}))
        self.assertEqual(observed[days[2]].states_by_venue["uniswap_v4"][v4_pool].fee_pips, 500)
        self.assertEqual(observed[days[2]].states_by_venue["uniswap_v4"][v4_pool].tick_spacing, 10)
        self.assertEqual(observed[days[4]].states_by_venue["uniswap_v3"][v3_pool].log_index, 7)
        self.assertEqual(observed[days[4]].states_by_venue["uniswap_v3"][linked_v3_pool].log_index, 13)
        self.assertIn(v4_pool, observed[days[4]].quarantined_pools["uniswap_v4"])
        self.assertNotIn(v4_pool, observed[days[4]].states_by_venue["uniswap_v4"])

    def test_replay_shard_contract_is_spawn_serializable(self) -> None:
        task = ReplayShardTask(0, ("20210504",), Path("state"), Path("raw"), Path("events.pkl"))
        result = ReplayShardResult(0, task.days, task.output_path, 12)
        self.assertEqual(pickle.loads(pickle.dumps(task)), task)
        self.assertEqual(pickle.loads(pickle.dumps(result)), result)

    def test_replay_shard_reduce_fails_closed_on_causal_disorder(self) -> None:
        event_late = TickReplayEvent((10, 2), "uniswap_v3", "liquidity", {"pool": {"id": "pool"}, "tickLower": "-10", "tickUpper": "10", "amount": "1"}, 1)
        event_early = TickReplayEvent((10, 1), "uniswap_v3", "liquidity", {"pool": {"id": "pool"}, "tickLower": "-10", "tickUpper": "10", "amount": "1"}, 1)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shard = root / "events.pkl"
            with shard.open("wb") as handle:
                pickle.dump(("20210504", event_late), handle)
                pickle.dump(("20210504", event_early), handle)
            result = ReplayShardResult(0, ("20210504",), shard, 2)
            with self.assertRaisesRegex(ValueError, "strict causal order"):
                replay_ordered_event_shards([result], boundaries=("20210504",), checkpoint_paths={"20210504": root / "pre_20210504.pkl"}, checkpoint_engine_key="engine", replay=TickReplayState(initialization_status_by_venue={"uniswap_v3": {"pool": "quote_supported"}}))

    def test_parallel_checkpoint_handles_base_boundary_without_history(self) -> None:
        day = "20210504"
        base = TickReplayState(token_decimals={"token": 18}, quarantined_pools={"uniswap_v4": {"static"}})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            segments = plan_daily_segments([day], workers=1, checkpoint_dir=root / "checkpoints")
            with patch("scripts.build_transaction_state_frontier.new_tick_replay", return_value=base):
                result = materialize_segment_checkpoints(segments, checkpoint_dir=root / "checkpoints", checkpoint_engine_key="engine", target_release=StableTargetContext(), market_state=root / "state", raw_root=root / "raw", workers=2)
            observed = load_replay_checkpoint(segments[0].checkpoint_path, engine_key="engine", pre_day=day)
        self.assertEqual(result, (0, 1))
        self.assertEqual(observed.token_decimals, base.token_decimals)
        self.assertEqual(observed.quarantined_pools, base.quarantined_pools)

    def test_checkpoint_source_drift_leaves_no_live_checkpoint(self) -> None:
        day = "20210504"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_dir = root / "checkpoints"
            segments = plan_daily_segments([day], workers=1, checkpoint_dir=checkpoint_dir)
            with (
                patch("scripts.build_transaction_state_frontier.new_tick_replay", return_value=TickReplayState()),
                self.assertRaisesRegex(RuntimeError, "exact-source drift"),
            ):
                materialize_segment_checkpoints(
                    segments,
                    checkpoint_dir=checkpoint_dir,
                    checkpoint_engine_key="engine",
                    target_release=DriftingTargetContext(fail_on=2),
                    market_state=root / "state",
                )
            self.assertFalse(segments[0].checkpoint_path.exists())

    def test_daily_source_drift_leaves_no_live_day_bundle(self) -> None:
        day = "20210504"

        def score(_day, _events, _replay, _v2, _vehicles, _release):
            return (
                pd.DataFrame({"day": [day], "route_id": ["route"]}),
                pd.DataFrame(),
                {"day": day, "scored_routes": 1, "rejected_routes": 0},
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            day_cache = root / "cache"
            segments = plan_daily_segments([day], workers=1, checkpoint_dir=root / "checkpoints")
            with (
                patch("scripts.build_transaction_state_frontier.load_replay_checkpoint", return_value=TickReplayState()),
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", return_value=[]),
                patch("scripts.build_transaction_state_frontier.load_v2_replay_day", return_value=object()),
                patch("scripts.build_transaction_state_frontier.score_day", side_effect=score),
                self.assertRaisesRegex(RuntimeError, "exact-source drift"),
            ):
                run_daily_segments(
                    segments,
                    workers=1,
                    checkpoint_engine_key="checkpoint",
                    day_cache=day_cache,
                    frontier_engine_key="frontier",
                    frontier_input_key="input",
                    vehicles=(),
                    target_release=DriftingTargetContext(fail_on=2),
                    market_state=root / "state",
                )
            self.assertFalse(any(day_cache.glob("*")))

    def test_serial_and_parallel_segments_write_frame_equivalent_days(self) -> None:
        days = [day.strftime("%Y%m%d") for day in pd.date_range("2021-05-04", periods=4)]
        release = TargetRelease("daily", "1" * 64, Path("pointer"), Path("manifest"), tuple(Path("day_generation") / "days" / f"{day}.json" for day in days), tuple(days), {})

        class FakeReplay:
            def __init__(self, position: int):
                self.position = position

        def load_checkpoint(path: Path, **_kwargs):
            return FakeReplay(days.index(checkpoint_day(path)))

        def score(day, _events, replay, _v2, _vehicles, _release):
            self.assertEqual(day, days[replay.position])
            value = replay.position
            replay.position += 1
            panel = pd.DataFrame({"day": [day], "route_id": [f"route-{day}"], "causal_position": [value]})
            return panel, pd.DataFrame(), {"day": day, "scored_routes": 1, "rejected_routes": 0}

        with TemporaryDirectory() as directory:
            root = Path(directory)
            serial_cache = root / "serial"
            parallel_cache = root / "parallel"
            serial_segments = plan_daily_segments(days, workers=1, checkpoint_dir=root / "serial-checkpoints")
            parallel_segments = plan_daily_segments(days, workers=2, checkpoint_dir=root / "parallel-checkpoints")
            common = {"checkpoint_engine_key": "checkpoint", "frontier_engine_key": "frontier", "frontier_input_key": "input", "vehicles": (), "target_release": StableTargetContext(), "market_state": Path("state")}
            with (
                patch("scripts.build_transaction_state_frontier.load_replay_checkpoint", side_effect=load_checkpoint),
                patch("scripts.build_transaction_state_frontier.load_tick_day_events", return_value=[]),
                patch("scripts.build_transaction_state_frontier.load_v2_replay_day", return_value=object()),
                patch("scripts.build_transaction_state_frontier.score_day", side_effect=score),
                patch("scripts.build_transaction_state_frontier.interruptible_process_pool", side_effect=inline_process_pool),
            ):
                serial_support = run_daily_segments(serial_segments, workers=1, day_cache=serial_cache, **common)
                parallel_support = run_daily_segments(parallel_segments, workers=2, day_cache=parallel_cache, **common)
            serial_panel = pd.concat([pd.read_parquet(serial_cache / f"{day}.parquet") for day in days], ignore_index=True)
            parallel_panel = pd.concat([pd.read_parquet(parallel_cache / f"{day}.parquet") for day in days], ignore_index=True)
        self.assertEqual(serial_support, parallel_support)
        pd.testing.assert_frame_equal(serial_panel, parallel_panel)

    def test_segment_worker_reuses_completed_days_without_rescoring(self) -> None:
        days = ("20210504", "20210505")
        release = TargetRelease("daily", "1" * 64, Path("pointer"), Path("manifest"), (), days, {})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            for day in days:
                write_cached_day(cache, day, pd.DataFrame({"day": [day], "route_id": [f"route-{day}"]}), pd.DataFrame(), {"day": day, "scored_routes": 1, "rejected_routes": 0}, engine_key="frontier", input_key="input")
            segment = plan_daily_segments(list(days), workers=1, checkpoint_dir=root / "checkpoints")[0]
            task = DailySegmentTask(segment, "checkpoint", cache, root / "staging", "frontier", "input", (), release, Path("state"))
            with (
                patch("scripts.build_transaction_state_frontier.load_replay_checkpoint", return_value=TickReplayState()),
                patch("scripts.build_transaction_state_frontier.warm_tick_day") as warm,
                patch("scripts.build_transaction_state_frontier.score_day") as score,
                patch("scripts.build_transaction_state_frontier.write_cached_day") as write,
            ):
                result = score_daily_segment(task)
        self.assertEqual((result.scored_days, result.cached_days), (0, 2))
        self.assertEqual(warm.call_count, 2)
        score.assert_not_called()
        write.assert_not_called()

    def test_segment_task_is_spawn_serializable(self) -> None:
        days = ["20210504", "20210505"]
        segment = plan_daily_segments(days, workers=1, checkpoint_dir=Path("checkpoints"))[0]
        release = TargetRelease("daily", "1" * 64, Path("pointer"), Path("manifest"), (Path("day"),), tuple(days), {"full_daily_dates": 2})
        task = DailySegmentTask(segment, "checkpoint", Path("cache"), Path("staging"), "frontier", "input", (WETH,), release, Path("state"))
        self.assertEqual(pickle.loads(pickle.dumps(task)), task)

    def test_worker_failure_prevents_daily_publication(self) -> None:
        days = ["20210504", "20210505"]
        release = TargetRelease("daily", "1" * 64, Path("pointer"), Path("manifest"), tuple(Path("day_generation") / "days" / f"{day}.json" for day in days), tuple(days), {})
        replay_lease = type(
            "ReplayLease",
            (),
            {
                "existing_paths": (),
                "content_identity_sha256": "replay",
                "assert_current": lambda self: None,
            },
        )()
        with (
            patch("sys.argv", ["build_transaction_state_frontier.py", "--daily-calendar", "--workers", "2"]),
            patch("scripts.build_transaction_state_frontier.require_node_d_release"),
            patch(
                "scripts.build_transaction_state_frontier.current_artifacts",
                return_value=nullcontext(),
            ),
            patch("scripts.build_transaction_state_frontier.available_days", return_value=days),
            patch("scripts.build_transaction_state_frontier.require_full_daily_target_release", return_value=release),
            patch.object(TargetRelease, "content_identity_sha256", new_callable=PropertyMock, return_value="source"),
            patch.object(TargetRelease, "assert_current"),
            patch("scripts.build_transaction_state_frontier.transaction_frontier_audit_days", return_value=days),
            patch("scripts.build_transaction_state_frontier.require_frontier_audit_gate", return_value=(1.0, 1.0, 1.0)),
            patch(
                "scripts.build_transaction_state_frontier.sparse_replay_history_lease",
                return_value=replay_lease,
            ) as replay_history,
            patch(
                "scripts.build_transaction_state_frontier.current_target_release",
                return_value=nullcontext(),
            ),
            patch(
                "scripts.build_transaction_state_frontier.current_file_lineage",
                return_value=nullcontext(),
            ),
            patch("scripts.build_transaction_state_frontier.frontier_cache_identity", return_value=("frontier", "input", "generation")),
            patch("scripts.build_transaction_state_frontier.load_cached_day_support", return_value=None),
            patch("scripts.build_transaction_state_frontier.replay_checkpoint_engine_key", return_value="checkpoint"),
            patch("scripts.build_transaction_state_frontier.target_day_scoring_weights", return_value={day: 1 for day in days}),
            patch("scripts.build_transaction_state_frontier.materialize_segment_checkpoints", return_value=(1, 2)),
            patch("scripts.build_transaction_state_frontier.run_daily_segments", side_effect=RuntimeError("worker failed")),
            patch("scripts.build_transaction_state_frontier.publish_full_daily_frontier") as publish,
        ):
            result = main()
        self.assertEqual(result, 1)
        replay_history.assert_called_once_with(days)
        publish.assert_not_called()

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
            inputs = [canonical_input]
            rows = assemble_cached_output(
                    root,
                    [
                        {"day": "20250101", "scored_routes": 1},
                        {"day": "20250102", "scored_routes": 1},
                    ],
                    suffix=".parquet",
                    count_column="scored_routes",
                    output=output,
                    inputs=inputs,
                    notes="test",
                    engine_key="engine",
                    input_key="input",
                )
            assembled = pd.read_parquet(output)
            manifest_path = inputs[1]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(rows, 2)
        self.assertEqual(len(assembled), 2)
        self.assertEqual(inputs[0], canonical_input)
        self.assertEqual(manifest_path.name, "daily.parquet.ordered-shards.json")
        self.assertEqual(
            [path.name for path in inputs[2:]],
            ["20250101.support.json", "20250102.support.json"],
        )
        self.assertEqual(len(manifest["ordered_shard_manifest_root"]), 64)
        self.assertEqual([entry["day"] for entry in manifest["entries"]], ["20250101", "20250102"])

    def test_assembly_exposes_every_marker_to_canonical_release_provenance(self) -> None:
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
            inputs = []
            assemble_cached_output(
                    day_cache,
                    [
                        {"day": "20250101", "scored_routes": 1},
                        {"day": "20250102", "scored_routes": 1},
                    ],
                    suffix=".parquet",
                    count_column="scored_routes",
                    output=output,
                    inputs=inputs,
                    notes="test",
                    engine_key="engine",
                    input_key="input",
                )
            self.assertIn(day_cache / "daily.parquet.ordered-shards.json", inputs)
            self.assertIn(day_cache / "20250101.support.json", inputs)
            self.assertIn(day_cache / "20250102.support.json", inputs)

    def test_empty_day_preserves_calendar_support(self) -> None:
        empty_replay = V2ReplayDay({}, {}, {}, {}, {}, {})
        release = TargetRelease("audit", "1" * 64, Path("pointer"), Path("manifest"), (), ("20200214",), {})
        released_support = {"all_exact_two_leg_routes": 0, "exact_venue_two_leg_routes": 0}
        with patch("scripts.build_transaction_state_frontier.read_target_day", return_value=(pd.DataFrame(columns=["leg1_venue", "leg2_venue"]), released_support)):
            targets, rejections, support = load_target_routes("20200214", release, empty_replay)
        self.assertEqual(targets, [])
        self.assertEqual(rejections, [])
        self.assertEqual(support["all_exact_two_leg_routes"], 0)
        self.assertEqual(support["exact_venue_two_leg_routes"], 0)


if __name__ == "__main__":
    unittest.main()
