#!/usr/bin/env python3
"""Build compact proof that current Graph consumers need no incremental fetch."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Mapping

from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.material_consumers import GRAPH_MATERIAL_CONSUMER_INTENTS, GraphMaterialConsumerIntent, validate_material_consumer_registry
from ddvc.fetch.raw import write_json
from ddvc.fetch.sources import get_source, iter_days
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.raw_certification import FIELD_CONTRACTS, RawPartition, load_certified_partition_ledger


DEFAULT_CERTIFICATE_ROOT = DATA_DIR / "processed" / "graph_thin_consumer_audit" / "source_markers"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "graph-thin-consumer-audit.json"


def _required_partitions(source: str, streams: set[str]) -> tuple[RawPartition, ...]:
    end = dt.datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date() + dt.timedelta(days=1)
    return tuple(
        RawPartition(source, stream, day.strftime("%Y%m%d"))
        for stream in sorted(streams)
        for day in iter_days(get_source(source).genesis, end)
    )


def _contract_fields(source: str, stream: str) -> set[str]:
    contract = FIELD_CONTRACTS.get((source, stream))
    if contract is None:
        raise ValueError(f"Graph thin-consumer stream lacks a raw field contract: {source}/{stream}")
    return set(contract.required_paths).union(*(set(group) for group in contract.required_any_paths))


def build_audit(
    *,
    data_root: Path,
    certificate_root: Path,
    intents: Mapping[str, GraphMaterialConsumerIntent] = GRAPH_MATERIAL_CONSUMER_INTENTS,
) -> dict[str, object]:
    validate_material_consumer_registry(intents)
    required_by_source: dict[str, set[str]] = {}
    consumers = []
    for name, intent in sorted(intents.items()):
        fields = []
        for requirement in intent.existing_streams:
            required_by_source.setdefault(requirement.source, set()).add(requirement.stream)
            missing = sorted(set(requirement.fields).difference(_contract_fields(requirement.source, requirement.stream)))
            if missing:
                raise ValueError(f"Graph thin-consumer field perimeter exceeds its certified contract: {name}/{requirement.source}/{requirement.stream}/{missing[:3]}")
            fields.append(
                {
                    "source": requirement.source,
                    "stream": requirement.stream,
                    "fields": list(requirement.fields),
                    "field_perimeter_sha256": canonical_json_sha256(list(requirement.fields)),
                }
            )
        consumers.append(
            {
                "consumer": name,
                "materiality_reason": intent.reason,
                "existing_stream_field_perimeter": fields,
                "allowed_new_streams": [f"{source}/{stream}" for source, stream in sorted(intent.allowed_new_streams)],
                "max_selected_streams": intent.max_selected_streams,
                "unresolved_non_graph_prerequisites": list(intent.unresolved_prerequisites),
                "new_graph_acquisition_required": bool(intent.allowed_new_streams),
            }
        )

    source_markers = []
    for source, streams in sorted(required_by_source.items()):
        certificate = certificate_root / f"{source}_local_certificate.json"
        partitions = _required_partitions(source, streams)
        rows, authority = load_certified_partition_ledger(
            certificate,
            data_root=data_root,
            partitions=partitions,
        )
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
                "certificate_file_sha256": file_sha256(certificate),
                **authority,
            }
        )

    registry_identity = {
        item["consumer"]: {
            "existing_stream_field_perimeter": item["existing_stream_field_perimeter"],
            "allowed_new_streams": item["allowed_new_streams"],
            "max_selected_streams": item["max_selected_streams"],
            "unresolved_non_graph_prerequisites": item["unresolved_non_graph_prerequisites"],
        }
        for item in consumers
    }
    authorized = sorted(
        {
            f"{source}/{stream}"
            for intent in intents.values()
            for source, stream in intent.allowed_new_streams
        }
    )
    return {
        "schema_version": 2,
        "kind": "graph_thin_consumer_materiality_audit",
        "research_sample_end": RESEARCH_SAMPLE_END,
        "consumer_registry_sha256": canonical_json_sha256(registry_identity),
        "source_release_markers": source_markers,
        "consumers": consumers,
        "authorized_graph_acquisition": {
            "streams": authorized,
            "stream_count": len(authorized),
        },
        "selection_rule": "Only a closed named consumer intent may authorize exact missing streams; installed-stream sufficiency is bound to certified partition identities and explicit consumer fields.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_DIR)
    parser.add_argument("--certificate-root", type=Path, default=DEFAULT_CERTIFICATE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_audit(data_root=args.data_root, certificate_root=args.certificate_root)
    write_json(args.output, payload)
    print(
        json.dumps(
            {
                "consumers": len(payload["consumers"]),
                "source_markers": len(payload["source_release_markers"]),
                "authorized_streams": payload["authorized_graph_acquisition"]["stream_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
