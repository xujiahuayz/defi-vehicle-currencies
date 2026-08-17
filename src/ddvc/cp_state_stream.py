"""Purpose-bound constant-product streams over canonical source-day files."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from ddvc.artifact_release import canonical_json_sha256, file_sha256, is_sha256
from ddvc.fetch.raw import source_day_stream_snapshot
from ddvc.paths import REPO_ROOT
from ddvc.state_data import (
    CP_COLUMNS,
    CP_STREAMS,
    SCHEMA_VERSION,
    STATE_ENGINE,
    iter_normalised_cp_records,
    iter_normalised_cp_reserve_records,
    raw_stream_path,
    state_partition_inputs,
)


RESERVE_STREAM = "hourly_reserves"


def _record_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _resolve_record_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def _timestamp_identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class CPStreamPartition:
    day: str
    expected_bytes: int
    expected_rows: int
    input_fingerprint: str
    raw_inputs: tuple[tuple[Path, tuple[int, int]], ...] = ()
    semantic_inputs: tuple[tuple[Path, str], ...] = ()

    def assert_current(self) -> None:
        for path, expected in self.raw_inputs:
            if not path.is_file() or _timestamp_identity(path) != expected:
                raise RuntimeError(f"constant-product source-day input changed: {path}")
        for path, expected in self.semantic_inputs:
            if not path.is_file() or file_sha256(path) != expected:
                raise RuntimeError("constant-product semantic correction input changed")


@dataclass(frozen=True)
class CPStateStreamSet:
    """One exact purpose-bound constant-product source perimeter."""

    venue: str
    raw_root: Path
    streams: tuple[str, ...]
    columns: tuple[str, ...]
    partitions: tuple[CPStreamPartition, ...]
    content_identity_sha256: str
    family: str = "constant_product"
    kind: str = "reserve_stream"

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(partition.day for partition in self.partitions)

    @property
    def provenance_inputs(self) -> tuple[Path, ...]:
        paths = tuple(
            path
            for partition in self.partitions
            for path, _identity in (*partition.raw_inputs, *partition.semantic_inputs)
        )
        return tuple(dict.fromkeys(paths))

    def manifest_record(self) -> dict[str, object]:
        if self.streams != (RESERVE_STREAM,):
            raise ValueError("only a reserve-only stream can enter the capital manifest")
        return {
            "authority_kind": "source_day_reserve_stream_v1",
            "venue": self.venue,
            "content_identity_sha256": self.content_identity_sha256,
            "partitions": [
                {
                    "day": partition.day,
                    "expected_bytes": partition.expected_bytes,
                    "expected_rows": partition.expected_rows,
                    "input_fingerprint": partition.input_fingerprint,
                    "inputs": [
                        {
                            "path": _record_path(path),
                            "bytes": identity[0],
                            "mtime_ns": identity[1],
                        }
                        for path, identity in partition.raw_inputs
                    ],
                }
                for partition in self.partitions
            ],
        }

    def _partition(self, day: str) -> CPStreamPartition:
        normalized = str(day).replace("-", "")
        matches = [partition for partition in self.partitions if partition.day == normalized]
        if len(matches) != 1:
            raise KeyError(f"day is outside the source-day perimeter: {normalized}")
        return matches[0]

    def certified_rows(self, day: str) -> int:
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
        normalized = tuple(str(day).replace("-", "") for day in days)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("source-day selection must be nonempty and unique")
        partitions = tuple(self._partition(day) for day in normalized)
        identity = canonical_json_sha256(
            {
                "policy": f"cp-{self.kind}-subset-v1",
                "parent_content_identity_sha256": self.content_identity_sha256,
                "days": normalized,
            }
        )
        return replace(self, partitions=partitions, content_identity_sha256=identity)


def _validate_legacy_manifest(record: Mapping[str, object]) -> None:
    """Keep an already-published capital release readable without restamping it."""

    certificate_path = _resolve_record_path(record.get("certificate_path"))
    ledger_path = _resolve_record_path(record.get("ledger_path"))
    if (
        not certificate_path.is_file()
        or file_sha256(certificate_path) != record.get("certificate_sha256")
        or not ledger_path.is_file()
        or file_sha256(ledger_path) != record.get("ledger_sha256")
    ):
        raise ValueError("legacy capital reserve evidence changed")


def validate_cp_stream_manifest(
    record: Mapping[str, object],
    *,
    expected_venue: str,
) -> None:
    """Reopen the source-day perimeter recorded by a capital generation."""

    if record.get("venue") != expected_venue:
        raise ValueError("capital reserve authority venue differs")
    raw_partitions = record.get("partitions")
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise ValueError("capital reserve authority perimeter is empty")
    days = [item.get("day") for item in raw_partitions if isinstance(item, Mapping)]
    if (
        len(days) != len(raw_partitions)
        or any(not isinstance(day, str) or not day for day in days)
        or days != sorted(set(days))
    ):
        raise ValueError("capital reserve authority calendar is invalid")
    kind = record.get("authority_kind")
    if kind == "local_certified_reserve_stream_v1":
        _validate_legacy_manifest(record)
        return
    if kind != "source_day_reserve_stream_v1":
        raise ValueError("capital reserve authority kind is invalid")
    if not is_sha256(record.get("content_identity_sha256")):
        raise ValueError("capital reserve content identity is invalid")
    for partition in raw_partitions:
        inputs = partition.get("inputs") if isinstance(partition, Mapping) else None
        if not isinstance(inputs, list) or len(inputs) != 2:
            raise ValueError("capital reserve source-day inputs are invalid")
        for item in inputs:
            path = _resolve_record_path(item.get("path"))
            if (
                not path.is_file()
                or _timestamp_identity(path)
                != (item.get("bytes"), item.get("mtime_ns"))
            ):
                raise ValueError("capital reserve source-day input changed")


def cp_state_stream(
    venue: str,
    days: Iterable[str],
    *,
    raw_root: Path,
) -> CPStateStreamSet:
    """Bind capital measurement to hourly reserve source-day files."""

    return _cp_streams(
        venue,
        days,
        raw_root=raw_root,
        streams=(RESERVE_STREAM,),
        kind="reserve_stream",
    )


def cp_event_stream(
    venue: str,
    days: Iterable[str],
    *,
    raw_root: Path,
) -> CPStateStreamSet:
    """Bind event-based V2 analyses to their required source-day files."""

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
    normalized = tuple(str(day).replace("-", "") for day in days)
    if not normalized or normalized != tuple(sorted(set(normalized))):
        raise ValueError("source-day calendar must be nonempty, unique, and sorted")
    data_root = raw_root.parents[1]
    partitions: list[CPStreamPartition] = []
    for day in normalized:
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
            (path, _timestamp_identity(path))
            for snapshot in snapshots
            for path in (Path(snapshot["path"]), Path(snapshot["marker_path"]))
        )
        raw_paths = {raw_stream_path(raw_root, venue, stream, day) for stream in streams}
        semantic_paths = (
            tuple(
                path
                for path in state_partition_inputs(raw_root, "constant_product", venue, day)
                if path not in raw_paths
            )
            if kind == "event_stream"
            else ()
        )
        semantic_inputs = tuple((path, file_sha256(path)) for path in semantic_paths)
        fingerprint = canonical_json_sha256(
            {
                "raw_inputs": [
                    {"path": path.name, "bytes": identity[0], "mtime_ns": identity[1]}
                    for path, identity in raw_inputs
                ],
                "semantic_inputs": [
                    {"path": _record_path(path), "sha256": digest}
                    for path, digest in semantic_inputs
                ],
            }
        )
        partitions.append(
            CPStreamPartition(
                day=day,
                expected_bytes=sum(Path(snapshot["path"]).stat().st_size for snapshot in snapshots),
                expected_rows=sum(int(snapshot["rows"]) for snapshot in snapshots),
                input_fingerprint=fingerprint,
                raw_inputs=raw_inputs,
                semantic_inputs=semantic_inputs,
            )
        )
    frozen = tuple(partitions)
    return CPStateStreamSet(
        venue=venue,
        raw_root=raw_root,
        streams=streams,
        columns=tuple(CP_COLUMNS),
        partitions=frozen,
        content_identity_sha256=canonical_json_sha256(
            {
                "policy": f"source-day-cp-{kind.replace('_', '-')}-v1",
                "schema_version": SCHEMA_VERSION,
                "normalizer_engine": STATE_ENGINE,
                "partitions": [
                    {"venue": venue, "day": item.day, "input_fingerprint": item.input_fingerprint}
                    for item in frozen
                ],
            }
        ),
        kind=kind,
    )
