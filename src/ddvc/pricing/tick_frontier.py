"""Best one- and two-leg paths on a replayed concentrated-liquidity opportunity set."""

from __future__ import annotations

from functools import partial

from ddvc.pricing.path_frontier import (
    LegQuote,
    PathQuote,
    best_leg,
    best_public_path,
    best_vehicle_path,
)
from ddvc.pricing.tick_quote import quote_tick_state
from ddvc.pricing.tick_state import TickPoolState


PoolIndex = dict[frozenset[str], list[tuple[str, str]]]


def build_pool_index(
    states_by_venue: dict[str, dict[str, TickPoolState]],
) -> PoolIndex:
    """Index every currently observed pool once by canonical unordered pair."""
    index: PoolIndex = {}
    for venue, states in states_by_venue.items():
        for pool_id, state in states.items():
            key = frozenset((state.token0, state.token1))
            entry = (venue, pool_id)
            if entry not in index.setdefault(key, []):
                index[key].append(entry)
    return index


def tick_leg_quotes(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    allowed_venues: set[str] | None,
    max_price_impact: float | None,
) -> list[LegQuote]:
    """Return every supported single-pool quote in deterministic identity order."""
    candidates = pool_index.get(frozenset((token_in, token_out)), [])
    quotes: list[LegQuote] = []
    for venue, pool_id in sorted(candidates):
        if allowed_venues is not None and venue not in allowed_venues:
            continue
        state = states_by_venue.get(venue, {}).get(pool_id)
        ticks = ticks_by_venue.get(venue, {}).get(pool_id)
        if state is None or ticks is None:
            continue
        quote = quote_tick_state(
            state,
            ticks,
            token_in,
            token_out,
            amount_in,
            max_price_impact=max_price_impact,
        )
        if quote is None:
            continue
        quotes.append(
            LegQuote(
                amount_out=quote.amount_out,
                venue=venue,
                pool=pool_id,
                price_impact=quote.price_impact,
            )
        )
    return quotes


def best_tick_leg(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    allowed_venues: set[str] | None,
    max_price_impact: float | None,
) -> LegQuote | None:
    """Return the highest-output supported single pool."""
    quote_legs = partial(
        tick_leg_quotes,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    return best_leg(token_in, token_out, amount_in, quote_legs=quote_legs)


def best_tick_vehicle_path(
    token_in: str,
    token_out: str,
    vehicle: str,
    amount_in: float,
    *,
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    allowed_venues: set[str] | None,
    max_price_impact: float | None,
) -> PathQuote | None:
    """Return the best sequential two-leg path through one fixed vehicle."""
    quote_legs = partial(
        tick_leg_quotes,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    return best_vehicle_path(
        token_in,
        token_out,
        vehicle=vehicle,
        amount_in=amount_in,
        quote_legs=quote_legs,
    )


def best_tick_public_path(
    token_in: str,
    token_out: str,
    vehicles: list[str] | tuple[str, ...],
    amount_in: float,
    *,
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    allowed_venues: set[str] | None,
    max_price_impact: float | None,
) -> PathQuote | None:
    """Return the best direct or prespecified one-vehicle path."""
    quote_legs = partial(
        tick_leg_quotes,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    return best_public_path(
        token_in,
        token_out,
        vehicles,
        amount_in,
        quote_legs=quote_legs,
    )
