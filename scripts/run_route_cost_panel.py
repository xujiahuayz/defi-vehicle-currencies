#!/usr/bin/env python3
"""Build a first DVC-native route-cost panel for Proposition 1.

This ports the counterfactual idea from DDC into the DVC raw layout. It combines
V2-style constant-product pools from Uniswap V2/SushiSwap V2 hourly reserves
with admitted V3/V4 concentrated-liquidity quotes reconstructed from ordered
swaps plus liquidity changes. Realised routes retain the full venue perimeter;
counterfactual quotes fail closed to protocol families whose exact historical
state, invariant, and independent validation are separately registered.
For each day, endpoint pair, vehicle candidate, and trade-size bucket, it
compares the best direct route against the best two-hop vehicle route available
in the same daily state.

The V3 layer maintains an incremental tick-net index from raw mints/burns and
uses the latest observed pool sqrtPrice/tick from raw swaps, so V3 quotes cross
initialized ticks offline without an RPC call.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import WETH, canonical_token
from ddvc.data_release import require_node_d_release
from ddvc.liquidity import require_quantity_support
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, ROUTE_COST_JOB_LOCK
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.prices import day_prices
from ddvc.provenance import cache_key
from ddvc.provenance import dependency_fingerprint
from ddvc.provenance import stamp as record_provenance
from ddvc.provenance import verify as verify_provenance
from ddvc.route_cache import (
    day_cache_is_current,
    manifest_path,
    write_day_cache,
    write_ordered_shard_manifest,
)
from ddvc.route_state import (
    OrderedTickStateCursor,
    TickStateCut,
    day_state_quality_fingerprints,
    load_cp_quote_states_by_hour,
    load_tick_quote_events,
    released_state_lineage_inputs,
)
from ddvc.state_data import STATE_ROOT
from ddvc.route_cost import (
    MAIN_ROUTE_COST_SPEC,
    MAX_INPUT_TO_RESERVE,
    MAX_PRICE_IMPACT,
    QUOTE_CELL_KEYS,
)
from ddvc.pricing.v2quote import quote_exact_input_float
from ddvc.pricing.tick_quote import quote_tick_state
from ddvc.pricing.v3quote import get_sqrt_ratio_at_tick
from ddvc.pricing.tick_state import (
    TickPoolState,
    active_liquidity,
)
from ddvc.pricing.tick_replay import TickReplayState
from ddvc.pricing.v3pools import load_token_decimals
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.route_cost_summary import write_route_cost_summary
from ddvc.work_partition import weighted_contiguous_chunks

ROOT = REPO_ROOT

TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"


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
QUOTE_FAMILY_PERIMETER = (
    ("uniswap_v2", "full_range_constant_product"),
    ("sushiswap_v2", "full_range_constant_product"),
    ("uniswap_v3", "concentrated_liquidity"),
    ("uniswap_v4", "vanilla_concentrated"),
)

# The support rule and quote-cell identity are owned by ``ddvc.route_cost`` so the
# builder, diagnostics, assembler, and cache fingerprint cannot drift independently.
DEFAULT_ROUTE_WORKERS = 4
MAX_ROUTE_WORKERS = 6
def bounded_route_workers(requested: int) -> int:
    return min(MAX_ROUTE_WORKERS, max(1, requested))


def apply_main_build_spec(args: argparse.Namespace) -> str:
    """Resolve the canonical release scope without relying on CLI defaults."""

    if not args.main_spec:
        args.hours = args.hours or "12"
        args.top_pairs = args.top_pairs if args.top_pairs is not None else 200
        args.trade_sizes = args.trade_sizes or "1000,10000,100000"
        return "custom"
    conflicts = {
        "start": args.start,
        "end": args.end,
        "hours": args.hours,
        "top_pairs": args.top_pairs,
        "trade_sizes": args.trade_sizes,
        "split_wrapped": args.split_wrapped or None,
        "no_v3": args.no_v3 or None,
    }
    supplied = sorted(name for name, value in conflicts.items() if value is not None)
    if supplied:
        raise ValueError(
            "--main-spec cannot be combined with scientific scope overrides: "
            + ", ".join(supplied)
        )
    args.start = None
    args.end = None
    args.hours = ",".join(str(hour) for hour in MAIN_ROUTE_COST_SPEC.hours_utc)
    args.top_pairs = MAIN_ROUTE_COST_SPEC.top_pairs
    args.trade_sizes = ",".join(
        str(int(value)) for value in MAIN_ROUTE_COST_SPEC.trade_sizes_usd
    )
    args.split_wrapped = not MAIN_ROUTE_COST_SPEC.unify_wrapped
    args.no_v3 = not MAIN_ROUTE_COST_SPEC.include_tick_venues
    return MAIN_ROUTE_COST_SPEC.scope


def require_quote_family_perimeter(*, include_tick: bool = True) -> None:
    """Bind this generation to independently admitted family/quantity contracts."""

    perimeter = QUOTE_FAMILY_PERIMETER if include_tick else QUOTE_FAMILY_PERIMETER[:2]
    for venue, family in perimeter:
        for quantity in ("quote_quality", "executable_band_depth"):
            require_quantity_support(
                venue,
                quantity,
                family,
                use="quote_quality",
            )


def estimated_day_input_bytes(stamp: str) -> int:
    """Compressed input bytes used to balance expensive contiguous day chunks."""
    paths = [DATA_DIR / "unified" / f"{stamp}.parquet"]
    paths.extend(
        STATE_ROOT / family / venue / f"{stamp}.parquet"
        for family, venue in (
            ("constant_product", "uniswap_v2"),
            ("constant_product", "sushiswap_v2"),
            ("tick", "uniswap_v3"),
            ("tick", "uniswap_v4"),
        )
    )
    return max(1, sum(path.stat().st_size for path in paths if path.exists()))
OUT_DATA = DATA_DIR / "empirical"
OUT = OUTPUT_DIR / "empirical"


# Cache generation = fingerprint of every source that can change a quote. Keyed in
# the PATH so a stale generation cannot be read at all, rather than being readable
# and merely mislabelled, which is how the hand-managed `v3_exact_tick` label let
# 2,242 days of quotes from a broken quoter survive two correctness fixes.
QUOTE_SOURCES = [
    "src/ddvc/route_cost.py",
    "src/ddvc/prices.py",
    "src/ddvc/pricing/v3quote.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/pricing/tick_quote.py",
    "src/ddvc/pricing/tick_state.py",
    "src/ddvc/pricing/v2quote.py",
    "src/ddvc/liquidity.py",
    "src/ddvc/state_data.py",
    "src/ddvc/graph_event_order.py",
    "src/ddvc/route_state.py",
    "src/ddvc/route_cache.py",
    "src/ddvc/pricing/tick_replay.py",
    "scripts/run_route_cost_panel.py",
]
QUOTE_INPUTS = [
    DATA_DIR / "unified",
    TOKEN_DECIMALS,
    *released_state_lineage_inputs(),
]


def quote_cache_generation(*, inputs: list[Path] | None = None) -> str:
    """Fingerprint quote code, released state, corrections, and certificates."""

    return cache_key(QUOTE_SOURCES, inputs=QUOTE_INPUTS if inputs is None else inputs)


def quote_dependency_identity(*, inputs: list[Path] | None = None) -> str:
    """Full lineage identity stored in every marker-last day-cache bundle."""

    return dependency_fingerprint(
        QUOTE_SOURCES,
        QUOTE_INPUTS if inputs is None else inputs,
    )


def require_quote_lineage(expected: str) -> None:
    """Fail closed if a released-state ancestor changed during a long build."""

    observed = quote_dependency_identity()
    if observed != expected:
        raise RuntimeError(
            f"released quote-state lineage changed during build: {expected} -> {observed}"
        )


QUOTE_DEPENDENCY_IDENTITY = quote_dependency_identity()
QUOTE_ENGINE = QUOTE_DEPENDENCY_IDENTITY[:12]
PANEL_SOURCES = [*QUOTE_SOURCES, "src/ddvc/panel_assembly.py"]
SUMMARY_SOURCES = [*QUOTE_SOURCES, "src/ddvc/route_cost_summary.py"]

# Cached day content also depends on the arguments that decide WHAT is computed,
# not only on the code that computes it. The cache ignored them, so a run at
# `--hour 0` silently reused rows priced at `--hour 12`, and a wider `--top-pairs`
# reused the narrower pair set. Both belong in the key for the same reason the
# code fingerprint does.
DAY_CACHE = OUT_DATA / "_route_cost_day_cache" / f"engine_{QUOTE_ENGINE}"
DAY_CACHE_SCOPE = "unconfigured"


def assert_unique_quote_cells(frame: pd.DataFrame, *, context: str) -> None:
    """Enforce the route-cost panel's one-row-per-economic-cell contract."""
    if frame.empty:
        return
    missing = sorted(set(QUOTE_CELL_KEYS) - set(frame.columns))
    if missing:
        raise ValueError(f"{context} is missing quote-cell columns: {', '.join(missing)}")
    duplicates = frame.duplicated(list(QUOTE_CELL_KEYS), keep=False)
    if duplicates.any():
        sample = frame.loc[duplicates, list(QUOTE_CELL_KEYS)].iloc[0].to_dict()
        raise ValueError(f"{context} has duplicate quote cells: {sample}")


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
    global DAY_CACHE, DAY_CACHE_SCOPE, QUOTE_DEPENDENCY_IDENTITY, QUOTE_ENGINE, QUOTE_INPUTS
    QUOTE_INPUTS = [
        DATA_DIR / "unified",
        TOKEN_DECIMALS,
        *released_state_lineage_inputs(),
    ]
    QUOTE_DEPENDENCY_IDENTITY = quote_dependency_identity()
    QUOTE_ENGINE = QUOTE_DEPENDENCY_IDENTITY[:12]
    hspec = "all" if len(hours) == 24 else "-".join(str(h) for h in hours)
    spec = (f"h{hspec}_p{top_pairs}_s{'-'.join(str(int(x)) for x in sizes)}"
            f"{'_nov3' if no_v3 else ''}{'_splitwrapped' if not UNIFY_WRAPPED else ''}")
    DAY_CACHE_SCOPE = spec
    DAY_CACHE = OUT_DATA / "_route_cost_day_cache" / f"engine_{QUOTE_ENGINE}" / spec
    DAY_CACHE.mkdir(parents=True, exist_ok=True)
    return DAY_CACHE


