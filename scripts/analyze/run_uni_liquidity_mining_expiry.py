#!/usr/bin/env python3
"""Explore the predetermined 2020 UNI liquidity-mining start and expiry.

Uniswap announced fixed rewards for four V2 WETH pools from 2020-09-18
00:00 UTC through 2020-11-17 00:00 UTC.  This program uses those dates as
externally fixed event times.  Its primary output is a matched pool-level
first stage in quantity-based liquidity, ``log(sqrt(reserve0 * reserve1))``;
USD capital is a secondary measurement.  Matching uses only pre-event capital
and liquidity trends.  Calendar-placebo and matched-label permutation results
are written with the estimates.

The secondary output follows WBTC endpoint pairs around the reward expiry.
It retains pairs that used both WETH and a core stablecoin before expiry and
whose WBTC--WETH leg predominantly used the rewarded Uniswap pool.  This is a
narrow before/after reduced form, not an instrument or a general route-choice
estimate: targeted pool selection and concurrent demand changes remain.

Reads
    data/processed/pool_capital_daily.parquet
    data/processed/endpoint_candidate_choices.parquet
Writes
    output/exhibits/uni_liquidity_mining_expiry.jsonl
    output/exhibits/uni_liquidity_mining_expiry_support.jsonl
"""

from __future__ import annotations

import argparse
import itertools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd

from ddvc.asset_types import STABLE
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit


POOL_CAPITAL = DATA_DIR / "processed/pool_capital_daily.parquet"
ROUTE_CHOICES = DATA_DIR / "processed/endpoint_candidate_choices.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/uni_liquidity_mining_expiry.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/uni_liquidity_mining_expiry_support.jsonl"

ANALYSIS_STATUS = "exploratory_predetermined_incentive_event"
OFFICIAL_SOURCE = "https://blog.uniswap.org/uni"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CORE_STABLES = frozenset({DAI, USDC, USDT})
ALL_STABLES = frozenset(STABLE)


@dataclass(frozen=True)
class RewardedPool:
    symbol: str
    address: str


@dataclass(frozen=True)
class IncentiveEvent:
    event: str
    date: pd.Timestamp
    timestamp_utc: str
    expected_liquidity_direction: int
    interpretation: str


REWARDED_POOLS = (
    RewardedPool("USDT_WETH", "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852"),
    RewardedPool("USDC_WETH", "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"),
    RewardedPool("DAI_WETH", "0xa478c2975ab1ea89e8196811f51a7b7ade33eb11"),
    RewardedPool("WBTC_WETH", "0xbb2b8038a1640196fbe3e38816f3e67cba72d940"),
)
REWARDED_POOL_ADDRESSES = tuple(pool.address for pool in REWARDED_POOLS)
EVENTS = (
    IncentiveEvent(
        event="reward_start",
        date=pd.Timestamp("2020-09-18"),
        timestamp_utc="2020-09-18T00:00:00Z",
        expected_liquidity_direction=1,
        interpretation="fixed start of UNI rewards for the four named V2 pools",
    ),
    IncentiveEvent(
        event="reward_expiry",
        date=pd.Timestamp("2020-11-17"),
        timestamp_utc="2020-11-17T00:00:00Z",
        expected_liquidity_direction=-1,
        interpretation="fixed expiry of UNI rewards for the four named V2 pools",
    ),
)

POOL_OUTCOMES = (
    ("log_sqrt_k", "log quantity-based constant-product liquidity"),
    ("log_capital_usd", "log reserve capital valued with the released daily price anchors"),
)
MATCH_COVARIATES = ("pre_mean_log_capital", "pre_slope_log_sqrt_k")
CODE_SOURCES = ["scripts/analyze/run_uni_liquidity_mining_expiry.py"]
INPUTS = [
    "data/processed/pool_capital_daily.parquet",
    "data/processed/endpoint_candidate_choices.parquet",
]


