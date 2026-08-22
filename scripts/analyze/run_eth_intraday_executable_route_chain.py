#!/usr/bin/env python3
"""Trace ETH declines into exact route prices and realised vehicle use.

The analysis uses the external Coinbase ETH/USD minute close and exact
pre-transaction replay for Uniswap V2 and SushiSwap V2.  A stress event begins
when the strictly available six-hour ETH return first crosses -10 percent;
retained events are at least 48 hours apart.  We quote the best stablecoin and
WETH two-leg paths at every eligible observed route in the six hours before
through 24 hours after each event.

The first outcome is the exact stablecoin-minus-WETH output advantage at the
observed input amount.  It is an executable quote, not dollar pool capital and
not a complete depth curve.  The second outcome is realised stablecoin vehicle
choice.  Event-by-endpoint-pair effects compare the same pair within an event,
and relative-hour effects absorb the common event-time profile.  Inference is
clustered by stress event and endpoint pair.

Writes
  data/processed/eth_intraday_executable_route_chain.parquet
  output/exhibits/eth_intraday_executable_route_chain.jsonl
  output/exhibits/eth_intraday_executable_route_chain_support.jsonl
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.pricing.tick_replay import TickReplayState
from ddvc.pricing.v2_replay import V2_VENUES, load_v2_replay_day
from ddvc.tables import write_exhibit
from scripts.analyze.run_contestable_vehicle_choice import (
    QUOTED_VEHICLES,
    prepare_frontier,
)
from scripts.analyze.run_exact_vehicle_frontier import route_targets, score_target


PRICE_INPUT = DATA_DIR / "processed/external_weth_usd_intraday.parquet"
PANEL_OUTPUT = DATA_DIR / "processed/eth_intraday_executable_route_chain.parquet"
SCORED_OUTPUT = DATA_DIR / "processed/eth_intraday_executable_route_chain_scored.parquet"
DAY_SUPPORT_OUTPUT = DATA_DIR / "processed/eth_intraday_executable_route_chain_day_support.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/eth_intraday_executable_route_chain.jsonl"
SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits/eth_intraday_executable_route_chain_support.jsonl"
)

START = "20200615"
END = "20260630"
RETURN_HOURS = 6
EVENT_THRESHOLD = 0.10
COOLDOWN_HOURS = 48
PRE_EVENT_HOURS = 6
POST_EVENT_HOURS = 24
PRICE_TOLERANCE_SECONDS = 180
MIN_OBSERVATIONS = 300
MIN_EVENT_CLUSTERS = 20
MIN_PAIR_CLUSTERS = 20

CODE_SOURCES = [
    "scripts/analyze/run_eth_intraday_executable_route_chain.py",
    "scripts/analyze/run_exact_vehicle_frontier.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/external_weth_usd_intraday.parquet",
    "data/unified/*.parquet",
    "data/raw/thegraph/uniswap_v2/*.parquet",
    "data/raw/thegraph/sushiswap_v2/*.parquet",
]


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    outcome: str
    predictors: tuple[str, ...]
    fixed_effects: tuple[str, ...]
    stage: str
    focal: bool
    family: str


MODEL_SPECS = (
    ModelSpec(
        "m1_quote_pair_event",
        "stable_output_advantage_100bp",
        ("eth_decline_6h_per_10pp", "log_input_usd"),
        ("event_pair",),
        "exact_executable_quote",
        False,
        "support_event_time_chain",
    ),
    ModelSpec(
        "m2_quote_pair_event_and_relative_hour",
        "stable_output_advantage_100bp",
        ("eth_decline_6h_per_10pp", "log_input_usd"),
        ("event_pair", "relative_hour_bin"),
        "exact_executable_quote",
        True,
        "primary_event_time_chain",
    ),
    ModelSpec(
        "m3_choice_pair_event_and_relative_hour",
        "chosen_stable",
        ("eth_decline_6h_per_10pp", "log_input_usd"),
        ("event_pair", "relative_hour_bin"),
        "realised_vehicle_choice",
        True,
        "primary_event_time_chain",
    ),
    ModelSpec(
        "m4_choice_conditioned_on_exact_quote",
        "chosen_stable",
        (
            "eth_decline_6h_per_10pp",
            "stable_output_advantage_100bp",
            "log_input_usd",
        ),
        ("event_pair", "relative_hour_bin"),
        "choice_conditional_on_exact_quote",
        False,
        "secondary_event_time_chain",
    ),
)


def load_external_prices(path: Path = PRICE_INPUT) -> pd.DataFrame:
    """Load the independent minute ETH/USD close in availability order."""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = duckdb.connect()
    try:
        frame = connection.execute(
            """
            SELECT
                available_at_utc::BIGINT AS available_at_utc,
                weth_usd::DOUBLE AS weth_usd
            FROM read_parquet(?)
            WHERE validation_status = 'valid'
              AND weth_usd > 0
            ORDER BY available_at_utc
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("external minute ETH/USD input is empty")
    if frame["available_at_utc"].duplicated().any():
        raise ValueError("external minute ETH/USD input has duplicate timestamps")
    if not frame["available_at_utc"].is_monotonic_increasing:
        raise ValueError("external minute ETH/USD input is not ordered")
    return frame


