from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

import pandas as pd
import pytest

import ddvc.counterfactual_publication as publication
from ddvc.counterfactual_publication import (
    PublicationRecoveryRequired,
    current_publication,
    publication_marker_path,
    publication_capability,
    register_publication_capability,
    require_current_publication,
    validate_publication_capability,
)
from ddvc.provenance import sidecar_path, verify
from ddvc.runtime import atomic_output, serialized_output_install, serialized_read_installs
from ddvc.tables import write_exhibit, write_panel


def _install_for_test(owner):
    return patch.object(sys.modules[__name__], owner.__name__, owner, create=True)


def test_real_counterfactual_cli_supports_direct_and_module_entrypoints() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "PYTHONPATH": f"{root / 'src'}:{root}",
    }
    commands = (
        [sys.executable, "scripts/build_counterfactual_dominance.py", "--help"],
        [sys.executable, "-m", "scripts.build_counterfactual_dominance", "--help"],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        assert "--stage" in completed.stdout


def test_capability_identity_cannot_be_copied_or_reexported() -> None:
    capability_id = f"test.identity.{uuid.uuid4().hex}"
    output = Path(tempfile.gettempdir()) / f"{capability_id}.out"
    register_publication_capability(capability_id, (output,))

    @publication_capability(
        capability_id,
        output_selector=lambda: (output,),
        source_selector=lambda: (),
    )
    def identity_owner():
        return "owner"

    with _install_for_test(identity_owner):
        assert validate_publication_capability(identity_owner) == capability_id

        @functools.wraps(identity_owner)
        def copied_owner():
            return "copied"

        with patch.object(
            sys.modules[__name__], identity_owner.__name__, copied_owner
        ):
            with pytest.raises(RuntimeError, match="registered publication owner"):
                validate_publication_capability(copied_owner)
            with pytest.raises(RuntimeError, match="installed callable"):
                validate_publication_capability(identity_owner)


@pytest.mark.parametrize("selected", [(), (Path("wrong"),)])
def test_capability_rejects_empty_or_wrong_output_selector(selected) -> None:
    capability_id = f"test.perimeter.{uuid.uuid4().hex}"
    expected = Path(tempfile.gettempdir()) / f"{capability_id}.out"
    register_publication_capability(capability_id, (expected,))

    @publication_capability(
        capability_id,
        output_selector=lambda: selected,
        source_selector=lambda: (),
    )
    def wrong_owner():
        raise AssertionError("wrong perimeter reached body")

    with _install_for_test(wrong_owner):
        with pytest.raises(RuntimeError, match="wrong output perimeter"):
            wrong_owner()


def test_unmocked_publication_installs_panel_exhibit_and_provenance() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.json"
        panel = root / "panel.parquet"
        exhibit = root / "exhibit.jsonl"
        source.write_text("source\n", encoding="utf-8")
        outputs = (panel, sidecar_path(panel), exhibit, sidecar_path(exhibit))
        capability_id = f"test.e2e.{uuid.uuid4().hex}"
        register_publication_capability(capability_id, outputs)

        @publication_capability(
            capability_id,
            output_selector=lambda: outputs,
            source_selector=lambda: (source,),
            assert_current=lambda: source.read_text(encoding="utf-8") == "source\n",
        )
        def e2e_owner():
            frame = pd.DataFrame({"value": [1, 2]})
            write_panel(frame, panel, inputs=[source])
            write_exhibit(frame, exhibit, inputs=[source])

        with _install_for_test(e2e_owner):
            e2e_owner()
        pd.testing.assert_frame_equal(pd.read_parquet(panel), pd.DataFrame({"value": [1, 2]}))
        assert exhibit.read_text(encoding="utf-8").count("\n") == 2
        assert sidecar_path(panel).is_file()
        assert sidecar_path(exhibit).is_file()
        assert verify(panel)["status"] == "ok"
        assert verify(exhibit)["status"] == "ok"


def test_failed_publication_restores_all_prior_outputs_twenty_times() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        created = root / "created"
        source.write_text("source", encoding="utf-8")
        for trial in range(20):
            target.write_text(f"prior-{trial}", encoding="utf-8")
            capability_id = f"test.rollback.{trial}.{uuid.uuid4().hex}"
            outputs = (target, created)
            register_publication_capability(capability_id, outputs)

            @publication_capability(
                capability_id,
                output_selector=lambda outputs=outputs: outputs,
                source_selector=lambda: (source,),
            )
            def failing_owner():
                with atomic_output(target) as temporary:
                    temporary.write_text("replacement", encoding="utf-8")
                with atomic_output(created) as temporary:
                    temporary.write_text("created", encoding="utf-8")
                raise RuntimeError("reject publication")

            with _install_for_test(failing_owner):
                with pytest.raises(RuntimeError, match="reject publication"):
                    failing_owner()
            assert target.read_text(encoding="utf-8") == f"prior-{trial}"
            assert not created.exists()


def test_unmocked_stamped_pair_rollback_restores_prior_pair() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        panel = root / "panel.parquet"
        sidecar = sidecar_path(panel)
        source.write_text("source", encoding="utf-8")
        panel.write_bytes(b"prior-panel")
        sidecar.write_bytes(b"prior-sidecar")
        capability_id = f"test.stamped-rollback.{uuid.uuid4().hex}"
        outputs = (panel, sidecar)
        register_publication_capability(capability_id, outputs)

        @publication_capability(
            capability_id,
            output_selector=lambda: outputs,
            source_selector=lambda: (source,),
        )
        def failing_owner():
            write_panel(pd.DataFrame({"value": [1]}), panel, inputs=[source])
            raise RuntimeError("reject stamped pair")

        with _install_for_test(failing_owner):
            with pytest.raises(RuntimeError, match="reject stamped pair"):
                failing_owner()
        assert panel.read_bytes() == b"prior-panel"
        assert sidecar.read_bytes() == b"prior-sidecar"


def test_rollback_backup_is_independent_of_in_place_target_mutation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        source.write_text("source", encoding="utf-8")
        target.write_text("prior", encoding="utf-8")
        capability_id = f"test.independent-backup.{uuid.uuid4().hex}"
        register_publication_capability(capability_id, (target,))

        @publication_capability(
            capability_id,
            output_selector=lambda: (target,),
            source_selector=lambda: (source,),
        )
        def mutating_owner():
            target.write_text("in-place mutation", encoding="utf-8")
            raise RuntimeError("reject in-place mutation")

        with _install_for_test(mutating_owner):
            with pytest.raises(RuntimeError, match="reject in-place mutation"):
                mutating_owner()
        assert target.read_text(encoding="utf-8") == "prior"


def test_entry_failure_leaves_no_transaction_directory() -> None:
    capability_id = f"test.entry.{uuid.uuid4().hex}"
    output = Path(tempfile.gettempdir()) / f"{capability_id}.out"
    register_publication_capability(capability_id, (output,))

    @publication_capability(
        capability_id,
        output_selector=lambda: (output,),
        source_selector=lambda: (),
    )
    def owner():
        raise AssertionError("body should not run")

    def fail_lock(**_perimeter):
        raise OSError("lock entry failed")

    with _install_for_test(owner), patch.object(
        publication, "serialized_artifact_transaction", fail_lock
    ):
        with pytest.raises(OSError, match="lock entry failed"):
            owner()
    assert not publication_marker_path(capability_id).exists()


def test_corrupt_on_disk_recovery_record_cannot_prevent_rollback() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        source.write_text("source", encoding="utf-8")
        target.write_text("prior", encoding="utf-8")
        capability_id = f"test.corrupt-record.{uuid.uuid4().hex}"
        marker = root / "marker.json"
        register_publication_capability(capability_id, (target,), marker_path=marker)
        transaction_root = marker.parent / f".{marker.name}.transactions"

        @publication_capability(
            capability_id,
            output_selector=lambda: (target,),
            source_selector=lambda: (source,),
        )
        def corrupting_owner():
            with atomic_output(target) as temporary:
                temporary.write_text("replacement", encoding="utf-8")
            active = set(transaction_root.iterdir())
            assert len(active) == 1
            (next(iter(active)) / "recovery.json").write_text(
                "{broken", encoding="utf-8"
            )
            raise RuntimeError("reject publication")

        with _install_for_test(corrupting_owner):
            with pytest.raises(RuntimeError, match="reject publication"):
                corrupting_owner()
        assert target.read_text(encoding="utf-8") == "prior"
        assert not transaction_root.exists() or not list(transaction_root.iterdir())


def test_restore_failure_retains_verified_backup_and_recovery_manifest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        source.write_text("source", encoding="utf-8")
        target.write_text("prior", encoding="utf-8")
        capability_id = f"test.recovery.{uuid.uuid4().hex}"
        marker = root / "marker.json"
        register_publication_capability(capability_id, (target,), marker_path=marker)

        @publication_capability(
            capability_id,
            output_selector=lambda: (target,),
            source_selector=lambda: (source,),
        )
        def failing_owner():
            with atomic_output(target) as temporary:
                temporary.write_text("replacement", encoding="utf-8")
            raise RuntimeError("reject publication")

        transaction_root = marker.parent / f".{marker.name}.transactions"
        original_replace = Path.replace

        def fail_restore(path: Path, destination: Path) -> Path:
            if path.name.endswith(".restore"):
                raise OSError("restore failed")
            return original_replace(path, destination)

        with _install_for_test(failing_owner), patch.object(
            Path, "replace", autospec=True, side_effect=fail_restore
        ):
            with pytest.raises(
                PublicationRecoveryRequired, match="recovery evidence retained"
            ):
                failing_owner()
        retained = set(transaction_root.iterdir())
        assert len(retained) == 1
        recovery_root = retained.pop()
        try:
            record = publication.json.loads(
                (recovery_root / "recovery.json").read_text(encoding="utf-8")
            )
            assert record["status"] == "manual_recovery_required"
            backups = list((recovery_root / "backups").iterdir())
            assert len(backups) == 1
            assert backups[0].read_text(encoding="utf-8") == "prior"
        finally:
            shutil.rmtree(recovery_root)


def test_symlink_source_lease_blocks_referent_writer_twenty_times() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.write_text('new'); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        real = work / "real"
        alias = work / "alias"
        real.write_text("prior", encoding="utf-8")
        alias.symlink_to(real.name)
        for trial in range(20):
            real.write_text(f"prior-{trial}", encoding="utf-8")
            with serialized_read_installs((alias,)):
                process = subprocess.Popen(
                    [sys.executable, "-c", script, str(real)],
                    cwd=root,
                    env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
                )
                time.sleep(0.02)
                assert process.poll() is None
                assert alias.read_text(encoding="utf-8") == f"prior-{trial}"
            process.wait(timeout=2)
            assert real.read_text(encoding="utf-8") == "new"


def test_symlink_source_lease_blocks_alias_retarget_twenty_times() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.write_text('new-alias'); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        real = work / "real"
        alias = work / "alias"
        real.write_text("prior", encoding="utf-8")
        for trial in range(20):
            alias.unlink(missing_ok=True)
            alias.symlink_to(real.name)
            with serialized_read_installs((alias,)):
                process = subprocess.Popen(
                    [sys.executable, "-c", script, str(alias)],
                    cwd=root,
                    env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
                )
                time.sleep(0.02)
                assert process.poll() is None
                assert alias.is_symlink()
                assert alias.read_text(encoding="utf-8") == "prior"
            process.wait(timeout=2)
            assert not alias.is_symlink()
            assert alias.read_text(encoding="utf-8") == "new-alias"


def test_active_capability_cannot_be_forged_by_naming_its_id() -> None:
    from scripts import build_counterfactual_dominance as builder

    frame = pd.DataFrame(
        {
            "tx": ["0xabc"],
            "receipt_allocation_scope": [
                "single_reconstructed_component_transaction"
            ],
        }
    )
    release = type(
        "Release",
        (),
        {
            "provenance_inputs": (Path("source"),),
            "content_identity_sha256": "a" * 64,
        },
    )()
    with pytest.raises(RuntimeError, match="requires publication capability"):
        builder._write_gross_release(
            frame,
            route_release=release,
            state_releases={"uniswap_v2": release},
        )
    assert not hasattr(publication, "counterfactual_publication")


def test_symlink_output_rollback_restores_referent_bytes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        referent = root / "referent"
        output = root / "output"
        marker = root / "marker.json"
        source.write_text("source", encoding="utf-8")
        referent.write_text("prior", encoding="utf-8")
        output.symlink_to(referent.name)
        capability_id = f"test.symlink-output.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (source,),
        )
        def owner():
            output.write_text("mutated-through-link", encoding="utf-8")
            raise RuntimeError("reject")

        with _install_for_test(owner), pytest.raises(RuntimeError, match="reject"):
            owner()
        assert output.is_symlink()
        assert referent.read_text(encoding="utf-8") == "prior"


