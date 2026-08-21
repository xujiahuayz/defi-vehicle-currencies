#!/usr/bin/env python3
"""Estimate LP-supply changes around the Uniswap V2 protocol-fee switch.

Uniswap governance proposal 93 set the Ethereum V2 factory ``feeTo`` in block
24,106,378 at 2025-12-27 20:33:11 UTC.  The LP share of each swap fell from
30 bp to 25 bp.  SushiSwap V2 already paid its LPs 25 bp and therefore supplies
a same-contract-family comparison for token pairs active on both venues.

The analysis uses Mint/Burn flows and deposited capital only.  It does not use
route choice or trade allocation as an outcome.  Monday-to-Sunday weeks are
matched by unordered token pair.  The partly treated week beginning Dec. 22 is
dropped; Dec. 29 is the first post-treatment week.  Event paths, pre-period
slopes, and pre-event placebo dates accompany the before-after contrast.

Because the fee changed once for every Uniswap V2 pool, there is one treated
venue-time cluster.  Pair-level standard errors describe cross-pair dispersion;
they do not create independent treatment assignments.  Results are therefore
reported as reduced-form event evidence, with venue-wide causal inference left
unavailable.

Reads
    data/processed/v2_lp_flow_pool_daily.parquet
    data/processed/sushiswap_v2_lp_flow_pool_daily.parquet
Writes
    output/exhibits/v2_protocol_fee_switch_pair_week.parquet
    output/exhibits/v2_protocol_fee_switch.jsonl
    output/exhibits/v2_protocol_fee_switch_support.jsonl
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import mean_clustered
from ddvc.capital_validation import USD_STABLE_TOKENS
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


UNISWAP_INPUT = DATA_DIR / "processed/v2_lp_flow_pool_daily.parquet"
SUSHISWAP_INPUT = DATA_DIR / "processed/sushiswap_v2_lp_flow_pool_daily.parquet"
PANEL_OUTPUT = OUTPUT_DIR / "exhibits/v2_protocol_fee_switch_pair_week.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v2_protocol_fee_switch.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v2_protocol_fee_switch_support.jsonl"

ACTIVATION_TIMESTAMP_UTC = "2025-12-27T20:33:11Z"
ACTIVATION_BLOCK = 24_106_378
ACTIVATION_TRANSACTION = (
    "0x091f0083242a777d55821c1189e568d6d033d9da501b75087dc736fa143d2c1e"
)
PARTIAL_WEEK = pd.Timestamp("2025-12-22")
FIRST_POST_WEEK = pd.Timestamp("2025-12-29")
FIRST_MAIN_WEEK = pd.Timestamp("2025-09-29")
LAST_MAIN_WEEK = pd.Timestamp("2026-03-16")
PRE_WEEKS = 12
POST_WEEKS = 12
REQUIRED_ACTIVE_DAYS_PER_WEEK = 7
MAIN_MIN_PRE_CAPITAL_USD = 10_000.0
PLACEBO_WEEKS = tuple(
    pd.Timestamp(day)
    for day in (
        "2025-10-27",
        "2025-11-03",
        "2025-11-10",
        "2025-11-17",
        "2025-11-24",
    )
)
PLACEBO_WINDOW_WEEKS = 4
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
STABLES = frozenset(str(token).lower() for token in USD_STABLE_TOKENS)

UNISWAP_PRE_LP_FEE = 0.003
UNISWAP_POST_LP_FEE = 0.0025
SUSHISWAP_LP_FEE = 0.0025

CODE_SOURCES = ["scripts/analyze/run_v2_protocol_fee_switch.py"]
INPUTS = [
    "data/processed/v2_lp_flow_pool_daily.parquet",
    "data/processed/sushiswap_v2_lp_flow_pool_daily.parquet",
]


@dataclass(frozen=True)
class Outcome:
    name: str
    label: str
    requires_complete_valuation: bool


OUTCOMES = (
    Outcome("asinh_add_flow_rate", "LP additions divided by prior capital", True),
    Outcome("asinh_remove_flow_rate", "LP withdrawals divided by prior capital", True),
    Outcome("asinh_net_flow_rate", "net LP additions divided by prior capital", True),
    Outcome("asinh_gross_flow_rate", "gross LP flow divided by prior capital", True),
    Outcome("log_capital_usd", "deposited pool capital", False),
    Outcome(
        "asinh_net_liquidity_rate",
        "net raw LP-token quantity divided by prior constant-product liquidity",
        False,
    ),
)


def _normalise_address(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower()


def _relative_week(week: pd.Series) -> pd.Series:
    week = pd.to_datetime(week)
    before = week.lt(PARTIAL_WEEK)
    result = pd.Series(index=week.index, dtype="int64")
    result.loc[before] = ((week.loc[before] - PARTIAL_WEEK).dt.days // 7).astype(int)
    result.loc[~before] = ((week.loc[~before] - FIRST_POST_WEEK).dt.days // 7).astype(int)
    return result


def _vehicle_class(token_a: str, token_b: str) -> str:
    tokens = {token_a, token_b}
    stable_count = len(tokens & STABLES)
    has_weth = WETH in tokens
    if stable_count == 2:
        return "stable_stable"
    if stable_count == 1 and has_weth:
        return "weth_stable"
    if stable_count == 1:
        return "stable_other"
    if has_weth:
        return "weth_other"
    return "other_other"


def load_daily_flows(
    uniswap_path: Path = UNISWAP_INPUT,
    sushiswap_path: Path = SUSHISWAP_INPUT,
) -> pd.DataFrame:
    """Read only daily columns and dates needed by the event study."""

    for path in (uniswap_path, sushiswap_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    first_day = FIRST_MAIN_WEEK.strftime("%Y-%m-%d")
    last_day = (LAST_MAIN_WEEK + pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    paths = [str(uniswap_path), str(sushiswap_path)]
    connection = duckdb.connect()
    try:
        frame = connection.execute(
            """
            SELECT
                lower(venue) AS venue,
                CAST(origin_date AS DATE) AS origin_date,
                lower(pool) AS pool,
                lower(token0_address) AS token0_address,
                lower(token1_address) AS token1_address,
                v2_add_lp_flow_usd,
                v2_remove_lp_flow_usd,
                v2_gross_lp_flow_usd,
                v2_net_add_lp_flow_usd,
                v2_add_liquidity,
                v2_remove_liquidity,
                v2_gross_liquidity,
                v2_net_add_liquidity,
                v2_raw_add_events,
                v2_raw_remove_events,
                v2_add_events_valued,
                v2_remove_events_valued,
                v2_missing_invalid_liquidity_events,
                v2_needs_complete_events,
                v2_volume_usd,
                v2_lagged_capital_usd,
                v2_lagged_sqrt_k,
                v2_capital_usd,
                v2_exact_lag_valid,
                v2_capital_valid
            FROM read_parquet(?, union_by_name=true)
            WHERE CAST(origin_date AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND lower(venue) IN ('uniswap_v2', 'sushiswap_v2')
            """,
            [paths, first_day, last_day],
        ).fetchdf()
    finally:
        connection.close()
    return frame


def _first_valid(group: pd.DataFrame, column: str, flag: str) -> float:
    values = pd.to_numeric(group[column], errors="coerce")
    valid = group[flag].fillna(False).astype(bool) & np.isfinite(values) & values.gt(0)
    if not valid.any():
        return float("nan")
    return float(values.loc[valid].iloc[0])


def _last_valid(group: pd.DataFrame, column: str, flag: str) -> float:
    values = pd.to_numeric(group[column], errors="coerce")
    valid = group[flag].fillna(False).astype(bool) & np.isfinite(values) & values.gt(0)
    if not valid.any():
        return float("nan")
    return float(values.loc[valid].iloc[-1])


def prepare_pair_week_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pool-days and form same-token-pair venue differences."""

    required = {
        "venue",
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_net_add_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
        "v2_net_add_liquidity",
        "v2_raw_add_events",
        "v2_raw_remove_events",
        "v2_add_events_valued",
        "v2_remove_events_valued",
        "v2_missing_invalid_liquidity_events",
        "v2_needs_complete_events",
        "v2_volume_usd",
        "v2_lagged_capital_usd",
        "v2_lagged_sqrt_k",
        "v2_capital_usd",
        "v2_exact_lag_valid",
        "v2_capital_valid",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"fee-switch daily input lacks columns: {missing}")
    data = frame.copy()
    data["venue"] = data["venue"].astype(str).str.lower()
    if not set(data["venue"]).issubset({"uniswap_v2", "sushiswap_v2"}):
        raise ValueError("fee-switch input contains a noncomparison venue")
    for column in ("pool", "token0_address", "token1_address"):
        data[column] = _normalise_address(data[column])
    data["origin_date"] = pd.to_datetime(data["origin_date"]).dt.normalize()
    data = data[
        data["origin_date"].between(
            FIRST_MAIN_WEEK, LAST_MAIN_WEEK + pd.Timedelta(days=6)
        )
    ].copy()
    data["origin_week"] = data["origin_date"] - pd.to_timedelta(
        data["origin_date"].dt.weekday, unit="D"
    )
    data = data[data["origin_week"].ne(PARTIAL_WEEK)].copy()
    data["token_a"] = data[["token0_address", "token1_address"]].min(axis=1)
    data["token_b"] = data[["token0_address", "token1_address"]].max(axis=1)
    data["token_pair"] = data["token_a"] + "|" + data["token_b"]
    if data.duplicated(["venue", "pool", "origin_date"]).any():
        raise ValueError("fee-switch daily input is not unique by venue, pool, date")
    pool_pair = data.groupby(["venue", "pool"])["token_pair"].nunique()
    if pool_pair.gt(1).any():
        raise ValueError("a V2 pool changes token identity inside the event window")
    pair_pools = data.groupby(["venue", "token_pair"])["pool"].nunique()
    if pair_pools.gt(1).any():
        raise ValueError("a V2 venue has multiple pools for one unordered token pair")

    numeric = [
        "v2_add_lp_flow_usd",
        "v2_remove_lp_flow_usd",
        "v2_gross_lp_flow_usd",
        "v2_net_add_lp_flow_usd",
        "v2_add_liquidity",
        "v2_remove_liquidity",
        "v2_gross_liquidity",
        "v2_net_add_liquidity",
        "v2_raw_add_events",
        "v2_raw_remove_events",
        "v2_add_events_valued",
        "v2_remove_events_valued",
        "v2_missing_invalid_liquidity_events",
        "v2_needs_complete_events",
        "v2_volume_usd",
        "v2_lagged_capital_usd",
        "v2_lagged_sqrt_k",
        "v2_capital_usd",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.sort_values(["venue", "token_pair", "origin_date"], kind="stable")
    rows: list[dict[str, object]] = []
    for (venue, token_pair, origin_week), group in data.groupby(
        ["venue", "token_pair", "origin_week"], sort=True
    ):
        raw_events = int(
            group["v2_raw_add_events"].fillna(0).sum()
            + group["v2_raw_remove_events"].fillna(0).sum()
        )
        valued_events = int(
            group["v2_add_events_valued"].fillna(0).sum()
            + group["v2_remove_events_valued"].fillna(0).sum()
        )
        prior_capital = _first_valid(
            group, "v2_lagged_capital_usd", "v2_exact_lag_valid"
        )
        prior_sqrt_k = _first_valid(group, "v2_lagged_sqrt_k", "v2_exact_lag_valid")
        end_capital = _last_valid(group, "v2_capital_usd", "v2_capital_valid")
        rows.append(
            {
                "venue": venue,
                "token_pair": token_pair,
                "token_a": str(group["token_a"].iloc[0]),
                "token_b": str(group["token_b"].iloc[0]),
                "pool": str(group["pool"].iloc[0]),
                "origin_week": origin_week,
                "active_days": int(group["origin_date"].nunique()),
                "prior_capital_usd": prior_capital,
                "prior_sqrt_k": prior_sqrt_k,
                "end_capital_usd": end_capital,
                "add_flow_usd": float(group["v2_add_lp_flow_usd"].fillna(0).sum()),
                "remove_flow_usd": float(
                    group["v2_remove_lp_flow_usd"].fillna(0).sum()
                ),
                "gross_flow_usd": float(
                    group["v2_gross_lp_flow_usd"].fillna(0).sum()
                ),
                "net_flow_usd": float(
                    group["v2_net_add_lp_flow_usd"].fillna(0).sum()
                ),
                "add_liquidity": float(group["v2_add_liquidity"].fillna(0).sum()),
                "remove_liquidity": float(
                    group["v2_remove_liquidity"].fillna(0).sum()
                ),
                "gross_liquidity": float(
                    group["v2_gross_liquidity"].fillna(0).sum()
                ),
                "net_liquidity": float(
                    group["v2_net_add_liquidity"].fillna(0).sum()
                ),
                "volume_usd": float(group["v2_volume_usd"].fillna(0).sum()),
                "raw_events": raw_events,
                "valued_events": valued_events,
                "complete_valuation": raw_events == valued_events,
                "missing_liquidity_events": int(
                    group["v2_missing_invalid_liquidity_events"].fillna(0).sum()
                ),
                "needs_complete_events": int(
                    group["v2_needs_complete_events"].fillna(0).sum()
                ),
            }
        )
    weekly = pd.DataFrame(rows)
    if weekly.empty:
        raise ValueError("fee-switch weekly comparison is empty")
    weekly["asinh_add_flow_rate"] = np.arcsinh(
        weekly["add_flow_usd"] / weekly["prior_capital_usd"]
    )
    weekly["asinh_remove_flow_rate"] = np.arcsinh(
        weekly["remove_flow_usd"] / weekly["prior_capital_usd"]
    )
    weekly["asinh_gross_flow_rate"] = np.arcsinh(
        weekly["gross_flow_usd"] / weekly["prior_capital_usd"]
    )
    weekly["asinh_net_flow_rate"] = np.arcsinh(
        weekly["net_flow_usd"] / weekly["prior_capital_usd"]
    )
    weekly["asinh_net_liquidity_rate"] = np.arcsinh(
        weekly["net_liquidity"] / weekly["prior_sqrt_k"]
    )
    weekly["log_capital_usd"] = np.log(weekly["end_capital_usd"])

    index_columns = ["token_pair", "token_a", "token_b", "origin_week"]
    value_columns = [
        "pool",
        "active_days",
        "prior_capital_usd",
        "prior_sqrt_k",
        "end_capital_usd",
        "add_flow_usd",
        "remove_flow_usd",
        "gross_flow_usd",
        "net_flow_usd",
        "add_liquidity",
        "remove_liquidity",
        "gross_liquidity",
        "net_liquidity",
        "volume_usd",
        "raw_events",
        "valued_events",
        "complete_valuation",
        "missing_liquidity_events",
        "needs_complete_events",
        *(outcome.name for outcome in OUTCOMES),
    ]
    wide = weekly.pivot(index=index_columns, columns="venue", values=value_columns)
    required_venues = {"uniswap_v2", "sushiswap_v2"}
    if not required_venues.issubset(set(wide.columns.get_level_values(1))):
        raise ValueError("fee-switch panel lacks one comparison venue")
    wide.columns = [f"{column}_{venue}" for column, venue in wide.columns]
    matched = wide.reset_index()
    matched["relative_week"] = _relative_week(matched["origin_week"])
    matched["post"] = matched["origin_week"].ge(FIRST_POST_WEEK)
    matched["vehicle_class"] = [
        _vehicle_class(a, b) for a, b in zip(matched["token_a"], matched["token_b"], strict=True)
    ]
    matched["stable_involving"] = matched["token_a"].isin(STABLES) | matched[
        "token_b"
    ].isin(STABLES)
    matched["weth_involving"] = matched["token_a"].eq(WETH) | matched["token_b"].eq(WETH)
    for outcome in OUTCOMES:
        matched[f"diff_{outcome.name}"] = (
            matched[f"{outcome.name}_uniswap_v2"]
            - matched[f"{outcome.name}_sushiswap_v2"]
        )
        if outcome.requires_complete_valuation:
            valid = matched["complete_valuation_uniswap_v2"].fillna(False) & matched[
                "complete_valuation_sushiswap_v2"
            ].fillna(False)
            matched.loc[~valid, f"diff_{outcome.name}"] = np.nan
    quantity_valid = matched["missing_liquidity_events_uniswap_v2"].fillna(1).eq(0) & matched[
        "missing_liquidity_events_sushiswap_v2"
    ].fillna(1).eq(0)
    matched.loc[~quantity_valid, "diff_asinh_net_liquidity_rate"] = np.nan
    return matched.sort_values(["token_pair", "origin_week"], kind="stable").reset_index(
        drop=True
    )


def select_balanced_pairs(
    panel: pd.DataFrame,
    *,
    outcome: str,
    min_pre_capital_usd: float = MAIN_MIN_PRE_CAPITAL_USD,
    required_pre_weeks: int = PRE_WEEKS,
    required_post_weeks: int = POST_WEEKS,
) -> pd.Index:
    """Return pairs with complete matched outcome support and material pre capital."""

    column = f"diff_{outcome}"
    if column not in panel:
        raise ValueError(f"unknown fee-switch outcome {outcome}")
    data = panel[np.isfinite(pd.to_numeric(panel[column], errors="coerce"))].copy()
    data = data[
        data["active_days_uniswap_v2"].eq(REQUIRED_ACTIVE_DAYS_PER_WEEK)
        & data["active_days_sushiswap_v2"].eq(REQUIRED_ACTIVE_DAYS_PER_WEEK)
    ].copy()
    pre = data[data["relative_week"].between(-PRE_WEEKS, -1)]
    post = data[data["relative_week"].between(0, POST_WEEKS - 1)]
    pre_counts = pre.groupby("token_pair")["origin_week"].nunique()
    post_counts = post.groupby("token_pair")["origin_week"].nunique()
    capital = pre.groupby("token_pair")[[
        "prior_capital_usd_uniswap_v2",
        "prior_capital_usd_sushiswap_v2",
    ]].median()
    selected = (
        pre_counts[pre_counts.ge(required_pre_weeks)].index
        .intersection(post_counts[post_counts.ge(required_post_weeks)].index)
        .intersection(
            capital[
                capital["prior_capital_usd_uniswap_v2"].ge(min_pre_capital_usd)
                & capital["prior_capital_usd_sushiswap_v2"].ge(min_pre_capital_usd)
            ].index
        )
    )
    return selected


def _mean_record(values: pd.Series, pairs: pd.Series) -> dict[str, float | int]:
    fit = mean_clustered(values, pairs)
    statistic = fit.estimate / fit.standard_error if fit.standard_error > 0 else np.nan
    p_value = (
        float(2 * stats.t.sf(abs(statistic), fit.n_clusters - 1))
        if fit.n_clusters > 1 and np.isfinite(statistic)
        else np.nan
    )
    return {
        "estimate": fit.estimate,
        "standard_error": fit.standard_error,
        "t_statistic": float(statistic),
        "p_value_pair_reference": p_value,
        "confidence_interval_lower": fit.confidence_interval_lower,
        "confidence_interval_upper": fit.confidence_interval_upper,
        "observations": fit.n_observations,
        "pair_clusters": fit.n_clusters,
    }


def _subsample(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "all_matched_pairs":
        return panel
    if name == "stable_involving":
        return panel[panel["stable_involving"]]
    if name == "weth_without_stable":
        return panel[panel["weth_involving"] & ~panel["stable_involving"]]
    raise ValueError(f"unknown fee-switch subsample {name}")


def estimate_fee_switch(
    panel: pd.DataFrame,
    *,
    min_pre_capital_usd: float = MAIN_MIN_PRE_CAPITAL_USD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return event, pretrend, DID, placebo, and support records."""

    result_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    for outcome in OUTCOMES:
        selected = select_balanced_pairs(
            panel,
            outcome=outcome.name,
            min_pre_capital_usd=min_pre_capital_usd,
        )
        balanced = panel[panel["token_pair"].isin(selected)].copy()
        for sample_name in ("all_matched_pairs", "stable_involving", "weth_without_stable"):
            sample = _subsample(balanced, sample_name)
            pairs = sample["token_pair"].drop_duplicates()
            support_rows.append(
                {
                    "record_type": "v2_protocol_fee_switch_support",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "sample": sample_name,
                    "pairs": int(len(pairs)),
                    "pair_weeks": int(len(sample)),
                    "minimum_pre_capital_usd_each_venue": float(min_pre_capital_usd),
                    "required_pre_weeks": PRE_WEEKS,
                    "required_post_weeks": POST_WEEKS,
                    "required_active_days_per_venue_week": (
                        REQUIRED_ACTIVE_DAYS_PER_WEEK
                    ),
                }
            )
            if len(pairs) < 2:
                continue
            value = f"diff_{outcome.name}"
            pivot = sample.pivot(
                index="token_pair", columns="relative_week", values=value
            ).apply(pd.to_numeric, errors="coerce")
            required = list(range(-PRE_WEEKS, 0)) + list(range(POST_WEEKS))
            pivot = pivot.dropna(subset=required)
            if len(pivot) < 2:
                continue

            full_change = pivot[list(range(POST_WEEKS))].mean(axis=1) - pivot[
                list(range(-PRE_WEEKS, 0))
            ].mean(axis=1)
            result_rows.append(
                {
                    "record_type": "difference_in_differences",
                    "window": "12_pre_12_post_weeks",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "sample": sample_name,
                    **_mean_record(full_change, full_change.index.to_series()),
                }
            )
            short_change = pivot[list(range(0, 4))].mean(axis=1) - pivot[
                list(range(-4, 0))
            ].mean(axis=1)
            result_rows.append(
                {
                    "record_type": "difference_in_differences",
                    "window": "4_pre_4_post_weeks",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "sample": sample_name,
                    **_mean_record(short_change, short_change.index.to_series()),
                }
            )

            baseline = pivot[-1]
            for relative_week in required:
                contrast = pivot[relative_week] - baseline
                result_rows.append(
                    {
                        "record_type": "event_path",
                        "window": "relative_to_week_minus_1",
                        "outcome": outcome.name,
                        "outcome_label": outcome.label,
                        "sample": sample_name,
                        "relative_week": relative_week,
                        **_mean_record(contrast, contrast.index.to_series()),
                    }
                )

            x = np.arange(-PRE_WEEKS, 0, dtype=float)
            slopes = pd.Series(
                [
                    np.polyfit(
                        x,
                        pivot.loc[pair, list(range(-PRE_WEEKS, 0))],
                        1,
                    )[0]
                    for pair in pivot.index
                ],
                index=pivot.index,
                name="pretrend_slope",
            )
            result_rows.append(
                {
                    "record_type": "pretrend",
                    "window": "12_pre_weeks",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "sample": sample_name,
                    **_mean_record(slopes, slopes.index.to_series()),
                }
            )

            placebo_estimates: list[float] = []
            sample_by_week = sample.set_index(["token_pair", "origin_week"])[value]
            for placebo_week in PLACEBO_WEEKS:
                pre_weeks = [
                    placebo_week - pd.Timedelta(weeks=offset)
                    for offset in range(PLACEBO_WINDOW_WEEKS, 0, -1)
                ]
                post_weeks = [
                    placebo_week + pd.Timedelta(weeks=offset)
                    for offset in range(PLACEBO_WINDOW_WEEKS)
                ]
                placebo_pivot = sample_by_week.unstack("origin_week").apply(
                    pd.to_numeric, errors="coerce"
                )
                placebo_pivot = placebo_pivot.dropna(subset=pre_weeks + post_weeks)
                if len(placebo_pivot) < 2:
                    continue
                changes = placebo_pivot[post_weeks].mean(axis=1) - placebo_pivot[
                    pre_weeks
                ].mean(axis=1)
                record = _mean_record(changes, changes.index.to_series())
                placebo_estimates.append(float(record["estimate"]))
                result_rows.append(
                    {
                        "record_type": "placebo_date",
                        "window": "4_pre_4_post_weeks",
                        "outcome": outcome.name,
                        "outcome_label": outcome.label,
                        "sample": sample_name,
                        "placebo_first_post_week": placebo_week.strftime("%Y-%m-%d"),
                        **record,
                    }
                )
            if placebo_estimates:
                result_rows.append(
                    {
                        "record_type": "placebo_reference",
                        "window": "4_pre_4_post_weeks",
                        "outcome": outcome.name,
                        "outcome_label": outcome.label,
                        "sample": sample_name,
                        "estimate": float(short_change.mean()),
                        "placebo_dates": len(placebo_estimates),
                        "placebo_minimum": float(min(placebo_estimates)),
                        "placebo_median": float(np.median(placebo_estimates)),
                        "placebo_maximum": float(max(placebo_estimates)),
                        "absolute_placebo_rank_fraction": float(
                            (1 + np.sum(np.abs(placebo_estimates) >= abs(short_change.mean())))
                            / (1 + len(placebo_estimates))
                        ),
                    }
                )

    results = pd.DataFrame(result_rows)
    support = pd.DataFrame(support_rows)
    if results.empty or support.empty:
        raise ValueError("fee-switch analysis produced no results")
    common = {
        "activation_timestamp_utc": ACTIVATION_TIMESTAMP_UTC,
        "activation_block": ACTIVATION_BLOCK,
        "activation_transaction": ACTIVATION_TRANSACTION,
        "partial_week_dropped": PARTIAL_WEEK.strftime("%Y-%m-%d"),
        "first_full_post_week": FIRST_POST_WEEK.strftime("%Y-%m-%d"),
        "uniswap_lp_fee_before": UNISWAP_PRE_LP_FEE,
        "uniswap_lp_fee_after": UNISWAP_POST_LP_FEE,
        "sushiswap_lp_fee": SUSHISWAP_LP_FEE,
        "assignment_unit": "one_uniswap_v2_venue_by_activation_time",
        "inference_scope": (
            "pair_reference_standard_errors_describe_cross_pair_dispersion; "
            "venue_level_causal_inference_unavailable"
        ),
        "simultaneous_change_boundary": (
            "proposal_93_was_a_governance_package; estimates_are_reduced_form_for_"
            "the_fee_activation_event_not_a_pure_fee_elasticity"
        ),
    }
    for key, value in common.items():
        results[key] = value
        support[key] = value
    return results, support


def run(
    *,
    uniswap_path: Path = UNISWAP_INPUT,
    sushiswap_path: Path = SUSHISWAP_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    min_pre_capital_usd: float = MAIN_MIN_PRE_CAPITAL_USD,
) -> int:
    daily = load_daily_flows(uniswap_path, sushiswap_path)
    panel = prepare_pair_week_panel(daily)
    results, support = estimate_fee_switch(
        panel, min_pre_capital_usd=min_pre_capital_usd
    )
    write_panel(panel, panel_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(panel):,} matched pair-weeks and {len(results):,} fee-switch results"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uniswap", type=Path, default=UNISWAP_INPUT)
    parser.add_argument("--sushiswap", type=Path, default=SUSHISWAP_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument(
        "--min-pre-capital-usd", type=float, default=MAIN_MIN_PRE_CAPITAL_USD
    )
    args = parser.parse_args()
    if args.min_pre_capital_usd < 0:
        raise ValueError("minimum pre-event capital cannot be negative")
    return run(
        uniswap_path=args.uniswap,
        sushiswap_path=args.sushiswap,
        panel_output=args.panel_output,
        result_output=args.result_output,
        support_output=args.support_output,
        min_pre_capital_usd=args.min_pre_capital_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