def _day_cache_identity(stamp: str) -> dict[str, object]:
    return {
        "day": stamp,
        "quote_engine": QUOTE_ENGINE,
        "quote_dependency_fingerprint": QUOTE_DEPENDENCY_IDENTITY,
        "scope": DAY_CACHE_SCOPE,
        "state_quality_fingerprints": day_state_quality_fingerprints(stamp),
    }


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


V3PoolState = TickPoolState


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

    symbol_rows = roles[["token", "symbol"]].copy()
    symbol_rows["symbol"] = symbol_rows["symbol"].fillna("").astype(str).str.strip()
    symbol_rows = symbol_rows[symbol_rows["symbol"].astype(bool)].drop_duplicates()
    symbol_rows["preferred"] = (
        symbol_rows["token"].eq(WETH)
        & symbol_rows["symbol"].str.upper().eq("WETH")
    )
    symbol_rows = symbol_rows.sort_values(
        ["token", "preferred", "symbol"],
        ascending=[True, False, True],
        kind="stable",
    ).drop_duplicates("token")
    symbols = dict(zip(symbol_rows["token"], symbol_rows["symbol"], strict=True))

    def unique_endpoint(role: str, name: str) -> pd.DataFrame:
        endpoint = roles.loc[
            roles["role"].eq(role), ["component_key", "token"]
        ].drop_duplicates()
        counts = endpoint.groupby("component_key")["token"].transform("nunique")
        return endpoint.loc[counts.eq(1)].rename(columns={"token": name})

    sources = unique_endpoint("source", "src")
    sinks = unique_endpoint("sink", "tgt")
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
        out.groupby(["src", "tgt"], as_index=False)
        .agg(realized_bridge_volume_usd=("volume", "sum"), n_routes=("volume", "size"))
        .sort_values("realized_bridge_volume_usd", ascending=False)
        .head(top_pairs)
    )
    out.insert(1, "src_sym", out["src"].map(symbols).fillna(""))
    out.insert(3, "tgt_sym", out["tgt"].map(symbols).fillna(""))
    return out


