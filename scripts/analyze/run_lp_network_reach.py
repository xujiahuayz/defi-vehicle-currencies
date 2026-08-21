#!/usr/bin/env python3
"""Test whether a vehicle's outside executable network precedes LP supply.

For an endpoint token x and vehicle v, the predictor is the most recent prior
monthly fixed-notional reach of v after removing x from the endpoint universe.
Because the reach frontier has one row per v--endpoint relation and its best
quote searches every admitted pool, this subtraction removes every observed
x--v pool, not merely the focal pool.  The remaining reach is therefore an
external network attribute of v.

The outcomes are decoded next-week LP additions and net supply from the V2 and
V3 provider-flow panels.  No realised route share, route choice, or trade-flow
variable enters the merge or regression.  Models retain the provider panels'
endpoint-by-week and pool fixed effects and pool/week clustered covariance.
The $10,000 and $100,000 frontiers are estimated separately.

Stable--stable core links remain in the reach frontier's separate descriptive
scope.  This test uses noncandidate spokes because the provider-flow panels
compare WETH and stablecoin pools for the same unrelated endpoint.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_lp_supply_returns import (
    MAIN_CAPITAL_THRESHOLD,
    comparison_sample as v2_comparison_sample,
)
from scripts.analyze.run_v3_lp_supply_returns import (
    MAIN_TVL_THRESHOLD,
    comparison_sample as v3_comparison_sample,
)


REACH_INPUT = DATA_DIR / "processed/fixed_notional_vehicle_reach_monthly.parquet"
V2_LP_INPUT = OUTPUT_DIR / "exhibits/lp_supply_returns_weekly.parquet"
V3_LP_INPUT = OUTPUT_DIR / "exhibits/v3_lp_supply_returns_weekly.parquet"
PANEL_OUTPUT = OUTPUT_DIR / "exhibits/lp_network_reach_weekly.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/lp_network_reach_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/lp_network_reach_support.jsonl"

MAX_REACH_AGE_DAYS = 45
OUTCOMES = {
    "net_supply": "next_asinh_net_supply_kusd",
    "capital_additions": "next_log1p_capital_additions_kusd",
}
COMMON_COLUMNS = [
    "origin_week",
    "pool_id",
    "endpoint_week_id",
    "candidate_address",
    "candidate_symbol",
    "candidate_type",
    "endpoint_address",
    "next_add_flow_usd",
    "next_remove_flow_usd",
    "next_net_add_flow_usd",
    "next_log1p_add_flow_ratio",
    "next_asinh_net_flow_ratio",
    "fee_yield_per_10bps",
    "trailing_log1p_add_flow_ratio",
    "trailing_log1p_remove_flow_ratio",
]
CODE_SOURCES = [
    "scripts/analyze/run_lp_network_reach.py",
    "scripts/analyze/run_fixed_notional_vehicle_reach.py",
    "scripts/analyze/run_lp_supply_returns.py",
    "scripts/analyze/run_v3_lp_supply_returns.py",
]


@dataclass(frozen=True)
class VenueSpec:
    venue: str
    risk_column: str
    stock_column: str
    age_column: str


VENUE_SPECS = {
    "uniswap_v2": VenueSpec(
        "uniswap_v2",
        "trailing_divergence_loss_bps",
        "log_capital_usd",
        "log1p_pool_age_weeks",
    ),
    "uniswap_v3": VenueSpec(
        "uniswap_v3",
        "trailing_cp_divergence_proxy_bps",
        "log_tvl_usd",
        "log1p_observed_pool_age_weeks",
    ),
}


def _reach_components(frontier: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {
        "day",
        "candidate_address",
        "endpoint_address",
        "endpoint_scope",
        "notional_usd",
        "executable",
        "all_in_cost_bps",
    }
    missing = sorted(required - set(frontier.columns))
    if missing:
        raise ValueError(f"LP network reach frontier lacks columns: {missing}")
    frame = frontier.loc[
        frontier["endpoint_scope"].eq("noncandidate_spoke")
    ].copy()
    frame["reach_day"] = pd.to_datetime(
        frame["day"].astype(str), format="%Y%m%d", errors="coerce"
    )
    frame["candidate_address"] = (
        frame["candidate_address"].astype(str).str.lower()
    )
    frame["endpoint_address"] = (
        frame["endpoint_address"].astype(str).str.lower()
    )
    frame["notional_usd"] = pd.to_numeric(
        frame["notional_usd"], errors="coerce"
    )
    frame["executable"] = frame["executable"].fillna(False).astype(bool)
    frame["all_in_cost_bps"] = pd.to_numeric(
        frame["all_in_cost_bps"], errors="coerce"
    )
    valid = (
        frame["reach_day"].notna()
        & frame["candidate_address"].ne("")
        & frame["endpoint_address"].ne("")
        & frame["notional_usd"].gt(0)
    )
    frame = frame.loc[valid].copy()
    keys = [
        "reach_day",
        "candidate_address",
        "endpoint_address",
        "notional_usd",
    ]
    if frame.empty or frame.duplicated(keys).any():
        raise ValueError("LP network reach frontier is empty or duplicated")
    frame["executable_cost_bps"] = frame["all_in_cost_bps"].where(
        frame["executable"]
    )
    group_keys = ["reach_day", "candidate_address", "notional_usd"]
    totals = (
        frame.groupby(group_keys, as_index=False)
        .agg(
            priced_endpoints=("endpoint_address", "nunique"),
            executable_endpoints=("executable", "sum"),
            executable_cost_sum_bps=("executable_cost_bps", "sum"),
            executable_cost_count=("executable_cost_bps", "count"),
        )
        .sort_values(group_keys)
        .reset_index(drop=True)
    )
    focal = frame.loc[
        :,
        [
            "reach_day",
            "candidate_address",
            "endpoint_address",
            "notional_usd",
            "executable",
            "executable_cost_bps",
        ],
    ].rename(
        columns={
            "executable": "focal_endpoint_executable",
            "executable_cost_bps": "focal_endpoint_cost_bps",
        }
    )
    return totals, focal


def _strict_prior_reach(
    lp: pd.DataFrame,
    totals: pd.DataFrame,
    *,
    max_age_days: int,
) -> pd.DataFrame:
    if max_age_days < 1:
        raise ValueError("LP network reach lag bound must be positive")
    rows: list[pd.DataFrame] = []
    for (candidate, notional), right in totals.groupby(
        ["candidate_address", "notional_usd"], sort=True
    ):
        left = lp.loc[lp["candidate_address"].eq(candidate)].copy()
        if left.empty:
            continue
        left["notional_usd"] = float(notional)
        joined = pd.merge_asof(
            left.sort_values("origin_week"),
            right.sort_values("reach_day"),
            left_on="origin_week",
            right_on="reach_day",
            by=["candidate_address", "notional_usd"],
            direction="backward",
            allow_exact_matches=False,
            tolerance=pd.Timedelta(days=max_age_days),
        )
        rows.append(joined)
    if not rows:
        raise ValueError("LP network reach has no candidate overlap with provider flows")
    return pd.concat(rows, ignore_index=True)


def attach_leave_focal_reach(
    frontier: pd.DataFrame,
    lp_panel: pd.DataFrame,
    *,
    max_age_days: int = MAX_REACH_AGE_DAYS,
) -> pd.DataFrame:
    """Attach strictly prior reach after removing the focal endpoint relation."""

    required_lp = {
        "origin_week",
        "candidate_address",
        "endpoint_address",
        "pool_id",
        "endpoint_week_id",
        "venue_family",
        "next_add_flow_usd",
        "next_remove_flow_usd",
        "next_net_add_flow_usd",
    }
    missing = sorted(required_lp - set(lp_panel.columns))
    if missing:
        raise ValueError(f"LP network reach provider panel lacks columns: {missing}")
    lp = lp_panel.copy()
    lp["origin_week"] = pd.to_datetime(lp["origin_week"]).dt.normalize()
    lp["candidate_address"] = lp["candidate_address"].astype(str).str.lower()
    lp["endpoint_address"] = lp["endpoint_address"].astype(str).str.lower()
    lp["next_asinh_net_supply_kusd"] = np.arcsinh(
        pd.to_numeric(lp["next_net_add_flow_usd"], errors="coerce") / 1_000.0
    )
    lp["next_log1p_capital_additions_kusd"] = np.log1p(
        pd.to_numeric(lp["next_add_flow_usd"], errors="coerce").clip(lower=0)
        / 1_000.0
    )
    if lp.duplicated(["pool_id", "origin_week"]).any():
        raise ValueError("LP network reach provider panel duplicates a pool-week")
    totals, focal = _reach_components(frontier)
    joined = _strict_prior_reach(lp, totals, max_age_days=max_age_days)
    joined = joined.merge(
        focal,
        on=[
            "reach_day",
            "candidate_address",
            "endpoint_address",
            "notional_usd",
        ],
        how="left",
        validate="many_to_one",
    )
    joined["focal_endpoint_in_priced_universe"] = joined[
        "focal_endpoint_executable"
    ].notna()
    focal_present = joined["focal_endpoint_in_priced_universe"].astype(int)
    focal_executable = joined["focal_endpoint_executable"].fillna(False).astype(int)
    focal_cost_present = joined["focal_endpoint_cost_bps"].notna().astype(int)
    joined["external_priced_endpoints"] = (
        joined["priced_endpoints"] - focal_present
    )
    joined["external_executable_endpoints"] = (
        joined["executable_endpoints"] - focal_executable
    )
    joined["external_executable_cost_sum_bps"] = (
        joined["executable_cost_sum_bps"]
        - joined["focal_endpoint_cost_bps"].fillna(0.0)
    )
    joined["external_executable_cost_count"] = (
        joined["executable_cost_count"] - focal_cost_present
    )
    denominator = joined["external_priced_endpoints"].where(
        joined["external_priced_endpoints"].gt(0)
    )
    cost_count = joined["external_executable_cost_count"].where(
        joined["external_executable_cost_count"].gt(0)
    )
    joined["external_coverage_share"] = (
        joined["external_executable_endpoints"] / denominator
    )
    joined["external_mean_all_in_cost_bps"] = (
        joined["external_executable_cost_sum_bps"] / cost_count
    )
    joined["external_coverage_per_10pp"] = (
        joined["external_coverage_share"] / 0.10
    )
    joined["log1p_external_executable_endpoints"] = np.log1p(
        joined["external_executable_endpoints"]
    )
    joined["log1p_external_priced_endpoints"] = np.log1p(
        joined["external_priced_endpoints"]
    )
    joined["reach_age_days"] = (
        joined["origin_week"] - joined["reach_day"]
    ).dt.days
    invalid = (
        joined["reach_day"].notna()
        & (
            joined["reach_day"].ge(joined["origin_week"])
            | joined["reach_age_days"].gt(max_age_days)
            | joined["external_priced_endpoints"].lt(0)
            | joined["external_executable_endpoints"].lt(0)
        )
    )
    if invalid.any():
        raise ValueError("LP network reach violates strict lag or leave-out accounting")
    return joined.sort_values(
        ["venue_family", "origin_week", "pool_id", "notional_usd"]
    ).reset_index(drop=True)


def _v2_panel(path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(path)
    panel = v2_comparison_sample(panel, MAIN_CAPITAL_THRESHOLD)
    spec = VENUE_SPECS["uniswap_v2"]
    selected = panel.loc[
        :,
        [
            *COMMON_COLUMNS,
            spec.risk_column,
            spec.stock_column,
            spec.age_column,
        ],
    ].copy()
    selected["venue_family"] = spec.venue
    return selected.rename(
        columns={
            spec.risk_column: "prior_price_risk_bps",
            spec.stock_column: "log_prior_pool_capital",
            spec.age_column: "log1p_pool_age",
        }
    )


def _v3_panel(path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(path)
    panel = v3_comparison_sample(panel, MAIN_TVL_THRESHOLD)
    spec = VENUE_SPECS["uniswap_v3"]
    selected = panel.loc[
        :,
        [
            *COMMON_COLUMNS,
            spec.risk_column,
            spec.stock_column,
            spec.age_column,
        ],
    ].copy()
    selected["venue_family"] = spec.venue
    return selected.rename(
        columns={
            spec.risk_column: "prior_price_risk_bps",
            spec.stock_column: "log_prior_pool_capital",
            spec.age_column: "log1p_pool_age",
        }
    )


def load_lp_outcomes(v2_path: Path, v3_path: Path) -> pd.DataFrame:
    """Read only provider-flow outcomes and their pre-existing supply controls."""

    missing = [path for path in (v2_path, v3_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(map(str, missing)))
    result = pd.concat(
        [_v2_panel(v2_path), _v3_panel(v3_path)],
        ignore_index=True,
        sort=False,
    )
    forbidden = [
        column
        for column in result.columns
        if any(term in column.lower() for term in ("route", "trade", "choice"))
    ]
    if forbidden:
        raise ValueError(f"provider-flow reach input contains route fields: {forbidden}")
    return result


def fit_reach_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 250,
    min_pool_clusters: int = 30,
    min_week_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate external-reach slopes for next-week net supply and additions."""

    predictors = [
        "log1p_external_executable_endpoints",
        "fee_yield_per_10bps",
        "prior_price_risk_bps",
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_prior_pool_capital",
        "log1p_pool_age",
    ]
    rows: list[dict[str, object]] = []
    for (venue, notional), group in panel.groupby(
        ["venue_family", "notional_usd"], sort=True
    ):
        for outcome_label, outcome in OUTCOMES.items():
            columns = [
                outcome,
                *predictors,
                "endpoint_week_id",
                "pool_id",
                "origin_week",
                "reach_age_days",
            ]
            model = group.loc[:, columns].dropna().reset_index(drop=True)
            for column in (outcome, *predictors):
                lower, upper = model[column].quantile([0.01, 0.99])
                if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
                    model[column] = model[column].clip(
                        lower=float(lower), upper=float(upper)
                    )
            if len(model) < min_observations:
                raise ValueError(
                    f"LP network reach {venue}/{notional}/{outcome_label} "
                    "has too few observations"
                )
            if model["pool_id"].nunique() < min_pool_clusters:
                raise ValueError("LP network reach has too few pool clusters")
            if model["origin_week"].nunique() < min_week_clusters:
                raise ValueError("LP network reach has too few week clusters")
            fixed_effects = (model["endpoint_week_id"], model["pool_id"])
            absorbed_outcome = absorb_fixed_effects(
                model[outcome], *fixed_effects
            )
            absorbed_design = absorb_fixed_effects(
                model[predictors], *fixed_effects
            )
            fit = ols_clustered(
                absorbed_outcome,
                absorbed_design,
                model["pool_id"],
                add_constant=False,
                absorbed_groups=fixed_effects,
                additional_clusters=(model["origin_week"],),
                min_observations=min_observations,
                min_clusters=min(min_pool_clusters, min_week_clusters),
            )
            model_id = (
                f"{venue}_{int(notional)}usd_external_reach_{outcome_label}"
            )
            for predictor, coefficient, standard_error, t_statistic, p_value in zip(
                predictors,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                rows.append(
                    {
                        "record_type": "lp_network_reach_coefficient",
                        "model_id": model_id,
                        "venue": venue,
                        "notional_usd": float(notional),
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": float(coefficient),
                        "standard_error": float(standard_error),
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "observations": int(fit.n_observations),
                        "pool_clusters": int(model["pool_id"].nunique()),
                        "week_clusters": int(model["origin_week"].nunique()),
                        "fixed_effects": "endpoint_x_week+pool",
                        "covariance": "pool_and_week_cluster_cr1",
                        "reach_timing": "latest_strictly_prior_monthly_close_max_45_days",
                        "reach_leave_out": "focal_endpoint_and_all_focal_endpoint_vehicle_pools",
                        "reach_scope": "priced_noncandidate_spokes",
                        "outcome_timing": "week_t_plus_1_decoded_provider_flow",
                        "route_variables": "none",
                        "mean_reach_age_days": float(model["reach_age_days"].mean()),
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("LP network reach model output is empty")
    primary = result["predictor"].eq("log1p_external_executable_endpoints")
    result["p_value_holm_reach_family"] = np.nan
    result.loc[primary, "p_value_holm_reach_family"] = holm_adjusted_pvalues(
        result.loc[primary, "p_value"]
    )
    return result


def support_records(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (venue, notional), group in panel.groupby(
        ["venue_family", "notional_usd"], sort=True
    ):
        attached = group.loc[group["reach_day"].notna()]
        rows.append(
            {
                "record_type": "lp_network_reach_support",
                "venue": venue,
                "notional_usd": float(notional),
                "provider_pool_weeks": int(len(group)),
                "reach_attached_pool_weeks": int(len(attached)),
                "reach_attachment_share": float(group["reach_day"].notna().mean()),
                "pools": int(attached["pool_id"].nunique()),
                "weeks": int(attached["origin_week"].nunique()),
                "endpoints": int(attached["endpoint_address"].nunique()),
                "mean_external_coverage_share": float(
                    attached["external_coverage_share"].mean()
                ),
                "mean_reach_age_days": float(attached["reach_age_days"].mean()),
                "focal_endpoint_priced_share": float(
                    attached["focal_endpoint_in_priced_universe"].mean()
                ),
                "reach_scope": "noncandidate_spokes_excluding_focal_endpoint",
                "provider_outcomes": "next_week_capital_additions_and_net_supply",
                "route_variables": "none",
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    reach_path: Path = REACH_INPUT,
    v2_path: Path = V2_LP_INPUT,
    v3_path: Path = V3_LP_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    for path in (reach_path, v2_path, v3_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    frontier = pd.read_parquet(reach_path)
    lp = load_lp_outcomes(v2_path, v3_path)
    panel = attach_leave_focal_reach(frontier, lp)
    models = fit_reach_models(panel)
    support = support_records(panel)
    write_panel(
        panel,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=[reach_path, v2_path, v3_path],
        notes=(
            "Strictly lagged fixed-notional vehicle reach after removing the "
            "focal endpoint, joined only to decoded provider-flow outcomes."
        ),
    )
    write_exhibit(
        models,
        model_output,
        code_sources=CODE_SOURCES,
        inputs=[panel_output],
    )
    write_exhibit(
        support,
        support_output,
        code_sources=CODE_SOURCES,
        inputs=[panel_output],
    )
    print(
        f"wrote {len(panel):,} LP network-reach pool-week-notionals, "
        f"{len(models):,} coefficients, and {len(support):,} support rows",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reach", type=Path, default=REACH_INPUT)
    parser.add_argument("--v2-lp", type=Path, default=V2_LP_INPUT)
    parser.add_argument("--v3-lp", type=Path, default=V3_LP_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        reach_path=args.reach,
        v2_path=args.v2_lp,
        v3_path=args.v3_lp,
        panel_output=args.panel_output,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
