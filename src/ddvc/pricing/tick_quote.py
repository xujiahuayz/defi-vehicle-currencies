"""Human-unit finite-size quotes from a causally replayed tick-pool state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ddvc.pricing.tick_state import active_liquidity
from ddvc.pricing.v3quote import get_sqrt_ratio_at_tick, quote_exact_input


class TickStateLike(Protocol):
    token0: str
    token1: str
    dec0: int
    dec1: int
    sqrt_price_x96: int
    tick: int
    fee_pips: int
    tick_spacing: int


@dataclass(frozen=True)
class SupportedTickQuote:
    amount_out: float
    marginal_out: float
    price_impact: float
    crossed_ticks: int


def quote_tick_state(
    state: TickStateLike,
    tick_net: dict[int, int],
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    max_price_impact: float | None,
) -> SupportedTickQuote | None:
    """Quote one exact input and apply an ex-ante own-leg impact boundary.

    ``max_price_impact=None`` is reserved for validation against realised swaps.
    Paper-facing frontiers pass their locked support boundary. A quote that cannot
    consume the full input is unsupported, even if the partial output is positive.
    """
    if amount_in <= 0 or not tick_net:
        return None
    if token_in == state.token0 and token_out == state.token1:
        zero_for_one = True
        decimals_in, decimals_out = state.dec0, state.dec1
    elif token_in == state.token1 and token_out == state.token0:
        zero_for_one = False
        decimals_in, decimals_out = state.dec1, state.dec0
    else:
        return None
    amount_atomic = int(amount_in * 10**decimals_in)
    if amount_atomic <= 0:
        return None
    liquidity = active_liquidity(tick_net, state.tick)
    if liquidity <= 0:
        return None
    sorted_ticks = tuple(sorted(tick_net))
    sqrt_ticks = tuple(get_sqrt_ratio_at_tick(tick) for tick in sorted_ticks)
    quote = quote_exact_input(
        zero_for_one=zero_for_one,
        amount_in=amount_atomic,
        sqrt_price_x96=state.sqrt_price_x96,
        liquidity=liquidity,
        tick_net=tick_net,
        tick_spacing=state.tick_spacing,
        fee_pips=state.fee_pips,
        sorted_ticks=sorted_ticks,
        sqrt_ticks=sqrt_ticks,
    )
    if quote.amount_in_used != amount_atomic or quote.amount_out <= 0:
        return None
    probe_atomic = max(1, amount_atomic // 10_000)
    probe = quote_exact_input(
        zero_for_one=zero_for_one,
        amount_in=probe_atomic,
        sqrt_price_x96=state.sqrt_price_x96,
        liquidity=liquidity,
        tick_net=tick_net,
        tick_spacing=state.tick_spacing,
        fee_pips=state.fee_pips,
        sorted_ticks=sorted_ticks,
        sqrt_ticks=sqrt_ticks,
    )
    if probe.amount_in_used != probe_atomic or probe.amount_out <= 0:
        return None
    scale = 10**decimals_out
    amount_out = quote.amount_out / scale
    marginal_out = probe.amount_out / scale * (amount_atomic / probe_atomic)
    if amount_out <= 0 or marginal_out <= 0:
        return None
    price_impact = (marginal_out - amount_out) / marginal_out
    if max_price_impact is not None and price_impact > max_price_impact:
        return None
    return SupportedTickQuote(
        amount_out=amount_out,
        marginal_out=marginal_out,
        price_impact=price_impact,
        crossed_ticks=quote.crossed_ticks,
    )
