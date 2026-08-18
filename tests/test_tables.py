from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ddvc.tables import (
    EXHIBIT_MAX_ROWS,
    read_exhibit,
    write_exhibit,
    write_panel,
    write_panel_batches,
    write_report,
)


def test_exhibit_is_direct_readable_json_lines(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["a", "b"], "value": [1.5, float("nan")]})
    path = write_exhibit(frame, tmp_path / "result")
    assert path == tmp_path / "result.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records == [
        {"name": "a", "value": 1.5},
        {"name": "b", "value": None},
    ]
    assert len(read_exhibit(path)) == 2
    assert not (tmp_path / "result.jsonl.prov.json").exists()


def test_exhibit_refuses_panel_sized_frames(tmp_path: Path) -> None:
    frame = pd.DataFrame({"value": range(EXHIBIT_MAX_ROWS + 1)})
    with pytest.raises(ValueError, match="write_panel"):
        write_exhibit(frame, tmp_path / "too-large.jsonl")


def test_big_integers_are_written_as_decimal_strings(tmp_path: Path) -> None:
    value = 2**120 + 7
    path = write_exhibit(pd.DataFrame({"value": [value]}), tmp_path / "big.jsonl")
    assert json.loads(path.read_text())["value"] == str(value)


def test_panel_is_direct_parquet_and_round_trips(tmp_path: Path) -> None:
    frame = pd.DataFrame({"key": [1, 2], "value": ["a", "b"]})
    path = write_panel(frame, tmp_path / "panel.parquet")
    pd.testing.assert_frame_equal(pd.read_parquet(path), frame)
    assert not (tmp_path / "panel.parquet.prov.json").exists()


def test_validator_runs_before_replacing_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "panel.parquet"
    prior = pd.DataFrame({"value": [1]})
    prior.to_parquet(path, index=False)

    def reject(_temporary: Path) -> None:
        raise ValueError("invalid staged panel")

    with pytest.raises(ValueError, match="invalid staged panel"):
        write_panel(
            pd.DataFrame({"value": [2]}),
            path,
            preinstall_validator=reject,
        )
    pd.testing.assert_frame_equal(pd.read_parquet(path), prior)


def test_panel_batches_stream_one_schema(tmp_path: Path) -> None:
    path, rows = write_panel_batches(
        [pd.DataFrame({"value": [1, 2]}), pd.DataFrame({"value": [3]})],
        tmp_path / "batches.parquet",
    )
    assert rows == 3
    assert pd.read_parquet(path)["value"].tolist() == [1, 2, 3]


def test_panel_batches_reject_schema_drift(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one schema"):
        write_panel_batches(
            [pd.DataFrame({"value": [1]}), pd.DataFrame({"other": [2]})],
            tmp_path / "batches.parquet",
        )


def test_panel_batches_reject_empty_stream(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        write_panel_batches([], tmp_path / "empty.parquet")


def test_report_writes_null_for_nonfinite_values(tmp_path: Path) -> None:
    path = write_report(
        pd.DataFrame({"value": [float("inf"), float("nan"), 2.0]}),
        tmp_path / "report.jsonl",
    )
    assert [json.loads(line)["value"] for line in path.read_text().splitlines()] == [
        None,
        None,
        2.0,
    ]
