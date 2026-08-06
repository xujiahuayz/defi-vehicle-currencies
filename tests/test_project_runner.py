from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run"


class ProjectRunnerTests(unittest.TestCase):
    def run_project(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(RUNNER), *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_runner_uses_current_worktree_and_safe_path(self) -> None:
        code = """import ddvc,json,pathlib,sys
root=pathlib.Path.cwd().resolve()
print(json.dumps({'package': str(pathlib.Path(ddvc.__file__).resolve()), 'safe': sys.flags.safe_path, 'paths': sys.path}))
"""
        state = json.loads(self.run_project("-c", code).stdout)
        self.assertTrue(state["safe"])
        self.assertTrue(state["package"].startswith(str(ROOT / "src")))
        self.assertNotIn(str(ROOT / "scripts"), state["paths"])

    def test_python_entrypoints_do_not_mutate_import_paths(self) -> None:
        mutation = "sys.path" + ".insert"
        offenders = [
            str(path.relative_to(ROOT))
            for parent in (ROOT / "scripts", ROOT / "tests")
            for path in parent.rglob("*.py")
            if mutation in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_runner_is_executable(self) -> None:
        self.assertTrue(os.access(RUNNER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
