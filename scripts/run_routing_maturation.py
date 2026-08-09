#!/usr/bin/env python3
"""Run the locked routing-maturation estimators on current D3 panels.

Reads
  data/processed/routing_maturation_cell_day.parquet
  data/processed/routing_transition_cells.parquet
  data/processed/routing_maturation_exact_horizons.parquet

Writes
  output/exhibits/routing_maturation_results.jsonl
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
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import require_current_artifacts
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit


CELL_DAY = DATA_DIR / "processed" / "routing_maturation_cell_day.parquet"
TRANSITION = DATA_DIR / "processed" / "routing_transition_cells.parquet"
EXACT_HORIZONS = DATA_DIR / "processed" / "routing_maturation_exact_horizons.parquet"
FRONTIER_SUPPORT = DATA_DIR / "processed" / "transaction_state_frontier_daily_support.parquet"
OUTPUT = OUTPUT_DIR / "exhibits" / "routing_maturation_results.jsonl"
LOCK = DATA_DIR / "processed" / ".routing_maturation_estimates.lock"
CODE_SOURCES = [
    "scripts/run_routing_maturation.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/analysis/routing_contract.py",
    "src/ddvc/analysis/routing_maturation.py",
    "src/ddvc/analysis/regression.py",
]


def support_review_required(support_frames: list[pd.DataFrame]) -> bool:
    """Collapse already-computed support ledgers without fitting a model."""

    return any(
        bool(frame["support_exit_review_required"].astype(bool).any())
        for frame in support_frames
    )


def main() -> int:
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
    review_required = support_review_required(results)
    if review_required:
        del horizons
        gc.collect()
        combined = pd.concat(results, ignore_index=True, sort=False)
        write_exhibit(
            combined,
            OUTPUT,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=(
                "routing maturation support geometry only; E-to-D review required; "
                "no fitted specifications"
            ),
        )
        print(
            "BLOCKED: routing-maturation support exit requires E-to-D review; "
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
    write_exhibit(
        combined,
        OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="locked routing maturation, conditioned transition, exact-calendar dynamics, and support geometry",
    )
    estimates = combined[combined["record_type"].eq("estimate")]
    print(
        f"wrote {len(estimates):,} fitted specifications and "
        f"{len(combined) - len(estimates):,} support rows"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="routing-maturation estimator"):
        raise SystemExit(main())
