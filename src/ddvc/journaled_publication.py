"""Crash-recoverable publication for a fixed bundle of filesystem artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from ddvc.runtime import file_sha256, serialized_output_installs


POLICY = "ddvc-journaled-publication-v1"
JOURNAL = "journal.json"
PREPARED = "prepared"
COMMITTED = "committed"
ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class PublicationRecovery:
    """Recovery outcome and immutable metadata from committed publications."""

    recovered: int
    committed_metadata: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _PublicationPerimeter:
    targets: dict[str, Path]
    staged: dict[str, Path] | None
    journal_root: Path


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _simple_label(raw: object) -> str:
    label = str(raw)
    if (
        not label
        or label in {".", ".."}
        or Path(label).is_absolute()
        or Path(label).name != label
        or "/" in label
        or "\\" in label
    ):
        raise ValueError(f"publication label is not a simple basename: {label!r}")
    return label


def _normalized_mapping(
    values: Mapping[object, Path], *, role: str
) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    for raw_label, raw_path in values.items():
        label = _simple_label(raw_label)
        if label in normalized:
            raise ValueError(f"publication {role} labels are not unique: {label}")
        normalized[label] = _lexical(Path(raw_path))
    return normalized


def _path_identities(path: Path) -> tuple[Path, ...]:
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"publication path cannot be resolved: {path}") from error
    identities = (path, resolved)
    return tuple(dict.fromkeys(identities))


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _require_disjoint(
    left_label: str,
    left: Path,
    right_label: str,
    right: Path,
) -> None:
    if any(
        _paths_overlap(left_identity, right_identity)
        for left_identity in _path_identities(left)
        for right_identity in _path_identities(right)
    ):
        raise ValueError(
            f"publication paths overlap: {left_label}={left}; {right_label}={right}"
        )


def _validate_leaf(path: Path, *, role: str, required: bool) -> None:
    if path.is_symlink():
        raise ValueError(f"publication {role} cannot be a leaf symlink: {path}")
    if not path.exists():
        if required:
            raise FileNotFoundError(f"publication {role} is absent: {path}")
        return
    if not path.is_file() and not path.is_dir():
        raise ValueError(f"publication {role} has an unsupported type: {path}")
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink() or (not child.is_file() and not child.is_dir()):
                raise ValueError(
                    f"publication {role} has an unsupported entry: {child}"
                )


def _validate_perimeter(
    targets: Mapping[object, Path],
    *,
    journal_root: Path,
    staged: Mapping[object, Path] | None = None,
) -> _PublicationPerimeter:
    """Validate the complete path graph without creating or changing a path."""

    selected_targets = _normalized_mapping(targets, role="target")
    if not selected_targets:
        raise ValueError("journaled publication requires at least one target")
    selected_staged = (
        _normalized_mapping(staged, role="staged") if staged is not None else None
    )
    if selected_staged is not None and set(selected_targets) != set(selected_staged):
        raise ValueError("journaled publication staged perimeter differs from targets")
    selected_journal_root = _lexical(Path(journal_root))
    if selected_journal_root.is_symlink():
        raise ValueError(
            f"publication journal root cannot be a leaf symlink: {selected_journal_root}"
        )
    if selected_journal_root.exists() and not selected_journal_root.is_dir():
        raise ValueError(
            f"publication journal root is not a directory: {selected_journal_root}"
        )
    for label, path in selected_targets.items():
        _validate_leaf(path, role=f"target {label}", required=False)
    if selected_staged is not None:
        for label, path in selected_staged.items():
            _validate_leaf(path, role=f"staged {label}", required=True)

    target_items = tuple(selected_targets.items())
    for index, (label, path) in enumerate(target_items):
        for other_label, other_path in target_items[index + 1 :]:
            _require_disjoint(f"target {label}", path, f"target {other_label}", other_path)
    if selected_staged is not None:
        staged_items = tuple(selected_staged.items())
        for index, (label, path) in enumerate(staged_items):
            for other_label, other_path in staged_items[index + 1 :]:
                _require_disjoint(f"staged {label}", path, f"staged {other_label}", other_path)
        for target_label, target in target_items:
            for staged_label, staged_path in staged_items:
                _require_disjoint(
                    f"target {target_label}",
                    target,
                    f"staged {staged_label}",
                    staged_path,
                )
    all_paths = [
        (f"target {label}", path) for label, path in target_items
    ] + [
        (f"staged {label}", path)
        for label, path in (selected_staged or {}).items()
    ]
    for label, path in all_paths:
        _require_disjoint("journal root", selected_journal_root, label, path)
    return _PublicationPerimeter(
        selected_targets,
        selected_staged,
        selected_journal_root,
    )


def _identity(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError(f"publication target has an unsupported type: {path}")
    if path.is_file():
        return {"kind": "file", "sha256": file_sha256(path)}
    if path.is_dir():
        entries: list[dict[str, str]] = []
        for child in sorted(path.rglob("*")):
            if child.is_symlink() or (not child.is_file() and not child.is_dir()):
                raise ValueError(f"publication target has an unsupported entry: {child}")
            relative = child.relative_to(path).as_posix()
            if child.is_dir():
                entries.append({"path": relative, "kind": "directory"})
            elif child.is_file():
                entries.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "sha256": file_sha256(child),
                    }
                )
        return {"kind": "directory", "entries": entries}
    if path.exists() or path.is_symlink():
        raise ValueError(f"publication target has an unsupported type: {path}")
    return {"kind": "absent"}


def _durable_replace(source: Path, target: Path) -> None:
    source_parent = source.parent
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)
    _fsync_directory(target_parent)
    if source_parent != target_parent:
        _fsync_directory(source_parent)


def _fsync_tree(path: Path) -> None:
    """Durably flush every staged file and directory before PREPARED."""

    if path.is_symlink():
        raise ValueError(f"publication stage has an unsupported type: {path}")
    if path.is_file():
        _fsync_file(path)
        return
    if not path.is_dir():
        raise ValueError(f"publication stage has an unsupported type: {path}")
    directories = [path]
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or (not child.is_file() and not child.is_dir()):
            raise ValueError(f"publication stage has an unsupported entry: {child}")
        if child.is_file():
            _fsync_file(child)
        else:
            directories.append(child)
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)


def _write_journal(stage: Path, payload: Mapping[str, object]) -> None:
    temporary = stage / f".{JOURNAL}.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _fsync_file(temporary)
    temporary.replace(stage / JOURNAL)
    _fsync_directory(stage)
    _fsync_directory(stage.parent)


def _read_journal(stage: Path) -> dict[str, object]:
    try:
        payload = json.loads((stage / JOURNAL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"publication journal is unreadable: {stage}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("policy") != POLICY
        or payload.get("state") not in {PREPARED, COMMITTED, ROLLED_BACK}
        or not isinstance(payload.get("targets"), dict)
        or not isinstance(payload.get("original_identities"), dict)
        or not isinstance(payload.get("published_identities"), dict)
        or not isinstance(payload.get("metadata"), dict)
    ):
        raise RuntimeError(f"publication journal is invalid: {stage}")
    return payload


def _target_records(
    stage: Path, targets: Mapping[str, Path]
) -> tuple[tuple[str, Path, Path, Path], ...]:
    return tuple(
        (
            label,
            Path(target),
            stage / "new" / label,
            stage / "backup" / label,
        )
        for label, target in sorted(targets.items())
    )


def _validated_identities(
    raw: object,
    records: tuple[tuple[str, Path, Path, Path], ...],
    *,
    label: str,
) -> dict[str, dict[str, object]]:
    names = {name for name, _target, _new, _backup in records}
    if not isinstance(raw, dict) or set(raw) != names:
        raise RuntimeError(f"publication {label} identity perimeter changed")
    identities: dict[str, dict[str, object]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict) or value.get("kind") not in {
            "absent",
            "directory",
            "file",
        }:
            raise RuntimeError(f"publication {label} identity is invalid: {name}")
        identities[str(name)] = value
    return identities


def _require_targets(
    journal: Mapping[str, object],
    records: tuple[tuple[str, Path, Path, Path], ...],
) -> None:
    recorded = journal["targets"]
    assert isinstance(recorded, dict)
    expected = {name: str(target.absolute()) for name, target, _new, _backup in records}
    if recorded != expected:
        raise RuntimeError("publication target perimeter changed")


def _require_live(
    records: tuple[tuple[str, Path, Path, Path], ...],
    expected: Mapping[str, dict[str, object]],
) -> None:
    for name, target, _new, _backup in records:
        if _identity(target) != expected[name]:
            raise RuntimeError(f"publication live identity mismatch: {name}")


def _restore(
    target: Path, backup: Path, *, expected_identity: dict[str, object]
) -> None:
    if _identity(target) == expected_identity:
        return
    if backup.exists() or backup.is_symlink():
        _remove(target)
        _durable_replace(backup, target)
    elif expected_identity.get("kind") == "absent":
        _remove(target)
        _fsync_directory(target.parent)
    if _identity(target) != expected_identity:
        raise RuntimeError(f"publication rollback identity mismatch: {target}")


def _publication_cut(_label: str) -> None:
    """Named no-op cut point used by real-process crash tests."""


def _finish_cleanup(
    stage: Path,
    records: tuple[tuple[str, Path, Path, Path], ...],
    *,
    live_identities: Mapping[str, dict[str, object]],
) -> None:
    _require_live(records, live_identities)
    for name, _target, new, backup in records:
        for disposable in (new, backup):
            if disposable.exists() or disposable.is_symlink():
                _remove(disposable)
                _fsync_directory(disposable.parent)
        _publication_cut(f"cleanup:{name}")
    for directory in (stage / "new", stage / "backup"):
        if directory.exists():
            directory.rmdir()
            _fsync_directory(stage)
    allowed = {stage / JOURNAL}
    unexpected = [path for path in stage.iterdir() if path not in allowed]
    if unexpected:
        raise RuntimeError(f"publication stage contains unexpected entries: {unexpected}")
    (stage / JOURNAL).unlink()
    _fsync_directory(stage)
    stage.rmdir()
    _fsync_directory(stage.parent)


def _stage_prefix(targets: Mapping[str, Path]) -> str:
    perimeter = json.dumps(
        {name: str(Path(path).absolute()) for name, path in sorted(targets.items())},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f".ddvc-publish-{hashlib.sha256(perimeter).hexdigest()[:24]}-"


def _recover_journaled_publications_unlocked(
    targets: Mapping[str, Path], *, journal_root: Path
) -> PublicationRecovery:
    """Recover prepared rollbacks and finish committed cleanup for one perimeter."""

    perimeter = _validate_perimeter(targets, journal_root=journal_root)
    selected = perimeter.targets
    stage_parent = perimeter.journal_root
    stage_parent.mkdir(parents=True, exist_ok=True)
    recovered = 0
    committed_metadata: list[dict[str, object]] = []
    for stage in sorted(stage_parent.glob(f"{_stage_prefix(selected)}*")):
        if not stage.is_dir():
            continue
        journal_path = stage / JOURNAL
        if not journal_path.is_file():
            backups = stage / "backup"
            if backups.exists() and any(backups.iterdir()):
                raise RuntimeError(f"publication has backups but no journal: {stage}")
            shutil.rmtree(stage)
            _fsync_directory(stage_parent)
            continue
        journal = _read_journal(stage)
        records = _target_records(stage, selected)
        _require_targets(journal, records)
        original = _validated_identities(
            journal["original_identities"], records, label="original"
        )
        published = _validated_identities(
            journal["published_identities"], records, label="published"
        )
        state = journal["state"]
        if state == PREPARED:
            for name, target, _new, backup in reversed(records):
                _restore(target, backup, expected_identity=original[name])
            journal = {**journal, "state": ROLLED_BACK}
            _write_journal(stage, journal)
            live = original
        elif state == COMMITTED:
            live = published
            committed_metadata.append(dict(journal["metadata"]))
        else:
            live = original
        _finish_cleanup(stage, records, live_identities=live)
        recovered += 1
    return PublicationRecovery(recovered, tuple(committed_metadata))


def recover_journaled_publications(
    targets: Mapping[str, Path], *, journal_root: Path
) -> PublicationRecovery:
    """Recover one perimeter while excluding every reader and writer."""

    perimeter = _validate_perimeter(targets, journal_root=journal_root)
    with serialized_output_installs(perimeter.targets.values()):
        return _recover_journaled_publications_unlocked(
            perimeter.targets, journal_root=perimeter.journal_root
        )


def _publish_journaled_bundle_unlocked(
    *,
    targets: Mapping[str, Path],
    staged: Mapping[str, Path],
    journal_root: Path,
    metadata: Mapping[str, object] | None = None,
    validate_preconditions: Callable[[], None] | None = None,
    validate_live: Callable[[], None] | None = None,
) -> None:
    """Publish a complete fixed bundle and preserve recovery state on failure.

    Staged paths are consumed. The caller must hold an exclusive lease over every
    target for recovery, publication, validation, and cleanup.
    """

    perimeter = _validate_perimeter(
        targets,
        staged=staged,
        journal_root=journal_root,
    )
    selected_targets = perimeter.targets
    assert perimeter.staged is not None
    selected_staged = perimeter.staged
    _recover_journaled_publications_unlocked(
        selected_targets, journal_root=perimeter.journal_root
    )
    for parent in {path.parent for path in selected_targets.values()}:
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            _fsync_directory(parent.parent)
    stage_parent = perimeter.journal_root
    stage_parent.mkdir(parents=True, exist_ok=True)
    _fsync_directory(stage_parent.parent)
    stage = Path(
        tempfile.mkdtemp(dir=stage_parent, prefix=_stage_prefix(selected_targets))
    )
    (stage / "new").mkdir()
    (stage / "backup").mkdir()
    records = _target_records(stage, selected_targets)
    journal_written = False
    try:
        for name, _target, new, _backup in records:
            source = selected_staged[name]
            _durable_replace(source, new)
            _fsync_tree(new)
        _fsync_directory(stage / "new")
        original = {
            name: _identity(target) for name, target, _new, _backup in records
        }
        published = {name: _identity(new) for name, _target, new, _backup in records}
        journal: dict[str, object] = {
            "policy": POLICY,
            "state": PREPARED,
            "targets": {
                name: str(target.absolute())
                for name, target, _new, _backup in records
            },
            "original_identities": original,
            "published_identities": published,
            "metadata": dict(metadata or {}),
        }
        _write_journal(stage, journal)
        journal_written = True
        try:
            if validate_preconditions is not None:
                validate_preconditions()
            for name, target, new, backup in records:
                if original[name]["kind"] != "absent":
                    _durable_replace(target, backup)
                _durable_replace(new, target)
                _publication_cut(f"installed:{name}")
            _require_live(records, published)
            if validate_preconditions is not None:
                validate_preconditions()
            if validate_live is not None:
                validate_live()
            journal = {**journal, "state": COMMITTED}
            _write_journal(stage, journal)
            _publication_cut("committed")
        except BaseException:
            try:
                for name, target, _new, backup in reversed(records):
                    _restore(target, backup, expected_identity=original[name])
                journal = {**journal, "state": ROLLED_BACK}
                _write_journal(stage, journal)
            except BaseException:
                raise
            _finish_cleanup(stage, records, live_identities=original)
            raise
        _finish_cleanup(stage, records, live_identities=published)
    except BaseException:
        if not journal_written:
            shutil.rmtree(stage, ignore_errors=True)
            _fsync_directory(stage_parent)
        raise


def publish_journaled_bundle(
    *,
    targets: Mapping[str, Path],
    staged: Mapping[str, Path],
    journal_root: Path,
    metadata: Mapping[str, object] | None = None,
    validate_preconditions: Callable[[], None] | None = None,
    validate_live: Callable[[], None] | None = None,
) -> None:
    """Publish a fixed bundle under one exclusive target perimeter."""

    perimeter = _validate_perimeter(
        targets,
        staged=staged,
        journal_root=journal_root,
    )
    assert perimeter.staged is not None
    with serialized_output_installs(perimeter.targets.values()):
        _publish_journaled_bundle_unlocked(
            targets=perimeter.targets,
            staged=perimeter.staged,
            journal_root=perimeter.journal_root,
            metadata=metadata,
            validate_preconditions=validate_preconditions,
            validate_live=validate_live,
        )
