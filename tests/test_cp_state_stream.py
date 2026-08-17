from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ddvc.artifact_release import file_sha256
from ddvc.cp_state_stream import (
    RESERVE_STREAM,
    cp_event_stream,
    cp_state_stream,
    validate_cp_stream_manifest,
)
from source_day_fixtures import install_source_day_metadata


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _reserve_fixture(raw: Path) -> Path:
    path = raw / "uniswap_v2" / "uniswap_v2_hourly_reserves_20250101.jsonl.gz"
    _write_rows(
        path,
        [
            {
                "id": "snapshot",
                "hourStartUnix": "1735689600",
                "reserve0": "10",
                "reserve1": "20",
                "pair": {
                    "id": "0xpool",
                    "token0": {"id": "0xa", "symbol": "A", "decimals": "18"},
                    "token1": {"id": "0xb", "symbol": "B", "decimals": "6"},
                },
            }
        ],
    )
    install_source_day_metadata(raw, "uniswap_v2", (RESERVE_STREAM,), "20250101")
    return path


def test_capital_manifest_reopens_source_day_inputs(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw" / "thegraph"
    _reserve_fixture(raw)
    release = cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    validate_cp_stream_manifest(release.manifest_record(), expected_venue="uniswap_v2")


def test_reserve_stream_requires_metadata(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw" / "thegraph"
    _reserve_fixture(raw)
    (raw / "uniswap_v2" / "uniswap_v2_meta_20250101.json").unlink()
    with pytest.raises(Exception, match="uncommitted"):
        cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)


def test_capital_stream_ignores_unregistered_event_files(tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "data" / "raw" / "thegraph"
    _reserve_fixture(raw)
    sentinels = {}
    for stream in ("swaps", "mints", "burns"):
        path = raw / "uniswap_v2" / f"uniswap_v2_{stream}_20250101.jsonl.gz"
        path.write_bytes(f"sentinel-{stream}".encode())
        sentinels[path] = path.read_bytes()
    monkeypatch.setattr(
        "ddvc.cp_state_stream.iter_normalised_cp_reserve_records",
        lambda *_args: iter(({"pool": "0x1"},)),
    )
    selected = cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert list(selected.read_day("20250101")) == [{"pool": "0x1"}]
    assert {path: path.read_bytes() for path in sentinels} == sentinels


def test_event_stream_binds_required_files(tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "data" / "raw" / "thegraph"
    streams = ("burns", "hourly_reserves", "mints", "swaps")
    for stream in streams:
        _write_rows(raw / "uniswap_v2" / f"uniswap_v2_{stream}_20250101.jsonl.gz", [])
    install_source_day_metadata(raw, "uniswap_v2", streams, "20250101")
    monkeypatch.setattr(
        "ddvc.cp_state_stream.state_partition_inputs",
        lambda *_args: [
            raw / "uniswap_v2" / f"uniswap_v2_{stream}_20250101.jsonl.gz"
            for stream in streams
        ],
    )
    selected = cp_event_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert selected.kind == "event_stream"
    assert len(selected.partitions[0].raw_inputs) == 8


def test_event_stream_rejects_timestamp_and_semantic_drift(tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "data" / "raw" / "thegraph"
    streams = ("burns", "hourly_reserves", "mints", "swaps")
    for stream in streams:
        _write_rows(raw / "uniswap_v2" / f"uniswap_v2_{stream}_20250101.jsonl.gz", [])
    install_source_day_metadata(raw, "uniswap_v2", streams, "20250101")
    correction = tmp_path / "correction.json"
    correction.write_text("generation one\n", encoding="utf-8")
    monkeypatch.setattr(
        "ddvc.cp_state_stream.state_partition_inputs",
        lambda *_args: [
            *(raw / "uniswap_v2" / f"uniswap_v2_{stream}_20250101.jsonl.gz" for stream in streams),
            correction,
        ],
    )
    selected = cp_event_stream("uniswap_v2", ("20250101",), raw_root=raw)
    selected.assert_current()
    correction.write_text("generation two\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="semantic correction input changed"):
        selected.assert_current()


def test_published_legacy_manifest_remains_readable_without_restamping(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    ledger = tmp_path / "ledger.jsonl"
    certificate.write_text("{}\n", encoding="utf-8")
    ledger.write_text("legacy evidence\n", encoding="utf-8")
    validate_cp_stream_manifest(
        {
            "authority_kind": "local_certified_reserve_stream_v1",
            "venue": "uniswap_v2",
            "certificate_path": str(certificate),
            "certificate_sha256": file_sha256(certificate),
            "ledger_path": str(ledger),
            "ledger_sha256": file_sha256(ledger),
            "partitions": [{"day": "20250101"}],
        },
        expected_venue="uniswap_v2",
    )
