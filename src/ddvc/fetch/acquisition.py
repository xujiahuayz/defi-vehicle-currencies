"""Canonical identity and mode rules for a frozen Graph acquisition generation."""

from __future__ import annotations

import hashlib
import gzip
import json
import math
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.thin_consumer_audit import validate_thin_consumer_audit_envelope
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
GRAPH_THIN_CONSUMER_AUDIT = REPO_ROOT / "docs" / "graph-thin-consumer-audit.json"
GRAPH_CANARY_EVIDENCE = REPO_ROOT / "docs" / "graph-query-canary-failures.jsonl.gz"
GRAPH_CANARY_CURRENT_EVIDENCE = REPO_ROOT / "docs" / "graph-query-canary-active-failures.jsonl.gz"
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
        compared = 0
        failed = 0
        for row in rows:
            values = path_value(row, values_path)
            compared += 1
            failed += int(bool(_vector_owner_failures(row, owner)))
        results[f"{values_path}~{identities_path}"] = {
            "compared_rows": compared,
            "failure_rows": failed,
        }
    return results


def vector_alignment_failures(
    row: dict[str, Any], owners: list[dict[str, str]]
) -> list[dict[str, object]]:
    """Return exact vector failures for one pre-quarantine row."""

    failures: list[dict[str, object]] = []
    for owner in owners:
        failures.extend(_vector_owner_failures(row, owner))
    return failures


def _valid_vector_value(value: object, *, identity: bool = False) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        if identity:
            return bool(value.strip())
        try:
            return Decimal(value.strip()).is_finite()
        except InvalidOperation:
            return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def _valid_vector_identity(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _valid_vector_value(value.get(field), identity=True)
            for field in ("id", "address")
        )
    return _valid_vector_value(value, identity=True)


def _vector_owner_failures(
    row: dict[str, Any], owner: Mapping[str, str]
) -> list[dict[str, object]]:
    values_path = owner["values_path"]
    identities_path = owner["identities_path"]
    values = path_value(row, values_path)
    identities = path_value(row, identities_path)
    values_length = len(values) if isinstance(values, list) else None
    identities_length = len(identities) if isinstance(identities, list) else None
    base = {
        "values_path": values_path,
        "identities_path": identities_path,
        "values_length": values_length,
        "identities_length": identities_length,
        "reason": owner.get("reason"),
    }
    if not isinstance(values, list) or not values:
        return [{**base, "failure": "missing_or_empty_values"}]
    identity_vector = values_path == identities_path or owner.get("reason") == "identity_vector"
    if not all(_valid_vector_value(value, identity=identity_vector) for value in values):
        return [{**base, "failure": "malformed_values"}]
    if not isinstance(identities, list) or not identities:
        return [{**base, "failure": "missing_or_empty_identities"}]
    if not all(_valid_vector_identity(value) for value in identities):
        return [{**base, "failure": "malformed_identities"}]
    if len(values) != len(identities):
        return [{**base, "failure": "length_mismatch"}]
    return []


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