def test_absent_output_under_symlink_ancestor_blocks_referent_writer() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.write_text('new'); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        real = work / "real"
        real.mkdir()
        alias = work / "alias"
        alias.symlink_to(real.name, target_is_directory=True)
        output = alias / "new"
        referent = real / "new"
        with serialized_output_install(output):
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(referent)],
                cwd=root,
                env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
            )
            time.sleep(0.05)
            assert process.poll() is None
            assert not referent.exists()
        process.wait(timeout=2)
        assert referent.read_text(encoding="utf-8") == "new"


def test_dangling_symlink_output_has_a_stable_lock_identity() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "output"
        output.symlink_to("missing")
        with serialized_output_install(output):
            assert output.is_symlink()


def test_publication_aborts_if_output_ancestor_retargets_before_marker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        old = root / "old"
        new = root / "new"
        old.mkdir()
        new.mkdir()
        (old / "output").write_text("prior", encoding="utf-8")
        alias = root / "alias"
        alias.symlink_to(old.name, target_is_directory=True)
        output = alias / "output"
        marker = root / "marker.json"
        capability_id = f"test.retarget-abort.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (),
        )
        def owner():
            alias.unlink()
            alias.symlink_to(new.name, target_is_directory=True)
            output.write_text("attacker-selected", encoding="utf-8")

        with _install_for_test(owner), pytest.raises(
            PublicationRecoveryRequired, match="recovery evidence retained"
        ) as error:
            owner()
        assert not marker.exists()
        assert (old / "output").read_text(encoding="utf-8") == "prior"
        assert (new / "output").read_text(encoding="utf-8") == "attacker-selected"
        recovery = Path(str(error.value).split(" at ", 1)[1])
        shutil.rmtree(recovery)


