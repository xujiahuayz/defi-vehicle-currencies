"""Portable validation for committed presentation-source artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.paths import REPO_ROOT
from ddvc.provenance import (
    code_fingerprint,
    describe_artifact_payload,
    sidecar_path,
)


def require_certified_presentation_source(path: Path) -> Path:
    """Validate a committed payload and producer without reopening host-only inputs.

    The data-owning checkout certifies the upstream perimeter before committing an
    exhibit and sidecar. A presentation checkout may not hold those large inputs, so
    it verifies the exact committed payload, its producer code, and its declared row
    count. Downstream provenance includes both this payload and its sidecar.
    """

    provenance_path = sidecar_path(path)
    if not path.is_file() or not provenance_path.is_file():
        raise FileNotFoundError(
            f"presentation payload or provenance is missing: {path}"
        )
    record = json.loads(provenance_path.read_text(encoding="utf-8"))
    relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    if record.get("artefact") != relative:
        raise ValueError(f"presentation provenance names another artifact: {path}")
    observed_identity = describe_artifact_payload(path, artefact=path)
    if record.get("payload_identity") != observed_identity:
        raise ValueError(f"presentation payload differs from its certificate: {path}")
    sources = record.get("code_sources")
    if not isinstance(sources, list) or code_fingerprint(sources) != record.get(
        "code_fingerprint"
    ):
        raise ValueError(f"presentation producer differs from its certificate: {path}")
    physical_rows = observed_identity.get("rows")
    if physical_rows is not None and record.get("rows") != physical_rows:
        raise ValueError(f"presentation row count differs from its certificate: {path}")
    return provenance_path