def _normalise_address(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower()


def _slope(x: pd.Series, y: pd.Series) -> float:
    usable = pd.DataFrame({"x": x, "y": y}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(usable) < 2 or usable["x"].nunique() < 2:
        return float("nan")
    return float(np.polyfit(usable["x"].astype(float), usable["y"].astype(float), 1)[0])


def load_pool_rows(
    path: Path,
    *,
    events: Sequence[IncentiveEvent] = EVENTS,
    window_days: int,
    placebo_shift_days: int,
) -> pd.DataFrame:
    """Read only the WETH-pool dates needed by the event and placebo windows."""

    dates = [event.date for event in events] + [
        event.date + pd.Timedelta(days=placebo_shift_days) for event in events
    ]
    first = min(dates) - pd.Timedelta(days=window_days)
    last = max(dates) + pd.Timedelta(days=window_days - 1)
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='1GB'")
    try:
        return connection.execute(
            """
            SELECT
                venue, day, pool, token0_address, token0_symbol,
                token1_address, token1_symbol, reserve0, reserve1,
                capital_usd, capital_valid, quantity_kind, pool_family
            FROM read_parquet(?)
            WHERE venue = 'uniswap_v2'
              AND day BETWEEN ? AND ?
              AND (
                    lower(token0_address) = ?
                 OR lower(token1_address) = ?
              )
            """,
            [
                str(path),
                first.strftime("%Y%m%d"),
                last.strftime("%Y%m%d"),
                WETH,
                WETH,
            ],
        ).fetchdf()
    finally:
        connection.close()


def prepare_pool_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate daily V2 WETH-pool observations and construct two outcomes."""

    required = {
        "venue",
        "day",
        "pool",
        "token0_address",
        "token1_address",
        "reserve0",
        "reserve1",
        "capital_usd",
        "capital_valid",
        "quantity_kind",
        "pool_family",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"UNI incentive pool input lacks columns: {missing}")
    data = frame.copy()
    data["pool"] = _normalise_address(data["pool"])
    data["token0_address"] = _normalise_address(data["token0_address"])
    data["token1_address"] = _normalise_address(data["token1_address"])
    data["date"] = pd.to_datetime(data["day"].astype(str), format="%Y%m%d").dt.normalize()
    for column in ("reserve0", "reserve1", "capital_usd"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[
        data["venue"].eq("uniswap_v2")
        & data["quantity_kind"].eq("deposited_capital")
        & data["pool_family"].eq("full_range_constant_product")
        & data["capital_valid"].astype(bool)
        & (data["token0_address"].eq(WETH) | data["token1_address"].eq(WETH))
        & data["reserve0"].gt(0)
        & data["reserve1"].gt(0)
        & data["capital_usd"].gt(0)
    ].copy()
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["reserve0", "reserve1", "capital_usd"]
    )
    if data.empty:
        raise ValueError("UNI incentive WETH-pool sample is empty")
    if data.duplicated(["pool", "date"]).any():
        raise ValueError("UNI incentive pool input is not unique by pool and date")
    data["other_address"] = np.where(
        data["token0_address"].eq(WETH),
        data["token1_address"],
        data["token0_address"],
    )
    data["log_sqrt_k"] = 0.5 * (
        np.log(data["reserve0"].astype(float))
        + np.log(data["reserve1"].astype(float))
    )
    data["log_capital_usd"] = np.log(data["capital_usd"].astype(float))
    return data.sort_values(["pool", "date"], kind="stable").reset_index(drop=True)


def event_pool_summary(
    panel: pd.DataFrame,
    event: IncentiveEvent,
    *,
    window_days: int,
    minimum_support_share: float,
    minimum_pre_capital_usd: float,
) -> pd.DataFrame:
    """Return the transparent pool risk set and event-window changes."""

    data = panel[
        panel["date"].between(
            event.date - pd.Timedelta(days=window_days),
            event.date + pd.Timedelta(days=window_days - 1),
        )
    ].copy()
    data["relative_day"] = (data["date"] - event.date).dt.days.astype(int)
    rows: list[dict[str, object]] = []
    required_days = int(math.ceil(window_days * minimum_support_share))
    for pool, group in data.groupby("pool", sort=True):
        pre = group[group["relative_day"].between(-window_days, -1)]
        post = group[group["relative_day"].between(0, window_days - 1)]
        pre_mean_capital = float(pre["capital_usd"].mean()) if not pre.empty else float("nan")
        record: dict[str, object] = {
            "pool": pool,
            "other_address": str(group["other_address"].iloc[0]),
            "treated": pool in REWARDED_POOL_ADDRESSES,
            "pre_days": int(pre["date"].nunique()),
            "post_days": int(post["date"].nunique()),
            "pre_mean_capital_usd": pre_mean_capital,
            "pre_mean_log_capital": float(pre["log_capital_usd"].mean()),
            "pre_slope_log_sqrt_k": _slope(pre["relative_day"], pre["log_sqrt_k"]),
        }
        for outcome, _description in POOL_OUTCOMES:
            record[f"pre_mean_{outcome}"] = float(pre[outcome].mean())
            record[f"post_mean_{outcome}"] = float(post[outcome].mean())
            record[f"delta_{outcome}"] = (
                record[f"post_mean_{outcome}"] - record[f"pre_mean_{outcome}"]
            )
        record["eligible"] = bool(
            record["pre_days"] >= required_days
            and record["post_days"] >= required_days
            and np.isfinite(pre_mean_capital)
            and pre_mean_capital >= minimum_pre_capital_usd
            and np.isfinite(record["pre_slope_log_sqrt_k"])
            and all(np.isfinite(record[f"delta_{outcome}"]) for outcome, _ in POOL_OUTCOMES)
        )
        rows.append(record)
    return pd.DataFrame(rows).sort_values("pool", kind="stable").reset_index(drop=True)


def _covariate_scales(summary: pd.DataFrame) -> dict[str, float]:
    scales: dict[str, float] = {}
    for column in MATCH_COVARIATES:
        scale = float(pd.to_numeric(summary[column], errors="coerce").std(ddof=0))
        scales[column] = scale if np.isfinite(scale) and scale > 0 else 1.0
    return scales


def match_pool_group(
    summary: pd.DataFrame,
    treated_pools: Iterable[str],
    *,
    matches_per_treated: int,
) -> pd.DataFrame:
    """Nearest-neighbour match on pre-event size and quantity trend."""

    eligible = summary[summary["eligible"].astype(bool)].copy()
    treated_set = frozenset(str(pool).lower() for pool in treated_pools)
    treated = eligible[eligible["pool"].isin(treated_set)]
    controls = eligible[~eligible["pool"].isin(treated_set)]
    if len(treated) != len(treated_set):
        raise ValueError("not every nominated treated pool passes the risk-set rules")
    if len(controls) < matches_per_treated:
        raise ValueError("too few eligible control pools for matching")
    scales = _covariate_scales(eligible)
    rows: list[dict[str, object]] = []
    for treated_row in treated.sort_values("pool").itertuples(index=False):
        distance = np.zeros(len(controls), dtype=float)
        for column in MATCH_COVARIATES:
            difference = controls[column].astype(float).to_numpy() - float(
                getattr(treated_row, column)
            )
            distance += np.square(difference / scales[column])
        ranked = controls.assign(match_distance=np.sqrt(distance)).sort_values(
            ["match_distance", "pool"], kind="stable"
        ).head(matches_per_treated)
        for rank, control in enumerate(ranked.itertuples(index=False), start=1):
            rows.append(
                {
                    "treated_pool": treated_row.pool,
                    "control_pool": control.pool,
                    "match_rank": rank,
                    "match_distance": float(control.match_distance),
                    "treated_pre_mean_log_capital": float(
                        treated_row.pre_mean_log_capital
                    ),
                    "control_pre_mean_log_capital": float(
                        control.pre_mean_log_capital
                    ),
                    "treated_pre_slope_log_sqrt_k": float(
                        treated_row.pre_slope_log_sqrt_k
                    ),
                    "control_pre_slope_log_sqrt_k": float(
                        control.pre_slope_log_sqrt_k
                    ),
                }
            )
    return pd.DataFrame(rows)


def matched_change(
    pool_changes: pd.DataFrame,
    matches: pd.DataFrame,
    *,
    outcome: str,
) -> dict[str, float | int]:
    """Average treated-minus-own-matched-controls change."""

    changes = pool_changes.set_index("pool")[f"delta_{outcome}"].astype(float)
    group_rows: list[tuple[float, float, float]] = []
    for treated_pool, group in matches.groupby("treated_pool", sort=True):
        treated_change = float(changes.loc[treated_pool])
        control_change = float(changes.loc[group["control_pool"]].mean())
        group_rows.append((treated_change, control_change, treated_change - control_change))
    values = np.asarray(group_rows, dtype=float)
    return {
        "treated_mean_change": float(values[:, 0].mean()),
        "matched_control_mean_change": float(values[:, 1].mean()),
        "matched_difference": float(values[:, 2].mean()),
        "treated_pools": int(len(values)),
        "matched_control_slots": int(len(matches)),
        "unique_matched_controls": int(matches["control_pool"].nunique()),
    }


def matched_event_path(
    panel: pd.DataFrame,
    event: IncentiveEvent,
    matches: pd.DataFrame,
    *,
    outcome: str,
    window_days: int,
) -> pd.DataFrame:
    """Daily treated-minus-matched-control path around one event."""

    data = panel[
        panel["date"].between(
            event.date - pd.Timedelta(days=window_days),
            event.date + pd.Timedelta(days=window_days - 1),
        )
    ][["pool", "date", outcome]].copy()
    data["relative_day"] = (data["date"] - event.date).dt.days.astype(int)
    indexed = data.set_index(["pool", "relative_day"])[outcome]
    pre_means = (
        data[data["relative_day"].lt(0)]
        .groupby("pool", sort=False)[outcome]
        .mean()
    )
    rows: list[dict[str, object]] = []
    for relative_day in range(-window_days, window_days):
        groups: list[tuple[float, float, float]] = []
        for treated_pool, matched in matches.groupby("treated_pool", sort=True):
            key = (treated_pool, relative_day)
            if key not in indexed.index:
                continue
            control_values = [
                float(indexed.loc[(pool, relative_day)] - pre_means.loc[pool])
                for pool in matched["control_pool"]
                if (pool, relative_day) in indexed.index and pool in pre_means.index
            ]
            if not control_values or treated_pool not in pre_means.index:
                continue
            treated_value = float(indexed.loc[key] - pre_means.loc[treated_pool])
            control_value = float(np.mean(control_values))
            groups.append((treated_value, control_value, treated_value - control_value))
        if not groups:
            continue
        values = np.asarray(groups, dtype=float)
        rows.append(
            {
                "relative_day": relative_day,
                "treated_change_from_pre_mean": float(values[:, 0].mean()),
                "matched_control_change_from_pre_mean": float(values[:, 1].mean()),
                "matched_difference": float(values[:, 2].mean()),
                "treated_groups_supported": int(len(values)),
            }
        )
    return pd.DataFrame(rows)


def matched_window_change(
    panel: pd.DataFrame,
    event_date: pd.Timestamp,
    matches: pd.DataFrame,
    *,
    outcome: str,
    window_days: int,
) -> dict[str, float | int]:
    """Apply fixed matches around an alternative calendar cutoff."""

    data = panel[
        panel["date"].between(
            event_date - pd.Timedelta(days=window_days),
            event_date + pd.Timedelta(days=window_days - 1),
        )
    ].copy()
    data["relative_day"] = (data["date"] - event_date).dt.days.astype(int)
    changes: list[tuple[float, float, float]] = []
    for treated_pool, matched in matches.groupby("treated_pool", sort=True):
        treated = data[data["pool"].eq(treated_pool)]
        treated_pre = treated[treated["relative_day"].lt(0)][outcome].mean()
        treated_post = treated[treated["relative_day"].ge(0)][outcome].mean()
        control_deltas: list[float] = []
        for control_pool in matched["control_pool"]:
            control = data[data["pool"].eq(control_pool)]
            pre = control[control["relative_day"].lt(0)][outcome].mean()
            post = control[control["relative_day"].ge(0)][outcome].mean()
            if np.isfinite(pre) and np.isfinite(post):
                control_deltas.append(float(post - pre))
        if np.isfinite(treated_pre) and np.isfinite(treated_post) and control_deltas:
            treated_delta = float(treated_post - treated_pre)
            control_delta = float(np.mean(control_deltas))
            changes.append((treated_delta, control_delta, treated_delta - control_delta))
    if not changes:
        return {
            "treated_mean_change": float("nan"),
            "matched_control_mean_change": float("nan"),
            "matched_difference": float("nan"),
            "treated_groups_supported": 0,
        }
    values = np.asarray(changes, dtype=float)
    return {
        "treated_mean_change": float(values[:, 0].mean()),
        "matched_control_mean_change": float(values[:, 1].mean()),
        "matched_difference": float(values[:, 2].mean()),
        "treated_groups_supported": int(len(values)),
    }


def _sample_assignments(
    pool_ids: Sequence[str],
    *,
    treated_count: int,
    maximum_assignments: int,
    seed: int,
) -> tuple[list[tuple[str, ...]], str, int]:
    total = math.comb(len(pool_ids), treated_count)
    if total <= maximum_assignments:
        return list(itertools.combinations(pool_ids, treated_count)), "all_combinations", total
    rng = np.random.default_rng(seed)
    selected: set[tuple[str, ...]] = set()
    while len(selected) < maximum_assignments:
        assignment = tuple(sorted(rng.choice(pool_ids, treated_count, replace=False)))
        selected.add(assignment)
    return sorted(selected), "seeded_subset_without_duplicate_assignments", total


def matched_label_reference(
    summary: pd.DataFrame,
    actual_treated: Sequence[str],
    *,
    outcome: str,
    matches_per_treated: int,
    maximum_assignments: int,
    seed: int,
) -> dict[str, object]:
    """Place the matched estimate in a deterministic pseudo-label reference."""

    eligible = summary[summary["eligible"].astype(bool)].copy()
    pool_ids = tuple(sorted(eligible["pool"].astype(str)))
    assignments, sampling, total = _sample_assignments(
        pool_ids,
        treated_count=len(actual_treated),
        maximum_assignments=maximum_assignments,
        seed=seed,
    )
    actual_matches = match_pool_group(
        eligible, actual_treated, matches_per_treated=matches_per_treated
    )
    actual = float(
        matched_change(eligible, actual_matches, outcome=outcome)["matched_difference"]
    )
    placebo_statistics: list[float] = []
    for assignment in assignments:
        try:
            pseudo_matches = match_pool_group(
                eligible, assignment, matches_per_treated=matches_per_treated
            )
        except ValueError:
            continue
        placebo_statistics.append(
            float(
                matched_change(eligible, pseudo_matches, outcome=outcome)[
                    "matched_difference"
                ]
            )
        )
    reference = np.asarray(placebo_statistics, dtype=float)
    if not len(reference):
        raise ValueError("matched-label reference produced no assignments")
    p_value = (1.0 + float(np.sum(np.abs(reference) >= abs(actual)))) / (
        1.0 + len(reference)
    )
    return {
        "actual_matched_difference": actual,
        "permutation_p_two_sided": p_value,
        "reference_assignments": int(len(reference)),
        "possible_assignments": int(total),
        "assignment_sampling": sampling,
        "seed": int(seed),
        "reference_q025": float(np.quantile(reference, 0.025)),
        "reference_median": float(np.quantile(reference, 0.5)),
        "reference_q975": float(np.quantile(reference, 0.975)),
        "inference_scope": (
            "matched-label diagnostic; reward-pool selection was not random, "
            "so this is not randomization inference"
        ),
    }


def load_wbtc_route_rows(
    path: Path,
    *,
    expiry: IncentiveEvent,
    window_days: int,
    placebo_shift_days: int,
) -> pd.DataFrame:
    """Read the bounded WBTC endpoint route window needed by the reduced form."""

    dates = [expiry.date, expiry.date + pd.Timedelta(days=placebo_shift_days)]
    first = min(dates) - pd.Timedelta(days=window_days)
    last = max(dates) + pd.Timedelta(days=window_days - 1)
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='1GB'")
    try:
        return connection.execute(
            """
            SELECT
                CAST(date AS DATE) AS date,
                lower(src) AS src,
                lower(tgt) AS tgt,
                lower(candidate_address) AS candidate_address,
                candidate_type,
                candidate_symbol,
                integration_scope,
                lower(hop1_venue) AS hop1_venue,
                lower(hop2_venue) AS hop2_venue,
                route_count
            FROM read_parquet(?)
            WHERE date BETWEEN ? AND ?
              AND (lower(src) = ? OR lower(tgt) = ?)
              AND candidate_type IN ('native', 'stable')
            """,
            [str(path), first.date(), last.date(), WBTC, WBTC],
        ).fetchdf()
    finally:
        connection.close()


def prepare_wbtc_routes(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep non-vehicle WBTC endpoint pairs and identify the adjacent V2 leg."""

    required = {
        "date",
        "src",
        "tgt",
        "candidate_address",
        "candidate_type",
        "hop1_venue",
        "hop2_venue",
        "route_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"UNI expiry WBTC route input lacks columns: {missing}")
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    for column in ("src", "tgt", "candidate_address"):
        data[column] = _normalise_address(data[column])
    for column in ("hop1_venue", "hop2_venue"):
        data[column] = data[column].fillna("").astype(str).str.lower()
    data["route_count"] = pd.to_numeric(data["route_count"], errors="coerce")
    wbtc_endpoint = data["src"].eq(WBTC) ^ data["tgt"].eq(WBTC)
    data = data[wbtc_endpoint & data["route_count"].gt(0)].copy()
    data["other_endpoint"] = np.where(data["src"].eq(WBTC), data["tgt"], data["src"])
    data = data[
        ~data["other_endpoint"].isin(ALL_STABLES | {WETH, WBTC})
        & data["candidate_address"].isin(CORE_STABLES | {WETH})
    ].copy()
    data["route_family"] = np.where(
        data["candidate_address"].eq(WETH), "native", "stable"
    )
    wbtc_adjacent_venue = np.where(
        data["src"].eq(WBTC), data["hop1_venue"], data["hop2_venue"]
    )
    data["treated_wbtc_weth_leg"] = (
        data["candidate_address"].eq(WETH)
        & pd.Series(wbtc_adjacent_venue, index=data.index).eq("uniswap_v2")
    )
    data["ordered_pair"] = data["src"] + ">" + data["tgt"]
    if data.empty:
        raise ValueError("UNI expiry clean WBTC endpoint route sample is empty")
    return data.sort_values(["ordered_pair", "date"], kind="stable").reset_index(drop=True)


def wbtc_pair_support(
    routes: pd.DataFrame,
    event_date: pd.Timestamp,
    *,
    window_days: int,
    minimum_pre_routes: int,
    minimum_pre_exposure: float,
) -> pd.DataFrame:
    """Select pairs using pre-expiry contestability and treated-leg exposure."""

    data = routes[
        routes["date"].between(
            event_date - pd.Timedelta(days=window_days),
            event_date + pd.Timedelta(days=window_days - 1),
        )
    ].copy()
    data["period"] = np.where(data["date"].lt(event_date), "pre", "post")
    rows: list[dict[str, object]] = []
    for pair, group in data.groupby("ordered_pair", sort=True):
        pre = group[group["period"].eq("pre")]
        post = group[group["period"].eq("post")]
        pre_native = float(
            pre.loc[pre["route_family"].eq("native"), "route_count"].sum()
        )
        pre_stable = float(
            pre.loc[pre["route_family"].eq("stable"), "route_count"].sum()
        )
        post_native = float(
            post.loc[post["route_family"].eq("native"), "route_count"].sum()
        )
        post_stable = float(
            post.loc[post["route_family"].eq("stable"), "route_count"].sum()
        )
        pre_exposed = float(pre.loc[pre["treated_wbtc_weth_leg"], "route_count"].sum())
        post_exposed = float(post.loc[post["treated_wbtc_weth_leg"], "route_count"].sum())
        exposure = pre_exposed / pre_native if pre_native > 0 else float("nan")
        pre_total = pre_native + pre_stable
        post_total = post_native + post_stable
        rows.append(
            {
                "ordered_pair": pair,
                "src": str(group["src"].iloc[0]),
                "tgt": str(group["tgt"].iloc[0]),
                "pre_native_routes": pre_native,
                "pre_stable_routes": pre_stable,
                "post_native_routes": post_native,
                "post_stable_routes": post_stable,
                "pre_total_routes": pre_total,
                "post_total_routes": post_total,
                "pre_treated_leg_routes": pre_exposed,
                "post_treated_leg_routes": post_exposed,
                "pre_treated_leg_exposure": exposure,
                "pre_active_days": int(pre["date"].nunique()),
                "post_active_days": int(post["date"].nunique()),
                "pre_contestable": bool(
                    pre_native > 0
                    and pre_stable > 0
                    and pre_total >= minimum_pre_routes
                ),
                "selected": bool(
                    pre_native > 0
                    and pre_stable > 0
                    and pre_total >= minimum_pre_routes
                    and np.isfinite(exposure)
                    and exposure >= minimum_pre_exposure
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("ordered_pair", kind="stable").reset_index(drop=True)


def _sign_flip_p_value(changes: np.ndarray, *, draws: int, seed: int) -> float:
    usable = np.asarray(changes, dtype=float)
    usable = usable[np.isfinite(usable)]
    if not len(usable):
        return float("nan")
    observed = abs(float(usable.mean()))
    total = 2 ** len(usable)
    if total <= draws:
        statistics = [
            abs(float(np.mean(usable * np.asarray(signs, dtype=float))))
            for signs in itertools.product((-1.0, 1.0), repeat=len(usable))
        ]
    else:
        rng = np.random.default_rng(seed)
        signs = rng.choice((-1.0, 1.0), size=(draws, len(usable)))
        statistics = np.abs((signs * usable).mean(axis=1)).tolist()
    return (1.0 + float(np.sum(np.asarray(statistics) >= observed))) / (
        1.0 + len(statistics)
    )


def wbtc_route_response(
    pair_support: pd.DataFrame,
    *,
    sign_flip_draws: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Summarise stable-versus-native use in the fixed pre-selected pair set."""

    selected = pair_support[pair_support["selected"].astype(bool)].copy()
    if selected.empty:
        raise ValueError("UNI expiry WBTC route sample has no pre-selected pairs")
    pre_native = float(selected["pre_native_routes"].sum())
    pre_stable = float(selected["pre_stable_routes"].sum())
    post_native = float(selected["post_native_routes"].sum())
    post_stable = float(selected["post_stable_routes"].sum())
    if pre_native + pre_stable <= 0 or post_native + post_stable <= 0:
        raise ValueError("UNI expiry WBTC route sample lacks pre- or post-expiry routes")
    pre_share = pre_stable / (pre_native + pre_stable)
    post_share = post_stable / (post_native + post_stable)
    same_active = selected[selected["post_total_routes"].gt(0)].copy()
    same_active["pre_stable_share"] = same_active["pre_stable_routes"] / same_active[
        "pre_total_routes"
    ]
    same_active["post_stable_share"] = same_active["post_stable_routes"] / same_active[
        "post_total_routes"
    ]
    same_active["stable_share_change"] = (
        same_active["post_stable_share"] - same_active["pre_stable_share"]
    )
    post_exposed = float(selected["post_treated_leg_routes"].sum())
    pre_exposed = float(selected["pre_treated_leg_routes"].sum())
    pre_exposed_share = pre_exposed / pre_native if pre_native > 0 else float("nan")
    post_exposed_share = post_exposed / post_native if post_native > 0 else float("nan")
    rows = pd.DataFrame(
        [
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "wbtc_expiry_route_response",
                "estimate": "route_weighted_stable_share_change",
                "value": post_share - pre_share,
                "pre_value": pre_share,
                "post_value": post_share,
                "unit": "share_point",
                "ordered_pairs": int(len(selected)),
                "scope": "fixed pre-expiry contestable and treated-leg-exposed WBTC endpoint pairs",
            },
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "wbtc_expiry_route_response",
                "estimate": "equal_pair_stable_share_change",
                "value": float(same_active["stable_share_change"].mean()),
                "pre_value": float(same_active["pre_stable_share"].mean()),
                "post_value": float(same_active["post_stable_share"].mean()),
                "unit": "share_point",
                "ordered_pairs": int(len(same_active)),
                "scope": "pre-selected WBTC endpoint pairs active after expiry",
            },
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "wbtc_expiry_route_response",
                "estimate": "native_route_treated_leg_share_change",
                "value": post_exposed_share - pre_exposed_share,
                "pre_value": pre_exposed_share,
                "post_value": post_exposed_share,
                "unit": "share_point",
                "ordered_pairs": int(len(selected)),
                "scope": "native routes in the fixed pre-selected WBTC endpoint-pair set",
            },
        ]
    )
    diagnostics = {
        "selected_pairs": int(len(selected)),
        "post_active_pairs": int(len(same_active)),
        "pre_routes": int(pre_native + pre_stable),
        "post_routes": int(post_native + post_stable),
        "pre_native_routes": int(pre_native),
        "pre_stable_routes": int(pre_stable),
        "post_native_routes": int(post_native),
        "post_stable_routes": int(post_stable),
        "median_pre_treated_leg_exposure": float(
            selected["pre_treated_leg_exposure"].median()
        ),
        "route_weighted_stable_share_change": post_share - pre_share,
        "equal_pair_stable_share_change": float(
            same_active["stable_share_change"].mean()
        ),
        "sign_flip_p_two_sided": _sign_flip_p_value(
            same_active["stable_share_change"].to_numpy(),
            draws=sign_flip_draws,
            seed=seed,
        ),
        "post_treated_leg_routes_if_available": int(post_exposed),
        "pre_treated_leg_share": pre_exposed_share,
        "post_treated_leg_share": post_exposed_share,
    }
    return rows, diagnostics


def wbtc_daily_path(
    routes: pd.DataFrame,
    selected_pairs: Sequence[str],
    event_date: pd.Timestamp,
    *,
    window_days: int,
) -> pd.DataFrame:
    """Daily route-weighted stable share for a pre-selected pair set."""

    data = routes[
        routes["ordered_pair"].isin(selected_pairs)
        & routes["date"].between(
            event_date - pd.Timedelta(days=window_days),
            event_date + pd.Timedelta(days=window_days - 1),
        )
    ].copy()
    if data.empty:
        return pd.DataFrame(
            columns=[
                "relative_day",
                "native",
                "stable",
                "total_routes",
                "stable_route_share",
            ]
        )
    data["relative_day"] = (data["date"] - event_date).dt.days.astype(int)
    grouped = (
        data.groupby(["relative_day", "route_family"], as_index=False)["route_count"]
        .sum()
        .pivot(index="relative_day", columns="route_family", values="route_count")
        .fillna(0.0)
        .reset_index()
    )
    for family in ("native", "stable"):
        if family not in grouped:
            grouped[family] = 0.0
    grouped["total_routes"] = grouped["native"] + grouped["stable"]
    grouped = grouped[grouped["total_routes"].gt(0)].copy()
    grouped["stable_route_share"] = grouped["stable"] / grouped["total_routes"]
    return grouped.sort_values("relative_day", kind="stable").reset_index(drop=True)


def _event_metadata_rows() -> pd.DataFrame:
    rows = []
    pool_list = ",".join(REWARDED_POOL_ADDRESSES)
    for event in EVENTS:
        rows.append(
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "event_metadata",
                "event": event.event,
                "event_date": event.date.date().isoformat(),
                "event_timestamp_utc": event.timestamp_utc,
                "expected_liquidity_direction": event.expected_liquidity_direction,
                "interpretation": event.interpretation,
                "treated_pools": pool_list,
                "official_source": OFFICIAL_SOURCE,
                "trader_fee_change": "none",
                "reward_rule": "5 million UNI allocated to each named pool over the fixed interval",
                "design_caveat": (
                    "start coincides with the UNI launch and contemporaneous liquidity migration; "
                    "use mainly as the signed reversal of expiry"
                    if event.event == "reward_start"
                    else "expiry was scheduled, but targeted pool selection and anticipation remain"
                ),
            }
        )
    return pd.DataFrame(rows)


def analyse_pool_events(
    panel: pd.DataFrame,
    *,
    window_days: int,
    minimum_support_share: float,
    minimum_pre_capital_usd: float,
    matches_per_treated: int,
    placebo_shift_days: int,
    maximum_assignments: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run both event first stages and return result and support rows."""

    results: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    for event_index, event in enumerate(EVENTS):
        summary = event_pool_summary(
            panel,
            event,
            window_days=window_days,
            minimum_support_share=minimum_support_share,
            minimum_pre_capital_usd=minimum_pre_capital_usd,
        )
        eligible = summary[summary["eligible"].astype(bool)]
        treated_supported = int(
            eligible["pool"].isin(REWARDED_POOL_ADDRESSES).sum()
        )
        controls = int((~eligible["pool"].isin(REWARDED_POOL_ADDRESSES)).sum())
        base_support = {
            "analysis_status": ANALYSIS_STATUS,
            "record_type": "pool_risk_set",
            "event": event.event,
            "event_date": event.date.date().isoformat(),
            "window_days_each_side": window_days,
            "minimum_daily_support_share": minimum_support_share,
            "minimum_pre_capital_usd": minimum_pre_capital_usd,
            "weth_pools_observed": int(len(summary)),
            "eligible_pools": int(len(eligible)),
            "ineligible_pools": int(len(summary) - len(eligible)),
            "treated_pools_required": len(REWARDED_POOLS),
            "treated_pools_supported": treated_supported,
            "eligible_control_pools": controls,
            "control_rule": (
                "untreated Uniswap V2 WETH pool; positive validated reserves and capital; "
                "minimum window coverage and pre-event mean capital"
            ),
            "match_rule": (
                "nearest controls in standardized pre-event mean log capital and "
                "pre-event log-sqrt-k slope; reuse across treated pools allowed"
            ),
        }
        support_rows.append(base_support)
        if treated_supported != len(REWARDED_POOLS) or controls < matches_per_treated:
            support_rows.append(
                {
                    "analysis_status": ANALYSIS_STATUS,
                    "record_type": "pool_stop_go",
                    "event": event.event,
                    "decision": "stop_insufficient_pool_support",
                    "reason": "not all treated pools or too few controls pass the stated risk-set rules",
                }
            )
            continue
        matches = match_pool_group(
            summary,
            REWARDED_POOL_ADDRESSES,
            matches_per_treated=matches_per_treated,
        )
        match_support = matches.copy()
        match_support.insert(0, "analysis_status", ANALYSIS_STATUS)
        match_support.insert(1, "record_type", "pool_match")
        match_support.insert(2, "event", event.event)
        support_rows.extend(match_support.to_dict("records"))
        quantity_gate: dict[str, object] | None = None
        for outcome_index, (outcome, description) in enumerate(POOL_OUTCOMES):
            estimate = matched_change(summary, matches, outcome=outcome)
            reference = matched_label_reference(
                summary,
                REWARDED_POOL_ADDRESSES,
                outcome=outcome,
                matches_per_treated=matches_per_treated,
                maximum_assignments=maximum_assignments,
                seed=seed + 100 * event_index + outcome_index,
            )
            path = matched_event_path(
                panel,
                event,
                matches,
                outcome=outcome,
                window_days=window_days,
            )
            pre_path = path[path["relative_day"].lt(0)]
            pretrend = _slope(pre_path["relative_day"], pre_path["matched_difference"])
            placebo_date = event.date + pd.Timedelta(days=placebo_shift_days)
            placebo = matched_window_change(
                panel,
                placebo_date,
                matches,
                outcome=outcome,
                window_days=window_days,
            )
            result = {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "pool_first_stage",
                "event": event.event,
                "event_date": event.date.date().isoformat(),
                "outcome": outcome,
                "outcome_description": description,
                "unit": "log_point",
                **estimate,
                **reference,
                "pretrend_daily_slope": pretrend,
                "calendar_placebo_date": placebo_date.date().isoformat(),
                "calendar_placebo_matched_difference": placebo["matched_difference"],
                "calendar_placebo_supported_treated_groups": placebo[
                    "treated_groups_supported"
                ],
                "interpretation_scope": (
                    "matched pool response around a predetermined reward date; "
                    "targeted pool selection and concurrent market changes remain"
                ),
            }
            results.append(pd.DataFrame([result]))
            path = path.copy()
            path.insert(0, "analysis_status", ANALYSIS_STATUS)
            path.insert(1, "record_type", "pool_event_time")
            path.insert(2, "event", event.event)
            path.insert(3, "outcome", outcome)
            results.append(path)
            if outcome == "log_sqrt_k":
                effect = float(estimate["matched_difference"])
                signed_effect = event.expected_liquidity_direction * effect
                coverage_pass = treated_supported == len(REWARDED_POOLS) and controls >= 20
                relevance_pass = signed_effect >= 0.10 and float(
                    reference["permutation_p_two_sided"]
                ) <= 0.10
                timing_pass = (
                    np.isfinite(placebo["matched_difference"])
                    and abs(float(placebo["matched_difference"])) < abs(effect)
                    and np.isfinite(pretrend)
                    and abs(float(pretrend) * window_days) < abs(effect)
                )
                quantity_gate = {
                    "analysis_status": ANALYSIS_STATUS,
                    "record_type": "pool_stop_go",
                    "event": event.event,
                    "decision": (
                        "go_quantity_liquidity_first_stage_for_further_design"
                        if coverage_pass and relevance_pass and timing_pass
                        else "stop_before_route_interpretation"
                    ),
                    "coverage_pass": coverage_pass,
                    "signed_relevance_pass": relevance_pass,
                    "timing_placebo_pass": timing_pass,
                    "minimum_abs_signed_effect_log_points": 0.10,
                    "maximum_reference_p": 0.10,
                    "scope": (
                        "sqrt-k is a quantity-based pool stock rather than a decoded "
                        "provider-flow measure; a go decision warrants the narrow "
                        "follow-up only and does not "
                        "convert the matched contrast into a causal estimate"
                    ),
                }
        if quantity_gate is not None:
            support_rows.append(quantity_gate)
    if not results:
        return pd.DataFrame(), pd.DataFrame(support_rows)
    return pd.concat(results, ignore_index=True, sort=False), pd.DataFrame(support_rows)


def analyse_wbtc_expiry_routes(
    routes: pd.DataFrame,
    *,
    window_days: int,
    minimum_pre_routes: int,
    minimum_pre_exposure: float,
    placebo_shift_days: int,
    sign_flip_draws: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the narrow WBTC endpoint reduced form and its promotion gate."""

    expiry = next(event for event in EVENTS if event.event == "reward_expiry")
    support = wbtc_pair_support(
        routes,
        expiry.date,
        window_days=window_days,
        minimum_pre_routes=minimum_pre_routes,
        minimum_pre_exposure=minimum_pre_exposure,
    )
    selected = support[support["selected"].astype(bool)]
    route_rows, diagnostics = wbtc_route_response(
        support,
        sign_flip_draws=sign_flip_draws,
        seed=seed,
    )
    selected_pairs = tuple(selected["ordered_pair"].astype(str))
    path = wbtc_daily_path(
        routes,
        selected_pairs,
        expiry.date,
        window_days=window_days,
    )
    path.insert(0, "analysis_status", ANALYSIS_STATUS)
    path.insert(1, "record_type", "wbtc_expiry_route_event_time")
    placebo_date = expiry.date + pd.Timedelta(days=placebo_shift_days)
    placebo_path = wbtc_daily_path(
        routes,
        selected_pairs,
        placebo_date,
        window_days=window_days,
    )
    placebo_pre = placebo_path[placebo_path["relative_day"].lt(0)]
    placebo_post = placebo_path[placebo_path["relative_day"].ge(0)]
    placebo_change = (
        float(placebo_post["stable"].sum())
        / float(placebo_post["total_routes"].sum())
        - float(placebo_pre["stable"].sum())
        / float(placebo_pre["total_routes"].sum())
        if not placebo_pre.empty
        and not placebo_post.empty
        and placebo_pre["total_routes"].sum() > 0
        and placebo_post["total_routes"].sum() > 0
        else float("nan")
    )
    pre_path = path[path["relative_day"].lt(0)]
    pretrend = _slope(pre_path["relative_day"], pre_path["stable_route_share"])
    route_rows["calendar_placebo_date"] = placebo_date.date().isoformat()
    route_rows["calendar_placebo_stable_share_change"] = placebo_change
    route_rows["pretrend_daily_stable_share_slope"] = pretrend
    route_rows["interpretation_scope"] = (
        "narrow fixed-support before/after reduced form; no untreated route control, "
        "and concurrent WBTC demand can affect the estimate"
    )
    support_pass = bool(
        diagnostics["selected_pairs"] >= 20
        and diagnostics["post_active_pairs"] >= 15
        and diagnostics["pre_routes"] >= 250
        and diagnostics["post_routes"] >= 250
        and diagnostics["median_pre_treated_leg_exposure"] >= minimum_pre_exposure
    )
    timing_pass = bool(
        np.isfinite(placebo_change)
        and abs(float(diagnostics["route_weighted_stable_share_change"]))
        > abs(placebo_change)
    )
    signal_pass = bool(
        np.isfinite(diagnostics["sign_flip_p_two_sided"])
        and float(diagnostics["sign_flip_p_two_sided"]) <= 0.10
    )
    support_rows = pd.DataFrame(
        [
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "wbtc_expiry_route_support",
                "event": "reward_expiry",
                "event_date": expiry.date.date().isoformat(),
                "window_days_each_side": window_days,
                "minimum_pre_routes": minimum_pre_routes,
                "minimum_pre_treated_leg_exposure": minimum_pre_exposure,
                "wbtc_endpoint_pairs_observed": int(len(support)),
                "pre_contestable_pairs": int(support["pre_contestable"].sum()),
                **diagnostics,
                "pair_rule": (
                    "ordered WBTC endpoint pair with a non-WETH/non-core-stable other "
                    "endpoint, both vehicle families used pre-expiry, and the stated "
                    "minimum pre-expiry route count and treated-leg exposure"
                ),
            },
            {
                "analysis_status": ANALYSIS_STATUS,
                "record_type": "wbtc_expiry_route_stop_go",
                "event": "reward_expiry",
                "decision": (
                    "go_report_narrow_reduced_form_only"
                    if support_pass and timing_pass and signal_pass
                    else "stop_no_distinct_narrow_route_response"
                ),
                "support_pass": support_pass,
                "calendar_placebo_pass": timing_pass,
                "pair_sign_flip_pass": signal_pass,
                "maximum_sign_flip_p": 0.10,
                "scope": (
                    "even a go result remains a narrow reduced form and must not be "
                    "described as general capital-to-routing causality"
                ),
            },
        ]
    )
    return pd.concat([route_rows, path], ignore_index=True, sort=False), support_rows


def run(
    *,
    pool_path: Path = POOL_CAPITAL,
    route_path: Path = ROUTE_CHOICES,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
    window_days: int = 14,
    minimum_support_share: float = 0.80,
    minimum_pre_capital_usd: float = 1_000_000.0,
    matches_per_treated: int = 5,
    minimum_wbtc_pre_routes: int = 5,
    minimum_wbtc_pre_exposure: float = 0.80,
    placebo_shift_days: int = -42,
    maximum_assignments: int = 1_999,
    seed: int = 20_201_117,
) -> int:
    if window_days < 5:
        raise ValueError("UNI incentive event window must be at least five days per side")
    if not 0 < minimum_support_share <= 1:
        raise ValueError("minimum support share must lie in (0, 1]")
    if matches_per_treated < 1:
        raise ValueError("matches per treated pool must be positive")
    if maximum_assignments < 99:
        raise ValueError("matched-label reference requires at least 99 assignments")
    if abs(placebo_shift_days) < 2 * window_days:
        raise ValueError("calendar placebo window must not overlap the event window")
    if minimum_wbtc_pre_routes < 1:
        raise ValueError("minimum WBTC pre-expiry route count must be positive")
    if not 0 < minimum_wbtc_pre_exposure <= 1:
        raise ValueError("minimum WBTC treated-leg exposure must lie in (0, 1]")
    pool_raw = load_pool_rows(
        pool_path,
        window_days=window_days,
        placebo_shift_days=placebo_shift_days,
    )
    pool_panel = prepare_pool_panel(pool_raw)
    pool_results, pool_support = analyse_pool_events(
        pool_panel,
        window_days=window_days,
        minimum_support_share=minimum_support_share,
        minimum_pre_capital_usd=minimum_pre_capital_usd,
        matches_per_treated=matches_per_treated,
        placebo_shift_days=placebo_shift_days,
        maximum_assignments=maximum_assignments,
        seed=seed,
    )
    expiry = next(event for event in EVENTS if event.event == "reward_expiry")
    route_raw = load_wbtc_route_rows(
        route_path,
        expiry=expiry,
        window_days=window_days,
        placebo_shift_days=placebo_shift_days,
    )
    routes = prepare_wbtc_routes(route_raw)
    route_results, route_support = analyse_wbtc_expiry_routes(
        routes,
        window_days=window_days,
        minimum_pre_routes=minimum_wbtc_pre_routes,
        minimum_pre_exposure=minimum_wbtc_pre_exposure,
        placebo_shift_days=placebo_shift_days,
        sign_flip_draws=maximum_assignments,
        seed=seed + 1_000,
    )
    result_frames = [_event_metadata_rows(), pool_results, route_results]
    results = pd.concat(
        [frame for frame in result_frames if not frame.empty],
        ignore_index=True,
        sort=False,
    )
    supports = pd.concat([pool_support, route_support], ignore_index=True, sort=False)
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(supports, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results)} UNI incentive result rows and "
        f"{len(supports)} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--route-choices", type=Path, default=ROUTE_CHOICES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--minimum-support-share", type=float, default=0.80)
    parser.add_argument("--minimum-pre-capital-usd", type=float, default=1_000_000.0)
    parser.add_argument("--matches-per-treated", type=int, default=5)
    parser.add_argument("--minimum-wbtc-pre-routes", type=int, default=5)
    parser.add_argument("--minimum-wbtc-pre-exposure", type=float, default=0.80)
    parser.add_argument("--placebo-shift-days", type=int, default=-42)
    parser.add_argument("--maximum-assignments", type=int, default=1_999)
    parser.add_argument("--seed", type=int, default=20_201_117)
    args = parser.parse_args()
    return run(
        pool_path=args.pool_capital,
        route_path=args.route_choices,
        output_path=args.output,
        support_path=args.support,
        window_days=args.window_days,
        minimum_support_share=args.minimum_support_share,
        minimum_pre_capital_usd=args.minimum_pre_capital_usd,
        matches_per_treated=args.matches_per_treated,
        minimum_wbtc_pre_routes=args.minimum_wbtc_pre_routes,
        minimum_wbtc_pre_exposure=args.minimum_wbtc_pre_exposure,
        placebo_shift_days=args.placebo_shift_days,
        maximum_assignments=args.maximum_assignments,
        seed=args.seed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
