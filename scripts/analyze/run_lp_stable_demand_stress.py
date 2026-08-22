#!/usr/bin/env python3
"""Test whether ETH stress precedes LP supply toward stablecoin legs.

The unit is an endpoint--candidate pool week.  The analysis reuses the balanced
Uniswap V2 and V3 LP-supply panels and compares stablecoin pools with WETH pools
for the same noncandidate endpoint and week.  Week-t ETH realised volatility
and return are measured from the canonical daily WETH price; LP additions,
withdrawals, and net supply occur in week t+1.

Endpoint-by-week effects absorb every endpoint-wide demand condition in week t,
while pool effects absorb persistent pool differences.  The focal coefficients
are therefore stablecoin-minus-WETH response slopes.  The ETH-return coefficient
is reported with its sign reversed, so a positive number means that a 10 percent
ETH decline predicts relatively more supply toward stablecoin legs.  Fee yield,
endpoint--candidate relative-price risk, earlier additions and withdrawals,
capital, and pool age follow the retained LP-supply designs.

The four additions coefficients (two stress measures by two venues) form the
primary Holm-adjusted family.  Withdrawals and net supply form separate
four-test secondary families.  These are predictive associations, not shocks
to stablecoin demand or provider preferences, and no route-use variable enters.

Writes
  output/exhibits/lp_stable_demand_stress_models.jsonl
  output/exhibits/lp_stable_demand_stress_support.jsonl
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.asset_types import STABLE
from ddvc.capital_contracts import MAX_POOL_CAPITAL_USD
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit


V2_PANEL_INPUT = OUTPUT_DIR / "exhibits/lp_supply_returns_weekly.parquet"
V3_PANEL_INPUT = OUTPUT_DIR / "exhibits/v3_lp_supply_returns_weekly.parquet"
PRICE_INPUT = DATA_DIR / "processed/token_price_daily.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/lp_stable_demand_stress_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/lp_stable_demand_stress_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
MATERIAL_CAPITAL_USD = 50_000.0
MAX_V3_TVL_STALENESS_WEEKS = 4
MIN_ETH_RETURN_DAYS = 7

CODE_SOURCES = ["scripts/analyze/run_lp_stable_demand_stress.py"]
INPUTS = [
    "output/exhibits/lp_supply_returns_weekly.parquet",
    "output/exhibits/v3_lp_supply_returns_weekly.parquet",
    "data/processed/token_price_daily.parquet",
]


@dataclass(frozen=True)
class VenueDesign:
    venue: str
    capital_column: str
    age_column: str
    maximum_staleness_column: str | None = None


VENUE_DESIGNS = (
    VenueDesign("uniswap_v2", "capital_usd", "pool_age_weeks"),
    VenueDesign(
        "uniswap_v3",
        "tvl_usd",
        "observed_pool_age_weeks",
        "tvl_staleness_weeks",
    ),
)

OUTCOMES = (
    ("additions", "next_log1p_add_flow_ratio", "primary_additions"),
    ("withdrawals", "next_log1p_remove_flow_ratio", "secondary_withdrawals"),
    ("net_supply", "next_asinh_net_flow_ratio", "secondary_net_supply"),
)

FOCAL_VOLATILITY = "stable_x_eth_realized_volatility"
FOCAL_DECLINE = "stable_x_eth_decline"
STABLE_ADDRESSES = {address.casefold() for address in STABLE}


def _parquet_columns(path: Path) -> set[str]:
    connection = duckdb.connect()
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        }
    finally:
        connection.close()


def load_weth_prices(path: Path = PRICE_INPUT) -> pd.DataFrame:
    """Load the canonical daily WETH price without reading unrelated tokens."""

    if not path.is_file():
        raise FileNotFoundError(path)
    columns = _parquet_columns(path)
    required = {"day", "token", "price_usd"}
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"daily price input lacks columns: {missing}")
    filters = ["lower(token) = ?", "price_usd > 0"]
    parameters: list[object] = [WETH]
    if "price_source" in columns:
        filters.append("price_source = 'canonical_repriced_route_legs'")
    if "validation_status" in columns:
        filters.append(
            "validation_status = "
            "'minimum_observations_and_price_consensus_passed'"
        )
    query = f"""
    SELECT
        strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
        price_usd::DOUBLE AS price_usd
    FROM read_parquet(?)
    WHERE {' AND '.join(filters)}
    ORDER BY origin_date
    """
    connection = duckdb.connect()
    try:
        frame = connection.execute(query, [str(path), *parameters]).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("canonical WETH daily price series is empty")
    return frame


def build_weekly_eth_stress(
    prices: pd.DataFrame,
    *,
    min_return_days: int = MIN_ETH_RETURN_DAYS,
) -> pd.DataFrame:
    """Build complete Monday--Sunday ETH return and realised-volatility weeks."""

    required = {"origin_date", "price_usd"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"WETH price frame lacks columns: {missing}")
    if min_return_days < 2 or min_return_days > 7:
        raise ValueError("ETH weekly stress requires two to seven return days")
    frame = prices[list(required)].copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    frame["price_usd"] = pd.to_numeric(frame["price_usd"], errors="coerce")
    frame = frame.sort_values("origin_date").reset_index(drop=True)
    if frame.duplicated("origin_date").any():
        raise ValueError("WETH daily price series has duplicate dates")
    if frame["price_usd"].isna().any() or frame["price_usd"].le(0).any():
        raise ValueError("WETH daily prices must be finite and positive")
    frame["lag_date"] = frame["origin_date"].shift(1)
    frame["log_return"] = np.log(frame["price_usd"]).diff()
    consecutive = frame["origin_date"].sub(frame["lag_date"]).dt.days.eq(1)
    frame.loc[~consecutive, "log_return"] = np.nan
    frame["origin_week"] = frame["origin_date"] - pd.to_timedelta(
        frame["origin_date"].dt.weekday, unit="D"
    )
    frame["return_sq"] = frame["log_return"].pow(2)
    weekly = (
        frame.groupby("origin_week", as_index=False, sort=True)
        .agg(
            eth_return=("log_return", "sum"),
            eth_return_sq_sum=("return_sq", "sum"),
            eth_return_days=("log_return", "count"),
        )
        .sort_values("origin_week")
        .reset_index(drop=True)
    )
    weekly = weekly[weekly["eth_return_days"].ge(min_return_days)].copy()
    weekly["eth_realized_volatility"] = np.sqrt(
        365.0
        * weekly["eth_return_sq_sum"]
        / weekly["eth_return_days"].astype(float)
    )
    weekly["eth_realized_volatility_per_10pp"] = (
        weekly["eth_realized_volatility"] / 0.10
    )
    weekly["eth_return_per_10pp"] = weekly["eth_return"] / 0.10
    if weekly.empty or not np.isfinite(
        weekly[
            ["eth_realized_volatility_per_10pp", "eth_return_per_10pp"]
        ].to_numpy(dtype=float)
    ).all():
        raise ValueError("weekly ETH stress series is empty or nonfinite")
    return weekly


def load_lp_panel(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)


def prepare_venue_sample(
    panel: pd.DataFrame,
    stress: pd.DataFrame,
    design: VenueDesign,
    *,
    material_capital_usd: float = MATERIAL_CAPITAL_USD,
) -> pd.DataFrame:
    """Harmonise a venue and retain endpoint-weeks with both vehicle families."""

    required = {
        "origin_week",
        "candidate_type",
        "endpoint_address",
        "pool_id",
        "endpoint_week_id",
        design.capital_column,
        design.age_column,
        "fee_yield_per_10bps",
        "trailing_relative_volatility_per_10pp",
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "next_log1p_add_flow_ratio",
        "next_log1p_remove_flow_ratio",
        "next_asinh_net_flow_ratio",
    }
    if design.maximum_staleness_column is not None:
        required.add(design.maximum_staleness_column)
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"{design.venue} LP panel lacks columns: {missing}")
    if material_capital_usd <= 0:
        raise ValueError("material pool capital must be positive")
    data = panel[list(required)].copy()
    data["origin_week"] = pd.to_datetime(data["origin_week"]).dt.normalize()
    data["candidate_type"] = data["candidate_type"].astype(str)
    data = data[data["candidate_type"].isin(["native", "stable"])].copy()
    data["pool_capital_usd"] = pd.to_numeric(
        data[design.capital_column], errors="coerce"
    )
    data["pool_age_weeks"] = pd.to_numeric(
        data[design.age_column], errors="coerce"
    )
    valid = data["pool_capital_usd"].ge(material_capital_usd)
    if design.venue == "uniswap_v3":
        valid &= data["pool_capital_usd"].le(MAX_POOL_CAPITAL_USD)
    if design.maximum_staleness_column is not None:
        valid &= pd.to_numeric(
            data[design.maximum_staleness_column], errors="coerce"
        ).le(MAX_V3_TVL_STALENESS_WEEKS)
    data = data.loc[valid].copy()
    families = data.groupby("endpoint_week_id")["candidate_type"].agg(set)
    eligible = families[
        families.map(lambda values: {"native", "stable"}.issubset(values))
    ].index
    data = data[data["endpoint_week_id"].isin(eligible)].copy()
    data = data.merge(
        stress[
            [
                "origin_week",
                "eth_return_days",
                "eth_realized_volatility",
                "eth_realized_volatility_per_10pp",
                "eth_return",
                "eth_return_per_10pp",
            ]
        ],
        on="origin_week",
        how="inner",
        validate="many_to_one",
    )
    data["stable_indicator"] = data["candidate_type"].eq("stable").astype(float)
    data["endpoint_is_stable"] = (
        data["endpoint_address"].astype(str).str.casefold().isin(STABLE_ADDRESSES)
    )
    data["log_pool_capital_usd"] = np.log(data["pool_capital_usd"])
    data["log1p_pool_age_weeks"] = np.log1p(data["pool_age_weeks"].clip(lower=0))
    data["venue"] = design.venue
    data = data.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
    if data.empty:
        raise ValueError(f"{design.venue} ETH-stress LP comparison is empty")
    return data


def _fit_outcome(
    data: pd.DataFrame,
    *,
    venue: str,
    outcome_name: str,
    outcome: str,
    multiplicity_family: str,
    min_observations: int,
    min_pool_clusters: int,
    min_week_clusters: int,
) -> list[dict[str, object]]:
    predictors = [
        FOCAL_VOLATILITY,
        "stable_x_eth_return",
        "fee_yield_per_10bps",
        "trailing_relative_volatility_per_10pp",
        "stable_x_fee_yield",
        "stable_x_pair_relative_volatility",
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_pool_capital_usd",
        "log1p_pool_age_weeks",
    ]
    columns = [
        outcome,
        "stable_indicator",
        "eth_realized_volatility_per_10pp",
        "eth_return_per_10pp",
        "fee_yield_per_10bps",
        "trailing_relative_volatility_per_10pp",
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_pool_capital_usd",
        "log1p_pool_age_weeks",
        "endpoint_week_id",
        "pool_id",
        "origin_week",
        "endpoint_address",
    ]
    model = data[columns].dropna().reset_index(drop=True)
    for column in (
        outcome,
        "fee_yield_per_10bps",
        "trailing_relative_volatility_per_10pp",
        "trailing_log1p_add_flow_ratio",
        "trailing_log1p_remove_flow_ratio",
        "log_pool_capital_usd",
        "log1p_pool_age_weeks",
    ):
        lower, upper = model[column].quantile([0.01, 0.99])
        if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
            model[column] = model[column].clip(lower=float(lower), upper=float(upper))
    stable = model["stable_indicator"].astype(float)
    model[FOCAL_VOLATILITY] = (
        stable * model["eth_realized_volatility_per_10pp"].astype(float)
    )
    model["stable_x_eth_return"] = (
        stable * model["eth_return_per_10pp"].astype(float)
    )
    model["stable_x_fee_yield"] = stable * model["fee_yield_per_10bps"].astype(float)
    model["stable_x_pair_relative_volatility"] = (
        stable * model["trailing_relative_volatility_per_10pp"].astype(float)
    )
    if len(model) < min_observations:
        raise ValueError(f"{venue} {outcome_name} has too few observations")
    if model["pool_id"].nunique() < min_pool_clusters:
        raise ValueError(f"{venue} {outcome_name} has too few pool clusters")
    if model["origin_week"].nunique() < min_week_clusters:
        raise ValueError(f"{venue} {outcome_name} has too few week clusters")
    fixed_effects = (model["endpoint_week_id"], model["pool_id"])
    residual_outcome = absorb_fixed_effects(model[outcome], *fixed_effects)
    residual_design = absorb_fixed_effects(model[predictors], *fixed_effects)
    fit = ols_clustered(
        residual_outcome,
        residual_design,
        model["pool_id"],
        add_constant=False,
        absorbed_groups=fixed_effects,
        additional_clusters=(model["origin_week"],),
        min_observations=min_observations,
        min_clusters=min(min_pool_clusters, min_week_clusters),
    )
    common = {
        "record_type": "lp_stable_demand_stress_coefficient",
        "venue": venue,
        "outcome_name": outcome_name,
        "outcome": outcome,
        "material_capital_usd": float(MATERIAL_CAPITAL_USD),
        "observations": int(fit.n_observations),
        "pools": int(model["pool_id"].nunique()),
        "weeks": int(model["origin_week"].nunique()),
        "endpoints": int(model["endpoint_address"].nunique()),
        "fixed_effects": "endpoint_x_week+pool",
        "covariance": "pool_and_week_cluster_cr1",
        "stress_timing": "week_t_monday_through_sunday",
        "outcome_timing": "week_t_plus_1",
        "conditioning": (
            "prior_four_week_fee_yield+pair_relative_volatility+additions+"
            "withdrawals+pool_capital+pool_age"
        ),
        "multiplicity_family": multiplicity_family,
        "interpretation": "predictive_stablecoin_minus_weth_lp_supply_response",
        "route_use_variables": "none",
    }
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, t_statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        reported_predictor = predictor
        reported_coefficient = float(coefficient)
        reported_t = float(t_statistic)
        focal = predictor in {FOCAL_VOLATILITY, "stable_x_eth_return"}
        effect_unit = "native_model_unit"
        if predictor == FOCAL_VOLATILITY:
            effect_unit = "per_10pp_higher_annualized_weekly_eth_volatility"
        elif predictor == "stable_x_eth_return":
            reported_predictor = FOCAL_DECLINE
            reported_coefficient = -reported_coefficient
            reported_t = -reported_t
            effect_unit = "per_10pp_eth_decline"
        rows.append(
            {
                **common,
                "predictor": reported_predictor,
                "coefficient": reported_coefficient,
                "standard_error": float(standard_error),
                "t_statistic": reported_t,
                "p_value": float(p_value),
                "holm_p_value": np.nan,
                "focal_family_member": focal,
                "effect_unit": effect_unit,
                "r_squared_within": float(fit.r_squared),
                "adjusted_r_squared_within": float(fit.adjusted_r_squared),
            }
        )
    return rows


def fit_stress_models(
    venue_samples: dict[str, pd.DataFrame],
    *,
    min_observations: int = 250,
    min_pool_clusters: int = 30,
    min_week_clusters: int = 20,
) -> pd.DataFrame:
    """Fit the two-outcome V2/V3 family and apply Holm within each outcome."""

    rows: list[dict[str, object]] = []
    for venue, data in venue_samples.items():
        for outcome_name, outcome, family in OUTCOMES:
            rows.extend(
                _fit_outcome(
                    data,
                    venue=venue,
                    outcome_name=outcome_name,
                    outcome=outcome,
                    multiplicity_family=family,
                    min_observations=min_observations,
                    min_pool_clusters=min_pool_clusters,
                    min_week_clusters=min_week_clusters,
                )
            )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("ETH-stress LP-supply model output is empty")
    focal = result["focal_family_member"].astype(bool)
    for family, positions in result[focal].groupby("multiplicity_family").groups.items():
        adjusted = holm_adjusted_pvalues(result.loc[positions, "p_value"])
        result.loc[positions, "holm_p_value"] = adjusted
    return result


def support_records(
    stress: pd.DataFrame,
    venue_samples: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "record_type": "lp_stable_demand_stress_price_support",
            "weeks": int(len(stress)),
            "first_week": stress["origin_week"].min().strftime("%Y-%m-%d"),
            "last_week": stress["origin_week"].max().strftime("%Y-%m-%d"),
            "median_annualized_eth_volatility": float(
                stress["eth_realized_volatility"].median()
            ),
            "p90_annualized_eth_volatility": float(
                stress["eth_realized_volatility"].quantile(0.90)
            ),
            "median_weekly_eth_return": float(stress["eth_return"].median()),
            "share_negative_eth_return_weeks": float(stress["eth_return"].lt(0).mean()),
            "stress_measure": (
                "complete_monday_sunday_daily_returns_from_canonical_weth_price"
            ),
        }
    ]
    for venue, data in venue_samples.items():
        rows.append(
            {
                "record_type": "lp_stable_demand_stress_sample_support",
                "venue": venue,
                "material_capital_usd": float(MATERIAL_CAPITAL_USD),
                "observations": int(len(data)),
                "endpoint_weeks": int(data["endpoint_week_id"].nunique()),
                "endpoints": int(data["endpoint_address"].nunique()),
                "pools": int(data["pool_id"].nunique()),
                "weeks": int(data["origin_week"].nunique()),
                "first_week": data["origin_week"].min().strftime("%Y-%m-%d"),
                "last_week": data["origin_week"].max().strftime("%Y-%m-%d"),
                "stable_pool_week_share": float(data["stable_indicator"].mean()),
                "known_stable_endpoint_pool_week_share": float(
                    data["endpoint_is_stable"].mean()
                ),
                "median_pool_capital_usd": float(data["pool_capital_usd"].median()),
                "outcomes": "next_week_additions_withdrawals_and_net_lp_supply",
                "comparison": "stablecoin_leg_minus_weth_leg_for_same_endpoint_week",
                "route_use_variables": "none",
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    v2_panel_path: Path = V2_PANEL_INPUT,
    v3_panel_path: Path = V3_PANEL_INPUT,
    price_path: Path = PRICE_INPUT,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    stress = build_weekly_eth_stress(load_weth_prices(price_path))
    paths = {
        "uniswap_v2": v2_panel_path,
        "uniswap_v3": v3_panel_path,
    }
    samples = {
        design.venue: prepare_venue_sample(
            load_lp_panel(paths[design.venue]), stress, design
        )
        for design in VENUE_DESIGNS
    }
    models = fit_stress_models(samples)
    support = support_records(stress, samples)
    write_exhibit(models, model_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(models):,} ETH-stress LP-supply coefficient rows and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-panel", type=Path, default=V2_PANEL_INPUT)
    parser.add_argument("--v3-panel", type=Path, default=V3_PANEL_INPUT)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        v2_panel_path=args.v2_panel,
        v3_panel_path=args.v3_panel,
        price_path=args.prices,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
