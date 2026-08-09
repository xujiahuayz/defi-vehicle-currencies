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
from ddvc.analysis.routing_contract import (
    HORIZONS_DAYS,
    MARGINS,
    MAX_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE_SPREAD,
    MIN_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE,
    PRIMARY_YEARS,
    REGRET_BIN_COLUMNS,
    REGRET_BIN_LEVELS,
    REPRODUCTION_TOLERANCES_BPS,
    TRANSITION_REPRODUCTION_TOLERANCE_BPS,
    TRANSITION_YEARS,
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
FRONTIER_SUPPORT_COLUMNS = (
    "day",
    "within_20pct_chosen_quote_eligible_routes",
    "within_20pct_chosen_quote_available",
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
    frequency_weights: bool = False,
    required_regressors: set[str] | None = None,
    retain_columns: Sequence[str] = (),
) -> tuple[ClusteredOLSResult, list[str], list[str], pd.DataFrame]:
    columns = [outcome, *regressors, fixed_effect, *cluster_columns, *retain_columns]
    if weight_column:
        columns.append(weight_column)
    model = frame.loc[:, list(dict.fromkeys(columns))].dropna().reset_index(drop=True)
    if model.empty:
        raise ValueError("routing estimator has no complete observations")
    numeric_columns = [outcome, *regressors]
    if weight_column:
        numeric_columns.append(weight_column)
    if not np.isfinite(model[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("routing estimator inputs must be finite")
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
        frequency_weights=frequency_weights,
    )
    if not np.isfinite(fit.beta).all():
        raise ValueError("routing estimator is unidentified after fixed-effect absorption")
    if not np.isfinite(fit.covariance).all():
        raise ValueError("routing estimator covariance is not finite")
    required_positions = [kept.index(column) for column in required]
    required_variances = np.diag(fit.covariance)[required_positions]
    if np.any(required_variances <= 0):
        raise ValueError("routing estimator required-regressor variance is not positive")
    return fit, kept, dropped, model


def _joint_wald(
    fit: ClusteredOLSResult, names: Sequence[str], tested: Sequence[str]
) -> tuple[float, int, float]:
    positions = [names.index(name) for name in tested]
    restriction_beta = fit.beta[positions]
    restriction_covariance = fit.covariance[np.ix_(positions, positions)]
    restriction_covariance = (
        restriction_covariance + restriction_covariance.T
    ) / 2
    if not np.isfinite(restriction_covariance).all():
        raise ValueError("joint year test has a non-finite covariance matrix")
    if np.linalg.eigvalsh(restriction_covariance).min() <= 0:
        raise ValueError("joint year test covariance matrix is not positive definite")
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
        frequency_weights=weight_column == "route_count",
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
        "cr1_observation_count": fit.finite_sample_observations,
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
    sample, support = _transition_common_support(frame)
    if sample.empty:
        raise ValueError("routing transition has no opportunity cell in both endpoint years")
    identifying_cells = int(support["identifying_opportunity_cells"])
    identifying_cell_share = float(support["identifying_opportunity_cell_share"])
    identifying_route_share = float(support["identifying_route_share"])
    candidate_cells = int(support["candidate_opportunity_cells"])
    candidate_routes = int(support["candidate_route_count"])
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
            frequency_weights=weight_column == "route_weight",
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
                "support": "common_month_day_and_opportunity_2024_2026",
                "reproduction_tolerance_bps": 1.0,
                "n_observations": fit.n_observations,
                "n_cells": int(model["opportunity_cell_id"].nunique()),
                "n_dates": int(model["date"].nunique()),
                "route_count": int(model["route_count"].sum()),
                "cr1_observation_count": fit.finite_sample_observations,
                "candidate_opportunity_cells": candidate_cells,
                "identifying_opportunity_cells": identifying_cells,
                "identifying_opportunity_cell_share": identifying_cell_share,
                "candidate_route_count": candidate_routes,
                "identifying_route_share": identifying_route_share,
                "pair_clusters": fit.cluster_counts[0],
                "date_clusters": fit.cluster_counts[1],
                "common_month_days": int(model["date"].dt.strftime("%m-%d").nunique()),
                "baseline_2024_mean": _weighted_mean(
                    baseline["stable_indicator"], baseline[weight_column]
                ),
                "comparison_2026_mean": _weighted_mean(
                    comparison["stable_indicator"], comparison[weight_column]
                ),
                "comparison_2026_beta": statistics["comparison_year_2026_beta"],
                "comparison_2026_se": statistics["comparison_year_2026_se"],
                "comparison_2026_t": statistics["comparison_year_2026_t"],
                "comparison_2026_p": statistics["comparison_year_2026_p"],
                "regret_control_count": len(kept) - 1,
                "dropped_collinear_controls": "|".join(dropped),
            }
        )
    return pd.DataFrame(rows)


