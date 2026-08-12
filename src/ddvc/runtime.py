"""Runtime guards for long or artifact-producing research jobs."""

from __future__ import annotations

import fcntl
import functools
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Iterator

DEFAULT_MAX_WORKERS = 8
_HELD_PUBLICATION_LOCKS = threading.local()
_ACTIVE_PUBLICATION_TRANSACTION: ContextVar["_PublicationTransaction | None"] = ContextVar(
    "ddvc_active_publication_transaction",
    default=None,
)
_ACTIVE_READ_SOURCES: ContextVar[frozenset[Path]] = ContextVar(
    "ddvc_active_read_sources",
    default=frozenset(),
)
_LOCK_SHARED = 1
_LOCK_EXCLUSIVE = 2
_PUBLICATION_CAPABILITIES: dict[str, tuple[str, tuple[Path, ...]]] = {}
PUBLICATION_CAPABILITY_REGISTRY = MappingProxyType(_PUBLICATION_CAPABILITIES)


def register_publication_capability(capability_id: str, callable_path: str, outputs: Iterable[Path]) -> None:
    """Register one exact callable and output perimeter before decorating it."""

    selected = tuple(_lexical_path(Path(path)) for path in outputs)
    if not capability_id.strip() or not callable_path.strip() or not selected:
        raise ValueError("publication capability registration must be complete and non-empty")
    specification = (callable_path, selected)
    prior = _PUBLICATION_CAPABILITIES.setdefault(capability_id, specification)
    if prior != specification:
        raise RuntimeError(f"publication capability {capability_id} was registered twice with different contracts")


class PublicationRecoveryRequired(RuntimeError):
    """A failed rollback retained everything needed for manual recovery."""


@dataclass
class _PublicationTransaction:
    root: Path
    source_paths: frozenset[Path]
    publication_paths: frozenset[Path]

    @property
    def metadata_path(self) -> Path:
        return self.root / "transaction.json"

    @property
    def journal_path(self) -> Path:
        return self.root / "journal.json"


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
        with serialized_output_install(target):
            temporary.replace(target)


def _lexical_path(path: Path) -> Path:
    candidate = Path(path)
    return candidate.parent.resolve() / candidate.name


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _lock_modes(targets: Iterable[Path]) -> dict[Path, int]:
    modes: dict[Path, int] = {}
    for raw_target in targets:
        target = _lexical_path(Path(raw_target))
        lineage = [target]
        parent = target.parent
        while parent != parent.parent:
            lineage.append(parent)
            parent = parent.parent
        for path in reversed(lineage):
            mode = _LOCK_EXCLUSIVE if path == target else _LOCK_SHARED
            modes[path] = max(mode, modes.get(path, 0))
    return modes


