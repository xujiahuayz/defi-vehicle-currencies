"""Locked estimators for routing maturation, conditioned rotation, and persistence."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    ClusteredOLSResult,
    absorb_fixed_effects,
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    ols_clustered,
)


PRIMARY_YEARS = (2021, 2022, 2023, 2024, 2025)
REPRODUCTION_TOLERANCES_BPS = (1.0, 0.1, 0.01)
HORIZONS_DAYS = (1, 7, 30, 120)
MARGINS = (
    "within_reach_search_regret",
    "reach_increment",
    "path_choice_increment",
    "public_path_regret",
)
REGRET_BIN_COLUMNS = (
    "within_reach_regret_bin",
    "reach_increment_bin",
    "path_choice_increment_bin",
)
MATURATION_OUTCOME_COLUMNS = tuple(
    [
        f"{margin}_over_{threshold}_share"
        for margin in MARGINS
        for threshold in ("0p01", "1", "10")
    ]
    + [f"{margin}_mean_log1p_bps" for margin in MARGINS]
)
MATURATION_COLUMNS = (
    "date",
    "cell_id",
    "route_count",
    "reproduction_tolerance_bps",
    "recurrent_primary",
    "recurrent_strict",
    *MATURATION_OUTCOME_COLUMNS,
)
TRANSITION_COLUMNS = (
    "date",
    "stable_indicator",
    "route_count",
    "reproduction_tolerance_bps",
    "endpoint_pair_id",
    "opportunity_cell_id",
    *REGRET_BIN_COLUMNS,
)
DYNAMIC_OUTCOME_COLUMNS = tuple(
    name
    for margin in MARGINS
    for name in (
        f"current_{margin}_over_1_share",
        f"future_{margin}_over_1_share",
    )
)
DYNAMIC_COLUMNS = (
    "cell_id",
    "origin_date",
    "horizon_days",
    "target_observed",
    "reproduction_tolerance_bps",
    *DYNAMIC_OUTCOME_COLUMNS,
)


def _required(frame: pd.DataFrame, columns: Sequence[str], *, name: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name} lacks columns: {sorted(missing)}")


def _independent_columns(
    values: pd.DataFrame, *, required: set[str]
) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    rank = 0
    for column in values.columns:
        candidate = values[[*kept, column]].to_numpy(dtype=float)
        candidate_rank = int(np.linalg.matrix_rank(candidate))
        if candidate_rank > rank:
            kept.append(column)
            rank = candidate_rank
        elif column in required:
            raise ValueError(f"required regressor {column} is absorbed or collinear")
        else:
            dropped.append(column)
    return kept, dropped


def _fit_within(
    frame: pd.DataFrame,
    *,
    outcome: str,
    regressors: Sequence[str],
    fixed_effect: str,
    cluster_columns: tuple[str, str],
    weight_column: str | None = None,
    required_regressors: set[str] | None = None,
    retain_columns: Sequence[str] = (),
) -> tuple[ClusteredOLSResult, list[str], list[str], pd.DataFrame]:
    columns = [outcome, *regressors, fixed_effect, *cluster_columns, *retain_columns]
    if weight_column:
        columns.append(weight_column)
    model = frame.loc[:, list(dict.fromkeys(columns))].dropna().reset_index(drop=True)
    if model.empty:
        raise ValueError("routing estimator has no complete observations")
    weights = model[weight_column] if weight_column else None
    if weights is not None and (
        not np.isfinite(weights.to_numpy(dtype=float)).all() or (weights <= 0).any()
    ):
        raise ValueError("routing estimator weights must be finite and positive")
    group = model[fixed_effect]
    y_within = absorb_fixed_effects(model[outcome], group, weights=weights)
    x_within = absorb_fixed_effects(model[list(regressors)], group, weights=weights)
    required = required_regressors or set(regressors)
    kept, dropped = _independent_columns(x_within, required=required)
    fit = ols_clustered(
        y_within,
        x_within[kept],
        model[cluster_columns[0]],
        add_constant=False,
        absorbed_groups=(group,),
        additional_clusters=(model[cluster_columns[1]],),
        weights=weights,
    )
    if not np.isfinite(fit.beta).all():
        raise ValueError("routing estimator is unidentified after fixed-effect absorption")
    return fit, kept, dropped, model


def _joint_wald(
    fit: ClusteredOLSResult, names: Sequence[str], tested: Sequence[str]
) -> tuple[float, int, float]:
    positions = [names.index(name) for name in tested]
    restriction_beta = fit.beta[positions]
    restriction_covariance = fit.covariance[np.ix_(positions, positions)]
    rank = int(np.linalg.matrix_rank(restriction_covariance))
    if rank != len(positions):
        raise ValueError("joint year test has a rank-deficient covariance matrix")
    statistic = float(
        restriction_beta.T @ np.linalg.solve(restriction_covariance, restriction_beta)
        / rank
    )
    denominator_df = fit.n_clusters - 1
    p_value = float(stats.f.sf(statistic, rank, denominator_df))
    return statistic, rank, p_value


def _weighted_mean(values: pd.Series, weights: pd.Series | None) -> float:
    if weights is None:
        return float(values.mean())
    return float(np.average(values.to_numpy(dtype=float), weights=weights.to_numpy(dtype=float)))


def _annual_fit(
    frame: pd.DataFrame,
    *,
    margin: str,
    outcome: str,
    spec: str,
    weighting: str,
    tolerance_bps: float,
    support: str,
    years: tuple[int, ...],
    weight_column: str | None = None,
) -> dict[str, object]:
    sample = frame.copy()
    sample["year"] = pd.to_datetime(sample["date"]).dt.year
    sample = sample[sample["year"].isin(years)].reset_index(drop=True)
    if 2021 not in set(sample["year"]) or 2025 not in set(sample["year"]):
        raise ValueError(f"{spec} requires both 2021 and 2025")
    year_terms: list[str] = []
    for year in years:
        if year == 2021:
            continue
        term = f"year_{year}"
        sample[term] = sample["year"].eq(year).astype(float)
        year_terms.append(term)
    primary_year_terms = [f"year_{year}" for year in PRIMARY_YEARS if year != 2021]
    fit, kept, dropped, model = _fit_within(
        sample,
        outcome=outcome,
        regressors=year_terms,
        fixed_effect="cell_id",
        cluster_columns=("cell_id", "date"),
        weight_column=weight_column,
        required_regressors=set(primary_year_terms),
        retain_columns=("year", "route_count"),
    )
    statistics = fit.named_statistics(kept)
    tested = [term for term in primary_year_terms if term in kept]
    if len(tested) != len(primary_year_terms):
        raise ValueError(f"{spec} does not identify all four primary year indicators")
    joint_statistic, joint_df, joint_p = _joint_wald(fit, kept, tested)
    model_weights = model[weight_column] if weight_column else None
    baseline = model[model["year"].eq(2021)]
    comparison = model[model["year"].eq(2025)]
    baseline_weights = baseline[weight_column] if weight_column else None
    comparison_weights = comparison[weight_column] if weight_column else None
    return {
        "record_type": "estimate",
        "family": "maturation",
        "spec": spec,
        "margin": margin,
        "outcome": outcome,
        "weighting": weighting,
        "support": support,
        "reproduction_tolerance_bps": tolerance_bps,
        "n_observations": fit.n_observations,
        "n_cells": int(model["cell_id"].nunique()),
        "n_dates": int(model["date"].nunique()),
        "route_count": int(model["route_count"].sum()),
        "cell_clusters": fit.cluster_counts[0],
        "date_clusters": fit.cluster_counts[1],
        "baseline_2021_mean": _weighted_mean(baseline[outcome], baseline_weights),
        "comparison_2025_mean": _weighted_mean(comparison[outcome], comparison_weights),
        "comparison_2025_beta": statistics["year_2025_beta"],
        "comparison_2025_se": statistics["year_2025_se"],
        "comparison_2025_t": statistics["year_2025_t"],
        "comparison_2025_p": statistics["year_2025_p"],
        "joint_year_f": joint_statistic,
        "joint_year_numerator_df": joint_df,
        "joint_year_denominator_df": fit.n_clusters - 1,
        "joint_year_p": joint_p,
        "dropped_collinear_controls": "|".join(dropped),
    }


def _linear_fit(frame: pd.DataFrame, *, margin: str, outcome: str) -> dict[str, object]:
    sample = frame.copy()
    sample["year"] = pd.to_datetime(sample["date"]).dt.year
    sample = sample[sample["year"].isin(PRIMARY_YEARS)].reset_index(drop=True)
    sample["elapsed_year"] = sample["year"] - PRIMARY_YEARS[0]
    fit, kept, dropped, model = _fit_within(
        sample,
        outcome=outcome,
        regressors=["elapsed_year"],
        fixed_effect="cell_id",
        cluster_columns=("cell_id", "date"),
        retain_columns=("route_count",),
    )
    statistics = fit.named_statistics(kept)
    return {
        "record_type": "estimate",
        "family": "maturation",
        "spec": "linear_elapsed_year_sensitivity",
        "margin": margin,
        "outcome": outcome,
        "weighting": "equal_cell_day",
        "support": "recurrent_primary",
        "reproduction_tolerance_bps": 1.0,
        "n_observations": fit.n_observations,
        "n_cells": int(model["cell_id"].nunique()),
        "n_dates": int(model["date"].nunique()),
        "route_count": int(model["route_count"].sum()),
        "cell_clusters": fit.cluster_counts[0],
        "date_clusters": fit.cluster_counts[1],
        "linear_year_beta": statistics["elapsed_year_beta"],
        "linear_year_se": statistics["elapsed_year_se"],
        "linear_year_t": statistics["elapsed_year_t"],
        "linear_year_p": statistics["elapsed_year_p"],
        "dropped_collinear_controls": "|".join(dropped),
    }


def estimate_maturation(frame: pd.DataFrame) -> pd.DataFrame:
    _required(frame, MATURATION_COLUMNS, name="routing maturation panel")
    rows: list[dict[str, object]] = []
    for margin in MARGINS:
        primary_outcome = f"{margin}_over_1_share"
        specifications = (
            ("primary_annual_profile", 1.0, "recurrent_primary", primary_outcome, "equal_cell_day", None),
            ("route_weighted_sensitivity", 1.0, "recurrent_primary", primary_outcome, "route_weighted_cell_day", "route_count"),
            ("log1p_mean_sensitivity", 1.0, "recurrent_primary", f"{margin}_mean_log1p_bps", "equal_cell_day", None),
            ("strict_recurrence_sensitivity", 1.0, "recurrent_strict", primary_outcome, "equal_cell_day", None),
            ("reproduction_0p1_sensitivity", 0.1, "recurrent_primary", primary_outcome, "equal_cell_day", None),
            ("reproduction_0p01_sensitivity", 0.01, "recurrent_primary", primary_outcome, "equal_cell_day", None),
            ("threshold_0p01_sensitivity", 1.0, "recurrent_primary", f"{margin}_over_0p01_share", "equal_cell_day", None),
            ("threshold_10_sensitivity", 1.0, "recurrent_primary", f"{margin}_over_10_share", "equal_cell_day", None),
            ("all_released_dates_lifecycle", 1.0, "all", primary_outcome, "equal_cell_day", None),
        )
        for spec, tolerance, support, outcome, weighting, weight_column in specifications:
            selected = frame["reproduction_tolerance_bps"].eq(tolerance)
            if support != "all":
                selected &= frame[support].astype(bool)
            sample = frame.loc[
                selected,
                ["date", "cell_id", "route_count", outcome],
            ].copy()
            years = (
                tuple(sorted(pd.to_datetime(sample["date"]).dt.year.unique()))
                if support == "all"
                else PRIMARY_YEARS
            )
            rows.append(
                _annual_fit(
                    sample,
                    margin=margin,
                    outcome=outcome,
                    spec=spec,
                    weighting=weighting,
                    tolerance_bps=tolerance,
                    support=support,
                    years=years,
                    weight_column=weight_column,
                )
            )
        primary = frame.loc[
            frame["reproduction_tolerance_bps"].eq(1.0)
            & frame["recurrent_primary"].astype(bool),
            ["date", "cell_id", "route_count", primary_outcome],
        ].copy()
        rows.append(_linear_fit(primary, margin=margin, outcome=primary_outcome))
    result = pd.DataFrame(rows)
    primary = result["spec"].eq("primary_annual_profile")
    result.loc[primary, "comparison_2025_holm_p"] = holm_adjusted_pvalues(
        result.loc[primary, "comparison_2025_p"]
    )
    return result


def estimate_transition(frame: pd.DataFrame) -> pd.DataFrame:
    _required(frame, TRANSITION_COLUMNS, name="routing transition panel")
    sample = frame.loc[
        frame["reproduction_tolerance_bps"].eq(1.0), TRANSITION_COLUMNS
    ].copy()
    sample["date"] = pd.to_datetime(sample["date"])
    sample["year"] = sample["date"].dt.year
    sample = sample[sample["year"].isin((2024, 2026))].copy()
    sample = sample[
        common_calendar_day_mask(
            sample["date"], sample["year"], baseline_year=2024, comparison_year=2026
        )
    ].reset_index(drop=True)
    sample["comparison_year_2026"] = sample["year"].eq(2026).astype(float)
    controls: list[str] = []
    for column in REGRET_BIN_COLUMNS:
        dummies = pd.get_dummies(sample[column], prefix=column, drop_first=True, dtype=float)
        sample[dummies.columns] = dummies
        controls.extend(dummies.columns.tolist())
    sample["route_weight"] = sample["route_count"].astype(float)
    date_routes = sample.groupby("date", observed=True)["route_count"].transform("sum")
    sample["equal_date_weight"] = sample["route_count"] / date_routes
    rows: list[dict[str, object]] = []
    for spec, weighting, weight_column in (
        ("route_weighted_primary", "route_weighted", "route_weight"),
        ("equal_date_sensitivity", "equal_date", "equal_date_weight"),
    ):
        regressors = ["comparison_year_2026", *controls]
        fit, kept, dropped, model = _fit_within(
            sample,
            outcome="stable_indicator",
            regressors=regressors,
            fixed_effect="opportunity_cell_id",
            cluster_columns=("endpoint_pair_id", "date"),
            weight_column=weight_column,
            required_regressors={"comparison_year_2026"},
            retain_columns=("year", "route_count"),
        )
        statistics = fit.named_statistics(kept)
        baseline = model[model["year"].eq(2024)]
        comparison = model[model["year"].eq(2026)]
        rows.append(
            {
                "record_type": "estimate",
                "family": "conditioned_transition",
                "spec": spec,
                "outcome": "stable_indicator",
                "weighting": weighting,
                "support": "common_month_day_2024_2026",
                "reproduction_tolerance_bps": 1.0,
                "n_observations": fit.n_observations,
                "n_cells": int(model["opportunity_cell_id"].nunique()),
                "n_dates": int(model["date"].nunique()),
                "route_count": int(model["route_count"].sum()),
                "pair_clusters": fit.cluster_counts[0],
                "date_clusters": fit.cluster_counts[1],
                "common_month_days": int(model["date"].dt.strftime("%m-%d").nunique()),
                "baseline_2024_mean": _weighted_mean(baseline["stable_indicator"], baseline[weight_column]),
                "comparison_2026_mean": _weighted_mean(comparison["stable_indicator"], comparison[weight_column]),
                "comparison_2026_beta": statistics["comparison_year_2026_beta"],
                "comparison_2026_se": statistics["comparison_year_2026_se"],
                "comparison_2026_t": statistics["comparison_year_2026_t"],
                "comparison_2026_p": statistics["comparison_year_2026_p"],
                "regret_control_count": len(kept) - 1,
                "dropped_collinear_controls": "|".join(dropped),
            }
        )
    return pd.DataFrame(rows)


def estimate_dynamics(frame: pd.DataFrame) -> pd.DataFrame:
    _required(frame, DYNAMIC_COLUMNS, name="routing exact-horizon panel")
    sample = frame.loc[
        frame["reproduction_tolerance_bps"].eq(1.0), DYNAMIC_COLUMNS
    ].copy()
    sample["origin_date"] = pd.to_datetime(sample["origin_date"])
    sample["origin_year"] = sample["origin_date"].dt.year
    sample = sample[sample["origin_year"].isin(PRIMARY_YEARS)].copy()
    rows: list[dict[str, object]] = []
    for horizon in HORIZONS_DAYS:
        horizon_sample = sample[sample["horizon_days"].eq(horizon)].copy()
        total_links = len(horizon_sample)
        observed = horizon_sample[horizon_sample["target_observed"].astype(bool)].reset_index(drop=True)
        for year in PRIMARY_YEARS[1:]:
            observed[f"origin_year_{year}"] = observed["origin_year"].eq(year).astype(float)
        year_terms = [f"origin_year_{year}" for year in PRIMARY_YEARS[1:]]
        for margin in MARGINS:
            current = f"current_{margin}_over_1_share"
            future = f"future_{margin}_over_1_share"
            fit, kept, dropped, model = _fit_within(
                observed,
                outcome=future,
                regressors=[current, *year_terms],
                fixed_effect="cell_id",
                cluster_columns=("cell_id", "origin_date"),
                required_regressors={current},
            )
            statistics = fit.named_statistics(kept)
            rows.append(
                {
                    "record_type": "estimate",
                    "family": "exact_horizon_dynamics",
                    "spec": "descriptive_persistence",
                    "margin": margin,
                    "outcome": future,
                    "weighting": "equal_cell_day",
                    "support": "recurrent_primary_exact_target",
                    "reproduction_tolerance_bps": 1.0,
                    "horizon_days": horizon,
                    "n_observations": fit.n_observations,
                    "n_links_total": total_links,
                    "link_coverage": fit.n_observations / total_links if total_links else np.nan,
                    "n_cells": int(model["cell_id"].nunique()),
                    "n_dates": int(model["origin_date"].nunique()),
                    "cell_clusters": fit.cluster_counts[0],
                    "date_clusters": fit.cluster_counts[1],
                    "current_share_beta": statistics[f"{current}_beta"],
                    "current_share_se": statistics[f"{current}_se"],
                    "current_share_t": statistics[f"{current}_t"],
                    "current_share_p": statistics[f"{current}_p"],
                    "dropped_collinear_controls": "|".join(dropped),
                }
            )
    return pd.DataFrame(rows)


def support_geometry(frame: pd.DataFrame) -> pd.DataFrame:
    _required(
        frame,
        [
            "date",
            "cell_id",
            "route_count",
            "reproduction_tolerance_bps",
            "recurrent_primary",
            "recurrent_strict",
        ],
        name="routing maturation panel",
    )
    data = frame[
        [
            "date",
            "cell_id",
            "route_count",
            "reproduction_tolerance_bps",
            "recurrent_primary",
            "recurrent_strict",
        ]
    ].copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    rows: list[dict[str, object]] = []
    for tolerance in REPRODUCTION_TOLERANCES_BPS:
        for support in ("recurrent_primary", "recurrent_strict"):
            selected = data[
                data["reproduction_tolerance_bps"].eq(tolerance)
                & data[support].astype(bool)
                & data["year"].isin(PRIMARY_YEARS)
            ]
            annual = selected.groupby("year", observed=True).agg(
                cell_days=("cell_id", "size"),
                cells=("cell_id", "nunique"),
                dates=("date", "nunique"),
                routes=("route_count", "sum"),
            )
            if set(annual.index) != set(PRIMARY_YEARS):
                raise ValueError(f"{support} at {tolerance} bps lacks a full primary year")
            cell_day_ratio = float(annual["cell_days"].min() / annual["cell_days"].max())
            route_ratio = float(annual["routes"].min() / annual["routes"].max())
            review = cell_day_ratio < 0.5 or route_ratio < 0.5
            for year, values in annual.iterrows():
                rows.append(
                    {
                        "record_type": "support",
                        "family": "maturation_support",
                        "spec": support,
                        "support": support,
                        "reproduction_tolerance_bps": tolerance,
                        "year": int(year),
                        "cell_days": int(values["cell_days"]),
                        "n_cells": int(values["cells"]),
                        "n_dates": int(values["dates"]),
                        "route_count": int(values["routes"]),
                        "minimum_to_maximum_cell_day_ratio": cell_day_ratio,
                        "minimum_to_maximum_route_ratio": route_ratio,
                        "support_exit_review_required": review,
                    }
                )
    return pd.DataFrame(rows)
