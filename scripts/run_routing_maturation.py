#!/usr/bin/env python3
"""Run the locked routing-maturation estimators on current D3 panels.

Reads
  data/processed/routing_maturation_cell_day.parquet
  data/processed/routing_transition_cells.parquet
  data/processed/routing_maturation_exact_horizons.parquet

Writes
  output/exhibits/e0_routing_maturation_estimates.jsonl
  output/exhibits/e0_routing_maturation_support.jsonl
"""

from __future__ import annotations

import gc

import pandas as pd

from ddvc.analysis.routing_maturation import (
    DYNAMIC_COLUMNS,
    MATURATION_COLUMNS,
    TRANSITION_COLUMNS,
    estimate_dynamics,
    estimate_maturation,
    estimate_transition,
    dynamics_support_geometry,
    frontier_verified_support_geometry,
    support_geometry,
    transition_support_geometry,
)
from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    write_model_exhibit,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import require_current_artifacts
from ddvc.runtime import exclusive_job


CELL_DAY = DATA_DIR / "processed" / "routing_maturation_cell_day.parquet"
TRANSITION = DATA_DIR / "processed" / "routing_transition_cells.parquet"
EXACT_HORIZONS = DATA_DIR / "processed" / "routing_maturation_exact_horizons.parquet"
FRONTIER_SUPPORT = DATA_DIR / "processed" / "transaction_state_frontier_daily_support.parquet"
ESTIMATE_OUTPUT = OUTPUT_DIR / "exhibits" / "e0_routing_maturation_estimates.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits" / "e0_routing_maturation_support.jsonl"
LOCK = DATA_DIR / "processed" / ".routing_maturation_estimates.lock"
CODE_SOURCES = [
    "scripts/run_routing_maturation.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/analysis/routing_contract.py",
    "src/ddvc/analysis/routing_maturation.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
]
SPEC_ID_COLUMNS = (
    "family",
    "spec",
    "margin",
    "outcome",
    "horizon_days",
    "weighting",
    "support",
    "reproduction_tolerance_bps",
)


def support_blocks_estimation(support_frames: list[pd.DataFrame]) -> bool:
    """Collapse calibrated hard support failures without fitting a model."""

    return any(
        bool(frame["blocks_estimation"].astype(bool).any())
        for frame in support_frames
    )


def main() -> int:
    context = model_artifact_context()
    inputs = [FRONTIER_SUPPORT, CELL_DAY, TRANSITION, EXACT_HORIZONS]
    require_current_artifacts(inputs, consumer="routing-maturation estimator")
    frontier_support = pd.read_parquet(
        FRONTIER_SUPPORT,
        columns=[
            "day",
            "within_20pct_chosen_quote_eligible_routes",
            "within_20pct_chosen_quote_available",
            "within_20pct_chosen_output_mismatch",
        ],
    )
    verified_support = frontier_verified_support_geometry(frontier_support)
    del frontier_support
    gc.collect()
    cell_support = pd.read_parquet(
        CELL_DAY,
        columns=[
            "date",
            "cell_id",
            "route_count",
            "reproduction_tolerance_bps",
            "recurrent_primary",
            "recurrent_strict",
        ],
    )
    maturation_support = support_geometry(cell_support)
    del cell_support
    gc.collect()
    transition = pd.read_parquet(TRANSITION, columns=list(TRANSITION_COLUMNS))
    transition_support = transition_support_geometry(transition)
    del transition
    gc.collect()
    horizons = pd.read_parquet(EXACT_HORIZONS, columns=list(DYNAMIC_COLUMNS))
    horizon_support = dynamics_support_geometry(horizons)
    results = [verified_support, maturation_support, transition_support, horizon_support]
    estimation_blocked = support_blocks_estimation(results)
    if estimation_blocked:
        del horizons
        gc.collect()
        combined = pd.concat(results, ignore_index=True, sort=False)
        write_model_exhibit(
            combined,
            SUPPORT_OUTPUT,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "routing maturation support geometry only; calibrated hard support failure; "
                "no fitted specifications"
            ),
        )
        print(
            "BLOCKED: routing-maturation calibrated support contract failed; "
            "wrote 0 fitted specifications"
        )
        return 2
    results.insert(0, estimate_dynamics(horizons))
    del horizons
    gc.collect()
    transition = pd.read_parquet(TRANSITION, columns=list(TRANSITION_COLUMNS))
    results.insert(0, estimate_transition(transition))
    del transition
    gc.collect()
    cell_day = pd.read_parquet(CELL_DAY, columns=list(MATURATION_COLUMNS))
    results.insert(0, estimate_maturation(cell_day))
    del cell_day
    gc.collect()
    combined = pd.concat(results, ignore_index=True, sort=False)
    estimates = combined[combined["record_type"].eq("estimate")].reset_index(drop=True)
    support = combined[~combined["record_type"].eq("estimate")].reset_index(drop=True)
    estimates = attach_spec_ids(
        estimates,
        prefix="routing_maturation_e0",
        columns=SPEC_ID_COLUMNS,
    )
    write_model_exhibit(
        estimates,
        ESTIMATE_OUTPUT,
        role="result",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="locked routing maturation, conditioned transition, exact-calendar dynamics, and support geometry",
    )
    write_model_exhibit(
        support,
        SUPPORT_OUTPUT,
        role="support",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="pre-fit routing-maturation support geometry bound to the same D3 release",
    )
    print(
        f"wrote {len(estimates):,} fitted specifications and "
        f"{len(combined) - len(estimates):,} support rows"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="routing-maturation estimator"):
        raise SystemExit(main())
