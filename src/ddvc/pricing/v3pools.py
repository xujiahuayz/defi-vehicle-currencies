"""Exact V3 pool statics (fee tier, token decimals) recovered offline.

The raw V3 layer holds swaps, mints and burns but no pool statics: no `feeTier`,
no `tickSpacing`, and no token `decimals`. All three are load-bearing. Fee enters
every quote directly, and decimals set the scale between the subgraph's
human-unit amounts and the raw integer units that `sqrtPriceX96` and `liquidity`
are denominated in. Getting decimals wrong by a factor of 10^12 is not a small
error: it silently turned a validation run into -100% and +1e17% quote errors.

The Graph gateway would serve all of it, but the eleven keys in `.env` are
quota-exhausted ("payment required for subsequent requests"), and topping up is
an open cost decision. Neither is needed, because both quantities are recoverable
from data already on disk.

FEE TIER, exactly. Every V3 pool is deployed by the canonical factory through
CREATE2, so its address is a pure function of `(token0, token1, fee)`:

    pool = keccak256(0xff ++ factory ++ keccak256(abi.encode(t0, t1, fee))
                     ++ POOL_INIT_CODE_HASH)[12:]

Only four fee tiers were ever enabled on mainnet, so computing all four addresses
and matching the observed pool id recovers the fee with certainty rather than
inference. This supersedes deducing the fee from the greatest common divisor of
observed initialized ticks, which is a guess that fails whenever a pool's
positions happen to share a coarser spacing than its tier allows.

DECIMALS, by identity. `sqrtPriceX96` encodes the RAW price while the subgraph's
`amount0`/`amount1` are decimal-adjusted, and the two are related by the decimals
gap alone:

    (sqrtPriceX96 / 2^96)^2 = amount1_raw / amount0_raw
                            = (amount1_human / amount0_human) * 10^(d1 - d0)

so `d1 - d0` is the base-10 log of the ratio between the two, taken over many
swaps and rounded. Pairing that gap with one anchor token of known decimals
pins both sides. Nearly every routing-relevant pool has a major asset on one
leg, which is exactly where the anchors are.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

try:                                                  # preferred, already a dep
    from eth_hash.auto import keccak as _keccak
except Exception:                                     # pragma: no cover
    from Crypto.Hash import keccak as _pyc

    def _keccak(b: bytes) -> bytes:
        return _pyc.new(digest_bits=256, data=b).digest()

FACTORY = bytes.fromhex("1F98431c8aD98523631AE4a59f267346ea31F984")
POOL_INIT_CODE_HASH = bytes.fromhex(
    "e34f199b19b2b4f47f68442619d555527d244f78a3297ea89325f843f87b8b54")

# The only tiers ever enabled on Ethereum mainnet, with their canonical spacings.
FEE_TIERS = (100, 500, 3000, 10000)
FEE_TO_TICK_SPACING = {100: 1, 500: 10, 3000: 60, 10000: 200}
DECIMAL_SAMPLE_SIZE = 12
DECIMAL_CONSENSUS_SHARE = 0.75

# Decimals we assert rather than derive. These are the vehicle candidates and the
# stablecoin anchors, so an error here would propagate everywhere; they are
# checked against the on-chain contracts and must not be edited casually.
ANCHOR_DECIMALS: dict[str, int] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": 18,  # WETH
    "0x0000000000000000000000000000000000000000": 18,  # native ETH sentinel
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,   # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7": 6,   # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f": 18,  # DAI
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": 8,   # WBTC
    "0x853d955acef822db058eb8505911ed77f175b99e": 18,  # FRAX
    "0x4fabb145d64652a948d72533023f6e7a623c7c53": 18,  # BUSD
    "0x5f98805a4e8be255a32880fdec7f6728c6568ba0": 18,  # LUSD
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": 18,  # stETH
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": 18,  # wstETH
}


def _addr_bytes(a: str) -> bytes:
    return bytes.fromhex(a[2:] if a.startswith("0x") else a)


@lru_cache(maxsize=1 << 16)
def compute_pool_address(token_a: str, token_b: str, fee: int) -> str:
    """CREATE2 address of the canonical V3 pool for this token pair and fee."""
    t0, t1 = _addr_bytes(token_a.lower()), _addr_bytes(token_b.lower())
    if t0 > t1:
        t0, t1 = t1, t0
    salt = _keccak(t0.rjust(32, b"\0") + t1.rjust(32, b"\0") + fee.to_bytes(32, "big"))
    return "0x" + _keccak(b"\xff" + FACTORY + salt + POOL_INIT_CODE_HASH)[12:].hex()


@lru_cache(maxsize=1 << 16)
def derive_fee_tier(pool_id: str, token0: str, token1: str) -> int | None:
    """Exact fee tier by CREATE2 address match, or None for a non-canonical pool.

    None is meaningful rather than a failure: it flags a pool this factory did not
    deploy, which should be excluded instead of quoted with a guessed fee.
    """
    pid = pool_id.lower()
    for fee in FEE_TIERS:
        if compute_pool_address(token0, token1, fee) == pid:
            return fee
    return None


def tick_spacing_for_fee(fee: int) -> int:
    return FEE_TO_TICK_SPACING.get(fee, 60)


def record_token_decimals(
    known: dict[str, int], token: str, decimals: int
) -> None:
    """Register one address-level decimal identity and reject conflicting pools."""
    address = token.lower()
    value = int(decimals)
    if not 0 <= value <= 36:
        raise ValueError(f"implausible token decimals for {address}: {value}")
    prior = ANCHOR_DECIMALS.get(address, known.get(address))
    if prior is not None and prior != value:
        raise ValueError(
            f"conflicting token decimals for {address}: {prior} versus {value}"
        )
    known[address] = value


def load_token_decimals(path: str | Path) -> dict[str, int]:
    """Load one validated address-level decimal registry from a parquet artefact."""
    import pandas as pd

    frame = pd.read_parquet(path, columns=["token", "decimals"])
    if frame.empty:
        raise ValueError(f"empty token-decimal registry: {path}")
    registry: dict[str, int] = {}
    for token, decimals in zip(frame["token"], frame["decimals"], strict=True):
        record_token_decimals(registry, str(token), int(decimals))
    if len(registry) != len(frame):
        raise ValueError(f"duplicate token identities in decimal registry: {path}")
    return registry


def decimals_gap_from_swaps(swaps: list[dict], min_obs: int = DECIMAL_SAMPLE_SIZE,
                            tol: float = 0.30) -> int | None:
    """`d1 - d0` from the gap between raw `sqrtPriceX96` and human amounts.

    Twelve swaps are required because this estimator feeds a maximum over every
    public pool. A single high-impact swap can put its average execution price near
    the wrong integer gap even when the ending marginal price is valid. That rare
    pool-level error is selected by the optimiser and becomes a 10x or 100x false
    route. The median of a rolling twelve-row sample rejects that failure while
    keeping the memory cost fixed. Pools without twelve mutually consistent usable
    observations remain outside exact-quote support.

    What the tolerance is for. A derived gap must land NEAR an integer, because a
    decimals gap is one by definition. A value sitting between integers means the
    identity did not hold, which is the signature of a rebasing or fee-on-transfer
    token whose amounts do not reconcile with reserves. Those must be rejected,
    not rounded: 99.99% of ground-truth observations fall within 0.30.

    The median over observations guards the remaining case where one row is junk.
    """
    gaps: list[float] = []
    for s in swaps:
        try:
            sq = int(s.get("sqrtPriceX96") or 0)
            a0, a1 = abs(float(s.get("amount0") or 0)), abs(float(s.get("amount1") or 0))
        except (TypeError, ValueError):
            continue
        if sq <= 0 or a0 <= 0 or a1 <= 0:
            continue
        price_raw = (sq / (1 << 96)) ** 2
        if price_raw <= 0:
            continue
        gaps.append(math.log10(price_raw / (a1 / a0)))
    if len(gaps) < min_obs:
        return None
    gaps.sort()
    med = gaps[len(gaps) // 2]
    candidate = round(med)
    support = sum(abs(gap - candidate) <= tol for gap in gaps)
    if (
        abs(med - candidate) > tol
        or support / len(gaps) < DECIMAL_CONSENSUS_SHARE
    ):
        return None                    # identity failed: rebasing or fee-on-transfer
    return int(candidate)


def resolve_decimals(
    token0: str,
    token1: str,
    swaps: list[dict],
    *,
    known_decimals: dict[str, int] | None = None,
) -> tuple[int, int] | None:
    """(dec0, dec1), using anchors where known and the price identity elsewhere.

    Returns None when neither leg is an anchor and the gap alone cannot pin the
    absolute scale, which is the honest outcome: the pool is then excluded rather
    than quoted on a guessed 18.
    """
    t0, t1 = token0.lower(), token1.lower()
    known = known_decimals or {}
    anchor0, anchor1 = ANCHOR_DECIMALS.get(t0), ANCHOR_DECIMALS.get(t1)
    if anchor0 is not None and anchor1 is not None:
        return anchor0, anchor1
    a0 = anchor0 if anchor0 is not None else known.get(t0)
    a1 = anchor1 if anchor1 is not None else known.get(t1)
    gap = decimals_gap_from_swaps(swaps)
    if gap is None:
        return None
    if a0 is not None and a1 is not None:
        return (a0, a1) if gap == a1 - a0 else None
    if a0 is not None:
        inferred = (a0, a0 + gap)
    elif a1 is not None:
        inferred = (a1 - gap, a1)
    else:
        return None
    if any(value < 0 or value > 36 for value in inferred):
        return None
    return inferred
