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
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output


PAIR_PANEL_INPUT = OUTPUT_DIR / "exhibits/vehicle_transition_pair_panel.parquet"
PAIR_SUPPORT_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_pair_support.parquet"
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
        if data["decile"].nunique() < 4:
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
    for path in (inputs.pair_panel, inputs.pair_support):
        if not path.is_file():
            raise FileNotFoundError(path)
    design = build_transition_design(inputs.pair_panel, inputs.pair_support)
    results, support = estimate_mechanism_sweep(design)
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
