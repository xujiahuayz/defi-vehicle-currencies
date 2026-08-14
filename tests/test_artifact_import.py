from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from types import SimpleNamespace

import pandas as pd
import pytest

import ddvc.artifact_import as artifact_import
import ddvc.provenance as provenance
from ddvc.artifact_import import (
    SSHReleaseSource,
    TransferPolicy,
    _StatusWriter,
    build_rsync_command,
    discover_release,
    import_release,
)
from ddvc.artifact_release import generation_id
from ddvc.endpoint_candidate_composition import (
    CHOICE_AUDIT_COLUMNS,
    CHOICE_COLUMNS,
    EXCLUSION_COLUMNS,
    PAIR_SUPPORT_COLUMNS,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
    current_endpoint_candidate_composition_release,
    publish_endpoint_candidate_composition_release,
)
from ddvc.provenance import sidecar_path


KIND = "test_release"
SCHEMA = 4
FILENAMES = {"rows": "rows.bin", "audit": "audit.bin"}
POINTER_RELATIVE = PurePosixPath("data/processed/test_release/current.json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalReadOnlySource:
    def __init__(self, root: Path, pointer_relative: PurePosixPath) -> None:
        self.root = root
        self.pointer_relative = pointer_relative
        self.pointer_reads = 0
        self.stat_calls: list[PurePosixPath] = []
        self.pointer_versions: list[bytes] | None = None

    def read_pointer_bytes(self) -> bytes:
        index = self.pointer_reads
        self.pointer_reads += 1
        if self.pointer_versions is not None:
            return self.pointer_versions[min(index, len(self.pointer_versions) - 1)]
        return (self.root / self.pointer_relative).read_bytes()

    def stat_size(self, relative_path: PurePosixPath) -> int:
        self.stat_calls.append(relative_path)
        return (self.root / relative_path).stat().st_size

    def rsync_spec(self, relative_path: PurePosixPath) -> str:
        return str(self.root / relative_path)


def _write_source(
    root: Path,
    *,
    include_sizes: bool = False,
    payloads: dict[str, bytes] | None = None,
) -> tuple[bytes, str]:
    payloads = payloads or {"rows": b"row-data\n", "audit": b"audit-data\n"}
    build_identity = "b" * 64
    artifact_hashes = {name: _sha(payloads[name]) for name in FILENAMES}
    generation = generation_id(artifact_hashes, build_identity)
    records: dict[str, dict[str, object]] = {}
    for name, filename in FILENAMES.items():
        payload_relative = POINTER_RELATIVE.parent / "generations" / generation / filename
        sidecar_relative = (
            PurePosixPath("data/manifests")
            / payload_relative.with_suffix(payload_relative.suffix + ".prov.json")
        )
        sidecar = json.dumps({"name": name, "generation": generation}, sort_keys=True).encode() + b"\n"
        (root / payload_relative).parent.mkdir(parents=True, exist_ok=True)
        (root / payload_relative).write_bytes(payloads[name])
        (root / sidecar_relative).parent.mkdir(parents=True, exist_ok=True)
        (root / sidecar_relative).write_bytes(sidecar)
        record: dict[str, object] = {
            "filename": filename,
            "sha256": artifact_hashes[name],
            "provenance_sha256": _sha(sidecar),
        }
        if include_sizes:
            record["size_bytes"] = len(payloads[name])
            record["provenance_size_bytes"] = len(sidecar)
        records[name] = record
    pointer = {
        "schema_version": SCHEMA,
        "kind": KIND,
        "generation_id": generation,
        "build_identity_sha256": build_identity,
        "artifacts": records,
    }
    pointer_bytes = json.dumps(pointer, sort_keys=True, indent=2).encode() + b"\n"
    path = root / POINTER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pointer_bytes)
    return pointer_bytes, generation


def _copy_runner(
    command: list[str], _timeout: float, _progress
) -> None:
    shutil.copyfile(Path(command[-2]), Path(command[-1]))


