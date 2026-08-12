"""Executable node-D release gate for every analysis-panel builder."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
from pathlib import Path

import pandas as pd

from ddvc.artifact_release import (
    canonical_json_sha256,
    file_sha256,
    file_stat_identity,
    is_sha256,
)
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source
from ddvc.reconstruct import (
    DEX_FAMILY,
    RECONSTRUCTION_ENGINE,
    UNIFIED_COLUMNS,
    UNIFIED_QUALITY_COLUMNS,
    UNIFIED_QUALITY_PANEL,
    active_route_sources,
    read_unified_quality,
    unified_path,
    unified_quality_path,
)
from ddvc.state_data import (
    CP_COLUMNS,
    FAMILY_STREAMS,
    MULTI_ASSET_COLUMNS,
    QUALITY_COLUMNS,
    RAW_ROOT,
    STATE_ENGINE,
    STATE_ROOT,
    TICK_COLUMNS,
    read_cp_quality,
    read_multi_asset_quality,
    read_tick_quality,
    state_partition_path,
    state_quality_path,
)
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import current_artifacts
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.runtime import serialized_read_installs
from ddvc.v2_event_completeness import (
    read_v2_event_source_release,
    resolve_v2_event_source_release,
    validate_v2_event_source_certificate,
    validate_v2_event_source_evidence_bundle,
)
from ddvc.v3_event_completeness import (
    read_v3_event_source_release,
    resolve_v3_event_source_release,
    validate_v3_event_source_certificate,
    validate_v3_event_source_evidence_bundle,
    v3_audit_days,
)
from ddvc.v4_quarantine import (
    V4_STATIC_QUARANTINE_PANEL,
    audit_v4_pool_static_conflicts,
    load_v4_static_quarantine,
)


MARKET_STATE_QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
ROUTE_RELEASE_ROOT = DATA_DIR / "unified"
MARKET_STATE_QUALITY_COLUMNS = [
    QUALITY_COLUMNS[0],
    "engine",
    *QUALITY_COLUMNS[1:],
    "scientific_support",
    "cross_venue_order_conflicts",
    "v4_static_conflict_pools",
]

STATE_COLUMN_CONTRACTS = {
    "tick": tuple(TICK_COLUMNS),
    "constant_product": tuple(CP_COLUMNS),
    "multi_asset": tuple(MULTI_ASSET_COLUMNS),
}


def _normalized_columns(columns: Iterable[str], contract: Iterable[str]) -> tuple[str, ...]:
    if isinstance(columns, (str, bytes)):
        raise ValueError("released partition columns must be an iterable of names")
    selected = tuple(str(column) for column in columns)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("released partition columns must be nonempty and unique")
    unknown = sorted(set(selected) - set(contract))
    if unknown:
        raise ValueError(f"released partition columns are outside the canonical schema: {unknown}")
    return selected


@dataclass(frozen=True)
class ReleasedPartition:
    """One ledger-selected immutable partition and its exact quality marker."""

    day: str
    path: Path
    marker_path: Path
    expected_rows: int
    expected_bytes: int
    expected_sha256: str
    marker_sha256: str
    input_fingerprint: str

    def assert_current(self) -> None:
        if not self.path.is_file() or not self.marker_path.is_file():
            raise RuntimeError(f"released partition disappeared: {self.path}")
        if self.path.stat().st_size != self.expected_bytes:
            raise RuntimeError(f"released partition size changed: {self.path}")
        if file_sha256(self.path) != self.expected_sha256:
            raise RuntimeError(f"released partition content changed: {self.path}")
        if file_sha256(self.marker_path) != self.marker_sha256:
            raise RuntimeError(f"released partition marker changed: {self.marker_path}")


@dataclass(frozen=True)
class ReleasedPartitionSet:
    """Ordered immutable partition perimeter admitted by one node-D ledger."""

    kind: str
    columns: tuple[str, ...]
    ledger_path: Path
    ledger_sha256: str
    partitions: tuple[ReleasedPartition, ...]
    content_identity_sha256: str
    provenance_inputs: tuple[Path, ...]
    family: str | None = None
    venue: str | None = None
    include_quarantined: bool = False
    quarantined_pools: tuple[str, ...] = ()
    quarantine_path: Path | None = None
    quarantine_sha256: str | None = None

    @property
    def days(self) -> tuple[str, ...]:
        return tuple(partition.day for partition in self.partitions)

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(partition.path for partition in self.partitions)

    @property
    def expected_rows(self) -> tuple[int, ...]:
        return tuple(partition.expected_rows for partition in self.partitions)

    def _partition(self, day: str) -> ReleasedPartition:
        normalized = str(day).replace("-", "")
        matches = [partition for partition in self.partitions if partition.day == normalized]
        if len(matches) != 1:
            raise KeyError(f"day is outside the released {self.kind} perimeter: {normalized}")
        return matches[0]

    def _lease_paths(self, partition: ReleasedPartition | None = None) -> tuple[Path, ...]:
        paths = [self.ledger_path]
        if self.kind == "route":
            route_root = (
                partition.path.parent
                if partition is not None
                else (
                    self.partitions[0].path.parent
                    if self.partitions
                    else self.ledger_path.parent
                )
            )
            paths.append(route_root)
        elif partition is not None:
            paths.extend((partition.path, partition.marker_path))
        if self.quarantine_path is not None:
            paths.append(self.quarantine_path)
        return tuple(dict.fromkeys(paths))

    def _assert_current_unlocked(self) -> None:
        if not self.ledger_path.is_file() or file_sha256(self.ledger_path) != self.ledger_sha256:
            raise RuntimeError(f"released {self.kind} ledger changed: {self.ledger_path}")
        if self.quarantine_path is not None and (
            not self.quarantine_path.is_file()
            or file_sha256(self.quarantine_path) != self.quarantine_sha256
        ):
            raise RuntimeError(f"released state quarantine changed: {self.quarantine_path}")
        for partition in self.partitions:
            partition.assert_current()

    def assert_current(self) -> None:
        with serialized_read_installs(self._lease_paths()):
            self._assert_current_unlocked()

    def select_days(self, days: Iterable[str]) -> ReleasedPartitionSet:
        """Return a lightweight immutable subset while retaining the parent release identity."""

        normalized = tuple(str(day).replace("-", "") for day in days)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("released partition day selection must be nonempty and unique")
        partitions = tuple(self._partition(day) for day in normalized)
        identity = canonical_json_sha256(
            {
                "policy": "node-d-released-partition-subset-v1",
                "parent_content_identity_sha256": self.content_identity_sha256,
                "days": normalized,
            }
        )
        provenance_inputs = (
            self.ledger_path,
            *((self.quarantine_path,) if self.quarantine_path is not None else ()),
            *(path for partition in partitions for path in (partition.path, partition.marker_path)),
        )
        return replace(
            self,
            partitions=partitions,
            content_identity_sha256=identity,
            provenance_inputs=provenance_inputs,
        )

    def read_day(self, day: str) -> pd.DataFrame:
        partition = self._partition(day)
        with serialized_read_installs(self._lease_paths(partition)):
            return self._read_day_unlocked(partition)

    def _read_day_unlocked(self, partition: ReleasedPartition) -> pd.DataFrame:
        if not self.ledger_path.is_file() or file_sha256(self.ledger_path) != self.ledger_sha256:
            raise RuntimeError(f"released {self.kind} ledger changed: {self.ledger_path}")
        before_quarantine = (
            file_stat_identity(self.quarantine_path)
            if self.quarantine_path is not None
            else None
        )
        if self.quarantine_path is not None and file_sha256(self.quarantine_path) != self.quarantine_sha256:
            raise RuntimeError(f"released state quarantine changed: {self.quarantine_path}")
        before_path = file_stat_identity(partition.path)
        before_marker = file_stat_identity(partition.marker_path)
        partition.assert_current()
        if self.quarantine_path is not None and (
            before_quarantine != file_stat_identity(self.quarantine_path)
            or file_sha256(self.quarantine_path) != self.quarantine_sha256
        ):
            raise RuntimeError(f"released state quarantine mutated during read: {self.quarantine_path}")
        read_columns = self.columns
        if self.kind == "state" and not self.include_quarantined and "usable" not in read_columns:
            read_columns = (*read_columns, "usable")
        if self.quarantined_pools and "pool" not in read_columns:
            read_columns = (*read_columns, "pool")
        frame = pd.read_parquet(partition.path, columns=list(read_columns))
        if len(frame) != partition.expected_rows:
            raise RuntimeError(f"released partition row count changed: {partition.path}")
        partition.assert_current()
        if before_path != file_stat_identity(partition.path) or before_marker != file_stat_identity(partition.marker_path):
            raise RuntimeError(f"released partition mutated during read: {partition.path}")
        if self.kind == "state" and not self.include_quarantined:
            frame = frame.loc[frame["usable"].astype(bool)].reset_index(drop=True)
            if self.quarantined_pools:
                frame = frame.loc[
                    ~frame["pool"].astype(str).str.lower().isin(self.quarantined_pools)
                ].reset_index(drop=True)
            if "usable" not in self.columns:
                frame = frame.drop(columns="usable")
            if self.quarantined_pools and "pool" not in self.columns:
                frame = frame.drop(columns="pool")
        return frame.loc[:, list(self.columns)]


@dataclass(frozen=True)
class ReleasePreinstallValidator:
    """Bind staged output provenance to the exact release used to derive it."""

    releases: tuple[ReleasedPartitionSet, ...]

    def __call__(self, _staged_path: Path) -> None:
        for release in self.releases:
            release.assert_current()

    @staticmethod
    def _resolved_record_path(value: object) -> Path:
        path = Path(str(value))
        return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()

    @staticmethod
    def _record_path(path: Path) -> str:
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(REPO_ROOT))
        except ValueError:
            return str(resolved)

    def _bindings(self) -> list[dict[str, str]]:
        bindings: dict[Path, str] = {}

        def bind(path: Path, expected_sha256: str) -> None:
            resolved = path.resolve()
            prior = bindings.setdefault(resolved, expected_sha256)
            if prior != expected_sha256:
                raise RuntimeError(
                    f"released input has conflicting identities: {resolved}"
                )

        for release in self.releases:
            bind(release.ledger_path, release.ledger_sha256)
            if release.quarantine_path is not None:
                if release.quarantine_sha256 is None:
                    raise RuntimeError("released quarantine lacks an exact identity")
                bind(release.quarantine_path, release.quarantine_sha256)
            for partition in release.partitions:
                bind(partition.path, partition.expected_sha256)
                bind(partition.marker_path, partition.marker_sha256)
        return [
            {"path": self._record_path(path), "sha256": digest}
            for path, digest in sorted(bindings.items(), key=lambda item: str(item[0]))
        ]

    def validate_prepared_stamp(self, prepared_stamp: bytes) -> bytes:
        """Recheck sources after stamping and embed their exact release identities."""

        try:
            record = json.loads(prepared_stamp)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("prepared provenance is not valid JSON") from exc
        input_paths = {
            self._resolved_record_path(item.get("path"))
            for item in record.get("inputs", [])
            if isinstance(item, dict) and item.get("path") is not None
        }
        bindings = self._bindings()
        missing = [
            binding["path"]
            for binding in bindings
            if self._resolved_record_path(binding["path"]) not in input_paths
        ]
        if missing:
            raise RuntimeError(
                f"prepared provenance omits {len(missing)} released inputs"
            )
        self(Path("<prepared-provenance>"))
        record["released_input_bindings"] = bindings
        return (
            json.dumps(record, indent=1, sort_keys=True) + "\n"
        ).encode()


def release_preinstall_validator(
    *releases: ReleasedPartitionSet,
) -> ReleasePreinstallValidator:
    """Return a staged-output validator that rechecks every bound release."""

    if not releases:
        raise ValueError("release pre-install validation requires at least one release")
    return ReleasePreinstallValidator(tuple(releases))


def audit_cross_venue_order_conflicts(
    venue_paths: Mapping[str, Iterable[str | Path]], *, sample_limit: int = 3
) -> tuple[int, list[dict[str, object]]]:
    """Count causal keys claimed by each pair of canonical tick-state venues."""
    import duckdb

    ordered = {
        venue: sorted(str(Path(path)) for path in paths)
        for venue, paths in sorted(venue_paths.items())
    }
    empty = [venue for venue, paths in ordered.items() if not paths]
    if len(ordered) < 2 or empty:
        raise ValueError(
            "cross-venue order audit requires at least two nonempty venue perimeters"
        )
    if sample_limit < 1:
        raise ValueError("cross-venue order audit sample limit must be positive")
    connection = duckdb.connect()
    collision_count = 0
    samples: list[dict[str, object]] = []
    try:
        venues = list(ordered)
        for left_index, left_venue in enumerate(venues):
            for right_venue in venues[left_index + 1 :]:
                pair_count = int(
                    connection.execute(
                        """
                        SELECT count(*)
                        FROM (
                            SELECT left_state.block_number, left_state.log_index
                            FROM read_parquet(?, union_by_name=true) AS left_state
                            INNER JOIN read_parquet(?, union_by_name=true) AS right_state
                            USING (block_number, log_index)
                            WHERE left_state.usable AND right_state.usable
                            GROUP BY left_state.block_number, left_state.log_index
                        )
                        """,
                        [ordered[left_venue], ordered[right_venue]],
                    ).fetchone()[0]
                )
                collision_count += pair_count
                remaining = sample_limit - len(samples)
                if pair_count == 0 or remaining == 0:
                    continue
                rows = connection.execute(
                    """
                    SELECT
                        left_state.block_number,
                        left_state.log_index,
                        list(DISTINCT left_state.tx_hash ORDER BY left_state.tx_hash),
                        list(DISTINCT right_state.tx_hash ORDER BY right_state.tx_hash)
                    FROM read_parquet(?, union_by_name=true) AS left_state
                    INNER JOIN read_parquet(?, union_by_name=true) AS right_state
                    USING (block_number, log_index)
                    WHERE left_state.usable AND right_state.usable
                    GROUP BY left_state.block_number, left_state.log_index
                    ORDER BY left_state.block_number, left_state.log_index
                    LIMIT ?
                    """,
                    [ordered[left_venue], ordered[right_venue], remaining],
                ).fetchall()
                samples.extend(
                    {
                        "block_number": int(block_number),
                        "log_index": int(log_index),
                        "venues": [left_venue, right_venue],
                        "transaction_hashes": sorted({*left_hashes, *right_hashes}),
                    }
                    for block_number, log_index, left_hashes, right_hashes in rows
                )
    finally:
        connection.close()
    return collision_count, samples


def _exact_key_gate(
    *,
    label: str,
    actual: Iterable[tuple[str, ...]],
    expected: Iterable[tuple[str, ...]],
) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    if actual_set == expected_set:
        return
    missing = sorted(expected_set - actual_set)[:3]
    extra = sorted(actual_set - expected_set)[:3]
    raise RuntimeError(
        f"node D has not released {label}: missing={missing}, extra={extra}"
    )


def expected_route_days() -> list[str]:
    return calendar_days(RESEARCH_SAMPLE_START, RESEARCH_SAMPLE_END)


def expected_state_keys() -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for family, venues in FAMILY_STREAMS.items():
        for venue in venues:
            start = max(
                RESEARCH_SAMPLE_START,
                get_source(venue).genesis.strftime("%Y%m%d"),
            )
            keys.extend(
                (family, venue, day)
                for day in calendar_days(start, RESEARCH_SAMPLE_END)
            )
    return keys


def _validated_release_ledger_unlocked(kind: str) -> pd.DataFrame:
    """Read and fully validate the one canonical ledger for a node-D family."""

    if kind not in {"route", "state"}:
        raise ValueError(f"unsupported node-D ledger kind: {kind}")
    path = UNIFIED_QUALITY_PANEL if kind == "route" else MARKET_STATE_QUALITY_PANEL
    label = "directed-route" if kind == "route" else "market-state"
    if not path.is_file():
        raise RuntimeError(f"node D has not released the full {label} quality ledger")
    before = file_stat_identity(path)
    ledger_sha256 = file_sha256(path)
    quality = pd.read_parquet(path)
    if before != file_stat_identity(path) or file_sha256(path) != ledger_sha256:
        raise RuntimeError(f"node D {label} quality ledger mutated during validation")
    quality.attrs["ledger_sha256"] = ledger_sha256
    expected_columns = UNIFIED_QUALITY_COLUMNS if kind == "route" else MARKET_STATE_QUALITY_COLUMNS
    if list(quality.columns) != expected_columns:
        raise RuntimeError(f"node D {label} quality schema is stale")
    if kind == "route":
        expected_days = expected_route_days()
        _exact_key_gate(
            label="the full directed-route calendar",
            actual=((str(day).zfill(8),) for day in quality["day"]),
            expected=((day,) for day in expected_days),
        )
        if quality["day"].astype(str).duplicated().any():
            raise RuntimeError("node D directed-route ledger contains duplicate days")
        if set(quality["engine"].astype(str)) != {RECONSTRUCTION_ENGINE}:
            raise RuntimeError("node D directed-route ledger belongs to a stale engine")
        if not quality["passed"].astype(bool).all():
            raise RuntimeError("node D directed-route ledger contains failed days")
        expected_venue_days = sum(
            len(active_route_sources(day, list(DEX_FAMILY))) for day in expected_days
        )
        if int(quality["expected_sources"].sum()) != expected_venue_days:
            raise RuntimeError("node D directed-route venue-day perimeter is incomplete")
        stale = [
            day
            for day in expected_days
            if read_unified_quality(day, list(DEX_FAMILY)) is None
        ]
        if stale:
            raise RuntimeError(f"node D directed-route release has {len(stale)} stale day(s), first={stale[0]}")
        ordered = quality.sort_values("day", kind="stable").reset_index(drop=True)
        ordered.attrs["ledger_sha256"] = ledger_sha256
        return ordered
    expected = expected_state_keys()
    actual = (
        (str(row.family), str(row.venue), str(row.day).zfill(8))
        for row in quality.itertuples(index=False)
    )
    _exact_key_gate(label="the full market-state calendar", actual=actual, expected=expected)
    if quality.duplicated(["family", "venue", "day"]).any():
        raise RuntimeError("node D market-state ledger contains duplicate partitions")
    if set(quality["engine"].astype(str)) != {STATE_ENGINE}:
        raise RuntimeError("node D market-state ledger belongs to a stale engine")
    if not quality["passed"].astype(bool).all():
        raise RuntimeError("node D market-state ledger contains failed partitions")
    conflict_counts = quality["cross_venue_order_conflicts"].astype(int)
    if conflict_counts.nunique() != 1 or int(conflict_counts.iloc[0]) != 0:
        raise RuntimeError("node D market-state ledger contains inconsistent or nonzero cross-venue block-log conflicts")
    quarantine_counts = quality["v4_static_conflict_pools"].astype(int)
    if quarantine_counts.nunique() != 1:
        raise RuntimeError("node D market-state ledger has inconsistent V4 quarantine counts")
    if int(quarantine_counts.iloc[0]) != len(
        load_v4_static_quarantine(V4_STATIC_QUARANTINE_PANEL)
    ):
        raise RuntimeError("node D market-state ledger disagrees with the V4 quarantine")
    support = quality["scientific_support"].astype(bool)
    if not pd.api.types.is_bool_dtype(quality["scientific_support"]):
        raise RuntimeError("node D market-state scientific support is not boolean")
    if not support.loc[~((quality["family"] == "tick") & (quality["venue"] == "uniswap_v4"))].all():
        raise RuntimeError("node D marks a non-V4 market-state partition scientifically unsupported")
    v4_support = quality.loc[(quality["family"] == "tick") & (quality["venue"] == "uniswap_v4"), ["day", "scientific_support"]].sort_values("day", kind="stable")
    if v4_support["scientific_support"].astype(bool).cummin().ne(v4_support["scientific_support"].astype(bool)).any():
        raise RuntimeError("node D V4 scientific support reopens after the exact prefix ends")
    readers = {
        "tick": read_tick_quality,
        "constant_product": read_cp_quality,
        "multi_asset": read_multi_asset_quality,
    }
    stale = [
        (family, venue, day)
        for family, venue, day in expected
        if readers[family](RAW_ROOT, venue, day) is None
    ]
    if stale:
        raise RuntimeError(f"node D market-state release has {len(stale)} stale partition(s), first={stale[0]}")
    ordered = quality.sort_values(["family", "venue", "day"], kind="stable").reset_index(drop=True)
    ordered.attrs["ledger_sha256"] = ledger_sha256
    return ordered


@contextmanager
def _current_release_ledger(kind: str) -> Iterator[pd.DataFrame]:
    """Lease and validate one ledger through its caller's complete consumption."""

    if kind not in {"route", "state"}:
        raise ValueError(f"unsupported node-D ledger kind: {kind}")
    path = UNIFIED_QUALITY_PANEL if kind == "route" else MARKET_STATE_QUALITY_PANEL
    label = "directed-route" if kind == "route" else "market-state"
    with serialized_read_installs(_release_lease_paths(kind), allow_missing=True):
        with current_artifacts([path], consumer=f"node D {label} release"):
            yield _validated_release_ledger_unlocked(kind)


