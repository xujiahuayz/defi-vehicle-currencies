"""Marker-last publication for small immutable analytical artifact bundles."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping

from ddvc.fetch.raw import write_json
from ddvc.journaled_publication import recover_journaled_publications
from ddvc.provenance import (
    code_fingerprint,
    describe_input,
    install_stamped_artifact,
    prepare_stamp,
    sidecar_path,
    verify,
)
from ddvc.runtime import (
    atomic_output,
    file_sha256,
    serialized_output_install,
    serialized_output_installs,
    serialized_read_installs,
    source_lock_paths,
    staged_output,
)


def file_stat_identity(path: Path) -> tuple[int, int, int, int, int]:
    """Return the exact filesystem identity used by mutation-safe readers."""

    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def is_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class ArtifactRelease:
    """One hash-verified immutable bundle selected by a marker-last pointer."""

    generation_id: str
    pointer_path: Path
    artifacts: Mapping[str, Path]
    pointer_sha256: str

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return tuple(self.artifacts[name] for name in sorted(self.artifacts))

    @property
    def provenance_paths(self) -> tuple[Path, ...]:
        return tuple(sidecar_path(path) for path in self.artifact_paths)

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return self.pointer_path, *self.artifact_paths, *self.provenance_paths

    def assert_current(self) -> None:
        if (
            not self.pointer_path.is_file()
            or file_sha256(self.pointer_path) != self.pointer_sha256
        ):
            raise RuntimeError("artifact release pointer changed after resolution")


@contextmanager
def current_artifact_release(release: ArtifactRelease):
    """Lease one pointer and its exact artifacts for the complete read."""

    with serialized_read_installs(release.lineage_paths):
        release.assert_current()
        yield release
        release.assert_current()


@dataclass(frozen=True)
class FileLineageLease:
    """One immutable identity over an exact set of source files."""

    bindings: tuple[tuple[Path, str | None], ...]

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(path for path, _digest in self.bindings)

    @property
    def existing_paths(self) -> tuple[Path, ...]:
        return tuple(path for path, digest in self.bindings if digest is not None)

    @property
    def content_identity_sha256(self) -> str:
        return canonical_json_sha256(
            [(str(path), digest) for path, digest in self.bindings]
        )

    def assert_current(self) -> None:
        for path, expected in self.bindings:
            if expected is None:
                if path.exists() or path.is_symlink():
                    raise RuntimeError(f"leased absent source file appeared: {path}")
                continue
            if not path.is_file():
                raise RuntimeError(f"leased source file disappeared: {path}")
            before = file_stat_identity(path)
            observed = file_sha256(path)
            if before != file_stat_identity(path) or observed != expected:
                raise RuntimeError(f"leased source file changed: {path}")


@contextmanager
def current_file_lineage(lease: FileLineageLease):
    """Hold one absence-aware filesystem lease around a complete source read."""

    with serialized_read_installs(lease.paths, allow_missing=True):
        lease.assert_current()
        yield lease
        lease.assert_current()


def bind_file_lineage(
    paths: list[Path] | tuple[Path, ...], *, allow_missing: bool = False
) -> FileLineageLease:
    """Hash one duplicate-free file perimeter with mutation detection."""

    selected = tuple(dict.fromkeys(Path(path) for path in paths))
    if not selected:
        raise ValueError("file-lineage lease requires at least one input")
    source_lock_paths(selected, allow_missing=allow_missing)
    bindings: list[tuple[Path, str | None]] = []
    for path in selected:
        if not path.is_file():
            if allow_missing and not path.exists() and not path.is_symlink():
                bindings.append((path, None))
                continue
            raise FileNotFoundError(f"leased source file is missing: {path}")
        before = file_stat_identity(path)
        digest = file_sha256(path)
        if before != file_stat_identity(path):
            raise RuntimeError(f"leased source file changed during hashing: {path}")
        bindings.append((path, digest))
    return FileLineageLease(tuple(bindings))


def combine_file_lineages(
    leases: list[FileLineageLease] | tuple[FileLineageLease, ...],
) -> FileLineageLease:
    """Combine already-bound snapshots without reopening their source pointers."""

    bindings: dict[Path, str | None] = {}
    for lease in leases:
        for path, digest in lease.bindings:
            prior = bindings.setdefault(path, digest)
            if prior != digest:
                raise RuntimeError(f"file lineage snapshots disagree: {path}")
    if not bindings:
        raise ValueError("combined file lineage requires at least one input")
    return FileLineageLease(tuple(bindings.items()))


def generation_id(artifact_sha256: Mapping[str, str], build_identity_sha256: str) -> str:
    return canonical_json_sha256(
        {
            "artifacts": dict(sorted(artifact_sha256.items())),
            "build_identity_sha256": build_identity_sha256,
        }
    )


def _validated_filenames(filenames: Mapping[str, object]) -> dict[str, str]:
    """Return unique simple basenames without touching the filesystem."""

    selected: dict[str, str] = {}
    seen: set[str] = set()
    for raw_name, raw_filename in filenames.items():
        name = str(raw_name)
        if name in selected:
            raise ValueError(f"artifact names are not unique after normalization: {name}")
        try:
            filename = os.fspath(raw_filename)
        except TypeError as error:
            raise ValueError(
                f"artifact filename is not path-like: {raw_filename!r}"
            ) from error
        if not isinstance(filename, str):
            raise ValueError(f"artifact filename is not text: {raw_filename!r}")
        if (
            not filename
            or filename in {".", ".."}
            or Path(filename).is_absolute()
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
        ):
            raise ValueError(
                f"artifact filename is not a simple basename: {filename!r}"
            )
        if filename in seen:
            raise ValueError(f"artifact filenames are not unique: {filename}")
        seen.add(filename)
        selected[name] = filename
    if not selected:
        raise ValueError("artifact release requires at least one filename")
    return selected


def generation_paths(
    release_root: Path,
    generation: str,
    filenames: Mapping[str, str],
) -> dict[str, Path]:
    selected = _validated_filenames(filenames)
    directory = release_root / "generations" / generation
    return {name: directory / filename for name, filename in selected.items()}


_STAGE_POLICY = "ddvc-artifact-release-stage-v1"
_STAGE_OWNER = "owner.json"
_SEED_RECOVERY_LIMIT = 64


def _artifact_stage_cut(_label: str) -> None:
    """Test hook for process-death cuts in outer-stage setup."""


def _pointer_stage_root(pointer_path: Path) -> Path:
    identity = hashlib.sha256(
        str(pointer_path.resolve(strict=False)).encode()
    ).hexdigest()[:24]
    return pointer_path.parent / f".ddvc-artifact-stage-{identity}"


def _pointer_seed_prefix(pointer_path: Path) -> str:
    identity = hashlib.sha256(
        str(pointer_path.resolve(strict=False)).encode()
    ).hexdigest()[:24]
    return f".ddvc-artifact-owner-seed-{identity}."


def _stage_owner_payload(pointer_path: Path) -> dict[str, object]:
    return {
        "policy": _STAGE_POLICY,
        "pointer_path": str(pointer_path.resolve(strict=False)),
    }


def _owner_seed_bytes(pointer_path: Path) -> bytes:
    return (json.dumps(_stage_owner_payload(pointer_path)) + "\n").encode()


def _recover_pointer_owner_seeds(pointer_path: Path) -> None:
    """Remove a bounded number of complete pointer-owned seeds only."""

    prefix = _pointer_seed_prefix(pointer_path)
    recovered = 0
    for candidate in pointer_path.parent.iterdir():
        name = candidate.name
        token = name[len(prefix) : -len(".tmp")] if name.endswith(".tmp") else ""
        if (
            not name.startswith(prefix)
            or not name.endswith(".tmp")
            or len(token) != 8
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in token
            )
        ):
            continue
        if recovered >= _SEED_RECOVERY_LIMIT:
            break
        recovered += 1
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            payload = candidate.read_bytes()
        except OSError:
            continue
        if payload == _owner_seed_bytes(pointer_path):
            candidate.unlink()


def _recover_pointer_stage(pointer_path: Path) -> None:
    """Remove only the stale outer stage owned by this exact pointer."""

    root = _pointer_stage_root(pointer_path)
    if not root.exists() and not root.is_symlink():
        return
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"artifact release stage has an unsafe type: {root}")
    owner_path = root / _STAGE_OWNER
    if not owner_path.exists() and not owner_path.is_symlink():
        try:
            root.rmdir()
        except OSError as error:
            raise RuntimeError(
                f"artifact release stage ownership is invalid: {root}"
            ) from error
        return
    if owner_path.is_symlink() or not owner_path.is_file():
        raise RuntimeError(f"artifact release stage ownership is invalid: {root}")
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"artifact release stage ownership is invalid: {root}") from error
    if owner != _stage_owner_payload(pointer_path):
        raise RuntimeError(f"artifact release stage belongs to another pointer: {root}")
    shutil.rmtree(root)


@contextmanager
def _pointer_stage(pointer_path: Path):
    """Own one crash-visible stage under the already-held pointer lock."""

    _recover_pointer_owner_seeds(pointer_path)
    _recover_pointer_stage(pointer_path)
    root = _pointer_stage_root(pointer_path)
    descriptor, seed_name = tempfile.mkstemp(
        dir=pointer_path.parent,
        prefix=_pointer_seed_prefix(pointer_path),
        suffix=".tmp",
    )
    seed = Path(seed_name)
    owner_bytes = _owner_seed_bytes(pointer_path)
    prefix_end = min(len(owner_bytes), len(b'{"policy":'))
    created_identity: tuple[int, int] | None = None
    owner_installed = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
            _artifact_stage_cut("seed_empty_fsynced")
            handle.write(owner_bytes[:prefix_end])
            handle.flush()
            os.fsync(handle.fileno())
            _artifact_stage_cut("seed_partial_fsynced")
            handle.write(owner_bytes[prefix_end:])
            handle.flush()
            os.fsync(handle.fileno())
            _artifact_stage_cut("seed_complete_fsynced")
        root.mkdir()
        created_identity = (root.stat().st_dev, root.stat().st_ino)
        _artifact_stage_cut("created")
        seed.replace(root / _STAGE_OWNER)
        owner_installed = True
        _artifact_stage_cut("owner_installed")
        payload = root / "payload"
        payload.mkdir()
        yield payload
    finally:
        seed.unlink(missing_ok=True)
        if owner_installed:
            _recover_pointer_stage(pointer_path)
        elif created_identity is not None and root.exists() and not root.is_symlink():
            current_identity = (root.stat().st_dev, root.stat().st_ino)
            if current_identity != created_identity:
                raise RuntimeError(
                    f"artifact release stage changed during setup: {root}"
                )
            shutil.rmtree(root)


def _pointer_generation(pointer_path: Path) -> str | None:
    if not pointer_path.is_file():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    generation = pointer.get("generation_id") if isinstance(pointer, dict) else None
    return str(generation) if is_sha256(generation) else None


def _reopen_existing_generation(
    targets: Mapping[str, Path],
    artifact_hashes: Mapping[str, str],
    validate: Callable[[Mapping[str, Path]], None],
) -> None:
    missing = [name for name, path in targets.items() if not path.is_file()]
    if missing:
        raise ValueError(f"existing artifact generation is partial: missing={missing}")
    for name, path in targets.items():
        if file_sha256(path) != artifact_hashes[name]:
            raise ValueError(f"existing artifact generation has different content: {name}")
        if not sidecar_path(path).is_file() or verify(path).get("status") != "ok":
            raise ValueError(f"existing artifact generation is not current: {name}")
    validate(targets)


_UNSTABLE_PROVENANCE_FIELDS = frozenset(
    {
        "argv",
        "created_at",
        "git",
        "libraries",
        "script",
        "artefact_mtime_ns",
    }
)


def _provenance_identity(payload: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(payload, Mapping):
        record = dict(payload)
    else:
        try:
            record = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("artifact provenance is not valid JSON") from error
    if not isinstance(record, dict):
        raise ValueError("artifact provenance is not a JSON object")
    identity = {
        key: value
        for key, value in record.items()
        if key not in _UNSTABLE_PROVENANCE_FIELDS
    }
    recorded_inputs = identity.get("inputs")
    if isinstance(recorded_inputs, list):
        identity["inputs"] = sorted(
            recorded_inputs,
            key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
        )
    return identity


def _read_provenance(path: Path) -> dict[str, object]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"artifact provenance is invalid: {path.name}") from error
    if not isinstance(record, dict):
        raise ValueError(f"artifact provenance is invalid: {path.name}")
    return record


def _resume_unselected_generation(
    *,
    targets: Mapping[str, Path],
    staged: Mapping[str, Path],
    artifact_hashes: Mapping[str, str],
    prepared_stamps: Mapping[str, bytes],
    code_sources: list[str],
    inputs: list[str | Path],
    row_counts: Mapping[str, int],
    notes: str | None,
    preinstall_validator: Callable[[Path], object] | None,
) -> None:
    """Resume only fragments that prove they belong to the expected generation."""

    states: dict[str, str] = {}
    sidecar_records: dict[str, dict[str, object]] = {}
    for name, target in targets.items():
        provenance_path = sidecar_path(target)
        artifact_exists = target.is_file()
        provenance_exists = provenance_path.is_file()
        state = (
            "complete"
            if artifact_exists and provenance_exists
            else "artifact_only"
            if artifact_exists
            else "sidecar_only"
            if provenance_exists
            else "absent"
        )
        states[name] = state
        if artifact_exists and file_sha256(target) != artifact_hashes[name]:
            raise ValueError(f"existing artifact generation has different content: {name}")
        if provenance_exists:
            record = _read_provenance(provenance_path)
            sidecar_records[name] = record
            if _provenance_identity(record) != _provenance_identity(prepared_stamps[name]):
                raise ValueError(f"existing artifact generation has different provenance: {name}")
        if state == "complete" and verify(target).get("status") != "ok":
            raise ValueError(f"existing artifact generation is not current: {name}")

    for name, target in targets.items():
        state = states[name]
        if state == "complete":
            continue
        if state == "absent":
            install_stamped_artifact(staged[name], target, prepared_stamps[name])
            continue
        if state == "artifact_only":
            if preinstall_validator is not None:
                preinstall_validator(target)
            prepared = prepare_stamp(
                target,
                content_path=target,
                code_sources=code_sources,
                inputs=inputs,
                rows=int(row_counts[name]),
                notes=notes,
            )
            prepared_validator = getattr(
                preinstall_validator, "validate_prepared_stamp", None
            )
            if prepared_validator is not None:
                prepared = prepared_validator(prepared)
            with atomic_output(sidecar_path(target)) as temporary:
                temporary.write_bytes(prepared)
            continue
        record = sidecar_records[name]
        recorded_mtime_ns = record.get("artefact_mtime_ns")
        if not isinstance(recorded_mtime_ns, int) or recorded_mtime_ns < 0:
            raise ValueError(f"existing artifact generation has invalid provenance time: {name}")
        staged_stat = staged[name].stat()
        os.utime(staged[name], ns=(staged_stat.st_atime_ns, recorded_mtime_ns))
        staged[name].replace(target)


def _recover_generation_publications(targets: Mapping[str, Path]) -> None:
    """Recover every payload-sidecar journal before inspecting a generation."""

    for target in targets.values():
        recover_journaled_publications(
            {"payload": target, "sidecar": sidecar_path(target)},
            journal_root=target.parent / ".ddvc-publication-journals",
        )


def _publish_generation_under_lock(
    *,
    pointer_path: Path,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    targets: Mapping[str, Path],
    staged: Mapping[str, Path],
    artifact_hashes: Mapping[str, str],
    prepared_stamps: Mapping[str, bytes],
    build_identity: str,
    generation: str,
    code_sources: list[str],
    inputs: list[str | Path],
    row_counts: Mapping[str, int],
    notes: str | None,
    preinstall_validator: Callable[[Path], object] | None,
    validate_staged: Callable[[Mapping[str, Path]], None],
    write_pointer: Callable[[Path, dict[str, object]], None],
) -> ArtifactRelease:
    """Recover, resume, validate and select one generation under its full lock."""

    _recover_generation_publications(targets)
    prior_pointer = pointer_path.read_bytes() if pointer_path.is_file() else None
    selected = _pointer_generation(pointer_path) == generation
    if selected:
        try:
            _reopen_existing_generation(targets, artifact_hashes, validate_staged)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"selected {kind} generation is incomplete or invalid"
            ) from error
    else:
        try:
            _resume_unselected_generation(
                targets=targets,
                staged=staged,
                artifact_hashes=artifact_hashes,
                prepared_stamps=prepared_stamps,
                code_sources=code_sources,
                inputs=inputs,
                row_counts=row_counts,
                notes=notes,
                preinstall_validator=preinstall_validator,
            )
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"unselected {kind} generation is incomplete or invalid"
            ) from error
    validate_staged(targets)
    stale = {
        name: verdict.get("status")
        for name, path in targets.items()
        if (verdict := verify(path)).get("status") != "ok"
    }
    if stale:
        raise RuntimeError(f"{kind} generation is not current before release: {stale}")
    _recover_generation_publications(targets)
    pointer = {
        "schema_version": schema_version,
        "kind": kind,
        "generation_id": generation,
        "build_identity_sha256": build_identity,
        "artifacts": {
            name: {
                "filename": filenames[name],
                "sha256": artifact_hashes[name],
                "provenance_sha256": file_sha256(sidecar_path(targets[name])),
            }
            for name in filenames
        },
    }
    try:
        write_pointer(pointer_path, pointer)
        return _resolve_artifact_release_unlocked(
            pointer_path,
            kind=kind,
            schema_version=schema_version,
            filenames=filenames,
            require_current_provenance=True,
            expected_generation=generation,
        )
    except BaseException:
        if prior_pointer is None:
            pointer_path.unlink(missing_ok=True)
        else:
            with staged_output(pointer_path) as rollback:
                rollback.write_bytes(prior_pointer)
                rollback.replace(pointer_path)
        raise


def _resolve_artifact_release_unlocked(
    pointer_path: Path,
    *,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    require_current_provenance: bool,
    expected_generation: str | None = None,
) -> ArtifactRelease:
    filenames = _validated_filenames(filenames)
    if not pointer_path.is_file():
        raise FileNotFoundError(f"missing {kind} current pointer: {pointer_path}")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{kind} current pointer is not valid JSON") from error
    generation = pointer.get("generation_id") if isinstance(pointer, dict) else None
    build_identity = pointer.get("build_identity_sha256") if isinstance(pointer, dict) else None
    records = pointer.get("artifacts") if isinstance(pointer, dict) else None
    if (
        not isinstance(pointer, dict)
        or pointer.get("schema_version") != schema_version
        or pointer.get("kind") != kind
        or not is_sha256(generation)
        or not is_sha256(build_identity)
        or not isinstance(records, dict)
        or set(records) != set(filenames)
    ):
        raise ValueError(f"invalid {kind} current pointer")
    if expected_generation is not None and generation != expected_generation:
        raise RuntimeError(f"{kind} current pointer selected a competing generation")
    artifact_hashes: dict[str, str] = {}
    provenance_hashes: dict[str, str] = {}
    for name, filename in filenames.items():
        record = records.get(name)
        if (
            not isinstance(record, dict)
            or record.get("filename") != filename
            or not is_sha256(record.get("sha256"))
            or not is_sha256(record.get("provenance_sha256"))
        ):
            raise ValueError(f"invalid {kind} pointer record: {name}")
        artifact_hashes[name] = str(record["sha256"])
        provenance_hashes[name] = str(record["provenance_sha256"])
    if generation_id(artifact_hashes, str(build_identity)) != generation:
        raise ValueError(f"{kind} generation identity disagrees with its pointer")
    paths = generation_paths(pointer_path.parent, str(generation), filenames)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"partial {kind} generation: missing={missing}")
    for name, path in paths.items():
        if file_sha256(path) != artifact_hashes[name]:
            raise ValueError(f"{kind} artifact digest disagrees: {name}")
        provenance_path = sidecar_path(path)
        if not provenance_path.is_file():
            raise FileNotFoundError(f"{kind} artifact lacks provenance: {name}")
        if file_sha256(provenance_path) != provenance_hashes[name]:
            raise ValueError(f"{kind} provenance digest disagrees: {name}")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{kind} provenance is invalid: {name}") from error
        if (
            not isinstance(provenance, dict)
            or provenance.get("artefact") != describe_input(path).get("path")
            or provenance.get("artefact_sha256") not in {None, artifact_hashes[name]}
        ):
            raise ValueError(f"{kind} provenance identifies different content: {name}")
        if require_current_provenance and verify(path).get("status") != "ok":
            raise ValueError(f"{kind} provenance is not current: {name}")
    return ArtifactRelease(
        str(generation), pointer_path, paths, file_sha256(pointer_path)
    )


def resolve_artifact_release(
    pointer_path: Path,
    *,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    require_current_provenance: bool = True,
) -> ArtifactRelease:
    """Resolve one pointer and reopen every artifact and provenance digest."""

    filenames = _validated_filenames(filenames)
    pointer_path = Path(pointer_path)
    with serialized_output_install(pointer_path):
        return _resolve_artifact_release_unlocked(
            pointer_path,
            kind=kind,
            schema_version=schema_version,
            filenames=filenames,
            require_current_provenance=require_current_provenance,
        )


def publish_artifact_release(
    *,
    pointer_path: Path,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    writers: Mapping[str, Callable[[Path], None]],
    row_counts: Mapping[str, int],
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str | None,
    validate_staged: Callable[[Mapping[str, Path]], None],
    preinstall_validator: Callable[[Path], object] | None = None,
    write_pointer: Callable[[Path, dict[str, object]], None] = write_json,
) -> ArtifactRelease:
    """Stage, stamp, reopen, and marker-release one complete artifact bundle."""

    filenames = _validated_filenames(filenames)
    if set(filenames) != set(writers) or set(filenames) != set(row_counts):
        raise ValueError("artifact release writers and row counts must match filenames")
    pointer_path = Path(pointer_path)
    release_root = pointer_path.parent
    release_root.mkdir(parents=True, exist_ok=True)
    with serialized_output_install(pointer_path):
        with _pointer_stage(pointer_path) as directory:
            staged = {
                name: directory / filename for name, filename in filenames.items()
            }
            for name, writer in writers.items():
                writer(staged[name])
            validate_staged(staged)
            artifact_hashes = {name: file_sha256(path) for name, path in staged.items()}
            described_inputs = sorted(
                (describe_input(path) for path in inputs),
                key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":")),
            )
            build_identity = canonical_json_sha256(
                {
                    "code_fingerprint": code_fingerprint(code_sources),
                    "filenames": dict(sorted(filenames.items())),
                    "inputs": described_inputs,
                    "kind": kind,
                    "notes": notes,
                    "row_counts": {
                        name: int(row_counts[name]) for name in sorted(row_counts)
                    },
                    "schema_version": schema_version,
                }
            )
            generation = generation_id(artifact_hashes, build_identity)
            targets = generation_paths(release_root, generation, filenames)
            prepared_stamps: dict[str, bytes] = {}
            prepared_validator = getattr(
                preinstall_validator, "validate_prepared_stamp", None
            )
            for name in filenames:
                prepared = prepare_stamp(
                    targets[name],
                    content_path=staged[name],
                    code_sources=code_sources,
                    described_inputs=described_inputs,
                    rows=int(row_counts[name]),
                    notes=notes,
                )
                if prepared_validator is not None:
                    prepared = prepared_validator(prepared)
                prepared_stamps[name] = prepared
            if preinstall_validator is not None:
                preinstall_validator(directory)
            publication_paths = tuple(
                path
                for target in targets.values()
                for path in (target, sidecar_path(target))
            )
            with serialized_output_installs(publication_paths):
                return _publish_generation_under_lock(
                    pointer_path=pointer_path,
                    kind=kind,
                    schema_version=schema_version,
                    filenames=filenames,
                    targets=targets,
                    staged=staged,
                    artifact_hashes=artifact_hashes,
                    prepared_stamps=prepared_stamps,
                    build_identity=build_identity,
                    generation=generation,
                    code_sources=code_sources,
                    inputs=inputs,
                    row_counts=row_counts,
                    notes=notes,
                    preinstall_validator=preinstall_validator,
                    validate_staged=validate_staged,
                    write_pointer=write_pointer,
                )
