"""Material-pair sensitivity for the endpoint-period composition accounting."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import (
    BASELINE_YEAR,
    COMPARISON_YEAR,
    METRICS,
    _annual_pair_mass,
    _common_calendar_choices,
    _decompose_metric_scope,
)


@dataclass(frozen=True)
class MaterialitySpec:
    """One prespecified ordered-pair × endpoint-period activity floor."""

    spec_id: str
    metric: str
    source_column: str
    minimum_pair_period_mass: float
    threshold_unit: str


MATERIALITY_SPECS = (
    MaterialitySpec(
        spec_id="route_count_floor_5",
        metric="count_share",
        source_column="route_count",
        minimum_pair_period_mass=5.0,
        threshold_unit="routes",
    ),
    MaterialitySpec(
        spec_id="route_count_floor_10",
        metric="count_share",
        source_column="route_count",
        minimum_pair_period_mass=10.0,
        threshold_unit="routes",
    ),
    MaterialitySpec(
        spec_id="supported_value_floor_5000",
        metric="strict_intermediation_value_share",
        source_column="within_20pct_value_usd",
        minimum_pair_period_mass=5_000.0,
        threshold_unit="usd_supported_value",
    ),
    MaterialitySpec(
        spec_id="supported_value_floor_50000",
        metric="strict_intermediation_value_share",
        source_column="within_20pct_value_usd",
        minimum_pair_period_mass=50_000.0,
        threshold_unit="usd_supported_value",
    ),
)


def material_pair_composition(
    choices: pd.DataFrame,
    *,
    specs: tuple[MaterialitySpec, ...] = MATERIALITY_SPECS,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rerun pooled composition after an endpoint-period materiality floor.

    A pair-period remains in a specification when its pooled native-plus-stable
    denominator over the common calendar meets the floor. The filter is applied
    separately in each endpoint period, so a pair can become period-specific
    when it clears the floor in only one period. The original four-term identity
    is then evaluated without changing its definitions.
    """

    if not specs:
        raise ValueError("material-pair composition specs are empty")
    if len({spec.spec_id for spec in specs}) != len(specs):
        raise ValueError("material-pair composition spec IDs must be unique")

    data, common_month_days = _common_calendar_choices(
        choices,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    summaries: list[pd.DataFrame] = []
    support_frames: list[pd.DataFrame] = []
    for spec in specs:
        if spec.metric not in METRICS:
            raise ValueError(f"unknown material-pair metric: {spec.metric}")
        if METRICS[spec.metric] != spec.source_column:
            raise ValueError(
                f"material-pair {spec.spec_id} source column disagrees with metric"
            )
        if spec.minimum_pair_period_mass <= 0:
            raise ValueError(
                f"material-pair {spec.spec_id} requires a positive threshold"
            )

        annual = _annual_pair_mass(
            data,
            metric_column=spec.source_column,
            reporting_scope="pooled",
        )
        full = annual[annual["denominator"].gt(0)].copy()
        retained = full[
            full["denominator"].ge(spec.minimum_pair_period_mass)
        ].copy()
        retained_years = set(retained["year"].astype(int).unique())
        if retained_years != {baseline_year, comparison_year}:
            raise ValueError(
                f"material-pair {spec.spec_id} lacks retained mass in an endpoint period"
            )

        summary, support, _contributions = _decompose_metric_scope(
            retained,
            metric=spec.metric,
            metric_column=spec.source_column,
            reporting_scope="pooled",
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            common_month_days=common_month_days,
        )
        full_mass = full.groupby("year")["denominator"].sum()
        retained_mass = retained.groupby("year")["denominator"].sum()
        full_cells = full.groupby("year").size()
        retained_cells = retained.groupby("year").size()

        metadata = {
            "robustness_spec_id": spec.spec_id,
            "minimum_pair_period_mass": float(spec.minimum_pair_period_mass),
            "threshold_unit": spec.threshold_unit,
            "threshold_rule": "ordered_endpoint_pair_period_denominator_gte_threshold",
            "baseline_full_pair_periods": int(full_cells.loc[baseline_year]),
            "comparison_full_pair_periods": int(full_cells.loc[comparison_year]),
            "baseline_retained_pair_periods": int(retained_cells.loc[baseline_year]),
            "comparison_retained_pair_periods": int(
                retained_cells.loc[comparison_year]
            ),
            "baseline_mass_retained_share": float(
                retained_mass.loc[baseline_year] / full_mass.loc[baseline_year]
            ),
            "comparison_mass_retained_share": float(
                retained_mass.loc[comparison_year] / full_mass.loc[comparison_year]
            ),
            "value_support": (
                "source_intermediary_destination_values_within_20pct"
                if spec.threshold_unit == "usd_supported_value"
                else "all_reconstructed_native_or_stable_routes"
            ),
        }
        for column, value in metadata.items():
            summary[column] = value
            support[column] = value
        summary["spec_id"] = (
            "vehicle_transition_pair_materiality:" + spec.spec_id
        )
        summaries.append(summary)
        support_frames.append(support)

    decomposition = pd.concat(summaries, ignore_index=True, sort=False).sort_values(
        ["metric", "minimum_pair_period_mass"], kind="stable"
    ).reset_index(drop=True)
    support = pd.concat(support_frames, ignore_index=True, sort=False).sort_values(
        ["metric", "minimum_pair_period_mass", "support_status"], kind="stable"
    ).reset_index(drop=True)
    return decomposition, support
