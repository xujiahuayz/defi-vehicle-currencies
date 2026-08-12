"""Runtime guards for long or artifact-producing research jobs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_MAX_WORKERS = 8
_FILE_DIGEST_CACHE_MAX = 128
_FILE_DIGEST_CACHE: OrderedDict[tuple[int, int, int, int, int], str] = OrderedDict()
_FILE_DIGEST_CACHE_LOCK = threading.Lock()
_HELD_ARTIFACT_LOCKS = threading.local()
_ACTIVE_READ_SOURCES: ContextVar[frozenset[Path]] = ContextVar(
    "ddvc_active_read_sources", default=frozenset()
)


def bounded_workers(requested: int, *, maximum: int = DEFAULT_MAX_WORKERS) -> int:
    """Clamp user-requested concurrency to a positive, explicit process bound."""
    if maximum < 1:
        raise ValueError("maximum worker count must be positive")
    return min(maximum, max(1, requested))


def file_sha256(path: Path) -> str:
    """Hash exact file bytes once per unchanged filesystem identity."""

    source = Path(path)
    before = source.stat()
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    with _FILE_DIGEST_CACHE_LOCK:
        cached = _FILE_DIGEST_CACHE.get(identity)
        if cached is not None:
            _FILE_DIGEST_CACHE.move_to_end(identity)
            return cached
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    after = source.stat()
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise RuntimeError(f"file changed while it was hashed: {source}")
    value = digest.hexdigest()
    with _FILE_DIGEST_CACHE_LOCK:
        _FILE_DIGEST_CACHE[identity] = value
        _FILE_DIGEST_CACHE.move_to_end(identity)
        while len(_FILE_DIGEST_CACHE) > _FILE_DIGEST_CACHE_MAX:
            _FILE_DIGEST_CACHE.popitem(last=False)
    return value


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
        with serialized_output_install(target):
            temporary.replace(target)


def _lexical_path(path: Path) -> Path:
    """Return an absolute lexical identity without erasing symlink ancestors."""

    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _source_paths(
    paths: Iterable[Path], *, allow_missing: bool = False
) -> tuple[Path, ...]:
    selected: list[Path] = []
    for raw in paths:
        path = _lexical_path(Path(raw))
        selected.append(path)
        if path.exists():
            selected.append(path.resolve(strict=True))
        elif path.is_symlink():
            raise FileNotFoundError(f"source lease path is a dangling symlink: {path}")
        elif not allow_missing:
            raise FileNotFoundError(f"source lease path is missing: {path}")
        else:
            # Resolve every existing symlink ancestor even when the leaf has not
            # been created.  Without this identity, ``alias/new`` and
            # ``real/new`` can bypass one another's locks.
            for ancestor in path.parents:
                if ancestor.is_symlink():
                    try:
                        ancestor.resolve(strict=True)
                    except FileNotFoundError as error:
                        raise FileNotFoundError(
                            f"source lease path has a dangling symlink ancestor: {path}"
                        ) from error
            selected.append(path.resolve(strict=False))
    return tuple(dict.fromkeys(selected))


def _output_lock_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    selected: list[Path] = []
    for raw in paths:
        path = _lexical_path(Path(raw))
        selected.append(path)
        # Non-strict resolution gives an as-yet absent output under a symlinked
        # ancestor the same lock identity as publication through its referent.
        selected.append(path.resolve(strict=False))
    return tuple(dict.fromkeys(selected))


@dataclass(frozen=True)
class ArtifactTransactionLease:
    """The exact source and output identities owned by one transaction."""

    sources: tuple[Path, ...]
    outputs: tuple[Path, ...]
    output_lock_paths: tuple[Path, ...]

    def assert_output_identities(self) -> None:
        """Reject a symlink or ancestor retarget before publication commits."""

        if _output_lock_paths(self.outputs) != self.output_lock_paths:
            raise RuntimeError("output symlink changed during artifact transaction")


def source_lock_paths(
    paths: Iterable[Path], *, allow_missing: bool = False
) -> tuple[Path, ...]:
    """Expose the canonical read identities used by the lock registry."""

    return _source_paths(paths, allow_missing=allow_missing)


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _artifact_lock_root() -> Path:
    root = Path(tempfile.gettempdir()) / "ddvc-artifact-lock-registry"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_lock_registry(path: Path, rows: list[dict[str, object]]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(rows, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _owner_is_live(path: Path) -> bool:
    try:
        handle = path.open("a+")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def _read_live_lock_rows(registry: Path) -> list[dict[str, object]]:
    try:
        rows = json.loads(registry.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        rows = []
    if not isinstance(rows, list):
        rows = []
    live: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        owner = Path(str(row.get("owner", "")))
        if owner.is_file() and _owner_is_live(owner):
            live.append(row)
        else:
            owner.unlink(missing_ok=True)
    return live


def _lock_conflicts(
    requested: Mapping[Path, int], existing: Iterable[dict[str, object]]
) -> bool:
    for row in existing:
        try:
            path = Path(str(row["path"]))
            mode = int(row["mode"])
        except (KeyError, TypeError, ValueError):
            continue
        for target, requested_mode in requested.items():
            if _paths_overlap(target, path) and (
                mode == fcntl.LOCK_EX or requested_mode == fcntl.LOCK_EX
            ):
                return True
    return False


@contextmanager
def _serialized_artifact_locks(
    exact_modes: Mapping[Path, int],
) -> Iterator[None]:
    """Own exact paths and conflict with owners of every ancestor or descendant."""

    exact = {_lexical_path(Path(path)): mode for path, mode in exact_modes.items()}
    if any(
        _paths_overlap(target, source)
        for target, mode in exact.items()
        if mode == fcntl.LOCK_EX
        for source in _ACTIVE_READ_SOURCES.get()
    ):
        raise RuntimeError("publication target overlaps a leased source")
    held = getattr(_HELD_ARTIFACT_LOCKS, "counts", None)
    if held is None:
        held = {}
        _HELD_ARTIFACT_LOCKS.counts = held
    reused: list[str] = []
    requested: dict[Path, int] = {}
    for path, mode in exact.items():
        overlapping = [
            (Path(identity), prior_mode)
            for identity, (_count, prior_mode) in held.items()
            if _paths_overlap(Path(identity), path)
        ]
        covering = [
            (identity, prior_mode)
            for identity, prior_mode in overlapping
            if identity == path or identity in path.parents
        ]
        if covering:
            if any(mode > prior_mode for _prior, prior_mode in covering):
                raise RuntimeError(f"nested artifact lock cannot upgrade {path}")
            identity = str(covering[0][0])
            count, prior_mode = held[identity]
            held[identity] = (count + 1, prior_mode)
            reused.append(identity)
        else:
            if any(
                mode == fcntl.LOCK_EX or prior_mode == fcntl.LOCK_EX
                for _prior, prior_mode in overlapping
            ):
                raise RuntimeError(
                    f"nested artifact lock cannot expand exclusive scope to {path}"
                )
            requested[path] = mode
    lock_root = _artifact_lock_root()
    owner = lock_root / f"owner-{os.getpid()}-{uuid.uuid4().hex}.lock"
    token = uuid.uuid4().hex
    registry = lock_root / "leases.json"
    owner_handle = None
    coordinator = None
    registered = False
    try:
        if requested:
            owner_handle = owner.open("a+")
            coordinator = (lock_root / "coordinator.lock").open("a+")
            fcntl.flock(owner_handle.fileno(), fcntl.LOCK_EX)
            while True:
                fcntl.flock(coordinator.fileno(), fcntl.LOCK_EX)
                try:
                    rows = _read_live_lock_rows(registry)
                    if not _lock_conflicts(requested, rows):
                        rows.extend(
                            {
                                "mode": int(mode),
                                "owner": str(owner),
                                "path": str(path),
                                "token": token,
                            }
                            for path, mode in requested.items()
                        )
                        registered = True
                    _atomic_lock_registry(registry, rows)
                finally:
                    fcntl.flock(coordinator.fileno(), fcntl.LOCK_UN)
                if registered:
                    break
                time.sleep(0.01)
            for path, mode in requested.items():
                held[str(path)] = (1, mode)
        yield
    finally:
        for identity in reversed(reused):
            count, mode = held[identity]
            if count > 1:
                held[identity] = (count - 1, mode)
            else:
                held.pop(identity, None)
        for path in requested:
            held.pop(str(path), None)
        try:
            if registered and coordinator is not None:
                fcntl.flock(coordinator.fileno(), fcntl.LOCK_EX)
                try:
                    rows = [
                        row
                        for row in _read_live_lock_rows(registry)
                        if row.get("token") != token
                    ]
                    _atomic_lock_registry(registry, rows)
                finally:
                    fcntl.flock(coordinator.fileno(), fcntl.LOCK_UN)
        finally:
            if owner_handle is not None:
                fcntl.flock(owner_handle.fileno(), fcntl.LOCK_UN)
                owner_handle.close()
                owner.unlink(missing_ok=True)
            if coordinator is not None:
                coordinator.close()


@contextmanager
def serialized_output_installs(targets: Iterable[Path]) -> Iterator[None]:
    """Own exact paths and conflict with owners of every ancestor or descendant."""

    exact = {path: fcntl.LOCK_EX for path in _output_lock_paths(targets)}
    with _serialized_artifact_locks(exact):
        yield


@contextmanager
def serialized_output_install(target: Path) -> Iterator[None]:
    """Serialize one publication path against ancestor and descendant owners."""

    with serialized_output_installs((target,)):
        yield


@contextmanager
def serialized_read_installs(
    targets: Iterable[Path], *, allow_missing: bool = False
) -> Iterator[None]:
    """Lease source identities, including declared absences, through a complete read."""

    requested = tuple(_lexical_path(Path(path)) for path in targets)
    selected = _source_paths(requested, allow_missing=allow_missing)
    if not selected:
        raise ValueError("source lease requires at least one path")
    with _serialized_artifact_locks(
        {path: fcntl.LOCK_SH for path in selected}
    ):
        if _source_paths(requested, allow_missing=allow_missing) != selected:
            raise RuntimeError("source symlink changed while its lease was acquired")
        token = _ACTIVE_READ_SOURCES.set(
            frozenset((*_ACTIVE_READ_SOURCES.get(), *selected))
        )
        try:
            yield
        finally:
            _ACTIVE_READ_SOURCES.reset(token)


@contextmanager
def serialized_artifact_transaction(
    *, sources: Iterable[Path], outputs: Iterable[Path]
) -> Iterator[ArtifactTransactionLease]:
    """Lease exact sources and own exact outputs under one ordered lock perimeter."""

    requested_sources = tuple(_lexical_path(Path(path)) for path in sources)
    selected_sources = _source_paths(requested_sources)
    selected_outputs = tuple(dict.fromkeys(_lexical_path(Path(path)) for path in outputs))
    selected_output_locks = _output_lock_paths(selected_outputs)
    if not selected_outputs:
        raise ValueError("artifact transaction requires at least one output")
    if any(
        _paths_overlap(source, output)
        for source in selected_sources
        for output in selected_output_locks
    ):
        raise ValueError("artifact transaction source overlaps an output")
    modes = {path: fcntl.LOCK_SH for path in selected_sources}
    modes.update({path: fcntl.LOCK_EX for path in selected_output_locks})
    with _serialized_artifact_locks(modes):
        if _source_paths(requested_sources) != selected_sources:
            raise RuntimeError("source symlink changed while its lease was acquired")
        if _output_lock_paths(selected_outputs) != selected_output_locks:
            raise RuntimeError("output symlink changed while its lease was acquired")
        token = _ACTIVE_READ_SOURCES.set(
            frozenset((*_ACTIVE_READ_SOURCES.get(), *selected_sources))
        )
        lease = ArtifactTransactionLease(
            selected_sources,
            selected_outputs,
            selected_output_locks,
        )
        try:
            yield lease
            lease.assert_output_identities()
        finally:
            _ACTIVE_READ_SOURCES.reset(token)


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
