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

import hashlib
import inspect
import json
from collections import defaultdict
from concurrent.futures import as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ddvc.artifact_release import canonical_json_sha256, file_sha256, is_sha256
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
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
from ddvc.provenance import code_fingerprint
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
RECONSTRUCTION_ENGINE = "pending-import"
UNIFIED_QUALITY_COLUMNS = [
    "schema_version",
    "engine",
    "day",
    "input_fingerprint",
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
    "output_sha256",
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


def load_legs(
    dex: str,
    day: str,
    *,
    data_root: Path | None = None,
    counters: dict[str, int] | None = None,
    expected_generation_identity: str | None = None,
) -> list[dict]:
    """Normalised legs for one DEX on one certified source-day."""
    fn = NORMALISERS[DEX_FAMILY[dex]]
    legs: list[dict] = []
    with verified_source_day_rows(
        dex,
        DEX_STREAM[dex],
        datetime.strptime(day, "%Y-%m-%d").date(),
        data_root=data_root or DATA_DIR,
        expected_generation_identity=expected_generation_identity,
    ) as rows:
        for rec in rows:
            if counters is not None:
                counters["raw_rows"] += 1
            leg = fn(rec)
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
        for tier in (STABLE_ADDRS, {WETH_ADDR, WBTC_ADDR}):
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
        "input_fingerprint": "",
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
        "output_sha256": "",
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
    if missing:
        preview = ", ".join(missing[:8])
        suffix = "" if len(missing) <= 8 else f", plus {len(missing) - 8} more"
        raise FileNotFoundError(
            f"route reconstruction raw preflight failed for {len(missing)} of {expected} "
            f"source-days before output publication: {preview}{suffix}"
        )
    return expected


def _route_input_generation_records(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    from ddvc.fetch.raw import raw_partition_generation_identity

    stamp = day.replace("-", "")
    root = data_root or DATA_DIR
    records: list[dict[str, str]] = []
    unavailable: list[str] = []
    for dex in active_route_sources(day, dexes):
        try:
            identity = raw_partition_generation_identity(
                dex, DEX_STREAM[dex], stamp, data_root=root
            )
        except (FileNotFoundError, OSError, RawFetchInvariantError, ValueError):
            unavailable.append(dex)
            continue
        records.append(
            {
                "source": dex,
                "stream": DEX_STREAM[dex],
                "day": stamp,
                "generation_identity_sha256": identity,
            }
        )
    return records, unavailable


def route_input_fingerprint(
    day: str,
    dexes: list[str],
    *,
    data_root: Path | None = None,
) -> str:
    """Bind an exact route day to committed content and query generations."""

    records, unavailable = _route_input_generation_records(
        day, dexes, data_root=data_root
    )
    if unavailable:
        raise RawFetchInvariantError(
            f"route inputs lack committed generation identity: {', '.join(unavailable)}"
        )
    return canonical_json_sha256(records)


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
    inputs = route_input_paths(day, dexes, data_root=data_root)
    records, unavailable = _route_input_generation_records(
        day, dexes, data_root=data_root
    )
    quality["input_fingerprint"] = canonical_json_sha256(records)
    quality["missing_sources"] = len(unavailable)
    if unavailable:
        return pd.DataFrame(), quality

    all_legs: list[dict] = []
    generation_identities = {
        str(record["source"]): str(record["generation_identity_sha256"])
        for record in records
    }
    for dex in active:
        all_legs.extend(
            load_legs(
                dex,
                day,
                data_root=data_root,
                counters=quality,
                expected_generation_identity=generation_identities[dex],
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


ROUTE_SEMANTIC_FUNCTIONS = (
    _f,
    _i,
    _norm_uni_signed,
    _norm_uni_v2,
    _norm_messari,
    _norm_balancer,
    _fluid_ts,
    _norm_fluid,
    _raw_file_path,
    load_legs,
    _median,
    _day_price_table,
    _reprice_legs,
    _root,
    _union,
    _component_profiles,
    _is_bridged,
    _empty_quality,
    active_route_sources,
    route_input_paths,
    route_input_fingerprint,
    _deduplicate_legs,
    reconstruct_day_with_quality,
    reconstruct_day,
)


def route_semantic_fingerprint() -> str:
    """Hash row semantics without tying day caches to build orchestration."""
    digest = hashlib.sha256()
    digest.update(code_fingerprint(ROUTE_SEMANTIC_SOURCES).encode())
    constants = {
        "dex_family": DEX_FAMILY,
        "dex_stream": DEX_STREAM,
        "dune_sources": sorted(DUNE_SOURCES),
        "bridge_tolerance": BRIDGE_TOL,
        "intermediate_tolerance": INTERMEDIATE_TOL,
        "stable_addresses": sorted(STABLE_ADDRS),
        "weth": WETH_ADDR,
        "wbtc": WBTC_ADDR,
        "sanity_max_usd": SANITY_MAX_USD,
        "reprice_rounds": REPRICE_ROUNDS,
        "unified_columns": UNIFIED_COLUMNS,
        "quality_columns": UNIFIED_QUALITY_COLUMNS,
    }
    digest.update(json.dumps(constants, sort_keys=True, separators=(",", ":")).encode())
    for function in ROUTE_SEMANTIC_FUNCTIONS:
        digest.update(function.__name__.encode())
        digest.update(inspect.getsource(function).encode())
    return digest.hexdigest()


RECONSTRUCTION_ENGINE = route_semantic_fingerprint()[:12]


# ---------------------------------------------------------------------------
# Available days discovery
# ---------------------------------------------------------------------------

def _available_days(dexes: list[str]) -> list[str]:
    """Independent full calendar; missing observed files stay in the denominator."""
    lower = max(
        RESEARCH_SAMPLE_START,
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
        current = route_input_fingerprint(day, dexes, data_root=data_root)
    except (FileNotFoundError, OSError, RawFetchInvariantError, ValueError):
        return None
    output_stat = output.stat()
    if (
        quality.get("engine") != RECONSTRUCTION_ENGINE
        or quality.get("input_fingerprint") != current
        or not quality.get("passed")
        or int(quality.get("output_rows", -1)) < 0
        or int(quality.get("output_bytes", -1)) != output_stat.st_size
        or int(quality.get("output_mtime_ns", -1)) != output_stat.st_mtime_ns
        or not is_sha256(quality.get("output_sha256"))
        or quality.get("output_sha256") != file_sha256(output)
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
    quality["output_sha256"] = file_sha256(out)
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
        and days[0].replace("-", "") == RESEARCH_SAMPLE_START
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
            code_sources=[*RECONSTRUCT_CODE_SOURCES, "scripts/run_reconstruct.py"],
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
            code_sources=[*RECONSTRUCT_CODE_SOURCES, "scripts/run_reconstruct.py"],
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
