"""Build and summarize the persisted raw AMM-data inventory."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
import gzip
import json
import os
from pathlib import Path
import re

import pandas as pd

from ddvc.fetch.sources import DEX_SOURCES


RAW_STREAMS = frozenset(
    {
        "swaps",
        "daily",
        "hourly_reserves",
        "mints",
        "burns",
        "modify_liquidities",
    }
)
LP_STREAMS = frozenset({"mints", "burns", "modify_liquidities"})
LEGACY_STREAM_KEYS = {"swaps": "swaps", "daily": "pool_days"}
INVENTORY_COLUMNS = [
    "source",
    "backend",
    "stream",
    "date",
    "raw_path",
    "records",
    "compressed_bytes",
    "mtime_ns",
    "count_method",
]


def metadata_row_count(metadata: dict[str, object], stream: str) -> int | None:
    """Read a stream count from either current or imported legacy sidecars."""

    streams = metadata.get("streams")
    if isinstance(streams, dict):
        stream_metadata = streams.get(stream)
        if isinstance(stream_metadata, dict) and stream_metadata.get("rows") is not None:
            return int(stream_metadata["rows"])

    legacy_key = LEGACY_STREAM_KEYS.get(stream)
    if legacy_key is not None and metadata.get(legacy_key) is not None:
        return int(metadata[legacy_key])
    return None


def count_jsonl_gz_rows(path: Path) -> int:
    """Count records in a gzipped JSONL file without parsing its payload."""

    records = 0
    final_byte = b""
    with gzip.open(path, "rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            records += chunk.count(b"\n")
            final_byte = chunk[-1:]
    if final_byte and final_byte != b"\n":
        records += 1
    return records


def _load_metadata(source_dir: Path, source: str) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for path in source_dir.glob(f"{source}_meta_*.json"):
        date_key = path.stem.rsplit("_", 1)[-1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            metadata[date_key] = payload
    return metadata


def _cached_counts(previous: pd.DataFrame | None) -> dict[str, tuple[int, int, int]]:
    if previous is None or previous.empty:
        return {}
    required = {"raw_path", "records", "compressed_bytes", "mtime_ns"}
    if not required.issubset(previous.columns):
        return {}
    return {
        str(row.raw_path): (
            int(row.records),
            int(row.compressed_bytes),
            int(row.mtime_ns),
        )
        for row in previous.itertuples(index=False)
    }


def build_raw_data_inventory(
    raw_root: Path,
    *,
    previous: pd.DataFrame | None = None,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Inventory every persisted AMM raw file and its exact record count."""

    cache = _cached_counts(previous)
    rows: list[dict[str, object]] = []
    exact_jobs: list[tuple[int, Path]] = []

    for source, source_spec in DEX_SOURCES.items():
        source_dir = raw_root / source_spec.backend / source
        if not source_dir.exists():
            raise FileNotFoundError(f"Raw source directory is missing: {source_dir}")

        metadata = _load_metadata(source_dir, source)
        filename_re = re.compile(
            rf"^{re.escape(source)}_(?P<stream>.+)_(?P<date>\d{{8}})\.jsonl\.gz$"
        )
        source_files = sorted(source_dir.glob(f"{source}_*.jsonl.gz"))
        if not source_files:
            raise FileNotFoundError(f"No raw data files found for {source}: {source_dir}")

        for path in source_files:
            match = filename_re.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unrecognized raw filename: {path}")
            stream = match.group("stream")
            if stream not in RAW_STREAMS:
                raise ValueError(f"Unregistered raw stream {stream!r}: {path}")

            date_key = match.group("date")
            stat = path.stat()
            raw_path = path.relative_to(raw_root).as_posix()
            records = metadata_row_count(metadata.get(date_key, {}), stream)
            method = "sidecar"
            if records is None:
                cached = cache.get(raw_path)
                if cached is not None and cached[1:] == (stat.st_size, stat.st_mtime_ns):
                    records = cached[0]
                    method = "cached exact scan"
                else:
                    method = "exact scan"

            rows.append(
                {
                    "source": source,
                    "backend": source_spec.backend,
                    "stream": stream,
                    "date": pd.to_datetime(date_key, format="%Y%m%d"),
                    "raw_path": raw_path,
                    "records": records,
                    "compressed_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "count_method": method,
                }
            )
            if records is None:
                exact_jobs.append((len(rows) - 1, path))

    if exact_jobs:
        worker_count = workers or min(10, max(1, (os.cpu_count() or 2) - 1))
        if progress is not None:
            compressed_gb = sum(path.stat().st_size for _, path in exact_jobs) / 1e9
            progress(
                f"counting {len(exact_jobs):,} raw files without complete sidecars "
                f"({compressed_gb:.1f} GB compressed; {worker_count} workers)"
            )
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            counts = executor.map(count_jsonl_gz_rows, (path for _, path in exact_jobs))
            for (row_index, _), count in zip(exact_jobs, counts, strict=True):
                rows[row_index]["records"] = count

    inventory = pd.DataFrame(rows, columns=INVENTORY_COLUMNS)
    if inventory.empty or inventory["records"].isna().any():
        raise ValueError("Raw-data inventory contains unresolved record counts.")
    if inventory["raw_path"].duplicated().any():
        raise ValueError("Raw-data inventory contains duplicate file paths.")
    inventory["records"] = inventory["records"].astype("int64")
    return inventory.sort_values(["source", "date", "stream"]).reset_index(drop=True)


def summarize_raw_data_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the file inventory into paper-facing AMM coverage statistics."""

    required = {
        "source",
        "backend",
        "stream",
        "date",
        "records",
        "compressed_bytes",
    }
    missing = required.difference(inventory.columns)
    if missing:
        raise KeyError(f"Raw-data inventory is missing columns: {sorted(missing)}")
    unknown_streams = set(inventory["stream"]).difference(RAW_STREAMS)
    if unknown_streams:
        raise ValueError(f"Raw-data inventory has unknown streams: {sorted(unknown_streams)}")

    rows: list[dict[str, object]] = []
    for source, source_spec in DEX_SOURCES.items():
        group = inventory[inventory["source"].eq(source)].copy()
        if group.empty:
            raise ValueError(f"Raw-data inventory has no rows for {source}.")
        swaps = group[group["stream"].eq("swaps")]
        active_swaps = swaps[swaps["records"].gt(0)]
        if active_swaps.empty:
            raise ValueError(f"Raw-data inventory has no positive swap day for {source}.")

        def stream_total(names: set[str] | frozenset[str]) -> int:
            return int(group.loc[group["stream"].isin(names), "records"].sum())

        rows.append(
            {
                "source": source,
                "backend": source_spec.backend,
                "start": pd.to_datetime(active_swaps["date"]).min().normalize(),
                "end": pd.to_datetime(active_swaps["date"]).max().normalize(),
                "active_days": int(active_swaps["date"].nunique()),
                "swap_records": stream_total({"swaps"}),
                "daily_state_records": stream_total({"daily"}),
                "hourly_state_records": stream_total({"hourly_reserves"}),
                "lp_event_records": stream_total(LP_STREAMS),
                "raw_files": int(group.shape[0]),
                "compressed_bytes": int(group["compressed_bytes"].sum()),
                "total_records": int(group["records"].sum()),
            }
        )
    return pd.DataFrame(rows)
