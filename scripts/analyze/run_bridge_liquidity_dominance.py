#!/usr/bin/env python3
"""Screen whether local bridge liquidity predicts vehicle choice.

The unit is a candidate vehicle inside an ordered ultimate pair x date x route
scope.  For each of the five headline vehicle candidates, the script measures
prior-calendar deposited capital on the two atomic legs that would make
``source -> candidate -> target`` feasible.  It then tests whether deeper local
bridge liquidity predicts the candidate's route share inside the same endpoint
opportunity.

This is an exploratory mechanism screen.  It is not a causal design and does
not measure executable route cost, active concentrated-liquidity depth, or LP
returns.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, linear_contrast, ols_clustered
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CHOICES_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
POOL_CAPITAL_INPUT = REPO_ROOT / "data/processed/pool_capital_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_dominance.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_dominance_support.jsonl"

BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
ENDPOINT_CUTOFF = "06-30"
CAPITAL_STATUS = "exact_state_prior_calendar"
MIN_SUPPORTED_CANDIDATES = 2
CODE_SOURCES = ["scripts/analyze/run_bridge_liquidity_dominance.py"]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/pool_capital_daily.parquet",
]


PANEL_QUERY = """
WITH candidates(candidate_symbol, candidate_address, is_stable) AS (
  VALUES
    ('WETH','0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',0),
    ('WBTC','0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',0),
    ('DAI','0x6b175474e89094c44da98b954eedeac495271d0f',1),
    ('USDC','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',1),
    ('USDT','0xdac17f958d2ee523a2206206994597c13d831ec7',1)
),
choice_group AS (
    SELECT
        CAST(date AS DATE) AS origin_date,
        lower(src) AS src,
        lower(tgt) AS tgt,
        integration_scope,
        sum(route_count)::DOUBLE AS all_candidate_routes
    FROM read_parquet(?)
    WHERE year(date) IN (?, ?)
      AND strftime(date, '%m-%d') <= ?
    GROUP BY 1, 2, 3, 4
),
five_group AS (
    SELECT
        CAST(date AS DATE) AS origin_date,
        lower(src) AS src,
        lower(tgt) AS tgt,
        integration_scope,
        sum(route_count)::DOUBLE AS five_route_total
    FROM read_parquet(?)
    WHERE year(date) IN (?, ?)
      AND strftime(date, '%m-%d') <= ?
      AND lower(candidate_address) IN (SELECT candidate_address FROM candidates)
    GROUP BY 1, 2, 3, 4
),
five_choice AS (
    SELECT
        CAST(date AS DATE) AS origin_date,
        lower(src) AS src,
        lower(tgt) AS tgt,
        integration_scope,
        lower(candidate_address) AS candidate_address,
        sum(route_count)::DOUBLE AS route_count
    FROM read_parquet(?)
    WHERE year(date) IN (?, ?)
      AND strftime(date, '%m-%d') <= ?
      AND lower(candidate_address) IN (SELECT candidate_address FROM candidates)
    GROUP BY 1, 2, 3, 4, 5
),
pair_capital AS (
    SELECT
        strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS origin_date,
        least(lower(token0_address), lower(token1_address)) AS token_a,
        greatest(lower(token0_address), lower(token1_address)) AS token_b,
        sum(capital_usd)::DOUBLE AS pair_capital_usd,
        count(DISTINCT pool)::DOUBLE AS pair_pool_count,
        count(DISTINCT venue)::DOUBLE AS pair_venue_count
    FROM read_parquet(?)
    WHERE quantity_kind = 'deposited_capital'
      AND capital_validation_status = ?
      AND capital_usd > 0
    GROUP BY 1, 2, 3
),
panel0 AS (
    SELECT
        g.origin_date,
        year(g.origin_date)::INTEGER AS year,
        g.src,
        g.tgt,
        g.integration_scope,
        c.candidate_symbol,
        c.candidate_address,
        c.is_stable::DOUBLE AS is_stable,
        coalesce(f.route_count, 0.0) AS route_count,
        fg.five_route_total,
        g.all_candidate_routes,
        coalesce(l1.pair_capital_usd, 0.0) AS leg1_capital_usd,
        coalesce(l2.pair_capital_usd, 0.0) AS leg2_capital_usd,
        coalesce(l1.pair_pool_count, 0.0) AS leg1_pool_count,
        coalesce(l2.pair_pool_count, 0.0) AS leg2_pool_count,
        least(
            coalesce(l1.pair_capital_usd, 0.0),
            coalesce(l2.pair_capital_usd, 0.0)
        ) AS bridge_min_capital_usd,
        sqrt(
            coalesce(l1.pair_capital_usd, 0.0)
            * coalesce(l2.pair_capital_usd, 0.0)
        ) AS bridge_geom_capital_usd
    FROM choice_group g
    JOIN five_group fg USING(origin_date, src, tgt, integration_scope)
    CROSS JOIN candidates c
    LEFT JOIN five_choice f
      USING(origin_date, src, tgt, integration_scope, candidate_address)
    LEFT JOIN pair_capital l1
      ON l1.origin_date = g.origin_date
     AND l1.token_a = least(g.src, c.candidate_address)
     AND l1.token_b = greatest(g.src, c.candidate_address)
    LEFT JOIN pair_capital l2
      ON l2.origin_date = g.origin_date
     AND l2.token_a = least(c.candidate_address, g.tgt)
     AND l2.token_b = greatest(c.candidate_address, g.tgt)
),
panel AS (
    SELECT
        *,
        sum(CASE WHEN bridge_min_capital_usd > 0 THEN 1 ELSE 0 END)
            OVER (PARTITION BY origin_date, src, tgt, integration_scope)
            AS supported_candidates
    FROM panel0
)
SELECT *
FROM panel
WHERE five_route_total > 0
  AND bridge_min_capital_usd > 0
  AND supported_candidates >= ?
