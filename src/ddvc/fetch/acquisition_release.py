"""Frozen, quality-gated Graph acquisition staging and release."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

from ddvc.artifact_release import file_sha256, publish_artifact_release, resolve_artifact_release
from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import research_sample_end_unix, vector_alignment_failures
from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.graphql_selection import selected_paths
from ddvc.fetch.raw import graph_query_contract_sha256, iter_graph_entity_rows, where_chunks_for_entity
from ddvc.fetch.schemas import EntitySpec, acquisition_schema
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.runtime import atomic_output, bounded_workers, interruptible_thread_pool, serialized_output_install, staged_output


GRAPH_ACQUISITION_RELEASE_KIND = "graph_acquisition_generation"
GRAPH_ACQUISITION_RELEASE_SCHEMA_VERSION = 1
GRAPH_ACQUISITION_RELEASE_FILENAMES = {"manifest": "manifest.json"}


@dataclass(frozen=True)
class AcquisitionTask:
    source: str
    entity: EntitySpec
    sample_end_block: int
    provider_head_block: int
    vector_owners: tuple[dict[str, str], ...]
    quality_action: str = "admit"


def _manifest_vector_owners(active: Mapping[str, Any], new: Mapping[str, Any]) -> dict[tuple[str, str], tuple[dict[str, str], ...]]:
    owners: dict[tuple[str, str], tuple[dict[str, str], ...]] = {}
    for manifest in (active, new):
        for source in manifest["sources"]:
            for record in source.get("entities", []):
                stream = str(record.get("stream") or record["entity"])
                owners[(str(source["source"]), stream)] = tuple(record.get("vector_owners") or ())
    return owners


def acquisition_tasks(
    *,
    active_manifest: Path,
    new_manifest: Path,
    sample_end_blocks: Mapping[str, int],
    provider_head_blocks: Mapping[str, int] | None = None,
    canary_path: Path | None = None,
) -> tuple[AcquisitionTask, ...]:
    """Materialize exactly one task for every frozen source/stream contract."""

    active = json.loads(active_manifest.read_text(encoding="utf-8"))
    new = json.loads(new_manifest.read_text(encoding="utf-8"))
    owners = _manifest_vector_owners(active, new)
    quality_actions: dict[tuple[str, str], str] = {}
    if canary_path is not None:
        canary = json.loads(canary_path.read_text(encoding="utf-8"))
        quality_actions = {
            (str(source["source"]), str(stream["stream"])): str(stream.get("quality_action") or "unresolved_query_failure")
            for source in canary.get("sources", [])
            for stream in source.get("streams", [])
        }
    tasks = []
    for source in sorted(sample_end_blocks):
        schema = acquisition_schema(
            source,
            active_manifest=active_manifest,
            new_manifest=new_manifest,
        )
        tasks.extend(
            AcquisitionTask(
                source=source,
                entity=entity,
                sample_end_block=int(sample_end_blocks[source]),
                provider_head_block=int((provider_head_blocks or sample_end_blocks)[source]),
                vector_owners=owners.get((source, entity.stream), ()),
                quality_action=quality_actions.get((source, entity.stream), "admit"),
            )
            for entity in schema.entities
        )
    identities = [(task.source, task.entity.stream) for task in tasks]
    if len(identities) != len(set(identities)):
        raise ValueError("Graph acquisition task perimeter contains duplicate streams")
    return tuple(tasks)


def acquisition_cutoff(task: AcquisitionTask) -> tuple[dict[str, Any], int]:
    """Return a sample-end where clause and block pin for a non-day task."""

    entity = task.entity
    direct = {path for path in selected_paths(entity.fields) if "." not in path}
    if entity.fetch_mode == "block_pinned_configuration":
        return {}, task.sample_end_block
    if entity.date_field and entity.date_field in direct:
        return {f"{entity.date_field}_lte": str(research_sample_end_unix())}, task.provider_head_block
    if entity.time_field in direct:
        return {f"{entity.time_field}_lte": str(research_sample_end_unix())}, task.provider_head_block
    for field in ("blockNumber", "block", "createdAtBlockNumber", "createdBlockNumber"):
        if field in direct:
            return {f"{field}_lte": str(task.sample_end_block)}, task.provider_head_block
    return {}, task.sample_end_block


def _days_for_task(task: AcquisitionTask) -> Iterable[dt.date]:
    end = dt.datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date()
    day = DEX_SOURCES[task.source].genesis
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def _jsonl_line(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_task_payloads(
    task: AcquisitionTask,
    *,
    clean_path: Path,
    quarantine_path: Path,
    max_pages_per_chunk: int,
) -> dict[str, int]:
    source = DEX_SOURCES[task.source]
    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    clean_rows = 0
    quarantine_rows = 0
    with clean_path.open("wb") as clean_raw, quarantine_path.open("wb") as quarantine_raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=clean_raw, mtime=0) as clean, gzip.GzipFile(filename="", mode="wb", fileobj=quarantine_raw, mtime=0) as quarantine:
            if task.entity.fetch_mode == "head_validation_only":
                return {"clean_rows": 0, "quarantine_rows": 0}
            if task.entity.fetch_mode == "day_partitioned":
                chunks = (
                    where
                    for day in _days_for_task(task)
                    for where in where_chunks_for_entity(task.entity, day)
                )
            else:
                where, _ = acquisition_cutoff(task)
                chunks = iter((where,))
            _, query_block = acquisition_cutoff(task)
            for where in chunks:
                rows = iter_graph_entity_rows(
                    client,
                    task.entity,
                    where_chunks=(where,),
                    block_number=query_block,
                    max_pages_per_chunk=max_pages_per_chunk,
                )
                for row in rows:
                    failures = vector_alignment_failures(row, list(task.vector_owners))
                    if failures:
                        quarantine.write(
                            _jsonl_line(
                                {
                                    "row": row,
                                    "alignment_failures": failures,
                                    "source": task.source,
                                    "stream": task.entity.stream,
                                }
                            )
                        )
                        quarantine_rows += 1
                    else:
                        clean.write(_jsonl_line(row))
                        clean_rows += 1
    return {"clean_rows": clean_rows, "quarantine_rows": quarantine_rows}


def _install_content_addressed(source: Path, root: Path) -> Path:
    digest = file_sha256(source)
    target = root / f"{digest}{''.join(source.suffixes)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with serialized_output_install(target):
        if target.is_file():
            if file_sha256(target) != digest:
                raise RuntimeError(f"immutable Graph acquisition payload is corrupt: {target}")
        else:
            with atomic_output(target) as temporary:
                shutil.copyfile(source, temporary)
        if file_sha256(target) != digest:
            raise RuntimeError(f"Graph acquisition payload failed install verification: {target}")
    return target


def _validate_generation_manifest(path: Path, *, release_root: Path | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("kind") != "graph_acquisition_payload_manifest":
        raise ValueError("invalid Graph acquisition payload manifest")
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ValueError("Graph acquisition payload manifest has no selected streams")
    if not isinstance(payload.get("selection_reason"), str) or not str(payload["selection_reason"]).strip():
        raise ValueError("Graph acquisition payload manifest lacks its materiality reason")
    for record in streams:
        if record.get("status") in {"canary_only_never_backfill", "provider_archive_unavailable_quarantined"}:
            continue
        for label in ("payload", "quarantine"):
            item = record.get(label)
            recorded = Path(str(item.get("path"))) if isinstance(item, dict) else Path()
            if recorded.is_absolute() or ".." in recorded.parts:
                raise ValueError(f"Graph acquisition {label} path is not portable")
            payload_path = (release_root or path.parents[2]) / recorded
            if not payload_path.is_file() or file_sha256(payload_path) != item.get("sha256"):
                raise ValueError(f"Graph acquisition {label} changed: {record.get('source')}/{record.get('stream')}")
    return payload


def publish_graph_acquisition(
    *,
    pointer_path: Path,
    tasks: tuple[AcquisitionTask, ...],
    inputs: list[Path],
    code_sources: list[str],
    selection_reason: str,
    max_pages_per_chunk: int = 10_000,
    workers: int = 5,
) -> None:
    """Stage selected streams, install immutable payloads, then publish one marker last."""

    if not tasks:
        raise ValueError("Graph acquisition requires at least one selected task")
    if not selection_reason.strip():
        raise ValueError("Graph acquisition requires a named materiality reason")
    identities = [(task.source, task.entity.stream) for task in tasks]
    if len(identities) != len(set(identities)):
        raise ValueError("selected Graph acquisition contains duplicate streams")
    payload_root = pointer_path.parent / "payloads"

    def stage(task: AcquisitionTask) -> dict[str, Any]:
        if task.entity.fetch_mode == "head_validation_only" or task.quality_action == "provider_archive_unavailable_quarantined":
            return {
                "source": task.source,
                "stream": task.entity.stream,
                "status": (
                    "canary_only_never_backfill"
                    if task.entity.fetch_mode == "head_validation_only"
                    else "provider_archive_unavailable_quarantined"
                ),
                "query_contract_sha256": graph_query_contract_sha256(task.entity),
            }
        with staged_output(payload_root / "candidate.jsonl.gz") as clean, staged_output(payload_root / "candidate-quarantine.jsonl.gz") as quarantine:
            counts = _write_task_payloads(
                task,
                clean_path=clean,
                quarantine_path=quarantine,
                max_pages_per_chunk=max_pages_per_chunk,
            )
            clean_target = _install_content_addressed(clean, payload_root / task.source / task.entity.stream / "clean")
            quarantine_target = _install_content_addressed(quarantine, payload_root / task.source / task.entity.stream / "quarantine")
            return {
                "source": task.source,
                "stream": task.entity.stream,
                "status": "staged",
                "fetch_mode": task.entity.fetch_mode,
                "sample_end_block": task.sample_end_block,
                "provider_head_block": task.provider_head_block,
                "query_contract_sha256": graph_query_contract_sha256(task.entity),
                "payload": {"path": str(clean_target.relative_to(pointer_path.parent)), "sha256": file_sha256(clean_target), "rows": counts["clean_rows"]},
                "quarantine": {"path": str(quarantine_target.relative_to(pointer_path.parent)), "sha256": file_sha256(quarantine_target), "rows": counts["quarantine_rows"]},
            }

    with interruptible_thread_pool(max_workers=bounded_workers(workers)) as executor:
        records = list(executor.map(stage, tasks))
    manifest = {
        "schema_version": 1,
        "kind": "graph_acquisition_payload_manifest",
        "research_sample_end": RESEARCH_SAMPLE_END,
        "selection_reason": selection_reason,
        "streams": records,
    }

    def write_manifest(path: Path) -> None:
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    publish_artifact_release(
        pointer_path=pointer_path,
        kind=GRAPH_ACQUISITION_RELEASE_KIND,
        schema_version=GRAPH_ACQUISITION_RELEASE_SCHEMA_VERSION,
        filenames=GRAPH_ACQUISITION_RELEASE_FILENAMES,
        writers={"manifest": write_manifest},
        row_counts={"manifest": len(records)},
        code_sources=code_sources,
        inputs=inputs,
        notes="consumer-selected Graph acquisition; clean rows released only after row-level vector quarantine",
        validate_staged=lambda paths: _validate_generation_manifest(paths["manifest"], release_root=pointer_path.parent),
    )


def resolve_graph_acquisition(pointer_path: Path) -> dict[str, Any]:
    """Resolve the marker and revalidate every immutable clean/quarantine payload."""

    release = resolve_artifact_release(
        pointer_path,
        kind=GRAPH_ACQUISITION_RELEASE_KIND,
        schema_version=GRAPH_ACQUISITION_RELEASE_SCHEMA_VERSION,
        filenames=GRAPH_ACQUISITION_RELEASE_FILENAMES,
    )
    return _validate_generation_manifest(release.artifacts["manifest"])