def test_retarget_during_marker_install_cannot_select_attacker_output() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        old = root / "old"
        new = root / "new"
        old.mkdir()
        new.mkdir()
        (old / "output").write_text("prior", encoding="utf-8")
        alias = root / "alias"
        alias.symlink_to(old.name, target_is_directory=True)
        output = alias / "output"
        marker = root / "marker.json"
        capability_id = f"test.marker-retarget.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (),
        )
        def owner():
            output.write_text("published", encoding="utf-8")

        real_atomic_json = publication._atomic_json

        def retarget_before_marker(path: Path, payload: object) -> None:
            if path == marker:
                alias.unlink()
                alias.symlink_to(new.name, target_is_directory=True)
                output.write_text("attacker-selected", encoding="utf-8")
            real_atomic_json(path, payload)

        with (
            _install_for_test(owner),
            patch.object(
                publication, "_atomic_json", side_effect=retarget_before_marker
            ),
            pytest.raises(PublicationRecoveryRequired) as error,
        ):
            owner()
        assert not marker.exists()
        with pytest.raises(RuntimeError, match="not current"):
            require_current_publication(capability_id, marker_path=marker)
        recovery = Path(str(error.value).split(" at ", 1)[1])
        shutil.rmtree(recovery)


def test_empty_preparing_journal_is_ignored_before_next_publication() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "output"
        marker = root / "marker.json"
        capability_id = f"test.empty-journal.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )
        empty = marker.parent / f".{marker.name}.transactions" / uuid.uuid4().hex
        empty.mkdir(parents=True)

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (),
        )
        def owner():
            output.write_text("published", encoding="utf-8")

        with _install_for_test(owner):
            owner()
        assert output.read_text(encoding="utf-8") == "published"
        require_current_publication(capability_id, marker_path=marker)
        assert not empty.exists()


