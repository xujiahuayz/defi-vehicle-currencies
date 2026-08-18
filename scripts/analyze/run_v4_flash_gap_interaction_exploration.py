#!/usr/bin/env python3
"""Estimate whether V4 flash accounting conditions the LP response to stable gaps.

Reads:
  data/processed/liquidity_capital_v2_candidate_day.parquet
  data/processed/v4_flash_accounting_candidate_daily.parquet
  data/processed/v4_lp_flow_candidate_daily.parquet
  data/processed/v4_lp_action_candidate_daily.parquet
  data/processed/v4_candidate_linked_pool_tvl_daily.parquet

Writes:
  output/exhibits/v4_flash_gap_interaction_exploration.jsonl
  output/exhibits/v4_flash_gap_interaction_support.jsonl

The unit is a stable-candidate V4-active origin day.  The estimating question is
whether a route-minus-capital gap has a different future LP association when the
same candidate-day also has more singleton internal routing, multi-leg routing,
or gross-to-net settlement reduction.  This is exploratory mechanism evidence,
not a causal provider-response design.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit
from scripts.analyze.run_liquidity_provision_behavior_exploration import (
    CANDIDATE_DAY_INPUT,
    candidate_share_gap_panel,
    load_candidate_day,
    supported_candidate_days,
)
from scripts.analyze.run_v4_flash_lp_mechanism_exploration import (
    CONTROLS as V4_ACTIVITY_CONTROLS,
    HORIZONS,
    PREDICTORS as FLASH_PREDICTORS,
    build_mechanism_panel,
    load_inputs as load_v4_inputs,
)


RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v4_flash_gap_interaction_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_flash_gap_interaction_support.jsonl"

OUTCOMES = (
    "future_log1p_gross_lp_flow_usd",
    "future_log1p_add_lp_flow_usd",
    "future_log1p_remove_lp_flow_usd",
    "future_delta_log1p_tvl_usd",
    "future_log1p_lp_actions",
    "future_narrow_medium_action_share",
    "future_wide_very_wide_action_share",
)
CODE_SOURCES = [
    "scripts/analyze/run_v4_flash_gap_interaction_exploration.py",
    "scripts/analyze/run_liquidity_provision_behavior_exploration.py",
    "scripts/analyze/run_v4_flash_lp_mechanism_exploration.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
    "data/processed/v4_lp_flow_candidate_daily.parquet",
    "data/processed/v4_lp_action_candidate_daily.parquet",
    "data/processed/v4_candidate_linked_pool_tvl_daily.parquet",
]


def _normalise_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["origin_date"] = pd.to_datetime(result["origin_date"]).dt.normalize()
    result["candidate_address"] = result["candidate_address"].astype(str).str.lower()
    result["candidate_symbol"] = result["candidate_symbol"].astype(str)
    return result


def load_stable_gap_panel(path: Path = CANDIDATE_DAY_INPUT) -> pd.DataFrame:
    """Return stable-candidate route-minus-capital gaps from the V2 day panel."""

    candidate_day = load_candidate_day(path)
    share_gap = candidate_share_gap_panel(supported_candidate_days(candidate_day))
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "is_stable",
        "route_capital_gap_5",
    }
    missing = sorted(required - set(share_gap.columns))
    if missing:
        raise ValueError(f"candidate share-gap panel lacks columns: {missing}")
    stable_gap = share_gap[share_gap["is_stable"].astype(bool)][
        [
            "origin_date",
            "candidate_address",
            "candidate_symbol",
            "is_stable",
            "route_capital_gap_5",
        ]
    ].copy()
    if stable_gap.empty:
        raise ValueError("stable route-capital gap panel is empty")
    return _normalise_key(stable_gap)


def build_flash_gap_interaction_panel(
    stable_gap: pd.DataFrame,
    mechanism_panel: pd.DataFrame,
) -> pd.DataFrame:
    """Merge stable route-capital gaps into the V4 flash-LP mechanism panel."""

    required_mechanism = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "horizon_days",
        *FLASH_PREDICTORS,
        *OUTCOMES,
        *V4_ACTIVITY_CONTROLS,
    }
    missing_mechanism = sorted(required_mechanism - set(mechanism_panel.columns))
    if missing_mechanism:
        raise ValueError(f"V4 mechanism panel lacks columns: {missing_mechanism}")
    required_gap = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "is_stable",
        "route_capital_gap_5",
    }
    missing_gap = sorted(required_gap - set(stable_gap.columns))
    if missing_gap:
        raise ValueError(f"stable gap panel lacks columns: {missing_gap}")

    key = ["origin_date", "candidate_address", "candidate_symbol"]
    left = _normalise_key(mechanism_panel)
    right = _normalise_key(stable_gap)
    panel = left.merge(
        right,
        on=key,
        how="inner",
        validate="many_to_one",
    )
    panel = panel[panel["is_stable"].astype(bool)].copy()
    required_numeric = [
        "route_capital_gap_5",
        *FLASH_PREDICTORS,
        *OUTCOMES,
        *V4_ACTIVITY_CONTROLS,
    ]
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=required_numeric
    )
    if panel.empty:
        raise ValueError("V4 flash-gap interaction panel is empty")
    return panel


def fit_flash_gap_interactions(
    panel: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
    predictors: Sequence[str] = FLASH_PREDICTORS,
    outcomes: Sequence[str] = OUTCOMES,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit candidate/date-FE interaction models for stable V4-active days."""

    rows: list[dict[str, object]] = []
    for horizon in horizons:
        horizon_panel = panel[panel["horizon_days"].eq(int(horizon))].copy()
        for predictor in predictors:
            if predictor not in horizon_panel.columns:
                raise ValueError(f"panel lacks V4 flash predictor {predictor}")
            interaction = f"route_capital_gap_5_x_{predictor}"
            for outcome in outcomes:
                data = horizon_panel[
                    [
                        "origin_date",
                        "candidate_address",
                        "route_capital_gap_5",
                        predictor,
                        *V4_ACTIVITY_CONTROLS,
                        outcome,
                    ]
                ].copy()
                data[interaction] = (
                    data["route_capital_gap_5"].astype(float)
                    * data[predictor].astype(float)
                )
                data = data.replace([np.inf, -np.inf], np.nan).dropna()
                if len(data) < min_observations:
                    continue
                regressors = (
                    "route_capital_gap_5",
                    predictor,
                    interaction,
                    *V4_ACTIVITY_CONTROLS,
                )
                residual = absorb_fixed_effects(
                    data[[outcome, *regressors]],
                    data["candidate_address"],
                    data["origin_date"],
                )
                fit = ols_clustered(
                    residual[outcome],
                    residual[list(regressors)],
                    data["origin_date"],
                    add_constant=False,
                    absorbed_groups=(data["candidate_address"], data["origin_date"]),
                    min_observations=min_observations,
                    min_clusters=min_clusters,
                )
                for term, coefficient, standard_error, t_statistic, p_value in zip(
                    regressors,
                    fit.beta,
                    fit.standard_errors,
                    fit.t_statistics,
                    fit.p_values,
                    strict=True,
                ):
                    coefficient = float(coefficient)
                    standard_error = float(standard_error)
                    rows.append(
                        {
                            "record_type": "v4_flash_gap_interaction_regression",
                            "analysis_status": "exploratory_mechanism",
                            "sample": "stable_v4_active_origin_candidate_days",
                            "horizon_days": int(horizon),
                            "outcome": outcome,
                            "flash_predictor": predictor,
                            "term": term,
                            "coefficient": coefficient,
                            "standard_error": standard_error,
                            "t_statistic": float(t_statistic),
                            "p_value": float(p_value),
                            "coefficient_per_10pp_gap": (
                                0.10 * coefficient
                                if term == "route_capital_gap_5"
                                else np.nan
                            ),
                            "standard_error_per_10pp_gap": (
                                0.10 * standard_error
                                if term == "route_capital_gap_5"
                                else np.nan
                            ),
                            "effect_per_10pp_gap_10pp_flash": (
                                0.01 * coefficient if term == interaction else np.nan
                            ),
                            "standard_error_per_10pp_gap_10pp_flash": (
                                0.01 * standard_error
                                if term == interaction
                                else np.nan
                            ),
                            "effect_per_10pp_gap_10pp_flash_pp": (
                                coefficient if term == interaction else np.nan
                            ),
                            "standard_error_per_10pp_gap_10pp_flash_pp": (
                                standard_error if term == interaction else np.nan
                            ),
                            "n_observations": int(fit.n_observations),
                            "date_clusters": int(fit.n_clusters),
                            "fixed_effects": "candidate_address+origin_date",
                            "covariance": "origin_date_clustered",
                            "activity_controls": "+".join(V4_ACTIVITY_CONTROLS),
                            "interpretation": (
                                "stable-candidate route-capital gap interacted with "
                                "same-day V4 singleton flash-accounting intensity; "
                                "exploratory association, not causal LP response"
                            ),
                        }
                    )
    if not rows:
        raise ValueError("no V4 flash-gap interaction regressions were estimated")
    return pd.DataFrame(rows)


