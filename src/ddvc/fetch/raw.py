"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
sidecar. Only ingestion audits and the canonical node-D materialisers may parse
this layer. Empirical runners consume versioned canonical events, states, or
analysis-ready panels and never re-query providers.
"""

from __future__ import annotations

import calendar
import datetime as dt
import gzip
import io
import json
from pathlib import Path
from typing import Any

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import DexSource, get_source
from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output
from ddvc.source_records import block_value, block_values as _block_values


def midnight_ts(day: dt.date) -> int:
    return calendar.timegm(dt.datetime(day.year, day.month, day.day).timetuple())


def raw_path(source: str, stream: str, day: dt.date) -> Path:
    return (
        DATA_DIR
        / "raw"
        / "thegraph"
        / source
        / f"{source}_{stream}_{day:%Y%m%d}.jsonl.gz"
    )


def meta_path(source: str, day: dt.date) -> Path:
    return (
        DATA_DIR
        / "raw"
        / "thegraph"
        / source
        / f"{source}_meta_{day:%Y%m%d}.json"
    )


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    with atomic_output(path) as temporary:
        with temporary.open("wb") as raw_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_handle,
                mtime=0,
            ) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as fh:
                    for row in rows:
                        fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
                        fh.write("\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a JSON object and remove a failed write's temporary file."""
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def where_for_entity(entity: EntitySpec, day: dt.date) -> dict[str, str]:
    start = midnight_ts(day)
    end = start + 86_400
    if entity.date_field:
        return {entity.date_field: str(start)}
    return {f"{entity.time_field}_gte": str(start), f"{entity.time_field}_lt": str(end)}


def where_chunks_for_entity(entity: EntitySpec, day: dt.date) -> list[dict[str, str]]:
    if entity.date_field:
        prefixes = "0123456789abcdef"
        chunks: list[dict[str, str]] = []
        for index, prefix in enumerate(prefixes):
            where = {entity.date_field: str(midnight_ts(day)), "id_gte": f"0x{prefix}"}
            if index + 1 < len(prefixes):
                where["id_lt"] = f"0x{prefixes[index + 1]}"
            chunks.append(where)
        return chunks
    if entity.stream == "hourly_reserves" and entity.time_field == "hourStartUnix":
        start = midnight_ts(day)
        return [{entity.time_field: str(start + 3600 * hour)} for hour in range(24)]
    if entity.stream == "swaps":
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
    return 1000


