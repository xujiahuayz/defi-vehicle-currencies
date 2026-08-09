"""Closed-form counterfactual quoting on constant-product pools.

Why this exists. Establishing whether an incumbent intermediary was ever strictly
cost-dominated requires pricing the road not taken *at the same market state* as
the road taken. Comparing realised trades cannot do it: intraday price movement
swamps execution cost by roughly a factor of 34 (see
`docs/finding-cost-dominance-not-yet-established.md`). The on-chain Quoter would
do it, but free RPC endpoints no longer serve historical state, returning either
"state at block N is pruned" or an authentication demand, and no archive
credential exists in this project.

Constant-product pools need neither. Their quote is closed form:

    out = (in * (1 - f) * R_out) / (R_in + in * (1 - f))

with f the pool fee (30 bp on Uniswap v2 and SushiSwap v2). Given reserves, the
quote is exact. The direct alternative is reconstructed immediately before the
realised route's first block-log event, while the vehicle route uses its realised
output. Both therefore refer to the same causal market moment.

Scope, and the direction of its bias. This covers Uniswap v2 and SushiSwap v2.
Uniswap v3, Curve and Balancer are excluded, since concentrated liquidity needs
the tick map and the others need their own invariants and state. That exclusion is
signed rather than merely noted: leaving venues out shrinks the counterfactual
universe, so the best available alternative route is understated, which makes the
incumbent route look *better* than it was. The measured incidence of cost
dominance is therefore a lower bound, which is the conservative direction for a
claim that such windows exist.

State reconstruction, and a subtlety that matters. The subgraph's PairHourData
reserve is the end-of-hour state. Replaying swaps forward from it is wrong and
measures badly. The state owner instead unwinds every known reserve change in
reverse block-log order, including Uniswap v2 mints and burns, and validates the
result against the nearest prior observed reserve after advancing every known
intervening change. Residual continuity breaks are excluded from counterfactual
pool search; an identified realised pool may only attempt same-size reproduction
and is retained only if the route-level output passes the separate tolerance.
Swap-only validation had median absolute error 0.0000%, with 96.7% of quotes
within 1% and 95.2% within 0.01% of realised output on 8,024 swaps; replaying
liquidity events recovers most counterfactual support without weakening the
continuity contract.

Remaining caveats, all reportable:
  - SushiSwap v2 liquidity events remain unavailable. Direct transfers and
    fee-on-transfer tokens are also not explicit state events. Reserve continuity
    detects and drops their residual breaks from the public alternative set;
    realised-pool reproduction remains subject to the output-validation gate.
  - quotes are gross of gas. A two-hop route costs more gas than one hop, so a
    gas-inclusive comparison is required before any all-in claim. Gas per route
    topology must be measured from receipts.
  - fee-on-transfer and rebasing tokens violate the constant-product identity and
    must be screened out.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from decimal import Decimal

# Uniswap v2 and SushiSwap v2 both charge 30 bp, expressed as the 997/1000 factor
# used on-chain.
FEE_NUM = 997
FEE_DEN = 1000


@dataclass(frozen=True)
class Pool:
    """A constant-product pool at one point in time, in human units."""
    pool_id: str
    token0: str
    token1: str
    reserve0: Decimal
    reserve1: Decimal
    venue: str = "uniswap_v2"

    def reserves_for(self, token_in: str) -> tuple[Decimal, Decimal] | None:
        """(reserve_in, reserve_out) when token_in is in this pool, else None."""
        t = token_in.lower()
        if t == self.token0:
            return self.reserve0, self.reserve1
        if t == self.token1:
            return self.reserve1, self.reserve0
        return None

    def other(self, token_in: str) -> str | None:
        t = token_in.lower()
        if t == self.token0:
            return self.token1
        if t == self.token1:
            return self.token0
        return None


@dataclass(frozen=True)
class ReserveEvent:
    """One constant-product swap with exact causal order and reserve states."""

    order: tuple[int, int]
    before: tuple[Decimal, Decimal]
    after: tuple[Decimal, Decimal]


def quote_one_hop(pool: Pool, token_in: str, amount_in: Decimal) -> Decimal | None:
    """Exact constant-product output, or None when the token is absent or reserves are empty."""
    r = pool.reserves_for(token_in)
    if r is None:
        return None
    r_in, r_out = r
    if r_in <= 0 or r_out <= 0 or amount_in <= 0:
        return None
    eff = amount_in * FEE_NUM / FEE_DEN
    return (eff * r_out) / (r_in + eff)


def quote_path(pools: list[Pool], token_in: str, amount_in: Decimal) -> Decimal | None:
    """Chain one-hop quotes along a path of pools, threading the token through."""
    amt = amount_in
    tok = token_in.lower()
    for p in pools:
        out = quote_one_hop(p, tok, amt)
        if out is None or out <= 0:
            return None
        nxt = p.other(tok)
        if nxt is None:
            return None
        amt, tok = out, nxt
    return amt


def best_direct(pools_by_pair: dict[tuple[str, str], list[Pool]],
                token_in: str, token_out: str, amount_in: Decimal) -> Decimal | None:
    """Best output over all direct pools joining the two endpoints."""
    key = tuple(sorted((token_in.lower(), token_out.lower())))
    cands = pools_by_pair.get(key, [])
    outs = [q for q in (quote_one_hop(p, token_in, amount_in) for p in cands) if q]
    return max(outs) if outs else None


def best_via(pools_by_pair: dict[tuple[str, str], list[Pool]],
             token_in: str, token_out: str, mid: str,
             amount_in: Decimal) -> Decimal | None:
    """Best output routing through a named intermediary, optimising each leg."""
    a, b, m = token_in.lower(), token_out.lower(), mid.lower()
    if m in (a, b):
        return None
    leg1 = pools_by_pair.get(tuple(sorted((a, m))), [])
    leg2 = pools_by_pair.get(tuple(sorted((m, b))), [])
    if not leg1 or not leg2:
        return None
    best = None
    for p1 in leg1:
        mid_amt = quote_one_hop(p1, a, amount_in)
        if not mid_amt:
            continue
        for p2 in leg2:
            out = quote_one_hop(p2, m, mid_amt)
            if out and (best is None or out > best):
                best = out
    return best


def cost_gap_bps(direct: Decimal | None, via: Decimal | None) -> float | None:
    """Basis points by which the direct route beats the intermediated one.

    Positive means direct returns more output, so the intermediary is dominated
    on quoted output. Gross of gas.
    """
    if not direct or not via or via <= 0:
        return None
    return float(10_000 * (direct - via) / via)


def unwind_hour(stored: tuple[Decimal, Decimal],
                swaps: list[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    """Recover pre-trade reserves for each swap in an hour.

    `stored` is the subgraph's end-of-hour reserve pair. `swaps` are the net
    (delta0, delta1) of each swap in execution order. Returns the reserve pair
    immediately BEFORE each swap, same order.

    Validated at median absolute error 0.0000% against realised outputs; the
    forward reading of the same data errs by 11.8%, so direction is not optional.
    """
    r0, r1 = stored
    pre: list[tuple[Decimal, Decimal]] = [(Decimal(0), Decimal(0))] * len(swaps)
    for i in range(len(swaps) - 1, -1, -1):
        d0, d1 = swaps[i]
        r0 -= d0
        r1 -= d1
        pre[i] = (r0, r1)
    return pre


def ordered_reserve_events(
    stored: tuple[Decimal, Decimal],
    changes: list[tuple[tuple[int, int], tuple[Decimal, Decimal]]],
) -> list[ReserveEvent]:
    """Reconstruct pre/post states for block-log ordered reserve changes.

    The changes may be swaps, mints or burns. Exact duplicate raw events are
    idempotent; two different deltas at one block-log identity are a hard conflict.
    """
    unique: dict[tuple[int, int], tuple[Decimal, Decimal]] = {}
    for order, delta in changes:
        prior = unique.get(order)
        if prior is not None and prior != delta:
            raise ValueError(f"conflicting reserve changes at block-log {order}")
        unique[order] = delta
    ordered = sorted(unique.items(), key=lambda item: item[0])
    deltas = [delta for _order, delta in ordered]
    before = unwind_hour(stored, deltas)
    return [
        ReserveEvent(
            order=order,
            before=pre,
            after=(pre[0] + delta[0], pre[1] + delta[1]),
        )
        for (order, delta), pre in zip(ordered, before, strict=True)
    ]


def reserve_state_before(
    events: list[ReserveEvent], target: tuple[int, int]
) -> tuple[Decimal, Decimal] | None:
    """State strictly before a target block-log order inside one clean pool-hour."""
    if not events:
        return None
    orders = [event.order for event in events]
    index = bisect.bisect_left(orders, target)
    if index < len(events):
        return events[index].before
    return events[-1].after


def apply_reserve_deltas(
    state: tuple[Decimal, Decimal],
    deltas: list[tuple[Decimal, Decimal]],
) -> tuple[Decimal, Decimal]:
    """Advance one reserve state through known swaps and liquidity events."""
    reserve0, reserve1 = state
    for delta0, delta1 in deltas:
        reserve0 += delta0
        reserve1 += delta1
    return reserve0, reserve1


def prior_observed_state(
    observed: dict[int, tuple[Decimal, Decimal]],
    known_deltas: dict[int, list[tuple[Decimal, Decimal]]],
    target_period: int,
) -> tuple[tuple[Decimal, Decimal], int] | None:
    """Nearest prior reserve advanced through known intervening periods."""
    periods = sorted(observed)
    prior_index = bisect.bisect_left(periods, target_period) - 1
    if prior_index < 0:
        return None
    prior_period = periods[prior_index]
    state = observed[prior_period]
    for period in sorted(known_deltas):
        if prior_period < period < target_period:
            state = apply_reserve_deltas(state, known_deltas[period])
    return state, prior_period


def hour_is_clean(stored_prev: tuple[Decimal, Decimal] | None,
                  stored: tuple[Decimal, Decimal],
                  deltas: list[tuple[Decimal, Decimal]],
                  tol: float = 1e-9) -> bool:
    """Are all reserve changes since the observed prior state accounted for?

    Unwinds known swaps, mints and burns from the stored end state and compares
    with the nearest prior state advanced through any known intervening changes.
    Agreement makes the reconstruction exact. Disagreement means an unobserved
    reserve change remains, so every reconstructed pre-state may be wrong.

    An unbridged hour can still attempt same-size reproduction of its identified
    realised pool. It may not enter counterfactual pool enumeration; that requires
    this continuity check to pass.

    Liquidity events are observed for Uniswap v2 but not SushiSwap v2. Residual
    breaks remain excluded, and their selection must be reported.
    """
    r0, r1 = stored
    for d0, d1 in reversed(deltas):
        r0 -= d0
        r1 -= d1
        if r0 <= 0 or r1 <= 0:
            return False          # unwind went negative: definitely contaminated
    if stored_prev is None:
        return False              # coherence is not evidence of reserve continuity
    p0, p1 = stored_prev
    if p0 <= 0 or p1 <= 0:
        return False
    return (abs(float((r0 - p0) / p0)) < tol
            and abs(float((r1 - p1) / p1)) < tol)


# ---------------------------------------------------------------------------
# Gas by route topology, measured from receipts rather than assumed.
#
# Measured 2026-08-05 on 2024-01-15 Uniswap v2 transactions via
# eth_getTransactionReceipt, which pruned nodes still serve because receipts are
# stored data and not historical state. Median gasUsed:
#
#     1 leg   154,604      2 legs  228,701      3 legs  319,906
#
# so roughly 74k-91k additional gas per extra hop. The absolute figure moves with
# token transfer costs and router implementation, so treat these as defaults and
# re-measure per sample period before publishing.
#
# The economically important property is that gas is a FIXED cost per route,
# so its share of notional falls as 1/size. At 25.8 gwei and ETH near $2,500 the
# second hop costs about 48 bp of a $1,000 trade, 4.8 bp of a $10,000 trade and
# 480 bp of a $100 trade. Any comparison of a one-hop against a two-hop route
# that ignores gas is therefore biased toward the two-hop route, and the bias is
# severe precisely for small trades.
# ---------------------------------------------------------------------------

GAS_BY_LEGS: dict[int, int] = {1: 154_604, 2: 228_701, 3: 319_906}
GAS_PER_EXTRA_HOP = 74_096


def gas_units(n_legs: int) -> int:
    """Median gas for a route of this many legs, extrapolating beyond measurement."""
    if n_legs in GAS_BY_LEGS:
        return GAS_BY_LEGS[n_legs]
    if n_legs < 1:
        return 0
    top = max(GAS_BY_LEGS)
    return GAS_BY_LEGS[top] + GAS_PER_EXTRA_HOP * (n_legs - top)


def gas_cost_bps(n_legs: int, notional_usd: float,
                 gas_price_gwei: float, eth_usd: float) -> float | None:
    """Gas cost of a route as basis points of notional.

    Returns None on a non-positive notional. Because gas is fixed per route, this
    is the term that makes route choice size-dependent: the same hop is negligible
    on a large trade and decisive on a small one.
    """
    return gas_cost_bps_from_units(
        gas_units(n_legs), notional_usd, gas_price_gwei, eth_usd
    )


def gas_cost_bps_from_units(
    route_gas_units: float,
    notional_usd: float,
    gas_price_gwei: float,
    eth_usd: float,
) -> float | None:
    """Gas cost in basis points from receipt-measured route gas units."""
    if notional_usd <= 0 or route_gas_units < 0:
        return None
    eth = route_gas_units * gas_price_gwei * 1e-9
    return 10_000 * (eth * eth_usd) / notional_usd


def all_in_direct_advantage_bps(
    gross_direct_advantage_bps: float,
    *,
    direct_legs: int,
    vehicle_legs: int,
    notional_usd: float,
    gas_price_gwei: float,
    eth_usd: float,
) -> float | None:
    """Direct-route advantage after charging each route its topology gas.

    A positive value means the direct route costs less. The sign is intentionally
    owned here: when the vehicle route has more legs, adding gas increases the
    direct advantage relative to the gross-of-gas comparison.
    """
    return all_in_direct_advantage_bps_from_units(
        gross_direct_advantage_bps,
        direct_gas_units=gas_units(direct_legs),
        vehicle_gas_units=gas_units(vehicle_legs),
        notional_usd=notional_usd,
        gas_price_gwei=gas_price_gwei,
        eth_usd=eth_usd,
    )


def all_in_direct_advantage_bps_from_units(
    gross_direct_advantage_bps: float,
    *,
    direct_gas_units: float,
    vehicle_gas_units: float,
    notional_usd: float,
    gas_price_gwei: float,
    eth_usd: float,
) -> float | None:
    """Direct-route advantage using gas units measured for the matched routes."""
    direct_gas = gas_cost_bps_from_units(
        direct_gas_units, notional_usd, gas_price_gwei, eth_usd
    )
    vehicle_gas = gas_cost_bps_from_units(
        vehicle_gas_units, notional_usd, gas_price_gwei, eth_usd
    )
    if direct_gas is None or vehicle_gas is None:
        return None
    return gross_direct_advantage_bps + vehicle_gas - direct_gas
