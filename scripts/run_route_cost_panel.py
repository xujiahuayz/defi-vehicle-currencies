#!/usr/bin/env python3
"""Build a first DVC-native route-cost panel for Proposition 1.

This ports the counterfactual idea from DDC into the DVC raw layout. It combines
V2-style constant-product pools from Uniswap V2/SushiSwap V2 hourly reserves
with Uniswap V3 quotes reconstructed from raw swaps plus mint/burn liquidity.
For each day, endpoint pair, vehicle candidate, and trade-size bucket, it
compares the best direct route against the best two-hop vehicle route available
in the same daily state.

The V3 layer maintains an incremental tick-net index from raw mints/burns and
uses the latest observed pool sqrtPrice/tick from raw swaps, so V3 quotes cross
initialized ticks offline without an RPC call.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.asset_types import canonical_token
from ddvc.fetch.raw import (
    block_value,
    timestamp_value,
    v4_pool_quote_supported,
    v4_statics_complete,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.prices import day_prices
from ddvc.provenance import cache_key
from ddvc.provenance import stamp as record_provenance
from ddvc.pricing.v2quote import quote_exact_input_float
from ddvc.pricing.stableswap import StablePool
from ddvc.pricing.stableswap import calibrate_amp as _calibrate_amp
from ddvc.pricing.stableswap import quote_exact_input as _stable_quote
from ddvc.pricing.weighted import (
    FIT_QUANTILE as _WEIGHTED_QUANTILE,
)
from ddvc.pricing.weighted import (
    MAX_CALIBRATION_ERROR as _WEIGHTED_GATE,
)
from ddvc.pricing.weighted import (
    MIN_QUOTED_SHARE as _WEIGHTED_MIN_SHARE,
)
from ddvc.pricing.weighted import ONE as _WEIGHTED_ONE
from ddvc.pricing.weighted import BalanceEvent, WeightedPool
from ddvc.pricing.weighted import calibrate_fee as _calibrate_fee
from ddvc.pricing.weighted import (
    calibrate_weight_ratio as _calibrate_weight_ratio,
)
from ddvc.pricing.weighted import quote_error_at as _weighted_error
from ddvc.pricing.weighted import quote_exact_input as _weighted_quote
from ddvc.pricing.weighted import rebuild_pre_trade_balances
from ddvc.pricing.v3quote import get_sqrt_ratio_at_tick, quote_exact_input
from ddvc.pricing.v3pools import (
    derive_fee_tier,
    resolve_decimals,
    tick_spacing_for_fee,
)

ROOT = REPO_ROOT

# Swap samples per pool, used only to pin token decimals by the sqrtPriceX96
# identity. Capped per pool, so this stays small next to the swap stream itself.
_SWAP_SAMPLE: dict[str, list[dict]] = {}


VEHICLE_BY_ADDRESS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
}
VEHICLE_ADDRESSES = tuple(VEHICLE_BY_ADDRESS)
V2_SOURCES = ("uniswap_v2", "sushiswap_v2")
V3_START = "20210504"
CURVE_START = "20200211"
BALANCER_START = "20210422"          # Balancer v2's first indexed swap day
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

# SUPPORT BOUND. A leg is not quoted when its input exceeds this fraction of the pool's
# input-side reserve.
#
# Every quoter here was validated on REALISED swaps, which are by construction trades
# someone chose to make in a pool deep enough to serve them. Applying them to hypothetical
# routes through pools no router would touch is extrapolation with no measured error, and
# the consequence was quantified: between 44.5% and 82.0% of the panel's gaps implied an
# arbitrage cycle that pays after three pool fees and three-hop gas, with a median gap of
# 4,655 basis points at a 100,000 dollar trade. A 46.5% same-block arbitrage would be
# taken instantly with a flash loan and no capital, so those gaps were not economics.
#
# The screen is EX-ANTE on the pool and never on the gap. Filtering on the gap conditions
# on the magnitude of a monotone function of the outcome, which is selection on the
# dependent variable, and that error already voided this project's previous defence
# against quote collapse.
#
# The level is a judgement and is stated as one. Measured over 932,270 realised swaps that
# clear the physical bound, trade size as a fraction of the input reserve is 0.0034 at the
# median, 0.0329 at the 90th percentile, 0.0541 at the 95th and 0.1486 at the 99th. The
# 99.9th percentile is 0.7833, and taking it would be wrong: a trade at 78% of a reserve
# moves price by roughly that much and is exactly what manufactures impossible gaps. The
# 95th percentile keeps essentially all ordinary trading while capping a single leg's price
# impact near a few hundred basis points, which is the order of the effects being measured.
# Reported as a parameter with sensitivity, never as a buried constant.
MAX_INPUT_TO_RESERVE = 0.05

# The same bound, expressed venue-agnostically as the leg's OWN price impact, so it
# applies to concentrated liquidity, StableSwap and weighted pools as well. A leg is
# rejected when its effective price is worse than its marginal price by more than this.
#
# Applying the reserve-ratio form to the constant-product branch alone was not enough:
# the median gap at a 100,000 dollar trade fell from 4,655 to 1,164 basis points, but
# 70.4% of gaps still implied a cycle that pays, because Uniswap v3 supplies most quotes
# and had no bound at all.
#
# This is NOT selection on the outcome. Price impact is a property of one leg against its
# own marginal price, computed without reference to the competing route, whereas the
# outcome is whether the direct route beats the vehicle route. Rejecting a leg nobody
# would take does not condition on which route wins.
MAX_PRICE_IMPACT = 0.05
MAX_ROUTE_WORKERS = 10


def _impact_ok(marginal_out: float, actual_out: float) -> bool:
    """Is this leg inside the support, judged by its own slippage?"""
    if marginal_out <= 0 or actual_out <= 0:
        return False
    return (marginal_out - actual_out) / marginal_out <= MAX_PRICE_IMPACT


def bounded_route_workers(requested: int) -> int:
    return min(MAX_ROUTE_WORKERS, max(1, requested))
OUT_DATA = DATA_DIR / "empirical"
OUT = OUTPUT_DIR / "empirical"


# Cache generation = fingerprint of every source that can change a quote. Keyed in
# the PATH so a stale generation cannot be read at all, rather than being readable
# and merely mislabelled, which is how the hand-managed `v3_exact_tick` label let
# 2,242 days of quotes from a broken quoter survive two correctness fixes.
QUOTE_SOURCES = [
    "src/ddvc/pricing/v3quote.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/pricing/v2quote.py",
    # Curve and Balancer price legs too, so a change to either changes quotes. Omitting
    # them left the fingerprint dishonest: tightening the Curve calibration gate would
    # not have invalidated a single cached day, which is the same defect as the original
    # date-keyed cache that served quotes from a broken quoter through two fixes.
    "src/ddvc/pricing/stableswap.py",
    "src/ddvc/pricing/weighted.py",
    "scripts/run_route_cost_panel.py",
]
QUOTE_INPUTS = [
    DATA_DIR / "unified",
    *(DATA_DIR / "raw" / "thegraph" / venue for venue in (
        "uniswap_v2",
        "sushiswap_v2",
        "uniswap_v3",
        "uniswap_v4",
        "curve",
        "balancer",
    )),
]
QUOTE_ENGINE = cache_key(QUOTE_SOURCES, inputs=QUOTE_INPUTS)
PANEL_SOURCES = [*QUOTE_SOURCES, "src/ddvc/panel_assembly.py"]

# Cached day content also depends on the arguments that decide WHAT is computed,
# not only on the code that computes it. The cache ignored them, so a run at
# `--hour 0` silently reused rows priced at `--hour 12`, and a wider `--top-pairs`
# reused the narrower pair set. Both belong in the key for the same reason the
# code fingerprint does.
DAY_CACHE = OUT_DATA / "_route_cost_day_cache" / f"engine_{QUOTE_ENGINE}"


def parse_hours(spec: str) -> tuple[int, ...]:
    """'12' | '0,6,12,18' | '0-23' | 'all' -> a tuple of UTC hours."""
    s = spec.strip().lower()
    if s == "all":
        return tuple(range(24))
    out: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return tuple(sorted(h for h in out if 0 <= h <= 23))


def _configure_cache(hours: tuple[int, ...], top_pairs: int, sizes: list[float],
                     no_v3: bool) -> Path:
    global DAY_CACHE
    hspec = "all" if len(hours) == 24 else "-".join(str(h) for h in hours)
    spec = (f"h{hspec}_p{top_pairs}_s{'-'.join(str(int(x)) for x in sizes)}"
            f"{'_nov3' if no_v3 else ''}{'_splitwrapped' if not UNIFY_WRAPPED else ''}")
    DAY_CACHE = OUT_DATA / "_route_cost_day_cache" / f"engine_{QUOTE_ENGINE}" / spec
    DAY_CACHE.mkdir(parents=True, exist_ok=True)
    return DAY_CACHE


@dataclass(frozen=True)
class Pool:
    source: str
    pool: str
    kind: str
    token0: str
    token1: str
    sym0: str
    sym1: str
    dec0: int
    dec1: int
    reserve0: float
    reserve1: float
    liquidity: int = 0
    sqrt_price_x96: int = 0
    tick: int = 0
    fee_pips: int = 3000
    tick_spacing: int = 60
    tick_net: dict[int, int] | None = None
    sorted_ticks: tuple[int, ...] | None = None
    sqrt_ticks: tuple[int, ...] | None = None
    stable: object | None = None      # StablePool for Curve-style n-token pools
    weighted: object | None = None    # WeightedPool for Balancer n-token weighted pools
    # W(token0) / W(token1) when the pool's reported weights failed their fit and the ratio
    # was identified from trades instead. None means the WeightedPool's own weights are used.
    weight_ratio: object | None = None


@dataclass
class V3PoolState:
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


def _raw_path(source: str, stream: str, stamp: str) -> Path:
    return DATA_DIR / "raw" / "thegraph" / source / f"{source}_{stream}_{stamp}.jsonl.gz"


def _available_stamps(start: str | None, end: str | None) -> list[str]:
    files = sorted((DATA_DIR / "unified").glob("[0-9]" * 8 + ".parquet"))
    stamps = [f.stem for f in files]
    if start:
        s = start.replace("-", "")
        stamps = [x for x in stamps if x >= s]
    if end:
        e = end.replace("-", "")
        stamps = [x for x in stamps if x <= e]
    return stamps


def _routes_by_pair(legs: pd.DataFrame, top_pairs: int) -> pd.DataFrame:
    clean = legs[legs["route_class"].isin(["single", "coherent"])]
    if clean.empty:
        return pd.DataFrame()

    clean = clean.copy()
    clean["component_key"] = clean["tx_hash"].astype(str) + "#" + clean["component_id"].astype(str)
    left = clean[["component_key", "token_in", "token_in_sym", "tin_role"]].rename(
        columns={"token_in": "token", "token_in_sym": "symbol", "tin_role": "role"}
    )
    right = clean[["component_key", "token_out", "token_out_sym", "tout_role"]].rename(
        columns={"token_out": "token", "token_out_sym": "symbol", "tout_role": "role"}
    )
    roles = pd.concat([left, right], ignore_index=True)
    # Canonicalise route ENDPOINTS the same way pool tokens are canonicalised.
    # Applying `canonical_token` to pool tokens but not to src/tgt made native ETH
    # resolve to WETH on one side of the join and stay as the zero address on the
    # other, so no pool key could ever match a native-ETH endpoint. 2,568,384 rows
    # carried direct_available and vehicle_available at exactly 0.000 against 0.722
    # and 0.336 elsewhere, which deleted precisely the pairs the native-asset
    # question is about, and it also starved Uniswap v4, whose pools are
    # native-ETH-paired: v4 legs survived on 30 of the 546 days its flow exists.
    roles["token"] = [canonical_token(x, unify_wrapped=UNIFY_WRAPPED) or ""
                      for x in roles["token"].astype(str).str.lower()]
    roles = roles[roles["token"].astype(bool)]
    sources = (
        roles[roles["role"].eq("source")][["component_key", "token", "symbol"]]
        .drop_duplicates()
        .rename(columns={"token": "src", "symbol": "src_sym"})
    )
    sinks = (
        roles[roles["role"].eq("sink")][["component_key", "token", "symbol"]]
        .drop_duplicates()
        .rename(columns={"token": "tgt", "symbol": "tgt_sym"})
    )
    if sources.empty or sinks.empty:
        return pd.DataFrame()

    vol = (
        clean.groupby("component_key", as_index=False)["amount_usd"]
        .mean()
        .rename(columns={"amount_usd": "volume"})
    )
    out = sources.merge(sinks, on="component_key", how="inner").merge(vol, on="component_key", how="left")
    out = out[out["src"].ne(out["tgt"])]
    if out.empty:
        return pd.DataFrame()
    out = (
        out.groupby(["src", "src_sym", "tgt", "tgt_sym"], as_index=False)
        .agg(realized_bridge_volume_usd=("volume", "sum"), n_routes=("volume", "size"))
        .sort_values("realized_bridge_volume_usd", ascending=False)
        .head(top_pairs)
    )
    return out


def _load_v2_pools_by_hour(stamp: str,
                           hours: tuple[int, ...]) -> dict[int, dict[frozenset[str], list[Pool]]]:
    """Pools for several hours of one day, in a single pass over each file.

    Reading the file once per hour would multiply IO by the number of hours for no
    gain, since every hour's rows sit in the same file. This keys rows by their
    `hourStartUnix` instead, so asking for all 24 hours costs one read.
    """
    ts_to_hour = {
        int(pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]} {h:02d}:00:00",
                         tz="UTC").timestamp()): h
        for h in hours
    }
    by_hour: dict[int, dict[frozenset[str], list[Pool]]] = {
        h: defaultdict(list) for h in hours}
    for source in V2_SOURCES:
        path = _raw_path(source, "hourly_reserves", stamp)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec = json.loads(line)
                hour = ts_to_hour.get(int(rec.get("hourStartUnix", -1)))
                if hour is None:
                    continue
                pools = by_hour[hour]
                pair = rec.get("pair") or {}
                t0 = pair.get("token0") or {}
                t1 = pair.get("token1") or {}
                try:
                    r0 = float(rec.get("reserve0") or 0)
                    r1 = float(rec.get("reserve1") or 0)
                except (TypeError, ValueError):
                    continue
                a0 = canonical_token(t0.get("id"), unify_wrapped=UNIFY_WRAPPED)
                a1 = canonical_token(t1.get("id"), unify_wrapped=UNIFY_WRAPPED)
                if not a0 or not a1 or r0 <= 0 or r1 <= 0:
                    continue
                pools[frozenset((a0, a1))].append(Pool(
                    source=source,
                    pool=str(pair.get("id", "")).lower(),
                    kind="v2",
                    token0=a0,
                    token1=a1,
                    sym0=str(t0.get("symbol", "")),
                    sym1=str(t1.get("symbol", "")),
                    dec0=int(t0.get("decimals", 18) or 18),
                    dec1=int(t1.get("decimals", 18) or 18),
                    reserve0=r0,
                    reserve1=r1,
                ))
    return by_hour


# One day's reserves, held for as long as that day is being priced. Days are
# processed in order, so a single entry is enough to turn 24 hourly lookups into one
# file read without holding the whole sample in memory.
_V2_DAY: dict[str, object] = {"stamp": None, "hours": None, "pools": None}


def _load_v2_pools(stamp: str, hour: int,
                   hours: tuple[int, ...] | None = None) -> dict[frozenset[str], list[Pool]]:
    want = hours or (hour,)
    if _V2_DAY["stamp"] != stamp or _V2_DAY["hours"] != want:
        _V2_DAY.update(stamp=stamp, hours=want,
                       pools=_load_v2_pools_by_hour(stamp, want))
    return _V2_DAY["pools"].get(hour, {})


def _infer_tick_spacing(ticks: dict[int, int]) -> int:
    vals = [abs(t) for t in ticks if t != 0]
    if not vals:
        return 60
    g = 0
    for val in vals:
        g = math.gcd(g, val)
    if g <= 1:
        return 1
    if g <= 10:
        return 10
    if g <= 60:
        return 60
    return 200


# Concentrated-liquidity venues, and how each reports a liquidity change. Uniswap
# v3 splits additions and removals into `mints` and `burns`, so the sign is carried
# by the stream. Uniswap v4 emits one `modify_liquidities` stream whose `amount` is
# already signed, a removal being negative, so its sign multiplier is +1.
TICK_VENUES: dict[str, tuple[tuple[str, int], ...]] = {
    "uniswap_v3": (("mints", 1), ("burns", -1)),
    "uniswap_v4": (("modify_liquidities", 1),),
}
V4_START = "20250101"

# Whether native ETH (Uniswap v4's zero address) and WETH are ONE currency or two.
# Set from --split-wrapped and included in the cache key, because it changes which
# routes exist rather than merely how they are labelled. See
# ddvc.asset_types.canonical_token for why the unified reading is primary.
UNIFY_WRAPPED = True


def _apply_tick_liquidity_events(
    venue: str,
    stamp: str,
    tick_net_by_pool: dict[str, dict[int, int]],
) -> None:
    """Accumulate net liquidity per initialized tick for one venue-day.

    Tick spacing is deliberately NOT tracked here. It was recomputed by taking a
    greatest common divisor over every tick in the pool on every single liquidity
    event, which is quadratic in events per pool per day and was a large share of
    the index warm-up, and the quoter never reads it: traversal is driven by the
    initialized ticks themselves.
    """
    for stream, sign in TICK_VENUES[venue]:
        path = _raw_path(venue, stream, stamp)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec = json.loads(line)
                pool = str((rec.get("pool") or {}).get("id", "")).lower()
                if not pool:
                    continue
                try:
                    amt = int(rec.get("amount") or 0)
                    lower = int(rec.get("tickLower"))
                    upper = int(rec.get("tickUpper"))
                except (TypeError, ValueError):
                    continue
                if amt == 0:
                    continue
                ticks = tick_net_by_pool.setdefault(pool, {})
                ticks[lower] = ticks.get(lower, 0) + sign * amt
                ticks[upper] = ticks.get(upper, 0) - sign * amt
                if ticks[lower] == 0:
                    del ticks[lower]
                if ticks.get(upper) == 0:
                    del ticks[upper]


def _absorb_swap_state(venue: str, rec: dict,
                       state_by_pool: dict[str, V3PoolState]) -> None:
    """Fold one swap into a venue's price state, keeping the latest by (block, log).

    Pool statics come from different places by venue and neither is guessed. v3 carries
    no feeTier in this raw layer, so the fee is recovered exactly from the CREATE2 pool
    address and decimals from the sqrtPriceX96 identity. v4 carries both feeTier and
    token decimals and tick spacing directly. Vanilla static-fee pools are priced at
    their declared fee, including non-v3 tiers. Dynamic-fee and hook-bearing pools are
    excluded because these rows do not reveal the per-swap hook cash flows or fee.
    """
    pool = rec.get("pool") or {}
    t0 = pool.get("token0") or {}
    t1 = pool.get("token1") or {}
    pool_id = str(pool.get("id", "")).lower()
    raw0 = str(t0.get("id", "")).lower()
    raw1 = str(t1.get("id", "")).lower()
    a0 = canonical_token(raw0, unify_wrapped=UNIFY_WRAPPED)
    a1 = canonical_token(raw1, unify_wrapped=UNIFY_WRAPPED)
    if not pool_id or not a0 or not a1:
        return
    try:
        # Alternate v4 Graph schemas can expose the transaction hash as a scalar
        # and omit blockNumber. Ethereum timestamps order their blocks, so a
        # timestamp is the honest fallback within a raw day.
        block = int(block_value(rec) or timestamp_value(rec) or 0)
        log_index = int(rec.get("logIndex") or 0)
        sqrt_price = int(rec.get("sqrtPriceX96") or rec.get("sqrtPrice") or 0)
        tick = int(rec.get("tick") or 0)
    except (TypeError, ValueError):
        return
    if sqrt_price <= 0:
        return
    old = state_by_pool.get(pool_id)
    if old is not None and (block, log_index) <= (old.block, old.log_index):
        return
    if venue == "uniswap_v4":
        if not v4_pool_quote_supported(rec):
            return
        try:
            fee = int(pool.get("feeTier"))
            tick_spacing = int(pool.get("tickSpacing"))
            dec = (int(t0.get("decimals")), int(t1.get("decimals")))
        except (TypeError, ValueError):
            return
    else:
        sample = _SWAP_SAMPLE.setdefault(pool_id, [])
        if len(sample) < 12:
            sample.append(rec)
        exact_fee = derive_fee_tier(pool_id, raw0, raw1)
        if exact_fee is None:
            return
        fee = exact_fee
        dec = resolve_decimals(raw0, raw1, sample)
        if dec is None:
            return
        tick_spacing = tick_spacing_for_fee(fee)
    state_by_pool[pool_id] = V3PoolState(
        pool=pool_id, token0=a0, token1=a1,
        sym0=str(t0.get("symbol", "")), sym1=str(t1.get("symbol", "")),
        dec0=dec[0], dec1=dec[1],
        sqrt_price_x96=sqrt_price, tick=tick, fee_pips=fee,
        tick_spacing=tick_spacing, block=block, log_index=log_index)


def _validate_v4_swap_schema(stamps: list[str]) -> None:
    """Refuse a build when any nonempty v4 day predates the required raw schema."""
    invalid: list[str] = []
    missing: list[str] = []
    for stamp in stamps:
        if stamp < V4_START:
            continue
        path = _raw_path("uniswap_v4", "swaps", stamp)
        if not path.exists():
            missing.append(stamp)
            continue
        with gzip.open(path, "rt") as fh:
            if any(
                not v4_statics_complete(json.loads(line))
                for line in fh
                if line.strip()
            ):
                invalid.append(stamp)
    if invalid or missing:
        problems = [*(f"{stamp} (missing)" for stamp in missing), *invalid]
        preview = ", ".join(problems[:5])
        more = f" and {len(problems) - 5:,} more" if len(problems) > 5 else ""
        raise RuntimeError(
            "Uniswap v4 raw swaps are missing or lack fee/tick-spacing/hook/token-decimal "
            f"statics on {len(problems):,} day(s): {preview}{more}. "
            "Refetch the swaps stream before pricing."
        )


def _update_tick_swap_state(venue: str, stamp: str,
                            state_by_pool: dict[str, V3PoolState]) -> None:
    """Whole-day price state, used only when warming the index past unpriced days."""
    path = _raw_path(venue, "swaps", stamp)
    if not path.exists():
        return
    with gzip.open(path, "rt") as fh:
        for line in fh:
            _absorb_swap_state(venue, json.loads(line), state_by_pool)


def load_day_tick_events(venue: str, stamp: str) -> dict[int, dict[str, list]]:
    """One day of a tick venue's events, bucketed by UTC hour, in one pass per file.

    Why this exists. State was advanced a whole DAY at a time and then all 24 priced
    hours shared that single end-of-day snapshot, while the v2 family was priced at
    each hour's own end-of-hour reserves. So an "hour" compared a constant-product pool
    at hour 3 against a concentrated-liquidity pool at hour 23. Measured on the deepest
    USDC/WETH pool on a calm day, that misalignment moved the price a median 0.345% and
    up to 1.04%, which is as large as the route-cost differences the panel exists to
    measure. The hourly dimension was fictitious for v3 and v4, and the error was
    present even in the original single-hour panel, where v2 sat at hour 12 and the
    tick venues sat at end of day.

    Reading per hour would multiply IO by 24, so each file is read once and its rows
    are bucketed by the hour they occurred in. The caller then advances state hour by
    hour and prices each hour against the state as of that hour.
    """
    out: dict[int, dict[str, list]] = {h: {"liq": [], "swaps": []} for h in range(24)}
    for stream, sign in TICK_VENUES[venue]:
        path = _raw_path(venue, stream, stamp)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec = json.loads(line)
                try:
                    ts = int(rec.get("timestamp") or 0)
                except (TypeError, ValueError):
                    continue
                if ts <= 0:
                    continue
                out[(ts % 86400) // 3600]["liq"].append((sign, rec))
    path = _raw_path(venue, "swaps", stamp)
    if path.exists():
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec = json.loads(line)
                try:
                    ts = int(timestamp_value(rec) or 0)
                except (TypeError, ValueError):
                    continue
                if ts <= 0:
                    continue
                out[(ts % 86400) // 3600]["swaps"].append(rec)
    return out


def apply_hour_events(venue: str, bucket: dict[str, list],
                      tick_net_by_pool: dict[str, dict[int, int]],
                      state_by_pool: dict[str, V3PoolState]) -> None:
    """Advance one tick venue's liquidity index and price state by a single hour."""
    for sign, rec in bucket["liq"]:
        pool = str((rec.get("pool") or {}).get("id", "")).lower()
        if not pool:
            continue
        try:
            amt = int(rec.get("amount") or 0)
            lower, upper = int(rec["tickLower"]), int(rec["tickUpper"])
        except (TypeError, ValueError, KeyError):
            continue
        if amt == 0:
            continue
        ticks = tick_net_by_pool.setdefault(pool, {})
        ticks[lower] = ticks.get(lower, 0) + sign * amt
        ticks[upper] = ticks.get(upper, 0) - sign * amt
        if ticks[lower] == 0:
            del ticks[lower]
        if ticks.get(upper) == 0:
            del ticks[upper]
    for rec in bucket["swaps"]:
        _absorb_swap_state(venue, rec, state_by_pool)