"""


def load_bridge_liquidity_panel(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
    endpoint_cutoff: str = ENDPOINT_CUTOFF,
    capital_status: str = CAPITAL_STATUS,
    min_supported_candidates: int = MIN_SUPPORTED_CANDIDATES,
) -> pd.DataFrame:
    """Load the supported five-candidate bridge-liquidity risk set."""

    connection = duckdb.connect()
    try:
        frame = connection.execute(
            PANEL_QUERY,
            [
                str(choices_path),
                baseline_year,
                comparison_year,
                endpoint_cutoff,
                str(choices_path),
                baseline_year,
                comparison_year,
                endpoint_cutoff,
                str(choices_path),
                baseline_year,
                comparison_year,
                endpoint_cutoff,
                str(pool_capital_path),
                capital_status,
                min_supported_candidates,
            ],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("bridge-liquidity panel is empty")
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    for column in ("src", "tgt", "candidate_address"):
        frame[column] = frame[column].astype(str).str.lower()
    frame["choice_group_id"] = (
        frame["origin_date"].dt.strftime("%Y%m%d")
        + "|"
        + frame["src"]
        + "|"
        + frame["tgt"]
        + "|"
        + frame["integration_scope"].astype(str)
    )
    frame["ordered_pair"] = frame["src"] + "|" + frame["tgt"]
    frame["route_share_five"] = (
        frame["route_count"].astype(float) / frame["five_route_total"].astype(float)
    )
    frame["selected_five"] = frame["route_count"].gt(0).astype(float)
    frame["log_bridge_min_capital"] = np.log1p(
        frame["bridge_min_capital_usd"].astype(float)
    )
    frame["log_bridge_geom_capital"] = np.log1p(
        frame["bridge_geom_capital_usd"].astype(float)
    )
    frame["log_bridge_min_capital_x_stable"] = (
        frame["log_bridge_min_capital"] * frame["is_stable"].astype(float)
    )
    numeric = [
        "route_share_five",
        "selected_five",
        "five_route_total",
        "bridge_min_capital_usd",
        "log_bridge_min_capital",
        "log_bridge_min_capital_x_stable",
    ]
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    if frame.empty:
        raise ValueError("bridge-liquidity panel lost all rows after validation")
    return frame.reset_index(drop=True)


def bridge_liquidity_top_rank_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize route share captured by the deepest local bridge candidate."""

    ranked = panel.sort_values(
        ["choice_group_id", "bridge_min_capital_usd", "candidate_symbol"],
        ascending=[True, False, True],
    ).copy()
    ranked["bridge_liquidity_rank"] = ranked.groupby("choice_group_id").cumcount() + 1
    rows: list[dict[str, object]] = []
    for sample_label, group in [
        ("pooled", ranked),
        *[
            (str(year), ranked[ranked["year"].eq(year)])
            for year in sorted(ranked["year"].dropna().unique())
        ],
    ]:
        if group.empty:
            continue
        top = group[group["bridge_liquidity_rank"].eq(1)].copy()
        denominator = float(top["five_route_total"].sum())
        if denominator <= 0:
            continue
        other = group[group["bridge_liquidity_rank"].gt(1)]
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_top_rank_summary",
                "sample": sample_label,
                "capital_status": CAPITAL_STATUS,
                "candidate_rows": int(len(group)),
                "choice_groups": int(top["choice_group_id"].nunique()),
                "ordered_pairs": int(top["ordered_pair"].nunique()),
                "days": int(top["origin_date"].nunique()),
                "top_bridge_route_share": float(top["route_count"].sum() / denominator),
                "other_supported_route_share": float(
                    other["route_count"].sum() / denominator
                ),
                "unsupported_or_unranked_route_share": float(
                    1.0
                    - (top["route_count"].sum() + other["route_count"].sum())
                    / denominator
                ),
                "top_bridge_selected_rate": float(
                    np.average(top["selected_five"], weights=top["five_route_total"])
                ),
                "top_bridge_stable_rate": float(
                    np.average(top["is_stable"], weights=top["five_route_total"])
                ),
                "mean_supported_candidates": float(
                    top["supported_candidates"].astype(float).mean()
                ),
                "interpretation": (
                    "deepest prior-calendar two-leg deposited-capital bridge inside "
                    "the five-candidate risk set; descriptive, not causal"
                ),
            }
        )
    return pd.DataFrame(rows)


