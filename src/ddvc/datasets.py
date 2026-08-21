"""Direct readers and schema checks for reconstructed routes and market state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR
from ddvc.reconstruct import (
    DEX_FAMILY,
    RECONSTRUCTION_ENGINE,
    ROUTE_SAMPLE_START,
    UNIFIED_COLUMNS,
    UNIFIED_QUALITY_PANEL,
    active_route_sources,
    unified_path,
)
from ddvc.runtime import serialized_read_installs
from ddvc.state_data import (
    CP_COLUMNS,
    FAMILY_STREAMS,
    MULTI_ASSET_COLUMNS,
    QUALITY_COLUMNS,
    STATE_ROOT,
    state_partition_path,
)


MARKET_STATE_QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
STATE_COLUMN_CONTRACTS = {
    "constant_product": tuple(CP_COLUMNS),
    "multi_asset": tuple(MULTI_ASSET_COLUMNS),
}


def _columns(columns: Iterable[str], contract: Iterable[str]) -> tuple[str, ...]:
    if isinstance(columns, (str, bytes)):
        raise ValueError("columns must be an iterable of names")
    selected = tuple(str(column) for column in columns)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("columns must be nonempty and unique")
    unknown = sorted(set(selected) - set(contract))
    if unknown:
        raise ValueError(f"columns are outside the canonical schema: {unknown}")
    return selected


def _stat(path: Path) -> tuple[int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True)
class DataPartition:
    """One directly addressed Parquet partition."""

    day: str
    path: Path
    expected_rows: int
    expected_bytes: int

    def assert_current(self) -> None:
        if not self.path.is_file():
            raise RuntimeError(f"dataset partition is missing: {self.path}")
        if self.expected_bytes >= 0 and self.path.stat().st_size != self.expected_bytes:
            raise RuntimeError(f"dataset partition size disagrees with quality table: {self.path}")


@dataclass(frozen=True)
class PartitionedDataset:
    """Ordered direct partition perimeter for one analysis input."""

    kind: str
    columns: tuple[str, ...]
    ledger_path: Path
    partitions: tuple[DataPartition, ...]
    family: str | None = None
    venue: str | None = None
    include_quarantined: bool = False
    quarantined_pools: tuple[str, ...] = ()
    quarantine_path: Path | None = None

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(partition.day for partition in self.partitions)

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(partition.path for partition in self.partitions)

    @property
    def input_paths(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((self.ledger_path, *self.paths, *((self.quarantine_path,) if self.quarantine_path else ()))))

    @property
    def label(self) -> str:
        scope = "/".join(value for value in (self.kind, self.family, self.venue) if value)
        return f"{scope}:{len(self.partitions)}-days"

    def _partition(self, day: str) -> DataPartition:
        normalized = str(day).replace("-", "")
        matches = [partition for partition in self.partitions if partition.day == normalized]
        if len(matches) != 1:
            raise KeyError(f"day is outside the dataset perimeter: {normalized}")
        return matches[0]

    def assert_current(self) -> None:
        if not self.ledger_path.is_file():
            raise RuntimeError(f"dataset quality table is missing: {self.ledger_path}")
        if self.quarantine_path is not None and not self.quarantine_path.is_file():
            raise RuntimeError(f"dataset quarantine is missing: {self.quarantine_path}")
        for partition in self.partitions:
            partition.assert_current()

    def select_days(self, days: Iterable[str]) -> "PartitionedDataset":
        selected = tuple(str(day).replace("-", "") for day in days)
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("day selection must be nonempty and unique")
        return replace(self, partitions=tuple(self._partition(day) for day in selected))

    def read_day(self, day: str) -> pd.DataFrame:
        partition = self._partition(day)
        lease = [self.ledger_path, partition.path]
        if self.quarantine_path is not None:
            lease.append(self.quarantine_path)
        with serialized_read_installs(lease):
            before = {path: _stat(path) for path in lease}
            partition.assert_current()
            read_columns = self.columns
            if self.kind == "state" and not self.include_quarantined and "usable" not in read_columns:
                read_columns = (*read_columns, "usable")
            if self.quarantined_pools and "pool" not in read_columns:
                read_columns = (*read_columns, "pool")
            frame = pd.read_parquet(partition.path, columns=list(read_columns))
            if len(frame) != partition.expected_rows:
                raise RuntimeError(f"dataset row count disagrees with quality table: {partition.path}")
            if any(not path.is_file() or _stat(path) != before[path] for path in lease):
                raise RuntimeError(f"dataset changed while being read: {partition.path}")
        if self.kind == "state" and not self.include_quarantined:
            frame = frame.loc[frame["usable"].astype(bool)].reset_index(drop=True)
            if self.quarantined_pools:
                frame = frame.loc[~frame["pool"].astype(str).str.lower().isin(self.quarantined_pools)].reset_index(drop=True)
            if "usable" not in self.columns:
                frame = frame.drop(columns="usable")
            if self.quarantined_pools and "pool" not in self.columns:
                frame = frame.drop(columns="pool")
        return frame.loc[:, list(self.columns)]


@dataclass(frozen=True)
class DatasetValidator:
    datasets: tuple[PartitionedDataset, ...]

    def __call__(self, _staged_path: Path) -> None:
        for dataset in self.datasets:
            dataset.assert_current()


def validate_before_install(*datasets: PartitionedDataset) -> DatasetValidator:
    if not datasets:
        raise ValueError("at least one dataset is required")
    return DatasetValidator(tuple(datasets))


def expected_route_days() -> list[str]:
    return calendar_days(ROUTE_SAMPLE_START, RESEARCH_SAMPLE_END)


def expected_state_keys() -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for family, venues in FAMILY_STREAMS.items():
        for venue in venues:
            start = max(RESEARCH_SAMPLE_START, get_source(venue).genesis.strftime("%Y%m%d"))
            keys.extend((family, venue, day) for day in calendar_days(start, RESEARCH_SAMPLE_END))
    return keys


def _quality(kind: str) -> pd.DataFrame:
    path = UNIFIED_QUALITY_PANEL if kind == "route" else MARKET_STATE_QUALITY_PANEL
    if not path.is_file():
        raise RuntimeError(f"required {kind} quality table is missing: {path}")
    before = _stat(path)
    quality = pd.read_parquet(path)
    if _stat(path) != before:
        raise RuntimeError(f"{kind} quality table changed while being read")
    if "passed" not in quality or not quality["passed"].astype(bool).all():
        raise RuntimeError(f"{kind} quality table contains failed partitions")
    if kind == "route":
        needed = {"day", "engine", "output_rows", "output_bytes"}
        if not needed.issubset(quality.columns):
            raise RuntimeError("route quality schema is incomplete")
        if set(quality["engine"].astype(str)) != {RECONSTRUCTION_ENGINE}:
            raise RuntimeError("route quality table belongs to a stale engine")
        observed = tuple(quality["day"].astype(str).str.zfill(8))
        if observed != tuple(expected_route_days()):
            raise RuntimeError("route quality table does not cover the full research calendar")
        expected_sources = sum(len(active_route_sources(day, list(DEX_FAMILY))) for day in observed)
        if "expected_sources" in quality and int(quality["expected_sources"].sum()) != expected_sources:
            raise RuntimeError("route quality table has incomplete venue-day support")
        return quality.sort_values("day", kind="stable").reset_index(drop=True)
    needed = {"family", "venue", "day", "canonical_rows", "output_bytes"}
    if not needed.issubset(quality.columns):
        raise RuntimeError("market-state quality schema is incomplete")
    actual = set(zip(quality["family"].astype(str), quality["venue"].astype(str), quality["day"].astype(str).str.zfill(8)))
    if actual != set(expected_state_keys()):
        raise RuntimeError("market-state quality table does not cover the required calendar")
    return quality.sort_values(["family", "venue", "day"], kind="stable").reset_index(drop=True)


def require_route_data() -> None:
    _quality("route")


def require_market_state_data() -> None:
    _quality("state")


def require_datasets(*, routes: bool = False, market_state: bool = False) -> None:
    if not routes and not market_state:
        raise ValueError("at least one dataset must be required")
    if routes:
        require_route_data()
    if market_state:
        require_market_state_data()


def route_partitions(columns: Iterable[str], *, nonempty: bool = False) -> PartitionedDataset:
    selected_columns = _columns(columns, UNIFIED_COLUMNS)
    quality = _quality("route")
    if nonempty:
        quality = quality.loc[quality["output_rows"].astype(int).gt(0)].copy()
    partitions = tuple(
        DataPartition(
            day=str(row.day).zfill(8),
            path=unified_path(str(row.day).zfill(8)),
            expected_rows=int(row.output_rows),
            expected_bytes=int(row.output_bytes),
        )
        for row in quality.itertuples(index=False)
    )
    dataset = PartitionedDataset("route", selected_columns, UNIFIED_QUALITY_PANEL, partitions)
    dataset.assert_current()
    return dataset


def state_partitions(
    family: str,
    venue: str,
    columns: Iterable[str],
    *,
    include_quarantined: bool = False,
) -> PartitionedDataset:
    if family not in FAMILY_STREAMS or venue not in FAMILY_STREAMS[family]:
        raise ValueError(f"unsupported state family/venue: {family}/{venue}")
    selected_columns = _columns(columns, STATE_COLUMN_CONTRACTS[family])
    quality = _quality("state")
    selected = quality.loc[quality["family"].astype(str).eq(family) & quality["venue"].astype(str).eq(venue)].copy()
    partitions = tuple(
        DataPartition(
            day=str(row.day).zfill(8),
            path=state_partition_path(family, venue, str(row.day).zfill(8), root=STATE_ROOT),
            expected_rows=int(row.canonical_rows),
            expected_bytes=int(row.output_bytes),
        )
        for row in selected.sort_values("day", kind="stable").itertuples(index=False)
    )
    dataset = PartitionedDataset(
        "state",
        selected_columns,
        MARKET_STATE_QUALITY_PANEL,
        partitions,
        family=family,
        venue=venue,
        include_quarantined=include_quarantined,
        quarantined_pools=(),
        quarantine_path=None,
    )
    dataset.assert_current()
    return dataset