def support_record(panel: pd.DataFrame, results: pd.DataFrame) -> dict[str, object]:
    """Summarise the interaction design."""

    return {
        "record_type": "v4_flash_gap_interaction_support",
        "analysis_status": "exploratory_mechanism",
        "sample": "stable_v4_active_origin_candidate_days",
        "candidate_count": int(panel["candidate_address"].nunique()),
        "candidate_symbols": "+".join(sorted(panel["candidate_symbol"].unique())),
        "first_date": str(panel["origin_date"].min().date()),
        "last_date": str(panel["origin_date"].max().date()),
        "candidate_days": int(
            panel[["origin_date", "candidate_address"]].drop_duplicates().shape[0]
        ),
        "horizon_rows": int(len(panel)),
        "horizons": "+".join(str(int(v)) for v in sorted(panel["horizon_days"].unique())),
        "result_rows": int(len(results)),
        "interaction_rows": int(
            results["term"].astype(str).str.startswith("route_capital_gap_5_x_").sum()
        ),
        "predictors": "+".join(FLASH_PREDICTORS),
        "outcomes": "+".join(OUTCOMES),
        "fixed_effects": "candidate+origin_date",
        "cluster": "origin_date",
        "quantity": (
            "stable-candidate V2 route-minus-capital gap interacted with "
            "V4 singleton netting proxies and matched to future V4 LP flow, "
            "candidate-linked TVL, LP actions, and range placement"
        ),
    }


def run(
    *,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    stable_gap = load_stable_gap_panel(candidate_day_path)
    flash, flow, actions, tvl = load_v4_inputs()
    mechanism_panel = build_mechanism_panel(flash, flow, actions, tvl)
    panel = build_flash_gap_interaction_panel(stable_gap, mechanism_panel)
    results = fit_flash_gap_interactions(panel)
    support = pd.DataFrame([support_record(panel, results)])
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    display_output = result_output.resolve()
    try:
        display_output = display_output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    print(
        f"wrote {len(results):,} V4 flash-gap interaction rows to {display_output}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    args = parser.parse_args()
    return run(
        result_output=args.result_output,
        support_output=args.support_output,
        candidate_day_path=args.candidate_day,
    )


if __name__ == "__main__":
    raise SystemExit(main())
