from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.datasets import (
    DataPartition,
    PartitionedDataset,
    expected_route_days,
    validate_before_install,
)
from ddvc.reconstruct import ROUTE_SAMPLE_START


def _dataset(tmp_path: Path) -> PartitionedDataset:
    ledger = tmp_path / "quality.parquet"
    panel = tmp_path / "20250101.parquet"
    pd.DataFrame({"value": [1, 2]}).to_parquet(panel, index=False)
    pd.DataFrame({"passed": [True]}).to_parquet(ledger, index=False)
    partition = DataPartition("20250101", panel, 2, panel.stat().st_size)
    return PartitionedDataset("route", ("value",), ledger, (partition,))


def test_direct_dataset_reads_declared_columns_and_rows(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    assert dataset.days == ("20250101",)
    assert dataset.input_paths == (dataset.ledger_path, dataset.partitions[0].path)
    assert dataset.read_day("20250101").to_dict("list") == {"value": [1, 2]}


def test_direct_dataset_rejects_size_or_row_drift(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    dataset.partitions[0].path.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="size disagrees"):
        dataset.assert_current()


def test_install_validator_rechecks_direct_inputs(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    validate_before_install(dataset)(tmp_path / "staged")
    dataset.partitions[0].path.unlink()
    with pytest.raises(RuntimeError, match="missing"):
        validate_before_install(dataset)(tmp_path / "staged")


def test_route_calendar_starts_with_the_canonical_v1_panel() -> None:
    days = expected_route_days()
    assert days[0] == ROUTE_SAMPLE_START
    assert days[0] == "20181102"
