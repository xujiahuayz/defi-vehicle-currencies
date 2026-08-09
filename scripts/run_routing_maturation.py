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
    support_geometry,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import require_current_artifacts
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit


CELL_DAY = DATA_DIR / "processed" / "routing_maturation_cell_day.parquet"
TRANSITION = DATA_DIR / "processed" / "routing_transition_cells.parquet"
EXACT_HORIZONS = DATA_DIR / "processed" / "routing_maturation_exact_horizons.parquet"
OUTPUT = OUTPUT_DIR / "exhibits" / "routing_maturation_results.jsonl"
LOCK = DATA_DIR / "processed" / ".routing_maturation_estimates.lock"
CODE_SOURCES = [
    "scripts/run_routing_maturation.py",
    "src/ddvc/analysis/routing_maturation.py",
    "src/ddvc/analysis/regression.py",
]


def maturation_results_after_support_gate(
    cell_day: pd.DataFrame,
) -> tuple[list[pd.DataFrame], bool]:
    """Return support only when the pre-fit E-to-D review gate is red."""

    support = support_geometry(cell_day)
    review_required = bool(
        support["support_exit_review_required"].astype(bool).any()
    )
    if review_required:
        return [support], True
    return [estimate_maturation(cell_day), support], False


def main() -> int:
    inputs = [CELL_DAY, TRANSITION, EXACT_HORIZONS]
    require_current_artifacts(inputs, consumer="routing-maturation estimator")
    cell_day = pd.read_parquet(CELL_DAY, columns=list(MATURATION_COLUMNS))
    results, review_required = maturation_results_after_support_gate(cell_day)
    del cell_day
    gc.collect()
    if review_required:
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
    transition = pd.read_parquet(TRANSITION, columns=list(TRANSITION_COLUMNS))
    results.append(estimate_transition(transition))
    del transition
    gc.collect()
    horizons = pd.read_parquet(EXACT_HORIZONS, columns=list(DYNAMIC_COLUMNS))
    results.append(estimate_dynamics(horizons))
    del horizons
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
