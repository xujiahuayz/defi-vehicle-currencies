"""Causal day replay for concentrated-liquidity venues."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ddvc.pricing.tick_frontier import PoolIndex, TickQuoteIndexes
from ddvc.pricing.tick_state import TickPoolState, absorb_swap_state, apply_tick_change
from ddvc.source_records import block_value, source_event_payload, transaction_id
from ddvc.state_data import RAW_ROOT, read_tick_partition, tick_partition_path


TICK_VENUES = ("uniswap_v3", "uniswap_v4")


@dataclass(frozen=True)
class TickReplayEvent:
    order: tuple[int, int]
    venue: str
    kind: str
    row: dict
    sign: int = 0


def chain_order(row: dict) -> tuple[int, int] | None:
    """Exact on-chain order; rows without a block number are not replayable."""
    try:
        block = int(block_value(row) or 0)
        log_index = int(row.get("logIndex") or 0)
    except (TypeError, ValueError):
        return None
    return (block, log_index) if block > 0 else None


def _plain(value: object) -> object | None:
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def canonical_tick_row(record: dict) -> dict:
    """Adapt one canonical record to the pricing domain object used by tick math."""
    token0 = {
        "id": _plain(record.get("token0_raw")),
        "symbol": _plain(record.get("symbol0")),
        "decimals": _plain(record.get("decimals0")),
    }
    token1 = {
        "id": _plain(record.get("token1_raw")),
        "symbol": _plain(record.get("symbol1")),
        "decimals": _plain(record.get("decimals1")),
    }
    pool = {
        "id": _plain(record.get("pool")),
        "token0": token0,
        "token1": token1,
        "feeTier": _plain(record.get("fee_pips")),
        "tickSpacing": _plain(record.get("tick_spacing")),
        "hooks": _plain(record.get("hooks")),
    }
    tx_hash = _plain(record.get("tx_hash"))
    block = _plain(record.get("block_number"))
    timestamp = _plain(record.get("timestamp"))
    return {
        "id": _plain(record.get("event_id")),
        "transaction": {
            "id": tx_hash,
            "blockNumber": block,
            "timestamp": timestamp,
        },
        "timestamp": timestamp,
        "logIndex": _plain(record.get("log_index")),
        "pool": pool,
        "amount0": _plain(record.get("amount0")),
        "amount1": _plain(record.get("amount1")),
        "sqrtPriceX96": _plain(record.get("sqrt_price_x96")),
        "tick": _plain(record.get("tick")),
        "amount": _plain(record.get("liquidity_delta")),
        "tickLower": _plain(record.get("tick_lower")),
        "tickUpper": _plain(record.get("tick_upper")),
    }


def _same_chain_event(left: TickReplayEvent, right: TickReplayEvent) -> bool:
    """Identify duplicate source entities for one on-chain log."""
    if (
        left.venue != right.venue
        or left.kind != right.kind
        or left.sign != right.sign
        or transaction_id(left.row) is None
        or transaction_id(left.row) != transaction_id(right.row)
    ):
        return False
    return source_event_payload(left.row) == source_event_payload(right.row)


def load_tick_day_events(
    state_root: Path,
    day: str,
    *,
    venues: tuple[str, ...] = TICK_VENUES,
    raw_root: Path = RAW_ROOT,
) -> list[TickReplayEvent]:
    """Load and globally order one canonical day's swaps and liquidity changes."""
    events: list[TickReplayEvent] = []
    for venue in venues:
        if not tick_partition_path(venue, day, root=state_root).exists():
            continue
        for record in read_tick_partition(
            venue, day, root=state_root, raw_root=raw_root
        ).to_dict("records"):
            row = canonical_tick_row(record)
            order = chain_order(row)
            if order is None:
                raise ValueError(f"canonical tick record lacks causal order: {venue} {day}")
            kind = str(record["record_type"])
            events.append(TickReplayEvent(order, venue, kind, row, 1 if kind == "liquidity" else 0))
    events.sort(
        key=lambda event: (
            event.order,
            0 if event.kind == "liquidity" else 1,
            event.venue,
        )
    )
    unique: list[TickReplayEvent] = []
    for event in events:
        if unique and unique[-1].order == event.order:
            prior = unique[-1]
            if (
                prior.venue == event.venue
                and prior.kind == event.kind
                and prior.sign == event.sign
                and prior.row == event.row
            ) or _same_chain_event(prior, event):
                continue
            raise ValueError(f"conflicting tick events at block-log {event.order}")
        unique.append(event)
    return unique


