"""Uniswap V3 exact-input quote math.

This is a DVC-local port of the DDC V3 quote core: Uniswap V3
``SwapMath.computeSwapStep`` plus ``TickMath``/``SqrtPriceMath`` in integer Q96
arithmetic. Callers may pass either an empty ``tick_net`` map for active-range
snapshot quotes, or a reconstructed initialized-tick map for full tick-crossing
quotes once the DVC liquidity-index layer is built.
"""
from __future__ import annotations

from dataclasses import dataclass

Q96 = 1 << 96
MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342


# --- TickMath.getSqrtRatioAtTick (exact integer port) -------------------------
def get_sqrt_ratio_at_tick(tick: int) -> int:
    if not (MIN_TICK <= tick <= MAX_TICK):
        raise ValueError(f"tick {tick} out of range")
    abs_tick = -tick if tick < 0 else tick
    ratio = 0xfffcb933bd6fad37aa2d162d1a594001 if (abs_tick & 0x1) else 0x100000000000000000000000000000000
    for bit, mul in (
        (0x2, 0xfff97272373d413259a46990580e213a),
        (0x4, 0xfff2e50f5f656932ef12357cf3c7fdcc),
        (0x8, 0xffe5caca7e10e4e61c3624eaa0941cd0),
        (0x10, 0xffcb9843d60f6159c9db58835c926644),
        (0x20, 0xff973b41fa98c081472e6896dfb254c0),
        (0x40, 0xff2ea16466c96a3843ec78b326b52861),
        (0x80, 0xfe5dee046a99a2a811c461f1969c3053),
        (0x100, 0xfcbe86c7900a88aedcffc83b479aa3a4),
        (0x200, 0xf987a7253ac413176f2b074cf7815e54),
        (0x400, 0xf3392b0822b70005940c7a398e4b70f3),
        (0x800, 0xe7159475a2c29b7443b29c7fa6e889d9),
        (0x1000, 0xd097f3bdfd2022b8845ad8f792aa5825),
        (0x2000, 0xa9f746462d870fdf8a65dc1f90e061e5),
        (0x4000, 0x70d869a156d2a1b890bb3df62baf32f7),
        (0x8000, 0x31be135f97d08fd981231505542fcfa6),
        (0x10000, 0x9aa508b5b7a84e1c677de54f3e99bc9),
        (0x20000, 0x5d6af8dedb81196699c329225ee604),
        (0x40000, 0x2216e584f5fa1ea926041bedfe98),
        (0x80000, 0x48a170391f7dc42444e8fa2),
    ):
        if abs_tick & bit:
            ratio = (ratio * mul) >> 128
    if tick > 0:
        ratio = ((1 << 256) - 1) // ratio  # type(uint256).max / ratio
    # ratio is Q128.128; downcast to Q96 with round-up
    return (ratio >> 32) + (1 if ratio % (1 << 32) else 0)


