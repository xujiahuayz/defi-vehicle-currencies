from __future__ import annotations

from pathlib import Path

import pytest

from ddvc.cp_state_stream import RESERVE_STREAM, certified_cp_event_stream, certified_cp_state_stream


def reserve_row(day: str, stream: str = RESERVE_STREAM) -> dict[str, object]:
    return {
        "source": "uniswap_v2",
        "stream": stream,
        "day": day,
        "logical_content_sha256": "a" * 64,
        "contract_sha256": "b" * 64,
        "observed_query_contract_sha256": "c" * 64,
        "observed_head_block_at_fetch": 123,
        "metadata_sha256": "d" * 64,
        "container_bytes": 42,
        "rows": 1,
    }


def authorities(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "data" / "processed" / "raw_generation"
    root.mkdir(parents=True)
    ledger = root / "reserve.jsonl"
    ledger.write_text("ledger", encoding="utf-8")
    certificate = root / "uniswap_v2_local_certificate.json"
    certificate.write_text('{"partition_ledger":"reserve.jsonl"}\n', encoding="utf-8")
    return certificate, ledger


def test_reserve_only_certificate_succeeds_without_event_authorities(tmp_path, monkeypatch) -> None:
    authorities(tmp_path)
    observed = []

    def load(_certificate, *, data_root, partitions):
        selected = sorted(partitions)
        observed.extend(selected)
        return [reserve_row(partition.day) for partition in selected], {}

    monkeypatch.setattr("ddvc.cp_state_stream.load_certified_partition_ledger", load)
    raw = tmp_path / "data" / "raw" / "thegraph"
    selected = certified_cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert selected.days == ("20250101",)
    assert {(item.stream, item.day) for item in observed} == {(RESERVE_STREAM, "20250101")}


def test_present_uncertified_reserve_bytes_are_rejected(tmp_path, monkeypatch) -> None:
    authorities(tmp_path)
    reserve = tmp_path / "data" / "raw" / "thegraph" / "uniswap_v2" / "uniswap_v2_hourly_reserves_20250101.jsonl.gz"
    reserve.parent.mkdir(parents=True)
    reserve.write_bytes(b"present but not certified")

    def reject(*_args, **_kwargs):
        raise ValueError("local scan certificate does not cover requested partition")

    monkeypatch.setattr("ddvc.cp_state_stream.load_certified_partition_ledger", reject)
    with pytest.raises(ValueError, match="does not cover requested partition"):
        certified_cp_state_stream("uniswap_v2", ("20250101",), raw_root=tmp_path / "data" / "raw" / "thegraph")


def test_capital_stream_does_not_inspect_present_swap_mint_or_burn_files(tmp_path, monkeypatch) -> None:
    authorities(tmp_path)
    raw = tmp_path / "data" / "raw" / "thegraph"
    venue_root = raw / "uniswap_v2"
    venue_root.mkdir(parents=True)
    event_bytes = {}
    for stream in ("swaps", "mints", "burns"):
        path = venue_root / f"uniswap_v2_{stream}_20250101.jsonl.gz"
        path.write_bytes(f"sentinel-{stream}".encode())
        event_bytes[path] = path.read_bytes()

    monkeypatch.setattr(
        "ddvc.cp_state_stream.load_certified_partition_ledger",
        lambda _certificate, *, data_root, partitions: ([reserve_row("20250101")], {}),
    )
    monkeypatch.setattr(
        "ddvc.cp_state_stream.iter_normalised_cp_reserve_records",
        lambda *_args: iter(({"pool": "0x1"},)),
    )
    selected = certified_cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert list(selected.read_day("20250101")) == [{"pool": "0x1"}]
    assert {path: path.read_bytes() for path in event_bytes} == event_bytes


def test_event_stream_binds_all_and_only_required_constant_product_streams(tmp_path, monkeypatch) -> None:
    authorities(tmp_path)
    observed = []

    def load(_certificate, *, data_root, partitions):
        selected = sorted(partitions)
        observed.extend(selected)
        return [reserve_row(partition.day, partition.stream) for partition in selected], {}

    monkeypatch.setattr("ddvc.cp_state_stream.load_certified_partition_ledger", load)
    monkeypatch.setattr(
        "ddvc.cp_state_stream.iter_normalised_cp_records",
        lambda *_args: iter(({"record_type": "snapshot"},)),
    )
    selected = certified_cp_event_stream(
        "uniswap_v2",
        ("20250101",),
        raw_root=tmp_path / "data" / "raw" / "thegraph",
    )
    assert selected.kind == "event_stream"
    assert [partition.stream for partition in observed] == [
        "burns", "hourly_reserves", "mints", "swaps"
    ]
    assert list(selected.read_day("20250101")) == [{"record_type": "snapshot"}]


def test_event_stream_rejects_semantic_correction_drift(tmp_path, monkeypatch) -> None:
    authorities(tmp_path)
    correction = tmp_path / "corrections.json"
    correction.write_text("generation one\n", encoding="utf-8")

    def load(_certificate, *, data_root, partitions):
        return [
            reserve_row(partition.day, partition.stream)
            for partition in sorted(partitions)
        ], {}

    monkeypatch.setattr("ddvc.cp_state_stream.load_certified_partition_ledger", load)
    monkeypatch.setattr(
        "ddvc.cp_state_stream.state_partition_inputs",
        lambda *_args: [correction],
    )
    selected = certified_cp_event_stream(
        "uniswap_v2",
        ("20250101",),
        raw_root=tmp_path / "data" / "raw" / "thegraph",
    )
    selected.assert_current()
    correction.write_text("generation two\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="semantic correction input changed"):
        selected.assert_current()
