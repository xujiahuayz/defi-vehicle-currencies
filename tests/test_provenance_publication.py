from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
from unittest.mock import patch

import pandas as pd
import pytest

import ddvc.journaled_publication as publication
import ddvc.provenance as provenance
from ddvc.provenance import (
    current_artifacts,
    describe_artifact_payload,
    recover_stamped_artifact_install,
    sidecar_path,
    stamp,
    verify,
)
from ddvc.runtime import file_sha256
from ddvc.tables import write_panel


def test_journal_root_and_recovery_are_mapping_order_independent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        journal_root = root / "journals"
        targets = {"first": root / "first.bin", "second": root / "second.bin"}
        for path, value in zip(targets.values(), (b"old-a", b"old-b"), strict=True):
            path.write_bytes(value)
        staged_root = root / "staged"
        staged_root.mkdir()
        staged = {"first": staged_root / "first.bin", "second": staged_root / "second.bin"}
        for path, value in zip(staged.values(), (b"new-a", b"new-b"), strict=True):
            path.write_bytes(value)

        def kill_after_first(label: str) -> None:
            if label == "installed:first":
                raise RuntimeError("interrupt")

        with patch.object(publication, "_publication_cut", side_effect=kill_after_first), patch.object(
            publication, "_restore", side_effect=RuntimeError("rollback failed")
        ), pytest.raises(RuntimeError, match="rollback failed"):
            publication.publish_journaled_bundle(
                targets=targets,
                staged=staged,
                journal_root=journal_root,
            )
        reversed_targets = dict(reversed(tuple(targets.items())))
        recovery = publication.recover_journaled_publications(
            reversed_targets, journal_root=journal_root
        )
        assert recovery.recovered == 1
        assert targets["first"].read_bytes() == b"old-a"
        assert targets["second"].read_bytes() == b"old-b"


def test_directory_identity_binds_empty_directory_topology() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tree = root / "tree"
        (tree / "empty" / "nested").mkdir(parents=True)
        (tree / "nonempty").mkdir()
        (tree / "nonempty" / "value.txt").write_text("value", encoding="utf-8")
        before = publication._identity(tree)
        (tree / "empty" / "nested").rmdir()
        after = publication._identity(tree)
        assert before != after
        assert {entry["path"] for entry in before["entries"] if entry["kind"] == "directory"} == {
            "empty",
            "empty/nested",
            "nonempty",
        }


def test_staged_directory_tree_is_fsynced_before_prepared_journal() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "target"
        staged = root / "staged"
        (staged / "empty").mkdir(parents=True)
        (staged / "nested").mkdir()
        (staged / "nested" / "value.txt").write_text("value", encoding="utf-8")
        observed: list[tuple[str, bool]] = []
        real_sync_tree = publication._fsync_tree
        real_write_journal = publication._write_journal

        def sync_tree(path: Path) -> None:
            real_sync_tree(path)
            observed.append(("tree", True))

        def write_journal(path: Path, payload: dict[str, object]) -> None:
            observed.append(("journal", (path / "new" / "tree" / "empty").is_dir()))
            real_write_journal(path, payload)

        with patch.object(publication, "_fsync_tree", side_effect=sync_tree), patch.object(
            publication, "_write_journal", side_effect=write_journal
        ):
            publication.publish_journaled_bundle(
                targets={"tree": target},
                staged={"tree": staged},
                journal_root=root / "journals",
            )
        assert observed[0] == ("tree", True)
        assert observed[1] == ("journal", True)


def test_jsonl_identity_counts_valid_records_with_optional_final_newline() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for suffix in ("", "\n"):
            path = root / f"records-{len(suffix)}.jsonl"
            path.write_text('{"row":1}\n{"row":2}' + suffix, encoding="utf-8")
            identity = describe_artifact_payload(path)
            assert identity["rows"] == 2
            assert identity["format"] == "jsonl"


@pytest.mark.parametrize("content", ['{"row":1}\n\n{"row":2}\n', '{"row":1}\nnot-json\n'])
def test_jsonl_identity_rejects_blank_or_invalid_records(content: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "records.jsonl"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="blank record|invalid JSON"):
            describe_artifact_payload(path)


def test_truly_metadata_free_legacy_sidecar_is_stale() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "artifact.bin"
        path.write_bytes(b"payload")
        stamp(path, code_sources=["tests/test_provenance_publication.py"])
        manifest = sidecar_path(path)
        record = json.loads(manifest.read_text(encoding="utf-8"))
        record.pop("payload_identity", None)
        record["artefact_bytes"] = None
        record["artefact_mtime_ns"] = None
        record["artefact_sha256"] = None
        manifest.write_text(json.dumps(record), encoding="utf-8")
        verdict = verify(path)
        assert verdict["status"] == "stale"
        assert verdict["content_current"] is False