@contextmanager
def _hierarchical_resource_locks(targets: Iterable[Path]) -> Iterator[None]:
    """Own exact paths while conflicting with every ancestor or descendant owner."""

    lock_root = Path(tempfile.gettempdir()) / "ddvc-artifact-install-locks-v2"
    lock_root.mkdir(parents=True, exist_ok=True)
    modes = _lock_modes(targets)
    held = getattr(_HELD_PUBLICATION_LOCKS, "counts", None)
    if held is None:
        held = {}
        _HELD_PUBLICATION_LOCKS.counts = held
    acquired: list[tuple[str, object | None]] = []
    try:
        for path in sorted(modes, key=lambda value: (len(value.parts), str(value))):
            identity = str(path)
            mode = modes[path]
            prior = held.get(identity)
            if prior is not None:
                count, prior_mode = prior
                if mode > prior_mode:
                    raise RuntimeError(
                        f"nested publication lock cannot upgrade {path}; declare the complete perimeter before entering"
                    )
                held[identity] = (count + 1, prior_mode)
                acquired.append((identity, None))
                continue
            lock_name = hashlib.sha256(identity.encode()).hexdigest()
            handle = (lock_root / f"{lock_name}.lock").open("a+")
            operation = fcntl.LOCK_EX if mode == _LOCK_EXCLUSIVE else fcntl.LOCK_SH
            fcntl.flock(handle.fileno(), operation)
            held[identity] = (1, mode)
            acquired.append((identity, handle))
        yield
    finally:
        for identity, handle in reversed(acquired):
            count, mode = held[identity]
            if count > 1:
                held[identity] = (count - 1, mode)
                continue
            held.pop(identity, None)
            if handle is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _journal_records(transaction: _PublicationTransaction) -> list[dict[str, object]]:
    if not transaction.journal_path.is_file():
        return []
    value = json.loads(transaction.journal_path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError("publication rollback journal is malformed")
    return value


def _journal_target(transaction: _PublicationTransaction, target: Path) -> None:
    normalized = _lexical_path(target)
    if normalized not in transaction.publication_paths:
        raise RuntimeError(f"publication target {normalized} is outside the declared publication perimeter")
    if any(_paths_overlap(normalized, source) for source in transaction.source_paths):
        raise RuntimeError(f"publication target overlaps a leased source: {normalized}")
    records = _journal_records(transaction)
    if any(record.get("target") == str(normalized) for record in records):
        return
    key = hashlib.sha256(str(normalized).encode()).hexdigest()
    backup = transaction.root / "backups" / key
    backup.parent.mkdir(parents=True, exist_ok=True)
    if normalized.is_symlink():
        record: dict[str, object] = {
            "target": str(normalized),
            "kind": "symlink",
            "link_target": os.readlink(normalized),
        }
    elif normalized.is_file():
        try:
            os.link(normalized, backup)
        except OSError:
            shutil.copy2(normalized, backup)
        record = {
            "target": str(normalized),
            "kind": "file",
            "backup": str(backup),
            "sha256": _file_sha256(normalized),
        }
    elif normalized.is_dir():
        raise RuntimeError(f"transactional publication cannot replace a directory: {normalized}")
    else:
        record = {"target": str(normalized), "kind": "absent"}
    records.append(record)
    _write_json_atomic(transaction.journal_path, records)


def _rollback_transaction(transaction: _PublicationTransaction) -> None:
    failures: list[dict[str, str]] = []
    records = _journal_records(transaction)
    for record in reversed(records):
        target = Path(str(record["target"]))
        try:
            kind = record["kind"]
            if kind == "file":
                backup = Path(str(record["backup"]))
                if not backup.is_file() or _file_sha256(backup) != record["sha256"]:
                    raise RuntimeError("rollback backup is absent or corrupt")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
                try:
                    try:
                        os.link(backup, temporary)
                    except OSError:
                        shutil.copy2(backup, temporary)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                if _file_sha256(target) != record["sha256"]:
                    raise RuntimeError("restored file failed digest verification")
            elif kind == "symlink":
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
                try:
                    temporary.symlink_to(str(record["link_target"]))
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                if not target.is_symlink() or os.readlink(target) != record["link_target"]:
                    raise RuntimeError("restored symlink failed verification")
            elif kind == "absent":
                target.unlink(missing_ok=True)
                if target.exists() or target.is_symlink():
                    raise RuntimeError("new publication target survived rollback")
            else:
                raise RuntimeError(f"unknown rollback entry kind: {kind}")
        except BaseException as error:
            failures.append({"target": str(target), "error": f"{type(error).__name__}: {error}"})
    if failures:
        recovery = {
            "schema_version": 1,
            "status": "manual_recovery_required",
            "transaction": str(transaction.metadata_path),
            "journal": str(transaction.journal_path),
            "failures": failures,
        }
        _write_json_atomic(transaction.root / "recovery.json", recovery)
        raise PublicationRecoveryRequired(
            f"publication rollback failed; recovery evidence retained at {transaction.root}"
        )


@contextmanager
def serialized_output_install(target: Path) -> Iterator[None]:
    """Serialize and, inside a publication owner, journal one exact output."""

    lexical_target = _lexical_path(target)
    if any(_paths_overlap(lexical_target, source) for source in _ACTIVE_READ_SOURCES.get()):
        raise RuntimeError(f"publication target overlaps a leased source: {lexical_target}")
    transaction = _ACTIVE_PUBLICATION_TRANSACTION.get()
    if transaction is not None:
        _journal_target(transaction, lexical_target)
        yield
        return
    with _hierarchical_resource_locks((lexical_target,)):
        yield


@contextmanager
def serialized_output_installs(targets: Iterable[Path]) -> Iterator[None]:
    resolved = tuple(dict.fromkeys(_lexical_path(Path(target)) for target in targets))
    if any(
        _paths_overlap(target, source)
        for target in resolved
        for source in _ACTIVE_READ_SOURCES.get()
    ):
        raise RuntimeError("publication target overlaps a leased source")
    transaction = _ACTIVE_PUBLICATION_TRANSACTION.get()
    if transaction is not None:
        for target in resolved:
            _journal_target(transaction, target)
        yield
        return
    with _hierarchical_resource_locks(resolved):
        yield


@contextmanager
def serialized_read_installs(
    targets: Iterable[Path],
    *,
    publication_paths: Iterable[Path] = (),
) -> Iterator[None]:
    """Lease exact sources and transactionally own a fixed output perimeter."""

    sources = frozenset(_lexical_path(Path(target)) for target in targets)
    publications = frozenset(_lexical_path(Path(target)) for target in publication_paths)
    if not sources and not publications:
        raise ValueError("publication lease requires a source or output path")
    overlap = next(
        (
            (source, publication)
            for source in sources
            for publication in publications
            if _paths_overlap(source, publication)
        ),
        None,
    )
    if overlap is not None:
        raise ValueError(f"publication perimeter overlaps a leased source: {overlap[0]} / {overlap[1]}")
    active = _ACTIVE_PUBLICATION_TRANSACTION.get()
    if active is not None:
        if publications or not sources.issubset(active.source_paths):
            raise RuntimeError("nested publication leases must stay within the complete declared source perimeter")
        yield
        return
    if not publications:
        with _hierarchical_resource_locks(sources):
            token = _ACTIVE_READ_SOURCES.set(frozenset((*_ACTIVE_READ_SOURCES.get(), *sources)))
            try:
                yield
            finally:
                _ACTIVE_READ_SOURCES.reset(token)
        return
    transaction_root = Path(tempfile.mkdtemp(prefix="ddvc-publication-transaction-"))
    transaction = _PublicationTransaction(transaction_root, sources, publications)
    committed = False
    rollback_complete = False
    try:
        _write_json_atomic(
            transaction.metadata_path,
            {
                "schema_version": 1,
                "source_paths": [str(path) for path in sorted(sources, key=str)],
                "publication_paths": [str(path) for path in sorted(publications, key=str)],
            },
        )
        with _hierarchical_resource_locks((*sources, *publications)):
            token = _ACTIVE_PUBLICATION_TRANSACTION.set(transaction)
            try:
                yield
                committed = True
            except BaseException:
                _rollback_transaction(transaction)
                rollback_complete = True
                raise
            finally:
                _ACTIVE_PUBLICATION_TRANSACTION.reset(token)
    finally:
        if committed or rollback_complete or not transaction.metadata_path.exists():
            shutil.rmtree(transaction.root, ignore_errors=True)


def publication_capability(
    capability_id: str,
    *,
    output_selector: Callable[..., Iterable[Path]],
    source_selector: Callable[..., Iterable[Path]],
    assert_current: Callable[..., object] | None = None,
    context: bool = False,
):
    """Bind one real publisher callable to one exact, non-empty output contract."""

    try:
        callable_path, registered_outputs = PUBLICATION_CAPABILITY_REGISTRY[capability_id]
    except KeyError as error:
        raise ValueError(f"unknown publication capability: {capability_id}") from error
    expected = tuple(_lexical_path(path) for path in registered_outputs)

    def decorate(function: Callable):
        actual_path = f"{function.__module__}:{function.__name__}"
        if actual_path != callable_path:
            raise ValueError(f"publication capability {capability_id} belongs to {callable_path}, not {actual_path}")

        def perimeter(args, kwargs):
            observed = tuple(_lexical_path(Path(path)) for path in output_selector(*args, **kwargs))
            if not observed or observed != expected:
                raise RuntimeError(f"publication capability {capability_id} declared the wrong output perimeter")
            sources = tuple(Path(path) for path in source_selector(*args, **kwargs))
            return observed, sources

        @functools.wraps(function)
        def published(*args, **kwargs):
            validate_publication_capability(published)
            observed, sources = perimeter(args, kwargs)
            with serialized_read_installs(sources, publication_paths=observed):
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                result = function(*args, **kwargs)
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                return result

        @functools.wraps(function)
        @contextmanager
        def published_context(*args, **kwargs):
            validate_publication_capability(published_context)
            observed, sources = perimeter(args, kwargs)
            with serialized_read_installs(sources, publication_paths=observed):
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                yield from function(*args, **kwargs)
                if assert_current is not None:
                    assert_current(*args, **kwargs)

        owner = published_context if context else published
        owner.__ddvc_publication_capability__ = MappingProxyType(
            {
                "capability_id": capability_id,
                "callable_path": callable_path,
                "outputs": expected,
            }
        )
        return owner

    return decorate


def validate_publication_capability(owner: Callable) -> dict[str, object]:
    """Validate the installed callable object, not an alias or source-code pattern."""

    metadata = getattr(owner, "__ddvc_publication_capability__", None)
    if not isinstance(metadata, Mapping):
        raise ValueError("callable has no publication capability metadata")
    capability_id = metadata.get("capability_id")
    try:
        callable_path, expected_outputs = PUBLICATION_CAPABILITY_REGISTRY[str(capability_id)]
    except KeyError as error:
        raise ValueError(f"unknown publication capability: {capability_id}") from error
    module_name, separator, function_name = callable_path.partition(":")
    if not separator:
        raise RuntimeError(f"invalid registered callable path: {callable_path}")
    installed = getattr(importlib.import_module(module_name), function_name, None)
    if installed is not owner:
        raise RuntimeError(f"publication capability {capability_id} is not the installed callable object")
    observed = tuple(_lexical_path(Path(path)) for path in metadata.get("outputs", ()))
    expected = tuple(_lexical_path(path) for path in expected_outputs)
    if not observed or observed != expected:
        raise RuntimeError(f"publication capability {capability_id} metadata has the wrong output perimeter")
    return metadata


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
