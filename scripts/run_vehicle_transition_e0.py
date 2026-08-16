#!/usr/bin/env python3
"""Run the D3-bound vehicle-transition E0 components, still short of the full family.

Three components live here. The pooled component estimates the family's declared
share change on the type-level intermediation panel. The dated-backing component
answers the family's `dated_backing_regimes` attack: it re-cuts the same estimand
by the dated regime of the stable candidate actually intermediating the route, so
a rotation into `stable` cannot be read as one instrument without evidence, and a
candidate whose label moved cannot masquerade as a change in use. The
fixed-opportunity component answers the `fixed_opportunity_conditioning` attack in
the half the released panel can carry: it re-estimates the same share on cohorts
of endpoint pairs, pair-candidate cells and pair-venue cells that are active in
both endpoint years, so that a rotation cannot be read as a change in choice when
it is a change in which units exist. The dimensions that attack also asks for —
reach, notional and search regret — need the unreleased transaction-state
frontier, and the component publishes each of them as an unsupported dimension
with its blocker instead of leaving the gap to be inferred.

The components are deliberately not merged. They read different released objects —
the type-level daily panel and the endpoint-candidate choice release — and
therefore different route universes, so each choice-panel component publishes its
own pooled row and a reconciliation against the pooled component instead of
implying that its terms decompose the headline exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.vehicle_backing_regimes import (
    ESTIMAND_MASS_COLUMNS,
    SCOPE_FILTERS,
    additivity_failures,
    assert_additive_decomposition,
    backing_regime_daily_shares,
    backing_regime_support,
    backing_regime_tests,
    regime_change_ledger,
    universe_reconciliation,
)
from ddvc.analysis.vehicle_fixed_opportunity import (
    ATTACK_ID as FIXED_OPPORTUNITY_ATTACK_ID,
)
from ddvc.analysis.vehicle_fixed_opportunity import (
    assert_cohort_additivity,
    cohort_additivity_failures,
    cohort_cell_ledger,
    cohort_mass_ledger,
    fixed_opportunity_daily_shares,
    fixed_opportunity_support,
    fixed_opportunity_tests,
    unsupported_dimension_ledger,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    current_endpoint_candidate_composition_release,
)
from ddvc.model_artifacts import (
    attach_spec_ids,
    expected_release_receipt_in_d3,
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
BACKING_ESTIMATE_OUTPUT = (
    OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_backing_regime_estimates.jsonl"
)
BACKING_SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_backing_regime_support.jsonl"
)
FIXED_OPPORTUNITY_ESTIMATE_OUTPUT = (
    OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_fixed_opportunity_estimates.jsonl"
)
FIXED_OPPORTUNITY_SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits" / "e0_vehicle_transition_fixed_opportunity_support.jsonl"
)
CODE_SOURCES = [
    "scripts/run_vehicle_transition_e0.py",
    "scripts/build_intermediation_by_type.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
]
BACKING_CODE_SOURCES = [
    *CODE_SOURCES,
    "src/ddvc/analysis/vehicle_backing_regimes.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/endpoint_candidate_composition_release.py",
]
FIXED_OPPORTUNITY_CODE_SOURCES = [
    *CODE_SOURCES,
    "src/ddvc/analysis/vehicle_backing_regimes.py",
    "src/ddvc/analysis/vehicle_fixed_opportunity.py",
    "src/ddvc/endpoint_candidate_composition_release.py",
]
FIXED_OPPORTUNITY_SPEC_ID_COLUMNS = (
    "routing_scope",
    "cohort",
    "stratum_role",
    "weighting",
    "value_support",
    "transformation",
    "baseline_year",
    "comparison_year",
    "hac_lag_days",
)
FIXED_OPPORTUNITY_COMPONENT_FAMILY = "vehicle_transition_fixed_opportunity_component"
BACKING_SPEC_ID_COLUMNS = (
    "routing_scope",
    "backing_regime",
    "weighting",
    "value_support",
    "transformation",
    "baseline_year",
    "comparison_year",
    "hac_lag_days",
)
BACKING_COMPONENT_FAMILY = "vehicle_transition_dated_backing_component"
BACKING_ATTACK_ID = "dated_backing_regimes"
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
# The `vehicle_transition_e0` attacks this runner now produces fitted or support
# evidence for. It is not the family's full perimeter and must never be written
# into an exploration plan as if it were: `fixed_opportunity_conditioning` is
# covered only in its fixed-cohort half, with reach, notional and search regret
# published as unsupported dimensions until the transaction-state frontier lands,
# and `within_pair_composition_decomposition` is produced by
# `scripts/run_vehicle_rotation_composition_e0.py`, not here.
COMPONENT_ATTACK_COVERAGE = (
    "dominance_measure_triangulation",
    "routing_strata_separation",
    "support_uncertainty_ledger",
    BACKING_ATTACK_ID,
    FIXED_OPPORTUNITY_ATTACK_ID,
)

if tuple(SCOPE_FILTERS) != VEHICLE_TRANSITION_SCOPES:
    raise RuntimeError("dated-backing strata differ from the transition routing perimeter")
if tuple(ESTIMAND_MASS_COLUMNS) != tuple(
    (weighting, value_support) for weighting, value_support, _prefix in VEHICLE_TRANSITION_ESTIMANDS
):
    raise RuntimeError("dated-backing estimands differ from the transition estimand perimeter")


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
    with require_released_model_inputs(
        context,
        [intermediation_path],
        root=root,
        consumer="E0 vehicle-transition runner",
    ) as inputs:
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


def run_dated_backing_regimes(
    *,
    root: Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
    intermediation_path: Path = INTERMEDIATION,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    estimate_output: Path = BACKING_ESTIMATE_OUTPUT,
    support_output: Path = BACKING_SUPPORT_OUTPUT,
    minimum_endpoint_days: int = MINIMUM_ENDPOINT_DAYS,
) -> int:
    """Write the dated-backing-regime attack evidence for the transition family.

    Support is written before anything is fitted, and it is written whatever the
    result: a regime too thin for the declared HAC horizon is a published support
    row with its reason, not a silently dropped specification. The run then refuses
    to publish estimates unless the fitted regime changes reproduce the pooled
    change on the same universe, which is the arithmetic the cut promises.
    """

    context = model_artifact_context(root=root, environment=environment)
    expected_receipt = expected_release_receipt_in_d3(context, pointer_path, root=root)
    with require_released_model_inputs(
        context,
        [intermediation_path],
        root=root,
        consumer="E0 vehicle-transition dated-backing component",
    ) as pooled_inputs:
        intermediation = pd.read_parquet(intermediation_path)
        pooled = vehicle_transition_tests(
            intermediation,
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
            hac_lag=HAC_LAG,
        )
        with current_endpoint_candidate_composition_release(
            pointer_path,
            expected_semantic_receipt=expected_receipt,
        ) as release:
            if release.generation_id != expected_receipt.generation_id:
                raise ValueError("endpoint release differs from the D3-bound generation")
            choices = pd.read_parquet(release.artifacts["choices"])
            daily = backing_regime_daily_shares(
                choices,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
            )
            support = backing_regime_support(
                daily,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                minimum_endpoint_days=minimum_endpoint_days,
            )
            ledger = regime_change_ledger(
                choices,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
            )
            estimates = backing_regime_tests(
                daily,
                support,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                hac_lag=HAC_LAG,
            )
            additivity = assert_additive_decomposition(estimates, support, strict=False)
            reconciliation = universe_reconciliation(estimates, pooled)
            support_records = pd.concat(
                [support, ledger, additivity, reconciliation],
                ignore_index=True,
                sort=False,
            )
            support_records.insert(0, "family", BACKING_COMPONENT_FAMILY)
            support_records.insert(1, "attack_id", BACKING_ATTACK_ID)
            release_inputs = list(release.bundle.lineage_paths)
            write_model_exhibit(
                support_records,
                support_output,
                role="support",
                context=context,
                code_sources=BACKING_CODE_SOURCES,
                inputs=[*pooled_inputs, *release_inputs],
                notes=(
                    "incomplete E0 family component: dated-backing support, regime-label "
                    "change ledger, share-level additivity check, and the pooled "
                    "choice-universe versus type-panel reconciliation"
                ),
            )
            broken = additivity_failures(additivity)
            if not broken.empty:
                raise ValueError(
                    "dated-backing regime changes do not sum to the pooled change: "
                    f"{broken['routing_scope'].tolist()}"
                )
            required_finite = ["change", "hac_standard_error", "t_statistic", "p_value"]
            numeric = estimates[required_finite].apply(pd.to_numeric, errors="coerce")
            if not np.isfinite(numeric).all().all():
                raise ValueError("dated-backing fitted perimeter is nonfinite")
            estimates.insert(0, "family", BACKING_COMPONENT_FAMILY)
            estimates.insert(1, "attack_id", BACKING_ATTACK_ID)
            estimates = attach_spec_ids(
                estimates,
                prefix="vehicle_transition_e0_dated_backing",
                columns=BACKING_SPEC_ID_COLUMNS,
            )
            if sorted(estimates["spec_id"].tolist()) != sorted(
                set(estimates["spec_id"].tolist())
            ):
                raise ValueError("dated-backing fitted spec_ids are not unique")
            write_model_exhibit(
                estimates,
                estimate_output,
                role="result",
                context=context,
                code_sources=BACKING_CODE_SOURCES,
                inputs=[*pooled_inputs, *release_inputs],
                notes=(
                    "incomplete E0 family component: 2024-to-2026 change in each dated "
                    "backing regime's share of the stable-plus-native intermediation "
                    "denominator on exact two-leg routing strata, with daily HAC "
                    "inference and Holm control across the simultaneous regime tests"
                ),
            )
            release.bundle.assert_current()
    fitted = int(len(estimates))
    gated = int((~support["fit_supported"].astype(bool)).sum())
    moved = int(ledger["label_moves_in_window"].astype(bool).sum())
    print(
        f"fitted {fitted} dated-backing specifications, gated {gated} on support, "
        f"{moved} candidate-regime rows with a label move inside the contrast window"
    )
    return 0


def run_fixed_opportunity_conditioning(
    *,
    root: Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
    intermediation_path: Path = INTERMEDIATION,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    estimate_output: Path = FIXED_OPPORTUNITY_ESTIMATE_OUTPUT,
    support_output: Path = FIXED_OPPORTUNITY_SUPPORT_OUTPUT,
    minimum_endpoint_days: int = MINIMUM_ENDPOINT_DAYS,
) -> int:
    """Write the fixed-cohort attack evidence for the transition family.

    Support is written before anything is fitted and whatever the result, so the
    cohort's retained mass, the cells it keeps, and the three dimensions the
    released panel cannot carry are all on the record before a coefficient is.
    The run then refuses to publish estimates unless each cohort's in- and
    out-of-cohort contributions reproduce the pooled change on the same days,
    which is the arithmetic the conditioning promises.
    """

    context = model_artifact_context(root=root, environment=environment)
    expected_receipt = expected_release_receipt_in_d3(context, pointer_path, root=root)
    with require_released_model_inputs(
        context,
        [intermediation_path],
        root=root,
        consumer="E0 vehicle-transition fixed-opportunity component",
    ) as pooled_inputs:
        intermediation = pd.read_parquet(intermediation_path)
        pooled = vehicle_transition_tests(
            intermediation,
            baseline_year=BASELINE_YEAR,
            comparison_year=COMPARISON_YEAR,
            hac_lag=HAC_LAG,
        )
        with current_endpoint_candidate_composition_release(
            pointer_path,
            expected_semantic_receipt=expected_receipt,
        ) as release:
            if release.generation_id != expected_receipt.generation_id:
                raise ValueError("endpoint release differs from the D3-bound generation")
            choices = pd.read_parquet(release.artifacts["choices"])
            daily = fixed_opportunity_daily_shares(
                choices,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
            )
            support = fixed_opportunity_support(
                daily,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                minimum_endpoint_days=minimum_endpoint_days,
            )
            estimates = fixed_opportunity_tests(
                daily,
                support,
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                hac_lag=HAC_LAG,
            )
            additivity = assert_cohort_additivity(estimates, strict=False)
            support_records = pd.concat(
                [
                    support,
                    cohort_cell_ledger(
                        choices,
                        baseline_year=BASELINE_YEAR,
                        comparison_year=COMPARISON_YEAR,
                    ),
                    cohort_mass_ledger(
                        daily,
                        baseline_year=BASELINE_YEAR,
                        comparison_year=COMPARISON_YEAR,
                    ),
                    unsupported_dimension_ledger(),
                    additivity,
                    universe_reconciliation(estimates, pooled),
                ],
                ignore_index=True,
                sort=False,
            )
            support_records.insert(0, "family", FIXED_OPPORTUNITY_COMPONENT_FAMILY)
            support_records.insert(1, "attack_id", FIXED_OPPORTUNITY_ATTACK_ID)
            release_inputs = list(release.bundle.lineage_paths)
            write_model_exhibit(
                support_records,
                support_output,
                role="support",
                context=context,
                code_sources=FIXED_OPPORTUNITY_CODE_SOURCES,
                inputs=[*pooled_inputs, *release_inputs],
                notes=(
                    "incomplete E0 family component: cohort day support, persistent-cell "
                    "and retained-mass ledgers, the reach, notional and search-regret "
                    "dimensions this attack cannot fit from the released panel, the "
                    "contribution additivity check, and the pooled choice-universe "
                    "versus type-panel reconciliation"
                ),
            )
            broken = cohort_additivity_failures(additivity)
            if not broken.empty:
                raise ValueError(
                    "cohort contributions do not sum to the pooled change: "
                    f"{broken['cohort'].tolist()}"
                )
            required_finite = ["change", "hac_standard_error", "t_statistic", "p_value"]
            numeric = estimates[required_finite].apply(pd.to_numeric, errors="coerce")
            if not np.isfinite(numeric).all().all():
                raise ValueError("fixed-opportunity fitted perimeter is nonfinite")
            estimates.insert(0, "family", FIXED_OPPORTUNITY_COMPONENT_FAMILY)
            estimates.insert(1, "attack_id", FIXED_OPPORTUNITY_ATTACK_ID)
            estimates = attach_spec_ids(
                estimates,
                prefix="vehicle_transition_e0_fixed_opportunity",
                columns=FIXED_OPPORTUNITY_SPEC_ID_COLUMNS,
            )
            if sorted(estimates["spec_id"].tolist()) != sorted(
                set(estimates["spec_id"].tolist())
            ):
                raise ValueError("fixed-opportunity fitted spec_ids are not unique")
            write_model_exhibit(
                estimates,
                estimate_output,
                role="result",
                context=context,
                code_sources=FIXED_OPPORTUNITY_CODE_SOURCES,
                inputs=[*pooled_inputs, *release_inputs],
                notes=(
                    "incomplete E0 family component: 2024-to-2026 change in the stable "
                    "share of the stable-plus-native intermediation denominator on exact "
                    "two-leg routing strata, estimated on cohorts of endpoint pairs, "
                    "pair-candidate cells and pair-venue cells active in both endpoint "
                    "years, with daily HAC inference and Holm control across the "
                    "simultaneous conditional tests"
                ),
            )
            release.bundle.assert_current()
    fitted = int(len(estimates))
    gated = int((~support["fit_supported"].astype(bool)).sum())
    unsupported = int(len(unsupported_dimension_ledger()))
    print(
        f"fitted {fitted} fixed-opportunity specifications, gated {gated} on support, "
        f"{unsupported} attack dimensions published as unsupported"
    )
    return 0


def main() -> int:
    status = run_vehicle_transition()
    if status != 0:
        return status
    status = run_dated_backing_regimes()
    if status != 0:
        return status
    return run_fixed_opportunity_conditioning()


if __name__ == "__main__":
    raise SystemExit(main())