@pytest.mark.parametrize(
    "replacement",
    [
        pd.DataFrame({"right": [2], "left": [1]}),
        pd.DataFrame({"left": [1.0], "right": [2]}),
    ],
)
def test_parquet_column_order_and_schema_mutations_are_stale(
    replacement: pd.DataFrame,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "panel.parquet"
        pd.DataFrame({"left": [1], "right": [2]}).to_parquet(path, index=False)
        stamp(path, code_sources=["tests/test_provenance_publication.py"], rows=1)
        replacement.to_parquet(path, index=False)
        verdict = verify(path)
        assert verdict["status"] == "stale"
        assert verdict["content_current"] is False


def test_digest_cache_uses_ctime_when_size_inode_and_mtime_are_reused() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "payload.bin"
        path.write_bytes(b"first")
        prior = path.stat()
        first = file_sha256(path)
        path.write_bytes(b"other")
        os.utime(path, ns=(prior.st_atime_ns, prior.st_mtime_ns))
        assert path.stat().st_ino == prior.st_ino
        assert path.stat().st_size == prior.st_size
        assert path.stat().st_mtime_ns == prior.st_mtime_ns
        assert file_sha256(path) != first


def test_rollback_failure_preserves_complete_recovery_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "panel.parquet"
        write_panel(
            pd.DataFrame({"value": [1]}),
            path,
            code_sources=["tests/test_provenance_publication.py"],
        )
        prior_payload = path.read_bytes()
        prior_sidecar = sidecar_path(path).read_bytes()

        def fail_after_pair(label: str) -> None:
            if label == "installed:sidecar":
                raise OSError("injected publication failure")

        with patch.object(publication, "_publication_cut", new=fail_after_pair), patch.object(
            publication, "_restore", side_effect=OSError("injected rollback failure")
        ), pytest.raises(OSError, match="injected rollback failure"):
            write_panel(
                pd.DataFrame({"value": [2]}),
                path,
                code_sources=["tests/test_provenance_publication.py"],
            )

        journal_root = root / ".ddvc-publication-journals"
        stages = list(journal_root.glob(".ddvc-publish-*"))
        assert len(stages) == 1
        journal = json.loads((stages[0] / publication.JOURNAL).read_text())
        assert journal["state"] == publication.PREPARED
        assert (stages[0] / "backup" / "payload").is_file()
        assert (stages[0] / "backup" / "sidecar").is_file()

        assert recover_stamped_artifact_install(path) == 1
        assert path.read_bytes() == prior_payload
        assert sidecar_path(path).read_bytes() == prior_sidecar
        assert list(journal_root.glob(".ddvc-publish-*")) == []


@pytest.mark.parametrize("cut", ["installed:payload", "installed:sidecar"])
def test_real_sigkill_after_each_pair_rename_recovers_prior_snapshot(cut: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "panel.parquet"
        write_panel(
            pd.DataFrame({"value": [1]}),
            path,
            code_sources=["tests/test_provenance_publication.py"],
        )
        prior_payload = path.read_bytes()
        prior_sidecar = sidecar_path(path).read_bytes()
        script = """
import os
from pathlib import Path
import signal
import sys
import pandas as pd
import ddvc.journaled_publication as publication
from ddvc.tables import write_panel
path = Path(sys.argv[1])
cut = sys.argv[2]
def kill_at(label):
    if label == cut:
        os.kill(os.getpid(), signal.SIGKILL)
publication._publication_cut = kill_at
write_panel(pd.DataFrame({"value": [2]}), path, code_sources=["tests/test_provenance_publication.py"])
"""
        result = subprocess.run([sys.executable, "-c", script, str(path), cut])
        assert result.returncode == -signal.SIGKILL
        assert recover_stamped_artifact_install(path) == 1
        assert path.read_bytes() == prior_payload
        assert sidecar_path(path).read_bytes() == prior_sidecar
        assert verify(path)["status"] == "ok"
        assert list((root / ".ddvc-publication-journals").glob(".ddvc-publish-*")) == []


def test_real_sigkill_after_committed_journal_finishes_new_release_cleanup() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "panel.parquet"
        write_panel(
            pd.DataFrame({"value": [1]}),
            path,
            code_sources=["tests/test_provenance_publication.py"],
        )
        script = """
import os
from pathlib import Path
import signal
import sys
import pandas as pd
import ddvc.journaled_publication as publication
from ddvc.tables import write_panel
path = Path(sys.argv[1])
def kill_at(label):
    if label == "committed":
        os.kill(os.getpid(), signal.SIGKILL)
publication._publication_cut = kill_at
write_panel(pd.DataFrame({"value": [2]}), path, code_sources=["tests/test_provenance_publication.py"])
"""
        result = subprocess.run([sys.executable, "-c", script, str(path)])
        assert result.returncode == -signal.SIGKILL
        assert recover_stamped_artifact_install(path) == 1
        assert pd.read_parquet(path)["value"].tolist() == [2]
        assert verify(path)["status"] == "ok"
        assert list((root / ".ddvc-publication-journals").glob(".ddvc-publish-*")) == []


def test_current_artifacts_holds_one_lease_through_multi_artifact_read() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = root / "first.parquet"
        second = root / "second.parquet"
        for path, value in ((first, 1), (second, 2)):
            write_panel(
                pd.DataFrame({"value": [value]}),
                path,
                code_sources=["tests/test_provenance_publication.py"],
            )
        attempted = Event()
        completed = Event()
        errors: list[BaseException] = []
        real_installs = provenance.serialized_output_installs

        @contextmanager
        def observed_installs(targets):
            attempted.set()
            with real_installs(targets):
                yield

        def replace_first() -> None:
            try:
                write_panel(
                    pd.DataFrame({"value": [3]}),
                    first,
                    code_sources=["tests/test_provenance_publication.py"],
                )
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()

        with current_artifacts([first, second], consumer="snapshot test"):
            with patch("ddvc.provenance.serialized_output_installs", new=observed_installs):
                writer = Thread(target=replace_first)
                writer.start()
                assert attempted.wait(timeout=5)
                assert not completed.wait(timeout=0.1)
                assert pd.read_parquet(first)["value"].tolist() == [1]
                assert pd.read_parquet(second)["value"].tolist() == [2]
        writer.join(timeout=5)
        assert not writer.is_alive()
        assert errors == []
        assert completed.is_set()
        assert pd.read_parquet(first)["value"].tolist() == [3]
