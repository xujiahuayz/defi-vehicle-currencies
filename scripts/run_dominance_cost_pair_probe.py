#!/usr/bin/env python3
"""Run the quarantined paired dominance-cost heterogeneity probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import time

from ddvc.analysis.dominance_cost_pair_probe import (
    load_panel,
    load_support,
    publish_probe,
    run_probe,
    resolve_probe_input,
)
from ddvc.artifact_release import file_sha256
from ddvc.paths import SHARED_RUNTIME_DIR, repo_path
from ddvc.runtime import exclusive_job


DEFAULT_OUTPUT = SHARED_RUNTIME_DIR / "provisional" / "dominance-cost-pair-probe"
COMPUTE_LOCK = SHARED_RUNTIME_DIR / "locks" / "dominance-cost-pair-probe.lock"


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-quarantined", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if not any("provisional" in part.lower() for part in output_dir.parts):
        raise ValueError("paired dominance-cost probe output must remain in a provisional namespace")
    started = time.perf_counter()
    with exclusive_job(COMPUTE_LOCK, job="dominance-cost paired heterogeneity probe"):
        resolved = resolve_probe_input(repo_path(args.pointer), allow_quarantined=args.allow_quarantined)
        artifacts = resolved.pop("artifacts")
        panel = Path(artifacts["panel"])
        support_path = Path(artifacts["support"])
        input_identity = {
            **resolved,
            "panel_filename": panel.name,
            "panel_sha256": file_sha256(panel),
            "panel_bytes": panel.stat().st_size,
            "support_filename": support_path.name,
            "support_sha256": file_sha256(support_path),
            "support_bytes": support_path.stat().st_size,
        }
        report, ledger = run_probe(load_panel(panel), load_support(support_path), input_identity)
        pointer = publish_probe(report, ledger, output_dir)
    print(
        json.dumps(
            {
                "elapsed_seconds": time.perf_counter() - started,
                "ledger_records": len(ledger),
                "max_rss_bytes": _rss_bytes(),
                "output_pointer": str(output_dir / "current.json"),
                "result_sha256": report["result_sha256"],
                "state_admissibility_counts": report["state_admissibility_counts"],
                "publication": pointer,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
