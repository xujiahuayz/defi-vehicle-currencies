"""Crash-safe D3 analysis releases over the exact claim-input perimeter."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ddvc.artifact_release import (
    ArtifactRelease,
    file_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.fetch.raw import write_json
from ddvc.model_registry import canonical_hash, claim_execution_perimeter, generation_id
from ddvc.paths import REPO_ROOT
from ddvc.provenance import (
    code_fingerprint,
    describe_input,
    portable_content_sha256,
    sidecar_path,
    verify,
)


ANALYSIS_RELEASE_SCHEMA_VERSION = 1
ANALYSIS_RELEASE_KIND = "d3_analysis_release"
ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION = 1
ANALYSIS_RELEASE_POINTER_KIND = "d3_analysis_release_bundle"
ANALYSIS_RELEASE_FILENAMES = {"certificate": "certificate.json"}
ANALYSIS_RELEASE_CURRENT = REPO_ROOT / "data" / "processed" / "d3_analysis_release" / "current.json"
SPECIFICATION_LOCK = REPO_ROOT / "docs" / "specification-lock.json"
ANALYSIS_RELEASE_CODE_SOURCES = (
    "src/ddvc/artifact_release.py",
    "src/ddvc/analysis_release.py",
    "src/ddvc/model_registry.py",
    "src/ddvc/provenance.py",
    "scripts/publish_analysis_release.py",
)


@dataclass(frozen=True)
class AnalysisRelease:
    """One reopened D3 certificate and its exact analysis-input identities."""

    generation: str
    pointer_path: Path | None
    certificate_path: Path
    certificate: dict[str, Any]
    root: Path

    @property
    def input_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / record["path"] for record in self.certificate["claim_inputs"])


@dataclass(frozen=True)
class AnalysisInputPerimeter:
    """Executable claim inputs plus explicit exclusions from one specification."""

    paths: dict[str, list[str]]
    executable_claim_ids: tuple[str, ...]
    excluded_claims: tuple[dict[str, Any], ...]


def resolve_repo_path(value: str | Path, *, root: Path, label: str) -> tuple[str, Path]:
    relative = Path(value)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must be a repository-relative path: {value}")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} escapes the repository: {value}")
    return relative.as_posix(), resolved


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return payload


def _active_claim_input_perimeter(specification: Mapping[str, Any]) -> AnalysisInputPerimeter:
    classified = claim_execution_perimeter(specification)
    perimeter: dict[str, list[str]] = {}
    executable_claim_ids: list[str] = []
    for claim in classified.executable_claims:
        claim_id = str(claim["id"])
        executable_claim_ids.append(claim_id)
        inputs = claim.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError(f"execution-open claim has no analysis inputs: {claim_id}")
        for value in inputs:
            if not isinstance(value, str) or not value:
                raise ValueError(f"execution-open claim has an invalid input path: {claim_id}")
            if Path(value).is_absolute() or ".." in Path(value).parts:
                raise ValueError(f"execution-open claim input is not repository-relative: {claim_id}/{value}")
            if value.startswith("data/raw/"):
                raise ValueError(f"raw provider input cannot enter a D3 release: {claim_id}/{value}")
            perimeter.setdefault(value, []).append(claim_id)
    if not executable_claim_ids or not perimeter:
        raise ValueError("specification lock has no execution-open claim-input perimeter")
    return AnalysisInputPerimeter(
        paths={path: sorted(set(claim_ids)) for path, claim_ids in sorted(perimeter.items())},
        executable_claim_ids=tuple(sorted(executable_claim_ids)),
        excluded_claims=classified.excluded_claims,
    )


def _validate_specification_identity(specification: Mapping[str, Any]) -> str:
    declared_hash = str(specification.get("lock_hash") or "")
    actual_hash = canonical_hash({key: value for key, value in specification.items() if key != "lock_hash"})
    if specification.get("schema_version") != 1 or declared_hash != actual_hash:
        raise ValueError("specification lock identity is stale or malformed")
    stage = str(specification.get("stage") or "")
    if stage not in {"design_seed", "confirmatory"}:
        raise ValueError(f"specification lock has an invalid stage: {stage or 'missing'}")
    return actual_hash


def _reopen_artifact(path: Path) -> dict[str, Any]:
    suffixes = path.suffixes
    if path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        return {
            "format": "parquet",
            "rows": int(parquet.metadata.num_rows),
            "columns": list(parquet.schema_arrow.names),
        }
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "format": "json",
            "rows": len(payload) if isinstance(payload, list) else 1,
            "columns": sorted(payload) if isinstance(payload, dict) else [],
        }
    if path.suffix == ".jsonl" or suffixes[-2:] == [".jsonl", ".gz"]:
        opener = gzip.open if path.suffix == ".gz" else Path.open
        rows = 0
        columns: set[str] = set()
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    columns.update(str(key) for key in value)
                rows += 1
        return {"format": "jsonl", "rows": rows, "columns": sorted(columns)}
    with path.open("rb") as handle:
        handle.read(1)
    return {"format": path.suffix.lstrip(".") or "binary", "rows": None, "columns": []}


def _provenance_identity(path: Path, *, verifier: Callable[[str | Path], dict[str, object]]) -> tuple[Path, dict[str, Any]]:
    verdict = verifier(path)
    if verdict.get("status") != "ok":
        raise RuntimeError(f"D3 claim input is not current: {path}: {verdict.get('status')}")
    provenance_path = sidecar_path(path)
    if not provenance_path.is_file():
        raise FileNotFoundError(f"D3 claim input lacks provenance: {path}")
    provenance = _load_json_object(provenance_path, label="claim-input provenance")
    described = describe_input(path)
    if provenance.get("artefact") != described.get("path"):
        raise ValueError(f"claim-input provenance identifies a different artifact: {path}")
    recorded_digest = provenance.get("artefact_sha256")
    exact_digest = file_sha256(path)
    if recorded_digest is not None and recorded_digest != exact_digest:
        raise ValueError(f"claim-input provenance identifies different content: {path}")
    return provenance_path, provenance


def _claim_input_records(
    perimeter: Mapping[str, list[str]],
    *,
    root: Path,
    verifier: Callable[[str | Path], dict[str, object]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative, claim_ids in perimeter.items():
        normalized, path = resolve_repo_path(relative, root=root, label="claim input")
        if not path.is_file():
            raise FileNotFoundError(f"D3 claim input is absent: {normalized}")
        provenance_path, _provenance = _provenance_identity(path, verifier=verifier)
        reopened = _reopen_artifact(path)
        records.append(
            {
                "path": normalized,
                "claim_ids": list(claim_ids),
                "bytes": path.stat().st_size,
                "content_sha256": portable_content_sha256(path),
                "provenance_path": provenance_path.relative_to(root).as_posix(),
                "provenance_sha256": file_sha256(provenance_path),
                **reopened,
            }
        )
    return records


def build_analysis_release_certificate(
    *,
    root: Path = REPO_ROOT,
    specification_path: str | Path = "docs/specification-lock.json",
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> tuple[dict[str, Any], list[Path]]:
    """Reopen every active claim input and build a content-addressed D3 certificate."""

    specification_relative, resolved_specification = resolve_repo_path(
        specification_path,
        root=root,
        label="specification lock",
    )
    if not resolved_specification.is_file():
        raise FileNotFoundError(f"specification lock is absent: {specification_relative}")
    specification = _load_json_object(resolved_specification, label="specification lock")
    specification_hash = _validate_specification_identity(specification)
    perimeter = _active_claim_input_perimeter(specification)
    records = _claim_input_records(perimeter.paths, root=root, verifier=verifier)
    certificate: dict[str, Any] = {
        "schema_version": ANALYSIS_RELEASE_SCHEMA_VERSION,
        "kind": ANALYSIS_RELEASE_KIND,
        "status": "pass",
        "specification_path": specification_relative,
        "specification_lock_hash": specification_hash,
        "specification_stage": specification["stage"],
        "executable_claim_ids": list(perimeter.executable_claim_ids),
        "excluded_claim_count": len(perimeter.excluded_claims),
        "excluded_claims": list(perimeter.excluded_claims),
        "claim_input_count": len(records),
        "claim_input_perimeter_sha256": canonical_hash(records),
        "claim_inputs": records,
        "code_fingerprint": code_fingerprint(list(code_sources)),
    }
    certificate["generation"] = generation_id(certificate)
    inputs = [
        resolved_specification,
        *[root / record["path"] for record in records],
        *[root / record["provenance_path"] for record in records],
    ]
    return certificate, inputs


def _write_staged_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def publish_analysis_release(
    *,
    root: Path = REPO_ROOT,
    specification_path: str | Path = "docs/specification-lock.json",
    pointer_path: str | Path = "data/processed/d3_analysis_release/current.json",
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> AnalysisRelease:
    """Reopen, stage, stamp, and marker-release one immutable D3 certificate."""

    _pointer_relative, resolved_pointer = resolve_repo_path(pointer_path, root=root, label="D3 release pointer")
    certificate, inputs = build_analysis_release_certificate(
        root=root,
        specification_path=specification_path,
        verifier=verifier,
        code_sources=code_sources,
    )

    def validate_staged(paths: Mapping[str, Path]) -> None:
        reopened = _load_json_object(paths["certificate"], label="staged D3 certificate")
        if reopened != certificate or generation_id(reopened) != certificate["generation"]:
            raise ValueError("staged D3 certificate does not round-trip exactly")

    bundle = publish_artifact_release(
        pointer_path=resolved_pointer,
        kind=ANALYSIS_RELEASE_POINTER_KIND,
        schema_version=ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
        filenames=ANALYSIS_RELEASE_FILENAMES,
        writers={"certificate": lambda path: _write_staged_json(path, certificate)},
        row_counts={"certificate": len(certificate["claim_inputs"])},
        code_sources=list(code_sources),
        inputs=inputs,
        notes=f"D3 analysis release {certificate['generation']}",
        validate_staged=validate_staged,
        write_pointer=write_json,
    )
    certificate_relative = bundle.artifacts["certificate"].relative_to(root).as_posix()
    release = resolve_analysis_release(
        certificate_path=certificate_relative,
        root=root,
        verifier=verifier,
        code_sources=code_sources,
    )
    if release.generation != certificate["generation"]:
        raise RuntimeError("installed D3 generation differs from its staged identity")
    return AnalysisRelease(release.generation, bundle.pointer_path, release.certificate_path, release.certificate, root)


def resolve_analysis_release(
    *,
    certificate_path: str | Path,
    root: Path = REPO_ROOT,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> AnalysisRelease:
    """Reopen a D3 certificate and independently reproduce its exact perimeter."""

    _relative, path = resolve_repo_path(certificate_path, root=root, label="D3 certificate")
    if not path.is_file():
        raise FileNotFoundError(f"D3 analysis-release certificate is absent: {path}")
    verdict = verifier(path)
    if verdict.get("status") != "ok":
        raise RuntimeError(f"D3 analysis-release certificate is not current: {verdict.get('status')}")
    certificate = _load_json_object(path, label="D3 analysis-release certificate")
    if (
        certificate.get("schema_version") != ANALYSIS_RELEASE_SCHEMA_VERSION
        or certificate.get("kind") != ANALYSIS_RELEASE_KIND
        or certificate.get("status") != "pass"
        or certificate.get("generation") != generation_id(certificate)
    ):
        raise ValueError("D3 analysis-release certificate is stale or malformed")
    expected, _inputs = build_analysis_release_certificate(
        root=root,
        specification_path=str(certificate.get("specification_path") or ""),
        verifier=verifier,
        code_sources=code_sources,
    )
    if expected != certificate:
        raise ValueError("D3 analysis-release certificate does not reproduce from current claim inputs")
    return AnalysisRelease(str(certificate["generation"]), None, path, certificate, root)


def resolve_current_analysis_release(
    *,
    pointer_path: str | Path = "data/processed/d3_analysis_release/current.json",
    root: Path = REPO_ROOT,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> AnalysisRelease:
    """Resolve the marker-last D3 pointer and independently reopen its certificate."""

    _relative, resolved_pointer = resolve_repo_path(pointer_path, root=root, label="D3 release pointer")
    bundle: ArtifactRelease = resolve_artifact_release(
        resolved_pointer,
        kind=ANALYSIS_RELEASE_POINTER_KIND,
        schema_version=ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
        filenames=ANALYSIS_RELEASE_FILENAMES,
    )
    certificate_relative = bundle.artifacts["certificate"].relative_to(root).as_posix()
    release = resolve_analysis_release(
        certificate_path=certificate_relative,
        root=root,
        verifier=verifier,
        code_sources=code_sources,
    )
    return AnalysisRelease(release.generation, bundle.pointer_path, release.certificate_path, release.certificate, root)
