"""One release boundary for fitted-model artifacts and their D3 identity."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ddvc.artifact_release import file_sha256
from ddvc.analysis_release import resolve_analysis_release, resolve_repo_path
from ddvc.model_registry import FITTED_MODEL_ARTIFACT_ROLES, MODEL_RUN_ARTIFACT_ROLES
from ddvc.paths import REPO_ROOT
from ddvc.provenance import current_artifacts, portable_content_sha256, sidecar_path
from ddvc.tables import write_exhibit, write_panel


_SPEC_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ModelArtifactContext:
    """The exact analysis generation every artifact from one model run consumes."""

    d3_generation: str
    d3_certificate_relative: str
    d3_certificate_path: Path
    d3_certificate_bytes: int
    d3_certificate_sha256: str
    d3_certificate_provenance_path: Path
    d3_certificate_provenance_sha256: str
    d3_input_relatives: frozenset[str]
    d3_input_records: Mapping[str, Mapping[str, object]]


def model_artifact_context(
    *,
    root: Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
) -> ModelArtifactContext:
    """Resolve and verify the D3 certificate injected by the E0/F orchestrator."""

    env = os.environ if environment is None else environment
    certificate_value = str(env.get("DDVC_D3_CERTIFICATE") or "")
    generation = str(env.get("DDVC_D3_GENERATION") or "")
    if not certificate_value or not generation:
        raise RuntimeError("model runner lacks its DDVC_D3_CERTIFICATE/DDVC_D3_GENERATION binding")
    certificate_relative, certificate_path = resolve_repo_path(
        certificate_value,
        root=root,
        label="model-run D3 certificate",
    )
    with current_artifacts(
        [certificate_path], consumer="model-run D3 certificate context"
    ):
        release = resolve_analysis_release(
            certificate_path=certificate_relative,
            root=root,
        )
        if release.generation != generation:
            raise ValueError(
                "model-run D3 generation disagrees with its certificate: "
                f"{generation} != {release.generation}"
            )
        provenance = sidecar_path(release.certificate_path)
        return ModelArtifactContext(
            d3_generation=release.generation,
            d3_certificate_relative=certificate_relative,
            d3_certificate_path=release.certificate_path,
            d3_certificate_bytes=release.certificate_path.stat().st_size,
            d3_certificate_sha256=file_sha256(release.certificate_path),
            d3_certificate_provenance_path=provenance,
            d3_certificate_provenance_sha256=file_sha256(provenance),
            d3_input_relatives=frozenset(
                path.relative_to(root).as_posix() for path in release.input_paths
            ),
            d3_input_records={
                str(record["path"]): record
                for record in release.certificate["claim_inputs"]
            },
        )


def assert_model_artifact_certificate_identity(
    context: ModelArtifactContext,
    certificate_path: str | Path,
) -> None:
    """Require a leased certificate pair to equal the context's verified identity."""

    certificate = Path(certificate_path)
    provenance = sidecar_path(certificate)
    observed = {
        "path": certificate.resolve(),
        "bytes": certificate.stat().st_size,
        "sha256": file_sha256(certificate),
        "provenance_path": provenance.resolve(),
        "provenance_sha256": file_sha256(provenance),
    }
    expected = {
        "path": context.d3_certificate_path.resolve(),
        "bytes": context.d3_certificate_bytes,
        "sha256": context.d3_certificate_sha256,
        "provenance_path": context.d3_certificate_provenance_path.resolve(),
        "provenance_sha256": context.d3_certificate_provenance_sha256,
    }
    mismatched = sorted(
        field for field, value in observed.items() if value != expected[field]
    )
    if mismatched:
        raise ValueError(
            "model-run D3 certificate changed between verification and lease admission: "
            f"fields={mismatched}"
        )


