from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.reconstruct import (
    DEX_FAMILY,
    RECONSTRUCT_CODE_SOURCES,
    ROUTE_SEMANTIC_FUNCTIONS,
    _available_days,
    _process_one,
    active_route_sources,
    preflight_route_input_perimeter,
    read_unified_quality,
    route_input_paths,
    load_legs,
)
from ddvc.fetch.raw import (
    graph_query_contract_sha256,
    raw_stream_identity,
    source_day_promotion_record,
)
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import get_source
from ddvc.provenance import portable_content_sha256
from ddvc.raw_certification import (
    RawPartition,
    scan_installed_generation,
    write_local_scan_certificate,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def write_v2_swap(data_root: Path, day: str, *, amount_in: str = "100") -> Path:
    path = route_input_paths(day, ["uniswap_v2"], data_root=data_root)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "swap",
        "transaction": {"id": "0xtx", "blockNumber": "10008566", "timestamp": "1588636801"},
        "timestamp": "1588636801",
        "logIndex": "7",
        "amount0In": amount_in,
        "amount0Out": "0",
        "amount1In": "0",
        "amount1Out": "0.05",
        "amountUSD": amount_in,
        "pair": {
            "id": "0xpool",
            "token0": {"id": USDC, "symbol": "USDC"},
            "token1": {"id": WETH, "symbol": "WETH"},
        },
    }
    with gzip.open(path, "wt") as handle:
        handle.write(json.dumps(row) + "\n")
    write_committed_marker(path, day)
    return path


def write_committed_marker(path: Path, day: str) -> None:
    source = get_source("uniswap_v2")
    entity = next(
        entity for entity in get_schema(source.schema).entities if entity.stream == "swaps"
    )
    stamp = day.replace("-", "")
    marker = path.with_name(f"uniswap_v2_meta_{stamp}.json")
    marker.write_text(
        json.dumps(
            {
                "source": "uniswap_v2",
                "day": day,
                "streams": {
                    "swaps": {
                        "path": raw_stream_identity(path),
                        "rows": 0,
                        "logical_content_sha256": portable_content_sha256(path),
                        "query_contract_sha256": graph_query_contract_sha256(entity),
                        "head_block_at_fetch": 20_000_000,
                    }
                },
                "promotion": source_day_promotion_record(
                    "uniswap_v2",
                    dt.date.fromisoformat(day),
                    {"swaps": portable_content_sha256(path)},
                ),
            }
        )
    )


class ReconstructGateTests(unittest.TestCase):
    def test_route_engine_tracks_source_genesis_but_not_fetch_orchestration(self) -> None:
        self.assertIn("src/ddvc/fetch/sources.py", RECONSTRUCT_CODE_SOURCES)
        self.assertIn("src/ddvc/source_records.py", RECONSTRUCT_CODE_SOURCES)
        self.assertNotIn("src/ddvc/fetch/raw.py", RECONSTRUCT_CODE_SOURCES)
        self.assertNotIn("run", {function.__name__ for function in ROUTE_SEMANTIC_FUNCTIONS})

    def test_full_route_calendar_is_independent_of_observed_files(self) -> None:
        days = _available_days(list(DEX_FAMILY))
        self.assertEqual((days[0], days[-1], len(days)), ("2020-02-11", "2026-06-30", 2332))
        self.assertEqual(
            sum(len(active_route_sources(day, list(DEX_FAMILY))) for day in days),
            12802,
        )

    def test_missing_launched_source_fails_instead_of_shrinking_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                base / "data",
                base / "unified",
            )
        self.assertEqual(status, "failed")
        self.assertFalse(quality["passed"])
        self.assertEqual(quality["missing_sources"], 1)

    def test_raw_preflight_rejects_broken_perimeter_before_output_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            marker = unified_root / ".quality" / "20200505.json"
            marker.parent.mkdir(parents=True)
            marker.write_text('{"sentinel": true}\n', encoding="utf-8")
            before = marker.read_bytes()
            with self.assertRaisesRegex(
                FileNotFoundError,
                "raw preflight failed.*uniswap_v2/20200505:payload\\+marker",
            ):
                preflight_route_input_perimeter(
                    ["2020-05-05"],
                    ["uniswap_v2"],
                    data_root=data_root,
                )
            self.assertEqual(marker.read_bytes(), before)

    def test_direct_route_loader_has_no_missing_raw_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "certificate is unreadable"):
                load_legs(
                    "uniswap_v2",
                    "2020-05-05",
                    data_root=Path(directory),
                )

    def test_route_day_is_current_only_against_exact_raw_inputs_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            raw = write_v2_swap(data_root, "2020-05-05")
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
            self.assertEqual(status, "written")
            self.assertTrue(quality["passed"])
            self.assertEqual(quality["raw_rows"], 1)
            self.assertEqual(quality["output_rows"], 1)
            self.assertIsNotNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            frame = pd.read_parquet(unified_root / "20200505.parquet")
            self.assertEqual(frame.loc[0, "amount_in"], 100.0)
            marker = raw.with_name("uniswap_v2_meta_20200505.json")
            marker_payload = json.loads(marker.read_text())
            marker_payload["streams"]["swaps"]["query_contract_sha256"] = "0" * 64
            marker.write_text(json.dumps(marker_payload))
            self.assertIsNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            write_committed_marker(raw, "2020-05-05")
            output = unified_root / "20200505.parquet"
            original = output.stat()
            payload = bytearray(output.read_bytes())
            payload[-1] ^= 1
            output.write_bytes(payload)
            os.utime(output, ns=(original.st_atime_ns, original.st_mtime_ns))
            self.assertIsNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
            self.assertEqual(status, "written")
            write_v2_swap(data_root, "2020-05-05", amount_in="101")
            self.assertIsNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            raw.unlink()

    def test_route_day_reads_legacy_payload_through_current_local_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            raw = write_v2_swap(data_root, "2020-05-05")
            marker = raw.with_name("uniswap_v2_meta_20200505.json")
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
            marker_payload.pop("promotion")
            marker_payload["streams"]["swaps"]["rows"] = 1
            marker.write_text(json.dumps(marker_payload), encoding="utf-8")
            partition = RawPartition("uniswap_v2", "swaps", "20200505")
            observed = scan_installed_generation(
                data_root,
                base / "scan",
                workers=1,
                partitions=[partition],
            )
            certificate = (
                data_root
                / "processed"
                / "raw_generation"
                / "uniswap_v2_local_certificate.json"
            )
            write_local_scan_certificate(
                certificate,
                observed,
                expected_partitions=[partition],
            )
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
        self.assertEqual(status, "written")
        self.assertTrue(quality["passed"])
        self.assertEqual(quality["raw_rows"], 1)
        self.assertEqual(quality["output_rows"], 1)

    def test_empty_but_present_day_materialises_a_typed_empty_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            raw = route_input_paths("2020-05-05", ["uniswap_v2"], data_root=data_root)[0]
            raw.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(raw, "wt"):
                pass
            write_committed_marker(raw, "2020-05-05")
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
            frame = pd.read_parquet(unified_root / "20200505.parquet")
        self.assertEqual(status, "written")
        self.assertTrue(quality["passed"])
        self.assertEqual(len(frame), 0)
        self.assertIn("tx_hash", frame.columns)


if __name__ == "__main__":
    unittest.main()
