#!/usr/bin/env python3
"""Regenerate the results evidence map from tracked scripts.

The final evidence map is intentionally built from generated CSV tables under
``output/tables/``. Those tables are ignored by git, so a clean checkout needs
the full upstream table chain before rebuilding ``paper/results_evidence_map.tex``:

1. Supporting analytics scripts write the ``table_r*`` inputs.
2. ``scripts/build_jfe_main_tables.py`` writes ``table_m01``-``table_m07``.
3. ``scripts/run_core_rq_experiments.py`` writes ``table_m08``-``table_m18``.
4. ``scripts/build_results_evidence_latex.py --pdf`` writes the committed TeX
   evidence map and a review PDF.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SUPPORT_TABLE_STEPS = [
    "run_empirical_proposition_tests.py",
    "run_robustness_tests.py",
    "run_claim_defense_analytics.py",
    "run_jfe_construct_validity_checks.py",
    "run_jfe_identification_extensions.py",
    "run_jfe_remaining_blocker_fixes.py",
    "run_feedback_proposition_tests.py",
]


def run_step(script: str, *args: str) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Regenerate generated tables and paper/results_evidence_map.tex only.",
    )
    args = parser.parse_args(argv)

    for script in SUPPORT_TABLE_STEPS:
        run_step(script)
    run_step("build_jfe_main_tables.py")
    run_step("run_core_rq_experiments.py")
    latex_args = [] if args.no_pdf else ["--pdf"]
    run_step("build_results_evidence_latex.py", *latex_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