def _load_v2_pools_by_hour(stamp: str,
                           hours: tuple[int, ...]) -> dict[int, dict[frozenset[str], list[Pool]]]:
    """Load released canonical end-of-hour reserves in one bounded day pass."""
    by_hour: dict[int, dict[frozenset[str], list[Pool]]] = {
        h: defaultdict(list) for h in hours}
    for source in V2_SOURCES:
        require_quantity_support(source, "quote_quality", "full_range_constant_product", use="quote_quality")
        require_quantity_support(source, "executable_band_depth", "full_range_constant_product", use="quote_quality")
    for hour, states in load_cp_quote_states_by_hour(stamp, hours).items():
        pools = by_hour[hour]
        for state in states:
            a0 = canonical_token(state.token0, unify_wrapped=UNIFY_WRAPPED)
            a1 = canonical_token(state.token1, unify_wrapped=UNIFY_WRAPPED)
            if not a0 or not a1 or state.reserve0 <= 0 or state.reserve1 <= 0:
                continue
            pools[frozenset((a0, a1))].append(Pool(
                source=state.venue,
                pool=state.pool,
                kind="v2",
                token0=a0,
                token1=a1,
                sym0=state.symbol0,
                sym1=state.symbol1,
                dec0=state.decimals0,
                dec1=state.decimals1,
                reserve0=state.reserve0,
                reserve1=state.reserve1,
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


V4_START = "20250101"

# Whether native ETH (Uniswap v4's zero address) and WETH are ONE currency or two.
# Set from --split-wrapped and included in the cache key, because it changes which
# routes exist rather than merely how they are labelled. See
# ddvc.asset_types.canonical_token for why the unified reading is primary.
UNIFY_WRAPPED = True


def new_tick_replay() -> TickReplayState:
    """Create one bounded canonical replay with the released decimal registry."""

    return TickReplayState(
        unify_wrapped=UNIFY_WRAPPED,
        token_decimals=load_token_decimals(TOKEN_DECIMALS),
    )


def advance_tick_day_hours(
    stamp: str,
    replay: TickReplayState,
    requested_hours: tuple[int, ...],
):
    """Preserve block-log order while yielding exact end-of-UTC-hour cuts."""

    venues = tuple(
        venue
        for venue, start in (("uniswap_v3", V3_START), ("uniswap_v4", V4_START))
        if stamp >= start
    )
    events = load_tick_quote_events(stamp, venues=venues)
    cursor = OrderedTickStateCursor(events)
    day_start = int(
        pd.Timestamp(
            f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]} 00:00:00", tz="UTC"
        ).timestamp()
    )
    requested = set(requested_hours)
    for hour in range(24):
        cursor.apply_until(replay, TickStateCut.hour_end(day_start + (hour + 1) * 3600))
        if hour in requested:
            yield hour
    cursor.require_consumed()


