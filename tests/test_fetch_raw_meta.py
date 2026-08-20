from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path

import pytest

from ddvc.fetch.raw import (
    RawFetchInvariantError,
    _gzip_payloads_equal,
    indexed_metadata_streams,
    repair_source_day_metadata,
    source_day_stream_snapshot,
    verified_source_day_rows,
    write_jsonl_gz,
)
from ddvc.fetch.sources import get_source


DAY = dt.date(2025, 1, 1)


def _paths(root: Path) -> tuple[Path, Path]:
    directory = root / "raw" / "thegraph" / "uniswap_v2"
    return (
        directory / "uniswap_v2_swaps_20250101.jsonl.gz",
        directory / "uniswap_v2_meta_20250101.json",
    )


def _write_source_day(root: Path, rows: list[dict[str, object]]) -> tuple[Path, Path]:
    payload, marker = _paths(root)
    write_jsonl_gz(payload, rows)
    marker.write_text(
        json.dumps(
            {
                "source": "uniswap_v2",
                "day": DAY.isoformat(),
                "streams": {
                    "swaps": {
                        "path": f"uniswap_v2/{payload.name}",
                        "rows": len(rows),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return payload, marker


def test_metadata_index_requires_row_count_and_exact_portable_path(tmp_path: Path) -> None:
    payload, marker = _write_source_day(tmp_path, [{"id": "one"}])
    assert indexed_metadata_streams(
        marker, expected_paths={"swaps": payload}
    ) == {"swaps"}
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["streams"]["swaps"]["path"] = "other/wrong.jsonl.gz"
    marker.write_text(json.dumps(record), encoding="utf-8")
    assert indexed_metadata_streams(
        marker, expected_paths={"swaps": payload}
    ) == set()


def test_source_day_reader_uses_metadata_and_checks_row_count(tmp_path: Path) -> None:
    _write_source_day(tmp_path, [{"id": "one"}])
    snapshot = source_day_stream_snapshot(
        "uniswap_v2", "swaps", DAY, data_root=tmp_path
    )
    assert snapshot["rows"] == 1
    with verified_source_day_rows(
        "uniswap_v2", "swaps", DAY, data_root=tmp_path
    ) as rows:
        assert list(rows) == [{"id": "one"}]

    marker = _paths(tmp_path)[1]
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["streams"]["swaps"]["rows"] = 2
    marker.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RawFetchInvariantError, match="row count"):
        with verified_source_day_rows(
            "uniswap_v2", "swaps", DAY, data_root=tmp_path
        ) as rows:
            list(rows)


def test_logical_gzip_comparison_needs_no_content_identity(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl.gz"
    second = tmp_path / "second.jsonl.gz"
    write_jsonl_gz(first, [{"id": "one"}])
    with gzip.open(second, "wt") as handle:
        handle.write('{"id":"one"}\n')
    assert _gzip_payloads_equal(first, second)
    write_jsonl_gz(second, [{"id": "two"}])
    assert not _gzip_payloads_equal(first, second)


def test_metadata_repair_counts_installed_rows(tmp_path: Path) -> None:
    payload, marker = _paths(tmp_path)
    write_jsonl_gz(
        payload,
        [
            {
                "id": "one",
                "transaction": {"blockNumber": "10"},
            }
        ],
    )
    repaired = repair_source_day_metadata(
        get_source("uniswap_v2"), DAY, streams={"swaps"}, data_root=tmp_path
    )
    assert marker.is_file()
    assert repaired["streams"]["swaps"]["rows"] == 1
    assert "sha256" not in json.dumps(repaired).lower()


def test_metadata_repair_indexes_an_installed_dune_stream(tmp_path: Path) -> None:
    directory = tmp_path / "raw" / "dune" / "fluid"
    payload = directory / "fluid_swaps_20250101.jsonl.gz"
    marker = directory / "fluid_meta_20250101.json"
    write_jsonl_gz(payload, [{"tx_hash": "one", "block_number": 10}])

    repaired = repair_source_day_metadata(
        get_source("fluid"), DAY, streams={"swaps"}, data_root=tmp_path
    )

    assert marker.is_file()
    assert repaired["source"] == "fluid"
    assert repaired["backend"] == "dune"
    assert repaired["streams"]["swaps"]["rows"] == 1
    with verified_source_day_rows(
        "fluid", "swaps", DAY, data_root=tmp_path
    ) as rows:
        assert list(rows) == [{"tx_hash": "one", "block_number": 10}]
