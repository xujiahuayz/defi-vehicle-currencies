"""Exact within-hour reserve replay for V2-style constant-product venues."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ddvc.asset_types import canonical_token
from ddvc.cpquote import (
    ReserveEvent,
    hour_is_clean,
    ordered_reserve_events,
    prior_observed_state,
    reserve_state_before,
)


V2_VENUES = ("uniswap_v2", "sushiswap_v2")
PoolKey = tuple[str, str]
PoolHourKey = tuple[str, str, int]
ChainOrder = tuple[int, int]


@dataclass(frozen=True)
class V2PoolMeta:
    venue: str
    pool: str
    token0: str
    token1: str


@dataclass(frozen=True)
class V2SwapEvent:
    venue: str
    pool: str
    tx_hash: str
    timestamp: int
    hour: int
    order: ChainOrder
    log_index: int
    row: dict


@dataclass(frozen=True)
class V2ReplayDay:
    """Clean exact-state pool hours and raw chosen-route identities for one day."""

    meta: dict[PoolKey, V2PoolMeta]
    pool_hour_events: dict[PoolHourKey, list[ReserveEvent]]
    state_support: dict[PoolHourKey, tuple[int, int]]
    swaps_by_pool_hour: dict[PoolHourKey, list[V2SwapEvent]]
    swaps_by_identity: dict[tuple[str, str, int], V2SwapEvent]
    pair_index: dict[frozenset[str], list[PoolKey]]

    def state_before(
        self,
        venue: str,
        pool: str,
        hour: int,
        order: ChainOrder,
    ) -> tuple[Decimal, Decimal] | None:
        events = self.pool_hour_events.get((venue, pool, hour))
        return reserve_state_before(events, order) if events else None

    def candidates(self, token0: str, token1: str) -> list[PoolKey]:
        return self.pair_index.get(frozenset((token0, token1)), [])


def reserve_delta(row: dict) -> tuple[Decimal, Decimal]:
    """Net reserve change from one V2 swap row."""
    return (
        Decimal(row.get("amount0In", "0")) - Decimal(row.get("amount0Out", "0")),
        Decimal(row.get("amount1In", "0")) - Decimal(row.get("amount1Out", "0")),
    )


def _read_reserves(
    path: Path,
    venue: str,
    reserves: dict[PoolHourKey, tuple[Decimal, Decimal]],
    meta: dict[PoolKey, V2PoolMeta],
    *,
    latest_only: bool,
) -> None:
    if not path.exists():
        return
    latest: dict[str, tuple[int, tuple[Decimal, Decimal], V2PoolMeta]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            pair = row.get("pair") or {}
            pool = str(pair.get("id") or "").lower()
            try:
                hour = int(row["hourStartUnix"])
                state = (Decimal(row["reserve0"]), Decimal(row["reserve1"]))
                token0 = canonical_token(str(pair["token0"]["id"]).lower())
                token1 = canonical_token(str(pair["token1"]["id"]).lower())
            except (KeyError, TypeError, ValueError):
                continue
            if not pool or token0 is None or token1 is None:
                continue
            pool_meta = V2PoolMeta(venue, pool, token0, token1)
            if latest_only:
                prior = latest.get(pool)
                if prior is None or hour > prior[0]:
                    latest[pool] = (hour, state, pool_meta)
            else:
                reserves[(venue, pool, hour)] = state
                meta[(venue, pool)] = pool_meta
    for pool, (hour, state, pool_meta) in latest.items():
        reserves[(venue, pool, hour)] = state
        meta[(venue, pool)] = pool_meta


def load_v2_replay_day(
    raw_root: Path,
    day: str,
    *,
    venues: tuple[str, ...] = V2_VENUES,
) -> V2ReplayDay:
    """Load and validate every reconstructable V2 pool-hour for ``day``."""
    reserves: dict[PoolHourKey, tuple[Decimal, Decimal]] = {}
    meta: dict[PoolKey, V2PoolMeta] = {}
    swaps: dict[PoolHourKey, list[V2SwapEvent]] = defaultdict(list)
    liquidity: dict[
        PoolHourKey, list[tuple[ChainOrder, tuple[Decimal, Decimal]]]
    ] = defaultdict(list)
    previous_day = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime(
        "%Y%m%d"
    )

    for venue in venues:
        venue_root = raw_root / venue
        _read_reserves(
            venue_root / f"{venue}_hourly_reserves_{previous_day}.jsonl.gz",
            venue,
            reserves,
            meta,
            latest_only=True,
        )
        _read_reserves(
            venue_root / f"{venue}_hourly_reserves_{day}.jsonl.gz",
            venue,
            reserves,
            meta,
            latest_only=False,
        )
        swap_path = venue_root / f"{venue}_swaps_{day}.jsonl.gz"
        if swap_path.exists():
            with gzip.open(swap_path, "rt") as handle:
                for line in handle:
                    row = json.loads(line)
                    pool = str((row.get("pair") or {}).get("id") or "").lower()
                    transaction = row.get("transaction") or {}
                    try:
                        timestamp = int(row["timestamp"])
                        log_index = int(row["logIndex"])
                        order = (int(transaction["blockNumber"]), log_index)
                    except (KeyError, TypeError, ValueError):
                        continue
                    tx_hash = str(transaction.get("id") or row.get("id") or "").lower()
                    if not pool or not tx_hash or timestamp <= 0:
                        continue
                    hour = timestamp - timestamp % 3600
                    swaps[(venue, pool, hour)].append(
                        V2SwapEvent(
                            venue,
                            pool,
                            tx_hash,
                            timestamp,
                            hour,
                            order,
                            log_index,
                            row,
                        )
                    )
        for stream, sign in (("mints", Decimal(1)), ("burns", Decimal(-1))):
            path = venue_root / f"{venue}_{stream}_{day}.jsonl.gz"
            if not path.exists():
                continue
            with gzip.open(path, "rt") as handle:
                for line in handle:
                    row = json.loads(line)
                    pool = str((row.get("pair") or {}).get("id") or "").lower()
                    transaction = row.get("transaction") or {}
                    try:
                        timestamp = int(row["timestamp"])
                        order = (int(transaction["blockNumber"]), int(row["logIndex"]))
                        delta = (
                            sign * Decimal(row["amount0"]),
                            sign * Decimal(row["amount1"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                    if pool:
                        hour = timestamp - timestamp % 3600
                        liquidity[(venue, pool, hour)].append((order, delta))

    candidate_events: dict[PoolHourKey, list[ReserveEvent]] = {}
    deltas_by_hour: dict[PoolHourKey, list[tuple[Decimal, Decimal]]] = {}
    for key in sorted(set(swaps) | set(liquidity)):
        stored = reserves.get(key)
        if stored is None:
            continue
        ordered_swaps = sorted(swaps.get(key, []), key=lambda event: event.order)
        changes = [
            *((event.order, reserve_delta(event.row)) for event in ordered_swaps),
            *liquidity.get(key, []),
        ]
        events = ordered_reserve_events(stored, changes)
        if any(
            value <= 0
            for event in events
            for state in (event.before, event.after)
            for value in state
        ):
            continue
        candidate_events[key] = events
        deltas_by_hour[key] = [
            (event.after[0] - event.before[0], event.after[1] - event.before[1])
            for event in events
        ]

    reserve_states: dict[PoolKey, dict[int, tuple[Decimal, Decimal]]] = defaultdict(dict)
    known_deltas: dict[PoolKey, dict[int, list[tuple[Decimal, Decimal]]]] = defaultdict(dict)
    for (venue, pool, hour), state in reserves.items():
        reserve_states[(venue, pool)][hour] = state
    for (venue, pool, hour), deltas in deltas_by_hour.items():
        known_deltas[(venue, pool)][hour] = deltas

    clean_events: dict[PoolHourKey, list[ReserveEvent]] = {}
    state_support: dict[PoolHourKey, tuple[int, int]] = {}
    for key, events in candidate_events.items():
        venue, pool, hour = key
        prior = prior_observed_state(
            reserve_states[(venue, pool)], known_deltas[(venue, pool)], hour
        )
        if prior is None:
            continue
        expected_start, previous_hour = prior
        if not hour_is_clean(expected_start, reserves[key], deltas_by_hour[key]):
            continue
        clean_events[key] = events
        state_support[key] = (
            (hour - previous_hour) // 3600,
            len(liquidity.get(key, [])),
        )

    swaps_by_identity: dict[tuple[str, str, int], V2SwapEvent] = {}
    for events in swaps.values():
        for event in events:
            key = (event.venue, event.tx_hash, event.log_index)
            prior = swaps_by_identity.get(key)
            if prior is not None and (
                prior.pool != event.pool
                or prior.order != event.order
                or reserve_delta(prior.row) != reserve_delta(event.row)
            ):
                raise ValueError(f"conflicting V2 transaction-log event: {key}")
            swaps_by_identity[key] = event

    pair_index: dict[frozenset[str], list[PoolKey]] = defaultdict(list)
    clean_pool_keys = {(venue, pool) for venue, pool, _hour in clean_events}
    for pool_key, pool_meta in meta.items():
        if pool_key in clean_pool_keys:
            pair_index[frozenset((pool_meta.token0, pool_meta.token1))].append(pool_key)
    return V2ReplayDay(
        meta=meta,
        pool_hour_events=clean_events,
        state_support=state_support,
        swaps_by_pool_hour={key: sorted(value, key=lambda event: event.order) for key, value in swaps.items()},
        swaps_by_identity=swaps_by_identity,
        pair_index={key: sorted(value) for key, value in pair_index.items()},
    )
