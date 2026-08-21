"""Cross-DEX route reconstruction — the canonical derived swap-events table.

Reads the local raw firehose for every DEX present on a UTC day, normalises
each swap to a directed ``tokenIn -> tokenOut`` leg, groups legs by transaction
hash, and reconstructs the route(s) inside each transaction by token
connectivity (a leg ``B->C`` joins ``A->B`` only when B feeds C — not by
shared hash alone). Each leg is written out tagged with:

  * ``component_id`` / ``n_components`` — connected components of the tx's
    token-transfer graph. One component = a coherent trade (a real multi-hop
    route OR a parallel split). >=2 components = the ambiguous case (unrelated
    trades bundled in one tx, OR one route bridged through a venue we don't
    index).
  * ``route_class`` — ``single`` | ``coherent`` | ``tricky_bridged`` |
    ``tricky_independent``. The two ``tricky_*`` classes are split by a
    value-conservation test (sink-USD of one component vs source-USD of
    another within 5%): conserving => probably one bridged route; not =>
    probably independent.
  * ``ambiguous`` — ``route_class`` is one of the ``tricky_*`` classes.
  * ``tin_role`` / ``tout_role`` — ``source`` | ``intermediate`` | ``sink``
    of the token within its component (net USD), so the vehicle-currency
    (intermediate = routing hub) signal and the realized-vs-intent split are
    recoverable without re-deriving.

Read-only on the raw store; writes one Parquet per day to ``data/unified/``.

USD repricing
~~~~~~~~~~~~~
The Uniswap V2/V3 subgraphs (and Balancer) compute each swap's ``amountUSD``
from the token's internally-derived price (``derivedETH`` × bundle price). For
tokens whose price-discovery path runs through a thin/spiked pool this can be
wrong by many orders of magnitude (e.g. a benign 0.1 TRIAS -> 3268 USDC trade
stamped amountUSD=1.28e18). Token *amounts* are always correct, so we discard
the subgraph USD and reprice each swap from its token amounts against a
stablecoin-anchored, per-day token price table built from the day's own swaps.
Sources that price each leg explicitly and reliably (Messari = Curve/Sushi,
which validated to 0.24%) are trusted as-is and only sanity-capped.
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import as_completed
from datetime import datetime, timezone
from functools import cache
import gzip
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ddvc.calendar import RESEARCH_SAMPLE_END, V1_GENESIS_START, calendar_days
from ddvc.fetch.raw import (
    RawFetchInvariantError,
    installed_source_day_paths,
    verified_source_day_rows,
)
from ddvc.fetch.sources import (
    ROUTE_DUNE_SOURCES,
    ROUTE_SOURCE_FAMILIES,
    ROUTE_SOURCE_STREAMS,
    get_source,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, RAW_MARKET_DATA_LOCK
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.source_records import block_value, timestamp_value, transaction_id
from ddvc.tables import write_exhibit, write_panel

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

ROUTE_SEMANTIC_SOURCES = [
    "src/ddvc/fetch/sources.py",
    "src/ddvc/source_records.py",
]
RECONSTRUCT_CODE_SOURCES = [
    "src/ddvc/calendar.py",
    "src/ddvc/reconstruct/__init__.py",
    *ROUTE_SEMANTIC_SOURCES,
]
RECONSTRUCTION_ENGINE = "direct-v4"
ROUTE_SAMPLE_START = V1_GENESIS_START
UNIFIED_QUALITY_COLUMNS = [
    "schema_version",
    "engine",
    "day",
    "input_bytes",
    "input_mtime_ns",
    "expected_sources",
    "missing_sources",
    "raw_rows",
    "normalised_rows",
    "usable_rows",
    "duplicate_events",
    "conflicting_events",
    "malformed_rows",
    "missing_identity",
    "missing_order",
    "unpriced_rows",
    "unpriced_provider_usd",
    "output_rows",
    "output_bytes",
    "output_mtime_ns",
    "passed",
]
UNIFIED_QUALITY_PANEL = DATA_DIR / "processed" / "unified_route_quality.parquet"
UNIFIED_QUALITY_EXHIBIT = OUTPUT_DIR / "exhibits" / "unified_route_quality.jsonl"
UNIFIED_COLUMNS = [
    "tx_hash",
    "log_index",
    "source",
    "token_in",
    "token_out",
    "token_in_sym",
    "token_out_sym",
    "amount_in",
    "amount_out",
    "amount_usd",
    "component_id",
    "n_components",
    "route_class",
    "ambiguous",
    "tin_role",
    "tout_role",
    "timestamp_utc",
]


def unified_path(stamp: str, *, root: Path | None = None) -> Path:
    """data/unified/YYYYMMDD.parquet"""
    return (root or DATA_DIR / "unified") / f"{stamp}.parquet"


def unified_quality_path(stamp: str, *, root: Path | None = None) -> Path:
    """Input-aware quality marker for one canonical route day."""
    base = root or DATA_DIR / "unified"
    return base / ".quality" / f"{stamp}.json"


# ---------------------------------------------------------------------------
# DEX source registry — family determines which normaliser to use
# ---------------------------------------------------------------------------

# DEX -> normaliser family. Sources sharing a raw schema share a family.
DEX_FAMILY = ROUTE_SOURCE_FAMILIES
DEX_STREAM = ROUTE_SOURCE_STREAMS
DUNE_SOURCES = ROUTE_DUNE_SOURCES

BRIDGE_TOL = 0.05        # value-conservation tolerance for bridged/independent split
INTERMEDIATE_TOL = 0.01  # |net token USD| below this share of component gross => pass-through

# ---------------------------------------------------------------------------
# USD repricing constants
# ---------------------------------------------------------------------------

WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
WBTC_ADDR = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
NATIVE_ETH_ADDR = "0x0000000000000000000000000000000000000000"
STABLE_ADDRS: set[str] = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
    "0x853d955acef822db058eb8505911ed77f175b99e",  # FRAX
    "0x0000000000085d4780b73119b644ae5ecd22b376",  # TUSD
    "0x8e870d67f660d95d5be530380d0ec0bd388289e1",  # USDP (Pax)
    "0x5f98805a4e8be255a32880fdec7f6728c6568ba0",  # LUSD
    "0x056fd409e1d7a124bd7017459dfea2f387b6d5cd",  # GUSD
    "0x57ab1ec28d129707052df4df418d58a2d46d5f51",  # sUSD
    "0x4fabb145d64652a948d72533023f6e7a623c7c53",  # BUSD
    "0x4c9edd5852cd905f086c759e8383e09bff1e68b3",  # USDe
    "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e",  # crvUSD
    "0x6c3ea9036406852006290770bedfcaba0e23a0e8",  # PYUSD
    "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409",  # FDUSD
    "0x865377367054516e17014ccded1e7d814edc9ce4",  # DOLA
}
# No single Ethereum DEX swap in this period legitimately clears this.
SANITY_MAX_USD = 5e8
REPRICE_ROUNDS = 4  # price-propagation passes through the day's token graph

# ---------------------------------------------------------------------------
# Type coercions
# ---------------------------------------------------------------------------

def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _i(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Normalisers — one per raw schema family
# ---------------------------------------------------------------------------

def _norm_uni_signed(rec: dict) -> dict | None:
    """Uniswap V3 / V4: signed amount0; positive => token0 flows into pool."""
    pool = rec.get("pool") or {}
    t0, t1 = pool.get("token0") or {}, pool.get("token1") or {}
    a0 = _f(rec.get("amount0"))
    if a0 == 0:
        return None
    a1 = _f(rec.get("amount1"))
    if a0 > 0:
        tin, tout, in_amt, out_amt = t0, t1, abs(a0), abs(a1)
    else:
        tin, tout, in_amt, out_amt = t1, t0, abs(a1), abs(a0)
    return {
        "tx": transaction_id(rec), "log": _i(rec.get("logIndex")),
        "block": block_value(rec) or 0, "ts": timestamp_value(rec) or 0,
        "tin": tin.get("symbol"), "tin_id": tin.get("id"),
        "tout": tout.get("symbol"), "tout_id": tout.get("id"),
        "usd": _f(rec.get("amountUSD")), "pool": pool.get("id"),
        "in_amt": in_amt, "out_amt": out_amt, "trusted": False,
    }


def _norm_uni_v2(rec: dict) -> dict | None:
    """Uniswap V2 / SushiSwap V2: amount0In / amount1In signed pairs."""
    pair = rec.get("pair") or {}
    t0, t1 = pair.get("token0") or {}, pair.get("token1") or {}
    a0in, a1in = _f(rec.get("amount0In")), _f(rec.get("amount1In"))
    a0out, a1out = _f(rec.get("amount0Out")), _f(rec.get("amount1Out"))
    if a0in > 0:
        tin, tout, in_amt, out_amt = t0, t1, a0in, a1out
    elif a1in > 0:
        tin, tout, in_amt, out_amt = t1, t0, a1in, a0out
    else:
        return None
    return {
        "tx": transaction_id(rec), "log": _i(rec.get("logIndex")),
        "block": block_value(rec) or 0, "ts": timestamp_value(rec) or 0,
        "tin": tin.get("symbol"), "tin_id": tin.get("id"),
        "tout": tout.get("symbol"), "tout_id": tout.get("id"),
        "usd": _f(rec.get("amountUSD")), "pool": pair.get("id"),
        "in_amt": in_amt, "out_amt": out_amt, "trusted": False,
    }


def _norm_messari(rec: dict) -> dict | None:
    """Curve / SushiSwap V3: explicit tokenIn->tokenOut; min(in_usd, out_usd).

    Messari gives an explicit USD for BOTH legs. A clean swap's two sides agree
    to within fees/slippage; corruption only ever *inflates* one side (a bad
    derived price -> huge USD), never deflates it. So the MIN of the two
    positive sides auto-selects the trustworthy side and is immune to exotic-
    stable-tail mispricing.
    """
    tin, tout = rec.get("tokenIn") or {}, rec.get("tokenOut") or {}
    in_usd, out_usd = _f(rec.get("amountInUSD")), _f(rec.get("amountOutUSD"))
    sides = [u for u in (in_usd, out_usd) if u > 0]
    usd = min(sides) if sides else 0.0
    return {
        "tx": rec.get("hash"), "log": _i(rec.get("logIndex")),
        "block": _i(rec.get("blockNumber")), "ts": _i(rec.get("timestamp")),
        "tin": tin.get("symbol"), "tin_id": tin.get("id"),
        "tout": tout.get("symbol"), "tout_id": tout.get("id"),
        "usd": usd, "pool": (rec.get("pool") or {}).get("id"),
        "in_amt": _f(rec.get("amountIn")), "out_amt": _f(rec.get("amountOut")),
        "trusted": True,
    }


def _norm_balancer(rec: dict) -> dict | None:
    """Balancer: explicit directed swaps with tokenIn/tokenOut addresses."""
    tx = rec.get("tx")
    if not tx:
        return None
    suffix = rec.get("id", "")[len(tx):]  # Balancer has no logIndex; it's the id suffix
    return {
        "tx": tx, "log": _i(suffix),
        "block": _i(rec.get("block")), "ts": _i(rec.get("timestamp")),
        "tin": rec.get("tokenInSym"), "tin_id": rec.get("tokenIn"),
        "tout": rec.get("tokenOutSym"), "tout_id": rec.get("tokenOut"),
        "usd": _f(rec.get("valueUSD")), "pool": (rec.get("poolId") or {}).get("id"),
        "in_amt": _f(rec.get("tokenAmountIn")), "out_amt": _f(rec.get("tokenAmountOut")),
        "trusted": False,  # Balancer linear-pool tokens can blow up -> reprice
    }


def _fluid_ts(s) -> int:
    if not s:
        return 0
    try:
        txt = str(s).replace(" UTC", "").split(".")[0]
        return int(datetime.strptime(txt, "%Y-%m-%d %H:%M:%S")
                   .replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0


def _norm_fluid(rec: dict) -> dict | None:
    """Fluid (Dune dex.trades): explicit token_sold / token_bought schema."""
    return {
        "tx": rec.get("tx_hash"), "log": _i(rec.get("evt_index")),
        "block": _i(rec.get("block_number")), "ts": _fluid_ts(rec.get("block_time")),
        "tin": rec.get("token_sold_symbol"), "tin_id": rec.get("token_sold_address"),
        "tout": rec.get("token_bought_symbol"), "tout_id": rec.get("token_bought_address"),
        "usd": _f(rec.get("amount_usd")), "pool": rec.get("pool"),
        "in_amt": _f(rec.get("token_sold_amount")), "out_amt": _f(rec.get("token_bought_amount")),
        "trusted": False,
    }


def _v1_event_log(event: dict, *, leg_offset: int) -> int:
    """Map V1's event sequence and side onto one collision-free leg index.

    The V1 subgraph occasionally gives the token-purchase and ETH-purchase
    events in one token-to-token transaction the same numeric prefix.  Doubling
    that prefix leaves the original sequence intact; the side offset preserves
    both directed legs instead of treating them as conflicting records.
    """

    return 2 * _i(str(event.get("id") or "").split("-", 1)[0]) + leg_offset


def _norm_uniswap_v1(
    rec: dict,
    registry: dict[str, tuple[str, str]],
) -> list[dict]:
    """Uniswap V1 exchange events as directed token/ETH legs."""

    exchange = str(rec.get("exchangeAddress") or "").lower()
    identity = registry.get(exchange)
    row_id = str(rec.get("id") or "")
    tx = row_id.split("-", 1)[0]
    if identity is None or not tx:
        return []
    token, symbol = identity
    common = {
        "tx": tx,
        "block": block_value(rec) or 0,
        "ts": timestamp_value(rec) or 0,
        "usd": 0.0,
        "pool": exchange,
        "trusted": False,
    }
    legs: list[dict] = []
    for event in rec.get("ethPurchaseEvents") or []:
        legs.append(
            {
                **common,
                "log": _v1_event_log(event, leg_offset=0),
                "tin": symbol,
                "tin_id": token,
                "tout": "ETH",
                "tout_id": NATIVE_ETH_ADDR,
                "in_amt": _f(event.get("tokenAmount")),
                "out_amt": _f(event.get("ethAmount")),
                "v1_direction": "token_to_eth",
                "v1_eth_amount": _f(event.get("ethAmount")),
            }
        )
    for event in rec.get("tokenPurchaseEvents") or []:
        legs.append(
            {
                **common,
                "log": _v1_event_log(event, leg_offset=1),
                "tin": "ETH",
                "tin_id": NATIVE_ETH_ADDR,
                "tout": symbol,
                "tout_id": token,
                "in_amt": _f(event.get("ethAmount")),
                "out_amt": _f(event.get("tokenAmount")),
                "v1_direction": "eth_to_token",
                "v1_eth_amount": _f(event.get("ethAmount")),
            }
        )
    return legs


NORMALISERS = {
    "uni_signed": _norm_uni_signed,
    "uni_v2": _norm_uni_v2,
    "messari": _norm_messari,
    "balancer": _norm_balancer,
    "fluid": _norm_fluid,
}


# ---------------------------------------------------------------------------
# Raw file loading — resolves path per source backend
# ---------------------------------------------------------------------------

def _raw_file_path(dex: str, stamp: str, *, data_root: Path | None = None) -> Path:
    """Resolve raw file path for a given DEX and YYYYMMDD stamp."""
    stream = DEX_STREAM[dex]
    data = data_root or DATA_DIR
    if dex in DUNE_SOURCES:
        return data / "raw" / "dune" / dex / f"{dex}_{stream}_{stamp}.jsonl.gz"
    return data / "raw" / "thegraph" / dex / f"{dex}_{stream}_{stamp}.jsonl.gz"


def v1_registry_paths(*, data_root: Path | None = None) -> tuple[Path, Path]:
    root = (data_root or DATA_DIR) / "raw" / "thegraph" / "uniswap_v1"
    return (
        root / "uniswap_v1_exchange_registry.jsonl.gz",
        root / "uniswap_v1_exchange_registry_meta.json",
    )


@cache
def _v1_registry(path_text: str) -> dict[str, tuple[str, str]]:
    path = Path(path_text)
    registry: dict[str, tuple[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            exchange = str(row.get("id") or "").lower()
            token = str(row.get("tokenAddress") or "").lower()
            symbol = str(row.get("tokenSymbol") or token[:10])
            if not exchange or not token or exchange in registry:
                raise ValueError("invalid or duplicate V1 exchange registry row")
            registry[exchange] = (token, symbol)
    if not registry:
        raise ValueError("V1 exchange registry is empty")
    return registry


def load_legs(
    dex: str,
    day: str,
    *,
    data_root: Path | None = None,
    counters: dict[str, int] | None = None,
) -> list[dict]:
    """Normalised legs for one DEX source-day."""
    family = DEX_FAMILY[dex]
    fn = NORMALISERS.get(family)
    registry = None
    if family == "uniswap_v1":
        registry = _v1_registry(str(v1_registry_paths(data_root=data_root)[0].resolve()))
    legs: list[dict] = []
    unknown_v1_exchanges: list[str] = []
    with verified_source_day_rows(
        dex,
        DEX_STREAM[dex],
        datetime.strptime(day, "%Y-%m-%d").date(),
        data_root=data_root or DATA_DIR,
    ) as rows:
        for rec in rows:
            if counters is not None:
                counters["raw_rows"] += 1
            if family == "uniswap_v1":
                exchange = str(rec.get("exchangeAddress") or "").lower()
                if exchange not in (registry or {}):
                    unknown_v1_exchanges.append(exchange)
                    normalised = []
                else:
                    # An empty list here is a V1 liquidity transaction with no swap
                    # event, not a missing token identity.
                    normalised = _norm_uniswap_v1(rec, registry or {})
            else:
                normalised = [fn(rec) if fn is not None else None]
            for leg in normalised:
                if not (
                    leg
                    and leg["tx"]
                    and leg["tin"]
                    and leg["tout"]
                    and leg["tin_id"]
                    and leg["tout_id"]
                    and leg["pool"]
                ):
                    if counters is not None:
                        counters["missing_identity"] += 1
                    continue
                if leg["block"] <= 0 or leg["ts"] <= 0 or leg["log"] < 0:
                    if counters is not None:
                        counters["missing_order"] += 1
                    continue
                # lowercase join keys so tx grouping + token matching are case-safe
                leg["tx"] = leg["tx"].lower()
                leg["tin_id"] = leg["tin_id"].lower()
                leg["tout_id"] = leg["tout_id"].lower()
                leg["dex"] = dex
                legs.append(leg)
                if counters is not None:
                    counters["normalised_rows"] += 1
    if unknown_v1_exchanges:
        raise ValueError(
            "Uniswap v1 exchange is absent from the exact registry: "
            f"{sorted(set(unknown_v1_exchanges))[0]}"
        )
    return legs


# ---------------------------------------------------------------------------
# USD repricing — bypass the subgraph's corruptible amountUSD
# ---------------------------------------------------------------------------

def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _day_price_table(legs: list[dict]) -> dict[str, float]:
    """Per-day robust USD price for each token, from swap token *amounts* only.

    Anchored on stablecoins (= $1). A token's price each round = the median
    over every swap where the counterparty is already priced of
    ``counterparty_price * counterparty_amount / this_amount``.  Because this
    uses amounts (always correct) and never the subgraph's amountUSD, it is
    immune to the derived-price corruption. The median guards against thin-pool
    real mispricing. Propagated a few rounds so prices reach tokens that only
    trade against WETH/WBTC, not stables directly.
    """
    price: dict[str, float] = {a: 1.0 for a in STABLE_ADDRS}
    # Keep only legs with both amounts present (repriceable, real two-sided swaps).
    pairs = [(l["tin_id"], l["in_amt"], l["tout_id"], l["out_amt"])
             for l in legs if not l["trusted"] and l["in_amt"] > 0 and l["out_amt"] > 0]
    for _ in range(REPRICE_ROUNDS):
        implied: dict[str, list[float]] = defaultdict(list)
        for a_id, a_amt, b_id, b_amt in pairs:
            if a_id in price and b_id not in STABLE_ADDRS and b_amt > 0:
                implied[b_id].append(price[a_id] * a_amt / b_amt)
            if b_id in price and a_id not in STABLE_ADDRS and a_amt > 0:
                implied[a_id].append(price[b_id] * b_amt / a_amt)
        changed = False
        for tok, vals in implied.items():
            p = _median(vals)
            if p > 0 and price.get(tok) != p:
                price[tok] = p
                changed = True
        if not changed:
            break
    return price


def _reprice_legs(legs: list[dict]) -> tuple[list[dict], int, float]:
    """Overwrite each leg's USD with an amount-derived value; drop the unanchorable.

    Repriceable legs (Uniswap V2/V3, Balancer, Fluid) take USD from the day's
    price table, preferring a stablecoin side, then WETH/WBTC, then any priced
    token. Trusted legs (Messari) keep their explicit per-leg USD. Either way,
    a leg whose final USD is unanchorable (no priced token, both 0) or still
    exceeds the sanity ceiling is dropped — that residue is junk<->junk dust
    with no numeraire path, never real volume.
    Returns (kept, n_dropped, dropped_subgraph_usd).
    """
    price = _day_price_table(legs)

    def leg_usd(l: dict) -> float | None:
        if l["trusted"]:
            return l["usd"]
        ti, to = l["tin_id"], l["tout_id"]
        ia, oa = l["in_amt"], l["out_amt"]
        # Prefer the most-trustworthy anchored side: stable > WETH/WBTC > any priced.
        for tier in (STABLE_ADDRS, {NATIVE_ETH_ADDR, WETH_ADDR, WBTC_ADDR}):
            if ti in tier and ti in price and ia > 0:
                return price[ti] * ia
            if to in tier and to in price and oa > 0:
                return price[to] * oa
        cands = []
        if ti in price and ia > 0:
            cands.append(price[ti] * ia)
        if to in price and oa > 0:
            cands.append(price[to] * oa)
        return _median(cands) if cands else None

    kept, dropped, dropped_usd = [], 0, 0.0
    for l in legs:
        u = leg_usd(l)
        if u is None or u <= 0 or u > SANITY_MAX_USD:
            dropped += 1
            dropped_usd += l["usd"]
            continue
        l["usd"] = u
        kept.append(l)
    return kept, dropped, dropped_usd


# ---------------------------------------------------------------------------
# Route reconstruction inside a transaction
# ---------------------------------------------------------------------------

def _root(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict, a: str, b: str) -> None:
    parent.setdefault(a, a)
    parent.setdefault(b, b)
    ra, rb = _root(parent, a), _root(parent, b)
    if ra != rb:
        parent[ra] = rb


def _component_profiles(comps: list[list[dict]]) -> list[dict]:
    """Per component: token net USD, source/sink totals, token roles."""
    profiles = []
    for comp in comps:
        net: dict[str, float] = defaultdict(float)
        gross = 0.0
        for leg in comp:
            net[leg["tout_id"]] += leg["usd"]
            net[leg["tin_id"]] -= leg["usd"]
            gross += leg["usd"]
        thresh = INTERMEDIATE_TOL * gross
        roles = {}
        source_total = sink_total = 0.0
        for tok, v in net.items():
            if v > thresh:
                roles[tok] = "sink"
                sink_total += v
            elif v < -thresh:
                roles[tok] = "source"
                source_total += -v
            else:
                roles[tok] = "intermediate"
        profiles.append({"roles": roles, "source": source_total, "sink": sink_total})
    return profiles


def _is_bridged(profiles: list[dict], tol: float) -> bool:
    """Does some component's sink-USD match another's source-USD within tol?"""
    for i, pi in enumerate(profiles):
        for j, pj in enumerate(profiles):
            if i == j:
                continue
            hi = max(pi["sink"], pj["source"])
            if hi > 0 and abs(pi["sink"] - pj["source"]) / hi <= tol:
                return True
    return False


def _empty_quality(day: str, active_sources: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "engine": RECONSTRUCTION_ENGINE,
        "day": day.replace("-", ""),
        "input_bytes": 0,
        "input_mtime_ns": 0,
        "expected_sources": len(active_sources),
        "missing_sources": 0,
        "raw_rows": 0,
        "normalised_rows": 0,
        "usable_rows": 0,
        "duplicate_events": 0,
        "conflicting_events": 0,
        "malformed_rows": 0,
        "missing_identity": 0,
        "missing_order": 0,
        "unpriced_rows": 0,
        "unpriced_provider_usd": 0.0,
        "output_rows": 0,
        "output_bytes": 0,
        "output_mtime_ns": 0,
        "passed": False,
    }


def active_route_sources(day: str, dexes: list[str]) -> list[str]:
    """Selected routed venues that had launched by one UTC day."""
    stamp = day.replace("-", "")
    return sorted(
        dex
        for dex in dexes
        if get_source(dex).genesis.strftime("%Y%m%d") <= stamp
    )


def route_input_paths(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> list[Path]:
    """Exact raw swap partitions required for one canonical route day."""
    stamp = day.replace("-", "")
    return [
        _raw_file_path(dex, stamp, data_root=data_root)
        for dex in active_route_sources(day, dexes)
    ]


def preflight_route_input_perimeter(
    days: list[str],
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> int:
    """Reject an incomplete raw perimeter before any route output is touched."""

    root = data_root or DATA_DIR
    missing: list[str] = []
    expected = 0
    for day in days:
        calendar_day = datetime.strptime(day, "%Y-%m-%d").date()
        for dex in active_route_sources(day, dexes):
            expected += 1
            raw, marker = installed_source_day_paths(
                dex,
                DEX_STREAM[dex],
                calendar_day,
                data_root=root,
            )
            absent = [
                label
                for label, path in (("payload", raw), ("marker", marker))
                if not path.is_file()
            ]
            if absent:
                missing.append(f"{dex}/{calendar_day:%Y%m%d}:{'+'.join(absent)}")
    if "uniswap_v1" in dexes:
        for label, path in zip(("registry", "registry-meta"), v1_registry_paths(data_root=root), strict=True):
            if not path.is_file():
                missing.append(f"uniswap_v1/static:{label}")
    if missing:
        preview = ", ".join(missing[:8])
        suffix = "" if len(missing) <= 8 else f", plus {len(missing) - 8} more"
        raise FileNotFoundError(
            f"route reconstruction raw preflight failed for {len(missing)} of {expected} "
            f"source-days before output publication: {preview}{suffix}"
        )
    return expected


def route_input_state(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> tuple[int, int, list[str]]:
    """Return direct file facts for required raw payloads and metadata."""

    root = data_root or DATA_DIR
    calendar_day = datetime.strptime(day, "%Y-%m-%d").date()
    files: list[Path] = []
    unavailable: list[str] = []
    for dex in active_route_sources(day, dexes):
        payload, marker = installed_source_day_paths(
            dex, DEX_STREAM[dex], calendar_day, data_root=root
        )
        if not payload.is_file() or not marker.is_file():
            unavailable.append(dex)
            continue
        files.extend((payload, marker))
    if "uniswap_v1" in active_route_sources(day, dexes):
        registry, metadata = v1_registry_paths(data_root=root)
        if not registry.is_file() or not metadata.is_file():
            unavailable.append("uniswap_v1_registry")
        else:
            files.extend((registry, metadata))
    stats = [path.stat() for path in files]
    return (
        sum(stat.st_size for stat in stats),
        max((stat.st_mtime_ns for stat in stats), default=0),
        unavailable,
    )


def _deduplicate_legs(
    legs: list[dict],
    counters: dict[str, object],
) -> list[dict]:
    """Keep one event per venue/transaction/log identity and reject conflicts."""
    unique: list[dict] = []
    seen: dict[tuple[str, str, int], dict] = {}
    for leg in legs:
        key = (str(leg["dex"]), str(leg["tx"]), int(leg["log"]))
        prior = seen.get(key)
        if prior is None:
            seen[key] = leg
            unique.append(leg)
            continue
        comparable = {name: value for name, value in leg.items() if name != "usd"}
        prior_comparable = {name: value for name, value in prior.items() if name != "usd"}
        if comparable == prior_comparable:
            counters["duplicate_events"] = int(counters["duplicate_events"]) + 1
        else:
            counters["conflicting_events"] = int(counters["conflicting_events"]) + 1
    return unique


def reconstruct_day_with_quality(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build one canonical route day and expose every exclusion before publication."""
    active = active_route_sources(day, dexes)
    quality = _empty_quality(day, active)
    input_bytes, input_mtime_ns, unavailable = route_input_state(
        day, dexes, data_root=data_root
    )
    quality["input_bytes"] = input_bytes
    quality["input_mtime_ns"] = input_mtime_ns
    quality["missing_sources"] = len(unavailable)
    if unavailable:
        return pd.DataFrame(), quality

    all_legs: list[dict] = []
    for dex in active:
        all_legs.extend(
            load_legs(
                dex,
                day,
                data_root=data_root,
                counters=quality,
            )
        )
    all_legs = _deduplicate_legs(all_legs, quality)

    # Reprice off token amounts against a stablecoin-anchored day price table,
    # discarding the subgraph's corruptible amountUSD, BEFORE route reconstruction
    # (every downstream USD — net flows, roles, volume metrics — reads leg["usd"]).
    all_legs, dropped, dropped_usd = _reprice_legs(all_legs)
    quality["unpriced_rows"] = dropped
    quality["unpriced_provider_usd"] = dropped_usd
    quality["usable_rows"] = len(all_legs)

    txs: dict[str, list[dict]] = defaultdict(list)
    for leg in all_legs:
        txs[leg["tx"]].append(leg)

    rows: list[dict] = []
    for tx, legs in txs.items():
        v1_legs = [leg for leg in legs if leg["dex"] == "uniswap_v1"]
        v1_bridge_valid = True
        sells: list[dict] = []
        buys: list[dict] = []
        if len(v1_legs) > 1:
            sells = [leg for leg in v1_legs if leg.get("v1_direction") == "token_to_eth"]
            buys = [leg for leg in v1_legs if leg.get("v1_direction") == "eth_to_token"]
            if len(v1_legs) != 2 or len(sells) != 1 or len(buys) != 1:
                v1_bridge_valid = False
            else:
                sold = float(sells[0].get("v1_eth_amount") or 0)
                bought = float(buys[0].get("v1_eth_amount") or 0)
                v1_bridge_valid = (
                    sold > 0
                    and bought > 0
                    and abs(sold - bought) / max(sold, bought) <= 0.01
                )

        v1_role_override: dict[str, str] = {}
        if v1_bridge_valid and len(legs) == len(v1_legs) == 2:
            # V1's nested call emits the destination exchange event before the
            # source exchange call finishes, reversing EVM log order relative to
            # economic token flow. Canonical routes are ordered by directed flow.
            ordered_logs = sorted(int(leg["log"]) for leg in v1_legs)
            sells[0]["log"], buys[0]["log"] = ordered_logs
            v1_role_override = {
                sells[0]["tin_id"]: "source",
                NATIVE_ETH_ADDR: "intermediate",
                buys[0]["tout_id"]: "sink",
            }

        legs.sort(key=lambda l: l["log"])
        n_legs = len(legs)
        if n_legs == 1:
            comps = [legs]
        else:
            parent: dict[str, str] = {}
            for leg in legs:
                _union(parent, leg["tin_id"], leg["tout_id"])
            grouped: dict[str, list[dict]] = defaultdict(list)
            for leg in legs:
                grouped[_root(parent, leg["tin_id"])].append(leg)
            comps = list(grouped.values())

        n_comp = len(comps)

        if n_legs == 1:
            route_class = "single"
        elif not v1_bridge_valid:
            route_class = "tricky_independent"
        elif n_comp == 1:
            route_class = "coherent"
        else:
            profiles = _component_profiles(comps)
            route_class = ("tricky_bridged" if _is_bridged(profiles, BRIDGE_TOL)
                           else "tricky_independent")
        ambiguous = route_class.startswith("tricky")

        for cid, comp in enumerate(comps):
            net: dict[str, float] = defaultdict(float)
            gross = 0.0
            for leg in comp:
                net[leg["tout_id"]] += leg["usd"]
                net[leg["tin_id"]] -= leg["usd"]
                gross += leg["usd"]
            thresh = INTERMEDIATE_TOL * gross

            def role(tok: str, _net=net, _thresh=thresh) -> str:
                if tok in v1_role_override:
                    return v1_role_override[tok]
                v = _net[tok]
                if v > _thresh:
                    return "sink"
                if v < -_thresh:
                    return "source"
                return "intermediate"

            for leg in comp:
                ts = leg["ts"]
                rows.append({
                    "tx_hash": tx,
                    "log_index": leg["log"],
                    "source": leg["dex"],
                    "token_in": leg["tin_id"],
                    "token_out": leg["tout_id"],
                    "token_in_sym": leg["tin"],
                    "token_out_sym": leg["tout"],
                    "amount_in": leg["in_amt"],
                    "amount_out": leg["out_amt"],
                    "amount_usd": leg["usd"],
                    "component_id": cid,
                    "n_components": n_comp,
                    "route_class": route_class,
                    "ambiguous": ambiguous,
                    "tin_role": role(leg["tin_id"]),
                    "tout_role": role(leg["tout_id"]),
                    "timestamp_utc": ts,
                })
    frame = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)
    quality["output_rows"] = len(frame)
    quality["passed"] = not any(
        int(quality[name])
        for name in ("missing_sources", "malformed_rows", "conflicting_events")
    )
    return frame, quality


