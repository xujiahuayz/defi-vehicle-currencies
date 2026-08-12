from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import threading

import pytest

import ddvc.artifact_release as artifact_release
from ddvc.artifact_release import (
    current_artifact_release,
    file_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.fetch.raw import write_json
from ddvc.provenance import sidecar_path


KIND = "test_release"
FILENAMES = {"rows": "rows.json", "certificate": "certificate.json"}


def _publish(
    pointer: Path,
    value: int,
    *,
    inputs=None,
    row_count: int = 1,
    write_pointer=write_json,
    validate_staged=None,
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
        write_pointer=write_pointer,
    )


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


def test_bundle_validation_finishes_before_pointer_publication(tmp_path: Path) -> None:
    pointer = tmp_path / "release" / "current.json"
    first = _publish(pointer, 1)
    validation_calls = 0

    def reject_installed_bundle(paths: dict[str, Path]) -> None:
        nonlocal validation_calls
        validation_calls += 1
        [json.loads(path.read_text()) for path in paths.values()]
        if validation_calls == 2:
            raise ValueError("simulated installed-bundle rejection")

    with pytest.raises(ValueError, match="installed-bundle rejection"):
        _publish(pointer, 2, validate_staged=reject_installed_bundle)

    assert validation_calls == 2
    assert resolve_artifact_release(
        pointer,
        kind=KIND,
        schema_version=1,
        filenames=FILENAMES,
    ).generation_id == first.generation_id


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