def _validated_release_ledger(kind: str) -> pd.DataFrame:
    """Validate one ledger while excluding a concurrent release publication."""

    with _current_release_ledger(kind) as quality:
        return quality


def _release_lease_paths(kind: str) -> tuple[Path, ...]:
    """Return the one publication perimeter leased by a node-D reader."""

    if kind == "route":
        return (UNIFIED_QUALITY_PANEL, ROUTE_RELEASE_ROOT)
    if kind == "state":
        return (MARKET_STATE_QUALITY_PANEL,)
    raise ValueError(f"unsupported node-D ledger kind: {kind}")


def require_route_release() -> None:
    _validated_release_ledger("route")


def require_market_state_prerelease() -> None:
    """Require structural state integrity before dependent source certificates exist."""

    _validated_release_ledger("state")


def _released_partition(
    *,
    day: str,
    path: Path,
    marker_path: Path,
    expected_rows: object,
    expected_bytes: object,
    expected_sha256: object,
    input_fingerprint: object,
) -> ReleasedPartition:
    if not path.is_file() or not marker_path.is_file():
        raise RuntimeError(f"node D ledger selects a missing partition or marker: {path}")
    try:
        rows, size = int(expected_rows), int(expected_bytes)
        digest = str(expected_sha256)
        fingerprint = str(input_fingerprint)
        if rows < 0 or size < 0 or not is_sha256(digest) or not is_sha256(fingerprint):
            raise ValueError("malformed identity")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise ValueError("marker is not an object")
        marker_rows = marker.get("output_rows", marker.get("canonical_rows"))
        marker_matches = (
            str(marker.get("day")).replace("-", "") == day
            and int(marker_rows if marker_rows is not None else -1) == rows
            and int(marker.get("output_bytes", -1)) == size
            and marker.get("output_sha256") == digest
            and marker.get("input_fingerprint") == fingerprint
            and marker.get("passed") is True
        )
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(f"node D partition marker is unreadable: {marker_path}") from error
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"node D ledger has malformed partition identity: {path}") from error
    if not marker_matches:
        raise RuntimeError(f"node D ledger disagrees with partition marker: {marker_path}")
    partition = ReleasedPartition(
        day=day,
        path=path,
        marker_path=marker_path,
        expected_rows=rows,
        expected_bytes=size,
        expected_sha256=digest,
        marker_sha256=file_sha256(marker_path),
        input_fingerprint=fingerprint,
    )
    partition.assert_current()
    return partition


