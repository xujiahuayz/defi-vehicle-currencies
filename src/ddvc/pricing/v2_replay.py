"""Exact within-hour reserve replay for V2-style constant-product venues."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ddvc.cpquote import (
    ReserveEvent,
    hour_is_clean,
    ordered_reserve_events,
    prior_observed_state,
    reserve_state_before,
)
from ddvc.state_data import RAW_ROOT, cp_partition_path, read_cp_partition


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
    """Net reserve change from one canonical V2 swap row."""
    return Decimal(str(row["amount0_delta"])), Decimal(str(row["amount1_delta"]))


def _read_reserves(
    frame,
    venue: str,
    reserves: dict[PoolHourKey, tuple[Decimal, Decimal]],
    meta: dict[PoolKey, V2PoolMeta],
    *,
    latest_only: bool,
) -> None:
    latest: dict[str, tuple[int, tuple[Decimal, Decimal], V2PoolMeta]] = {}
    snapshots = frame[frame["record_type"].eq("snapshot")]
    for row in snapshots.to_dict("records"):
        pool = str(row.get("pool") or "").lower()
        try:
            hour = int(row["period_start"])
            state = (Decimal(str(row["reserve0"])), Decimal(str(row["reserve1"])))
            token0 = str(row["token0"]).lower()
            token1 = str(row["token1"]).lower()
        except (InvalidOperation, KeyError, TypeError, ValueError):
            continue
        if not pool or not token0 or not token1:
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
    state_root: Path,
    day: str,
    *,
    venues: tuple[str, ...] = V2_VENUES,
    raw_root: Path = RAW_ROOT,
) -> V2ReplayDay:
    """Load and validate every reconstructable canonical V2 pool-hour for ``day``."""
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
        previous_frame = (
            read_cp_partition(venue, previous_day, root=state_root, raw_root=raw_root)
            if cp_partition_path(venue, previous_day, root=state_root).exists()
            else None
        )
        day_frame = (
            read_cp_partition(venue, day, root=state_root, raw_root=raw_root)
            if cp_partition_path(venue, day, root=state_root).exists()
            else None
        )
        if previous_frame is not None:
            _read_reserves(previous_frame, venue, reserves, meta, latest_only=True)
        if day_frame is None:
            continue
        _read_reserves(day_frame, venue, reserves, meta, latest_only=False)
        for row in day_frame[day_frame["record_type"].eq("swap")].to_dict("records"):
            pool = str(row.get("pool") or "").lower()
            try:
                timestamp = int(row["timestamp"])
                log_index = int(row["log_index"])
                order = (int(row["block_number"]), log_index)
            except (InvalidOperation, KeyError, TypeError, ValueError):
                continue
            tx_hash = str(row.get("tx_hash") or "").lower()
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
        for row in day_frame[day_frame["record_type"].eq("liquidity")].to_dict("records"):
            pool = str(row.get("pool") or "").lower()
            try:
                timestamp = int(row["timestamp"])
                order = (int(row["block_number"]), int(row["log_index"]))
                delta = (
                    Decimal(str(row["amount0_delta"])),
                    Decimal(str(row["amount1_delta"])),
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
