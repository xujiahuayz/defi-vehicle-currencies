#!/usr/bin/env python3
"""Screen dynamic feedback between local bridge depth and vehicle use.

The static bridge-liquidity screen asks whether local prior two-leg capital is
associated with route choice inside an endpoint-date-scope opportunity.  This
script follows the same source-candidate-target bridge forward in calendar time.
It asks two descriptive questions:

1. Does current route share predict later growth in that same local bridge?
2. Does current bridge depth predict later route-share gains in that same local
   bridge?

The design is predictive and descriptive.  It does not identify provider-flow
causality, active concentrated-liquidity depth, or all-in execution cost.
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
HORIZONS = (7, 30, 60, 120)
CODE_SOURCES = ["scripts/analyze/run_bridge_liquidity_feedback.py"]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/pool_capital_daily.parquet",
]


def build_bridge_liquidity_feedback_panel(
    panel: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    """Join each local bridge to its exact future horizon observation."""

    if not horizons:
        raise ValueError("at least one feedback horizon is required")
    work = panel.copy()
    work["candidate_pair_scope"] = (
        work["src"].astype(str)
        + "|"
        + work["tgt"].astype(str)
        + "|"
        + work["candidate_address"].astype(str)
        + "|"
        + work["integration_scope"].astype(str)
    )
    future = work.loc[
        :,
        [
            "candidate_pair_scope",
            "origin_date",
            "route_share_five",
            "selected_five",
            "log_bridge_min_capital",
            "bridge_min_capital_usd",
        ],
    ].rename(
        columns={
            "origin_date": "future_date",
            "route_share_five": "future_route_share_five",
            "selected_five": "future_selected_five",
            "log_bridge_min_capital": "future_log_bridge_min_capital",
            "bridge_min_capital_usd": "future_bridge_min_capital_usd",
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
        joined["future_delta_log_bridge_min_capital"] = (
            joined["future_log_bridge_min_capital"]
            - joined["log_bridge_min_capital"]
        )
        joined["future_delta_route_share_five"] = (
            joined["future_route_share_five"] - joined["route_share_five"]
        )
        frames.append(joined)
    if not frames:
        raise ValueError("bridge-liquidity feedback panel is empty")
    result = pd.concat(frames, ignore_index=True)
    numeric = [
        "route_share_five",
        "log_bridge_min_capital",
        "future_delta_log_bridge_min_capital",
        "future_delta_route_share_five",
        "five_route_total",
    ]
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if result.empty:
        raise ValueError("bridge-liquidity feedback panel lost all rows after validation")
    return result.reset_index(drop=True)


def bridge_liquidity_feedback_support_rows(feedback: pd.DataFrame) -> pd.DataFrame:
    """Summarize support by exact calendar horizon."""

    rows = []
    for horizon, group in feedback.groupby("horizon_days", sort=True):
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "horizon_days": int(horizon),
                "candidate_rows": int(len(group)),
                "choice_groups": int(group["choice_group_id"].nunique()),
                "ordered_pairs": int(group["ordered_pair"].nunique()),
                "days": int(group["origin_date"].nunique()),
                "candidates": int(group["candidate_address"].nunique()),
                "quantity": (
                    "same source-candidate-target bridge observed at the exact "
                    "future calendar horizon"
                ),
            }
        )
    return pd.DataFrame(rows)


def bridge_liquidity_feedback_regressions(
    feedback: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate dynamic local bridge-depth and route-share associations."""

    specs = (
        (
            "future_bridge_depth_growth",
            "future_delta_log_bridge_min_capital",
            ("route_share_five", "log_bridge_min_capital"),
            "Does current route share predict later growth in local bridge depth?",
        ),
        (
            "future_route_share_growth",
            "future_delta_route_share_five",
            ("log_bridge_min_capital", "route_share_five"),
            "Does current local bridge depth predict later route-share growth?",
        ),
    )
    rows: list[dict[str, object]] = []
    for horizon, horizon_data in feedback.groupby("horizon_days", sort=True):
        for model_id, outcome, regressors, question in specs:
            columns = [
                outcome,
                *regressors,
                "candidate_address",
                "origin_date",
                "ordered_pair",
                "five_route_total",
            ]
            data = (
                horizon_data.loc[:, columns]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .copy()
            )
            residual = absorb_fixed_effects(
                data[[outcome, *regressors]],
                data["candidate_address"],
                data["origin_date"],
                weights=data["five_route_total"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[list(regressors)],
                data["ordered_pair"],
                add_constant=False,
                absorbed_groups=(data["candidate_address"], data["origin_date"]),
                additional_clusters=(data["origin_date"],),
                weights=data["five_route_total"],
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
                        "question": question,
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "regressor": regressor,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(fit.t_statistics[index]),
                        "p_value": float(fit.p_values[index]),
                        "effect_for_10pp_route_share": (
                            0.1 * coefficient if regressor == "route_share_five" else None
                        ),
                        "effect_pp_per_log_point": (
                            100.0 * coefficient
                            if outcome == "future_delta_route_share_five"
                            and regressor == "log_bridge_min_capital"
                            else None
                        ),
                        "n_observations": int(fit.n_observations),
                        "ordered_pair_clusters": int(fit.cluster_counts[0]),
                        "date_clusters": int(fit.cluster_counts[1]),
                        "fixed_effects": "candidate+origin_date",
                        "covariance": "two_way_ordered_pair_date_cr1",
                        "weight": "five_candidate_route_count",
                        "interpretation": (
                            "same-bridge predictive association; not provider-flow "
                            "causality or executable depth"
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
    result = pd.concat(
        [
            bridge_liquidity_feedback_support_rows(feedback),
            bridge_liquidity_feedback_regressions(feedback),
        ],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(
        bridge_liquidity_feedback_support_rows(feedback),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(result):,} bridge-feedback rows over "
        f"{feedback['candidate_pair_scope'].nunique():,} local bridges"
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
