from __future__ import annotations

import datetime as dt
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts.fetch import (
    fetch_raw_market_data,
    supervise_raw_fetch,
)
from scripts.process import build_market_state
from scripts.fetch.fetch_raw_market_data import (
    build_parser,
    cmd_coverage,
    cmd_fetch,
    cmd_repair_meta,
    coverage_report,
    coverage_has_gaps,
    effective_range,
    fetch_gap_days,
    indexed_metadata_streams,
    missing_streams,
    research_sample_end_exclusive,
    required_streams_by_source,
    sparse_days,
)

from ddvc.fetch.raw import raw_path, where_for_entity
from ddvc.fetch.graph import GraphClient
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import get_source, iter_days, last_complete_month_exclusive
from ddvc.reconstruct import RAW_MARKET_DATA_LOCK as RECONSTRUCT_RAW_MARKET_DATA_LOCK
from ddvc.runtime import exclusive_job


class FetchPlanningTests(unittest.TestCase):
    def test_repair_meta_is_routed_through_the_existing_fetch_owner(self) -> None:
        args = build_parser().parse_args(
            [
                "repair-meta",
                "--dex",
                "uniswap_v2",
                "--streams",
                "mints",
                "burns",
                "--dry-run",
            ]
        )
        self.assertIs(args.func, cmd_repair_meta)

    def test_metadata_coverage_requires_a_row_ledger_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meta.json"
            path.write_text(
                '{"streams":{"mints":{"rows":0,"path":"mints.gz"},'
                '"burns":{"rows":2},"swaps":{"path":"swaps.gz"}}}'
            )
            self.assertEqual(indexed_metadata_streams(path), {"mints"})

    def test_metadata_coverage_requires_the_exact_installed_stream_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "meta.json"
            installed = root / "mints.jsonl.gz"
            metadata.write_text(
                '{"streams":{"mints":{"rows":2,"path":"wrong.jsonl.gz"}}}'
            )
            self.assertEqual(
                indexed_metadata_streams(
                    metadata,
                    expected_paths={"mints": installed},
                ),
                set(),
            )

    def test_metadata_coverage_ignores_host_prefix_but_not_source_or_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "meta.json"
            metadata.write_text(
                '{"streams":{"mints":{"rows":2,"path":'
                '"/source-host/project/data/raw/thegraph/uniswap_v2/'
                'uniswap_v2_mints_20250101.jsonl.gz"}}}'
            )
            expected = Path(
                "/worker-host/checkout/data/raw/thegraph/uniswap_v2/"
                "uniswap_v2_mints_20250101.jsonl.gz"
            )
            self.assertEqual(
                indexed_metadata_streams(
                    metadata,
                    expected_paths={"mints": expected},
                ),
                {"mints"},
            )
            wrong_source = expected.parent.parent / "sushiswap_v2" / expected.name
            self.assertEqual(
                indexed_metadata_streams(
                    metadata,
                    expected_paths={"mints": wrong_source},
                ),
                set(),
            )
            wrong_filename = expected.with_name("uniswap_v2_mints_20250102.jsonl.gz")
            self.assertEqual(
                indexed_metadata_streams(
                    metadata,
                    expected_paths={"mints": wrong_filename},
                ),
                set(),
            )

    def test_missing_files_only_does_not_treat_an_installed_unindexed_stream_as_absent(self) -> None:
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "swaps.jsonl.gz"
            raw.touch()
            with (
                patch.object(fetch_raw_market_data, "stream_target", return_value=raw),
                patch.object(fetch_raw_market_data, "metadata_target", return_value=Path(directory) / "missing-meta.json"),
            ):
                self.assertEqual(missing_streams("uniswap_v3", day, ["swaps"]), ["swaps"])
                self.assertEqual(missing_streams("uniswap_v3", day, ["swaps"], include_unindexed=False), [])

    def test_one_frozen_graph_head_is_passed_to_every_planned_day(self) -> None:
        start = dt.date(2022, 1, 1)
        end = dt.date(2022, 1, 3)
        with (
            patch.object(fetch_raw_market_data, "read_source_day_metadata", return_value={}),
            patch.object(fetch_raw_market_data, "missing_streams", return_value=["swaps"]),
            patch.object(fetch_raw_market_data, "frozen_graph_head", return_value=999) as frozen,
            patch.object(fetch_raw_market_data, "fetch_source_day", return_value={"streams": {}}) as fetch,
            patch("builtins.print"),
        ):
            fetch_gap_days("uniswap_v3", start, end, streams={"swaps"}, overwrite=False, dry_run=False, dune_sleep=0, max_retries=0)
        frozen.assert_called_once()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual({call.kwargs["head_block_at_fetch"] for call in fetch.call_args_list}, {999})

    def test_supervisor_counts_unindexed_graph_streams_without_conflating_dune_metadata(self) -> None:
        report = {
            "graph": {"backend": "thegraph", "missing": {"swaps": 2, "daily": 100}, "missing_required": {"swaps": 2}, "unindexed_meta": {"swaps": 3, "mints": 100}, "unindexed_required_meta": {"swaps": 3}},
            "dune": {"backend": "dune", "missing": {"swaps": 5, "daily": 100}, "missing_required": {"swaps": 5}, "unindexed_meta": {"swaps": 7}},
        }
        self.assertEqual(supervise_raw_fetch.missing_total(report), 10)
        self.assertEqual(supervise_raw_fetch.missing_sources(report), [("graph", ["swaps"]), ("dune", ["swaps"])])
        self.assertEqual(supervise_raw_fetch.missing_sources(report, include_unindexed=False), [("graph", ["swaps"]), ("dune", ["swaps"])])

    def test_supervisor_fetches_only_absent_required_files_then_stops_for_adjudication(self) -> None:
        initial = {"graph": {"backend": "thegraph", "missing": {"swaps": 1, "daily": 100}, "missing_required": {"swaps": 1}, "unindexed_required_meta": {"swaps": 1}}}
        final = {"graph": {"backend": "thegraph", "missing": {"swaps": 0, "daily": 100}, "missing_required": {"swaps": 0}, "unindexed_required_meta": {"swaps": 1}}}
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "supervisor.jsonl"
            with (
                patch.object(supervise_raw_fetch, "coverage", side_effect=[initial, final]),
                patch.object(supervise_raw_fetch, "run", return_value=0) as run,
                patch("sys.argv", ["supervise_raw_fetch.py", "--end", "2026-07-01", "--log", str(log), "--cycles", "1"]),
            ):
                self.assertEqual(supervise_raw_fetch.main(), 3)
            invoked = run.call_args.args[0]
            self.assertIn("--required-only", invoked)
            self.assertIn("--missing-files-only", invoked)

    def test_strict_coverage_fails_any_missing_or_unindexed_perimeter(self) -> None:
        complete = {
            "venue": {
                "missing_meta": 0,
                "missing": {"swaps": 0},
                "unindexed_meta": {"swaps": 0},
            }
        }
        self.assertFalse(coverage_has_gaps(complete))
        for field in ("missing", "unindexed_meta"):
            broken = {"venue": {**complete["venue"], field: {"swaps": 1}}}
            self.assertTrue(coverage_has_gaps(broken))
        self.assertTrue(
            coverage_has_gaps({"venue": {**complete["venue"], "missing_meta": 1}})
        )

    def test_strict_coverage_ignores_visible_optional_gaps(self) -> None:
        report = {
            "venue": {
                "missing_required_meta": 0,
                "missing_required": {"swaps": 0},
                "unindexed_required_meta": {"swaps": 0},
                "missing_optional": {"daily": 10},
                "unindexed_optional_meta": {"daily": 20},
                "missing_meta": 20,
            }
        }
        self.assertFalse(coverage_has_gaps(report))
        report["venue"]["unindexed_required_meta"]["swaps"] = 1
        self.assertTrue(coverage_has_gaps(report))

    def test_required_stream_union_is_derived_from_active_consumers(self) -> None:
        required = required_streams_by_source()
        end = dt.date(2026, 7, 1)
        total = sum(len(iter_days(get_source(venue).genesis, end)) * len(streams) for venue, streams in required.items())
        graph_total = sum(len(iter_days(get_source(venue).genesis, end)) * len(streams) for venue, streams in required.items() if get_source(venue).backend == "thegraph")
        self.assertEqual(total, 41_627)
        self.assertEqual(graph_total, 41_017)
        self.assertEqual(required["uniswap_v1"], frozenset({"swaps"}))
        self.assertEqual(required["fluid"], frozenset({"swaps"}))

    def test_coverage_indexes_required_and_optional_direct_paths(self) -> None:
        source = get_source("uniswap_v3")
        end = source.genesis + dt.timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "meta.json"
            metadata.write_text("{}")
            targets = {stream: root / f"{stream}.jsonl.gz" for stream in ("swaps", "optional")}
            for target in targets.values():
                target.touch()
            with (
                patch.object(fetch_raw_market_data, "available_streams", return_value=["swaps", "optional"]),
                patch.object(fetch_raw_market_data, "required_streams_by_source", return_value={"uniswap_v3": frozenset({"swaps"})}),
                patch.object(fetch_raw_market_data, "metadata_target", return_value=metadata),
                patch.object(fetch_raw_market_data, "stream_target", side_effect=lambda _name, stream, _day: targets[stream]),
                patch.object(fetch_raw_market_data, "indexed_metadata_streams", return_value={"swaps"}) as indexed,
            ):
                report = coverage_report(["uniswap_v3"], {"uniswap_v3": end})
            self.assertEqual(indexed.call_count, 1)
            self.assertEqual(set(indexed.call_args.kwargs["expected_paths"]), {"swaps", "optional"})
            self.assertEqual(report["uniswap_v3"]["unindexed_required_meta"]["swaps"], 0)
            self.assertEqual(report["uniswap_v3"]["unindexed_optional_meta"]["optional"], 1)
            self.assertEqual(report["uniswap_v3"]["optional_streams"], ["optional"])

    def test_fetch_and_materialisation_share_one_raw_data_lock(self) -> None:
        self.assertEqual(
            fetch_raw_market_data.RAW_MUTATION_LOCK,
            build_market_state.RAW_MARKET_DATA_LOCK,
        )
        self.assertEqual(
            fetch_raw_market_data.RAW_MUTATION_LOCK,
            RECONSTRUCT_RAW_MARKET_DATA_LOCK,
        )

    def test_fetch_command_holds_the_shared_raw_mutation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "raw.lock"
            with (
                patch.object(fetch_raw_market_data, "RAW_MUTATION_LOCK", lock),
                patch.object(fetch_raw_market_data, "_cmd_fetch", return_value=7) as inner,
            ):
                self.assertEqual(cmd_fetch(Namespace()), 7)
            inner.assert_called_once()
            self.assertTrue(lock.exists())

    def test_coverage_holds_raw_mutation_lease_through_report_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "raw.lock"
            entered = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []

            def paused_coverage(_args):
                entered.set()
                self.assertTrue(release.wait(timeout=10))
                return 0

            def cover() -> None:
                try:
                    cmd_coverage(Namespace())
                except BaseException as error:
                    errors.append(error)

            with (
                patch.object(fetch_raw_market_data, "RAW_MUTATION_LOCK", lock),
                patch.object(fetch_raw_market_data, "_cmd_coverage", side_effect=paused_coverage),
            ):
                coverage = threading.Thread(target=cover)
                coverage.start()
                self.assertTrue(entered.wait(timeout=10))
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with exclusive_job(lock, job="synthetic raw writer"):
                        self.fail("raw writer entered during coverage reporting")
                release.set()
                coverage.join(timeout=10)
            self.assertFalse(coverage.is_alive())
            self.assertEqual(errors, [])

    def test_sparse_repair_calendar_is_unique_sorted_and_genesis_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "days.txt"
            path.write_text("# repair\n2024-10-26\n2024-10-25\n2024-10-26\n")
            self.assertEqual(
                sparse_days(path, "uniswap_v2"),
                [dt.date(2024, 10, 25), dt.date(2024, 10, 26)],
            )
            path.write_text("2020-05-04\n")
            with self.assertRaisesRegex(ValueError, "precedes genesis"):
                sparse_days(path, "uniswap_v2")

    def test_graph_response_has_true_body_deadline(self) -> None:
        class Response:
            def iter_content(self, *, chunk_size: int):
                self.chunk_size = chunk_size
                yield b'{"data":'
                yield b'{}}'

        client = object.__new__(GraphClient)
        client.response_deadline_seconds = 2
        response = Response()
        with patch("ddvc.fetch.graph.time.monotonic", side_effect=[0, 1, 3]):
            with self.assertRaisesRegex(TimeoutError, "body deadline"):
                client._response_json(response)
        self.assertEqual(response.chunk_size, 64 * 1024)

    def test_graph_response_decodes_within_deadline(self) -> None:
        class Response:
            def iter_content(self, *, chunk_size: int):
                yield b'{"data":'
                yield b'{}}'

        client = object.__new__(GraphClient)
        client.response_deadline_seconds = 2
        with patch("ddvc.fetch.graph.time.monotonic", side_effect=[0, 1, 2]):
            self.assertEqual(client._response_json(Response()), {"data": {}})

    def test_last_complete_month_exclusive(self) -> None:
        self.assertEqual(last_complete_month_exclusive(dt.date(2026, 7, 1)), dt.date(2026, 7, 1))
        self.assertEqual(last_complete_month_exclusive(dt.date(2026, 7, 31)), dt.date(2026, 7, 1))

    def test_fetch_default_end_is_locked_research_sample_not_current_month(self) -> None:
        self.assertEqual(research_sample_end_exclusive(), dt.date(2026, 7, 1))
        self.assertEqual(effective_range("fluid", "genesis", None)[1], dt.date(2026, 7, 1))

    def test_genesis_sources_cover_core_dexes(self) -> None:
        self.assertEqual(get_source("curve").genesis, dt.date(2020, 2, 11))
        self.assertEqual(get_source("curve").genesis_block, 9_461_159)
        self.assertEqual(get_source("uniswap_v1").genesis, dt.date(2018, 11, 2))
        self.assertEqual(get_source("uniswap_v1").backend, "thegraph")
        self.assertEqual(get_source("uniswap_v2").genesis, dt.date(2020, 5, 5))
        self.assertEqual(get_source("uniswap_v2").genesis_block, 10_008_566)
        self.assertEqual(get_source("uniswap_v3").genesis, dt.date(2021, 5, 4))
        self.assertEqual(get_source("uniswap_v3").genesis_block, 12_369_879)
        self.assertEqual(get_source("uniswap_v3").factory_deployment_block, 12_369_621)
        self.assertEqual(get_source("uniswap_v4").genesis, dt.date(2025, 1, 24))
        self.assertEqual(get_source("uniswap_v4").genesis_block, 21_696_375)
        self.assertEqual(get_source("sushiswap_v2").backend, "thegraph")
        self.assertEqual(get_source("sushiswap_v2").graph_path, "deployments/id")
        self.assertEqual(get_source("fluid").genesis_block, 21_071_249)

    def test_schema_overfetches_liquidity_streams(self) -> None:
        streams = {entity.stream for entity in get_schema("uniswap_v3").entities}
        self.assertLessEqual({"swaps", "daily", "mints", "burns"}, streams)
        streams = {entity.stream for entity in get_schema("uniswap_v4").entities}
        self.assertLessEqual({"swaps", "daily", "modify_liquidities"}, streams)
        v4_swaps = next(
            entity for entity in get_schema("uniswap_v4").entities if entity.stream == "swaps"
        )
        self.assertIn("feeTier", v4_swaps.fields)
        self.assertIn("transaction {", v4_swaps.fields)

    def test_where_for_timestamp_and_date_entities(self) -> None:
        day = dt.date(2026, 6, 30)
        timestamp_entity = EntitySpec(stream="swaps", entity="swaps", fields="id")
        self.assertEqual(
            where_for_entity(timestamp_entity, day),
            {"timestamp_gte": "1782777600", "timestamp_lt": "1782864000"},
        )
        date_entity = EntitySpec(stream="daily", entity="poolDayDatas", fields="id", date_field="date")
        self.assertEqual(where_for_entity(date_entity, day), {"date": "1782777600"})

    def test_raw_path_is_partitioned_by_source_stream_and_year(self) -> None:
        path = raw_path("uniswap_v3", "swaps", dt.date(2026, 6, 30))
        self.assertTrue(
            path.as_posix().endswith(
                "data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_20260630.jsonl.gz"
            )
        )

    def test_iter_days_is_half_open(self) -> None:
        self.assertEqual(
            iter_days(dt.date(2026, 6, 29), dt.date(2026, 7, 1)),
            [dt.date(2026, 6, 29), dt.date(2026, 6, 30)],
        )
