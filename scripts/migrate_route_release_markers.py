#!/usr/bin/env python3
"""Migrate one proven-equivalent route release without rebuilding partitions.

This is a marker migration, not a route rebuild. It accepts only the named
legacy and current engines, validates every legacy Parquet against its marker
and ledger, resolves every current raw input through its installed authority,
and requires exact fresh reconstruction on every released day.
The engine migration proves equivalence by exact fresh reconstruction. The
storage-authority relocation mode instead requires a pre-relocation authority
snapshot, exact scientific raw identities, and byte-identical released
partitions. When no pre-change snapshot exists because a per-source local
certificate merely gained non-route streams for another consumer family, the
perimeter-expansion derivation reconstructs the prior certificate from the
current ledger's rows for the prior stream perimeter (the route stream alone,
or the exact named stream set the pre-expansion certificate covered) and
admits it only when the derived per-day fingerprints reproduce every released
marker exactly, then feeds the standard relocation gate. No live marker
changes occur until the complete plan passes.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ddvc.artifact_release import (
    canonical_json_sha256,
    file_sha256,
    file_stat_identity,
    generation_id,
    is_sha256,
)
from ddvc.data_release import released_route_partitions
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    current_endpoint_candidate_composition_release,
)
from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, OUTPUT_DIR, RAW_MARKET_DATA_LOCK, REPO_ROOT
from ddvc.journaled_publication import publish_journaled_bundle, recover_journaled_publications
from ddvc.provenance import (
    code_fingerprint,
    current_artifacts,
    describe_input,
    input_matches,
    prepare_stamp,
    sidecar_path,
    verify,
)
from ddvc.reconstruct import (
    DEX_FAMILY,
    DEX_STREAM,
    DUNE_SOURCES,
    RECONSTRUCT_CODE_SOURCES,
    RECONSTRUCTION_ENGINE,
    UNIFIED_COLUMNS,
    UNIFIED_QUALITY_COLUMNS,
    UNIFIED_QUALITY_EXHIBIT,
    UNIFIED_QUALITY_PANEL,
    _available_days,
    active_route_sources,
    reconstruct_day_with_quality,
    route_input_fingerprint,
    unified_path,
    unified_quality_path,
)
from ddvc.raw_certification import (
    LOCAL_CERTIFICATE_POLICY,
    RawPartition,
    local_scan_certificate_path,
    raw_partition_relocation_identity,
    write_local_scan_certificate,
)
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
    interruptible_thread_pool,
    serialized_output_installs,
)
from ddvc.tables import _stringify_big_ints


LEGACY_ENGINE = "514160b28189"
MIGRATION_TARGET_ENGINE = "d3f16e9c4da6"
MIGRATION_POLICY = "route-release-marker-migration-v2"
RELOCATION_POLICY = "route-release-storage-authority-relocation-v1"
AUTHORITY_SNAPSHOT_POLICY = "route-raw-authority-snapshot-v1"
PERIMETER_EXPANSION_DERIVATION_POLICY = (
    "route-raw-authority-perimeter-expansion-derivation-v1"
)
JOURNAL_ROOT_NAME = ".route-marker-migration-journals"
_OUTPUT_IDENTITY_FIELDS = {
    "output_bytes",
    "output_mtime_ns",
    "output_sha256",
}
_MIGRATABLE_IDENTITY_FIELDS = {
    "engine",
    "input_fingerprint",
    *_OUTPUT_IDENTITY_FIELDS,
}


@dataclass(frozen=True)
class MigrationPlan:
    migration_policy: str
    days: tuple[str, ...]
    quality: pd.DataFrame
    markers: dict[str, dict[str, object]]
    legacy_marker_sha256: dict[str, str]
    current_input_fingerprints: dict[str, str]
    validation: pd.DataFrame
    authority_snapshot_sha256: str | None = None

    @property
    def legacy_marker_set_sha256(self) -> str:
        return canonical_json_sha256(self.legacy_marker_sha256)


def _stamp(day: object) -> str:
    return str(day).replace("-", "").zfill(8)


def _calendar_day(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def _json_value(value: object) -> object:
    if hasattr(value, "item"):
        value = value.item()
    return value


def _selected_days(dexes: list[str], days: list[str] | None) -> tuple[str, ...]:
    selected = tuple(
        _stamp(day) for day in (days if days is not None else _available_days(dexes))
    )
    if len(selected) != len(set(selected)) or tuple(sorted(selected)) != selected:
        raise ValueError("route marker migration days must be unique and sorted")
    return selected


def _load_release_perimeter(
    *,
    selected: tuple[str, ...],
    unified_root: Path,
    quality_panel: Path,
    expected_engine: str,
) -> tuple[pd.DataFrame, dict[str, dict[str, object]], dict[str, str]]:
    if not quality_panel.is_file():
        raise FileNotFoundError("route quality ledger is missing")
    ledger = pd.read_parquet(quality_panel)
    ledger["day"] = ledger["day"].map(_stamp)
    if tuple(ledger["day"].tolist()) != selected:
        raise ValueError("route quality ledger perimeter is not exact")
    observed_markers = {
        path.stem for path in (unified_root / ".quality").glob("*.json")
    }
    if observed_markers != set(selected):
        raise ValueError("route marker directory perimeter is not exact")
    markers: dict[str, dict[str, object]] = {}
    marker_hashes: dict[str, str] = {}
    for day in selected:
        marker, marker_hash = _validate_partition(
            day, unified_root=unified_root, expected_engine=expected_engine
        )
        markers[day] = marker
        marker_hashes[day] = marker_hash
    _require_exact_ledger_rows(ledger, markers)
    return ledger, markers, marker_hashes


def _snapshot_digest(payload: dict[str, object]) -> str:
    body = {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    return canonical_json_sha256(body)


def route_authority_snapshot(
    *,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    dexes: list[str],
    days: list[str] | None = None,
) -> dict[str, object]:
    """Capture the raw authority evidence required before a storage relocation."""

    selected = _selected_days(dexes, days)
    ledger, markers, marker_hashes = _load_release_perimeter(
        selected=selected,
        unified_root=unified_root,
        quality_panel=quality_panel,
        expected_engine=RECONSTRUCTION_ENGINE,
    )
    entries: list[dict[str, object]] = []
    for day in selected:
        for source in active_route_sources(_calendar_day(day), dexes):
            stream = DEX_STREAM[source]
            relocation = raw_partition_relocation_identity(
                source, stream, day, data_root=data_root
            )
            generation = relocation.get("generation_identity_sha256")
            if not is_sha256(generation):
                raise ValueError(
                    f"raw authority lacks generation identity: {source}/{stream}/{day}"
                )
            scientific = relocation["scientific_identity"]
            assert isinstance(scientific, dict)
            entries.append(
                {
                    "source": source,
                    "stream": stream,
                    "day": day,
                    "generation_identity_sha256": generation,
                    "scientific_identity": scientific,
                    "scientific_identity_sha256": canonical_json_sha256(scientific),
                }
            )
    payload: dict[str, object] = {
        "policy": AUTHORITY_SNAPSHOT_POLICY,
        "route_engine": RECONSTRUCTION_ENGINE,
        "days": list(selected),
        "dexes": list(dexes),
        "entries": entries,
        "route_release": {
            "quality_ledger_sha256": file_sha256(quality_panel),
            "quality_ledger_rows": len(ledger),
            "marker_sha256": marker_hashes,
            "partitions": {
                day: {
                    "rows": int(markers[day]["output_rows"]),
                    "bytes": int(markers[day]["output_bytes"]),
                    "sha256": str(markers[day]["output_sha256"]),
                }
                for day in selected
            },
        },
    }
    payload["snapshot_sha256"] = _snapshot_digest(payload)
    return payload


def write_route_authority_snapshot(
    path: Path,
    *,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    dexes: list[str],
    days: list[str] | None = None,
    raw_lock: Path = RAW_MARKET_DATA_LOCK,
) -> dict[str, object]:
    """Write one immutable pre-relocation raw-authority snapshot atomically."""

    with exclusive_job(
        raw_lock,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with serialized_output_installs((unified_root, quality_panel)):
            if path.exists() or path.is_symlink():
                raise FileExistsError(
                    f"route authority snapshot already exists: {path}"
                )
            payload = route_authority_snapshot(
                data_root=data_root,
                unified_root=unified_root,
                quality_panel=quality_panel,
                dexes=dexes,
                days=days,
            )
            with atomic_output(path) as temporary:
                temporary.write_text(
                    json.dumps(payload, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    if json.loads(path.read_text(encoding="utf-8")) != payload:
        raise RuntimeError("route authority snapshot did not reopen exactly")
    return payload


def _derived_prior_generation_identity(
    certificate: dict[str, object],
    *,
    row: dict[str, object],
    source_registry_generation: str,
) -> str:
    """Recompute the identity the prior route-stream certificate granted one row.

    Mirrors the local-certificate branch of raw_partition_read_authority; any
    drift between the two formulas fails closed because the derived per-day
    fingerprints must reproduce every released marker exactly.
    """

    selected_identity = [
        {
            "source": row["source"],
            "stream": row["stream"],
            "day": row["day"],
            "logical_content_sha256": row["logical_content_sha256"],
            "contract_sha256": row["contract_sha256"],
            "observed_query_contract_sha256": row.get(
                "observed_query_contract_sha256"
            ),
            "observed_head_block_at_fetch": row.get("observed_head_block_at_fetch"),
            "metadata_sha256": row.get("metadata_sha256"),
        }
    ]
    authority = {
        "policy": LOCAL_CERTIFICATE_POLICY,
        "certificate_sha256": certificate["certificate_sha256"],
        "partition_ledger_sha256": certificate["partition_ledger_sha256"],
        "partition_count": certificate["partition_count"],
        "selected_partition_count": 1,
        "selected_partition_identity_sha256": canonical_json_sha256(
            selected_identity
        ),
    }
    return canonical_json_sha256(
        {
            "authority": authority,
            "source": row["source"],
            "stream": row["stream"],
            "day": row["day"],
            "logical_content_sha256": row["logical_content_sha256"],
            "contract_sha256": row["contract_sha256"],
            "observed_query_contract_sha256": row.get(
                "observed_query_contract_sha256"
            ),
            "observed_head_block_at_fetch": row.get("observed_head_block_at_fetch"),
            "metadata_sha256": row.get("metadata_sha256"),
            "source_registry_generation_sha256": source_registry_generation,
        }
    )


def parse_expanded_source_specs(
    expanded_sources: list[str],
) -> dict[str, frozenset[str]]:
    """Parse `source` or `source=streamA,streamB` prior-perimeter specs.

    A bare source names the route stream alone; the explicit form names the
    exact stream set the pre-expansion certificate covered. The route stream
    must always be inside the prior perimeter, because the released markers
    bind their route partitions through that certificate.
    """

    specs: dict[str, frozenset[str]] = {}
    for raw in expanded_sources:
        source, separator, streams_text = raw.partition("=")
        source = source.strip()
        if not source:
            raise ValueError(f"expanded source spec lacks a source: {raw!r}")
        if separator:
            streams = frozenset(
                stream.strip() for stream in streams_text.split(",") if stream.strip()
            )
            if not streams:
                raise ValueError(f"expanded source spec lacks streams: {raw!r}")
        else:
            streams = frozenset({DEX_STREAM[source]}) if source in DEX_STREAM else frozenset()
        prior = specs.get(source)
        if prior is not None and prior != streams:
            raise ValueError(
                f"expanded source {source} has conflicting prior perimeters"
            )
        specs[source] = streams
    return specs


def _reconstruct_prior_route_stream_certificate(
    source: str,
    *,
    data_root: Path,
    scratch: Path,
    prior_streams: frozenset[str] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Rebuild the pre-expansion certificate from the current ledger's rows.

    The prior perimeter defaults to the route stream alone; when the
    pre-expansion certificate also covered other unchanged streams (for
    example hourly_reserves certified for the capital consumer), the caller
    names that exact stream set and the reconstruction takes those rows
    verbatim from the current ledger. Every reconstructed row must carry the
    current contract identity, so a stream whose consumer contract changed in
    the expansion can never be smuggled into the prior perimeter.
    """

    stream = DEX_STREAM[source]
    streams = prior_streams or frozenset({stream})
    if stream not in streams:
        raise ValueError(
            f"prior certificate perimeter must include the route stream: "
            f"{source}/{stream}"
        )
    certificate_path = local_scan_certificate_path(source, data_root=data_root)
    current_certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    ledger_path = certificate_path.with_name(
        str(current_certificate["partition_ledger"])
    )
    rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    subset = [row for row in rows if row["stream"] in streams]
    observed_streams = {str(row["stream"]) for row in subset}
    if missing_streams := sorted(streams - observed_streams):
        raise ValueError(
            f"current certificate carries no rows for prior streams: "
            f"{source}/{','.join(missing_streams)}"
        )
    if len(subset) == len(rows):
        raise ValueError(
            f"certificate perimeter was not expanded beyond the route stream: {source}"
        )
    workspace = scratch / source
    workspace.mkdir()
    prior_certificate = write_local_scan_certificate(
        workspace / certificate_path.name,
        subset,
        expected_partitions=[
            RawPartition(str(row["source"]), str(row["stream"]), str(row["day"]))
            for row in subset
        ],
        ledger_path=workspace / str(current_certificate["partition_ledger"]),
    )
    route_rows = {
        str(row["day"]): row for row in subset if row["stream"] == stream
    }
    return prior_certificate, route_rows


