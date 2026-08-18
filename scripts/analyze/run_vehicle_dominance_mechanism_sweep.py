#!/usr/bin/env python3
"""Screen market-state drivers of the 2024-to-2026 stable-vehicle transition.

This is an exploratory mechanism screen. It consumes only the released
vehicle-transition pair panel and endpoint-pair support ledger, then asks which
observable pair-day states characterize stable-vehicle gains, turn-ons, and
leader switches. It is not a causal design and does not upgrade claim status.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.asset_types import classify
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output


PAIR_PANEL_INPUT = OUTPUT_DIR / "exhibits/vehicle_transition_pair_panel.parquet"
PAIR_SUPPORT_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_pair_support.parquet"
CHOICES_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_dominance_mechanism_sweep.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_dominance_mechanism_support.jsonl"

BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
METRICS = (
    "count_share",
    "matched_strict_count_share",
    "strict_intermediation_value_share",
)
BASE_RHS = (
    "baseline_log_market_routes",
    "baseline_direct_route_share",
    "baseline_complex_route_share",
    "baseline_primary_choice_share",
    "baseline_pair_age_log",
    "cross_venue",
)
CHANGE_RHS = (
    "market_route_growth_log",
    "direct_route_share_change",
    "complex_route_share_change",
)
DIRECT_THIN_RHS = (
    "baseline_thinness",
    "baseline_direct_route_share",
    "baseline_direct_x_thin",
    "baseline_complex_route_share",
    "baseline_primary_choice_share",
    "baseline_pair_age_log",
    "cross_venue",
)
REGIME_THRESHOLD = 0.5
RISK_SET_MIN_TOTAL_ROUTES = (1, 5, 20)
RISK_SET_CENTRALITY_REGRESSORS = (
    "is_stable",
    "is_stable_x_2026",
    "log_leaveout_candidate_pair_scopes",
)
STABLE_TURN_ON_HORIZON_DAYS = 30
STABLE_TURN_ON_PREDICTORS = (
    "is_2026",
    "stable_endpoint",
    "is_2026_x_stable_endpoint",
    "log_market_routes",
    "direct_share",
    "complex_share",
    "primary_choice_share",
    "pair_age_log",
)
STABLE_TURN_ON_DECILE_VARIABLES = (
    "log_market_routes",
    "pair_age_log",
)
MODEL_SPECS = (
    (
        "share_change_baseline_state",
        "stable_share_change",
        BASE_RHS,
        "Which initial market states characterize later stable-vehicle gains?",
    ),
    (
        "share_change_state_and_dynamics",
        "stable_share_change",
        (*BASE_RHS, *CHANGE_RHS),
        "Do changes in market structure add explanatory power beyond initial state?",
    ),
    (
        "turn_on_lpm",
        "stable_turn_on",
        BASE_RHS,
        "Where does a stable vehicle appear after no baseline stable use?",
    ),
    (
        "turn_on_direct_thin_interaction",
        "stable_turn_on",
        DIRECT_THIN_RHS,
        "Is direct-route availability more predictive of stable turn-on in thin markets?",
    ),
    (
        "leader_switch_lpm",
        "stable_leader_switch",
        BASE_RHS,
        "Where does the stable vehicle become the majority route vehicle?",
    ),
)


@dataclass(frozen=True)
class SweepInputs:
    pair_panel: Path = PAIR_PANEL_INPUT
    pair_support: Path = PAIR_SUPPORT_INPUT
    candidate_choices: Path = CHOICES_INPUT
    results: Path = RESULT_OUTPUT
    support: Path = SUPPORT_OUTPUT


def _read_support_covariates(path: Path) -> pd.DataFrame:
    """Read only the endpoint-pair support fields used by the screen."""

    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            SELECT
                CAST(date AS DATE) AS date,
                year(date)::INTEGER AS year,
                src,
                tgt,
                sum(market_route_count)::DOUBLE AS market_route_count,
                sum(primary_choice_route_count)::DOUBLE AS primary_choice_route_count,
                sum(direct_route_count)::DOUBLE AS direct_route_count,
                sum(direct_split_route_count)::DOUBLE AS direct_split_route_count,
                sum(other_candidate_route_count)::DOUBLE AS other_candidate_route_count,
                sum(
                    multiple_intermediary_route_count
                    + split_or_join_route_count
                    + nonsequential_two_leg_route_count
                )::DOUBLE AS complex_route_count,
                min(CAST(pair_first_supported_date AS DATE)) AS pair_first_supported_date,
                max(CAST(pair_last_supported_date AS DATE)) AS pair_last_supported_date
            FROM read_parquet(?)
            WHERE year(date) IN (?, ?)
              AND strftime(date, '%m-%d') <= '06-30'
            GROUP BY 1, 2, 3, 4
            """,
            [str(path), BASELINE_YEAR, COMPARISON_YEAR],
        ).fetchdf()
    finally:
        connection.close()