def advance_tick_venues(
    stamp: str,
    replay: TickReplayState,
) -> None:
    """Apply one day of liquidity events and price updates for every tick venue.

    Kept as one function so a caller cannot advance v3 and forget v4: the index is
    a running sum from inception, and a venue silently left un-advanced would quote
    against stale liquidity without failing.
    """
    for _hour in advance_tick_day_hours(stamp, replay, ()):
        pass


def _load_tick_pools_from_state(
    venue: str,
    state_by_pool: dict[str, V3PoolState],
    tick_net_by_pool: dict[str, dict[int, int]],
    required_pairs: set[frozenset[str]] | None = None,
) -> dict[frozenset[str], list[Pool]]:
    family = (
        "vanilla_concentrated"
        if venue == "uniswap_v4"
        else "concentrated_liquidity"
    )
    require_quantity_support(venue, "quote_quality", family, use="quote_quality")
    require_quantity_support(
        venue,
        "executable_band_depth",
        family,
        use="quote_quality",
    )
    pools: dict[frozenset[str], list[Pool]] = defaultdict(list)
    for pool_id, st in state_by_pool.items():
        key = frozenset((st.token0, st.token1))
        if required_pairs is not None and key not in required_pairs:
            continue
        ticks = tick_net_by_pool.get(pool_id)
        if not ticks:
            continue
        liq = active_liquidity(ticks, st.tick)
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
        # Dispatch on whether the pool HAS a tick map rather than on a kind string.
        # Renaming the kind from "v3_exact" to "tick_exact" while this branch still
        # tested the old value made every concentrated-liquidity pool load, enter the
        # pool dict, and then be skipped without quoting or erroring. The panel came
        # out at 123.8 million rows containing no v3 or v4 at all, which looks exactly
        # like a successful build. A behavioural test cannot drift that way.
        elif p.tick_net is not None and token_in in (p.token0, p.token1) and token_out in (p.token0, p.token1):
            try:
                quote = quote_tick_state(
                    p,
                    p.tick_net,
                    token_in,
                    token_out,
                    amount_in,
                    max_price_impact=MAX_PRICE_IMPACT,
                )
                if quote is None:
                    continue
                out = quote.amount_out
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
    out = pd.DataFrame(rows)
    assert_unique_quote_cells(out, context=f"route-cost day {stamp} hour {hour}")
    return out


