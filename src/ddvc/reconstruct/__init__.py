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

import gzip
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.fetch.raw import raw_path
from ddvc.fetch.dune import dune_path
import datetime as _dt

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def unified_path(stamp: str) -> Path:
    """data/unified/YYYYMMDD.parquet"""
    return DATA_DIR / "unified" / f"{stamp}.parquet"


# ---------------------------------------------------------------------------
# DEX source registry — family determines which normaliser to use
# ---------------------------------------------------------------------------

# DEX -> normaliser family. Sources sharing a raw schema share a family.
DEX_FAMILY: dict[str, str] = {
    "uniswap_v3": "uni_signed",
    "uniswap_v4": "uni_signed",
    "uniswap_v2": "uni_v2",
    "sushiswap_v2": "uni_v2",
    "curve": "messari",
    "sushiswap_v3": "messari",
    "balancer": "balancer",
    "fluid": "fluid",
}

# The 'swaps' stream name for each DEX (raw_path key)
DEX_STREAM: dict[str, str] = {
    "uniswap_v3": "swaps",
    "uniswap_v4": "swaps",
    "uniswap_v2": "swaps",
    "sushiswap_v2": "swaps",
    "curve": "swaps",
    "sushiswap_v3": "swaps",
    "balancer": "swaps",
    "fluid": "swaps",  # dune backend uses dune_path
}

# fluid uses the dune backend
DUNE_SOURCES = {"fluid"}

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
    txn = rec.get("transaction") or {}
    return {
        "tx": txn.get("id"), "log": _i(rec.get("logIndex")),
        "block": _i(txn.get("blockNumber")), "ts": _i(rec.get("timestamp") or txn.get("timestamp")),
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
    txn = rec.get("transaction") or {}
    return {
        "tx": txn.get("id"), "log": _i(rec.get("logIndex")),
        "block": _i(txn.get("blockNumber")), "ts": _i(rec.get("timestamp") or txn.get("timestamp")),
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
        "in_amt": 0.0, "out_amt": 0.0, "trusted": True,
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

def _raw_file_path(dex: str, stamp: str) -> Path:
    """Resolve raw file path for a given DEX and YYYYMMDD stamp."""
    day = _dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    stream = DEX_STREAM[dex]
    if dex in DUNE_SOURCES:
        return dune_path(dex, stream, day)
    return raw_path(dex, stream, day)


def load_legs(dex: str, day: str) -> list[dict]:
    """Normalised legs for one DEX on one day; [] if no raw file that day."""
    path = _raw_file_path(dex, day.replace("-", ""))
    if not path.exists():
        return []
    fn = NORMALISERS[DEX_FAMILY[dex]]
    legs: list[dict] = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            leg = fn(rec)
            if not (leg and leg["tx"] and leg["tin"] and leg["tout"]
                    and leg["tin_id"] and leg["tout_id"]):
                continue
            # lowercase join keys so tx grouping + token matching are case-safe
            leg["tx"] = leg["tx"].lower()
            leg["tin_id"] = leg["tin_id"].lower()
            leg["tout_id"] = leg["tout_id"].lower()
            leg["dex"] = dex
            legs.append(leg)
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


def reconstruct_day(day: str, dexes: list[str]) -> pd.DataFrame:
    """All legs for the day, tagged with route metadata. Empty df if no data."""
    all_legs: list[dict] = []
    for dex in dexes:
        all_legs.extend(load_legs(dex, day))

    # Reprice off token amounts against a stablecoin-anchored day price table,
    # discarding the subgraph's corruptible amountUSD, BEFORE route reconstruction
    # (every downstream USD — net flows, roles, volume metrics — reads leg["usd"]).
    all_legs, _dropped, _dropped_usd = _reprice_legs(all_legs)

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
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Available days discovery
# ---------------------------------------------------------------------------

def _available_days(dexes: list[str]) -> list[str]:
    """Union of UTC days (YYYY-MM-DD) for which any DEX has a raw swaps file."""
    days: set[str] = set()
    for dex in dexes:
        if dex in DUNE_SOURCES:
            d = DATA_DIR / "raw" / "dune" / dex
        else:
            d = DATA_DIR / "raw" / "thegraph" / dex
        if not d.is_dir():
            continue
        stream = DEX_STREAM[dex]
        for f in d.glob(f"{dex}_{stream}_*.jsonl.gz"):
            # Handle symlinks to empty files gracefully
            stem = f.name
            # extract stamp: last underscore-separated token before .jsonl.gz
            parts = stem.replace(".jsonl.gz", "").split("_")
            stamp = parts[-1]
            if len(stamp) == 8 and stamp.isdigit():
                days.add(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
    return sorted(days)


# ---------------------------------------------------------------------------
# Per-day processing and batch run
# ---------------------------------------------------------------------------

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _process_one(day: str, dexes: list[str], skip_existing: bool) -> tuple[str, int]:
    stamp = day.replace("-", "")
    out = unified_path(stamp)
    if skip_existing and out.exists():
        return day, -1
    df = reconstruct_day(day, dexes)
    if df.empty:
        return day, 0
    _write_parquet(df, out)
    return day, len(df)


def run(
    start: str | None = None,
    end: str | None = None,
    day: str | None = None,
    dexes: list[str] | None = None,
    concurrency: int = 8,
    skip_existing: bool = True,
) -> None:
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
        return

    print(
        f"reconstructing {len(days)} day(s) [{days[0]} .. {days[-1]}] "
        f"across {len(dexes)} DEXes, concurrency={concurrency}",
        flush=True,
    )

    done = skipped = empty = 0
    total_rows = 0
    with ProcessPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_process_one, d, dexes, skip_existing): d for d in days}
        for i, fut in enumerate(as_completed(futs), 1):
            d, n = fut.result()
            if n == -1:
                skipped += 1
            elif n == 0:
                empty += 1
            else:
                done += 1
                total_rows += n
            if i % 50 == 0 or i == len(days):
                print(
                    f"  [{i}/{len(days)}] written={done} skipped={skipped} "
                    f"empty={empty} rows={total_rows:,}",
                    flush=True,
                )

    print(
        f"done: {done} written, {skipped} skipped, {empty} empty; "
        f"{total_rows:,} total legs -> {DATA_DIR / 'unified'}",
        flush=True,
    )