def add_trailing_return(
    prices: pd.DataFrame,
    *,
    return_hours: int = RETURN_HOURS,
    tolerance_seconds: int = PRICE_TOLERANCE_SECONDS,
) -> pd.DataFrame:
    """Attach a backward-looking return to every available minute close."""

    if return_hours <= 0 or tolerance_seconds < 0:
        raise ValueError("return window and price tolerance must be valid")
    frame = prices[["available_at_utc", "weth_usd"]].copy()
    frame = frame.sort_values("available_at_utc", kind="stable").reset_index(drop=True)
    lag_targets = pd.DataFrame(
        {
            "lag_target_utc": frame["available_at_utc"]
            - int(return_hours * 3600)
        }
    )
    lagged = pd.merge_asof(
        lag_targets,
        frame.rename(
            columns={
                "available_at_utc": "lag_available_at_utc",
                "weth_usd": "lag_weth_usd",
            }
        ),
        left_on="lag_target_utc",
        right_on="lag_available_at_utc",
        direction="backward",
        tolerance=tolerance_seconds,
    )
    frame["lag_available_at_utc"] = lagged["lag_available_at_utc"]
    frame["lag_weth_usd"] = lagged["lag_weth_usd"]
    frame["eth_log_return_6h"] = np.log(frame["weth_usd"]) - np.log(
        frame["lag_weth_usd"]
    )
    frame["eth_decline_6h"] = -frame["eth_log_return_6h"]
    return frame


def detect_decline_events(
    price_state: pd.DataFrame,
    *,
    start: str = START,
    end: str = END,
    threshold: float = EVENT_THRESHOLD,
    cooldown_hours: int = COOLDOWN_HOURS,
    pre_hours: int = PRE_EVENT_HOURS,
    post_hours: int = POST_EVENT_HOURS,
) -> pd.DataFrame:
    """Return first threshold crossings separated by a declared cooldown."""

    if threshold <= 0 or cooldown_hours <= pre_hours + post_hours:
        raise ValueError("event threshold must be positive and windows nonoverlapping")
    if pre_hours < 0 or post_hours <= 0:
        raise ValueError("event windows must be nonnegative and have a positive post period")
    frame = price_state.dropna(subset=["eth_decline_6h"]).copy()
    frame = frame.sort_values("available_at_utc", kind="stable").reset_index(drop=True)
    previous_decline = frame["eth_decline_6h"].shift(1)
    consecutive = frame["available_at_utc"].diff().le(120)
    crossing = (
        frame["eth_decline_6h"].ge(float(threshold))
        & previous_decline.lt(float(threshold))
        & consecutive
    )
    candidates = frame[crossing].copy()
    start_ts = int(pd.Timestamp(start, tz="UTC").timestamp())
    end_ts = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    candidates = candidates[
        candidates["available_at_utc"].sub(pre_hours * 3600).ge(start_ts)
        & candidates["available_at_utc"].add(post_hours * 3600).lt(end_ts)
    ]
    kept: list[pd.Series] = []
    last = -10**18
    cooldown_seconds = int(cooldown_hours * 3600)
    for row in candidates.itertuples(index=False):
        event_ts = int(row.available_at_utc)
        if event_ts - last < cooldown_seconds:
            continue
        kept.append(pd.Series(row._asdict()))
        last = event_ts
    if not kept:
        raise ValueError("no ETH decline events clear the declared bounds")
    events = pd.DataFrame(kept).reset_index(drop=True)
    events["event_id"] = events["available_at_utc"].astype(int).map(
        lambda value: f"eth6h_{value}"
    )
    events["event_ts"] = events["available_at_utc"].astype(int)
    events["event_time_utc"] = pd.to_datetime(events["event_ts"], unit="s", utc=True)
    events["window_start_utc"] = events["event_ts"] - int(pre_hours * 3600)
    events["window_end_utc"] = events["event_ts"] + int(post_hours * 3600)
    events["crossing_decline_6h"] = events["eth_decline_6h"].astype(float)
    return events[
        [
            "event_id",
            "event_ts",
            "event_time_utc",
            "window_start_utc",
            "window_end_utc",
            "crossing_decline_6h",
        ]
    ]


