"""Runtime proof that installed Graph data satisfy every closed consumer."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.material_consumers import GRAPH_MATERIAL_CONSUMER_INTENTS, GraphMaterialConsumerIntent, material_consumer_registry_identity, material_consumer_registry_sha256, validate_material_consumer_registry
from ddvc.fetch.sources import get_source, iter_days
from ddvc.provenance import portable_content_sha256

if TYPE_CHECKING:
    from ddvc.raw_certification import RawPartition


def required_partitions(source: str, streams: set[str]) -> tuple[RawPartition, ...]:
    from ddvc.raw_certification import RawPartition

    end = dt.datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date() + dt.timedelta(days=1)
    return tuple(
        RawPartition(source, stream, day.strftime("%Y%m%d"))
        for stream in sorted(streams)
        for day in iter_days(get_source(source).genesis, end)
    )


def contract_fields(source: str, stream: str) -> set[str]:
    from ddvc.raw_certification import FIELD_CONTRACTS

    contract = FIELD_CONTRACTS.get((source, stream))
    if contract is None:
        raise ValueError(f"Graph thin-consumer stream lacks a raw field contract: {source}/{stream}")
    return set(contract.required_paths).union(*(set(group) for group in contract.required_any_paths))


def build_thin_consumer_audit(
    *,
    data_root: Path,
    certificate_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> dict[str, object]:
    """Reopen certificates and installed raw identities, then build exact proof."""

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
    from ddvc.raw_certification import load_certified_partition_ledger

    for source, streams in sorted(required_by_source.items()):
        certificate = certificate_root / f"{source}_local_certificate.json"
        partitions = required_partitions(source, streams)
        rows, authority = load_certified_partition_ledger(certificate, data_root=data_root, partitions=partitions)
        observed = {(str(row["source"]), str(row["stream"]), str(row["day"])) for row in rows}
        expected = {(item.source, item.stream, item.day) for item in partitions}
        if observed != expected:
            raise ValueError(f"Graph thin-consumer source marker has a different perimeter: {source}")
        source_markers.append(
            {
                "source": source,
                "streams": sorted(streams),
                "first_day": min(item.day for item in partitions),
                "last_day": max(item.day for item in partitions),
                "selected_partitions": len(partitions),
                "nonempty_partitions": sum(int(row.get("rows", 0)) > 0 for row in rows),
                "selected_rows": sum(int(row.get("rows", 0)) for row in rows),
                "certificate_file_sha256": portable_content_sha256(certificate),
                **authority,
            }
        )

    authorized = sorted({f"{source}/{stream}" for intent in intents.values() for source, stream in intent.allowed_new_streams})
    return {
        "schema_version": 2,
        "kind": "graph_thin_consumer_materiality_audit",
        "research_sample_end": RESEARCH_SAMPLE_END,
        "consumer_registry_sha256": material_consumer_registry_sha256(intents),
        "source_release_markers": source_markers,
        "consumers": consumers,
        "authorized_graph_acquisition": {"streams": authorized, "stream_count": len(authorized)},
        "selection_rule": "Only a closed named consumer intent may authorize exact missing streams; installed-stream sufficiency is bound to certified partition identities and explicit consumer fields.",
    }


def resolve_thin_consumer_audit(
    audit_path: Path,
    *,
    data_root: Path,
    certificate_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> dict[str, object]:
    """Recompute the checked-in audit from live certificates and raw identities."""

    recorded_identity = validate_thin_consumer_audit_envelope(audit_path, intents=intents)
    recorded = recorded_identity["audit"]
    intents = GRAPH_MATERIAL_CONSUMER_INTENTS if intents is None else intents
    recomputed = build_thin_consumer_audit(data_root=data_root, certificate_root=certificate_root, intents=intents)
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
        or recorded.get("schema_version") != 2
        or recorded.get("kind") != "graph_thin_consumer_materiality_audit"
        or recorded.get("research_sample_end") != RESEARCH_SAMPLE_END
    ):
        raise ValueError("Graph thin-consumer audit has an invalid envelope")
    intents = GRAPH_MATERIAL_CONSUMER_INTENTS if intents is None else intents
    registry_sha256 = material_consumer_registry_sha256(intents)
    if recorded.get("consumer_registry_sha256") != registry_sha256:
        raise ValueError("Graph thin-consumer audit has stale consumer registry identity")
    return {
        "audit": recorded,
        "audit_sha256": portable_content_sha256(audit_path),
        "consumer_registry_sha256": registry_sha256,
    }
