"""Causal day replay for concentrated-liquidity venues."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

from ddvc.fetch.raw import timestamp_value
from ddvc.pricing.tick_frontier import PoolIndex
from ddvc.pricing.tick_state import TickPoolState, absorb_swap_state, apply_tick_change


TICK_LIQUIDITY_STREAMS: dict[str, tuple[tuple[str, int], ...]] = {
    "uniswap_v3": (("mints", 1), ("burns", -1)),
    "uniswap_v4": (("modify_liquidities", 1),),
}


@dataclass(frozen=True)
class TickReplayEvent:
    order: tuple[int, int]
    venue: str
    kind: str
    row: dict
    sign: int = 0


def timestamp_order(row: dict) -> tuple[int, int] | None:
    """Comparable chain order across V3 and V4 when V4 omits block number."""
    try:
        timestamp = int(timestamp_value(row) or 0)
        log_index = int(row.get("logIndex") or 0)
    except (TypeError, ValueError):
        return None
    return (timestamp, log_index) if timestamp > 0 else None


def _raw_path(raw_root: Path, venue: str, stream: str, day: str) -> Path:
    return raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"


def _load_stream(
    raw_root: Path,
    venue: str,
    stream: str,
    day: str,
    *,
    kind: str,
    sign: int = 0,
) -> list[TickReplayEvent]:
    path = _raw_path(raw_root, venue, stream, day)
    if not path.exists():
        return []
    events: list[TickReplayEvent] = []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            order = timestamp_order(row)
            if order is not None:
                events.append(TickReplayEvent(order, venue, kind, row, sign))
    return events


def load_tick_day_events(
    raw_root: Path,
    day: str,
    *,
    venues: tuple[str, ...] = ("uniswap_v3", "uniswap_v4"),
) -> list[TickReplayEvent]:
    """Load and globally order one day's swaps and liquidity changes."""
    events: list[TickReplayEvent] = []
    for venue in venues:
        for stream, sign in TICK_LIQUIDITY_STREAMS[venue]:
            events.extend(
                _load_stream(
                    raw_root,
                    venue,
                    stream,
                    day,
                    kind="liquidity",
                    sign=sign,
                )
            )
        events.extend(
            _load_stream(raw_root, venue, "swaps", day, kind="swap")
        )
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
            ):
                continue
            raise ValueError(f"conflicting tick events at timestamp-log {event.order}")
        unique.append(event)
    return unique


@dataclass
class TickReplayState:
    """Mutable tick maps, latest swap states and pool-pair index for one replay."""

    unify_wrapped: bool = True
    ticks_by_venue: dict[str, dict[str, dict[int, int]]] = field(default_factory=dict)
    states_by_venue: dict[str, dict[str, TickPoolState]] = field(default_factory=dict)
    pool_index: PoolIndex = field(default_factory=dict)
    swap_samples: dict[str, list[dict]] = field(default_factory=dict)

    def apply(self, event: TickReplayEvent) -> None:
        ticks = self.ticks_by_venue.setdefault(event.venue, {})
        states = self.states_by_venue.setdefault(event.venue, {})
        pool = str((event.row.get("pool") or {}).get("id") or "").lower()
        if not pool:
            return
        if event.kind == "liquidity":
            apply_tick_change(
                ticks.setdefault(pool, {}),
                event.row,
                sign=event.sign,
            )
            return
        prior = states.get(pool)
        absorb_swap_state(
            event.venue,
            event.row,
            states,
            swap_samples=self.swap_samples,
            unify_wrapped=self.unify_wrapped,
        )
        current = states.get(pool)
        if prior is None and current is not None:
            key = frozenset((current.token0, current.token1))
            entry = (event.venue, pool)
            candidates = self.pool_index.setdefault(key, [])
            if entry not in candidates:
                candidates.append(entry)
                candidates.sort()

    def apply_all(self, events: list[TickReplayEvent]) -> None:
        for event in events:
            self.apply(event)