def _positive_share(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    values = numerator.astype(float) / denominator.astype(float)
    return values.where(denominator.astype(float) > 0)


def _flatten_year_columns(frame: pd.DataFrame) -> pd.DataFrame:
    flattened = frame.copy()
    flattened.columns = [
        f"{name}_{year}" if year else str(name)
        for name, year in flattened.columns.to_flat_index()
    ]
    return flattened.reset_index()


def build_transition_design(
    pair_panel_path: Path = PAIR_PANEL_INPUT,
    pair_support_path: Path = PAIR_SUPPORT_INPUT,
) -> pd.DataFrame:
    """Return pair-month-day-scope transition rows with market-state covariates."""

    pair_panel = pd.read_parquet(pair_panel_path)
    required_panel = {
        "metric",
        "year",
        "date",
        "src",
        "tgt",
        "month_day",
        "integration_scope",
        "denominator",
        "stable_share",
    }
    missing = sorted(required_panel - set(pair_panel.columns))
    if missing:
        raise ValueError(f"vehicle-transition pair panel lacks columns: {missing}")
    pair_panel = pair_panel[pair_panel["metric"].isin(METRICS)].copy()
    pair_panel["date"] = pd.to_datetime(pair_panel["date"], errors="raise").dt.normalize()
    pair_panel["year"] = pair_panel["year"].astype(int)
    support = _read_support_covariates(pair_support_path)
    support["date"] = pd.to_datetime(support["date"], errors="raise").dt.normalize()
    support["pair_first_supported_date"] = pd.to_datetime(
        support["pair_first_supported_date"], errors="raise"
    ).dt.normalize()
    support["pair_last_supported_date"] = pd.to_datetime(
        support["pair_last_supported_date"], errors="raise"
    ).dt.normalize()
    support["direct_route_share"] = _positive_share(
        support["direct_route_count"], support["market_route_count"]
    )
    support["complex_route_share"] = _positive_share(
        support["complex_route_count"], support["market_route_count"]
    )
    support["primary_choice_share"] = _positive_share(
        support["primary_choice_route_count"], support["market_route_count"]
    )
    support["pair_age_days"] = (
        support["date"] - support["pair_first_supported_date"]
    ).dt.days.clip(lower=0)

    merged = pair_panel.merge(
        support[
            [
                "date",
                "year",
                "src",
                "tgt",
                "market_route_count",
                "primary_choice_route_count",
                "direct_route_share",
                "complex_route_share",
                "primary_choice_share",
                "pair_age_days",
            ]
        ],
        on=["date", "year", "src", "tgt"],
        how="inner",
        validate="many_to_one",
    )
    keys = ["metric", "src", "tgt", "month_day", "integration_scope"]
    value_columns = [
        "stable_share",
        "denominator",
        "market_route_count",
        "primary_choice_route_count",
        "direct_route_share",
        "complex_route_share",
        "primary_choice_share",
        "pair_age_days",
    ]
    duplicated = merged.duplicated([*keys, "year"])
    if duplicated.any():
        raise ValueError("mechanism screen has duplicate pair-year design rows")
    pivot = _flatten_year_columns(
        merged.pivot(index=keys, columns="year", values=value_columns)
    )
    required_year_columns = [
        f"{column}_{year}"
        for column in value_columns
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    ]
    missing_years = sorted(column for column in required_year_columns if column not in pivot)
    if missing_years:
        raise ValueError(f"mechanism screen lacks endpoint-year columns: {missing_years}")
    design = pivot.dropna(subset=required_year_columns).copy()
    base = str(BASELINE_YEAR)
    comp = str(COMPARISON_YEAR)
    design["stable_share_change"] = (
        design[f"stable_share_{comp}"] - design[f"stable_share_{base}"]
    )
    design["stable_turn_on"] = (
        design[f"stable_share_{base}"].le(0.0)
        & design[f"stable_share_{comp}"].gt(0.0)
    ).astype(float)
    design["stable_leader_switch"] = (
        design[f"stable_share_{base}"].lt(0.5)
        & design[f"stable_share_{comp}"].ge(0.5)
    ).astype(float)
    denominator_sum = (
        design[f"denominator_{base}"].astype(float)
        + design[f"denominator_{comp}"].astype(float)
    )
    design["effective_transition_weight"] = (
        design[f"denominator_{base}"].astype(float)
        * design[f"denominator_{comp}"].astype(float)
        / denominator_sum
    )
    design["baseline_log_market_routes"] = np.log1p(
        design[f"market_route_count_{base}"].astype(float)
    )
    design["baseline_thinness"] = -design["baseline_log_market_routes"]
    design["comparison_log_market_routes"] = np.log1p(
        design[f"market_route_count_{comp}"].astype(float)
    )
    design["market_route_growth_log"] = (
        design["comparison_log_market_routes"] - design["baseline_log_market_routes"]
    )
    design["baseline_direct_route_share"] = design[f"direct_route_share_{base}"].astype(float)
    design["baseline_complex_route_share"] = design[f"complex_route_share_{base}"].astype(float)
    design["baseline_primary_choice_share"] = design[f"primary_choice_share_{base}"].astype(float)
    design["baseline_pair_age_log"] = np.log1p(design[f"pair_age_days_{base}"].astype(float))
    design["baseline_direct_x_thin"] = (
        design["baseline_direct_route_share"] * design["baseline_thinness"]
    )
    design["direct_route_share_change"] = (
        design[f"direct_route_share_{comp}"].astype(float)
        - design[f"direct_route_share_{base}"].astype(float)
    )
    design["complex_route_share_change"] = (
        design[f"complex_route_share_{comp}"].astype(float)
        - design[f"complex_route_share_{base}"].astype(float)
    )
    design["cross_venue"] = design["integration_scope"].eq("cross_venue").astype(float)
    design["ordered_pair_cluster"] = list(
        design[["src", "tgt"]].itertuples(index=False, name=None)
    )
    return design.sort_values(keys).reset_index(drop=True)


def _fit_specification(
    sample: pd.DataFrame,
    *,
    metric: str,
    model_id: str,
    outcome: str,
    regressors: Iterable[str],
    question: str,
    min_clusters: int,
) -> list[dict[str, object]]:
    regressors = tuple(regressors)
    columns = [
        outcome,
        *regressors,
        "month_day",
        "ordered_pair_cluster",
        "effective_transition_weight",
    ]
    data = (
        sample[sample["metric"].eq(metric)]
        .loc[:, columns]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .copy()
    )
    data = data[data["effective_transition_weight"].gt(0.0)].copy()
    if data.empty:
        raise ValueError(f"mechanism screen {metric}:{model_id} has no usable rows")
    residual = absorb_fixed_effects(
        data[[outcome, *regressors]],
        data["month_day"],
        weights=data["effective_transition_weight"],
    )
    fit = ols_clustered(
        residual[outcome],
        residual[list(regressors)],
        data["ordered_pair_cluster"],
        add_constant=False,
        absorbed_groups=(data["month_day"],),
        additional_clusters=(data["month_day"],),
        weights=data["effective_transition_weight"],
        min_observations=200,
        min_clusters=min_clusters,
    )
    rows: list[dict[str, object]] = []
    for index, regressor in enumerate(regressors):
        scale = float(data[regressor].std(ddof=0))
        coefficient = float(fit.beta[index])
        standard_error = float(fit.standard_errors[index])
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": metric,
                "model_id": model_id,
                "question": question,
                "outcome": outcome,
                "regressor": regressor,
                "coefficient": coefficient,
                "coefficient_pp": 100.0 * coefficient,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
                "t_statistic": float(fit.t_statistics[index]),
                "p_value": float(fit.p_values[index]),
                "one_sd_effect_pp": 100.0 * coefficient * scale,
                "regressor_sd": scale,
                "observations": fit.n_observations,
                "ordered_pair_clusters": int(fit.cluster_counts[0]),
                "month_day_clusters": int(fit.cluster_counts[1]),
                "fixed_effects": "month_day",
                "covariance": "two_way_ordered_pair_month_day_cr1",
                "weight": "harmonic_endpoint_denominator_mass",
                "interpretation": "descriptive_driver_screen_not_causal",
                "rival_story": (
                    "endpoint demand, feasible route set, notional, router search, and "
                    "unobserved token shocks may jointly drive both market state and "
                    "stable-vehicle gains"
                ),
            }
        )
    return rows


