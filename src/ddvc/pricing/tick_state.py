"""Shared initialized-tick state updates and transaction-order replay."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ddvc.asset_types import canonical_token
from ddvc.fetch.raw import block_value, timestamp_value, v4_pool_quote_supported
from ddvc.pricing.v3pools import (
    DECIMAL_SAMPLE_SIZE,
    derive_fee_tier,
    record_token_decimals,
    resolve_decimals,
    tick_spacing_for_fee,
)


@dataclass
class TickPoolState:
    """Latest quotable concentrated-liquidity pool state in chain order."""

    pool: str
    token0: str
    token1: str
    sym0: str
    sym1: str
    dec0: int
    dec1: int
    sqrt_price_x96: int
    tick: int
    fee_pips: int
    tick_spacing: int
    block: int
    log_index: int


def event_order(row: dict) -> tuple[int, int]:
    """Canonical within-chain order for a raw swap or liquidity event."""
    return (
        int(block_value(row) or timestamp_value(row) or 0),
        int(row.get("logIndex") or 0),
    )


def apply_tick_change(ticks: dict[int, int], row: dict, *, sign: int = 1) -> None:
    """Apply one signed liquidity change to its lower and upper boundary ticks."""
    try:
        amount = sign * int(row.get("amount") or 0)
        lower, upper = int(row["tickLower"]), int(row["tickUpper"])
    except (TypeError, ValueError, KeyError):
        return
    if amount == 0:
        return
    ticks[lower] = ticks.get(lower, 0) + amount
    ticks[upper] = ticks.get(upper, 0) - amount
    if ticks[lower] == 0:
        del ticks[lower]
    if ticks.get(upper) == 0:
        del ticks[upper]


def active_liquidity(ticks: dict[int, int], current_tick: int) -> int:
    """Active liquidity implied by boundary-tick net changes at ``current_tick``."""
    return sum(value for tick, value in ticks.items() if tick <= current_tick)


def absorb_swap_state(
    venue: str,
    row: dict,
    state_by_pool: dict[str, TickPoolState],
    *,
    swap_samples: dict[str, list[dict]],
    token_decimals: dict[str, int],
    unify_wrapped: bool = True,
) -> None:
    """Fold one V3/V4 swap into the canonical latest-state index.

    V3 fee and decimals are recovered from the canonical pool identity and swap
    price identity. V4 statics come from the raw row, and unsupported dynamic-fee
    or hook-bearing pools never enter the index. Callers own the bounded sample
    dictionary because replay jobs may maintain independent histories.
    """
    pool = row.get("pool") or {}
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    pool_id = str(pool.get("id", "")).lower()
    raw0 = str(token0.get("id", "")).lower()
    raw1 = str(token1.get("id", "")).lower()
    canonical0 = canonical_token(raw0, unify_wrapped=unify_wrapped)
    canonical1 = canonical_token(raw1, unify_wrapped=unify_wrapped)
    if not pool_id or not canonical0 or not canonical1:
        return
    try:
        block = int(block_value(row) or timestamp_value(row) or 0)
        log_index = int(row.get("logIndex") or 0)
        sqrt_price_x96 = int(row.get("sqrtPriceX96") or row.get("sqrtPrice") or 0)
        tick = int(row.get("tick") or 0)
    except (TypeError, ValueError):
        return
    if sqrt_price_x96 <= 0:
        return
    old = state_by_pool.get(pool_id)
    if old is not None and (block, log_index) <= (old.block, old.log_index):
        return
    if old is not None:
        if (canonical0, canonical1) != (old.token0, old.token1):
            raise ValueError(f"concentrated-liquidity pool token identity changed: {pool_id}")
        if venue == "uniswap_v4":
            if not v4_pool_quote_supported(row):
                return
            try:
                observed_statics = (
                    int(pool.get("feeTier")),
                    int(pool.get("tickSpacing")),
                    int(token0.get("decimals")),
                    int(token1.get("decimals")),
                )
            except (TypeError, ValueError):
                return
            expected_statics = (
                old.fee_pips,
                old.tick_spacing,
                old.dec0,
                old.dec1,
            )
            if observed_statics != expected_statics:
                raise ValueError(f"Uniswap v4 pool statics changed: {pool_id}")
        fee_pips = old.fee_pips
        tick_spacing = old.tick_spacing
        decimals = (old.dec0, old.dec1)
    elif venue == "uniswap_v4":
        if not v4_pool_quote_supported(row):
            return
        try:
            fee_pips = int(pool.get("feeTier"))
            tick_spacing = int(pool.get("tickSpacing"))
            decimals = (int(token0.get("decimals")), int(token1.get("decimals")))
        except (TypeError, ValueError):
            return
        record_token_decimals(token_decimals, raw0, decimals[0])
        record_token_decimals(token_decimals, raw1, decimals[1])
    else:
        sample = swap_samples.setdefault(pool_id, [])
        sample.append(row)
        if len(sample) > DECIMAL_SAMPLE_SIZE:
            del sample[0]
        fee_pips = derive_fee_tier(pool_id, raw0, raw1)
        if fee_pips is None:
            return
        decimals = resolve_decimals(
            raw0,
            raw1,
            sample,
            known_decimals=token_decimals,
        )
        if decimals is None:
            return
        record_token_decimals(token_decimals, raw0, decimals[0])
        record_token_decimals(token_decimals, raw1, decimals[1])
        tick_spacing = tick_spacing_for_fee(fee_pips)
    state_by_pool[pool_id] = TickPoolState(
        pool=pool_id,
        token0=canonical0,
        token1=canonical1,
        sym0=old.sym0 if old is not None else str(token0.get("symbol", "")),
        sym1=old.sym1 if old is not None else str(token1.get("symbol", "")),
        dec0=decimals[0],
        dec1=decimals[1],
        sqrt_price_x96=sqrt_price_x96,
        tick=tick,
        fee_pips=fee_pips,
        tick_spacing=tick_spacing,
        block=block,
        log_index=log_index,
    )
    swap_samples.pop(pool_id, None)


def iter_pretrade_states(
    swaps: list[dict],
    changes: list[tuple[int, dict]],
    initial_ticks: dict[int, int],
) -> Iterator[tuple[dict, dict, dict[int, int]]]:
    """Yield consecutive swaps with the tick map immediately before the latter.

    ``changes`` carries an explicit sign because V3 splits mints and burns while V4
    stores signed deltas in one stream. Liquidity and swap events are interleaved by
    block and log index, preventing target-day liquidity from leaking backward.
    """
    stream = [
        (*event_order(row), 0, index, sign, row)
        for index, (sign, row) in enumerate(changes)
    ]
    stream.extend(
        (*event_order(row), 1, index, 0, row)
        for index, row in enumerate(swaps)
    )
    ticks = dict(initial_ticks)
    previous_swap: dict | None = None
    for _block, _log_index, kind, _sequence, sign, row in sorted(stream):
        if kind == 0:
            apply_tick_change(ticks, row, sign=sign)
            continue
        if previous_swap is not None:
            yield previous_swap, row, dict(ticks)
        previous_swap = row
