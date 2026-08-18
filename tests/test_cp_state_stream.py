from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ddvc.cp_state_stream import cp_event_stream, cp_state_stream


def _raw(tmp_path: Path, streams: tuple[str, ...]) -> Path:
    raw = tmp_path / "data" / "raw" / "thegraph"
    root = raw / "uniswap_v2"
    root.mkdir(parents=True)
    metadata: dict[str, object] = {
        "source": "uniswap_v2",
        "day": "2025-01-01",
        "streams": {},
    }
    for stream in {"hourly_reserves", *streams}:
        path = root / f"uniswap_v2_{stream}_20250101.jsonl.gz"
        with gzip.open(path, "wt") as handle:
            handle.write(json.dumps({"id": "1"}) + "\n")
        metadata["streams"][stream] = {"rows": 1, "path": str(path)}  # type: ignore[index]
    (root / "uniswap_v2_meta_20250101.json").write_text(
        json.dumps(metadata) + "\n", encoding="utf-8"
    )
    return raw


def test_reserve_stream_uses_direct_raw_paths_and_row_counts(tmp_path: Path) -> None:
    raw = _raw(tmp_path, ("hourly_reserves",))
    stream = cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert stream.days == ("20250101",)
    assert stream.source_rows("20250101") == 1
    assert len(stream.input_paths) == 2
    stream.assert_current()


def test_stream_detects_source_replacement(tmp_path: Path) -> None:
    raw = _raw(tmp_path, ("hourly_reserves",))
    stream = cp_state_stream("uniswap_v2", ("20250101",), raw_root=raw)
    stream.input_paths[0].write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed"):
        stream.assert_current()


def test_event_stream_requires_sorted_unique_days(tmp_path: Path) -> None:
    raw = _raw(tmp_path, ("swaps", "mints", "burns", "syncs"))
    stream = cp_event_stream("uniswap_v2", ("20250101",), raw_root=raw)
    assert stream.kind == "event_stream"
    with pytest.raises(ValueError, match="unique"):
        cp_event_stream("uniswap_v2", ("20250101", "20250101"), raw_root=raw)
