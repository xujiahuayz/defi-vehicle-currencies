#!/usr/bin/env python3
"""Relate contestable vehicle choice to exact prices, depth, and incumbency.

The exact-price panel holds the ordered endpoint pair, observed input amount,
and pre-transaction state fixed while quoting the best public WETH route and
the best public DAI, USDC, or USDT route.  This runner keeps observations for
which both vehicle families are executable and asks two related questions:

1. Does the family with the larger exact pretrade output carry the route?
2. Once one vehicle family appears before the other for a pair, does its
   retention reflect the current output comparison and prior-calendar V2
   bridge capital?

The capital comparison does not condition on V2 winning the exact-price
contest.  It measures aggregate deposited capital across Uniswap V2 and
SushiSwap V2 pools on both required legs, lagged to the prior calendar day.
The estimates use ordered-pair and date fixed effects with two-way clustered
standard errors.  They describe route choice inside observed public
opportunity sets; they do not identify an exogenous liquidity-supply effect.

Exact prices are computed on the fifteenth day of each month for observed
two-leg routes on Uniswap V2, SushiSwap V2, and Uniswap V3.  The quoted family
universe is WETH versus DAI, USDC, or USDT.  The pair-support aggregate used to
date family entry covers every token classified as native or stable and cannot
be token-filtered; exclusive first-family entry is therefore the primary
incumbency definition and mixed first-day majorities are reported separately.

Reads
    data/processed/exact_vehicle_frontier_monthly.parquet
    data/processed/endpoint_candidate_pair_support.parquet
    data/processed/pool_capital_daily.parquet
Writes
    output/exhibits/contestable_vehicle_choice.jsonl
    output/exhibits/contestable_vehicle_choice_support.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit


FRONTIER = DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
PAIR_SUPPORT = DATA_DIR / "processed/endpoint_candidate_pair_support.parquet"
POOL_CAPITAL = DATA_DIR / "processed/pool_capital_daily.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/contestable_vehicle_choice.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/contestable_vehicle_choice_support.jsonl"
LOCK = SHARED_RUNTIME_DIR / "contestable-vehicle-choice.lock"

MIN_INPUT_USD = 100.0
QUOTED_LEG_MAX_PRICE_IMPACT = 0.05
MIN_PRICE_LEAD_BPS = 1.0
MIN_INCUMBENT_AGE_DAYS = 30
MAX_LINEAR_ADVANTAGE_BPS = 1_000.0
MIN_CONSEQUENCE_CELL_ROUTES = 100
MIN_CONSEQUENCE_CELL_PAIRS = 20
MIN_CONSEQUENCE_LOSS_ROUTES = 20
V2_VENUES = frozenset(("uniswap_v2", "sushiswap_v2"))
CAPITAL_STATUS = "exact_state_prior_calendar"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
QUOTED_VEHICLES = frozenset((WETH, DAI, USDC, USDT))
QUOTED_STABLES = frozenset((DAI, USDC, USDT))
EXACT_VENUE_SCOPE = "uniswap_v2+sushiswap_v2+uniswap_v3"
SAMPLING_CALENDAR = "monthly_fifteenth"
CODE_SOURCES = ["scripts/analyze/run_contestable_vehicle_choice.py"]
INPUTS = [
    "data/processed/exact_vehicle_frontier_monthly.parquet",
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/pool_capital_daily.parquet",
]

FRONTIER_COLUMNS = (
    "day",
    "route_id",
    "token_in",
    "token_out",
    "chosen_vehicle",
    "chosen_vehicle_type",
    "input_usd",
    "output_usd",
    "within_20pct",
    "chosen_max_price_impact",
    "vehicle_families_contestable",
    "stable_minus_native_bps",
    "native_public_out",
    "stable_public_out",
    "native_public_vehicle",
    "stable_public_vehicle",
)


def _path(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


def prepare_frontier(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Validate the exact panel and retain the common-support contest."""

    missing = sorted(set(FRONTIER_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"exact-price panel lacks contest columns: {missing}")
    data = frame.loc[:, list(FRONTIER_COLUMNS)].copy()
    day_text = data["day"].astype(str).str.replace(r"\.0$", "", regex=True)
    data["date"] = pd.to_datetime(day_text, format="%Y%m%d", errors="raise")
    data["day"] = data["date"].dt.strftime("%Y%m%d")
    for column in (
        "input_usd",
        "output_usd",
        "chosen_max_price_impact",
        "stable_minus_native_bps",
        "native_public_out",
        "stable_public_out",
    ):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    for column in (
        "token_in",
        "token_out",
        "chosen_vehicle",
        "native_public_vehicle",
        "stable_public_vehicle",
    ):
        data[column] = data[column].astype("string").str.lower()
    classified = data[
        data["within_20pct"].astype(bool)
        & data["input_usd"].ge(MIN_INPUT_USD)
        & data["output_usd"].gt(0)
        & data["chosen_vehicle_type"].isin(("native", "stable"))
    ].copy()
    base = classified[classified["chosen_vehicle"].isin(QUOTED_VEHICLES)].copy()
    contestable = base[
        base["vehicle_families_contestable"].astype(bool)
        & base["native_public_out"].gt(0)
        & base["stable_public_out"].gt(0)
        & base["native_public_vehicle"].eq(WETH)
        & base["stable_public_vehicle"].isin(QUOTED_STABLES)
    ].copy()
    contestable = contestable.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "stable_minus_native_bps",
            "input_usd",
            "output_usd",
            "chosen_max_price_impact",
        ]
    )
    if contestable.empty:
        raise ValueError("exact-price contestable sample is empty")
    if contestable["route_id"].duplicated().any():
        raise ValueError("exact-price contest contains duplicated route ids")
    contestable["chosen_stable"] = contestable["chosen_vehicle_type"].eq(
        "stable"
    )
    gap = contestable["stable_minus_native_bps"].astype(float)
    contestable["symmetric_common_support"] = contestable[
        "chosen_max_price_impact"
    ].le(QUOTED_LEG_MAX_PRICE_IMPACT)
    contestable["stable_price_leader"] = gap.gt(MIN_PRICE_LEAD_BPS)
    contestable["native_price_leader"] = gap.lt(-MIN_PRICE_LEAD_BPS)
    contestable["price_tie"] = ~(contestable["stable_price_leader"] | contestable["native_price_leader"])
    contestable["chosen_matches_price_leader"] = np.select(
        [contestable["stable_price_leader"], contestable["native_price_leader"]],
        [contestable["chosen_stable"], ~contestable["chosen_stable"]],
        default=False,
    ).astype(bool)
    contestable["stable_output_advantage_100bp"] = gap.clip(
        -MAX_LINEAR_ADVANTAGE_BPS, MAX_LINEAR_ADVANTAGE_BPS
    ) / 100.0
    contestable["stable_output_advantage_capped"] = gap.abs().gt(
        MAX_LINEAR_ADVANTAGE_BPS
    )
    contestable["log_input_usd"] = np.log(contestable["input_usd"])
    chosen_family_out = np.where(
        contestable["chosen_stable"],
        contestable["stable_public_out"],
        contestable["native_public_out"],
    )
    alternative_family_out = np.where(
        contestable["chosen_stable"],
        contestable["native_public_out"],
        contestable["stable_public_out"],
    )
    contestable["foregone_family_output_bps"] = np.maximum(
        10_000.0
        * np.divide(
            alternative_family_out - chosen_family_out,
            chosen_family_out,
            out=np.zeros(len(contestable), dtype=float),
            where=chosen_family_out > 0,
        ),
        0.0,
    )
    contestable["ordered_pair"] = (
        contestable["token_in"].astype(str)
        + ">"
        + contestable["token_out"].astype(str)
    )
    support = {
        "frontier_rows": int(len(data)),
        "eligible_classified_vehicle_rows": int(len(classified)),
        "eligible_observed_vehicle_rows": int(len(base)),
        "contestable_rows": int(len(contestable)),
        "contestable_symmetric_common_support_rows": int(
            contestable["symmetric_common_support"].sum()
        ),
    }
    return contestable.reset_index(drop=True), support


