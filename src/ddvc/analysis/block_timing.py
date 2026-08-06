"""Causally ordered marginal-price states for block-timing diagnostics."""

from __future__ import annotations

import bisect
import gzip
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.pricing.v3pools import resolve_decimals

Q96 = 1 << 96
SwapState = tuple[int, int, int, int, float]


@dataclass(frozen=True)
class SwapEvent:
    pool_id: str
    block: int
    log_index: int


@dataclass
class V3DayState:
    tokens: dict[str, tuple[str, str]]
    decimals: dict[str, tuple[int, int]]
    series: dict[str, list[SwapState]]
    events: dict[tuple[str, int], SwapEvent]
    transaction_first_log: dict[str, int]


def load_v3_day(path: Path) -> V3DayState:
    """Load V3 metadata, event identities and post-swap states in causal order."""
    tokens: dict[str, tuple[str, str]] = {}
    decimals: dict[str, tuple[int, int]] = {}
    explicit_decimals: dict[str, tuple[int, int]] = {}
    swap_samples: dict[str, list[dict]] = defaultdict(list)
    series: dict[str, list[SwapState]] = defaultdict(list)
    events: dict[tuple[str, int], SwapEvent] = {}
    raw_events: dict[tuple[str, int], dict] = {}
    transaction_first_log: dict[str, int] = {}
    if not path.exists():
        return V3DayState(tokens, decimals, series, events, transaction_first_log)
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pool = row.get("pool") or {}
            pool_id = str(pool.get("id") or "").lower()
            token0 = str((pool.get("token0") or {}).get("id") or "").lower()
            token1 = str((pool.get("token1") or {}).get("id") or "").lower()
            transaction_id = str((row.get("transaction") or {}).get("id") or "").lower()
            try:
                block = int((row.get("transaction") or {}).get("blockNumber") or 0)
                log_index = int(row.get("logIndex") or 0)
                timestamp = int(row.get("timestamp") or 0)
                sqrt_price_x96 = int(row.get("sqrtPriceX96") or 0)
            except (TypeError, ValueError):
                continue
            if not (
                pool_id
                and token0
                and token1
                and transaction_id
                and block
                and timestamp
                and sqrt_price_x96 > 0
            ):
                continue
            event_key = (transaction_id, log_index)
            if event_key in raw_events:
                prior = {key: value for key, value in raw_events[event_key].items() if key != "id"}
                current = {key: value for key, value in row.items() if key != "id"}
                if current == prior:
                    continue
                raise ValueError(f"conflicting V3 transaction-log event: {event_key}")
            raw_events[event_key] = row
            tokens[pool_id] = (token0, token1)
            raw_decimals = (
                (pool.get("token0") or {}).get("decimals"),
                (pool.get("token1") or {}).get("decimals"),
            )
            if all(value is not None and value != "" for value in raw_decimals):
                try:
                    parsed_decimals = tuple(int(value) for value in raw_decimals)
                except (TypeError, ValueError):
                    parsed_decimals = ()
                if len(parsed_decimals) == 2 and all(0 <= value <= 255 for value in parsed_decimals):
                    prior = explicit_decimals.get(pool_id)
                    if prior is not None and prior != parsed_decimals:
                        raise ValueError(f"inconsistent V3 token decimals for pool: {pool_id}")
                    explicit_decimals[pool_id] = parsed_decimals
            sample = swap_samples[pool_id]
            if len(sample) < 12:
                sample.append(row)
            events[event_key] = SwapEvent(pool_id, block, log_index)
            transaction_first_log[transaction_id] = min(
                log_index,
                transaction_first_log.get(transaction_id, log_index),
            )
            series[pool_id].append(
                (
                    block,
                    log_index,
                    timestamp,
                    timestamp // 3600,
                    2.0 * math.log(sqrt_price_x96 / Q96),
                )
            )
    for pool_id in series:
        series[pool_id].sort()
        token0, token1 = tokens[pool_id]
        resolved = resolve_decimals(token0, token1, swap_samples[pool_id])
        explicit = explicit_decimals.get(pool_id)
        if explicit is not None:
            decimals[pool_id] = explicit
        elif resolved is not None:
            decimals[pool_id] = resolved
    return V3DayState(tokens, decimals, series, events, transaction_first_log)


def load_v3_swap_day(
    path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, list[SwapState]]]:
    """Compatibility projection for triangle analyses."""
    day = load_v3_day(path)
    return day.tokens, day.series