def derive_perimeter_expansion_authority_snapshot(
    path: Path,
    *,
    expanded_sources: list[str],
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    dexes: list[str],
    days: list[str] | None = None,
    raw_lock: Path = RAW_MARKET_DATA_LOCK,
) -> dict[str, object]:
    """Derive the pre-expansion raw authority and prove it bound every marker.

    A certificate perimeter expansion adds non-route streams to a per-source
    local certificate for a different consumer family, changing the certificate
    container identity without touching any route payload. The prior authority
    is reconstructed deterministically from the current certified ledger's
    route-stream rows, and the snapshot is admitted only when the derived
    per-day fingerprints reproduce every released route marker's stored
    input fingerprint exactly. That reproduction is a hash-exact proof that
    the route-stream rows, consumer contract, and source registry are
    unchanged since the markers were written; a payload, contract, or registry
    change makes the derivation fail closed.
    """

    specs = parse_expanded_source_specs(expanded_sources)
    expanded = sorted(specs)
    if not expanded:
        raise ValueError("perimeter-expansion derivation requires expanded sources")
    if unknown := [source for source in expanded if source not in dexes]:
        raise ValueError(
            f"expanded sources outside the route perimeter: {', '.join(unknown)}"
        )
    with exclusive_job(
        raw_lock,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with serialized_output_installs((unified_root, quality_panel)):
            if path.exists() or path.is_symlink():
                raise FileExistsError(
                    f"route authority snapshot already exists: {path}"
                )
            selected = _selected_days(dexes, days)
            ledger, markers, marker_hashes = _load_release_perimeter(
                selected=selected,
                unified_root=unified_root,
                quality_panel=quality_panel,
                expected_engine=RECONSTRUCTION_ENGINE,
            )
            prior: dict[str, tuple[dict[str, object], dict[str, dict[str, object]]]] = {}
            with tempfile.TemporaryDirectory(
                prefix="ddvc-perimeter-expansion-derivation-"
            ) as directory:
                for source in expanded:
                    prior[source] = _reconstruct_prior_route_stream_certificate(
                        source,
                        data_root=data_root,
                        scratch=Path(directory),
                        prior_streams=specs[source],
                    )
            entries: list[dict[str, object]] = []
            rebound_days = 0
            for day in selected:
                old_records: list[dict[str, str]] = []
                current_records: list[dict[str, str]] = []
                for source in active_route_sources(_calendar_day(day), dexes):
                    stream = DEX_STREAM[source]
                    relocation = raw_partition_relocation_identity(
                        source, stream, day, data_root=data_root
                    )
                    scientific = relocation["scientific_identity"]
                    assert isinstance(scientific, dict)
                    current_generation = str(
                        relocation["generation_identity_sha256"]
                    )
                    if source in prior:
                        certificate, rows_by_day = prior[source]
                        row = rows_by_day.get(day)
                        if row is None:
                            raise ValueError(
                                "prior certificate does not cover route partition: "
                                f"{source}/{stream}/{day}"
                            )
                        generation = _derived_prior_generation_identity(
                            certificate,
                            row=row,
                            source_registry_generation=str(
                                scientific["source_registry_generation"]
                            ),
                        )
                    else:
                        generation = current_generation
                    old_records.append(
                        {
                            "source": source,
                            "stream": stream,
                            "day": day,
                            "generation_identity_sha256": generation,
                        }
                    )
                    current_records.append(
                        {
                            "source": source,
                            "stream": stream,
                            "day": day,
                            "generation_identity_sha256": current_generation,
                        }
                    )
                    entries.append(
                        {
                            "source": source,
                            "stream": stream,
                            "day": day,
                            "generation_identity_sha256": generation,
                            "scientific_identity": scientific,
                            "scientific_identity_sha256": canonical_json_sha256(
                                scientific
                            ),
                        }
                    )
                derived_fingerprint = canonical_json_sha256(old_records)
                if derived_fingerprint != markers[day].get("input_fingerprint"):
                    raise ValueError(
                        "derived prior authority does not reproduce the released "
                        f"route marker: {day}"
                    )
                rebound_days += int(
                    canonical_json_sha256(current_records) != derived_fingerprint
                )
            if rebound_days == 0:
                raise ValueError(
                    "perimeter-expansion derivation found no marker to rebind"
                )
            payload: dict[str, object] = {
                "policy": AUTHORITY_SNAPSHOT_POLICY,
                "route_engine": RECONSTRUCTION_ENGINE,
                "days": list(selected),
                "dexes": list(dexes),
                "entries": entries,
                "route_release": {
                    "quality_ledger_sha256": file_sha256(quality_panel),
                    "quality_ledger_rows": len(ledger),
                    "marker_sha256": marker_hashes,
                    "partitions": {
                        day: {
                            "rows": int(markers[day]["output_rows"]),
                            "bytes": int(markers[day]["output_bytes"]),
                            "sha256": str(markers[day]["output_sha256"]),
                        }
                        for day in selected
                    },
                },
                "derivation": {
                    "policy": PERIMETER_EXPANSION_DERIVATION_POLICY,
                    "expanded_sources": expanded,
                    "prior_stream_perimeters": {
                        source: sorted(specs[source]) for source in expanded
                    },
                    "prior_certificates": {
                        source: prior[source][0] for source in expanded
                    },
                    "rebound_days": rebound_days,
                },
            }
            payload["snapshot_sha256"] = _snapshot_digest(payload)
            with atomic_output(path) as temporary:
                temporary.write_text(
                    json.dumps(payload, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    if json.loads(path.read_text(encoding="utf-8")) != payload:
        raise RuntimeError("route authority snapshot did not reopen exactly")
    return payload


def _require_exact_ledger_rows(
    ledger: pd.DataFrame,
    marker_by_day: dict[str, dict[str, object]],
) -> None:
    if list(ledger.columns) != UNIFIED_QUALITY_COLUMNS:
        raise ValueError("legacy route quality ledger schema is not exact")
    if ledger["day"].map(_stamp).duplicated().any():
        raise ValueError("legacy route quality ledger contains duplicate days")
    for row in ledger.itertuples(index=False):
        day = _stamp(row.day)
        marker = marker_by_day[day]
        for column in UNIFIED_QUALITY_COLUMNS:
            if marker.get(column) != _json_value(getattr(row, column)):
                raise ValueError(
                    f"legacy route ledger disagrees with marker: {day}/{column}"
                )


def _validate_partition(
    day: str,
    *,
    unified_root: Path,
    expected_engine: str,
) -> tuple[dict[str, object], str]:
    output = unified_path(day, root=unified_root)
    marker_path = unified_quality_path(day, root=unified_root)
    if not output.is_file() or not marker_path.is_file():
        raise FileNotFoundError(f"route partition is incomplete: {day}")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"route marker is unreadable: {day}") from error
    if not isinstance(marker, dict):
        raise ValueError(f"route marker is not an object: {day}")
    if marker.get("engine") != expected_engine:
        raise ValueError(
            f"route marker engine differs from the admitted migration source: {day}"
        )
    if _stamp(marker.get("day")) != day or marker.get("passed") is not True:
        raise ValueError(f"route marker did not pass for its named day: {day}")
    before = file_stat_identity(output)
    digest = file_sha256(output)
    if before != file_stat_identity(output):
        raise RuntimeError(f"route partition mutated during hashing: {day}")
    output_rows = int(marker.get("output_rows", -1))
    output_stat = output.stat()
    if (
        output_rows < 0
        or int(marker.get("output_bytes", -1)) != output_stat.st_size
        or int(marker.get("output_mtime_ns", -1)) != output_stat.st_mtime_ns
        or marker.get("output_sha256") != digest
        or pq.ParquetFile(output).metadata.num_rows != output_rows
    ):
        raise ValueError(f"route partition disagrees with marker hash or rows: {day}")
    fingerprint = marker.get("input_fingerprint")
    if not is_sha256(fingerprint):
        raise ValueError(f"route marker lacks an input fingerprint: {day}")
    return marker, file_sha256(marker_path)


def _plan_day(
    day: str,
    *,
    data_root: Path,
    unified_root: Path,
    dexes: list[str],
) -> tuple[str, dict[str, object], str, str]:
    marker, marker_hash = _validate_partition(
        day, unified_root=unified_root, expected_engine=LEGACY_ENGINE
    )
    current_fingerprint = route_input_fingerprint(
        _calendar_day(day), dexes, data_root=data_root
    )
    output = unified_path(day, root=unified_root)
    stat = output.stat()
    migrated = dict(marker)
    migrated.update(
        {
            "engine": RECONSTRUCTION_ENGINE,
            "input_fingerprint": current_fingerprint,
            "output_bytes": stat.st_size,
            "output_mtime_ns": stat.st_mtime_ns,
            "output_sha256": marker["output_sha256"],
        }
    )
    return day, migrated, marker_hash, current_fingerprint


def _validate_fresh_day(
    day: str,
    *,
    dexes: list[str],
    data_root: Path,
    unified_root: Path,
    legacy_marker: dict[str, object],
    current_input_fingerprint: str,
    scratch: Path,
) -> dict[str, object]:
    fresh, quality = reconstruct_day_with_quality(
        _calendar_day(day), dexes, data_root=data_root
    )
    if quality.get("passed") is not True:
        raise ValueError(f"current raw reconstruction failed during migration: {day}")
    if quality.get("input_fingerprint") != current_input_fingerprint:
        raise RuntimeError(f"current route input changed during migration: {day}")
    old = pd.read_parquet(unified_path(day, root=unified_root))
    try:
        pd.testing.assert_frame_equal(
            old.reset_index(drop=True),
            fresh.reset_index(drop=True),
            check_dtype=True,
            check_exact=True,
            check_like=False,
        )
    except AssertionError as error:
        raise ValueError(
            f"legacy and current route semantics differ during migration: {day}"
        ) from error
    for field in UNIFIED_QUALITY_COLUMNS:
        if field in _MIGRATABLE_IDENTITY_FIELDS:
            continue
        if legacy_marker.get(field) != _json_value(quality.get(field)):
            raise ValueError(
                f"legacy and current route quality differ during migration: {day}/{field}"
            )
    first = scratch / f"{day}-a.parquet"
    second = scratch / f"{day}-b.parquet"
    try:
        fresh.to_parquet(first, index=False)
        fresh.to_parquet(second, index=False)
        first_hash = file_sha256(first)
        second_hash = file_sha256(second)
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
    if first_hash != second_hash:
        raise RuntimeError(f"fresh route serialization is not deterministic: {day}")
    return {
        "day": day,
        "active_venues": ",".join(
            active_route_sources(_calendar_day(day), dexes)
        ),
        "rows": len(fresh),
        "exact_frame_equal": True,
        "fresh_serialization_deterministic": True,
        "fresh_parquet_matches_legacy_bytes": first_hash
        == legacy_marker["output_sha256"],
    }


def _validate_fresh_day_job(
    job: tuple[
        str,
        list[str],
        Path,
        Path,
        dict[str, object],
        str,
        Path,
    ],
) -> dict[str, object]:
    day, dexes, data_root, unified_root, marker, fingerprint, scratch = job
    return _validate_fresh_day(
        day,
        dexes=dexes,
        data_root=data_root,
        unified_root=unified_root,
        legacy_marker=marker,
        current_input_fingerprint=fingerprint,
        scratch=scratch,
    )


def plan_migration(
    *,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    dexes: list[str],
    days: list[str] | None = None,
    workers: int = 4,
) -> MigrationPlan:
    """Validate the complete migration perimeter without changing live outputs."""

    if RECONSTRUCTION_ENGINE != MIGRATION_TARGET_ENGINE:
        raise RuntimeError(
            "route marker migration target is stale: "
            f"expected {MIGRATION_TARGET_ENGINE}, observed {RECONSTRUCTION_ENGINE}"
        )
    selected = _selected_days(dexes, days)
    ledger, legacy_markers, expected_marker_hashes = _load_release_perimeter(
        selected=selected,
        unified_root=unified_root,
        quality_panel=quality_panel,
        expected_engine=LEGACY_ENGINE,
    )
    markers: dict[str, dict[str, object]] = {}
    marker_hashes: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    worker_count = bounded_workers(workers, maximum=8)
    with interruptible_thread_pool(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _plan_day,
                day,
                data_root=data_root,
                unified_root=unified_root,
                dexes=dexes,
            ): day
            for day in selected
        }
        for future in as_completed(futures):
            day, migrated, marker_hash, current_fingerprint = future.result()
            markers[day] = migrated
            marker_hashes[day] = marker_hash
            fingerprints[day] = current_fingerprint
    if marker_hashes != expected_marker_hashes:
        raise RuntimeError("route markers changed while planning the migration")
    with tempfile.TemporaryDirectory(prefix="ddvc-route-marker-validation-") as directory:
        scratch = Path(directory)
        jobs = [
            (
                day,
                dexes,
                data_root,
                unified_root,
                legacy_markers[day],
                fingerprints[day],
                scratch,
            )
            for day in selected
        ]
        if worker_count == 1:
            validation_rows = [_validate_fresh_day_job(job) for job in jobs]
        else:
            with interruptible_process_pool(worker_count) as pool:
                validation_rows = list(pool.map(_validate_fresh_day_job, jobs))
    quality = pd.DataFrame(
        [markers[day] for day in selected], columns=UNIFIED_QUALITY_COLUMNS
    )
    return MigrationPlan(
        migration_policy=MIGRATION_POLICY,
        days=selected,
        quality=quality,
        markers=markers,
        legacy_marker_sha256=marker_hashes,
        current_input_fingerprints=fingerprints,
        validation=pd.DataFrame(validation_rows),
    )


def _load_authority_snapshot(
    path: Path,
    *,
    selected: tuple[str, ...],
    dexes: list[str],
) -> tuple[
    dict[tuple[str, str, str], dict[str, object]],
    dict[str, object],
    str,
]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("route authority snapshot is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("route authority snapshot must be an object")
    snapshot_sha256 = payload.get("snapshot_sha256")
    entries = payload.get("entries")
    route_release = payload.get("route_release")
    if (
        payload.get("policy") != AUTHORITY_SNAPSHOT_POLICY
        or payload.get("route_engine") != RECONSTRUCTION_ENGINE
        or payload.get("days") != list(selected)
        or payload.get("dexes") != dexes
        or not is_sha256(snapshot_sha256)
        or snapshot_sha256 != _snapshot_digest(payload)
        or not isinstance(entries, list)
        or not isinstance(route_release, dict)
    ):
        raise ValueError("route authority snapshot envelope mismatch")
    indexed: dict[tuple[str, str, str], dict[str, object]] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise ValueError("route authority snapshot entry is not an object")
        key = (
            str(raw_entry.get("source")),
            str(raw_entry.get("stream")),
            str(raw_entry.get("day")),
        )
        scientific = raw_entry.get("scientific_identity")
        generation = raw_entry.get("generation_identity_sha256")
        if (
            key in indexed
            or not is_sha256(generation)
            or not isinstance(scientific, dict)
            or raw_entry.get("scientific_identity_sha256")
            != canonical_json_sha256(scientific)
            or (
                str(scientific.get("source")),
                str(scientific.get("stream")),
                str(scientific.get("day")),
            )
            != key
        ):
            raise ValueError(f"route authority snapshot entry is invalid: {key}")
        indexed[key] = raw_entry
    expected = {
        (source, DEX_STREAM[source], day)
        for day in selected
        for source in active_route_sources(_calendar_day(day), dexes)
    }
    if set(indexed) != expected:
        raise ValueError("route authority snapshot partition perimeter is not exact")
    marker_hashes = route_release.get("marker_sha256")
    partitions = route_release.get("partitions")
    if (
        not is_sha256(route_release.get("quality_ledger_sha256"))
        or route_release.get("quality_ledger_rows") != len(selected)
        or not isinstance(marker_hashes, dict)
        or set(marker_hashes) != set(selected)
        or any(not is_sha256(marker_hashes[day]) for day in selected)
        or not isinstance(partitions, dict)
        or set(partitions) != set(selected)
    ):
        raise ValueError("route authority snapshot release identity is invalid")
    for day in selected:
        partition = partitions[day]
        if (
            not isinstance(partition, dict)
            or isinstance(partition.get("rows"), bool)
            or not isinstance(partition.get("rows"), int)
            or int(partition["rows"]) < 0
            or isinstance(partition.get("bytes"), bool)
            or not isinstance(partition.get("bytes"), int)
            or int(partition["bytes"]) < 0
            or not is_sha256(partition.get("sha256"))
        ):
            raise ValueError(
                f"route authority snapshot partition identity is invalid: {day}"
            )
    return indexed, route_release, str(snapshot_sha256)


def plan_storage_authority_relocation(
    *,
    authority_snapshot: Path,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    dexes: list[str],
    days: list[str] | None = None,
) -> MigrationPlan:
    """Rebind markers after a scientifically identical raw storage relocation."""

    if RECONSTRUCTION_ENGINE != MIGRATION_TARGET_ENGINE:
        raise RuntimeError(
            "route storage-authority relocation target is stale: "
            f"expected {MIGRATION_TARGET_ENGINE}, observed {RECONSTRUCTION_ENGINE}"
        )
    selected = _selected_days(dexes, days)
    ledger, old_markers, marker_hashes = _load_release_perimeter(
        selected=selected,
        unified_root=unified_root,
        quality_panel=quality_panel,
        expected_engine=RECONSTRUCTION_ENGINE,
    )
    old_authorities, old_release, snapshot_sha256 = _load_authority_snapshot(
        authority_snapshot, selected=selected, dexes=dexes
    )
    if (
        file_sha256(quality_panel) != old_release["quality_ledger_sha256"]
        or marker_hashes != old_release["marker_sha256"]
    ):
        raise ValueError(
            "route release marker or ledger changed after authority snapshot"
        )
    old_partitions = old_release["partitions"]
    assert isinstance(old_partitions, dict)
    for day in selected:
        marker = old_markers[day]
        if old_partitions[day] != {
            "rows": int(marker["output_rows"]),
            "bytes": int(marker["output_bytes"]),
            "sha256": str(marker["output_sha256"]),
        }:
            raise ValueError(
                f"route partition changed after authority snapshot: {day}"
            )
    markers: dict[str, dict[str, object]] = {}
    current_fingerprints: dict[str, str] = {}
    validation_rows: list[dict[str, object]] = []
    changed = 0
    for day in selected:
        old_generation_records: list[dict[str, str]] = []
        current_generation_records: list[dict[str, str]] = []
        for source in active_route_sources(_calendar_day(day), dexes):
            stream = DEX_STREAM[source]
            key = (source, stream, day)
            old_entry = old_authorities[key]
            old_generation_records.append(
                {
                    "source": source,
                    "stream": stream,
                    "day": day,
                    "generation_identity_sha256": str(
                        old_entry["generation_identity_sha256"]
                    ),
                }
            )
            current_relocation = raw_partition_relocation_identity(
                source, stream, day, data_root=data_root
            )
            current_scientific = current_relocation["scientific_identity"]
            if current_scientific != old_entry["scientific_identity"]:
                raise ValueError(
                    "raw scientific identity changed during storage relocation: "
                    f"{source}/{stream}/{day}"
                )
            current_generation = current_relocation.get(
                "generation_identity_sha256"
            )
            if not is_sha256(current_generation):
                raise ValueError(
                    f"current raw authority lacks generation identity: {source}/{stream}/{day}"
                )
            current_generation_records.append(
                {
                    "source": source,
                    "stream": stream,
                    "day": day,
                    "generation_identity_sha256": str(current_generation),
                }
            )
        old_fingerprint = canonical_json_sha256(old_generation_records)
        if old_fingerprint != old_markers[day].get("input_fingerprint"):
            raise ValueError(
                f"pre-relocation authority snapshot does not bind route marker: {day}"
            )
        current_fingerprint = canonical_json_sha256(current_generation_records)
        changed += int(current_fingerprint != old_fingerprint)
        migrated = dict(old_markers[day])
        migrated["input_fingerprint"] = current_fingerprint
        markers[day] = migrated
        current_fingerprints[day] = current_fingerprint
        validation_rows.append(
            {
                "day": day,
                "raw_partitions": len(current_generation_records),
                "scientific_identity_equal": True,
                "partition_bytes_rows_marker_ledger_equal": True,
                "input_fingerprint_changed": current_fingerprint
                != old_fingerprint,
            }
        )
    if changed == 0:
        raise ValueError("route storage-authority relocation would be a no-op")
    quality = pd.DataFrame(
        [markers[day] for day in selected], columns=UNIFIED_QUALITY_COLUMNS
    )
    return MigrationPlan(
        migration_policy=RELOCATION_POLICY,
        days=selected,
        quality=quality,
        markers=markers,
        legacy_marker_sha256=marker_hashes,
        current_input_fingerprints=current_fingerprints,
        validation=pd.DataFrame(validation_rows),
        authority_snapshot_sha256=snapshot_sha256,
    )


def _validate_relocation_dependencies(
    plan: MigrationPlan,
    *,
    authority_snapshot: Path,
    data_root: Path,
    unified_root: Path,
    dexes: list[str],
) -> None:
    """Recheck read-only raw and route dependencies inside publication."""

    old_authorities, _old_release, snapshot_sha256 = _load_authority_snapshot(
        authority_snapshot, selected=plan.days, dexes=dexes
    )
    if snapshot_sha256 != plan.authority_snapshot_sha256:
        raise RuntimeError("route authority snapshot changed before publication")
    for day in plan.days:
        output = unified_path(day, root=unified_root)
        before = file_stat_identity(output)
        digest = file_sha256(output)
        after = file_stat_identity(output)
        marker = plan.markers[day]
        if (
            before != after
            or before[2] != int(marker["output_bytes"])
            or before[3] != int(marker["output_mtime_ns"])
            or digest != marker["output_sha256"]
            or pq.ParquetFile(output).metadata.num_rows
            != int(marker["output_rows"])
        ):
            raise RuntimeError(
                f"route partition changed before migration commit: {day}"
            )
        generation_records: list[dict[str, str]] = []
        for source in active_route_sources(_calendar_day(day), dexes):
            stream = DEX_STREAM[source]
            relocation = raw_partition_relocation_identity(
                source, stream, day, data_root=data_root
            )
            if relocation["scientific_identity"] != old_authorities[
                (source, stream, day)
            ]["scientific_identity"]:
                raise RuntimeError(
                    "raw scientific identity changed before migration commit: "
                    f"{source}/{stream}/{day}"
                )
            generation_records.append(
                {
                    "source": source,
                    "stream": stream,
                    "day": day,
                    "generation_identity_sha256": str(
                        relocation["generation_identity_sha256"]
                    ),
                }
            )
        if canonical_json_sha256(generation_records) != plan.current_input_fingerprints[day]:
            raise RuntimeError(
                f"raw authority generation changed before migration commit: {day}"
            )


def _quality_summary(quality: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "calendar_days": len(quality),
            "expected_venue_days": int(quality["expected_sources"].sum()),
            "raw_rows": int(quality["raw_rows"].sum()),
            "normalised_rows": int(quality["normalised_rows"].sum()),
            "usable_rows": int(quality["usable_rows"].sum()),
            "output_rows": int(quality["output_rows"].sum()),
            "missing_sources": int(quality["missing_sources"].sum()),
            "duplicate_events": int(quality["duplicate_events"].sum()),
            "conflicting_events": int(quality["conflicting_events"].sum()),
            "malformed_rows": int(quality["malformed_rows"].sum()),
            "missing_identity": int(quality["missing_identity"].sum()),
            "missing_order": int(quality["missing_order"].sum()),
            "unpriced_rows": int(quality["unpriced_rows"].sum()),
            "failed_days": int((~quality["passed"].astype(bool)).sum()),
        }]
    )