def _validate_canary_evidence(
    canary: Mapping[str, Any], evidence_path: Path, *, label: str
) -> None:
    evidence = canary.get("quarantine_failure_evidence") or {}
    if (
        not evidence_path.is_file()
        or evidence.get("sha256") != sha256_file(evidence_path)
        or evidence.get("path") != repository_path_identity(evidence_path)
    ):
        raise ValueError(f"Graph {label} lacks current compact quarantine evidence")
    expected: dict[
        str,
        tuple[
            str,
            str,
            str,
            int,
            int,
            frozenset[int],
            list[dict[str, str]],
        ],
    ] = {}
    sampled_rows = 0
    for source in canary.get("sources", []):
        source_name = str(source.get("source") or "")
        for stream in source.get("streams", []):
            stream_name = str(stream.get("stream") or "")
            for sample in stream.get("samples", []):
                if sample.get("status") != "ok":
                    continue
                key = sample.get("quarantine_failure_evidence_key")
                rows = sample.get("quarantine_failure_evidence_rows")
                if not isinstance(key, str) or not key or type(rows) is not int or rows < 0:
                    raise ValueError(f"Graph {label} has malformed quarantine evidence metadata")
                if key in expected:
                    raise ValueError(f"Graph {label} repeats a quarantine evidence key")
                returned = sample.get("returned_rows")
                if type(returned) is not int or returned < rows:
                    raise ValueError(f"Graph {label} has malformed quarantine sample counts")
                failure_indices = sample.get("alignment_failure_row_indices")
                requested = sample.get("requested_rows")
                epoch = sample.get("epoch")
                if (
                    not isinstance(failure_indices, list)
                    or any(type(index) is not int or index < 0 or index >= returned for index in failure_indices)
                    or len(failure_indices) != len(set(failure_indices))
                    or len(failure_indices) != rows
                    or type(requested) is not int
                    or requested < returned
                    or not isinstance(epoch, str)
                    or not epoch
                ):
                    raise ValueError(f"Graph {label} has malformed quarantine sample identity")
                expected[key] = (
                    source_name,
                    stream_name,
                    epoch,
                    requested,
                    rows,
                    frozenset(failure_indices),
                    list(stream.get("vector_owners") or []),
                )
                sampled_rows += returned
    if evidence.get("sampled_rows") != sampled_rows:
        raise ValueError(f"Graph {label} quarantine evidence sampled-row count disagrees")
    observed_counts: dict[str, int] = {}
    observed_rows: set[tuple[str, int]] = set()
    try:
        with gzip.open(evidence_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.get("sample_key") if isinstance(row, dict) else None
                index = row.get("row_index") if isinstance(row, dict) else None
                if (
                    key not in expected
                    or type(index) is not int
                    or index < 0
                    or not isinstance(row.get("alignment_failures"), list)
                    or not row["alignment_failures"]
                    or row.get("source") != expected[key][0]
                    or row.get("stream") != expected[key][1]
                    or row.get("epoch") != expected[key][2]
                    or row.get("requested_rows") != expected[key][3]
                    or index not in expected[key][5]
                    or not isinstance(row.get("row"), dict)
                    or vector_alignment_failures(row["row"], expected[key][6])
                    != row["alignment_failures"]
                    or (key, index) in observed_rows
                ):
                    raise ValueError(f"Graph {label} quarantine evidence contains a non-failure row")
                observed_rows.add((key, index))
                observed_counts[key] = observed_counts.get(key, 0) + 1
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Graph {label} quarantine evidence is unreadable") from error
    expected_counts = {
        key: rows
        for key, (_source, _stream, _epoch, _requested, rows, _indices, _owners) in expected.items()
        if rows
    }
    if observed_counts != expected_counts or evidence.get("rows") != len(observed_rows):
        raise ValueError(f"Graph {label} quarantine evidence row counts disagree")


def validate_prelaunch_inputs(
    *,
    freeze_path: Path,
    inventory_path: Path,
    active_manifest_path: Path,
    new_manifest_path: Path,
    canary_path: Path,
    canary_evidence_path: Path,
    current_canary_path: Path,
    current_canary_evidence_path: Path,
    root_population_path: Path,
    forecast_path: Path,
    thin_audit_path: Path,
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
    thin_audit = validate_thin_consumer_audit_envelope(thin_audit_path)
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
    if forecast_inputs.get("thin_consumer_audit_sha256") != thin_audit["audit_sha256"]:
        raise ValueError("Graph forecast has stale thin_consumer_audit_sha256")
    if forecast_inputs.get("consumer_registry_sha256") != thin_audit["consumer_registry_sha256"]:
        raise ValueError("Graph forecast has stale consumer_registry_sha256")
    _validate_canary_evidence(canary, canary_evidence_path, label="canary")
    _validate_canary_evidence(
        current_canary,
        current_canary_evidence_path,
        label="current canary",
    )
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
        "thin_consumer_audit_sha256": thin_audit["audit_sha256"],
        "consumer_registry_sha256": thin_audit["consumer_registry_sha256"],
    }
