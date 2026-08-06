"""Runtime guards for long or artifact-producing research jobs."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@contextmanager
def atomic_output(target: Path) -> Iterator[Path]:
    """Yield a unique sibling path and atomically install it on success."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_job(lock_path: Path, *, job: str) -> Iterator[None]:
    """Hold a non-blocking process lock and record the current owner for diagnosis."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            owner = handle.read().strip() or "owner metadata unavailable"
            raise RuntimeError(f"{job} is already running: {owner}") from exc
        owner = {
            "argv": sys.argv,
            "job": job,
            "pid": os.getpid(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(owner, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
