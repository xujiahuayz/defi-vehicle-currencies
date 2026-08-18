"""Direct constant-product streams over retained source-day files."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from ddvc.fetch.raw import source_day_stream_snapshot
from ddvc.state_data import (
    CP_COLUMNS,
    CP_STREAMS,
    iter_normalised_cp_records,
    iter_normalised_cp_reserve_records,
    raw_stream_path,
    state_partition_inputs,
)


RESERVE_STREAM = "hourly_reserves"


def _stat(path: Path) -> tuple[int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True)
class CPStreamPartition:
    day: str
    expected_bytes: int
    expected_rows: int
    inputs: tuple[tuple[Path, tuple[int, int, int, int]], ...]

    def assert_current(self) -> None:
        for path, expected in self.inputs:
            if not path.is_file() or _stat(path) != expected:
                raise RuntimeError(f"constant-product source-day input changed: {path}")


@dataclass(frozen=True)
class CPStateStreamSet:
    """One direct, purpose-bound constant-product source perimeter."""

    venue: str
    raw_root: Path
    streams: tuple[str, ...]
    columns: tuple[str, ...]
    partitions: tuple[CPStreamPartition, ...]
    family: str = "constant_product"
    kind: str = "reserve_stream"

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(partition.day for partition in self.partitions)

    @property
    def input_paths(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(path for partition in self.partitions for path, _ in partition.inputs))

    def _partition(self, day: str) -> CPStreamPartition:
        normalized = str(day).replace("-", "")
        matches = [partition for partition in self.partitions if partition.day == normalized]
        if len(matches) != 1:
            raise KeyError(f"day is outside the source-day perimeter: {normalized}")
        return matches[0]

    def source_rows(self, day: str) -> int:
        return self._partition(day).expected_rows

    def assert_current(self) -> None:
        for partition in self.partitions:
            partition.assert_current()

    def read_day(self, day: str) -> Iterator[dict[str, object]]:
        partition = self._partition(day)
        partition.assert_current()
        if self.streams == (RESERVE_STREAM,):
            return iter_normalised_cp_reserve_records(self.raw_root, self.venue, partition.day)
        return iter_normalised_cp_records(self.raw_root, self.venue, partition.day)

    def select_days(self, days: Iterable[str]) -> "CPStateStreamSet":
        selected = tuple(str(day).replace("-", "") for day in days)
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("source-day selection must be nonempty and unique")
        return replace(self, partitions=tuple(self._partition(day) for day in selected))


def cp_state_stream(venue: str, days: Iterable[str], *, raw_root: Path) -> CPStateStreamSet:
    """Read hourly reserve records used by deposited-capital measurement."""

    return _cp_streams(venue, days, raw_root=raw_root, streams=(RESERVE_STREAM,), kind="reserve_stream")


def cp_event_stream(venue: str, days: Iterable[str], *, raw_root: Path) -> CPStateStreamSet:
    """Read constant-product event streams used by event-based analyses."""

    if venue not in CP_STREAMS:
        raise ValueError(f"unsupported constant-product venue: {venue}")
    return _cp_streams(
        venue,
        days,
        raw_root=raw_root,
        streams=tuple(stream for stream, _record_type, _sign in CP_STREAMS[venue]),
        kind="event_stream",
    )


def _cp_streams(
    venue: str,
    days: Iterable[str],
    *,
    raw_root: Path,
    streams: tuple[str, ...],
    kind: str,
) -> CPStateStreamSet:
    if venue not in CP_STREAMS:
        raise ValueError(f"unsupported constant-product venue: {venue}")
    selected = tuple(str(day).replace("-", "") for day in days)
    if not selected or selected != tuple(sorted(set(selected))):
        raise ValueError("source-day calendar must be nonempty, unique, and sorted")
    data_root = raw_root.parents[1]
    partitions: list[CPStreamPartition] = []
    for day in selected:
        snapshots = [
            source_day_stream_snapshot(
                venue,
                stream,
                dt.datetime.strptime(day, "%Y%m%d").date(),
                data_root=data_root,
            )
            for stream in streams
        ]
        raw_inputs = tuple(
            path
            for snapshot in snapshots
            for path in (Path(snapshot["path"]), Path(snapshot["marker_path"]))
        )
        raw_paths = {raw_stream_path(raw_root, venue, stream, day) for stream in streams}
        correction_inputs = (
            tuple(
                path
                for path in state_partition_inputs(raw_root, "constant_product", venue, day)
                if path not in raw_paths
            )
            if kind == "event_stream"
            else ()
        )
        inputs = tuple((path, _stat(path)) for path in (*raw_inputs, *correction_inputs))
        partitions.append(
            CPStreamPartition(
                day=day,
                expected_bytes=sum(Path(snapshot["path"]).stat().st_size for snapshot in snapshots),
                expected_rows=sum(int(snapshot["rows"]) for snapshot in snapshots),
                inputs=inputs,
            )
        )
    return CPStateStreamSet(
        venue=venue,
        raw_root=raw_root,
        streams=streams,
        columns=tuple(CP_COLUMNS),
        partitions=tuple(partitions),
        kind=kind,
    )
