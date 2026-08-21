#!/usr/bin/env python3
"""Measure V2-family LP flows before first use of a supported stable route.

The event sample comes directly from
``load_bridge_establishment_event_panel``.  For events whose first observed
stable route follows bridge establishment by at least seven days, we identify
the supported stablecoin used on that first-use date and follow every Uniswap
V2 or SushiSwap V2 pool on the exact source--stablecoin and
stablecoin--target token pairs.

Mint and Burn records provide actual LP additions and withdrawals.  Additions
on a pool's first active day in the retained V2-family panel are reported as
new-pool seeding; later additions are reported as additions to an already
active pool.  The main pre-use comparisons use only days strictly before the
first stable route.  First-use-day flows remain a separate event-time cell.

The reconstructed route ledger retains venues and token legs but not executed
pool addresses.  The pool set is therefore every V2-family pool on the exact
two token legs that is active by first use, not an assertion about which pool
the router executed against.  The bridge event also inherits the existing
30-day persistence requirement, which uses future support to select events.
These boundaries make the exercise descriptive timing evidence, not a causal
test of provider motives.

Reads
    data/processed/endpoint_candidate_choices.parquet
    data/processed/pool_capital_daily.parquet
    data/processed/v2_lp_flow_pool_daily.parquet
    data/processed/sushiswap_v2_lp_flow_pool_daily.parquet
Writes
    output/exhibits/bridge_lp_flow_before_use_pool_day.parquet
    output/exhibits/bridge_lp_flow_before_use_event_day.parquet
    output/exhibits/bridge_lp_flow_before_use.jsonl
    output/exhibits/bridge_lp_flow_before_use_support.jsonl
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
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_bridge_liquidity_dominance import (
    BRIDGE_ADOPTION_MIN_LAG_DAYS,
    BRIDGE_ESTABLISHMENT_POST_DAYS,
    CHOICES_INPUT,
    POOL_CAPITAL_INPUT,
    load_bridge_establishment_event_panel,
)


UNISWAP_INPUT = DATA_DIR / "processed/v2_lp_flow_pool_daily.parquet"
SUSHISWAP_INPUT = DATA_DIR / "processed/sushiswap_v2_lp_flow_pool_daily.parquet"
POOL_PANEL_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use_pool_day.parquet"
EVENT_DAY_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use_event_day.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use_support.jsonl"

PRE_DAYS = 28
POST_DAYS = 7
EVENT_DAYS = tuple(range(-PRE_DAYS, POST_DAYS + 1))
EVENT_BINS = (
    ("pre_week_4", -28, -22, -4),
    ("pre_week_3", -21, -15, -3),
    ("pre_week_2", -14, -8, -2),
    ("pre_week_1", -7, -1, -1),
    ("first_use_day", 0, 0, 0),
    ("post_week_1", 1, 7, 1),
)

CODE_SOURCES = [
    "scripts/analyze/run_bridge_lp_flow_before_use.py",
    "scripts/analyze/run_bridge_liquidity_dominance.py",
]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/pool_capital_daily.parquet",
    "data/processed/v2_lp_flow_pool_daily.parquet",
    "data/processed/sushiswap_v2_lp_flow_pool_daily.parquet",
]

FLOW_COLUMNS = (
    "v2_add_lp_flow_usd",
    "v2_remove_lp_flow_usd",
    "v2_gross_lp_flow_usd",
    "v2_net_add_lp_flow_usd",
    "v2_add_liquidity",
    "v2_remove_liquidity",
    "v2_raw_add_events",
    "v2_raw_remove_events",
    "v2_add_events_valued",
    "v2_remove_events_valued",
)


@dataclass(frozen=True)
class Outcome:
    name: str
    transformation: str
    label: str


OUTCOMES = (
    Outcome("add_flow_usd", "log1p", "LP additions"),
    Outcome("seed_add_flow_usd", "log1p", "new-pool seeding"),
    Outcome(
        "existing_add_flow_usd",
        "log1p",
        "additions to already-active pools",
    ),
    Outcome("remove_flow_usd", "log1p", "LP withdrawals"),
    Outcome("net_add_flow_usd", "asinh", "net LP additions"),
)


def _normalise_address(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower()


def bridge_adoption_events(
    bridge_panel: pd.DataFrame,
    *,
    min_lag_days: int = BRIDGE_ADOPTION_MIN_LAG_DAYS,
    max_lag_days: int = BRIDGE_ESTABLISHMENT_POST_DAYS - 1,
) -> pd.DataFrame:
    """Return one existing bridge event per delayed first stable-route use."""

    columns = [
        "event_id",
        "ordered_pair",
        "event_date",
        "first_stable_route_date",
        "src",
        "tgt",
        "integration_scope",
        "event_stablecoin_addresses",
    ]
    missing = sorted(set(columns) - set(bridge_panel.columns))
    if missing:
        raise ValueError(f"bridge panel lacks LP-timing event columns: {missing}")
    events = bridge_panel.loc[:, columns].drop_duplicates().copy()
    if events.empty or events["event_id"].duplicated().any():
        raise ValueError("bridge LP-timing fields vary within an event")
    for column in ("event_date", "first_stable_route_date"):
        events[column] = pd.to_datetime(events[column], errors="coerce").dt.normalize()
    for column in ("src", "tgt"):
        events[column] = _normalise_address(events[column])
    events["event_stablecoin_addresses"] = (
        events["event_stablecoin_addresses"].fillna("").astype(str).str.lower()
    )
    events["adoption_lag_days"] = (
        events["first_stable_route_date"] - events["event_date"]
    ).dt.days
    events = events[
        events["first_stable_route_date"].notna()
        & events["adoption_lag_days"].between(min_lag_days, max_lag_days)
    ].copy()
    if events.empty:
        raise ValueError("bridge panel has no delayed first-use events")
    events["window_start"] = events["first_stable_route_date"] - pd.Timedelta(
        days=PRE_DAYS
    )
    events["window_end"] = events["first_stable_route_date"] + pd.Timedelta(
        days=POST_DAYS
    )
    return events.sort_values("event_id").reset_index(drop=True)


def load_first_use_choices(
    events: pd.DataFrame,
    path: Path = CHOICES_INPUT,
) -> pd.DataFrame:
    """Read only supported-stablecoin choices on each event's first-use date."""

    if not path.is_file():
        raise FileNotFoundError(path)
    keys = events[
        [
            "event_id",
            "src",
            "tgt",
            "integration_scope",
            "first_stable_route_date",
            "event_stablecoin_addresses",
        ]
    ].copy()
    connection = duckdb.connect()
    try:
        connection.register("bridge_first_use_events", keys)
        choices = connection.execute(
            """
            SELECT
                e.event_id,
                CAST(c.date AS DATE) AS date,
                lower(c.src) AS src,
                lower(c.tgt) AS tgt,
                c.integration_scope,
                lower(c.candidate_address) AS candidate_address,
                max(c.candidate_symbol) AS candidate_symbol,
                sum(c.route_count)::DOUBLE AS route_count
            FROM bridge_first_use_events e
            JOIN read_parquet(?) c
              ON lower(c.src) = e.src
             AND lower(c.tgt) = e.tgt
             AND c.integration_scope = e.integration_scope
             AND CAST(c.date AS DATE) = CAST(e.first_stable_route_date AS DATE)
             AND list_contains(
                 string_split(e.event_stablecoin_addresses, ','),
                 lower(c.candidate_address)
             )
             AND c.route_count > 0
            GROUP BY 1, 2, 3, 4, 5, 6
            ORDER BY 1, route_count DESC, candidate_address
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()
    return choices


def select_first_used_supported_stablecoin(
    events: pd.DataFrame,
    choices: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the most-used supported stablecoin on the exact first-use date."""

    required = {
        "event_id",
        "date",
        "src",
        "tgt",
        "integration_scope",
        "candidate_address",
        "candidate_symbol",
        "route_count",
    }
    missing = sorted(required - set(choices.columns))
    if missing:
        raise ValueError(f"first-use choices lack columns: {missing}")
    use = choices.copy()
    use["date"] = pd.to_datetime(use["date"], errors="raise").dt.normalize()
    for column in ("src", "tgt", "candidate_address"):
        use[column] = _normalise_address(use[column])
    use["route_count"] = pd.to_numeric(use["route_count"], errors="coerce")
    event_keys = events[
        [
            "event_id",
            "src",
            "tgt",
            "integration_scope",
            "first_stable_route_date",
            "event_stablecoin_addresses",
        ]
    ]
    use = use.merge(
        event_keys,
        on=["event_id", "src", "tgt", "integration_scope"],
        how="inner",
        validate="many_to_one",
    )
    use = use[use["date"].eq(use["first_stable_route_date"])].copy()
    supported = [
        address in set(text.split(","))
        for address, text in zip(
            use["candidate_address"],
            use["event_stablecoin_addresses"],
            strict=True,
        )
    ]
    use = use[np.asarray(supported, dtype=bool) & use["route_count"].gt(0)].copy()
    use = (
        use.groupby(
            ["event_id", "candidate_address", "candidate_symbol"],
            as_index=False,
        )["route_count"]
        .sum()
        .sort_values(
            ["event_id", "route_count", "candidate_address"],
            ascending=[True, False, True],
        )
        .drop_duplicates("event_id")
    )
    if len(use) != len(events):
        missing_events = sorted(set(events["event_id"]) - set(use["event_id"]))
        raise ValueError(
            "supported stablecoin is missing on first-use date: "
            f"{missing_events[:5]}"
        )
    attached = events.merge(use, on="event_id", how="left", validate="one_to_one")
    return attached.sort_values("event_id").reset_index(drop=True)


def exact_leg_requests(events: pd.DataFrame) -> pd.DataFrame:
    """Return the two unordered endpoint--stablecoin token pairs per event."""

    required = {
        "event_id",
        "ordered_pair",
        "first_stable_route_date",
        "candidate_address",
        "candidate_symbol",
        "src",
        "tgt",
        "window_start",
        "window_end",
    }
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"adoption events lack exact-leg columns: {missing}")
    requests = events.merge(
        pd.DataFrame(
            {
                "leg": ["source", "target"],
                "endpoint_column": ["src", "tgt"],
            }
        ),
        how="cross",
    )
    requests["endpoint_address"] = np.where(
        requests["leg"].eq("source"), requests["src"], requests["tgt"]
    )
    candidate = _normalise_address(requests["candidate_address"])
    endpoint = _normalise_address(requests["endpoint_address"])
    if candidate.eq(endpoint).any():
        raise ValueError("stablecoin candidate cannot also be an endpoint")
    requests["token_a"] = np.where(candidate.le(endpoint), candidate, endpoint)
    requests["token_b"] = np.where(candidate.le(endpoint), endpoint, candidate)
    if requests.duplicated(["event_id", "leg"]).any() or len(requests) != 2 * len(
        events
    ):
        raise ValueError("exact bridge requests do not contain two legs per event")
    return requests.reset_index(drop=True)


