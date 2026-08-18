"""Direct validation for committed presentation-source artifacts."""

from __future__ import annotations

from pathlib import Path


def require_presentation_source(path: Path) -> None:
    """Require the direct generated input used by a table, figure, or slide."""

    if not path.is_file():
        raise FileNotFoundError(f"presentation source is missing: {path}")
