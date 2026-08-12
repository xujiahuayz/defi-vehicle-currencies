"""Exact, recoverable publication boundary for counterfactual outputs only."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import MappingProxyType
from typing import Iterator
import uuid

from ddvc.runtime import serialized_artifact_transaction


class PublicationRecoveryRequired(RuntimeError):
    """A failed rollback retained the prior outputs for manual recovery."""


@dataclass(frozen=True)
class _Backup:
    target: Path
    kind: str
    backup: Path | None = None
    sha256: str | None = None
    link_target: str | None = None

    def record(self) -> dict[str, object]:
        return {
            "target": str(self.target),
            "kind": self.kind,
            "backup": str(self.backup) if self.backup is not None else None,
            "sha256": self.sha256,
            "link_target": self.link_target,
        }


@dataclass(frozen=True)
class _Capability:
    outputs: tuple[Path, ...]


_CAPABILITIES: dict[str, _Capability] = {}
_CAPABILITY_OWNERS: dict[str, Callable] = {}
PUBLICATION_CAPABILITY_REGISTRY: Mapping[str, _Capability] = MappingProxyType(
    _CAPABILITIES
)
_ACTIVE_CAPABILITY: ContextVar[str | None] = ContextVar(
    "ddvc_counterfactual_publication_capability", default=None
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lexical(path: Path) -> Path:
    candidate = Path(path)
    return candidate.parent.resolve() / candidate.name


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _snapshot(target: Path, root: Path) -> _Backup:
    target = _lexical(target)
    key = hashlib.sha256(str(target).encode()).hexdigest()
    backup = root / "backups" / key
    if target.is_symlink():
        return _Backup(target, "symlink", link_target=os.readlink(target))
    if target.is_file():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        return _Backup(target, "file", backup=backup, sha256=_sha256(target))
    if target.exists():
        raise RuntimeError(f"counterfactual publication target is not a file: {target}")
    return _Backup(target, "absent")


def _restore(backup: _Backup) -> None:
    target = backup.target
    if backup.kind == "absent":
        target.unlink(missing_ok=True)
        if target.exists() or target.is_symlink():
            raise RuntimeError("new output survived rollback")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    try:
        if backup.kind == "file":
            if (
                backup.backup is None
                or backup.sha256 is None
                or not backup.backup.is_file()
                or _sha256(backup.backup) != backup.sha256
            ):
                raise RuntimeError("rollback backup is absent or corrupt")
            try:
                os.link(backup.backup, temporary)
            except OSError:
                shutil.copy2(backup.backup, temporary)
            temporary.replace(target)
            if _sha256(target) != backup.sha256:
                raise RuntimeError("restored output failed digest verification")
        elif backup.kind == "symlink":
            temporary.symlink_to(str(backup.link_target))
            temporary.replace(target)
            if not target.is_symlink() or os.readlink(target) != backup.link_target:
                raise RuntimeError("restored symlink failed verification")
        else:
            raise RuntimeError(f"unknown backup kind: {backup.kind}")
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def counterfactual_publication(
    capability_id: str,
    *,
    sources: Iterable[Path],
    outputs: Iterable[Path],
) -> Iterator[None]:
    """Own a fixed counterfactual perimeter and restore every prior output on failure."""

    with serialized_artifact_transaction(
        sources=sources, outputs=outputs
    ) as (source_paths, output_paths):
        transaction_root: Path | None = None
        backups: list[_Backup] = []
        entered = False
        try:
            transaction_root = Path(
                tempfile.mkdtemp(prefix="ddvc-counterfactual-publication-")
            )
            _atomic_json(
                transaction_root / "transaction.json",
                {
                    "schema_version": 1,
                    "capability_id": capability_id,
                    "sources": [str(path) for path in source_paths],
                    "outputs": [str(path) for path in output_paths],
                },
            )
            backups = [_snapshot(path, transaction_root) for path in output_paths]
            _atomic_json(
                transaction_root / "recovery.json",
                {
                    "schema_version": 1,
                    "status": "active",
                    "backups": [backup.record() for backup in backups],
                },
            )
            token = _ACTIVE_CAPABILITY.set(capability_id)
            entered = True
            try:
                yield
                _atomic_json(
                    transaction_root / "recovery.json",
                    {
                        "schema_version": 1,
                        "status": "committed",
                        "backups": [backup.record() for backup in backups],
                    },
                )
            except BaseException as original:
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
                    manifest_error = None
                    try:
                        _atomic_json(
                            transaction_root / "recovery.json",
                            {
                                "schema_version": 1,
                                "status": "manual_recovery_required",
                                "backups": [backup.record() for backup in backups],
                                "failures": failures,
                                "original_error": f"{type(original).__name__}: {original}",
                            },
                        )
                    except BaseException as error:
                        manifest_error = f"; recovery manifest update failed: {type(error).__name__}: {error}"
                    raise PublicationRecoveryRequired(
                        f"counterfactual publication rollback failed; recovery evidence retained at {transaction_root}{manifest_error or ''}"
                    ) from original
                shutil.rmtree(transaction_root, ignore_errors=True)
                transaction_root = None
                raise
            finally:
                _ACTIVE_CAPABILITY.reset(token)
        finally:
            if transaction_root is not None and not entered:
                shutil.rmtree(transaction_root, ignore_errors=True)
            elif transaction_root is not None and entered and sys.exc_info()[0] is None:
                shutil.rmtree(transaction_root, ignore_errors=True)


def register_publication_capability(
    capability_id: str, outputs: Iterable[Path]
) -> None:
    selected = tuple(dict.fromkeys(_lexical(Path(path)) for path in outputs))
    if not capability_id.strip() or not selected:
        raise ValueError("publication capability must have an id and outputs")
    prior = _CAPABILITIES.setdefault(capability_id, _Capability(selected))
    if prior.outputs != selected:
        raise RuntimeError(f"publication capability {capability_id} changed outputs")


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
        def owner(*args, **kwargs):
            validate_publication_capability(owner)
            outputs = tuple(_lexical(Path(path)) for path in output_selector(*args, **kwargs))
            if not outputs or outputs != capability.outputs:
                raise RuntimeError(
                    f"publication capability {capability_id} declared the wrong output perimeter"
                )
            sources = tuple(Path(path) for path in source_selector(*args, **kwargs))
            with counterfactual_publication(
                capability_id, sources=sources, outputs=outputs
            ):
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                result = function(*args, **kwargs)
                if assert_current is not None:
                    assert_current(*args, **kwargs)
                return result

        owner.__name__ = function.__name__
        owner.__qualname__ = function.__qualname__
        owner.__doc__ = function.__doc__
        owner.__module__ = function.__module__
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
    if _ACTIVE_CAPABILITY.get() != capability_id:
        raise RuntimeError(
            f"canonical output requires publication capability {capability_id}"
        )