def advance_tick_venues(
    stamp: str,
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    state_by_venue: dict[str, dict[str, V3PoolState]],
) -> None:
    """Apply one day of liquidity events and price updates for every tick venue.

    Kept as one function so a caller cannot advance v3 and forget v4: the index is
    a running sum from inception, and a venue silently left un-advanced would quote
    against stale liquidity without failing.
    """
    for venue, start in (("uniswap_v3", V3_START), ("uniswap_v4", V4_START)):
        if stamp < start:
            continue
        _apply_tick_liquidity_events(venue, stamp, ticks_by_venue.setdefault(venue, {}))
        _update_tick_swap_state(venue, stamp, state_by_venue.setdefault(venue, {}))


def _active_liquidity(ticks: dict[int, int], current_tick: int) -> int:
    return sum(v for t, v in ticks.items() if t <= current_tick)


def _load_tick_pools_from_state(
    venue: str,
    state_by_pool: dict[str, V3PoolState],
    tick_net_by_pool: dict[str, dict[int, int]],
    required_pairs: set[frozenset[str]] | None = None,
) -> dict[frozenset[str], list[Pool]]:
    pools: dict[frozenset[str], list[Pool]] = defaultdict(list)
    for pool_id, st in state_by_pool.items():
        key = frozenset((st.token0, st.token1))
        if required_pairs is not None and key not in required_pairs:
            continue
        ticks = tick_net_by_pool.get(pool_id)
        if not ticks:
            continue
        liq = _active_liquidity(ticks, st.tick)
        if liq <= 0:
            continue
        sorted_ticks = tuple(sorted(ticks))
        sqrt_ticks = tuple(get_sqrt_ratio_at_tick(t) for t in sorted_ticks)
        pools[key].append(Pool(
                source=venue,
                pool=pool_id,
                kind="tick_exact",
                token0=st.token0,
                token1=st.token1,
                sym0=st.sym0,
                sym1=st.sym1,
                dec0=st.dec0,
                dec1=st.dec1,
                reserve0=0.0,
                reserve1=0.0,
                liquidity=liq,
                sqrt_price_x96=st.sqrt_price_x96,
                tick=st.tick,
                fee_pips=st.fee_pips,
                tick_spacing=st.tick_spacing,
                tick_net=ticks,
                sorted_ticks=sorted_ticks,
                sqrt_ticks=sqrt_ticks,
        ))
    return pools