def reconstruct_day(day: str, dexes: list[str]) -> pd.DataFrame:
    """All usable route legs for one day, after canonical quality checks."""
    frame, quality = reconstruct_day_with_quality(day, dexes)
    if not quality["passed"]:
        raise ValueError(
            f"canonical route input failed on {day}: "
            f"missing={quality['missing_sources']}, malformed={quality['malformed_rows']}, "
            f"conflicts={quality['conflicting_events']}"
        )
    return frame


# ---------------------------------------------------------------------------
# Available days discovery
# ---------------------------------------------------------------------------

def _available_days(dexes: list[str]) -> list[str]:
    """Independent full calendar; missing observed files stay in the denominator."""
    lower = max(
        ROUTE_SAMPLE_START,
        min(get_source(dex).genesis.strftime("%Y%m%d") for dex in dexes),
    )
    return [
        f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        for stamp in calendar_days(lower, RESEARCH_SAMPLE_END)
    ]


# ---------------------------------------------------------------------------
# Per-day processing and batch run
# ---------------------------------------------------------------------------

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    with atomic_output(path) as temporary:
        df.to_parquet(temporary, index=False)


def _write_quality_marker(
    quality: dict[str, object],
    *,
    unified_root: Path | None = None,
) -> None:
    marker = unified_quality_path(str(quality["day"]), root=unified_root)
    with atomic_output(marker) as temporary:
        temporary.write_text(json.dumps(quality, indent=1, sort_keys=True) + "\n")


