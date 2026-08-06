"""Causally ordered marginal-price states for block-timing diagnostics."""

from __future__ import annotations

import bisect
import gzip
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

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
