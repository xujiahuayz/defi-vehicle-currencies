"""Balancer weighted-pool exact-input quoting, with the snapshot instant identified from data.

Why Balancer has to be priced. The route-cost experiment compares the best one-hop route against the best two-hop route through each candidate vehicle, and "best" is defined over all venues, so a missing venue understates the best route on every leg it could have served and the bias lands wherever that venue was strongest. Balancer is the sixth of seven venues and the only one whose pools are n-token with arbitrary weights, which means a single Balancer pool supplies quotes for every pair among its tokens the way a Curve pool does, and it is where the 80/20 native-asset pairings and the multi-asset stable baskets sit. Leaving it out therefore does not shave a uniform slice off every route, it removes a specific kind of route.

The invariant. Balancer weighted pools hold a weighted geometric mean constant, prod(B_i ^ W_i), where the normalised weights W_i sum to one. For a two-token swap that gives the exact-input form:

    amountOut = B_out * (1 - (B_in / (B_in + amountIn * (1 - swapFee))) ^ (W_in / W_out))

Uniswap's constant product is the special case W_in = W_out, where the exponent is one and the expression collapses to the familiar reserve formula. Only the ratio W_in / W_out enters, so an equal-weight Balancer pool and a Uniswap v2 pair with the same reserves quote identically, and every departure from that is the weight ratio doing work.

Where the balances come from, and why this is the load-bearing part. The raw layer carries daily `poolSnapshots`, and the naive reading is that a daily balance snapshot is all Balancer legs can ever have, which would be a real granularity penalty on a venue whose weighted pools hold volatile assets and drift hard within a day. That reading is wrong, and the correction was measured on this project's own data. `poolSnapshots.amounts` is overwritten on every event of the day, so the stored value is the balance after the LAST event of that day, not the first. Three candidate readings were scored against realised swaps: holding the snapshot balances flat across the day gives a median absolute quote error of 1.2% to 1.8%, treating the snapshot as the day's opening state and rolling forward gives 1.8% to 4.4%, and treating it as the day's closing state and rolling the day's event sequence BACKWARD gives 0.0000%. The snapshot instant is therefore identified by which reading reproduces trades, in the same way Curve's amplification coefficient was, and Balancer legs get per-swap balances with no daily-snapshot penalty at all.

That reconstruction needs the day's events ordered, and the raw layer supports it: `block` orders across blocks and the decimal log index suffixed to an entity id orders within a block. It also needs ALL the events, and swaps are not all of them. Joins and exits move balances too, and a walk built from swaps alone leaves an unobservable jump wherever liquidity entered or left the pool. That jump is then charged to the invariant, which is a specific and expensive confusion: it looks exactly like a pool running different maths. Measured, the confusion is most of the coverage. Swaps alone price 177 of 367 testable pool-days and leave 96.9% of tested volume excluded, and merging the joins-and-exits stream into the same sequence takes that to 87 of 105 with 33.0% of tested volume excluded, with every remaining exclusion a non-weighted pool family. So the fix is not a tolerance, it is a stream.

The weight ratio and the fee, and when they need identifying instead of reading. `PoolToken.weight` and `Pool.swapFee` are both reported, and for a plain weighted pool that never repriced itself both are exact, which is where the 0.0000% above comes from. Neither is always exact. The subgraph serves both at the head block while the balances come from a historical snapshot, so a pool that changed either since is quoted with the wrong parameter against a past state. Liquidity-bootstrapping pools shift weights on a schedule by design and managed pools shift them on demand, and a weighted pool's owner can change its fee at will. The fee case was visible in the validation before it was diagnosed: read parameters reproduce 2024 trades to 1e-9% and 2022 trades only to 0.19%, which is a fee-sized gap and not a maths-sized one, since the fee enters through amountIn * (1 - fee) so a fee wrong by a basis point moves the quote by about a basis point.

Both are identified instead of assumed, which is the move Curve's amplification coefficient needed. The invariant maps balances, the weight ratio, the fee and amountIn to amountOut, and every Balancer swap in the raw layer reports amountIn and amountOut, so with balances reconstructed either parameter is the only unknown and is recovered by fitting realised trades. Reading is tried first and each fit introduces exactly one free scalar, so a pool that reproduces its trades on read parameters is never handed a fitted one.

Exclusion is decided by achieved fit error, never by the pool type string. Balancer runs several families of maths under one vault: stable and composable-stable pools use a StableSwap-style invariant, Gyroscope pools use an elliptic curve, and linear and boosted pools price wrapped positions against a target range. None of those is a weighted geometric mean, and the honest outcome for one of them is exclusion. The temptation is to exclude on `poolType`, which is a label and not a measurement, and this project already paid for the equivalent shortcut on Curve: an amplification range that merely looked plausible let crypto-pools through to be fitted with the wrong invariant, and they came back with 36% median quote errors instead of being rejected. So every pool gets scored on its own trades whatever its type says, and acceptance is the achieved error clearing the gate. A stable pool that reproduces its trades within the gate is quotable and a pool labelled Weighted that does not is excluded. What the labels then buy is a diagnosis and not a decision: reading which types the gate rejects, and how much volume they carry, is how the coverage bound gets signed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

# Balancer's fixed-point convention: weights and the swap fee are 18-decimal values, so
# one whole unit is 1e18 and a 0.3% fee is 3e15.
ONE = 10 ** 18

# Vault limit. A weighted pool reverts an exact-input swap paying in more than 30% of the
# input token's balance, so a quote past that bound is not an executable price and must come
# back as None. Route-cost work asks for quotes at fixed notional sizes against pools of every
# depth, which walks into this bound constantly, and a number returned there would be a
# fiction the panel could not have traded. The vault's matching 30% cap on the OUTPUT side
# governs exact-output swaps only and is not applied here, because applying it would reject
# legitimate exact-input trades: a 30%-in trade on an 80/20 pool takes about 65% of the
# output balance and still executes.
MAX_IN_RATIO = ONE * 3 // 10

# Working precision for the fractional power. The pool's own LogExpMath carries roughly
# 1e-14 relative error plus a small upward fudge, so 60 digits is far finer than the
# contract itself and the residual sits orders of magnitude below the tens of basis points
# the route-cost comparison is measuring.
POW_PRECISION = 60

# The acceptance gate, and the only thing that decides whether a pool is quotable. Set at 0.1%
# and not at the 1% the Curve gate uses, because the achieved errors separate cleanly there and
# 1% was measured to be too loose for this venue. At a 1% gate the stable, composable-stable and
# Gyroscope pools clear it on a fitted weight ratio and then score 0.05% to 1.08% on held-out
# trades, carrying a p99 of 12%, while pools that really are weighted score between 1e-9% and
# 0.004%. So the two populations are two orders of magnitude apart and 1% sits inside the gap
# instead of below it. Tightening to 0.1% takes the held-out median to 0.0000% and the within-1%
# share to 99.3% or better, and tightening further to 0.01% buys nothing and only costs coverage.
# This is the Curve lesson in a second form: there the over-permissive object was a parameter
# range and here it is an error threshold, and either way the wrong-invariant pools arrive quoted
# instead of excluded.
MAX_CALIBRATION_ERROR = 0.001

# The gate is read at a HIGH quantile of the fitting set's error and demands that nearly every
# trade be quotable, because a median gate is gameable and was measured to be gamed. A stable pool
# cleared a 0.1% MEDIAN fit gate on alternate trades and then scored 34% median error on the
# trades in between: half its fitting trades were near par and cost nothing to fit, and a median
# cannot see the other half. A pool whose parameters are right has essentially zero error on EVERY
# trade, so demanding the 90th percentile clear the gate costs a real weighted pool nothing and is
# fatal to anything merely approximating the curve. Same for coverage: a formula that quotes a
# quarter of a pool's trades and scores well on those has not been tested on that pool.
FIT_QUANTILE = 0.90
MIN_QUOTED_SHARE = 0.9

# Fewer trades than this on one token pair cannot identify that pair's weight ratio. One or two
# trades are fitted exactly by construction, which then reads as a clean fit.
MIN_PAIR_OBSERVATIONS = 4

# The grid for identifying W_in / W_out. Balancer caps any normalised weight at 98% and
# floors it at 1%, so the ratio between two weights lives inside roughly 1/98 to 98. The
# grid is logarithmic because a quote's sensitivity to the exponent is multiplicative:
# telling 4 from 4.2 barely moves a quote while telling 1 from 4 moves it a great deal.
WEIGHT_RATIO_MIN = Decimal("0.01")
WEIGHT_RATIO_MAX = Decimal("99")

# The swap fee's own bounds, from the vault: no weighted pool may run below 0.0001% or above
# 10%. Same role as the weight-ratio bounds, meaning they bound a search and decide nothing.
FEE_MIN = 10 ** 12
FEE_MAX = 10 ** 17


@dataclass(frozen=True)
class WeightedPool:
    """A Balancer weighted pool at one instant, balances in RAW integer token units."""

    pool_id: str
    tokens: tuple[str, ...]
    balances: tuple[int, ...]
    decimals: tuple[int, ...]
    weights: tuple[int, ...]          # normalised weights in 1e18 units, summing to ONE
    fee: int = 3 * 10 ** 15           # 0.3% in 1e18 units, Balancer's common default
    venue: str = "balancer"
    pool_type: str = "Weighted"

    def index_of(self, token: str) -> int | None:
        t = token.lower()
        for i, x in enumerate(self.tokens):
            if x == t:
                return i
        return None

    def normalised(self) -> tuple[int, ...]:
        """Balances rescaled to 18 decimals, which is what the vault upscales to.

        The decimals cancel out of the weighted formula, because the input side enters only
        as a ratio and the output side scales linearly, so this step changes no quote. It is
        written out anyway. The vault does it, and the one thing this project cannot afford
        is a decimals convention that lives in a reader's head: a 6-decimal stablecoin read
        on an 18-decimal scale is a factor of 1e12, which is the error that reversed a v3
        validation earlier here, and a later change to this formula that stops being scale
        free would inherit the bug silently.
        """
        return tuple(b * 10 ** (18 - d) for b, d in zip(self.balances, self.decimals))


# One realised trade with the pool state it faced: (pool, token_in, token_out, raw amount in,
# raw amount out). Carrying the state per trade is what lets a reconstructed balance path be
# scored without any single-instant approximation.
Observation = tuple["WeightedPool", str, str, int, int]


def _pow(base: Decimal, exponent: Decimal) -> Decimal:
    """base ** exponent at POW_PRECISION digits, for a positive base.

    The pool computes this with its own LogExpMath, which rounds the power UP and then multiplies
    the complement DOWN, so its result is a hair below the exact value. This returns the exact
    value at 60 digits and lets the caller floor, which differs from the contract by around 1e-14
    relative, orders of magnitude below the tens of basis points the route-cost comparison measures.
    """
    if base <= 0:
        return Decimal(0)
    if exponent == 1:
        return base
    with localcontext() as ctx:
        ctx.prec = POW_PRECISION
        return (base.ln() * exponent).exp()


def quote_exact_input(pool: WeightedPool, token_in: str, token_out: str,
                      amount_in_raw: int,
                      weight_ratio: Decimal | None = None,
                      fee: int | None = None) -> int | None:
    """Output in RAW units of token_out, net of the pool fee, or None if unquotable.

    `weight_ratio` and `fee` override W_in / W_out and the swap fee for callers holding a value
    identified from trades instead of read from the subgraph. None means use the pool's own.
    """
    i = pool.index_of(token_in)
    j = pool.index_of(token_out)
    if i is None or j is None or i == j or amount_in_raw <= 0:
        return None
    xp = pool.normalised()
    if xp[i] <= 0 or xp[j] <= 0:
        return None
    swap_fee = pool.fee if fee is None else int(fee)
    if not (0 <= swap_fee < ONE):
        return None

    if weight_ratio is None:
        w_in, w_out = pool.weights[i], pool.weights[j]
        if w_in <= 0 or w_out <= 0:
            return None                       # a pool with no weights is not this pool type
        ratio = Decimal(w_in) / Decimal(w_out)
    else:
        ratio = Decimal(weight_ratio)
    if not (WEIGHT_RATIO_MIN <= ratio <= WEIGHT_RATIO_MAX):
        return None

    scale_in = 10 ** (18 - pool.decimals[i])
    scale_out = 10 ** (18 - pool.decimals[j])
    amount_in = amount_in_raw * scale_in
    # The vault rounds the fee up, so the trader keeps strictly less than the exact share.
    fee_amount = -(-amount_in * swap_fee // ONE)
    amount_in_net = amount_in - fee_amount
    if amount_in_net <= 0:
        return None
    if amount_in * ONE > xp[i] * MAX_IN_RATIO:
        return None                           # over the vault's in-ratio cap: would revert

    with localcontext() as ctx:
        ctx.prec = POW_PRECISION
        base = Decimal(xp[i]) / Decimal(xp[i] + amount_in_net)
        out_normalised = Decimal(xp[j]) * (1 - _pow(base, ratio))
    if out_normalised <= 0:
        return None
    # Floor, matching the vault's downward rounding. The truncation to an integer happens
    # before the division so the arithmetic is exact in Python ints: Decimal floor division
    # on balances of 1e33 overflows the ambient context precision.
    out = int(out_normalised) // scale_out
    return out if out > 0 else None


def quote_errors(observations: list[Observation],
                 weight_ratio: Decimal | None = None,
                 fee: int | None = None) -> list[float]:
    """Absolute relative quote errors over realised trades, skipping anything unquotable.

    Each observation carries its OWN pool state, because the reconstruction above gives every
    trade the balances it actually faced. Passing one static pool for a whole day would be the
    mixed-instant defect this project has already been bitten by.
    """
    errs: list[float] = []
    for pool, t_in, t_out, amt_in, amt_out in observations:
        if amt_out <= 0:
            continue
        q = quote_exact_input(pool, t_in, t_out, amt_in,
                              weight_ratio=weight_ratio, fee=fee)
        if q is None:
            continue
        errs.append(abs(q - amt_out) / amt_out)
    return errs


def quote_error_at(observations: list[Observation], quantile: float = FIT_QUANTILE,
                   weight_ratio: Decimal | None = None,
                   fee: int | None = None,
                   min_share: float = MIN_QUOTED_SHARE) -> float | None:
    """Absolute relative quote error at one quantile, or None when too few trades price.

    `min_share` guards the case where the formula quotes only a handful of a pool's trades and
    scores well on those, which would let a pool in on a fit that never covered it.
    """
    if not observations:
        return None
    errs = quote_errors(observations, weight_ratio=weight_ratio, fee=fee)
    if len(errs) < max(1, int(min_share * len(observations))):
        return None
    errs.sort()
    return errs[min(len(errs) - 1, int(quantile * len(errs)))]


def median_quote_error(observations: list[Observation],
                       weight_ratio: Decimal | None = None,
                       fee: int | None = None,
                       min_share: float = MIN_QUOTED_SHARE) -> float | None:
    """Median absolute relative quote error, for reporting a fit and not for gating one."""
    return quote_error_at(observations, 0.5, weight_ratio=weight_ratio, fee=fee,
                          min_share=min_share)


def calibrate_fee(observations: list[Observation],
                  weight_ratio: Decimal | None = None,
                  max_error: float = MAX_CALIBRATION_ERROR) -> tuple[int, float] | None:
    """Recover the swap fee by fitting realised trades, as (fee in 1e18 units, achieved error).

    Why the fee needs identifying at all, given that the subgraph reports it. `Pool.swapFee` is
    served at the head block while the balances come from a historical snapshot, and a weighted
    pool's owner can change its fee, so a pool that repriced itself since is quoted at today's
    fee against a past state. That shows up as a near-constant relative bias, because the fee
    enters the quote through amountIn * (1 - fee) and a fee wrong by one basis point moves the
    output by about one basis point. It was visible: read fees reproduce 2024 trades to 1e-9%
    but 2022 trades only to 0.19%, which is a fee-sized gap and not a maths-sized one.

    Coarse grid over the fees Balancer pools actually run, then a refinement, because the error
    is unimodal in the fee. The error scored is `FIT_QUANTILE` of the absolute errors, not their
    median, for the reason recorded at that constant. Returns None when nothing reproduces the
    observations.
    """
    if not observations:
        return None
    grid = tuple(int(ONE * Decimal(str(v))) for v in (
        0.000001, 0.00001, 0.0001, 0.0002, 0.0003, 0.0004, 0.0005, 0.001, 0.0015, 0.002,
        0.0025, 0.003, 0.004, 0.005, 0.0075, 0.01, 0.02, 0.03, 0.05, 0.1))

    def error_at(fee: int) -> float | None:
        if not (FEE_MIN <= fee <= FEE_MAX):
            return None
        return quote_error_at(observations, weight_ratio=weight_ratio, fee=fee)

    best: tuple[int, float] | None = None
    for fee in grid:
        e = error_at(fee)
        if e is not None and (best is None or e < best[1]):
            best = (fee, e)
    if best is None:
        return None
    lower = [f for f in grid if f < best[0]]
    upper = [f for f in grid if f > best[0]]
    lo = max(lower) if lower else FEE_MIN
    hi = min(upper) if upper else FEE_MAX
    while hi - lo > 2:
        m1 = lo + (hi - lo) // 3
        m2 = hi - (hi - lo) // 3
        e1, e2 = error_at(m1), error_at(m2)
        if e1 is None and e2 is None:
            break
        if e2 is None or (e1 is not None and e1 <= e2):
            hi = m2
            if e1 is not None and e1 < best[1]:
                best = (m1, e1)
        else:
            lo = m1
            if e2 < best[1]:
                best = (m2, e2)
    if best[1] > max_error:
        return None
    return best


def calibrate_weight_ratio(token_a: str, token_b: str,
                           observations: list[Observation],
                           fee: int | None = None,
                           max_error: float = MAX_CALIBRATION_ERROR
                           ) -> tuple[Decimal, float] | None:
    """Recover W_a / W_b for one pair by fitting realised trades, as (ratio, achieved error).

    Every quantity in the weighted formula except the weight ratio is observed, so the ratio is
    identified. Observations may run in either direction across the pair, and a trade going b to
    a is scored with the reciprocal exponent, which is what the invariant implies and which
    doubles the trades available to pin one number.

    Returns None when no candidate ratio reproduces the observations. That is the honest outcome
    for a pool running different maths, and such a pool has to be excluded, not quoted at
    whichever exponent happened to minimise a large error.
    """
    a, b = token_a.lower(), token_b.lower()
    if a == b:
        return None
    forward = [o for o in observations if o[1].lower() == a and o[2].lower() == b]
    reverse = [o for o in observations if o[1].lower() == b and o[2].lower() == a]
    total = len(forward) + len(reverse)
    if total < MIN_PAIR_OBSERVATIONS:
        return None

    def error_at(ratio: Decimal) -> float | None:
        errs = (quote_errors(forward, weight_ratio=ratio, fee=fee)
                + quote_errors(reverse, weight_ratio=1 / ratio, fee=fee))
        if len(errs) < max(1, int(MIN_QUOTED_SHARE * total)):
            return None
        errs.sort()
        return errs[min(len(errs) - 1, int(FIT_QUANTILE * len(errs)))]

    grid = tuple(Decimal(str(v)) for v in (
        0.0102, 0.02, 0.04, 0.0625, 0.1, 0.15, 0.2, 0.25, 0.3333, 0.5, 0.6667, 0.8,
        1, 1.25, 1.5, 3, 4, 5, 6.6667, 9, 16, 25, 49, 98))
    best: tuple[Decimal, float] | None = None
    for ratio in grid:
        e = error_at(ratio)
        if e is not None and (best is None or e < best[1]):
            best = (ratio, e)
    if best is None:
        return None

    # Refine inside the bracketing grid interval. The coarse grid alone leaves real error on
    # the table, and the same shortcut on Curve cost 0.84% median error on a pool whose true
    # parameter sat between grid points, which would swamp a signal measured in tens of basis
    # points. Ternary search in log space, because the error is unimodal in the exponent over
    # a bracket and the exponent's effect is multiplicative.
    lower = [r for r in grid if r < best[0]]
    upper = [r for r in grid if r > best[0]]
    lo = max(lower) if lower else WEIGHT_RATIO_MIN
    hi = min(upper) if upper else WEIGHT_RATIO_MAX
    with localcontext() as ctx:
        ctx.prec = POW_PRECISION
        log_lo, log_hi = lo.ln(), hi.ln()
        for _ in range(40):
            if log_hi - log_lo < Decimal("1e-6"):
                break
            m1 = log_lo + (log_hi - log_lo) / 3
            m2 = log_hi - (log_hi - log_lo) / 3
            r1, r2 = m1.exp(), m2.exp()
            e1, e2 = error_at(r1), error_at(r2)
            if e1 is None and e2 is None:
                break
            if e2 is None or (e1 is not None and e1 <= e2):
                log_hi = m2
                if e1 is not None and e1 < best[1]:
                    best = (r1, e1)
            else:
                log_lo = m1
                if e2 < best[1]:
                    best = (r2, e2)

    # Reject instead of returning a bad fit. A pool whose best achievable error is large is
    # not a weighted pool, and quoting it would inject that error into the panel dressed as
    # market depth.
    if best[1] > max_error:
        return None
    return best


@dataclass(frozen=True)
class BalanceEvent:
    """One signed RAW change to a pool's balances, in the pool's own token order.

    A swap and a liquidity event differ only in whether a quote is scored against the state
    before them, so both are carried as delta vectors and `is_swap` marks which.
    """

    deltas: tuple[int, ...]
    is_swap: bool = True


def rebuild_pre_trade_balances(closing_balances: tuple[int, ...],
                               ordered_events: list[BalanceEvent]
                               ) -> list[tuple[int, ...]] | None:
    """Pre-trade RAW balances for each swap in a day, walked back from the closing state.

    `closing_balances` is the day's `poolSnapshots.amounts`, which the module docstring shows is
    the balance after the day's last event. Netting the whole day's flow off it recovers the
    opening state, and replaying that flow forward gives the exact balances each swap faced. That
    is what turns one daily snapshot into per-swap pool state.

    `ordered_events` has to carry joins and exits as well as swaps, because those move balances
    too. A reconstruction from swaps alone leaves an unobservable jump wherever liquidity entered
    or left, and that jump is indistinguishable from the pool running different maths, so it would
    be charged to the invariant and exclude a perfectly good weighted pool.

    Returns None when the walk drives any balance to zero or below, which means the day's events
    are still not fully observed and the pool has to fail here instead of being quoted against an
    impossible reserve.
    """
    n = len(closing_balances)
    if any(len(e.deltas) != n for e in ordered_events):
        return None
    running = list(closing_balances)
    for event in ordered_events:
        running = [b - d for b, d in zip(running, event.deltas)]
    if any(b <= 0 for b in running):
        return None
    path: list[tuple[int, ...]] = []
    for event in ordered_events:
        if event.is_swap:
            path.append(tuple(running))
        running = [b + d for b, d in zip(running, event.deltas)]
        if any(b <= 0 for b in running):
            return None
    return path
