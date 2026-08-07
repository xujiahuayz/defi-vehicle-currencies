"""Path-frontier adapter for exact-state V2 constant-product pools."""

from __future__ import annotations

from decimal import Decimal

from ddvc.cpquote import Pool, quote_one_hop
from ddvc.pricing.path_frontier import LegQuote
from ddvc.pricing.v2_replay import ChainOrder, V2ReplayDay


def quote_v2_pool(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    venue: str,
    pool_id: str,
    hour: int,
    order: ChainOrder,
    replay: V2ReplayDay,
    max_input_to_reserve: float | None,
) -> LegQuote | None:
    """Quote one identified pool immediately before ``order``."""
    meta = replay.meta.get((venue, pool_id))
    state = replay.state_before(venue, pool_id, hour, order)
    if meta is None or state is None:
        return None
    pool = Pool(
        pool_id,
        meta.token0,
        meta.token1,
        state[0],
        state[1],
        venue,
    )
    reserves = pool.reserves_for(token_in)
    if reserves is None:
        return None
    reserve_in, reserve_out = reserves
    amount = Decimal(str(amount_in))
    support_ratio = float(amount / reserve_in) if reserve_in > 0 else float("inf")
    if max_input_to_reserve is not None and support_ratio > max_input_to_reserve:
        return None
    output = quote_one_hop(pool, token_in, amount)
    if output is None or output <= 0 or reserve_out <= 0:
        return None
    spot_output = amount * reserve_out / reserve_in
    price_impact = max(0.0, 1.0 - float(output / spot_output))
    return LegQuote(float(output), venue, pool_id, price_impact)


def v2_leg_quotes(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    replay: V2ReplayDay,
    hour: int,
    order: ChainOrder,
    allowed_venues: set[str] | None,
    max_input_to_reserve: float | None,
) -> list[LegQuote]:
    """Return every supported V2 quote in deterministic pool identity order."""
    quotes: list[LegQuote] = []
    for venue, pool_id in replay.candidates(token_in, token_out):
        if allowed_venues is not None and venue not in allowed_venues:
            continue
        quote = quote_v2_pool(
            token_in,
            token_out,
            amount_in,
            venue=venue,
            pool_id=pool_id,
            hour=hour,
            order=order,
            replay=replay,
            max_input_to_reserve=max_input_to_reserve,
        )
        if quote is not None:
            quotes.append(quote)
    return quotes
