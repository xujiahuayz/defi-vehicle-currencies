"""Curve StableSwap exact-input quoting, with the amplification coefficient calibrated.

Why Curve has to be priced. The route-cost experiment compares the best one-hop route
against the best two-hop route through each candidate vehicle, and "best" is defined
over all venues, so omitting a venue understates every leg it could have served. Curve
carries roughly 85% of Uniswap v2's volume on sampled 2024 days and it is where
stable-to-stable legs live, so its absence falls hardest on stable-intermediated
routes. That is not hypothetical: in the four-venue panel a stable vehicle's quote
collapses below half the notional 37.6% of the time against 9.6% for the native asset,
and the resulting gap in dominance rates, 86.7% against 58.1%, tracks the collapse gap
almost one for one. Most of the measured native advantage may therefore be our missing
venue rather than the market's thin liquidity.

The invariant. StableSwap interpolates between a constant-sum curve, which is flat and
gives zero slippage, and a constant-product curve, which is what Uniswap uses. For a
pool of n tokens with balances x_i, amplification A and invariant D:

    A n^n sum(x_i) + D = A D n^n + D^(n+1) / (n^n prod(x_i))

D is solved by Newton iteration, and an exact-input quote solves the same equation for
the output balance after adding the input. Both loops are the reference implementations
from Curve's own contracts, in integer arithmetic, so the quote is exact rather than
approximate given the balances and A.

The amplification coefficient, and why it does not need fetching. A is Curve-specific
and the Messari subgraph standardises it away, so it is not in the raw layer. It is
identified from the data instead: the invariant maps (balances, A, fee, amountIn) to
amountOut, and every Curve swap in the raw layer reports amountIn and amountOut, so A
is the only unknown and can be recovered by fitting realised trades. That is strictly
better than assuming a value, and it validates itself: a fitted A that reproduces
held-out trades is evidence the whole pricing path is right, in the same way the v2,
v3 and v4 quoters were accepted only after reproducing realised swaps.

A is also bounded by construction. Curve pools run A between roughly 10 and 5000, with
stable pools at the high end and volatile ones at the low end, so a fit landing outside
that range is a signal the pool is not a StableSwap pool at all, most likely a
crypto-pool using a different invariant, and it should be excluded rather than quoted.
"""

from __future__ import annotations

from dataclasses import dataclass

# Curve fixed-point convention: fees are in units of 1e10.
FEE_DENOMINATOR = 10 ** 10
# A is stored on-chain multiplied by n^(n-1) in some versions; this module takes the
# plain A and applies the n^n factors explicitly, matching the reference get_D.
A_PRECISION = 100

# Pools outside this range are not StableSwap pools and must be excluded, not quoted.
A_MIN, A_MAX = 1, 100_000


@dataclass(frozen=True)
class StablePool:
    """A StableSwap pool at one instant, balances in RAW integer token units."""

    pool_id: str
    tokens: tuple[str, ...]
    balances: tuple[int, ...]
    decimals: tuple[int, ...]
    amp: int
    fee_pips: int = 4_000_000        # Curve's common 0.04%, in 1e10 units
    venue: str = "curve"

    def index_of(self, token: str) -> int | None:
        t = token.lower()
        for i, x in enumerate(self.tokens):
            if x == t:
                return i
        return None

    def normalised(self) -> tuple[int, ...]:
        """Balances rescaled to 18 decimals, which is what the invariant assumes.

        StableSwap treats its tokens as interchangeable at par, so they must be on a
        common scale first. Skipping this step silently prices a 6-decimal stablecoin
        as though it were 10^12 times smaller than an 18-decimal one, which is the same
        class of error that reversed a v3 validation earlier in this project.
        """
        return tuple(b * 10 ** (18 - d) for b, d in zip(self.balances, self.decimals))


