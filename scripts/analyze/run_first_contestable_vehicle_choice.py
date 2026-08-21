#!/usr/bin/env python3
"""Estimate first vehicle choice after both vehicle families become feasible.

This is distinct from original endpoint-pair entry.  The retained monthly mode
follows entrants through the fifteenth-of-month exact-state panel.  The separate
four-per-month mode replays days 1, 8, 15, and 22 directly, quotes each observed
route before execution, and stops following a pair after its first sampled date
with both a WETH path and a DAI/USDC/USDT path.  Every eligible route on that
first sampled contest date enters the route-level choice models, with
endpoint-pair and date clustered inference.

The result asks two questions.  First, do exact output and prior-calendar
weak-leg V2 capital explain stablecoin selection once a two-family opportunity
set exists?  Second, does the vehicle family used at pair entry retain the route
when that first genuine contest arrives?  Entry-to-contestability lags and both
route- and pair-weighted retention rates travel with the estimates.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import PRIMARY_REPO_ROOT, REPO_ROOT
from ddvc.pricing.tick_replay import TickReplayState, load_tick_day_events
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_contestable_vehicle_choice import (
    MAX_LINEAR_ADVANTAGE_BPS,
    QUOTED_STABLES,
    QUOTED_VEHICLES,
    QUOTED_LEG_MAX_PRICE_IMPACT,
    WETH,
)
from scripts.analyze.run_entry_day_vehicle_choice import (
    END,
    LOCK as EXACT_REPLAY_LOCK,
    MIN_ROUTE_INPUT_USD,
    PAIR_SUPPORT,
    POOL_CAPITAL,
    PRIMARY_RAW_ROOT,
    START,
    TICK_START,
    _fit_entry_model,
    attach_entry_capital,
    load_material_entries,
    score_entry_day,
)


DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD = 5_000.0
PRIMARY_DATA_DIR = PRIMARY_REPO_ROOT / "data"
FRONTIER = PRIMARY_DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
PANEL = REPO_ROOT / "data/processed/first_contestable_vehicle_choice.parquet"
OUTPUT = REPO_ROOT / "output/exhibits/first_contestable_vehicle_choice.jsonl"
SUPPORT = REPO_ROOT / "output/exhibits/first_contestable_vehicle_choice_support.jsonl"
FOUR_PER_MONTH_PANEL = (
    REPO_ROOT
    / "data/processed/first_contestable_vehicle_choice_four_per_month.parquet"
)
FOUR_PER_MONTH_OUTPUT = (
    REPO_ROOT
    / "output/exhibits/first_contestable_vehicle_choice_four_per_month.jsonl"
)
FOUR_PER_MONTH_SUPPORT = (
    REPO_ROOT
    / "output/exhibits/first_contestable_vehicle_choice_four_per_month_support.jsonl"
)
FOUR_PER_MONTH_DAYS = (1, 8, 15, 22)
FOUR_PER_MONTH_CALENDAR = "fixed_days_1_8_15_22"
FOUR_PER_MONTH_MAXIMUM_GAP_DAYS = 10
CODE_SOURCES = [
    "scripts/analyze/run_first_contestable_vehicle_choice.py",
    "scripts/analyze/run_entry_day_vehicle_choice.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/exact_vehicle_frontier_monthly.parquet",
    "data/processed/pool_capital_daily.parquet",
]
FOUR_PER_MONTH_INPUTS = [
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/pool_capital_daily.parquet",
    "data/unified/*.parquet",
    "data/raw/thegraph/uniswap_v2/*",
    "data/raw/thegraph/sushiswap_v2/*",
    "data/raw/thegraph/uniswap_v3/*",
]


def first_contestable_routes(
    frontier_path: Path,
    entries: pd.DataFrame,
) -> pd.DataFrame:
    """Return all exact routes on each pair's first sampled contestable date."""

    connection = duckdb.connect()
    try:
        connection.register("material_entries", entries)
        panel = connection.execute(
            """
            WITH exact_supported AS (
                SELECT
                    strptime(f.day, '%Y%m%d')::DATE AS exact_date,
                    f.day,
                    f.route_id,
                    lower(f.token_in) AS token_in,
                    lower(f.token_out) AS token_out,
                    lower(f.chosen_vehicle) AS chosen_vehicle,
                    f.chosen_vehicle_type,
                    f.input_usd,
                    f.output_usd,
                    f.within_20pct,
                    f.chosen_max_price_impact,
                    f.vehicle_families_contestable,
                    f.stable_minus_native_bps,
                    f.native_public_out,
                    lower(f.native_public_vehicle) AS native_public_vehicle,
                    f.native_public_venues,
                    f.stable_public_out,
                    lower(f.stable_public_vehicle) AS stable_public_vehicle,
                    f.stable_public_venues
                FROM read_parquet(?) f
                WHERE f.within_20pct
                  AND f.input_usd >= ?
                  AND f.output_usd > 0
                  AND f.chosen_max_price_impact <= ?
                  AND f.vehicle_families_contestable
                  AND f.native_public_out > 0
                  AND f.stable_public_out > 0
                  AND lower(f.native_public_vehicle) = ?
                  AND lower(f.stable_public_vehicle) IN (?, ?, ?)
                  AND lower(f.chosen_vehicle) IN (?, ?, ?, ?)
                  AND f.chosen_vehicle_type IN ('native', 'stable')
            ),
            joined AS (
                SELECT
                    e.day AS entry_day,
                    e.entry_date,
                    e.token_in,
                    e.token_out,
                    e.ordered_pair,
                    e.entry_primary_routes,
                    e.entry_native_routes,
                    e.entry_stable_routes,
                    e.entry_stable_share,
                    e.entry_stable,
                    e.entry_tie,
                    e.entry_exclusive,
                    e.entry_mixed,
                    e.entry_coherent_routes,
                    e.entry_coherent_value_usd,
                    x.exact_date,
                    x.day,
                    x.route_id,
                    x.chosen_vehicle,
                    x.chosen_vehicle_type,
                    x.input_usd,
                    x.output_usd,
                    x.within_20pct,
                    x.chosen_max_price_impact,
                    x.vehicle_families_contestable,
                    x.stable_minus_native_bps,
                    x.native_public_out,
                    x.native_public_vehicle,
                    x.native_public_venues,
                    x.stable_public_out,
                    x.stable_public_vehicle,
                    x.stable_public_venues,
                    min(x.exact_date) OVER (
                        PARTITION BY x.token_in, x.token_out
                    ) AS first_contestable_date
                FROM exact_supported x
                JOIN material_entries e
                  ON x.token_in = e.token_in
                 AND x.token_out = e.token_out
                WHERE x.exact_date >= e.entry_date
            )
            SELECT *
            FROM joined
            WHERE exact_date = first_contestable_date
            ORDER BY exact_date, token_in, token_out, route_id
            """,
            [
                str(frontier_path),
                MIN_ROUTE_INPUT_USD,
                QUOTED_LEG_MAX_PRICE_IMPACT,
                WETH,
                *sorted(QUOTED_STABLES),
                *sorted(QUOTED_VEHICLES),
            ],
        ).fetchdf()
    finally:
        connection.close()
    if panel.empty:
        raise ValueError("material entrants have no sampled exact contestable date")
    if panel["route_id"].duplicated().any():
        raise ValueError("first-contestable panel contains duplicated route ids")
    panel["ordered_pair"] = (
        panel["token_in"].astype(str) + ">" + panel["token_out"].astype(str)
    )
    panel["route_scope"] = (
        panel["native_public_venues"].astype(str)
        + "||"
        + panel["stable_public_venues"].astype(str)
    )
    panel["chosen_stable"] = panel["chosen_vehicle_type"].eq("stable").astype(float)
    panel["entry_to_contestability_days"] = (
        pd.to_datetime(panel["first_contestable_date"])
        - pd.to_datetime(panel["entry_date"])
    ).dt.days
    panel["entry_vehicle_retained"] = np.where(
        panel["entry_stable"].notna(),
        panel["chosen_stable"].eq(panel["entry_stable"]).astype(float),
        np.nan,
    )
    return panel.reset_index(drop=True)


