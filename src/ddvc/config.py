"""Small, dependency-free configuration readers shared by data providers."""

from __future__ import annotations

import os
from pathlib import Path

from ddvc.paths import REPO_ROOT


def dotenv_path() -> Path | None:
    """Resolve the local or runner-supplied project environment file."""
    local = REPO_ROOT / ".env"
    if local.is_file():
        return local
    supplied = os.getenv("DDVC_ENV_FILE")
    if not supplied:
        return None
    candidate = Path(supplied)
    return candidate if candidate.is_file() else None


def dotenv_value(*names: str) -> str:
    """Read the first named value from the project environment file."""
    path = dotenv_path()
    if path is None:
        return ""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return next((values[name] for name in names if values.get(name)), "")