def test_publication_fsyncs_outputs_and_marker_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "output"
        marker = root / "marker.json"
        capability_id = f"test.fsync.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (),
        )
        def owner():
            output.write_text("published", encoding="utf-8")

        real_fsync = os.fsync
        with _install_for_test(owner), patch.object(
            publication.os, "fsync", wraps=real_fsync
        ) as fsync:
            owner()
        assert fsync.call_count >= 6
        require_current_publication(capability_id, marker_path=marker)


def test_retained_recovery_backups_remain_independent_after_partial_restore() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        first = root / "first"
        second = root / "second"
        marker = root / "marker.json"
        source.write_text("source", encoding="utf-8")
        first.write_text("prior-first", encoding="utf-8")
        second.write_text("prior-second", encoding="utf-8")
        capability_id = f"test.independent-retained.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (first, second), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (first, second),
            source_selector=lambda: (source,),
        )
        def owner():
            first.write_text("new-first", encoding="utf-8")
            second.write_text("new-second", encoding="utf-8")
            raise RuntimeError("reject")

        original_replace = Path.replace

        def fail_one_restore(path: Path, destination: Path) -> Path:
            if path.name.endswith(".restore") and Path(destination) == first:
                raise OSError("restore failed")
            return original_replace(path, destination)

        with _install_for_test(owner), patch.object(
            Path, "replace", autospec=True, side_effect=fail_one_restore
        ), pytest.raises(PublicationRecoveryRequired) as error:
            owner()
        recovery = Path(str(error.value).split(" at ", 1)[1])
        try:
            record = json.loads(
                (recovery / "recovery.json").read_text(encoding="utf-8")
            )
            second_record = next(
                row
                for row in record["backups"]
                if Path(row["target"]) == second
            )
            backup = Path(second_record["backup"])
            assert second.stat().st_ino != backup.stat().st_ino
            second.write_text("later-mutation", encoding="utf-8")
            assert backup.read_text(encoding="utf-8") == "prior-second"
        finally:
            shutil.rmtree(recovery)


