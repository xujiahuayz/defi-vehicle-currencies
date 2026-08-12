from __future__ import annotations

import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.fetch.graph import build_query
from ddvc.fetch.dune import (
    DUNE_QUERY_END_EXCLUSIVE_FIELD,
    DUNE_QUERY_START_FIELD,
    dune_meta_path,
    dune_query_contract_sha256,
    fetch_dune_month,
)
from ddvc.fetch.raw import (
    committed_source_day_generation_identity,
    RawFetchInvariantError,
    RawRefetchDivergenceError,
    fetch_source_day,
    graph_query_contract_sha256,
    index_existing_stream,
    merge_stream_metadata,
    installed_source_day_paths,
    indexed_metadata_streams,
    promote_source_day,
    raw_stream_metadata_is_current,
    repair_source_day_metadata,
    raw_stream_identity,
    require_mergeable_partial_metadata,
    require_committed_source_day_stream,
    source_day_promotion_record,
    verified_jsonl_gz_rows,
    write_json,
    write_jsonl_gz,
)
from ddvc.provenance import portable_content_sha256
from ddvc.fetch.schemas import EntitySpec, SchemaSpec, get_schema
from ddvc.fetch.sources import get_source
from ddvc.fetch.pool_daily import read_pool_day_values
from ddvc.reconstruct import load_legs
from ddvc.source_records import (
    block_value,
    merge_v4_statics,
    source_event_payload,
    timestamp_value,
    transaction_id,
    v4_pool_quote_supported,
    v4_quote_status,
    v4_statics_complete,
)
from scripts.fetch_raw_market_data import enrich_v4_statics_day


def v3_route_row(identity: str = "current") -> dict[str, object]:
    return {
        "id": identity,
        "transaction": {
            "id": f"tx-{identity}",
            "blockNumber": "1",
            "timestamp": "1640995201",
        },
        "timestamp": "1640995201",
        "pool": {
            "id": "pool",
            "token0": {"id": "token0", "symbol": "T0"},
            "token1": {"id": "token1", "symbol": "T1"},
        },
        "amount0": "1",
        "amount1": "-1",
        "sqrtPriceX96": "79228162514264337593543950336",
        "tick": "0",
        "logIndex": "0",
    }


def fluid_route_row(day: dt.date) -> dict[str, object]:
    return {
        "tx_hash": "0xabc",
        "evt_index": 1,
        "block_number": 18_900_000,
        "block_time": f"{day.isoformat()} 00:00:01.000 UTC",
        "token_sold_address": "token0",
        "token_sold_symbol": "T0",
        "token_sold_amount": 1,
        "token_bought_address": "token1",
        "token_bought_symbol": "T1",
        "token_bought_amount": 2,
        "amount_usd": 2,
        "pool": "pool",
    }


def graph_stream_query_sha256(source_name: str, stream: str) -> str:
    source = get_source(source_name)
    entity = next(
        entity
        for entity in get_schema(source.schema).entities
        if entity.stream == stream
    )
    return graph_query_contract_sha256(entity)