def _write(df: pd.DataFrame, path: Path) -> None:
    with atomic_output(path) as temporary:
        df.to_parquet(temporary, index=False)


def _day_cache_path(stamp: str) -> Path:
    return DAY_CACHE / f"{stamp}.parquet"


def _missing_day_cache(stamps: list[str]) -> list[Path]:
    """Return shards without a current marker-last lineage bundle."""

    return [
        path
        for stamp in stamps
        if not day_cache_is_current(
            path := _day_cache_path(stamp),
            identity=_day_cache_identity(stamp),
        )
    ]


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
    replay = new_tick_replay() if not payload["no_v3"] else None
    if not payload["no_v3"]:
        for s in payload["warm"]:
            advance_tick_venues(s, replay)
    built = 0
    for s in payload["stamps"]:
        cache_path = _day_cache_path(s)
        cached = day_cache_is_current(
            cache_path,
            identity=_day_cache_identity(s),
        )
        # The index is a running sum from inception, so a cached day still has to be
        # walked or every later day quotes against stale liquidity.
        if cached:
            if replay is not None:
                advance_tick_venues(s, replay)
            continue
        parts = []
        cuts = (
            advance_tick_day_hours(s, replay, hours)
            if replay is not None
            else iter(hours)
        )
        for h in cuts:
            parts.append(_build_day(s, sizes, top_pairs=payload["top_pairs"], hour=h,
                                    tick_state=(replay.states_by_venue if replay is not None else None),
                                    tick_ticks=(replay.ticks_by_venue if replay is not None else None),
                                    all_hours=hours))
        parts = [x for x in parts if not x.empty]
        day = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        write_day_cache(
            _canonicalize_cost_measure(day),
            cache_path,
            identity=_day_cache_identity(s),
        )
        built += 1
    return built


