from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading

import pytest

import ddvc.artifact_release as artifact_release
import ddvc.provenance as provenance
from ddvc.artifact_release import (
    ArtifactRelease,
    bind_file_lineage,
    current_artifact_release,
    current_file_lineage,
    file_sha256,
    generation_paths,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.runtime import atomic_output
from ddvc.fetch.raw import write_json
from ddvc.provenance import sidecar_path
from ddvc.journaled_publication import recover_journaled_publications


KIND = "test_release"
FILENAMES = {"rows": "rows.json", "certificate": "certificate.json"}


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, object], ...]:
    records: list[tuple[str, str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            records.append((relative, "symlink", path.readlink().as_posix()))
        elif path.is_dir():
            records.append((relative, "directory", None))
        else:
            records.append((relative, "file", path.read_bytes()))
    return tuple(records)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "../escape.json",
        "nested/value.json",
        "nested\\value.json",
        "nul\x00name.json",
    ],
)
@pytest.mark.parametrize("operation", ["publish", "resolve", "generation_paths"])
def test_invalid_filenames_are_rejected_before_any_mutation(
    tmp_path: Path, filename: str, operation: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    outside = tmp_path / "escape.json"
    outside.write_text("untouched", encoding="utf-8")
    selected = {"rows": filename}
    before = _tree_snapshot(tmp_path)
    with pytest.raises(ValueError, match="simple basename"):
        if operation == "publish":
            publish_artifact_release(
                pointer_path=pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
                writers={"rows": lambda path: path.write_text("mutated", encoding="utf-8")},
                row_counts={"rows": 1},
                code_sources=["src/ddvc/artifact_release.py"],
                inputs=[],
                notes="invalid filename",
                validate_staged=lambda _paths: None,
            )
        elif operation == "resolve":
            resolve_artifact_release(
                pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
            )
        else:
            generation_paths(tmp_path / "release", "a" * 64, selected)
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("operation", ["publish", "resolve", "generation_paths"])
def test_absolute_filename_is_rejected_before_any_mutation(
    tmp_path: Path, operation: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    outside = tmp_path / "outside.json"
    selected = {"rows": str(outside)}
    before = _tree_snapshot(tmp_path)
    with pytest.raises(ValueError, match="simple basename"):
        if operation == "publish":
            publish_artifact_release(
                pointer_path=pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
                writers={"rows": lambda path: path.write_text("mutated", encoding="utf-8")},
                row_counts={"rows": 1},
                code_sources=["src/ddvc/artifact_release.py"],
                inputs=[],
                notes="invalid filename",
                validate_staged=lambda _paths: None,
            )
        elif operation == "resolve":
            resolve_artifact_release(
                pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
            )
        else:
            generation_paths(tmp_path / "release", "a" * 64, selected)
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("operation", ["publish", "resolve", "generation_paths"])
def test_duplicate_normalized_filenames_are_rejected_without_mutation(
    tmp_path: Path, operation: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    selected = {"rows": "same.json", "certificate": Path("same.json")}
    before = _tree_snapshot(tmp_path)
    with pytest.raises(ValueError, match="not unique"):
        if operation == "publish":
            publish_artifact_release(
                pointer_path=pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
                writers={"rows": lambda _path: None, "certificate": lambda _path: None},
                row_counts={"rows": 1, "certificate": 1},
                code_sources=["src/ddvc/artifact_release.py"],
                inputs=[],
                notes="duplicate filenames",
                validate_staged=lambda _paths: None,
            )
        elif operation == "resolve":
            resolve_artifact_release(
                pointer,
                kind=KIND,
                schema_version=1,
                filenames=selected,
            )
        else:
            generation_paths(tmp_path / "release", "a" * 64, selected)
    assert _tree_snapshot(tmp_path) == before


def _publish(
    pointer: Path,
    value: int,
    *,
    inputs=None,
    row_count: int = 1,
    write_pointer=write_json,
    validate_staged=None,
    semantic_validator_fingerprint=None,
):
    payloads = {"rows": {"value": value}, "certificate": {"status": "pass", "value": value}}
    validate = validate_staged or (
        lambda paths: [json.loads(path.read_text()) for path in paths.values()]
    )
    return publish_artifact_release(
        pointer_path=pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
        writers={
            name: lambda path, payload=payload: write_json(path, payload)
            for name, payload in payloads.items()
        },
        row_counts={"rows": row_count, "certificate": row_count},
        code_sources=["src/ddvc/artifact_release.py"],
        inputs=inputs or [],
        notes="test bundle",
        validate_staged=validate,
        semantic_validator_fingerprint=semantic_validator_fingerprint,
        write_pointer=write_pointer,
    )


def _publish_large(pointer: Path) -> ArtifactRelease:
    payloads = {
        "rows": {"value": 7, "blob": "r" * 2_000_000},
        "certificate": {"status": "pass", "value": 7, "blob": "c" * 1_500_000},
    }
    return publish_artifact_release(
        pointer_path=pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
        writers={
            name: lambda path, payload=payload: write_json(path, payload)
            for name, payload in payloads.items()
        },
        row_counts={"rows": 1, "certificate": 1},
        code_sources=["src/ddvc/artifact_release.py"],
        inputs=[],
        notes="test bundle",
        validate_staged=lambda paths: [json.loads(path.read_text()) for path in paths.values()],
    )


def test_relative_records_reopen_against_the_provenance_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "source.json"
    source.write_text('{"value": 1}\n', encoding="utf-8")
    pointer = root / "release" / "current.json"
    monkeypatch.setattr(provenance, "ROOT", root)
    monkeypatch.setattr(provenance, "MANIFESTS", root / "manifests")

    published = _publish(pointer, 1, inputs=[source])
    reopened = resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    )

    assert reopened.generation_id == published.generation_id
    assert reopened.input_paths == (source.resolve(),)


def test_marker_last_interruption_preserves_the_prior_release(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)

    def interrupted(_path: Path, _payload: dict[str, object]) -> None:
        raise RuntimeError("simulated pointer interruption")

    with pytest.raises(RuntimeError, match="pointer interruption"):
        _publish(pointer, 2, write_pointer=interrupted)

    reopened = resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    )
    assert reopened.generation_id == first.generation_id
    assert json.loads(reopened.artifacts["rows"].read_text()) == {"value": 1}


def test_reader_cannot_observe_failed_pointer_publication(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    pointer_written = threading.Event()
    release_failure = threading.Event()
    observations: list[object] = []

    def fail_after_write(path: Path, payload: dict[str, object]) -> None:
        write_json(path, payload)
        pointer_written.set()
        assert release_failure.wait(timeout=10)
        raise RuntimeError("simulated pointer publication")

    def publish() -> None:
        with pytest.raises(RuntimeError, match="pointer publication"):
            _publish(pointer, 2, write_pointer=fail_after_write)

    def read() -> None:
        assert pointer_written.wait(timeout=10)
        observations.append(
            resolve_artifact_release(
                pointer,
                kind=KIND,
                schema_version=1,
                filenames=FILENAMES,
            )
        )

    publisher = threading.Thread(target=publish)
    reader = threading.Thread(target=read)
    publisher.start()
    assert pointer_written.wait(timeout=10)
    reader.start()
    release_failure.set()
    publisher.join(timeout=10)
    reader.join(timeout=10)
    assert not publisher.is_alive() and not reader.is_alive()
    assert len(observations) == 1
    observed = observations[0]
    assert isinstance(observed, ArtifactRelease)
    assert observed.generation_id == first.generation_id
    assert json.loads(observed.artifacts["rows"].read_text()) == {"value": 1}


def test_current_release_lease_blocks_pointer_switch_twenty_times(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    for trial in range(20):
        selected = _publish(pointer, trial)
        entered = threading.Event()
        completed = threading.Event()

        def switch() -> None:
            entered.set()
            _publish(pointer, trial + 1000)
            completed.set()

        with current_artifact_release(selected):
            thread = threading.Thread(target=switch)
            thread.start()
            assert entered.wait(timeout=1)
            assert not completed.wait(timeout=0.02)
            assert json.loads(selected.artifacts["rows"].read_text()) == {
                "value": trial
            }
        thread.join(timeout=2)
        assert completed.is_set()


def test_absent_file_lineage_lease_blocks_creation_until_reader_exits(
    tmp_path: Path,
) -> None:
    target = tmp_path / "absent.json"
    lease = bind_file_lineage([target], allow_missing=True)
    entered = threading.Event()
    completed = threading.Event()

    def create() -> None:
        entered.set()
        with atomic_output(target) as temporary:
            temporary.write_text("created\n", encoding="utf-8")
        completed.set()

    with current_file_lineage(lease):
        thread = threading.Thread(target=create)
        thread.start()
        assert entered.wait(timeout=1)
        assert not completed.wait(timeout=0.05)
        assert not target.exists()
    thread.join(timeout=2)
    assert completed.is_set()


def test_dangling_symlink_is_not_bound_as_an_absent_source(tmp_path: Path) -> None:
    dangling = tmp_path / "dangling"
    dangling.symlink_to("missing")
    with pytest.raises(FileNotFoundError, match="dangling symlink"):
        bind_file_lineage([dangling], allow_missing=True)


def test_dangling_symlink_ancestor_is_not_bound_as_an_absent_source(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to("missing-directory", target_is_directory=True)

    with pytest.raises(FileNotFoundError, match="dangling symlink ancestor"):
        bind_file_lineage([alias / "new.json"], allow_missing=True)


def test_absent_file_lineage_detects_a_new_dangling_symlink(tmp_path: Path) -> None:
    target = tmp_path / "absent.json"
    lease = bind_file_lineage([target], allow_missing=True)
    target.symlink_to("still-missing.json")

    with pytest.raises(RuntimeError, match="absent source file appeared"):
        lease.assert_current()


def test_absent_alias_lease_blocks_publication_through_its_referent(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    alias_target = alias / "current.json"
    real_target = real / "current.json"
    lease = bind_file_lineage([alias_target], allow_missing=True)
    attempted = threading.Event()
    completed = threading.Event()

    def publish() -> None:
        attempted.set()
        with atomic_output(real_target) as temporary:
            temporary.write_text("published\n", encoding="utf-8")
        completed.set()

    with current_file_lineage(lease):
        thread = threading.Thread(target=publish)
        thread.start()
        assert attempted.wait(timeout=1)
        assert not completed.wait(timeout=0.05)
        assert not alias_target.exists()
    thread.join(timeout=2)
    assert completed.is_set()
    assert alias_target.read_text(encoding="utf-8") == "published\n"


def test_semantic_bundle_validation_runs_once_before_pointer_publication(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    validation_calls = 0

    def reject_installed_bundle(paths: dict[str, Path]) -> None:
        nonlocal validation_calls
        validation_calls += 1
        [json.loads(path.read_text()) for path in paths.values()]
    second = _publish(pointer, 2, validate_staged=reject_installed_bundle)

    assert validation_calls == 1
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == second.generation_id
    assert second.generation_id != first.generation_id


def test_legacy_publication_does_not_synthesize_a_semantic_receipt(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    release = _publish(pointer, 1)
    assert release.semantic_receipt is None
    assert "semantic_validation" not in json.loads(pointer.read_text(encoding="utf-8"))


def test_invalid_semantics_cannot_install_a_pointer_or_receipt(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    pointer_before = pointer.read_bytes()
    validation_calls = 0

    def reject_staged(_paths: dict[str, Path]) -> None:
        nonlocal validation_calls
        validation_calls += 1
        raise ValueError("invalid bundle semantics")

    with pytest.raises(ValueError, match="invalid bundle semantics"):
        _publish(pointer, 2, validate_staged=reject_staged)

    assert validation_calls == 1
    assert pointer.read_bytes() == pointer_before
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == first.generation_id


@pytest.mark.parametrize("tamper", ["alternate", "missing"])
def test_expected_receipt_must_equal_the_pointer_receipt(
    tmp_path: Path, tamper: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    release = _publish(pointer, 1, semantic_validator_fingerprint="e" * 64)
    assert release.semantic_receipt is not None
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    if tamper == "alternate":
        payload["semantic_validation"]["validator_fingerprint"] = "f" * 64
    else:
        payload.pop("semantic_validation")
    write_json(pointer, payload)

    with pytest.raises(ValueError, match="receipt"):
        resolve_artifact_release(
            pointer,
            kind=KIND,
            schema_version=1,
            filenames=FILENAMES,
            semantic_validator_fingerprint=(
                release.semantic_receipt.validator_fingerprint
            ),
            semantic=False,
            expected_semantic_receipt=release.semantic_receipt,
        )


def test_post_pointer_validation_failure_rolls_back_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    original = artifact_release._resolve_artifact_release_unlocked

    def reject_new(path: Path, **kwargs):
        if kwargs.get("expected_generation") is not None:
            raise RuntimeError("post-install rejection")
        return original(path, **kwargs)

    monkeypatch.setattr(
        artifact_release, "_resolve_artifact_release_unlocked", reject_new
    )
    with pytest.raises(RuntimeError, match="post-install rejection"):
        _publish(pointer, 2)
    monkeypatch.setattr(
        artifact_release, "_resolve_artifact_release_unlocked", original
    )
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == first.generation_id

    empty_pointer = tmp_path / "empty" / "current.json"
    monkeypatch.setattr(
        artifact_release, "_resolve_artifact_release_unlocked", reject_new
    )
    with pytest.raises(RuntimeError, match="post-install rejection"):
        _publish(empty_pointer, 3)
    assert not empty_pointer.exists()


def test_identical_retry_never_rewrites_the_selected_generation(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    provenance = {
        name: sidecar_path(path).read_bytes() for name, path in first.artifacts.items()
    }

    def interrupted(_path: Path, _payload: dict[str, object]) -> None:
        raise RuntimeError("simulated pointer interruption")

    with pytest.raises(RuntimeError, match="pointer interruption"):
        _publish(pointer, 1, write_pointer=interrupted)

    reopened = resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    )
    assert reopened.generation_id == first.generation_id
    assert {
        name: sidecar_path(path).read_bytes()
        for name, path in reopened.artifacts.items()
    } == provenance


def test_identical_retry_reuses_an_unselected_complete_generation_byte_for_byte(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    artifact_bytes = {name: path.read_bytes() for name, path in first.artifacts.items()}
    provenance_bytes = {
        name: sidecar_path(path).read_bytes() for name, path in first.artifacts.items()
    }
    artifact_mtimes = {
        name: path.stat().st_mtime_ns for name, path in first.artifacts.items()
    }
    _publish(pointer, 2)

    reopened = _publish(pointer, 1)

    assert reopened.generation_id == first.generation_id
    assert {
        name: path.read_bytes() for name, path in reopened.artifacts.items()
    } == artifact_bytes
    assert {
        name: sidecar_path(path).read_bytes()
        for name, path in reopened.artifacts.items()
    } == provenance_bytes
    assert {
        name: path.stat().st_mtime_ns for name, path in reopened.artifacts.items()
    } == artifact_mtimes


def test_declared_row_counts_are_bound_into_the_generation_identity(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1, row_count=1)

    second = _publish(pointer, 1, row_count=2)

    assert second.generation_id != first.generation_id
    assert {
        json.loads(sidecar_path(path).read_text(encoding="utf-8"))["rows"]
        for path in second.artifacts.values()
    } == {2}


def test_input_order_does_not_prevent_reopening_the_same_unselected_generation(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first_input = tmp_path / "first.json"
    second_input = tmp_path / "second.json"
    write_json(first_input, {"value": 1})
    write_json(second_input, {"value": 2})
    first = _publish(pointer, 1, inputs=[first_input, second_input])
    provenance = {
        name: sidecar_path(path).read_bytes() for name, path in first.artifacts.items()
    }
    _publish(pointer, 2, inputs=[first_input, second_input])

    reopened = _publish(pointer, 1, inputs=[second_input, first_input])

    assert reopened.generation_id == first.generation_id
    assert {
        name: sidecar_path(path).read_bytes()
        for name, path in reopened.artifacts.items()
    } == provenance


def test_identical_retry_recovers_an_exact_unselected_artifact_only(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    path = first.artifacts["rows"]
    expected_bytes = path.read_bytes()
    expected_mtime = path.stat().st_mtime_ns
    _publish(pointer, 2)
    sidecar_path(path).unlink()

    reopened = _publish(pointer, 1)

    assert reopened.generation_id == first.generation_id
    assert path.read_bytes() == expected_bytes
    assert path.stat().st_mtime_ns == expected_mtime
    assert sidecar_path(path).is_file()


def test_identical_retry_recovers_a_matching_unselected_sidecar_only(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    path = first.artifacts["rows"]
    provenance = sidecar_path(path).read_bytes()
    _publish(pointer, 2)
    path.unlink()

    reopened = _publish(pointer, 1)

    assert reopened.generation_id == first.generation_id
    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
    assert sidecar_path(path).read_bytes() == provenance


def test_unselected_artifact_only_with_different_content_is_fatal(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    path = first.artifacts["rows"]
    _publish(pointer, 2)
    sidecar_path(path).unlink()
    path.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unselected.*incomplete or invalid"):
        _publish(pointer, 1)

    assert path.read_text(encoding="utf-8") == '{"tampered": true}\n'


def test_unselected_sidecar_only_with_different_identity_is_fatal(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    path = first.artifacts["rows"]
    _publish(pointer, 2)
    path.unlink()
    provenance_path = sidecar_path(path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["rows"] = 999
    write_json(provenance_path, provenance)
    conflicting_bytes = provenance_path.read_bytes()

    with pytest.raises(RuntimeError, match="unselected.*incomplete or invalid"):
        _publish(pointer, 1)

    assert not path.exists()
    assert provenance_path.read_bytes() == conflicting_bytes


def test_selected_partial_generation_is_never_repaired(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    selected = _publish(pointer, 1)
    path = selected.artifacts["rows"]
    artifact_bytes = path.read_bytes()
    sidecar_path(path).unlink()

    with pytest.raises(RuntimeError, match="selected.*incomplete or invalid"):
        _publish(pointer, 1)

    assert path.read_bytes() == artifact_bytes
    assert not sidecar_path(path).exists()


def test_invalid_unselected_generation_is_never_deleted_or_repaired_in_place(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    unselected = _publish(pointer, 1)
    selected = _publish(pointer, 2)
    path = unselected.artifacts["rows"]
    path.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unselected.*incomplete or invalid"):
        _publish(pointer, 1)

    assert path.read_text(encoding="utf-8") == '{"tampered": true}\n'
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == selected.generation_id


def test_resolver_rejects_stale_provenance_even_when_pointer_digest_agrees(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    release = _publish(pointer, 1)
    provenance_path = sidecar_path(release.artifacts["rows"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["code_fingerprint"] = "0" * 64
    write_json(provenance_path, provenance)
    marker = json.loads(pointer.read_text(encoding="utf-8"))
    marker["artifacts"]["rows"]["provenance_sha256"] = file_sha256(provenance_path)
    write_json(pointer, marker)

    with pytest.raises(ValueError, match="provenance is not current"):
        resolve_artifact_release(
            pointer,
            kind=KIND,
            schema_version=1,
            filenames=FILENAMES,
        )


def test_resolver_preserves_semantically_compatible_source_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "release" / "current.json"
    release = _publish(pointer, 1)
    expected = release.generation_id
    monkeypatch.setattr(artifact_release, "code_fingerprint", lambda _sources: "0" * 64)

    reopened = resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    )

    assert reopened.generation_id == expected


def test_concurrent_publishers_each_return_the_generation_they_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "release" / "current.json"
    real_lock = artifact_release.serialized_output_install
    first_pointer_written = threading.Event()
    second_pointer_written = threading.Event()
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    @contextmanager
    def controlled_lock(target: Path):
        with real_lock(target):
            yield
        if threading.current_thread().name == "publisher-one":
            assert second_pointer_written.wait(timeout=10)

    def first_write(path: Path, payload: dict[str, object]) -> None:
        write_json(path, payload)
        first_pointer_written.set()

    def second_write(path: Path, payload: dict[str, object]) -> None:
        write_json(path, payload)
        second_pointer_written.set()

    def run(name: str, value: int, write_pointer) -> None:
        try:
            results[name] = _publish(pointer, value, write_pointer=write_pointer)
        except BaseException as error:
            errors[name] = error

    monkeypatch.setattr(artifact_release, "serialized_output_install", controlled_lock)
    first_thread = threading.Thread(
        target=run,
        args=("first", 1, first_write),
        name="publisher-one",
    )
    second_thread = threading.Thread(
        target=run,
        args=("second", 2, second_write),
        name="publisher-two",
    )
    first_thread.start()
    assert first_pointer_written.wait(timeout=10)
    second_thread.start()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == {}
    first = results["first"]
    second = results["second"]
    assert json.loads(first.artifacts["rows"].read_text(encoding="utf-8")) == {"value": 1}
    assert json.loads(second.artifacts["rows"].read_text(encoding="utf-8")) == {"value": 2}
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == second.generation_id


@pytest.mark.parametrize("target", ["artifact", "provenance"])
def test_release_reopening_rejects_tampered_generation(
    tmp_path: Path, target: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    release = _publish(pointer, 1)
    path = release.artifacts["rows"]
    if target == "artifact":
        path.write_text('{"value": 9}\n', encoding="utf-8")
    else:
        sidecar_path(path).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest disagrees"):
        resolve_artifact_release(
            pointer,
            kind=KIND,
            schema_version=1,
            filenames=FILENAMES,
        )


@pytest.mark.parametrize("cut", ["installed:payload", "installed:sidecar", "committed"])
def test_real_sigkill_is_recovered_before_generation_resume_and_pointer_selection(
    tmp_path: Path, cut: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    program = r'''
import json
import os
from pathlib import Path
import signal
import sys

from ddvc import journaled_publication as publication
from ddvc.artifact_release import publish_artifact_release
from ddvc.fetch.raw import write_json

pointer = Path(sys.argv[1])
cut = sys.argv[2]

def kill_at(label):
    if label == cut:
        os.kill(os.getpid(), signal.SIGKILL)

publication._publication_cut = kill_at
payloads = {
    "rows": {"value": 7, "blob": "r" * 2_000_000},
    "certificate": {"status": "pass", "value": 7, "blob": "c" * 1_500_000},
}
publish_artifact_release(
    pointer_path=pointer,
    kind="test_release",
    schema_version=1,
    filenames={"rows": "rows.json", "certificate": "certificate.json"},
    writers={
        name: lambda path, payload=payload: write_json(path, payload)
        for name, payload in payloads.items()
    },
    row_counts={"rows": 1, "certificate": 1},
    code_sources=["src/ddvc/artifact_release.py"],
    inputs=[],
    notes="test bundle",
    validate_staged=lambda paths: [json.loads(path.read_text()) for path in paths.values()],
)
'''
    killed = subprocess.run(
        [sys.executable, "-c", program, str(pointer), cut],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    assert killed.returncode == -signal.SIGKILL
    stale_outer_stages = list(pointer.parent.glob(".ddvc-artifact-stage-*"))
    assert len(stale_outer_stages) == 1
    resumed = _publish_large(pointer)
    rows = json.loads(resumed.artifacts["rows"].read_text(encoding="utf-8"))
    certificate = json.loads(
        resumed.artifacts["certificate"].read_text(encoding="utf-8")
    )
    assert (rows["value"], len(rows["blob"])) == (7, 2_000_000)
    assert (certificate["value"], len(certificate["blob"])) == (7, 1_500_000)
    assert not list(pointer.parent.rglob(".ddvc-publish-*"))
    assert not list(pointer.parent.glob(".ddvc-artifact-stage-*"))
    selected_bytes = {
        name: (path.read_bytes(), sidecar_path(path).read_bytes())
        for name, path in resumed.artifacts.items()
    }
    for path in resumed.artifacts.values():
        recovery = recover_journaled_publications(
            {"payload": path, "sidecar": sidecar_path(path)},
            journal_root=path.parent / ".ddvc-publication-journals",
        )
        assert recovery.recovered == 0
    assert {
        name: (path.read_bytes(), sidecar_path(path).read_bytes())
        for name, path in resumed.artifacts.items()
    } == selected_bytes
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == resumed.generation_id


def test_pointer_stage_recovery_does_not_delete_another_pointers_stage(
    tmp_path: Path,
) -> None:
    first_pointer = tmp_path / "release" / "first.json"
    other_pointer = tmp_path / "release" / "other.json"
    other_stage = artifact_release._pointer_stage_root(other_pointer)
    other_stage.mkdir(parents=True)
    write_json(
        other_stage / artifact_release._STAGE_OWNER,
        artifact_release._stage_owner_payload(other_pointer),
    )
    sentinel = other_stage / "payload" / "unrelated.bin"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"unrelated")

    _publish(first_pointer, 1)

    assert sentinel.read_bytes() == b"unrelated"
    assert other_stage.is_dir()


def test_pointer_stage_recovery_rejects_unowned_stage_without_deleting_it(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    stage = artifact_release._pointer_stage_root(pointer)
    stage.mkdir(parents=True)
    write_json(
        stage / artifact_release._STAGE_OWNER,
        artifact_release._stage_owner_payload(tmp_path / "different.json"),
    )
    sentinel = stage / "payload" / "unrelated.bin"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"unrelated")

    with pytest.raises(RuntimeError, match="another pointer"):
        _publish(pointer, 1)

    assert sentinel.read_bytes() == b"unrelated"


def test_pointer_stage_setup_failure_removes_only_the_stage_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "release" / "current.json"
    pointer.parent.mkdir(parents=True)

    def fail_owner_write(label: str) -> None:
        if label == "seed_partial_fsynced":
            raise OSError("simulated owner write failure")

    monkeypatch.setattr(artifact_release, "_artifact_stage_cut", fail_owner_write)
    with pytest.raises(OSError, match="owner write failure"):
        with artifact_release._pointer_stage(pointer):
            raise AssertionError("stage setup unexpectedly completed")

    assert not artifact_release._pointer_stage_root(pointer).exists()


def test_real_sigkill_before_stage_owner_is_recovered_by_ordinary_retry(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    program = r'''
import os
from pathlib import Path
import signal
import sys

import ddvc.artifact_release as release
from ddvc.artifact_release import publish_artifact_release
from ddvc.fetch.raw import write_json

pointer = Path(sys.argv[1])

def kill_at(label):
    if label == "created":
        os.kill(os.getpid(), signal.SIGKILL)

release._artifact_stage_cut = kill_at
publish_artifact_release(
    pointer_path=pointer,
    kind="test_release",
    schema_version=1,
    filenames={"rows": "rows.json", "certificate": "certificate.json"},
    writers={
        "rows": lambda path: write_json(path, {"value": 7}),
        "certificate": lambda path: write_json(path, {"status": "pass"}),
    },
    row_counts={"rows": 1, "certificate": 1},
    code_sources=["src/ddvc/artifact_release.py"],
    inputs=[],
    notes="pre-owner process-death test",
    validate_staged=lambda _paths: None,
)
'''
    killed = subprocess.run(
        [sys.executable, "-c", program, str(pointer)],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )

    assert killed.returncode == -signal.SIGKILL
    stage = artifact_release._pointer_stage_root(pointer)
    assert stage.is_dir()
    assert list(stage.iterdir()) == []

    resumed = _publish(pointer, 7)

    assert json.loads(resumed.artifacts["rows"].read_text()) == {"value": 7}
    assert not stage.exists()


@pytest.mark.parametrize(
    "cut",
    [
        "seed_empty_fsynced",
        "seed_partial_fsynced",
        "seed_complete_fsynced",
        "owner_installed",
    ],
)
def test_real_sigkill_across_private_owner_seed_transitions_is_recoverable(
    tmp_path: Path, cut: str
) -> None:
    pointer = tmp_path / "release" / "current.json"
    program = r'''
import os
from pathlib import Path
import signal
import sys

import ddvc.artifact_release as release
from ddvc.artifact_release import publish_artifact_release
from ddvc.fetch.raw import write_json

pointer = Path(sys.argv[1])
cut = sys.argv[2]

def kill_at(label):
    if label == cut:
        os.kill(os.getpid(), signal.SIGKILL)

release._artifact_stage_cut = kill_at
publish_artifact_release(
    pointer_path=pointer,
    kind="test_release",
    schema_version=1,
    filenames={"rows": "rows.json", "certificate": "certificate.json"},
    writers={
        "rows": lambda path: write_json(path, {"value": 7}),
        "certificate": lambda path: write_json(path, {"status": "pass"}),
    },
    row_counts={"rows": 1, "certificate": 1},
    code_sources=["src/ddvc/artifact_release.py"],
    inputs=[],
    notes="private owner seed process-death test",
    validate_staged=lambda _paths: None,
)
'''
    killed = subprocess.run(
        [sys.executable, "-c", program, str(pointer), cut],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )

    assert killed.returncode == -signal.SIGKILL
    stage = artifact_release._pointer_stage_root(pointer)
    seeds = list(pointer.parent.glob(f"{artifact_release._pointer_seed_prefix(pointer)}*.tmp"))
    if cut.startswith("seed_"):
        assert not stage.exists()
        assert len(seeds) == 1
        if cut == "seed_empty_fsynced":
            assert seeds[0].read_bytes() == b""
        elif cut == "seed_partial_fsynced":
            assert seeds[0].read_bytes() == b'{"policy":'
        else:
            assert seeds[0].read_bytes() == artifact_release._owner_seed_bytes(pointer)
    else:
        assert stage.joinpath(artifact_release._STAGE_OWNER).is_file()
        assert seeds == []

    resumed = _publish(pointer, 7)

    assert json.loads(resumed.artifacts["rows"].read_text()) == {"value": 7}
    assert not stage.exists()
    remaining = list(pointer.parent.glob(f"{artifact_release._pointer_seed_prefix(pointer)}*.tmp"))
    if cut in {"seed_empty_fsynced", "seed_partial_fsynced"}:
        assert remaining == seeds
    else:
        assert remaining == []


@pytest.mark.parametrize("extra_content", [False, True])
def test_foreign_owner_temporary_is_rejected_and_preserved(
    tmp_path: Path, extra_content: bool
) -> None:
    pointer = tmp_path / "release" / "current.json"
    stage = artifact_release._pointer_stage_root(pointer)
    stage.mkdir(parents=True)
    foreign = stage / ".owner.json.abc123_4.tmp"
    write_json(
        foreign,
        artifact_release._stage_owner_payload(tmp_path / "different.json"),
    )
    if extra_content:
        (stage / "foreign.bin").write_bytes(b"unrelated")
    before = _tree_snapshot(stage)

    with pytest.raises(RuntimeError, match="ownership is invalid"):
        _publish(pointer, 1)

    assert _tree_snapshot(stage) == before


def test_valid_owner_temporary_with_extra_content_is_rejected_and_preserved(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    stage = artifact_release._pointer_stage_root(pointer)
    stage.mkdir(parents=True)
    write_json(
        stage / ".owner.json.abc123_4.tmp",
        artifact_release._stage_owner_payload(pointer),
    )
    (stage / "foreign.bin").write_bytes(b"unrelated")
    before = _tree_snapshot(stage)

    with pytest.raises(RuntimeError, match="ownership is invalid"):
        _publish(pointer, 1)

    assert _tree_snapshot(stage) == before


def test_owner_temporary_symlink_is_rejected_and_preserved(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    stage = artifact_release._pointer_stage_root(pointer)
    stage.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    write_json(outside, artifact_release._stage_owner_payload(pointer))
    (stage / ".owner.json.abc123_4.tmp").symlink_to(outside)
    before = _tree_snapshot(tmp_path)

    with pytest.raises(RuntimeError, match="ownership is invalid"):
        _publish(pointer, 1)

    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("payload", [b"", b'{"policy":', b"foreign"])
def test_partial_or_foreign_owner_seed_does_not_block_retry_and_is_preserved(
    tmp_path: Path, payload: bytes
) -> None:
    pointer = tmp_path / "release" / "current.json"
    pointer.parent.mkdir(parents=True)
    seed = pointer.parent / f"{artifact_release._pointer_seed_prefix(pointer)}abc123_4.tmp"
    seed.write_bytes(payload)

    resumed = _publish(pointer, 1)

    assert json.loads(resumed.artifacts["rows"].read_text()) == {"value": 1}
    assert seed.read_bytes() == payload


def test_foreign_owner_seed_symlink_does_not_block_retry_and_is_preserved(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "release" / "current.json"
    pointer.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_bytes(artifact_release._owner_seed_bytes(pointer))
    seed = pointer.parent / f"{artifact_release._pointer_seed_prefix(pointer)}abc123_4.tmp"
    seed.symlink_to(outside)

    resumed = _publish(pointer, 1)

    assert json.loads(resumed.artifacts["rows"].read_text()) == {"value": 1}
    assert seed.is_symlink()
    assert outside.read_bytes() == artifact_release._owner_seed_bytes(pointer)
