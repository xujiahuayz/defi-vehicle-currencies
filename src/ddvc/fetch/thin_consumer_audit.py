"""Runtime proof that installed Graph data satisfy every closed consumer."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.graphql_selection import selected_paths
from ddvc.fetch.material_consumers import GRAPH_MATERIAL_CONSUMER_INTENTS, GraphMaterialConsumerIntent, graph_acquisition_authorization, material_consumer_registry_identity, material_consumer_registry_sha256, validate_material_consumer_registry
from ddvc.fetch.sources import get_source, iter_days
from ddvc.paths import RAW_MARKET_DATA_LOCK
from ddvc.provenance import portable_content_sha256
from ddvc.runtime import atomic_output, exclusive_job

@dataclass(frozen=True, order=True)
class RawPartition:
    source: str
    stream: str
    day: str


def required_partitions(source: str, streams: set[str]) -> tuple[RawPartition, ...]:
    end = dt.datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date() + dt.timedelta(days=1)
    return tuple(
        RawPartition(source, stream, day.strftime("%Y%m%d"))
        for stream in sorted(streams)
        for day in iter_days(get_source(source).genesis, end)
    )


def contract_fields(source: str, stream: str) -> set[str]:
    from ddvc.fetch.schemas import get_schema

    entity = next(
        (item for item in get_schema(get_source(source).schema).entities if item.stream == stream),
        None,
    )
    if entity is None:
        raise ValueError(f"Graph thin-consumer stream lacks a fetch schema: {source}/{stream}")
    return selected_paths(entity.fields)


def _build_thin_consumer_audit_unlocked(
    *,
    data_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> dict[str, object]:
    """Reopen installed source-day files, then build the exact sufficiency proof."""

    intents = GRAPH_MATERIAL_CONSUMER_INTENTS if intents is None else intents
    validate_material_consumer_registry(intents)
    registry_identity = material_consumer_registry_identity(intents)
    required_by_source: dict[str, set[str]] = {}
    consumers = []
    for name, intent in sorted(intents.items()):
        fields = registry_identity[name]["existing_stream_field_perimeter"]
        for requirement in intent.existing_streams:
            required_by_source.setdefault(requirement.source, set()).add(requirement.stream)
            missing = sorted(set(requirement.fields).difference(contract_fields(requirement.source, requirement.stream)))
            if missing:
                raise ValueError(f"Graph thin-consumer field perimeter exceeds its certified contract: {name}/{requirement.source}/{requirement.stream}/{missing[:3]}")
        consumers.append(
            {
                "consumer": name,
                **registry_identity[name],
                "new_graph_acquisition_required": bool(intent.allowed_new_streams),
            }
        )

    source_markers = []
    from ddvc.fetch.raw import source_day_stream_snapshot

    for source, streams in sorted(required_by_source.items()):
        partitions = required_partitions(source, streams)
        rows = [
            source_day_stream_snapshot(
                item.source,
                item.stream,
                dt.datetime.strptime(item.day, "%Y%m%d").date(),
                data_root=data_root,
            )
            for item in partitions
        ]
        source_markers.append(
            {
                "source": source,
                "streams": sorted(streams),
                "first_day": min(item.day for item in partitions),
                "last_day": max(item.day for item in partitions),
                "selected_partitions": len(partitions),
                "nonempty_partitions": sum(int(row.get("rows", 0)) > 0 for row in rows),
                "selected_rows": sum(int(row.get("rows", 0)) for row in rows),
                "selected_bytes": sum(int(row["payload_stat"][2]) for row in rows),
                "latest_mtime_ns": max(
                    max(int(row["payload_stat"][3]), int(row["marker_stat"][3]))
                    for row in rows
                ),
                "identity_policy": "source-day-file-timestamp-v1",
            }
        )

    authorization = graph_acquisition_authorization(intents)
    return {
        "schema_version": 3,
        "kind": "graph_thin_consumer_materiality_audit",
        "research_sample_end": RESEARCH_SAMPLE_END,
        "consumer_registry_sha256": material_consumer_registry_sha256(intents),
        "source_release_markers": source_markers,
        "consumers": consumers,
        "authorized_graph_acquisition": authorization,
        "selection_rule": "Only a closed named consumer intent may authorize exact missing streams; installed-stream sufficiency is reopened from source-day files and explicit fetch-schema fields.",
    }


def build_thin_consumer_audit(
    *,
    data_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
    mutation_lock: Path = RAW_MARKET_DATA_LOCK,
) -> dict[str, object]:
    """Build exact proof while excluding every canonical raw-data writer."""

    with exclusive_job(mutation_lock, job="Graph thin-consumer source certification"):
        return _build_thin_consumer_audit_unlocked(
            data_root=data_root,
            intents=intents,
        )


def _write_thin_consumer_audit_unlocked(
    audit_path: Path,
    payload: Mapping[str, object],
) -> None:
    """Atomically install a built audit; the caller owns the raw mutation lease."""

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(audit_path) as temporary:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def publish_thin_consumer_audit(
    audit_path: Path,
    *,
    data_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
    mutation_lock: Path = RAW_MARKET_DATA_LOCK,
) -> dict[str, object]:
    """Build and publish one audit under a single raw-generation lease."""

    with exclusive_job(mutation_lock, job="Graph thin-consumer audit publication"):
        payload = _build_thin_consumer_audit_unlocked(
            data_root=data_root,
            intents=intents,
        )
        _write_thin_consumer_audit_unlocked(audit_path, payload)
        return payload


def resolve_thin_consumer_audit(
    audit_path: Path,
    *,
    data_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
    mutation_lock: Path = RAW_MARKET_DATA_LOCK,
) -> dict[str, object]:
    """Recompute the checked-in audit from live certificates and raw identities."""

    with exclusive_job(mutation_lock, job="Graph thin-consumer source certification"):
        recorded_identity = validate_thin_consumer_audit_envelope(audit_path, intents=intents)
        recorded = recorded_identity["audit"]
        intents = GRAPH_MATERIAL_CONSUMER_INTENTS if intents is None else intents
        recomputed = _build_thin_consumer_audit_unlocked(data_root=data_root, intents=intents)
        if recorded != recomputed:
            raise ValueError("Graph thin-consumer audit disagrees with live certified raw identities")
        return recorded_identity


def validate_thin_consumer_audit_envelope(
    audit_path: Path,
    *,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> dict[str, object]:
    """Validate the static audit contract and bind it to the live registry."""

    try:
        recorded = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Graph thin-consumer audit is missing or invalid") from error
    if (
        not isinstance(recorded, dict)
        or recorded.get("schema_version") != 3
        or recorded.get("kind") != "graph_thin_consumer_materiality_audit"
        or recorded.get("research_sample_end") != RESEARCH_SAMPLE_END
    ):
        raise ValueError("Graph thin-consumer audit has an invalid envelope")
    intents = GRAPH_MATERIAL_CONSUMER_INTENTS if intents is None else intents
    registry_sha256 = material_consumer_registry_sha256(intents)
    if recorded.get("consumer_registry_sha256") != registry_sha256:
        raise ValueError("Graph thin-consumer audit has stale consumer registry identity")
    authorization = graph_acquisition_authorization(intents)
    if recorded.get("authorized_graph_acquisition") != authorization:
        raise ValueError("Graph thin-consumer audit has stale acquisition authorization")
    return {
        "audit": recorded,
        "audit_sha256": portable_content_sha256(audit_path),
        "consumer_registry_sha256": registry_sha256,
        "authorized_graph_acquisition": authorization,
    }
