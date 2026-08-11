"""Raw market-data fetch orchestration.

The fetcher writes source responses verbatim to gzipped JSONL and a small metadata
sidecar. Only ingestion audits and the canonical node-D materialisers may parse
this layer. Empirical runners consume versioned canonical events, states, or
analysis-ready panels and never re-query providers.
"""

from __future__ import annotations

import calendar
from contextlib import ExitStack, contextmanager
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any, Callable

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
RAW_SOURCE_DAY_PROMOTION_SCHEMA_VERSION = 1
RAW_REFETCH_DIVERGENCE_ROOT = DATA_DIR / "raw" / "thegraph" / "_refetch_divergence"


class RawFetchInvariantError(RuntimeError):
    """A non-transient raw-fetch failure that retrying cannot repair."""


class RawRefetchDivergenceError(RawFetchInvariantError):
    """A refetch disagreed with an installed canonical capture."""


def source_day_promotion_record(
    source_name: str,
    day: dt.date,
    stream_hashes: Mapping[str, str],
) -> dict[str, object]:
    """Build the deterministic record binding every stream in one promoted day."""

    if not stream_hashes or any(
        not isinstance(digest, str) or len(digest) != 64
        for digest in stream_hashes.values()
    ):
        raise RawFetchInvariantError("source-day promotion stream perimeter is invalid")
    contract = {
        "schema_version": RAW_SOURCE_DAY_PROMOTION_SCHEMA_VERSION,
        "source": source_name,
        "day": day.isoformat(),
        "streams": dict(sorted(stream_hashes.items())),
    }
    promotion_id = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "policy": "raw-source-day-promotion-v1",
        "promotion_id": promotion_id,
        "contract": contract,
    }


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
    """Resolve one provider partition and its source-day commit record."""

    backend = "dune" if get_source(source_name).backend == "dune" else "thegraph"
    directory = data_root / "raw" / backend / source_name
    return (
        directory / f"{source_name}_{stream}_{day:%Y%m%d}.jsonl.gz",
        directory / f"{source_name}_meta_{day:%Y%m%d}.json",
    )


def require_committed_source_day_stream(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
) -> Path:
    """Reject a missing or torn raw/source-day pair before canonical consumption."""

    path, marker_path = installed_source_day_paths(
        source_name, stream, day, data_root=data_root
    )
    return require_committed_source_day_path(
        path,
        marker_path,
        source_name=source_name,
        stream=stream,
        day=day,
    )


def require_committed_source_day_path(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
) -> Path:
    """Validate an explicitly resolved raw path against its source-day commit record."""

    expected_hash = _required_source_day_stream_hash(
        path,
        marker_path,
        source_name=source_name,
        stream=stream,
        day=day,
    )
    if portable_content_sha256(path) != expected_hash:
        raise RawFetchInvariantError(
            f"raw source-day payload disagrees with its commit record: {source_name}/{stream}/{day:%Y%m%d}"
        )
    return path


def _required_source_day_stream_hash(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
) -> str:
    """Validate source-day marker identity and return its committed logical hash."""

    if not path.is_file() or not marker_path.is_file():
        raise RawFetchInvariantError(
            f"raw source-day is uncommitted: {source_name}/{stream}/{day:%Y%m%d}"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RawFetchInvariantError(f"raw source-day marker is unreadable: {marker_path}") from exc
    streams = marker.get("streams") if isinstance(marker, dict) else None
    stream_marker = streams.get(stream) if isinstance(streams, dict) else None
    expected_day = day.isoformat()
    if (
        not isinstance(marker, dict)
        or marker.get("source") != source_name
        or marker.get("day") != expected_day
        or not isinstance(stream_marker, dict)
    ):
        raise RawFetchInvariantError(
            f"raw source-day marker perimeter mismatch: {source_name}/{stream}/{day:%Y%m%d}"
        )
    expected_hash = stream_marker.get("logical_content_sha256")
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != 64
    ):
        raise RawFetchInvariantError(
            f"raw source-day payload disagrees with its commit record: {source_name}/{stream}/{day:%Y%m%d}"
        )
    return expected_hash