def bridge_liquidity_depth_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate within-opportunity bridge-liquidity slopes."""

    specs = (
        (
            "route_share_log_min_depth",
            "route_share_five",
            ("log_bridge_min_capital",),
        ),
        (
            "route_share_log_min_depth_stable_interaction",
            "route_share_five",
            ("log_bridge_min_capital", "log_bridge_min_capital_x_stable"),
        ),
        (
            "selection_log_min_depth",
            "selected_five",
            ("log_bridge_min_capital",),
        ),
        (
            "selection_log_min_depth_stable_interaction",
            "selected_five",
            ("log_bridge_min_capital", "log_bridge_min_capital_x_stable"),
        ),
    )
    rows: list[dict[str, object]] = []
    for model_id, outcome, regressors in specs:
        columns = [
            outcome,
            *regressors,
            "choice_group_id",
            "candidate_address",
            "origin_date",
            "ordered_pair",
            "five_route_total",
        ]
        data = (
            panel.loc[:, columns]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        residual = absorb_fixed_effects(
            data[[outcome, *regressors]],
            data["choice_group_id"],
            data["candidate_address"],
            weights=data["five_route_total"],
        )
        fit = ols_clustered(
            residual[outcome],
            residual[list(regressors)],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=(data["choice_group_id"], data["candidate_address"]),
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
                    "record_type": "bridge_liquidity_depth_regression",
                    "model_id": model_id,
                    "outcome": outcome,
                    "regressor": regressor,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(fit.t_statistics[index]),
                    "p_value": float(fit.p_values[index]),
                    "coefficient_pp_per_log_point": 100.0 * coefficient,
                    "standard_error_pp_per_log_point": 100.0 * standard_error,
                    "n_observations": int(fit.n_observations),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "ordered_ultimate_pair_date_scope+candidate",
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "five_candidate_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "interpretation": (
                        "prior two-leg deposited-capital depth association, "
                        "not direct-cost dominance or causal liquidity supply"
                    ),
                }
            )
        if len(regressors) == 2:
            stable_total = linear_contrast(fit, [1.0, 1.0])
            rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "record_type": "bridge_liquidity_depth_regression",
                    "model_id": model_id,
                    "outcome": outcome,
                    "regressor": "stable_total_log_bridge_min_capital",
                    "coefficient": stable_total.estimate,
                    "standard_error": stable_total.standard_error,
                    "t_statistic": stable_total.t_statistic,
                    "p_value": stable_total.p_value,
                    "coefficient_pp_per_log_point": 100.0 * stable_total.estimate,
                    "standard_error_pp_per_log_point": 100.0
                    * stable_total.standard_error,
                    "n_observations": int(fit.n_observations),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "ordered_ultimate_pair_date_scope+candidate",
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "five_candidate_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "interpretation": (
                        "stable-candidate total slope for prior two-leg deposited "
                        "capital inside the same opportunity"
                    ),
                }
            )
    return pd.DataFrame(rows)


def support_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the support ledger for the bridge-liquidity screen."""

    return pd.DataFrame(
        [
            {
                "claim_status": "provisional_exploratory",
                "record_type": "support",
                "choices_input": str(CHOICES_INPUT.relative_to(REPO_ROOT)),
                "pool_capital_input": str(POOL_CAPITAL_INPUT.relative_to(REPO_ROOT)),
                "capital_status": CAPITAL_STATUS,
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "endpoint_cutoff": ENDPOINT_CUTOFF,
                "candidate_rows": int(len(panel)),
                "choice_groups": int(panel["choice_group_id"].nunique()),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "days": int(panel["origin_date"].nunique()),
                "candidate_count": int(panel["candidate_address"].nunique()),
                "min_supported_candidates": MIN_SUPPORTED_CANDIDATES,
                "quantity": (
                    "prior-calendar deposited capital on both atomic legs of "
                    "source-candidate-target; not executable quote depth"
                ),
            }
        ]
    )


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
    result = pd.concat(
        [
            bridge_liquidity_top_rank_summaries(panel),
            bridge_liquidity_depth_regressions(panel),
        ],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support_rows(panel), support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(result):,} bridge-liquidity rows over "
        f"{panel['choice_group_id'].nunique():,} choice groups"
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
