"""Marker-last publication for small immutable analytical artifact bundles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

from ddvc.fetch.raw import write_json
from ddvc.provenance import (
    code_fingerprint,
    describe_input,
    install_stamped_artifact,
    prepare_stamp,
    sidecar_path,
    verify,
)
from ddvc.runtime import atomic_output, serialized_output_install


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return tuple(self.artifacts[name] for name in sorted(self.artifacts))

    @property
    def provenance_paths(self) -> tuple[Path, ...]:
        return tuple(sidecar_path(path) for path in self.artifact_paths)

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return self.pointer_path, *self.artifact_paths, *self.provenance_paths


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
                if path.exists():
                    raise RuntimeError(f"leased absent source file appeared: {path}")
                continue
            if not path.is_file():
                raise RuntimeError(f"leased source file disappeared: {path}")
            before = file_stat_identity(path)
            observed = file_sha256(path)
            if before != file_stat_identity(path) or observed != expected:
                raise RuntimeError(f"leased source file changed: {path}")


def bind_file_lineage(
    paths: list[Path] | tuple[Path, ...], *, allow_missing: bool = False
) -> FileLineageLease:
    """Hash one duplicate-free file perimeter with mutation detection."""

    selected = tuple(dict.fromkeys(Path(path) for path in paths))
    if not selected:
        raise ValueError("file-lineage lease requires at least one input")
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


def generation_id(artifact_sha256: Mapping[str, str], build_identity_sha256: str) -> str:
    return canonical_json_sha256(
        {
            "artifacts": dict(sorted(artifact_sha256.items())),
            "build_identity_sha256": build_identity_sha256,
        }
    )


def generation_paths(
    release_root: Path,
    generation: str,
    filenames: Mapping[str, str],
) -> dict[str, Path]:
    directory = release_root / "generations" / generation
    return {name: directory / filename for name, filename in filenames.items()}


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
            prepared = prepare_stamp(
                target,
                content_path=target,
                code_sources=code_sources,
                inputs=inputs,
                rows=int(row_counts[name]),
                notes=notes,
            )
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


def _resolve_artifact_release_unlocked(
    pointer_path: Path,
    *,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    require_current_provenance: bool,
    expected_generation: str | None = None,
) -> ArtifactRelease:
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
    return ArtifactRelease(str(generation), pointer_path, paths)


def resolve_artifact_release(
    pointer_path: Path,
    *,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    require_current_provenance: bool = True,
) -> ArtifactRelease:
    """Resolve one pointer and reopen every artifact and provenance digest."""

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
    write_pointer: Callable[[Path, dict[str, object]], None] = write_json,
) -> ArtifactRelease:
    """Stage, stamp, reopen, and marker-release one complete artifact bundle."""

    if set(filenames) != set(writers) or set(filenames) != set(row_counts):
        raise ValueError("artifact release writers and row counts must match filenames")
    pointer_path = Path(pointer_path)
    release_root = pointer_path.parent
    release_root.mkdir(parents=True, exist_ok=True)
    with serialized_output_install(pointer_path):
        with tempfile.TemporaryDirectory(prefix=f".{kind}-", dir=release_root) as directory:
            staged = {
                name: Path(directory) / filename for name, filename in filenames.items()
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
            prepared_stamps = {
                name: prepare_stamp(
                    targets[name],
                    content_path=staged[name],
                    code_sources=code_sources,
                    inputs=inputs,
                    rows=int(row_counts[name]),
                    notes=notes,
                )
                for name in filenames
            }
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
            write_pointer(pointer_path, pointer)
            return _resolve_artifact_release_unlocked(
                pointer_path,
                kind=kind,
                schema_version=schema_version,
                filenames=filenames,
                require_current_provenance=True,
                expected_generation=generation,
            )