def _publication_targets(
    *,
    unified_root: Path,
    quality_panel: Path,
    quality_exhibit: Path,
) -> dict[str, Path]:
    panel_sidecar = sidecar_path(quality_panel)
    exhibit_sidecar = sidecar_path(quality_exhibit)
    return {
        "markers": unified_root / ".quality",
        "panel": quality_panel,
        "panel_sidecar": panel_sidecar,
        "exhibit": quality_exhibit,
        "exhibit_sidecar": exhibit_sidecar,
    }


def _plan_from_committed_recovery(
    journal: dict[str, object],
    *,
    unified_root: Path,
    quality_panel: Path,
    expected_policy: str,
) -> MigrationPlan:
    """Reopen the exact plan recorded by a durably committed publication."""

    if journal.get("policy") != expected_policy:
        raise RuntimeError("committed route migration belongs to a foreign policy")
    days_raw = journal.get("days")
    legacy_hashes = journal.get("legacy_marker_sha256")
    fingerprints = journal.get("current_input_fingerprints")
    validation_raw = journal.get("validation")
    if (
        not isinstance(days_raw, list)
        or not all(isinstance(day, str) for day in days_raw)
        or not isinstance(legacy_hashes, dict)
        or not isinstance(fingerprints, dict)
        or not isinstance(validation_raw, list)
    ):
        raise RuntimeError("committed route migration journal lacks its exact plan")
    days = tuple(days_raw)
    if (
        len(days) != len(set(days))
        or tuple(sorted(days)) != days
        or set(legacy_hashes) != set(days)
        or set(fingerprints) != set(days)
    ):
        raise RuntimeError("committed route migration journal plan is inconsistent")
    quality = pd.read_parquet(quality_panel)
    quality["day"] = quality["day"].map(_stamp)
    if tuple(quality["day"].tolist()) != days:
        raise RuntimeError("committed route migration ledger perimeter changed")
    markers = {
        day: json.loads(
            unified_quality_path(day, root=unified_root).read_text(encoding="utf-8")
        )
        for day in days
    }
    if any(marker.get("engine") != RECONSTRUCTION_ENGINE for marker in markers.values()):
        raise RuntimeError("committed route migration markers are not current")
    return MigrationPlan(
        migration_policy=expected_policy,
        days=days,
        quality=quality,
        markers=markers,
        legacy_marker_sha256={day: str(legacy_hashes[day]) for day in days},
        current_input_fingerprints={day: str(fingerprints[day]) for day in days},
        validation=pd.DataFrame(validation_raw),
        authority_snapshot_sha256=(
            str(journal["authority_snapshot_sha256"])
            if journal.get("authority_snapshot_sha256") is not None
            else None
        ),
    )