@dataclass
class TickReplayState:
    """Mutable tick maps, latest swap states and pool-pair index for one replay."""

    unify_wrapped: bool = True
    ticks_by_venue: dict[str, dict[str, dict[int, int]]] = field(default_factory=dict)
    states_by_venue: dict[str, dict[str, TickPoolState]] = field(default_factory=dict)
    pool_index: PoolIndex = field(default_factory=dict)
    quote_indexes_by_venue: TickQuoteIndexes = field(default_factory=dict)
    swap_samples: dict[str, list[dict]] = field(default_factory=dict)
    token_decimals: dict[str, int] = field(default_factory=dict)
    quarantined_pools: dict[str, set[str]] = field(default_factory=dict)

    def apply_liquidity(self, venue: str, row: dict, *, sign: int) -> None:
        ticks = self.ticks_by_venue.setdefault(venue, {})
        pool = str((row.get("pool") or {}).get("id") or "").lower()
        if not pool or pool in self.quarantined_pools.get(venue, set()):
            return
        apply_tick_change(ticks.setdefault(pool, {}), row, sign=sign)
        self.quote_indexes_by_venue.setdefault(venue, {}).pop(pool, None)

    def apply_swap(self, venue: str, row: dict) -> None:
        # Exact-state replay must never compare a Unix timestamp with an Ethereum
        # block height. Some legacy V4 rows have only a scalar transaction hash;
        # they can identify a swap, but cannot establish its causal chain order.
        if chain_order(row) is None:
            return
        states = self.states_by_venue.setdefault(venue, {})
        pool = str((row.get("pool") or {}).get("id") or "").lower()
        if not pool:
            return
        prior = states.get(pool)
        absorb_swap_state(
            venue,
            row,
            states,
            swap_samples=self.swap_samples,
            token_decimals=self.token_decimals,
            quarantined_pools=self.quarantined_pools,
            unify_wrapped=self.unify_wrapped,
        )
        if pool in self.quarantined_pools.get(venue, set()):
            removed = states.pop(pool, None) or prior
            self.ticks_by_venue.setdefault(venue, {}).pop(pool, None)
            self.quote_indexes_by_venue.setdefault(venue, {}).pop(pool, None)
            self.swap_samples.pop(pool, None)
            if removed is not None:
                key = frozenset((removed.token0, removed.token1))
                candidates = self.pool_index.get(key, [])
                if (venue, pool) in candidates:
                    candidates.remove((venue, pool))
                if not candidates:
                    self.pool_index.pop(key, None)
            return
        current = states.get(pool)
        if prior is None and current is not None:
            key = frozenset((current.token0, current.token1))
            entry = (venue, pool)
            candidates = self.pool_index.setdefault(key, [])
            if entry not in candidates:
                candidates.append(entry)
                candidates.sort()

    def apply(self, event: TickReplayEvent) -> None:
        if event.kind == "liquidity":
            self.apply_liquidity(event.venue, event.row, sign=event.sign)
        else:
            self.apply_swap(event.venue, event.row)

    def apply_all(self, events: list[TickReplayEvent]) -> None:
        for event in events:
            self.apply(event)


def warm_tick_day(
    state_root: Path,
    day: str,
    replay: TickReplayState,
    *,
    venues: tuple[str, ...] = TICK_VENUES,
    raw_root: Path = RAW_ROOT,
) -> None:
    """Stream one canonical non-target day into end-of-day state."""
    replay.apply_all(
        load_tick_day_events(state_root, day, venues=venues, raw_root=raw_root)
    )