def _transition_common_support(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int | float]]:
    """Return the endpoint-year sample restricted to identifying opportunity cells."""

    _required(frame, TRANSITION_COLUMNS, name="routing transition panel")
    sample = frame.loc[
        frame["reproduction_tolerance_bps"].eq(
            TRANSITION_REPRODUCTION_TOLERANCE_BPS
        ),
        TRANSITION_COLUMNS,
    ].copy()
    sample["date"] = pd.to_datetime(sample["date"])
    sample["year"] = sample["date"].dt.year
    sample = sample[sample["year"].isin(TRANSITION_YEARS)].copy()
    sample = sample[
        common_calendar_day_mask(
            sample["date"],
            sample["year"],
            baseline_year=TRANSITION_YEARS[0],
            comparison_year=TRANSITION_YEARS[1],
        )
    ].reset_index(drop=True)
    if sample.empty:
        raise ValueError("routing transition has no common endpoint-year calendar support")
    if not np.isfinite(sample["route_count"].to_numpy(dtype=float)).all() or (
        sample["route_count"] <= 0
    ).any():
        raise ValueError("routing transition route counts must be finite and positive")
    if not sample["stable_indicator"].isin((0, 1)).all():
        raise ValueError("routing transition stable indicator must be binary")
    for column in REGRET_BIN_COLUMNS:
        if not sample[column].isin(REGRET_BIN_LEVELS).all():
            raise ValueError(f"routing transition {column} has an invalid regret bin")
    year_counts = sample.groupby("opportunity_cell_id", observed=True)["year"].nunique()
    identifying_ids = year_counts[year_counts.eq(2)].index
    identifying = sample[sample["opportunity_cell_id"].isin(identifying_ids)].reset_index(
        drop=True
    )
    candidate_cells = int(sample["opportunity_cell_id"].nunique())
    candidate_routes = int(sample["route_count"].sum())
    identifying_cells = int(identifying["opportunity_cell_id"].nunique())
    identifying_routes = int(identifying["route_count"].sum())
    support: dict[str, int | float] = {
        "candidate_observations": len(sample),
        "candidate_opportunity_cells": candidate_cells,
        "candidate_route_count": candidate_routes,
        "identifying_observations": len(identifying),
        "identifying_opportunity_cells": identifying_cells,
        "identifying_route_count": identifying_routes,
        "identifying_opportunity_cell_share": identifying_cells / candidate_cells,
        "identifying_route_share": identifying_routes / candidate_routes,
    }
    return identifying, support


def transition_support_geometry(frame: pd.DataFrame) -> pd.DataFrame:
    """Describe and gate the common-opportunity support before transition fits."""

    sample, support = _transition_common_support(frame)
    annual = sample.groupby("year", observed=True).agg(
        observations=("opportunity_cell_id", "size"),
        cells=("opportunity_cell_id", "nunique"),
        dates=("date", "nunique"),
        routes=("route_count", "sum"),
    ).reindex(TRANSITION_YEARS, fill_value=0)
    maximum_observations = int(annual["observations"].max())
    maximum_routes = int(annual["routes"].max())
    observation_ratio = (
        float(annual["observations"].min() / maximum_observations)
        if maximum_observations
        else 0.0
    )
    route_ratio = (
        float(annual["routes"].min() / maximum_routes) if maximum_routes else 0.0
    )
    review = (
        float(support["identifying_opportunity_cell_share"]) < 0.5
        or float(support["identifying_route_share"]) < 0.5
        or observation_ratio < 0.5
        or route_ratio < 0.5
    )
    rows: list[dict[str, object]] = []
    for year, values in annual.iterrows():
        rows.append(
            {
                "record_type": "support",
                "family": "conditioned_transition_support",
                "spec": "common_opportunity_2024_2026",
                "support": "common_month_day_and_opportunity_2024_2026",
                "reproduction_tolerance_bps": 1.0,
                "year": int(year),
                "observations": int(values["observations"]),
                "n_cells": int(values["cells"]),
                "n_dates": int(values["dates"]),
                "route_count": int(values["routes"]),
                **support,
                "minimum_to_maximum_observation_ratio": observation_ratio,
                "minimum_to_maximum_route_ratio": route_ratio,
                "support_exit_review_required": review,
            }
        )
    return pd.DataFrame(rows)


