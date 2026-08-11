"""One release boundary for fitted-model artifacts and their D3 identity."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from ddvc.analysis_release import resolve_analysis_release, resolve_repo_path
from ddvc.model_registry import FITTED_MODEL_ARTIFACT_ROLES, MODEL_RUN_ARTIFACT_ROLES
from ddvc.paths import REPO_ROOT
from ddvc.tables import write_exhibit


_SPEC_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ModelArtifactContext:
    """The exact analysis generation every artifact from one model run consumes."""

    d3_generation: str
    d3_certificate_relative: str
    d3_certificate_path: Path


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
    certificate_relative, _certificate_path = resolve_repo_path(
        certificate_value,
        root=root,
        label="model-run D3 certificate",
    )
    release = resolve_analysis_release(
        certificate_path=certificate_relative,
        root=root,
    )
    if release.generation != generation:
        raise ValueError(
            "model-run D3 generation disagrees with its certificate: "
            f"{generation} != {release.generation}"
        )
    return ModelArtifactContext(
        d3_generation=release.generation,
        d3_certificate_relative=certificate_relative,
        d3_certificate_path=release.certificate_path,
    )


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
