from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ddvc.runtime import atomic_output, exclusive_job, interruptible_process_pool


class RuntimeGuardTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
