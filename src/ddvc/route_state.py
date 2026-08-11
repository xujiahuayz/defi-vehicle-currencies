"""Released canonical market-state boundary for route-cost construction.

Route-cost code may discover realised routes from the unified route panel, but it
must never reconstruct quote state from provider rows.  This module is the narrow
adapter from node-D's released, reconciliation-aware state partitions to the two
state shapes the route quoter needs: end-of-hour constant-product snapshots and
globally ordered concentrated-liquidity events bucketed by UTC hour.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

import pandas as pd

from ddvc.data_release import MARKET_STATE_QUALITY_PANEL
from ddvc.graph_event_order import correction_root_for_graph
from ddvc.pricing.tick_replay import TICK_VENUES, TickReplayEvent, load_tick_day_events
from ddvc.provenance import sidecar_path
from ddvc.state_data import (
    RAW_ROOT,
    STATE_ROOT,
    cp_partition_path,
    state_quality_path,
    read_cp_partition,
)
from ddvc.v2_event_completeness import (
    V2_EVENT_SOURCE_CURRENT,
    resolve_v2_event_source_release,
)
from ddvc.v4_quarantine import V4_STATIC_QUARANTINE_PANEL


CP_QUOTE_VENUES = ("uniswap_v2", "sushiswap_v2")


@dataclass(frozen=True)
class ConstantProductQuoteState:
    """One released pool state at the end of an exact UTC hour."""

    venue: str
    pool: str
    token0: str
    token1: str
    symbol0: str
    symbol1: str
    decimals0: int
    decimals1: int
    reserve0: float
    reserve1: float


@dataclass(frozen=True)
class TickStateCut:
    """One explicit temporal convention for ordered tick-state replay."""

    kind: Literal["hour_end", "strict_before_event"]
    timestamp_exclusive: int | None = None
    order_exclusive: tuple[int, int] | None = None

    @classmethod
    def hour_end(cls, timestamp_exclusive: int) -> "TickStateCut":
        return cls("hour_end", timestamp_exclusive=int(timestamp_exclusive))

    @classmethod
    def strict_before_event(cls, order: tuple[int, int]) -> "TickStateCut":
        return cls("strict_before_event", order_exclusive=order)


def _event_timestamp(event: TickReplayEvent) -> int:
    return int(
        (event.row.get("transaction") or {}).get("timestamp")
        or event.row.get("timestamp")
        or 0
    )


@dataclass
class OrderedTickStateCursor:
    """Apply a canonical event sequence once, preserving exact block-log order."""

    events: tuple[TickReplayEvent, ...]
    position: int = 0

    def __post_init__(self) -> None:
        orders = [event.order for event in self.events]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise ValueError("tick quote events are not uniquely ordered by block-log")
        timestamps = [_event_timestamp(event) for event in self.events]
        if any(value <= 0 for value in timestamps) or timestamps != sorted(timestamps):
            raise ValueError("tick quote event timestamps are not positive and monotone")

    def apply_until(self, replay, cut: TickStateCut) -> int:
        """Advance through one exclusive cut and return the number applied."""

        if cut.kind == "hour_end":
            if cut.timestamp_exclusive is None or cut.order_exclusive is not None:
                raise ValueError("hour-end cut requires one exclusive timestamp")
            eligible = lambda event: _event_timestamp(event) < cut.timestamp_exclusive
        elif cut.kind == "strict_before_event":
            if cut.order_exclusive is None or cut.timestamp_exclusive is not None:
                raise ValueError("strict event cut requires one exclusive block-log order")
            eligible = lambda event: event.order < cut.order_exclusive
        else:
            raise ValueError(f"unsupported tick state cut: {cut.kind}")
        start = self.position
        while self.position < len(self.events) and eligible(self.events[self.position]):
            replay.apply(self.events[self.position])
            self.position += 1
        return self.position - start

    def require_consumed(self) -> None:
        if self.position != len(self.events):
            event = self.events[self.position]
            raise ValueError(f"tick quote event remains beyond final cut: {event.order}")

    def apply_remaining(self, replay) -> int:
        start = self.position
        while self.position < len(self.events):
            replay.apply(self.events[self.position])
            self.position += 1
        return self.position - start


def released_state_lineage_inputs(
    *,
    state_root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
) -> list[Path]:
    """Return every released-state ancestor that can change a route quote.

    The materialised tree covers exact state and its per-partition quality
    markers.  The correction tree is also explicit: changing a reconciliation
    invalidates a quote generation immediately, while node D separately refuses
    stale materialisations.  Certificates and their provenance records are
    included so a certificate replacement cannot inherit an earlier cache.
    """

    event_source_inputs = [V2_EVENT_SOURCE_CURRENT]
    if V2_EVENT_SOURCE_CURRENT.is_file():
        event_source_inputs = list(resolve_v2_event_source_release().lineage_paths)
    certificates = [
        MARKET_STATE_QUALITY_PANEL,
        V4_STATIC_QUARANTINE_PANEL,
        *event_source_inputs,
    ]
    return [
        state_root,
        correction_root_for_graph(raw_root),
        *certificates,
        *(sidecar_path(path) for path in (MARKET_STATE_QUALITY_PANEL, V4_STATIC_QUARANTINE_PANEL)),
    ]


def load_cp_quote_states_by_hour(
    day: str,
    hours: tuple[int, ...],
    *,
    state_root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
    venues: tuple[str, ...] = CP_QUOTE_VENUES,
) -> dict[int, list[ConstantProductQuoteState]]:
    """Load released end-of-hour V2-family states in bounded day memory."""

    day_start = int(
        pd.Timestamp(
            f"{day[:4]}-{day[4:6]}-{day[6:]} 00:00:00", tz="UTC"
        ).timestamp()
    )
    requested = {day_start + hour * 3600: hour for hour in hours}
    states: dict[int, list[ConstantProductQuoteState]] = {
        hour: [] for hour in hours
    }
    observed: set[tuple[str, str, int]] = set()
    for venue in venues:
        path = cp_partition_path(venue, day, root=state_root)
        if not path.exists():
            continue
        frame = read_cp_partition(
            venue,
            day,
            root=state_root,
            raw_root=raw_root,
        )
        snapshots = frame.loc[
            frame["record_type"].eq("snapshot")
            & frame["quote_supported"].astype(bool)
            & frame["period_start"].isin(requested)
        ]
        for row in snapshots.to_dict("records"):
            hour = requested[int(row["period_start"])]
            key = (venue, str(row["pool"]), hour)
            if key in observed:
                raise ValueError(f"duplicate canonical quote state: {key}")
            observed.add(key)
            states[hour].append(
                ConstantProductQuoteState(
                    venue=venue,
                    pool=str(row["pool"]).lower(),
                    token0=str(row["token0"]).lower(),
                    token1=str(row["token1"]).lower(),
                    symbol0=str(row.get("symbol0") or ""),
                    symbol1=str(row.get("symbol1") or ""),
                    decimals0=int(row["decimals0"]),
                    decimals1=int(row["decimals1"]),
                    reserve0=float(row["reserve0"]),
                    reserve1=float(row["reserve1"]),
                )
            )
    return states


def load_tick_quote_events(
    day: str,
    *,
    state_root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
    venues: tuple[str, ...] = TICK_VENUES,
) -> tuple[TickReplayEvent, ...]:
    """Load one bounded canonical day without discarding block-log interleaving."""

    events = tuple(
        load_tick_day_events(
            state_root,
            day,
            venues=venues,
            raw_root=raw_root,
        )
    )
    start = int(
        pd.Timestamp(
            f"{day[:4]}-{day[4:6]}-{day[6:]} 00:00:00", tz="UTC"
        ).timestamp()
    )
    end = start + 86400
    outside = [event.order for event in events if not start <= _event_timestamp(event) < end]
    if outside:
        raise ValueError(f"canonical tick event falls outside its UTC day: {day}/{outside[0]}")
    return events


def day_state_quality_fingerprints(
    day: str,
    *,
    state_root: Path = STATE_ROOT,
    families: tuple[tuple[str, str], ...] = (
        ("constant_product", "uniswap_v2"),
        ("constant_product", "sushiswap_v2"),
        ("tick", "uniswap_v3"),
        ("tick", "uniswap_v4"),
    ),
) -> dict[str, str]:
    """Bind a route-day marker to every available canonical quality identity."""

    fingerprints: dict[str, str] = {}
    for family, venue in families:
        marker = state_quality_path(family, venue, day, root=state_root)
        if not marker.exists():
            continue
        record = json.loads(marker.read_text(encoding="utf-8"))
        if not bool(record.get("passed")) or not record.get("input_fingerprint"):
            raise ValueError(f"unreleased canonical state marker: {family}/{venue}/{day}")
        fingerprints[f"{family}/{venue}"] = str(record["input_fingerprint"])
    return fingerprints
