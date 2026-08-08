from __future__ import annotations

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
    require_current_artifacts,
    semantic_code_fingerprint,
)


class ProvenanceInputTests(unittest.TestCase):
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
