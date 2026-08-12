"""Certified reserve streams for purpose-bound constant-product capital."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from collections.abc import Iterator
from typing import Iterable, Mapping

from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.paths import REPO_ROOT
from ddvc.raw_certification import RawPartition, load_certified_partition_ledger, local_scan_certificate_path
from ddvc.state_data import CP_COLUMNS, CP_STREAMS, SCHEMA_VERSION, STATE_ENGINE, iter_normalised_cp_records, iter_normalised_cp_reserve_records, raw_stream_path, state_partition_inputs


RESERVE_STREAM = "hourly_reserves"


def _reserve_identity(row: Mapping[str, object]) -> str:
    return canonical_json_sha256(
        {
            "source": row.get("source"),
            "stream": row.get("stream"),
            "day": row.get("day"),
            "logical_content_sha256": row.get("logical_content_sha256"),
            "contract_sha256": row.get("contract_sha256"),
            "observed_query_contract_sha256": row.get("observed_query_contract_sha256"),
            "observed_head_block_at_fetch": row.get("observed_head_block_at_fetch"),
            "metadata_sha256": row.get("metadata_sha256"),
        }
    )


@dataclass(frozen=True)
class CPStreamPartition:
    day: str
    expected_bytes: int
    expected_rows: int
    input_fingerprint: str
    semantic_inputs: tuple[tuple[Path, str], ...] = ()


@dataclass(frozen=True)
class CPStateStreamSet:
    """One exact purpose-bound constant-product stream perimeter."""

    venue: str
    raw_root: Path
    streams: tuple[str, ...]
    columns: tuple[str, ...]
    partitions: tuple[CPStreamPartition, ...]
    content_identity_sha256: str
    ledger_path: Path
    ledger_sha256: str
    certificate_path: Path
    certificate_sha256: str
    family: str = "constant_product"
    kind: str = "reserve_stream"

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(partition.day for partition in self.partitions)

    @property
    def provenance_inputs(self) -> tuple[Path, ...]:
        paths = (
            self.certificate_path,
            self.ledger_path,
            *(
                path
                for partition in self.partitions
                for path, _digest in partition.semantic_inputs
            ),
        )
        return tuple(dict.fromkeys(paths))

    def manifest_record(self) -> dict[str, object]:
        """Serialize the exact selected reserve authority for later reopening."""

        if self.streams != (RESERVE_STREAM,):
            raise ValueError("only a reserve-only stream can enter the capital manifest")

        return {
            "authority_kind": "local_certified_reserve_stream_v1",
            "venue": self.venue,
            "content_identity_sha256": self.content_identity_sha256,
            "certificate_path": _record_path(self.certificate_path),
            "certificate_sha256": self.certificate_sha256,
            "ledger_path": _record_path(self.ledger_path),
            "ledger_sha256": self.ledger_sha256,
            "partitions": [
                {
                    "day": partition.day,
                    "expected_bytes": partition.expected_bytes,
                    "expected_rows": partition.expected_rows,
                    "input_fingerprint": partition.input_fingerprint,
                }
                for partition in self.partitions
            ],
        }

    def _partition(self, day: str) -> CPStreamPartition:
        normalized = str(day).replace("-", "")
        matches = [partition for partition in self.partitions if partition.day == normalized]
        if len(matches) != 1:
            raise KeyError(f"day is outside the certified reserve perimeter: {normalized}")
        return matches[0]

    def certified_rows(self, day: str) -> int:
        return self._partition(day).expected_rows

    def _certified_ledger_rows(self, days: Iterable[str]) -> list[dict[str, object]]:
        data_root = self.raw_root.parents[1]
        selected_days = tuple(days)
        requested = [
            RawPartition(self.venue, stream, day)
            for day in selected_days
            for stream in self.streams
        ]
        rows, _authority = load_certified_partition_ledger(
            self.certificate_path,
            data_root=data_root,
            partitions=requested,
        )
        observed = [
            (str(row.get("source")), str(row.get("stream")), str(row.get("day")))
            for row in rows
        ]
        expected = [
            (partition.source, partition.stream, partition.day)
            for partition in sorted(requested)
        ]
        if observed != expected:
            raise RuntimeError("certified reserve ledger returned a different partition perimeter")
        return rows

    def assert_current(self) -> None:
        if file_sha256(self.certificate_path) != self.certificate_sha256:
            raise RuntimeError(f"reserve certificate changed: {self.certificate_path}")
        if file_sha256(self.ledger_path) != self.ledger_sha256:
            raise RuntimeError(f"reserve partition ledger changed: {self.ledger_path}")
        rows = self._certified_ledger_rows(self.days)
        observed = {
            day: _complete_day_identity(
                [row for row in rows if str(row["day"]) == day],
                self._partition(day).semantic_inputs,
            )
            for day in self.days
        }
        for partition in self.partitions:
            if observed.get(partition.day) != partition.input_fingerprint:
                raise RuntimeError(f"certified reserve stream changed: {self.venue}/{partition.day}")

    def read_day(self, day: str) -> Iterator[dict[str, object]]:
        partition = self._partition(day)
        rows = self._certified_ledger_rows((partition.day,))
        if _complete_day_identity(rows, partition.semantic_inputs) != partition.input_fingerprint:
            raise RuntimeError(f"certified reserve stream changed: {self.venue}/{partition.day}")
        if self.streams == (RESERVE_STREAM,):
            return iter_normalised_cp_reserve_records(self.raw_root, self.venue, partition.day)
        return iter_normalised_cp_records(self.raw_root, self.venue, partition.day)

    def select_days(self, days: Iterable[str]) -> "CPStateStreamSet":
        normalized = tuple(str(day).replace("-", "") for day in days)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("reserve day selection must be nonempty and unique")
        partitions = tuple(self._partition(day) for day in normalized)
        identity = canonical_json_sha256(
            {
                "policy": f"certified-cp-{self.kind}-subset-v1",
                "parent_content_identity_sha256": self.content_identity_sha256,
                "days": normalized,
            }
        )
        return replace(self, partitions=partitions, content_identity_sha256=identity)


def _record_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _resolve_record_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def _certificate_data_root(certificate_path: Path) -> Path:
    """Recover the canonical data root from a local raw certificate path."""

    if (
        certificate_path.parent.name != "raw_generation"
        or certificate_path.parent.parent.name != "processed"
    ):
        raise ValueError(
            "capital reserve authority certificate is outside processed/raw_generation"
        )
    return certificate_path.parent.parent.parent


def _day_identity(rows: Iterable[Mapping[str, object]]) -> str:
    selected = list(rows)
    if len(selected) == 1:
        return _reserve_identity(selected[0])
    return canonical_json_sha256(
        [
            {
                "stream": str(row["stream"]),
                "identity_sha256": _reserve_identity(row),
            }
            for row in selected
        ]
    )


def _complete_day_identity(
    rows: Iterable[Mapping[str, object]],
    semantic_inputs: tuple[tuple[Path, str], ...],
) -> str:
    raw_identity = _day_identity(rows)
    observed_semantic = tuple(
        (_record_path(path), file_sha256(path))
        for path, _expected in semantic_inputs
    )
    expected_semantic = tuple(
        (_record_path(path), expected)
        for path, expected in semantic_inputs
    )
    if observed_semantic != expected_semantic:
        raise RuntimeError("constant-product semantic correction input changed")
    if not expected_semantic:
        return raw_identity
    return canonical_json_sha256(
        {
            "raw_identity_sha256": raw_identity,
            "semantic_inputs": expected_semantic,
        }
    )


def validate_certified_cp_stream_manifest(
    record: Mapping[str, object],
    *,
    expected_venue: str,
) -> None:
    """Reopen every selected raw identity recorded by a capital generation."""

    if record.get("authority_kind") != "local_certified_reserve_stream_v1":
        raise ValueError("capital reserve authority kind is invalid")
    if record.get("venue") != expected_venue:
        raise ValueError("capital reserve authority venue differs")
    certificate_path = _resolve_record_path(record.get("certificate_path"))
    ledger_path = _resolve_record_path(record.get("ledger_path"))
    if (
        not certificate_path.is_file()
        or file_sha256(certificate_path) != record.get("certificate_sha256")
        or not ledger_path.is_file()
        or file_sha256(ledger_path) != record.get("ledger_sha256")
    ):
        raise ValueError("capital reserve authority certificate or ledger changed")
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
    requested = [RawPartition(expected_venue, RESERVE_STREAM, str(day)) for day in days]
    data_root = _certificate_data_root(certificate_path)
    rows, _authority = load_certified_partition_ledger(
        certificate_path,
        data_root=data_root,
        partitions=requested,
    )
    observed_partitions = [
        {
            "day": str(row["day"]),
            "expected_bytes": int(row["container_bytes"]),
            "expected_rows": int(row["rows"]),
            "input_fingerprint": _reserve_identity(row),
        }
        for row in rows
    ]
    if observed_partitions != raw_partitions:
        raise ValueError("capital reserve authority partition identity changed")
    observed_content_identity = canonical_json_sha256(
        {
            "policy": "certified-cp-reserve-stream-v1",
            "schema_version": SCHEMA_VERSION,
            "normalizer_engine": STATE_ENGINE,
            "partitions": [
                {
                    "venue": expected_venue,
                    "day": item["day"],
                    "input_fingerprint": item["input_fingerprint"],
                }
                for item in observed_partitions
            ],
        }
    )
    if observed_content_identity != record.get("content_identity_sha256"):
        raise ValueError("capital reserve authority content identity changed")


def certified_cp_state_stream(
    venue: str,
    days: Iterable[str],
    *,
    raw_root: Path,
) -> CPStateStreamSet:
    """Bind capital measurement to certified hourly reserves and nothing else."""

    return _certified_cp_streams(
        venue,
        days,
        raw_root=raw_root,
        streams=(RESERVE_STREAM,),
        kind="reserve_stream",
    )


def certified_cp_event_stream(
    venue: str,
    days: Iterable[str],
    *,
    raw_root: Path,
) -> CPStateStreamSet:
    """Bind event-based V2 analyses to the exact required raw stream set."""

    if venue not in CP_STREAMS:
        raise ValueError(f"unsupported constant-product venue: {venue}")
    return _certified_cp_streams(
        venue,
        days,
        raw_root=raw_root,
        streams=tuple(stream for stream, _record_type, _sign in CP_STREAMS[venue]),
        kind="event_stream",
    )


def _certified_cp_streams(
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
        raise ValueError("reserve calendar must be nonempty, unique, and sorted")
    data_root = raw_root.parents[1]
    certificate_path = local_scan_certificate_path(venue, data_root=data_root)
    requested = [
        RawPartition(venue, stream, day)
        for day in normalized
        for stream in streams
    ]
    rows, _authority = load_certified_partition_ledger(
        certificate_path,
        data_root=data_root,
        partitions=requested,
    )
    observed = [
        (str(row.get("source")), str(row.get("stream")), str(row.get("day")))
        for row in rows
    ]
    expected = [
        (partition.source, partition.stream, partition.day)
        for partition in sorted(requested)
    ]
    if observed != expected:
        raise RuntimeError("certified reserve ledger returned a different partition perimeter")
    rows_by_day = {
        day: [row for row in rows if str(row["day"]) == day]
        for day in normalized
    }
    semantic_inputs_by_day: dict[str, tuple[tuple[Path, str], ...]] = {}
    for day in normalized:
        raw_paths = {
            raw_stream_path(raw_root, venue, stream, day)
            for stream in streams
        }
        semantic_paths = (
            tuple(
                path
                for path in state_partition_inputs(
                    raw_root, "constant_product", venue, day
                )
                if path not in raw_paths
            )
            if kind == "event_stream"
            else ()
        )
        semantic_inputs_by_day[day] = tuple(
            (path, file_sha256(path)) for path in semantic_paths
        )
    fingerprints = {
        day: _complete_day_identity(
            rows_by_day[day], semantic_inputs_by_day[day]
        )
        for day in normalized
    }
    partitions = tuple(
        CPStreamPartition(
            day=day,
            expected_bytes=sum(int(row["container_bytes"]) for row in rows_by_day[day]),
            expected_rows=sum(int(row["rows"]) for row in rows_by_day[day]),
            input_fingerprint=fingerprints[day],
            semantic_inputs=semantic_inputs_by_day[day],
        )
        for day in normalized
    )
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    ledger_path = certificate_path.with_name(str(certificate["partition_ledger"]))
    return CPStateStreamSet(
        venue=venue,
        raw_root=raw_root,
        streams=streams,
        columns=tuple(CP_COLUMNS),
        partitions=partitions,
        content_identity_sha256=canonical_json_sha256(
            {
                "policy": f"certified-cp-{kind.replace('_', '-')}-v1",
                "schema_version": SCHEMA_VERSION,
                "normalizer_engine": STATE_ENGINE,
                "partitions": [
                    {"venue": venue, "day": day, "input_fingerprint": fingerprints[day]}
                    for day in normalized
                ],
            }
        ),
        ledger_path=ledger_path,
        ledger_sha256=file_sha256(ledger_path),
        certificate_path=certificate_path,
        certificate_sha256=file_sha256(certificate_path),
        kind=kind,
    )
