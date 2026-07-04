#!/usr/bin/env python3
"""Supervise gap-only raw fetches and switch to narrower stream fetches on failure."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
FETCH = ROOT / "scripts" / "fetch_raw_market_data.py"


def run(args: list[str], log: Path) -> int:
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "supervisor_run", "args": args, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")
        fh.flush()
        proc = subprocess.run([str(PYTHON), str(FETCH), *args], cwd=ROOT, stdout=fh, stderr=fh)
        fh.write(json.dumps({"event": "supervisor_exit", "code": proc.returncode, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")
        fh.flush()
        return proc.returncode


def coverage(end: str) -> dict[str, object]:
    proc = subprocess.run(
        [str(PYTHON), str(FETCH), "coverage", "--dex", "all", "--end", end],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(proc.stdout)


def missing_total(report: dict[str, object]) -> int:
    return sum(
        int(count)
        for source in report.values()
        for count in source["missing"].values()  # type: ignore[index]
    )


def missing_sources(report: dict[str, object]) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for name, source in report.items():
        streams = [stream for stream, count in source["missing"].items() if count]  # type: ignore[index]
        if streams:
            rows.append((name, streams))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", required=True)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--cycles", type=int, default=24)
    parser.add_argument("--sleep", type=int, default=60)
    args = parser.parse_args()

    for cycle in range(1, args.cycles + 1):
        report = coverage(args.end)
        total = missing_total(report)
        with args.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "supervisor_coverage", "cycle": cycle, "missing_total": total}) + "\n")
        if total == 0:
            return 0

        code = run(
            ["fetch", "--dex", "all", "--start", "genesis", "--end", args.end, "--gaps-only", "--dune-sleep", "8", "--max-retries", "8"],
            args.log,
        )
        if code == 0:
            continue

        # Adaptive fallback: a broad multi-stream day can fail even when narrower
        # source/stream fetches work. Split the remaining work before retrying.
        for source, streams in missing_sources(coverage(args.end)):
            for stream in streams:
                run(
                    [
                        "fetch",
                        "--dex",
                        source,
                        "--start",
                        "genesis",
                        "--end",
                        args.end,
                        "--streams",
                        stream,
                        "--gaps-only",
                        "--dune-sleep",
                        "8",
                        "--max-retries",
                        "4",
                    ],
                    args.log,
                )
        time.sleep(args.sleep)
    return 2 if missing_total(coverage(args.end)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
