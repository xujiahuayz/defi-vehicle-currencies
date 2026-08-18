"""Small validation and writing helpers for analysis outputs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ddvc.paths import REPO_ROOT
from ddvc.tables import write_exhibit, write_panel
from ddvc.workflow import current_inputs


MODEL_RUN_ARTIFACT_ROLES = {"result", "support", "diagnostic", "panel", "resampling"}
FITTED_MODEL_ARTIFACT_ROLES = {"result", "diagnostic"}
_SPEC_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ModelArtifactContext:
    """Direct-path analysis context retained for a stable caller API."""

    root: Path = REPO_ROOT


def model_artifact_context(
    *, root: Path = REPO_ROOT, environment: Mapping[str, str] | None = None
) -> ModelArtifactContext:
    del environment
    return ModelArtifactContext(root=root)


@contextmanager
def require_released_model_inputs(
    context: ModelArtifactContext,
    inputs: Sequence[str | Path],
    *,
    root: Path = REPO_ROOT,
    consumer: str,
):
    """Lease direct analysis inputs while the model reads them."""

    del context
    resolved = [Path(value) if Path(value).is_absolute() else root / value for value in inputs]
    with current_inputs(resolved, consumer=consumer):
        yield resolved


def _spec_token(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return _SPEC_TOKEN.sub("-", str(value).strip().lower()).strip("-")


def attach_spec_ids(
    frame: pd.DataFrame, *, prefix: str, columns: Sequence[str]
) -> pd.DataFrame:
    """Attach readable specification labels from substantive fit fields."""

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
        label = ".".join([prefix_token, *[value for value in semantic if value]])
        prior = semantic_rows.setdefault(label, semantic)
        if prior != semantic:
            raise ValueError(f"specification id collision: {label}")
        identifiers.append(label)
    output.insert(0, "spec_id", identifiers)
    return output


def _validate_model_frame(frame: pd.DataFrame, *, role: str) -> None:
    if role not in MODEL_RUN_ARTIFACT_ROLES:
        raise ValueError(f"model artifact role is invalid: {role}")
    has_spec_id = "spec_id" in frame.columns
    if role in FITTED_MODEL_ARTIFACT_ROLES:
        if not has_spec_id or frame.empty:
            raise ValueError("fitted model artifact requires nonempty spec_id rows")
        if frame["spec_id"].isna().any() or any(
            not isinstance(value, str) or not value for value in frame["spec_id"]
        ):
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
    del context
    _validate_model_frame(frame, role=role)
    return write_exhibit(frame, path, code_sources=code_sources, inputs=inputs, notes=notes)


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
    del context
    _validate_model_frame(frame, role=role)
    return write_panel(frame, path, code_sources=code_sources, inputs=inputs, notes=notes)