def _lease_factory(filenames=FILENAMES):
    @contextmanager
    def lease(pointer_path: Path):
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        generation = pointer["generation_id"]
        for name, filename in filenames.items():
            record = pointer["artifacts"][name]
            payload = pointer_path.parent / "generations" / generation / filename
            assert _sha(payload.read_bytes()) == record["sha256"]
            assert _sha(sidecar_path(payload).read_bytes()) == record["provenance_sha256"]
        yield SimpleNamespace(generation_id=generation)

    return lease


def _run(
    remote: Path,
    local: Path,
    *,
    source: LocalReadOnlySource | None = None,
    runner=_copy_runner,
    lease_factory=None,
    policy: TransferPolicy | None = None,
    clock=None,
):
    source = source or LocalReadOnlySource(remote, POINTER_RELATIVE)
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    return import_release(
        source=source,
        local_pointer=local / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
        lease_factory=lease_factory or _lease_factory(),
        status_path=local / "status.json",
        policy=policy
        or TransferPolicy(max_attempts=3, initial_backoff_seconds=0, maximum_backoff_seconds=0),
        run_command=runner,
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_rsync_command_is_resumable_fresh_and_bounded() -> None:
    policy = TransferPolicy(
        connect_timeout_seconds=7,
        server_alive_interval_seconds=11,
        server_alive_count_max=3,
        idle_timeout_seconds=47,
        hard_attempt_timeout_seconds=91,
    )
    command = build_rsync_command(
        source_spec="studio:/immutable/member", destination=Path("/tmp/member"), policy=policy
    )
    assert "--partial" in command
    assert "--inplace" in command
    assert not any("append" in argument for argument in command)
    assert "--timeout=47" in command
    ssh = command[command.index("-e") + 1]
    assert "ControlMaster=no" in ssh
    assert "ConnectTimeout=7" in ssh
    assert "ServerAliveInterval=11" in ssh
    assert "ServerAliveCountMax=3" in ssh


def test_ssh_source_rejects_option_like_host() -> None:
    with pytest.raises(ValueError, match="non-option"):
        SSHReleaseSource(
            host="-oProxyCommand=malicious",
            remote_repo_root=PurePosixPath("/srv/project"),
            pointer_repo_relative=POINTER_RELATIVE,
            policy=TransferPolicy(),
        )


def test_declared_sizes_avoid_remote_stat_and_stage_under_pointer_identity(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, generation = _write_source(remote, include_sizes=True)
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    discovered = discover_release(
        source=source,
        local_pointer=local / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
    )
    assert source.stat_calls == []
    assert discovered.pointer_sha256 == _sha(pointer_bytes)
    assert discovered.stage_root == (
        local / POINTER_RELATIVE.parent / ".incoming" / _sha(pointer_bytes) / generation
    )


def test_remote_stat_fallback_covers_payloads_and_pointer_listed_sidecars(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    _write_source(remote)
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    discover_release(
        source=source,
        local_pointer=tmp_path / "local" / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
    )
    assert len(source.stat_calls) == 4
    assert sum(str(path).endswith(".prov.json") for path in source.stat_calls) == 2


@pytest.mark.parametrize("field,value", [("schema_version", 99), ("kind", "other")])
def test_pointer_schema_mismatch_is_rejected_before_transfer(
    tmp_path: Path, field: str, value: object
) -> None:
    remote = tmp_path / "remote"
    pointer_bytes, _generation = _write_source(remote)
    pointer = json.loads(pointer_bytes)
    pointer[field] = value
    (remote / POINTER_RELATIVE).write_text(json.dumps(pointer) + "\n", encoding="utf-8")
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    with pytest.raises(ValueError, match="wrong schema or perimeter"):
        discover_release(
            source=source,
            local_pointer=tmp_path / "local" / POINTER_RELATIVE,
            pointer_repo_relative=POINTER_RELATIVE,
            kind=KIND,
            schema_version=SCHEMA,
            filenames=FILENAMES,
        )
    assert source.stat_calls == []


def test_generation_identity_mismatch_is_rejected_before_transfer(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    pointer_bytes, _generation = _write_source(remote)
    pointer = json.loads(pointer_bytes)
    pointer["generation_id"] = "a" * 64
    (remote / POINTER_RELATIVE).write_text(json.dumps(pointer) + "\n", encoding="utf-8")
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    with pytest.raises(ValueError, match="generation identity"):
        discover_release(
            source=source,
            local_pointer=tmp_path / "local" / POINTER_RELATIVE,
            pointer_repo_relative=POINTER_RELATIVE,
            kind=KIND,
            schema_version=SCHEMA,
            filenames=FILENAMES,
        )
    assert source.stat_calls == []


def test_interruption_resumes_partial_without_mutating_source(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, _generation = _write_source(remote)
    before = {
        path.relative_to(remote): path.read_bytes()
        for path in remote.rglob("*")
        if path.is_file()
    }
    calls = 0

    def interrupted(command: list[str], _timeout: float, progress) -> None:
        nonlocal calls
        calls += 1
        source = Path(command[-2])
        destination = Path(command[-1])
        if calls == 1:
            destination.write_bytes(source.read_bytes()[:3])
            progress()
            raise TimeoutError("cut")
        shutil.copyfile(source, destination)

    _run(remote, local, runner=interrupted)
    assert calls == 5
    assert (local / POINTER_RELATIVE).read_bytes() == pointer_bytes
    after = {
        path.relative_to(remote): path.read_bytes()
        for path in remote.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("bad_size", [None, 10_000])
def test_wrong_prefix_same_size_and_oversize_are_repaired_before_rsync(
    tmp_path: Path, bad_size: int | None
) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _write_source(remote, include_sizes=True)
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    discovered = discover_release(
        source=source,
        local_pointer=local / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
    )
    first = discovered.objects[0]
    first.staged_path.parent.mkdir(parents=True, exist_ok=True)
    first.staged_path.write_bytes(
        b"x" * (first.expected_size if bad_size is None else bad_size)
    )
    observed_absent = False

    def runner(command: list[str], _timeout: float, _progress) -> None:
        nonlocal observed_absent
        destination = Path(command[-1])
        if destination == first.staged_path:
            observed_absent = not destination.exists()
        shutil.copyfile(Path(command[-2]), destination)

    _run(remote, local, source=source, runner=runner)
    assert observed_absent


def test_sha_mismatch_is_repaired_once_and_refused_when_persistent(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _write_source(remote)
    first_attempt = True

    def repairable(command: list[str], _timeout: float, _progress) -> None:
        nonlocal first_attempt
        destination = Path(command[-1])
        source = Path(command[-2])
        if first_attempt:
            first_attempt = False
            destination.write_bytes(b"z" * source.stat().st_size)
        else:
            shutil.copyfile(source, destination)

    _run(remote, local, runner=repairable)
    assert not first_attempt

    refused = tmp_path / "refused"
    prior = refused / POINTER_RELATIVE
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"old-pointer\n")

    def corrupt(command: list[str], _timeout: float, _progress) -> None:
        source = Path(command[-2])
        Path(command[-1]).write_bytes(b"q" * source.stat().st_size)

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        _run(
            remote,
            refused,
            runner=corrupt,
            policy=TransferPolicy(
                max_attempts=2,
                initial_backoff_seconds=0,
                maximum_backoff_seconds=0,
            ),
        )
    assert prior.read_bytes() == b"old-pointer\n"


def test_pointer_listed_provenance_sha_is_enforced(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, generation = _write_source(remote)
    pointer = json.loads(pointer_bytes)
    filename = FILENAMES["rows"]
    sidecar_relative = (
        PurePosixPath("data/manifests")
        / (POINTER_RELATIVE.parent / "generations" / generation / filename).with_suffix(
            ".bin.prov.json"
        )
    )
    sidecar = remote / sidecar_relative
    sidecar.write_bytes(b"x" * sidecar.stat().st_size)
    with pytest.raises(RuntimeError, match="rows.provenance"):
        _run(
            remote,
            local,
            policy=TransferPolicy(
                max_attempts=2,
                initial_backoff_seconds=0,
                maximum_backoff_seconds=0,
            ),
        )
    assert not (local / POINTER_RELATIVE).exists()
    assert pointer["artifacts"]["rows"]["provenance_sha256"] != _sha(
        sidecar.read_bytes()
    )


def test_pointer_drift_refuses_install_and_preserves_previous_pointer(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, _generation = _write_source(remote)
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    drift = json.loads(pointer_bytes)
    drift["extra"] = "new remote selection"
    source.pointer_versions = [pointer_bytes, json.dumps(drift).encode() + b"\n"]
    pointer = local / POINTER_RELATIVE
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"prior\n")
    with pytest.raises(RuntimeError, match="drifted"):
        _run(remote, local, source=source)
    assert pointer.read_bytes() == b"prior\n"


def test_pointer_is_installed_last_and_typed_lease_failure_rolls_it_back(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, generation = _write_source(remote)
    pointer = local / POINTER_RELATIVE
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"prior-pointer\n")
    lease_entered = False

    @contextmanager
    def rejecting_lease(pointer_path: Path):
        nonlocal lease_entered
        lease_entered = True
        assert pointer_path.read_bytes() == pointer_bytes
        parsed = json.loads(pointer_bytes)
        for name, filename in FILENAMES.items():
            member = pointer_path.parent / "generations" / generation / filename
            assert member.is_file()
            assert sidecar_path(member).is_file()
            assert _sha(member.read_bytes()) == parsed["artifacts"][name]["sha256"]
        raise ValueError("typed semantic rejection")
        yield

    with pytest.raises(ValueError, match="typed semantic rejection"):
        _run(remote, local, lease_factory=rejecting_lease)
    assert lease_entered
    assert pointer.read_bytes() == b"prior-pointer\n"
    incoming = pointer.parent / ".incoming" / _sha(pointer_bytes) / generation
    assert incoming.is_dir()
    assert len(tuple(incoming.rglob("*.*"))) >= 4
    for filename in FILENAMES.values():
        member = pointer.parent / "generations" / generation / filename
        assert not member.exists()
        assert not sidecar_path(member).exists()


def test_rollback_restores_pointer_observed_after_publication_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _write_source(remote)
    pointer = local / POINTER_RELATIVE
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"pointer-before-lock\n")
    pointer_inside_lock = b"newer-pointer-inside-lock\n"

    @contextmanager
    def competing_publication(_outputs):
        pointer.write_bytes(pointer_inside_lock)
        yield

    @contextmanager
    def rejecting_lease(_pointer_path: Path):
        raise ValueError("typed rejection after competing publication")
        yield

    monkeypatch.setattr(
        artifact_import, "serialized_output_installs", competing_publication
    )
    with pytest.raises(ValueError, match="typed rejection"):
        _run(remote, local, lease_factory=rejecting_lease)
    assert pointer.read_bytes() == pointer_inside_lock


def test_status_eta_requires_fresh_measured_progress(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _write_source(remote, include_sizes=True)
    source = LocalReadOnlySource(remote, POINTER_RELATIVE)
    release = discover_release(
        source=source,
        local_pointer=local / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
    )
    now = [10.0]
    status_path = local / "status.json"
    status = _StatusWriter(
        status_path, release, fresh_seconds=5, clock=lambda: now[0]
    )
    status.write("discovered")
    assert json.loads(status_path.read_text())["eta_seconds"] is None
    member = release.objects[0]
    member.staged_path.parent.mkdir(parents=True, exist_ok=True)
    member.staged_path.write_bytes(b"x" * min(2, member.expected_size))
    now[0] += 1
    status.write("transferring", member=member, attempt=1)
    fresh = json.loads(status_path.read_text())
    assert fresh["eta_seconds"] is not None
    assert fresh["rolling_bytes_per_second"] > 0
    now[0] += 6
    status.write("retrying", member=member, attempt=2, error="idle")
    stale = json.loads(status_path.read_text())
    assert stale["eta_seconds"] is None
    assert stale["last_progress_age_seconds"] == 6


def test_jobs_are_fail_closed_above_two(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _write_source(remote)
    with pytest.raises(ValueError, match="must be 1 or 2"):
        import_release(
            source=LocalReadOnlySource(remote, POINTER_RELATIVE),
            local_pointer=local / POINTER_RELATIVE,
            pointer_repo_relative=POINTER_RELATIVE,
            kind=KIND,
            schema_version=SCHEMA,
            filenames=FILENAMES,
            lease_factory=_lease_factory(),
            status_path=local / "status.json",
            jobs=3,
        )


def test_two_transfer_jobs_are_explicitly_supported(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    pointer_bytes, generation = _write_source(remote)
    imported = import_release(
        source=LocalReadOnlySource(remote, POINTER_RELATIVE),
        local_pointer=local / POINTER_RELATIVE,
        pointer_repo_relative=POINTER_RELATIVE,
        kind=KIND,
        schema_version=SCHEMA,
        filenames=FILENAMES,
        lease_factory=_lease_factory(),
        status_path=local / "status.json",
        jobs=2,
        policy=TransferPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        ),
        run_command=_copy_runner,
        sleep=lambda _seconds: None,
    )
    assert imported.generation_id == generation
    assert (local / POINTER_RELATIVE).read_bytes() == pointer_bytes


def test_real_endpoint_typed_lease_reopens_imported_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    monkeypatch.setattr(provenance, "ROOT", remote)
    monkeypatch.setattr(provenance, "MANIFESTS", remote / "data/manifests")
    pointer_relative = PurePosixPath(
        "data/processed/endpoint_candidate_composition_release/current.json"
    )
    remote_pointer = remote / pointer_relative
    empty_choices = pd.DataFrame(columns=CHOICE_COLUMNS)
    empty_audit = pd.DataFrame(columns=CHOICE_AUDIT_COLUMNS)
    empty_support = pd.DataFrame(columns=PAIR_SUPPORT_COLUMNS)
    empty_exclusions = pd.DataFrame(columns=EXCLUSION_COLUMNS)
    frames = {
        "choices": empty_choices,
        "choice_audit": empty_audit,
        "pair_support": empty_support,
        "exclusions": empty_exclusions,
    }
    published = publish_endpoint_candidate_composition_release(
        writers={
            name: lambda path, frame=frame: frame.to_parquet(path, index=False)
            for name, frame in frames.items()
        },
        row_counts={name: 0 for name in frames},
        code_sources=["src/ddvc/endpoint_candidate_composition_release.py"],
        inputs=[],
        notes="typed importer test",
        preinstall_validator=lambda _path: None,
        pointer_path=remote_pointer,
    )

    monkeypatch.setattr(provenance, "ROOT", local)
    monkeypatch.setattr(provenance, "MANIFESTS", local / "data/manifests")
    source = LocalReadOnlySource(remote, pointer_relative)
    imported = import_release(
        source=source,
        local_pointer=local / pointer_relative,
        pointer_repo_relative=pointer_relative,
        kind=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
        schema_version=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
        filenames=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
        lease_factory=current_endpoint_candidate_composition_release,
        status_path=local / "status.json",
        policy=TransferPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        ),
        run_command=_copy_runner,
        sleep=lambda _seconds: None,
    )
    assert imported.generation_id == published.generation_id
    assert (local / pointer_relative).read_bytes() == remote_pointer.read_bytes()
