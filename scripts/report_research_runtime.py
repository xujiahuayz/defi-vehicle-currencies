#!/usr/bin/env python3
"""Report declared research jobs and host capacity without controlling either.

The JSON manifest has ``hosts`` keyed by name and a ``jobs`` list. Each host declares ``transport`` (``local`` or ``ssh``), an optional SSH ``target`` and a human ``reason``. Each job declares ``node``, ``host``, display-only ``command``, ``dependencies``, status ``markers`` keyed by running/complete/failed and an optional ``host_reason``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_SSH_TARGET = re.compile(r"^[A-Za-z0-9_.@:-]+$")
_PROBE_PROGRAM = r'''
import json
import os
import pathlib
import subprocess


def memory():
    proc = pathlib.Path("/proc/meminfo")
    if proc.is_file():
        values = {}
        for line in proc.read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        return values.get("MemTotal"), values.get("MemAvailable")
    try:
        total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        page = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"], text=True).strip())
        values = {}
        for line in subprocess.check_output(["vm_stat"], text=True).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().rstrip("."))
        available = page * sum(values.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
        return total, available
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return None, None


total, available = memory()
markers = {}
for value in MARKER_PATHS:
    try:
        stat = os.stat(value)
        markers[value] = {"exists": True, "mtime": stat.st_mtime}
    except FileNotFoundError:
        markers[value] = {"exists": False, "mtime": None}
print(json.dumps({"cpu_count": os.cpu_count(), "load_1m": os.getloadavg()[0], "memory_total_bytes": total, "memory_available_bytes": available, "markers": markers}))
'''


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), "manifest must be an object")
    hosts = manifest.get("hosts")
    jobs = manifest.get("jobs")
    _require(isinstance(hosts, dict) and hosts, "hosts must be a non-empty object")
    _require(isinstance(jobs, list) and jobs, "jobs must be a non-empty list")
    for name, host in hosts.items():
        _require(isinstance(name, str) and name, "host names must be non-empty strings")
        _require(isinstance(host, dict), f"host {name} must be an object")
        transport = host.get("transport")
        _require(transport in {"local", "ssh"}, f"host {name} transport must be local or ssh")
        if transport == "ssh":
            target = host.get("target")
            _require(isinstance(target, str) and bool(_SSH_TARGET.fullmatch(target)) and not target.startswith("-"), f"host {name} has an unsafe SSH target")
    names: set[str] = set()
    for job in jobs:
        _require(isinstance(job, dict), "each job must be an object")
        node = job.get("node")
        _require(isinstance(node, str) and node and node not in names, "job nodes must be unique non-empty strings")
        names.add(node)
        _require(job.get("host") in hosts, f"job {node} names an unknown host")
        _require(isinstance(job.get("command"), str) and job["command"], f"job {node} needs a display-only command")
        _require(isinstance(job.get("dependencies", []), list), f"job {node} dependencies must be a list")
        markers = job.get("markers")
        _require(isinstance(markers, dict) and markers, f"job {node} needs status markers")
        _require(set(markers) <= {"running", "complete", "failed"}, f"job {node} has an unknown marker kind")
        _require(all(isinstance(value, str) and value for value in markers.values()), f"job {node} marker paths must be strings")
    for job in jobs:
        node = job["node"]
        _require(all(isinstance(dep, str) and dep in names and dep != node for dep in job.get("dependencies", [])), f"job {node} has an invalid dependency")
        if hosts[job["host"]]["transport"] == "local":
            job["markers"] = {kind: str((path.parent / value).resolve()) if not Path(value).is_absolute() else value for kind, value in job["markers"].items()}
        else:
            _require(all(Path(value).is_absolute() for value in job["markers"].values()), f"remote markers for {node} must be absolute paths")
    remaining = {job["node"]: set(job.get("dependencies", [])) for job in jobs}
    resolved: set[str] = set()
    while remaining:
        ready = {node for node, dependencies in remaining.items() if dependencies <= resolved}
        _require(bool(ready), "job dependencies contain a cycle")
        resolved.update(ready)
        for node in ready:
            del remaining[node]
    return manifest


def probe_host(host: dict[str, Any], marker_paths: list[str]) -> dict[str, Any]:
    program = f"MARKER_PATHS = {json.dumps(marker_paths)}\n{_PROBE_PROGRAM}"
    command = [sys.executable, "-"] if host["transport"] == "local" else ["ssh", host["target"], "python3", "-"]
    try:
        result = subprocess.run(command, input=program, text=True, capture_output=True, timeout=20, check=True)
        report = json.loads(result.stdout)
        report["reachable"] = True
        return report
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as error:
        return {"reachable": False, "error": str(error), "markers": {}}


def inspect(manifest: dict[str, Any]) -> dict[str, Any]:
    paths_by_host = {name: [] for name in manifest["hosts"]}
    for job in manifest["jobs"]:
        paths_by_host[job["host"]].extend(job["markers"].values())
    hosts = {name: {**probe_host(spec, sorted(set(paths_by_host[name]))), "reason": spec.get("reason", "")} for name, spec in manifest["hosts"].items()}
    jobs: list[dict[str, Any]] = []
    by_node: dict[str, dict[str, Any]] = {}
    for job in manifest["jobs"]:
        host = hosts[job["host"]]
        found = [kind for kind, path in job["markers"].items() if host.get("markers", {}).get(path, {}).get("exists")]
        terminal = [kind for kind in found if kind in {"complete", "failed"}]
        if not host["reachable"]:
            status = "unknown"
        elif len(terminal) > 1:
            status = "conflict"
        elif terminal:
            status = terminal[0]
        elif "running" in found:
            status = "running"
        else:
            status = "pending"
        row = {**job, "status": status, "marker": ",".join(f"{kind}:{job['markers'][kind]}" for kind in found) or None, "host_reason": job.get("host_reason", host.get("reason", ""))}
        jobs.append(row)
        by_node[job["node"]] = row
    for row in jobs:
        if row["status"] == "pending":
            row["status"] = "ready" if all(by_node[dep]["status"] == "complete" for dep in row.get("dependencies", [])) else "waiting"
    sets = {status: [row["node"] for row in jobs if row["status"] == status] for status in ("ready", "running", "waiting", "complete", "failed", "conflict", "unknown")}
    defects = [{"node": row["node"], "host": row["host"], "reason": "dependencies complete but no running or terminal marker"} for row in jobs if row["status"] == "ready"]
    return {"hosts": hosts, "jobs": jobs, "sets": sets, "scheduling_defects": defects}


def _gib(value: int | None) -> str:
    return "?" if value is None else f"{value / 2**30:.1f}GiB"


def print_text(report: dict[str, Any]) -> None:
    print("HOSTS")
    for name, host in report["hosts"].items():
        if not host["reachable"]:
            print(f"  {name}: unreachable ({host['error']}) reason={host['reason'] or '-'}")
            continue
        print(f"  {name}: load={host.get('load_1m', '?')}/{host.get('cpu_count', '?')} memory={_gib(host.get('memory_available_bytes'))}/{_gib(host.get('memory_total_bytes'))} reason={host['reason'] or '-'}")
    print("NODES")
    for row in report["jobs"]:
        print(f"  {row['node']}: {row['status']} host={row['host']} marker={row['marker'] or '-'} host_reason={row['host_reason'] or '-'} command={row['command']}")
    print("SETS " + " ".join(f"{name}={','.join(nodes) or '-'}" for name, nodes in report["sets"].items()))
    for defect in report["scheduling_defects"]:
        print(f"SCHEDULING DEFECT ready+idle: {defect['node']} on {defect['host']}: {defect['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = inspect(load_manifest(args.manifest.resolve()))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 1 if report["scheduling_defects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
