#!/usr/bin/env python3
"""Build the four direct endpoint-candidate composition tables."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.endpoint_candidate_composition import (
    CHOICE_COLUMNS,
    CHOICE_AUDIT_COLUMNS,
    CHOICE_AUDIT_INTEGER_COLUMNS,
    CHOICE_AUDIT_KEYS,
    CHOICE_KEYS,
    COLLISION_AUDIT_INTEGER_COLUMNS,
    COLLISION_AUDIT_VALUE_COLUMNS,
    ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES,
    EXCLUSION_COLUMNS,
    EXCLUSION_KEYS,
    MAGNITUDE_COUNT_COLUMNS,
    MAGNITUDE_VALUE_COLUMNS,
    PAIR_KEYS,
    PAIR_SUPPORT_COLUMNS,
    PAIR_SUPPORT_COUNT_COLUMNS,
    PAIR_SUPPORT_VALUE_COLUMNS,
    ROUTE_INPUT_COLUMNS,
    endpoint_candidate_composition_for_day,
)
from ddvc.endpoint_candidate_composition_data import (
    ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
    validate_endpoint_candidate_composition_paths,
)
from ddvc.datasets import PartitionedDataset, route_partitions
from ddvc.paths import DATA_DIR, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool


LOCK = SHARED_RUNTIME_DIR / "endpoint-candidate-composition.lock"
CODE_SOURCES = [
    "scripts/process/build_endpoint_candidate_composition.py",
    "src/ddvc/route_data.py",
    *ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES,
    "src/ddvc/endpoint_candidate_composition_data.py",
]
TABLE_COLUMNS = {
    "choices": CHOICE_COLUMNS,
    "choice_audit": CHOICE_AUDIT_COLUMNS,
    "pair_support": PAIR_SUPPORT_COLUMNS,
    "exclusions": EXCLUSION_COLUMNS,
}
TABLE_KEYS = {
    "choices": CHOICE_KEYS,
    "choice_audit": CHOICE_AUDIT_KEYS,
    "pair_support": PAIR_KEYS,
    "exclusions": EXCLUSION_KEYS,
}
COUNT_COLUMNS = set(MAGNITUDE_COUNT_COLUMNS) | set(PAIR_SUPPORT_COUNT_COLUMNS)
VALUE_COLUMNS = (
    set(MAGNITUDE_VALUE_COLUMNS)
    | set(PAIR_SUPPORT_VALUE_COLUMNS)
    | set(COLLISION_AUDIT_VALUE_COLUMNS)
)
INTEGER_COLUMNS = (
    COUNT_COLUMNS
    | set(CHOICE_AUDIT_INTEGER_COLUMNS)
    | set(COLLISION_AUDIT_INTEGER_COLUMNS)
)
DATE_COLUMNS = {
    "date",
    "pair_first_supported_date",
    "pair_last_supported_date",
}
BOOL_COLUMNS = {"pair_entry_on_day", "pair_last_observed_on_day"}


def _schema(columns: list[str]) -> pa.Schema:
    fields: list[pa.Field] = []
    for column in columns:
        if column in INTEGER_COLUMNS:
            dtype = pa.int64()
        elif column in VALUE_COLUMNS:
            dtype = pa.float64()
        elif column in DATE_COLUMNS:
            dtype = pa.timestamp("ns")
        elif column in BOOL_COLUMNS:
            dtype = pa.bool_()
        else:
            dtype = pa.string()
        fields.append(pa.field(column, dtype, nullable=True))
    return pa.schema(fields)


TABLE_SCHEMAS = {name: _schema(columns) for name, columns in TABLE_COLUMNS.items()}


@dataclass(frozen=True)
class DayShard:
    day: str
    paths: Mapping[str, str]
    row_counts: Mapping[str, int]


@dataclass(frozen=True)
class BuildOutcome:
    days: int
    row_counts: Mapping[str, int]
    installed: bool


def _write_frame(frame: pd.DataFrame, path: Path, *, table: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrow = pa.Table.from_pandas(
        frame[TABLE_COLUMNS[table]],
        schema=TABLE_SCHEMAS[table],
        preserve_index=False,
        safe=True,
    )
    pq.write_table(arrow, path, compression="zstd")


def build_day_shard(
    release: PartitionedDataset,
    day: str,
    scratch_root: str,
) -> DayShard:
    """Build one independently validated UTC-day shard."""

    if release.days != (day,):
        raise ValueError("endpoint-candidate worker requires one exact released day")
    bundle = endpoint_candidate_composition_for_day(release.read_day(day), day)
    directory = Path(scratch_root) / day
    paths: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    for name in TABLE_COLUMNS:
        frame = getattr(bundle, name)
        row_counts[name] = len(frame)
        if frame.empty:
            continue
        path = directory / f"{name}.parquet"
        _write_frame(frame, path, table=name)
        paths[name] = str(path)
    return DayShard(day, paths, row_counts)


def _reduce_days(
    release: PartitionedDataset,
    *,
    workers: int,
    scratch_root: Path,
) -> list[DayShard]:
    selected_workers = bounded_workers(workers)
    subsets = [(release.select_days((day,)), day, str(scratch_root)) for day in release.days]
    if selected_workers == 1:
        results = [build_day_shard(*arguments) for arguments in subsets]
    else:
        results = []
        with interruptible_process_pool(selected_workers) as pool:
            futures = {pool.submit(build_day_shard, *arguments): arguments[1] for arguments in subsets}
            for index, future in enumerate(as_completed(futures), 1):
                results.append(future.result())
                if index % 250 == 0:
                    print(f"  reduced {index:,}/{len(subsets):,} days", flush=True)
    results.sort(key=lambda shard: shard.day)
    observed = tuple(shard.day for shard in results)
    if observed != release.days:
        raise RuntimeError("endpoint-candidate reduction did not cover the exact released perimeter")
    return results


def _pair_lifecycle(shards: list[DayShard]) -> dict[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp]]:
    lifecycle: dict[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp]] = {}
    for shard in shards:
        path_text = shard.paths.get("pair_support")
        if path_text is None:
            continue
        frame = pd.read_parquet(path_text, columns=["date", "src", "tgt"])
        for row in frame.itertuples(index=False):
            key = (str(row.src), str(row.tgt))
            observed = pd.Timestamp(row.date)
            prior = lifecycle.get(key)
            lifecycle[key] = (
                min(prior[0], observed) if prior else observed,
                max(prior[1], observed) if prior else observed,
            )
    return lifecycle


def _assemble_table(
    shards: list[DayShard],
    output: Path,
    *,
    table: str,
    lifecycle: Mapping[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp]],
) -> int:
    schema = TABLE_SCHEMAS[table]
    writer = pq.ParquetWriter(output, schema, compression="zstd")
    rows = 0
    try:
        for shard in shards:
            path_text = shard.paths.get(table)
            if path_text is None:
                continue
            frame = pd.read_parquet(path_text)
            if table == "pair_support":
                keys = zip(frame["src"].astype(str), frame["tgt"].astype(str), strict=True)
                bounds = [lifecycle[key] for key in keys]
                frame["pair_first_supported_date"] = [first for first, _last in bounds]
                frame["pair_last_supported_date"] = [last for _first, last in bounds]
                frame["pair_entry_on_day"] = frame["date"].eq(frame["pair_first_supported_date"])
                frame["pair_last_observed_on_day"] = frame["date"].eq(frame["pair_last_supported_date"])
            frame = frame.sort_values(TABLE_KEYS[table], kind="stable").reset_index(drop=True)
            arrow = pa.Table.from_pandas(
                frame[TABLE_COLUMNS[table]],
                schema=schema,
                preserve_index=False,
                safe=True,
            )
            writer.write_table(arrow)
            rows += len(frame)
        if rows == 0:
            writer.write_table(pa.Table.from_pylist([], schema=schema))
    finally:
        writer.close()
    expected = sum(int(shard.row_counts[table]) for shard in shards)
    if rows != expected:
        raise RuntimeError(
            f"endpoint-candidate {table} assembly lost rows: expected={expected}; observed={rows}"
        )
    return rows


def _assemble_release(
    shards: list[DayShard],
    output_root: Path,
) -> tuple[dict[str, Path], dict[str, int]]:
    output_root.mkdir(parents=True, exist_ok=True)
    lifecycle = _pair_lifecycle(shards)
    paths = {name: output_root / f"{name}.parquet" for name in TABLE_COLUMNS}
    row_counts = {
        name: _assemble_table(
            shards,
            paths[name],
            table=name,
            lifecycle=lifecycle,
        )
        for name in TABLE_COLUMNS
    }
    observed = validate_endpoint_candidate_composition_paths(paths)
    if observed != row_counts:
        raise RuntimeError("endpoint-candidate assembled row counts changed during validation")
    return paths, row_counts


def build_endpoint_candidate_composition(
    release: PartitionedDataset,
    *,
    workers: int,
    limit: int | None = None,
    output_paths: Mapping[str, Path] = ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
    scratch_parent: Path | None = None,
    lock_path: Path = LOCK,
) -> BuildOutcome:
    """Reduce one exact route dataset and atomically replace the four tables."""

    if not release.days:
        raise RuntimeError("endpoint-candidate source release has no calendar days")
    if limit is not None and limit < 1:
        raise ValueError("diagnostic limit must be positive")
    selected = release.select_days(release.days[:limit]) if limit is not None else release
    scratch_parent = scratch_parent or DATA_DIR / "processed"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with exclusive_job(lock_path, job="endpoint-candidate composition release"):
        with tempfile.TemporaryDirectory(
            dir=scratch_parent,
            prefix=".endpoint-candidate-composition-",
        ) as temporary:
            scratch = Path(temporary)
            shards = _reduce_days(
                selected,
                workers=workers,
                scratch_root=scratch / "days",
            )
            paths, row_counts = _assemble_release(shards, scratch / "assembled")
            if limit is not None:
                release.assert_current()
                return BuildOutcome(len(selected.days), row_counts, False)
            release.assert_current()
            for name, source in paths.items():
                target = output_paths[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as reader, atomic_output(target) as temporary:
                    with temporary.open("wb") as writer:
                        while chunk := reader.read(8 * 1024 * 1024):
                            writer.write(chunk)
            release.assert_current()
            return BuildOutcome(len(selected.days), row_counts, True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--limit",
        type=int,
        help="diagnostic day limit; validates a temporary subset and cannot replace outputs",
    )
    args = parser.parse_args()
    route_release = route_partitions(ROUTE_INPUT_COLUMNS, nonempty=False)
    print(
        f"reducing {len(route_release.days):,} released route days with "
        f"{bounded_workers(args.workers)} workers",
        flush=True,
    )
    outcome = build_endpoint_candidate_composition(
        route_release,
        workers=args.workers,
        limit=args.limit,
    )
    counts = ", ".join(
        f"{name}={rows:,}" for name, rows in sorted(outcome.row_counts.items())
    )
    if not outcome.installed:
        print(
            f"diagnostic subset validated on {outcome.days:,} days ({counts}); outputs unchanged"
        )
    else:
        print(
            f"wrote endpoint-candidate tables from {outcome.days:,} days ({counts})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
