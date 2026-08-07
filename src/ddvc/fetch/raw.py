"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
sidecar. Downstream scripts should derive routes, liquidity concentration, and
panels from this local raw layer rather than re-querying providers.
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


def transaction_value(row: dict[str, Any], field: str) -> Any:
    """Read transaction data from either nested or scalar Graph schemas.

    Older Uniswap subgraphs expose ``transaction { id blockNumber timestamp }``;
    the current v4 schema exposes the transaction hash as a scalar string. Keeping
    that variant handling here prevents every downstream reader from growing its
    own slightly different schema shim.
    """
    transaction = row.get("transaction")
    if isinstance(transaction, dict):
        return transaction.get(field)
    if field == "id" and isinstance(transaction, str):
        return transaction
    return None


def _block_values(rows: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for row in rows:
        candidates = [
            row.get("block"),
            row.get("blockNumber"),
            transaction_value(row, "blockNumber"),
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


def block_value(row: dict[str, Any] | None) -> int | None:
    if row is None:
        return None
    values = _block_values([row])
    return values[0] if values else None


def timestamp_value(row: dict[str, Any] | None) -> int | None:
    if row is None:
        return None
    candidates = [
        row.get("timestamp"),
        transaction_value(row, "timestamp"),
        row.get("hourStartUnix"),
        row.get("date"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def transaction_id(row: dict[str, Any]) -> str | None:
    value = transaction_value(row, "id")
    return str(value) if value else None


def source_event_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Return chain-event content without the provider's mutable entity ID."""
    return {key: value for key, value in row.items() if key != "id"}


def v4_statics_complete(row: dict[str, Any]) -> bool:
    pool = row.get("pool") or {}
    return (
        pool.get("feeTier") is not None
        and pool.get("tickSpacing") is not None
        and pool.get("hooks") is not None
        and (pool.get("token0") or {}).get("decimals") is not None
        and (pool.get("token1") or {}).get("decimals") is not None
    )


V4_DYNAMIC_FEE_FLAG = 1 << 23
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def v4_quote_status(row: dict[str, Any]) -> str:
    """Why a v4 pool is or is not supported by vanilla concentrated-liquidity math."""
    if not v4_statics_complete(row):
        return "incomplete_statics"
    pool = row.get("pool") or {}
    try:
        fee = int(pool["feeTier"])
        tick_spacing = int(pool["tickSpacing"])
    except (KeyError, TypeError, ValueError):
        return "invalid_statics"
    hooks = str(pool.get("hooks") or "").lower()
    dynamic = bool(fee & V4_DYNAMIC_FEE_FLAG)
    hooked = hooks != ZERO_ADDRESS
    if dynamic and hooked:
        return "dynamic_fee_and_hooks"
    if dynamic:
        return "dynamic_fee"
    if hooked:
        return "hooks"
    if fee < 0 or fee >= 1_000_000 or tick_spacing <= 0:
        return "invalid_statics"
    return "vanilla_static_fee"


def v4_pool_quote_supported(row: dict[str, Any]) -> bool:
    return v4_quote_status(row) == "vanilla_static_fee"


def merge_v4_statics(row: dict[str, Any], auxiliary: dict[str, Any]) -> None:
    """Merge only immutable v4 pool statics, refusing any identity mismatch."""
    primary_pool = row.get("pool") or {}
    auxiliary_pool = auxiliary.get("pool") or {}
    identities = (
        (row.get("id"), auxiliary.get("id")),
        (primary_pool.get("id"), auxiliary_pool.get("id")),
        ((primary_pool.get("token0") or {}).get("id"), (auxiliary_pool.get("token0") or {}).get("id")),
        ((primary_pool.get("token1") or {}).get("id"), (auxiliary_pool.get("token1") or {}).get("id")),
    )
    if any(
        left is None or right is None or str(left).lower() != str(right).lower()
        for left, right in identities
    ):
        raise RuntimeError(f"v4 static identity mismatch for swap {row.get('id')}")
    primary_pool["feeTier"] = auxiliary_pool.get("feeTier")
    primary_pool["tickSpacing"] = auxiliary_pool.get("tickSpacing")
    primary_pool["hooks"] = auxiliary_pool.get("hooks")
    for token in ("token0", "token1"):
        primary_pool[token]["decimals"] = auxiliary_pool[token].get("decimals")
    if not v4_statics_complete(row):
        raise RuntimeError(f"v4 auxiliary statics incomplete for swap {row.get('id')}")


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
    meta_out = meta_path(source.name, day)
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