def load_exact_support_pools(
    events: pd.DataFrame,
    path: Path = POOL_CAPITAL_INPUT,
) -> pd.DataFrame:
    """Return exact V2-family pools with capital at first stable-route use.

    Prior-calendar capital identifies support available strictly before the
    first route. Same-day capital additionally retains pools first activated
    during the use date, but those pools remain contemporaneous because daily
    data cannot order a Mint and a route within the day.
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    requests = exact_leg_requests(events)
    connection = duckdb.connect()
    try:
        connection.register("bridge_exact_leg_requests", requests)
        pools = connection.execute(
            """
            SELECT
                r.event_id,
                r.leg,
                r.token_a,
                r.token_b,
                lower(p.venue) AS venue,
                lower(p.pool) AS pool,
                sum(CASE WHEN p.exact_lag_valid
                         THEN coalesce(p.capital_usd_lagged, 0) ELSE 0 END)::DOUBLE
                    AS prior_capital_usd,
                sum(CASE WHEN p.capital_valid
                         THEN coalesce(p.capital_usd, 0) ELSE 0 END)::DOUBLE
                    AS same_day_capital_usd
            FROM bridge_exact_leg_requests r
            JOIN read_parquet(?) p
              ON strptime(CAST(p.day AS VARCHAR), '%Y%m%d')::DATE
                    = CAST(r.first_stable_route_date AS DATE)
             AND least(lower(p.token0_address), lower(p.token1_address)) = r.token_a
             AND greatest(lower(p.token0_address), lower(p.token1_address)) = r.token_b
             AND lower(p.venue) IN ('uniswap_v2', 'sushiswap_v2')
            WHERE p.quantity_kind = 'deposited_capital'
              AND (
                    (p.exact_lag_valid AND p.capital_usd_lagged > 0)
                 OR (p.capital_valid AND p.capital_usd > 0)
              )
            GROUP BY 1, 2, 3, 4, 5, 6
            HAVING prior_capital_usd > 0 OR same_day_capital_usd > 0
            ORDER BY event_id, leg, venue, pool
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()
    return pools