# Curve pools, keyed on the day. The amplification coefficient is not published by the
# Messari subgraph, so it is calibrated per pool-day from that day's own realised trades
# and the pool is admitted only if the calibration reproduced them: median 0.022% error
# with 98.8% of quotes inside 1% across seven validated days. A pool whose best fit is
# poor is running a different invariant, almost always one of Curve's crypto-pools, and
# is excluded rather than quoted with an error that would enter the panel as depth.
_CURVE_DAY: dict[str, object] = {"stamp": None, "pools": None}


def _load_curve_pools(stamp: str) -> dict[frozenset[str], list[Pool]]:
    """Quotable Curve pools for one day, calibrated and screened.

    An n-token pool serves every pair among its tokens, so one pool registers under
    each unordered pair it can bridge. Balances are daily snapshots, which the
    validation showed is adequate here: intra-day drift would have surfaced in that
    0.022% error and did not.
    """
    if _CURVE_DAY["stamp"] == stamp:
        return _CURVE_DAY["pools"]

    meta: dict[str, dict] = {}
    path = _raw_path("curve", "daily", stamp)
    if path.exists():
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                pool = r.get("pool") or {}
                pid = str(pool.get("id", "")).lower()
                bals = r.get("inputTokenBalances")
                toks = pool.get("inputTokens") or []
                if not pid or not bals or len(bals) != len(toks) or len(toks) < 2:
                    continue
                try:
                    meta[pid] = {
                        "tokens": tuple(
                            canonical_token(tk.get("id"), unify_wrapped=UNIFY_WRAPPED) or ""
                            for tk in toks),
                        "raw_tokens": tuple(str(tk.get("id", "")).lower() for tk in toks),
                        "decimals": tuple(int(tk.get("decimals")) for tk in toks),
                        "balances": tuple(int(b) for b in bals),
                        "syms": tuple(str(tk.get("symbol", "")) for tk in toks),
                    }
                except (TypeError, ValueError):
                    continue

    trades: dict[str, list] = defaultdict(list)
    spath = _raw_path("curve", "swaps", stamp)
    if spath.exists() and meta:
        with gzip.open(spath, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                s = json.loads(line)
                pid = ((s.get("pool") or {}).get("id") or "").lower()
                if pid not in meta:
                    continue
                try:
                    ti = str(s["tokenIn"]["id"]).lower()
                    to = str(s["tokenOut"]["id"]).lower()
                    ai, ao = int(s["amountIn"]), int(s["amountOut"])
                except (KeyError, TypeError, ValueError):
                    continue
                if ai > 0 and ao > 0:
                    trades[pid].append((ti, to, ai, ao))

    pools: dict[frozenset[str], list[Pool]] = defaultdict(list)
    for pid, m in meta.items():
        obs = trades.get(pid) or []
        if len(obs) < 4:
            continue
        fit = _calibrate_amp(m["balances"], m["decimals"], m["raw_tokens"], obs)
        if fit is None:
            continue
        amp, _err = fit
        sp = StablePool(pool_id=pid, tokens=m["raw_tokens"], balances=m["balances"],
                        decimals=m["decimals"], amp=amp)
        n = len(m["tokens"])
        for i in range(n):
            for j in range(i + 1, n):
                a, b = m["tokens"][i], m["tokens"][j]
                if not a or not b or a == b:
                    continue
                pools[frozenset((a, b))].append(Pool(
                    source="curve", pool=pid, kind="stable",
                    token0=a, token1=b, sym0=m["syms"][i], sym1=m["syms"][j],
                    dec0=m["decimals"][i], dec1=m["decimals"][j],
                    reserve0=0.0, reserve1=0.0, stable=sp))
    _CURVE_DAY.update(stamp=stamp, pools=pools)
    return pools


# Balancer weighted pools, keyed on the day AND resolved to each hour of it.
#
# Why this is not a daily loader like Curve's. Balancer publishes one `poolSnapshots.amounts`
# record per pool-day, and pricing every hour of the day against that one vector is the
# mixed-instant defect this panel already paid for once, when the concentrated-liquidity venues
# sat at end of day while the constant-product family sat at end of hour and the two disagreed by
# a median 0.345% against a signal of tens of basis points. Curve could take the daily reading
# because StableSwap near par is almost flat, and the validation confirmed intra-day drift was
# invisible in its 0.022% error. Balancer weighted pools hold volatile assets on purpose, so the
# same shortcut is not available: holding the snapshot flat across the day costs a median 1.7% of
# quote error, which is five times the misalignment the panel already treated as a defect.
#
# What makes hourly state cheap anyway. The snapshot is the balance after the day's LAST event, so
# netting the day's whole flow off it recovers the opening state and replaying that flow forward
# reaches every intermediate state, including the state at the end of each hour. The flow is the
# day's swaps plus its joins and exits, both already on disk, so the whole day's hourly path costs
# two file reads and no extra fetch. That is why Balancer gets end-of-hour balances on the same
# convention as the v2 family instead of a daily approximation.
_BAL_DAY: dict[str, object] = {"stamp": None, "hours": None, "pools": None}

# A pool-day with fewer trades than this cannot be screened at all, so it is excluded. Pricing it
# unscreened would put a pool whose maths was never checked into the panel, which is the thing the
# achieved-fit-error rule exists to prevent.
_BAL_MIN_SCREEN_TRADES = 2

# Fitting a parameter needs more evidence than reading one. Below this, only the reported weights
# and fee are allowed, because one free scalar against two or three trades fits them by
# construction and the clean fit that produces means nothing.
_BAL_MIN_FIT_TRADES = 4


def _bal_pool_meta(stamp: str) -> dict[str, dict]:
    """Per-pool statics and the day's CLOSING balances, in RAW integer units."""
    meta: dict[str, dict] = {}
    path = _raw_path("balancer", "daily", stamp)
    if not path.exists():
        return meta
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            pool = r.get("pool") or {}
            pid = str(pool.get("id", "")).lower()
            toks = pool.get("tokens") or []
            order = [str(a).lower() for a in (pool.get("tokensList") or [])]
            amounts = r.get("amounts") or []
            if not pid or len(toks) < 2 or len(order) != len(amounts):
                continue
            try:
                raw_tokens = tuple(str(t.get("address", "")).lower() for t in toks)
                decimals = tuple(int(t["decimals"]) for t in toks)
                weights = tuple(
                    int(Decimal(str(t["weight"])) * _WEIGHTED_ONE)
                    if t.get("weight") is not None else 0
                    for t in toks)
                human = dict(zip(order, amounts))
                closing = tuple(
                    int((Decimal(str(human.get(a, "0"))) * (10 ** d)).to_integral_value())
                    for a, d in zip(raw_tokens, decimals))
                fee = int(Decimal(str(pool.get("swapFee") or "0")) * _WEIGHTED_ONE)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
            canon = tuple(canonical_token(a, unify_wrapped=UNIFY_WRAPPED) or ""
                          for a in raw_tokens)
            # Canonicalising native ETH onto WETH could in principle collapse two of one pool's
            # tokens into one address, and the quote looks its tokens up by address, so the pool
            # would silently price the wrong leg. Balancer holds WETH and not native ETH so this
            # should never fire, and it is checked instead of assumed.
            present = [c for c in canon if c]
            if len(set(present)) != len(present):
                continue
            meta[pid] = {
                "raw_tokens": raw_tokens, "tokens": canon, "decimals": decimals,
                "weights": weights, "closing": closing, "fee": fee,
                "syms": tuple(str(t.get("symbol", "")) for t in toks),
                "pool_type": str(pool.get("poolType") or "unknown"),
            }
    return meta


def _bal_day_events(stamp: str, meta: dict[str, dict]) -> dict[str, list]:
    """The day's swaps, joins and exits per pool, in execution order with their hour.

    `block` orders across blocks and the decimal log index suffixed to an entity id orders within
    one block, which is the only intra-block ordering the raw layer carries. Joins and exits are
    merged into the same sequence because they move balances too, and a swap-only walk leaves an
    unobservable jump wherever liquidity entered or left the pool.
    """
    day_start = int(pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}", tz="UTC").timestamp())

    def hour_of(ts: int) -> int:
        return min(23, max(0, (int(ts) - day_start) // 3600))

    def log_index(entity_id: str) -> int:
        return int(entity_id[66:]) if len(entity_id) > 66 else 0

    staged: dict[str, list] = defaultdict(list)
    spath = _raw_path("balancer", "swaps", stamp)
    if spath.exists():
        with gzip.open(spath, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                s = json.loads(line)
                pid = ((s.get("poolId") or {}).get("id") or "").lower()
                if pid not in meta:
                    continue
                try:
                    staged[pid].append((
                        int(s["block"]), log_index(str(s["id"])), hour_of(s["timestamp"]),
                        "swap", str(s["tokenIn"]).lower(), str(s["tokenOut"]).lower(),
                        Decimal(str(s["tokenAmountIn"])), Decimal(str(s["tokenAmountOut"])),
                        None))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue
    jpath = _raw_path("balancer", "joins_exits", stamp)
    if jpath.exists():
        with gzip.open(jpath, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = json.loads(line)
                pool = e.get("pool") or {}
                pid = (pool.get("id") or "").lower()
                if pid not in meta:
                    continue
                order = [str(a).lower() for a in (pool.get("tokensList") or [])]
                amounts = e.get("amounts") or []
                if len(order) != len(amounts):
                    continue
                sign = -1 if str(e.get("type") or "").lower() == "exit" else 1
                try:
                    signed = {a: sign * Decimal(str(v)) for a, v in zip(order, amounts)}
                    staged[pid].append((
                        int(e["block"]), log_index(str(e["id"])), hour_of(e["timestamp"]),
                        "liquidity", None, None, None, None, signed))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue
    for v in staged.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return staged


def _bal_walk_day(m: dict, staged: list) -> tuple[list, dict[int, tuple[int, ...]]] | None:
    """Replay one pool's day, returning its scorable trades and its end-of-hour balances.

    Two things come out of one walk. The trades, each paired as an observation with the pool state
    it actually faced, which is what the screen is scored on. And the balances at the END of every
    hour, which is the state the panel prices that hour against, on the same convention the v2
    family's hourly reserves already use.
    """
    dec = dict(zip(m["raw_tokens"], m["decimals"]))
    idx = {t: i for i, t in enumerate(m["raw_tokens"])}
    n = len(m["raw_tokens"])
    events: list[BalanceEvent] = []
    swap_rows: list[tuple[str, str, int, int, int]] = []
    for _, _, hour, kind, t_in, t_out, amt_in, amt_out, signed in staged:
        deltas = [0] * n
        if kind == "swap":
            if t_in not in dec or t_out not in dec or t_in == t_out:
                return None
            try:
                raw_in = int((amt_in * (10 ** dec[t_in])).to_integral_value())
                raw_out = int((amt_out * (10 ** dec[t_out])).to_integral_value())
            except ArithmeticError:
                return None
            if raw_in <= 0 or raw_out <= 0:
                return None
            deltas[idx[t_in]] = raw_in
            deltas[idx[t_out]] = -raw_out
            swap_rows.append((t_in, t_out, raw_in, raw_out, hour))
            events.append(BalanceEvent(deltas=tuple(deltas), is_swap=True))
            continue
        for token, amount in signed.items():
            if token not in idx:
                continue                       # a token the snapshot does not carry
            try:
                deltas[idx[token]] = int((amount * (10 ** dec[token])).to_integral_value())
            except ArithmeticError:
                return None
        events.append(BalanceEvent(deltas=tuple(deltas), is_swap=False))

    path = rebuild_pre_trade_balances(m["closing"], events)
    if path is None or len(path) != len(swap_rows):
        return None

    # The opening state is the pre-trade state of the first swap when the day opens on a swap, and
    # otherwise it has to be recomputed, because a day opening on a join has no swap to read it
    # from. Netting the whole flow off the closing snapshot gives it either way.
    opening = list(m["closing"])
    for event in events:
        opening = [b - d for b, d in zip(opening, event.deltas)]

    # End-of-hour balances. Every event stamps the hour it landed in, so the last event of an hour
    # leaves that hour's closing state behind. Hours with no events carry the previous hour
    # forward, and hours before the day's first event carry the opening state.
    at_hour: dict[int, tuple[int, ...]] = {}
    running = list(opening)
    for event, (_, _, hour, *_rest) in zip(events, staged):
        running = [b + d for b, d in zip(running, event.deltas)]
        at_hour[hour] = tuple(running)
    hourly: dict[int, tuple[int, ...]] = {}
    carried = tuple(opening)
    for h in range(24):
        carried = at_hour.get(h, carried)
        hourly[h] = carried

    # Observations carry the pool's RAW token addresses, because trades reference those, and the
    # pool's reported fee, because the screen's first tier is exactly the reported parameters.
    observations = [
        (WeightedPool(pool_id="screen", tokens=m["raw_tokens"], balances=balances,
                      decimals=m["decimals"], weights=m["weights"], fee=m["fee"],
                      pool_type=m["pool_type"]),
         t_in, t_out, raw_in, raw_out)
        for balances, (t_in, t_out, raw_in, raw_out, _) in zip(path, swap_rows)
    ]
    return observations, hourly


def _bal_screen(m: dict, obs: list) -> tuple[int, dict] | None:
    """Accept a pool-day on achieved fit error, returning (fee, weight-ratio map) or None.

    Three tiers, each adding at most one free scalar, in order of how much they assume. Read
    parameters first, since for a plain weighted pool that never repriced itself the reported
    weights and fee are exact. Then the fee alone, which is the parameter most likely to be stale
    because the subgraph serves it at the head block and a pool's owner can change it. Then the
    weight ratio per token pair, which is what a liquidity-bootstrapping or managed pool needs.

    Nothing is excluded on `poolType`. Balancer's vault hosts stable, composable-stable,
    Gyroscope, linear and boosted pools and none of those is a weighted geometric mean, but the
    label is not the test: an amplification range that merely looked plausible let Curve
    crypto-pools into a StableSwap fit at 36% median error, and the fix there and here is to
    decide on the error a pool actually achieves.
    """
    if len(obs) < _BAL_MIN_SCREEN_TRADES:
        return None
    reported = _weighted_error(obs)
    if reported is not None and reported <= _WEIGHTED_GATE:
        return m["fee"], {}
    if len(obs) < _BAL_MIN_FIT_TRADES:
        return None

    fee_fit = _calibrate_fee(obs, max_error=_WEIGHTED_GATE)
    if fee_fit is not None:
        return fee_fit[0], {}

    by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for o in obs:
        key = (o[1], o[2]) if o[1] < o[2] else (o[2], o[1])
        by_pair[key].append(o)
    ratios: dict[tuple[str, str], object] = {}
    for (a, b), sub in by_pair.items():
        fit = _calibrate_weight_ratio(a, b, sub, max_error=_WEIGHTED_GATE)
        if fit is not None:
            ratios[(a, b)] = fit[0]
            ratios[(b, a)] = 1 / fit[0]
    if not ratios:
        return None
    covered = [o for o in obs if (o[1], o[2]) in ratios]
    if len(covered) < max(1, int(_WEIGHTED_MIN_SHARE * len(obs))):
        return None                             # a subset fit would leave the rest unpriced
    errs: list[float] = []
    for o in covered:
        q = _weighted_quote(o[0], o[1], o[2], o[3], weight_ratio=ratios[(o[1], o[2])])
        if q is None or o[4] <= 0:
            continue
        errs.append(abs(q - o[4]) / o[4])
    if len(errs) < max(1, int(_WEIGHTED_MIN_SHARE * len(obs))):
        return None
    errs.sort()
    achieved = errs[min(len(errs) - 1, int(_WEIGHTED_QUANTILE * len(errs)))]
    if achieved > _WEIGHTED_GATE:
        return None
    return m["fee"], ratios


def _load_balancer_pools_by_hour(
        stamp: str, hours: tuple[int, ...]) -> dict[int, dict[frozenset[str], list[Pool]]]:
    """Screened Balancer weighted pools for one day, resolved to each requested hour.

    An n-token weighted pool serves every pair among its tokens, so one pool registers under each
    unordered pair it can bridge, the way `_load_curve_pools` does for Curve.
    """
    by_hour: dict[int, dict[frozenset[str], list[Pool]]] = {
        h: defaultdict(list) for h in hours}
    meta = _bal_pool_meta(stamp)
    if not meta:
        return by_hour
    staged = _bal_day_events(stamp, meta)

    for pid, m in meta.items():
        rec = staged.get(pid) or []
        if not rec:
            continue
        walked = _bal_walk_day(m, rec)
        if walked is None:
            continue
        obs, hourly = walked
        if not obs:
            continue
        # The screen is scored against the state each trade faced, which is the same object the
        # validation used. Every hour of the day reuses the one verdict, so the calibration is paid
        # once per pool-day and not once per pool-hour.
        verdict = _bal_screen(m, obs)
        if verdict is None:
            continue
        fee, ratios = verdict

        n = len(m["tokens"])
        for h in hours:
            balances = hourly[h]
            if any(b <= 0 for b in balances):
                continue
            wp = WeightedPool(pool_id=pid, tokens=m["tokens"], balances=balances,
                              decimals=m["decimals"], weights=m["weights"], fee=fee,
                              pool_type=m["pool_type"])
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = m["tokens"][i], m["tokens"][j]
                    if not a or not b or a == b:
                        continue
                    ra, rb = m["raw_tokens"][i], m["raw_tokens"][j]
                    ratio = ratios.get((ra, rb)) if ratios else None
                    if ratios and ratio is None:
                        continue          # this pair's exponent was never identified
                    by_hour[h][frozenset((a, b))].append(Pool(
                        source="balancer", pool=pid, kind="weighted",
                        token0=a, token1=b, sym0=m["syms"][i], sym1=m["syms"][j],
                        dec0=m["decimals"][i], dec1=m["decimals"][j],
                        reserve0=0.0, reserve1=0.0, weighted=wp, weight_ratio=ratio))
    return by_hour


def _load_balancer_pools(stamp: str, hour: int,
                         hours: tuple[int, ...] | None = None
                         ) -> dict[frozenset[str], list[Pool]]:
    want = hours or (hour,)
    if _BAL_DAY["stamp"] != stamp or _BAL_DAY["hours"] != want:
        _BAL_DAY.update(stamp=stamp, hours=want,
                        pools=_load_balancer_pools_by_hour(stamp, want))
    return _BAL_DAY["pools"].get(hour, {})


def _best_quote(
    pools: dict[frozenset[str], list[Pool]],
    token_in: str,
    token_out: str,
    amount_in: float,
) -> tuple[float, str, str] | tuple[float, None, None]:
    """Best output across every pool joining the two tokens.

    A pool that matches neither the constant-product nor the tick-map branch is a
    defect rather than a pool to skip, so it is counted and reported instead of
    silently contributing nothing.
    """
    best = 0.0
    best_source = None
    best_pool = None
    for p in pools.get(frozenset((token_in, token_out)), []):
        # Support bound, applied before the quote so it can never depend on the answer.
        if p.kind == "v2":
            res_in = p.reserve0 if token_in == p.token0 else p.reserve1
            if res_in <= 0 or amount_in > MAX_INPUT_TO_RESERVE * res_in:
                continue
        if p.kind == "v2" and token_in == p.token0 and token_out == p.token1:
            out = quote_exact_input_float(amount_in, p.reserve0, p.reserve1)
        elif p.kind == "v2" and token_in == p.token1 and token_out == p.token0:
            out = quote_exact_input_float(amount_in, p.reserve1, p.reserve0)
        elif p.stable is not None:
            # Curve-style n-token pool. The StableSwap quote needs RAW integer units,
            # and the pool's own token order is preserved on the StablePool, so the
            # canonicalised endpoints are mapped back through it.
            si = p.stable.index_of(token_in if token_in != WETH_ADDR else token_in)
            if si is None:
                continue
            dec_in = p.dec0 if token_in == p.token0 else p.dec1
            dec_out = p.dec1 if token_in == p.token0 else p.dec0
            amt_atomic = int(amount_in * 10 ** dec_in)
            raw_out = _stable_quote(p.stable, token_in, token_out, amt_atomic)
            probe_atomic = max(1, amt_atomic // 10_000)
            probe_raw = _stable_quote(p.stable, token_in, token_out, probe_atomic)
            if raw_out and probe_raw:
                out = raw_out / 10 ** dec_out
                marginal = (probe_raw / 10 ** dec_out) * (amt_atomic / probe_atomic)
                if not _impact_ok(marginal, out):
                    continue
                if out > best:
                    best, best_source, best_pool = out, p.source, p.pool
            continue
        elif p.weighted is not None:
            # Balancer n-token weighted pool. The quote needs RAW integer units and the pool's own
            # token order is preserved on the WeightedPool, so the canonical endpoints index into
            # it directly. `weight_ratio` is set only when the pool's reported weights failed
            # their fit and the exponent was identified from trades, and it is stored for
            # token0 to token1, so the reverse direction takes its reciprocal.
            dec_in = p.dec0 if token_in == p.token0 else p.dec1
            dec_out = p.dec1 if token_in == p.token0 else p.dec0
            ratio = p.weight_ratio
            if ratio is not None and token_in != p.token0:
                ratio = 1 / ratio
            raw_out = _weighted_quote(p.weighted, token_in, token_out,
                                      int(amount_in * 10 ** dec_in), weight_ratio=ratio)
            if raw_out:
                out = raw_out / 10 ** dec_out
                if out > best:
                    best, best_source, best_pool = out, p.source, p.pool
            continue
        # Dispatch on whether the pool HAS a tick map rather than on a kind string.
        # Renaming the kind from "v3_exact" to "tick_exact" while this branch still
        # tested the old value made every concentrated-liquidity pool load, enter the
        # pool dict, and then be skipped without quoting or erroring. The panel came
        # out at 123.8 million rows containing no v3 or v4 at all, which looks exactly
        # like a successful build. A behavioural test cannot drift that way.
        elif p.tick_net is not None and token_in in (p.token0, p.token1) and token_out in (p.token0, p.token1):
            # Probe with a trade small enough to be effectively marginal, then require
            # the real trade's unit price to stay within the support bound of it.
            zero_for_one = token_in == p.token0
            dec_in = p.dec0 if zero_for_one else p.dec1
            dec_out = p.dec1 if zero_for_one else p.dec0
            amount_atomic = int(amount_in * (10 ** dec_in))
            if amount_atomic <= 0:
                continue
            try:
                q = quote_exact_input(
                    zero_for_one=zero_for_one,
                    amount_in=amount_atomic,
                    sqrt_price_x96=p.sqrt_price_x96,
                    liquidity=p.liquidity,
                    tick_net=p.tick_net or {},
                    tick_spacing=p.tick_spacing,
                    fee_pips=p.fee_pips,
                    sorted_ticks=p.sorted_ticks,
                    sqrt_ticks=p.sqrt_ticks,
                )
                out = q.amount_out / (10 ** dec_out)
                probe_atomic = max(1, amount_atomic // 10_000)
                pq = quote_exact_input(
                    zero_for_one=zero_for_one,
                    amount_in=probe_atomic,
                    sqrt_price_x96=p.sqrt_price_x96,
                    liquidity=p.liquidity,
                    tick_net=p.tick_net or {},
                    tick_spacing=p.tick_spacing,
                    fee_pips=p.fee_pips,
                    sorted_ticks=p.sorted_ticks,
                    sqrt_ticks=p.sqrt_ticks,
                )
                probe_out = pq.amount_out / (10 ** dec_out)
                if probe_out <= 0:
                    continue
                marginal = probe_out * (amount_atomic / probe_atomic)
                if not _impact_ok(marginal, out):
                    continue
            except Exception:
                continue
        else:
            continue
        if out > best:
            best = out
            best_source = p.source
            best_pool = p.pool
    return best, best_source, best_pool


def _build_day(
    stamp: str,
    trade_sizes: list[float],
    top_pairs: int,
    hour: int,
    tick_state: dict[str, dict[str, V3PoolState]] | None,
    tick_ticks: dict[str, dict[str, dict[int, int]]] | None,
    all_hours: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    unified = DATA_DIR / "unified" / f"{stamp}.parquet"
    if not unified.exists():
        return pd.DataFrame()
    cols = [
        "tx_hash", "component_id", "route_class", "token_in", "token_out",
        "token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd",
        "tin_role", "tout_role",
    ]
    legs = pd.read_parquet(unified, columns=cols)
    prices = day_prices(legs)
    pairs = _routes_by_pair(legs, top_pairs=top_pairs)
    if pairs.empty:
        return pd.DataFrame()
    # Copy, because the day's v2 pools are cached and shared across the hours of
    # that day: extending the cached mapping in place would leak one hour's
    # concentrated-liquidity pools into every later hour of the same day.
    pools = defaultdict(list)
    for key, vals in _load_v2_pools(stamp, hour=hour, hours=all_hours or (hour,)).items():
        pools[key].extend(vals)
    if stamp >= CURVE_START:
        for key, vals in _load_curve_pools(stamp).items():
            pools[key].extend(vals)
    if stamp >= BALANCER_START:
        # Hour-resolved, unlike Curve, because the balance path is reconstructed and an hourly
        # reading therefore costs nothing beyond the walk that the screen already needs.
        for key, vals in _load_balancer_pools(stamp, hour=hour,
                                             hours=all_hours or (hour,)).items():
            pools[key].extend(vals)
    if tick_state and tick_ticks:
        required_pairs: set[frozenset[str]] = set()
        for r in pairs.itertuples(index=False):
            required_pairs.add(frozenset((r.src, r.tgt)))
            for veh in VEHICLE_ADDRESSES:
                if veh in (r.src, r.tgt) or veh not in prices:
                    continue
                required_pairs.add(frozenset((r.src, veh)))
                required_pairs.add(frozenset((veh, r.tgt)))
        for venue in sorted(tick_state):
            v_pools = _load_tick_pools_from_state(
                venue, tick_state[venue], tick_ticks.get(venue, {}),
                required_pairs=required_pairs)
            for key, vals in v_pools.items():
                pools[key].extend(vals)
        v3_pools = {}
        for key, vals in v3_pools.items():
            pools[key].extend(vals)
    if not pools:
        return pd.DataFrame()

    rows = []
    for r in pairs.itertuples(index=False):
        if r.src not in prices or r.tgt not in prices:
            continue
        src_price = prices[r.src][1]
        tgt_price = prices[r.tgt][1]
        if src_price <= 0 or tgt_price <= 0:
            continue
        for notional in trade_sizes:
            amount_src = notional / src_price
            direct_out, direct_source, direct_pool = _best_quote(pools, r.src, r.tgt, amount_src)
            direct_usd = direct_out * tgt_price if direct_out > 0 else 0.0
            for veh in VEHICLE_ADDRESSES:
                if veh in (r.src, r.tgt) or veh not in prices:
                    continue
                mid_out, hop1_source, hop1_pool = _best_quote(pools, r.src, veh, amount_src)
                veh_usd = 0.0
                hop2_source = hop2_pool = None
                if mid_out > 0:
                    final_out, hop2_source, hop2_pool = _best_quote(pools, veh, r.tgt, mid_out)
                    veh_usd = final_out * tgt_price if final_out > 0 else 0.0
                direct_cost_advantage = (
                    (direct_usd - veh_usd) / direct_usd
                    if direct_usd > 0 and veh_usd > 0 else math.nan
                )
                rows.append({
                    "date": date,
                    "method": "v2_cp_plus_v3_exact_tick",
                    "reserve_hour_utc": hour,
                    "src": r.src,
                    "src_sym": r.src_sym,
                    "tgt": r.tgt,
                    "tgt_sym": r.tgt_sym,
                    "vehicle": veh,
                    "vehicle_sym": VEHICLE_BY_ADDRESS[veh],
                    "trade_size_usd": notional,
                    "direct_available": bool(direct_usd > 0),
                    "vehicle_available": bool(veh_usd > 0),
                    "direct_output_usd": direct_usd,
                    "vehicle_output_usd": veh_usd,
                    "direct_cost_advantage": direct_cost_advantage,
                    "direct_source": direct_source,
                    "direct_pool": direct_pool,
                    "hop1_source": hop1_source,
                    "hop1_pool": hop1_pool,
                    "hop2_source": hop2_source,
                    "hop2_pool": hop2_pool,
                    "realized_bridge_volume_usd": float(r.realized_bridge_volume_usd),
                    "n_realized_routes": int(r.n_routes),
                })
    return pd.DataFrame(rows)


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _day_cache_path(stamp: str) -> Path:
    return DAY_CACHE / f"{stamp}.parquet"


def _canonicalize_cost_measure(panel: pd.DataFrame) -> pd.DataFrame:
    """Expose only the direct-minus-indirect fraction in persisted panels."""

    if panel.empty:
        return panel
    out = panel.copy()
    direct = pd.to_numeric(out["direct_output_usd"], errors="coerce")
    indirect = pd.to_numeric(out["vehicle_output_usd"], errors="coerce")
    common_support = direct.gt(0) & indirect.gt(0)
    out["direct_cost_advantage"] = np.where(
        common_support,
        (direct - indirect) / direct,
        np.nan,
    )
    return out.drop(columns=["vehicle_route_advantage"], errors="ignore")


def _migrate_day_cache() -> int:
    paths = sorted(DAY_CACHE.glob("*.parquet"))
    migrated = 0
    for i, path in enumerate(paths, 1):
        day = pd.read_parquet(path)
        if "vehicle_route_advantage" in day.columns:
            _write(_canonicalize_cost_measure(day), path)
            migrated += 1
        if i % 250 == 0 or i == len(paths):
            print(f"route-cost cache migration [{i}/{len(paths)}] {path.stem}", flush=True)
    print(f"migrated {migrated:,} route-cost day-cache files")
    return 0


def _summarize(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    x = panel.copy()
    rows = []
    for (vehicle, size), g in x.groupby(["vehicle_sym", "trade_size_usd"]):
        avail = g[g["vehicle_available"]]
        both = g[
            g["vehicle_available"]
            & g["direct_available"]
            & np.isfinite(g["direct_cost_advantage"])
        ]
        adv = (
            both["direct_cost_advantage"].clip(lower=-10, upper=10)
            if len(both)
            else pd.Series(dtype=float)
        )
        t_stat = p_value = math.nan
        if len(adv) > 2 and float(adv.std()) > 0:
            t_stat, p_value = stats.ttest_1samp(adv.to_numpy(dtype=float), 0.0)
        rows.append({
            "vehicle": vehicle,
            "trade_size_usd": size,
            "rows": int(len(g)),
            "vehicle_available_share": float(g["vehicle_available"].mean()),
            "direct_available_share": float(g["direct_available"].mean()),
            "both_available_rows": int(len(both)),
            "vehicle_beats_direct_share": float((both["direct_cost_advantage"] < 0).mean()) if len(both) else math.nan,
            "direct_cost_advantage_median": float(both["direct_cost_advantage"].median()) if len(both) else math.nan,
            "direct_cost_advantage_p25": float(both["direct_cost_advantage"].quantile(0.25)) if len(both) else math.nan,
            "direct_cost_advantage_p75": float(both["direct_cost_advantage"].quantile(0.75)) if len(both) else math.nan,
            "direct_cost_advantage_winsor_mean": float(adv.mean()) if len(adv) else math.nan,
            "t_winsor_mean": float(t_stat) if np.isfinite(t_stat) else math.nan,
            "p_winsor_mean": float(p_value) if np.isfinite(p_value) else math.nan,
            "no_direct_vehicle_available_rows": int((~g["direct_available"] & g["vehicle_available"]).sum()),
            "covered_realized_volume_usd": float(avail["realized_bridge_volume_usd"].sum()),
        })
    return pd.DataFrame(rows).sort_values(["trade_size_usd", "vehicle"])



def _price_chunk(payload: dict) -> int:
    global UNIFY_WRAPPED
    """Warm the V3 index up to this chunk of days, then price and cache them.

    The day loop looks serial because a V3 pool's active liquidity is the running
    sum of every mint and burn since inception, so a day cannot be priced before its
    predecessors have been applied. Measured, though, that accumulation is 270s over
    986 days while pricing one hour of one day is 1.36s, so the scan is 0.4% of a
    run and the quoting is all of it. Each worker can therefore replay the cheap
    prefix itself and then price a contiguous chunk in parallel: 20.6 hours of
    serial pricing becomes about 2, at a total duplicated warm-up cost of well under
    an hour of core time. Workers touch disjoint day files, so the cache needs no
    locking.
    """
    UNIFY_WRAPPED = bool(payload.get("unify_wrapped", True))
    hours = tuple(payload["hours"])
    sizes = list(payload["sizes"])
    _configure_cache(hours, payload["top_pairs"], sizes, payload["no_v3"])
    ticks: dict[str, dict[str, dict[int, int]]] = {}
    state: dict[str, dict[str, V3PoolState]] = {}
    if not payload["no_v3"]:
        for s in payload["warm"]:
            advance_tick_venues(s, ticks, state)
    built = 0
    for s in payload["stamps"]:
        cache_path = _day_cache_path(s)
        cached = cache_path.exists()
        # The index is a running sum from inception, so a cached day still has to be
        # walked or every later day quotes against stale liquidity.
        buckets: dict[str, dict[int, dict[str, list]]] = {}
        if not payload["no_v3"]:
            for venue, start in (("uniswap_v3", V3_START), ("uniswap_v4", V4_START)):
                if s >= start:
                    buckets[venue] = load_day_tick_events(venue, s)
        if cached:
            for venue, per_hour in buckets.items():
                for h in range(24):
                    apply_hour_events(venue, per_hour[h],
                                      ticks.setdefault(venue, {}),
                                      state.setdefault(venue, {}))
            continue
        parts = []
        for h in hours:
            # Advance every tick venue THROUGH this hour before pricing it, so the
            # concentrated-liquidity venues sit at the same instant as the v2 family's
            # end-of-hour reserves.
            for venue, per_hour in buckets.items():
                apply_hour_events(venue, per_hour[h],
                                  ticks.setdefault(venue, {}),
                                  state.setdefault(venue, {}))
            parts.append(_build_day(s, sizes, top_pairs=payload["top_pairs"], hour=h,
                                    tick_state=(state if buckets or state else None),
                                    tick_ticks=(ticks if buckets or ticks else None),
                                    all_hours=hours))
        # Hours not priced still have to be applied, or the next day starts stale.
        for venue, per_hour in buckets.items():
            for h in range(24):
                if h not in hours:
                    apply_hour_events(venue, per_hour[h],
                                      ticks.setdefault(venue, {}),
                                      state.setdefault(venue, {}))
        parts = [x for x in parts if not x.empty]
        day = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        _write(_canonicalize_cost_measure(day), cache_path)
        built += 1
    return built


def main() -> int:
    ap = argparse.ArgumentParser(description="Run DVC route-cost counterfactual panel.")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument(
        "--hours", default="12",
        help="UTC hours of each day to price, as a comma list or range: '12', "
             "'0,6,12,18', or 'all' for every hour. A single hour samples one state "
             "per day, which is 1/24 of the hourly reserve data actually held.")
    ap.add_argument("--top-pairs", type=int, default=200)
    ap.add_argument("--trade-sizes", default="1000,10000,100000")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--split-wrapped", action="store_true",
                    help="treat native ETH and WETH as DISTINCT assets. Default "
                         "unifies them, since wrapping is one-for-one and routers "
                         "wrap silently, so a trader spending ETH never chose WETH")
    ap.add_argument("--workers", type=int, default=10,
                    help="parallel day-chunk workers; each replays the cheap V3 "
                         "liquidity scan then prices its own contiguous chunk")
    ap.add_argument(
        "--migrate-day-cache",
        action="store_true",
        help="rewrite legacy day-cache files to the canonical direct-cost schema and exit",
    )
    ap.add_argument("--no-v3", action="store_true", help="only use V2-style constant-product pools")
    args = ap.parse_args()
    args.workers = bounded_route_workers(args.workers)

    global UNIFY_WRAPPED
    UNIFY_WRAPPED = not args.split_wrapped

    if args.migrate_day_cache:
        return _migrate_day_cache()

    out_path = OUT_DATA / "route_cost_panel_v2.parquet"
    summary_path = OUT / "route_cost_panel_v2_summary.pkl"
    if out_path.exists() and not args.force:
        panel = pd.read_parquet(out_path)
        needs_migration = "vehicle_route_advantage" in panel.columns
        panel = _canonicalize_cost_measure(panel)
        if needs_migration:
            _write(panel, out_path)
    else:
        sizes = [float(x) for x in args.trade_sizes.split(",") if x.strip()]
        hours = parse_hours(args.hours)
        if not hours:
            sys.exit("--hours resolved to nothing")
        cache_dir = _configure_cache(hours, args.top_pairs, sizes, args.no_v3)
        print(f"pricing {len(hours)} hour(s) per day: {hours}", flush=True)
        print(f"day cache: {cache_dir.relative_to(ROOT)}", flush=True)
        frames = []
        stamps = _available_stamps(args.start, args.end)
        history_stamps = [
            stamp for stamp in _available_stamps(None, None)
            if not stamps or stamp <= max(stamps)
        ]
        _validate_v4_swap_schema(history_stamps)
        v3_ticks: dict[str, dict[str, dict[int, int]]] = {}
        v3_state: dict[str, dict[str, V3PoolState]] = {}

        # WARM THE LIQUIDITY INDEX FROM V3 LAUNCH, whatever --start says.
        #
        # A V3 pool's active liquidity is the running sum of every mint and burn
        # since inception, so the index is only correct for a run that has seen all
        # of them. Previously the index started empty at --start, which meant a
        # narrow range quoted against almost no liquidity and returned quotes that
        # were wrong by orders of magnitude WITHOUT FAILING: a one-day run finished
        # in two seconds and wrote a plausible-looking panel. --start now selects
        # which days are OUTPUT, never what the index has accumulated.
        # Only the serial path needs the parent to hold the index. In the parallel
        # path each worker replays the prefix for its own chunk, so warming here
        # would be several minutes of work thrown away.
        parallel = args.workers > 1 and len(stamps) > args.workers
        if not args.no_v3 and stamps and not parallel:
            warm = [s for s in _available_stamps(None, None)
                    if V3_START <= s < min(stamps)]
            if warm:
                print(f"warming V3 liquidity index over {len(warm)} day(s) "
                      f"{warm[0]}..{warm[-1]} before the first output day",
                      flush=True)
                for j, stamp in enumerate(warm, 1):
                    advance_tick_venues(stamp, v3_ticks, v3_state)
                    if j % 200 == 0 or j == len(warm):
                        print(f"  warm [{j}/{len(warm)}] {stamp} "
                              f"({sum(len(x) for x in v3_ticks.values()):,} pools indexed)", flush=True)

        if parallel:
            all_stamps = _available_stamps(None, None)
            width = -(-len(stamps) // args.workers)          # ceil division
            chunks = [stamps[j:j + width] for j in range(0, len(stamps), width)]
            payloads = []
            for ch in chunks:
                warm = [s for s in all_stamps if V3_START <= s < min(ch)] \
                    if not args.no_v3 else []
                payloads.append({"stamps": ch, "warm": warm, "hours": list(hours),
                                 "sizes": sizes, "top_pairs": args.top_pairs,
                                 "no_v3": args.no_v3,
                                 "unify_wrapped": UNIFY_WRAPPED})
            print(f"pricing {len(stamps):,} days in {len(chunks)} chunks across "
                  f"{args.workers} workers "
                  f"({min(len(c) for c in chunks)}-{max(len(c) for c in chunks)} days each)",
                  flush=True)
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futs = {pool.submit(_price_chunk, pl): i for i, pl in enumerate(payloads)}
                for k, fut in enumerate(as_completed(futs), 1):
                    built = fut.result()
                    print(f"  chunk {futs[fut] + 1}/{len(payloads)} done "
                          f"({built} days priced) [{k}/{len(payloads)} chunks]", flush=True)
            # Assemble through the same strict, atomic owner as the recovery command.
            # This scans every shard schema before writing, refuses missing shards,
            # and never exposes a partial panel at the final path.
            import pyarrow.parquet as pq

            cache_paths = [_day_cache_path(stamp) for stamp in stamps]
            missing = [path.stem for path in cache_paths if not path.exists()]
            if missing:
                preview = ", ".join(missing[:5])
                raise RuntimeError(
                    f"cannot assemble: {len(missing):,} expected day shard(s) missing: {preview}"
                )

            def assembly_progress(index: int, total: int, rows: int) -> None:
                if index % 250 == 0 or index == total:
                    print(f"  assembling [{index}/{total}] {rows:,} rows", flush=True)

            assembled = assemble_parquet_shards(
                cache_paths,
                out_path,
                progress=assembly_progress,
            )
            n_rows = assembled.rows
            print(f"assembled {n_rows:,} rows into {out_path.name}", flush=True)

            # The summary needs only a handful of columns, so read those back with
            # projection rather than holding the whole panel.
            # Must cover every column _summarize touches. Omitting one turns a
            # completed 763 MB panel into a KeyError after all the work is done.
            summary_cols = ["date", "method", "src", "src_sym", "tgt", "tgt_sym",
                            "vehicle", "vehicle_sym", "trade_size_usd",
                            "direct_available", "vehicle_available",
                            "direct_output_usd", "vehicle_output_usd",
                            "direct_cost_advantage", "direct_source", "hop1_source",
                            "realized_bridge_volume_usd", "n_realized_routes"]
            have = set(pq.ParquetFile(out_path).schema.names) if n_rows else set()
            panel = (pq.read_table(out_path,
                                   columns=[c for c in summary_cols if c in have])
                     .to_pandas() if n_rows else pd.DataFrame())
            summary = _summarize(panel)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary.to_pickle(summary_path)
            record_provenance(out_path, code_sources=PANEL_SOURCES, inputs=QUOTE_INPUTS,
                              rows=n_rows,
                              notes=f"quote engine {QUOTE_ENGINE}; "
                                    f"day cache {DAY_CACHE.name}; {len(hours)} hour(s)/day")
            record_provenance(summary_path, code_sources=QUOTE_SOURCES, inputs=QUOTE_INPUTS,
                              rows=len(summary))
            print(f"wrote {len(panel):,} rows -> {out_path}")
            print(f"wrote summary -> {summary_path}")
            return 0

        for i, stamp in enumerate(stamps, 1):
            day_v3_state = None
            day_v3_ticks = None
            if not args.no_v3 and stamp >= V3_START:
                advance_tick_venues(stamp, v3_ticks, v3_state)
                day_v3_state = v3_state
                day_v3_ticks = v3_ticks
            cache_path = _day_cache_path(stamp)
            if cache_path.exists():
                day = pd.read_parquet(cache_path)
                needs_migration = "vehicle_route_advantage" in day.columns
                day = _canonicalize_cost_measure(day)
                if needs_migration:
                    _write(day, cache_path)
            else:
                parts = [
                    _build_day(
                        stamp,
                        sizes,
                        top_pairs=args.top_pairs,
                        hour=h,
                        all_hours=hours,
                        tick_state=day_v3_state,
                        tick_ticks=day_v3_ticks,
                    )
                    for h in hours
                ]
                parts = [x for x in parts if not x.empty]
                day = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
                day = _canonicalize_cost_measure(day)
                _write(day, cache_path)
            if not day.empty:
                frames.append(day)
            if i % 25 == 0 or i == len(stamps):
                print(f"route-cost panel [{i}/{len(stamps)}] {stamp}", flush=True)
        panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        _write(panel, out_path)
    summary = _summarize(panel)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_pickle(summary_path)
    record_provenance(out_path, code_sources=PANEL_SOURCES, inputs=QUOTE_INPUTS,
                      rows=len(panel),
                      notes=f"quote engine {QUOTE_ENGINE}; day cache {DAY_CACHE.name}")
    record_provenance(summary_path, code_sources=QUOTE_SOURCES, inputs=QUOTE_INPUTS,
                      rows=len(summary))
    print(f"wrote {len(panel):,} rows -> {out_path}")
    print(f"wrote summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
