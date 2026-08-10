from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ddvc.paths import REPO_ROOT, _shared_git_runtime_dir, literature_papers_dir, repo_path
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
    interruptible_thread_pool,
)


class RuntimeGuardTests(unittest.TestCase):
    def test_cli_paths_resolve_once_against_the_repository(self) -> None:
        self.assertEqual(repo_path("data/panel.parquet"), REPO_ROOT / "data/panel.parquet")
        absolute = Path("/tmp/panel.parquet")
        self.assertEqual(repo_path(absolute), absolute)

    def test_git_runtime_directory_is_shared_across_linked_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            primary = root / "primary"
            worktree = root / "worktree"
            git_dir = primary / ".git" / "worktrees" / "research"
            git_dir.mkdir(parents=True)
            worktree.mkdir()
            (worktree / ".git").write_text(f"gitdir: {git_dir}\n")
            (git_dir / "commondir").write_text("../..\n")
            expected = primary.resolve() / ".git" / "ddvc-runtime"
            self.assertEqual(_shared_git_runtime_dir(primary), expected)
            self.assertEqual(_shared_git_runtime_dir(worktree), expected)

    def test_ignored_literature_corpus_is_shared_across_linked_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            primary = root / "primary"
            worktree = root / "worktree"
            git_dir = primary / ".git" / "worktrees" / "research"
            git_dir.mkdir(parents=True)
            worktree.mkdir()
            (worktree / ".git").write_text(f"gitdir: {git_dir}\n")
            (git_dir / "commondir").write_text("../..\n")
            expected = primary.resolve() / "literature" / "papers"
            self.assertEqual(literature_papers_dir(primary), expected)
            self.assertEqual(literature_papers_dir(worktree), expected)

    def test_worker_bound_is_positive_and_capped(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(20), 8)
        self.assertEqual(bounded_workers(20, maximum=3), 3)

    def test_atomic_output_installs_only_successful_unique_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "artifact.json"
            with atomic_output(target) as temporary:
                self.assertNotEqual(temporary, target.with_name(target.name + ".tmp"))
                temporary.write_text("complete\n")
            self.assertEqual(target.read_text(), "complete\n")
            with self.assertRaisesRegex(RuntimeError, "failed"):
                with atomic_output(target) as temporary:
                    temporary.write_text("partial\n")
                    raise RuntimeError("failed")
            self.assertEqual(target.read_text(), "complete\n")
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_exclusive_job_refuses_a_concurrent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "job.lock"
            with exclusive_job(lock_path, job="test job"):
                with self.assertRaisesRegex(RuntimeError, "test job is already running"):
                    with exclusive_job(lock_path, job="test job"):
                        self.fail("a second owner acquired the same job lock")

    def test_interrupted_process_pool_terminates_workers(self) -> None:
        executor = MagicMock()
        with patch("ddvc.runtime.ProcessPoolExecutor", return_value=executor):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with interruptible_process_pool(2):
                    raise RuntimeError("stop")
        executor.terminate_workers.assert_called_once_with()
        executor.shutdown.assert_not_called()

    def test_interrupted_thread_pool_waits_for_active_work_before_failure_escapes(self) -> None:
        executor = MagicMock()
        with patch("ddvc.runtime.ThreadPoolExecutor", return_value=executor):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with interruptible_thread_pool(2):
                    raise RuntimeError("stop")
        executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_active_thread_cannot_publish_after_failure_escapes(self) -> None:
        started = threading.Event()
        write_times: list[float] = []

        def active_write() -> None:
            started.set()
            time.sleep(0.03)
            write_times.append(time.monotonic())

        with self.assertRaisesRegex(RuntimeError, "stop"):
            with interruptible_thread_pool(1) as executor:
                executor.submit(active_write)
                self.assertTrue(started.wait(timeout=1))
                raise RuntimeError("stop")
        escaped_at = time.monotonic()
        self.assertEqual(len(write_times), 1)
        self.assertLessEqual(write_times[0], escaped_at)
        time.sleep(0.03)
        self.assertEqual(len(write_times), 1)


if __name__ == "__main__":
    unittest.main()