def four_per_month_days(
    start: str = START,
    end: str = END,
) -> list[str]:
    """Return the fixed 1/8/15/22 calendar inside the inclusive bounds."""

    lo = pd.to_datetime(start, format="%Y%m%d")
    hi = pd.to_datetime(end, format="%Y%m%d")
    if hi < lo:
        raise ValueError("four-per-month calendar ends before it starts")
    calendar = pd.date_range(lo, hi, freq="D")
    return [
        observed.strftime("%Y%m%d")
        for observed in calendar
        if observed.day in FOUR_PER_MONTH_DAYS
    ]


def four_per_month_schedule(
    entries: pd.DataFrame,
    pair_support_path: Path,
    *,
    start: str = START,
    end: str = END,
) -> pd.DataFrame:
    """Return active entrant pairs on the fixed four-date sampling grid."""

    if entries.empty:
        raise ValueError("four-per-month entry cohort is empty")
    connection = duckdb.connect()
    try:
        connection.register("material_entries", entries)
        schedule = connection.execute(
            """
            SELECT
                strftime(CAST(s.date AS DATE), '%Y%m%d') AS day,
                e.day AS entry_day,
                e.entry_date,
                e.token_in,
                e.token_out,
                e.ordered_pair,
                e.entry_primary_routes,
                e.entry_native_routes,
                e.entry_stable_routes,
                e.entry_stable_share,
                e.entry_stable,
                e.entry_tie,
                e.entry_exclusive,
                e.entry_mixed,
                e.entry_coherent_routes,
                e.entry_coherent_value_usd,
                s.primary_choice_route_count::DOUBLE AS sampled_primary_routes,
                (
                    s.native_within_20pct_routes
                    + s.stable_within_20pct_routes
                )::DOUBLE AS sampled_coherent_routes,
                (
                    s.native_within_20pct_value_usd
                    + s.stable_within_20pct_value_usd
                )::DOUBLE AS sampled_coherent_value_usd
            FROM read_parquet(?) s
            JOIN material_entries e
              ON lower(s.src) = e.token_in
             AND lower(s.tgt) = e.token_out
            WHERE s.primary_choice_route_count > 0
              AND CAST(s.date AS DATE) >= e.entry_date
              AND CAST(s.date AS DATE)
                    BETWEEN strptime(?, '%Y%m%d') AND strptime(?, '%Y%m%d')
              AND day(CAST(s.date AS DATE)) IN (?, ?, ?, ?)
            ORDER BY s.date, e.token_in, e.token_out
            """,
            [str(pair_support_path), start, end, *FOUR_PER_MONTH_DAYS],
        ).fetchdf()
    finally:
        connection.close()
    if schedule.empty:
        raise ValueError("material entrants have no active four-per-month dates")
    keys = ["day", "token_in", "token_out"]
    if schedule.duplicated(keys).any():
        raise ValueError("four-per-month schedule duplicates a pair-date")
    sampled_days = pd.to_numeric(schedule["day"].str[-2:], errors="raise")
    if not sampled_days.isin(FOUR_PER_MONTH_DAYS).all():
        raise ValueError("four-per-month schedule escaped its fixed calendar")
    if (
        pd.to_datetime(schedule["day"], format="%Y%m%d")
        < pd.to_datetime(schedule["entry_date"])
    ).any():
        raise ValueError("four-per-month schedule precedes pair entry")
    return schedule.reset_index(drop=True)


