#!/usr/bin/env python3
"""Test whether stablecoin route frequency predicts later routed-value leadership.

The outcome and predictor are continuous USDT-minus-USDC shares within exact
two-leg stablecoin intermediation.  Counts use all route support; routed value
uses the project's strict 20 percent value-agreement support.  The primary
seven-day dynamic regression conditions on the current value gap and calendar
effects.  One- and 30-day horizons are timing sensitivities.  The reverse
value-to-count equation is a diagnostic for bidirectional feedback or common
slow-moving shocks, not a second causal claim.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/provisional/stable_frequency_value_dynamics_e0.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import holm_adjusted_pvalues, ols_hac
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit


INPUT = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUTPUT = OUTPUT_DIR / "provisional" / "stable_frequency_value_dynamics_e0.jsonl"
HORIZONS = (1, 7, 30)
PRIMARY_HORIZON = 7
BASE_HAC_LAG = 30
REQUIRED_COLUMNS = (
    "date",
    "cnt_two_leg_stable",
    "cnt_two_leg_USDT",
    "cnt_two_leg_USDC",
    "usd_within_20pct_two_leg_stable",
    "usd_within_20pct_two_leg_USDT",
    "usd_within_20pct_two_leg_USDC",
)
CODE_SOURCES = [
    "scripts/run_stable_frequency_value_dynamics_e0.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]


def daily_gaps(panel: pd.DataFrame) -> pd.DataFrame:
    """Return consecutive-day count and strict-value leadership gaps."""

    missing = sorted(set(REQUIRED_COLUMNS) - set(panel.columns))
    if missing:
        raise ValueError(f"intermediation panel is missing columns: {missing}")
    data = panel[list(REQUIRED_COLUMNS)].copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    if data["date"].duplicated().any():
        raise ValueError("intermediation panel has duplicate dates")
    for column in REQUIRED_COLUMNS[1:]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[
        data["cnt_two_leg_stable"].gt(0)
        & data["usd_within_20pct_two_leg_stable"].gt(0)
    ].sort_values("date", kind="stable")
    data["count_gap"] = (
        data["cnt_two_leg_USDT"] - data["cnt_two_leg_USDC"]
    ) / data["cnt_two_leg_stable"]
    data["strict_value_gap"] = (
        data["usd_within_20pct_two_leg_USDT"]
        - data["usd_within_20pct_two_leg_USDC"]
    ) / data["usd_within_20pct_two_leg_stable"]
    if not data[["count_gap", "strict_value_gap"]].apply(
        lambda column: column.between(-1, 1).all()
    ).all():
        raise ValueError("USDT-minus-USDC shares fall outside their stablecoin denominator")
    data["year"] = data["date"].dt.year
    data["calendar_month"] = data["date"].dt.month
    return data.reset_index(drop=True)


def horizon_sample(data: pd.DataFrame, horizon: int, direction: str) -> pd.DataFrame:
    """Join an origin day to the exact future calendar day for one direction."""

    if horizon < 1:
        raise ValueError("prediction horizon must be positive")
    if direction not in {"count_to_value", "value_to_count"}:
        raise ValueError(f"unsupported direction: {direction}")
    predictor = "count_gap" if direction == "count_to_value" else "strict_value_gap"
    current_outcome = "strict_value_gap" if direction == "count_to_value" else "count_gap"
    future = data[["date", current_outcome]].copy()
    future["date"] = future["date"] - pd.Timedelta(days=horizon)
    future = future.rename(columns={current_outcome: "future_outcome"})
    sample = data.merge(future, on="date", how="inner", validate="one_to_one")
    sample = sample.rename(
        columns={predictor: "predictor", current_outcome: "current_outcome"}
    )
    sample["horizon"] = horizon
    sample["direction"] = direction
    sample["future_date"] = sample["date"] + pd.Timedelta(days=horizon)
    if not sample["future_date"].sub(sample["date"]).dt.days.eq(horizon).all():
        raise RuntimeError("horizon join did not preserve exact calendar distance")
    return sample


def _design(sample: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    years = pd.get_dummies(
        sample["year"], prefix="year", drop_first=True, dtype=float
    )
    months = pd.get_dummies(
        sample["calendar_month"], prefix="month", drop_first=True, dtype=float
    )
    names = ["constant", "predictor", "current_outcome", *years.columns, *months.columns]
    design = np.column_stack(
        [
            np.ones(len(sample)),
            sample["predictor"].to_numpy(float),
            sample["current_outcome"].to_numpy(float),
            years.to_numpy(float),
            months.to_numpy(float),
        ]
    )
    if np.linalg.matrix_rank(design) != design.shape[1]:
        raise ValueError("dynamic leadership design is rank deficient")
    return design, [str(name) for name in names]


def fit_dynamic(sample: pd.DataFrame) -> dict[str, object]:
    """Fit one continuous-share dynamic regression with actual-calendar HAC."""

    design, names = _design(sample)
    outcome = sample["future_outcome"].to_numpy(float)
    hac_lag = max(BASE_HAC_LAG, int(sample["horizon"].iloc[0]))
    beta, covariance = ols_hac(
        outcome,
        design,
        hac_lag,
        time_index=sample["date"],
    )
    standard_errors = np.sqrt(np.diag(covariance))
    predictor_index = names.index("predictor")
    coefficient = float(beta[predictor_index])
    standard_error = float(standard_errors[predictor_index])
    degrees_freedom = max(len(sample) - design.shape[1], 1)
    t_statistic = coefficient / standard_error if standard_error > 0 else np.nan
    p_value = (
        float(2 * stats.t.sf(abs(t_statistic), degrees_freedom))
        if np.isfinite(t_statistic)
        else np.nan
    )
    critical = float(stats.t.ppf(0.975, degrees_freedom))
    residual = outcome - design @ beta
    total = float(np.square(outcome - outcome.mean()).sum())
    r_squared = 1 - float(np.square(residual).sum()) / total if total > 0 else np.nan
    direction = str(sample["direction"].iloc[0])
    horizon = int(sample["horizon"].iloc[0])
    return {
        "row_type": "dynamic_estimate",
        "direction": direction,
        "horizon_days": horizon,
        "primary_specification": direction == "count_to_value" and horizon == PRIMARY_HORIZON,
        "coefficient": coefficient,
        "standard_error": standard_error,
        "t_statistic": float(t_statistic),
        "p_value": p_value,
        "confidence_interval_lower": coefficient - critical * standard_error,
        "confidence_interval_upper": coefficient + critical * standard_error,
        "effect_of_10pp_predictor_gap_pp": 10 * coefficient,
        "current_outcome_coefficient": float(beta[names.index("current_outcome")]),
        "observations": int(len(sample)),
        "origin_start": sample["date"].min().date().isoformat(),
        "origin_end": sample["date"].max().date().isoformat(),
        "future_end": sample["future_date"].max().date().isoformat(),
        "r_squared": r_squared,
        "fixed_effects": "calendar_year_and_month_of_year",
        "covariance": f"newey_west_actual_calendar_day_lag_{hac_lag}",
        "estimand": (
            "later_strict_value_USDT_minus_USDC_share_conditional_on_current_value_share"
            if direction == "count_to_value"
            else "later_count_USDT_minus_USDC_share_conditional_on_current_count_share"
        ),
        "claim_boundary": "predictive_descriptive_not_causal_or_structural_feedback",
    }


def method_assessment() -> pd.DataFrame:
    """Record why the estimator follows the economic unit rather than a method battery."""

    rows = [
        (
            "dynamic_OLS_with_actual_calendar_HAC",
            "selected",
            "daily aggregate outcome is a continuous within-stablecoin share gap; conditioning on its current level targets incremental predictive content and HAC addresses serial dependence",
        ),
        (
            "panel_fixed_effects",
            "not_applicable",
            "the estimand is one market-wide daily series, so there is no independent pair, pool, or provider panel dimension to absorb",
        ),
        (
            "grouped_logit_or_binomial",
            "rejected_for_this_estimand",
            "thresholding a continuous share gap into a leader indicator discards economic magnitude and does not create independent Bernoulli trials",
        ),
        (
            "survival_or_discrete_time_hazard",
            "rejected_for_this_estimand",
            "the question concerns continuous adjustment at fixed horizons rather than time to a unique first event; leadership can reverse repeatedly and endpoint spells are censored",
        ),
        (
            "difference_in_differences_or_event_study",
            "not_identified",
            "there is no exogenous treatment date or untreated comparison series; calendar time cannot identify a technology or adoption effect",
        ),
        (
            "iid_t_test",
            "rejected",
            "daily observations are serially dependent and horizons overlap, so an iid mean comparison understates uncertainty",
        ),
        (
            "KS_distribution_test",
            "rejected",
            "the estimand is conditional lead-lag adjustment rather than equality of two independent distributions; textbook KS critical values are invalid for this time series",
        ),
    ]
    return pd.DataFrame(rows, columns=["method", "status", "reason"]).assign(
        row_type="method_assessment"
    )


def result_frame(panel: pd.DataFrame) -> pd.DataFrame:
    data = daily_gaps(panel)
    estimates = pd.DataFrame(
        [
            fit_dynamic(horizon_sample(data, horizon, direction))
            for horizon in HORIZONS
            for direction in ("count_to_value", "value_to_count")
        ]
    )
    estimates["p_value_holm_within_horizon"] = np.nan
    for _horizon, index in estimates.groupby("horizon_days", sort=False).groups.items():
        estimates.loc[index, "p_value_holm_within_horizon"] = holm_adjusted_pvalues(
            estimates.loc[index, "p_value"]
        )
    support = pd.DataFrame(
        [
            {
                "row_type": "support",
                "daily_observations": int(len(data)),
                "date_start": data["date"].min().date().isoformat(),
                "date_end": data["date"].max().date().isoformat(),
                "count_activity": float(data["cnt_two_leg_stable"].sum()),
                "strict_value_activity_usd": float(
                    data["usd_within_20pct_two_leg_stable"].sum()
                ),
                "count_value_gap_correlation": float(
                    data[["count_gap", "strict_value_gap"]].corr().iloc[0, 1]
                ),
                "unit": "calendar_day",
                "comparison_set": "USDT_and_USDC_within_all_stablecoin_exact_two_leg_intermediary_activity",
            }
        ]
    )
    return pd.concat([support, estimates, method_assessment()], ignore_index=True, sort=False)


def run(input_path: Path = INPUT, output_path: Path = OUTPUT) -> Path:
    with current_artifacts([input_path], consumer="stable frequency-value dynamics E0"):
        panel = pd.read_parquet(input_path, columns=list(REQUIRED_COLUMNS))
        result = result_frame(panel)
        return write_exhibit(
            result,
            output_path,
            code_sources=CODE_SOURCES,
            inputs=[input_path],
            notes=(
                "E0 dynamic association between route-frequency and strict-supported routed-value leadership; "
                "seven-day count-to-value regression primary, one- and 30-day timing sensitivities, reverse direction diagnostic; "
                "Gopinath and Stein (2021) raw PDF pp. 5-6 supplies only the strategic-complementarity motivation; "
                "the observed dynamics are descriptive and cannot identify feedback or causality"
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        path = run(args.input, args.output)
    except RuntimeError as exc:
        print(f"INPUT BLOCKED: {exc}")
        return 2
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