def _released_partition_set(
    *,
    kind: str,
    columns: tuple[str, ...],
    ledger_path: Path,
    ledger_sha256: str,
    partitions: tuple[ReleasedPartition, ...],
    family: str | None = None,
    venue: str | None = None,
    include_quarantined: bool = False,
    quarantined_pools: tuple[str, ...] = (),
    quarantine_path: Path | None = None,
    quarantine_sha256: str | None = None,
) -> ReleasedPartitionSet:
    if file_sha256(ledger_path) != ledger_sha256:
        raise RuntimeError(f"released {kind} ledger changed during partition binding")
    if (quarantine_path is None) != (quarantine_sha256 is None):
        raise ValueError("released state quarantine path and digest must be bound together")
    identity = canonical_json_sha256(
        {
            "policy": "node-d-released-partitions-v1",
            "kind": kind,
            "family": family,
            "venue": venue,
            "columns": columns,
            "include_quarantined": include_quarantined,
            "quarantined_pools": quarantined_pools,
            "quarantine_sha256": quarantine_sha256,
            "ledger_sha256": ledger_sha256,
            "partitions": [
                {
                    "day": partition.day,
                    "rows": partition.expected_rows,
                    "bytes": partition.expected_bytes,
                    "sha256": partition.expected_sha256,
                    "marker_sha256": partition.marker_sha256,
                    "input_fingerprint": partition.input_fingerprint,
                }
                for partition in partitions
            ],
        }
    )
    provenance_inputs = (
        ledger_path,
        *((quarantine_path,) if quarantine_path is not None else ()),
        *(path for partition in partitions for path in (partition.path, partition.marker_path)),
    )
    return ReleasedPartitionSet(
        kind=kind,
        columns=columns,
        ledger_path=ledger_path,
        ledger_sha256=ledger_sha256,
        partitions=partitions,
        content_identity_sha256=identity,
        provenance_inputs=provenance_inputs,
        family=family,
        venue=venue,
        include_quarantined=include_quarantined,
        quarantined_pools=quarantined_pools,
        quarantine_path=quarantine_path,
        quarantine_sha256=quarantine_sha256,
    )


