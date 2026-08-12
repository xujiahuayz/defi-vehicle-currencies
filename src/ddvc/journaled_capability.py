"""Crash-recoverable capability boundary for fixed in-place artifact bundles."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Iterator
import uuid

from ddvc.runtime import serialized_artifact_transaction, serialized_read_installs


class JournaledCapabilityRecoveryRequired(RuntimeError):
    """A failed rollback retained independent evidence for manual recovery."""


@dataclass(frozen=True)
class _Backup:
    target: Path
    kind: str
    resolved_parent: Path
    backup: Path | None = None
    sha256: str | None = None
    link_target: str | None = None
    referent: Path | None = None
    referent_kind: str | None = None
    referent_backup: Path | None = None
    referent_sha256: str | None = None

    def record(self) -> dict[str, object]:
        return {
            "target": str(self.target),
            "kind": self.kind,
            "resolved_parent": str(self.resolved_parent),
            "backup": str(self.backup) if self.backup is not None else None,
            "sha256": self.sha256,
            "link_target": self.link_target,
            "referent": str(self.referent) if self.referent is not None else None,
            "referent_kind": self.referent_kind,
            "referent_backup": (
                str(self.referent_backup)
                if self.referent_backup is not None
                else None
            ),
            "referent_sha256": self.referent_sha256,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> _Backup:
        def optional_path(key: str) -> Path | None:
            value = record.get(key)
            return Path(str(value)) if value is not None else None

        return cls(
            target=Path(str(record["target"])),
            kind=str(record["kind"]),
            resolved_parent=Path(str(record["resolved_parent"])),
            backup=optional_path("backup"),
            sha256=str(record["sha256"]) if record.get("sha256") else None,
            link_target=(
                str(record["link_target"])
                if record.get("link_target") is not None
                else None
            ),
            referent=optional_path("referent"),
            referent_kind=(
                str(record["referent_kind"])
                if record.get("referent_kind") is not None
                else None
            ),
            referent_backup=optional_path("referent_backup"),
            referent_sha256=(
                str(record["referent_sha256"])
                if record.get("referent_sha256")
                else None
            ),
        )


@dataclass(frozen=True)
class _Capability:
    capability_id: str
    outputs: tuple[Path, ...]
    marker: Path
    seal: object = field(default_factory=object, repr=False, compare=False)


@dataclass(frozen=True)
class _OutputIdentity:
    """One output's exact path, referent, metadata and byte identity."""

    description: dict[str, object]
    path_stat: tuple[int, int, int, int, int, int]
    referent_stat: tuple[int, int, int, int, int, int]


