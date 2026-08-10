from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread, current_thread
from unittest.mock import patch

import pandas as pd

import ddvc.provenance as provenance
from ddvc.provenance import CONTENT_HASH_MAX_BYTES, sidecar_path, stamp, verify
from ddvc.runtime import staged_output

from ddvc.tables import write_exhibit, write_panel, write_panel_batches


class ExhibitWriterTests(unittest.TestCase):
    def test_nonfinite_values_are_strict_json_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "exhibit.jsonl"
            write_exhibit(
                pd.DataFrame({"nan": [float("nan")], "inf": [float("inf")]}),
                out,
                code_sources=["tests/test_tables.py"],
            )
            text = out.read_text()
            self.assertNotIn("NaN", text)
            self.assertNotIn("Infinity", text)
            self.assertEqual(json.loads(text), {"inf": None, "nan": None})

    def test_gzip_output_is_byte_deterministic_across_target_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.jsonl.gz"
            second = root / "second.jsonl.gz"
            frame = pd.DataFrame({"value": [1, 2]})
            for output in (first, second):
                write_exhibit(
                    frame,
                    output,
                    code_sources=["tests/test_tables.py"],
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with gzip.open(first, "rt") as handle:
                self.assertEqual(len(handle.readlines()), 2)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_panel_writer_leaves_no_fixed_or_unique_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            write_panel(
                pd.DataFrame({"value": [1, 2]}),
                output,
                code_sources=["tests/test_tables.py"],
            )
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [1, 2])
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_batch_panel_does_not_replace_prior_release_when_stamping_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_bytes(b"prior-sidecar\n")
            prior_sidecar = sidecar.read_bytes()
            with patch("ddvc.tables.prepare_stamp", side_effect=RuntimeError("stamp failed")), self.assertRaisesRegex(RuntimeError, "stamp failed"):
                write_panel_batches([pd.DataFrame({"value": [2]})], output, code_sources=["tests/test_tables.py"])
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), prior_sidecar)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_batch_panel_validator_failure_preserves_prior_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.write_bytes(b"prior-sidecar\n")
            with self.assertRaisesRegex(ValueError, "validator rejected"):
                write_panel_batches([pd.DataFrame({"value": [2]})], output, code_sources=["tests/test_tables.py"], preinstall_validator=lambda _path: (_ for _ in ()).throw(ValueError("validator rejected")))
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_single_panel_validator_failure_preserves_prior_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.write_bytes(b"prior-sidecar\n")
            with self.assertRaisesRegex(ValueError, "validator rejected"):
                write_panel(pd.DataFrame({"value": [2]}), output, code_sources=["tests/test_tables.py"], preinstall_validator=lambda _path: (_ for _ in ()).throw(ValueError("validator rejected")))
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_exhibit_validator_failure_preserves_prior_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "exhibit.jsonl"
            output.write_bytes(b'{"value":1}\n')
            sidecar = sidecar_path(output)
            sidecar.write_bytes(b"prior-sidecar\n")
            with self.assertRaisesRegex(ValueError, "validator rejected"):
                write_exhibit(pd.DataFrame({"value": [2]}), output, code_sources=["tests/test_tables.py"], preinstall_validator=lambda _path: (_ for _ in ()).throw(ValueError("validator rejected")))
            self.assertEqual(output.read_bytes(), b'{"value":1}\n')
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_batch_generator_and_schema_failures_preserve_prior_pair(self) -> None:
        def broken_generator():
            yield pd.DataFrame({"value": [2]})
            raise RuntimeError("generator failed")

        cases = (
            (broken_generator(), RuntimeError, "generator failed"),
            ([pd.DataFrame({"value": [2]}), pd.DataFrame({"value": ["different schema"]})], ValueError, "do not share one schema"),
        )
        for frames, error_type, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "panel.parquet"
                pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
                prior = output.read_bytes()
                sidecar = sidecar_path(output)
                sidecar.write_bytes(b"prior-sidecar\n")
                with self.assertRaisesRegex(error_type, message):
                    write_panel_batches(frames, output, code_sources=["tests/test_tables.py"])
                self.assertEqual(output.read_bytes(), prior)
                self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")
                self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_batch_panel_installs_matching_content_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "panel.parquet"
            returned, rows = write_panel_batches([pd.DataFrame({"value": [2, 3]})], output, code_sources=["tests/test_tables.py"])
            sidecar = sidecar_path(output)
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(returned, output)
            self.assertEqual(rows, 2)
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [2, 3])
            self.assertEqual(record["artefact_bytes"], output.stat().st_size)
            self.assertEqual(record["artefact_mtime_ns"], output.stat().st_mtime_ns)
            self.assertEqual(record["artefact_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_batch_panel_restores_prior_pair_at_every_install_failure_boundary(self) -> None:
        failure_modes = ((boundary, after_move) for boundary in range(1, 5) for after_move in (False, True))
        for failing_replace, fail_after_move in failure_modes:
            with self.subTest(failing_replace=failing_replace, fail_after_move=fail_after_move), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "panel.parquet"
                pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
                prior = output.read_bytes()
                sidecar = sidecar_path(output)
                sidecar.write_bytes(b"prior-sidecar\n")
                prior_sidecar = sidecar.read_bytes()
                original_replace = Path.replace
                forward_replaces = 0
                failed = False

                def inject_failure(source: Path, target: Path, *args, **kwargs):
                    nonlocal failed, forward_replaces
                    if not failed:
                        forward_replaces += 1
                        if forward_replaces == failing_replace:
                            failed = True
                            if fail_after_move:
                                original_replace(source, target, *args, **kwargs)
                            raise OSError("injected install failure")
                    return original_replace(source, target, *args, **kwargs)

                with patch.object(Path, "replace", new=inject_failure), self.assertRaisesRegex(OSError, "injected install failure"):
                    write_panel_batches([pd.DataFrame({"value": [2]})], output, code_sources=["tests/test_tables.py"])
                self.assertTrue(failed)
                self.assertEqual(output.read_bytes(), prior)
                self.assertEqual(sidecar.read_bytes(), prior_sidecar)
                self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_nested_same_target_staging_uses_unique_paths_and_cleans_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "panel.parquet"
            with staged_output(target) as first:
                with staged_output(target) as second:
                    self.assertNotEqual(first, second)
                    self.assertTrue(first.exists())
                    self.assertTrue(second.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_large_stamp_and_verify_do_not_hash_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "large.parquet"
            with output.open("wb") as handle:
                handle.truncate(CONTENT_HASH_MAX_BYTES + 1)
            with patch("ddvc.provenance._content_sha256", side_effect=AssertionError("large artefact hashed")):
                stamp(output, code_sources=["tests/test_tables.py"])
                verdict = verify(output)
            record = json.loads(sidecar_path(output).read_text(encoding="utf-8"))
            self.assertIsNone(record["artefact_sha256"])
            self.assertEqual(record["artefact_bytes"], CONTENT_HASH_MAX_BYTES + 1)
            self.assertTrue(verdict["content_current"])

    def test_same_target_publications_serialize_and_leave_matching_last_writer_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            sidecar = sidecar_path(output)
            first_holds_lock = Event()
            release_first = Event()
            second_attempted_lock = Event()
            second_acquired_lock = Event()
            errors: list[BaseException] = []
            real_staged_output = provenance.staged_output
            real_install_lock = provenance.serialized_output_install
            first_sidecar_stage = True

            @contextmanager
            def observed_install_lock(target: Path):
                if current_thread().name == "publisher-b":
                    second_attempted_lock.set()
                with real_install_lock(target):
                    if current_thread().name == "publisher-b":
                        second_acquired_lock.set()
                    yield

            @contextmanager
            def held_staged_output(target: Path):
                nonlocal first_sidecar_stage
                with real_staged_output(target) as temporary:
                    if current_thread().name == "publisher-a" and Path(target) == sidecar and first_sidecar_stage:
                        first_sidecar_stage = False
                        first_holds_lock.set()
                        if not release_first.wait(timeout=5):
                            raise TimeoutError("test did not release first publisher")
                    yield temporary

            def publish(value: int) -> None:
                try:
                    write_panel(pd.DataFrame({"value": [value]}), output, code_sources=["tests/test_tables.py"])
                except BaseException as error:
                    errors.append(error)

            with patch("ddvc.provenance.serialized_output_install", new=observed_install_lock), patch("ddvc.provenance.staged_output", new=held_staged_output):
                first = Thread(target=publish, args=(1,), name="publisher-a")
                second = Thread(target=publish, args=(2,), name="publisher-b")
                first.start()
                self.assertTrue(first_holds_lock.wait(timeout=5))
                second.start()
                self.assertTrue(second_attempted_lock.wait(timeout=5))
                self.assertFalse(second_acquired_lock.is_set())
                release_first.set()
                first.join(timeout=5)
                second.join(timeout=5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(second_acquired_lock.is_set())
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [2])
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(record["artefact_bytes"], output.stat().st_size)
            self.assertEqual(record["artefact_mtime_ns"], output.stat().st_mtime_ns)
            self.assertEqual(record["artefact_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_standalone_stamp_cannot_race_a_same_target_panel_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            write_panel(pd.DataFrame({"value": [1]}), output, code_sources=["tests/test_tables.py"])
            sidecar = sidecar_path(output)
            stamp_holds_lock = Event()
            release_stamp = Event()
            writer_attempted_lock = Event()
            writer_acquired_lock = Event()
            errors: list[BaseException] = []
            real_atomic_output = provenance.atomic_output
            real_install_lock = provenance.serialized_output_install

            @contextmanager
            def observed_install_lock(target: Path):
                if current_thread().name == "panel-writer":
                    writer_attempted_lock.set()
                with real_install_lock(target):
                    if current_thread().name == "panel-writer":
                        writer_acquired_lock.set()
                    yield

            @contextmanager
            def held_stamp_sidecar(target: Path):
                with real_atomic_output(target) as temporary:
                    if current_thread().name == "standalone-stamp":
                        stamp_holds_lock.set()
                        if not release_stamp.wait(timeout=5):
                            raise TimeoutError("test did not release standalone stamp")
                    yield temporary

            def restamp() -> None:
                try:
                    stamp(output, code_sources=["tests/test_tables.py"])
                except BaseException as error:
                    errors.append(error)

            def publish() -> None:
                try:
                    write_panel(pd.DataFrame({"value": [2]}), output, code_sources=["tests/test_tables.py"])
                except BaseException as error:
                    errors.append(error)

            with patch("ddvc.provenance.serialized_output_install", new=observed_install_lock), patch("ddvc.provenance.atomic_output", new=held_stamp_sidecar):
                stamper = Thread(target=restamp, name="standalone-stamp")
                writer = Thread(target=publish, name="panel-writer")
                stamper.start()
                self.assertTrue(stamp_holds_lock.wait(timeout=5))
                writer.start()
                self.assertTrue(writer_attempted_lock.wait(timeout=5))
                self.assertFalse(writer_acquired_lock.is_set())
                release_stamp.set()
                stamper.join(timeout=5)
                writer.join(timeout=5)
            self.assertFalse(stamper.is_alive())
            self.assertFalse(writer.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(writer_acquired_lock.is_set())
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [2])
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(record["artefact_bytes"], output.stat().st_size)
            self.assertEqual(record["artefact_mtime_ns"], output.stat().st_mtime_ns)
            self.assertEqual(record["artefact_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_symlink_replacement_does_not_change_same_target_lock_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            referent = root / "referent.parquet"
            output = root / "panel.parquet"
            pd.DataFrame({"value": [0]}).to_parquet(referent, index=False)
            output.symlink_to(referent.name)
            stamp(output, code_sources=["tests/test_tables.py"])
            sidecar = sidecar_path(output)
            first_replaced_symlink = Event()
            release_first = Event()
            second_attempted_lock = Event()
            second_acquired_lock = Event()
            errors: list[BaseException] = []
            real_install_lock = provenance.serialized_output_install
            real_replace = Path.replace
            held_after_replace = False

            @contextmanager
            def observed_install_lock(target: Path):
                if current_thread().name == "symlink-publisher-b":
                    second_attempted_lock.set()
                with real_install_lock(target):
                    if current_thread().name == "symlink-publisher-b":
                        second_acquired_lock.set()
                    yield

            def held_replace(source: Path, target: Path, *args, **kwargs):
                nonlocal held_after_replace
                result = real_replace(source, target, *args, **kwargs)
                if current_thread().name == "symlink-publisher-a" and Path(target) == output and Path(source) != output and not held_after_replace:
                    held_after_replace = True
                    first_replaced_symlink.set()
                    if not release_first.wait(timeout=5):
                        raise TimeoutError("test did not release symlink publisher")
                return result

            def publish(value: int) -> None:
                try:
                    write_panel(pd.DataFrame({"value": [value]}), output, code_sources=["tests/test_tables.py"])
                except BaseException as error:
                    errors.append(error)

            with patch("ddvc.provenance.serialized_output_install", new=observed_install_lock), patch.object(Path, "replace", new=held_replace):
                first = Thread(target=publish, args=(1,), name="symlink-publisher-a")
                second = Thread(target=publish, args=(2,), name="symlink-publisher-b")
                first.start()
                self.assertTrue(first_replaced_symlink.wait(timeout=5))
                self.assertFalse(output.is_symlink())
                second.start()
                self.assertTrue(second_attempted_lock.wait(timeout=5))
                self.assertFalse(second_acquired_lock.is_set())
                release_first.set()
                first.join(timeout=5)
                second.join(timeout=5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(second_acquired_lock.is_set())
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [2])
            self.assertEqual(pd.read_parquet(referent)["value"].tolist(), [0])
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(record["artefact_bytes"], output.stat().st_size)
            self.assertEqual(record["artefact_mtime_ns"], output.stat().st_mtime_ns)
            self.assertEqual(record["artefact_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
