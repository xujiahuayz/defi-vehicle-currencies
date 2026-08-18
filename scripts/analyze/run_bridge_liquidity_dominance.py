#!/usr/bin/env python3
"""Screen whether local bridge liquidity predicts vehicle choice.

The unit is a candidate vehicle inside an ordered ultimate pair x date x route
scope.  For each of the five headline vehicle candidates, the script measures
prior-calendar deposited capital on the two atomic legs that would make
``source -> candidate -> target`` feasible.  It then tests whether deeper local
bridge liquidity predicts the candidate's route share inside the same endpoint
opportunity.

The same panel also runs a horse race between local bridge depth, candidate
reach elsewhere in the routing network, and the stable label.  This is an
exploratory mechanism screen.  It is not a causal design and does not measure
executable route cost, active concentrated-liquidity depth, or LP returns.
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
PAIR_SUPPORT_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_pair_support.parquet"
POOL_CAPITAL_INPUT = REPO_ROOT / "data/processed/pool_capital_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_dominance.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_liquidity_dominance_support.jsonl"

BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
ENDPOINT_CUTOFF = "06-30"
CAPITAL_STATUS = "exact_state_prior_calendar"
MIN_SUPPORTED_CANDIDATES = 2
STABLE_ISSUER_CANDIDATES = ("DAI", "USDC", "USDT")
CODE_SOURCES = ["scripts/analyze/run_bridge_liquidity_dominance.py"]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/endpoint_candidate_pair_support.parquet",
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

PANEL_QUERY_WITH_ZERO_BRIDGES = PANEL_QUERY.replace(
    "  AND bridge_min_capital_usd > 0\n",
    "",
)


def _candidate_global_reach_features(
    panel: pd.DataFrame,
    *,
    choices_path: Path,
    baseline_year: int,
    comparison_year: int,
    endpoint_cutoff: str,
) -> pd.DataFrame:
    """Add candidate-level route-reach controls measured outside the local bridge.

    Same-day controls leave out the current opportunity.  Lag controls use the
    previous 30 calendar days and therefore precede the route opportunity.  All
    quantities come from the endpoint-candidate choice ledger, not from pool
    capital, so the horse-race rows separate a candidate's general network use
    from source-candidate-target bridge depth.
    """

    keys = (
        panel.loc[:, ["origin_date", "candidate_address", "integration_scope"]]
        .drop_duplicates()
        .copy()
    )
    candidates = panel.loc[:, ["candidate_address"]].drop_duplicates().copy()
    connection = duckdb.connect()
    try:
        connection.register("panel_keys", keys)
        connection.register("panel_candidates", candidates)
        reach = connection.execute(
            """
            WITH five_choice AS (
                SELECT
                    CAST(date AS DATE) AS origin_date,
                    lower(src) AS src,
                    lower(tgt) AS tgt,
                    lower(candidate_address) AS candidate_address,
                    integration_scope,
                    sum(route_count)::DOUBLE AS route_count
                FROM read_parquet(?)
                WHERE year(date) IN (?, ?)
                  AND strftime(date, '%m-%d') <= ?
                  AND lower(candidate_address) IN (
                      SELECT candidate_address FROM panel_candidates
                  )
                GROUP BY 1, 2, 3, 4, 5
            ),
            daily AS (
                SELECT
                    origin_date,
                    candidate_address,
                    integration_scope,
                    sum(route_count)::DOUBLE AS global_route_count_day,
                    count(*)::DOUBLE AS global_pair_count_day
                FROM five_choice
                GROUP BY 1, 2, 3
            ),
            lag AS (
                SELECT
                    CAST(k.origin_date AS DATE) AS origin_date,
                    k.candidate_address,
                    k.integration_scope,
                    coalesce(sum(c.route_count), 0.0)::DOUBLE
                        AS global_route_count_lag30,
                    count(c.route_count)::DOUBLE AS global_pair_day_count_lag30,
                    count(DISTINCT CASE
                        WHEN c.route_count IS NOT NULL THEN c.src || '|' || c.tgt
                        ELSE NULL
                    END)::DOUBLE AS global_pair_count_lag30
                FROM panel_keys k
                LEFT JOIN five_choice c
                  ON c.candidate_address = k.candidate_address
                 AND c.integration_scope = k.integration_scope
                 AND c.origin_date >= CAST(k.origin_date AS DATE) - INTERVAL 30 DAY
                 AND c.origin_date < CAST(k.origin_date AS DATE)
                GROUP BY 1, 2, 3
            )
            SELECT
                CAST(k.origin_date AS DATE) AS origin_date,
                k.candidate_address,
                k.integration_scope,
                coalesce(d.global_route_count_day, 0.0)::DOUBLE
                    AS global_route_count_day,
                coalesce(d.global_pair_count_day, 0.0)::DOUBLE
                    AS global_pair_count_day,
                lag.global_route_count_lag30,
                lag.global_pair_day_count_lag30,
                lag.global_pair_count_lag30
            FROM panel_keys k
            LEFT JOIN daily d
              ON d.origin_date = CAST(k.origin_date AS DATE)
             AND d.candidate_address = k.candidate_address
             AND d.integration_scope = k.integration_scope
            LEFT JOIN lag
              ON lag.origin_date = CAST(k.origin_date AS DATE)
             AND lag.candidate_address = k.candidate_address
             AND lag.integration_scope = k.integration_scope
            """,
            [str(choices_path), baseline_year, comparison_year, endpoint_cutoff],
        ).fetchdf()
    finally:
        connection.close()

    reach["origin_date"] = pd.to_datetime(reach["origin_date"]).dt.normalize()
    reach["candidate_address"] = reach["candidate_address"].astype(str).str.lower()
    augmented = panel.merge(
        reach,
        on=["origin_date", "candidate_address", "integration_scope"],
        how="left",
        validate="many_to_one",
    )
    raw_columns = [
        "global_route_count_day",
        "global_pair_count_day",
        "global_route_count_lag30",
        "global_pair_day_count_lag30",
        "global_pair_count_lag30",
    ]
    for column in raw_columns:
        augmented[column] = augmented[column].fillna(0.0).astype(float)
    augmented["global_route_count_day_leaveout"] = (
        augmented["global_route_count_day"] - augmented["route_count"].astype(float)
    ).clip(lower=0.0)
    augmented["global_pair_count_day_leaveout"] = (
        augmented["global_pair_count_day"] - augmented["selected_five"].astype(float)
    ).clip(lower=0.0)
    log_columns = [
        "global_route_count_day_leaveout",
        "global_pair_count_day_leaveout",
        "global_route_count_lag30",
        "global_pair_day_count_lag30",
        "global_pair_count_lag30",
    ]
    for column in log_columns:
        augmented[f"log_{column}"] = np.log1p(augmented[column].astype(float))
    return augmented


def load_bridge_liquidity_panel(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
    endpoint_cutoff: str = ENDPOINT_CUTOFF,
    capital_status: str = CAPITAL_STATUS,
    min_supported_candidates: int = MIN_SUPPORTED_CANDIDATES,
    include_zero_bridge_candidates: bool = False,
) -> pd.DataFrame:
    """Load the supported five-candidate bridge-liquidity risk set."""

    query = PANEL_QUERY_WITH_ZERO_BRIDGES if include_zero_bridge_candidates else PANEL_QUERY
    connection = duckdb.connect()
    try:
        frame = connection.execute(
            query,
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
    frame["log_bridge_max_capital"] = np.log1p(
        np.maximum(
            frame["leg1_capital_usd"].astype(float),
            frame["leg2_capital_usd"].astype(float),
        )
    )
    frame["log_bridge_sum_capital"] = np.log1p(
        frame["leg1_capital_usd"].astype(float)
        + frame["leg2_capital_usd"].astype(float)
    )
    frame["log_bridge_geom_capital"] = np.log1p(
        frame["bridge_geom_capital_usd"].astype(float)
    )
    frame["log_bridge_imbalance"] = (
        np.log1p(frame["leg1_capital_usd"].astype(float))
        - np.log1p(frame["leg2_capital_usd"].astype(float))
    ).abs()
    frame["log_bridge_min_capital_x_stable"] = (
        frame["log_bridge_min_capital"] * frame["is_stable"].astype(float)
    )
    frame = _candidate_global_reach_features(
        frame,
        choices_path=choices_path,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        endpoint_cutoff=endpoint_cutoff,
    )
    numeric = [
        "route_share_five",
        "selected_five",
        "five_route_total",
        "bridge_min_capital_usd",
        "log_bridge_min_capital",
        "log_bridge_max_capital",
        "log_bridge_sum_capital",
        "log_bridge_min_capital_x_stable",
        "log_bridge_geom_capital",
        "log_bridge_imbalance",
        "log_global_route_count_day_leaveout",
        "log_global_route_count_lag30",
        "log_global_pair_count_lag30",
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


def bridge_liquidity_horse_race_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate local bridge depth against candidate reach and stable identity."""

    specs = (
        (
            "route_share_depth_global_reach_candidate_fe",
            "route_share_five",
            (
                "log_bridge_min_capital",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id", "candidate_address"),
            "ordered_ultimate_pair_date_scope+candidate",
        ),
        (
            "selection_depth_global_reach_candidate_fe",
            "selected_five",
            (
                "log_bridge_min_capital",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id", "candidate_address"),
            "ordered_ultimate_pair_date_scope+candidate",
        ),
        (
            "route_share_stable_depth_reach",
            "route_share_five",
            (
                "is_stable",
                "log_bridge_min_capital",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id",),
            "ordered_ultimate_pair_date_scope",
        ),
        (
            "selection_stable_depth_reach",
            "selected_five",
            (
                "is_stable",
                "log_bridge_min_capital",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id",),
            "ordered_ultimate_pair_date_scope",
        ),
    )
    rows: list[dict[str, object]] = []
    for model_id, outcome, regressors, fixed_effects, fixed_effect_label in specs:
        columns = [
            outcome,
            *regressors,
            *fixed_effects,
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
            *(data[column] for column in fixed_effects),
            weights=data["five_route_total"],
        )
        fit = ols_clustered(
            residual[outcome],
            residual[list(regressors)],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=tuple(data[column] for column in fixed_effects),
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
                    "record_type": "bridge_liquidity_horse_race_regression",
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
                    "fixed_effects": fixed_effect_label,
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "five_candidate_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "candidate_reach_quantity": (
                        "same-day leave-one-out and prior-30-day five-candidate "
                        "route reach in endpoint_candidate_choices"
                    ),
                    "interpretation": (
                        "local prior bridge-depth association conditional on "
                        "candidate network reach; descriptive, not causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


def bridge_liquidity_entry_birth_panel(
    panel: pd.DataFrame,
    *,
    pair_support_path: Path = PAIR_SUPPORT_INPUT,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
    endpoint_cutoff: str = ENDPOINT_CUTOFF,
) -> pd.DataFrame:
    """Return bridge-choice rows for first-observed ultimate-pair dates.

    The broader panel keeps zero bridge-depth candidates because absence of a
    feasible local bridge is part of the entry choice set.  The opportunity
    still requires at least two locally supported candidates through
    ``supported_candidates`` inherited from the loader.
    """

    connection = duckdb.connect()
    try:
        entries = connection.execute(
            """
            SELECT DISTINCT
                CAST(date AS DATE) AS origin_date,
                lower(src) AS src,
                lower(tgt) AS tgt
            FROM read_parquet(?)
            WHERE pair_entry_on_day
              AND primary_choice_route_count > 0
              AND year(date) IN (?, ?)
              AND strftime(date, '%m-%d') <= ?
            """,
            [str(pair_support_path), baseline_year, comparison_year, endpoint_cutoff],
        ).fetchdf()
    finally:
        connection.close()
    if entries.empty:
        raise ValueError("bridge-liquidity entry support is empty")
    entries["origin_date"] = pd.to_datetime(entries["origin_date"]).dt.normalize()
    for column in ("src", "tgt"):
        entries[column] = entries[column].astype(str).str.lower()
    entry_panel = panel.merge(entries, on=["origin_date", "src", "tgt"], how="inner")
    if entry_panel.empty:
        raise ValueError("bridge-liquidity entry panel is empty")
    return entry_panel.reset_index(drop=True)


def bridge_liquidity_entry_birth_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 100,
    min_clusters: int = 20,
) -> pd.DataFrame:
    """Estimate local bridge depth in first-observed market choice sets."""

    specs = (
        (
            "entry_route_share_depth_reach_candidate_fe",
            "route_share_five",
            (
                "log_bridge_min_capital",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id", "candidate_address"),
            "ordered_ultimate_pair_entry_date_scope+candidate",
        ),
        (
            "entry_selection_depth_reach_candidate_fe",
            "selected_five",
            (
                "log_bridge_min_capital",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id", "candidate_address"),
            "ordered_ultimate_pair_entry_date_scope+candidate",
        ),
        (
            "entry_route_share_stable_depth_reach",
            "route_share_five",
            (
                "is_stable",
                "log_bridge_min_capital",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            ("choice_group_id",),
            "ordered_ultimate_pair_entry_date_scope",
        ),
    )
    rows: list[dict[str, object]] = []
    for model_id, outcome, regressors, fixed_effects, fixed_effect_label in specs:
        columns = [
            outcome,
            *regressors,
            *fixed_effects,
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
            *(data[column] for column in fixed_effects),
            weights=data["five_route_total"],
        )
        fit = ols_clustered(
            residual[outcome],
            residual[list(regressors)],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=tuple(data[column] for column in fixed_effects),
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
                    "record_type": "bridge_liquidity_entry_birth_regression",
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
                    "choice_groups": int(data["choice_group_id"].nunique()),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": fixed_effect_label,
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "five_candidate_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "candidate_reach_quantity": (
                        "prior-30-day five-candidate route and pair reach in "
                        "endpoint_candidate_choices"
                    ),
                    "interpretation": (
                        "market-birth local bridge-depth association conditional "
                        "on candidate network reach; descriptive, not causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


def bridge_liquidity_bottleneck_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Test whether route share follows the weak bridge leg rather than bulk depth."""

    specs = (
        (
            "route_share_min_max_depth_reach_candidate_fe",
            (
                "log_bridge_min_capital",
                "log_bridge_max_capital",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            (
                "Does the weaker local bridge leg matter after the stronger leg "
                "and candidate reach are held fixed?"
            ),
        ),
        (
            "route_share_geom_imbalance_reach_candidate_fe",
            (
                "log_bridge_geom_capital",
                "log_bridge_imbalance",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            (
                "Does unbalanced two-leg liquidity reduce route share at a given "
                "geometric bridge depth?"
            ),
        ),
    )
    rows: list[dict[str, object]] = []
    for model_id, regressors, question in specs:
        columns = [
            "route_share_five",
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
            data[["route_share_five", *regressors]],
            data["choice_group_id"],
            data["candidate_address"],
            weights=data["five_route_total"],
        )
        fit = ols_clustered(
            residual["route_share_five"],
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
                    "record_type": "bridge_liquidity_bottleneck_regression",
                    "model_id": model_id,
                    "question": question,
                    "outcome": "route_share_five",
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
                    "candidate_reach_quantity": (
                        "same-day leave-one-out and prior-30-day five-candidate "
                        "route reach in endpoint_candidate_choices"
                    ),
                    "interpretation": (
                        "local bridge-bottleneck association conditional on "
                        "candidate network reach; descriptive, not causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


def bridge_liquidity_leave_one_candidate_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
    min_supported_candidates: int = MIN_SUPPORTED_CANDIDATES,
) -> pd.DataFrame:
    """Re-run the bridge-depth horse race after dropping each headline candidate."""

    regressors = (
        "log_bridge_min_capital",
        "log_global_route_count_day_leaveout",
        "log_global_route_count_lag30",
        "log_global_pair_count_lag30",
    )
    fixed_effects = ("choice_group_id", "candidate_address")
    rows: list[dict[str, object]] = []
    for candidate_symbol in sorted(panel["candidate_symbol"].dropna().unique()):
        subset = panel[~panel["candidate_symbol"].eq(candidate_symbol)].copy()
        remaining_candidates = subset.groupby("choice_group_id")[
            "candidate_address"
        ].transform("nunique")
        subset = subset[remaining_candidates >= min_supported_candidates].copy()
        columns = [
            "route_share_five",
            *regressors,
            *fixed_effects,
            "origin_date",
            "ordered_pair",
            "five_route_total",
        ]
        data = (
            subset.loc[:, columns]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        residual = absorb_fixed_effects(
            data[["route_share_five", *regressors]],
            *(data[column] for column in fixed_effects),
            weights=data["five_route_total"],
        )
        fit = ols_clustered(
            residual["route_share_five"],
            residual[list(regressors)],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=tuple(data[column] for column in fixed_effects),
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
                    "record_type": "bridge_liquidity_leave_one_candidate_regression",
                    "model_id": "route_share_depth_global_reach_candidate_fe",
                    "dropped_candidate_symbol": str(candidate_symbol),
                    "outcome": "route_share_five",
                    "regressor": regressor,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(fit.t_statistics[index]),
                    "p_value": float(fit.p_values[index]),
                    "coefficient_pp_per_log_point": 100.0 * coefficient,
                    "standard_error_pp_per_log_point": 100.0 * standard_error,
                    "n_observations": int(fit.n_observations),
                    "choice_groups": int(data["choice_group_id"].nunique()),
                    "remaining_candidate_count": int(
                        subset["candidate_address"].nunique()
                    ),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "ordered_ultimate_pair_date_scope+candidate",
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "five_candidate_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "candidate_reach_quantity": (
                        "same-day leave-one-out and prior-30-day five-candidate "
                        "route reach in endpoint_candidate_choices"
                    ),
                    "outcome_denominator": (
                        "original five-candidate route total retained after "
                        "dropping one candidate"
                    ),
                    "interpretation": (
                        "leave-one-candidate robustness for the local prior "
                        "bridge-depth association conditional on candidate reach"
                    ),
                }
            )
    return pd.DataFrame(rows)


def bridge_liquidity_stable_issuer_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
    min_supported_stable_candidates: int = 2,
) -> pd.DataFrame:
    """Compare DAI, USDC, and USDT inside stable-only bridge risk sets."""

    stable = panel[panel["candidate_symbol"].isin(STABLE_ISSUER_CANDIDATES)].copy()
    stable["stable_supported_count"] = stable.groupby("choice_group_id")[
        "candidate_address"
    ].transform("nunique")
    stable = stable[
        stable["stable_supported_count"].ge(min_supported_stable_candidates)
    ].copy()
    stable["stable_supported_total_routes"] = stable.groupby("choice_group_id")[
        "route_count"
    ].transform("sum")
    stable = stable[stable["stable_supported_total_routes"].gt(0)].copy()
    if stable.empty:
        raise ValueError("stable-issuer bridge risk set is empty")
    stable["route_share_stable_supported"] = stable["route_count"].astype(
        float
    ) / stable["stable_supported_total_routes"].astype(float)
    stable["is_usdc"] = stable["candidate_symbol"].eq("USDC").astype(float)
    stable["is_usdt"] = stable["candidate_symbol"].eq("USDT").astype(float)
    stable["is_2026"] = stable["year"].eq(COMPARISON_YEAR).astype(float)
    stable["is_usdc_x_2026"] = stable["is_usdc"] * stable["is_2026"]
    stable["is_usdt_x_2026"] = stable["is_usdt"] * stable["is_2026"]

    rows: list[dict[str, object]] = [
        {
            "claim_status": "provisional_exploratory",
            "record_type": "bridge_liquidity_stable_issuer_support",
            "model_id": "stable_issuer_bridge_race_support",
            "candidate_rows": int(len(stable)),
            "choice_groups": int(stable["choice_group_id"].nunique()),
            "ordered_pairs": int(stable["ordered_pair"].nunique()),
            "days": int(stable["origin_date"].nunique()),
            "stable_issuer_candidates": ",".join(STABLE_ISSUER_CANDIDATES),
            "min_supported_stable_candidates": int(min_supported_stable_candidates),
            "route_count": float(
                stable.drop_duplicates("choice_group_id")[
                    "stable_supported_total_routes"
                ].sum()
            ),
            "outcome": "route_share_stable_supported",
            "outcome_denominator": "supported DAI/USDC/USDT route mass in the same opportunity",
            "interpretation": (
                "stable-issuer race inside supported stable-candidate bridge "
                "opportunities; descriptive, not causal"
            ),
        }
    ]
    specs = (
        (
            "stable_issuer_identity_fe",
            ("is_usdc", "is_usdt"),
            "issuer identity inside stable-supported opportunities",
        ),
        (
            "stable_issuer_depth_reach_fe",
            (
                "is_usdc",
                "is_usdt",
                "log_bridge_min_capital",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            "issuer identity with local depth and candidate reach controls",
        ),
        (
            "stable_issuer_2026_depth_reach_fe",
            (
                "is_usdc",
                "is_usdt",
                "is_usdc_x_2026",
                "is_usdt_x_2026",
                "log_bridge_min_capital",
                "log_global_route_count_day_leaveout",
                "log_global_route_count_lag30",
                "log_global_pair_count_lag30",
            ),
            "issuer identity, 2026 interactions, local depth, and candidate reach controls",
        ),
    )
    for model_id, regressors, question in specs:
        columns = [
            "route_share_stable_supported",
            *regressors,
            "choice_group_id",
            "origin_date",
            "ordered_pair",
            "stable_supported_total_routes",
        ]
        data = (
            stable.loc[:, columns]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .copy()
        )
        residual = absorb_fixed_effects(
            data[["route_share_stable_supported", *regressors]],
            data["choice_group_id"],
            weights=data["stable_supported_total_routes"],
        )
        fit = ols_clustered(
            residual["route_share_stable_supported"],
            residual[list(regressors)],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=(data["choice_group_id"],),
            additional_clusters=(data["origin_date"],),
            weights=data["stable_supported_total_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for index, regressor in enumerate(regressors):
            coefficient = float(fit.beta[index])
            standard_error = float(fit.standard_errors[index])
            rows.append(
                {
                    "claim_status": "provisional_exploratory",
                    "record_type": "bridge_liquidity_stable_issuer_regression",
                    "model_id": model_id,
                    "question": question,
                    "outcome": "route_share_stable_supported",
                    "regressor": regressor,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "t_statistic": float(fit.t_statistics[index]),
                    "p_value": float(fit.p_values[index]),
                    "coefficient_pp": 100.0 * coefficient,
                    "standard_error_pp": 100.0 * standard_error,
                    "n_observations": int(fit.n_observations),
                    "ordered_pair_clusters": int(fit.cluster_counts[0]),
                    "date_clusters": int(fit.cluster_counts[1]),
                    "fixed_effects": "ordered_ultimate_pair_date_scope",
                    "covariance": "two_way_ordered_pair_date_cr1",
                    "weight": "supported_stable_route_count",
                    "capital_status": CAPITAL_STATUS,
                    "omitted_candidate": "DAI",
                    "candidate_reach_quantity": (
                        "same-day leave-one-out and prior-30-day five-candidate "
                        "route reach in endpoint_candidate_choices"
                    ),
                    "outcome_denominator": (
                        "supported DAI/USDC/USDT route mass in the same opportunity"
                    ),
                    "interpretation": (
                        "stable issuer identity and local depth association inside "
                        "the supported stable-candidate risk set; descriptive, not causal"
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


def support_rows(
    panel: pd.DataFrame,
    *,
    entry_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the support ledger for the bridge-liquidity screen."""

    rows: list[dict[str, object]] = [
        {
            "claim_status": "provisional_exploratory",
            "record_type": "support",
            "choices_input": str(CHOICES_INPUT.relative_to(REPO_ROOT)),
            "pair_support_input": str(PAIR_SUPPORT_INPUT.relative_to(REPO_ROOT)),
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
            "include_zero_bridge_candidates": False,
            "quantity": (
                "prior-calendar deposited capital on both atomic legs of "
                "source-candidate-target; not executable quote depth"
            ),
        }
    ]
    if entry_panel is not None:
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "entry_birth_support",
                "choices_input": str(CHOICES_INPUT.relative_to(REPO_ROOT)),
                "pair_support_input": str(PAIR_SUPPORT_INPUT.relative_to(REPO_ROOT)),
                "pool_capital_input": str(POOL_CAPITAL_INPUT.relative_to(REPO_ROOT)),
                "capital_status": CAPITAL_STATUS,
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "endpoint_cutoff": ENDPOINT_CUTOFF,
                "candidate_rows": int(len(entry_panel)),
                "choice_groups": int(entry_panel["choice_group_id"].nunique()),
                "ordered_pairs": int(entry_panel["ordered_pair"].nunique()),
                "days": int(entry_panel["origin_date"].nunique()),
                "candidate_count": int(entry_panel["candidate_address"].nunique()),
                "min_supported_candidates": MIN_SUPPORTED_CANDIDATES,
                "include_zero_bridge_candidates": True,
                "quantity": (
                    "entry-date five-candidate risk set; zero local two-leg "
                    "bridge capital is retained as a candidate attribute"
                ),
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    choices_path: Path = CHOICES_INPUT,
    pair_support_path: Path = PAIR_SUPPORT_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    panel = load_bridge_liquidity_panel(
        choices_path=choices_path,
        pool_capital_path=pool_capital_path,
    )
    entry_panel = bridge_liquidity_entry_birth_panel(
        load_bridge_liquidity_panel(
            choices_path=choices_path,
            pool_capital_path=pool_capital_path,
            include_zero_bridge_candidates=True,
        ),
        pair_support_path=pair_support_path,
    )
    result = pd.concat(
        [
            bridge_liquidity_top_rank_summaries(panel),
            bridge_liquidity_depth_regressions(panel),
            bridge_liquidity_horse_race_regressions(panel),
            bridge_liquidity_entry_birth_regressions(entry_panel),
            bridge_liquidity_bottleneck_regressions(panel),
            bridge_liquidity_leave_one_candidate_regressions(panel),
            bridge_liquidity_stable_issuer_regressions(panel),
        ],
        ignore_index=True,
    )
    write_exhibit(result, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(
        support_rows(panel, entry_panel=entry_panel),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(result):,} bridge-liquidity rows over "
        f"{panel['choice_group_id'].nunique():,} choice groups"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT_INPUT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pair_support_path=args.pair_support,
        pool_capital_path=args.pool_capital,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
