"""Restartable, marker-last import of an immutable artifact release.

The transfer source is deliberately injected.  Discovery and remote stat are
read-only, while installation reuses the repository's artifact locks and exact
pointer bytes.  This keeps host access policy outside the scientific package.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, Mapping, Protocol

from ddvc.artifact_release import generation_id, is_sha256
from ddvc.provenance import sidecar_path
from ddvc.runtime import (
    atomic_output,
    file_sha256,
    serialized_output_installs,
    staged_output,
)


class ReadOnlyReleaseSource(Protocol):
    """The only remote operations an importer may request."""

    def read_pointer_bytes(self) -> bytes: ...

    def stat_size(self, relative_path: PurePosixPath) -> int: ...

    def rsync_spec(self, relative_path: PurePosixPath) -> str: ...


@dataclass(frozen=True)
class TransferPolicy:
    connect_timeout_seconds: int = 10
    server_alive_interval_seconds: int = 15
    server_alive_count_max: int = 2
    idle_timeout_seconds: int = 60
    hard_attempt_timeout_seconds: int = 600
    max_attempts: int = 4
    initial_backoff_seconds: float = 2.0
    maximum_backoff_seconds: float = 30.0
    eta_fresh_seconds: float = 120.0

    def __post_init__(self) -> None:
        integer_positive = (
            self.connect_timeout_seconds,
            self.server_alive_interval_seconds,
            self.server_alive_count_max,
            self.idle_timeout_seconds,
            self.hard_attempt_timeout_seconds,
            self.max_attempts,
        )
        if any(value < 1 for value in integer_positive):
            raise ValueError("transfer timeouts and attempt count must be positive")
        if self.initial_backoff_seconds < 0 or self.maximum_backoff_seconds < 0:
            raise ValueError("transfer backoff cannot be negative")
        if self.initial_backoff_seconds > self.maximum_backoff_seconds:
            raise ValueError("initial transfer backoff exceeds its maximum")
        if self.eta_fresh_seconds <= 0:
            raise ValueError("ETA freshness window must be positive")


@dataclass(frozen=True)
class ReleaseObject:
    """One pointer-bound payload or provenance object."""

    key: str
    relative_path: PurePosixPath
    staged_path: Path
    final_path: Path
    expected_size: int
    expected_sha256: str


@dataclass(frozen=True)
class DiscoveredRelease:
    pointer_bytes: bytes
    pointer_sha256: str
    pointer: Mapping[str, object]
    generation_id: str
    objects: tuple[ReleaseObject, ...]
    stage_root: Path

    @property
    def total_bytes(self) -> int:
        return sum(item.expected_size for item in self.objects)


def _safe_relative(path: PurePosixPath) -> PurePosixPath:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"release source path is not a safe relative path: {path}")
    return path


def _pointer_record_size(
    record: Mapping[str, object],
    field: str,
    *,
    source: ReadOnlyReleaseSource,
    relative_path: PurePosixPath,
) -> int:
    declared = record.get(field)
    if declared is None:
        size = source.stat_size(relative_path)
    elif isinstance(declared, bool) or not isinstance(declared, int):
        raise ValueError(f"pointer {field} is not an integer")
    else:
        size = declared
    if size < 0:
        raise ValueError(f"pointer {field} is negative")
    return size


def discover_release(
    *,
    source: ReadOnlyReleaseSource,
    local_pointer: Path,
    pointer_repo_relative: PurePosixPath,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
) -> DiscoveredRelease:
    """Capture and validate one exact pointer before any transfer starts."""

    pointer_repo_relative = _safe_relative(pointer_repo_relative)
    seen_filenames: set[str] = set()
    for filename in filenames.values():
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
        ):
            raise ValueError(f"release filename is not a simple basename: {filename!r}")
        if filename in seen_filenames:
            raise ValueError(f"release filenames are not unique: {filename}")
        seen_filenames.add(filename)
    pointer_bytes = source.read_pointer_bytes()
    pointer_sha = hashlib.sha256(pointer_bytes).hexdigest()
    try:
        pointer = json.loads(pointer_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("remote release pointer is not valid UTF-8 JSON") from error
    generation = pointer.get("generation_id") if isinstance(pointer, dict) else None
    build_identity = pointer.get("build_identity_sha256") if isinstance(pointer, dict) else None
    records = pointer.get("artifacts") if isinstance(pointer, dict) else None
    if (
        not isinstance(pointer, dict)
        or pointer.get("kind") != kind
        or pointer.get("schema_version") != schema_version
        or not is_sha256(generation)
        or not is_sha256(build_identity)
        or not isinstance(records, dict)
        or set(records) != set(filenames)
    ):
        raise ValueError("remote release pointer has the wrong schema or perimeter")

    artifact_hashes: dict[str, str] = {}
    for name, expected_filename in filenames.items():
        record = records.get(name)
        if (
            not isinstance(record, dict)
            or record.get("filename") != expected_filename
            or not is_sha256(record.get("sha256"))
            or not is_sha256(record.get("provenance_sha256"))
        ):
            raise ValueError(f"remote release pointer has an invalid record: {name}")
        artifact_hashes[name] = str(record["sha256"])
    if generation_id(artifact_hashes, str(build_identity)) != generation:
        raise ValueError("remote release generation identity disagrees with its pointer")

    release_relative = pointer_repo_relative.parent
    generation_relative = release_relative / "generations" / str(generation)
    stage_root = local_pointer.parent / ".incoming" / pointer_sha / str(generation)
    objects: list[ReleaseObject] = []
    for name, filename in filenames.items():
        record = records[name]
        assert isinstance(record, dict)
        payload_relative = _safe_relative(generation_relative / filename)
        provenance_relative = _safe_relative(
            PurePosixPath("data/manifests")
            / payload_relative.with_suffix(payload_relative.suffix + ".prov.json")
        )
        final_payload = local_pointer.parent / "generations" / str(generation) / filename
        final_provenance = sidecar_path(final_payload)
        objects.extend(
            (
                ReleaseObject(
                    key=name,
                    relative_path=payload_relative,
                    staged_path=stage_root / "payloads" / filename,
                    final_path=final_payload,
                    expected_size=_pointer_record_size(
                        record,
                        "size_bytes",
                        source=source,
                        relative_path=payload_relative,
                    ),
                    expected_sha256=str(record["sha256"]),
                ),
                ReleaseObject(
                    key=f"{name}.provenance",
                    relative_path=provenance_relative,
                    staged_path=stage_root / "provenance" / f"{filename}.prov.json",
                    final_path=final_provenance,
                    expected_size=_pointer_record_size(
                        record,
                        "provenance_size_bytes",
                        source=source,
                        relative_path=provenance_relative,
                    ),
                    expected_sha256=str(record["provenance_sha256"]),
                ),
            )
        )
    return DiscoveredRelease(
        pointer_bytes=pointer_bytes,
        pointer_sha256=pointer_sha,
        pointer=pointer,
        generation_id=str(generation),
        objects=tuple(objects),
        stage_root=stage_root,
    )


def build_rsync_command(
    *, source_spec: str, destination: Path, policy: TransferPolicy
) -> list[str]:
    """Construct one fresh, bounded, resumable transfer attempt."""

    ssh = [
        "ssh",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        f"ConnectTimeout={policy.connect_timeout_seconds}",
        "-o",
        f"ServerAliveInterval={policy.server_alive_interval_seconds}",
        "-o",
        f"ServerAliveCountMax={policy.server_alive_count_max}",
    ]
    return [
        "rsync",
        "--partial",
        "--inplace",
        f"--timeout={policy.idle_timeout_seconds}",
        "-e",
        shlex.join(ssh),
        source_spec,
        str(destination),
    ]


class SSHReleaseSource:
    """Read-only source rooted at one absolute repository on an SSH host."""

    def __init__(
        self,
        *,
        host: str,
        remote_repo_root: PurePosixPath,
        pointer_repo_relative: PurePosixPath,
        policy: TransferPolicy,
        run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        if (
            not host
            or host.startswith("-")
            or any(character.isspace() for character in host)
        ):
            raise ValueError("SSH host must be a non-option, non-empty token")
        if not remote_repo_root.is_absolute():
            raise ValueError("remote repository root must be absolute")
        self.host = host
        self.remote_repo_root = remote_repo_root
        self.pointer_repo_relative = _safe_relative(pointer_repo_relative)
        self.policy = policy
        self._run = run

    def _ssh(self, command: str) -> bytes:
        argv = [
            "ssh",
            "-o",
            "ControlMaster=no",
            "-o",
            "ControlPath=none",
            "-o",
            f"ConnectTimeout={self.policy.connect_timeout_seconds}",
            "-o",
            f"ServerAliveInterval={self.policy.server_alive_interval_seconds}",
            "-o",
            f"ServerAliveCountMax={self.policy.server_alive_count_max}",
            self.host,
            command,
        ]
        completed = self._run(
            argv,
            check=True,
            capture_output=True,
            timeout=self.policy.hard_attempt_timeout_seconds,
        )
        return completed.stdout

    def _absolute(self, relative_path: PurePosixPath) -> PurePosixPath:
        return self.remote_repo_root / _safe_relative(relative_path)

    def read_pointer_bytes(self) -> bytes:
        path = self._absolute(self.pointer_repo_relative)
        return self._ssh(f"cat -- {shlex.quote(str(path))}")

    def stat_size(self, relative_path: PurePosixPath) -> int:
        path = self._absolute(relative_path)
        raw = self._ssh(f"wc -c < {shlex.quote(str(path))}")
        try:
            size = int(raw.strip())
        except ValueError as error:
            raise ValueError(f"remote stat returned an invalid size for {relative_path}") from error
        if size < 0:
            raise ValueError(f"remote stat returned a negative size for {relative_path}")
        return size

    def rsync_spec(self, relative_path: PurePosixPath) -> str:
        path = self._absolute(relative_path)
        return f"{self.host}:{shlex.quote(str(path))}"


class _StatusWriter:
    def __init__(
        self,
        path: Path,
        release: DiscoveredRelease,
        *,
        fresh_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self.path = path
        self.release = release
        self.fresh_seconds = fresh_seconds
        self.clock = clock
        self.started_at = clock()
        self.last_progress_at: float | None = None
        self.last_total = self._bytes_present()
        self.initial_total = self.last_total
        self.samples: deque[tuple[float, int]] = deque([(self.started_at, self.last_total)], maxlen=16)
        self.lock = threading.Lock()

    def _bytes_present(self) -> int:
        total = 0
        for item in self.release.objects:
            try:
                total += min(item.staged_path.stat().st_size, item.expected_size)
            except FileNotFoundError:
                pass
        return total

    def write(
        self,
        state: str,
        *,
        member: ReleaseObject | None = None,
        attempt: int = 0,
        error: str | None = None,
    ) -> None:
        with self.lock:
            now = self.clock()
            total = self._bytes_present()
            if total > self.last_total:
                self.last_progress_at = now
            self.last_total = total
            self.samples.append((now, total))
            while len(self.samples) > 2 and now - self.samples[0][0] > 120:
                self.samples.popleft()
            rolling_elapsed = now - self.samples[0][0]
            rolling_delta = total - self.samples[0][1]
            rolling_bps = (
                max(0, rolling_delta) / rolling_elapsed if rolling_elapsed > 0 else 0.0
            )
            lifetime_elapsed = now - self.started_at
            lifetime_delta = total - self.initial_total if lifetime_elapsed > 0 else 0
            lifetime_bps = (
                max(0, lifetime_delta) / lifetime_elapsed if lifetime_elapsed > 0 else 0.0
            )
            last_age = (
                None if self.last_progress_at is None else max(0.0, now - self.last_progress_at)
            )
            eta = None
            if (
                last_age is not None
                and last_age <= self.fresh_seconds
                and rolling_bps > 0
                and total < self.release.total_bytes
            ):
                eta = (self.release.total_bytes - total) / rolling_bps
            member_bytes = 0
            member_percent = None
            if member is not None:
                try:
                    member_bytes = min(member.staged_path.stat().st_size, member.expected_size)
                except FileNotFoundError:
                    pass
                member_percent = (
                    100.0 if member.expected_size == 0 else 100.0 * member_bytes / member.expected_size
                )
            record = {
                "schema_version": 1,
                "state": state,
                "pointer_sha256": self.release.pointer_sha256,
                "generation_id": self.release.generation_id,
                "member": None if member is None else member.key,
                "member_bytes": member_bytes,
                "member_total_bytes": None if member is None else member.expected_size,
                "member_percent": member_percent,
                "total_bytes": total,
                "expected_total_bytes": self.release.total_bytes,
                "total_percent": (
                    100.0
                    if self.release.total_bytes == 0
                    else 100.0 * total / self.release.total_bytes
                ),
                "rolling_bytes_per_second": rolling_bps,
                "lifetime_bytes_per_second": lifetime_bps,
                "eta_seconds": eta,
                "last_progress_age_seconds": last_age,
                "attempt": attempt,
                "error": error,
            }
            with atomic_output(self.path) as temporary:
                temporary.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")


CommandRunner = Callable[[list[str], float, Callable[[], None]], None]
LeaseFactory = Callable[[Path], AbstractContextManager[object]]


def _subprocess_command_runner(
    command: list[str], hard_timeout: float, progress: Callable[[], None]
) -> None:
    """Run one rsync in its own group, polling bytes and enforcing a hard bound."""

    process = subprocess.Popen(command, start_new_session=True)
    deadline = time.monotonic() + hard_timeout
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise subprocess.TimeoutExpired(command, hard_timeout)
            progress()
            time.sleep(min(1.0, remaining))
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise


def _verified(path: Path, expected_size: int, expected_sha256: str) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == expected_size
        and file_sha256(path) == expected_sha256
    )


def _transfer_one(
    item: ReleaseObject,
    *,
    source: ReadOnlyReleaseSource,
    policy: TransferPolicy,
    status: _StatusWriter,
    run_command: CommandRunner,
    sleep: Callable[[float], None],
) -> None:
    item.staged_path.parent.mkdir(parents=True, exist_ok=True)
    if _verified(item.staged_path, item.expected_size, item.expected_sha256):
        status.write("transferring", member=item)
        return
    for attempt in range(1, policy.max_attempts + 1):
        if item.staged_path.exists() or item.staged_path.is_symlink():
            if (
                item.staged_path.is_symlink()
                or not item.staged_path.is_file()
                or item.staged_path.stat().st_size >= item.expected_size
            ):
                item.staged_path.unlink()
        status.write("transferring", member=item, attempt=attempt)
        command = build_rsync_command(
            source_spec=source.rsync_spec(item.relative_path),
            destination=item.staged_path,
            policy=policy,
        )
        try:
            run_command(
                command,
                policy.hard_attempt_timeout_seconds,
                lambda: status.write("transferring", member=item, attempt=attempt),
            )
            observed_size = item.staged_path.stat().st_size
            if observed_size != item.expected_size:
                raise ValueError(
                    f"{item.key} size mismatch: expected {item.expected_size}, observed {observed_size}"
                )
            if file_sha256(item.staged_path) != item.expected_sha256:
                item.staged_path.unlink()
                raise ValueError(f"{item.key} SHA-256 mismatch")
            status.write("transferring", member=item, attempt=attempt)
            return
        except (FileNotFoundError, OSError, subprocess.SubprocessError, ValueError) as error:
            status.write("retrying", member=item, attempt=attempt, error=str(error))
            if attempt == policy.max_attempts:
                raise RuntimeError(
                    f"failed to transfer {item.key} after {attempt} attempts"
                ) from error
            backoff = min(
                policy.maximum_backoff_seconds,
                policy.initial_backoff_seconds * (2 ** (attempt - 1)),
            )
            sleep(backoff)


def _install_verified(
    release: DiscoveredRelease,
    *,
    local_pointer: Path,
    lease_factory: LeaseFactory,
) -> object:
    outputs = tuple(item.final_path for item in release.objects) + (local_pointer,)
    installed: list[ReleaseObject] = []
    with serialized_output_installs(outputs):
        prior_pointer = local_pointer.read_bytes() if local_pointer.is_file() else None
        try:
            for item in release.objects:
                if not _verified(item.staged_path, item.expected_size, item.expected_sha256):
                    raise RuntimeError(
                        f"staged release object changed before install: {item.key}"
                    )
                if _verified(item.final_path, item.expected_size, item.expected_sha256):
                    continue
                with staged_output(item.final_path) as temporary:
                    shutil.copyfile(item.staged_path, temporary)
                    if not _verified(temporary, item.expected_size, item.expected_sha256):
                        raise RuntimeError(f"installed copy failed verification: {item.key}")
                    temporary.replace(item.final_path)
                installed.append(item)
            with staged_output(local_pointer) as temporary_pointer:
                temporary_pointer.write_bytes(release.pointer_bytes)
                if file_sha256(temporary_pointer) != release.pointer_sha256:
                    raise RuntimeError("staged pointer bytes changed before publication")
                temporary_pointer.replace(local_pointer)
            with lease_factory(local_pointer) as reopened:
                generation = getattr(reopened, "generation_id", None)
                if generation != release.generation_id:
                    raise RuntimeError("typed lease reopened a different generation")
                return reopened
        except BaseException:
            if prior_pointer is None:
                local_pointer.unlink(missing_ok=True)
            else:
                with staged_output(local_pointer) as rollback:
                    rollback.write_bytes(prior_pointer)
                    rollback.replace(local_pointer)
            # The verified source snapshot remains resumable under .incoming.
            # Remove only objects this attempt installed, leaving pre-existing
            # byte-identical generation members untouched.
            for item in installed:
                if _verified(item.final_path, item.expected_size, item.expected_sha256):
                    item.final_path.unlink()
            raise


def import_release(
    *,
    source: ReadOnlyReleaseSource,
    local_pointer: Path,
    pointer_repo_relative: PurePosixPath,
    kind: str,
    schema_version: int,
    filenames: Mapping[str, str],
    lease_factory: LeaseFactory,
    status_path: Path,
    jobs: int = 1,
    policy: TransferPolicy = TransferPolicy(),
    run_command: CommandRunner = _subprocess_command_runner,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> object:
    """Import one immutable pointer snapshot and reopen its typed lease."""

    if jobs not in {1, 2}:
        raise ValueError("artifact import jobs must be 1 or 2")
    release = discover_release(
        source=source,
        local_pointer=local_pointer,
        pointer_repo_relative=pointer_repo_relative,
        kind=kind,
        schema_version=schema_version,
        filenames=filenames,
    )
    status = _StatusWriter(
        status_path,
        release,
        fresh_seconds=policy.eta_fresh_seconds,
        clock=clock,
    )
    status.write("discovered")
    try:
        if jobs == 1:
            for item in release.objects:
                _transfer_one(
                    item,
                    source=source,
                    policy=policy,
                    status=status,
                    run_command=run_command,
                    sleep=sleep,
                )
        else:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _transfer_one,
                        item,
                        source=source,
                        policy=policy,
                        status=status,
                        run_command=run_command,
                        sleep=sleep,
                    )
                    for item in release.objects
                ]
                for future in futures:
                    future.result()
        status.write("verifying")
        for item in release.objects:
            if not _verified(item.staged_path, item.expected_size, item.expected_sha256):
                raise RuntimeError(f"release object failed final verification: {item.key}")
        if source.read_pointer_bytes() != release.pointer_bytes:
            raise RuntimeError("remote release pointer drifted during transfer")
        status.write("installing")
        result = _install_verified(
            release,
            local_pointer=local_pointer,
            lease_factory=lease_factory,
        )
        status.write("complete")
        return result
    except BaseException as error:
        status.write("failed", error=str(error))
        raise