def load_first_vehicle_roles(path: Path) -> pd.DataFrame:
    """Return first observed family use and separate exclusive from mixed entry."""

    connection = duckdb.connect()
    try:
        frame = connection.execute(
            """
            WITH vehicle_days AS (
                SELECT
                    CAST(date AS DATE) AS first_vehicle_date,
                    lower(src) AS token_in,
                    lower(tgt) AS token_out,
                    stable_choice_route_count::DOUBLE AS entry_stable_routes,
                    native_choice_route_count::DOUBLE AS entry_native_routes,
                    primary_choice_route_count::DOUBLE AS entry_primary_routes,
                    pair_first_supported_date,
                    row_number() OVER (
                        PARTITION BY lower(src), lower(tgt)
                        ORDER BY date
                    ) AS sequence
                FROM read_parquet(?)
                WHERE primary_choice_route_count > 0
            )
            SELECT
                first_vehicle_date,
                token_in,
                token_out,
                entry_stable_routes,
                entry_native_routes,
                entry_primary_routes,
                CAST(pair_first_supported_date AS DATE) AS first_market_date,
                CASE
                    WHEN entry_stable_routes > entry_native_routes THEN 1.0
                    WHEN entry_native_routes > entry_stable_routes THEN 0.0
                    ELSE NULL
                END AS entry_stable,
                entry_stable_routes = entry_native_routes AS entry_tie,
                (
                    (entry_stable_routes > 0 AND entry_native_routes = 0)
                    OR (entry_native_routes > 0 AND entry_stable_routes = 0)
                ) AS entry_exclusive,
                (
                    entry_stable_routes > 0 AND entry_native_routes > 0
                ) AS entry_mixed
            FROM vehicle_days
            WHERE sequence = 1
            ORDER BY token_in, token_out
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()
    if frame.duplicated(["token_in", "token_out"]).any():
        raise ValueError("first-vehicle ledger contains duplicated ordered pairs")
    return frame


def attach_incumbency(frontier: pd.DataFrame, roles: pd.DataFrame) -> pd.DataFrame:
    """Attach historical vehicle roles without dropping current observations."""

    required = {
        "first_vehicle_date",
        "token_in",
        "token_out",
        "entry_stable",
        "entry_exclusive",
        "entry_mixed",
    }
    missing = sorted(required - set(roles.columns))
    if missing:
        raise ValueError(f"first-vehicle ledger lacks columns: {missing}")
    data = frontier.merge(
        roles,
        on=["token_in", "token_out"],
        how="left",
        validate="many_to_one",
    )
    data["first_vehicle_date"] = pd.to_datetime(
        data["first_vehicle_date"], errors="raise"
    ).dt.normalize()
    data["vehicle_age_days"] = (
        data["date"] - data["first_vehicle_date"]
    ).dt.days
    if "first_market_date" in data:
        data["first_market_date"] = pd.to_datetime(
            data["first_market_date"], errors="raise"
        ).dt.normalize()
    else:
        data["first_market_date"] = pd.NaT
    data["pair_age_days"] = (data["date"] - data["first_market_date"]).dt.days
    data["entry_day_observation"] = data["vehicle_age_days"].eq(0)
    data["pre_entry_observation"] = data["vehicle_age_days"].lt(0)
    data["incumbent_known_prior"] = (
        data["entry_stable"].notna() & data["vehicle_age_days"].gt(0)
    )
    data["exclusive_incumbent_known_prior"] = (
        data["incumbent_known_prior"] & data["entry_exclusive"].fillna(False)
    )
    data["mixed_majority_incumbent_known_prior"] = (
        data["incumbent_known_prior"] & data["entry_mixed"].fillna(False)
    )
    data["mature_incumbent"] = (
        data["entry_stable"].notna()
        & data["vehicle_age_days"].ge(MIN_INCUMBENT_AGE_DAYS)
    )
    data["mature_exclusive_incumbent"] = (
        data["mature_incumbent"] & data["entry_exclusive"].fillna(False)
    )
    data["mature_mixed_entry_majority"] = (
        data["mature_incumbent"] & data["entry_mixed"].fillna(False)
    )
    entry_is_stable = data["entry_stable"].eq(1.0)
    data["incumbent_retained"] = np.where(
        data["incumbent_known_prior"],
        data["chosen_stable"].eq(entry_is_stable).astype(float),
        np.nan,
    )
    data["challenger_price_leader"] = np.where(
        data["incumbent_known_prior"],
        np.where(
            entry_is_stable,
            data["native_price_leader"],
            data["stable_price_leader"],
        ).astype(float),
        np.nan,
    )
    data["incumbent_price_leader"] = np.where(
        data["incumbent_known_prior"],
        np.where(
            entry_is_stable,
            data["stable_price_leader"],
            data["native_price_leader"],
        ).astype(float),
        np.nan,
    )
    gap = data["stable_minus_native_bps"].astype(float)
    native_relative_to_stable = np.divide(
        -10_000.0 * gap,
        10_000.0 + gap,
        out=np.full(len(data), np.nan),
        where=(10_000.0 + gap).abs().gt(1e-12),
    )
    incumbent_advantage = np.where(
        entry_is_stable, gap, native_relative_to_stable
    )
    incumbent_advantage = np.where(
        data["incumbent_known_prior"], incumbent_advantage, np.nan
    )
    data["incumbent_output_advantage_bps"] = incumbent_advantage
    data["incumbent_output_advantage_capped"] = np.where(
        data["incumbent_known_prior"],
        np.abs(incumbent_advantage) > MAX_LINEAR_ADVANTAGE_BPS,
        False,
    )
    data["incumbent_output_advantage_100bp"] = np.clip(
        incumbent_advantage,
        -MAX_LINEAR_ADVANTAGE_BPS,
        MAX_LINEAR_ADVANTAGE_BPS,
    ) / 100.0
    data["challenger_price_leader_x_entry_stable"] = (
        data["challenger_price_leader"]
        * data["entry_stable"].astype(float)
    )
    return data.reset_index(drop=True)


def load_lagged_v2_bridge_capital(
    frontier: pd.DataFrame,
    pool_capital_path: Path,
) -> pd.DataFrame:
    """Measure prior-calendar aggregate V2 bridge capital for both families."""

    required = {
        "day",
        "token_in",
        "token_out",
        "stable_public_vehicle",
        "native_public_vehicle",
    }
    missing = sorted(required - set(frontier.columns))
    if missing:
        raise ValueError(f"contestable frontier lacks depth keys: {missing}")
    requests = (
        frontier.loc[
            :,
            [
                "day",
                "token_in",
                "token_out",
                "stable_public_vehicle",
                "native_public_vehicle",
            ],
        ]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    if requests.empty:
        return requests.assign(
            stable_v2_bridge_capital_usd=pd.Series(dtype=float),
            native_v2_bridge_capital_usd=pd.Series(dtype=float),
        )
    requests.insert(0, "depth_request_id", np.arange(len(requests), dtype=np.int64))
    connection = duckdb.connect()
    try:
        connection.register("depth_requests", requests)
        depth = connection.execute(
            """
            WITH requested_legs AS (
                SELECT DISTINCT
                    day,
                    least(token_in, stable_public_vehicle) AS token_a,
                    greatest(token_in, stable_public_vehicle) AS token_b
                FROM depth_requests
                UNION
                SELECT DISTINCT
                    day,
                    least(stable_public_vehicle, token_out) AS token_a,
                    greatest(stable_public_vehicle, token_out) AS token_b
                FROM depth_requests
                UNION
                SELECT DISTINCT
                    day,
                    least(token_in, native_public_vehicle) AS token_a,
                    greatest(token_in, native_public_vehicle) AS token_b
                FROM depth_requests
                UNION
                SELECT DISTINCT
                    day,
                    least(native_public_vehicle, token_out) AS token_a,
                    greatest(native_public_vehicle, token_out) AS token_b
                FROM depth_requests
            ),
            pair_capital AS (
                SELECT
                    p.day,
                    least(lower(p.token0_address), lower(p.token1_address)) AS token_a,
                    greatest(lower(p.token0_address), lower(p.token1_address)) AS token_b,
                    sum(p.capital_usd_lagged)::DOUBLE AS capital_usd
                FROM read_parquet(?) p
                JOIN requested_legs r
                  ON p.day = r.day
                 AND least(lower(p.token0_address), lower(p.token1_address)) = r.token_a
                 AND greatest(lower(p.token0_address), lower(p.token1_address)) = r.token_b
                WHERE p.quantity_kind = 'deposited_capital'
                  AND lower(p.venue) IN ('uniswap_v2', 'sushiswap_v2')
                  AND p.capital_validation_status = ?
                  AND p.capital_usd_lagged > 0
                GROUP BY 1, 2, 3
            )
            SELECT
                r.depth_request_id,
                least(coalesce(s1.capital_usd, 0), coalesce(s2.capital_usd, 0))::DOUBLE
                    AS stable_v2_bridge_capital_usd,
                least(coalesce(n1.capital_usd, 0), coalesce(n2.capital_usd, 0))::DOUBLE
                    AS native_v2_bridge_capital_usd
            FROM depth_requests r
            LEFT JOIN pair_capital s1
              ON s1.day = r.day
             AND s1.token_a = least(r.token_in, r.stable_public_vehicle)
             AND s1.token_b = greatest(r.token_in, r.stable_public_vehicle)
            LEFT JOIN pair_capital s2
              ON s2.day = r.day
             AND s2.token_a = least(r.stable_public_vehicle, r.token_out)
             AND s2.token_b = greatest(r.stable_public_vehicle, r.token_out)
            LEFT JOIN pair_capital n1
              ON n1.day = r.day
             AND n1.token_a = least(r.token_in, r.native_public_vehicle)
             AND n1.token_b = greatest(r.token_in, r.native_public_vehicle)
            LEFT JOIN pair_capital n2
              ON n2.day = r.day
             AND n2.token_a = least(r.native_public_vehicle, r.token_out)
             AND n2.token_b = greatest(r.native_public_vehicle, r.token_out)
            ORDER BY r.depth_request_id
            """,
            [str(pool_capital_path), CAPITAL_STATUS],
        ).fetchdf()
    finally:
        connection.close()
    if len(depth) != len(requests) or depth["depth_request_id"].nunique() != len(
        requests
    ):
        raise ValueError("V2 bridge-capital join did not preserve request identity")
    return requests.merge(
        depth,
        on="depth_request_id",
        how="inner",
        validate="one_to_one",
    ).drop(columns="depth_request_id")


def attach_v2_bridge_capital(
    frontier: pd.DataFrame, capital: pd.DataFrame
) -> pd.DataFrame:
    """Join lagged V2 bridge capital and express it relative to the incumbent."""

    keys = [
        "day",
        "token_in",
        "token_out",
        "stable_public_vehicle",
        "native_public_vehicle",
    ]
    data = frontier.merge(capital, on=keys, how="left", validate="many_to_one")
    data["v2_capital_request_matched"] = data[
        "stable_v2_bridge_capital_usd"
    ].notna()
    for column in (
        "stable_v2_bridge_capital_usd",
        "native_v2_bridge_capital_usd",
    ):
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    total = (
        data["stable_v2_bridge_capital_usd"]
        + data["native_v2_bridge_capital_usd"]
    )
    data["both_v2_bridge_capitals_positive"] = (
        data["stable_v2_bridge_capital_usd"].gt(0)
        & data["native_v2_bridge_capital_usd"].gt(0)
    )
    data["stable_v2_capital_share"] = np.divide(
        data["stable_v2_bridge_capital_usd"],
        total,
        out=np.full(len(data), np.nan),
        where=total.gt(0),
    )
    data["stable_v2_capital_advantage_10pp"] = (
        data["stable_v2_capital_share"] - 0.5
    ) / 0.10
    if "entry_stable" in data:
        data["incumbent_v2_capital_share"] = np.where(
            data["entry_stable"].eq(1.0),
            data["stable_v2_capital_share"],
            1.0 - data["stable_v2_capital_share"],
        )
        data.loc[
            ~data["incumbent_known_prior"], "incumbent_v2_capital_share"
        ] = np.nan
        data["incumbent_v2_capital_advantage_10pp"] = (
            data["incumbent_v2_capital_share"] - 0.5
        ) / 0.10
        data["price_x_incumbent_v2_capital"] = (
            data["incumbent_output_advantage_100bp"]
            * data["incumbent_v2_capital_advantage_10pp"]
        )
        data["challenger_leader_x_incumbent_v2_capital"] = (
            data["challenger_price_leader"]
            * data["incumbent_v2_capital_advantage_10pp"]
        )
    return data


def _fit_model(
    frame: pd.DataFrame,
    *,
    model_id: str,
    outcome: str,
    predictors: tuple[str, ...],
    sample: str,
) -> pd.DataFrame:
    columns = [
        outcome,
        *predictors,
        "ordered_pair",
        "day",
    ]
    data = frame.loc[:, columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    complete_case_observations = len(data)
    pair_size = data.groupby("ordered_pair")["ordered_pair"].transform("size")
    data = data[pair_size.gt(1)].copy()
    singleton_pair_rows_dropped = complete_case_observations - len(data)
    if len(data) < 500 or data["ordered_pair"].nunique() < 20 or data["day"].nunique() < 20:
        raise ValueError(f"contestable choice model {model_id} has insufficient support")
    transformed = absorb_fixed_effects(
        data[[outcome, *predictors]],
        data["ordered_pair"],
        data["day"],
    )
    fit = ols_clustered(
        transformed[outcome],
        transformed[list(predictors)],
        data["ordered_pair"],
        add_constant=False,
        absorbed_groups=(data["ordered_pair"], data["day"]),
        additional_clusters=(data["day"],),
        min_observations=500,
        min_clusters=20,
    )
    if not np.isfinite(fit.beta).all() or not np.isfinite(fit.standard_errors).all():
        raise ValueError(f"contestable choice model {model_id} is not estimable")
    cluster_counts = fit.cluster_counts or (
        data["ordered_pair"].nunique(),
        data["day"].nunique(),
    )
    rows = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "contestable_vehicle_choice_regression",
                "model_id": model_id,
                "sample": sample,
                "outcome": outcome,
                "regressor": predictor,
                "coefficient": float(coefficient),
                "coefficient_pp": 100.0 * float(coefficient),
                "standard_error": float(standard_error),
                "standard_error_pp": 100.0 * float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "complete_case_observations": int(complete_case_observations),
                "singleton_pair_rows_dropped": int(
                    singleton_pair_rows_dropped
                ),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "dates": int(data["day"].nunique()),
                "ordered_pair_clusters": int(cluster_counts[0]),
                "date_clusters": int(cluster_counts[1]),
                "fixed_effects": "ordered_endpoint_pair+calendar_date",
                "covariance": "two_way_ordered_pair_calendar_date_cr1",
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data[outcome].mean()),
                "price_lead_threshold_bps": MIN_PRICE_LEAD_BPS,
                "linear_price_advantage_cap_bps": MAX_LINEAR_ADVANTAGE_BPS,
                "interpretation": (
                    "descriptive exact pretrade association within observed "
                    "public opportunity sets"
                ),
            }
        )
    return pd.DataFrame(rows)


def regression_results(panel: pd.DataFrame) -> pd.DataFrame:
    """Estimate price, exclusive-entry retention, and V2-capital columns."""

    non_ties = panel[~panel["price_tie"]].copy()
    common = non_ties[non_ties["symmetric_common_support"]].copy()
    exclusive = common[common["mature_exclusive_incumbent"]].copy()
    exclusive_unrestricted = non_ties[
        non_ties["mature_exclusive_incumbent"]
    ].copy()
    mixed = common[common["mature_mixed_entry_majority"]].copy()
    v2_capital = exclusive[
        exclusive["both_v2_bridge_capitals_positive"]
    ].copy()
    rows = [
        _fit_model(
            common,
            model_id="stable_choice_price_leader",
            outcome="chosen_stable",
            predictors=("stable_price_leader", "log_input_usd"),
            sample="contestable_symmetric_common_support",
        ),
        _fit_model(
            non_ties,
            model_id="stable_choice_price_leader_unrestricted_impact",
            outcome="chosen_stable",
            predictors=("stable_price_leader", "log_input_usd"),
            sample="contestable_unrestricted_chosen_impact",
        ),
        _fit_model(
            exclusive,
            model_id="exclusive_incumbent_retention_price_leader",
            outcome="incumbent_retained",
            predictors=(
                "challenger_price_leader",
                "challenger_price_leader_x_entry_stable",
                "log_input_usd",
            ),
            sample="mature_exclusive_entry_symmetric_common_support",
        ),
        _fit_model(
            exclusive_unrestricted,
            model_id=(
                "exclusive_incumbent_retention_price_leader_"
                "unrestricted_impact"
            ),
            outcome="incumbent_retained",
            predictors=(
                "challenger_price_leader",
                "challenger_price_leader_x_entry_stable",
                "log_input_usd",
            ),
            sample="mature_exclusive_entry_unrestricted_chosen_impact",
        ),
        _fit_model(
            mixed,
            model_id="mixed_entry_majority_retention_price_leader",
            outcome="incumbent_retained",
            predictors=(
                "challenger_price_leader",
                "challenger_price_leader_x_entry_stable",
                "log_input_usd",
            ),
            sample="mature_mixed_entry_majority_symmetric_common_support",
        ),
        _fit_model(
            v2_capital,
            model_id="exclusive_retention_price_v2_capital",
            outcome="incumbent_retained",
            predictors=(
                "incumbent_output_advantage_100bp",
                "incumbent_v2_capital_advantage_10pp",
                "log_input_usd",
            ),
            sample="mature_exclusive_entry_positive_v2_bridge_capital",
        ),
        _fit_model(
            v2_capital,
            model_id="exclusive_retention_price_v2_capital_interaction",
            outcome="incumbent_retained",
            predictors=(
                "incumbent_output_advantage_100bp",
                "incumbent_v2_capital_advantage_10pp",
                "price_x_incumbent_v2_capital",
                "log_input_usd",
            ),
            sample="mature_exclusive_entry_positive_v2_bridge_capital",
        ),
        _fit_model(
            v2_capital,
            model_id=(
                "exclusive_retention_challenger_leader_"
                "v2_capital_interaction"
            ),
            outcome="incumbent_retained",
            predictors=(
                "challenger_price_leader",
                "challenger_price_leader_x_entry_stable",
                "incumbent_v2_capital_advantage_10pp",
                "challenger_leader_x_incumbent_v2_capital",
                "log_input_usd",
            ),
            sample="mature_exclusive_entry_positive_v2_bridge_capital",
        ),
    ]
    return pd.concat(rows, ignore_index=True, sort=False)


def _output_consequence_summary(
    frame: pd.DataFrame,
    *,
    sample: str,
    split_dimension: str,
    split_category: str,
    split_definition: str,
    parent_sample: str,
    parent_routes: int,
) -> dict[str, object]:
    """Summarize exact output left on the table, subject to support guards."""

    loss_bps = pd.to_numeric(
        frame["foregone_family_output_bps"], errors="coerce"
    )
    input_value = pd.to_numeric(frame["input_usd"], errors="coerce")
    valid = (
        loss_bps.notna()
        & input_value.notna()
        & pd.Series(np.isfinite(loss_bps), index=frame.index)
        & pd.Series(np.isfinite(input_value), index=frame.index)
        & loss_bps.ge(0)
        & input_value.gt(0)
    )
    if not bool(valid.all()):
        raise ValueError("output-consequence rows require positive input values")
    lower_output = loss_bps.gt(MIN_PRICE_LEAD_BPS)
    routes = int(len(frame))
    ordered_pairs = int(frame["ordered_pair"].nunique())
    dates = int(frame["day"].nunique())
    lower_output_routes = int(lower_output.sum())
    cell_supported = (
        routes >= MIN_CONSEQUENCE_CELL_ROUTES
        and ordered_pairs >= MIN_CONSEQUENCE_CELL_PAIRS
    )
    conditional_supported = (
        cell_supported
        and lower_output_routes >= MIN_CONSEQUENCE_LOSS_ROUTES
    )
    thresholded_loss_bps = loss_bps.where(lower_output, 0.0)
    weighted_loss_bps = (
        float(np.average(thresholded_loss_bps, weights=input_value))
        if cell_supported and input_value.sum() > 0
        else np.nan
    )
    conditional_loss = loss_bps[lower_output]
    return {
        "record_type": (
            "family_output_consequence"
            if split_dimension == "all"
            else "family_output_consequence_split"
        ),
        "sample": sample,
        "split_dimension": split_dimension,
        "split_category": split_category,
        "split_definition": split_definition,
        "parent_sample": parent_sample,
        "routes": routes,
        "ordered_pairs": ordered_pairs,
        "dates": dates,
        "parent_routes": int(parent_routes),
        "cell_route_share": (
            float(routes / parent_routes) if parent_routes else np.nan
        ),
        "lower_output_family_routes": lower_output_routes,
        "lower_output_family_share": (
            float(lower_output_routes / routes)
            if cell_supported and routes
            else np.nan
        ),
        "lower_output_route_share_of_parent": (
            float(lower_output_routes / parent_routes)
            if parent_routes
            else np.nan
        ),
        "input_value_weighted_foregone_bps": weighted_loss_bps,
        "median_foregone_output_bps_if_over_1bp": (
            float(conditional_loss.median())
            if conditional_supported
            else np.nan
        ),
        "p90_foregone_output_bps_if_over_1bp": (
            float(conditional_loss.quantile(0.9))
            if conditional_supported
            else np.nan
        ),
        "minimum_cell_routes": MIN_CONSEQUENCE_CELL_ROUTES,
        "minimum_cell_ordered_pairs": MIN_CONSEQUENCE_CELL_PAIRS,
        "minimum_conditional_loss_routes": MIN_CONSEQUENCE_LOSS_ROUTES,
        "cell_meets_minimum_support": bool(cell_supported),
        "conditional_loss_meets_minimum_support": bool(
            conditional_supported
        ),
        "split_categories_mutually_exclusive": True,
        "split_categories_exhaustive_within_parent_sample": True,
        "minimum_output_difference_bps": MIN_PRICE_LEAD_BPS,
        "output_difference_rule": "strictly_greater_than_threshold",
        "weighted_loss_below_threshold_bps": 0.0,
        "comparison": (
            "best exact public route in the observed vehicle family versus "
            "the best exact public route in the rival vehicle family"
        ),
        "loss_bps_denominator": "exact output from observed vehicle family",
        "weighting": "observed_route_input_value_usd",
        "dollar_consequence_reported": False,
        "gas_consequence_reported": False,
        "causal_interpretation": False,
    }


def output_consequence_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the overall output comparison and prespecified economic splits."""

    consequence = panel[panel["symmetric_common_support"]].copy()
    parent_sample = "contestable_symmetric_common_support"
    rows: list[dict[str, object]] = [
        _output_consequence_summary(
            consequence,
            sample=parent_sample,
            split_dimension="all",
            split_category="all",
            split_definition="full common-support sample",
            parent_sample=parent_sample,
            parent_routes=len(consequence),
        )
    ]

    def add_split(
        frame: pd.DataFrame,
        *,
        dimension: str,
        categories: pd.Series,
        ordered_categories: tuple[str, ...],
        split_parent_sample: str,
        split_definition: str,
    ) -> None:
        if len(categories) != len(frame) or not categories.index.equals(frame.index):
            raise ValueError(f"{dimension} categories do not align with split rows")
        if categories.isna().any():
            raise ValueError(f"{dimension} leaves routes without a category")
        unknown = sorted(set(categories.astype(str)) - set(ordered_categories))
        if unknown:
            raise ValueError(f"{dimension} has undeclared categories: {unknown}")
        for category in ordered_categories:
            cell = frame[categories.eq(category)]
            rows.append(
                _output_consequence_summary(
                    cell,
                    sample=f"{split_parent_sample}:{category}",
                    split_dimension=dimension,
                    split_category=category,
                    split_definition=split_definition,
                    parent_sample=split_parent_sample,
                    parent_routes=len(frame),
                )
            )

    incumbency_status = pd.Series(
        np.select(
            [
                consequence["mature_exclusive_incumbent"],
                ~consequence["incumbent_known_prior"],
            ],
            ["mature_exclusive_incumbent", "no_known_incumbent"],
            default="known_prior_other_entry_or_age",
        ),
        index=consequence.index,
        dtype="string",
    )
    add_split(
        consequence,
        dimension="incumbency_status",
        categories=incumbency_status,
        ordered_categories=(
            "mature_exclusive_incumbent",
            "no_known_incumbent",
            "known_prior_other_entry_or_age",
        ),
        split_parent_sample=parent_sample,
        split_definition=(
            "strictly prior vehicle-family entry; mature exclusive entry is "
            "at least 30 days old"
        ),
    )

    mature_exclusive = consequence[
        consequence["mature_exclusive_incumbent"]
    ].copy()
    if mature_exclusive["incumbent_retained"].isna().any():
        raise ValueError("mature exclusive incumbency leaves route choice undefined")
    incumbent_choice = pd.Series(
        np.where(
            mature_exclusive["incumbent_retained"].eq(1.0),
            "incumbent_retained",
            "challenger_used",
        ),
        index=mature_exclusive.index,
        dtype="string",
    )
    add_split(
        mature_exclusive,
        dimension="mature_exclusive_route_choice",
        categories=incumbent_choice,
        ordered_categories=("incumbent_retained", "challenger_used"),
        split_parent_sample=(
            "mature_exclusive_entry_symmetric_common_support"
        ),
        split_definition=(
            "observed family equals the exclusive first family or uses its rival"
        ),
    )

    pair_age = pd.to_numeric(consequence["pair_age_days"], errors="coerce")
    pair_age_category = pd.Series(
        np.select(
            [
                pair_age.between(0, 89, inclusive="both"),
                pair_age.between(90, 364, inclusive="both"),
                pair_age.ge(365),
                pair_age.lt(0),
            ],
            [
                "0_to_89_days",
                "90_to_364_days",
                "365_plus_days",
                "before_recorded_pair_entry",
            ],
            default="pair_entry_date_unavailable",
        ),
        index=consequence.index,
        dtype="string",
    )
    add_split(
        consequence,
        dimension="pair_age",
        categories=pair_age_category,
        ordered_categories=(
            "0_to_89_days",
            "90_to_364_days",
            "365_plus_days",
            "before_recorded_pair_entry",
            "pair_entry_date_unavailable",
        ),
        split_parent_sample=parent_sample,
        split_definition="days since pair_first_supported_date",
    )

    input_value = pd.to_numeric(consequence["input_usd"], errors="coerce")
    input_size_category = pd.Series(
        np.select(
            [
                input_value.lt(1_000),
                input_value.lt(10_000),
                input_value.lt(100_000),
            ],
            ["100_to_999_usd", "1k_to_9_999_usd", "10k_to_99_999_usd"],
            default="100k_plus_usd",
        ),
        index=consequence.index,
        dtype="string",
    )
    add_split(
        consequence,
        dimension="input_size",
        categories=input_size_category,
        ordered_categories=(
            "100_to_999_usd",
            "1k_to_9_999_usd",
            "10k_to_99_999_usd",
            "100k_plus_usd",
        ),
        split_parent_sample=parent_sample,
        split_definition="observed route input value in US dollars",
    )

    positive_capital = consequence[
        consequence["both_v2_bridge_capitals_positive"]
    ].copy()
    if (
        positive_capital["stable_v2_bridge_capital_usd"].le(0).any()
        or positive_capital["native_v2_bridge_capital_usd"].le(0).any()
    ):
        raise ValueError("positive-capital split contains a zero family capital")
    relative_capital = np.divide(
        positive_capital["stable_v2_bridge_capital_usd"],
        positive_capital["native_v2_bridge_capital_usd"],
    )
    relative_capital_category = pd.Series(
        np.select(
            [relative_capital.lt(0.5), relative_capital.le(2.0)],
            ["native_over_2x_stable", "within_2x"],
            default="stable_over_2x_native",
        ),
        index=positive_capital.index,
        dtype="string",
    )
    add_split(
        positive_capital,
        dimension="relative_v2_bridge_capital",
        categories=relative_capital_category,
        ordered_categories=(
            "native_over_2x_stable",
            "within_2x",
            "stable_over_2x_native",
        ),
        split_parent_sample=(
            "contestable_symmetric_common_support_positive_v2_bridge_capital"
        ),
        split_definition=(
            "stablecoin-to-WETH ratio of prior-day V2 bottleneck capital; "
            "both family capitals are positive"
        ),
    )
    return pd.DataFrame(rows)


def support_rows(
    panel: pd.DataFrame,
    *,
    load_counts: dict[str, int],
) -> pd.DataFrame:
    """Report sample support, V2-capital coverage, and output consequences."""

    rows: list[dict[str, object]] = []
    scope = {
        "sampling_calendar": SAMPLING_CALENDAR,
        "exact_venue_scope": EXACT_VENUE_SCOPE,
        "quoted_vehicle_universe": "WETH+DAI+USDC+USDT",
        "entry_family_scope": "all_classified_native_or_stable",
        "entry_scope_limitation": (
            "pair-support aggregates cannot be token-filtered; exclusive "
            "first-family entry is primary"
        ),
        "minimum_input_usd": MIN_INPUT_USD,
        "quoted_alternative_max_leg_price_impact": (
            QUOTED_LEG_MAX_PRICE_IMPACT
        ),
        "minimum_incumbent_age_days": MIN_INCUMBENT_AGE_DAYS,
        "incumbency_uses_strictly_prior_dates": True,
        "v2_bridge_capital_timing": "prior_calendar_day_deposited_capital",
        **load_counts,
    }
    for label, frame in (
        ("contestable_exact_routes", panel),
        (
            "contestable_symmetric_common_support",
            panel[panel["symmetric_common_support"]],
        ),
        (
            "mature_exclusive_entry_symmetric_common_support",
            panel[
                panel["mature_exclusive_incumbent"]
                & panel["symmetric_common_support"]
            ],
        ),
        (
            "mature_mixed_entry_majority_symmetric_common_support",
            panel[
                panel["mature_mixed_entry_majority"]
                & panel["symmetric_common_support"]
            ],
        ),
        (
            "mature_exclusive_entry_positive_v2_bridge_capital",
            panel[
                panel["mature_exclusive_incumbent"]
                & panel["symmetric_common_support"]
                & panel["both_v2_bridge_capitals_positive"]
            ],
        ),
    ):
        non_ties = frame[~frame["price_tie"]]
        rows.append(
            {
                "record_type": "contestable_vehicle_choice_support",
                "sample": label,
                "routes": int(len(frame)),
                "ordered_pairs": int(frame["ordered_pair"].nunique()),
                "dates": int(frame["day"].nunique()),
                "price_non_tie_routes": int(len(non_ties)),
                "chosen_matches_price_leader_share": (
                    float(non_ties["chosen_matches_price_leader"].mean())
                    if len(non_ties)
                    else np.nan
                ),
                "incumbent_retained_share": (
                    float(frame["incumbent_retained"].mean())
                    if "incumbent_retained" in frame and len(frame)
                    else np.nan
                ),
                "challenger_price_leader_share": (
                    float(non_ties["challenger_price_leader"].mean())
                    if "challenger_price_leader" in non_ties and len(non_ties)
                    else np.nan
                ),
                "both_positive_v2_bridge_capital_share": (
                    float(frame["both_v2_bridge_capitals_positive"].mean())
                    if len(frame)
                    else np.nan
                ),
                "stable_v2_bridge_capital_positive_share": (
                    float(frame["stable_v2_bridge_capital_usd"].gt(0).mean())
                    if len(frame)
                    else np.nan
                ),
                "native_v2_bridge_capital_positive_share": (
                    float(frame["native_v2_bridge_capital_usd"].gt(0).mean())
                    if len(frame)
                    else np.nan
                ),
                "stable_output_advantage_cap_share": (
                    float(frame["stable_output_advantage_capped"].mean())
                    if len(frame)
                    else np.nan
                ),
                "incumbent_output_advantage_cap_share": (
                    float(
                        frame.loc[
                            frame["incumbent_known_prior"],
                            "incumbent_output_advantage_capped",
                        ].mean()
                    )
                    if frame["incumbent_known_prior"].any()
                    else np.nan
                ),
                "chosen_impact_above_support_share": (
                    float((~frame["symmetric_common_support"]).mean())
                    if len(frame)
                    else np.nan
                ),
                "entry_day_routes": int(frame["entry_day_observation"].sum()),
                "pre_entry_routes": int(frame["pre_entry_observation"].sum()),
                **scope,
            }
        )
    primary_capital = panel[
        panel["mature_exclusive_incumbent"]
        & panel["symmetric_common_support"]
        & panel["both_v2_bridge_capitals_positive"]
    ].copy()
    for year, group in primary_capital.groupby(
        primary_capital["date"].dt.year, sort=True
    ):
        rows.append(
            {
                "record_type": "lagged_v2_bridge_capital_year_support",
                "sample": "mature_exclusive_entry_positive_v2_bridge_capital",
                "year": int(year),
                "routes": int(len(group)),
                "ordered_pairs": int(group["ordered_pair"].nunique()),
                "dates": int(group["day"].nunique()),
                **scope,
            }
        )
    mature = panel[
        panel["mature_exclusive_incumbent"]
        & panel["symmetric_common_support"]
        & ~panel["price_tie"]
    ].copy()
    for relation, selector in (
        ("incumbent_price_leader", mature["incumbent_price_leader"].eq(1.0)),
        ("challenger_price_leader", mature["challenger_price_leader"].eq(1.0)),
    ):
        selected = mature[selector]
        rows.append(
            {
                "record_type": "incumbent_price_relation_summary",
                "sample": relation,
                "routes": int(len(selected)),
                "ordered_pairs": int(selected["ordered_pair"].nunique()),
                "dates": int(selected["day"].nunique()),
                "incumbent_retained_share": (
                    float(selected["incumbent_retained"].mean())
                    if len(selected)
                    else np.nan
                ),
                "price_lead_threshold_bps": MIN_PRICE_LEAD_BPS,
                **scope,
            }
        )
    consequence = output_consequence_rows(panel)
    for record in consequence.to_dict(orient="records"):
        rows.append({**record, **scope})
    return pd.DataFrame(rows)


def run(
    *,
    root: Path = REPO_ROOT,
    frontier_path: Path = FRONTIER,
    pair_support_path: Path = PAIR_SUPPORT,
    pool_capital_path: Path = POOL_CAPITAL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
) -> int:
    frontier_path = _path(frontier_path, root)
    pair_support_path = _path(pair_support_path, root)
    pool_capital_path = _path(pool_capital_path, root)
    output_path = _path(output_path, root)
    support_path = _path(support_path, root)
    for path in (frontier_path, pair_support_path, pool_capital_path):
        if not path.is_file():
            raise FileNotFoundError(f"contestable-choice input is missing: {path}")
    raw_frontier = pd.read_parquet(frontier_path, columns=list(FRONTIER_COLUMNS))
    frontier, load_counts = prepare_frontier(raw_frontier)
    roles = load_first_vehicle_roles(pair_support_path)
    panel_with_roles = attach_incumbency(frontier, roles)
    capital = load_lagged_v2_bridge_capital(
        panel_with_roles, pool_capital_path
    )
    panel = attach_v2_bridge_capital(panel_with_roles, capital)
    results = regression_results(panel)
    support = support_rows(panel, load_counts=load_counts)
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results):,} coefficient rows over "
        f"{len(panel):,} contestable routes"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    args = parser.parse_args()
    return run(
        frontier_path=args.frontier,
        pair_support_path=args.pair_support,
        pool_capital_path=args.pool_capital,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    with exclusive_job(LOCK, job="contestable vehicle choice"):
        raise SystemExit(main())