def main() -> int:
    ap = argparse.ArgumentParser(description="Run DVC route-cost counterfactual panel.")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument(
        "--hours", default=None,
        help="UTC hours of each day to price, as a comma list or range: '12', "
             "'0,6,12,18', or 'all' for every hour. A single hour samples one state "
             "per day, which is 1/24 of the hourly reserve data actually held.")
    ap.add_argument("--top-pairs", type=int, default=None)
    ap.add_argument("--trade-sizes", default=None)
    ap.add_argument(
        "--main-spec",
        action="store_true",
        help="use the canonical full-sample, 24-hour release scope and reject overrides",
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--split-wrapped", action="store_true",
                    help="treat native ETH and WETH as DISTINCT assets. Default "
                         "unifies them, since wrapping is one-for-one and routers "
                         "wrap silently, so a trader spending ETH never chose WETH")
    ap.add_argument("--workers", type=int, default=DEFAULT_ROUTE_WORKERS,
                    help="parallel byte-weighted contiguous day chunks; each worker "
                         "replays the cheap V3 liquidity prefix (default 4, maximum 6)")
    ap.add_argument("--no-v3", action="store_true", help="only use V2-style constant-product pools")
    args = ap.parse_args()
    try:
        build_scope = apply_main_build_spec(args)
    except ValueError as error:
        ap.error(str(error))
    args.workers = bounded_route_workers(args.workers)
    require_quote_family_perimeter(include_tick=not args.no_v3)
    active_quote_perimeter = (
        QUOTE_FAMILY_PERIMETER
        if not args.no_v3
        else QUOTE_FAMILY_PERIMETER[:2]
    )
    quote_perimeter_label = ",".join(
        f"{venue}/{family}" for venue, family in active_quote_perimeter
    )
    require_node_d_release(routes=True, market_state=True)

    global UNIFY_WRAPPED
    UNIFY_WRAPPED = not args.split_wrapped
    print(f"resolved route-cost build scope: {build_scope}", flush=True)

    out_path = OUT_DATA / "route_cost_panel_v2.parquet"
    summary_path = OUT / "route_cost_panel_v2_summary.pkl"
    released_panel = (
        out_path.exists()
        and not args.force
        and verify_provenance(out_path).get("status") == "ok"
    )
    if out_path.exists() and not args.force and not released_panel:
        print("existing route-cost panel is stale against released state; rebuilding", flush=True)
    if released_panel:
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
        tick_replay = new_tick_replay() if not args.no_v3 else None

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
                    advance_tick_venues(stamp, tick_replay)
                    if j % 200 == 0 or j == len(warm):
                        print(f"  warm [{j}/{len(warm)}] {stamp} "
                              f"({sum(len(x) for x in tick_replay.ticks_by_venue.values()):,} pools indexed)", flush=True)

        if parallel:
            if _missing_day_cache(stamps):
                all_stamps = _available_stamps(None, None)
                work_bytes = {stamp: estimated_day_input_bytes(stamp) for stamp in stamps}
                chunks = weighted_contiguous_chunks(
                    stamps,
                    [work_bytes[stamp] for stamp in stamps],
                    args.workers,
                )
                payloads = []
                for ch in chunks:
                    warm = [s for s in all_stamps if V3_START <= s < min(ch)] \
                        if not args.no_v3 else []
                    payloads.append({"stamps": ch, "warm": warm, "hours": list(hours),
                                     "sizes": sizes, "top_pairs": args.top_pairs,
                                     "no_v3": args.no_v3,
                                     "unify_wrapped": UNIFY_WRAPPED})
                chunk_megabytes = [
                    sum(work_bytes[stamp] for stamp in chunk) / 1_000_000
                    for chunk in chunks
                ]
                print(
                    f"pricing {len(stamps):,} days in {len(chunks)} byte-weighted "
                    f"contiguous chunks across {args.workers} workers "
                    f"({min(len(c) for c in chunks)}-{max(len(c) for c in chunks)} days; "
                    f"{min(chunk_megabytes):,.0f}-{max(chunk_megabytes):,.0f} input MB)",
                    flush=True,
                )
                with ProcessPoolExecutor(max_workers=args.workers) as pool:
                    futs = {pool.submit(_price_chunk, pl): i for i, pl in enumerate(payloads)}
                    for k, fut in enumerate(as_completed(futs), 1):
                        built = fut.result()
                        print(f"  chunk {futs[fut] + 1}/{len(payloads)} done "
                              f"({built} days priced) [{k}/{len(payloads)} chunks]", flush=True)
            else:
                print(f"all {len(stamps):,} day shards cached; skipping liquidity replay",
                      flush=True)
            # Assemble through the same strict, atomic owner as the recovery command.
            # This scans every shard schema before writing, refuses missing shards,
            # and never exposes a partial panel at the final path.
            cache_paths = [_day_cache_path(stamp) for stamp in stamps]
            write_ordered_shard_manifest(
                cache_paths,
                identities=[_day_cache_identity(stamp) for stamp in stamps],
                output=manifest_path(DAY_CACHE),
            )

            def assembly_progress(index: int, total: int, rows: int) -> None:
                if index % 250 == 0 or index == total:
                    print(f"  assembling [{index}/{total}] {rows:,} rows", flush=True)

            require_quote_lineage(QUOTE_DEPENDENCY_IDENTITY)
            assembled = assemble_parquet_shards(
                cache_paths,
                out_path,
                progress=assembly_progress,
                unique_keys=QUOTE_CELL_KEYS,
            )
            n_rows = assembled.rows
            print(f"assembled {n_rows:,} rows into {out_path.name}", flush=True)

            summary = write_route_cost_summary(out_path, summary_path)
            record_provenance(out_path, code_sources=PANEL_SOURCES, inputs=QUOTE_INPUTS,
                              rows=n_rows,
                              notes=f"scope={build_scope}; quote engine {QUOTE_ENGINE}; "
                                    f"day cache {DAY_CACHE.name}; {len(hours)} hour(s)/day; "
                                    f"counterfactual quote families {quote_perimeter_label}")
            record_provenance(summary_path, code_sources=SUMMARY_SOURCES, inputs=[out_path],
                              rows=len(summary))
            print(f"wrote {n_rows:,} rows -> {out_path}")
            print(f"wrote summary -> {summary_path}")
            return 0

        for i, stamp in enumerate(stamps, 1):
            cache_path = _day_cache_path(stamp)
            identity = _day_cache_identity(stamp)
            if day_cache_is_current(cache_path, identity=identity):
                if tick_replay is not None:
                    advance_tick_venues(stamp, tick_replay)
                day = pd.read_parquet(cache_path)
                day = _canonicalize_cost_measure(day)
            else:
                parts = []
                cuts = (
                    advance_tick_day_hours(stamp, tick_replay, hours)
                    if tick_replay is not None
                    else iter(hours)
                )
                for hour in cuts:
                    parts.append(
                        _build_day(
                            stamp,
                            sizes,
                            top_pairs=args.top_pairs,
                            hour=hour,
                            all_hours=hours,
                            tick_state=(tick_replay.states_by_venue if tick_replay is not None else None),
                            tick_ticks=(tick_replay.ticks_by_venue if tick_replay is not None else None),
                        )
                    )
                parts = [x for x in parts if not x.empty]
                day = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
                day = _canonicalize_cost_measure(day)
                write_day_cache(day, cache_path, identity=identity)
            if not day.empty:
                frames.append(day)
            if i % 25 == 0 or i == len(stamps):
                print(f"route-cost panel [{i}/{len(stamps)}] {stamp}", flush=True)
        panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        assert_unique_quote_cells(panel, context="serial route-cost panel")
        write_ordered_shard_manifest(
            [_day_cache_path(stamp) for stamp in stamps],
            identities=[_day_cache_identity(stamp) for stamp in stamps],
            output=manifest_path(DAY_CACHE),
        )
        require_quote_lineage(QUOTE_DEPENDENCY_IDENTITY)
        _write(panel, out_path)
    summary = write_route_cost_summary(out_path, summary_path)
    record_provenance(out_path, code_sources=PANEL_SOURCES, inputs=QUOTE_INPUTS,
                      rows=len(panel),
                      notes=f"scope={build_scope}; quote engine {QUOTE_ENGINE}; day cache {DAY_CACHE.name}; "
                            f"counterfactual quote families {quote_perimeter_label}")
    record_provenance(summary_path, code_sources=SUMMARY_SOURCES, inputs=[out_path],
                      rows=len(summary))
    print(f"wrote {len(panel):,} rows -> {out_path}")
    print(f"wrote summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    with exclusive_job(ROUTE_COST_JOB_LOCK, job="route-cost panel build or assembly"):
        raise SystemExit(main())