def publish_migration(
    plan: MigrationPlan,
    *,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    quality_exhibit: Path,
    authority_snapshot: Path | None = None,
    dexes: list[str] | None = None,
) -> None:
    """Stage and publish all five route-release outputs as one journaled bundle."""

    targets = _publication_targets(
        unified_root=unified_root,
        quality_panel=quality_panel,
        quality_exhibit=quality_exhibit,
    )
    journal_root = unified_root.parent / JOURNAL_ROOT_NAME
    with tempfile.TemporaryDirectory(
        dir=unified_root.parent, prefix=".route-marker-stage-"
    ) as directory:
        stage = Path(directory)
        staged_markers = stage / "markers"
        staged_markers.mkdir()
        planned_marker_hashes: dict[str, str] = {}
        for day in plan.days:
            path = staged_markers / f"{day}.json"
            path.write_text(
                json.dumps(plan.markers[day], indent=1, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            reopened = json.loads(path.read_text(encoding="utf-8"))
            if reopened != plan.markers[day]:
                raise RuntimeError(f"staged route marker did not reopen exactly: {day}")
            planned_marker_hashes[day] = file_sha256(path)
        if set(planned_marker_hashes) != set(plan.days):
            raise RuntimeError("staged route marker perimeter is incomplete")
        raw_roots = [
            data_root / "raw" / ("dune" if dex in DUNE_SOURCES else "thegraph") / dex
            for dex in sorted(DEX_FAMILY)
        ]
        validation_kind = (
            "exact_fresh_validation_days"
            if plan.migration_policy == MIGRATION_POLICY
            else "exact_authority_relocation_days"
        )
        notes = (
            f"{plan.migration_policy}; current_engine={RECONSTRUCTION_ENGINE}; "
            f"source_marker_set_sha256={plan.legacy_marker_set_sha256}; "
            f"{validation_kind}={len(plan.validation)}"
        )
        staged_panel = stage / "panel.parquet"
        plan.quality.to_parquet(staged_panel, index=False)
        marker_input = describe_input(staged_markers)
        marker_input["path"] = describe_input(targets["markers"])["path"]
        panel_stamp = json.loads(
            prepare_stamp(
                quality_panel,
                content_path=staged_panel,
                code_sources=[
                    *RECONSTRUCT_CODE_SOURCES,
                    "scripts/migrate_route_release_markers.py",
                ],
                inputs=[
                    *raw_roots,
                    *([authority_snapshot] if authority_snapshot is not None else []),
                ],
                rows=len(plan.quality),
                notes=notes,
            )
        )
        panel_stamp["inputs"] = [
            marker_input,
            *panel_stamp["inputs"],
        ]
        staged_panel_sidecar = stage / "panel.prov.json"
        staged_panel_sidecar.write_text(
            json.dumps(panel_stamp, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staged_exhibit = stage / "exhibit.jsonl"
        summary = _stringify_big_ints(_quality_summary(plan.quality))
        with staged_exhibit.open("w", encoding="utf-8") as handle:
            for record in summary.to_dict("records"):
                handle.write(json.dumps(record, allow_nan=False, default=str, sort_keys=True) + "\n")
        panel_input = describe_input(staged_panel)
        panel_input["path"] = describe_input(quality_panel)["path"]
        exhibit_stamp = json.loads(
            prepare_stamp(
                quality_exhibit,
                content_path=staged_exhibit,
                code_sources=[
                    *RECONSTRUCT_CODE_SOURCES,
                    "scripts/migrate_route_release_markers.py",
                ],
                inputs=[],
                rows=len(summary),
                notes=notes,
            )
        )
        exhibit_stamp["inputs"] = [panel_input]
        staged_exhibit_sidecar = stage / "exhibit.prov.json"
        staged_exhibit_sidecar.write_text(
            json.dumps(exhibit_stamp, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metadata = {
            "policy": plan.migration_policy,
            "legacy_engine": (
                LEGACY_ENGINE if plan.migration_policy == MIGRATION_POLICY else None
            ),
            "current_engine": RECONSTRUCTION_ENGINE,
            "days": list(plan.days),
            "legacy_marker_sha256": plan.legacy_marker_sha256,
            "current_input_fingerprints": plan.current_input_fingerprints,
            "validation": plan.validation.to_dict("records"),
            "authority_snapshot_sha256": plan.authority_snapshot_sha256,
        }
        def validate_live() -> None:
            observed = pd.read_parquet(quality_panel)
            pd.testing.assert_frame_equal(
                observed.reset_index(drop=True),
                plan.quality.reset_index(drop=True),
                check_dtype=True,
                check_exact=True,
            )
            with current_artifacts(
                [quality_panel, quality_exhibit],
                consumer="route marker migration publication",
            ):
                pass
            for day, expected_hash in planned_marker_hashes.items():
                if file_sha256(unified_quality_path(day, root=unified_root)) != expected_hash:
                    raise RuntimeError(f"published route marker changed: {day}")

        if plan.migration_policy == RELOCATION_POLICY:
            if authority_snapshot is None or dexes is None:
                raise ValueError(
                    "storage-authority publication requires its snapshot and source perimeter"
                )
            replanned = plan_storage_authority_relocation(
                authority_snapshot=authority_snapshot,
                data_root=data_root,
                unified_root=unified_root,
                quality_panel=quality_panel,
                dexes=dexes,
                days=list(plan.days),
            )
            pd.testing.assert_frame_equal(
                replanned.quality,
                plan.quality,
                check_dtype=True,
                check_exact=True,
            )
            if (
                replanned.markers != plan.markers
                or replanned.legacy_marker_sha256 != plan.legacy_marker_sha256
                or replanned.current_input_fingerprints
                != plan.current_input_fingerprints
                or replanned.authority_snapshot_sha256
                != plan.authority_snapshot_sha256
            ):
                raise RuntimeError(
                    "route storage-authority relocation changed before publication"
                )
            validate_preconditions = lambda: _validate_relocation_dependencies(
                plan,
                authority_snapshot=authority_snapshot,
                data_root=data_root,
                unified_root=unified_root,
                dexes=dexes,
            )
        else:
            validate_preconditions = None

        publish_journaled_bundle(
            targets=targets,
            staged={
                "markers": staged_markers,
                "panel": staged_panel,
                "panel_sidecar": staged_panel_sidecar,
                "exhibit": staged_exhibit,
                "exhibit_sidecar": staged_exhibit_sidecar,
            },
            journal_root=journal_root,
            metadata=metadata,
            validate_preconditions=validate_preconditions,
            validate_live=validate_live,
        )


_INPUT_IDENTITY_KEYS = (
    "exists",
    "kind",
    "bytes",
    "sha256",
    "mtime_ns",
    "entries",
    "tree_fingerprint",
)
DOWNSTREAM_REBIND_POLICY = "route-release-downstream-binding-rebind-v1"
DOWNSTREAM_REBIND_PANELS = (
    DATA_DIR / "processed" / "cross_venue_routing_daily.parquet",
    DATA_DIR / "processed" / "intermediation_by_type_daily.parquet",
    DATA_DIR / "processed" / "vehicle_excess_use_daily.parquet",
)
DOWNSTREAM_REBIND_EXHIBITS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl",
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_support.jsonl",
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.parquet",
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_contributions.parquet",
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl",
)


def current_route_release_bindings() -> tuple[dict[str, str], frozenset[str]]:
    """Exact current released route identities and the marker-owned subset.

    The bindings are the same ledger, partition, and marker identities a
    builder pins at publication; the migratable subset is exactly what this
    owner is allowed to have changed: the quality ledger and per-day markers.
    Partition identities are never migratable.
    """

    release = released_route_partitions((UNIFIED_COLUMNS[0],))

    def record_path(path: Path) -> str:
        resolved = Path(path).resolve()
        try:
            return str(resolved.relative_to(REPO_ROOT))
        except ValueError:
            return str(resolved)

    ledger = record_path(release.ledger_path)
    bindings = {ledger: release.ledger_sha256}
    migratable = {ledger}
    for partition in release.partitions:
        bindings[record_path(partition.path)] = partition.expected_sha256
        marker = record_path(partition.marker_path)
        bindings[marker] = partition.marker_sha256
        migratable.add(marker)
    return bindings, frozenset(migratable)


def rebind_released_input_bindings(
    payload: Path,
    *,
    current_bindings: Mapping[str, str],
    migratable_paths: frozenset[str],
    rebind_note: str,
    sidecar: Path | None = None,
    root: Path = REPO_ROOT,
    require_current_code: bool = True,
) -> bool:
    """Rebind proven-equivalent release identities on one byte-unchanged consumer.

    Refuses unless the payload bytes, its code fingerprint, and every binding
    outside the migrated marker/ledger family are exactly current. Never
    rebuilds or touches the payload; only the sidecar's stale identities move,
    and only to identities the current certified release itself asserts.
    Members of a frozen typed release pass ``require_current_code=False``:
    their consumption contract is the installed generation plus its semantic
    receipt, not a live code fingerprint.
    """

    payload = Path(payload)
    side = Path(sidecar) if sidecar is not None else sidecar_path(payload)
    with serialized_output_installs((payload, side)):
        if not payload.is_file():
            raise RuntimeError(f"downstream rebind target is missing: {payload}")
        if not side.is_file():
            raise RuntimeError(f"downstream rebind target is unstamped: {payload}")
        record = json.loads(side.read_text(encoding="utf-8"))
        recorded_digest = record.get("artefact_sha256")
        if not is_sha256(recorded_digest):
            raise RuntimeError(
                f"downstream rebind target lacks an exact identity: {payload}"
            )
        observed_digest = file_sha256(payload)
        identity = record.get("payload_identity")
        identity_digest = identity.get("sha256") if isinstance(identity, dict) else None
        if observed_digest != recorded_digest or (
            identity_digest is not None and identity_digest != observed_digest
        ):
            raise RuntimeError(f"downstream payload changed; rebind refused: {payload}")
        sources = record.get("code_sources") or []
        if require_current_code and code_fingerprint(
            [str(source) for source in sources]
        ) != record.get("code_fingerprint"):
            raise RuntimeError(
                f"downstream code is not current; rebind refused: {payload}"
            )
        raw_bindings = record.get("released_input_bindings") or []
        old: dict[str, str] = {}
        for item in raw_bindings:
            if not isinstance(item, dict) or not is_sha256(item.get("sha256")):
                raise RuntimeError(f"downstream release binding is invalid: {payload}")
            path_key = str(item.get("path"))
            if path_key in old:
                raise RuntimeError(
                    f"downstream release bindings repeat a path: {payload}"
                )
            old[path_key] = str(item["sha256"])
        changed: list[str] = []
        foreign: list[str] = []
        for path_key, digest in old.items():
            expected = current_bindings.get(path_key)
            if expected is not None:
                if digest != expected:
                    target = changed if path_key in migratable_paths else foreign
                    target.append(path_key)
                continue
            source = Path(path_key)
            source = source if source.is_absolute() else root / source
            if not source.is_file() or file_sha256(source) != digest:
                foreign.append(path_key)
        if foreign:
            raise RuntimeError(
                "downstream rebind found identity changes outside the migrated "
                f"marker/ledger family; rebind refused: {sorted(foreign)[:3]}"
            )
        rebound_inputs = False
        for item in record.get("inputs") or []:
            if not isinstance(item, dict):
                raise RuntimeError(
                    f"downstream provenance input is invalid: {payload}"
                )
            path_key = str(item.get("path"))
            source = Path(path_key)
            source = source if source.is_absolute() else root / source
            expected = (
                current_bindings.get(path_key) if "sha256" in item else None
            )
            if expected is None:
                observed = describe_input(source)
                if any(
                    observed.get(key) != item.get(key)
                    for key in _INPUT_IDENTITY_KEYS
                    if key in item
                ):
                    raise RuntimeError(
                        "downstream input changed outside the migrated "
                        f"release; rebind refused: {path_key}"
                    )
                continue
            if item.get("sha256") == expected:
                continue
            if path_key not in migratable_paths:
                raise RuntimeError(
                    "downstream input changed outside the migrated "
                    f"marker/ledger family; rebind refused: {path_key}"
                )
            refreshed = describe_input(source)
            if refreshed.get("sha256") != expected:
                raise RuntimeError(
                    "downstream input does not match the current release "
                    f"identity: {path_key}"
                )
            for key in list(item):
                if key == "path":
                    continue
                if key not in refreshed:
                    raise RuntimeError(
                        f"downstream input field cannot be refreshed: {key}: {path_key}"
                    )
                if item[key] != refreshed[key]:
                    item[key] = refreshed[key]
                    rebound_inputs = True
        if not changed and not rebound_inputs:
            return False
        record["released_input_bindings"] = [
            {
                "path": item["path"],
                "sha256": current_bindings.get(str(item["path"]), item["sha256"]),
            }
            for item in raw_bindings
        ]
        notes = str(record.get("notes") or "")
        if rebind_note not in notes:
            record["notes"] = f"{notes}; {rebind_note}" if notes else rebind_note
        with atomic_output(side) as temporary:
            temporary.write_text(
                json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
        return True


def rebind_endpoint_composition_release(
    *,
    current_bindings: Mapping[str, str],
    migratable_paths: frozenset[str],
    rebind_note: str,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    sidecar_for: Callable[[Path], Path] = sidecar_path,
    root: Path = REPO_ROOT,
) -> bool:
    """Rebind the endpoint release's member sidecars and republish its pointer.

    The generation and its semantic receipt are identity functions of the
    member payload bytes and the frozen build identity, so a pure sidecar
    rebind must reproduce the installed generation exactly; anything else is a
    refusal. Member payloads are never rewritten.
    """

    pointer_path = Path(pointer_path)
    with serialized_output_installs((pointer_path,)):
        if not pointer_path.is_file():
            raise RuntimeError(f"endpoint release pointer is missing: {pointer_path}")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        generation = str(pointer.get("generation_id") or "")
        build_identity = str(pointer.get("build_identity_sha256") or "")
        artifacts = pointer.get("artifacts")
        if (
            not is_sha256(generation)
            or not is_sha256(build_identity)
            or not isinstance(artifacts, dict)
        ):
            raise RuntimeError(f"endpoint release pointer is invalid: {pointer_path}")
        generation_dir = pointer_path.parent / "generations" / generation
        artifact_hashes: dict[str, str] = {}
        for name, info in sorted(artifacts.items()):
            target = generation_dir / str(info["filename"])
            observed = file_sha256(target)
            if observed != info.get("sha256"):
                raise RuntimeError(
                    f"endpoint member payload changed; rebind refused: {target}"
                )
            artifact_hashes[str(name)] = observed
        if generation_id(artifact_hashes, build_identity) != generation:
            raise RuntimeError(
                "endpoint generation identity does not reproduce; rebind refused"
            )
        changed = False
        for name, info in sorted(artifacts.items()):
            target = generation_dir / str(info["filename"])
            member_sidecar = sidecar_for(target)
            if rebind_released_input_bindings(
                target,
                current_bindings=current_bindings,
                migratable_paths=migratable_paths,
                rebind_note=rebind_note,
                sidecar=member_sidecar,
                root=root,
                require_current_code=False,
            ):
                changed = True
            observed_provenance = file_sha256(member_sidecar)
            if observed_provenance != info.get("provenance_sha256"):
                artifacts[name] = {**info, "provenance_sha256": observed_provenance}
                changed = True
        if changed:
            write_json(pointer_path, pointer)
        return changed


def restamp_migration_owned_artifact(
    artefact: Path,
    *,
    restamp_note: str,
    sidecar: Path | None = None,
    root: Path = REPO_ROOT,
) -> bool:
    """Refresh the code fingerprint on one byte-unchanged output of this owner.

    Amending this script changes the stamped code fingerprint of the quality
    ledger and exhibit it publishes, without touching their payloads or
    inputs. The restamp is refused unless the payload bytes and every input
    identity are exactly current, so only the fingerprint moves.
    """

    payload = Path(artefact)
    side = Path(sidecar) if sidecar is not None else sidecar_path(payload)
    with serialized_output_installs((payload, side)):
        if not payload.is_file() or not side.is_file():
            raise RuntimeError(f"restamp target is missing or unstamped: {payload}")
        record = json.loads(side.read_text(encoding="utf-8"))
        recorded_digest = record.get("artefact_sha256")
        if not is_sha256(recorded_digest) or file_sha256(payload) != recorded_digest:
            raise RuntimeError(f"payload changed; restamp refused: {payload}")
        for item in record.get("inputs") or []:
            if not isinstance(item, dict):
                raise RuntimeError(f"restamp target input is invalid: {payload}")
            source = Path(str(item.get("path")))
            source = source if source.is_absolute() else root / source
            observed = describe_input(source)
            if any(
                observed.get(key) != item.get(key)
                for key in _INPUT_IDENTITY_KEYS
                if key in item
            ):
                raise RuntimeError(
                    f"inputs changed; restamp refused: {payload}: {item.get('path')}"
                )
        sources = [str(source) for source in record.get("code_sources") or []]
        current = code_fingerprint(sources)
        if record.get("code_fingerprint") == current:
            return False
        record["code_fingerprint"] = current
        notes = str(record.get("notes") or "")
        if restamp_note not in notes:
            record["notes"] = f"{notes}; {restamp_note}" if notes else restamp_note
        with atomic_output(side) as temporary:
            temporary.write_text(
                json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
        return True


def rebind_downstream_route_consumers(
    *,
    panels: tuple[Path, ...] = DOWNSTREAM_REBIND_PANELS,
    endpoint_pointer: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
) -> dict[str, bool]:
    """Rebind every gate-blocking consumer of the migrated route identities."""

    restamp_note = (
        f"{DOWNSTREAM_REBIND_POLICY}: exact-payload code-fingerprint restamp "
        "after amending the migration owner with the downstream rebind"
    )
    outcomes: dict[str, bool] = {}
    for owned in (UNIFIED_QUALITY_PANEL, UNIFIED_QUALITY_EXHIBIT):
        outcomes[str(Path(owned).relative_to(REPO_ROOT))] = (
            restamp_migration_owned_artifact(owned, restamp_note=restamp_note)
        )
        verdict = verify(owned)
        if verdict.get("status") != "ok":
            raise RuntimeError(
                f"owned-artifact restamp did not restore currency: {owned}: "
                f"{verdict.get('status')}"
            )
    bindings, migratable = current_route_release_bindings()
    note = (
        f"{DOWNSTREAM_REBIND_POLICY}: released-input bindings rebound to the "
        "current certified route release after the V2 certificate perimeter "
        "expansion; payload bytes and every route partition identity unchanged"
    )
    for panel in panels:
        outcomes[str(panel.relative_to(REPO_ROOT))] = rebind_released_input_bindings(
            panel,
            current_bindings=bindings,
            migratable_paths=migratable,
            rebind_note=note,
        )
        verdict = verify(panel)
        if verdict.get("status") != "ok":
            raise RuntimeError(
                f"downstream rebind did not restore currency: {panel}: "
                f"{verdict.get('status')}"
            )
    pointer_key = str(Path(endpoint_pointer).relative_to(REPO_ROOT))
    outcomes[pointer_key] = rebind_endpoint_composition_release(
        current_bindings=bindings,
        migratable_paths=migratable,
        rebind_note=note,
        pointer_path=endpoint_pointer,
    )
    with current_endpoint_candidate_composition_release(endpoint_pointer):
        pass

    # Second ring: exhibits that bound the endpoint release representation
    # itself. Their payloads and code are unchanged; only the pointer bytes
    # and member sidecars this same unit proved and rebound may differ.
    def record_path(path: Path) -> str:
        resolved = Path(path).resolve()
        try:
            return str(resolved.relative_to(REPO_ROOT))
        except ValueError:
            return str(resolved)

    pointer_path = Path(endpoint_pointer)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    generation_dir = pointer_path.parent / "generations" / str(pointer["generation_id"])
    release_bindings = dict(bindings)
    release_migratable = set(migratable)
    release_bindings[record_path(pointer_path)] = file_sha256(pointer_path)
    release_migratable.add(record_path(pointer_path))
    for info in pointer["artifacts"].values():
        target = generation_dir / str(info["filename"])
        member_sidecar = sidecar_path(target)
        release_bindings[record_path(target)] = str(info["sha256"])
        release_bindings[record_path(member_sidecar)] = str(info["provenance_sha256"])
        release_migratable.add(record_path(member_sidecar))
    for exhibit in DOWNSTREAM_REBIND_EXHIBITS:
        outcomes[record_path(exhibit)] = rebind_released_input_bindings(
            exhibit,
            current_bindings=release_bindings,
            migratable_paths=frozenset(release_migratable),
            rebind_note=note,
        )
        verdict = verify(exhibit)
        if verdict.get("status") != "ok":
            raise RuntimeError(
                f"downstream rebind did not restore currency: {exhibit}: "
                f"{verdict.get('status')}"
            )
    return outcomes


def migrate_route_release_markers(
    *,
    data_root: Path = DATA_DIR,
    unified_root: Path | None = None,
    quality_panel: Path = UNIFIED_QUALITY_PANEL,
    quality_exhibit: Path = UNIFIED_QUALITY_EXHIBIT,
    dexes: list[str] | None = None,
    days: list[str] | None = None,
    workers: int = 4,
    publish: bool = False,
    raw_lock: Path = RAW_MARKET_DATA_LOCK,
    authority_snapshot: Path | None = None,
) -> MigrationPlan:
    """Plan and optionally publish one admitted route marker migration."""

    dexes = dexes or list(DEX_FAMILY)
    migration_policy = (
        RELOCATION_POLICY if authority_snapshot is not None else MIGRATION_POLICY
    )
    unified_root = unified_root or data_root / "unified"
    with exclusive_job(
        raw_lock,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with serialized_output_installs((unified_root, quality_panel, quality_exhibit)):
            targets = _publication_targets(
                unified_root=unified_root,
                quality_panel=quality_panel,
                quality_exhibit=quality_exhibit,
            )
            recovery = recover_journaled_publications(
                targets,
                journal_root=unified_root.parent / JOURNAL_ROOT_NAME,
            )
            if len(recovery.committed_metadata) > 1:
                raise RuntimeError("multiple committed route migration stages exist")
            if recovery.committed_metadata:
                return _plan_from_committed_recovery(
                    recovery.committed_metadata[0],
                    unified_root=unified_root,
                    quality_panel=quality_panel,
                    expected_policy=migration_policy,
                )
            if authority_snapshot is None:
                plan = plan_migration(
                    data_root=data_root,
                    unified_root=unified_root,
                    quality_panel=quality_panel,
                    dexes=dexes,
                    days=days,
                    workers=workers,
                )
            else:
                plan = plan_storage_authority_relocation(
                    authority_snapshot=authority_snapshot,
                    data_root=data_root,
                    unified_root=unified_root,
                    quality_panel=quality_panel,
                    dexes=dexes,
                    days=days,
                )
            if publish:
                publish_migration(
                    plan,
                    data_root=data_root,
                    unified_root=unified_root,
                    quality_panel=quality_panel,
                    quality_exhibit=quality_exhibit,
                    authority_snapshot=authority_snapshot,
                    dexes=dexes,
                )
            return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="publish markers and the ledger after the complete dry-run gate passes",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--authority-snapshot",
        type=Path,
        help="pre-relocation authority snapshot; selects relocation-only mode",
    )
    parser.add_argument(
        "--write-authority-snapshot",
        type=Path,
        help="capture authority evidence before relocation, then exit",
    )
    parser.add_argument(
        "--write-perimeter-expansion-snapshot",
        type=Path,
        help=(
            "derive the pre-expansion authority from the current certified "
            "ledgers' route-stream rows, prove it binds every released marker, "
            "write it as a relocation snapshot, then exit"
        ),
    )
    parser.add_argument(
        "--expanded-source",
        action="append",
        default=None,
        help=(
            "source whose local certificate gained non-route streams "
            "(repeatable); a bare source names a route-stream-only prior "
            "certificate, while source=streamA,streamB names the exact prior "
            "stream perimeter when the pre-expansion certificate already "
            "covered other unchanged streams"
        ),
    )
    parser.add_argument(
        "--rebind-downstream-consumers",
        action="store_true",
        help=(
            "rebind byte-unchanged downstream consumers of the released route "
            "identities (three processed route panels plus the endpoint "
            "composition release) after a proven marker migration, then exit"
        ),
    )
    args = parser.parse_args()
    if args.rebind_downstream_consumers:
        if (
            args.publish
            or args.authority_snapshot is not None
            or args.write_authority_snapshot is not None
            or args.write_perimeter_expansion_snapshot is not None
            or args.expanded_source
        ):
            parser.error(
                "--rebind-downstream-consumers cannot be combined with "
                "migration options"
            )
        outcomes = rebind_downstream_route_consumers()
        for target, rebound in sorted(outcomes.items()):
            print(f"{'rebound' if rebound else 'already current'}: {target}", flush=True)
        print(
            "downstream rebind complete: "
            f"{sum(outcomes.values())}/{len(outcomes)} targets rebound",
            flush=True,
        )
        return 0
    if args.write_perimeter_expansion_snapshot is not None:
        if (
            args.publish
            or args.authority_snapshot is not None
            or args.write_authority_snapshot is not None
        ):
            parser.error(
                "--write-perimeter-expansion-snapshot cannot be combined with "
                "migration options"
            )
        if not args.expanded_source:
            parser.error(
                "--write-perimeter-expansion-snapshot requires --expanded-source"
            )
        snapshot = derive_perimeter_expansion_authority_snapshot(
            args.write_perimeter_expansion_snapshot,
            expanded_sources=args.expanded_source,
            data_root=DATA_DIR,
            unified_root=DATA_DIR / "unified",
            quality_panel=UNIFIED_QUALITY_PANEL,
            dexes=list(DEX_FAMILY),
        )
        derivation = snapshot["derivation"]
        assert isinstance(derivation, dict)
        print(
            "perimeter-expansion authority snapshot written: "
            f"{len(snapshot['entries']):,} raw partitions; "
            f"{int(derivation['rebound_days']):,} markers to rebind",
            flush=True,
        )
        return 0
    if args.expanded_source:
        parser.error(
            "--expanded-source requires --write-perimeter-expansion-snapshot"
        )
    if args.write_authority_snapshot is not None:
        if args.publish or args.authority_snapshot is not None:
            parser.error(
                "--write-authority-snapshot cannot be combined with migration options"
            )
        snapshot = write_route_authority_snapshot(
            args.write_authority_snapshot,
            data_root=DATA_DIR,
            unified_root=DATA_DIR / "unified",
            quality_panel=UNIFIED_QUALITY_PANEL,
            dexes=list(DEX_FAMILY),
        )
        print(
            "route authority snapshot written: "
            f"{len(snapshot['entries']):,} raw partitions",
            flush=True,
        )
        return 0
    plan = migrate_route_release_markers(
        publish=args.publish,
        workers=args.workers,
        authority_snapshot=args.authority_snapshot,
    )
    if plan.migration_policy == MIGRATION_POLICY:
        detail = (
            f"{len(plan.validation):,} exact fresh validation days; "
            f"{int(plan.validation['fresh_parquet_matches_legacy_bytes'].sum()):,} "
            "byte-identical fresh Parquets"
        )
    else:
        detail = (
            f"{len(plan.validation):,} exact authority-equivalent days; "
            f"{int(plan.validation['input_fingerprint_changed'].sum()):,} "
            "fingerprints changed"
        )
    print(
        f"route marker migration gate passed: {len(plan.days):,} days; "
        f"{detail}; "
        f"published={args.publish}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