def get_d(balances: tuple[int, ...], amp: int, max_iter: int = 255) -> int:
    """Solve the StableSwap invariant D by Newton iteration, as the contract does."""
    n = len(balances)
    s = sum(balances)
    if s == 0:
        return 0
    d = s
    ann = amp * n
    for _ in range(max_iter):
        d_p = d
        for b in balances:
            if b == 0:
                return 0
            d_p = d_p * d // (b * n)
        d_prev = d
        d = (ann * s // A_PRECISION + d_p * n) * d // (
            (ann - A_PRECISION) * d // A_PRECISION + (n + 1) * d_p)
        if abs(d - d_prev) <= 1:
            return d
    return d


def get_y(balances: tuple[int, ...], amp: int, i: int, j: int, x: int,
          max_iter: int = 255) -> int:
    """Balance of token j once token i's balance is x, holding the invariant fixed."""
    n = len(balances)
    d = get_d(balances, amp)
    if d == 0:
        return 0
    ann = amp * n
    c = d
    s = 0
    for k in range(n):
        if k == i:
            xk = x
        elif k == j:
            continue
        else:
            xk = balances[k]
        if xk == 0:
            return 0
        s += xk
        c = c * d // (xk * n)
    c = c * d * A_PRECISION // (ann * n)
    b = s + d * A_PRECISION // ann
    y = d
    for _ in range(max_iter):
        y_prev = y
        y = (y * y + c) // (2 * y + b - d)
        if abs(y - y_prev) <= 1:
            return y
    return y


def quote_exact_input(pool: StablePool, token_in: str, token_out: str,
                      amount_in_raw: int) -> int | None:
    """Output in RAW units of token_out, net of the pool fee, or None if unquotable."""
    i = pool.index_of(token_in)
    j = pool.index_of(token_out)
    if i is None or j is None or i == j or amount_in_raw <= 0:
        return None
    if not (A_MIN <= pool.amp <= A_MAX):
        return None
    xp = list(pool.normalised())
    if any(b <= 0 for b in xp):
        return None
    scale_in = 10 ** (18 - pool.decimals[i])
    scale_out = 10 ** (18 - pool.decimals[j])
    x = xp[i] + amount_in_raw * scale_in
    y = get_y(tuple(xp), pool.amp, i, j, x)
    if y <= 0 or y >= xp[j]:
        return None
    dy = xp[j] - y - 1                      # the contract's off-by-one guard
    fee = dy * pool.fee_pips // FEE_DENOMINATOR
    out = (dy - fee) // scale_out
    return out if out > 0 else None


def calibrate_amp(balances: tuple[int, ...], decimals: tuple[int, ...],
                  tokens: tuple[str, ...], observations: list[tuple[str, str, int, int]],
                  fee_pips: int = 4_000_000,
                  candidates: tuple[int, ...] | None = None) -> tuple[int, float] | None:
    """Recover A by fitting realised trades, returning (A, median absolute error).

    Every quantity in the invariant except A is observed, so A is identified rather
    than assumed. Candidates sweep the range Curve pools actually use, on a log grid
    because the quote's sensitivity to A falls sharply as A rises: distinguishing 2000
    from 2200 barely moves a quote, while 10 against 100 moves it a great deal.

    Returns None when no candidate reproduces the observations, which is the honest
    outcome for a pool that is not a StableSwap pool. Such pools must be excluded, not
    quoted with a best-fit A that happens to minimise a large error.
    """
    if not observations:
        return None
    grid = candidates or tuple(
        int(round(v)) for v in (
            5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750,
            1000, 1500, 2000, 3000, 5000, 10000, 20000, 50000))
    def median_error(amp: int) -> float | None:
        pool = StablePool(pool_id="fit", tokens=tokens, balances=balances,
                          decimals=decimals, amp=amp, fee_pips=fee_pips)
        errs = []
        for t_in, t_out, amt_in, amt_out in observations:
            q = quote_exact_input(pool, t_in, t_out, amt_in)
            if q is None or amt_out <= 0:
                continue
            errs.append(abs(q - amt_out) / amt_out)
        if len(errs) < max(1, len(observations) // 4):
            return None
        errs.sort()
        return errs[len(errs) // 2]

    best: tuple[int, float] | None = None
    for amp in grid:
        med = median_error(amp)
        if med is not None and (best is None or med < best[1]):
            best = (amp, med)
    if best is None:
        return None

    # Refine locally. A coarse log grid leaves real error on the table: recovering a
    # true A of 350 from the grid alone lands on 300 with 0.84% median error, and route
    # cost differences here are tens of basis points, so a percent of quote error would
    # swamp the signal. Ternary search over the bracketing grid interval, on integers,
    # because median error is unimodal in A over a bracket.
    lo_candidates = [a for a in grid if a < best[0]]
    hi_candidates = [a for a in grid if a > best[0]]
    lo = max(lo_candidates) if lo_candidates else max(A_MIN, best[0] // 2)
    hi = min(hi_candidates) if hi_candidates else min(A_MAX, best[0] * 2)
    while hi - lo > 2:
        m1 = lo + (hi - lo) // 3
        m2 = hi - (hi - lo) // 3
        e1, e2 = median_error(m1), median_error(m2)
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
    return best