def frontier_state_support_geometry(frame: pd.DataFrame) -> pd.DataFrame:
    """Gate primary-year time selection in chosen-state availability before fitting."""

    _required(frame, FRONTIER_SUPPORT_COLUMNS, name="transaction frontier support")
    support = frame.loc[:, FRONTIER_SUPPORT_COLUMNS].copy()
    support["date"] = pd.to_datetime(support["day"], format="%Y%m%d", errors="coerce")
    if support["date"].isna().any():
        raise ValueError("transaction frontier support contains an invalid day")
    if support["date"].duplicated().any():
        raise ValueError("transaction frontier support contains duplicate days")
    support["year"] = support["date"].dt.year
    support = support[support["year"].isin(PRIMARY_YEARS)].copy()
    count_columns = list(FRONTIER_SUPPORT_COLUMNS[1:])
    support[count_columns] = support[count_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    counts = support[count_columns].to_numpy(dtype=float)
    if not np.isfinite(counts).all() or (counts < 0).any():
        raise ValueError("transaction frontier support counts must be finite and nonnegative")
    if not np.equal(counts, np.floor(counts)).all():
        raise ValueError("transaction frontier support counts must be integers")
    if (
        support["within_20pct_chosen_quote_available"]
        > support["within_20pct_chosen_quote_eligible_routes"]
    ).any():
        raise ValueError("available chosen quotes exceed eligible routes")
    annual = support.groupby("year", observed=True).agg(
        eligible_routes=("within_20pct_chosen_quote_eligible_routes", "sum"),
        quoted_routes=("within_20pct_chosen_quote_available", "sum"),
        dates=("date", "nunique"),
    ).reindex(PRIMARY_YEARS, fill_value=0)
    annual["chosen_state_coverage"] = np.divide(
        annual["quoted_routes"],
        annual["eligible_routes"],
        out=np.zeros(len(annual), dtype=float),
        where=annual["eligible_routes"].gt(0),
    )
    minimum_coverage = float(annual["chosen_state_coverage"].min())
    maximum_coverage = float(annual["chosen_state_coverage"].max())
    coverage_spread = maximum_coverage - minimum_coverage
    review = (
        minimum_coverage < MIN_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE
        or coverage_spread > MAX_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE_SPREAD
    )
    rows: list[dict[str, object]] = []
    for year, values in annual.iterrows():
        rows.append(
            {
                "record_type": "support",
                "family": "frontier_state_coverage_support",
                "spec": "primary_year_time_selection",
                "support": "within_20pct_chosen_quote_eligible",
                "reproduction_tolerance_bps": 1.0,
                "year": int(year),
                "eligible_routes": int(values["eligible_routes"]),
                "quoted_routes": int(values["quoted_routes"]),
                "n_dates": int(values["dates"]),
                "chosen_state_coverage": float(values["chosen_state_coverage"]),
                "minimum_primary_year_coverage": minimum_coverage,
                "maximum_primary_year_coverage": maximum_coverage,
                "primary_year_coverage_spread": coverage_spread,
                "minimum_coverage_gate": MIN_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE,
                "maximum_spread_gate": MAX_PRIMARY_YEAR_CHOSEN_STATE_COVERAGE_SPREAD,
                "support_exit_review_required": review,
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


def dynamics_support_geometry(frame: pd.DataFrame) -> pd.DataFrame:
    """Describe exact-link attrition by horizon and origin year before fitting."""

    _required(frame, DYNAMIC_COLUMNS, name="routing exact-horizon panel")
    sample = frame.loc[
        frame["reproduction_tolerance_bps"].eq(1.0), DYNAMIC_COLUMNS
    ].copy()
    sample["origin_date"] = pd.to_datetime(sample["origin_date"])
    if sample["origin_date"].isna().any():
        raise ValueError("routing exact-horizon origin dates must be valid")
    sample["origin_year"] = sample["origin_date"].dt.year
    sample = sample[sample["origin_year"].isin(PRIMARY_YEARS)].copy()
    if not set(sample["horizon_days"]).issubset(set(HORIZONS_DAYS)):
        raise ValueError("routing exact-horizon support contains a noncanonical horizon")
    if sample.empty:
        raise ValueError("routing exact-horizon support is empty")
    duplicate = sample.duplicated(["cell_id", "origin_date", "horizon_days"], keep=False)
    if duplicate.any():
        raise ValueError("routing exact-horizon support contains duplicate links")
    if not sample["target_observed"].isin((True, False)).all():
        raise ValueError("routing exact-horizon target flag must be binary")
    current_columns = [name for name in DYNAMIC_OUTCOME_COLUMNS if name.startswith("current_")]
    future_columns = [name for name in DYNAMIC_OUTCOME_COLUMNS if name.startswith("future_")]
    if not sample[current_columns].notna().all(axis=1).all():
        raise ValueError("routing exact-horizon current outcomes must be complete")
    if not np.isfinite(sample[current_columns].to_numpy(dtype=float)).all():
        raise ValueError("routing exact-horizon current outcomes must be finite")
    future_complete = sample[future_columns].notna().all(axis=1)
    future_any = sample[future_columns].notna().any(axis=1)
    observed = sample["target_observed"].astype(bool)
    if not observed.eq(future_complete).all() or ((~observed) & future_any).any():
        raise ValueError("routing exact-horizon target flag disagrees with outcome completeness")
    if not np.isfinite(sample.loc[observed, future_columns].to_numpy(dtype=float)).all():
        raise ValueError("routing exact-horizon observed future outcomes must be finite")
    annual = sample.groupby(["horizon_days", "origin_year"], observed=True).agg(
        total_links=("cell_id", "size"),
        observed_links=("target_observed", "sum"),
        origin_cells=("cell_id", "nunique"),
        origin_dates=("origin_date", "nunique"),
    )
    expected = pd.MultiIndex.from_product(
        [HORIZONS_DAYS, PRIMARY_YEARS], names=["horizon_days", "origin_year"]
    )
    annual = annual.reindex(expected, fill_value=0).reset_index()
    annual["link_coverage"] = np.divide(
        annual["observed_links"],
        annual["total_links"],
        out=np.zeros(len(annual), dtype=float),
        where=annual["total_links"].gt(0),
    )
    rows: list[dict[str, object]] = []
    for horizon, horizon_rows in annual.groupby("horizon_days", observed=True):
        maximum_observed = int(horizon_rows["observed_links"].max())
        observed_ratio = (
            float(horizon_rows["observed_links"].min() / maximum_observed)
            if maximum_observed
            else 0.0
        )
        minimum_coverage = float(horizon_rows["link_coverage"].min())
        review = minimum_coverage < 0.5 or observed_ratio < 0.5
        for record in horizon_rows.to_dict("records"):
            rows.append(
                {
                    "record_type": "support",
                    "family": "exact_horizon_support",
                    "spec": "recurrent_primary_exact_target",
                    "support": "origin_year_exact_calendar_link",
                    "reproduction_tolerance_bps": 1.0,
                    "horizon_days": int(horizon),
                    "year": int(record["origin_year"]),
                    "total_links": int(record["total_links"]),
                    "observed_links": int(record["observed_links"]),
                    "n_cells": int(record["origin_cells"]),
                    "n_dates": int(record["origin_dates"]),
                    "link_coverage": float(record["link_coverage"]),
                    "minimum_annual_link_coverage": minimum_coverage,
                    "minimum_to_maximum_observed_link_ratio": observed_ratio,
                    "support_exit_review_required": review,
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
