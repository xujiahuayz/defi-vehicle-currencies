"""Canonical identity and mode rules for a frozen Graph acquisition generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.paths import REPO_ROOT


GRAPH_SCHEMA_INVENTORY = REPO_ROOT / "docs" / "graph-schema-inventory.json"
GRAPH_ACTIVE_MANIFEST = REPO_ROOT / "docs" / "graph-field-admission.json"
GRAPH_NEW_STREAM_INVENTORY = REPO_ROOT / "docs" / "graph-admitted-stream-inventory.json"
GRAPH_NEW_MANIFEST = REPO_ROOT / "docs" / "graph-new-stream-field-admission.json"
GRAPH_ACQUISITION_FREEZE = REPO_ROOT / "docs" / "graph-acquisition-freeze.json"
GRAPH_ROOT_POPULATION = REPO_ROOT / "docs" / "graph-root-population.json"
GRAPH_CANARY_CURRENT = REPO_ROOT / "docs" / "graph-query-canaries-active-current.json"
GRAPH_CANARY_FINAL = REPO_ROOT / "docs" / "graph-query-canaries-final.json"
GRAPH_ACQUISITION_FORECAST = REPO_ROOT / "docs" / "graph-acquisition-forecast.json"
GRAPH_CANARY_EVIDENCE = REPO_ROOT / "docs" / "graph-query-canaries-final-evidence.jsonl.gz"
GRAPH_TIME_FIELDS = (
    "timestamp",
    "startTimestamp",
    "endTimestamp",
    "date",
    "periodStartUnix",
    "hourStartUnix",
    "day",
    "createdAtTimestamp",
    "createdTimestamp",
    "createTime",
)
GRAPH_BLOCK_FIELDS = ("blockNumber", "block", "createdAtBlockNumber", "createdBlockNumber")


def research_sample_end_unix() -> int:
    return int(
        datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    ) + 86_399


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_path_identity(path: Path) -> str:
    """Return a portable repo-relative identity, or an exact external path."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def source_contract_sha256(source_name: str) -> str:
    source = DEX_SOURCES[source_name]
    return hashlib.sha256(
        json.dumps(
            {
                "source": source_name,
                "schema": source.schema,
                "graph_path": source.graph_path,
                "subgraph_id": source.subgraph_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def path_value(row: dict[str, Any], path: str) -> Any:
    """Resolve one direct relation path without flattening its terminal value."""

    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def vector_alignment_results(
    rows: list[dict[str, Any]], owners: list[dict[str, str]]
) -> dict[str, dict[str, int]]:
    """Compare every populated vector with its typed identity vector.

    A populated value vector without a populated identity vector is a failed
    comparison, not an untested row.  This keeps missing ownership from passing a
    canary through a zero-comparison loophole.
    """

    results: dict[str, dict[str, int]] = {}
    for owner in owners:
        values_path = owner["values_path"]
        identities_path = owner["identities_path"]
        if values_path == identities_path:
            continue
        compared = 0
        failed = 0
        for row in rows:
            values = path_value(row, values_path)
            if not isinstance(values, list):
                continue
            identities = path_value(row, identities_path)
            compared += 1
            failed += int(
                not isinstance(identities, list) or len(values) != len(identities)
            )
        results[f"{values_path}~{identities_path}"] = {
            "compared_rows": compared,
            "failure_rows": failed,
        }
    return results


def vector_alignment_failures(
    row: dict[str, Any], owners: list[dict[str, str]]
) -> list[dict[str, object]]:
    """Return exact non-self vector failures for one pre-quarantine row."""

    failures: list[dict[str, object]] = []
    for owner in owners:
        values_path = owner["values_path"]
        identities_path = owner["identities_path"]
        if values_path == identities_path:
            continue
        values = path_value(row, values_path)
        if not isinstance(values, list):
            continue
        identities = path_value(row, identities_path)
        if not isinstance(identities, list) or len(values) != len(identities):
            failures.append(
                {
                    "values_path": values_path,
                    "identities_path": identities_path,
                    "values_length": len(values),
                    "identities_length": (
                        len(identities) if isinstance(identities, list) else None
                    ),
                    "reason": owner.get("reason"),
                }
            )
    return failures


def validate_freeze(
    freeze: dict[str, Any],
    *,
    inventory: Path,
    active_manifest: Path,
    new_manifest: Path,
    expected_sources: set[str],
) -> dict[str, int]:
    from ddvc.ethereum_day_cuts import validate_utc_day_block_bounds

    expected_hashes = {
        "schema_inventory_sha256": sha256_file(inventory),
        "active_manifest_sha256": sha256_file(active_manifest),
        "new_manifest_sha256": sha256_file(new_manifest),
    }
    for name, expected in expected_hashes.items():
        if freeze.get(name) != expected:
            raise ValueError(f"Graph acquisition freeze has stale {name}")
    if freeze.get("research_sample_end") != RESEARCH_SAMPLE_END:
        raise ValueError("Graph acquisition freeze has stale research cutoff")
    boundary = freeze.get("sample_end_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("Graph acquisition freeze lacks sample-end boundary evidence")
    try:
        validate_utc_day_block_bounds(boundary, RESEARCH_SAMPLE_END)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Graph acquisition freeze has invalid sample-end boundary evidence") from error
    if not boundary.get("rpc_evidence"):
        raise ValueError("Graph acquisition freeze sample-end boundary lacks RPC evidence")
    boundary_block = int(boundary["end_block"])
    records = freeze.get("sources") or []
    heads = {str(record["source"]): int(record["head_block"]) for record in records}
    if set(heads) != expected_sources or len(records) != len(heads):
        raise ValueError("Graph acquisition freeze source perimeter differs")
    for record in records:
        source_name = str(record["source"])
        sample_end_block = record.get("sample_end_block")
        if (
            isinstance(sample_end_block, bool)
            or not isinstance(sample_end_block, int)
            or sample_end_block < int(DEX_SOURCES[source_name].genesis_block or 0)
            or sample_end_block > int(record["head_block"])
            or sample_end_block != boundary_block
        ):
            raise ValueError(
                f"Graph acquisition freeze lacks valid sample-end block evidence: {source_name}"
            )
        if record.get("source_contract_sha256") != source_contract_sha256(source_name):
            raise ValueError(f"Graph acquisition freeze has stale source contract: {source_name}")
    return {
        str(record["source"]): int(record["sample_end_block"])
        for record in records
    }


def frozen_provider_heads(freeze: dict[str, Any]) -> dict[str, int]:
    """Return provider heads only after the caller has validated the freeze."""

    return {
        str(record["source"]): int(record["head_block"])
        for record in freeze.get("sources", [])
    }


def validate_prelaunch_inputs(
    *,
    freeze_path: Path,
    inventory_path: Path,
    active_manifest_path: Path,
    new_manifest_path: Path,
    canary_path: Path,
    canary_evidence_path: Path,
    current_canary_path: Path,
    root_population_path: Path,
    forecast_path: Path,
) -> dict[str, object]:
    """Recompute every launch identity and veto unresolved quality evidence."""

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    expected_sources = {
        str(record["source"])
        for record in freeze.get("sources", [])
        if isinstance(record, dict) and record.get("source")
    }
    sample_end_blocks = validate_freeze(
        freeze,
        inventory=inventory_path,
        active_manifest=active_manifest_path,
        new_manifest=new_manifest_path,
        expected_sources=expected_sources,
    )
    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    current_canary = json.loads(current_canary_path.read_text(encoding="utf-8"))
    root_population = json.loads(root_population_path.read_text(encoding="utf-8"))
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    expected = {
        "freeze_sha256": sha256_file(freeze_path),
        "schema_inventory_sha256": sha256_file(inventory_path),
        "active_manifest_sha256": sha256_file(active_manifest_path),
        "new_manifest_sha256": sha256_file(new_manifest_path),
    }
    for label, payload in (("canary", canary), ("current canary", current_canary), ("root population", root_population)):
        for key, digest in expected.items():
            if payload.get(key) != digest:
                raise ValueError(f"Graph {label} has stale {key}")
    forecast_inputs = forecast.get("inputs") or {}
    if forecast_inputs.get("freeze_sha256") != expected["freeze_sha256"]:
        raise ValueError("Graph forecast has stale freeze_sha256")
    if forecast_inputs.get("final_canary_sha256") != sha256_file(canary_path):
        raise ValueError("Graph forecast has stale final_canary_sha256")
    if forecast_inputs.get("current_canary_sha256") != sha256_file(current_canary_path):
        raise ValueError("Graph forecast has stale current_canary_sha256")
    if forecast_inputs.get("root_population_sha256") != sha256_file(root_population_path):
        raise ValueError("Graph forecast has stale root_population_sha256")
    evidence = canary.get("pre_quarantine_evidence") or {}
    if (
        not canary_evidence_path.is_file()
        or evidence.get("sha256") != sha256_file(canary_evidence_path)
        or evidence.get("path") != repository_path_identity(canary_evidence_path)
    ):
        raise ValueError("Graph canary lacks current pre-quarantine row evidence")
    unresolved = [
        (source["source"], stream["stream"])
        for source in canary.get("sources", [])
        for stream in source.get("streams", [])
        if (
            int(stream.get("summary", {}).get("failed_samples", 0)) > 0
            and stream.get("quality_action") != "provider_archive_unavailable_quarantined"
        )
        or (
            int(stream.get("summary", {}).get("alignment_failure_rows", 0)) > 0
            and stream.get("quality_action") != "row_quarantine_before_release"
        )
    ]
    if unresolved:
        raise ValueError(f"Graph canary has unresolved quality failures: {unresolved[:3]}")
    if int(root_population.get("summary", {}).get("errors", 0)):
        raise ValueError("Graph root population has unresolved query failures")
    if forecast.get("launch_decision") != "inventory_validated_consumer_selection_required":
        raise ValueError("Graph inventory forecast does not require consumer selection")
    return {
        "sample_end_blocks": sample_end_blocks,
        "provider_head_blocks": frozen_provider_heads(freeze),
        "stream_count": sum(
            len(source.get("streams", [])) for source in canary.get("sources", [])
        ),
        "freeze_sha256": expected["freeze_sha256"],
    }
