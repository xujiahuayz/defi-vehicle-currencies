from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.provenance import (
    _fingerprint_contents,
    _legacy_semantic_compatible,
    cache_key,
    describe_input,
    ensure_released_directory_alias,
    git_state,
    input_matches,
    portable_content_manifest,
    portable_content_sha256,
    portable_manifest_sha256,
    require_current_artifacts,
    semantic_code_fingerprint,
)


class ProvenanceInputTests(unittest.TestCase):
    def test_portable_hash_ignores_gzip_container_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.jsonl.gz"
            second = root / "second.jsonl.gz"
            payload = b'{"id":"a"}\n{"id":"b"}\n'
            with first.open("wb") as raw_handle:
                with gzip.GzipFile(filename="first-source", mode="wb", fileobj=raw_handle, mtime=1) as handle:
                    handle.write(payload)
            with second.open("wb") as raw_handle:
                with gzip.GzipFile(filename="second-source", mode="wb", fileobj=raw_handle, mtime=2) as handle:
                    handle.write(payload)

            self.assertNotEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(portable_content_sha256(first), portable_content_sha256(second))

    def test_portable_manifest_has_sorted_exact_perimeter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.json").write_text("b", encoding="utf-8")
            (root / "a.json").write_text("a", encoding="utf-8")
            (root / "ignored.txt").write_text("ignored", encoding="utf-8")

            manifest = portable_content_manifest(root, patterns=["*.json"])

            self.assertEqual([entry["path"] for entry in manifest], ["a.json", "b.json"])
            self.assertEqual({entry["content_encoding"] for entry in manifest}, {"identity"})

    def test_portable_manifest_root_excludes_gzip_container_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            payload = b'{"id":"same"}\n'
            for directory, embedded_name in ((first_root, "a"), (second_root, "longer-name")):
                path = directory / "day.jsonl.gz"
                with path.open("wb") as raw_handle:
                    with gzip.GzipFile(filename=embedded_name, mode="wb", fileobj=raw_handle, mtime=0) as handle:
                        handle.write(payload)

            first = portable_content_manifest(first_root, patterns=["*.jsonl.gz"])
            second = portable_content_manifest(second_root, patterns=["*.jsonl.gz"])

            self.assertNotEqual(first[0]["container_bytes"], second[0]["container_bytes"])
            self.assertEqual(portable_manifest_sha256(first), portable_manifest_sha256(second))

    def test_portable_manifest_rejects_an_empty_perimeter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                portable_content_manifest(tmp, patterns=["*.jsonl.gz"])

    @patch("ddvc.provenance.verify", return_value={"status": "ok"})
    @patch("ddvc.provenance.sidecar_path")
    def test_documentation_only_release_aliases_recorded_engine_without_copying(
        self, sidecar_path, _verify
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            perimeter = root / "cache"
            released = perimeter / "engine_released"
            expected = perimeter / "engine_current"
            released.mkdir(parents=True)
            superseded = perimeter / "engine_superseded_alias"
            superseded.symlink_to(released.name, target_is_directory=True)
            marker = root / "release.prov.json"
            marker.write_text(
                '{"inputs": [{"path": "' + str(released) + '"}]}',
                encoding="utf-8",
            )
            sidecar_path.return_value = marker

            actual = ensure_released_directory_alias(
                root / "release.parquet", expected=expected, under=perimeter
            )

            self.assertEqual(actual, released)
            self.assertFalse(superseded.exists())
            self.assertFalse(superseded.is_symlink())
            self.assertTrue(expected.is_symlink())
            self.assertEqual(expected.resolve(), released.resolve())
            self.assertIsNone(
                ensure_released_directory_alias(
                    root / "release.parquet", expected=expected, under=perimeter
                )
            )

    def test_semantic_fingerprint_ignores_docstrings_but_not_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "module.py"
            source.write_text('"""old explanation"""\n\ndef value():\n    """old detail"""\n    return 1\n')
            with patch("ddvc.provenance.ROOT", root):
                before = semantic_code_fingerprint(["module.py"])
                source.write_text('"""new explanation"""\n\ndef value():\n    """new detail"""\n    return 1\n')
                after_documentation = semantic_code_fingerprint(["module.py"])
                source.write_text('"""new explanation"""\n\ndef value():\n    return 2\n')
                after_code = semantic_code_fingerprint(["module.py"])
            self.assertEqual(before, after_documentation)
            self.assertNotEqual(before, after_code)

    @patch("ddvc.provenance._git_source")
    def test_legacy_stamp_requires_exact_old_bytes_before_ast_fallback(self, git_source) -> None:
        old = b'"""old"""\nvalue = 1\n'
        new = b'"""new"""\nvalue = 1\n'
        changed = b'"""new"""\nvalue = 2\n'
        git_source.return_value = old
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "module.py"
            source.write_bytes(new)
            record = {
                "code_sources": ["module.py"],
                "code_fingerprint": _fingerprint_contents({"module.py": old}, semantic=False),
                "git": {"commit": "abc", "dirty_tracked_files": [], "dirty_untracked_files": []},
            }
            with patch("ddvc.provenance.ROOT", root):
                self.assertTrue(_legacy_semantic_compatible(record))
                source.write_bytes(changed)
                self.assertFalse(_legacy_semantic_compatible(record))
            record["code_fingerprint"] = "not-the-stamped-bytes"
            with patch("ddvc.provenance.ROOT", root):
                source.write_bytes(new)
                self.assertFalse(_legacy_semantic_compatible(record))

    @patch("ddvc.provenance.verify")
    def test_consumer_gate_rejects_any_noncurrent_input(self, verify) -> None:
        verify.side_effect = [
            {"artefact": "first.parquet", "status": "ok"},
            {"artefact": "second.parquet", "status": "stale"},
        ]
        with self.assertRaisesRegex(
            RuntimeError, "consumer requires current analysis inputs: second.parquet=stale"
        ):
            require_current_artifacts(
                ["first.parquet", "second.parquet"], consumer="consumer"
            )

    def test_absolute_data_symlink_keeps_its_logical_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "worktree"
            shared = Path(tmp) / "shared"
            shared.mkdir()
            (shared / "day.parquet").write_text("data")
            link = root / "data" / "unified"
            link.parent.mkdir(parents=True)
            link.symlink_to(shared, target_is_directory=True)

            with patch("ddvc.provenance.ROOT", root):
                record = describe_input(link)
                self.assertTrue(input_matches(record))

            self.assertEqual(record["path"], "data/unified")

    def test_file_change_invalidates_recorded_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.txt"
            path.write_text("first")
            record = describe_input(path)
            self.assertTrue(input_matches(record))
            path.write_text("second")
            self.assertFalse(input_matches(record))

    def test_directory_tree_change_invalidates_recorded_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a")
            record = describe_input(root)
            self.assertEqual(record["kind"], "directory")
            self.assertEqual(record["entries"], 1)
            self.assertTrue(input_matches(record))
            (root / "b.txt").write_text("b")
            self.assertFalse(input_matches(record))

    def test_cache_key_changes_with_declared_input_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a")
            sources = ["tests/test_provenance_inputs.py"]
            before = cache_key(sources, inputs=[root])
            (root / "b.txt").write_text("b")
            after = cache_key(sources, inputs=[root])
            self.assertNotEqual(before, after)

    def test_token_price_release_does_not_treat_resumability_cache_as_input(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "scripts" / "build_token_price_panel.py").read_text()
        self.assertIn("inputs=INPUTS", source)
        self.assertNotIn("inputs=[*INPUTS, root]", source)
        self.assertIn("resumable cache", source)

    @patch("ddvc.provenance._run")
    def test_generated_target_does_not_mark_its_own_build_dirty(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/result.jsonl\n M src/ddvc/model.py",
            "main",
        ]
        state = git_state(["output/exhibits/result.jsonl"])
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_tracked_files"], ["src/ddvc/model.py"])

    @patch("ddvc.provenance._run")
    def test_only_generated_targets_yield_a_clean_build_state(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/result.jsonl\n M data/manifests/output/exhibits/result.jsonl.prov.json",
            "main",
        ]
        state = git_state(
            [
                "output/exhibits/result.jsonl",
                "data/manifests/output/exhibits/result.jsonl.prov.json",
            ]
        )
        self.assertFalse(state["dirty"])
        self.assertEqual(state["dirty_tracked_files"], [])

    @patch("ddvc.provenance._run")
    def test_other_generated_outputs_do_not_taint_code_state(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/first.jsonl\n M data/manifests/output/exhibits/first.jsonl.prov.json",
            "main",
        ]
        state = git_state()
        self.assertFalse(state["dirty"])
        self.assertEqual(
            state["dirty_generated_files"],
            [
                "output/exhibits/first.jsonl",
                "data/manifests/output/exhibits/first.jsonl.prov.json",
            ],
        )

    @patch("ddvc.provenance._run")
    def test_untracked_source_marks_build_dirty(self, run) -> None:
        run.side_effect = [
            "abc123",
            "?? src/ddvc/new_estimator.py\n?? output/exhibits/new.jsonl",
            "main",
        ]
        state = git_state()
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_untracked_files"], ["src/ddvc/new_estimator.py"])
        self.assertEqual(state["dirty_generated_files"], ["output/exhibits/new.jsonl"])


if __name__ == "__main__":
    unittest.main()