def released_route_partitions(columns: Iterable[str], *, nonempty: bool = False) -> ReleasedPartitionSet:
    """Return all released days, or only days with positive route-row support."""

    selected_columns = _normalized_columns(columns, UNIFIED_COLUMNS)
    with _current_release_ledger("route") as quality:
        ledger_sha256 = str(quality.attrs["ledger_sha256"])
        if nonempty:
            quality = quality.loc[quality["output_rows"].astype(int).gt(0)].copy()
            if quality.empty:
                raise RuntimeError("node D released route perimeter has no nonempty partitions")
        partitions = tuple(
            _released_partition(
                day=str(row.day).zfill(8),
                path=unified_path(str(row.day).zfill(8)),
                marker_path=unified_quality_path(str(row.day).zfill(8)),
                expected_rows=row.output_rows,
                expected_bytes=row.output_bytes,
                expected_sha256=row.output_sha256,
                input_fingerprint=row.input_fingerprint,
            )
            for row in quality.itertuples(index=False)
        )
        return _released_partition_set(
            kind="route",
            columns=selected_columns,
            ledger_path=UNIFIED_QUALITY_PANEL,
            ledger_sha256=ledger_sha256,
            partitions=partitions,
        )


def released_state_partitions(
    family: str,
    venue: str,
    columns: Iterable[str],
    *,
    include_quarantined: bool = False,
) -> ReleasedPartitionSet:
    """Return one exact immutable state perimeter selected by node D."""

    if family not in FAMILY_STREAMS or venue not in FAMILY_STREAMS[family]:
        raise ValueError(f"unsupported canonical state family/venue: {family}/{venue}")
    selected_columns = _normalized_columns(columns, STATE_COLUMN_CONTRACTS[family])
    with _current_release_ledger("state") as quality:
        ledger_sha256 = str(quality.attrs["ledger_sha256"])
        selected = quality.loc[
            quality["family"].astype(str).eq(family)
            & quality["venue"].astype(str).eq(venue)
        ].sort_values("day", kind="stable")
        if family == "tick" and venue == "uniswap_v4":
            selected = selected.loc[selected["scientific_support"].astype(bool)].copy()
            if selected.empty:
                raise RuntimeError("node D V4 state release has no scientifically supported exact-prefix partitions")
        partitions = tuple(
            _released_partition(
                day=str(row.day).zfill(8),
                path=state_partition_path(family, venue, str(row.day).zfill(8), root=STATE_ROOT),
                marker_path=state_quality_path(family, venue, str(row.day).zfill(8), root=STATE_ROOT),
                expected_rows=row.canonical_rows,
                expected_bytes=row.output_bytes,
                expected_sha256=row.output_sha256,
                input_fingerprint=row.input_fingerprint,
            )
            for row in selected.itertuples(index=False)
        )
        quarantined_pools: tuple[str, ...] = ()
        quarantine_path: Path | None = None
        quarantine_sha256: str | None = None
        if family == "tick" and venue == "uniswap_v4" and not include_quarantined:
            quarantine_path = V4_STATIC_QUARANTINE_PANEL
            before = file_stat_identity(quarantine_path)
            quarantine_sha256 = file_sha256(quarantine_path)
            quarantined_pools = tuple(
                sorted(load_v4_static_quarantine(quarantine_path))
            )
            if (
                before != file_stat_identity(quarantine_path)
                or file_sha256(quarantine_path) != quarantine_sha256
            ):
                raise RuntimeError("V4 static quarantine mutated during release binding")
        return _released_partition_set(
            kind="state",
            columns=selected_columns,
            ledger_path=MARKET_STATE_QUALITY_PANEL,
            ledger_sha256=ledger_sha256,
            partitions=partitions,
            family=family,
            venue=venue,
            include_quarantined=include_quarantined,
            quarantined_pools=quarantined_pools,
            quarantine_path=quarantine_path,
            quarantine_sha256=quarantine_sha256,
        )