def load_relevant_v2_family_flows(
    support_pools: pd.DataFrame,
    uniswap_path: Path = UNISWAP_INPUT,
    sushiswap_path: Path = SUSHISWAP_INPUT,
) -> pd.DataFrame:
    """Read full Mint/Burn histories for the exact capital-support pools."""

    for path in (uniswap_path, sushiswap_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    required = {"venue", "pool"}
    missing = sorted(required - set(support_pools.columns))
    if missing:
        raise ValueError(f"exact support pools lack flow keys: {missing}")
    pool_keys = support_pools[["venue", "pool"]].drop_duplicates().copy()
    for column in ("venue", "pool"):
        pool_keys[column] = _normalise_address(pool_keys[column])
    if pool_keys.empty:
        return pd.DataFrame()
    connection = duckdb.connect()
    try:
        connection.register("bridge_exact_support_pools", pool_keys)
        frame = connection.execute(
            """
            WITH flow AS (
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
                    v2_raw_add_events,
                    v2_raw_remove_events,
                    v2_add_events_valued,
                    v2_remove_events_valued,
                    v2_lagged_capital_usd,
                    v2_capital_usd,
                    v2_exact_lag_valid,
                    v2_capital_valid
                FROM read_parquet(?, union_by_name=true)
                WHERE lower(venue) IN ('uniswap_v2', 'sushiswap_v2')
            )
            SELECT f.*
            FROM flow f
            JOIN bridge_exact_support_pools p
              ON p.venue = f.venue AND p.pool = f.pool
            ORDER BY venue, pool, origin_date
            """,
            [[str(uniswap_path), str(sushiswap_path)]],
        ).fetchdf()
    finally:
        connection.close()
    return frame


def _prepare_flows(flow_rows: pd.DataFrame) -> pd.DataFrame:
    required = {
        "venue",
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "v2_lagged_capital_usd",
        "v2_capital_usd",
        "v2_exact_lag_valid",
        "v2_capital_valid",
        *FLOW_COLUMNS,
    }
    missing = sorted(required - set(flow_rows.columns))
    if missing:
        raise ValueError(f"V2-family LP-flow input lacks columns: {missing}")
    flow = flow_rows.copy()
    for column in ("venue", "pool", "token0_address", "token1_address"):
        flow[column] = _normalise_address(flow[column])
    flow["origin_date"] = pd.to_datetime(flow["origin_date"], errors="raise").dt.normalize()
    if not set(flow["venue"]).issubset({"uniswap_v2", "sushiswap_v2"}):
        raise ValueError("bridge LP-flow input contains a non-V2-family venue")
    if flow.duplicated(["venue", "pool", "origin_date"]).any():
        raise ValueError("bridge LP-flow input has duplicate pool-days")
    identity = flow.groupby(["venue", "pool"])[
        ["token0_address", "token1_address"]
    ].nunique()
    if identity.gt(1).any(axis=None):
        raise ValueError("V2-family pool identity changes across days")
    flow["token_a"] = flow[["token0_address", "token1_address"]].min(axis=1)
    flow["token_b"] = flow[["token0_address", "token1_address"]].max(axis=1)
    for column in (*FLOW_COLUMNS, "v2_lagged_capital_usd", "v2_capital_usd"):
        flow[column] = pd.to_numeric(flow[column], errors="coerce")
    for column in ("v2_exact_lag_valid", "v2_capital_valid"):
        flow[column] = flow[column].fillna(False).astype(bool)

    current_active = (
        (flow["v2_capital_valid"] & flow["v2_capital_usd"].gt(0))
        | flow["v2_raw_add_events"].gt(0)
    )
    prior_active = flow["v2_exact_lag_valid"] & flow[
        "v2_lagged_capital_usd"
    ].gt(0)
    flow["activity_date_candidate"] = pd.NaT
    flow["prior_activity_date_candidate"] = pd.NaT
    flow.loc[current_active, "activity_date_candidate"] = flow.loc[
        current_active, "origin_date"
    ]
    flow.loc[prior_active, "prior_activity_date_candidate"] = flow.loc[
        prior_active, "origin_date"
    ] - pd.Timedelta(days=1)
    first_current = flow.groupby(["venue", "pool"])[
        "activity_date_candidate"
    ].transform("min")
    first_prior = flow.groupby(["venue", "pool"])[
        "prior_activity_date_candidate"
    ].transform("min")
    flow["pool_first_active_date"] = pd.concat(
        [first_current, first_prior], axis=1
    ).min(axis=1)
    return flow.drop(
        columns=["activity_date_candidate", "prior_activity_date_candidate"]
    ).sort_values(["venue", "pool", "origin_date"])


def build_event_pool_days(
    events: pd.DataFrame,
    flow_rows: pd.DataFrame,
    support_pools: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match actual pool flows to both exact legs and build a balanced day grid."""

    requests = exact_leg_requests(events)
    flow = _prepare_flows(flow_rows)
    support_required = {
        "event_id",
        "leg",
        "token_a",
        "token_b",
        "venue",
        "pool",
        "prior_capital_usd",
        "same_day_capital_usd",
    }
    missing = sorted(support_required - set(support_pools.columns))
    if missing:
        raise ValueError(f"exact support-pool input lacks columns: {missing}")
    support = support_pools.copy()
    for column in ("token_a", "token_b", "venue", "pool"):
        support[column] = _normalise_address(support[column])
    for column in ("prior_capital_usd", "same_day_capital_usd"):
        support[column] = pd.to_numeric(support[column], errors="coerce").fillna(0.0)
    if support.duplicated(["event_id", "leg", "venue", "pool"]).any():
        raise ValueError("exact support-pool input has duplicate event-leg pools")
    support = requests.merge(
        support,
        on=["event_id", "leg", "token_a", "token_b"],
        how="left",
        validate="one_to_many",
        suffixes=("", "_support"),
    )
    pool_identity = (
        flow[
            [
                "venue",
                "pool",
                "token_a",
                "token_b",
                "pool_first_active_date",
            ]
        ]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    if pool_identity.duplicated(["venue", "pool"]).any():
        raise ValueError("V2-family pool has multiple inferred activation dates")
    matched = support.merge(
        pool_identity,
        on=["venue", "pool"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_flow"),
    )
    identity_mismatch = matched["token_a_flow"].notna() & (
        matched["token_a_flow"].ne(matched["token_a"])
        | matched["token_b_flow"].ne(matched["token_b"])
    )
    if identity_mismatch.any():
        raise ValueError("support-pool token identity disagrees with LP-flow panel")
    matched["flow_history_available"] = matched["token_a_flow"].notna()
    matched["pool_key"] = np.where(
        matched["pool"].notna(),
        matched["venue"].astype(str) + "|" + matched["pool"].astype(str),
        None,
    )
    matched["pool_first_active_date"] = pd.to_datetime(
        matched["pool_first_active_date"], errors="coerce"
    ).dt.normalize()
    prior_bound = matched["first_stable_route_date"] - pd.Timedelta(days=1)
    same_day_bound = matched["first_stable_route_date"]
    support_bound = pd.Series(pd.NaT, index=matched.index, dtype="datetime64[ns]")
    support_bound.loc[matched["same_day_capital_usd"].gt(0)] = same_day_bound
    support_bound.loc[matched["prior_capital_usd"].gt(0)] = prior_bound
    matched["pool_first_active_date"] = pd.concat(
        [matched["pool_first_active_date"], support_bound], axis=1
    ).min(axis=1)
    matched["active_by_first_use"] = (
        matched["flow_history_available"]
        & (
            matched["prior_capital_usd"].gt(0)
            | matched["same_day_capital_usd"].gt(0)
        )
    )
    matched["active_strictly_before_first_use"] = (
        matched["flow_history_available"] & matched["prior_capital_usd"].gt(0)
    )
    coverage = (
        matched.groupby(["event_id", "leg"], as_index=False)
        .agg(
            pools_on_exact_leg=("pool_key", "nunique"),
            flow_matched_pools=("flow_history_available", "sum"),
            pools_active_by_first_use=("active_by_first_use", "sum"),
            pools_active_strictly_before_first_use=(
                "active_strictly_before_first_use",
                "sum",
            ),
        )
        .merge(
            requests[["event_id", "ordered_pair", "first_stable_route_date", "leg"]],
            on=["event_id", "leg"],
            how="right",
            validate="one_to_one",
        )
    )
    for column in (
        "pools_on_exact_leg",
        "flow_matched_pools",
        "pools_active_by_first_use",
        "pools_active_strictly_before_first_use",
    ):
        coverage[column] = coverage[column].fillna(0).astype(int)
    event_coverage = (
        coverage.groupby(
            ["event_id", "ordered_pair", "first_stable_route_date"], as_index=False
        )
        .agg(
            covered_legs_by_first_use=(
                "pools_active_by_first_use",
                lambda values: int(np.sum(np.asarray(values) > 0)),
            ),
            covered_legs_strictly_before_first_use=(
                "pools_active_strictly_before_first_use",
                lambda values: int(np.sum(np.asarray(values) > 0)),
            ),
            exact_leg_pools=("pools_on_exact_leg", "sum"),
            active_pools_by_first_use=("pools_active_by_first_use", "sum"),
        )
    )
    event_coverage["both_legs_by_first_use"] = event_coverage[
        "covered_legs_by_first_use"
    ].eq(2)
    event_coverage["both_legs_strictly_before_first_use"] = event_coverage[
        "covered_legs_strictly_before_first_use"
    ].eq(2)

    pools = matched[matched["active_by_first_use"]].copy()
    if pools.empty:
        raise ValueError("no V2-family pools are active by first stable-route use")
    grid = pools.merge(pd.DataFrame({"relative_day": EVENT_DAYS}), how="cross")
    grid["origin_date"] = grid["first_stable_route_date"] + pd.to_timedelta(
        grid["relative_day"], unit="D"
    )
    merge_columns = ["venue", "pool", "origin_date"]
    values = flow[merge_columns + list(FLOW_COLUMNS)].copy()
    grid = grid.merge(values, on=merge_columns, how="left", validate="many_to_one")
    for column in FLOW_COLUMNS:
        grid[column] = pd.to_numeric(grid[column], errors="coerce").fillna(0.0)
    grid["add_usd_complete"] = grid["v2_raw_add_events"].eq(
        grid["v2_add_events_valued"]
    )
    grid["remove_usd_complete"] = grid["v2_raw_remove_events"].eq(
        grid["v2_remove_events_valued"]
    )
    grid["usd_flow_complete"] = grid["add_usd_complete"] & grid[
        "remove_usd_complete"
    ]
    grid["seed_day"] = grid["origin_date"].eq(grid["pool_first_active_date"])
    grid["seed_add_flow_usd"] = np.where(
        grid["seed_day"], grid["v2_add_lp_flow_usd"], 0.0
    )
    grid["existing_add_flow_usd"] = np.where(
        grid["pool_first_active_date"].lt(grid["origin_date"]),
        grid["v2_add_lp_flow_usd"],
        0.0,
    )
    unexplained = (
        grid["v2_add_lp_flow_usd"].gt(0)
        & ~grid["seed_day"]
        & ~grid["pool_first_active_date"].lt(grid["origin_date"])
    )
    if unexplained.any():
        raise ValueError("positive addition cannot be classified by prior pool state")
    grid = grid.merge(
        event_coverage[
            [
                "event_id",
                "both_legs_by_first_use",
                "both_legs_strictly_before_first_use",
            ]
        ],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    return (
        grid.sort_values(
            ["event_id", "relative_day", "leg", "venue", "pool"]
        ).reset_index(drop=True),
        event_coverage.sort_values("event_id").reset_index(drop=True),
    )


def aggregate_event_days(pool_days: pd.DataFrame) -> pd.DataFrame:
    """Collapse exact-pool rows to one balanced two-leg row per event-day."""

    data = pool_days[pool_days["both_legs_by_first_use"]].copy()
    if data.empty:
        raise ValueError("no bridge events have both exact V2-family legs by first use")
    keys = [
        "event_id",
        "ordered_pair",
        "first_stable_route_date",
        "candidate_symbol",
        "candidate_address",
        "relative_day",
        "origin_date",
        "both_legs_strictly_before_first_use",
    ]
    grouped = data.groupby(keys, as_index=False).agg(
        add_flow_usd=("v2_add_lp_flow_usd", "sum"),
        seed_add_flow_usd=("seed_add_flow_usd", "sum"),
        existing_add_flow_usd=("existing_add_flow_usd", "sum"),
        remove_flow_usd=("v2_remove_lp_flow_usd", "sum"),
        gross_flow_usd=("v2_gross_lp_flow_usd", "sum"),
        net_add_flow_usd=("v2_net_add_lp_flow_usd", "sum"),
        raw_add_events=("v2_raw_add_events", "sum"),
        raw_remove_events=("v2_raw_remove_events", "sum"),
        valued_add_events=("v2_add_events_valued", "sum"),
        valued_remove_events=("v2_remove_events_valued", "sum"),
        exact_leg_pools=("pool_key", "nunique"),
        legs=("leg", "nunique"),
        usd_flow_complete=("usd_flow_complete", "all"),
    )
    if not grouped["legs"].eq(2).all():
        raise ValueError("balanced bridge event-day lost one exact token leg")
    grouped["strict_add_flow_usd"] = grouped["add_flow_usd"].where(
        grouped["valued_add_events"].eq(grouped["raw_add_events"])
    )
    grouped["strict_seed_add_flow_usd"] = grouped["seed_add_flow_usd"].where(
        grouped["valued_add_events"].eq(grouped["raw_add_events"])
    )
    grouped["strict_existing_add_flow_usd"] = grouped[
        "existing_add_flow_usd"
    ].where(grouped["valued_add_events"].eq(grouped["raw_add_events"]))
    grouped["strict_remove_flow_usd"] = grouped["remove_flow_usd"].where(
        grouped["valued_remove_events"].eq(grouped["raw_remove_events"])
    )
    grouped["strict_net_add_flow_usd"] = grouped["net_add_flow_usd"].where(
        grouped["usd_flow_complete"]
    )
    counts = grouped.groupby("event_id")["relative_day"].agg(set)
    balanced = counts[counts.eq(set(EVENT_DAYS))].index
    grouped = grouped[grouped["event_id"].isin(balanced)].copy()
    if grouped.empty:
        raise ValueError("bridge LP event-day panel has no balanced events")
    return grouped.sort_values(["event_id", "relative_day"]).reset_index(drop=True)


def _transform(values: pd.Series, kind: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if kind == "log1p":
        if numeric.dropna().lt(0).any():
            raise ValueError("log1p LP-flow outcome cannot be negative")
        return np.log1p(numeric)
    if kind == "asinh":
        return np.arcsinh(numeric)
    raise ValueError(f"unknown LP-flow transformation {kind}")


def _mean_record(values: pd.Series, clusters: pd.Series) -> dict[str, float | int]:
    fit = mean_clustered(values, clusters)
    statistic = (
        fit.estimate / fit.standard_error
        if np.isfinite(fit.standard_error) and fit.standard_error > 0
        else np.nan
    )
    p_value = (
        float(2 * stats.t.sf(abs(statistic), fit.n_clusters - 1))
        if fit.n_clusters > 1 and np.isfinite(statistic)
        else np.nan
    )
    return {
        "estimate": fit.estimate,
        "standard_error": fit.standard_error,
        "t_statistic": float(statistic),
        "p_value": p_value,
        "confidence_interval_lower": fit.confidence_interval_lower,
        "confidence_interval_upper": fit.confidence_interval_upper,
        "observations": fit.n_observations,
        "ordered_pair_clusters": fit.n_clusters,
    }


def _event_bins(event_days: pd.DataFrame) -> pd.DataFrame:
    data = event_days.copy()
    data["event_bin"] = None
    data["event_bin_index"] = np.nan
    for name, lower, upper, index in EVENT_BINS:
        in_bin = data["relative_day"].between(lower, upper)
        data.loc[in_bin, "event_bin"] = name
        data.loc[in_bin, "event_bin_index"] = index
    if data["event_bin"].isna().any():
        raise ValueError("event-day row lies outside declared event bins")
    aggregate = {
        "ordered_pair": ("ordered_pair", "first"),
        "first_stable_route_date": ("first_stable_route_date", "first"),
        "event_bin_index": ("event_bin_index", "first"),
        "days": ("relative_day", "size"),
    }
    for outcome in OUTCOMES:
        strict = f"strict_{outcome.name}"
        aggregate[outcome.name] = (
            strict,
            lambda values: (
                float(values.mean()) if values.notna().all() else float("nan")
            ),
        )
    binned = data.groupby(["event_id", "event_bin"], as_index=False).agg(**aggregate)
    expected = {name for name, *_rest in EVENT_BINS}
    complete = binned.groupby("event_id")["event_bin"].agg(set)
    complete_events = complete[complete.eq(expected)].index
    return binned[binned["event_id"].isin(complete_events)].reset_index(drop=True)


def _estimate_lp_flow_sample(
    event_days: pd.DataFrame,
    *,
    sample_name: str,
) -> list[dict[str, object]]:
    """Estimate one declared event sample."""

    binned = _event_bins(event_days)
    if binned.empty:
        raise ValueError("bridge LP-flow timing has no complete binned events")
    rows: list[dict[str, object]] = []
    for outcome in OUTCOMES:
        available = binned.dropna(subset=[outcome.name]).copy()
        wide = available.pivot(index="event_id", columns="event_bin", values=outcome.name)
        ordered_pairs = available.drop_duplicates("event_id").set_index("event_id")[
            "ordered_pair"
        ]
        required = [name for name, *_rest in EVENT_BINS]
        wide = wide.dropna(subset=required)
        if wide.empty:
            continue
        clusters = ordered_pairs.reindex(wide.index)
        for name, lower, upper, index in EVENT_BINS:
            values = wide[name]
            level = _mean_record(values, clusters)
            rows.append(
                {
                    "record_type": "event_path_level",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "transformation": "level_usd_daily_average",
                    "event_bin": name,
                    "event_bin_index": index,
                    "relative_day_start": lower,
                    "relative_day_end": upper,
                    "median": float(values.median()),
                    "positive_share": float(values.gt(0).mean()),
                    **level,
                }
            )
            transformed = _transform(values, outcome.transformation)
            reference = _transform(wide["pre_week_4"], outcome.transformation)
            rows.append(
                {
                    "record_type": "event_path_contrast",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "transformation": outcome.transformation,
                    "event_bin": name,
                    "event_bin_index": index,
                    "relative_day_start": lower,
                    "relative_day_end": upper,
                    "reference_bin": "pre_week_4",
                    **_mean_record(transformed - reference, clusters),
                }
            )

        early = wide[["pre_week_4", "pre_week_3", "pre_week_2"]].mean(axis=1)
        late = wide["pre_week_1"]
        acceleration = _transform(late, outcome.transformation) - _transform(
            early, outcome.transformation
        )
        rows.append(
            {
                "record_type": "pre_use_acceleration",
                "outcome": outcome.name,
                "outcome_label": outcome.label,
                "transformation": outcome.transformation,
                "window": "days_minus_7_to_minus_1_vs_days_minus_28_to_minus_8",
                "first_use_day_excluded": True,
                **_mean_record(acceleration, clusters),
            }
        )

        for window, names in (
            ("early_pre_weeks", ["pre_week_4", "pre_week_3", "pre_week_2"]),
            (
                "all_pre_weeks",
                ["pre_week_4", "pre_week_3", "pre_week_2", "pre_week_1"],
            ),
        ):
            x = np.arange(len(names), dtype=float)
            transformed = pd.DataFrame(
                {
                    name: _transform(wide[name], outcome.transformation)
                    for name in names
                }
            )
            slopes = pd.Series(
                [np.polyfit(x, transformed.loc[event_id, names], 1)[0] for event_id in wide.index],
                index=wide.index,
            )
            rows.append(
                {
                    "record_type": "pretrend_slope",
                    "outcome": outcome.name,
                    "outcome_label": outcome.label,
                    "transformation": outcome.transformation,
                    "window": window,
                    "slope_unit": "one_seven_day_bin",
                    "first_use_day_excluded": True,
                    **_mean_record(slopes, clusters),
                }
            )

    for row in rows:
        row["sample"] = sample_name
    return rows


def estimate_lp_flow_timing(
    event_days: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return binned event paths, pre-use acceleration, and pretrend slopes."""

    rows = _estimate_lp_flow_sample(
        event_days,
        sample_name="both_v2_family_legs_by_first_use",
    )
    strict_events = event_days.loc[
        event_days["both_legs_strictly_before_first_use"], "event_id"
    ].unique()
    if len(strict_events):
        rows.extend(
            _estimate_lp_flow_sample(
                event_days[event_days["event_id"].isin(strict_events)],
                sample_name="both_v2_family_legs_strictly_before_first_use",
            )
        )
    results = pd.DataFrame(rows)
    if results.empty:
        raise ValueError("bridge LP-flow timing produced no estimable outcomes")
    support = pd.DataFrame(
        [
            {
                "record_type": "bridge_lp_flow_before_use_support",
                "events": int(event_days["event_id"].nunique()),
                "ordered_pairs": int(event_days["ordered_pair"].nunique()),
                "first_event_date": str(
                    pd.to_datetime(event_days["first_stable_route_date"]).min().date()
                ),
                "last_event_date": str(
                    pd.to_datetime(event_days["first_stable_route_date"]).max().date()
                ),
                "pre_days": PRE_DAYS,
                "post_days": POST_DAYS,
                "strict_prior_two_leg_events": int(
                    event_days.loc[
                        event_days["both_legs_strictly_before_first_use"], "event_id"
                    ].nunique()
                ),
                "complete_usd_event_day_share": float(
                    event_days["usd_flow_complete"].mean()
                ),
                "event_source": (
                    "existing_first_persistent_stable_bridge_events_from_"
                    "load_bridge_establishment_event_panel"
                ),
                "pool_scope": (
                    "all_uniswap_v2_and_sushiswap_v2_pools_on_the_exact_two_"
                    "endpoint_stablecoin_token_pairs_active_by_first_use"
                ),
                "pool_attribution_boundary": (
                    "route_reconstruction_retains_venues_and_token_legs_but_not_"
                    "executed_pool_addresses"
                ),
                "seeding_definition": (
                    "actual_mint_flow_on_first_active_day_in_retained_v2_family_"
                    "panel;_not_verified_contract_deployment"
                ),
                "temporal_boundary": (
                    "pre_use_statistics_end_at_day_minus_1;day_zero_reported_"
                    "separately;candidate_identity_fixed_from_first_use_day"
                ),
                "selection_boundary": (
                    "bridge_events_inherit_future_30_day_persistent_support_"
                    "selection;timing_results_are_descriptive"
                ),
            }
        ]
    )
    return results, support


def run(
    *,
    choices_path: Path = CHOICES_INPUT,
    pool_capital_path: Path = POOL_CAPITAL_INPUT,
    uniswap_path: Path = UNISWAP_INPUT,
    sushiswap_path: Path = SUSHISWAP_INPUT,
    pool_panel_output: Path = POOL_PANEL_OUTPUT,
    event_day_output: Path = EVENT_DAY_OUTPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    bridge_panel = load_bridge_establishment_event_panel(
        choices_path=choices_path,
        pool_capital_path=pool_capital_path,
    )
    events = bridge_adoption_events(bridge_panel)
    first_use_choices = load_first_use_choices(events, choices_path)
    events = select_first_used_supported_stablecoin(events, first_use_choices)
    support_pools = load_exact_support_pools(events, pool_capital_path)
    flow_rows = load_relevant_v2_family_flows(
        support_pools,
        uniswap_path=uniswap_path,
        sushiswap_path=sushiswap_path,
    )
    pool_days, coverage = build_event_pool_days(events, flow_rows, support_pools)
    event_days = aggregate_event_days(pool_days)
    results, support = estimate_lp_flow_timing(event_days)
    support["eligible_delayed_bridge_events"] = len(events)
    support["events_with_both_v2_family_legs_by_first_use"] = int(
        coverage["both_legs_by_first_use"].sum()
    )
    support["events_with_both_v2_family_legs_strictly_prior"] = int(
        coverage["both_legs_strictly_before_first_use"].sum()
    )
    write_panel(pool_days, pool_panel_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_panel(event_days, event_day_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(event_days):,} event-days for "
        f"{event_days['event_id'].nunique():,} delayed bridge events"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL_INPUT)
    parser.add_argument("--uniswap", type=Path, default=UNISWAP_INPUT)
    parser.add_argument("--sushiswap", type=Path, default=SUSHISWAP_INPUT)
    parser.add_argument("--pool-panel-output", type=Path, default=POOL_PANEL_OUTPUT)
    parser.add_argument("--event-day-output", type=Path, default=EVENT_DAY_OUTPUT)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        choices_path=args.choices,
        pool_capital_path=args.pool_capital,
        uniswap_path=args.uniswap,
        sushiswap_path=args.sushiswap,
        pool_panel_output=args.pool_panel_output,
        event_day_output=args.event_day_output,
        result_output=args.result_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