def event_day_tasks(events: pd.DataFrame) -> list[tuple[str, tuple[tuple, ...]]]:
    """Map nonoverlapping event windows to the UTC dates that must be replayed."""

    by_day: dict[str, list[tuple]] = defaultdict(list)
    for row in events.itertuples(index=False):
        first = pd.to_datetime(int(row.window_start_utc), unit="s", utc=True).floor("D")
        last = pd.to_datetime(int(row.window_end_utc - 1), unit="s", utc=True).floor("D")
        for date in pd.date_range(first, last, freq="D"):
            by_day[date.strftime("%Y%m%d")].append(
                (
                    str(row.event_id),
                    int(row.event_ts),
                    int(row.window_start_utc),
                    int(row.window_end_utc),
                )
            )
    for day, windows in by_day.items():
        ordered = sorted(windows, key=lambda value: value[2])
        for left, right in zip(ordered, ordered[1:]):
            if left[3] > right[2]:
                raise ValueError(f"overlapping stress windows on {day}")
    return [(day, tuple(windows)) for day, windows in sorted(by_day.items())]


def _score_v2_day(task: tuple[str, tuple[tuple, ...]]) -> tuple[list[dict], dict]:
    """Score one independent V2/Sushi day at exact pre-transaction state."""

    day, windows = task
    started = perf_counter()
    try:
        replay = load_v2_replay_day(None, day)
    except ValueError as error:
        message = str(error)
        if "constant-product exact-event contract failed" not in message:
            raise
        return [], {
            "record_type": "eth_intraday_executable_route_chain_day_support",
            "day": day,
            "windows": len(windows),
            "v2_sushi_targets": 0,
            "window_targets": 0,
            "scored_routes": 0,
            "chosen_reproduction_share": np.nan,
            "elapsed_seconds": perf_counter() - started,
            "state_status": "excluded_exact_event_contract_failure",
            "state_error": message,
        }
    targets, reasons = route_targets(day, v2_replay=replay, tick_events=[])
    v2_targets = [
        target
        for target in targets
        if all(venue in V2_VENUES for venue in target.route.venues)
    ]
    rows: list[dict] = []
    selected_targets = 0
    exact_replay = TickReplayState()
    for target in v2_targets:
        matched = [
            window
            for window in windows
            if int(window[2]) <= int(target.timestamp) < int(window[3])
        ]
        if not matched:
            continue
        if len(matched) != 1:
            raise ValueError(f"route belongs to multiple stress windows on {day}")
        selected_targets += 1
        result = score_target(target, replay=exact_replay, v2_replay=replay)
        if result is None:
            continue
        event_id, event_ts, _start, _end = matched[0]
        result["timestamp_utc"] = int(target.timestamp)
        result["event_id"] = str(event_id)
        result["event_ts"] = int(event_ts)
        rows.append(result)
    support = {
        "record_type": "eth_intraday_executable_route_chain_day_support",
        "day": day,
        "windows": len(windows),
        "v2_sushi_targets": len(v2_targets),
        "window_targets": selected_targets,
        "scored_routes": len(rows),
        "chosen_reproduction_share": (
            len(rows) / selected_targets if selected_targets else np.nan
        ),
        "elapsed_seconds": perf_counter() - started,
        **{f"route_target_{key}": value for key, value in reasons.items()},
    }
    return rows, support


