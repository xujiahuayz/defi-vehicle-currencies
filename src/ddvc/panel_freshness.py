"""Cheap timestamp freshness for the one canonical analysis-panel pointer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ddvc.model_registry import claim_execution_perimeter
from ddvc.paths import REPO_ROOT


CANONICAL_PANEL_POINTER = Path("data/processed/d3_analysis_release/current.json")
SPECIFICATION = Path("docs/specification-lock.json")


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def canonical_panel_inputs(
    specification: Mapping[str, Any],
    *,
    root: Path = REPO_ROOT,
) -> tuple[Path, ...]:
    """Return the exact, execution-open inputs named by the committed design."""

    perimeter = claim_execution_perimeter(specification)
    paths = {
        root / str(value)
        for claim in perimeter.executable_claims
        for value in claim.get("inputs", [])
    }
    if not paths:
        raise ValueError("specification has no execution-open panel inputs")
    return tuple(sorted(paths))


def check_canonical_panel_freshness(
    *,
    root: Path = REPO_ROOT,
    pointer: Path = CANONICAL_PANEL_POINTER,
    specification: Path = SPECIFICATION,
) -> tuple[bool, str]:
    """Check existence and mtimes only; do not recompute hashes or certificates."""

    panel_path = root / pointer
    specification_path = root / specification
    try:
        payload = _read_object(specification_path, label="specification")
        inputs = canonical_panel_inputs(payload, root=root)
    except (OSError, TypeError, ValueError) as error:
        return False, str(error)
    missing = [path.relative_to(root).as_posix() for path in inputs if not path.is_file()]
    if not panel_path.is_file():
        missing.insert(0, pointer.as_posix())
    if missing:
        return False, f"missing={missing}"
    panel_mtime = panel_path.stat().st_mtime_ns
    newest = max(inputs, key=lambda path: path.stat().st_mtime_ns)
    newest_mtime = newest.stat().st_mtime_ns
    passed = panel_mtime >= newest_mtime
    return passed, (
        f"panel={pointer.as_posix()}; inputs={len(inputs)}; "
        f"newest_input={newest.relative_to(root).as_posix()}; "
        f"status={'fresh' if passed else 'stale'}"
    )