class RawMetaMergeTests(unittest.TestCase):
    def test_dune_fetch_records_exact_query_window_on_every_stream(self) -> None:
        source = get_source("fluid")
        start = dt.date(2024, 11, 1)
        end = dt.date(2024, 11, 3)
        rows = [fluid_route_row(start), fluid_route_row(start + dt.timedelta(days=1))]
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ddvc.fetch.dune._execute_sql", return_value="execution"
        ), patch("ddvc.fetch.dune._await_rows", return_value=rows):
            root = Path(tmp)
            fetch_dune_month(
                source,
                start,
                end,
                streams={"swaps", "daily"},
                skip_existing=False,
                data_root=root,
            )
            expected_hash = dune_query_contract_sha256(source, start, end)
            for day in (start, start + dt.timedelta(days=1)):
                marker = json.loads(
                    dune_meta_path(source.name, day, data_root=root).read_text()
                )
                for stream in ("swaps", "daily"):
                    self.assertEqual(
                        marker["streams"][stream][DUNE_QUERY_START_FIELD],
                        start.isoformat(),
                    )
                    self.assertEqual(
                        marker["streams"][stream][DUNE_QUERY_END_EXCLUSIVE_FIELD],
                        end.isoformat(),
                    )
                    self.assertEqual(
                        marker["streams"][stream]["query_contract_sha256"],
                        expected_hash,
                    )

    def test_dune_fetch_rejects_provider_rows_outside_query_window(self) -> None:
        source = get_source("fluid")
        start = dt.date(2024, 11, 1)
        end = dt.date(2024, 11, 2)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ddvc.fetch.dune._execute_sql", return_value="execution"
        ), patch(
            "ddvc.fetch.dune._await_rows", return_value=[fluid_route_row(end)]
        ):
            with self.assertRaisesRegex(ValueError, "outside the requested query window"):
                fetch_dune_month(
                    source,
                    start,
                    end,
                    streams={"swaps"},
                    skip_existing=False,
                    data_root=Path(tmp),
                )

    def _write_dune_candidate(
        self,
        root: Path,
        day: dt.date,
        *,
        query_start: object,
        query_end_exclusive: object,
        query_contract_sha256: str,
    ) -> None:
        raw, marker = installed_source_day_paths(
            "fluid", "swaps", day, data_root=root
        )
        write_jsonl_gz(raw, [fluid_route_row(day)])
        write_json(
            marker,
            {
                "source": "fluid",
                "day": day.isoformat(),
                "streams": {
                    "swaps": {
                        "rows": 1,
                        "logical_content_sha256": portable_content_sha256(raw),
                        "query_contract_sha256": query_contract_sha256,
                        DUNE_QUERY_START_FIELD: query_start,
                        DUNE_QUERY_END_EXCLUSIVE_FIELD: query_end_exclusive,
                    }
                },
            },
        )

    def test_dune_month_window_promotes_with_exact_recorded_query_contract(self) -> None:
        day = dt.date(2024, 11, 15)
        start = dt.date(2024, 11, 1)
        end = dt.date(2024, 12, 1)
        source = get_source("fluid")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            canonical = root / "canonical"
            self._write_dune_candidate(
                candidate,
                day,
                query_start=start.isoformat(),
                query_end_exclusive=end.isoformat(),
                query_contract_sha256=dune_query_contract_sha256(source, start, end),
            )
            promoted = promote_source_day(
                "fluid",
                day,
                {"swaps"},
                candidate_root=candidate,
                evidence_root=root / "evidence",
                data_root=canonical,
            )
            self.assertEqual(promoted["status"], "committed")
            require_committed_source_day_stream(
                "fluid", "swaps", day, data_root=canonical
            )
            identity = committed_source_day_generation_identity(
                "fluid", "swaps", day, data_root=canonical
            )
            self.assertEqual(len(identity), 64)
            _raw, marker = installed_source_day_paths(
                "fluid", "swaps", day, data_root=canonical
            )
            payload = json.loads(marker.read_text())
            payload["promotion"] = {
                "policy": payload["promotion"]["policy"],
                "promotion_id": payload["promotion"]["promotion_id"],
            }
            marker.write_text(json.dumps(payload))
            self.assertEqual(
                len(
                    committed_source_day_generation_identity(
                        "fluid", "swaps", day, data_root=canonical
                    )
                ),
                64,
            )
            payload["promotion"]["promotion_id"] = "invalid"
            marker.write_text(json.dumps(payload))
            with self.assertRaisesRegex(
                RawFetchInvariantError, "promotion identity"
            ):
                committed_source_day_generation_identity(
                    "fluid", "swaps", day, data_root=canonical
                )
            write_jsonl_gz(_raw, [{"tampered": True}])
            payload["streams"]["swaps"][
                "logical_content_sha256"
            ] = portable_content_sha256(_raw)
            payload["promotion"] = {
                "policy": "raw-source-day-promotion-v1",
                "promotion_id": promoted["promotion_id"],
            }
            marker.write_text(json.dumps(payload))
            with self.assertRaisesRegex(
                RawFetchInvariantError, "promotion identity"
            ):
                committed_source_day_generation_identity(
                    "fluid", "swaps", day, data_root=canonical
                )

    def test_dune_promotion_rejects_window_and_contract_tampering(self) -> None:
        day = dt.date(2024, 11, 15)
        source = get_source("fluid")
        valid_start = dt.date(2024, 11, 1)
        valid_end = dt.date(2024, 12, 1)
        cases = {
            "unparseable": (
                "not-a-date",
                valid_end.isoformat(),
                dune_query_contract_sha256(source, valid_start, valid_end),
            ),
            "reversed": (
                valid_end.isoformat(),
                valid_start.isoformat(),
                dune_query_contract_sha256(source, valid_start, valid_end),
            ),
            "outside_day": (
                "2024-10-01",
                "2024-11-01",
                dune_query_contract_sha256(
                    source, dt.date(2024, 10, 1), dt.date(2024, 11, 1)
                ),
            ),
            "hash_mismatch": (
                valid_start.isoformat(),
                valid_end.isoformat(),
                "0" * 64,
            ),
        }
        for label, (start, end, query_hash) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._write_dune_candidate(
                    root / "candidate",
                    day,
                    query_start=start,
                    query_end_exclusive=end,
                    query_contract_sha256=query_hash,
                )
                with self.assertRaisesRegex(
                    RawFetchInvariantError, "current query provenance"
                ):
                    promote_source_day(
                        "fluid",
                        day,
                        {"swaps"},
                        candidate_root=root / "candidate",
                        evidence_root=root / "evidence",
                        data_root=root / "canonical",
                    )

    def test_verified_reader_rejects_early_exit_without_rehashing_twice(self) -> None:
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, marker = installed_source_day_paths(
                "uniswap_v3", "swaps", day, data_root=root
            )
            write_jsonl_gz(raw, [{"id": "first"}, {"id": "second"}])
            write_json(
                marker,
                {
                    "source": "uniswap_v3",
                    "day": day.isoformat(),
                    "streams": {
                        "swaps": {
                            "logical_content_sha256": portable_content_sha256(raw)
                        }
                    },
                },
            )
            with self.assertRaisesRegex(
                RawFetchInvariantError, "was not exhausted"
            ):
                with verified_jsonl_gz_rows(
                    raw,
                    marker,
                    source_name="uniswap_v3",
                    stream="swaps",
                    day=day,
                ) as rows:
                    next(rows)

    def test_route_loader_enforces_source_day_gate_with_exact_perimeter(self) -> None:
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, marker = installed_source_day_paths(
                "uniswap_v3", "swaps", day, data_root=root
            )
            write_jsonl_gz(raw, [{"id": "row"}])
            write_json(
                marker,
                {
                    "source": "uniswap_v3",
                    "day": day.isoformat(),
                    "streams": {
                        "swaps": {
                            "path": raw_stream_identity(raw),
                            "logical_content_sha256": "0" * 64,
                            "query_contract_sha256": graph_query_contract_sha256(
                                next(
                                    entity
                                    for entity in get_schema("uniswap_v3").entities
                                    if entity.stream == "swaps"
                                )
                            ),
                            "head_block_at_fetch": 20_000_000,
                        }
                    },
                    "promotion": source_day_promotion_record(
                        "uniswap_v3",
                        day,
                        {"swaps": "0" * 64},
                    ),
                },
            )
            with self.assertRaisesRegex(
                RawFetchInvariantError, "disagrees with its commit record"
            ):
                load_legs("uniswap_v3", day.isoformat(), data_root=root)

    def test_pool_daily_reader_rejects_raw_marker_mismatch(self) -> None:
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, marker = installed_source_day_paths(
                "uniswap_v2", "daily", day, data_root=root
            )
            write_jsonl_gz(raw, [{"id": "row"}])
            write_json(
                marker,
                {
                    "source": "uniswap_v2",
                    "day": day.isoformat(),
                    "streams": {
                        "daily": {"logical_content_sha256": "0" * 64}
                    },
                },
            )
            with self.assertRaisesRegex(
                RawFetchInvariantError, "disagrees with its commit record"
            ):
                read_pool_day_values("uniswap_v2", raw.parent)

    def test_source_day_promotion_fails_closed_after_raw_before_marker_and_resumes(self) -> None:
        source = "uniswap_v3"
        stream = "swaps"
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            candidate = root / "candidate"
            evidence = root / "evidence"
            canonical_raw, canonical_marker = installed_source_day_paths(
                source, stream, day, data_root=canonical
            )
            candidate_raw, candidate_marker = installed_source_day_paths(
                source, stream, day, data_root=candidate
            )
            write_jsonl_gz(canonical_raw, [{"id": "legacy"}])
            write_jsonl_gz(candidate_raw, [v3_route_row()])
            for path, marker in (
                (canonical_raw, canonical_marker),
                (candidate_raw, candidate_marker),
            ):
                write_json(
                    marker,
                    {
                        "source": source,
                        "day": day.isoformat(),
                        "streams": {
                            stream: {
                                "rows": 1,
                                "logical_content_sha256": portable_content_sha256(path),
                                **(
                                    {
                                        "query_contract_sha256": graph_stream_query_sha256(
                                            source, stream
                                        ),
                                        "head_block_at_fetch": 20_000_000,
                                    }
                                    if path == candidate_raw
                                    else {}
                                ),
                            }
                        },
                    },
                )
            require_committed_source_day_stream(
                source, stream, day, data_root=canonical
            )

            def crash(_path: Path) -> None:
                raise RuntimeError("injected crash after raw install")

            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                promote_source_day(
                    source,
                    day,
                    {stream},
                    candidate_root=candidate,
                    evidence_root=evidence,
                    data_root=canonical,
                    after_raw_install=crash,
                )
            with self.assertRaisesRegex(
                RawFetchInvariantError, "disagrees with its commit record"
            ):
                require_committed_source_day_stream(
                    source, stream, day, data_root=canonical
                )
            resumed = promote_source_day(
                source,
                day,
                {stream},
                candidate_root=candidate,
                evidence_root=evidence,
                data_root=canonical,
            )
            self.assertEqual(resumed["status"], "committed")
            self.assertEqual(
                require_committed_source_day_stream(
                    source, stream, day, data_root=canonical
                ),
                canonical_raw,
            )
            self.assertEqual(
                promote_source_day(
                    source,
                    day,
                    {stream},
                    candidate_root=candidate,
                    evidence_root=evidence,
                    data_root=canonical,
                )["status"],
                "already_committed",
            )
            self.assertEqual(len(list(evidence.rglob("legacy-*.jsonl.gz"))), 1)
            self.assertEqual(len(list(evidence.rglob("candidate-*.jsonl.gz"))), 1)

    def test_missing_partition_promotion_records_absence_and_resumes_after_crash(self) -> None:
        source = "uniswap_v3"
        stream = "swaps"
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            candidate = root / "candidate"
            evidence = root / "evidence"
            candidate_raw, candidate_marker = installed_source_day_paths(
                source, stream, day, data_root=candidate
            )
            write_jsonl_gz(candidate_raw, [v3_route_row()])
            write_json(
                candidate_marker,
                {
                    "source": source,
                    "day": day.isoformat(),
                    "streams": {
                        stream: {
                            "rows": 1,
                            "logical_content_sha256": portable_content_sha256(
                                candidate_raw
                            ),
                            "query_contract_sha256": graph_stream_query_sha256(
                                source, stream
                            ),
                            "head_block_at_fetch": 20_000_000,
                        }
                    },
                },
            )

            def crash(_path: Path) -> None:
                raise RuntimeError("injected missing-partition crash")

            with self.assertRaisesRegex(RuntimeError, "missing-partition crash"):
                promote_source_day(
                    source,
                    day,
                    {stream},
                    candidate_root=candidate,
                    evidence_root=evidence,
                    data_root=canonical,
                    after_raw_install=crash,
                )
            with self.assertRaisesRegex(RawFetchInvariantError, "uncommitted"):
                require_committed_source_day_stream(
                    source, stream, day, data_root=canonical
                )
            resumed = promote_source_day(
                source,
                day,
                {stream},
                candidate_root=candidate,
                evidence_root=evidence,
                data_root=canonical,
            )
            self.assertEqual(resumed["status"], "committed")
            prepared = json.loads(
                next(evidence.rglob("promotion-prepared.json")).read_text()
            )
            self.assertTrue(
                prepared["retained_streams"][0]["legacy_missing"]
            )
            self.assertIsNone(
                prepared["retained_streams"][0]["legacy_evidence"]
            )
            require_committed_source_day_stream(
                source, stream, day, data_root=canonical
            )

    def test_existing_stream_index_rejects_invalid_gzip_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl.gz"
            path.write_bytes(b"not gzip")
            with self.assertRaisesRegex(RuntimeError, "valid gzip JSONL"):
                index_existing_stream(
                    path,
                    EntitySpec(stream="mints", entity="mints", fields="id"),
                )

    def test_metadata_repair_indexes_installed_stream_and_preserves_other_streams(self) -> None:
        day = dt.date(2022, 1, 1)
        source = get_source("uniswap_v2")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "mints.jsonl.gz"
            metadata = root / "meta.json"
            write_jsonl_gz(
                raw,
                [
                    {"id": "mint-1", "transaction": {"blockNumber": "20"}},
                    {"id": "mint-2", "transaction": {"blockNumber": "10"}},
                ],
            )
            write_json(
                metadata,
                {
                    "source": "uniswap_v2",
                    "day": day.isoformat(),
                    "fetched_at_utc": "2022-01-02T00:00:00+00:00",
                    "streams": {
                        "hourly_reserves": {
                            "status": "fetched",
                            "rows": 24,
                            "min_block": 5,
                            "max_block": 30,
                        }
                    },
                },
            )
            with (
                patch("ddvc.fetch.raw.raw_path", return_value=raw),
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
            ):
                got = repair_source_day_metadata(source, day, streams={"mints"})
            self.assertEqual(set(got["streams"]), {"hourly_reserves", "mints"})
            self.assertEqual(
                got["streams"]["mints"]["status"],
                "indexed_existing_unverified_query_contract",
            )
            self.assertEqual(got["streams"]["mints"]["path"], raw_stream_identity(raw))
            self.assertEqual(got["streams"]["mints"]["rows"], 2)
            self.assertEqual(got["streams"]["mints"]["min_block"], 10)
            self.assertEqual(got["streams"]["mints"]["max_block"], 20)
            self.assertEqual(got["min_block"], 5)
            self.assertEqual(got["max_block"], 30)
            self.assertEqual(got["fetched_at_utc"], "2022-01-02T00:00:00+00:00")
            self.assertIn("metadata_indexed_at_utc", got)

    def test_field_expansion_invalidates_old_raw_query_metadata_and_refetches(self) -> None:
        day = dt.date(2022, 1, 1)
        source = get_source("uniswap_v3")
        source_entity = next(
            entity for entity in get_schema(source.schema).entities if entity.stream == "swaps"
        )
        current = EntitySpec(
            stream=source_entity.stream,
            entity=source_entity.entity,
            fields=source_entity.fields + " liquidity",
            time_field=source_entity.time_field,
            date_field=source_entity.date_field,
        )
        old = EntitySpec(
            stream=current.stream,
            entity=current.entity,
            fields=current.fields.replace(" liquidity", ""),
            time_field=current.time_field,
            date_field=current.date_field,
        )
        self.assertNotEqual(
            graph_query_contract_sha256(old),
            graph_query_contract_sha256(current),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "uniswap_v3_swaps_20220101.jsonl.gz"
            metadata = root / "uniswap_v3_meta_20220101.json"
            with raw.open("wb") as raw_handle:
                with gzip.GzipFile(filename="legacy-name", mode="wb", fileobj=raw_handle, mtime=1) as compressed:
                    compressed.write(b'{"id":"old-swap"}\n')
            canonical_bytes = raw.read_bytes()
            old_stream = {
                "status": "fetched",
                "path": raw_stream_identity(raw),
                "rows": 1,
                "query_contract_sha256": graph_query_contract_sha256(old),
            }
            write_json(
                metadata,
                {
                    "source": source.name,
                    "day": day.isoformat(),
                    "streams": {"swaps": old_stream},
                },
            )
            self.assertFalse(
                raw_stream_metadata_is_current(
                    old_stream,
                    current,
                    expected_path=raw,
                )
            )
            with (
                patch("ddvc.fetch.raw.raw_path", return_value=raw),
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
                patch("ddvc.fetch.raw.GraphClient"),
                patch("ddvc.fetch.raw.graph_keys", return_value=["key"]),
                patch(
                    "ddvc.fetch.raw.get_schema",
                    return_value=SchemaSpec(name=source.schema, entities=(current,)),
                ),
                patch("ddvc.fetch.raw.head_block", return_value=20_000_000),
                patch("ddvc.fetch.raw.where_chunks_for_entity", return_value=[{}]),
                patch("ddvc.fetch.raw.paginate", return_value=[{"id": "old-swap"}]) as paginate,
            ):
                refreshed = fetch_source_day(
                    source,
                    day,
                    streams={"swaps"},
                    skip_existing=True,
                )
            paginate.assert_called()
            self.assertEqual(raw.read_bytes(), canonical_bytes)
            self.assertEqual(refreshed["streams"]["swaps"]["status"], "refetched_identical")
            self.assertEqual(
                refreshed["streams"]["swaps"]["query_contract_sha256"],
                graph_query_contract_sha256(current),
            )
            self.assertEqual(refreshed["streams"]["swaps"]["logical_content_sha256"], portable_content_sha256(raw))
            self.assertEqual(refreshed["streams"]["swaps"]["head_block_at_fetch"], 20_000_000)
            self.assertIn("fetched_at_utc", refreshed["streams"]["swaps"])
            self.assertEqual(paginate.call_args.kwargs["block_number"], 20_000_000)
            self.assertEqual(indexed_metadata_streams(metadata, expected_paths={"swaps": raw}, expected_query_contracts={"swaps": graph_query_contract_sha256(current)}, verify_content_hashes=True), {"swaps"})

    def test_source_day_identity_is_rejected_before_network(self) -> None:
        source = get_source("uniswap_v3")
        day = dt.date(2022, 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "meta.json"
            write_json(metadata, {"source": "wrong-source", "day": day.isoformat()})
            with (
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
                patch("ddvc.fetch.raw.GraphClient") as client,
            ):
                with self.assertRaisesRegex(RawFetchInvariantError, "identity conflicts"):
                    fetch_source_day(source, day, streams={"swaps"})
            client.assert_not_called()

    def test_later_stream_failure_leaves_every_canonical_file_unchanged(self) -> None:
        source = get_source("uniswap_v3")
        day = dt.date(2022, 1, 1)
        entities = (
            EntitySpec(stream="first", entity="firstRows", fields="id"),
            EntitySpec(stream="second", entity="secondRows", fields="id"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {name: root / f"{name}.jsonl.gz" for name in ("first", "second")}
            metadata = root / "meta.json"
            for name, path in paths.items():
                write_jsonl_gz(path, [{"id": f"old-{name}"}])
            write_json(metadata, {"source": source.name, "day": day.isoformat(), "streams": {}})
            before = {name: path.read_bytes() for name, path in paths.items()}
            metadata_before = metadata.read_bytes()
            with (
                patch("ddvc.fetch.raw.get_schema", return_value=SchemaSpec(name=source.schema, entities=entities)),
                patch("ddvc.fetch.raw.raw_path", side_effect=lambda _source, stream, _day: paths[stream]),
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
                patch("ddvc.fetch.raw.GraphClient"),
                patch("ddvc.fetch.raw.graph_keys", return_value=["key"]),
                patch("ddvc.fetch.raw.where_chunks_for_entity", return_value=[{}]),
                patch("ddvc.fetch.raw.paginate", side_effect=[[{"id": "new-first"}], RuntimeError("later stream failed")]),
            ):
                with self.assertRaisesRegex(RuntimeError, "later stream failed"):
                    fetch_source_day(source, day, head_block_at_fetch=20_000_000)
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)
            self.assertEqual(metadata.read_bytes(), metadata_before)

    def test_divergence_preserves_canonical_raw_and_metadata_with_content_addressed_evidence(self) -> None:
        source = get_source("uniswap_v3")
        day = dt.date(2022, 1, 1)
        entity = EntitySpec(stream="swaps", entity="swaps", fields="id")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "uniswap_v3_swaps_20220101.jsonl.gz"
            metadata = root / "uniswap_v3_meta_20220101.json"
            evidence = root / "evidence"
            write_jsonl_gz(raw, [{"id": "old"}])
            write_json(metadata, {"source": source.name, "day": day.isoformat(), "streams": {"swaps": {"path": raw_stream_identity(raw), "rows": 1}}})
            raw_before = raw.read_bytes()
            metadata_before = metadata.read_bytes()
            with (
                patch("ddvc.fetch.raw.get_schema", return_value=SchemaSpec(name=source.schema, entities=(entity,))),
                patch("ddvc.fetch.raw.raw_path", return_value=raw),
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
                patch("ddvc.fetch.raw.RAW_REFETCH_DIVERGENCE_ROOT", evidence),
                patch("ddvc.fetch.raw.GraphClient"),
                patch("ddvc.fetch.raw.graph_keys", return_value=["key"]),
                patch("ddvc.fetch.raw.where_chunks_for_entity", return_value=[{}]),
                patch("ddvc.fetch.raw.paginate", return_value=[{"id": "new"}]),
            ):
                with self.assertRaisesRegex(RawRefetchDivergenceError, "refetch diverged"):
                    fetch_source_day(source, day, streams={"swaps"}, skip_existing=False, head_block_at_fetch=20_000_000)
            self.assertEqual(raw.read_bytes(), raw_before)
            self.assertEqual(metadata.read_bytes(), metadata_before)
            records = list(evidence.rglob("comparison-*.json"))
            self.assertEqual(len(records), 1)
            record = json.loads(records[0].read_text())
            self.assertNotEqual(record["canonical"]["logical_content_sha256"], record["candidate"]["logical_content_sha256"])
            self.assertEqual(record["head_block_at_fetch"], 20_000_000)
            self.assertEqual(len(list(evidence.rglob("*.jsonl.gz"))), 2)

    def test_new_streams_publish_before_the_marker_sidecar_and_roll_back_if_it_fails(self) -> None:
        source = get_source("uniswap_v3")
        day = dt.date(2022, 1, 1)
        entities = (
            EntitySpec(stream="first", entity="firstRows", fields="id"),
            EntitySpec(stream="second", entity="secondRows", fields="id"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {name: root / f"{name}.jsonl.gz" for name in ("first", "second")}
            metadata = root / "meta.json"

            def fail_after_observing_marker_order(_path, _value):
                self.assertTrue(all(path.exists() for path in paths.values()))
                raise OSError("sidecar failed")

            with (
                patch("ddvc.fetch.raw.get_schema", return_value=SchemaSpec(name=source.schema, entities=entities)),
                patch("ddvc.fetch.raw.raw_path", side_effect=lambda _source, stream, _day: paths[stream]),
                patch("ddvc.fetch.raw.meta_path", return_value=metadata),
                patch("ddvc.fetch.raw.GraphClient"),
                patch("ddvc.fetch.raw.graph_keys", return_value=["key"]),
                patch("ddvc.fetch.raw.where_chunks_for_entity", return_value=[{}]),
                patch("ddvc.fetch.raw.paginate", side_effect=[[{"id": "first"}], [{"id": "second"}]]),
                patch("ddvc.fetch.raw.write_json", side_effect=fail_after_observing_marker_order),
            ):
                with self.assertRaisesRegex(OSError, "sidecar failed"):
                    fetch_source_day(source, day, head_block_at_fetch=20_000_000)
            self.assertFalse(metadata.exists())
            self.assertFalse(any(path.exists() for path in paths.values()))

    def test_strict_stream_index_reopens_the_recorded_logical_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "source_swaps_20220101.jsonl.gz"
            metadata = root / "source_meta_20220101.json"
            write_jsonl_gz(raw, [{"id": "row"}])
            write_json(metadata, {"streams": {"swaps": {"path": raw_stream_identity(raw), "rows": 1, "query_contract_sha256": "contract", "logical_content_sha256": "0" * 64}}})
            with patch("ddvc.fetch.raw.portable_content_sha256", side_effect=AssertionError("routine coverage hashed payload")):
                self.assertEqual(indexed_metadata_streams(metadata, expected_paths={"swaps": raw}, expected_query_contracts={"swaps": "contract"}), {"swaps"})
            self.assertEqual(indexed_metadata_streams(metadata, expected_paths={"swaps": raw}, expected_query_contracts={"swaps": "contract"}, verify_content_hashes=True), set())

    def test_partial_refresh_refuses_legacy_metadata_without_stream_ledger(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "legacy metadata"):
            require_mergeable_partial_metadata(
                {"swaps": 100},
                requested_streams={"daily"},
                canonical_streams={"daily", "swaps"},
            )
        require_mergeable_partial_metadata(
            {"streams": {"daily": {"status": "fetched"}}},
            requested_streams={"daily"},
            canonical_streams={"daily", "swaps"},
        )

    def test_graph_query_can_lock_an_immutable_historical_block(self) -> None:
        query = build_query(
            "pools",
            "id",
            {},
            block_number=123,
        )
        self.assertIn("block: { number: 123 }", query)

    def test_graph_pagination_progress_receives_cumulative_rows(self) -> None:
        from ddvc.fetch.graph import paginate

        class Client:
            sleep_seconds = 0

            def __init__(self) -> None:
                self.calls = 0

            def query(self, _query, _variables):
                self.calls += 1
                return {"pools": [{"id": "a"}]} if self.calls == 1 else {"pools": []}

        updates = []
        rows = paginate(
            Client(),
            entity="pools",
            fields="id",
            base_where={},
            page_size=1,
            progress=lambda count, last_id: updates.append((count, last_id)),
        )
        self.assertEqual(rows, [{"id": "a"}])
        self.assertEqual(updates, [(1, "a")])

    def test_raw_gzip_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "rows.jsonl.gz"
            rows = [{"b": 2, "a": 1}]
            write_jsonl_gz(target, rows)
            first = target.read_bytes()
            write_jsonl_gz(target, rows)
            self.assertEqual(target.read_bytes(), first)

    def test_raw_stream_identity_is_portable_across_checkout_prefixes(self) -> None:
        first = Path("/first/checkout/data/raw/thegraph/uniswap_v2/day.jsonl.gz")
        second = Path("/other/checkout/data/raw/thegraph/uniswap_v2/day.jsonl.gz")
        self.assertEqual(raw_stream_identity(first), raw_stream_identity(second))

    def test_transaction_accessors_support_nested_and_scalar_graph_schemas(self) -> None:
        nested = {
            "transaction": {"id": "0xabc", "blockNumber": "123", "timestamp": "456"}
        }
        scalar = {"transaction": "0xdef", "timestamp": "789"}
        self.assertEqual(transaction_id(nested), "0xabc")
        self.assertEqual(block_value(nested), 123)
        self.assertEqual(timestamp_value(nested), 456)
        self.assertEqual(transaction_id(scalar), "0xdef")
        self.assertIsNone(block_value(scalar))
        self.assertEqual(timestamp_value(scalar), 789)

    def test_source_event_payload_excludes_only_provider_entity_id(self) -> None:
        row = {"id": "provider-index", "transaction": "0xabc", "logIndex": "7"}
        self.assertEqual(
            source_event_payload(row),
            {"transaction": "0xabc", "logIndex": "7"},
        )

    def test_v4_static_merge_changes_only_declared_quote_statics(self) -> None:
        primary = {
            "id": "swap-1",
            "amount0": "1",
            "amount1": "-2",
            "transaction": {"id": "tx", "blockNumber": "3"},
            "pool": {
                "id": "pool",
                "token0": {"id": "token-a", "symbol": "A"},
                "token1": {"id": "token-b", "symbol": "B"},
            },
        }
        auxiliary = {
            "id": "swap-1",
            "pool": {
                "id": "pool",
                "feeTier": 500,
                "tickSpacing": 10,
                "hooks": "0x0000000000000000000000000000000000000000",
                "token0": {"id": "token-a", "symbol": "A", "decimals": "18"},
                "token1": {"id": "token-b", "symbol": "B", "decimals": "6"},
            },
        }
        merge_v4_statics(primary, auxiliary)
        self.assertTrue(v4_statics_complete(primary))
        self.assertEqual(primary["amount0"], "1")
        self.assertEqual(primary["amount1"], "-2")
        self.assertEqual(primary["transaction"]["blockNumber"], "3")
        self.assertEqual(primary["pool"]["feeTier"], 500)
        self.assertEqual(primary["pool"]["tickSpacing"], 10)
        self.assertEqual(primary["pool"]["token0"]["decimals"], "18")

    def test_v4_quote_support_excludes_dynamic_fees_and_hooks(self) -> None:
        def row(fee: int, hooks: str = "0x0000000000000000000000000000000000000000", tick_spacing: int = 10):
            return {
                "id": "swap",
                "pool": {
                    "id": "pool",
                    "feeTier": fee,
                    "tickSpacing": tick_spacing,
                    "hooks": hooks,
                    "token0": {"id": "token-a", "decimals": "18"},
                    "token1": {"id": "token-b", "decimals": "6"},
                },
            }

        self.assertTrue(v4_pool_quote_supported(row(9_000)))
        self.assertEqual(v4_quote_status(row(1 << 23)), "dynamic_fee")
        self.assertEqual(v4_quote_status(row(500, "0x0000000000000000000000000000000000000001")), "hooks")
        self.assertEqual(
            v4_quote_status(row(1 << 23, "0x0000000000000000000000000000000000000001")),
            "dynamic_fee_and_hooks",
        )
        self.assertTrue(v4_pool_quote_supported(row(1_000_000, tick_spacing=32_767)))
        for invalid in (row(1_000_001), row((1 << 23) | 1), row(500, tick_spacing=0), row(500, tick_spacing=32_768), row(500, "0x01"), row(500, "0x" + "gg" * 20)):
            self.assertEqual(v4_quote_status(invalid), "invalid_statics")

    def test_v4_static_merge_refuses_a_pool_identity_mismatch(self) -> None:
        primary = {
            "id": "swap-1",
            "pool": {
                "id": "pool-a",
                "token0": {"id": "token-a"},
                "token1": {"id": "token-b"},
            },
        }
        auxiliary = {
            "id": "swap-1",
            "pool": {
                "id": "pool-b",
                "feeTier": 500,
                "tickSpacing": 10,
                "hooks": "0x0000000000000000000000000000000000000000",
                "token0": {"id": "token-a", "decimals": "18"},
                "token1": {"id": "token-b", "decimals": "6"},
            },
        }
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            merge_v4_statics(primary, auxiliary)

    def test_v4_enrichment_recovers_metadata_after_an_interrupted_raw_write(self) -> None:
        day = dt.date(2025, 9, 14)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "swaps.jsonl.gz"
            metadata = root / "meta.json"
            write_jsonl_gz(
                raw,
                [
                    {
                        "id": "swap-1",
                        "pool": {
                            "id": "pool",
                            "feeTier": 500,
                            "tickSpacing": 10,
                            "hooks": "0x0000000000000000000000000000000000000000",
                            "token0": {"id": "token-a", "decimals": "18"},
                            "token1": {"id": "token-b", "decimals": "6"},
                        },
                    }
                ],
            )
            write_json(
                metadata,
                {
                    "source": "uniswap_v4",
                    "day": day.isoformat(),
                    "statics_enrichment": {"status": "prepared"},
                },
            )
            with (
                patch("scripts.fetch_raw_market_data.raw_path", return_value=raw),
                patch("scripts.fetch_raw_market_data.meta_path", return_value=metadata),
            ):
                result = enrich_v4_statics_day(day)
            self.assertEqual(result["status"], "recovered")
            recorded = json.loads(metadata.read_text())
            self.assertEqual(recorded["statics_enrichment"]["status"], "complete")

    def test_v4_static_merge_refuses_a_swap_identity_mismatch(self) -> None:
        primary = {
            "id": "swap-1",
            "pool": {
                "id": "pool",
                "token0": {"id": "token-a"},
                "token1": {"id": "token-b"},
            },
        }
        auxiliary = {
            "id": "swap-2",
            "pool": {
                "id": "pool",
                "feeTier": 500,
                "tickSpacing": 10,
                "hooks": "0x0000000000000000000000000000000000000000",
                "token0": {"id": "token-a", "decimals": "18"},
                "token1": {"id": "token-b", "decimals": "6"},
            },
        }
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            merge_v4_statics(primary, auxiliary)

    def test_partial_refresh_preserves_other_streams_and_recomputes_bounds(self) -> None:
        old = {
            "head_block_at_fetch": 100,
            "min_block": 10,
            "max_block": 20,
            "streams": {
                "daily": {
                    "status": "fetched",
                    "min_block": 10,
                    "max_block": 20,
                },
                "swaps": {
                    "status": "fetched",
                    "min_block": 11,
                    "max_block": 19,
                },
            },
        }
        fresh = {
            "head_block_at_fetch": 200,
            "min_block": 12,
            "max_block": 30,
            "streams": {
                "swaps": {
                    "status": "fetched",
                    "min_block": 12,
                    "max_block": 30,
                },
            },
        }
        got = merge_stream_metadata(old, fresh)
        self.assertEqual(set(got["streams"]), {"daily", "swaps"})
        self.assertEqual(got["streams"]["daily"]["max_block"], 20)
        self.assertEqual(got["streams"]["swaps"]["max_block"], 30)
        self.assertEqual(got["min_block"], 10)
        self.assertEqual(got["max_block"], 30)
        self.assertEqual(got["head_block_at_fetch"], 200)

    def test_skipped_stream_does_not_erase_prior_row_and_block_details(self) -> None:
        old = {
            "streams": {
                "swaps": {
                    "status": "fetched",
                    "rows": 17,
                    "min_block": 10,
                    "max_block": 20,
                }
            }
        }
        fresh = {
            "streams": {
                "swaps": {"status": "skipped", "path": "already-there.jsonl.gz"}
            }
        }
        got = merge_stream_metadata(old, fresh)
        self.assertEqual(got["streams"]["swaps"]["status"], "fetched")
        self.assertEqual(got["streams"]["swaps"]["rows"], 17)
        self.assertEqual(got["min_block"], 10)
        self.assertEqual(got["max_block"], 20)


if __name__ == "__main__":
    unittest.main()
