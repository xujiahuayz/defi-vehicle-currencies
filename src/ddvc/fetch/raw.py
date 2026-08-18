"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
file. Only ingestion audits and the canonical materialisers may parse
this layer. Empirical runners consume versioned canonical events, states, or
analysis-ready panels and never re-query providers.
"""

from __future__ import annotations

import calendar
from contextlib import ExitStack, contextmanager
import datetime as dt
import gzip
import io
import json
import os
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, iter_paginate, paginate
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import DexSource, get_source
from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output, staged_output
from ddvc.source_records import block_value, block_values as _block_values


RAW_GRAPH_PAGE_SIZE = 1000
class RawFetchInvariantError(RuntimeError):
    """A non-transient raw-fetch failure that retrying cannot repair."""


class RawRefetchDivergenceError(RawFetchInvariantError):
    """A refetch disagreed with an installed raw capture."""


def _file_stat_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def midnight_ts(day: dt.date) -> int:
    return calendar.timegm(dt.datetime(day.year, day.month, day.day).timetuple())


def raw_path(
    source: str, stream: str, day: dt.date, *, data_root: Path = DATA_DIR
) -> Path:
    return (
        data_root
        / "raw"
        / "thegraph"
        / source
        / f"{source}_{stream}_{day:%Y%m%d}.jsonl.gz"
    )


def meta_path(source: str, day: dt.date, *, data_root: Path = DATA_DIR) -> Path:
    return (
        data_root
        / "raw"
        / "thegraph"
        / source
        / f"{source}_meta_{day:%Y%m%d}.json"
    )


def installed_source_day_paths(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
) -> tuple[Path, Path]:
    """Resolve one provider payload and its small operational metadata file."""

    backend = "dune" if get_source(source_name).backend == "dune" else "thegraph"
    directory = data_root / "raw" / backend / source_name
    return (
        directory / f"{source_name}_{stream}_{day:%Y%m%d}.jsonl.gz",
        directory / f"{source_name}_meta_{day:%Y%m%d}.json",
    )


def _stream_marker(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
) -> dict[str, Any]:
    if not path.is_file() or not marker_path.is_file():
        raise RawFetchInvariantError(
            f"raw source-day is uncommitted: {source_name}/{stream}/{day:%Y%m%d}"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RawFetchInvariantError(f"raw source-day metadata is unreadable: {marker_path}") from exc
    streams = marker.get("streams") if isinstance(marker, dict) else None
    item = streams.get(stream) if isinstance(streams, dict) else None
    rows = item.get("rows") if isinstance(item, dict) else None
    recorded_path = item.get("path") if isinstance(item, dict) else None
    if (
        marker.get("source") != source_name
        or marker.get("day") != day.isoformat()
        or isinstance(rows, bool)
        or not isinstance(rows, int)
        or rows < 0
        or not recorded_path
        or raw_stream_identity(Path(str(recorded_path))) != raw_stream_identity(path)
    ):
        raise RawFetchInvariantError(
            f"raw source-day metadata mismatch: {source_name}/{stream}/{day:%Y%m%d}"
        )
    return item


def require_committed_source_day_path(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
) -> Path:
    _stream_marker(
        path, marker_path, source_name=source_name, stream=stream, day=day
    )
    return path


def require_committed_source_day_stream(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
) -> Path:
    path, marker = installed_source_day_paths(
        source_name, stream, day, data_root=data_root
    )
    return require_committed_source_day_path(
        path, marker, source_name=source_name, stream=stream, day=day
    )


def source_day_stream_snapshot(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
) -> dict[str, object]:
    """Return row count and file facts used to detect changes during a read."""

    path, marker_path = installed_source_day_paths(
        source_name, stream, day, data_root=data_root
    )
    item = _stream_marker(
        path, marker_path, source_name=source_name, stream=stream, day=day
    )
    return {
        "source": source_name,
        "stream": stream,
        "day": day.strftime("%Y%m%d"),
        "path": path,
        "marker_path": marker_path,
        "rows": int(item["rows"]),
        "payload_stat": _file_stat_identity(path),
        "marker_stat": _file_stat_identity(marker_path),
    }


def _json_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RawFetchInvariantError(f"raw JSONL is malformed: {path}") from exc
            if not isinstance(row, dict):
                raise RawFetchInvariantError(f"raw JSONL row is not an object: {path}")
            yield row


@contextmanager
def verified_jsonl_gz_rows(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
):
    """Read one complete gzip JSONL source-day through its operational metadata."""

    before = source_day_stream_snapshot(
        source_name, stream, day, data_root=path.parents[3]
    )
    exhausted = False
    observed_rows = 0

    def rows():
        nonlocal exhausted, observed_rows
        for row in _json_rows(path):
            observed_rows += 1
            yield row
        exhausted = True

    iterator = rows()
    try:
        yield iterator
    finally:
        if not exhausted:
            iterator.close()
            raise RawFetchInvariantError(
                f"raw stream was not exhausted: {source_name}/{stream}/{day:%Y%m%d}"
            )
    if observed_rows != int(before["rows"]):
        raise RawFetchInvariantError(
            f"raw row count differs from metadata: {source_name}/{stream}/{day:%Y%m%d}"
        )
    after = source_day_stream_snapshot(
        source_name, stream, day, data_root=path.parents[3]
    )
    if after != before:
        raise RawFetchInvariantError(
            f"raw source-day changed during read: {source_name}/{stream}/{day:%Y%m%d}"
        )


@contextmanager
def verified_source_day_rows(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
):
    """Read one complete source-day and reject concurrent file replacement."""

    before = source_day_stream_snapshot(
        source_name, stream, day, data_root=data_root
    )
    exhausted = False
    observed_rows = 0

    def rows():
        nonlocal exhausted, observed_rows
        for row in _json_rows(Path(before["path"])):
            observed_rows += 1
            yield row
        exhausted = True

    iterator = rows()
    try:
        yield iterator
    finally:
        if not exhausted:
            iterator.close()
            raise RawFetchInvariantError(
                f"raw stream was not exhausted: {source_name}/{stream}/{day:%Y%m%d}"
            )
    if observed_rows != int(before["rows"]):
        raise RawFetchInvariantError(
            f"raw row count differs from metadata: {source_name}/{stream}/{day:%Y%m%d}"
        )
    after = source_day_stream_snapshot(
        source_name, stream, day, data_root=data_root
    )
    if after != before:
        raise RawFetchInvariantError(
            f"raw source-day changed during read: {source_name}/{stream}/{day:%Y%m%d}"
        )


def _raw_path_at(source: str, stream: str, day: dt.date, data_root: Path) -> Path:
    return (
        raw_path(source, stream, day)
        if data_root == DATA_DIR
        else raw_path(source, stream, day, data_root=data_root)
    )


def raw_stream_identity(path: Path) -> str:
    """Portable source/filename identity for one installed raw stream."""

    return f"{path.parent.name}/{path.name}"


def _jsonl_line(row: Mapping[str, Any]) -> str:
    return json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Atomically stream deterministic JSON Lines without retaining the iterable."""

    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(_jsonl_line(row))