def test_parent_read_lease_blocks_child_writer() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.write_text('new'); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        parent = Path(directory) / "parent"
        parent.mkdir()
        child = parent / "child"
        child.write_text("prior", encoding="utf-8")
        with serialized_read_installs((parent,)):
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(child)],
                cwd=root,
                env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
            )
            time.sleep(0.05)
            assert process.poll() is None
            assert child.read_text(encoding="utf-8") == "prior"
        process.wait(timeout=2)
        assert child.read_text(encoding="utf-8") == "new"


def test_nested_parent_read_lease_expands_beyond_child_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.write_text('new'); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        parent = Path(directory) / "parent"
        parent.mkdir()
        child = parent / "child"
        sibling = parent / "sibling"
        child.write_text("child", encoding="utf-8")
        sibling.write_text("prior", encoding="utf-8")
        with serialized_read_installs((child,)):
            with serialized_read_installs((parent,)):
                process = subprocess.Popen(
                    [sys.executable, "-c", script, str(sibling)],
                    cwd=root,
                    env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
                )
                time.sleep(0.05)
                assert process.poll() is None
                assert sibling.read_text(encoding="utf-8") == "prior"
            process.wait(timeout=2)
            assert sibling.read_text(encoding="utf-8") == "new"


def test_symlinked_ancestor_cannot_retarget_during_source_lease() -> None:
    root = Path(__file__).resolve().parents[1]
    script = "from pathlib import Path; from ddvc.runtime import atomic_output; import sys; target=Path(sys.argv[1]); context=atomic_output(target); temporary=context.__enter__(); temporary.unlink(); temporary.symlink_to(sys.argv[2], target_is_directory=True); context.__exit__(None,None,None)"
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        old = work / "old"
        new = work / "new"
        old.mkdir()
        new.mkdir()
        (old / "file").write_text("old", encoding="utf-8")
        (new / "file").write_text("new", encoding="utf-8")
        alias = work / "alias"
        alias.symlink_to(old.name, target_is_directory=True)
        source = alias / "file"
        with serialized_read_installs((source,)):
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(alias), new.name],
                cwd=root,
                env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
            )
            time.sleep(0.05)
            assert process.poll() is None
            assert source.read_text(encoding="utf-8") == "old"
        process.wait(timeout=2)
        assert source.read_text(encoding="utf-8") == "new"


