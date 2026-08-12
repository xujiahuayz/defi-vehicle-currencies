#!/usr/bin/env python3
"""Migrate one proven-equivalent route release to the current marker engine.

This is a marker migration, not a route rebuild. It accepts only the named
legacy and current engines, validates every legacy Parquet against its marker
and ledger, resolves every current raw input through its installed authority,
and requires exact fresh reconstruction on every released day.
No live marker changes until the complete plan passes. Publication swaps the
marker directory and writes the global quality ledger last; any ordinary
publication failure restores the legacy release.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ddvc.artifact_release import canonical_json_sha256, file_sha256, file_stat_identity, is_sha256
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.provenance import sidecar_path
from ddvc.reconstruct import (
    DEX_FAMILY,
    DUNE_SOURCES,
    RECONSTRUCT_CODE_SOURCES,
    RECONSTRUCTION_ENGINE,
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
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
    interruptible_thread_pool,
    serialized_output_installs,
)
from ddvc.tables import write_exhibit, write_panel


LEGACY_ENGINE = "514160b28189"
MIGRATION_TARGET_ENGINE = "d3f16e9c4da6"
MIGRATION_POLICY = "route-release-marker-migration-v1"
_STAGE_PREFIX = ".route-marker-migration-"
_JOURNAL_NAME = "publication-journal.json"
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
    days: tuple[str, ...]
    quality: pd.DataFrame
    markers: dict[str, dict[str, object]]
    legacy_marker_sha256: dict[str, str]
    current_input_fingerprints: dict[str, str]
    validation: pd.DataFrame

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


def _validate_legacy_partition(
    day: str,
    *,
    unified_root: Path,
) -> tuple[dict[str, object], str]:
    output = unified_path(day, root=unified_root)
    marker_path = unified_quality_path(day, root=unified_root)
    if not output.is_file() or not marker_path.is_file():
        raise FileNotFoundError(f"legacy route partition is incomplete: {day}")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"legacy route marker is unreadable: {day}") from error
    if not isinstance(marker, dict):
        raise ValueError(f"legacy route marker is not an object: {day}")
    if marker.get("engine") != LEGACY_ENGINE:
        raise ValueError(f"route marker is not from the admitted legacy engine: {day}")
    if _stamp(marker.get("day")) != day or marker.get("passed") is not True:
        raise ValueError(f"legacy route marker did not pass for its named day: {day}")
    before = file_stat_identity(output)
    digest = file_sha256(output)
    if before != file_stat_identity(output):
        raise RuntimeError(f"legacy route partition mutated during hashing: {day}")
    output_rows = int(marker.get("output_rows", -1))
    if (
        output_rows < 0
        or int(marker.get("output_bytes", -1)) != output.stat().st_size
        or marker.get("output_sha256") != digest
        or pq.ParquetFile(output).metadata.num_rows != output_rows
    ):
        raise ValueError(f"legacy route partition disagrees with marker hash or rows: {day}")
    fingerprint = marker.get("input_fingerprint")
    if not is_sha256(fingerprint):
        raise ValueError(f"legacy route marker lacks an input fingerprint: {day}")
    return marker, file_sha256(marker_path)


def _plan_day(
    day: str,
    *,
    data_root: Path,
    unified_root: Path,
    dexes: list[str],
) -> tuple[str, dict[str, object], str, str]:
    marker, marker_hash = _validate_legacy_partition(day, unified_root=unified_root)
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
    fresh.to_parquet(first, index=False)
    fresh.to_parquet(second, index=False)
    first_hash = file_sha256(first)
    second_hash = file_sha256(second)
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
    selected = tuple(
        _stamp(day)
        for day in (
            days
            if days is not None
            else _available_days(dexes)
        )
    )
    if len(selected) != len(set(selected)) or tuple(sorted(selected)) != selected:
        raise ValueError("route marker migration days must be unique and sorted")
    if not quality_panel.is_file():
        raise FileNotFoundError("legacy route quality ledger is missing")
    ledger = pd.read_parquet(quality_panel)
    ledger["day"] = ledger["day"].map(_stamp)
    if tuple(ledger["day"].tolist()) != selected:
        raise ValueError("legacy route quality ledger perimeter is not exact")
    observed_markers = {
        path.stem for path in (unified_root / ".quality").glob("*.json")
    }
    if observed_markers != set(selected):
        raise ValueError("legacy route marker directory perimeter is not exact")
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
    _require_exact_ledger_rows(ledger, {
        day: json.loads(
            unified_quality_path(day, root=unified_root).read_text(encoding="utf-8")
        )
        for day in selected
    })
    with tempfile.TemporaryDirectory(prefix="ddvc-route-marker-validation-") as directory:
        scratch = Path(directory)
        jobs = [
            (
                day,
                dexes,
                data_root,
                unified_root,
                markers[day] | {"engine": LEGACY_ENGINE},
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
        days=selected,
        quality=quality,
        markers=markers,
        legacy_marker_sha256=marker_hashes,
        current_input_fingerprints=fingerprints,
        validation=pd.DataFrame(validation_rows),
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


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _restore(path: Path, backup: Path, *, existed: bool) -> None:
    if backup.exists():
        _remove(path)
        backup.replace(path)
    elif not existed:
        _remove(path)


def _publication_targets(
    stage: Path,
    *,
    unified_root: Path,
    quality_panel: Path,
    quality_exhibit: Path,
) -> tuple[tuple[str, Path, Path], ...]:
    panel_sidecar = sidecar_path(quality_panel)
    exhibit_sidecar = sidecar_path(quality_exhibit)
    return (
        ("markers", unified_root / ".quality", stage / "legacy-quality"),
        ("panel", quality_panel, stage / "legacy-quality-panel"),
        (
            "panel_sidecar",
            panel_sidecar,
            stage / "legacy-quality-panel.provenance",
        ),
        ("exhibit", quality_exhibit, stage / "legacy-quality-exhibit"),
        (
            "exhibit_sidecar",
            exhibit_sidecar,
            stage / "legacy-quality-exhibit.provenance",
        ),
    )


def recover_interrupted_publication(
    *,
    unified_root: Path,
    quality_panel: Path,
    quality_exhibit: Path,
) -> int:
    """Roll an interrupted marker-first publication back to its legacy release."""

    recovered = 0
    for stage in sorted(unified_root.parent.glob(f"{_STAGE_PREFIX}*")):
        if not stage.is_dir():
            continue
        journal_path = stage / _JOURNAL_NAME
        if not journal_path.is_file():
            if any(stage.glob("legacy-*")):
                raise RuntimeError(
                    f"interrupted route migration has backups but no journal: {stage}"
                )
            shutil.rmtree(stage)
            continue
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"interrupted route migration journal is unreadable: {stage}"
            ) from error
        if journal.get("policy") != MIGRATION_POLICY or not isinstance(
            journal.get("original_existence"), dict
        ):
            raise RuntimeError(
                f"interrupted route migration journal is invalid: {stage}"
            )
        original = journal["original_existence"]
        targets = _publication_targets(
            stage,
            unified_root=unified_root,
            quality_panel=quality_panel,
            quality_exhibit=quality_exhibit,
        )
        if set(original) != {label for label, _path, _backup in targets}:
            raise RuntimeError(
                f"interrupted route migration journal perimeter changed: {stage}"
            )
        for label, path, backup in reversed(targets):
            _restore(path, backup, existed=bool(original[label]))
        shutil.rmtree(stage)
        recovered += 1
    return recovered


def publish_migration(
    plan: MigrationPlan,
    *,
    data_root: Path,
    unified_root: Path,
    quality_panel: Path,
    quality_exhibit: Path,
) -> None:
    """Publish marker-first and ledger-last, restoring the old release on failure."""

    stage = Path(
        tempfile.mkdtemp(
            dir=unified_root.parent,
            prefix=_STAGE_PREFIX,
        )
    )
    staged_markers = stage / "quality"
    staged_markers.mkdir()
    try:
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
        targets = _publication_targets(
            stage,
            unified_root=unified_root,
            quality_panel=quality_panel,
            quality_exhibit=quality_exhibit,
        )
        original_existence = {
            label: path.exists() for label, path, _backup in targets
        }
        journal = {
            "policy": MIGRATION_POLICY,
            "legacy_engine": LEGACY_ENGINE,
            "current_engine": RECONSTRUCTION_ENGINE,
            "original_existence": original_existence,
        }
        with atomic_output(stage / _JOURNAL_NAME) as temporary:
            temporary.write_text(
                json.dumps(journal, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        target_by_label = {
            label: (path, backup) for label, path, backup in targets
        }
        live_markers, marker_backup = target_by_label["markers"]
        try:
            live_markers.replace(marker_backup)
            staged_markers.replace(live_markers)
            for label, path, backup in targets[1:]:
                if original_existence[label]:
                    path.replace(backup)
            raw_roots = [
                data_root / "raw" / ("dune" if dex in DUNE_SOURCES else "thegraph") / dex
                for dex in sorted(DEX_FAMILY)
            ]
            notes = (
                f"{MIGRATION_POLICY}; legacy_engine={LEGACY_ENGINE}; "
                f"current_engine={RECONSTRUCTION_ENGINE}; "
                f"legacy_marker_set_sha256={plan.legacy_marker_set_sha256}; "
                f"exact_fresh_validation_days={len(plan.validation)}"
            )
            write_panel(
                plan.quality,
                quality_panel,
                code_sources=[
                    *RECONSTRUCT_CODE_SOURCES,
                    "scripts/migrate_route_release_markers.py",
                ],
                inputs=[live_markers, *raw_roots],
                notes=notes,
            )
            write_exhibit(
                _quality_summary(plan.quality),
                quality_exhibit,
                code_sources=[
                    *RECONSTRUCT_CODE_SOURCES,
                    "scripts/migrate_route_release_markers.py",
                ],
                inputs=[quality_panel],
                notes=notes,
            )
            observed = pd.read_parquet(quality_panel)
            pd.testing.assert_frame_equal(
                observed.reset_index(drop=True),
                plan.quality.reset_index(drop=True),
                check_dtype=True,
                check_exact=True,
            )
            for day, expected_hash in planned_marker_hashes.items():
                if file_sha256(unified_quality_path(day, root=unified_root)) != expected_hash:
                    raise RuntimeError(f"published route marker changed: {day}")
        except BaseException:
            for label, path, backup in reversed(targets):
                _restore(path, backup, existed=original_existence[label])
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


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
) -> MigrationPlan:
    """Plan, and optionally publish, the one admitted route marker migration."""

    dexes = dexes or list(DEX_FAMILY)
    unified_root = unified_root or data_root / "unified"
    with exclusive_job(
        raw_lock,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with serialized_output_installs((unified_root, quality_panel, quality_exhibit)):
            recover_interrupted_publication(
                unified_root=unified_root,
                quality_panel=quality_panel,
                quality_exhibit=quality_exhibit,
            )
            plan = plan_migration(
                data_root=data_root,
                unified_root=unified_root,
                quality_panel=quality_panel,
                dexes=dexes,
                days=days,
                workers=workers,
            )
            if publish:
                publish_migration(
                    plan,
                    data_root=data_root,
                    unified_root=unified_root,
                    quality_panel=quality_panel,
                    quality_exhibit=quality_exhibit,
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
    args = parser.parse_args()
    plan = migrate_route_release_markers(
        publish=args.publish,
        workers=args.workers,
    )
    byte_equal = int(
        plan.validation["fresh_parquet_matches_legacy_bytes"].sum()
    )
    print(
        f"route marker migration gate passed: {len(plan.days):,} days; "
        f"{len(plan.validation):,} exact fresh validation days; "
        f"{byte_equal:,} byte-identical fresh Parquets; "
        f"published={args.publish}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
