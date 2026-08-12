"""Causal day replay for concentrated-liquidity venues."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from ddvc.pricing.tick_frontier import PoolIndex, TickQuoteIndexes, build_pool_index
from ddvc.asset_types import canonical_token
from ddvc.fetch.sources import get_source
from ddvc.pricing.tick_state import TickPoolState, absorb_swap_state, apply_tick_change
from ddvc.source_records import block_value, source_event_payload, transaction_id, v4_quote_status
from ddvc.state_data import RAW_ROOT, normalise_tick_partition, read_tick_partition, tick_partition_path, tick_scientific_support


TICK_VENUES = ("uniswap_v3", "uniswap_v4")


@dataclass(frozen=True)
class TickReplayEvent:
    order: tuple[int, int]
    venue: str
    kind: str
    row: dict
    sign: int = 0


def chain_order(row: dict) -> tuple[int, int] | None:
    """Exact on-chain order; both block and log index must be explicit."""
    try:
        block = int(block_value(row) or 0)
        raw_log_index = row.get("logIndex")
        if raw_log_index is None or bool(pd.isna(raw_log_index)):
            return None
        log_index = int(raw_log_index)
    except (TypeError, ValueError):
        return None
    return (block, log_index) if block > 0 and log_index >= 0 else None


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
    quote_unsupported_reason = _plain(record.get("quote_unsupported_reason"))
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
        "quoteUnsupportedReason": quote_unsupported_reason,
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
    state_root: Path | None,
    day: str,
    *,
    venues: tuple[str, ...] = TICK_VENUES,
    raw_root: Path = RAW_ROOT,
) -> list[TickReplayEvent]:
    """Load and globally order one canonical day's swaps and liquidity changes."""
    events: list[TickReplayEvent] = []
    selected_date = datetime.strptime(day, "%Y%m%d").date()
    for venue in venues:
        if state_root is None and selected_date < get_source(venue).genesis:
            continue
        partition_exists = state_root is None or tick_partition_path(venue, day, root=state_root).exists()
        if venue == "uniswap_v4":
            try:
                scientifically_supported = tick_scientific_support(raw_root, venue, day)
            except FileNotFoundError:
                if not partition_exists:
                    continue
                raise
            if not scientifically_supported:
                frame = read_tick_partition(venue, day, root=state_root, raw_root=raw_root) if partition_exists else pd.DataFrame()
                if not frame.empty:
                    raise ValueError(f"unsupported V4 day carries canonical tick state: {day}")
                timestamp = int(pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]} 00:00:00", tz="UTC").timestamp())
                events.append(TickReplayEvent((0, 0), venue, "scientific_support_end", {"timestamp": timestamp, "transaction": {"timestamp": timestamp}}))
                continue
        if not partition_exists:
            continue
        if state_root is None:
            frame, quality = normalise_tick_partition(raw_root, venue, day)
            if not quality.passed:
                raise ValueError(
                    f"tick exact-event contract failed: {venue}/{day}; "
                    f"missing_streams={quality.missing_required_streams}; "
                    f"conflicts={quality.conflicting_events}"
                )
        else:
            frame = read_tick_partition(venue, day, root=state_root, raw_root=raw_root)
        for record in frame.to_dict("records"):
            row = canonical_tick_row(record)
            order = chain_order(row)
            if order is None:
                raise ValueError(f"canonical tick record lacks causal order: {venue} {day}")
            kind = str(record["record_type"])
            events.append(TickReplayEvent(order, venue, kind, row, 1 if kind == "liquidity" else 0))
    events.sort(
        key=lambda event: (
            event.order,
            {"scientific_support_end": 0, "initialize": 1, "liquidity": 2, "swap": 3}.get(event.kind, 4),
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
    initialization_status_by_venue: dict[str, dict[str, str]] = field(default_factory=dict)
    scientifically_unsupported_venues: set[str] = field(default_factory=set)

    def rebuild_derived_indexes(self) -> None:
        """Rebuild quote-discovery state from the causal replay state."""
        self.pool_index = build_pool_index(self.states_by_venue)
        for candidates in self.pool_index.values():
            candidates.sort()
        self.quote_indexes_by_venue = {}

    def close_scientific_support(self, venue: str) -> None:
        """Purge one venue when its certified exact-state prefix ends."""

        unsupported = getattr(self, "scientifically_unsupported_venues", None)
        if unsupported is None:
            unsupported = set()
            self.scientifically_unsupported_venues = unsupported
        pool_ids = set(self.states_by_venue.get(venue, {})) | set(self.ticks_by_venue.get(venue, {})) | set(self.initialization_status_by_venue.get(venue, {}))
        self.states_by_venue.pop(venue, None)
        self.ticks_by_venue.pop(venue, None)
        self.quote_indexes_by_venue.pop(venue, None)
        self.initialization_status_by_venue.pop(venue, None)
        self.quarantined_pools.pop(venue, None)
        for pool in pool_ids:
            self.swap_samples.pop(pool, None)
        unsupported.add(venue)
        self.rebuild_derived_indexes()

    def apply_liquidity(self, venue: str, row: dict, *, sign: int) -> None:
        ticks = self.ticks_by_venue.setdefault(venue, {})
        pool = str((row.get("pool") or {}).get("id") or "").lower()
        if not pool or pool in self.quarantined_pools.get(venue, set()):
            return
        status = self.initialization_status_by_venue.get(venue, {}).get(pool)
        if status is None:
            raise ValueError(f"liquidity event precedes certified Initialize: {venue}/{pool}")
        if status != "quote_supported":
            return
        apply_tick_change(ticks.setdefault(pool, {}), row, sign=sign)
        self.quote_indexes_by_venue.setdefault(venue, {}).pop(pool, None)

    def apply_initialize(self, venue: str, row: dict) -> None:
        """Create exact pool state before any liquidity change or Swap can consume it."""

        order = chain_order(row)
        pool_data = row.get("pool") or {}
        pool = str(pool_data.get("id") or "").lower()
        if order is None or not pool:
            raise ValueError(f"certified Initialize lacks causal identity: {venue}/{pool}")
        statuses = self.initialization_status_by_venue.setdefault(venue, {})
        if pool in statuses:
            raise ValueError(f"pool has more than one certified Initialize: {venue}/{pool}")
        token0, token1 = pool_data.get("token0") or {}, pool_data.get("token1") or {}
        raw0, raw1 = str(token0.get("id") or "").lower(), str(token1.get("id") or "").lower()
        explicit_reason = str(row.get("quoteUnsupportedReason") or "")
        if explicit_reason == "unknown_token_metadata":
            statuses[pool] = "unsupported:unknown_token_metadata"
            return
        try:
            decimals = (int(token0["decimals"]), int(token1["decimals"]))
            fee_pips = int(pool_data["feeTier"])
            tick_spacing = int(pool_data["tickSpacing"])
            sqrt_price_x96 = int(row["sqrtPriceX96"])
            tick = int(row["tick"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"certified Initialize lacks exact state statics: {venue}/{pool}") from error
        if not raw0 or not raw1 or any(value < 0 or value > 36 for value in decimals) or sqrt_price_x96 <= 0 or tick_spacing <= 0:
            raise ValueError(f"certified Initialize has invalid state statics: {venue}/{pool}")
        reason = v4_quote_status(row) if venue == "uniswap_v4" else "vanilla_static_fee"
        if venue == "uniswap_v4" and reason != "vanilla_static_fee":
            statuses[pool] = f"unsupported:{reason}"
            return
        canonical0 = canonical_token(raw0, unify_wrapped=self.unify_wrapped)
        canonical1 = canonical_token(raw1, unify_wrapped=self.unify_wrapped)
        state = TickPoolState(
            pool=pool,
            token0=canonical0,
            token1=canonical1,
            sym0=str(token0.get("symbol") or ""),
            sym1=str(token1.get("symbol") or ""),
            dec0=decimals[0],
            dec1=decimals[1],
            sqrt_price_x96=sqrt_price_x96,
            tick=tick,
            fee_pips=fee_pips,
            tick_spacing=tick_spacing,
            block=order[0],
            log_index=order[1],
        )
        self.states_by_venue.setdefault(venue, {})[pool] = state
        self.ticks_by_venue.setdefault(venue, {}).setdefault(pool, {})
        statuses[pool] = "quote_supported"
        key = frozenset((canonical0, canonical1))
        entry = (venue, pool)
        candidates = self.pool_index.setdefault(key, [])
        if entry not in candidates:
            candidates.append(entry)
            candidates.sort()
        self.token_decimals[raw0], self.token_decimals[raw1] = decimals

    def apply_swap(self, venue: str, row: dict) -> None:
        # Exact-state replay never substitutes a Unix timestamp for an Ethereum block height; a scalar transaction hash identifies a legacy V4 swap but cannot establish causal chain order.
        if chain_order(row) is None:
            return
        states = self.states_by_venue.setdefault(venue, {})
        pool = str((row.get("pool") or {}).get("id") or "").lower()
        if not pool:
            return
        prior = states.get(pool)
        if pool not in self.initialization_status_by_venue.get(venue, {}):
            raise ValueError(f"swap event precedes certified Initialize: {venue}/{pool}")
        if self.initialization_status_by_venue[venue][pool] != "quote_supported":
            return
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
        if event.kind == "scientific_support_end":
            self.close_scientific_support(event.venue)
            return
        if event.venue in getattr(self, "scientifically_unsupported_venues", set()):
            raise ValueError(f"tick event attempts to reopen closed scientific support: {event.venue}")
        if event.kind == "initialize":
            self.apply_initialize(event.venue, event.row)
        elif event.kind == "liquidity":
            self.apply_liquidity(event.venue, event.row, sign=event.sign)
        elif event.kind == "swap":
            self.apply_swap(event.venue, event.row)
        else:
            raise ValueError(f"unsupported tick replay event kind: {event.kind}")

    def apply_all(self, events: list[TickReplayEvent]) -> None:
        for event in events:
            self.apply(event)


def warm_tick_day(
    state_root: Path | None,
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
