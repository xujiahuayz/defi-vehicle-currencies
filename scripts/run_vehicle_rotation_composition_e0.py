#!/usr/bin/env python3
"""Run the pre-frontier raw aggregate descriptive companion.

This four-term accounting is not a decomposition of a fixed-effects coefficient.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import (
    estimate_pair_fixed_effect_rotation,
    load_market_incidence_annual_pairs,
    vehicle_rotation_composition,
    vehicle_rotation_market_incidence_decomposition,
)
from ddvc.artifact_release import SemanticValidationReceipt
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    current_endpoint_candidate_composition_release,
)
from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    write_model_exhibit,
    write_model_panel,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import exclusive_job


PAIR_PANEL = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.parquet"
PAIR_CONTRIBUTIONS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_contributions.parquet"
)
DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_support.jsonl"
FIXED_EFFECT_RESULTS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
)
LOCK = DATA_DIR / "processed" / ".vehicle-rotation-composition-e0.lock"
CODE_SOURCES = [
    "scripts/run_vehicle_rotation_composition_e0.py",
    "src/ddvc/analysis/vehicle_rotation_composition.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/calendar.py",
    "src/ddvc/endpoint_candidate_composition.py",
    "src/ddvc/endpoint_candidate_composition_release.py",
    "src/ddvc/model_artifacts.py",
]


def _expected_release_in_d3(context, pointer_path: Path, *, root: Path):
    relative = pointer_path.resolve().relative_to(root.resolve()).as_posix()
    record = context.d3_input_records.get(relative)
    if record is None:
        raise ValueError(
            "vehicle-rotation composition release is outside the bound D3 release: "
            f"{relative}"
        )
    receipt = record.get("semantic_validation")
    if not isinstance(receipt, dict):
        raise ValueError("bound endpoint release lacks a semantic receipt")
    expected = SemanticValidationReceipt(
        str(receipt.get("generation_id") or ""),
        str(receipt.get("validator_fingerprint") or ""),
    )
    if record.get("release_generation") != expected.generation_id:
        raise ValueError("bound endpoint release generation and receipt disagree")
    return expected


def run(
    *,
    root: Path = REPO_ROOT,
    environment=None,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    pair_panel_output: Path = PAIR_PANEL,
    pair_contribution_output: Path = PAIR_CONTRIBUTIONS,
    decomposition_output: Path = DECOMPOSITION,
    support_output: Path = SUPPORT,
    fixed_effect_output: Path = FIXED_EFFECT_RESULTS,
) -> int:
    context = model_artifact_context(root=root, environment=environment)
    expected_receipt = _expected_release_in_d3(context, pointer_path, root=root)
    with current_endpoint_candidate_composition_release(
        pointer_path,
        expected_semantic_receipt=expected_receipt,
    ) as release:
        if release.generation_id != expected_receipt.generation_id:
            raise ValueError("endpoint release differs from the D3-bound generation")
        choices = pd.read_parquet(release.artifacts["choices"])
        detail, decomposition, support, pair_contributions = (
            vehicle_rotation_composition(choices)
        )
        fixed_effect_results = estimate_pair_fixed_effect_rotation(detail)
        annual_market_pairs = load_market_incidence_annual_pairs(
            release.artifacts["pair_support"], release.artifacts["choices"]
        )
        market_decomposition, market_support = (
            vehicle_rotation_market_incidence_decomposition(annual_market_pairs)
        )
        decomposition = pd.concat(
            [decomposition, market_decomposition], ignore_index=True, sort=False
        )
        support = pd.concat([support, market_support], ignore_index=True, sort=False)
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
        write_model_panel(
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
        write_model_panel(
            pair_contributions,
            pair_contribution_output,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "ranked descriptive ordered-pair contributions to within-pair choice, "
                "pair reweighting, and baseline- or comparison-exclusive composition; "
                "each row carries the intentionally unallocated aggregate common-support "
                "bridge and the aggregate total change"
            ),
        )
        fixed_effect_results = attach_spec_ids(
            fixed_effect_results,
            prefix="vehicle_transition_pair_fixed_effects",
            columns=("metric", "baseline_year", "comparison_year", "estimator_id"),
        )
        write_model_exhibit(
            fixed_effect_results,
            fixed_effect_output,
            role="result",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=[pair_panel_output, *inputs],
            notes=(
                "locked denominator-mass WLS estimate of the 2026-minus-2024 stable-share "
                "change inside ordered-pair by month-day by realised-integration-scope "
                "cells, with two-way ordered-pair and calendar-date CR1 inference"
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
        f"wrote {len(detail):,} cell rows, {len(pair_contributions):,} ranked pair "
        f"contributions, {len(fixed_effect_results):,} fixed-effect results, "
        f"{len(decomposition):,} decomposition rows, and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle-rotation composition E0"):
        raise SystemExit(main())