def merge_stream_metadata(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial stream refresh without deleting provenance for other streams."""
    merged = {**existing, **fresh}
    streams = dict(existing.get("streams") or {})
    for name, item in (fresh.get("streams") or {}).items():
        if item.get("status") == "skipped" and name in streams:
            continue
        streams[name] = item
    merged["streams"] = streams
    mins = [
        int(item["min_block"])
        for item in streams.values()
        if item.get("min_block") is not None
    ]
    maxes = [
        int(item["max_block"])
        for item in streams.values()
        if item.get("max_block") is not None
    ]
    merged["min_block"] = min(mins) if mins else None
    merged["max_block"] = max(maxes) if maxes else None
    return merged


def require_mergeable_partial_metadata(
    existing: dict[str, Any],
    *,
    requested_streams: set[str],
    canonical_streams: set[str],
) -> None:
    """Refuse a partial refresh when legacy metadata cannot preserve omitted streams."""

    if requested_streams == canonical_streams:
        return
    recorded = existing.get("streams")
    if not isinstance(recorded, dict) or not recorded:
        raise RuntimeError(
            "partial raw refresh cannot merge into legacy metadata without a stream ledger; "
            "refresh the canonical stream set together once"
        )


def index_existing_stream(path: Path, entity: EntitySpec) -> dict[str, Any]:
    """Rebuild one stream's sidecar facts from its installed gzip payload."""

    rows = 0
    min_block: int | None = None
    max_block: int | None = None
    line_number = 0
    try:
        with gzip.open(path, "rt") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("raw JSONL row is not an object")
                rows += 1
                block = block_value(record)
                if block is not None:
                    min_block = block if min_block is None else min(min_block, block)
                    max_block = block if max_block is None else max(max_block, block)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"installed raw stream is not valid gzip JSONL at {path}:{line_number}: {exc}"
        ) from exc
    return {
        "path": str(path),
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
) -> dict[str, Any]:
    """Index installed streams and merge them into one source-day sidecar."""

    schema = get_schema(source.schema)
    selected = [entity for entity in schema.entities if streams is None or entity.stream in streams]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}
    stream_meta: dict[str, dict[str, Any]] = {}
    for entity in selected:
        path = raw_path(source.name, entity.stream, day)
        if not path.is_file():
            raise FileNotFoundError(f"installed raw stream is missing: {path}")
        stream_meta[entity.stream] = index_existing_stream(path, entity)
    meta_out = meta_path(source.name, day)
    existing: dict[str, Any] = {}
    if meta_out.exists():
        try:
            existing = json.loads(meta_out.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"raw metadata is unreadable: {meta_out}: {exc}") from exc
        expected = {"source": source.name, "day": day.isoformat()}
        conflicts = {
            key: (existing.get(key), value)
            for key, value in expected.items()
            if existing.get(key) not in (None, value)
        }
        if conflicts:
            raise RuntimeError(f"raw metadata identity conflicts at {meta_out}: {conflicts}")
    fresh = {
        "source": source.name,
        "schema": source.schema,
        "subgraph_id": source.subgraph_id,
        "graph_path": source.graph_path,
        "source_genesis_block": source.genesis_block,
        "source_genesis_date_utc": source.genesis_date_utc.isoformat(),
        "day": day.isoformat(),
        "streams": stream_meta,
        "metadata_indexed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    merged = merge_stream_metadata(existing, fresh)
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    write_json(meta_out, merged)
    return merged


def fetch_source_day(
    source: DexSource,
    day: dt.date,
    *,
    streams: set[str] | None = None,
    skip_existing: bool = True,
) -> dict[str, Any]:
    schema = get_schema(source.schema)
    selected = [entity for entity in schema.entities if streams is None or entity.stream in streams]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}

    meta_out = meta_path(source.name, day)
    if streams is not None and meta_out.exists():
        existing_meta = json.loads(meta_out.read_text())
        require_mergeable_partial_metadata(
            existing_meta,
            requested_streams={entity.stream for entity in selected},
            canonical_streams={entity.stream for entity in schema.entities},
        )

    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    head = head_block(client)
    stream_meta: dict[str, dict[str, Any]] = {}
    all_blocks: list[int] = []
    for entity in selected:
        out = raw_path(source.name, entity.stream, day)
        if skip_existing and out.exists():
            stream_meta[entity.stream] = {"path": str(out), "status": "skipped"}
            continue
        rows: list[dict[str, Any]] = []
        for where in where_chunks_for_entity(entity, day):
            rows.extend(
                paginate(
                    client,
                    entity=entity.entity,
                    fields=entity.fields,
                    base_where=where,
                    page_size=page_size_for_entity(entity),
                )
            )
        write_jsonl_gz(out, rows)
        blocks = _block_values(rows)
        all_blocks.extend(blocks)
        stream_meta[entity.stream] = {
            "path": str(out),
            "status": "fetched",
            "entity": entity.entity,
            "rows": len(rows),
            "min_block": min(blocks) if blocks else None,
            "max_block": max(blocks) if blocks else None,
        }

    meta = {
        "source": source.name,
        "schema": source.schema,
        "subgraph_id": source.subgraph_id,
        "graph_path": source.graph_path,
        "source_genesis_block": source.genesis_block,
        "source_genesis_date_utc": source.genesis_date_utc.isoformat(),
        "day": day.isoformat(),
        "head_block_at_fetch": head,
        "min_block": min(all_blocks) if all_blocks else None,
        "max_block": max(all_blocks) if all_blocks else None,
        "streams": stream_meta,
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    if meta_out.exists():
        try:
            meta = merge_stream_metadata(json.loads(meta_out.read_text()), meta)
        except (OSError, json.JSONDecodeError):
            pass
    write_json(meta_out, meta)
    return meta


def stream_names_for_source(source_name: str) -> list[str]:
    source = get_source(source_name)
    return [entity.stream for entity in get_schema(source.schema).entities]
