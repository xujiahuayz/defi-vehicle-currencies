#!/usr/bin/env python3
"""Run one D3-bound vehicle-transition smoke component, not the complete E0 family."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    require_released_model_inputs,
    write_model_exhibit,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from scripts.build_intermediation_by_type import (
    HAC_LAG,
    VEHICLE_TRANSITION_ESTIMANDS,
    VEHICLE_TRANSITION_SCOPES,
    VEHICLE_TRANSITION_SPECIFICATIONS,
    vehicle_transition_support_geometry,
    vehicle_transition_tests,
)


INTERMEDIATION = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
ESTIMATE_OUTPUT = OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_smoke_estimates.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_smoke_support.jsonl"
CODE_SOURCES = [
    "scripts/run_vehicle_transition_e0.py",
    "scripts/build_intermediation_by_type.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
]
SPEC_ID_COLUMNS = (
    "routing_scope",
    "weighting",
    "value_support",
    "transformation",
    "baseline_year",
    "comparison_year",
    "hac_lag_days",
)
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
MINIMUM_ENDPOINT_DAYS = HAC_LAG + 1
COMPONENT_STATUS = "smoke_only_incomplete_family"
COMPONENT_FAMILY = "vehicle_transition_smoke_component"


def expected_spec_ids() -> list[str]:
    """Return the exact fitted perimeter for the later executable E0 plan."""

    rows = [
        {
            "routing_scope": scope,
            "weighting": weighting,
            "value_support": value_support,
            "transformation": transformation,
            "baseline_year": BASELINE_YEAR,
            "comparison_year": COMPARISON_YEAR,
            "hac_lag_days": HAC_LAG,
        }
        for scope in VEHICLE_TRANSITION_SCOPES
        for weighting, value_support, _column_prefix in VEHICLE_TRANSITION_ESTIMANDS
        for transformation in ("share_level", "log_odds")
    ]
    identified = attach_spec_ids(
        pd.DataFrame(rows),
        prefix="vehicle_transition_e0_smoke",
        columns=SPEC_ID_COLUMNS,
    )
    return sorted(identified["spec_id"].tolist())


def run_vehicle_transition(
    *,
    root: Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
    intermediation_path: Path = INTERMEDIATION,
    estimate_output: Path = ESTIMATE_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    minimum_endpoint_days: int = MINIMUM_ENDPOINT_DAYS,
) -> int:
    """Write green support then fitted output, or only red support and exit two."""

    context = model_artifact_context(root=root, environment=environment)
    inputs = require_released_model_inputs(
        context,
        [intermediation_path],
        root=root,
        consumer="E0 vehicle-transition runner",
    )
    intermediation = pd.read_parquet(intermediation_path)
    support = vehicle_transition_support_geometry(
        intermediation,
        baseline_year=BASELINE_YEAR,
        comparison_year=COMPARISON_YEAR,
        minimum_endpoint_days=minimum_endpoint_days,
    )
    support["family"] = COMPONENT_FAMILY
    write_model_exhibit(
        support,
        support_output,
        role="support",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="incomplete E0 smoke component: pre-fit support for the exact intermediation contrasts only",
    )
    if bool(support["support_exit_review_required"].astype(bool).any()):
        return 2
    estimates = vehicle_transition_tests(
        intermediation,
        baseline_year=BASELINE_YEAR,
        comparison_year=COMPARISON_YEAR,
        hac_lag=HAC_LAG,
    )
    required_finite = ["change", "hac_standard_error", "t_statistic", "p_value", "p_value_holm"]
    numeric = estimates[required_finite].apply(pd.to_numeric, errors="coerce")
    if len(estimates) != VEHICLE_TRANSITION_SPECIFICATIONS or not np.isfinite(numeric).all().all():
        raise ValueError("vehicle-transition fitted perimeter is incomplete or nonfinite")
    estimates.insert(0, "family", COMPONENT_FAMILY)
    estimates = attach_spec_ids(
        estimates,
        prefix="vehicle_transition_e0_smoke",
        columns=SPEC_ID_COLUMNS,
    )
    if sorted(estimates["spec_id"].tolist()) != expected_spec_ids():
        raise ValueError("vehicle-transition fitted spec_ids differ from the declared perimeter")
    write_model_exhibit(
        estimates,
        estimate_output,
        role="result",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="incomplete E0 smoke component: native-to-stable share changes on exact two-leg routing strata with daily HAC inference",
    )
    return 0


def main() -> int:
    return run_vehicle_transition()


if __name__ == "__main__":
    raise SystemExit(main())
