from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import audit_v2_refetch_receipts, build_market_state, fetch_raw_market_data
from scripts.fetch_raw_market_data import (
    build_parser,
    cmd_fetch,
    cmd_repair_meta,
    coverage_has_gaps,
    indexed_metadata_streams,
    sparse_days,
)

from ddvc.fetch.raw import raw_path, where_for_entity
from ddvc.fetch.graph import GraphClient
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import get_source, iter_days, last_complete_month_exclusive
from ddvc.reconstruct import RAW_MARKET_DATA_LOCK as RECONSTRUCT_RAW_MARKET_DATA_LOCK


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
            metadata.write_text(
                '{"streams":{"mints":{"rows":2,"path":"'
                + str(installed)
                + '"}}}'
            )
            self.assertEqual(
                indexed_metadata_streams(
                    metadata,
                    expected_paths={"mints": installed},
                ),
                {"mints"},
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

    def test_fetch_and_materialisation_share_one_raw_data_lock(self) -> None:
        self.assertEqual(
            fetch_raw_market_data.RAW_MUTATION_LOCK,
            build_market_state.RAW_MARKET_DATA_LOCK,
        )
        self.assertEqual(
            fetch_raw_market_data.RAW_MUTATION_LOCK,
            RECONSTRUCT_RAW_MARKET_DATA_LOCK,
        )
        self.assertEqual(
            fetch_raw_market_data.RAW_MUTATION_LOCK,
            audit_v2_refetch_receipts.RAW_MARKET_DATA_LOCK,
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

    def test_genesis_sources_cover_core_dexes(self) -> None:
        self.assertEqual(get_source("curve").genesis, dt.date(2020, 2, 11))
        self.assertEqual(get_source("curve").genesis_block, 9_461_159)
        self.assertEqual(get_source("uniswap_v1").genesis, dt.date(2018, 11, 2))
        self.assertEqual(get_source("uniswap_v1").backend, "thegraph")
        self.assertEqual(get_source("uniswap_v2").genesis, dt.date(2020, 5, 5))
        self.assertEqual(get_source("uniswap_v2").genesis_block, 10_008_566)
        self.assertEqual(get_source("uniswap_v3").genesis, dt.date(2021, 5, 4))
        self.assertEqual(get_source("uniswap_v3").genesis_block, 12_369_879)
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
