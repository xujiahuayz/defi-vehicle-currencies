"""Unified exact-state path quotes across V2, V3, and V4 venue families."""

from __future__ import annotations

from dataclasses import dataclass

from ddvc.pricing.path_frontier import LegQuote, PathQuote
from ddvc.pricing.tick_frontier import (
    PoolIndex,
    TickQuoteIndexes,
    quote_tick_pool,
    tick_leg_quotes,
)
from ddvc.pricing.tick_state import TickPoolState
from ddvc.pricing.v2_frontier import quote_v2_pool, v2_leg_quotes
from ddvc.pricing.v2_replay import ChainOrder, V2ReplayDay, V2_VENUES


@dataclass
class MixedFrontierState:
    """All state needed to quote one transaction-time opportunity set."""

    tick_pool_index: PoolIndex
    tick_states_by_venue: dict[str, dict[str, TickPoolState]]
    tick_ticks_by_venue: dict[str, dict[str, dict[int, int]]]
    tick_quote_indexes_by_venue: TickQuoteIndexes
    v2_replay: V2ReplayDay | None
    v2_hour: int | None
    v2_order: ChainOrder | None


def quote_mixed_pool(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    venue: str,
    pool_id: str,
    state: MixedFrontierState,
    max_support: float | None,
) -> LegQuote | None:
    """Dispatch one identified pool quote to its canonical venue adapter."""
    if venue in V2_VENUES:
        if state.v2_replay is None or state.v2_hour is None or state.v2_order is None:
            return None
        return quote_v2_pool(
            token_in,
            token_out,
            amount_in,
            venue=venue,
            pool_id=pool_id,
            hour=state.v2_hour,
            order=state.v2_order,
            replay=state.v2_replay,
            max_input_to_reserve=max_support,
        )
    return quote_tick_pool(
        token_in,
        token_out,
        amount_in,
        venue=venue,
        pool_id=pool_id,
        states_by_venue=state.tick_states_by_venue,
        ticks_by_venue=state.tick_ticks_by_venue,
        max_price_impact=max_support,
        quote_indexes_by_venue=state.tick_quote_indexes_by_venue,
    )

def mixed_leg_quotes(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    state: MixedFrontierState,
    allowed_venues: set[str] | None,
    max_support: float | None,
) -> list[LegQuote]:
    """Return every V2/V3/V4 single-pool quote on the supported state."""
    quotes = tick_leg_quotes(
        token_in,
        token_out,
        amount_in,
        pool_index=state.tick_pool_index,
        states_by_venue=state.tick_states_by_venue,
        ticks_by_venue=state.tick_ticks_by_venue,
        allowed_venues=allowed_venues,
        max_price_impact=max_support,
        quote_indexes_by_venue=state.tick_quote_indexes_by_venue,
    )
    if state.v2_replay is not None and state.v2_hour is not None and state.v2_order is not None:
        quotes.extend(
            v2_leg_quotes(
                token_in,
                token_out,
                amount_in,
                replay=state.v2_replay,
                hour=state.v2_hour,
                order=state.v2_order,
                allowed_venues=allowed_venues,
                max_input_to_reserve=max_support,
            )
        )
    return sorted(quotes, key=lambda quote: (quote.venue, quote.pool))


def quote_mixed_path(
    token_in: str,
    token_out: str,
    vehicle: str,
    amount_in: float,
    *,
    venues: tuple[str, str],
    pools: tuple[str, str],
    state: MixedFrontierState,
    max_support: float | None,
) -> PathQuote | None:
    """Quote one identified two-leg path, including paths that cross families."""
    first = quote_mixed_pool(
        token_in,
        vehicle,
        amount_in,
        venue=venues[0],
        pool_id=pools[0],
        state=state,
        max_support=max_support,
    )
    if first is None:
        return None
    second = quote_mixed_pool(
        vehicle,
        token_out,
        first.amount_out,
        venue=venues[1],
        pool_id=pools[1],
        state=state,
        max_support=max_support,
    )
    if second is None:
        return None
    return PathQuote(
        amount_out=second.amount_out,
        vehicle=vehicle,
        venues=venues,
        pools=pools,
        price_impacts=(first.price_impact, second.price_impact),
    )
