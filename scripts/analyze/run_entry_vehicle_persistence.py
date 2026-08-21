#!/usr/bin/env python3
"""Estimate vehicle persistence in disjoint windows after pair entry.

The older formation exploration includes the entry day in its follow-up totals
and defines the 120-day outcome cumulatively over days 0--120.  Those outcomes
partly restate the entry state and cannot distinguish early retention from
later persistence.  This analysis instead uses two disjoint windows, days
1--30 and days 31--120. Stable-share outcomes use pairs that trade again;
separate models report whether trading recurs. Estimates are reported with
equal-pair and route-activity weights.

The regression output is tidy by model column: every coefficient row carries a
stable ``model_id`` and ``column_order`` so the table renderer need not select
one-off results from a mixed exploration ledger.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import ols_clustered
from ddvc.asset_types import classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output


PAIR_SUPPORT = DATA_DIR / "processed/endpoint_candidate_pair_support.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/entry_vehicle_persistence_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/entry_vehicle_persistence_support.jsonl"
SAMPLE_END = pd.Timestamp("2026-06-30")
ENTRY_YEARS = (2024, 2026)
MAX_FOLLOWUP_DAY = 120
ROBUSTNESS_MIN_OBSERVATIONS = 400


@dataclass(frozen=True)
class FollowupWindow:
    window_id: str
    start_day: int
    end_day: int


WINDOWS = (
    FollowupWindow("days_1_30", 1, 30),
    FollowupWindow("days_31_120", 31, 120),
)

BASE_CONTROLS = (
    "is_2026",
    "stable_endpoint",
    "log_entry_routes",
    "entry_direct_share",
    "entry_complex_share",
)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    column_order: int
    window_id: str
    weighting: str
    controls: bool
    min_entry_routes: int = 1


MODEL_SPECS = (
    ModelSpec("m1_early_pair", 1, "days_1_30", "equal_pair", False),
    ModelSpec("m2_early_pair_controls", 2, "days_1_30", "equal_pair", True),
    ModelSpec(
        "m3_early_activity_controls",
        3,
        "days_1_30",
        "post_entry_route_activity",
        True,
    ),
    ModelSpec("m4_late_pair", 4, "days_31_120", "equal_pair", False),
    ModelSpec(
        "m5_late_pair_controls",
        5,
        "days_31_120",
        "equal_pair",
        True,
    ),
    ModelSpec(
        "m6_late_activity_controls",
        6,
        "days_31_120",
        "post_entry_route_activity",
        True,
    ),
    ModelSpec(
        "m7_early_pair_controls_min5",
        7,
        "days_1_30",
        "equal_pair",
        True,
        5,
    ),
    ModelSpec(
        "m8_early_pair_controls_min10",
        8,
        "days_1_30",
        "equal_pair",
        True,
        10,
    ),
    ModelSpec(
        "m9_late_pair_controls_min5",
        9,
        "days_31_120",
        "equal_pair",
        True,
        5,
    ),
    ModelSpec(
        "m10_late_pair_controls_min10",
        10,
        "days_31_120",
        "equal_pair",
        True,
        10,
    ),
)

RETRADE_MODEL_SPECS = (
    ModelSpec(
        "r1_early_retrade_controls",
        1,
        "days_1_30",
        "equal_pair",
        True,
    ),
    ModelSpec(
        "r2_late_retrade_controls",
        2,
        "days_31_120",
        "equal_pair",
        True,
    ),
)


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _read_sql(query: str) -> pd.DataFrame:
    connection = duckdb.connect()
    try:
        return connection.execute(query).fetchdf()
    finally:
        connection.close()


def _require_finite_fit(fit: object, model_id: str) -> None:
    """Reject model columns whose estimator returned placeholder NaNs."""

    arrays = (
        np.asarray(fit.beta, dtype=float),
        np.asarray(fit.standard_errors, dtype=float),
        np.asarray(fit.t_statistics, dtype=float),
        np.asarray(fit.p_values, dtype=float),
        np.asarray([fit.r_squared, fit.adjusted_r_squared], dtype=float),
    )
    if not all(np.isfinite(values).all() for values in arrays):
        raise ValueError(f"{model_id} produced a nonfinite regression fit")


def _endpoint_flags(src: object, tgt: object) -> tuple[bool, bool]:
    _src_symbol, src_type = classify(src)
    _tgt_symbol, tgt_type = classify(tgt)
    types = {src_type, tgt_type}
    return "native" in types, "stable" in types


def build_post_entry_panel(
    pair_support_path: Path = PAIR_SUPPORT,
    *,
    sample_end: pd.Timestamp = SAMPLE_END,
    entry_years: tuple[int, ...] = ENTRY_YEARS,
) -> pd.DataFrame:
    """Build one ordered-pair row per disjoint post-entry window.

    Every entrant must have a complete 120-calendar-day follow-up.  Pairs with
    no activity remain in the panel with ``retraded=False`` so attrition is
    visible, while their persistence outcome is missing by construction.
    """

    if not entry_years:
        raise ValueError("entry_years cannot be empty")
    if not pair_support_path.is_file():
        raise FileNotFoundError(pair_support_path)
    path = _sql_path(pair_support_path)
    years = ", ".join(str(int(year)) for year in entry_years)
    sample_end = pd.Timestamp(sample_end).normalize()
    sample_end_text = sample_end.strftime("%Y-%m-%d")
    common_entry_cutoff = sample_end - pd.Timedelta(days=MAX_FOLLOWUP_DAY)
    common_entry_cutoff_mm_dd = common_entry_cutoff.strftime("%m-%d")
    wide = _read_sql(
        f"""
        WITH entries AS (
            SELECT
                CAST(date AS DATE) AS entry_date,
                src,
                tgt,
                year(date)::INTEGER AS entry_year,
                primary_choice_route_count::DOUBLE AS entry_primary_routes,
                stable_choice_route_count::DOUBLE AS entry_stable_routes,
                native_choice_route_count::DOUBLE AS entry_native_routes,
                direct_route_count::DOUBLE AS entry_direct_routes,
                (
                    multiple_intermediary_route_count
                    + split_or_join_route_count
                    + nonsequential_two_leg_route_count
                )::DOUBLE AS entry_complex_routes,
                market_route_count::DOUBLE AS entry_market_routes
            FROM read_parquet('{path}')
            WHERE pair_entry_on_day
              AND primary_choice_route_count > 0
              AND year(date) IN ({years})
              AND strftime(date, '%m-%d') <= '{common_entry_cutoff_mm_dd}'
              AND date + INTERVAL {MAX_FOLLOWUP_DAY} DAY
                    <= DATE '{sample_end_text}'
        ),
        follow AS (
            SELECT
                e.*,
                sum(p.primary_choice_route_count) FILTER (
                    WHERE p.date <= e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS early_primary_routes,
                sum(p.stable_choice_route_count) FILTER (
                    WHERE p.date <= e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS early_stable_routes,
                sum(p.native_choice_route_count) FILTER (
                    WHERE p.date <= e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS early_native_routes,
                count(*) FILTER (
                    WHERE p.date <= e.entry_date + INTERVAL 30 DAY
                )::INTEGER AS early_active_days,
                sum(p.primary_choice_route_count) FILTER (
                    WHERE p.date > e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS late_primary_routes,
                sum(p.stable_choice_route_count) FILTER (
                    WHERE p.date > e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS late_stable_routes,
                sum(p.native_choice_route_count) FILTER (
                    WHERE p.date > e.entry_date + INTERVAL 30 DAY
                )::DOUBLE AS late_native_routes,
                count(*) FILTER (
                    WHERE p.date > e.entry_date + INTERVAL 30 DAY
                )::INTEGER AS late_active_days
            FROM entries e
            LEFT JOIN read_parquet('{path}') p
              ON p.src = e.src
             AND p.tgt = e.tgt
             AND p.date > e.entry_date
             AND p.date <= e.entry_date + INTERVAL {MAX_FOLLOWUP_DAY} DAY
             AND p.primary_choice_route_count > 0
            GROUP BY ALL
        )
        SELECT *
        FROM follow
        ORDER BY entry_date, src, tgt
        """
    )
    if wide.empty:
        raise ValueError("post-entry persistence panel has no complete entrants")
    if wide.duplicated(["entry_date", "src", "tgt"]).any():
        raise ValueError("post-entry persistence panel has duplicate entrants")

    flags = [_endpoint_flags(src, tgt) for src, tgt in zip(wide["src"], wide["tgt"])]
    wide["native_endpoint"] = [flag[0] for flag in flags]
    wide["stable_endpoint"] = [float(flag[1]) for flag in flags]
    wide = wide[~wide["native_endpoint"]].copy()
    if wide.empty:
        raise ValueError("post-entry persistence panel has no non-native entrants")

    wide["entry_date"] = pd.to_datetime(wide["entry_date"])
    wide["sample_end"] = sample_end
    wide["common_entry_calendar_cutoff_mm_dd"] = common_entry_cutoff_mm_dd
    wide["entry_stable_share"] = (
        wide["entry_stable_routes"] / wide["entry_primary_routes"]
    )
    wide["entry_stable_dominant"] = (
        wide["entry_stable_routes"] > wide["entry_native_routes"]
    ).astype(float)
    wide["is_2026"] = wide["entry_year"].eq(2026).astype(float)
    wide["log_entry_routes"] = np.log1p(wide["entry_primary_routes"])
    market_routes = wide["entry_market_routes"].replace(0, np.nan)
    wide["entry_direct_share"] = (
        wide["entry_direct_routes"] / market_routes
    ).fillna(0.0).clip(0.0, 1.0)
    wide["entry_complex_share"] = (
        wide["entry_complex_routes"] / market_routes
    ).fillna(0.0).clip(0.0, 1.0)

    window_frames: list[pd.DataFrame] = []
    for window, prefix in zip(WINDOWS, ("early", "late"), strict=True):
        frame = wide.copy()
        frame["window_id"] = window.window_id
        frame["window_start_day"] = window.start_day
        frame["window_end_day"] = window.end_day
        frame["post_primary_routes"] = frame[f"{prefix}_primary_routes"].fillna(0.0)
        frame["post_stable_routes"] = frame[f"{prefix}_stable_routes"].fillna(0.0)
        frame["post_native_routes"] = frame[f"{prefix}_native_routes"].fillna(0.0)
        frame["post_active_days"] = frame[f"{prefix}_active_days"].fillna(0).astype(int)
        frame["retraded"] = frame["post_primary_routes"].gt(0)
        frame["post_stable_share"] = np.where(
            frame["retraded"],
            frame["post_stable_routes"] / frame["post_primary_routes"],
            np.nan,
        )
        frame["post_stable_dominant"] = np.where(
            frame["retraded"],
            (frame["post_stable_routes"] > frame["post_native_routes"]).astype(float),
            np.nan,
        )
        window_frames.append(frame)

    panel = pd.concat(window_frames, ignore_index=True, sort=False)
    keep = [
        "entry_date",
        "src",
        "tgt",
        "entry_year",
        "sample_end",
        "common_entry_calendar_cutoff_mm_dd",
        "window_id",
        "window_start_day",
        "window_end_day",
        "entry_primary_routes",
        "entry_stable_routes",
        "entry_native_routes",
        "entry_stable_share",
        "entry_stable_dominant",
        "is_2026",
        "stable_endpoint",
        "log_entry_routes",
        "entry_direct_share",
        "entry_complex_share",
        "post_primary_routes",
        "post_stable_routes",
        "post_native_routes",
        "post_active_days",
        "retraded",
        "post_stable_share",
        "post_stable_dominant",
    ]
    panel = panel[keep].sort_values(
        ["window_start_day", "entry_date", "src", "tgt"]
    ).reset_index(drop=True)
    observed = panel.loc[panel["retraded"], "post_stable_share"]
    if ((observed < -1e-12) | (observed > 1 + 1e-12)).any():
        raise ValueError("post-entry stable share is outside [0, 1]")
    return panel


def sample_support(panel: pd.DataFrame) -> pd.DataFrame:
    """Report eligible entrants and retrading attrition by window and cohort."""

    required = {
        "window_id",
        "window_start_day",
        "window_end_day",
        "entry_year",
        "entry_date",
        "sample_end",
        "common_entry_calendar_cutoff_mm_dd",
        "retraded",
        "post_primary_routes",
        "post_active_days",
        "post_stable_share",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"post-entry panel lacks support columns: {missing}")
    rows: list[dict[str, object]] = []
    for window_id, window in panel.groupby("window_id", sort=False):
        groups: list[tuple[str, pd.DataFrame]] = [("all", window)]
        groups.extend(
            (str(int(year)), group)
            for year, group in window.groupby("entry_year", sort=True)
        )
        for cohort, group in groups:
            active = group[group["retraded"]].copy()
            activity = float(active["post_primary_routes"].sum())
            rows.append(
                {
                    "record_type": "post_entry_persistence_support",
                    "window_id": str(window_id),
                    "window_start_day": int(group["window_start_day"].iloc[0]),
                    "window_end_day": int(group["window_end_day"].iloc[0]),
                    "entry_year": cohort,
                    "eligible_pairs": int(len(group)),
                    "retrading_pairs": int(len(active)),
                    "nonretrading_pairs": int(len(group) - len(active)),
                    "retrade_rate": float(len(active) / len(group)),
                    "post_primary_routes": activity,
                    "mean_active_days_retraders": (
                        float(active["post_active_days"].mean())
                        if len(active)
                        else np.nan
                    ),
                    "equal_pair_stable_share": (
                        float(active["post_stable_share"].mean())
                        if len(active)
                        else np.nan
                    ),
                    "activity_weighted_stable_share": (
                        float(
                            np.average(
                                active["post_stable_share"],
                                weights=active["post_primary_routes"],
                            )
                        )
                        if activity > 0
                        else np.nan
                    ),
                    "entry_date_min": group["entry_date"].min(),
                    "entry_date_max": group["entry_date"].max(),
                    "sample_end": group["sample_end"].iloc[0],
                    "common_entry_calendar_cutoff_mm_dd": group[
                        "common_entry_calendar_cutoff_mm_dd"
                    ].iloc[0],
                    "entry_day_excluded": True,
                    "entry_state_measurement": "entry_day_only",
                    "retrading_required_for_outcome": True,
                    "complete_through_day": MAX_FOLLOWUP_DAY,
                }
            )
    return pd.DataFrame(rows)


def fit_persistence_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit the declared model columns on retrading pairs only."""

    required = {
        "entry_date",
        "window_id",
        "retraded",
        "post_primary_routes",
        "post_stable_share",
        "entry_primary_routes",
        "entry_stable_share",
        *BASE_CONTROLS,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"post-entry panel lacks regression columns: {missing}")
    support = sample_support(panel)
    all_support = support[support["entry_year"].eq("all")].set_index("window_id")
    rows: list[dict[str, object]] = []
    for spec in MODEL_SPECS:
        predictors = ["entry_stable_share"]
        if spec.controls:
            predictors.extend(BASE_CONTROLS)
        eligible = panel[
            panel["window_id"].eq(spec.window_id)
            & panel["entry_primary_routes"].ge(spec.min_entry_routes)
        ].copy()
        sample = eligible[eligible["retraded"]].copy()
        sample = sample[
            ["entry_date", "post_primary_routes", "post_stable_share", *predictors]
        ].replace([np.inf, -np.inf], np.nan).dropna()
        if sample.empty:
            raise ValueError(f"{spec.model_id} has no retrading pairs")
        weights = (
            sample["post_primary_routes"]
            if spec.weighting == "post_entry_route_activity"
            else None
        )
        required_observations = (
            min(min_observations, ROBUSTNESS_MIN_OBSERVATIONS)
            if spec.min_entry_routes > 1
            else min_observations
        )
        fit = ols_clustered(
            sample["post_stable_share"].astype(float),
            sample[predictors].astype(float),
            sample["entry_date"],
            weights=weights,
            min_observations=required_observations,
            min_clusters=min_clusters,
        )
        _require_finite_fit(fit, spec.model_id)
        names = ["constant", *predictors]
        window_support = all_support.loc[spec.window_id]
        eligible_pairs = int(len(eligible))
        retrading_pairs = int(eligible["retraded"].sum())
        dependent_mean = (
            float(
                np.average(
                    sample["post_stable_share"],
                    weights=sample["post_primary_routes"],
                )
            )
            if spec.weighting == "post_entry_route_activity"
            else float(sample["post_stable_share"].mean())
        )
        for name, beta, se, t_stat, p_value in zip(
            names,
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "post_entry_persistence_model_coefficient",
                    "table_id": "post_entry_stable_share",
                    "model_id": spec.model_id,
                    "column_order": spec.column_order,
                    "window_id": spec.window_id,
                    "window_start_day": int(window_support["window_start_day"]),
                    "window_end_day": int(window_support["window_end_day"]),
                    "outcome": "post_stable_share",
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "effect_pp_per_10pp": (
                        10.0 * float(beta)
                        if name == "entry_stable_share"
                        else np.nan
                    ),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "standard_error_pp_per_10pp": (
                        10.0 * float(se)
                        if name == "entry_stable_share"
                        else np.nan
                    ),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "r_squared": float(fit.r_squared),
                    "adjusted_r_squared": float(fit.adjusted_r_squared),
                    "dependent_mean": dependent_mean,
                    "weighting": spec.weighting,
                    "minimum_entry_routes": spec.min_entry_routes,
                    "minimum_required_observations": required_observations,
                    "specification_role": (
                        "entry_route_threshold_robustness"
                        if spec.min_entry_routes > 1
                        else "main"
                    ),
                    "controls_included": spec.controls,
                    "controls": ",".join(BASE_CONTROLS) if spec.controls else "none",
                    "covariance_id": "entry_date_cluster_cr1",
                    "eligible_pairs": eligible_pairs,
                    "retrading_pairs": retrading_pairs,
                    "retrade_rate": retrading_pairs / eligible_pairs,
                    "common_entry_calendar_cutoff_mm_dd": window_support[
                        "common_entry_calendar_cutoff_mm_dd"
                    ],
                    "entry_day_excluded": True,
                    "entry_state_measurement": "entry_day_only",
                    "retrading_required": True,
                    "complete_through_day": MAX_FOLLOWUP_DAY,
                    "inference_status": "provisional_descriptive",
                    "inference_note": (
                        "entry-date CR1 inference; current price and depth are "
                        "examined in the contestable-choice analysis"
                    ),
                }
            )
    result = pd.DataFrame(rows).sort_values(
        ["column_order", "predictor"]
    ).reset_index(drop=True)
    if result["column_order"].nunique() != len(MODEL_SPECS):
        raise ValueError("post-entry persistence output lost a model column")
    return result


def fit_retrade_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate subsequent-trading incidence on every eligible entrant."""

    required = {
        "entry_date",
        "window_id",
        "retraded",
        "entry_stable_share",
        *BASE_CONTROLS,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"post-entry panel lacks retrading columns: {missing}")
    support = sample_support(panel)
    all_support = support[support["entry_year"].eq("all")].set_index("window_id")
    rows: list[dict[str, object]] = []
    predictors = ["entry_stable_share", *BASE_CONTROLS]
    for spec in RETRADE_MODEL_SPECS:
        sample = panel[panel["window_id"].eq(spec.window_id)].copy()
        sample = sample[
            ["entry_date", "retraded", *predictors]
        ].replace([np.inf, -np.inf], np.nan).dropna()
        if sample.empty:
            raise ValueError(f"{spec.model_id} has no eligible pairs")
        outcome = sample["retraded"].astype(float)
        fit = ols_clustered(
            outcome,
            sample[predictors].astype(float),
            sample["entry_date"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        _require_finite_fit(fit, spec.model_id)
        window_support = all_support.loc[spec.window_id]
        for name, beta, se, t_stat, p_value in zip(
            ["constant", *predictors],
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "post_entry_retrade_model_coefficient",
                    "table_id": "post_entry_retrade_probability",
                    "model_id": spec.model_id,
                    "column_order": spec.column_order,
                    "window_id": spec.window_id,
                    "window_start_day": int(window_support["window_start_day"]),
                    "window_end_day": int(window_support["window_end_day"]),
                    "outcome": "retraded",
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "effect_pp_per_10pp": (
                        10.0 * float(beta)
                        if name == "entry_stable_share"
                        else np.nan
                    ),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "standard_error_pp_per_10pp": (
                        10.0 * float(se)
                        if name == "entry_stable_share"
                        else np.nan
                    ),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "r_squared": float(fit.r_squared),
                    "adjusted_r_squared": float(fit.adjusted_r_squared),
                    "dependent_mean": float(outcome.mean()),
                    "weighting": "equal_pair",
                    "controls_included": True,
                    "controls": ",".join(BASE_CONTROLS),
                    "covariance_id": "entry_date_cluster_cr1",
                    "eligible_pairs": int(window_support["eligible_pairs"]),
                    "retrading_pairs": int(window_support["retrading_pairs"]),
                    "nonretrading_pairs": int(window_support["nonretrading_pairs"]),
                    "retrade_rate": float(window_support["retrade_rate"]),
                    "common_entry_calendar_cutoff_mm_dd": window_support[
                        "common_entry_calendar_cutoff_mm_dd"
                    ],
                    "entry_day_excluded": True,
                    "entry_state_measurement": "entry_day_only",
                    "retrading_required": False,
                    "complete_through_day": MAX_FOLLOWUP_DAY,
                    "inference_status": "provisional_descriptive",
                    "inference_note": (
                        "entry-date CR1 inference; current price and depth are "
                        "examined in the contestable-choice analysis"
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["column_order", "predictor"]
    ).reset_index(drop=True)


def run(
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    sample_end: pd.Timestamp = SAMPLE_END,
) -> int:
    panel = build_post_entry_panel(pair_support_path, sample_end=sample_end)
    support = sample_support(panel)
    models = pd.concat(
        [fit_persistence_models(panel), fit_retrade_models(panel)],
        ignore_index=True,
        sort=False,
    )
    model_output.parent.mkdir(parents=True, exist_ok=True)
    support_output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(model_output) as temporary:
        models.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    with atomic_output(support_output) as temporary:
        support.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    print(
        f"wrote {len(models):,} coefficient rows and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--sample-end", type=pd.Timestamp, default=SAMPLE_END)
    args = parser.parse_args()
    return run(
        pair_support_path=args.pair_support,
        model_output=args.model_output,
        support_output=args.support_output,
        sample_end=args.sample_end,
    )


if __name__ == "__main__":
    raise SystemExit(main())
