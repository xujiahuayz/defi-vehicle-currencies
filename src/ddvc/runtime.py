"""Runtime guards for long or artifact-producing research jobs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_MAX_WORKERS = 8


def bounded_workers(requested: int, *, maximum: int = DEFAULT_MAX_WORKERS) -> int:
    """Clamp user-requested concurrency to a positive, explicit process bound."""
    if maximum < 1:
        raise ValueError("maximum worker count must be positive")
    return min(maximum, max(1, requested))


@contextmanager
def staged_output(target: Path) -> Iterator[Path]:
    """Yield a unique sibling path without installing it automatically."""

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
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def atomic_output(target: Path) -> Iterator[Path]:
    """Yield a unique sibling path and atomically install it on success."""

    with staged_output(target) as temporary:
        yield temporary
        temporary.replace(target)


@contextmanager
def serialized_output_install(target: Path) -> Iterator[None]:
    """Serialize the short publication boundary for one resolved target path."""

    lock_root = Path(tempfile.gettempdir()) / "ddvc-artifact-install-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lexical_target = target.parent.resolve() / target.name
    identity = hashlib.sha256(str(lexical_target).encode()).hexdigest()
    handle = (lock_root / f"{identity}.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


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


def _inclusive_intervals_overlap(
    first_start: int,
    first_end: int,
    second_start: int,
    second_end: int,
) -> bool:
    return first_start <= second_end and second_start <= first_end


@contextmanager
def exclusive_interval_job(
    lock_root: Path,
    start: int,
    end: int,
    *,
    job: str,
) -> Iterator[None]:
    """Own one inclusive integer interval while refusing concurrent overlaps.

    A short registry lock makes stale-owner cleanup, overlap inspection, and owner
    publication atomic. Each live owner then holds its own file lock, so disjoint
    intervals can proceed independently after leaving the registry boundary.
    """

    if isinstance(start, bool) or isinstance(end, bool):
        raise TypeError("interval bounds must be integers")
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("interval bounds must be integers")
    if start > end:
        raise ValueError(f"interval start {start} exceeds end {end}")
    if not job.strip():
        raise ValueError("interval job name must be non-empty")

    lock_root.mkdir(parents=True, exist_ok=True)
    registry_path = lock_root / ".registry.lock"
    registry_handle = registry_path.open("a+")
    owner_handle = None
    owner_path = None
    registry_locked = False
    try:
        fcntl.flock(registry_handle.fileno(), fcntl.LOCK_EX)
        registry_locked = True
        for candidate_path in sorted(lock_root.glob("*.owner.json")):
            try:
                candidate_handle = candidate_path.open("a+", encoding="utf-8")
            except FileNotFoundError:
                continue
            try:
                try:
                    fcntl.flock(
                        candidate_handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except BlockingIOError:
                    candidate_handle.seek(0)
                    try:
                        candidate = json.load(candidate_handle)
                        candidate_start = int(candidate["start"])
                        candidate_end = int(candidate["end"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise RuntimeError(
                            f"{job} cannot inspect active interval owner metadata: "
                            f"{candidate_path.name}"
                        ) from exc
                    if _inclusive_intervals_overlap(
                        start,
                        end,
                        candidate_start,
                        candidate_end,
                    ):
                        active_job = candidate.get("job", "unknown job")
                        active_pid = candidate.get("pid", "unknown")
                        active_started = candidate.get("started_at_utc", "unknown")
                        raise RuntimeError(
                            f"{job} interval [{start}, {end}] overlaps active "
                            f"{active_job} interval [{candidate_start}, {candidate_end}]; "
                            f"pid={active_pid}; started_at_utc={active_started}"
                        )
                else:
                    candidate_path.unlink(missing_ok=True)
                    fcntl.flock(candidate_handle.fileno(), fcntl.LOCK_UN)
            finally:
                candidate_handle.close()

        descriptor, owner_name = tempfile.mkstemp(
            dir=lock_root,
            prefix=f"range-{start}-{end}-",
            suffix=".owner.json",
        )
        owner_path = Path(owner_name)
        owner_handle = os.fdopen(descriptor, "w+", encoding="utf-8")
        fcntl.flock(owner_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner = {
            "argv": sys.argv,
            "end": end,
            "job": job,
            "pid": os.getpid(),
            "start": start,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        json.dump(owner, owner_handle, sort_keys=True)
        owner_handle.write("\n")
        owner_handle.flush()
        os.fsync(owner_handle.fileno())
        fcntl.flock(registry_handle.fileno(), fcntl.LOCK_UN)
        registry_locked = False
        yield
    finally:
        if owner_handle is not None:
            if not registry_locked:
                fcntl.flock(registry_handle.fileno(), fcntl.LOCK_EX)
                registry_locked = True
            if owner_path is not None:
                owner_path.unlink(missing_ok=True)
            fcntl.flock(owner_handle.fileno(), fcntl.LOCK_UN)
            owner_handle.close()
        if registry_locked:
            fcntl.flock(registry_handle.fileno(), fcntl.LOCK_UN)
        registry_handle.close()


@contextmanager
def interruptible_process_pool(max_workers: int) -> Iterator[ProcessPoolExecutor]:
    """Terminate worker processes promptly when a long reduction is interrupted."""
    executor = ProcessPoolExecutor(max_workers=max_workers)
    try:
        yield executor
    except BaseException:
        terminate_workers = getattr(executor, "terminate_workers", None)
        if terminate_workers is not None:
            terminate_workers()
        else:
            processes = list(getattr(executor, "_processes", {}).values())
            executor.shutdown(wait=False, cancel_futures=True)
            for process in processes:
                if process.is_alive():
                    process.terminate()
            for process in processes:
                process.join(timeout=1)
        raise
    else:
        executor.shutdown(wait=True)


@contextmanager
def interruptible_thread_pool(max_workers: int) -> Iterator[ThreadPoolExecutor]:
    """Cancel queued work and wait for active calls before failure escapes."""

    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        yield executor
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
