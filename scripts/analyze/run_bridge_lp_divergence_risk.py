#!/usr/bin/env python3
"""Relate prior relative-price risk to constant-product bridge depth.

The unit is an endpoint-pair, monthly anchor date, and candidate vehicle. Each
anchor uses endpoint-pair activity from the preceding calendar month. Risk uses
daily endpoint-minus-vehicle returns from days -30 through -1. Deposited
capital is the exact prior-calendar state in full-range Uniswap V2 and
SushiSwap V2 pools. The comparison keeps endpoint-pair-by-date and candidate
fixed effects and clusters by endpoint pair and anchor date.

This is suggestive evidence about equilibrium liquidity allocation. Relative
price risk is not an exogenous LP-supply shock, and deposited capital is not a
provider-level flow or return.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output


CHOICES = DATA_DIR / "processed/endpoint_candidate_choices.parquet"
POOL_CAPITAL = DATA_DIR / "processed/pool_capital_daily.parquet"
TOKEN_PRICES = DATA_DIR / "processed/token_price_daily.parquet"
MODEL_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_divergence_risk_models.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_divergence_risk_support.jsonl"

SAMPLE_START = pd.Timestamp("2020-06-01")
SAMPLE_END = pd.Timestamp("2026-05-01")
RISK_DAYS = 30
MIN_RISK_OBSERVATIONS = 20
MIN_PRIOR_PAIR_ROUTES = 10
CAPITAL_STATUS = "exact_state_prior_calendar"

CANDIDATES = (
    ("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "native"),
    ("DAI", "0x6b175474e89094c44da98b954eedeac495271d0f", "stable"),
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "stable"),
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", "stable"),
)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    column_order: int
    outcome: str
    risk_predictor: str
    future_depth: bool


MODEL_SPECS = (
    ModelSpec(
        "m1_prior_depth_volatility",
        1,
        "log_prior_bridge_depth",
        "bridge_relative_volatility",
        False,
    ),
    ModelSpec(
        "m2_prior_depth_divergence_loss",
        2,
        "log_prior_bridge_depth",
        "bridge_daily_divergence_loss_bps",
        False,
    ),
    ModelSpec(
        "m3_future_depth_volatility",
        3,
        "log_future_bridge_depth",
        "bridge_relative_volatility",
        True,
    ),
    ModelSpec(
        "m4_future_depth_divergence_loss",
        4,
        "log_future_bridge_depth",
        "bridge_daily_divergence_loss_bps",
        True,
    ),
)


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _candidate_values() -> str:
    return ",\n".join(
        f"('{symbol}','{address}','{kind}')"
        for symbol, address, kind in CANDIDATES
    )


def build_bridge_risk_panel(
    *,
    choices_path: Path = CHOICES,
    pool_capital_path: Path = POOL_CAPITAL,
    token_prices_path: Path = TOKEN_PRICES,
    sample_start: pd.Timestamp = SAMPLE_START,
    sample_end: pd.Timestamp = SAMPLE_END,
    risk_days: int = RISK_DAYS,
    min_risk_observations: int = MIN_RISK_OBSERVATIONS,
    min_prior_pair_routes: int = MIN_PRIOR_PAIR_ROUTES,
) -> pd.DataFrame:
    """Build monthly vehicle rows with strictly prior risk and capital states."""

    for path in (choices_path, pool_capital_path, token_prices_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if risk_days < 2 or min_risk_observations < 2:
        raise ValueError("risk windows require at least two observations")
    if min_risk_observations > risk_days:
        raise ValueError("minimum risk observations exceed the risk window")
    if min_prior_pair_routes < 1:
        raise ValueError("minimum prior pair routes must be positive")

    choice_path = _sql_path(choices_path)
    capital_path = _sql_path(pool_capital_path)
    price_path = _sql_path(token_prices_path)
    start = pd.Timestamp(sample_start).strftime("%Y-%m-%d")
    end = pd.Timestamp(sample_end).strftime("%Y-%m-%d")
    query = f"""
    WITH candidates(candidate_symbol, candidate_address, candidate_type) AS (
        VALUES {_candidate_values()}
    ),
    choice_daily AS (
        SELECT
            CAST(date AS DATE) AS origin_date,
            lower(src) AS src,
            lower(tgt) AS tgt,
            lower(candidate_address) AS candidate_address,
            sum(route_count)::DOUBLE AS route_count
        FROM read_parquet('{choice_path}')
        WHERE CAST(date AS DATE) >= DATE '{start}' - INTERVAL 1 MONTH
          AND CAST(date AS DATE) < DATE '{end}'
        GROUP BY 1,2,3,4
    ),
    pair_month AS (
        SELECT
            (date_trunc('month', origin_date) + INTERVAL 1 MONTH)::DATE
                AS anchor_date,
            src,
            tgt,
            sum(route_count)::DOUBLE AS prior_pair_routes
        FROM choice_daily
        GROUP BY 1,2,3
        HAVING sum(route_count) >= {int(min_prior_pair_routes)}
    ),
    candidate_month AS (
        SELECT
            (date_trunc('month', d.origin_date) + INTERVAL 1 MONTH)::DATE
                AS anchor_date,
            d.src,
            d.tgt,
            d.candidate_address,
            sum(d.route_count)::DOUBLE AS prior_candidate_routes
        FROM choice_daily d
        JOIN candidates c USING (candidate_address)
        GROUP BY 1,2,3,4
    ),
    opportunities AS (
        SELECT
            row_number() OVER ()::BIGINT AS opportunity_id,
            p.anchor_date,
            p.src,
            p.tgt,
            p.src || '|' || p.tgt AS ordered_pair,
            strftime(p.anchor_date, '%Y%m%d') || '|' || p.src || '|' || p.tgt
                AS pair_date_id,
            c.candidate_symbol,
            c.candidate_address,
            c.candidate_type,
            p.prior_pair_routes,
            coalesce(m.prior_candidate_routes, 0)::DOUBLE
                AS prior_candidate_routes
        FROM pair_month p
        CROSS JOIN candidates c
        LEFT JOIN candidate_month m
          ON m.anchor_date = p.anchor_date
         AND m.src = p.src
         AND m.tgt = p.tgt
         AND m.candidate_address = c.candidate_address
        WHERE p.anchor_date BETWEEN DATE '{start}' AND DATE '{end}'
          AND c.candidate_address NOT IN (p.src, p.tgt)
    ),
    pair_capital AS (
        SELECT
            strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
            least(lower(token0_address), lower(token1_address)) AS token_a,
            greatest(lower(token0_address), lower(token1_address)) AS token_b,
            sum(capital_usd_lagged)::DOUBLE AS pair_capital_usd,
            count(DISTINCT pool)::INTEGER AS pool_count
        FROM read_parquet('{capital_path}')
        WHERE quantity_kind = 'deposited_capital'
          AND capital_validation_status = '{CAPITAL_STATUS}'
          AND capital_usd_lagged > 0
          AND pool_family = 'full_range_constant_product'
          AND invariant_family = 'full_range_constant_product'
        GROUP BY 1,2,3
    ),
    depth AS (
        SELECT
            o.*,
            coalesce(c1.pair_capital_usd, 0)::DOUBLE AS prior_leg1_capital,
            coalesce(c2.pair_capital_usd, 0)::DOUBLE AS prior_leg2_capital,
            coalesce(f1.pair_capital_usd, 0)::DOUBLE AS future_leg1_capital,
            coalesce(f2.pair_capital_usd, 0)::DOUBLE AS future_leg2_capital,
            least(
                coalesce(c1.pair_capital_usd, 0),
                coalesce(c2.pair_capital_usd, 0)
            )::DOUBLE AS prior_bridge_depth,
            least(
                coalesce(f1.pair_capital_usd, 0),
                coalesce(f2.pair_capital_usd, 0)
            )::DOUBLE AS future_bridge_depth
        FROM opportunities o
        LEFT JOIN pair_capital c1
          ON c1.origin_date = o.anchor_date
         AND c1.token_a = least(o.src, o.candidate_address)
         AND c1.token_b = greatest(o.src, o.candidate_address)
        LEFT JOIN pair_capital c2
          ON c2.origin_date = o.anchor_date
         AND c2.token_a = least(o.tgt, o.candidate_address)
         AND c2.token_b = greatest(o.tgt, o.candidate_address)
        LEFT JOIN pair_capital f1
          ON f1.origin_date = o.anchor_date + INTERVAL 30 DAY
         AND f1.token_a = least(o.src, o.candidate_address)
         AND f1.token_b = greatest(o.src, o.candidate_address)
        LEFT JOIN pair_capital f2
          ON f2.origin_date = o.anchor_date + INTERVAL 30 DAY
         AND f2.token_a = least(o.tgt, o.candidate_address)
         AND f2.token_b = greatest(o.tgt, o.candidate_address)
    ),
    comparable_pair_dates AS (
        SELECT pair_date_id
        FROM depth
        GROUP BY 1
        HAVING count(*) >= 2
           AND max((candidate_type = 'native')::INTEGER) = 1
           AND max((candidate_type = 'stable')::INTEGER) = 1
           AND max((candidate_type = 'native'
                    AND prior_bridge_depth > 0)::INTEGER) = 1
           AND max((candidate_type = 'stable'
                    AND prior_bridge_depth > 0)::INTEGER) = 1
    ),
    comparable_opportunities AS MATERIALIZED (
        SELECT d.*
        FROM depth d
        JOIN comparable_pair_dates g USING (pair_date_id)
    ),
    price_level AS (
        SELECT
            strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
            lower(token) AS token,
            ln(price_usd)::DOUBLE AS log_price,
            lag(ln(price_usd)) OVER (
                PARTITION BY lower(token)
                ORDER BY strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE
            )::DOUBLE AS lag_log_price,
            lag(strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE) OVER (
                PARTITION BY lower(token)
                ORDER BY strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE
            ) AS lag_date
        FROM read_parquet('{price_path}')
        WHERE price_usd > 0
          AND strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE
                BETWEEN DATE '{start}' - INTERVAL {int(risk_days + 1)} DAY
                    AND DATE '{end}'
    ),
    token_return AS (
        SELECT
            origin_date,
            token,
            log_price - lag_log_price AS log_return
        FROM price_level
        WHERE date_diff('day', lag_date, origin_date) = 1
    ),
    leg_request AS (
        SELECT
            opportunity_id,
            anchor_date,
            candidate_address,
            'source' AS leg,
            src AS endpoint_address
        FROM comparable_opportunities
        UNION ALL
        SELECT
            opportunity_id,
            anchor_date,
            candidate_address,
            'target' AS leg,
            tgt AS endpoint_address
        FROM comparable_opportunities
    ),
    leg_risk AS (
        SELECT
            r.opportunity_id,
            r.leg,
            count(*)::INTEGER AS risk_observations,
            stddev_samp(e.log_return - v.log_return) * sqrt(365.0)
                AS annualized_relative_volatility,
            avg(
                1.0 - 1.0 / cosh((e.log_return - v.log_return) / 2.0)
            ) * 10000.0 AS daily_divergence_loss_bps
        FROM leg_request r
        JOIN token_return e
          ON e.token = r.endpoint_address
         AND e.origin_date >= r.anchor_date - INTERVAL {int(risk_days)} DAY
         AND e.origin_date < r.anchor_date
        JOIN token_return v
          ON v.token = r.candidate_address
         AND v.origin_date = e.origin_date
        GROUP BY 1,2
        HAVING count(*) >= {int(min_risk_observations)}
    ),
    bridge_risk AS (
        SELECT
            opportunity_id,
            greatest(
                max(CASE WHEN leg = 'source'
                         THEN annualized_relative_volatility END),
                max(CASE WHEN leg = 'target'
                         THEN annualized_relative_volatility END)
            )::DOUBLE AS bridge_relative_volatility,
            greatest(
                max(CASE WHEN leg = 'source'
                         THEN daily_divergence_loss_bps END),
                max(CASE WHEN leg = 'target'
                         THEN daily_divergence_loss_bps END)
            )::DOUBLE AS bridge_daily_divergence_loss_bps,
            least(
                max(CASE WHEN leg = 'source' THEN risk_observations END),
                max(CASE WHEN leg = 'target' THEN risk_observations END)
            )::INTEGER AS bridge_risk_observations
        FROM leg_risk
        GROUP BY 1
        HAVING count(*) = 2
    ),
    risk_depth AS (
        SELECT
            o.*,
            r.bridge_relative_volatility,
            r.bridge_daily_divergence_loss_bps,
            r.bridge_risk_observations
        FROM comparable_opportunities o
        JOIN bridge_risk r USING (opportunity_id)
    ),
    risk_comparable_pair_dates AS (
        SELECT pair_date_id
        FROM risk_depth
        GROUP BY 1
        HAVING count(*) >= 2
           AND max((candidate_type = 'native')::INTEGER) = 1
           AND max((candidate_type = 'stable')::INTEGER) = 1
    )
    SELECT d.*
    FROM risk_depth d
    JOIN risk_comparable_pair_dates g USING (pair_date_id)
    ORDER BY anchor_date, src, tgt, candidate_symbol
    """
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=4")
        connection.execute("PRAGMA memory_limit='48GB'")
        connection.execute("PRAGMA temp_directory='/tmp/ddvc_bridge_lp_risk'")
        connection.execute("PRAGMA preserve_insertion_order=false")
        frame = connection.execute(query).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("bridge LP-risk panel is empty")

    frame["anchor_date"] = pd.to_datetime(frame["anchor_date"]).dt.normalize()
    frame["log_prior_bridge_depth"] = np.log1p(frame["prior_bridge_depth"])
    frame["log_future_bridge_depth"] = np.log1p(frame["future_bridge_depth"])
    frame["log_prior_candidate_routes"] = np.log1p(
        frame["prior_candidate_routes"]
    )
    frame["prior_bridge_supported"] = frame["prior_bridge_depth"].gt(0).astype(float)
    frame["future_bridge_supported"] = frame["future_bridge_depth"].gt(0).astype(float)
    numeric = [
        "bridge_relative_volatility",
        "bridge_daily_divergence_loss_bps",
        "log_prior_bridge_depth",
        "log_future_bridge_depth",
        "log_prior_candidate_routes",
    ]
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if frame.empty:
        raise ValueError("bridge LP-risk panel lost all rows after validation")
    group_classes = frame.groupby("pair_date_id")["candidate_type"].agg(set)
    if not group_classes.map(lambda values: {"native", "stable"}.issubset(values)).all():
        raise ValueError("bridge LP-risk panel lacks within-date vehicle classes")
    return frame.reset_index(drop=True)


def _require_finite_fit(fit: object, model_id: str) -> None:
    arrays = (
        np.asarray(fit.beta, dtype=float),
        np.asarray(fit.standard_errors, dtype=float),
        np.asarray(fit.t_statistics, dtype=float),
        np.asarray(fit.p_values, dtype=float),
        np.asarray([fit.r_squared, fit.adjusted_r_squared], dtype=float),
    )
    if not all(np.isfinite(values).all() for values in arrays):
        raise ValueError(f"{model_id} produced a nonfinite regression fit")


def fit_bridge_risk_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_pair_clusters: int = 30,
    min_date_clusters: int = 30,
) -> pd.DataFrame:
    """Fit within-pair-date, within-candidate descriptive risk regressions."""

    required = {
        "anchor_date",
        "ordered_pair",
        "pair_date_id",
        "candidate_symbol",
        "bridge_relative_volatility",
        "bridge_daily_divergence_loss_bps",
        "log_prior_bridge_depth",
        "log_future_bridge_depth",
        "log_prior_candidate_routes",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"bridge LP-risk panel lacks model columns: {missing}")

    rows: list[dict[str, object]] = []
    for spec in MODEL_SPECS:
        predictors = [spec.risk_predictor, "log_prior_candidate_routes"]
        if spec.future_depth:
            predictors.append("log_prior_bridge_depth")
        data = panel[
            [
                spec.outcome,
                *predictors,
                "pair_date_id",
                "candidate_symbol",
                "ordered_pair",
                "anchor_date",
            ]
        ].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
        if len(data) < min_observations:
            raise ValueError(f"{spec.model_id} has too few observations")
        if data["ordered_pair"].nunique() < min_pair_clusters:
            raise ValueError(f"{spec.model_id} has too few endpoint-pair clusters")
        if data["anchor_date"].nunique() < min_date_clusters:
            raise ValueError(f"{spec.model_id} has too few date clusters")

        fixed_effects = (data["pair_date_id"], data["candidate_symbol"])
        outcome = absorb_fixed_effects(data[spec.outcome], *fixed_effects)
        design = absorb_fixed_effects(data[predictors], *fixed_effects)
        fit = ols_clustered(
            outcome,
            design,
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=fixed_effects,
            additional_clusters=(data["anchor_date"],),
            min_observations=min_observations,
            min_clusters=min(min_pair_clusters, min_date_clusters),
        )
        _require_finite_fit(fit, spec.model_id)
        for name, beta, se, t_stat, p_value in zip(
            predictors,
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            coefficient = float(beta)
            standard_error = float(se)
            rows.append(
                {
                    "record_type": "bridge_lp_divergence_risk_model_coefficient",
                    "table_id": "bridge_lp_divergence_risk",
                    "model_id": spec.model_id,
                    "column_order": spec.column_order,
                    "outcome": spec.outcome,
                    "predictor": name,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "effect_log_points_per_10pp_volatility": (
                        0.10 * coefficient
                        if name == "bridge_relative_volatility"
                        else np.nan
                    ),
                    "standard_error_log_points_per_10pp_volatility": (
                        0.10 * standard_error
                        if name == "bridge_relative_volatility"
                        else np.nan
                    ),
                    "effect_log_points_per_1bp_daily_divergence_loss": (
                        coefficient
                        if name == "bridge_daily_divergence_loss_bps"
                        else np.nan
                    ),
                    "standard_error_log_points_per_1bp_daily_divergence_loss": (
                        standard_error
                        if name == "bridge_daily_divergence_loss_bps"
                        else np.nan
                    ),
                    "observations": int(fit.n_observations),
                    "endpoint_pair_clusters": int(fit.cluster_counts[0]),
                    "anchor_date_clusters": int(fit.cluster_counts[1]),
                    "r_squared_within": float(fit.r_squared),
                    "adjusted_r_squared_within": float(fit.adjusted_r_squared),
                    "dependent_mean": float(data[spec.outcome].mean()),
                    "fixed_effects": "ordered_endpoint_pair_x_anchor_date+candidate",
                    "covariance_id": "endpoint_pair_and_anchor_date_cluster_cr1",
                    "risk_window": "days_-30_to_-1",
                    "capital_timing": (
                        "anchor_plus_30_prior_calendar_state"
                        if spec.future_depth
                        else "anchor_prior_calendar_state"
                    ),
                    "interpretation": "suggestive_equilibrium_association_not_causal",
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["column_order", "predictor"]
    ).reset_index(drop=True)


def support_records(panel: pd.DataFrame) -> pd.DataFrame:
    """Describe sample coverage and the unavailable fee/volume control."""

    type_medians = panel.groupby("candidate_type").median(numeric_only=True)
    risk_by_pair_date = panel.pivot_table(
        index="pair_date_id",
        columns="candidate_type",
        values=(
            "bridge_relative_volatility",
            "bridge_daily_divergence_loss_bps",
        ),
        aggfunc="mean",
    ).dropna()
    volatility_gap = (
        risk_by_pair_date[("bridge_relative_volatility", "stable")]
        - risk_by_pair_date[("bridge_relative_volatility", "native")]
    )
    divergence_gap = (
        risk_by_pair_date[("bridge_daily_divergence_loss_bps", "stable")]
        - risk_by_pair_date[("bridge_daily_divergence_loss_bps", "native")]
    )
    return pd.DataFrame(
        [
            {
                "record_type": "bridge_lp_divergence_risk_sample",
                "observations": int(len(panel)),
                "pair_dates": int(panel["pair_date_id"].nunique()),
                "ordered_endpoint_pairs": int(panel["ordered_pair"].nunique()),
                "candidate_vehicles": int(panel["candidate_symbol"].nunique()),
                "anchor_dates": int(panel["anchor_date"].nunique()),
                "first_anchor_date": panel["anchor_date"].min(),
                "last_anchor_date": panel["anchor_date"].max(),
                "anchor_years": ",".join(
                    str(int(year))
                    for year in sorted(panel["anchor_date"].dt.year.unique())
                ),
                "prior_bridge_support_share": float(
                    panel["prior_bridge_supported"].mean()
                ),
                "future_bridge_support_share": float(
                    panel["future_bridge_supported"].mean()
                ),
                "median_bridge_relative_volatility": float(
                    panel["bridge_relative_volatility"].median()
                ),
                "median_daily_divergence_loss_bps": float(
                    panel["bridge_daily_divergence_loss_bps"].median()
                ),
                "median_native_bridge_relative_volatility": float(
                    type_medians.loc["native", "bridge_relative_volatility"]
                ),
                "median_stable_bridge_relative_volatility": float(
                    type_medians.loc["stable", "bridge_relative_volatility"]
                ),
                "median_native_daily_divergence_loss_bps": float(
                    type_medians.loc[
                        "native", "bridge_daily_divergence_loss_bps"
                    ]
                ),
                "median_stable_daily_divergence_loss_bps": float(
                    type_medians.loc[
                        "stable", "bridge_daily_divergence_loss_bps"
                    ]
                ),
                "mean_stable_minus_native_relative_volatility": float(
                    volatility_gap.mean()
                ),
                "share_pair_dates_stable_relative_volatility_lower": float(
                    volatility_gap.lt(0).mean()
                ),
                "mean_stable_minus_native_daily_divergence_loss_bps": float(
                    divergence_gap.mean()
                ),
                "share_pair_dates_stable_divergence_loss_lower": float(
                    divergence_gap.lt(0).mean()
                ),
                "risk_window_days": RISK_DAYS,
                "minimum_risk_observations": MIN_RISK_OBSERVATIONS,
                "minimum_prior_pair_routes": MIN_PRIOR_PAIR_ROUTES,
                "pool_families": "uniswap_v2+sushiswap_v2_full_range_constant_product",
                "capital_measurement": "exact_prior_calendar_deposited_capital",
                "fee_control_status": "unavailable_zero_nonmissing_exact_capital_rows",
                "volume_control_status": "unavailable_zero_nonmissing_exact_capital_rows",
                "route_activity_control": "log_prior_calendar_month_candidate_routes",
                "stable_risk_conjecture_status": (
                    "not_supported_in_aggregate_bridge_comparison"
                ),
                "interpretation": "suggestive_equilibrium_association_not_causal",
            }
        ]
    )


def run(
    *,
    choices_path: Path = CHOICES,
    pool_capital_path: Path = POOL_CAPITAL,
    token_prices_path: Path = TOKEN_PRICES,
    model_output: Path = MODEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    panel = build_bridge_risk_panel(
        choices_path=choices_path,
        pool_capital_path=pool_capital_path,
        token_prices_path=token_prices_path,
    )
    models = fit_bridge_risk_models(panel)
    support = support_records(panel)
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
    print(f"wrote {len(models):,} model rows and {len(support):,} support rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--token-prices", type=Path, default=TOKEN_PRICES)
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pool_capital_path=args.pool_capital,
        token_prices_path=args.token_prices,
        model_output=args.model_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
