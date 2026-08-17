"""Crash-safe D3 analysis releases over the exact claim-input perimeter."""

from __future__ import annotations

import gzip
import json
from contextlib import ExitStack, contextmanager
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ddvc.artifact_release import (
    ArtifactRelease,
    SemanticValidationReceipt,
    bind_file_lineage,
    current_artifact_release,
    current_file_lineage,
    file_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.d3_stage_registry import d3_release_postcondition
from ddvc.fetch.raw import write_json
from ddvc.model_registry import canonical_hash, claim_execution_perimeter, generation_id
from ddvc.paths import REPO_ROOT
from ddvc.panel_freshness import check_canonical_panel_freshness
from ddvc.provenance import (
    code_fingerprint,
    describe_input,
    portable_content_sha256,
    semantic_code_fingerprint,
    sidecar_path,
    verify,
    current_artifacts,
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
    "src/ddvc/d3_stage_registry.py",
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


def _typed_release_record(
    relative: str,
    claim_ids: list[str],
    bundle: ArtifactRelease,
    *,
    root: Path,
    require_semantic_receipt: bool,
) -> dict[str, Any]:
    receipt = bundle.semantic_receipt
    if require_semantic_receipt and receipt is None:
        raise ValueError(f"D3 typed release lacks semantic validation: {relative}")
    def record_path(path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    record = {
        "path": relative,
        "claim_ids": list(claim_ids),
        "input_kind": "release_pointer",
        "bytes": bundle.pointer_path.stat().st_size,
        "content_sha256": bundle.pointer_sha256,
        "release_generation": bundle.generation_id,
        "release_artifacts": [
            {
                "name": name,
                "path": record_path(path),
                "content_sha256": bundle.artifact_sha256[name],
                "provenance_path": record_path(sidecar_path(path)),
                "provenance_sha256": bundle.provenance_sha256[name],
            }
            for name, path in sorted(bundle.artifacts.items())
        ],
        "format": "release_pointer",
        "rows": len(bundle.artifacts),
        "columns": sorted(bundle.artifacts),
    }
    if require_semantic_receipt:
        assert receipt is not None
        record["semantic_validation"] = receipt.as_record()
    return record


@contextmanager
def _current_registered_release(
    postcondition: Any,
    pointer_path: Path,
    *,
    expected_semantic_receipt: SemanticValidationReceipt | None = None,
) -> Any:
    """Resolve one typed input and keep its exact lineage leased through use."""

    with ExitStack() as stack:
        if postcondition.receipt_backed_lease is not None:
            released = stack.enter_context(
                postcondition.receipt_backed_lease(
                    pointer_path,
                    expected_semantic_receipt=expected_semantic_receipt,
                )
            )
        else:
            released = postcondition.resolver(pointer_path)
        bundle = getattr(released, "bundle", None)
        if not isinstance(bundle, ArtifactRelease):
            raise TypeError("D3 typed resolver did not return an artifact release")
        if postcondition.receipt_backed_lease is None:
            stack.enter_context(current_artifact_release(bundle))
        yield bundle


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


@contextmanager
def _leased_analysis_release_certificate(
    perimeter: Mapping[str, list[str]],
    *,
    root: Path,
    verifier: Callable[[str | Path], dict[str, object]],
) -> Any:
    """Build claim records while every input identity remains leased."""

    records: list[dict[str, Any]] = []
    lineage: list[Path] = []
    with ExitStack() as stack:
        for relative, claim_ids in perimeter.items():
            normalized, path = resolve_repo_path(
                relative, root=root, label="claim input"
            )
            if not path.is_file():
                raise FileNotFoundError(f"D3 claim input is absent: {normalized}")
            postcondition = d3_release_postcondition(normalized)
            if postcondition is not None:
                bundle = stack.enter_context(
                    _current_registered_release(postcondition, path)
                )
                records.append(
                    _typed_release_record(
                        normalized,
                        claim_ids,
                        bundle,
                        root=root,
                        require_semantic_receipt=(
                            postcondition.receipt_backed_lease is not None
                        ),
                    )
                )
                lineage.extend(bundle.lineage_paths)
                continue
            stack.enter_context(
                current_artifacts([path], consumer="D3 claim input")
            )
            provenance_path, _provenance = _provenance_identity(
                path, verifier=verifier
            )
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
            lineage.extend((path, provenance_path))
        yield records, list(dict.fromkeys(lineage))


@contextmanager
def _analysis_release_certificate_context(
    *,
    root: Path = REPO_ROOT,
    specification_path: str | Path = "docs/specification-lock.json",
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> Any:
    """Hold specification and typed-input leases through certificate consumption."""

    specification_relative, resolved_specification = resolve_repo_path(
        specification_path,
        root=root,
        label="specification lock",
    )
    if not resolved_specification.is_file():
        raise FileNotFoundError(f"specification lock is absent: {specification_relative}")
    specification_lease = bind_file_lineage([resolved_specification])
    with current_file_lineage(specification_lease):
        specification = _load_json_object(
            resolved_specification, label="specification lock"
        )
        specification_hash = _validate_specification_identity(specification)
        perimeter = _active_claim_input_perimeter(specification)
        with _leased_analysis_release_certificate(
            perimeter.paths, root=root, verifier=verifier
        ) as (records, lineage):
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
                "code_semantic_fingerprint": semantic_code_fingerprint(
                    list(code_sources)
                ),
            }
            certificate["generation"] = generation_id(certificate)
            yield certificate, [resolved_specification, *lineage]


def build_analysis_release_certificate(
    *,
    root: Path = REPO_ROOT,
    specification_path: str | Path = "docs/specification-lock.json",
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> tuple[dict[str, Any], list[Path]]:
    """Audit every active claim input and build one leased D3 certificate."""

    with _analysis_release_certificate_context(
        root=root,
        specification_path=specification_path,
        verifier=verifier,
        code_sources=code_sources,
    ) as result:
        return result


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
    with _analysis_release_certificate_context(
        root=root,
        specification_path=specification_path,
        verifier=verifier,
        code_sources=code_sources,
    ) as (certificate, inputs):

        def validate_staged(paths: Mapping[str, Path]) -> None:
            reopened = _load_json_object(
                paths["certificate"], label="staged D3 certificate"
            )
            if (
                reopened != certificate
                or generation_id(reopened) != certificate["generation"]
            ):
                raise ValueError("staged D3 certificate does not round-trip exactly")

        bundle = publish_artifact_release(
            pointer_path=resolved_pointer,
            kind=ANALYSIS_RELEASE_POINTER_KIND,
            schema_version=ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
            filenames=ANALYSIS_RELEASE_FILENAMES,
            writers={
                "certificate": lambda path: _write_staged_json(path, certificate)
            },
            row_counts={"certificate": len(certificate["claim_inputs"])},
            code_sources=list(code_sources),
            inputs=inputs,
            notes=f"D3 analysis release {certificate['generation']}",
            validate_staged=validate_staged,
            write_pointer=write_json,
        )
        certificate_path = bundle.artifacts["certificate"]
        return AnalysisRelease(
            str(certificate["generation"]),
            bundle.pointer_path,
            certificate_path,
            certificate,
            root,
        )


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
    certificate = _load_json_object(path, label="D3 analysis-release certificate")
    if (
        certificate.get("schema_version") != ANALYSIS_RELEASE_SCHEMA_VERSION
        or certificate.get("kind") != ANALYSIS_RELEASE_KIND
        or certificate.get("status") != "pass"
        or certificate.get("generation") != generation_id(certificate)
    ):
        raise ValueError("D3 analysis-release certificate is stale or malformed")
    specification_relative, specification_path = resolve_repo_path(
        str(certificate.get("specification_path") or ""),
        root=root,
        label="specification lock",
    )
    specification = _load_json_object(
        specification_path, label="specification lock"
    )
    specification_hash = _validate_specification_identity(specification)
    perimeter = _active_claim_input_perimeter(specification)
    if (
        certificate.get("specification_path") != specification_relative
        or certificate.get("specification_lock_hash") != specification_hash
        or certificate.get("specification_stage") != specification["stage"]
        or certificate.get("executable_claim_ids")
        != list(perimeter.executable_claim_ids)
        or certificate.get("excluded_claim_count") != len(perimeter.excluded_claims)
        or certificate.get("excluded_claims") != list(perimeter.excluded_claims)
    ):
        raise ValueError("D3 analysis-release certificate disagrees with its specification")
    records = certificate.get("claim_inputs")
    if not isinstance(records, list) or len(records) != len(perimeter.paths):
        raise ValueError("D3 analysis-release certificate has an invalid claim-input perimeter")
    by_path = {
        str(record.get("path") or ""): record
        for record in records
        if isinstance(record, dict)
    }
    if set(by_path) != set(perimeter.paths):
        raise ValueError("D3 analysis-release certificate claim-input paths changed")
    for relative, claim_ids in perimeter.paths.items():
        record = by_path[relative]
        if record.get("claim_ids") != claim_ids:
            raise ValueError(f"D3 analysis-release claim binding changed: {relative}")
        _normalized, input_path = resolve_repo_path(
            relative, root=root, label="claim input"
        )
        postcondition = d3_release_postcondition(relative)
        if postcondition is None:
            provenance_path, _provenance = _provenance_identity(
                input_path, verifier=verifier
            )
            current = {
                "path": relative,
                "claim_ids": claim_ids,
                "bytes": input_path.stat().st_size,
                "content_sha256": portable_content_sha256(input_path),
                "provenance_path": provenance_path.relative_to(root).as_posix(),
                "provenance_sha256": file_sha256(provenance_path),
                **_reopen_artifact(input_path),
            }
            if current != record:
                raise ValueError(
                    f"D3 analysis-release flat input identity changed: {relative}"
                )
            continue
        receipt = None
        if postcondition.receipt_backed_lease is not None:
            receipt_record = record.get("semantic_validation")
            if (
                not isinstance(receipt_record, dict)
                or not isinstance(receipt_record.get("generation_id"), str)
                or not isinstance(receipt_record.get("validator_fingerprint"), str)
            ):
                raise ValueError(f"D3 typed release receipt is malformed: {relative}")
            receipt = SemanticValidationReceipt(
                receipt_record["generation_id"],
                receipt_record["validator_fingerprint"],
            )
        with _current_registered_release(
            postcondition,
            input_path,
            expected_semantic_receipt=receipt,
        ) as bundle:
            current = _typed_release_record(
                relative,
                claim_ids,
                bundle,
                root=root,
                require_semantic_receipt=postcondition.receipt_backed_lease is not None,
            )
        if current != record:
            raise ValueError(f"D3 typed release identity changed: {relative}")
    if (
        certificate.get("claim_input_count") != len(records)
        or certificate.get("claim_input_perimeter_sha256") != canonical_hash(records)
    ):
        raise ValueError("D3 analysis-release claim-input identity is stale")
    return AnalysisRelease(str(certificate["generation"]), None, path, certificate, root)


def resolve_current_analysis_release(
    *,
    pointer_path: str | Path = "data/processed/d3_analysis_release/current.json",
    root: Path = REPO_ROOT,
    verifier: Callable[[str | Path], dict[str, object]] = verify,
    code_sources: tuple[str, ...] = ANALYSIS_RELEASE_CODE_SOURCES,
) -> AnalysisRelease:
    """Resolve the marker-last D3 pointer through the one timestamp freshness check."""

    relative, resolved_pointer = resolve_repo_path(
        pointer_path, root=root, label="D3 release pointer"
    )
    pointer = _load_json_object(resolved_pointer, label="D3 release pointer")
    bundle_generation = str(pointer.get("generation_id") or "")
    record = (pointer.get("artifacts") or {}).get("certificate")
    if not bundle_generation or not isinstance(record, dict):
        raise ValueError("D3 release pointer is malformed")
    certificate_path = (
        resolved_pointer.parent
        / "generations"
        / bundle_generation
        / str(record.get("filename") or "certificate.json")
    )
    certificate = _load_json_object(certificate_path, label="D3 analysis panel")
    passed, detail = check_canonical_panel_freshness(
        root=root,
        pointer=Path(relative),
        specification=Path(
            str(certificate.get("specification_path") or SPECIFICATION_LOCK)
        ),
    )
    if not passed:
        raise RuntimeError(f"D3 analysis panel is not current: {detail}")
    generation = str(certificate.get("generation") or "")
    if not generation or certificate.get("claim_inputs") is None:
        raise ValueError("D3 analysis panel manifest is malformed")
    return AnalysisRelease(
        generation,
        resolved_pointer,
        certificate_path,
        certificate,
        root,
    )
