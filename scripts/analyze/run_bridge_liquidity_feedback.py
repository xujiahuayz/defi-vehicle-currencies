#!/usr/bin/env python3
"""Estimate dynamic comovement between local bridge depth and vehicle use.

The unit is a source--candidate--destination bridge on a calendar date.  The
forward specifications estimate future levels, rather than changes or a
route-minus-capital gap:

    B[b,t+h] = beta_R R[b,t] + f(B[b,t]) + bridge FE + date FE + error
    R[b,t+h] = beta_B B[b,t] + f(R[b,t]) + bridge FE + date FE + error

``B`` is log weak-leg deposited capital and ``R`` is the candidate's share of
five-vehicle route activity.  Cubic initial-state controls remove the direct
mathematical coupling that arises when the current level is embedded with a
negative sign in a change outcome.  Time-reversed specifications replace the
dated predictor with its end-of-window lead and provide a symmetric benchmark.
Every specification is estimated with bridge and date
fixed effects under both equal pair-date-scope and route-activity weights.

The estimates remain predictive.  Deposited capital is not executable depth,
and common expected demand can move route use and capital together.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import OUTPUT_DIR
from ddvc.tables import write_exhibit
from scripts.analyze.run_bridge_liquidity_dominance import (
    CHOICES_INPUT,
    POOL_CAPITAL_INPUT,
    load_bridge_liquidity_panel,
)


RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_feedback.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_feedback_support.jsonl"
HORIZONS = (30, 60, 120)
WEIGHT_SCHEMES = ("pair", "activity")
CODE_SOURCES = ["scripts/analyze/run_bridge_liquidity_feedback.py"]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/pool_capital_daily.parquet",
]


def _bridge_identifier(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["src"].astype(str)
        + "|"
        + frame["tgt"].astype(str)
        + "|"
        + frame["candidate_address"].astype(str)
        + "|"
        + frame["integration_scope"].astype(str)
    )


def build_bridge_liquidity_feedback_panel(
    panel: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    """Build exact-horizon forward and end-of-window benchmark observations."""

    if not horizons or any(int(value) <= 0 for value in horizons):
        raise ValueError("feedback horizons must be positive calendar-day counts")
    work = panel.copy()
    work["origin_date"] = pd.to_datetime(work["origin_date"]).dt.normalize()
    work["candidate_pair_scope"] = _bridge_identifier(work)
    key = ["candidate_pair_scope", "origin_date"]
    if work.duplicated(key).any():
        raise ValueError("bridge-liquidity panel is not unique by bridge and date")

    future = work.loc[
        :,
        [
            "candidate_pair_scope",
            "origin_date",
            "route_share_five",
            "selected_five",
            "log_bridge_min_capital",
            "bridge_min_capital_usd",
            "five_route_total",
            "choice_group_id",
        ],
    ].rename(
        columns={
            "origin_date": "future_date",
            "route_share_five": "future_route_share_five",
            "selected_five": "future_selected_five",
            "log_bridge_min_capital": "future_log_bridge_min_capital",
            "bridge_min_capital_usd": "future_bridge_min_capital_usd",
            "five_route_total": "future_five_route_total",
            "choice_group_id": "future_choice_group_id",
        }
    )

    frames: list[pd.DataFrame] = []
    for horizon in horizons:
        current = work.copy()
        current["horizon_days"] = int(horizon)
        current["future_date"] = current["origin_date"] + pd.Timedelta(days=horizon)
        joined = current.merge(
            future,
            on=["candidate_pair_scope", "future_date"],
            how="inner",
            validate="one_to_one",
        )
        if joined.empty:
            continue

        forward = joined.copy()
        forward["timing"] = "forward"
        forward["analysis_date"] = forward["origin_date"]
        forward["depth_outcome"] = forward["future_log_bridge_min_capital"]
        forward["route_share_outcome"] = forward["future_route_share_five"]
        forward["route_share_predictor"] = forward["route_share_five"]
        forward["depth_predictor"] = forward["log_bridge_min_capital"]
        forward["initial_depth"] = forward["log_bridge_min_capital"]
        forward["initial_route_share"] = forward["route_share_five"]
        forward["weight_group_id"] = forward["choice_group_id"]
        forward["weight_activity"] = forward["five_route_total"]

        reversed_window = joined.copy()
        reversed_window["timing"] = "time_reversed"
        reversed_window["analysis_date"] = reversed_window["future_date"]
        reversed_window["depth_outcome"] = reversed_window[
            "log_bridge_min_capital"
        ]
        reversed_window["route_share_outcome"] = reversed_window[
            "route_share_five"
        ]
        reversed_window["route_share_predictor"] = reversed_window[
            "future_route_share_five"
        ]
        reversed_window["depth_predictor"] = reversed_window[
            "future_log_bridge_min_capital"
        ]
        reversed_window["initial_depth"] = reversed_window[
            "future_log_bridge_min_capital"
        ]
        reversed_window["initial_route_share"] = reversed_window[
            "future_route_share_five"
        ]
        reversed_window["weight_group_id"] = reversed_window[
            "future_choice_group_id"
        ]
        reversed_window["weight_activity"] = reversed_window[
            "future_five_route_total"
        ]
        frames.extend((forward, reversed_window))

    if not frames:
        raise ValueError("bridge-liquidity feedback panel is empty")
    result = pd.concat(frames, ignore_index=True)
    result["stable_candidate"] = result["is_stable"].astype(float)
    numeric = [
        "depth_outcome",
        "route_share_outcome",
        "route_share_predictor",
        "depth_predictor",
        "initial_depth",
        "initial_route_share",
        "weight_activity",
    ]
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if result.empty:
        raise ValueError("bridge-liquidity feedback panel lost all rows after validation")
    if (result["weight_activity"] <= 0).any():
        raise ValueError("bridge-liquidity feedback activity weights must be positive")
    return result.reset_index(drop=True)


def bridge_liquidity_feedback_support_rows(feedback: pd.DataFrame) -> pd.DataFrame:
    """Summarize support separately by timing and exact calendar horizon."""

    rows = []
    for (timing, horizon), group in feedback.groupby(
        ["timing", "horizon_days"], sort=True
    ):
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "timing": str(timing),
                "horizon_days": int(horizon),
                "candidate_rows": int(len(group)),
                "choice_groups": int(group["weight_group_id"].nunique()),
                "local_bridges": int(group["candidate_pair_scope"].nunique()),
                "ordered_pairs": int(group["ordered_pair"].nunique()),
                "days": int(group["analysis_date"].nunique()),
                "candidates": int(group["candidate_address"].nunique()),
                "quantity": (
                    "continuing positive-depth candidate bridge with active "
                    "five-vehicle routes at both exact dates"
                ),
            }
        )
    return pd.DataFrame(rows)


def _flexible_initial_controls(
    values: pd.Series,
    *,
    prefix: str,
) -> pd.DataFrame:
    """Return a numerically stable cubic in the initial outcome level."""

    numeric = values.astype(float)
    center = float(numeric.median())
    scale = float(numeric.quantile(0.75) - numeric.quantile(0.25))
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = float(numeric.std(ddof=0))
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = 1.0
    standardized = (numeric - center) / scale
    return pd.DataFrame(
        {
            f"{prefix}_linear": standardized,
            f"{prefix}_squared": standardized.pow(2),
            f"{prefix}_cubed": standardized.pow(3),
        },
        index=values.index,
    )


def _model_weights(data: pd.DataFrame, scheme: str) -> pd.Series:
    """Make each pair-date-scope sum to one or to its route activity."""

    candidates_per_group = data.groupby("weight_group_id")[
        "candidate_pair_scope"
    ].transform("size")
    if (candidates_per_group <= 0).any():
        raise ValueError("feedback weight groups cannot be empty")
    if scheme == "pair":
        weights = 1.0 / candidates_per_group.astype(float)
    elif scheme == "activity":
        weights = data["weight_activity"].astype(float) / candidates_per_group
    else:
        raise ValueError(f"unknown feedback weight scheme: {scheme}")
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("feedback regression weights must be finite and positive")
    return weights


def bridge_liquidity_feedback_regressions(
    feedback: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate forward level models and symmetric time-reversed benchmarks."""

    specifications = (
        (
            "future_bridge_depth_level",
            "depth_outcome",
            "route_share_predictor",
            "initial_depth",
            "all_candidates",
            "Current route share and later local bridge depth",
        ),
        (
            "future_bridge_depth_level_stable_candidate",
            "depth_outcome",
            "route_share_predictor",
            "initial_depth",
            "stable_candidates",
            "Current stablecoin route share and later local bridge depth",
        ),
        (
            "future_route_share_level",
            "route_share_outcome",
            "depth_predictor",
            "initial_route_share",
            "all_candidates",
            "Current local bridge depth and later route share",
        ),
        (
            "future_route_share_level_stable_candidate",
            "route_share_outcome",
            "depth_predictor",
            "initial_route_share",
            "stable_candidates",
            "Current stablecoin bridge depth and later route share",
        ),
    )
    rows: list[dict[str, object]] = []
    for (timing, horizon), horizon_data in feedback.groupby(
        ["timing", "horizon_days"], sort=True
    ):
        for (
            model_id,
            outcome,
            focal_regressor,
            initial_level,
            sample_id,
            question,
        ) in specifications:
            sample = horizon_data
            if sample_id == "stable_candidates":
                sample = sample[sample["stable_candidate"].eq(1.0)]
            columns = [
                outcome,
                focal_regressor,
                initial_level,
                "candidate_pair_scope",
                "analysis_date",
                "ordered_pair",
                "weight_group_id",
                "weight_activity",
            ]
            data = (
                sample.loc[:, columns]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            flexible = _flexible_initial_controls(
                data[initial_level], prefix=initial_level
            )
            data = pd.concat([data, flexible], axis=1)
            controls = list(flexible.columns)
            regressors = [focal_regressor, *controls]
            for weight_scheme in WEIGHT_SCHEMES:
                weights = _model_weights(data, weight_scheme)
                residual = absorb_fixed_effects(
                    data[[outcome, *regressors]],
                    data["candidate_pair_scope"],
                    data["analysis_date"],
                    weights=weights,
                )
                fit = ols_clustered(
                    residual[outcome],
                    residual[regressors],
                    data["ordered_pair"],
                    add_constant=False,
                    absorbed_groups=(
                        data["candidate_pair_scope"],
                        data["analysis_date"],
                    ),
                    additional_clusters=(data["analysis_date"],),
                    weights=weights,
                    min_observations=min_observations,
                    min_clusters=min_clusters,
                )
                for index, regressor in enumerate(regressors):
                    coefficient = float(fit.beta[index])
                    standard_error = float(fit.standard_errors[index])
                    rows.append(
                        {
                            "claim_status": "provisional_exploratory",
                            "record_type": "bridge_liquidity_feedback_regression",
                            "model_id": model_id,
                            "sample_id": sample_id,
                            "question": question,
                            "timing": str(timing),
                            "horizon_days": int(horizon),
                            "outcome": outcome,
                            "regressor": regressor,
                            "focal_regressor": regressor == focal_regressor,
                            "coefficient": coefficient,
                            "standard_error": standard_error,
                            "t_statistic": float(fit.t_statistics[index]),
                            "p_value": float(fit.p_values[index]),
                            "effect_for_10pp_route_share": (
                                0.1 * coefficient
                                if regressor == "route_share_predictor"
                                else None
                            ),
                            "effect_pp_per_log_point": (
                                100.0 * coefficient
                                if regressor == "depth_predictor"
                                else None
                            ),
                            "n_observations": int(fit.n_observations),
                            "local_bridges": int(
                                data["candidate_pair_scope"].nunique()
                            ),
                            "ordered_pair_clusters": int(fit.cluster_counts[0]),
                            "date_clusters": int(fit.cluster_counts[1]),
                            "fixed_effects": "local_bridge+analysis_date",
                            "initial_level_controls": (
                                f"cubic_standardized_{initial_level}"
                            ),
                            "covariance": "two_way_ordered_pair_date_cr1",
                            "weight_scheme": weight_scheme,
                            "weight": (
                                "equal_pair_date_scope"
                                if weight_scheme == "pair"
                                else "five_candidate_route_count"
                            ),
                            "r_squared_within": float(fit.r_squared),
                            "interpretation": (
                                "forward conditional level association"
                                if timing == "forward"
                                else "time-reversed end-of-window predictor benchmark"
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def run(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    panel = load_bridge_liquidity_panel(
        choices_path=choices_path,
        pool_capital_path=pool_capital_path,
    )
    feedback = build_bridge_liquidity_feedback_panel(panel)
    support = bridge_liquidity_feedback_support_rows(feedback)
    result = pd.concat(
        [support, bridge_liquidity_feedback_regressions(feedback)],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    forward = feedback[feedback["timing"].eq("forward")]
    print(
        f"wrote {len(result):,} bridge-depth rows over "
        f"{forward['candidate_pair_scope'].nunique():,} local bridges"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pool_capital_path=args.pool_capital,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
