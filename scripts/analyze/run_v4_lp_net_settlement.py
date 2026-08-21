#!/usr/bin/env python3
"""Relate observed V4 net settlement to subsequent LP supply behavior.

Reads:
  data/processed/v4_lp_net_settlement_weekly.parquet

Writes:
  output/exhibits/v4_lp_net_settlement.jsonl
  output/exhibits/v4_lp_net_settlement_support.jsonl

The unit is an active transaction-origin--pool week in a vehicle-linked V4
pool.  Week-t use of transaction-level netting and measured settlement
compression is related to LP actions over weeks t+1 through t+4.  Regressions
absorb origin-pool and calendar-week fixed effects and cluster by origin-pool.

The estimates are descriptive, lagged within-origin-pool associations.  The
origin is not verified beneficial ownership; observed subsequent inactivity is
a censoring-sensitive persistence proxy rather than LP exit.  Gas is excluded
because the raw event records contain neither gas used nor gas price.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


WEEKLY_INPUT = REPO_ROOT / "data/processed/v4_lp_net_settlement_weekly.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_net_settlement.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_net_settlement_support.jsonl"
HORIZON_WEEKS = 4
MIN_VALUE_COVERAGE = 0.80

PREDICTORS = (
    "netting_tx_share",
    "settlement_count_reduction_share",
    "amount_netting_value_share",
)
OUTCOMES = (
    "future_log1p_add_lp_flow_usd",
    "future_log1p_remove_lp_flow_usd",
    "future_net_add_flow_balance",
    "future_active",
    "future_log1p_reposition_txs",
    "future_mean_add_log_tick_width",
)
CONTROLS = (
    "log1p_current_gross_lp_flow_usd",
    "log1p_current_lp_txs",
    "current_net_add_flow_balance",
    "current_reposition_tx_share",
)

CODE_SOURCES = [
    "scripts/analyze/run_v4_lp_net_settlement.py",
    "scripts/process/build_v4_lp_net_settlement_weekly.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = ["data/processed/v4_lp_net_settlement_weekly.parquet"]


def _require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V4 LP net-settlement weekly panel lacks columns: {missing}")


def load_weekly(path: Path = WEEKLY_INPUT) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["week_start"] = pd.to_datetime(frame["week_start"]).dt.normalize()
    frame["origin"] = frame["origin"].astype(str).str.lower()
    frame["pool"] = frame["pool"].astype(str).str.lower()
    frame["provider_pool_id"] = frame["origin"] + "|" + frame["pool"]
    return frame


def build_horizon_panel(
    weekly: pd.DataFrame,
    *,
    horizon_weeks: int = HORIZON_WEEKS,
) -> pd.DataFrame:
    """Attach subsequent-week LP outcomes to each active week."""

    if horizon_weeks < 1:
        raise ValueError("V4 LP net-settlement horizon must be positive")
    required = {
        "week_start",
        "origin",
        "pool",
        "provider_pool_id",
        "lp_tx_count",
        "netting_tx_share",
        "settlement_count_reduction_share",
        "amount_netting_value_share",
        "settlement_value_coverage_share",
        "gross_lp_flow_usd",
        "add_lp_flow_usd",
        "remove_lp_flow_usd",
        "net_add_flow_balance",
        "supply_side_assignments",
        "valued_supply_side_assignments",
        "reposition_tx_count",
        "reposition_tx_share",
        "add_log_tick_width_sum",
        "add_range_observations",
        "last_observed_participation_proxy",
    }
    _require_columns(weekly, required)
    data = weekly.copy()
    data["week_start"] = pd.to_datetime(data["week_start"]).dt.normalize()
    data = data.sort_values(["provider_pool_id", "week_start"]).reset_index(drop=True)
    last_complete_week = data["week_start"].max()
    horizon_delta = pd.Timedelta(weeks=horizon_weeks)
    rows: list[dict[str, object]] = []
    for provider_pool_id, group in data.groupby("provider_pool_id", sort=True):
        group = group.sort_values("week_start")
        for current in group.itertuples(index=False):
            origin_week = pd.Timestamp(current.week_start)
            horizon_end = origin_week + horizon_delta
            if horizon_end > last_complete_week:
                continue
            future = group[
                group["week_start"].gt(origin_week)
                & group["week_start"].le(horizon_end)
            ]
            future_tx = float(future["lp_tx_count"].sum())
            future_add = float(future["add_lp_flow_usd"].sum())
            future_remove = float(future["remove_lp_flow_usd"].sum())
            future_gross = future_add + future_remove
            future_supply_sides = float(future["supply_side_assignments"].sum())
            future_valued_sides = float(
                future["valued_supply_side_assignments"].sum()
            )
            future_range_count = float(future["add_range_observations"].sum())
            future_range_sum = float(future["add_log_tick_width_sum"].sum())
            record = {
                "week_start": origin_week,
                "horizon_weeks": int(horizon_weeks),
                "provider_pool_id": provider_pool_id,
                "origin": str(current.origin),
                "pool": str(current.pool),
                **{predictor: float(getattr(current, predictor)) for predictor in PREDICTORS},
                "current_settlement_value_coverage_share": float(
                    current.settlement_value_coverage_share
                ),
                "log1p_current_gross_lp_flow_usd": float(
                    np.log1p(float(current.gross_lp_flow_usd))
                ),
                "log1p_current_lp_txs": float(np.log1p(float(current.lp_tx_count))),
                "current_net_add_flow_balance": float(current.net_add_flow_balance),
                "current_reposition_tx_share": float(current.reposition_tx_share),
                "current_last_observed_participation_proxy": int(
                    current.last_observed_participation_proxy
                ),
                "future_lp_txs": future_tx,
                "future_log1p_add_lp_flow_usd": float(np.log1p(future_add)),
                "future_log1p_remove_lp_flow_usd": float(np.log1p(future_remove)),
                "future_net_add_flow_balance": (
                    (future_add - future_remove) / (future_gross + 1.0)
                ),
                "future_active": int(future_tx > 0),
                "future_inactivity_persistence_proxy": int(future_tx == 0),
                "future_log1p_reposition_txs": float(
                    np.log1p(float(future["reposition_tx_count"].sum()))
                ),
                "future_mean_add_log_tick_width": (
                    future_range_sum / future_range_count
                    if future_range_count > 0
                    else np.nan
                ),
                "future_lp_flow_value_coverage_share": (
                    future_valued_sides / future_supply_sides
                    if future_supply_sides > 0
                    else 1.0
                ),
            }
            rows.append(record)
    if not rows:
        raise ValueError("V4 LP net-settlement horizon panel is empty")
    return pd.DataFrame(rows)


def fit_net_settlement_models(
    panel: pd.DataFrame,
    *,
    predictors: Sequence[str] = PREDICTORS,
    outcomes: Sequence[str] = OUTCOMES,
    controls: Sequence[str] = CONTROLS,
    min_observations: int = 500,
    min_clusters: int = 50,
    minimum_value_coverage: float = MIN_VALUE_COVERAGE,
) -> pd.DataFrame:
    """Estimate the declared LP-supply associations and adjust them jointly."""

    if not 0 < minimum_value_coverage <= 1:
        raise ValueError("minimum V4 LP value coverage must lie in (0, 1]")
    required = {
        "week_start",
        "provider_pool_id",
        "current_settlement_value_coverage_share",
        "future_lp_flow_value_coverage_share",
        *predictors,
        *outcomes,
        *controls,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"V4 LP net-settlement horizon panel lacks columns: {missing}")
    flow_outcomes = {
        "future_log1p_add_lp_flow_usd",
        "future_log1p_remove_lp_flow_usd",
        "future_net_add_flow_balance",
    }
    rows: list[dict[str, object]] = []
    for predictor in predictors:
        for outcome in outcomes:
            columns = [outcome, predictor, *controls]
            data = panel[
                [
                    "week_start",
                    "provider_pool_id",
                    "current_settlement_value_coverage_share",
                    "future_lp_flow_value_coverage_share",
                    *columns,
                ]
            ].copy()
            if predictor == "amount_netting_value_share":
                data = data[
                    data["current_settlement_value_coverage_share"].ge(
                        minimum_value_coverage
                    )
                ]
            if outcome in flow_outcomes:
                data = data[
                    data["future_lp_flow_value_coverage_share"].ge(
                        minimum_value_coverage
                    )
                ]
            data = data.dropna(subset=columns)
            repeated = data.groupby("provider_pool_id")["week_start"].transform("size")
            data = data[repeated.ge(2)].copy()
            if data.empty:
                continue
            residual = absorb_fixed_effects(
                data[columns], data["provider_pool_id"], data["week_start"]
            )
            retained_controls = [
                control
                for control in controls
                if np.isfinite(residual[control]).all()
                and float(residual[control].var()) > 1e-14
            ]
            design_columns = [predictor, *retained_controls]
            fit = ols_clustered(
                residual[outcome],
                residual[design_columns],
                data["provider_pool_id"],
                add_constant=False,
                absorbed_groups=(data["provider_pool_id"], data["week_start"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            rows.append(
                {
                    "record_type": "v4_lp_net_settlement_regression",
                    "analysis_status": "exploratory_lp_supply_association",
                    "predictor": predictor,
                    "outcome": outcome,
                    "coefficient": float(fit.beta[0]),
                    "coefficient_per_10pp": float(0.10 * fit.beta[0]),
                    "standard_error": float(fit.standard_errors[0]),
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "observations": int(fit.n_observations),
                    "provider_pool_clusters": int(fit.n_clusters),
                    "calendar_weeks": int(data["week_start"].nunique()),
                    "provider_pools": int(data["provider_pool_id"].nunique()),
                    "horizon_weeks": int(panel["horizon_weeks"].iloc[0]),
                    "fixed_effects": "transaction_origin_pool+calendar_week",
                    "cluster": "transaction_origin_pool",
                    "controls": "+".join(retained_controls),
                    "minimum_value_coverage": float(minimum_value_coverage),
                    "identity_scope": (
                        "transaction origin participation; beneficial ownership "
                        "is not observed"
                    ),
                    "interpretation_scope": (
                        "lagged within-origin-pool association, not a causal effect"
                    ),
                }
            )
    if not rows:
        raise ValueError("V4 LP net-settlement models produced no result rows")
    results = pd.DataFrame(rows)
    results["p_value_holm"] = holm_adjusted_pvalues(results["p_value"])
    return results


def run(
    *,
    weekly_input: Path = WEEKLY_INPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    horizon_weeks: int = HORIZON_WEEKS,
    min_observations: int = 500,
    min_clusters: int = 50,
    minimum_value_coverage: float = MIN_VALUE_COVERAGE,
) -> int:
    weekly = load_weekly(weekly_input)
    panel = build_horizon_panel(weekly, horizon_weeks=horizon_weeks)
    results = fit_net_settlement_models(
        panel,
        min_observations=min_observations,
        min_clusters=min_clusters,
        minimum_value_coverage=minimum_value_coverage,
    )
    support = pd.DataFrame(
        [
            {
                "record_type": "v4_lp_net_settlement_support",
                "analysis_status": "exploratory_lp_supply_association",
                "provider_pool_week_rows": len(weekly),
                "horizon_rows": len(panel),
                "provider_proxies": int(weekly["origin"].nunique()),
                "pools": int(weekly["pool"].nunique()),
                "provider_pools": int(weekly["provider_pool_id"].nunique()),
                "calendar_weeks": int(weekly["week_start"].nunique()),
                "horizon_weeks": int(horizon_weeks),
                "predictors": "+".join(PREDICTORS),
                "outcomes": "+".join(OUTCOMES),
                "minimum_value_coverage": float(minimum_value_coverage),
                "identity_boundary": (
                    "transaction origin is a participation proxy, not verified "
                    "LP-position beneficial ownership"
                ),
                "participation_boundary": (
                    "subsequent inactivity and last observed participation are "
                    "censoring-sensitive persistence proxies, not exit"
                ),
                "settlement_boundary": (
                    "event-flow obligation compression; settle/take calls are unobserved"
                ),
                "gas_boundary": "gas used and gas price are absent and not proxied",
                "range_boundary": (
                    "future mean added-position tick width is conditional on an "
                    "observed add action"
                ),
                "v3_boundary": (
                    "V3 omitted because it has no comparable within-protocol "
                    "flash-netting-use margin"
                ),
                "causal_boundary": "descriptive lagged association",
            }
        ]
    )
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results)} V4 LP net-settlement estimates from "
        f"{len(panel):,} provider-pool-week horizons"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weekly", type=Path, default=WEEKLY_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--horizon-weeks", type=int, default=HORIZON_WEEKS)
    parser.add_argument("--min-observations", type=int, default=500)
    parser.add_argument("--min-clusters", type=int, default=50)
    parser.add_argument(
        "--minimum-value-coverage", type=float, default=MIN_VALUE_COVERAGE
    )
    args = parser.parse_args()
    return run(
        weekly_input=args.weekly,
        result_output=args.output,
        support_output=args.support,
        horizon_weeks=args.horizon_weeks,
        min_observations=args.min_observations,
        min_clusters=args.min_clusters,
        minimum_value_coverage=args.minimum_value_coverage,
    )


if __name__ == "__main__":
    raise SystemExit(main())