def test_publication_marker_binds_symlinked_ancestor_identity() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        old = root / "old"
        new = root / "new"
        old.mkdir()
        new.mkdir()
        (old / "output").write_text("published", encoding="utf-8")
        (new / "output").write_text("published", encoding="utf-8")
        alias = root / "alias"
        alias.symlink_to(old.name, target_is_directory=True)
        output = alias / "output"
        marker = root / "marker.json"
        capability_id = f"test.ancestor-marker.{uuid.uuid4().hex}"
        register_publication_capability(
            capability_id, (output,), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (output,),
            source_selector=lambda: (),
        )
        def owner():
            output.write_text("published", encoding="utf-8")

        with _install_for_test(owner):
            owner()
        require_current_publication(capability_id, marker_path=marker)
        alias.unlink()
        alias.symlink_to(new.name, target_is_directory=True)
        with pytest.raises(RuntimeError, match="disagree with marker"):
            require_current_publication(capability_id, marker_path=marker)


def test_process_exit_is_recovered_before_next_publication() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        source = work / "source"
        first = work / "first"
        second = work / "second"
        marker = work / "marker.json"
        source.write_text("source", encoding="utf-8")
        first.write_text("prior-first", encoding="utf-8")
        second.write_text("prior-second", encoding="utf-8")
        capability_id = f"test.crash.{uuid.uuid4().hex}"
        crash_program = """
from pathlib import Path
from ddvc.counterfactual_publication import register_publication_capability, publication_capability
import os
import sys
capability_id = sys.argv[1]
source, first, second, marker = map(Path, sys.argv[2:])
register_publication_capability(capability_id, (first, second), marker_path=marker)
@publication_capability(capability_id, output_selector=lambda: (first, second), source_selector=lambda: (source,))
def owner():
    first.write_text("new-first", encoding="utf-8")
    os._exit(17)
owner()
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                crash_program,
                capability_id,
                str(source),
                str(first),
                str(second),
                str(marker),
            ],
            cwd=root,
            env={**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"},
        )
        assert completed.returncode == 17
        assert first.read_text(encoding="utf-8") == "new-first"
        register_publication_capability(
            capability_id, (first, second), marker_path=marker
        )

        @publication_capability(
            capability_id,
            output_selector=lambda: (first, second),
            source_selector=lambda: (source,),
        )
        def owner():
            first.write_text("committed-first", encoding="utf-8")
            second.write_text("committed-second", encoding="utf-8")

        with _install_for_test(owner):
            owner()
        assert first.read_text(encoding="utf-8") == "committed-first"
        assert second.read_text(encoding="utf-8") == "committed-second"
        with current_publication(
            capability_id,
            marker_path=marker,
            expected_outputs=(first, second),
        ):
            pass
