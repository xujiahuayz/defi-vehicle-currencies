"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
sidecar. Downstream scripts should derive routes, liquidity concentration, and
panels from this local raw layer rather than re-querying providers.
"""

from __future__ import annotations

import calendar
import datetime as dt
import gzip
import json
from pathlib import Path
from typing import Any

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import DexSource, get_source
from ddvc.paths import DATA_DIR


def midnight_ts(day: dt.date) -> int:
    return calendar.timegm(dt.datetime(day.year, day.month, day.day).timetuple())


def raw_path(source: str, stream: str, day: dt.date) -> Path:
    return (
        DATA_DIR
        / "raw"
        / "thegraph"
        / source
        / stream
        / f"{day:%Y}"
        / f"{source}_{stream}_{day:%Y%m%d}.jsonl.gz"
    )


def meta_path(source: str, day: dt.date) -> Path:
    return (
        DATA_DIR
        / "raw"
        / "thegraph"
        / source
        / "_meta"
        / f"{day:%Y}"
        / f"{source}_meta_{day:%Y%m%d}.json"
    )


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
            fh.write("\n")
    tmp.replace(path)


def where_for_entity(entity: EntitySpec, day: dt.date) -> dict[str, str]:
    start = midnight_ts(day)
    end = start + 86_400
    if entity.date_field:
        return {entity.date_field: str(start)}
    return {f"{entity.time_field}_gte": str(start), f"{entity.time_field}_lt": str(end)}


def _block_values(rows: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for row in rows:
        candidates = [
            row.get("block"),
            row.get("blockNumber"),
            (row.get("transaction") or {}).get("blockNumber"),
        ]
        for value in candidates:
            if value is None:
                continue
            try:
                values.append(int(value))
                break
            except (TypeError, ValueError):
                continue
    return values


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

    client = GraphClient(source.subgraph_id, graph_keys())
    head = head_block(client)
    stream_meta: dict[str, dict[str, Any]] = {}
    all_blocks: list[int] = []
    for entity in selected:
        out = raw_path(source.name, entity.stream, day)
        if skip_existing and out.exists():
            stream_meta[entity.stream] = {"path": str(out), "status": "skipped"}
            continue
        rows = paginate(
            client,
            entity=entity.entity,
            fields=entity.fields,
            base_where=where_for_entity(entity, day),
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
        "day": day.isoformat(),
        "head_block_at_fetch": head,
        "min_block": min(all_blocks) if all_blocks else None,
        "max_block": max(all_blocks) if all_blocks else None,
        "streams": stream_meta,
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    meta_out = meta_path(source.name, day)
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    tmp = meta_out.with_name(meta_out.name + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True))
    tmp.replace(meta_out)
    return meta


def stream_names_for_source(source_name: str) -> list[str]:
    source = get_source(source_name)
    return [entity.stream for entity in get_schema(source.schema).entities]