@contextmanager
def require_released_model_inputs(
    context: ModelArtifactContext,
    inputs: Sequence[str | Path],
    *,
    root: Path = REPO_ROOT,
    consumer: str,
):
    """Lease every model input as an exact, current member of the D3 release."""

    resolved_root = root.resolve()
    resolved_inputs: list[Path] = []
    relative_inputs: list[str] = []
    for value in inputs:
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not resolved.is_relative_to(resolved_root):
                raise ValueError(f"{consumer} input escapes the repository: {value}")
            relative = resolved.relative_to(resolved_root).as_posix()
        else:
            relative, resolved = resolve_repo_path(
                candidate,
                root=root,
                label=f"{consumer} input",
            )
        relative_inputs.append(relative)
        resolved_inputs.append(resolved)
    missing = sorted(set(relative_inputs) - context.d3_input_relatives)
    if missing:
        raise ValueError(f"{consumer} input is outside the bound D3 release: {missing}")
    with current_artifacts(resolved_inputs, consumer=consumer):
        for relative, resolved in zip(
            relative_inputs, resolved_inputs, strict=True
        ):
            record = context.d3_input_records.get(relative)
            if not isinstance(record, Mapping):
                raise ValueError(
                    f"{consumer} input lacks an exact D3 identity record: {relative}"
                )
            if record.get("input_kind") == "release_pointer":
                raise ValueError(
                    f"{consumer} typed release requires its canonical typed lease: "
                    f"{relative}"
                )
            provenance = sidecar_path(resolved)
            try:
                provenance_relative = provenance.resolve().relative_to(
                    resolved_root
                ).as_posix()
            except ValueError as error:
                raise ValueError(
                    f"{consumer} provenance escapes the repository: {relative}"
                ) from error
            observed = {
                "bytes": resolved.stat().st_size,
                "content_sha256": portable_content_sha256(resolved),
                "provenance_path": provenance_relative,
                "provenance_sha256": file_sha256(provenance),
            }
            mismatched = sorted(
                field
                for field, value in observed.items()
                if record.get(field) != value
            )
            if mismatched:
                raise ValueError(
                    f"{consumer} input differs from its bound D3 identity: "
                    f"{relative}; fields={mismatched}"
                )
        yield resolved_inputs


def _spec_token(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    token = _SPEC_TOKEN.sub("-", str(value).strip().lower()).strip("-")
    return token


def attach_spec_ids(
    frame: pd.DataFrame,
    *,
    prefix: str,
    columns: Sequence[str],
) -> pd.DataFrame:
    """Attach stable, human-readable specification IDs from semantic fit fields."""

    if frame.empty:
        raise ValueError("fitted model artifact cannot be empty")
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"specification identity columns are absent: {missing}")
    prefix_token = _spec_token(prefix)
    if not prefix_token:
        raise ValueError("specification id prefix is empty")
    output = frame.copy()
    identifiers: list[str] = []
    semantic_rows: dict[str, tuple[str, ...]] = {}
    for row in output.loc[:, list(columns)].itertuples(index=False, name=None):
        semantic = tuple(_spec_token(value) for value in row)
        identity = ".".join([prefix_token, *[value for value in semantic if value]])
        prior = semantic_rows.setdefault(identity, semantic)
        if prior != semantic:
            raise ValueError(f"specification id collision: {identity}")
        identifiers.append(identity)
    output.insert(0, "spec_id", identifiers)
    return output


def _validate_model_frame(frame: pd.DataFrame, *, role: str) -> None:
    if role not in MODEL_RUN_ARTIFACT_ROLES:
        raise ValueError(f"model artifact role is invalid: {role}")
    has_spec_id = "spec_id" in frame.columns
    if role in FITTED_MODEL_ARTIFACT_ROLES:
        if not has_spec_id or frame.empty:
            raise ValueError("fitted model artifact requires nonempty spec_id rows")
        values = frame["spec_id"]
        if values.isna().any() or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("fitted model artifact contains an invalid spec_id")
    elif has_spec_id:
        raise ValueError("support artifact cannot contain spec_id")


def write_model_exhibit(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    role: str,
    context: ModelArtifactContext,
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str,
) -> Path:
    """Write one validated model artifact with the exact D3 certificate as an input."""

    _validate_model_frame(frame, role=role)
    d3_input = context.d3_certificate_path
    bound_inputs = [d3_input, *[value for value in inputs if Path(value) != d3_input]]
    return write_exhibit(
        frame,
        path,
        code_sources=["src/ddvc/model_artifacts.py", *code_sources],
        inputs=bound_inputs,
        notes=notes,
        preinstall_validator=lambda _path: _validate_model_frame(frame, role=role),
    )


def write_model_panel(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    role: str,
    context: ModelArtifactContext,
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str,
) -> Path:
    """Write a large validated model panel with the exact D3 certificate bound."""

    _validate_model_frame(frame, role=role)
    d3_input = context.d3_certificate_path
    bound_inputs = [d3_input, *[value for value in inputs if Path(value) != d3_input]]
    return write_panel(
        frame,
        path,
        code_sources=["src/ddvc/model_artifacts.py", *code_sources],
        inputs=bound_inputs,
        notes=notes,
        preinstall_validator=lambda _path: _validate_model_frame(frame, role=role),
    )
