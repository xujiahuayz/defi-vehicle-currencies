"""Best one- and two-leg paths on a replayed concentrated-liquidity opportunity set."""

from __future__ import annotations

from dataclasses import dataclass

from ddvc.pricing.tick_quote import quote_tick_state
from ddvc.pricing.tick_state import TickPoolState


PoolIndex = dict[frozenset[str], list[tuple[str, str]]]


@dataclass(frozen=True)
class TickPathQuote:
    amount_out: float
    vehicle: str | None
    venues: tuple[str, ...]
    pools: tuple[str, ...]
    price_impacts: tuple[float, ...]


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
) -> TickPathQuote | None:
    """Return the highest-output supported single pool, with deterministic ties."""
    candidates = pool_index.get(frozenset((token_in, token_out)), [])
    best: TickPathQuote | None = None
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
        candidate = TickPathQuote(
            amount_out=quote.amount_out,
            vehicle=None,
            venues=(venue,),
            pools=(pool_id,),
            price_impacts=(quote.price_impact,),
        )
        if best is None or candidate.amount_out > best.amount_out:
            best = candidate
    return best


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
) -> TickPathQuote | None:
    """Return the best sequential two-leg path through one fixed vehicle."""
    if vehicle in (token_in, token_out):
        return None
    first = best_tick_leg(
        token_in,
        vehicle,
        amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    if first is None:
        return None
    second = best_tick_leg(
        vehicle,
        token_out,
        first.amount_out,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    if second is None:
        return None
    return TickPathQuote(
        amount_out=second.amount_out,
        vehicle=vehicle,
        venues=first.venues + second.venues,
        pools=first.pools + second.pools,
        price_impacts=first.price_impacts + second.price_impacts,
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
) -> TickPathQuote | None:
    """Return the best direct or prespecified one-vehicle path."""
    best = best_tick_leg(
        token_in,
        token_out,
        amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_price_impact,
    )
    for vehicle in vehicles:
        candidate = best_tick_vehicle_path(
            token_in,
            token_out,
            vehicle,
            amount_in,
            pool_index=pool_index,
            states_by_venue=states_by_venue,
            ticks_by_venue=ticks_by_venue,
            allowed_venues=allowed_venues,
            max_price_impact=max_price_impact,
        )
        if candidate is not None and (
            best is None or candidate.amount_out > best.amount_out
        ):
            best = candidate
    return best