def write_jsonl_gz(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Atomically stream byte-deterministic gzip JSON Lines from any iterable."""

    with atomic_output(path) as temporary:
        _write_jsonl_gz_payload(temporary, rows)


def _write_jsonl_gz_payload(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(_jsonl_line(row))


def repair_torn_jsonl_journal(path: Path) -> bool:
    """Drop an interrupted final fragment or terminate a complete final JSON value."""

    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("r+b") as handle:
        handle.seek(0, io.SEEK_END)
        end = handle.tell()
        handle.seek(end - 1)
        if handle.read(1) == b"\n":
            return False
        cursor = end
        reverse_chunks: list[bytes] = []
        line_start = 0
        while cursor > 0:
            chunk_start = max(0, cursor - 64 * 1024)
            handle.seek(chunk_start)
            chunk = handle.read(cursor - chunk_start)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                line_start = chunk_start + newline + 1
                reverse_chunks.append(chunk[newline + 1 :])
                break
            reverse_chunks.append(chunk)
            cursor = chunk_start
        final = b"".join(reversed(reverse_chunks))
        try:
            json.loads(final.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            handle.seek(line_start)
            handle.truncate()
        else:
            handle.seek(0, io.SEEK_END)
            handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a JSON object and remove a failed write's temporary file."""
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def where_for_entity(entity: EntitySpec, day: dt.date) -> dict[str, str]:
    if entity.fetch_mode != "day_partitioned":
        raise ValueError(
            f"{entity.stream} uses {entity.fetch_mode}; it cannot enter a day fetch"
        )
    start = midnight_ts(day)
    end = start + 86_400
    if entity.date_field:
        return {entity.date_field: str(start)}
    return {f"{entity.time_field}_gte": str(start), f"{entity.time_field}_lt": str(end)}


def where_chunks_for_entity(entity: EntitySpec, day: dt.date) -> list[dict[str, str]]:
    if entity.fetch_mode != "day_partitioned":
        raise ValueError(
            f"{entity.stream} uses {entity.fetch_mode}; it requires its dedicated acquisition runner"
        )
    policy = query_chunk_policy(entity)
    if policy == "date_exact_hex_id_prefix_v1":
        prefixes = "0123456789abcdef"
        chunks: list[dict[str, str]] = []
        for index, prefix in enumerate(prefixes):
            where = {entity.date_field: str(midnight_ts(day)), "id_gte": f"0x{prefix}"}
            if index + 1 < len(prefixes):
                where["id_lt"] = f"0x{prefixes[index + 1]}"
            chunks.append(where)
        return chunks
    if policy == "hour_exact_v1":
        start = midnight_ts(day)
        return [{entity.time_field: str(start + 3600 * hour)} for hour in range(24)]
    if policy == "hour_range_v1":
        start = midnight_ts(day)
        return [
            {
                f"{entity.time_field}_gte": str(start + 3600 * hour),
                f"{entity.time_field}_lt": str(start + 3600 * (hour + 1)),
            }
            for hour in range(24)
        ]
    return [where_for_entity(entity, day)]


def page_size_for_entity(entity: EntitySpec) -> int:
    return RAW_GRAPH_PAGE_SIZE


def query_chunk_policy(entity: EntitySpec) -> str:
    """Return the canonical day-query partition policy for one Graph entity."""

    if entity.fetch_mode != "day_partitioned":
        return {
            "global_historical": "global_id_ascending_v1",
            "static_snapshot": "frozen_head_id_ascending_v1",
            "block_pinned_configuration": "explicit_block_checkpoint_id_ascending_v1",
            "head_validation_only": "canary_only_never_backfill",
        }[entity.fetch_mode]
    if entity.date_field:
        return "date_exact_hex_id_prefix_v1"
    if entity.stream == "hourly_reserves" and entity.time_field == "hourStartUnix":
        return "hour_exact_v1"
    if entity.stream == "swaps":
        return "hour_range_v1"
    return "day_range_v1"


def fetch_graph_entity_rows(
    client: GraphClient,
    entity: EntitySpec,
    *,
    where_chunks: Iterable[dict[str, Any]],
    block_number: int,
    max_pages_per_chunk: int = 10_000,
) -> list[dict[str, Any]]:
    """Fetch all rows for one declared Graph entity and day."""

    rows: list[dict[str, Any]] = []
    for where in where_chunks:
        rows.extend(
            paginate(
                client,
                entity=entity.entity,
                fields=entity.fields,
                base_where=where,
                page_size=page_size_for_entity(entity),
                block_number=block_number,
                max_pages=max_pages_per_chunk,
            )
        )
    return rows


def iter_graph_entity_rows(
    client: GraphClient,
    entity: EntitySpec,
    *,
    where_chunks: Iterable[dict[str, Any]],
    block_number: int,
    max_pages_per_chunk: int = 10_000,
) -> Iterable[dict[str, Any]]:
    for where in where_chunks:
        yield from iter_paginate(
            client,
            entity=entity.entity,
            fields=entity.fields,
            base_where=where,
            page_size=page_size_for_entity(entity),
            block_number=block_number,
            max_pages=max_pages_per_chunk,
        )


def _raw_stream_metadata_item_is_current(
    item: object, *, expected_path: Path | None = None
) -> bool:
    if (
        not isinstance(item, dict)
        or isinstance(item.get("rows"), bool)
        or not isinstance(item.get("rows"), int)
        or item["rows"] < 0
        or not item.get("path")
    ):
        return False
    return expected_path is None or raw_stream_identity(
        Path(str(item["path"]))
    ) == raw_stream_identity(expected_path)


def raw_stream_metadata_is_current(
    item: object,
    entity: EntitySpec,
    *,
    expected_path: Path | None = None,
) -> bool:
    """Return whether operational metadata names the installed stream and row count."""

    return _raw_stream_metadata_item_is_current(item, expected_path=expected_path)


def indexed_metadata_streams(
    path: Path,
    *,
    expected_paths: dict[str, Path] | None = None,
    **_legacy_options: object,
) -> set[str]:
    """Return streams with a row ledger and the expected portable path."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, dict):
        return set()
    return {
        str(name)
        for name, item in streams.items()
        if _raw_stream_metadata_item_is_current(
            item, expected_path=(expected_paths or {}).get(str(name))
        )
    }


def merge_stream_metadata(
    existing: dict[str, Any], fresh: dict[str, Any]
) -> dict[str, Any]:
    """Merge a partial fetch without dropping metadata for omitted streams."""

    merged = {**existing, **fresh}
    streams = dict(existing.get("streams") or {})
    for name, item in (fresh.get("streams") or {}).items():
        if item.get("status") == "skipped" and name in streams:
            continue
        streams[name] = item
    merged["streams"] = streams
    blocks = [
        int(value)
        for item in streams.values()
        for value in (item.get("min_block"), item.get("max_block"))
        if value is not None
    ]
    merged["min_block"] = min(blocks) if blocks else None
    merged["max_block"] = max(blocks) if blocks else None
    return merged


def require_mergeable_partial_metadata(
    existing: dict[str, Any],
    *,
    requested_streams: set[str],
    canonical_streams: set[str],
) -> None:
    if requested_streams == canonical_streams:
        return
    if not isinstance(existing.get("streams"), dict):
        raise RawFetchInvariantError(
            "partial raw refresh requires existing per-stream metadata; "
            "repair metadata or fetch all streams once"
        )


def read_source_day_metadata(
    source: DexSource, day: dt.date, *, data_root: Path = DATA_DIR
) -> dict[str, Any]:
    path = meta_path(source.name, day, data_root=data_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RawFetchInvariantError(f"raw metadata is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise RawFetchInvariantError(f"raw metadata is not an object: {path}")
    if payload.get("source") not in (None, source.name) or payload.get("day") not in (
        None, day.isoformat()
    ):
        raise RawFetchInvariantError(f"raw metadata identity conflicts at {path}")
    return payload


def require_frozen_graph_head(source: DexSource, head: int | None) -> int:
    minimum = source.genesis_block or 0
    if head is None or isinstance(head, bool) or head < minimum:
        raise RuntimeError(f"Graph source did not expose a valid frozen head: {source.name}")
    return head


def frozen_graph_head(source: DexSource) -> int:
    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    return require_frozen_graph_head(source, head_block(client))


def index_existing_stream(path: Path, entity: EntitySpec) -> dict[str, Any]:
    """Rebuild the small row/block ledger for an installed raw stream."""

    rows = 0
    min_block: int | None = None
    max_block: int | None = None
    try:
        for record in _json_rows(path):
            rows += 1
            block = block_value(record)
            if block is not None:
                min_block = block if min_block is None else min(min_block, block)
                max_block = block if max_block is None else max(max_block, block)
    except (OSError, EOFError) as exc:
        raise RuntimeError(f"installed raw stream is unreadable: {path}") from exc
    return {
        "path": raw_stream_identity(path),
        "status": "indexed_existing",
        "entity": entity.entity,
        "rows": rows,
        "min_block": min_block,
        "max_block": max_block,
    }


def repair_source_day_metadata(
    source: DexSource,
    day: dt.date,
    *,
    streams: set[str] | None = None,
    data_root: Path = DATA_DIR,
) -> dict[str, Any]:
    schema = get_schema(source.schema)
    selected = [
        entity for entity in schema.entities
        if streams is None or entity.stream in streams
    ]
    existing = read_source_day_metadata(source, day, data_root=data_root)
    stream_meta: dict[str, dict[str, Any]] = {}
    for entity in selected:
        path = _raw_path_at(source.name, entity.stream, day, data_root)
        if not path.is_file():
            raise FileNotFoundError(f"installed raw stream is missing: {path}")
        stream_meta[entity.stream] = index_existing_stream(path, entity)
    fresh = {
        "source": source.name,
        "backend": "thegraph",
        "schema": source.schema,
        "subgraph_id": source.subgraph_id,
        "day": day.isoformat(),
        "streams": stream_meta,
        "metadata_indexed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    merged = merge_stream_metadata(existing, fresh)
    write_json(meta_path(source.name, day, data_root=data_root), merged)
    return merged



def _gzip_payloads_equal(first: Path, second: Path) -> bool:
    """Compare logical gzip bytes directly without assigning a content identity."""

    try:
        with gzip.open(first, "rb") as left, gzip.open(second, "rb") as right:
            while True:
                a = left.read(1024 * 1024)
                b = right.read(1024 * 1024)
                if a != b:
                    return False
                if not a:
                    return True
    except (OSError, EOFError):
        return False


def _preserve_refetch_candidate(
    source: DexSource, day: dt.date, entity: EntitySpec, candidate: Path, *, data_root: Path
) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = data_root / "raw" / "refetch_candidates" / source.name / f"{day:%Y%m%d}"
    target = root / f"{entity.stream}_{stamp}.jsonl.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate.replace(target)
    return target


def fetch_source_day(
    source: DexSource,
    day: dt.date,
    *,
    streams: set[str] | None = None,
    skip_existing: bool = True,
    head_block_at_fetch: int | None = None,
    data_root: Path = DATA_DIR,
    max_pages_per_chunk: int = 10_000,
    max_transient_retries: int = 4,
) -> dict[str, Any]:
    """Fetch a Graph source-day, installing payloads before one metadata update."""

    schema = get_schema(source.schema)
    selected = [
        entity for entity in schema.entities
        if streams is None or entity.stream in streams
    ]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}
    meta_out = meta_path(source.name, day, data_root=data_root)
    existing = read_source_day_metadata(source, day, data_root=data_root)
    if streams is not None and meta_out.exists():
        require_mergeable_partial_metadata(
            existing,
            requested_streams={entity.stream for entity in selected},
            canonical_streams={entity.stream for entity in schema.entities},
        )
    existing_streams = existing.get("streams")
    existing_streams = existing_streams if isinstance(existing_streams, dict) else {}
    client = GraphClient(
        source.subgraph_id,
        graph_keys(),
        graph_path=source.graph_path,
        max_transient_retries=max_transient_retries,
    )
    head = require_frozen_graph_head(
        source,
        head_block_at_fetch if head_block_at_fetch is not None else head_block(client),
    )
    stream_meta: dict[str, dict[str, Any]] = {}
    staged: list[dict[str, Any]] = []
    with ExitStack() as stack:
        for entity in selected:
            target = _raw_path_at(source.name, entity.stream, day, data_root)
            if (
                skip_existing
                and target.is_file()
                and raw_stream_metadata_is_current(
                    existing_streams.get(entity.stream), entity, expected_path=target
                )
            ):
                stream_meta[entity.stream] = {
                    "path": raw_stream_identity(target), "status": "skipped"
                }
                continue
            rows = fetch_graph_entity_rows(
                client,
                entity,
                where_chunks=where_chunks_for_entity(entity, day),
                block_number=head,
                max_pages_per_chunk=max_pages_per_chunk,
            )
            temporary = stack.enter_context(staged_output(target))
            _write_jsonl_gz_payload(temporary, rows)
            blocks = _block_values(rows)
            staged.append(
                {
                    "entity": entity,
                    "target": target,
                    "temporary": temporary,
                    "target_existed": target.exists(),
                    "metadata": {
                        "path": raw_stream_identity(target),
                        "status": "fetched",
                        "entity": entity.entity,
                        "rows": len(rows),
                        "min_block": min(blocks) if blocks else None,
                        "max_block": max(blocks) if blocks else None,
                        "head_block_at_fetch": head,
                        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    },
                }
            )

        divergent = [
            item for item in staged
            if item["target_existed"]
            and not _gzip_payloads_equal(item["target"], item["temporary"])
        ]
        if divergent:
            preserved = [
                _preserve_refetch_candidate(
                    source, day, item["entity"], item["temporary"], data_root=data_root
                )
                for item in divergent
            ]
            raise RawRefetchDivergenceError(
                f"refetch differs from installed raw data for {source.name} {day}; "
                f"candidate preserved at {preserved[0]}"
            )

        for item in staged:
            if item["target_existed"]:
                item["metadata"]["status"] = "refetched_identical"
            else:
                item["temporary"].replace(item["target"])
            stream_meta[item["entity"].stream] = item["metadata"]

        fresh = {
            "source": source.name,
            "backend": "thegraph",
            "schema": source.schema,
            "subgraph_id": source.subgraph_id,
            "source_genesis_block": source.genesis_block,
            "source_genesis_date_utc": source.genesis_date_utc.isoformat(),
            "day": day.isoformat(),
            "head_block_at_fetch": head,
            "streams": stream_meta,
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        merged = merge_stream_metadata(existing, fresh)
        write_json(meta_out, merged)
        return merged


def stream_names_for_source(source_name: str) -> list[str]:
    source = get_source(source_name)
    return [entity.stream for entity in get_schema(source.schema).entities]