def score_event_days(
    tasks: list[tuple[str, tuple[tuple, ...]]],
    *,
    workers: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay independent V2 days, optionally in parallel."""

    if workers < 1:
        raise ValueError("workers must be positive")
    all_rows: list[dict] = []
    all_support: list[dict] = []
    iterator = map(_score_v2_day, tasks)
    executor = None
    if workers > 1:
        executor = ProcessPoolExecutor(max_workers=workers)
        iterator = executor.map(_score_v2_day, tasks, chunksize=1)
    try:
        for index, (rows, support) in enumerate(iterator, 1):
            all_rows.extend(rows)
            all_support.append(support)
            print(
                f"[{index}/{len(tasks)}] {support['day']}: "
                f"targets={support['window_targets']:,} "
                f"scored={support['scored_routes']:,} "
                f"seconds={support['elapsed_seconds']:.1f}",
                flush=True,
            )
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    if not all_rows:
        raise ValueError("no event-window routes clear exact replay")
    return pd.DataFrame(all_rows), pd.DataFrame(all_support)


def attach_route_price_state(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    return_hours: int = RETURN_HOURS,
    tolerance_seconds: int = PRICE_TOLERANCE_SECONDS,
) -> pd.DataFrame:
    """Attach strictly available current and lagged external ETH prices."""

    data = panel.sort_values("timestamp_utc", kind="stable").reset_index(drop=True)
    right = prices[["available_at_utc", "weth_usd"]].sort_values(
        "available_at_utc", kind="stable"
    )
    current = pd.merge_asof(
        data[["timestamp_utc"]],
        right,
        left_on="timestamp_utc",
        right_on="available_at_utc",
        direction="backward",
        tolerance=tolerance_seconds,
        allow_exact_matches=False,
    )
    lag_targets = pd.DataFrame(
        {"lag_target_utc": data["timestamp_utc"] - int(return_hours * 3600)}
    )
    lagged = pd.merge_asof(
        lag_targets,
        right.rename(
            columns={
                "available_at_utc": "lag_available_at_utc",
                "weth_usd": "lag_weth_usd",
            }
        ),
        left_on="lag_target_utc",
        right_on="lag_available_at_utc",
        direction="backward",
        tolerance=tolerance_seconds,
        allow_exact_matches=False,
    )
    data["eth_price_available_at_utc"] = current["available_at_utc"]
    data["eth_price_usd"] = current["weth_usd"]
    data["eth_lag_price_available_at_utc"] = lagged["lag_available_at_utc"]
    data["eth_lag_price_usd"] = lagged["lag_weth_usd"]
    data["eth_log_return_6h"] = np.log(data["eth_price_usd"]) - np.log(
        data["eth_lag_price_usd"]
    )
    data["eth_decline_6h_per_10pp"] = -data["eth_log_return_6h"] / 0.10
    return data


def prepare_panel(scored: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Build the clean exact-quote contest among nonvehicle endpoints."""

    metadata_columns = ["route_id", "timestamp_utc", "event_id", "event_ts"]
    metadata = scored.loc[:, metadata_columns].copy()
    if metadata["route_id"].duplicated().any():
        raise ValueError("scored event routes contain duplicate route ids")
    contestable, _frontier_counts = prepare_frontier(scored)
    contestable = contestable.merge(
        metadata,
        on="route_id",
        how="left",
        validate="one_to_one",
    )
    excluded = frozenset(str(value).casefold() for value in QUOTED_VEHICLES)
    contestable = contestable[
        contestable["symmetric_common_support"].astype(bool)
        & ~contestable["token_in"].astype(str).str.casefold().isin(excluded)
        & ~contestable["token_out"].astype(str).str.casefold().isin(excluded)
    ].copy()
    if contestable.empty:
        raise ValueError("nonvehicle-endpoint event contest is empty")
    data = attach_route_price_state(contestable, prices)
    data["relative_hours"] = (
        data["timestamp_utc"] - data["event_ts"]
    ) / 3600.0
    data["relative_hour_bin"] = np.floor(data["relative_hours"]).astype("Int64")
    data["event_pair"] = data["event_id"].astype(str) + "|" + data["ordered_pair"]
    data["chosen_stable"] = data["chosen_stable"].astype(float)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "eth_decline_6h_per_10pp",
            "stable_output_advantage_100bp",
            "chosen_stable",
            "log_input_usd",
            "relative_hour_bin",
        ]
    )
    if data.empty or data["route_id"].duplicated().any():
        raise ValueError("event-time exact-route panel is empty or duplicated")
    if not data["eth_price_available_at_utc"].lt(data["timestamp_utc"]).all():
        raise ValueError("route price attachment uses information unavailable at execution")
    return data.sort_values(["event_ts", "timestamp_utc", "route_id"]).reset_index(
        drop=True
    )


