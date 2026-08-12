from __future__ import annotations

import functools
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
    publication_capability,
    register_publication_capability,
    validate_publication_capability,
)
from ddvc.provenance import sidecar_path, verify
from ddvc.runtime import atomic_output, serialized_read_installs
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
    transaction_root = Path(tempfile.gettempdir())
    before = set(transaction_root.glob("ddvc-counterfactual-publication-*"))

    def fail_lock(**_perimeter):
        raise OSError("lock entry failed")

    with patch.object(publication, "serialized_artifact_transaction", fail_lock):
        with pytest.raises(OSError, match="lock entry failed"):
            with publication.counterfactual_publication(
                "test.entry", sources=(Path("source"),), outputs=(Path("output"),)
            ):
                raise AssertionError("body should not run")
    assert set(transaction_root.glob("ddvc-counterfactual-publication-*")) == before


def test_corrupt_on_disk_recovery_record_cannot_prevent_rollback() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        source.write_text("source", encoding="utf-8")
        target.write_text("prior", encoding="utf-8")
        capability_id = f"test.corrupt-record.{uuid.uuid4().hex}"
        register_publication_capability(capability_id, (target,))
        transaction_root = Path(tempfile.gettempdir())
        before = set(transaction_root.glob("ddvc-counterfactual-publication-*"))

        @publication_capability(
            capability_id,
            output_selector=lambda: (target,),
            source_selector=lambda: (source,),
        )
        def corrupting_owner():
            with atomic_output(target) as temporary:
                temporary.write_text("replacement", encoding="utf-8")
            active = set(
                transaction_root.glob("ddvc-counterfactual-publication-*")
            ) - before
            assert len(active) == 1
            (next(iter(active)) / "recovery.json").write_text(
                "{broken", encoding="utf-8"
            )
            raise RuntimeError("reject publication")

        with _install_for_test(corrupting_owner):
            with pytest.raises(RuntimeError, match="reject publication"):
                corrupting_owner()
        assert target.read_text(encoding="utf-8") == "prior"
        assert set(transaction_root.glob("ddvc-counterfactual-publication-*")) == before


def test_restore_failure_retains_verified_backup_and_recovery_manifest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        target = root / "target"
        source.write_text("source", encoding="utf-8")
        target.write_text("prior", encoding="utf-8")
        capability_id = f"test.recovery.{uuid.uuid4().hex}"
        register_publication_capability(capability_id, (target,))

        @publication_capability(
            capability_id,
            output_selector=lambda: (target,),
            source_selector=lambda: (source,),
        )
        def failing_owner():
            with atomic_output(target) as temporary:
                temporary.write_text("replacement", encoding="utf-8")
            raise RuntimeError("reject publication")

        transaction_root = Path(tempfile.gettempdir())
        before = set(transaction_root.glob("ddvc-counterfactual-publication-*"))
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
        retained = set(transaction_root.glob("ddvc-counterfactual-publication-*")) - before
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