def require_market_state_release() -> None:
    """Require structural state integrity and every independent source certificate."""

    require_market_state_prerelease()
    require_v2_event_source_release()
    require_v3_event_source_release()


def require_v2_event_source_release() -> None:
    """Require the current independent-chain certificate for V2 replay events."""

    try:
        release = resolve_v2_event_source_release()
        with current_artifacts(
            list(release.artifact_paths),
            consumer="node D V2-family market-state release",
        ):
            summary, exceptions, certificate = read_v2_event_source_release(release)
            expected_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
            validate_v2_event_source_certificate(
                summary,
                exceptions,
                certificate,
                expected_days,
            )
            validate_v2_event_source_evidence_bundle(certificate, summary=summary)
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"node D V2-family event-source certificate failed: {error}"
        ) from error


def require_v3_event_source_release() -> None:
    """Require the current independent-chain certificate for V3 core events."""

    try:
        release = resolve_v3_event_source_release()
        with current_artifacts(
            list(release.artifact_paths),
            consumer="node D V3 market-state release",
        ):
            summary, exceptions, quarantine, certificate = read_v3_event_source_release(
                release
            )
            expected_days = v3_audit_days(UNIFIED_QUALITY_PANEL)
            validate_v3_event_source_certificate(
                summary,
                exceptions,
                quarantine,
                certificate,
                expected_days,
            )
            validate_v3_event_source_evidence_bundle(
                certificate, summary=summary, quarantine=quarantine
            )
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"node D V3 event-source certificate failed: {error}"
        ) from error


def require_node_d_release(*, routes: bool = False, market_state: bool = False) -> None:
    if not routes and not market_state:
        raise ValueError("at least one node-D contract must be required")
    if routes:
        require_route_release()
    if market_state:
        require_market_state_release()
