from __future__ import annotations

import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.fetch.graph import build_query
from ddvc.fetch.raw import (
    RawFetchInvariantError,
    RawRefetchDivergenceError,
    fetch_source_day,
    graph_query_contract_sha256,
    index_existing_stream,
    merge_stream_metadata,
    indexed_metadata_streams,
    raw_stream_metadata_is_current,
    repair_source_day_metadata,
    raw_stream_identity,
    require_mergeable_partial_metadata,
    write_json,
    write_jsonl_gz,
)
from ddvc.provenance import portable_content_sha256
from ddvc.fetch.schemas import EntitySpec, SchemaSpec, get_schema
from ddvc.fetch.sources import get_source
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


class RawMetaMergeTests(unittest.TestCase):
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
        def row(fee: int, hooks: str = "0x0000000000000000000000000000000000000000"):
            return {
                "id": "swap",
                "pool": {
                    "id": "pool",
                    "feeTier": fee,
                    "tickSpacing": 10,
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
