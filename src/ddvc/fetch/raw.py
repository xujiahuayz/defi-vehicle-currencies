"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
sidecar. Only ingestion audits and the canonical node-D materialisers may parse
this layer. Empirical runners consume versioned canonical events, states, or
analysis-ready panels and never re-query providers.
"""

from __future__ import annotations

import calendar
from contextlib import ExitStack
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import DexSource, get_source
from ddvc.paths import DATA_DIR
from ddvc.provenance import portable_content_sha256
from ddvc.runtime import atomic_output, serialized_output_install, staged_output
from ddvc.source_records import block_value, block_values as _block_values


RAW_GRAPH_QUERY_CONTRACT_VERSION = 1
RAW_GRAPH_PAGE_SIZE = 1000
RAW_REFETCH_DIVERGENCE_SCHEMA_VERSION = 1
RAW_REFETCH_DIVERGENCE_ROOT = DATA_DIR / "raw" / "thegraph" / "_refetch_divergence"


class RawFetchInvariantError(RuntimeError):
    """A non-transient raw-fetch failure that retrying cannot repair."""


class RawRefetchDivergenceError(RawFetchInvariantError):
    """A refetch disagreed with an installed canonical capture."""


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
    start = midnight_ts(day)
    end = start + 86_400
    if entity.date_field:
        return {entity.date_field: str(start)}
    return {f"{entity.time_field}_gte": str(start), f"{entity.time_field}_lt": str(end)}


def where_chunks_for_entity(entity: EntitySpec, day: dt.date) -> list[dict[str, str]]:
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

    if entity.date_field:
        return "date_exact_hex_id_prefix_v1"
    if entity.stream == "hourly_reserves" and entity.time_field == "hourStartUnix":
        return "hour_exact_v1"
    if entity.stream == "swaps":
        return "hour_range_v1"
    return "day_range_v1"


def graph_query_contract_sha256(entity: EntitySpec) -> str:
    """Hash the complete canonical query shape that produced one raw stream."""

    payload = {
        "version": RAW_GRAPH_QUERY_CONTRACT_VERSION,
        "stream": entity.stream,
        "entity": entity.entity,
        "fields": " ".join(entity.fields.split()),
        "time_field": entity.time_field,
        "date_field": entity.date_field,
        "chunk_policy": query_chunk_policy(entity),
        "page_size": page_size_for_entity(entity),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def graph_query_contracts_for_source(source_name: str) -> dict[str, str]:
    """Return the canonical per-stream Graph query identities for one source."""

    source = get_source(source_name)
    return {
        entity.stream: graph_query_contract_sha256(entity)
        for entity in get_schema(source.schema).entities
    }


def _raw_stream_metadata_item_is_current(
    item: object,
    *,
    expected_path: Path | None = None,
    expected_query_contract: str | None = None,
    verify_content_hash: bool = False,
) -> bool:
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("rows"), int)
        or item["rows"] < 0
        or not item.get("path")
        or (
            expected_query_contract is not None
            and item.get("query_contract_sha256") != expected_query_contract
        )
    ):
        return False
    if expected_path is None:
        return not verify_content_hash
    recorded = Path(str(item["path"]))
    if raw_stream_identity(recorded) != raw_stream_identity(expected_path):
        return False
    if not verify_content_hash:
        return True
    recorded_hash = item.get("logical_content_sha256")
    recorded_head = item.get("head_block_at_fetch")
    recorded_time = item.get("fetched_at_utc")
    if not isinstance(recorded_hash, str) or len(recorded_hash) != 64 or isinstance(recorded_head, bool) or not isinstance(recorded_head, int) or recorded_head < 0 or not isinstance(recorded_time, str) or not recorded_time:
        return False
    try:
        return portable_content_sha256(expected_path) == recorded_hash
    except (OSError, EOFError):
        return False


def raw_stream_metadata_is_current(
    item: object,
    entity: EntitySpec,
    *,
    expected_path: Path | None = None,
) -> bool:
    """Require a checked ledger, portable path and exact query-shape identity."""

    return _raw_stream_metadata_item_is_current(
        item,
        expected_path=expected_path,
        expected_query_contract=graph_query_contract_sha256(entity),
    )


def indexed_metadata_streams(
    path: Path,
    *,
    expected_paths: dict[str, Path] | None = None,
    expected_query_contracts: dict[str, str] | None = None,
    verify_content_hashes: bool = False,
) -> set[str]:
    """Return streams whose sidecar ledger and optional query identity are current."""

    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    streams = payload.get("streams")
    if not isinstance(streams, dict):
        return set()
    indexed: set[str] = set()
    for name, item in streams.items():
        stream = str(name)
        expected = (expected_paths or {}).get(stream)
        expected_contract = (expected_query_contracts or {}).get(stream)
        if not _raw_stream_metadata_item_is_current(
            item,
            expected_path=expected,
            expected_query_contract=expected_contract,
            verify_content_hash=verify_content_hashes,
        ):
            continue
        indexed.add(stream)
    return indexed


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
        raise RawFetchInvariantError(
            "partial raw refresh cannot merge into legacy metadata without a stream ledger; "
            "refresh the canonical stream set together once"
        )


def read_source_day_metadata(source: DexSource, day: dt.date) -> dict[str, Any]:
    """Read and validate the canonical source/day identity before any provider call."""

    path = meta_path(source.name, day)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RawFetchInvariantError(f"raw metadata is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RawFetchInvariantError(f"raw metadata is not an object: {path}")
    expected = {"source": source.name, "day": day.isoformat()}
    conflicts = {key: (payload.get(key), value) for key, value in expected.items() if payload.get(key) not in (None, value)}
    if conflicts:
        raise RawFetchInvariantError(f"raw metadata identity conflicts at {path}: {conflicts}")
    return payload


def require_frozen_graph_head(source: DexSource, head: int | None) -> int:
    minimum = source.genesis_block or 0
    if head is None or isinstance(head, bool) or head < minimum:
        raise RuntimeError(f"Graph source did not expose a valid frozen head: {source.name}")
    return head


def frozen_graph_head(source: DexSource) -> int:
    """Resolve one immutable Graph snapshot for a complete source fetch run."""

    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    return require_frozen_graph_head(source, head_block(client))


def _evidence_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_DIR))
    except ValueError:
        return str(path)


def _install_immutable_evidence(source: Path, target: Path, expected_hash: str) -> None:
    """Install one content-addressed evidence file once and never replace it."""

    with serialized_output_install(target):
        if target.exists():
            if portable_content_sha256(target) != expected_hash:
                raise RawFetchInvariantError(f"content-addressed refetch evidence is corrupt: {target}")
            return
        with atomic_output(target) as temporary:
            shutil.copyfile(source, temporary)
        if portable_content_sha256(target) != expected_hash:
            raise RawFetchInvariantError(f"installed refetch evidence failed its content hash: {target}")


def preserve_refetch_divergence(
    *,
    source: DexSource,
    day: dt.date,
    entity: EntitySpec,
    canonical_path: Path,
    candidate_path: Path,
    canonical_hash: str,
    candidate_hash: str,
    head_block_at_fetch: int,
    fetched_at_utc: str,
    prior_stream_metadata: object,
    metadata_path: Path,
) -> Path:
    """Preserve both captures and an immutable comparison record without changing canonical state."""

    root = RAW_REFETCH_DIVERGENCE_ROOT / source.name / f"{day:%Y%m%d}" / entity.stream
    canonical_evidence = root / f"{canonical_hash}.jsonl.gz"
    candidate_evidence = root / f"{candidate_hash}.jsonl.gz"
    _install_immutable_evidence(canonical_path, canonical_evidence, canonical_hash)
    _install_immutable_evidence(candidate_path, candidate_evidence, candidate_hash)
    metadata_evidence: Path | None = None
    metadata_hash: str | None = None
    if metadata_path.exists():
        metadata_hash = portable_content_sha256(metadata_path)
        metadata_evidence = root / f"metadata-{metadata_hash}.json"
        _install_immutable_evidence(metadata_path, metadata_evidence, metadata_hash)
    record = {
        "schema_version": RAW_REFETCH_DIVERGENCE_SCHEMA_VERSION,
        "source": source.name,
        "day": day.isoformat(),
        "stream": entity.stream,
        "entity": entity.entity,
        "query_contract_sha256": graph_query_contract_sha256(entity),
        "head_block_at_fetch": head_block_at_fetch,
        "fetched_at_utc": fetched_at_utc,
        "canonical": {"logical_content_sha256": canonical_hash, "evidence_path": _evidence_relative_path(canonical_evidence), "stream_metadata": prior_stream_metadata},
        "candidate": {"logical_content_sha256": candidate_hash, "evidence_path": _evidence_relative_path(candidate_evidence)},
        "canonical_metadata": {"logical_content_sha256": metadata_hash, "evidence_path": _evidence_relative_path(metadata_evidence) if metadata_evidence is not None else None},
    }
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    record_hash = hashlib.sha256(payload).hexdigest()
    record_path = root / f"comparison-{record_hash}.json"
    with serialized_output_install(record_path):
        if record_path.exists():
            if record_path.read_bytes() != payload:
                raise RawFetchInvariantError(f"content-addressed refetch comparison is corrupt: {record_path}")
        else:
            with atomic_output(record_path) as temporary:
                temporary.write_bytes(payload)
    return record_path


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
        "path": raw_stream_identity(path),
        "status": "indexed_existing",
        "entity": entity.entity,
        "rows": rows,
        "min_block": min_block,
        "max_block": max_block,
        "logical_content_sha256": portable_content_sha256(path),
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
    meta_out = meta_path(source.name, day)
    existing = read_source_day_metadata(source, day)
    stream_meta: dict[str, dict[str, Any]] = {}
    existing_streams = existing.get("streams")
    for entity in selected:
        path = raw_path(source.name, entity.stream, day)
        if not path.is_file():
            raise FileNotFoundError(f"installed raw stream is missing: {path}")
        indexed = index_existing_stream(path, entity)
        prior = (
            existing_streams.get(entity.stream)
            if isinstance(existing_streams, dict)
            else None
        )
        if raw_stream_metadata_is_current(prior, entity, expected_path=path):
            indexed["query_contract_sha256"] = graph_query_contract_sha256(entity)
        else:
            indexed["status"] = "indexed_existing_unverified_query_contract"
        stream_meta[entity.stream] = indexed
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
    head_block_at_fetch: int | None = None,
) -> dict[str, Any]:
    schema = get_schema(source.schema)
    selected = [entity for entity in schema.entities if streams is None or entity.stream in streams]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}

    meta_out = meta_path(source.name, day)
    existing_meta = read_source_day_metadata(source, day)
    if streams is not None and meta_out.exists():
        require_mergeable_partial_metadata(
            existing_meta,
            requested_streams={entity.stream for entity in selected},
            canonical_streams={entity.stream for entity in schema.entities},
        )

    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    head = require_frozen_graph_head(source, head_block_at_fetch if head_block_at_fetch is not None else head_block(client))
    stream_meta: dict[str, dict[str, Any]] = {}
    existing_streams = existing_meta.get("streams")
    existing_streams = existing_streams if isinstance(existing_streams, dict) else {}
    staged: list[dict[str, Any]] = []
    with ExitStack() as stack:
        for entity in selected:
            out = raw_path(source.name, entity.stream, day)
            existing_stream = existing_streams.get(entity.stream)
            if skip_existing and out.exists() and raw_stream_metadata_is_current(existing_stream, entity, expected_path=out):
                stream_meta[entity.stream] = {"path": raw_stream_identity(out), "status": "skipped"}
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
                        block_number=head,
                    )
                )
            temporary = stack.enter_context(staged_output(out))
            _write_jsonl_gz_payload(temporary, rows)
            blocks = _block_values(rows)
            fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
            candidate_hash = portable_content_sha256(temporary, content_encoding="gzip")
            canonical_hash = portable_content_sha256(out) if out.exists() else None
            staged.append(
                {
                    "entity": entity,
                    "target": out,
                    "temporary": temporary,
                    "target_existed": out.exists(),
                    "canonical_hash": canonical_hash,
                    "candidate_hash": candidate_hash,
                    "metadata": {
                        "path": raw_stream_identity(out),
                        "status": "refetched_identical" if canonical_hash == candidate_hash else "fetched",
                        "entity": entity.entity,
                        "rows": len(rows),
                        "min_block": min(blocks) if blocks else None,
                        "max_block": max(blocks) if blocks else None,
                        "query_contract_sha256": graph_query_contract_sha256(entity),
                        "logical_content_sha256": candidate_hash,
                        "head_block_at_fetch": head,
                        "fetched_at_utc": fetched_at,
                    },
                }
            )

        divergent = [item for item in staged if item["target_existed"] and item["canonical_hash"] != item["candidate_hash"]]
        if divergent:
            records = [
                preserve_refetch_divergence(
                    source=source,
                    day=day,
                    entity=item["entity"],
                    canonical_path=item["target"],
                    candidate_path=item["temporary"],
                    canonical_hash=item["canonical_hash"],
                    candidate_hash=item["candidate_hash"],
                    head_block_at_fetch=head,
                    fetched_at_utc=item["metadata"]["fetched_at_utc"],
                    prior_stream_metadata=existing_streams.get(item["entity"].stream),
                    metadata_path=meta_out,
                )
                for item in divergent
            ]
            raise RawRefetchDivergenceError(f"refetch diverged from {len(records)} installed canonical stream(s) for {source.name} {day}; evidence: {records[0]}")

        for item in staged:
            stream_meta[item["entity"].stream] = item["metadata"]
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
        fresh = {
            "source": source.name,
            "schema": source.schema,
            "subgraph_id": source.subgraph_id,
            "graph_path": source.graph_path,
            "source_genesis_block": source.genesis_block,
            "source_genesis_date_utc": source.genesis_date_utc.isoformat(),
            "day": day.isoformat(),
            "head_block_at_fetch": head,
            "streams": stream_meta,
            "fetched_at_utc": fetched_at,
        }
        meta = merge_stream_metadata(existing_meta, fresh) if existing_meta else merge_stream_metadata({}, fresh)
        installed: list[Path] = []
        try:
            for item in staged:
                if not item["target_existed"]:
                    item["temporary"].replace(item["target"])
                    installed.append(item["target"])
            meta_out.parent.mkdir(parents=True, exist_ok=True)
            write_json(meta_out, meta)
        except BaseException:
            for path in installed:
                path.unlink(missing_ok=True)
            raise
        return meta


def stream_names_for_source(source_name: str) -> list[str]:
    source = get_source(source_name)
    return [entity.stream for entity in get_schema(source.schema).entities]