def read_unified_quality(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
    unified_root: Path | None = None,
) -> dict[str, object] | None:
    """Return one current passing route-day marker, otherwise None."""
    stamp = day.replace("-", "")
    output = unified_path(stamp, root=unified_root)
    marker = unified_quality_path(stamp, root=unified_root)
    if not output.exists() or not marker.exists():
        return None
    try:
        quality = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    try:
        input_bytes, input_mtime_ns, unavailable = route_input_state(
            day, dexes, data_root=data_root
        )
    except (FileNotFoundError, OSError, ValueError):
        return None
    output_stat = output.stat()
    try:
        parquet_rows = pq.ParquetFile(output).metadata.num_rows
    except Exception:
        return None
    if (
        quality.get("engine") != RECONSTRUCTION_ENGINE
        or unavailable
        or int(quality.get("input_bytes", -1)) != input_bytes
        or int(quality.get("input_mtime_ns", -1)) != input_mtime_ns
        or output_stat.st_mtime_ns < input_mtime_ns
        or not quality.get("passed")
        or int(quality.get("output_rows", -1)) < 0
        or int(quality.get("output_rows", -1)) != parquet_rows
        or int(quality.get("output_bytes", -1)) != output_stat.st_size
        or int(quality.get("output_mtime_ns", -1)) != output_stat.st_mtime_ns
    ):
        return None
    return quality