class PoolView:
    """Strict pre-event state and end-of-hour state for one pool."""

    def __init__(self, sequence: list[SwapState]) -> None:
        self.orders = [
            (block, log_index)
            for block, log_index, _timestamp, _hour, _price in sequence
        ]
        self.logp = [price for _block, _log, _timestamp, _hour, price in sequence]
        self.by_hour: dict[int, float] = {}
        self.hour_end_ts: dict[int, int] = {}
        for _block, _log, timestamp, hour, price in sequence:
            self.by_hour[hour] = price
            self.hour_end_ts[hour] = timestamp

    def before(self, block: int, log_index: int) -> float | None:
        """Return the last post-swap state strictly before the target event."""
        index = bisect.bisect_left(self.orders, (block, log_index)) - 1
        return self.logp[index] if index >= 0 else None

    def at_hour(self, hour: int) -> float | None:
        return self.by_hour.get(hour)


def oriented(
    log_price: float,
    token0: str,
    token1: str,
    token_in: str,
    token_out: str,
) -> float | None:
    """Orient log token1/token0 as log output units per input unit."""
    if token0 == token_in and token1 == token_out:
        return log_price
    if token0 == token_out and token1 == token_in:
        return -log_price
    return None


def oriented_human(
    log_price: float,
    token0: str,
    token1: str,
    decimals0: int,
    decimals1: int,
    token_in: str,
    token_out: str,
) -> float | None:
    """Orient a raw-unit V3 log price into human output units per input unit."""
    human_token1_per_token0 = log_price + (decimals0 - decimals1) * math.log(10)
    return oriented(
        human_token1_per_token0,
        token0,
        token1,
        token_in,
        token_out,
    )


