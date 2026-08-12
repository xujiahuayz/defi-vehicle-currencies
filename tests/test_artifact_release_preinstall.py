from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ddvc.artifact_release as artifact_release
from ddvc.artifact_release import publish_artifact_release, resolve_artifact_release
from ddvc.data_release import release_preinstall_validator
from ddvc.provenance import sidecar_path


class PreparedValidator:
    def __init__(self) -> None:
        self.path_calls = 0
        self.stamp_calls = 0

    def __call__(self, _path: Path) -> None:
        self.path_calls += 1

    def validate_prepared_stamp(self, prepared: bytes) -> bytes:
        self.stamp_calls += 1
        payload = json.loads(prepared)
        payload["prepared_validator"] = "passed"
        return (json.dumps(payload, sort_keys=True) + "\n").encode()


def test_preinstall_stamp_validator_runs_again_on_artifact_only_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "release" / "current.json"
    source = tmp_path / "source.txt"
    source.write_text("source\n")
    validator = PreparedValidator()
    original = artifact_release.install_stamped_artifact
    cut = True

    def interrupt_after_payload(staged, target, prepared):
        nonlocal cut
        original(staged, target, prepared)
        if cut:
            cut = False
            sidecar_path(target).unlink()
            raise KeyboardInterrupt

    arguments = dict(
        pointer_path=pointer,
        kind="prepared-validator-test",
        schema_version=1,
        filenames={"panel": "panel.bin"},
        writers={"panel": lambda path: path.write_bytes(b"payload")},
        row_counts={"panel": 1},
        code_sources=["tests/test_artifact_release_preinstall.py"],
        inputs=[source],
        notes="artifact-only resume contract",
        validate_staged=lambda paths: None,
        preinstall_validator=validator,
    )
    monkeypatch.setattr(
        artifact_release, "install_stamped_artifact", interrupt_after_payload
    )
    with pytest.raises(KeyboardInterrupt):
        publish_artifact_release(**arguments)
    assert not pointer.exists()
    monkeypatch.setattr(artifact_release, "install_stamped_artifact", original)
    release = publish_artifact_release(**arguments)
    reopened = resolve_artifact_release(
        pointer,
        kind="prepared-validator-test",
        schema_version=1,
        filenames={"panel": "panel.bin"},
    )
    assert reopened.generation_id == release.generation_id
    provenance = json.loads(sidecar_path(release.artifacts["panel"]).read_text())
    assert provenance["prepared_validator"] == "passed"
    assert validator.path_calls >= 3
    assert validator.stamp_calls >= 3


def test_release_stamp_requires_anchor_input_but_embeds_full_bindings(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.parquet"
    ledger.write_bytes(b"ledger")
    panel = tmp_path / "panel.parquet"
    panel.write_bytes(b"panel")
    marker = tmp_path / "panel.quality.json"
    marker.write_bytes(b"marker")
    release = SimpleNamespace(
        ledger_path=ledger,
        ledger_sha256=artifact_release.file_sha256(ledger),
        quarantine_path=None,
        quarantine_sha256=None,
        partitions=(
            SimpleNamespace(
                path=panel,
                expected_sha256=artifact_release.file_sha256(panel),
                marker_path=marker,
                marker_sha256=artifact_release.file_sha256(marker),
            ),
        ),
        assert_current=lambda: None,
    )
    validator = release_preinstall_validator(release)
    with pytest.raises(RuntimeError, match="release anchors"):
        validator.validate_prepared_stamp(json.dumps({"inputs": []}).encode())
    prepared = validator.validate_prepared_stamp(
        json.dumps({"inputs": [{"path": str(ledger)}]}).encode()
    )
    bindings = json.loads(prepared)["released_input_bindings"]
    assert {record["path"] for record in bindings} == {
        str(ledger.resolve()),
        str(panel.resolve()),
        str(marker.resolve()),
    }