def _decile_contrasts(sample: pd.DataFrame, metric: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for variable in (
        "baseline_log_market_routes",
        "baseline_direct_route_share",
        "baseline_complex_route_share",
        "baseline_primary_choice_share",
        "baseline_pair_age_log",
        "market_route_growth_log",
    ):
        data = (
            sample[sample["metric"].eq(metric)]
            .loc[
                :,
                [
                    "stable_share_change",
                    variable,
                    "effective_transition_weight",
                ],
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        data = data[data["effective_transition_weight"].gt(0.0)].copy()
        if data[variable].nunique() < 10:
            continue
        data["decile"] = pd.qcut(data[variable], 10, labels=False, duplicates="drop")
        quantile_bins = int(data["decile"].nunique())
        if quantile_bins < 2:
            continue
        low = data[data["decile"].eq(data["decile"].min())]
        high = data[data["decile"].eq(data["decile"].max())]

        def weighted_mean(frame: pd.DataFrame) -> float:
            return float(
                np.average(
                    frame["stable_share_change"].astype(float),
                    weights=frame["effective_transition_weight"].astype(float),
                )
            )

        low_mean = weighted_mean(low)
        high_mean = weighted_mean(high)
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": metric,
                "model_id": "top_bottom_decile_contrast",
                "outcome": "stable_share_change",
                "regressor": variable,
                "bottom_decile_mean_pp": 100.0 * low_mean,
                "top_decile_mean_pp": 100.0 * high_mean,
                "top_minus_bottom_pp": 100.0 * (high_mean - low_mean),
                "bottom_decile_rows": int(len(low)),
                "top_decile_rows": int(len(high)),
                "interpretation": "weighted_descriptive_decile_contrast_not_causal",
            }
        )
    return rows


def _regime_persistence_rows(
    design: pd.DataFrame,
    *,
    min_clusters: int,
) -> list[dict[str, object]]:
    """Summarise whether continuing markets keep their baseline vehicle regime."""

    rows: list[dict[str, object]] = []
    for (metric, integration_scope), group in design.groupby(
        ["metric", "integration_scope"], sort=True
    ):
        sample = (
            group.loc[
                :,
                [
                    "src",
                    "tgt",
                    "month_day",
                    f"stable_share_{BASELINE_YEAR}",
                    f"stable_share_{COMPARISON_YEAR}",
                    "effective_transition_weight",
                    "ordered_pair_cluster",
                ],
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        sample = sample[sample["effective_transition_weight"].gt(0.0)].copy()
        if sample.empty:
            continue
        baseline_share = sample[f"stable_share_{BASELINE_YEAR}"]
        comparison_share = sample[f"stable_share_{COMPARISON_YEAR}"]
        for baseline_regime, baseline_mask, comparison_mask in (
            (
                "stable_majority",
                baseline_share.ge(REGIME_THRESHOLD),
                comparison_share.ge(REGIME_THRESHOLD),
            ),
            (
                "native_majority",
                baseline_share.lt(REGIME_THRESHOLD),
                comparison_share.lt(REGIME_THRESHOLD),
            ),
        ):
            data = sample.loc[baseline_mask].copy()
            if data.empty:
                continue
            data["regime_persists"] = comparison_mask.loc[data.index].astype(float)
            fit = ols_clustered(
                data["regime_persists"],
                pd.DataFrame(index=data.index),
                data["ordered_pair_cluster"],
                add_constant=True,
                additional_clusters=(data["month_day"],),
                weights=data["effective_transition_weight"],
                min_observations=min_clusters,
                min_clusters=min_clusters,
            )
            estimate = float(fit.beta[0])
            standard_error = float(fit.standard_errors[0])
            rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "experiment_family": "vehicle_dominance_mechanism_sweep",
                    "metric": metric,
                    "model_id": "regime_persistence",
                    "question": "Do continuing markets keep their baseline majority vehicle regime?",
                    "integration_scope": integration_scope,
                    "baseline_regime": baseline_regime,
                    "outcome": "regime_persists",
                    "coefficient": estimate,
                    "coefficient_pp": 100.0 * estimate,
                    "standard_error": standard_error,
                    "standard_error_pp": 100.0 * standard_error,
                    "switch_rate": 1.0 - estimate,
                    "switch_rate_pp": 100.0 * (1.0 - estimate),
                    "observations": fit.n_observations,
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "month_day_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "none",
                    "covariance": "two_way_ordered_pair_month_day_cr1",
                    "weight": "harmonic_endpoint_denominator_mass",
                    "interpretation": "descriptive_regime_persistence_not_causal",
                }
            )
    return rows


def build_candidate_risk_set_design(path: Path = CHOICES_INPUT) -> pd.DataFrame:
    """Return observed mixed native-stable candidate risk sets.

    The unit is a candidate inside an observed pair-day-route-scope set. The
    design deliberately keeps only risk sets where both native and stable
    candidates appear, so the coefficient is not a disguised entry-margin or
    availability comparison.
    """

    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        frame = connection.execute(
            """
            WITH candidate_rows AS (
                SELECT
                    CAST(date AS DATE) AS date,
                    src,
                    tgt,
                    integration_scope,
                    lower(candidate_address) AS candidate_address,
                    any_value(candidate_symbol) AS candidate_symbol,
                    any_value(candidate_type) AS candidate_type,
                    sum(route_count)::DOUBLE AS route_count
                FROM read_parquet(?)
                WHERE year(date) IN (?, ?)
                  AND month(date) <= 6
                  AND candidate_type IN ('stable', 'native')
                GROUP BY 1, 2, 3, 4, 5
            ),
            candidate_centrality AS (
                SELECT
                    date,
                    candidate_address,
                    sum(route_count)::DOUBLE AS candidate_day_routes,
                    count(DISTINCT concat(src, '|', tgt, '|', integration_scope))::DOUBLE
                        AS candidate_day_pair_scopes
                FROM candidate_rows
                GROUP BY 1, 2
            ),
            risk_sets AS (
                SELECT
                    r.*,
                    c.candidate_day_routes,
                    c.candidate_day_pair_scopes,
                    sum(route_count) OVER (
                        PARTITION BY date, src, tgt, integration_scope
                    ) AS total_routes,
                    count(*) OVER (
                        PARTITION BY date, src, tgt, integration_scope
                    ) AS candidate_rows,
                    max((candidate_type = 'stable')::INTEGER) OVER (
                        PARTITION BY date, src, tgt, integration_scope
                    ) AS has_stable,
                    max((candidate_type = 'native')::INTEGER) OVER (
                        PARTITION BY date, src, tgt, integration_scope
                    ) AS has_native
                FROM candidate_rows r
                JOIN candidate_centrality c USING (date, candidate_address)
            )
            SELECT *
            FROM risk_sets
            WHERE total_routes > 0
              AND candidate_rows >= 2
              AND has_stable = 1
              AND has_native = 1
            """,
            [str(path), BASELINE_YEAR, COMPARISON_YEAR],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("candidate risk-set design is empty")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["year"] = frame["date"].dt.year.astype(int)
    frame["month_day"] = frame["date"].dt.strftime("%m-%d")
    frame["route_share"] = frame["route_count"].astype(float) / frame[
        "total_routes"
    ].astype(float)
    frame["is_stable"] = frame["candidate_type"].eq("stable").astype(float)
    frame["is_2026"] = frame["year"].eq(COMPARISON_YEAR).astype(float)
    frame["is_stable_x_2026"] = frame["is_stable"] * frame["is_2026"]
    frame["leaveout_candidate_routes"] = (
        frame["candidate_day_routes"].astype(float) - frame["route_count"].astype(float)
    ).clip(lower=0.0)
    frame["leaveout_candidate_pair_scopes"] = (
        frame["candidate_day_pair_scopes"].astype(float) - 1.0
    ).clip(lower=0.0)
    frame["log_leaveout_candidate_routes"] = np.log1p(
        frame["leaveout_candidate_routes"]
    )
    frame["log_leaveout_candidate_pair_scopes"] = np.log1p(
        frame["leaveout_candidate_pair_scopes"]
    )
    frame["risk_set_id"] = (
        frame["date"].astype(str)
        + "|"
        + frame["src"].astype(str)
        + ">"
        + frame["tgt"].astype(str)
        + "|"
        + frame["integration_scope"].astype(str)
    )
    frame["ordered_pair_scope"] = (
        frame["src"].astype(str)
        + ">"
        + frame["tgt"].astype(str)
        + "|"
        + frame["integration_scope"].astype(str)
    )
    return frame


def estimate_candidate_risk_set_choice(
    design: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test stable-candidate route share within mixed native-stable risk sets."""

    required = {
        "date",
        "year",
        "route_count",
        "total_routes",
        "route_share",
        "candidate_type",
        "is_stable",
        "is_stable_x_2026",
        "log_leaveout_candidate_pair_scopes",
        "risk_set_id",
        "ordered_pair_scope",
    }
    missing = sorted(required - set(design.columns))
    if missing:
        raise ValueError(f"candidate risk-set design lacks columns: {missing}")
    result_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    for threshold in RISK_SET_MIN_TOTAL_ROUTES:
        sample = design[design["total_routes"].ge(threshold)].copy()
        if sample.empty:
            continue
        support_rows.append(
            {
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set",
                "min_total_routes": int(threshold),
                "rows": int(len(sample)),
                "ordered_pairs": int(
                    sample[["src", "tgt"]].drop_duplicates().shape[0]
                ),
                "risk_sets": int(sample["risk_set_id"].nunique()),
                "month_days": int(sample["month_day"].nunique()),
                "claim_status": "provisional_exploratory",
            }
        )
        for year, group in sample.groupby("year", sort=True):
            result_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "experiment_family": "vehicle_dominance_mechanism_sweep",
                    "metric": "candidate_route_share",
                    "model_id": "mixed_native_stable_risk_set_summary",
                    "min_total_routes": int(threshold),
                    "year": int(year),
                    "candidate_rows": int(len(group)),
                    "risk_sets": int(group["risk_set_id"].nunique()),
                    "routes": float(group["route_count"].sum()),
                    "stable_candidate_row_share": float(
                        group["is_stable"].astype(float).mean()
                    ),
                    "stable_route_share": float(
                        group.loc[group["candidate_type"].eq("stable"), "route_count"].sum()
                        / group["route_count"].sum()
                    ),
                    "native_route_share": float(
                        group.loc[group["candidate_type"].eq("native"), "route_count"].sum()
                        / group["route_count"].sum()
                    ),
                    "interpretation": "mixed_native_stable_observed_risk_set_summary_not_feasible_set",
                }
            )
        data = (
            sample[
                [
                    "route_share",
                    "is_stable",
                    "is_stable_x_2026",
                    "risk_set_id",
                    "ordered_pair_scope",
                    "date",
                    "total_routes",
                ]
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        residual = absorb_fixed_effects(
            data[["route_share", "is_stable", "is_stable_x_2026"]],
            data["risk_set_id"],
            weights=data["total_routes"],
        )
        fit = ols_clustered(
            residual["route_share"],
            residual[["is_stable", "is_stable_x_2026"]],
            data["ordered_pair_scope"],
            add_constant=False,
            absorbed_groups=(data["risk_set_id"],),
            additional_clusters=(data["date"],),
            weights=data["total_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for regressor, coefficient, standard_error, t_statistic, p_value in zip(
            ("is_stable", "is_stable_x_2026"),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            result_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "experiment_family": "vehicle_dominance_mechanism_sweep",
                    "metric": "candidate_route_share",
                    "model_id": "mixed_native_stable_risk_set_fe",
                    "question": (
                        "Do stable candidates win more route share inside the same "
                        "observed native-stable pair-day-scope risk set?"
                    ),
                    "min_total_routes": int(threshold),
                    "outcome": "candidate_route_share",
                    "regressor": regressor,
                    "coefficient": float(coefficient),
                    "coefficient_pp": 100.0 * float(coefficient),
                    "standard_error": float(standard_error),
                    "standard_error_pp": 100.0 * float(standard_error),
                    "t_statistic": float(t_statistic),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "pair_day_scope_risk_set",
                    "covariance": "two_way_ordered_pair_scope_date_cr1",
                    "weight": "risk_set_total_route_count",
                    "interpretation": "within_observed_risk_set_choice_screen_not_causal",
                    "rival_story": (
                        "stable dominance could arise because stable candidates win "
                        "inside already-mixed risk sets; this screen tests that rival "
                        "against the entry and persistence margins"
                    ),
                }
            )
        centrality_data = (
            sample[
                [
                    "route_share",
                    *RISK_SET_CENTRALITY_REGRESSORS,
                    "risk_set_id",
                    "ordered_pair_scope",
                    "date",
                    "total_routes",
                ]
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        centrality_residual = absorb_fixed_effects(
            centrality_data[["route_share", *RISK_SET_CENTRALITY_REGRESSORS]],
            centrality_data["risk_set_id"],
            weights=centrality_data["total_routes"],
        )
        centrality_fit = ols_clustered(
            centrality_residual["route_share"],
            centrality_residual[list(RISK_SET_CENTRALITY_REGRESSORS)],
            centrality_data["ordered_pair_scope"],
            add_constant=False,
            absorbed_groups=(centrality_data["risk_set_id"],),
            additional_clusters=(centrality_data["date"],),
            weights=centrality_data["total_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for regressor, coefficient, standard_error, t_statistic, p_value in zip(
            RISK_SET_CENTRALITY_REGRESSORS,
            centrality_fit.beta,
            centrality_fit.standard_errors,
            centrality_fit.t_statistics,
            centrality_fit.p_values,
            strict=True,
        ):
            result_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "experiment_family": "vehicle_dominance_mechanism_sweep",
                    "metric": "candidate_route_share",
                    "model_id": "mixed_native_stable_risk_set_centrality_fe",
                    "question": (
                        "Inside the same observed native-stable pair-day-scope "
                        "risk set, does a candidate's broader same-day network "
                        "reach explain route share?"
                    ),
                    "min_total_routes": int(threshold),
                    "outcome": "candidate_route_share",
                    "regressor": regressor,
                    "coefficient": float(coefficient),
                    "coefficient_pp": 100.0 * float(coefficient),
                    "standard_error": float(standard_error),
                    "standard_error_pp": 100.0 * float(standard_error),
                    "t_statistic": float(t_statistic),
                    "p_value": float(p_value),
                    "observations": int(centrality_fit.n_observations),
                    "ordered_pair_clusters": int(centrality_fit.cluster_counts[0]),
                    "date_clusters": int(centrality_fit.cluster_counts[1]),
                    "fixed_effects": "pair_day_scope_risk_set",
                    "covariance": "two_way_ordered_pair_scope_date_cr1",
                    "weight": "risk_set_total_route_count",
                    "centrality_measure": (
                        "log one plus the candidate's same-day observed "
                        "native/stable pair-scope count outside the current risk set"
                    ),
                    "interpretation": (
                        "within_observed_risk_set_network_centrality_screen_not_causal"
                    ),
                    "rival_story": (
                        "candidate network reach may proxy liquidity, token news, "
                        "router defaults, venue coverage, or repeated endpoint demand"
                    ),
                }
            )
    return pd.DataFrame(result_rows), pd.DataFrame(support_rows)


def build_stable_turn_on_hazard_design(
    path: Path = PAIR_SUPPORT_INPUT,
    *,
    horizon_days: int = STABLE_TURN_ON_HORIZON_DAYS,
) -> pd.DataFrame:
    """Return native-only pair-days and future stable-vehicle turn-on outcomes.

    The risk-set unit is an active ordered ultimate pair-day in January-May 2024
    or 2026 with positive primary native-or-stable vehicle use and zero stable
    vehicle use on the origin date. The future outcome asks whether any stable
    vehicle appears over the next complete horizon. This is a descriptive hazard
    screen, not a causal timing design.
    """

    if horizon_days <= 0:
        raise ValueError("stable turn-on horizon must be positive")
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        frame = connection.execute(
            f"""
            WITH base AS (
                SELECT
                    CAST(date AS DATE) AS date,
                    src,
                    tgt,
                    year(date)::INTEGER AS year,
                    strftime(date, '%m-%d') AS month_day,
                    market_route_count::DOUBLE AS market_route_count,
                    primary_choice_route_count::DOUBLE AS primary_choice_route_count,
                    stable_choice_route_count::DOUBLE AS stable_choice_route_count,
                    direct_route_count::DOUBLE AS direct_route_count,
                    (
                        multiple_intermediary_route_count
                        + split_or_join_route_count
                        + nonsequential_two_leg_route_count
                    )::DOUBLE AS complex_route_count,
                    CAST(pair_first_supported_date AS DATE) AS pair_first_supported_date,
                    sum(stable_choice_route_count) OVER (
                        PARTITION BY src, tgt
                        ORDER BY CAST(date AS DATE)
                        RANGE BETWEEN INTERVAL 1 DAY FOLLOWING
                                  AND INTERVAL {int(horizon_days)} DAY FOLLOWING
                    )::DOUBLE AS future_stable_routes,
                    sum(primary_choice_route_count) OVER (
                        PARTITION BY src, tgt
                        ORDER BY CAST(date AS DATE)
                        RANGE BETWEEN INTERVAL 1 DAY FOLLOWING
                                  AND INTERVAL {int(horizon_days)} DAY FOLLOWING
                    )::DOUBLE AS future_primary_routes
                FROM read_parquet(?)
                WHERE year(date) IN (?, ?)
                  AND strftime(date, '%m-%d') <= '05-31'
            )
            SELECT *
            FROM base
            WHERE primary_choice_route_count > 0
              AND stable_choice_route_count = 0
              AND market_route_count > 0
            """,
            [str(path), BASELINE_YEAR, COMPARISON_YEAR],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("stable turn-on hazard design is empty")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["pair_first_supported_date"] = pd.to_datetime(
        frame["pair_first_supported_date"], errors="raise"
    ).dt.normalize()
    addresses = pd.unique(frame[["src", "tgt"]].values.ravel())
    address_types = {address: classify(address)[1] for address in addresses}
    frame["src_type"] = frame["src"].map(address_types)
    frame["tgt_type"] = frame["tgt"].map(address_types)
    frame["stable_endpoint"] = (
        frame["src_type"].eq("stable") | frame["tgt_type"].eq("stable")
    ).astype(float)
    frame["future_stable_routes"] = frame["future_stable_routes"].fillna(0.0)
    frame["future_primary_routes"] = frame["future_primary_routes"].fillna(0.0)
    frame["future_stable_turn_on"] = frame["future_stable_routes"].gt(0.0).astype(float)
    frame["future_stable_share"] = (
        frame["future_stable_routes"] / frame["future_primary_routes"].replace(0.0, np.nan)
    )
    frame["log_market_routes"] = np.log1p(frame["market_route_count"].astype(float))
    frame["direct_share"] = (
        frame["direct_route_count"].astype(float)
        / frame["market_route_count"].astype(float)
    ).clip(0.0, 1.0)
    frame["complex_share"] = (
        frame["complex_route_count"].astype(float)
        / frame["market_route_count"].astype(float)
    ).clip(0.0, 1.0)
    frame["primary_choice_share"] = (
        frame["primary_choice_route_count"].astype(float)
        / frame["market_route_count"].astype(float)
    ).clip(0.0, 1.0)
    frame["pair_age_log"] = np.log1p(
        (frame["date"] - frame["pair_first_supported_date"]).dt.days.clip(lower=0)
    )
    frame["is_2026"] = frame["year"].eq(COMPARISON_YEAR).astype(float)
    frame["is_2026_x_stable_endpoint"] = (
        frame["is_2026"] * frame["stable_endpoint"]
    )
    frame["ordered_pair_cluster"] = frame["src"].astype(str) + ">" + frame["tgt"].astype(str)
    return frame


def estimate_stable_turn_on_hazard(
    design: pd.DataFrame,
    *,
    horizon_days: int = STABLE_TURN_ON_HORIZON_DAYS,
    min_observations: int = 200,
    min_clusters: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate the descriptive native-only-to-stable turn-on hazard screen."""

    missing = sorted(
        {
            "date",
            "year",
            "month_day",
            "src",
            "tgt",
            "market_route_count",
            "future_stable_turn_on",
            "future_stable_share",
            "stable_endpoint",
            "ordered_pair_cluster",
            *STABLE_TURN_ON_PREDICTORS,
        }
        - set(design.columns)
    )
    if missing:
        raise ValueError(f"stable turn-on hazard design lacks columns: {missing}")
    result_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    support_rows.append(
        {
            "experiment_family": "vehicle_dominance_mechanism_sweep",
            "metric": "native_only_pair_day_stable_turn_on",
            "model_id": "stable_turn_on_hazard",
            "horizon_days": int(horizon_days),
            "rows": int(len(design)),
            "ordered_pairs": int(design[["src", "tgt"]].drop_duplicates().shape[0]),
            "dates": int(design["date"].nunique()),
            "claim_status": "provisional_exploratory",
        }
    )
    for (year, stable_endpoint), group in design.groupby(
        ["year", "stable_endpoint"], sort=True
    ):
        weights = group["market_route_count"].astype(float)
        result_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_summary",
                "horizon_days": int(horizon_days),
                "year": int(year),
                "stable_endpoint": bool(stable_endpoint),
                "rows": int(len(group)),
                "ordered_pairs": int(group[["src", "tgt"]].drop_duplicates().shape[0]),
                "weighted_turn_on_rate": float(
                    np.average(group["future_stable_turn_on"], weights=weights)
                ),
                "weighted_turn_on_rate_pp": 100.0
                * float(np.average(group["future_stable_turn_on"], weights=weights)),
                "unweighted_turn_on_rate": float(group["future_stable_turn_on"].mean()),
                "weight": "origin_market_route_count",
                "interpretation": (
                    "native-only active pair-day future stable-vehicle turn-on, "
                    "not causal timing"
                ),
            }
        )
    for outcome in ("future_stable_turn_on", "future_stable_share"):
        data = (
            design[
                [
                    outcome,
                    "month_day",
                    "date",
                    "ordered_pair_cluster",
                    "market_route_count",
                    *STABLE_TURN_ON_PREDICTORS,
                ]
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        data = data[data["market_route_count"].gt(0.0)].copy()
        residual = absorb_fixed_effects(
            data[[outcome, *STABLE_TURN_ON_PREDICTORS]],
            data["month_day"],
            weights=data["market_route_count"],
        )
        fit = ols_clustered(
            residual[outcome],
            residual[list(STABLE_TURN_ON_PREDICTORS)],
            data["ordered_pair_cluster"],
            add_constant=False,
            absorbed_groups=(data["month_day"],),
            additional_clusters=(data["date"],),
            weights=data["market_route_count"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for index, predictor in enumerate(STABLE_TURN_ON_PREDICTORS):
            coefficient = float(fit.beta[index])
            standard_error = float(fit.standard_errors[index])
            scale = float(data[predictor].std(ddof=0))
            result_rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "experiment_family": "vehicle_dominance_mechanism_sweep",
                    "metric": "native_only_pair_day_stable_turn_on",
                    "model_id": "stable_turn_on_hazard_fe",
                    "question": (
                        "Among active pair-days with no stable vehicle today, "
                        "which states predict stable vehicle use over the next month?"
                    ),
                    "horizon_days": int(horizon_days),
                    "outcome": outcome,
                    "regressor": predictor,
                    "coefficient": coefficient,
                    "coefficient_pp": 100.0 * coefficient,
                    "standard_error": standard_error,
                    "standard_error_pp": 100.0 * standard_error,
                    "t_statistic": float(fit.t_statistics[index]),
                    "p_value": float(fit.p_values[index]),
                    "one_sd_effect_pp": 100.0 * coefficient * scale,
                    "regressor_sd": scale,
                    "observations": int(fit.n_observations),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "month_day",
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "origin_market_route_count",
                    "interpretation": (
                        "native-only-to-stable vehicle turn-on association, not causal timing"
                    ),
                    "rival_story": (
                        "market thickness and pair age may proxy router coverage, "
                        "token news, or repeated endpoint demand rather than a pure "
                        "liquidity externality"
                    ),
                }
            )
    for variable in STABLE_TURN_ON_DECILE_VARIABLES:
        data = (
            design[
                [
                    variable,
                    "future_stable_turn_on",
                    "market_route_count",
                ]
            ]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        if data[variable].nunique() < 10:
            continue
        data["decile"] = pd.qcut(data[variable], 10, labels=False, duplicates="drop")
        quantile_bins = int(data["decile"].nunique())
        if quantile_bins < 2:
            continue
        low = data[data["decile"].eq(data["decile"].min())]
        high = data[data["decile"].eq(data["decile"].max())]

        def weighted_turn_on(frame: pd.DataFrame) -> float:
            return float(
                np.average(
                    frame["future_stable_turn_on"].astype(float),
                    weights=frame["market_route_count"].astype(float),
                )
            )

        low_rate = weighted_turn_on(low)
        high_rate = weighted_turn_on(high)
        result_rows.append(
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_decile",
                "horizon_days": int(horizon_days),
                "outcome": "future_stable_turn_on",
                "regressor": variable,
                "bottom_decile_turn_on_rate": low_rate,
                "top_decile_turn_on_rate": high_rate,
                "top_minus_bottom_pp": 100.0 * (high_rate - low_rate),
                "bottom_decile_rows": int(len(low)),
                "top_decile_rows": int(len(high)),
                "quantile_bins": quantile_bins,
                "weight": "origin_market_route_count",
                "interpretation": (
                    "weighted native-only-to-stable hazard contrast, not causal timing"
                ),
            }
        )
    return pd.DataFrame(result_rows), pd.DataFrame(support_rows)


def estimate_mechanism_sweep(
    design: pd.DataFrame,
    *,
    min_clusters: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit the exploratory model grid and return result and support frames."""

    missing = sorted(
        {
            "metric",
            "month_day",
            "stable_share_change",
            "stable_turn_on",
            "stable_leader_switch",
            "effective_transition_weight",
            "ordered_pair_cluster",
            *BASE_RHS,
            *CHANGE_RHS,
            *DIRECT_THIN_RHS,
        }
        - set(design.columns)
    )
    if missing:
        raise ValueError(f"mechanism sweep design lacks columns: {missing}")
    result_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    for metric in METRICS:
        metric_sample = design[design["metric"].eq(metric)]
        support_rows.append(
            {
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": metric,
                "rows": int(len(metric_sample)),
                "ordered_pairs": int(
                    metric_sample[["src", "tgt"]].drop_duplicates().shape[0]
                ),
                "month_days": int(metric_sample["month_day"].nunique()),
                "integration_scopes": int(metric_sample["integration_scope"].nunique()),
                "mean_stable_share_change_pp": 100.0
                * float(metric_sample["stable_share_change"].mean()),
                "weighted_mean_stable_share_change_pp": 100.0
                * float(
                    np.average(
                        metric_sample["stable_share_change"],
                        weights=metric_sample["effective_transition_weight"],
                    )
                ),
                "stable_turn_on_rate": float(metric_sample["stable_turn_on"].mean()),
                "stable_leader_switch_rate": float(
                    metric_sample["stable_leader_switch"].mean()
                ),
                "claim_status": "provisional_exploratory",
            }
        )
        for model_id, outcome, regressors, question in MODEL_SPECS:
            result_rows.extend(
                _fit_specification(
                    design,
                    metric=metric,
                    model_id=model_id,
                    outcome=outcome,
                    regressors=regressors,
                    question=question,
                    min_clusters=min_clusters,
                )
            )
        result_rows.extend(_decile_contrasts(design, metric))
    result_rows.extend(_regime_persistence_rows(design, min_clusters=min_clusters))
    return pd.DataFrame(result_rows), pd.DataFrame(support_rows)


def _write_jsonl(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        frame.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=12,
        )


def run(inputs: SweepInputs = SweepInputs()) -> int:
    for path in (inputs.pair_panel, inputs.pair_support, inputs.candidate_choices):
        if not path.is_file():
            raise FileNotFoundError(path)
    design = build_transition_design(inputs.pair_panel, inputs.pair_support)
    results, support = estimate_mechanism_sweep(design)
    risk_design = build_candidate_risk_set_design(inputs.candidate_choices)
    risk_results, risk_support = estimate_candidate_risk_set_choice(risk_design)
    hazard_design = build_stable_turn_on_hazard_design(inputs.pair_support)
    hazard_results, hazard_support = estimate_stable_turn_on_hazard(hazard_design)
    results = pd.concat(
        [results, risk_results, hazard_results],
        ignore_index=True,
        sort=False,
    )
    support = pd.concat(
        [support, risk_support, hazard_support],
        ignore_index=True,
        sort=False,
    )
    _write_jsonl(results, inputs.results)
    _write_jsonl(support, inputs.support)
    print(
        f"wrote {len(results):,} exploratory mechanism rows and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
