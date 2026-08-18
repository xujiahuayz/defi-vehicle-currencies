"""Direct-path input checks for the research workflow."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from ddvc.paths import REPO_ROOT
from ddvc.runtime import serialized_read_installs


def _unique_paths(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(Path(path) for path in paths))


def _stat_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@contextmanager
def current_inputs(paths: Iterable[str | Path], *, consumer: str):
    """Lease required files for one read without a parallel metadata layer."""

    selected = _unique_paths(paths)
    if not selected:
        raise ValueError("input lease requires at least one path")
    with serialized_read_installs(selected, allow_missing=True):
        missing = [path for path in selected if not path.is_file()]
        if missing:
            detail = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"{consumer} requires missing input(s): {detail}")
        before = {path: _stat_identity(path) for path in selected}
        yield selected
        changed = [
            path
            for path in selected
            if not path.is_file() or _stat_identity(path) != before[path]
        ]
        if changed:
            detail = ", ".join(str(path) for path in changed)
            raise RuntimeError(f"{consumer} input(s) changed while being read: {detail}")


def describe_file(path: str | Path) -> dict[str, object]:
    """Return human-readable file facts used in diagnostics, not identity proofs."""

    selected = Path(path)
    stat = selected.stat()
    try:
        relative = str(selected.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        relative = str(selected)
    return {
        "path": relative,
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }
