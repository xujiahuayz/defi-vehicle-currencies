#!/usr/bin/env python3
"""Summarize Balancer stable-core and stable-spoke LP event flows.

The evidence is corroborating and descriptive.  It compares observed joins,
exits, and net joining across exact stablecoin cores and two-token stablecoin
spokes; reports pool concentration; and repeats each class after removing its
largest pool by fully priced gross flow.  Sender addresses are never interpreted
as beneficial LP owners.

Lagged volume, reported TVL, and relative-price-risk correlations are emitted
only when the processed panel has exact consecutive-Sunday state and complete
event dollarization.  Reported TVL is a Balancer subgraph quantity, not an
independently reconstructed capital stock.  Any risk association is descriptive
and cannot establish why capital was supplied.
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from ddvc.capital_validation import (
    PRICE_MEDIAN_FACTOR,
    PRICE_ROLLING_DAYS,
    USD_STABLE_PRICE_BOUNDS,
    USD_STABLE_TOKENS,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, TOKEN_PRICE_DAILY_PANEL
from ddvc.tables import write_exhibit


FLOW_INPUT = DATA_DIR / "processed/balancer_stable_core_lp_flow_weekly.parquet"
SUMMARY_OUTPUT = OUTPUT_DIR / "exhibits/balancer_stable_core_lp_flow_summary.jsonl"
CONCENTRATION_OUTPUT = (
    OUTPUT_DIR / "exhibits/balancer_stable_core_lp_flow_concentration.jsonl"
)
CORRELATION_OUTPUT = (
    OUTPUT_DIR / "exhibits/balancer_stable_core_lp_flow_correlations.jsonl"
)
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/balancer_stable_core_lp_flow_support.jsonl"

RISK_WINDOW_DAYS = 28
MIN_RISK_RETURN_DAYS = 20
MIN_CORRELATION_ROWS = 20
MIN_CORRELATION_POOLS = 2
POOL_CLASSES = ("stable_core", "stable_spoke")
USD_STABLES = frozenset(str(token).lower() for token in USD_STABLE_TOKENS)

CODE_SOURCES = ["scripts/analyze/run_balancer_stable_core_lp_flows.py"]
INPUTS = [
    "data/processed/balancer_stable_core_lp_flow_weekly.parquet",
    "data/processed/token_price_daily.parquet",
]


def validate_panel(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "week_start",
        "pool",
        "pool_class",
        "token_addresses",
        "join_event_count",
        "exit_event_count",
        "event_count",
        "priced_event_count",
        "priced_join_flow_usd",
        "priced_exit_flow_usd",
        "priced_gross_flow_usd",
        "priced_net_join_flow_usd",
        "flow_value_complete",
        "lagged_reported_tvl_usd",
        "lagged_volume_usd",
        "lagged_state_complete",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Balancer stable-core flow panel lacks columns: {missing}")
    if frame.empty:
        raise ValueError("Balancer stable-core flow panel is empty")
    if frame.duplicated(["week_start", "pool"]).any():
        raise ValueError("Balancer stable-core flow panel has duplicate pool-weeks")
    if not frame["pool_class"].isin(POOL_CLASSES).all():
        raise ValueError("Balancer flow panel contains an unsupported pool class")
    result = frame.copy()
    result["week_start"] = pd.to_datetime(result["week_start"])
    return result


def build_pool_concentration(
    panel: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rank pools within core/spoke classes and identify the largest pool."""

    rows: list[dict[str, object]] = []
    dominant: dict[str, str] = {}
    for pool_class in POOL_CLASSES:
        group = panel.loc[panel["pool_class"].eq(pool_class)].copy()
        if group.empty:
            continue
        pooled = (
            group.groupby("pool", sort=True)
            .agg(
                token_addresses=("token_addresses", "first"),
                pool_weeks=("week_start", "size"),
                active_pool_weeks=("event_count", lambda value: int((value > 0).sum())),
                join_event_count=("join_event_count", "sum"),
                exit_event_count=("exit_event_count", "sum"),
                event_count=("event_count", "sum"),
                priced_event_count=("priced_event_count", "sum"),
                priced_gross_flow_usd=("priced_gross_flow_usd", "sum"),
            )
            .reset_index()
        )
        total_flow = float(pooled["priced_gross_flow_usd"].sum())
        total_events = int(pooled["event_count"].sum())
        pooled["priced_gross_flow_share"] = (
            pooled["priced_gross_flow_usd"] / total_flow if total_flow > 0 else 0.0
        )
        pooled["event_share"] = (
            pooled["event_count"] / total_events if total_events > 0 else 0.0
        )
        pooled = pooled.sort_values(
            ["priced_gross_flow_usd", "event_count", "pool"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        if pooled.empty:
            continue
        dominant_pool = str(pooled.iloc[0]["pool"])
        dominant[pool_class] = dominant_pool
        pooled["pool_class"] = pool_class
        pooled["flow_rank"] = np.arange(1, len(pooled) + 1)
        pooled["largest_pool"] = pooled["pool"].eq(dominant_pool)
        pooled["priced_flow_hhi"] = float(
            np.square(pooled["priced_gross_flow_share"]).sum()
        )
        pooled["event_hhi"] = float(np.square(pooled["event_share"]).sum())
        rows.extend(pooled.to_dict("records"))
    return pd.DataFrame(rows), dominant


def summarize_flows(
    panel: pd.DataFrame,
    dominant: dict[str, str],
) -> pd.DataFrame:
    """Return full and leave-largest-pool-out flow totals for each class."""

    rows: list[dict[str, object]] = []
    for pool_class in POOL_CLASSES:
        base = panel.loc[panel["pool_class"].eq(pool_class)].copy()
        if base.empty:
            continue
        largest = dominant.get(pool_class)
        for sample, group in (
            ("all_pools", base),
            ("exclude_largest_pool", base.loc[base["pool"].ne(largest)]),
        ):
            complete = group["flow_value_complete"].astype(bool)
            observed_events = int(group["event_count"].sum())
            priced_events = int(group["priced_event_count"].sum())
            join_flow = float(group["priced_join_flow_usd"].sum())
            exit_flow = float(group["priced_exit_flow_usd"].sum())
            rows.append(
                {
                    "record_type": "balancer_stable_core_lp_flow_summary",
                    "pool_class": pool_class,
                    "sample": sample,
                    "excluded_pool": largest if sample == "exclude_largest_pool" else None,
                    "pools": int(group["pool"].nunique()),
                    "pool_weeks": int(len(group)),
                    "active_pool_weeks": int(group["event_count"].gt(0).sum()),
                    "join_event_count": int(group["join_event_count"].sum()),
                    "exit_event_count": int(group["exit_event_count"].sum()),
                    "event_count": observed_events,
                    "priced_event_count": priced_events,
                    "priced_event_share": (
                        float(priced_events / observed_events)
                        if observed_events > 0
                        else None
                    ),
                    "fully_priced_pool_weeks": int(complete.sum()),
                    "priced_join_flow_usd": join_flow,
                    "priced_exit_flow_usd": exit_flow,
                    "priced_gross_flow_usd": join_flow + exit_flow,
                    "priced_net_join_flow_usd": join_flow - exit_flow,
                    "quantity_boundary": (
                        "USD flows sum fully priced events; missing-price events are "
                        "omitted from dollars but retained in event counts and coverage"
                    ),
                    "interpretation_boundary": (
                        "corroborating observed pool flow; sender addresses are not "
                        "beneficial-owner identities"
                    ),
                }
            )
    return pd.DataFrame(rows)


def load_validated_price_frame(
    path: Path,
    tokens: set[str],
) -> pd.DataFrame:
    """Load only pool tokens passing the canonical address-day price screen."""

    if not path.is_file():
        raise FileNotFoundError(path)
    prices = pd.read_parquet(
        path,
        columns=["day", "token", "price_usd", "price_source", "validation_status"],
        filters=[("token", "in", sorted(tokens))],
    )
    if prices.empty:
        return pd.DataFrame(columns=["day", "token", "price_usd"])
    prices = prices.copy()
    prices["day"] = pd.to_datetime(prices["day"].astype(str), format="%Y%m%d")
    prices["token"] = prices["token"].astype(str).str.lower()
    prices["price_usd"] = pd.to_numeric(prices["price_usd"], errors="coerce")
    if prices.duplicated(["day", "token"]).any():
        raise ValueError("canonical price panel has duplicate Balancer token-days")
    prices = prices.sort_values(["token", "day"]).reset_index(drop=True)
    median = prices.groupby("token", sort=False)["price_usd"].transform(
        lambda value: value.rolling(PRICE_ROLLING_DAYS, min_periods=5).median()
    )
    value = prices["price_usd"]
    valid = (
        np.isfinite(value)
        & value.gt(0)
        & np.isfinite(median)
        & median.gt(0)
        & value.between(median / PRICE_MEDIAN_FACTOR, median * PRICE_MEDIAN_FACTOR)
        & prices["price_source"].eq("canonical_repriced_route_legs")
        & prices["validation_status"].eq(
            "minimum_observations_and_price_consensus_passed"
        )
    )
    stable = prices["token"].isin(USD_STABLES)
    valid &= ~stable | value.between(*USD_STABLE_PRICE_BOUNDS)
    return prices.loc[valid, ["day", "token", "price_usd"]].reset_index(drop=True)


def attach_trailing_relative_volatility(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    window_days: int = RISK_WINDOW_DAYS,
    min_return_days: int = MIN_RISK_RETURN_DAYS,
) -> pd.DataFrame:
    """Attach the largest pairwise relative-return volatility in each pool."""

    if window_days < 2 or min_return_days < 2 or min_return_days >= window_days:
        raise ValueError("invalid Balancer trailing-risk window")
    result = panel.copy()
    result["trailing_relative_volatility_annualized"] = np.nan
    result["trailing_relative_return_days"] = 0
    if prices.empty:
        return result
    price_pivot = prices.pivot(index="day", columns="token", values="price_usd").sort_index()
    cache: dict[tuple[str, pd.Timestamp], tuple[float | None, int]] = {}
    for index, row in result.iterrows():
        token_key = str(row["token_addresses"])
        week_start = pd.Timestamp(row["week_start"])
        cache_key = (token_key, week_start)
        if cache_key not in cache:
            tokens = token_key.split(",")
            start = week_start - pd.Timedelta(days=window_days + 1)
            end = week_start - pd.Timedelta(days=1)
            available = [token for token in tokens if token in price_pivot.columns]
            if len(available) != len(tokens):
                cache[cache_key] = (None, 0)
            else:
                levels = price_pivot.loc[
                    (price_pivot.index >= start) & (price_pivot.index <= end), tokens
                ].reindex(pd.date_range(start, end, freq="D"))
                log_returns = np.log(levels).diff()
                pair_risk: list[float] = []
                pair_days: list[int] = []
                for left, right in combinations(tokens, 2):
                    relative = (log_returns[left] - log_returns[right]).dropna()
                    pair_days.append(int(len(relative)))
                    if len(relative) >= min_return_days:
                        pair_risk.append(float(relative.std(ddof=1) * np.sqrt(365.0)))
                if not pair_risk or min(pair_days, default=0) < min_return_days:
                    cache[cache_key] = (None, min(pair_days, default=0))
                else:
                    cache[cache_key] = (max(pair_risk), min(pair_days))
        risk, observations = cache[cache_key]
        if risk is not None:
            result.at[index, "trailing_relative_volatility_annualized"] = risk
        result.at[index, "trailing_relative_return_days"] = observations
    return result


def prepare_correlation_panel(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    complete = (
        result["flow_value_complete"].astype(bool)
        & result["lagged_state_complete"].astype(bool)
        & pd.to_numeric(result["lagged_reported_tvl_usd"], errors="coerce").gt(0)
        & pd.to_numeric(result["lagged_volume_usd"], errors="coerce").ge(0)
    )
    result = result.loc[complete].copy()
    tvl = pd.to_numeric(result["lagged_reported_tvl_usd"], errors="coerce")
    result["gross_flow_intensity"] = result["priced_gross_flow_usd"] / tvl
    result["join_flow_intensity"] = result["priced_join_flow_usd"] / tvl
    result["exit_flow_intensity"] = result["priced_exit_flow_usd"] / tvl
    result["lagged_volume_turnover"] = result["lagged_volume_usd"] / tvl
    result["log_lagged_reported_tvl"] = np.log(tvl)
    return result.replace([np.inf, -np.inf], np.nan)


def _correlation_row(
    data: pd.DataFrame,
    *,
    pool_class: str,
    sample: str,
    outcome: str,
    predictor: str,
    excluded_pool: str | None,
) -> dict[str, object]:
    usable = data.dropna(subset=[outcome, predictor]).copy()
    support_ok = (
        len(usable) >= MIN_CORRELATION_ROWS
        and usable["pool"].nunique() >= MIN_CORRELATION_POOLS
        and usable[outcome].nunique() > 1
        and usable[predictor].nunique() > 1
    )
    row: dict[str, object] = {
        "record_type": "balancer_stable_core_lp_flow_correlation",
        "pool_class": pool_class,
        "sample": sample,
        "excluded_pool": excluded_pool,
        "outcome": outcome,
        "predictor": predictor,
        "pool_weeks": int(len(usable)),
        "pools": int(usable["pool"].nunique()),
        "weeks": int(usable["week_start"].nunique()),
        "status": "estimated" if support_ok else "withheld_insufficient_clean_support",
        "pearson_correlation": None,
        "pearson_p_value": None,
        "spearman_correlation": None,
        "spearman_p_value": None,
        "state_basis": (
            "prior-Sunday reported TVL and cumulative-volume difference over "
            "the preceding exact Sunday-to-Sunday week"
        ),
        "interpretation_boundary": (
            "descriptive association only; relative-price risk is not established "
            "as an LP motive and sender addresses do not identify beneficial owners"
        ),
    }
    if support_ok:
        pearson = pearsonr(usable[outcome], usable[predictor])
        spearman = spearmanr(usable[outcome], usable[predictor])
        row.update(
            {
                "pearson_correlation": float(pearson.statistic),
                "pearson_p_value": float(pearson.pvalue),
                "spearman_correlation": float(spearman.statistic),
                "spearman_p_value": float(spearman.pvalue),
            }
        )
    return row


def build_correlations(
    panel: pd.DataFrame,
    dominant: dict[str, str],
) -> pd.DataFrame:
    outcomes = ("gross_flow_intensity", "join_flow_intensity", "exit_flow_intensity")
    predictors = (
        "lagged_volume_turnover",
        "log_lagged_reported_tvl",
        "trailing_relative_volatility_annualized",
    )
    rows: list[dict[str, object]] = []
    for pool_class in POOL_CLASSES:
        base = panel.loc[panel["pool_class"].eq(pool_class)]
        if base.empty:
            continue
        largest = dominant.get(pool_class)
        for sample, data in (
            ("all_pools", base),
            ("exclude_largest_pool", base.loc[base["pool"].ne(largest)]),
        ):
            for outcome in outcomes:
                for predictor in predictors:
                    rows.append(
                        _correlation_row(
                            data,
                            pool_class=pool_class,
                            sample=sample,
                            outcome=outcome,
                            predictor=predictor,
                            excluded_pool=(
                                largest if sample == "exclude_largest_pool" else None
                            ),
                        )
                    )
    return pd.DataFrame(rows)


def run(
    *,
    flow_path: Path = FLOW_INPUT,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    summary_path: Path = SUMMARY_OUTPUT,
    concentration_path: Path = CONCENTRATION_OUTPUT,
    correlation_path: Path = CORRELATION_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    if not flow_path.is_file():
        raise FileNotFoundError(flow_path)
    panel = validate_panel(pd.read_parquet(flow_path))
    concentration, dominant = build_pool_concentration(panel)
    summary = summarize_flows(panel, dominant)
    tokens = {
        token
        for values in panel["token_addresses"].astype(str)
        for token in values.split(",")
    }
    prices = load_validated_price_frame(price_path, tokens)
    with_risk = attach_trailing_relative_volatility(panel, prices)
    correlation_panel = prepare_correlation_panel(with_risk)
    correlations = build_correlations(correlation_panel, dominant)
    support = pd.DataFrame(
        [
            {
                "record_type": "balancer_stable_core_lp_flow_support",
                "pool_week_rows": int(len(panel)),
                "pools": int(panel["pool"].nunique()),
                "stable_core_pools": int(
                    panel.loc[panel["pool_class"].eq("stable_core"), "pool"].nunique()
                ),
                "stable_spoke_pools": int(
                    panel.loc[panel["pool_class"].eq("stable_spoke"), "pool"].nunique()
                ),
                "observed_events": int(panel["event_count"].sum()),
                "priced_events": int(panel["priced_event_count"].sum()),
                "complete_state_pool_weeks": int(panel["lagged_state_complete"].sum()),
                "risk_supported_pool_weeks": int(
                    with_risk["trailing_relative_volatility_annualized"].notna().sum()
                ),
                "estimated_correlation_rows": int(
                    correlations["status"].eq("estimated").sum()
                ),
                "normalization_status": (
                    "reported_tvl_correlations_available_with_stated_boundary"
                    if correlations["status"].eq("estimated").any()
                    else "withheld_insufficient_exact_state_or_price_support"
                ),
                "evidence_role": (
                    "corroborating stable-core versus stable-spoke LP-flow evidence; "
                    "not a stand-alone motive or causal design"
                ),
                "ownership_boundary": (
                    "sender is an observed transaction address, not a beneficial owner"
                ),
            }
        ]
    )
    write_exhibit(summary, summary_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(
        concentration,
        concentration_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        correlations,
        correlation_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote Balancer core/spoke LP-flow summaries for "
        f"{panel['pool'].nunique():,} pools"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", type=Path, default=FLOW_INPUT)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument("--summary", type=Path, default=SUMMARY_OUTPUT)
    parser.add_argument("--concentration", type=Path, default=CONCENTRATION_OUTPUT)
    parser.add_argument("--correlations", type=Path, default=CORRELATION_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        flow_path=args.flow,
        price_path=args.price,
        summary_path=args.summary,
        concentration_path=args.concentration,
        correlation_path=args.correlations,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