def _process_one(
    day: str,
    dexes: list[str],
    force: bool,
    data_root: Path | None = None,
    unified_root: Path | None = None,
) -> tuple[dict[str, object], str]:
    stamp = day.replace("-", "")
    out = unified_path(stamp, root=unified_root)
    if not force:
        current = read_unified_quality(
            day,
            dexes,
            data_root=data_root,
            unified_root=unified_root,
        )
        if current is not None:
            return current, "current"
    df, quality = reconstruct_day_with_quality(day, dexes, data_root=data_root)
    if not quality["passed"]:
        _write_quality_marker(quality, unified_root=unified_root)
        return quality, "failed"
    _write_parquet(df, out)
    output_stat = out.stat()
    quality["output_bytes"] = output_stat.st_size
    quality["output_mtime_ns"] = output_stat.st_mtime_ns
    _write_quality_marker(quality, unified_root=unified_root)
    return quality, "written"


def run(
    start: str | None = None,
    end: str | None = None,
    day: str | None = None,
    dexes: list[str] | None = None,
    concurrency: int = 8,
    skip_existing: bool = True,
) -> int:
    """Reconstruct all (or a range of) days and write unified Parquet files.

    start / end are YYYY-MM-DD inclusive bounds. day overrides start/end for a
    single day. dexes defaults to all known DEX families.
    """
    dexes = dexes or list(DEX_FAMILY)
    if day:
        days = [day]
    else:
        days = _available_days(dexes)
        if start:
            days = [d for d in days if d >= start]
        if end:
            days = [d for d in days if d <= end]
    if not days:
        print("no days to process", flush=True)
        return 0

    workers = bounded_workers(concurrency, maximum=10)
    print(
        f"reconstructing {len(days)} day(s) [{days[0]} .. {days[-1]}] "
        f"across {len(dexes)} DEXes, concurrency={workers}",
        flush=True,
    )

    done = skipped = failed = 0
    total_rows = 0
    quality_rows: list[dict[str, object]] = []
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        preflight_route_input_perimeter(days, dexes)
        with interruptible_process_pool(workers) as pool:
            futures = {
                pool.submit(_process_one, day_value, dexes, not skip_existing): day_value
                for day_value in days
            }
            for index, future in enumerate(as_completed(futures), 1):
                quality, status = future.result()
                quality_rows.append(quality)
                if status == "current":
                    skipped += 1
                elif status == "failed":
                    failed += 1
                else:
                    done += 1
                    total_rows += int(quality["output_rows"])
                if index % 50 == 0 or index == len(days):
                    print(
                        f"  [{index}/{len(days)}] written={done} current={skipped} "
                        f"failed={failed} rows={total_rows:,}",
                        flush=True,
                    )

    full_run = (
        set(dexes) == set(DEX_FAMILY)
        and days[0].replace("-", "") == ROUTE_SAMPLE_START
        and days[-1].replace("-", "") == RESEARCH_SAMPLE_END
    )
    quality = pd.DataFrame(quality_rows, columns=UNIFIED_QUALITY_COLUMNS).sort_values("day")
    if full_run:
        raw_source_roots = [
            DATA_DIR / "raw" / ("dune" if dex in DUNE_SOURCES else "thegraph") / dex
            for dex in sorted(DEX_FAMILY)
        ]
        write_panel(
            quality,
            UNIFIED_QUALITY_PANEL,
            code_sources=[*RECONSTRUCT_CODE_SOURCES, "scripts/process/run_reconstruct.py"],
            inputs=[DATA_DIR / "unified" / ".quality", *raw_source_roots],
            notes="full-calendar canonical directed-route quality gate",
        )
        summary = pd.DataFrame(
            [{
                "calendar_days": len(quality),
                "expected_venue_days": int(quality["expected_sources"].sum()),
                "raw_rows": int(quality["raw_rows"].sum()),
                "normalised_rows": int(quality["normalised_rows"].sum()),
                "usable_rows": int(quality["usable_rows"].sum()),
                "output_rows": int(quality["output_rows"].sum()),
                "missing_sources": int(quality["missing_sources"].sum()),
                "duplicate_events": int(quality["duplicate_events"].sum()),
                "conflicting_events": int(quality["conflicting_events"].sum()),
                "malformed_rows": int(quality["malformed_rows"].sum()),
                "missing_identity": int(quality["missing_identity"].sum()),
                "missing_order": int(quality["missing_order"].sum()),
                "unpriced_rows": int(quality["unpriced_rows"].sum()),
                "failed_days": int((~quality["passed"]).sum()),
            }]
        )
        write_exhibit(
            summary,
            UNIFIED_QUALITY_EXHIBIT,
            code_sources=[*RECONSTRUCT_CODE_SOURCES, "scripts/process/run_reconstruct.py"],
            inputs=[UNIFIED_QUALITY_PANEL],
            notes="canonical directed-route coverage and integrity summary",
        )
        print(summary.to_string(index=False), flush=True)
    else:
        print("PARTIAL: the global route quality ledger was not published", flush=True)
    print(
        f"done: {done} written, {skipped} current, {failed} failed; "
        f"{total_rows:,} newly materialised legs",
        flush=True,
    )
    return 1 if failed else 0