def committed_source_day_generation_identity(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
) -> str:
    """Bind one promoted source-day payload to its exact query generation."""

    path, marker_path = installed_source_day_paths(
        source_name, stream, day, data_root=data_root
    )
    logical_content_sha256 = _required_source_day_stream_hash(
        path,
        marker_path,
        source_name=source_name,
        stream=stream,
        day=day,
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    stream_marker = marker["streams"][stream]
    promotion = marker.get("promotion")
    marker_streams = marker["streams"]
    stream_hashes = {
        name: item.get("logical_content_sha256")
        for name, item in marker_streams.items()
        if isinstance(item, dict)
    }
    try:
        expected_promotion = source_day_promotion_record(
            source_name, day, stream_hashes
        )
    except RawFetchInvariantError:
        expected_promotion = None
    legacy_exact_promotion = (
        {
            "policy": "raw-source-day-promotion-v1",
            "promotion_id": expected_promotion["promotion_id"],
        }
        if expected_promotion is not None
        else None
    )
    if (
        expected_promotion is None
        or promotion not in (expected_promotion, legacy_exact_promotion)
        or stream_marker.get("path") != raw_stream_identity(path)
        or stream_hashes.get(stream) != logical_content_sha256
    ):
        raise RawFetchInvariantError(
            f"raw source-day lacks a committed promotion identity: "
            f"{source_name}/{stream}/{day:%Y%m%d}"
        )
    source = get_source(source_name)
    if source.backend == "thegraph":
        entity = next(
            entity
            for entity in get_schema(source.schema).entities
            if entity.stream == stream
        )
        expected_query_contract = graph_query_contract_sha256(entity)
        head_block = stream_marker.get(
            "head_block_at_fetch", marker.get("head_block_at_fetch")
        )
        if (
            stream_marker.get("query_contract_sha256") != expected_query_contract
            or isinstance(head_block, bool)
            or not isinstance(head_block, int)
            or head_block < 0
        ):
            raise RawFetchInvariantError(
                f"raw source-day lacks current frozen query provenance: "
                f"{source_name}/{stream}/{day:%Y%m%d}"
            )
        query_generation: dict[str, object] = {
            "query_contract_sha256": expected_query_contract,
            "head_block_at_fetch": head_block,
        }
    else:
        from ddvc.fetch.dune import validated_dune_query_window

        try:
            query_start, query_end = validated_dune_query_window(
                source, day, stream_marker
            )
        except ValueError as exc:
            raise RawFetchInvariantError(
                f"raw source-day lacks current Dune query provenance: "
                f"{source_name}/{stream}/{day:%Y%m%d}: {exc}"
            ) from exc
        query_generation = {
            "query_contract_sha256": stream_marker["query_contract_sha256"],
            "query_start_date": query_start.isoformat(),
            "query_end_date_exclusive": query_end.isoformat(),
        }
    identity = {
        "authority": "promoted-source-day-v1",
        "source": source_name,
        "stream": stream,
        "day": day.isoformat(),
        "logical_content_sha256": logical_content_sha256,
        "promotion": promotion,
        "query_generation": query_generation,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@contextmanager
def verified_jsonl_gz_content_rows(
    path: Path,
    expected_logical_sha256: str,
    *,
    authority_label: str,
):
    """Parse gzip JSONL once and verify an authority-bound logical hash at EOF."""

    if (
        not isinstance(expected_logical_sha256, str)
        or len(expected_logical_sha256) != 64
    ):
        raise RawFetchInvariantError(
            f"raw stream authority lacks a logical content hash: {authority_label}"
        )
    exhausted = False

    def rows():
        nonlocal exhausted
        digest = hashlib.sha256()
        with gzip.open(path, "rb") as handle:
            for raw_line in handle:
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RawFetchInvariantError(
                        f"committed raw JSONL is malformed: {path}"
                    ) from exc
                if not isinstance(row, dict):
                    raise RawFetchInvariantError(
                        f"committed raw JSONL row is not an object: {path}"
                    )
                yield row
        if digest.hexdigest() != expected_logical_sha256:
            raise RawFetchInvariantError(
                f"raw source-day payload disagrees with its commit record or certified authority: {authority_label}"
            )
        exhausted = True

    iterator = rows()
    try:
        yield iterator
    except BaseException:
        iterator.close()
        raise
    else:
        if not exhausted:
            iterator.close()
            raise RawFetchInvariantError(
                f"committed raw stream was not exhausted: {authority_label}"
            )


@contextmanager
def verified_jsonl_gz_rows(
    path: Path,
    marker_path: Path,
    *,
    source_name: str,
    stream: str,
    day: dt.date,
):
    """Parse a promoted gzip JSONL stream once and verify its logical hash at EOF."""

    expected_hash = _required_source_day_stream_hash(
        path,
        marker_path,
        source_name=source_name,
        stream=stream,
        day=day,
    )
    with verified_jsonl_gz_content_rows(
        path,
        expected_hash,
        authority_label=f"{source_name}/{stream}/{day:%Y%m%d}",
    ) as rows:
        yield rows


@contextmanager
def verified_source_day_rows(
    source_name: str,
    stream: str,
    day: dt.date,
    *,
    data_root: Path = DATA_DIR,
    expected_generation_identity: str | None = None,
):
    """Single-pass one promoted or locally certified canonical source-day stream."""

    from ddvc.raw_certification import raw_partition_read_authority

    stamp = day.strftime("%Y%m%d")
    before = raw_partition_read_authority(
        source_name, stream, stamp, data_root=data_root
    )
    actual_identity = str(before["generation_identity_sha256"])
    if (
        expected_generation_identity is not None
        and actual_identity != expected_generation_identity
    ):
        raise RawFetchInvariantError(
            f"raw partition authority changed before read: {source_name}/{stream}/{stamp}"
        )
    label = f"{source_name}/{stream}/{stamp} via {before['authority_kind']}"
    with verified_jsonl_gz_content_rows(
        Path(before["path"]),
        str(before["logical_content_sha256"]),
        authority_label=label,
    ) as rows:
        yield rows
    after = raw_partition_read_authority(
        source_name, stream, stamp, data_root=data_root
    )
    if after != before:
        raise RawFetchInvariantError(
            f"raw partition authority changed during read: {source_name}/{stream}/{stamp}"
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


def read_source_day_metadata(
    source: DexSource, day: dt.date, *, data_root: Path = DATA_DIR
) -> dict[str, Any]:
    """Read and validate the canonical source/day identity before any provider call."""

    path = meta_path(source.name, day, data_root=data_root)
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
    data_root: Path = DATA_DIR,
) -> Path:
    """Preserve both captures and an immutable comparison record without changing canonical state."""

    root = (
        (RAW_REFETCH_DIVERGENCE_ROOT if data_root == DATA_DIR else data_root / "raw" / "thegraph" / "_refetch_divergence")
        / source.name
        / f"{day:%Y%m%d}"
        / entity.stream
    )
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


def _promote_source_day_unlocked(
    source_name: str,
    day: dt.date,
    streams: set[str],
    *,
    candidate_root: Path,
    evidence_root: Path,
    data_root: Path = DATA_DIR,
    after_raw_install: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Crash-safely promote verified candidate streams and commit the source-day marker last."""

    if not streams:
        raise ValueError("source-day promotion requires at least one stream")
    source = get_source(source_name)
    available = (
        {"swaps", "daily"}
        if source.backend == "dune"
        else {entity.stream for entity in get_schema(source.schema).entities}
    )
    if unknown := sorted(streams.difference(available)):
        raise ValueError(f"source-day promotion names unavailable streams: {unknown}")
    candidate_marker_path: Path | None = None
    candidates: dict[str, tuple[Path, str]] = {}
    for stream in sorted(streams):
        candidate_path = require_committed_source_day_stream(
            source_name,
            stream,
            day,
            data_root=candidate_root,
        )
        _candidate_path, observed_marker = installed_source_day_paths(
            source_name,
            stream,
            day,
            data_root=candidate_root,
        )
        candidate_marker_path = candidate_marker_path or observed_marker
        if observed_marker != candidate_marker_path:
            raise RawFetchInvariantError("candidate streams do not share one source-day marker")
        candidates[stream] = (candidate_path, portable_content_sha256(candidate_path))
    if candidate_marker_path is None:
        raise AssertionError("candidate source-day marker was not resolved")
    candidate_marker = json.loads(candidate_marker_path.read_text(encoding="utf-8"))
    candidate_streams = candidate_marker.get("streams") or {}
    for stream in sorted(streams):
        stream_marker = candidate_streams.get(stream)
        if not isinstance(stream_marker, dict):
            raise RawFetchInvariantError(f"candidate source-day marker omits {stream}")
        if source.backend == "thegraph":
            entity = next(
                entity
                for entity in get_schema(source.schema).entities
                if entity.stream == stream
            )
            expected_query = graph_query_contract_sha256(entity)
            head = stream_marker.get(
                "head_block_at_fetch", candidate_marker.get("head_block_at_fetch")
            )
            if (
                stream_marker.get("query_contract_sha256") != expected_query
                or isinstance(head, bool)
                or not isinstance(head, int)
                or head < 0
            ):
                raise RawFetchInvariantError(
                    f"candidate stream lacks current frozen query provenance: {source_name}/{stream}/{day:%Y%m%d}"
                )
        else:
            from ddvc.fetch.dune import validated_dune_query_window

            try:
                validated_dune_query_window(source, day, stream_marker)
            except ValueError as error:
                raise RawFetchInvariantError(
                    f"candidate Dune stream lacks current query provenance: {source_name}/{stream}/{day:%Y%m%d}: {error}"
                ) from error
    from ddvc.raw_certification import RawPartition, scan_installed_generation

    candidate_partitions = [
        RawPartition(source_name, stream, f"{day:%Y%m%d}")
        for stream in sorted(streams)
    ]
    candidate_scan = scan_installed_generation(
        candidate_root,
        evidence_root / ".promotion-scan-cache",
        workers=1,
        partitions=candidate_partitions,
    )
    candidate_failures = [
        row for row in candidate_scan if row.get("local_pass") is not True
    ]
    if candidate_failures:
        first = candidate_failures[0]
        raise RawFetchInvariantError(
            f"candidate stream fails the consumer contract: {first['source']}/{first['stream']}/{first['day']} errors={first.get('errors')}"
        )
    destination_marker_path: Path | None = None
    destinations: dict[str, Path] = {}
    for stream in sorted(streams):
        destination_path, observed_marker = installed_source_day_paths(
            source_name,
            stream,
            day,
            data_root=data_root,
        )
        destination_marker_path = destination_marker_path or observed_marker
        if observed_marker != destination_marker_path:
            raise RawFetchInvariantError("canonical streams do not share one source-day marker")
        destinations[stream] = destination_path
    if destination_marker_path is None:
        raise AssertionError("canonical source-day marker was not resolved")
    if destination_marker_path.is_file():
        try:
            installed_marker = json.loads(destination_marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RawFetchInvariantError(
                f"canonical source-day marker is unreadable: {destination_marker_path}"
            ) from exc
        if not isinstance(installed_marker, dict):
            raise RawFetchInvariantError(
                f"canonical source-day marker is not an object: {destination_marker_path}"
            )
    else:
        installed_marker = {
            "source": source_name,
            "day": day.isoformat(),
            "streams": {},
        }
    installed_streams = installed_marker.get("streams")
    if not isinstance(installed_streams, dict):
        raise RawFetchInvariantError(
            f"canonical source-day marker streams are invalid: {destination_marker_path}"
        )
    resulting_hashes: dict[str, str] = {}
    for retained_stream, retained_marker in sorted(installed_streams.items()):
        if retained_stream in candidates:
            continue
        if not isinstance(retained_marker, dict):
            raise RawFetchInvariantError(
                f"canonical source-day marker stream is invalid: {source_name}/{retained_stream}/{day:%Y%m%d}"
            )
        require_committed_source_day_stream(
            source_name, retained_stream, day, data_root=data_root
        )
        retained_hash = retained_marker.get("logical_content_sha256")
        if not isinstance(retained_hash, str) or len(retained_hash) != 64:
            raise RawFetchInvariantError(
                f"canonical source-day marker stream lacks content identity: {source_name}/{retained_stream}/{day:%Y%m%d}"
            )
        resulting_hashes[retained_stream] = retained_hash
    resulting_hashes.update(
        {
            stream: digest
            for stream, (_path, digest) in sorted(candidates.items())
        }
    )
    promotion = source_day_promotion_record(source_name, day, resulting_hashes)
    promotion_contract = promotion["contract"]
    promotion_id = str(promotion["promotion_id"])
    day_evidence = evidence_root / source_name / f"{day:%Y%m%d}" / promotion_id
    prepared_path = day_evidence / "promotion-prepared.json"
    if installed_marker.get("promotion") == promotion:
        for stream in resulting_hashes:
            committed_source_day_generation_identity(
                source_name, stream, day, data_root=data_root
            )
        return {
            **promotion_contract,
            "promotion_id": promotion_id,
            "status": "already_committed",
        }
    if prepared_path.is_file():
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        if prepared.get("promotion_contract") != promotion_contract:
            raise RawFetchInvariantError("prepared promotion contract changed")
    else:
        retained: list[dict[str, object]] = []
        for stream, destination in sorted(destinations.items()):
            legacy_missing = not destination.is_file()
            legacy_hash = (
                None if legacy_missing else portable_content_sha256(destination)
            )
            legacy_evidence = (
                None
                if legacy_missing
                else day_evidence / stream / f"legacy-{legacy_hash}.jsonl.gz"
            )
            candidate_path, candidate_hash = candidates[stream]
            candidate_evidence = day_evidence / stream / f"candidate-{candidate_hash}.jsonl.gz"
            if legacy_evidence is not None and legacy_hash is not None:
                _install_immutable_evidence(
                    destination, legacy_evidence, legacy_hash
                )
            _install_immutable_evidence(candidate_path, candidate_evidence, candidate_hash)
            retained.append(
                {
                    "stream": stream,
                    "legacy_missing": legacy_missing,
                    "legacy_sha256": legacy_hash,
                    "legacy_evidence": (
                        str(legacy_evidence.relative_to(evidence_root))
                        if legacy_evidence is not None
                        else None
                    ),
                    "candidate_sha256": candidate_hash,
                    "candidate_evidence": str(candidate_evidence.relative_to(evidence_root)),
                }
            )
        marker_hash = portable_content_sha256(destination_marker_path) if destination_marker_path.is_file() else None
        marker_evidence = None
        if marker_hash is not None:
            marker_evidence = day_evidence / f"legacy-marker-{marker_hash}.json"
            _install_immutable_evidence(
                destination_marker_path, marker_evidence, marker_hash
            )
        prepared = {
            "policy": "raw-source-day-promotion-prepared-v1",
            "promotion_contract": promotion_contract,
            "retained_streams": retained,
            "legacy_marker_sha256": marker_hash,
            "legacy_marker_evidence": (
                str(marker_evidence.relative_to(evidence_root))
                if marker_evidence is not None
                else None
            ),
        }
        write_json(prepared_path, prepared)
    retained_by_stream = {
        item["stream"]: item for item in prepared.get("retained_streams") or []
    }
    if set(retained_by_stream) != streams:
        raise RawFetchInvariantError("prepared promotion evidence perimeter changed")
    new_marker = dict(installed_marker)
    new_marker.update(
        {
            "source": source_name,
            "day": day.isoformat(),
            "streams": dict(installed_marker.get("streams") or {}),
        }
    )
    for stream, (candidate_path, candidate_hash) in sorted(candidates.items()):
        candidate_stream_marker = candidate_streams.get(stream)
        if not isinstance(candidate_stream_marker, dict):
            raise RawFetchInvariantError(f"candidate source-day marker omits {stream}")
        candidate_stream_marker = dict(candidate_stream_marker)
        candidate_stream_marker["path"] = raw_stream_identity(destinations[stream])
        candidate_stream_marker["logical_content_sha256"] = candidate_hash
        new_marker["streams"][stream] = candidate_stream_marker
        retained = retained_by_stream[stream]
        destination_hash = (
            portable_content_sha256(destinations[stream])
            if destinations[stream].is_file()
            else None
        )
        if destination_hash != candidate_hash:
            expected_legacy = retained.get("legacy_sha256")
            if destination_hash != expected_legacy or bool(
                retained.get("legacy_missing")
            ) != (destination_hash is None):
                raise RawFetchInvariantError(
                    f"canonical source-day changed outside promotion: {source_name}/{stream}/{day:%Y%m%d}"
                )
            with atomic_output(destinations[stream]) as temporary:
                shutil.copyfile(candidate_path, temporary)
            if portable_content_sha256(destinations[stream]) != candidate_hash:
                raise RawFetchInvariantError(f"promoted raw stream failed its hash: {destinations[stream]}")
            if after_raw_install is not None:
                after_raw_install(destinations[stream])
    new_marker["promotion"] = promotion
    write_json(destination_marker_path, new_marker)
    for stream in streams:
        require_committed_source_day_stream(
            source_name, stream, day, data_root=data_root
        )
    return {**promotion_contract, "promotion_id": promotion_id, "status": "committed"}


def promote_source_day(
    source_name: str,
    day: dt.date,
    streams: set[str],
    *,
    candidate_root: Path,
    evidence_root: Path,
    data_root: Path = DATA_DIR,
    after_raw_install: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Serialize one source-day promotion so concurrent stream sets cannot lose marker state."""

    _path, marker_path = installed_source_day_paths(
        source_name,
        next(iter(sorted(streams)), "swaps"),
        day,
        data_root=data_root,
    )
    with serialized_output_install(marker_path):
        return _promote_source_day_unlocked(
            source_name,
            day,
            streams,
            candidate_root=candidate_root,
            evidence_root=evidence_root,
            data_root=data_root,
            after_raw_install=after_raw_install,
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
    data_root: Path = DATA_DIR,
) -> dict[str, Any]:
    """Index installed streams and merge them into one source-day sidecar."""

    schema = get_schema(source.schema)
    selected = [entity for entity in schema.entities if streams is None or entity.stream in streams]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}
    meta_out = meta_path(source.name, day, data_root=data_root)
    existing = read_source_day_metadata(source, day, data_root=data_root)
    stream_meta: dict[str, dict[str, Any]] = {}
    existing_streams = existing.get("streams")
    for entity in selected:
        path = _raw_path_at(source.name, entity.stream, day, data_root)
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
    data_root: Path = DATA_DIR,
    max_pages_per_chunk: int = 10_000,
    max_transient_retries: int = 4,
) -> dict[str, Any]:
    schema = get_schema(source.schema)
    selected = [entity for entity in schema.entities if streams is None or entity.stream in streams]
    if not selected:
        return {"source": source.name, "day": day.isoformat(), "streams": {}}

    meta_out = meta_path(source.name, day, data_root=data_root)
    existing_meta = read_source_day_metadata(source, day, data_root=data_root)
    if streams is not None and meta_out.exists():
        require_mergeable_partial_metadata(
            existing_meta,
            requested_streams={entity.stream for entity in selected},
            canonical_streams={entity.stream for entity in schema.entities},
        )

    client = GraphClient(
        source.subgraph_id,
        graph_keys(),
        graph_path=source.graph_path,
        max_transient_retries=max_transient_retries,
    )
    head = require_frozen_graph_head(source, head_block_at_fetch if head_block_at_fetch is not None else head_block(client))
    stream_meta: dict[str, dict[str, Any]] = {}
    existing_streams = existing_meta.get("streams")
    existing_streams = existing_streams if isinstance(existing_streams, dict) else {}
    staged: list[dict[str, Any]] = []
    with ExitStack() as stack:
        for entity in selected:
            out = _raw_path_at(source.name, entity.stream, day, data_root)
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
                        max_pages=max_pages_per_chunk,
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
                    data_root=data_root,
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