def _fit_model(panel: pd.DataFrame, spec: ModelSpec) -> list[dict[str, object]]:
    columns = [
        spec.outcome,
        *spec.predictors,
        *spec.fixed_effects,
        "event_pair",
        "event_id",
        "ordered_pair",
    ]
    data = panel.loc[:, list(dict.fromkeys(columns))].dropna().copy()
    event_pair_size = data.groupby("event_pair")["event_pair"].transform("size")
    data = data[event_pair_size.gt(1)].copy()
    if len(data) < MIN_OBSERVATIONS:
        raise ValueError(f"{spec.model_id} has too few observations")
    if data["event_id"].nunique() < MIN_EVENT_CLUSTERS:
        raise ValueError(f"{spec.model_id} has too few stress events")
    if data["ordered_pair"].nunique() < MIN_PAIR_CLUSTERS:
        raise ValueError(f"{spec.model_id} has too few endpoint pairs")
    groups = tuple(data[column] for column in spec.fixed_effects)
    transformed = absorb_fixed_effects(
        data[[spec.outcome, *spec.predictors]], *groups
    )
    fit = ols_clustered(
        transformed[spec.outcome],
        transformed[list(spec.predictors)],
        data["event_id"],
        add_constant=False,
        absorbed_groups=groups,
        additional_clusters=(data["ordered_pair"],),
        min_observations=MIN_OBSERVATIONS,
        min_clusters=MIN_EVENT_CLUSTERS,
    )
    if not np.isfinite(fit.beta).all() or not np.isfinite(fit.standard_errors).all():
        raise ValueError(f"{spec.model_id} is not estimable")
    rows: list[dict[str, object]] = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        spec.predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "eth_intraday_executable_route_chain_regression",
                "model_id": spec.model_id,
                "chain_stage": spec.stage,
                "sample": "v2_sushiv2_nonvehicle_endpoints_both_families_executable",
                "outcome": spec.outcome,
                "predictor": predictor,
                "coefficient": float(coefficient),
                "standard_error": float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "holm_p_value": np.nan,
                "focal_decline_coefficient": bool(
                    spec.focal and predictor == "eth_decline_6h_per_10pp"
                ),
                "multiplicity_family": spec.family,
                "observations": int(fit.n_observations),
                "events": int(data["event_id"].nunique()),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "fixed_effects": "+".join(spec.fixed_effects),
                "covariance": "stress_event_and_ordered_pair_cluster_cr1",
                "eth_timing": "strictly_available_coinbase_close_t_minus_6h_to_t",
                "quote_interpretation": "exact_pretransaction_output_at_observed_notional",
                "depth_interpretation": "not_dollar_tvl_and_not_a_complete_depth_curve",
                "venue_scope": "uniswap_v2+sushiswap_v2",
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data[spec.outcome].mean()),
                "causal_interpretation": False,
            }
        )
    return rows


def summarize_event_time(panel: pd.DataFrame) -> list[dict[str, object]]:
    """Return readable event-time bins without replacing the regression design."""

    bins = (-6.0, -3.0, 0.0, 1.0, 6.0, 24.0)
    labels = ("h-6_to_h-3", "h-3_to_h0", "h0_to_h1", "h1_to_h6", "h6_to_h24")
    data = panel.copy()
    data["event_time_bin"] = pd.cut(
        data["relative_hours"], bins=bins, labels=labels, right=False
    )
    rows: list[dict[str, object]] = []
    for label, group in data.dropna(subset=["event_time_bin"]).groupby(
        "event_time_bin", observed=True, sort=False
    ):
        rows.append(
            {
                "record_type": "eth_intraday_executable_route_chain_event_time",
                "event_time_bin": str(label),
                "routes": int(len(group)),
                "events": int(group["event_id"].nunique()),
                "ordered_pairs": int(group["ordered_pair"].nunique()),
                "mean_eth_decline_6h_per_10pp": float(
                    group["eth_decline_6h_per_10pp"].mean()
                ),
                "mean_stable_output_advantage_bps": float(
                    100.0 * group["stable_output_advantage_100bp"].mean()
                ),
                "stable_vehicle_share": float(group["chosen_stable"].mean()),
            }
        )
    return rows


