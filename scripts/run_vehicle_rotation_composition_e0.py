#!/usr/bin/env python3
"""Run the pre-frontier within-cell vehicle-rotation decomposition."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import vehicle_rotation_composition
from ddvc.artifact_release import current_artifact_release
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    resolve_endpoint_candidate_composition_release,
)
from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    write_model_exhibit,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import exclusive_job


PAIR_PANEL = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.jsonl"
DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_support.jsonl"
LOCK = DATA_DIR / "processed" / ".vehicle-rotation-composition-e0.lock"
CODE_SOURCES = [
    "scripts/run_vehicle_rotation_composition_e0.py",
    "src/ddvc/analysis/vehicle_rotation_composition.py",
    "src/ddvc/calendar.py",
    "src/ddvc/endpoint_candidate_composition.py",
    "src/ddvc/endpoint_candidate_composition_release.py",
    "src/ddvc/model_artifacts.py",
]


def _require_release_in_d3(context, pointer_path: Path, *, root: Path) -> None:
    relative = pointer_path.resolve().relative_to(root.resolve()).as_posix()
    if relative not in context.d3_input_relatives:
        raise ValueError(
            "vehicle-rotation composition release is outside the bound D3 release: "
            f"{relative}"
        )


def run(
    *,
    root: Path = REPO_ROOT,
    environment=None,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    pair_panel_output: Path = PAIR_PANEL,
    decomposition_output: Path = DECOMPOSITION,
    support_output: Path = SUPPORT,
) -> int:
    context = model_artifact_context(root=root, environment=environment)
    release = resolve_endpoint_candidate_composition_release(pointer_path)
    _require_release_in_d3(context, release.pointer_path, root=root)
    with current_artifact_release(release.bundle):
        choices = pd.read_parquet(release.artifacts["choices"])
        detail, decomposition, support = vehicle_rotation_composition(choices)
        decomposition = attach_spec_ids(
            decomposition,
            prefix="vehicle_transition_pair_decomposition",
            columns=(
                "metric",
                "reporting_scope",
                "baseline_year",
                "comparison_year",
                "estimand_scope",
            ),
        )
        inputs = list(release.bundle.lineage_paths)
        write_model_exhibit(
            detail,
            pair_panel_output,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "locked pair-date-integration-scope panel on measure-specific common "
                "month-day support; notional, observed opportunity, and exact "
                "search-efficiency state remain unobserved"
            ),
        )
        write_model_exhibit(
            decomposition,
            decomposition_output,
            role="result",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "exact locked midpoint decomposition of the realised 2024-to-2026 "
                "stable-share change into within-common-pair, common-pair reweighting, "
                "common-support-mass, and exclusive-pair terms"
            ),
        )
        write_model_exhibit(
            support,
            support_output,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "measure-specific common month-day, pair-membership, and integration-"
                "scope support for the descriptive realised-composition decomposition"
            ),
        )
        release.bundle.assert_current()
    print(
        f"wrote {len(detail):,} cell rows, {len(decomposition):,} decomposition rows, "
        f"and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle-rotation composition E0"):
        raise SystemExit(main())
