"""Portable validation for committed presentation-source artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.provenance import sidecar_path


def require_current_presentation_source(path: Path) -> Path:
    """Require the current payload and its lightweight downstream sidecar.

    The canonical panel owner is responsible for the single freshness decision.
    Presentation builders only need a present payload and sidecar; they do not
    reopen or re-certify the upstream graph.
    """

    provenance_path = sidecar_path(path)
    if not path.is_file() or not provenance_path.is_file():
        raise FileNotFoundError(
            f"presentation payload or provenance is missing: {path}"
        )
    json.loads(provenance_path.read_text(encoding="utf-8"))
    return provenance_path