_CAPABILITIES: dict[str, _Capability] = {}
_CAPABILITY_OWNERS: dict[str, Callable] = {}
_ACTIVE_CAPABILITY: ContextVar[object | None] = ContextVar(
    "ddvc_journaled_publication_capability", default=None
)
_RETIRED_OWNER = "retired-owner.json"
_RETIRED_CLEANUP_LIMIT = 64


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_identity(stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        stat.st_mode,
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _registered_marker(capability_id: str, marker_path: Path | None) -> Path:
    if marker_path is not None:
        return _lexical(marker_path)
    capability = _CAPABILITIES.get(capability_id)
    if capability is None:
        raise ValueError(
            f"journaled capability is not registered: {capability_id}"
        )
    return capability.marker


def _atomic_json(path: Path, payload: object) -> None:
    _durable_mkdir(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _durable_mkdir(path: Path) -> None:
    """Create missing directories and persist every new directory entry."""

    path = _lexical(path)
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if not directory.is_dir():
                raise
        else:
            _fsync_directory(directory)
            _fsync_directory(directory.parent)


def _publication_cleanup_cut(_label: str) -> None:
    """Named no-op cut point used by real-process cleanup crash tests."""


def _independent_copy(source: Path, destination: Path) -> None:
    _durable_mkdir(destination.parent)
    shutil.copy2(source, destination)
    if source.stat().st_ino == destination.stat().st_ino:
        raise RuntimeError("publication backup is not independent")
    _fsync_file(destination)
    _fsync_directory(destination.parent)


def _snapshot(target: Path, root: Path) -> _Backup:
    target = _lexical(target)
    resolved_parent = target.parent.resolve(strict=False)
    key = hashlib.sha256(str(target).encode()).hexdigest()
    backup = root / "backups" / key
    if target.is_symlink():
        link_target = os.readlink(target)
        referent = target.resolve(strict=False)
        if referent.is_file():
            referent_backup = root / "backups" / f"{key}.referent"
            _independent_copy(referent, referent_backup)
            return _Backup(
                target,
                "symlink",
                resolved_parent,
                link_target=link_target,
                referent=referent,
                referent_kind="file",
                referent_backup=referent_backup,
                referent_sha256=_sha256(referent),
            )
        if referent.exists():
            raise RuntimeError(
                f"counterfactual publication symlink targets a non-file: {target}"
            )
        return _Backup(
            target,
            "symlink",
            resolved_parent,
            link_target=link_target,
            referent=referent,
            referent_kind="absent",
        )
    if target.is_file():
        _independent_copy(target, backup)
        return _Backup(
            target,
            "file",
            resolved_parent,
            backup=backup,
            sha256=_sha256(target),
        )
    if target.exists():
        raise RuntimeError(f"counterfactual publication target is not a file: {target}")
    return _Backup(target, "absent", resolved_parent)


def _restore_file(backup: Path | None, target: Path, digest: str | None) -> None:
    if (
        backup is None
        or digest is None
        or not backup.is_file()
        or _sha256(backup) != digest
    ):
        raise RuntimeError("rollback backup is absent or corrupt")
    _durable_mkdir(target.parent)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    try:
        _independent_copy(backup, temporary)
        temporary.replace(target)
        _fsync_directory(target.parent)
        if _sha256(target) != digest or target.stat().st_ino == backup.stat().st_ino:
            raise RuntimeError("restored output failed independent digest verification")
    finally:
        temporary.unlink(missing_ok=True)


def _restore(backup: _Backup) -> None:
    target = backup.target
    if target.parent.resolve(strict=False) != backup.resolved_parent:
        raise RuntimeError("publication output ancestor changed before rollback")
    if backup.kind == "absent":
        existed = target.exists() or target.is_symlink()
        target.unlink(missing_ok=True)
        if existed:
            _fsync_directory(target.parent)
        if target.exists() or target.is_symlink():
            raise RuntimeError("new output survived rollback")
        return
    if backup.kind == "file":
        _restore_file(backup.backup, target, backup.sha256)
        return
    if backup.kind != "symlink" or backup.link_target is None:
        raise RuntimeError(f"unknown backup kind: {backup.kind}")
    if backup.referent is None or backup.referent_kind not in {"file", "absent"}:
        raise RuntimeError("symlink rollback lacks referent identity")
    if backup.referent_kind == "file":
        _restore_file(
            backup.referent_backup,
            backup.referent,
            backup.referent_sha256,
        )
    else:
        referent_existed = backup.referent.exists() or backup.referent.is_symlink()
        backup.referent.unlink(missing_ok=True)
        if referent_existed:
            _fsync_directory(backup.referent.parent)
    _durable_mkdir(target.parent)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    try:
        temporary.symlink_to(backup.link_target)
        temporary.replace(target)
        _fsync_directory(target.parent)
        if not target.is_symlink() or os.readlink(target) != backup.link_target:
            raise RuntimeError("restored symlink failed verification")
    finally:
        temporary.unlink(missing_ok=True)


def _describe_output(path: Path) -> dict[str, object]:
    path = _lexical(path)
    if path.is_symlink():
        referent = path.resolve(strict=True)
        if not referent.is_file():
            raise RuntimeError(f"published output is not a file: {path}")
        return {
            "path": str(path),
            "kind": "symlink",
            "link_target": os.readlink(path),
            "resolved_path": str(referent),
            "sha256": _sha256(referent),
        }
    if not path.is_file():
        raise RuntimeError(f"published output is absent: {path}")
    return {
        "path": str(path),
        "kind": "file",
        "resolved_path": str(path.resolve(strict=True)),
        "sha256": _sha256(path),
    }


def _seal_output(path: Path) -> _OutputIdentity:
    """Bind exact bytes and metadata while rejecting mutation during hashing."""

    selected = _lexical(path)
    path_before = _stat_identity(selected.lstat())
    referent = selected.resolve(strict=True) if selected.is_symlink() else selected
    referent_before = _stat_identity(referent.stat())
    description = _describe_output(selected)
    path_after = _stat_identity(selected.lstat())
    referent_after = _stat_identity(referent.stat())
    if path_before != path_after or referent_before != referent_after:
        raise RuntimeError(f"published output changed while sealed: {selected}")
    return _OutputIdentity(description, path_after, referent_after)


def _seal_outputs(outputs: Iterable[Path]) -> tuple[_OutputIdentity, ...]:
    return tuple(_seal_output(Path(path)) for path in outputs)


def _require_marker_commit(
    capability: _Capability,
    *,
    transaction_id: str,
    expected_payload: dict[str, object],
    sealed_outputs: tuple[_OutputIdentity, ...],
) -> None:
    """Reopen the marker and exact outputs before discarding rollback evidence."""

    try:
        installed = json.loads(capability.marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("counterfactual publication marker did not reopen") from error
    if installed != expected_payload:
        raise RuntimeError("counterfactual publication marker changed during commit")
    if _seal_outputs(capability.outputs) != sealed_outputs:
        raise RuntimeError("counterfactual publication output changed during commit")
    validated = _validate_marker_payload(
        capability.capability_id,
        capability.marker,
        installed,
        expected_outputs=capability.outputs,
    )
    if validated.get("transaction_id") != transaction_id:
        raise RuntimeError("counterfactual publication marker selected another transaction")


def _marker_payload(
    capability: _Capability,
    *,
    transaction_id: str,
    outputs: list[dict[str, object]],
) -> dict[str, object]:
    generation_id = hashlib.sha256(
        json.dumps(outputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "capability_id": capability.capability_id,
        "transaction_id": transaction_id,
        "generation_id": generation_id,
        "committed_at_utc": datetime.now(timezone.utc).isoformat(),
        "outputs": outputs,
    }


def _sync_outputs(outputs: Iterable[Path]) -> None:
    """Persist every member before the marker that selects the generation."""

    for raw in outputs:
        path = _lexical(Path(raw))
        durable_file = path.resolve(strict=True) if path.is_symlink() else path
        if not durable_file.is_file():
            raise RuntimeError(f"published output is not a file: {path}")
        _fsync_file(durable_file)
        _fsync_directory(durable_file.parent)
        if path.is_symlink():
            _fsync_directory(path.parent)


def _validate_marker_payload(
    capability_id: str,
    marker: Path,
    payload: object,
    *,
    expected_outputs: Iterable[Path] | None = None,
) -> dict[str, object]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("capability_id") != capability_id
        or not isinstance(payload.get("outputs"), list)
    ):
        raise RuntimeError(
            f"counterfactual publication marker is invalid: {capability_id}"
        )
    observed = [_describe_output(Path(str(row.get("path", "")))) for row in payload["outputs"] if isinstance(row, dict)]
    if observed != payload["outputs"]:
        raise RuntimeError(
            f"counterfactual publication outputs disagree with marker: {capability_id}"
        )
    expected = (
        tuple(_lexical(Path(path)) for path in expected_outputs)
        if expected_outputs is not None
        else _CAPABILITIES.get(capability_id).outputs
        if capability_id in _CAPABILITIES
        else None
    )
    if expected is not None and tuple(Path(row["path"]) for row in observed) != expected:
        raise RuntimeError(
            f"counterfactual publication marker has the wrong output perimeter: {capability_id}"
        )
    generation_id = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if payload.get("generation_id") != generation_id:
        raise RuntimeError(
            f"counterfactual publication generation is invalid: {capability_id}"
        )
    return payload


def require_current_publication(
    capability_id: str,
    *,
    marker_path: Path | None = None,
    expected_outputs: Iterable[Path] | None = None,
) -> dict[str, object]:
    """Require one marker-last generation before consuming any member output."""

    marker = _registered_marker(capability_id, marker_path)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
        raise RuntimeError(
            f"counterfactual publication is not current: {capability_id}"
        ) from error
    return _validate_marker_payload(
        capability_id,
        marker,
        payload,
        expected_outputs=expected_outputs,
    )


@contextmanager
def current_publication(
    capability_id: str,
    *,
    marker_path: Path | None = None,
    expected_outputs: Iterable[Path] | None = None,
) -> Iterator[dict[str, object]]:
    """Lease a complete marker-selected generation through a consumer read."""

    marker = _registered_marker(capability_id, marker_path)
    initial = require_current_publication(
        capability_id,
        marker_path=marker,
        expected_outputs=expected_outputs,
    )
    paths = tuple(Path(str(row["path"])) for row in initial["outputs"])
    with serialized_read_installs((marker, *paths)):
        current = require_current_publication(
            capability_id,
            marker_path=marker,
            expected_outputs=expected_outputs,
        )
        if current != initial:
            raise RuntimeError(
                f"counterfactual publication changed while its lease was acquired: {capability_id}"
            )
        yield current
        if require_current_publication(
            capability_id,
            marker_path=marker,
            expected_outputs=expected_outputs,
        ) != current:
            raise RuntimeError(
                f"counterfactual publication changed during read: {capability_id}"
            )


def _journal_root(capability: _Capability) -> Path:
    return capability.marker.parent / f".{capability.marker.name}.transactions"


def _retired_prefix(capability: _Capability) -> str:
    return f"{_journal_root(capability).name}.retired."


def _retired_owner_payload(
    capability: _Capability, transaction_id: str
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "capability_id": capability.capability_id,
        "transaction_id": transaction_id,
        "policy": "ddvc-counterfactual-retired-transaction-v1",
    }


def _valid_transaction_id(value: str) -> bool:
    return len(value) == 32 and all(
        character in "0123456789abcdef" for character in value
    )


def _cleanup_retired_transactions(capability: _Capability) -> None:
    """Boundedly remove only transaction tombstones owned by this capability."""

    parent = capability.marker.parent
    prefix = _retired_prefix(capability)
    seen = 0
    for candidate in sorted(parent.iterdir()):
        if not candidate.name.startswith(prefix):
            continue
        transaction_id = candidate.name[len(prefix) :]
        if not _valid_transaction_id(transaction_id):
            continue
        if seen >= _RETIRED_CLEANUP_LIMIT:
            break
        seen += 1
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        owner = candidate / _RETIRED_OWNER
        if not owner.exists() and not owner.is_symlink():
            try:
                candidate.rmdir()
            except OSError:
                pass
            else:
                _fsync_directory(parent)
            continue
        if owner.is_symlink() or not owner.is_file():
            continue
        try:
            payload = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload != _retired_owner_payload(capability, transaction_id):
            continue
        for child in sorted(candidate.iterdir()):
            if child == owner:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            _fsync_directory(candidate)
            _publication_cleanup_cut(f"retired_removed:{child.name}")
        owner.unlink()
        _fsync_directory(candidate)
        _publication_cleanup_cut("retired_owner_removed")
        candidate.rmdir()
        _fsync_directory(parent)
        _publication_cleanup_cut("retired_removed")


def _retire_transaction(
    root: Path, capability: _Capability, transaction_id: str
) -> None:
    """Atomically leave the active journal namespace before recursive cleanup."""

    journal = _journal_root(capability)
    if (
        root.parent != journal
        or root.name != transaction_id
        or not _valid_transaction_id(transaction_id)
    ):
        raise RuntimeError("counterfactual transaction retirement perimeter is invalid")
    owner = root / _RETIRED_OWNER
    _atomic_json(owner, _retired_owner_payload(capability, transaction_id))
    _publication_cleanup_cut("retired_owner_installed")
    retired = journal.parent / f"{_retired_prefix(capability)}{transaction_id}"
    if retired.exists() or retired.is_symlink():
        raise RuntimeError("counterfactual transaction tombstone already exists")
    root.replace(retired)
    _fsync_directory(journal)
    _fsync_directory(journal.parent)
    _publication_cleanup_cut("retired")
    _cleanup_retired_transactions(capability)


def _write_status(
    root: Path,
    *,
    capability: _Capability,
    transaction_id: str,
    status: str,
    backups: Iterable[_Backup],
    failures: list[dict[str, str]] | None = None,
    original_error: str | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "capability_id": capability.capability_id,
        "transaction_id": transaction_id,
        "status": status,
        "backups": [backup.record() for backup in backups],
        "failures": failures or [],
        "original_error": original_error,
    }
    _atomic_json(root / "transaction.json", payload)
    _atomic_json(root / "recovery.json", payload)


def _rollback(
    root: Path,
    capability: _Capability,
    transaction_id: str,
    backups: list[_Backup],
    original: BaseException | None,
) -> None:
    failures: list[dict[str, str]] = []
    for backup in reversed(backups):
        try:
            _restore(backup)
        except BaseException as error:
            failures.append(
                {
                    "target": str(backup.target),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    if failures:
        manifest_error = ""
        try:
            _write_status(
                root,
                capability=capability,
                transaction_id=transaction_id,
                status="manual_recovery_required",
                backups=backups,
                failures=failures,
                original_error=(
                    f"{type(original).__name__}: {original}"
                    if original is not None
                    else "process_exit_or_restart"
                ),
            )
        except BaseException as error:
            manifest_error = (
                f"; recovery manifest update failed: {type(error).__name__}: {error}"
            )
        raise JournaledCapabilityRecoveryRequired(
            f"counterfactual publication rollback failed; recovery evidence retained at {root}{manifest_error}"
        ) from original
    _write_status(
        root,
        capability=capability,
        transaction_id=transaction_id,
        status="rolled_back",
        backups=backups,
        original_error=(
            f"{type(original).__name__}: {original}"
            if original is not None
            else "process_exit_or_restart"
        ),
    )
    _retire_transaction(root, capability, transaction_id)


def _marker_commits_transaction(
    capability: _Capability, transaction_id: str
) -> bool:
    try:
        payload = require_current_publication(
            capability.capability_id, marker_path=capability.marker
        )
    except RuntimeError:
        return False
    return payload.get("transaction_id") == transaction_id


def _recover_transactions(capability: _Capability) -> None:
    _cleanup_retired_transactions(capability)
    journal = _journal_root(capability)
    if not journal.is_dir():
        return
    for root in sorted(path for path in journal.iterdir() if path.is_dir()):
        transaction_path = root / "transaction.json"
        if not transaction_path.exists():
            entries = tuple(root.iterdir())
            if not entries or all(
                path.is_file()
                and path.name.startswith(".transaction.json.")
                and path.name.endswith(".tmp")
                for path in entries
            ):
                for path in entries:
                    path.unlink()
                    _fsync_directory(root)
                root.rmdir()
                _fsync_directory(journal)
                continue
        try:
            record = json.loads(
                transaction_path.read_text(encoding="utf-8")
            )
            if (
                not isinstance(record, dict)
                or record.get("schema_version") != 1
                or record.get("capability_id") != capability.capability_id
                or not isinstance(record.get("backups"), list)
            ):
                raise ValueError("invalid transaction record")
            transaction_id = str(record["transaction_id"])
            status = str(record["status"])
            backups = [
                _Backup.from_record(item)
                for item in record["backups"]
                if isinstance(item, dict)
            ]
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise JournaledCapabilityRecoveryRequired(
                f"counterfactual publication has corrupt recovery evidence at {root}"
            ) from error
        expected_targets = (*capability.outputs, capability.marker)
        if status == "active" and tuple(backup.target for backup in backups) != expected_targets:
            raise JournaledCapabilityRecoveryRequired(
                f"counterfactual publication has incomplete recovery evidence at {root}"
            )
        if status in {"preparing", "committed", "rolled_back"}:
            _retire_transaction(root, capability, transaction_id)
        elif status == "active" and _marker_commits_transaction(
            capability, transaction_id
        ):
            _retire_transaction(root, capability, transaction_id)
        elif status == "active":
            _rollback(root, capability, transaction_id, backups, None)
        else:
            raise JournaledCapabilityRecoveryRequired(
                f"counterfactual publication requires manual recovery at {root}"
            )


@contextmanager
def _publication_transaction(
    capability: _Capability,
    *,
    sources: Iterable[Path],
    outputs: Iterable[Path],
) -> Iterator[None]:
    selected_outputs = tuple(dict.fromkeys(_lexical(Path(path)) for path in outputs))
    if selected_outputs != capability.outputs:
        raise RuntimeError(
            f"publication capability {capability.capability_id} declared the wrong output perimeter"
        )
    _durable_mkdir(capability.marker.parent)
    with serialized_artifact_transaction(
        sources=sources, outputs=(*selected_outputs, capability.marker)
    ) as transaction:
        _recover_transactions(capability)
        journal = _journal_root(capability)
        _durable_mkdir(journal)
        transaction_id = uuid.uuid4().hex
        root = journal / transaction_id
        _durable_mkdir(root)
        backups: list[_Backup] = []
        _write_status(
            root,
            capability=capability,
            transaction_id=transaction_id,
            status="preparing",
            backups=backups,
        )
        try:
            backups = [
                _snapshot(path, root) for path in (*selected_outputs, capability.marker)
            ]
            _write_status(
                root,
                capability=capability,
                transaction_id=transaction_id,
                status="active",
                backups=backups,
            )
        except BaseException:
            _retire_transaction(root, capability, transaction_id)
            raise
        token = _ACTIVE_CAPABILITY.set(capability.seal)
        try:
            try:
                yield
                transaction.assert_output_identities()
                _sync_outputs(selected_outputs)
                transaction.assert_output_identities()
                sealed_outputs = _seal_outputs(selected_outputs)
                output_descriptions = [
                    identity.description for identity in sealed_outputs
                ]
                transaction.assert_output_identities()
                marker_payload = _marker_payload(
                    capability,
                    transaction_id=transaction_id,
                    outputs=output_descriptions,
                )
                _atomic_json(
                    capability.marker,
                    marker_payload,
                )
                transaction.assert_output_identities()
                _require_marker_commit(
                    capability,
                    transaction_id=transaction_id,
                    expected_payload=marker_payload,
                    sealed_outputs=sealed_outputs,
                )
                _write_status(
                    root,
                    capability=capability,
                    transaction_id=transaction_id,
                    status="committed",
                    backups=backups,
                )
                transaction.assert_output_identities()
                _require_marker_commit(
                    capability,
                    transaction_id=transaction_id,
                    expected_payload=marker_payload,
                    sealed_outputs=sealed_outputs,
                )
            except BaseException as original:
                _rollback(root, capability, transaction_id, backups, original)
                raise
        finally:
            _ACTIVE_CAPABILITY.reset(token)
        _retire_transaction(root, capability, transaction_id)


def register_publication_capability(
    capability_id: str,
    outputs: Iterable[Path],
    *,
    marker_path: Path,
) -> None:
    selected = tuple(dict.fromkeys(_lexical(Path(path)) for path in outputs))
    marker = _lexical(marker_path)
    if not capability_id.strip() or not selected:
        raise ValueError("publication capability must have an id and outputs")
    if marker in selected:
        raise ValueError("publication marker cannot be a member output")
    prior = _CAPABILITIES.setdefault(
        capability_id, _Capability(capability_id, selected, marker)
    )
    if prior.outputs != selected or prior.marker != marker:
        raise RuntimeError(f"publication capability {capability_id} changed perimeter")


def publication_capability(
    capability_id: str,
    *,
    output_selector: Callable[..., Iterable[Path]],
    source_selector: Callable[..., Iterable[Path]],
    assert_current: Callable[..., object] | None = None,
):
    try:
        capability = _CAPABILITIES[capability_id]
    except KeyError as error:
        raise ValueError(f"unknown publication capability: {capability_id}") from error

    def decorate(function: Callable):
        @wraps(function)
        def owner(*args, **kwargs):
            validate_publication_capability(owner)
            outputs = tuple(
                _lexical(Path(path)) for path in output_selector(*args, **kwargs)
            )
            sources = tuple(Path(path) for path in source_selector(*args, **kwargs))
            with _publication_transaction(
                capability, sources=sources, outputs=outputs
            ):
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                result = function(*args, **kwargs)
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                return result

        owner.__ddvc_publication_capability__ = capability_id
        if capability_id in _CAPABILITY_OWNERS:
            raise RuntimeError(f"publication capability {capability_id} has two owners")
        _CAPABILITY_OWNERS[capability_id] = owner
        return owner

    return decorate


def validate_publication_capability(owner: Callable) -> str:
    capability_id = getattr(owner, "__ddvc_publication_capability__", None)
    capability = _CAPABILITIES.get(str(capability_id))
    if capability is None or _CAPABILITY_OWNERS.get(str(capability_id)) is not owner:
        raise RuntimeError("callable is not the registered publication owner")
    installed = getattr(sys.modules.get(owner.__module__), owner.__name__, None)
    if installed is not owner:
        raise RuntimeError("publication owner is not the installed callable object")
    return str(capability_id)


def require_active_publication(capability_id: str) -> None:
    capability = _CAPABILITIES.get(capability_id)
    if capability is None or _ACTIVE_CAPABILITY.get() is not capability.seal:
        raise RuntimeError(
            f"canonical output requires publication capability {capability_id}"
        )