def summarise_triangle_maturation(
    triangles: pd.DataFrame,
    *,
    recurrence_thresholds: tuple[int, ...] = (2, 3, 4, 6, 10),
    horizon_bins: int = 4,
    cluster_hac_lag: int = 3,
) -> pd.DataFrame:
    """Estimate price-gap compression on recurrent and horizon-balanced triangles."""
    if horizon_bins < 2:
        raise ValueError("triangle maturation requires at least two horizon bins")
    required = {
        "day",
        "src",
        "tgt",
        "vehicle",
        "direct_pool",
        "hop1_pool",
        "hop2_pool",
        "median_gap_bps",
        "n_observations",
    }
    missing = required - set(triangles.columns)
    if missing:
        raise ValueError(f"triangle maturation is missing columns: {sorted(missing)}")
    frame = triangles.copy()
    frame["date"] = pd.to_datetime(frame["day"], format="%Y%m%d")
    frame = frame[
        np.isfinite(frame["median_gap_bps"])
        & frame["median_gap_bps"].gt(0)
        & frame["n_observations"].gt(0)
    ].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["year"] = (
        (frame["date"] - frame["date"].min()).dt.total_seconds()
        / (365.25 * 24 * 60 * 60)
    )
    frame["log_gap"] = np.log(frame["median_gap_bps"])
    frame["economic_triangle"] = (
        frame["src"].astype(str)
        + "|"
        + frame["tgt"].astype(str)
        + "|"
        + frame["vehicle"].astype(str)
    )
    frame["exact_pool_triangle"] = (
        frame["direct_pool"].astype(str)
        + "|"
        + frame["hop1_pool"].astype(str)
        + "|"
        + frame["hop2_pool"].astype(str)
    )
    elapsed = (frame["date"] - frame["date"].min()).dt.total_seconds()
    span = float(elapsed.max())
    frame["horizon_bin"] = (
        (elapsed / span * horizon_bins).clip(upper=horizon_bins - 1).astype(int)
        if span > 0
        else 0
    )
    rows: list[dict[str, object]] = []
    for identity in ("economic_triangle", "exact_pool_triangle"):
        recurrence = frame.groupby(identity)["date"].transform("nunique")
        covered_bins = frame.groupby(identity)["horizon_bin"].transform("nunique")
        for minimum_dates in recurrence_thresholds:
            recurrent = recurrence.ge(minimum_dates)
            panels = {
                "recurrent_support": recurrent,
                "horizon_balanced": recurrent & covered_bins.eq(horizon_bins),
            }
            for panel, selected in panels.items():
                sample = frame[selected].copy()
                if sample.empty:
                    continue
                y = absorb_fixed_effects(sample["log_gap"], sample[identity])
                x = absorb_fixed_effects(sample["year"], sample[identity])
                fit = ols_clustered(
                    y,
                    x,
                    sample["date"],
                    absorbed_groups=(sample[identity],),
                    min_observations=30,
                    cluster_hac_lag=cluster_hac_lag,
                )
                beta = float(fit.beta[1])
                rows.append(
                    {
                        "panel": panel,
                        "identity": identity,
                        "minimum_dates": minimum_dates,
                        "required_horizon_bins": (
                            horizon_bins if panel == "horizon_balanced" else 0
                        ),
                        "cluster_hac_lag": cluster_hac_lag,
                        "triangle_days": fit.n_observations,
                        "triangles": int(sample[identity].nunique()),
                        "dates": fit.n_clusters,
                        "absorbed_degrees_of_freedom": fit.absorbed_degrees_of_freedom,
                        "log_gap_time_beta": beta,
                        "annual_compression": (
                            float(1 - np.exp(beta)) if np.isfinite(beta) else np.nan
                        ),
                        "standard_error": float(fit.standard_errors[1]),
                        "t": float(fit.t_statistics[1]),
                        "p": float(fit.p_values[1]),
                    }
                )
    for year, sample in frame.groupby(frame["date"].dt.year):
        rows.append(
            {
                "panel": "annual_descriptive",
                "identity": "all_sampled_triangles",
                "minimum_dates": np.nan,
                "required_horizon_bins": np.nan,
                "cluster_hac_lag": np.nan,
                "triangle_days": len(sample),
                "triangles": int(sample["economic_triangle"].nunique()),
                "dates": int(sample["date"].nunique()),
                "year": int(year),
                "median_gap_bps": float(sample["median_gap_bps"].median()),
                "snapshot_weighted_mean_gap_bps": float(
                    np.average(
                        sample["median_gap_bps"],
                        weights=sample["n_observations"],
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def summarise_timing_conditionals(
    observation_frames: Iterable[pd.DataFrame],
) -> pd.DataFrame:
    """Aggregate timing diagnostics from an iterable of daily observation frames."""
    gap_buckets = (
        (0, 5, "under 5 bps"),
        (5, 10, "5 to 10 bps"),
        (10, 25, "10 to 25 bps"),
        (25, 50, "25 to 50 bps"),
        (50, 100, "50 to 100 bps"),
        (100, 250, "100 to 250 bps"),
        (250, 10**9, "above 250 bps"),
    )
    time_buckets = (
        (0, 60, "under 1 min"),
        (60, 300, "1 to 5 min"),
        (300, 900, "5 to 15 min"),
        (900, 1800, "15 to 30 min"),
        (1800, 3600, "30 to 60 min"),
    )
    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"observations": 0, "flips": 0, "dominated": 0}
    )
    for raw in observation_frames:
        frame = raw.copy()
        if frame.empty:
            continue
        required = {"m_own_bps", "m_hr_bps", "secs_to_boundary"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"timing observations are missing columns: {sorted(missing)}")
        frame["flipped"] = (frame["m_own_bps"].gt(0) != frame["m_hr_bps"].gt(0)).astype(int)
        frame["gap_bps"] = frame["m_own_bps"].abs()

        def add(
            cut: str,
            bucket: str,
            selected: pd.DataFrame,
            *,
            dominated: pd.Series | None = None,
        ) -> None:
            record = totals[(cut, bucket)]
            record["observations"] += len(selected)
            record["flips"] += int(selected["flipped"].sum())
            if dominated is not None:
                record["dominated"] += int(dominated.sum())

        for lower, upper, label in gap_buckets:
            add("gap_at_own_event", label, frame[frame["gap_bps"].between(lower, upper, inclusive="left")])
        for lower, upper, label in time_buckets:
            add(
                "time_to_hour_boundary",
                label,
                frame[frame["secs_to_boundary"].between(lower, upper, inclusive="left")],
            )
        for wedge in (0, 5, 10, 30, 60, 100):
            own = frame["m_own_bps"] + wedge
            hour = frame["m_hr_bps"] + wedge
            selected = frame.assign(flipped=(own.gt(0) != hour.gt(0)).astype(int))
            add("fee_wedge_bps", str(wedge), selected, dominated=own.lt(0))
        add("pooled", "all", frame)
        for threshold in (25, 50, 100):
            add("gap_minimum_bps", str(threshold), frame[frame["gap_bps"].ge(threshold)])

    rows: list[dict[str, object]] = []
    for (cut, bucket), record in totals.items():
        observations = record["observations"]
        if observations < 50 and cut in {"gap_at_own_event", "time_to_hour_boundary"}:
            continue
        row: dict[str, object] = {
            "cut": cut,
            "bucket": bucket,
            "observations": observations,
            "value": record["flips"] / observations if observations else np.nan,
        }
        if cut == "fee_wedge_bps":
            row["dominated_share"] = record["dominated"] / observations if observations else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
