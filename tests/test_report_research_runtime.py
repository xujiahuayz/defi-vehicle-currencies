from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "report_research_runtime", ROOT / "scripts" / "utils" / "report_research_runtime.py"
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class ResearchRuntimeReportTests(unittest.TestCase):
    def manifest(self, root: Path) -> Path:
        path = root / "runtime.json"
        path.write_text(json.dumps({
            "hosts": {
                "m3": {"transport": "local", "reason": "interactive analysis"},
                "studio": {"transport": "ssh", "target": "studio", "reason": "large-memory processing"},
            },
            "jobs": [
                {"node": "D2", "host": "studio", "host_reason": "capital build", "command": "./scripts/run build.py", "dependencies": [], "markers": {"complete": "/remote/d2.complete", "failed": "/remote/d2.failed", "running": "/remote/d2.running"}},
                {"node": "D3", "host": "m3", "command": "./scripts/run regress.py", "dependencies": ["D2"], "markers": {"complete": "markers/d3.complete", "running": "markers/d3.running"}},
            ],
        }), encoding="utf-8")
        return path

    def test_report_classifies_dependencies_and_flags_ready_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = RUNTIME.load_manifest(self.manifest(Path(temporary)))
            local_complete = manifest["jobs"][1]["markers"]["complete"]
            local_running = manifest["jobs"][1]["markers"]["running"]
            reports = {
                "local": {"reachable": True, "cpu_count": 8, "load_1m": 1.0, "memory_total_bytes": 64, "memory_available_bytes": 32, "markers": {local_complete: {"exists": False}, local_running: {"exists": False}}},
                "ssh": {"reachable": True, "cpu_count": 16, "load_1m": 2.0, "memory_total_bytes": 128, "memory_available_bytes": 96, "markers": {"/remote/d2.complete": {"exists": True}, "/remote/d2.failed": {"exists": False}, "/remote/d2.running": {"exists": False}}},
            }
            with patch.object(RUNTIME, "probe_host", side_effect=lambda host, _paths: reports[host["transport"]]):
                report = RUNTIME.inspect(manifest)
        self.assertEqual(report["sets"]["complete"], ["D2"])
        self.assertEqual(report["sets"]["ready"], ["D3"])
        self.assertEqual(report["scheduling_defects"], [{"node": "D3", "host": "m3", "reason": "dependencies complete but no running or terminal marker"}])

    def test_pending_job_waits_for_incomplete_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = RUNTIME.load_manifest(self.manifest(Path(temporary)))
            with patch.object(RUNTIME, "probe_host", return_value={"reachable": True, "markers": {}}):
                report = RUNTIME.inspect(manifest)
        self.assertEqual(report["sets"]["ready"], ["D2"])
        self.assertEqual(report["sets"]["waiting"], ["D3"])

    def test_terminal_marker_conflict_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = RUNTIME.load_manifest(self.manifest(Path(temporary)))
            remote = {path: {"exists": kind in {"complete", "failed"}} for kind, path in manifest["jobs"][0]["markers"].items()}
            with patch.object(RUNTIME, "probe_host", side_effect=lambda host, _paths: {"reachable": True, "markers": remote if host["transport"] == "ssh" else {}}):
                report = RUNTIME.inspect(manifest)
        self.assertEqual(report["sets"]["conflict"], ["D2"])
        self.assertEqual(report["sets"]["waiting"], ["D3"])

    def test_ssh_probe_is_one_read_only_python_stdin_call(self) -> None:
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps({"cpu_count": 16, "load_1m": 1.5, "memory_total_bytes": 128, "memory_available_bytes": 64, "markers": {"/x": {"exists": False}}}), stderr="")
        with patch.object(RUNTIME.subprocess, "run", return_value=response) as run:
            report = RUNTIME.probe_host({"transport": "ssh", "target": "studio"}, ["/x"])
        self.assertTrue(report["reachable"])
        self.assertEqual(run.call_args.args[0], ["ssh", "studio", "python3", "-"])
        self.assertNotIn("kill", run.call_args.kwargs["input"])
        self.assertNotIn("write_text", run.call_args.kwargs["input"])

    def test_manifest_rejects_remote_relative_markers_and_unsafe_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.manifest(Path(temporary))
            body = json.loads(path.read_text())
            body["jobs"][0]["markers"]["complete"] = "relative.complete"
            path.write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError, "remote markers"):
                RUNTIME.load_manifest(path)
            body["jobs"][0]["markers"]["complete"] = "/remote/complete"
            body["hosts"]["studio"]["target"] = "-oProxyCommand=bad"
            path.write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError, "unsafe SSH target"):
                RUNTIME.load_manifest(path)

    def test_manifest_rejects_dependency_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.manifest(Path(temporary))
            body = json.loads(path.read_text())
            body["jobs"][0]["dependencies"] = ["D3"]
            path.write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError, "cycle"):
                RUNTIME.load_manifest(path)


if __name__ == "__main__":
    unittest.main()
