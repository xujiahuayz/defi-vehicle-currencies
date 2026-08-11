"""Canonical consumer-required raw source and stream perimeter."""

from __future__ import annotations

from ddvc.fetch.pool_daily import POOL_DAILY_SCHEMAS
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import DEX_SOURCES, ROUTE_SOURCE_FAMILIES, get_source
from ddvc.state_data import FAMILY_STREAMS


def consumer_required_streams() -> dict[str, frozenset[str]]:
    required: dict[str, set[str]] = {
        venue: {"swaps"} for venue in ROUTE_SOURCE_FAMILIES
    }
    for venues in FAMILY_STREAMS.values():
        for venue, specifications in venues.items():
            required.setdefault(venue, set()).update(
                stream for stream, _kind, _sign in specifications
            )
    for venue in POOL_DAILY_SCHEMAS:
        required.setdefault(venue, set()).add("daily")
    if unknown := sorted(set(required).difference(DEX_SOURCES)):
        raise RuntimeError(f"raw consumer registry names unknown sources: {unknown}")
    for venue, streams in required.items():
        source = get_source(venue)
        available = (
            {"swaps", "daily"}
            if source.backend == "dune"
            else {entity.stream for entity in get_schema(source.schema).entities}
        )
        if unavailable := sorted(streams.difference(available)):
            raise RuntimeError(
                f"raw consumer registry names unavailable {venue} streams: {unavailable}"
            )
    return {venue: frozenset(streams) for venue, streams in required.items()}