def estimate(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for spec in MODEL_SPECS:
        rows.extend(_fit_model(panel, spec))
    results = pd.DataFrame(rows)
    focal = results["focal_decline_coefficient"].astype(bool)
    results.loc[focal, "holm_p_value"] = holm_adjusted_pvalues(
        results.loc[focal, "p_value"]
    )
    return pd.concat(
        [results, pd.DataFrame(summarize_event_time(panel))],
        ignore_index=True,
        sort=False,
    )


def support_record(
    events: pd.DataFrame,
    day_support: pd.DataFrame,
    scored: pd.DataFrame,
    panel: pd.DataFrame,
) -> pd.DataFrame:
    record = {
        "record_type": "eth_intraday_executable_route_chain_support",
        "events": int(events["event_id"].nunique()),
        "first_event_utc": str(events["event_time_utc"].min()),
        "last_event_utc": str(events["event_time_utc"].max()),
        "event_definition": "first_strictly_available_6h_eth_decline_crossing_10_percent",
        "event_cooldown_hours": COOLDOWN_HOURS,
        "event_window_hours": f"-{PRE_EVENT_HOURS}_to_+{POST_EVENT_HOURS}",
        "days_replayed": int(day_support["day"].nunique()),
        "window_targets": int(day_support["window_targets"].sum()),
        "exactly_reproduced_routes": int(len(scored)),
        "chosen_reproduction_share": float(
            len(scored) / day_support["window_targets"].sum()
        ),
        "contestable_clean_routes": int(len(panel)),
        "ordered_pairs": int(panel["ordered_pair"].nunique()),
        "venue_scope": "uniswap_v2+sushiswap_v2",
        "endpoint_scope": "neither_endpoint_is_weth_dai_usdc_or_usdt",
        "price_source": "coinbase_exchange_eth_usd_spot_1m_close",
        "price_timing": "latest_available_close_strictly_before_transaction",
        "quote_interpretation": "exact_pretransaction_output_at_observed_notional",
        "depth_interpretation": "not_dollar_tvl_and_not_a_complete_depth_curve",
        "v3_exclusion_reason": (
            "bounded_independent_day_replay_avoids_rebuilding_continuous_v3_tick_state"
        ),
        "causal_interpretation": False,
    }
    return pd.DataFrame([record])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--resume-scored", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prices = load_external_prices()
    if args.summarize_only:
        if not PANEL_OUTPUT.is_file():
            parser.error("--summarize-only requires the retained event panel")
        panel = pd.read_parquet(PANEL_OUTPUT)
        results = estimate(panel)
        print(results.to_string(index=False), flush=True)
        if not args.no_write:
            write_exhibit(
                results,
                RESULT_OUTPUT,
                code_sources=CODE_SOURCES,
                inputs=[PANEL_OUTPUT],
            )
        return 0

    price_state = add_trailing_return(prices)
    events = detect_decline_events(price_state, start=args.start, end=args.end)
    if args.max_events is not None:
        if args.max_events < 1:
            parser.error("--max-events must be positive")
        events = events.head(args.max_events).copy()
    if args.resume_scored:
        if not SCORED_OUTPUT.is_file() or not DAY_SUPPORT_OUTPUT.is_file():
            parser.error("--resume-scored requires the replay checkpoints")
        scored = pd.read_parquet(SCORED_OUTPUT)
        day_support = pd.read_parquet(DAY_SUPPORT_OUTPUT)
        print(f"resumed scored routes={len(scored):,}", flush=True)
    else:
        tasks = event_day_tasks(events)
        print(
            f"events={len(events):,} replay_days={len(tasks):,} workers={args.workers}",
            flush=True,
        )
        scored, day_support = score_event_days(tasks, workers=args.workers)
        if not args.no_write:
            PANEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            scored.to_parquet(SCORED_OUTPUT, index=False)
            day_support.to_parquet(DAY_SUPPORT_OUTPUT, index=False)
    panel = prepare_panel(scored, prices)
    results = estimate(panel)
    support = support_record(events, day_support, scored, panel)
    print(results.to_string(index=False), flush=True)
    print(support.to_string(index=False), flush=True)
    if args.no_write:
        return 0
    PANEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_OUTPUT, index=False)
    write_exhibit(
        results,
        RESULT_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL_OUTPUT, PRICE_INPUT],
    )
    write_exhibit(
        pd.concat([support, day_support], ignore_index=True, sort=False),
        SUPPORT_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL_OUTPUT, PRICE_INPUT],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
