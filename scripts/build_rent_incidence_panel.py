#!/usr/bin/env python3
"""Pool-day panels of LP rent incidence: fee yield, loss-versus-rebalancing, gas.

Two venues, built the same way so their columns line up.

UNISWAP V2. `pairHourData` gives end-of-hour reserves and hourly USD volume for
every pair, which is everything the constant-product accounting needs. Fees are
30 basis points of volume. The pool's marginal price is `reserve1 / reserve0`,
so realised variance comes from the pool itself rather than an external feed.
Loss-versus-rebalancing for a constant-product pool is the closed form of
Milionis, Moallemi, Roughgarden and Zhang: the instantaneous rate is one eighth
of the variance rate times pool value, and integrating over a day gives realised
variance over eight times pool value. Realised variance is invariant to which
leg is the numeraire, because inverting a price only flips the sign of every log
return, so the dollar figure does not depend on that choice; what the choice
fixes is the interpretation, which is stated in the finding.

UNISWAP V3. There is no pool-statics table in the raw layer, so the fee tier is
recovered exactly from the CREATE2 pool address by `ddvc.pricing.v3pools`, and
active liquidity is reconstructed by accumulating every mint and burn into a
per-pool map of net liquidity deltas at initialised ticks. Active liquidity at a
given tick is then the running sum of deltas at or below it. This is exact for
the liquidity actually deployed. What is an APPROXIMATION is the return
accounting on top of it: an in-range position is treated as a constant-product
pool with the same local liquidity, which is right while the price stays inside
the range and wrong at the moment it leaves, and the day's tick is a single
volume-weighted summary of a path.

GAS. Every mint and every burn is a transaction someone paid for, so the counts
observed in the raw layer times a per-operation gas figure times the day's
median gas price times the ETH price is the pool's realised repositioning bill.
It is netted at pool level against pool-level fee revenue, which is the correct
incidence: the pool's providers as a group paid it.

Screens are applied in the analysis script, not here, so that the panel keeps
the rows a screen removes and the screen can be reported and varied.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.pricing.v3pools import derive_fee_tier  # noqa: E402
from ddvc.tables import write_panel  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph"
PROC = ROOT / "data" / "processed"

V2_FEE = 0.003

# Per-operation gas for a liquidity event. The repository's only receipt-measured
# figure is for swaps (`ddvc.cpquote.GAS_BY_LEGS`: 154,604 units for one leg,
# measured on 2024-01-15 receipts). A liquidity event moves two token balances
# plus position state instead of one balance pair, so these are set as multiples
# of that measured baseline rather than invented: a v2 mint or burn at roughly
# the cost of a one-leg swap, a v3 mint at roughly 1.6x it because the position
# manager writes an NFT and tick state, a v3 burn plus collect at roughly 1.3x.
# The analysis script re-runs every net-return conclusion across a wide band
# around these, because the level is an assumption and the sign of a net return
# must not rest on one.
GAS_UNITS = {"v2_mint": 155_000, "v2_burn": 155_000,
             "v3_mint": 250_000, "v3_burn": 200_000}


def _iter(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _rv_multiscale(hours: np.ndarray, prices: np.ndarray,
                   scale: float = 1.0) -> tuple[float, float, float, float]:
    """Realised variance at three sampling scales, plus the largest single move.

    A constant-product pool's marginal price only moves when someone trades it,
    and a round trip through the fee band moves it and moves it back, so hourly
    realised variance on the pool's own price carries a microstructure component
    that is largest exactly where the pool is thinnest. Sampling more coarsely
    shrinks that component while leaving the fundamental part alone, which is
    what makes the coarse estimates a bound on the bias rather than a taste
    difference. `scale` is 2 when the input is a square-root price.
    """
    if prices.size < 2:
        return 0.0, 0.0, 0.0, 0.0
    lp = np.log(prices) * scale
    lr = np.diff(lp)
    rv1 = float(np.sum(lr ** 2))
    bucket = hours // 4
    last = {}
    for b, v in zip(bucket, lp):
        last[b] = v
    keys = sorted(last)
    lp4 = np.array([last[k] for k in keys], dtype=float)
    rv4 = float(np.sum(np.diff(lp4) ** 2)) if lp4.size > 1 else 0.0
    rv_oc = float((lp[-1] - lp[0]) ** 2)
    return rv1, rv4, rv_oc, float(np.max(np.abs(lr)))


def _days(venue: str, stream: str) -> list[str]:
    pat = f"{venue}_{stream}_*.jsonl.gz"
    return sorted(p.name.split("_")[-1].split(".")[0]
                  for p in (RAW / venue).glob(pat))


# ---------------------------------------------------------------------------
# Uniswap v2
# ---------------------------------------------------------------------------

def _v2_day(day: str) -> list[dict]:
    hours: dict[str, list] = defaultdict(list)
    meta: dict[str, tuple] = {}
    for rec in _iter(RAW / "uniswap_v2" / f"uniswap_v2_hourly_reserves_{day}.jsonl.gz"):
        pair = rec["pair"]
        pid = pair["id"]
        if pid not in meta:
            t0, t1 = pair["token0"], pair["token1"]
            meta[pid] = (t0["id"], t1["id"], t0.get("symbol"), t1.get("symbol"))
        hours[pid].append((int(rec["hourStartUnix"]), _f(rec["reserve0"]),
                           _f(rec["reserve1"]), _f(rec["hourlyVolumeUSD"])))

    mints: dict[str, int] = defaultdict(int)
    burns: dict[str, int] = defaultdict(int)
    for rec in _iter(RAW / "uniswap_v2" / f"uniswap_v2_mints_{day}.jsonl.gz"):
        mints[rec["pair"]["id"]] += 1
    for rec in _iter(RAW / "uniswap_v2" / f"uniswap_v2_burns_{day}.jsonl.gz"):
        burns[rec["pair"]["id"]] += 1

    out = []
    for pid, rows in hours.items():
        rows.sort()
        r0 = np.array([r[1] for r in rows], dtype=float)
        r1 = np.array([r[2] for r in rows], dtype=float)
        vol = float(np.nansum([r[3] for r in rows]))
        ok = (r0 > 0) & (r1 > 0) & np.isfinite(r0) & np.isfinite(r1)
        if ok.sum() == 0:
            continue
        price = r1[ok] / r0[ok]
        hh = np.array([r[0] for r in rows], dtype=np.int64)[ok] // 3600
        rv1, rv4, rvoc, mx = _rv_multiscale(hh, price)
        t0, t1, s0, s1 = meta[pid]
        out.append({
            "day": day, "venue": "uniswap_v2", "pool": pid,
            "token0": t0, "token1": t1, "sym0": s0, "sym1": s1,
            "n_hours": int(ok.sum()), "n_ret": int(max(0, ok.sum() - 1)),
            "volume_usd": vol,
            "reserve0": float(np.nanmean(r0[ok])), "reserve1": float(np.nanmean(r1[ok])),
            "rv": rv1, "rv_4h": rv4, "rv_oc": rvoc, "max_abs_ret": mx,
            "n_mint": mints.get(pid, 0), "n_burn": burns.get(pid, 0),
            "fee_rate": V2_FEE, "liquidity": float("nan"),
        })
    return out


# ---------------------------------------------------------------------------
# Uniswap v3
# ---------------------------------------------------------------------------

def _v3_events(day: str) -> list[tuple]:
    """(pool, tickLower, tickUpper, signed liquidity delta) for one day."""
    ev = []
    for stream, sign in (("mints", 1), ("burns", -1)):
        for rec in _iter(RAW / "uniswap_v3" / f"uniswap_v3_{stream}_{day}.jsonl.gz"):
            try:
                amt = int(rec["amount"])
            except (TypeError, ValueError, KeyError):
                continue
            if amt == 0:
                continue
            ev.append((rec["pool"]["id"], int(rec["tickLower"]),
                       int(rec["tickUpper"]), sign * amt))
    return ev


def _v3_event_counts(day: str) -> dict[str, tuple[int, int]]:
    m: dict[str, int] = defaultdict(int)
    b: dict[str, int] = defaultdict(int)
    for rec in _iter(RAW / "uniswap_v3" / f"uniswap_v3_mints_{day}.jsonl.gz"):
        m[rec["pool"]["id"]] += 1
    for rec in _iter(RAW / "uniswap_v3" / f"uniswap_v3_burns_{day}.jsonl.gz"):
        b[rec["pool"]["id"]] += 1
    keys = set(m) | set(b)
    return {k: (m.get(k, 0), b.get(k, 0)) for k in keys}


def _v3_swaps_day(day: str, keep: set[str] | None) -> dict[str, dict]:
    """Per-pool swap summary for one day: volume, hourly price path, tick."""
    acc: dict[str, dict] = {}
    for rec in _iter(RAW / "uniswap_v3" / f"uniswap_v3_swaps_{day}.jsonl.gz"):
        pool = rec["pool"]
        pid = pool["id"]
        if keep is not None and pid not in keep:
            continue
        a = acc.get(pid)
        if a is None:
            t0, t1 = pool["token0"], pool["token1"]
            a = acc[pid] = {"token0": t0["id"], "token1": t1["id"],
                            "sym0": t0.get("symbol"), "sym1": t1.get("symbol"),
                            "vol": 0.0, "n": 0, "hp": {}, "ticks": [], "w": []}
        usd = _f(rec.get("amountUSD"))
        if math.isfinite(usd):
            a["vol"] += usd
        a["n"] += 1
        ts = int(rec["timestamp"])
        sp = _f(rec.get("sqrtPriceX96"))
        if math.isfinite(sp) and sp > 0:
            a["hp"][ts // 3600] = sp
        try:
            tick = int(rec["tick"])
        except (TypeError, ValueError, KeyError):
            tick = None
        if tick is not None:
            a["ticks"].append(tick)
            a["w"].append(abs(usd) if math.isfinite(usd) else 0.0)
    return acc


def _v3_pool_universe(days: list[str], top_n: int) -> set[str]:
    """Pools ranked by swap count on a stratified sample of days."""
    sample = days[:: max(1, len(days) // 60)]
    counts: dict[str, int] = defaultdict(int)
    with ProcessPoolExecutor() as ex:
        for res in ex.map(_v3_count_day, sample):
            for k, v in res.items():
                counts[k] += v
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return {k for k, _ in ranked[:top_n]}


def _v3_count_day(day: str) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for rec in _iter(RAW / "uniswap_v3" / f"uniswap_v3_swaps_{day}.jsonl.gz"):
        c[rec["pool"]["id"]] += 1
    return dict(c)


class Fenwick:
    """Prefix sums over a fixed compressed tick index, with point updates.

    Active liquidity at a tick is the sum of every net liquidity delta at or
    below it, and both the deltas and the query tick change every day, so the
    naive rebuild is a full pass over a pool's tick set per pool-day. A binary
    indexed tree makes each of those logarithmic instead. Python integers hold
    the values because `liquidity` is uint128 and overflows int64.
    """

    __slots__ = ("n", "t")

    def __init__(self, n: int) -> None:
        self.n = n
        self.t = [0] * (n + 1)

    def add(self, i: int, v: int) -> None:
        i += 1
        while i <= self.n:
            self.t[i] += v
            i += i & (-i)

    def prefix(self, i: int) -> int:
        """Sum over compressed positions 0..i inclusive."""
        i += 1
        s = 0
        while i > 0:
            s += self.t[i]
            i -= i & (-i)
        return s


def build_v2() -> pd.DataFrame:
    days = _days("uniswap_v2", "hourly_reserves")
    rows: list[dict] = []
    with ProcessPoolExecutor() as ex:
        for i, res in enumerate(ex.map(_v2_day, days, chunksize=8)):
            rows.extend(res)
            if i % 200 == 0:
                print(f"  v2 {days[i]} ({i}/{len(days)}) rows={len(rows):,}", flush=True)
    return pd.DataFrame(rows)


def build_v3(top_n: int = 400) -> pd.DataFrame:
    swap_days = _days("uniswap_v3", "swaps")
    print(f"  v3 ranking pools over {len(swap_days)} days", flush=True)
    keep = _v3_pool_universe(swap_days, top_n)
    print(f"  v3 universe {len(keep)} pools", flush=True)

    ev_days = sorted(set(_days("uniswap_v3", "mints")) | set(_days("uniswap_v3", "burns")))
    all_days = sorted(set(swap_days) | set(ev_days))

    # Pass one: read every liquidity event for the universe, so each pool's tick
    # set is known before the replay and can be compressed into a fixed index.
    print("  v3 reading liquidity events", flush=True)
    events: dict[str, list[tuple]] = defaultdict(list)
    with ProcessPoolExecutor() as ex:
        for d, res in zip(ev_days, ex.map(_v3_events, ev_days, chunksize=16)):
            for pid, lo, hi, delta in res:
                if pid in keep:
                    events[d].append((pid, lo, hi, delta))
    pool_ticks: dict[str, set[int]] = defaultdict(set)
    for evs in events.values():
        for pid, lo, hi, _ in evs:
            pool_ticks[pid].add(lo)
            pool_ticks[pid].add(hi)
    index: dict[str, tuple[list[int], dict[int, int]]] = {}
    trees: dict[str, Fenwick] = {}
    for pid, ts in pool_ticks.items():
        srt = sorted(ts)
        index[pid] = (srt, {t: i for i, t in enumerate(srt)})
        trees[pid] = Fenwick(len(srt))
    print(f"  v3 tick sets built for {len(index)} pools", flush=True)

    # Pass two: replay chronologically. A day's liquidity events are applied
    # before that day's returns are priced, so newly minted depth counts for the
    # day it arrived; the alternative convention moves nothing material because
    # the tick summary is already a daily average.
    rows: list[dict] = []
    for i, d in enumerate(all_days):
        for pid, lo, hi, delta in events.get(d, ()):
            srt, pos = index[pid]
            tree = trees[pid]
            tree.add(pos[lo], delta)
            tree.add(pos[hi], -delta)
        swaps = _v3_swaps_day(d, keep)
        if not swaps:
            continue
        counts = _v3_event_counts(d)
        for pid, a in swaps.items():
            if not a["ticks"]:
                continue
            w = np.array(a["w"], dtype=float)
            tk = np.array(a["ticks"], dtype=float)
            tick = int(np.average(tk, weights=w) if w.sum() > 0 else np.mean(tk))
            hp = sorted(a["hp"].items())
            hh = np.array([k for k, _ in hp], dtype=np.int64)
            sp = np.array([v for _, v in hp], dtype=float)
            rv1, rv4, rvoc, mx = _rv_multiscale(hh, sp, scale=2.0)
            fee = derive_fee_tier(pid, a["token0"], a["token1"])
            liq = float("nan")
            if pid in index:
                srt, _pos = index[pid]
                j = int(np.searchsorted(srt, tick, side="right")) - 1
                liq = float(trees[pid].prefix(j)) if j >= 0 else 0.0
            nm, nb = counts.get(pid, (0, 0))
            rows.append({
                "day": d, "venue": "uniswap_v3", "pool": pid,
                "token0": a["token0"], "token1": a["token1"],
                "sym0": a["sym0"], "sym1": a["sym1"],
                "n_hours": len(hp), "n_ret": max(0, len(hp) - 1),
                "volume_usd": a["vol"], "n_swap": a["n"],
                "reserve0": float("nan"), "reserve1": float("nan"),
                "rv": rv1, "rv_4h": rv4, "rv_oc": rvoc, "max_abs_ret": mx,
                "n_mint": nm, "n_burn": nb,
                "fee_rate": (fee / 1e6) if fee else float("nan"),
                "tick": tick, "liquidity": liq,
                "sqrt_price_x96": float(np.median(sp)) if sp.size else float("nan"),
            })
        if i % 200 == 0:
            print(f"  v3 {d} ({i}/{len(all_days)}) rows={len(rows):,}", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("v2", "both"):
        v2 = build_v2()
        print(f"v2 pool-days: {len(v2):,}", flush=True)
        write_panel(v2, PROC / "rent_incidence_v2_pool_day.parquet",
                    code_sources=["scripts/build_rent_incidence_panel.py"])
    if which in ("v3", "both"):
        v3 = build_v3()
        print(f"v3 pool-days: {len(v3):,}", flush=True)
        write_panel(v3, PROC / "rent_incidence_v3_pool_day.parquet",
                    code_sources=["scripts/build_rent_incidence_panel.py",
                                  "src/ddvc/pricing/v3pools.py"])


if __name__ == "__main__":
    main()
