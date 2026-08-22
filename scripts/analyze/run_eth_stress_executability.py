#!/usr/bin/env python3
"""Separate ETH-price accounting, executable prices, and realised routing.

The retained monthly exact-price panel holds the endpoint pair, observed input
amount, pretrade state, and public venue set fixed while quoting the best WETH
and stablecoin paths.  This runner attaches prior-calendar V2/Sushi V2 weak-leg
deposited capital and the canonical WETH return over days -30 through -1.

On one common sample with both route families executable and both weak-leg
capital measures positive, it asks whether a 10 percentage point ETH decline
predicts:

1. stablecoin-minus-WETH log weak-leg USD capital;
2. the exact stablecoin-minus-WETH output advantage; and
3. realised stablecoin route choice.

The choice model is then conditioned on exact output and relative capital.
Ordered-pair and calendar-month effects absorb persistent pair differences and
seasonality, while a linear calendar-time control absorbs the broad trend;
inference clusters by ordered pair and exact date.  Full date effects cannot be
combined with an ETH return that is common to every route on that date.

USD capital can move through mark-to-market accounting without any provider
action.  Exact output records the executable consequence of the observed pool
state.  Chosen vehicle records the empirical routing response.  None is called
an LP withdrawal; decoded LP flows and V2 liquidity quantity are measured in a
separate analysis.

Writes
  output/exhibits/eth_stress_executability.jsonl
  output/exhibits/eth_stress_executability_support.jsonl
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
from ddvc.tables import write_exhibit
from scripts.analyze.run_contestable_vehicle_choice import (
    FRONTIER,
    POOL_CAPITAL,
    attach_v2_bridge_capital,
    load_lagged_v2_bridge_capital,
    prepare_frontier,
)
from scripts.analyze.run_lp_stable_demand_stress import (
    PRICE_INPUT,
    load_weth_prices,
)


RESULT_OUTPUT = OUTPUT_DIR / "exhibits/eth_stress_executability.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/eth_stress_executability_support.jsonl"
STRESS_WINDOW_DAYS = 30

CODE_SOURCES = [
    "scripts/analyze/run_eth_stress_executability.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/exact_vehicle_frontier_monthly.parquet",
    "data/processed/pool_capital_daily.parquet",
    "data/processed/token_price_daily.parquet",
]


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    outcome: str
    predictors: tuple[str, ...]
    sample: str
    multiplicity_family: str
    chain_stage: str


BASE_PREDICTORS = (
    "eth_decline_per_10pp",
    "eth_volatility_per_10pp",
    "log_input_usd",
    "calendar_time_years",
)

MODEL_SPECS = (
    ModelSpec(
        "m1_relative_usd_depth",
        "stable_minus_weth_log_v2_depth",
        BASE_PREDICTORS,
        "common_exact_routes_positive_both_v2_weak_legs",
        "primary_mark_to_market_execution_routing_chain",
        "usd_depth_accounting",
    ),
    ModelSpec(
        "m2_exact_output_advantage",
        "stable_output_advantage_100bp",
        BASE_PREDICTORS,
        "common_exact_routes_positive_both_v2_weak_legs",
        "primary_mark_to_market_execution_routing_chain",
        "exact_executable_output",
    ),
    ModelSpec(
        "m3_realised_stable_choice",
        "chosen_stable",
        BASE_PREDICTORS,
        "common_exact_routes_positive_both_v2_weak_legs",
        "primary_mark_to_market_execution_routing_chain",
        "realised_route_choice",
    ),
    ModelSpec(
        "m4_output_advantage_conditioned_on_depth",
        "stable_output_advantage_100bp",
        (
            *BASE_PREDICTORS,
            "stable_v2_capital_advantage_10pp",
        ),
        "common_exact_routes_positive_both_v2_weak_legs",
        "secondary_conditioned_transmission",
        "exact_output_conditional_on_usd_depth",
    ),
    ModelSpec(
        "m5_realised_choice_conditioned_on_output_and_depth",
        "chosen_stable",
        (
            *BASE_PREDICTORS,
            "stable_output_advantage_100bp",
            "stable_v2_capital_advantage_10pp",
        ),
        "common_exact_routes_positive_both_v2_weak_legs",
        "secondary_conditioned_transmission",
        "route_choice_conditional_on_output_and_usd_depth",
    ),
)


def build_trailing_eth_state(
    prices: pd.DataFrame,
    *,
    window_days: int = STRESS_WINDOW_DAYS,
) -> pd.DataFrame:
    """Measure ETH return and volatility strictly before each calendar date."""

    required = {"origin_date", "price_usd"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"WETH price frame lacks columns: {missing}")
    if window_days < 2:
        raise ValueError("ETH stress window must contain at least two days")
    frame = prices[["origin_date", "price_usd"]].copy()
    frame["date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    frame["price_usd"] = pd.to_numeric(frame["price_usd"], errors="coerce")
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame.duplicated("date").any():
        raise ValueError("WETH daily price series has duplicate dates")
    if frame["price_usd"].isna().any() or frame["price_usd"].le(0).any():
        raise ValueError("WETH daily prices must be finite and positive")
    frame["lag_date"] = frame["date"].shift(1)
    frame["daily_log_return"] = np.log(frame["price_usd"]).diff()
    consecutive = frame["date"].sub(frame["lag_date"]).dt.days.eq(1)
    frame.loc[~consecutive, "daily_log_return"] = np.nan
    prior_return = frame["daily_log_return"].shift(1)
    frame["prior_return_days"] = prior_return.rolling(
        window_days, min_periods=window_days
    ).count()
    frame["trailing_eth_return"] = prior_return.rolling(
        window_days, min_periods=window_days
    ).sum()
    frame["trailing_eth_volatility"] = np.sqrt(
        365.0
        * prior_return.pow(2).rolling(
            window_days, min_periods=window_days
        ).mean()
    )
    frame["eth_decline_per_10pp"] = -frame["trailing_eth_return"] / 0.10
    frame["eth_volatility_per_10pp"] = (
        frame["trailing_eth_volatility"] / 0.10
    )
    result = frame.dropna(
        subset=[
            "trailing_eth_return",
            "trailing_eth_volatility",
            "eth_decline_per_10pp",
            "eth_volatility_per_10pp",
        ]
    )[
        [
            "date",
            "prior_return_days",
            "trailing_eth_return",
            "trailing_eth_volatility",
            "eth_decline_per_10pp",
            "eth_volatility_per_10pp",
        ]
    ].reset_index(drop=True)
    if result.empty or not result["prior_return_days"].eq(window_days).all():
        raise ValueError("strictly prior ETH stress series is empty or incomplete")
    return result


def prepare_executability_panel(
    frontier: pd.DataFrame,
    capital: pd.DataFrame,
    stress: pd.DataFrame,
) -> pd.DataFrame:
    """Build one common exact-route sample for all three stages."""

    data = attach_v2_bridge_capital(frontier, capital)
    data = data[data["symmetric_common_support"].astype(bool)].copy()
    data = data.merge(stress, on="date", how="inner", validate="many_to_one")
    data = data[data["both_v2_bridge_capitals_positive"].astype(bool)].copy()
    if data.empty:
        raise ValueError("ETH-stress exact-route common sample is empty")
    data["stable_minus_weth_log_v2_depth"] = np.log(
        data["stable_v2_bridge_capital_usd"]
    ) - np.log(data["native_v2_bridge_capital_usd"])
    data["calendar_month"] = data["date"].dt.month.astype(str)
    data["calendar_time_years"] = (
        data["date"] - pd.Timestamp("2018-01-01")
    ).dt.days / 365.25
    data["chosen_stable"] = data["chosen_stable"].astype(float)
    required_finite = [
        "stable_minus_weth_log_v2_depth",
        "stable_output_advantage_100bp",
        "stable_v2_capital_advantage_10pp",
        "chosen_stable",
        "eth_decline_per_10pp",
        "eth_volatility_per_10pp",
        "log_input_usd",
        "calendar_time_years",
    ]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=required_finite
    )
    if data.empty or data["route_id"].duplicated().any():
        raise ValueError("exact-route mechanism panel is empty or duplicated")
    return data.reset_index(drop=True)


def _fit_model(
    panel: pd.DataFrame,
    spec: ModelSpec,
    *,
    min_observations: int,
    min_pair_clusters: int,
    min_date_clusters: int,
) -> list[dict[str, object]]:
    columns = [
        spec.outcome,
        *spec.predictors,
        "ordered_pair",
        "date",
        "calendar_month",
    ]
    data = panel[columns].dropna().copy()
    pair_size = data.groupby("ordered_pair")["ordered_pair"].transform("size")
    data = data[pair_size.gt(1)].copy()
    for column in (
        spec.outcome,
        "log_input_usd",
        "stable_v2_capital_advantage_10pp",
    ):
        if column not in data or column in {"chosen_stable"}:
            continue
        lower, upper = data[column].quantile([0.01, 0.99])
        if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
            data[column] = data[column].clip(lower=float(lower), upper=float(upper))
    if len(data) < min_observations:
        raise ValueError(f"{spec.model_id} has too few observations")
    if data["ordered_pair"].nunique() < min_pair_clusters:
        raise ValueError(f"{spec.model_id} has too few ordered-pair clusters")
    if data["date"].nunique() < min_date_clusters:
        raise ValueError(f"{spec.model_id} has too few date clusters")
    fixed_effects = (
        data["ordered_pair"],
        data["calendar_month"],
    )
    residual = absorb_fixed_effects(
        data[[spec.outcome, *spec.predictors]], *fixed_effects
    )
    fit = ols_clustered(
        residual[spec.outcome],
        residual[list(spec.predictors)],
        data["ordered_pair"],
        add_constant=False,
        absorbed_groups=fixed_effects,
        additional_clusters=(data["date"],),
        min_observations=min_observations,
        min_clusters=min(min_pair_clusters, min_date_clusters),
    )
    if not np.isfinite(fit.beta).all() or not np.isfinite(
        fit.standard_errors
    ).all():
        raise ValueError(f"{spec.model_id} is not estimable")
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        spec.predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "eth_stress_executability_regression",
                "model_id": spec.model_id,
                "chain_stage": spec.chain_stage,
                "sample": spec.sample,
                "outcome": spec.outcome,
                "predictor": predictor,
                "coefficient": float(coefficient),
                "standard_error": float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "holm_p_value": np.nan,
                "focal_decline_coefficient": predictor == "eth_decline_per_10pp",
                "multiplicity_family": spec.multiplicity_family,
                "observations": int(fit.n_observations),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "dates": int(data["date"].nunique()),
                "fixed_effects": "ordered_pair+calendar_month",
                "time_controls": "linear_calendar_time_in_years",
                "date_effects": "not_absorbed_marketwide_eth_return_is_date_level",
                "covariance": "ordered_pair_and_exact_date_cluster_cr1",
                "stress_timing": "canonical_weth_return_days_minus_30_through_minus_1",
                "exact_route_state": "same_pair_notional_pretrade_state_and_public_venue_set",
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data[spec.outcome].mean()),
                "causal_interpretation": False,
            }
        )
    return rows


def fit_chain_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 500,
    min_pair_clusters: int = 20,
    min_date_clusters: int = 20,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for spec in MODEL_SPECS:
        rows.extend(
            _fit_model(
                panel,
                spec,
                min_observations=min_observations,
                min_pair_clusters=min_pair_clusters,
                min_date_clusters=min_date_clusters,
            )
        )
    result = pd.DataFrame(rows)
    focal = result["focal_decline_coefficient"].astype(bool)
    for _, positions in result[focal].groupby("multiplicity_family").groups.items():
        result.loc[positions, "holm_p_value"] = holm_adjusted_pvalues(
            result.loc[positions, "p_value"]
        )
    if result.empty or result.loc[focal, "holm_p_value"].isna().any():
        raise ValueError("ETH-stress executability results are empty or incomplete")
    return result


def support_records(
    frontier_support: dict[str, int],
    contestable: pd.DataFrame,
    panel: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "eth_stress_executability_support",
                **frontier_support,
                "symmetric_common_support_rows": int(
                    contestable["symmetric_common_support"].sum()
                ),
                "common_positive_depth_rows": int(len(panel)),
                "common_positive_depth_share_of_contestable": float(
                    len(panel) / len(contestable)
                ),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "dates": int(panel["date"].nunique()),
                "first_date": panel["date"].min().strftime("%Y-%m-%d"),
                "last_date": panel["date"].max().strftime("%Y-%m-%d"),
                "median_input_usd": float(panel["input_usd"].median()),
                "stable_route_share": float(panel["chosen_stable"].mean()),
                "median_stable_v2_capital_share": float(
                    panel["stable_v2_capital_share"].median()
                ),
                "median_exact_stable_output_advantage_bps": float(
                    100.0 * panel["stable_output_advantage_100bp"].median()
                ),
                "unit": "observed_exact_route_opportunity",
                "depth_measure": "prior_calendar_v2_sushiv2_weak_leg_deposited_usd_capital",
                "depth_interpretation": "mark_to_market_pool_state_not_provider_flow",
                "output_interpretation": "exact_executable_output_same_pretrade_state",
                "choice_interpretation": "realised_vehicle_family_conditional_both_feasible",
                "lp_withdrawal_interpretation": "measured_separately_not_in_this_output",
            }
        ]
    )


def run(
    *,
    frontier_path: Path = FRONTIER,
    pool_capital_path: Path = POOL_CAPITAL,
    price_path: Path = PRICE_INPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    raw_frontier = pd.read_parquet(frontier_path)
    contestable, frontier_support = prepare_frontier(raw_frontier)
    capital = load_lagged_v2_bridge_capital(contestable, pool_capital_path)
    stress = build_trailing_eth_state(load_weth_prices(price_path))
    panel = prepare_executability_panel(contestable, capital, stress)
    results = fit_chain_models(panel)
    support = support_records(frontier_support, contestable, panel)
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results):,} coefficients for {len(panel):,} exact routes "
        f"across {panel['ordered_pair'].nunique():,} ordered pairs"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        frontier_path=args.frontier,
        pool_capital_path=args.pool_capital,
        price_path=args.prices,
        result_output=args.result_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