# --- SqrtPriceMath ------------------------------------------------------------
def _get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    num1 = liquidity << 96
    num2 = sqrt_b - sqrt_a
    if round_up:
        return _ceil_div(_ceil_div(num1 * num2, sqrt_b), sqrt_a)
    return (num1 * num2 // sqrt_b) // sqrt_a


def _get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if round_up:
        return _ceil_div(liquidity * (sqrt_b - sqrt_a), Q96)
    return liquidity * (sqrt_b - sqrt_a) // Q96


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _next_sqrt_from_amount0_in(sqrt_p: int, liquidity: int, amount: int) -> int:
    # token0 in (price decreases). roundup.
    num = liquidity << 96
    product = amount * sqrt_p
    denom = num + product
    return _ceil_div(num * sqrt_p, denom)


def _next_sqrt_from_amount1_in(sqrt_p: int, liquidity: int, amount: int) -> int:
    # token1 in (price increases).
    quotient = (amount << 96) // liquidity
    return sqrt_p + quotient


@dataclass
class QuoteResult:
    amount_out: int
    amount_in_used: int
    sqrt_price_after: int
    crossed_ticks: int


def quote_exact_input(
    *,
    zero_for_one: bool,
    amount_in: int,
    sqrt_price_x96: int,
    liquidity: int,
    tick_net: dict[int, int],
    tick_spacing: int,
    fee_pips: int,
) -> QuoteResult:
    """Quote ``amount_in`` of the input token. ``zero_for_one`` True = token0 in,
    token1 out (price falls). ``tick_net`` = {tick: net liquidity delta}, ``fee_pips``
    in hundredths of a bip (3000 = 0.30%). Faithful computeSwapStep loop."""
    sqrt_p = sqrt_price_x96
    L = liquidity
    amount_remaining = amount_in
    amount_out = 0
    crossed = 0
    sorted_ticks = sorted(tick_net)

    def _next_init_tick(cur_sqrt: int) -> int | None:
        # next initialized tick in the swap direction (by sqrt price)
        cand = [t for t in sorted_ticks if (get_sqrt_ratio_at_tick(t) < cur_sqrt) == zero_for_one]
        if not cand:
            return None
        return max(cand) if zero_for_one else min(cand)

    guard = 0
    while amount_remaining > 0:
        guard += 1
        if guard > 5_000:  # pathological; bail rather than spin
            break
        nxt = _next_init_tick(sqrt_p)
        sqrt_target = get_sqrt_ratio_at_tick(nxt) if nxt is not None else (
            MIN_SQRT_RATIO + 1 if zero_for_one else MAX_SQRT_RATIO - 1
        )
        if L == 0:
            # no liquidity in this range; jump to the next tick if any, else stop
            if nxt is None:
                break
            sqrt_p = sqrt_target
            L += tick_net[nxt] if zero_for_one else tick_net[nxt]
            # (sign handled at cross below; here L was 0 so just set via cross)
            L = max(L, 0)
            crossed += 1
            continue

        amount_less_fee = amount_remaining - _ceil_div(amount_remaining * fee_pips, 10 ** 6)
        # how far can we move within [sqrt_p, sqrt_target] with amount_less_fee?
        if zero_for_one:
            max_amount0 = _get_amount0_delta(sqrt_target, sqrt_p, L, True)
            if amount_less_fee >= max_amount0:
                sqrt_next = sqrt_target
                step_in = max_amount0
            else:
                sqrt_next = _next_sqrt_from_amount0_in(sqrt_p, L, amount_less_fee)
                step_in = _get_amount0_delta(sqrt_next, sqrt_p, L, True)
            step_out = _get_amount1_delta(sqrt_next, sqrt_p, L, False)
        else:
            max_amount1 = _get_amount1_delta(sqrt_p, sqrt_target, L, True)
            if amount_less_fee >= max_amount1:
                sqrt_next = sqrt_target
                step_in = max_amount1
            else:
                sqrt_next = _next_sqrt_from_amount1_in(sqrt_p, L, amount_less_fee)
                step_in = _get_amount1_delta(sqrt_p, sqrt_next, L, True)
            step_out = _get_amount0_delta(sqrt_p, sqrt_next, L, False)

        # fee on the consumed input
        if sqrt_next == sqrt_target:
            fee_amt = _ceil_div(step_in * fee_pips, 10 ** 6 - fee_pips)
        else:
            fee_amt = amount_remaining - step_in
        consumed = step_in + fee_amt
        if consumed <= 0:
            break
        amount_remaining -= min(consumed, amount_remaining)
        amount_out += step_out
        sqrt_p = sqrt_next

        if nxt is not None and sqrt_p == sqrt_target:
            # cross the tick: liquidityNet applies (subtract when zeroForOne)
            net = tick_net[nxt]
            L = L + (-net if zero_for_one else net)
            if L < 0:
                L = 0
            crossed += 1
        if nxt is None and sqrt_p == sqrt_target:
            break

    return QuoteResult(amount_out=amount_out, amount_in_used=amount_in - amount_remaining,
                       sqrt_price_after=sqrt_p, crossed_ticks=crossed)