def replay_four_per_month_schedule(
    schedule: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay exact state and retain each pair's earliest sampled contest date."""

    if schedule.empty:
        raise ValueError("four-per-month replay schedule is empty")
    selected_days = sorted(schedule["day"].astype(str).unique())
    by_day = {
        day: frame.copy()
        for day, frame in schedule.groupby("day", sort=True)
    }
    unresolved = set(
        zip(
            schedule["token_in"].astype(str),
            schedule["token_out"].astype(str),
            strict=True,
        )
    )
    replay = TickReplayState()
    replay_start = min(selected_days[0], TICK_START)
    calendar = pd.date_range(
        pd.to_datetime(replay_start, format="%Y%m%d"),
        pd.to_datetime(selected_days[-1], format="%Y%m%d"),
        freq="D",
    )
    all_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    started = perf_counter()
    for index, observed in enumerate(calendar, 1):
        day = observed.strftime("%Y%m%d")
        sampled = by_day.get(day)
        current = None
        if sampled is not None and unresolved:
            pair_keys = list(
                zip(
                    sampled["token_in"].astype(str),
                    sampled["token_out"].astype(str),
                    strict=True,
                )
            )
            current = sampled.loc[
                [key in unresolved for key in pair_keys]
            ].copy()
        if current is not None and not current.empty:
            unresolved_before = len(unresolved)
            rows, support = score_entry_day(day, current, replay)
            first_pairs = {
                (str(row["token_in"]), str(row["token_out"]))
                for row in rows
            }
            if first_pairs - unresolved:
                raise ValueError("exact replay returned an already resolved pair")
            all_rows.extend(rows)
            unresolved.difference_update(first_pairs)
            support_rows.append(
                {
                    **support,
                    "sampling_calendar": FOUR_PER_MONTH_CALENDAR,
                    "scheduled_pairs": int(len(sampled)),
                    "unresolved_pairs_scored": int(len(current)),
                    "unresolved_pairs_before": int(unresolved_before),
                    "first_contestable_pairs": int(len(first_pairs)),
                    "unresolved_pairs_after": int(len(unresolved)),
                }
            )
            print(
                f"{day}: unresolved={unresolved_before:,} "
                f"pairs={len(current):,} first-contests={len(first_pairs):,}",
                flush=True,
            )
        elif day >= TICK_START:
            replay.apply_all(
                load_tick_day_events(
                    None,
                    day,
                    venues=("uniswap_v3",),
                    raw_root=PRIMARY_RAW_ROOT,
                )
            )
        if not unresolved:
            break
        if index % 180 == 0:
            elapsed = perf_counter() - started
            print(
                f"replayed through {day}; elapsed={elapsed / 60:.1f} minutes",
                flush=True,
            )
    panel = pd.DataFrame(all_rows)
    support = pd.DataFrame(support_rows)
    if panel.empty:
        raise ValueError("four-per-month replay found no exact contestable routes")
    if panel["route_id"].duplicated().any():
        raise ValueError("four-per-month replay duplicates route ids")
    pair_dates = panel.groupby(["token_in", "token_out"])["day"].nunique()
    if pair_dates.gt(1).any():
        raise ValueError("four-per-month replay retained later contest dates")
    return panel.reset_index(drop=True), support.reset_index(drop=True)


def prepare_four_per_month_panel(
    exact: pd.DataFrame,
    entries: pd.DataFrame,
) -> pd.DataFrame:
    """Attach entry identity and common first-contest fields to exact rows."""

    metadata = entries[
        [
            "day",
            "token_in",
            "token_out",
            "entry_stable",
            "entry_tie",
            "entry_exclusive",
            "entry_mixed",
        ]
    ].rename(columns={"day": "entry_day"})
    data = exact.drop(
        columns=[
            column
            for column in (
                "entry_day",
                "entry_stable",
                "entry_tie",
                "entry_exclusive",
                "entry_mixed",
            )
            if column in exact
        ]
    ).merge(
        metadata,
        on=["token_in", "token_out"],
        how="left",
        validate="many_to_one",
    )
    if data["entry_day"].isna().any():
        raise ValueError("four-per-month panel misses entry metadata")
    data["exact_date"] = pd.to_datetime(data["day"], format="%Y%m%d")
    data["first_contestable_date"] = data["exact_date"]
    data["ordered_pair"] = (
        data["token_in"].astype(str) + ">" + data["token_out"].astype(str)
    )
    data["route_scope"] = (
        data["native_public_venues"].astype(str)
        + "||"
        + data["stable_public_venues"].astype(str)
    )
    data["chosen_stable"] = data["chosen_vehicle_type"].eq("stable").astype(float)
    data["entry_to_contestability_days"] = (
        data["exact_date"] - pd.to_datetime(data["entry_date"])
    ).dt.days
    data["entry_vehicle_retained"] = np.where(
        data["entry_stable"].notna(),
        data["chosen_stable"].eq(data["entry_stable"]).astype(float),
        np.nan,
    )
    data["sampling_calendar"] = FOUR_PER_MONTH_CALENDAR
    data["fixed_sample_days"] = ",".join(map(str, FOUR_PER_MONTH_DAYS))
    data["maximum_sampling_gap_days"] = FOUR_PER_MONTH_MAXIMUM_GAP_DAYS
    return data.sort_values(
        ["day", "token_in", "token_out", "route_id"], kind="stable"
    ).reset_index(drop=True)


def attach_oriented_variables(panel: pd.DataFrame, capital_path: Path) -> pd.DataFrame:
    """Attach capital and orient price/depth toward the vehicle used at entry."""

    data = attach_entry_capital(panel, capital_path)
    gap = pd.to_numeric(data["stable_minus_native_bps"], errors="coerce")
    native_relative_to_stable = np.divide(
        -10_000.0 * gap,
        10_000.0 + gap,
        out=np.full(len(data), np.nan),
        where=(10_000.0 + gap).abs().gt(1e-12),
    )
    entry_advantage_bps = np.where(
        data["entry_stable"].eq(1.0), gap, native_relative_to_stable
    )
    data["entry_vehicle_output_advantage_100bp"] = (
        np.clip(
            entry_advantage_bps,
            -MAX_LINEAR_ADVANTAGE_BPS,
            MAX_LINEAR_ADVANTAGE_BPS,
        )
        / 100.0
    )
    entry_capital_share = np.where(
        data["entry_stable"].eq(1.0),
        data["stable_v2_capital_share"],
        1.0 - data["stable_v2_capital_share"],
    )
    data["entry_vehicle_v2_capital_share_10pp"] = (
        entry_capital_share - 0.5
    ) / 0.10
    return data


def choice_results(
    panel: pd.DataFrame,
    *,
    entry_value_threshold_usd: float = DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
    sampling_calendar: str = "monthly_fifteenth",
) -> pd.DataFrame:
    """Estimate stable selection and entry-family retention on common samples."""

    complete = panel[panel["both_v2_bridge_capitals_positive"]].copy()
    clear_entry = complete[complete["entry_stable"].notna()].copy()
    rows = [
        _fit_entry_model(
            panel,
            model_id="price_only_all_first_contestable",
            predictors=("stable_output_advantage_100bp",),
            sample="all_first_sampled_exact_contestable_routes",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            complete,
            model_id="c1_price_only_common_capital_sample",
            predictors=("stable_output_advantage_100bp",),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            complete,
            model_id="c2_capital_only_common_sample",
            predictors=("stable_v2_capital_share_10pp",),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            complete,
            model_id="c3_price_and_capital_common_sample",
            predictors=(
                "stable_output_advantage_100bp",
                "stable_v2_capital_share_10pp",
            ),
            sample="first_contestable_positive_both_family_prior_v2_capital",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r1_entry_retention_price_only",
            predictors=("entry_vehicle_output_advantage_100bp",),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r2_entry_retention_capital_only",
            predictors=("entry_vehicle_v2_capital_share_10pp",),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
        _fit_entry_model(
            clear_entry,
            model_id="r3_entry_retention_price_and_capital",
            predictors=(
                "entry_vehicle_output_advantage_100bp",
                "entry_vehicle_v2_capital_share_10pp",
            ),
            sample="clear_entry_family_first_contestable_positive_capital",
            outcome="entry_vehicle_retained",
            choice_timing="first_sampled_exact_contestable_date_after_entry",
            record_type="first_contestable_vehicle_choice_regression",
            entry_value_threshold_usd=entry_value_threshold_usd,
        ),
    ]
    result = pd.concat(rows, ignore_index=True, sort=False)
    result["sampling_calendar"] = sampling_calendar
    return result


def support_results(
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    entry_value_threshold_usd: float = DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
    sampling_calendar: str = "monthly_fifteenth",
) -> pd.DataFrame:
    """Report contestability coverage, lags, and entry-family survival."""

    pair = (
        panel.groupby("ordered_pair", as_index=False, sort=True)
        .agg(
            entry_stable=("entry_stable", "first"),
            first_contestable_stable_share=("chosen_stable", "mean"),
            routes=("route_id", "size"),
            entry_to_contestability_days=("entry_to_contestability_days", "first"),
        )
    )
    pair["first_contestable_stable"] = np.where(
        pair["first_contestable_stable_share"].gt(0.5),
        1.0,
        np.where(pair["first_contestable_stable_share"].lt(0.5), 0.0, np.nan),
    )
    pair["entry_vehicle_retained"] = np.where(
        pair["entry_stable"].notna() & pair["first_contestable_stable"].notna(),
        pair["entry_stable"].eq(pair["first_contestable_stable"]).astype(float),
        np.nan,
    )
    clear_routes = panel[panel["entry_vehicle_retained"].notna()]
    complete = panel[panel["both_v2_bridge_capitals_positive"]]
    lag = pair["entry_to_contestability_days"]
    result = pd.DataFrame(
        [
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "material_entry_cohort",
                "entry_pairs": int(len(entries)),
                "entry_dates": int(entries["day"].nunique()),
                "pairs_reaching_sampled_contestability": int(len(pair)),
                "contestability_coverage_share": float(len(pair) / len(entries)),
                "minimum_entry_value_usd": float(
                    entries["entry_coherent_value_usd"].min()
                ),
                "entry_value_threshold_usd": float(entry_value_threshold_usd),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "first_sampled_exact_contestable_routes",
                "routes": int(len(panel)),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "dates": int(panel["day"].nunique()),
                "stable_choice_share": float(panel["chosen_stable"].mean()),
                "both_positive_prior_v2_capital_share": float(
                    panel["both_v2_bridge_capitals_positive"].mean()
                ),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "entry_to_first_sampled_contestability_lag",
                "pairs": int(len(pair)),
                "median_days": float(lag.median()),
                "p25_days": float(lag.quantile(0.25)),
                "p75_days": float(lag.quantile(0.75)),
                "p90_days": float(lag.quantile(0.90)),
                "within_120_days_share": float(lag.le(120).mean()),
                "monthly_sampling": sampling_calendar == "monthly_fifteenth",
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "entry_vehicle_survival",
                "route_weighted_retention_share": float(
                    clear_routes["entry_vehicle_retained"].mean()
                ),
                "route_weighted_routes": int(len(clear_routes)),
                "equal_pair_retention_share": float(
                    pair["entry_vehicle_retained"].mean()
                ),
                "equal_pair_pairs": int(pair["entry_vehicle_retained"].notna().sum()),
                "pair_ties_excluded": int(pair["first_contestable_stable"].isna().sum()),
            },
            {
                "record_type": "first_contestable_vehicle_choice_support",
                "sample": "positive_both_family_prior_v2_capital",
                "routes": int(len(complete)),
                "ordered_pairs": int(complete["ordered_pair"].nunique()),
                "dates": int(complete["day"].nunique()),
            },
        ]
    )
    result["sampling_calendar"] = sampling_calendar
    return result


def four_per_month_support_results(
    entries: pd.DataFrame,
    schedule: pd.DataFrame,
    panel: pd.DataFrame,
    day_support: pd.DataFrame,
    *,
    elapsed_seconds: float,
) -> pd.DataFrame:
    """Add fixed-calendar coverage and exact-route attrition to core support."""

    result = support_results(
        entries,
        panel,
        entry_value_threshold_usd=DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
        sampling_calendar=FOUR_PER_MONTH_CALENDAR,
    )

    def total(column: str) -> int:
        if column not in day_support:
            return 0
        return int(pd.to_numeric(day_support[column], errors="coerce").fillna(0).sum())

    schedule_row = {
        "record_type": "first_contestable_vehicle_choice_support",
        "sample": "four_per_month_sampling_schedule",
        "entry_pairs": int(len(entries)),
        "scheduled_pairs": int(schedule["ordered_pair"].nunique()),
        "scheduled_pair_days": int(len(schedule)),
        "scheduled_dates": int(schedule["day"].nunique()),
        "scheduled_primary_routes": float(schedule["sampled_primary_routes"].sum()),
        "scheduled_coherent_routes": float(
            schedule["sampled_coherent_routes"].sum()
        ),
        "scheduled_entry_coverage_share": float(
            schedule["ordered_pair"].nunique() / len(entries)
        ),
        "entry_value_threshold_usd": DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
        "elapsed_seconds": float(elapsed_seconds),
    }
    funnel_row = {
        "record_type": "first_contestable_vehicle_choice_support",
        "sample": "four_per_month_exact_attrition",
        "linear_routes": total("linear_routes"),
        "exact_venue_routes": total("exact_venue_routes"),
        "selected_pair_routes": total("selected_pair_routes"),
        "mapped_selected_pair_routes": total("mapped_selected_pair_routes"),
        "economic_targets": total("economic_targets"),
        "chosen_quote_reproduced": total("chosen_quote_reproduced"),
        "native_path_available": total("native_path_available"),
        "stable_path_available": total("stable_path_available"),
        "both_paths_available": total("both_paths_available"),
        "chosen_impact_supported": total("chosen_impact_supported"),
        "exact_contestable_routes": total("exact_contestable_rows"),
        "first_contestable_pairs": int(panel["ordered_pair"].nunique()),
        "scored_dates": int(day_support.get("day", pd.Series(dtype=str)).nunique()),
        "elapsed_seconds": float(elapsed_seconds),
    }
    result = pd.concat(
        [result, pd.DataFrame([schedule_row, funnel_row])],
        ignore_index=True,
        sort=False,
    )
    result["sampling_calendar"] = FOUR_PER_MONTH_CALENDAR
    result["fixed_sample_days"] = ",".join(map(str, FOUR_PER_MONTH_DAYS))
    result["fixed_samples_per_month"] = len(FOUR_PER_MONTH_DAYS)
    result["maximum_sampling_gap_days"] = FOUR_PER_MONTH_MAXIMUM_GAP_DAYS
    return result


def run(
    *,
    frontier_path: Path = FRONTIER,
    capital_path: Path = POOL_CAPITAL,
    panel_path: Path = PANEL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
    minimum_entry_value_usd: float = DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
    start: str = START,
    end: str = END,
    support_only: bool = False,
    sampling_calendar: str = "monthly_fifteenth",
) -> int:
    entries = load_material_entries(
        PRIMARY_DATA_DIR / "processed/endpoint_candidate_pair_support.parquet",
        minimum_entry_value_usd=minimum_entry_value_usd,
        start=start,
        end=end,
    )
    exact = first_contestable_routes(frontier_path, entries)
    panel = attach_oriented_variables(exact, capital_path)
    support = support_results(
        entries,
        panel,
        entry_value_threshold_usd=minimum_entry_value_usd,
        sampling_calendar=sampling_calendar,
    )
    write_panel(panel, panel_path, code_sources=CODE_SOURCES)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(support.to_string(index=False), flush=True)
    if support_only:
        return 0
    results = choice_results(
        panel,
        entry_value_threshold_usd=minimum_entry_value_usd,
        sampling_calendar=sampling_calendar,
    )
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(results.to_string(index=False), flush=True)
    return 0


def run_four_per_month(
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    capital_path: Path = POOL_CAPITAL,
    panel_path: Path = FOUR_PER_MONTH_PANEL,
    output_path: Path = FOUR_PER_MONTH_OUTPUT,
    support_path: Path = FOUR_PER_MONTH_SUPPORT,
    minimum_entry_value_usd: float = DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
    start: str = START,
    end: str = END,
    support_only: bool = False,
) -> int:
    """Build the isolated four-date exact panel and its estimates."""

    if minimum_entry_value_usd != DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD:
        raise ValueError(
            "four-per-month mode is fixed to the $5,000 material-entry cohort"
        )
    entries = load_material_entries(
        pair_support_path,
        minimum_entry_value_usd=minimum_entry_value_usd,
        start=start,
        end=end,
    )
    schedule = four_per_month_schedule(
        entries,
        pair_support_path,
        start=start,
        end=end,
    )
    started = perf_counter()
    exact, day_support = replay_four_per_month_schedule(schedule)
    prepared = prepare_four_per_month_panel(exact, entries)
    panel = attach_oriented_variables(prepared, capital_path)
    elapsed = perf_counter() - started
    support = four_per_month_support_results(
        entries,
        schedule,
        panel,
        day_support,
        elapsed_seconds=elapsed,
    )
    write_panel(panel, panel_path, code_sources=CODE_SOURCES)
    write_exhibit(
        support,
        support_path,
        code_sources=CODE_SOURCES,
        inputs=FOUR_PER_MONTH_INPUTS,
    )
    print(support.to_string(index=False), flush=True)
    if support_only:
        return 0
    results = choice_results(
        panel,
        entry_value_threshold_usd=minimum_entry_value_usd,
        sampling_calendar=FOUR_PER_MONTH_CALENDAR,
    )
    write_exhibit(
        results,
        output_path,
        code_sources=CODE_SOURCES,
        inputs=FOUR_PER_MONTH_INPUTS,
    )
    print(results.to_string(index=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT)
    parser.add_argument("--capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--panel", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--support", type=Path)
    parser.add_argument(
        "--minimum-entry-value-usd",
        type=float,
        default=DEFAULT_FIRST_CONTESTABLE_ENTRY_VALUE_USD,
    )
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--support-only", action="store_true")
    parser.add_argument(
        "--four-per-month",
        action="store_true",
        help=(
            "replay the fixed 1/8/15/22 grid and write the isolated "
            "four-per-month output family"
        ),
    )
    parser.add_argument(
        "--sampling-calendar",
        default="monthly_fifteenth",
        help="identifier for the fixed exact-state sampling calendar",
    )
    args = parser.parse_args()
    if args.four_per_month:
        panel_path = args.panel or FOUR_PER_MONTH_PANEL
        output_path = args.output or FOUR_PER_MONTH_OUTPUT
        support_path = args.support or FOUR_PER_MONTH_SUPPORT
        with exclusive_job(
            EXACT_REPLAY_LOCK,
            job="four-per-month first contestable vehicle choice",
        ):
            return run_four_per_month(
                pair_support_path=args.pair_support,
                capital_path=args.capital,
                panel_path=panel_path,
                output_path=output_path,
                support_path=support_path,
                minimum_entry_value_usd=args.minimum_entry_value_usd,
                start=args.start.replace("-", ""),
                end=args.end.replace("-", ""),
                support_only=args.support_only,
            )
    return run(
        frontier_path=args.frontier,
        capital_path=args.capital,
        panel_path=args.panel or PANEL,
        output_path=args.output or OUTPUT,
        support_path=args.support or SUPPORT,
        minimum_entry_value_usd=args.minimum_entry_value_usd,
        start=args.start.replace("-", ""),
        end=args.end.replace("-", ""),
        support_only=args.support_only,
        sampling_calendar=args.sampling_calendar,
    )


if __name__ == "__main__":
    raise SystemExit(main())
