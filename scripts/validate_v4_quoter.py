#!/usr/bin/env python3
"""Does the V3 concentrated-liquidity quoter reproduce realised Uniswap v4 swaps?

Uniswap v4 keeps v3's concentrated-liquidity maths, so `quote_exact_input` should
price it unchanged. Three things differ and each is checked rather than assumed:
liquidity changes arrive as a single `modify_liquidities` stream where a removal is
a NEGATIVE amount instead of a separate burns feed; the pool identifier is a 32-byte
pool id under the singleton PoolManager rather than a contract address, so the
CREATE2 fee derivation used for v3 does not apply and is not needed because v4
carries `feeTier` directly; and token0 may be the zero address, meaning NATIVE ETH
rather than WETH, since v4 restored unwrapped ETH as a pool asset.

Method mirrors the v3 validation: consecutive swaps in the same pool give the
pre-trade state, so each swap is re-quoted against the state left by its
predecessor and compared with what it actually returned. Errors are reported by
direction and by whether the quote crossed an initialized tick, because a
tick-traversal fault is directional and a pooled statistic hides it. That is not
hypothetical: the same check on v3 found upward-crossing quotes low by a median
62.6% while every other cell was exact.

Hook-bearing and dynamic-fee pools are outside this quoter's contract because the
subgraph rows do not expose their per-swap hook cash flows or realised fee. They are
excluded explicitly and measured in the separate v4 support audit. Static-fee pools
use their actual tick spacing and can carry fee tiers outside v3's four-tier set.

Writes  output/exhibits/v4_quoter_validation.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json

import pandas as pd

from ddvc.fetch.raw import block_value, timestamp_value, v4_pool_quote_supported
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.pricing.v3quote import quote_exact_input
from ddvc.tables import write_exhibit

RAW = DATA_DIR / "raw" / "thegraph" / "uniswap_v4"
OUT = OUTPUT_DIR / "exhibits" / "v4_quoter_validation.jsonl"


def days() -> list[str]:
    return sorted(p.name[len("uniswap_v4_swaps_"):-len(".jsonl.gz")]
                  for p in RAW.glob("uniswap_v4_swaps_*.jsonl.gz"))


def accumulate_ticks(through: str, pools: set[str]) -> dict[str, dict[int, int]]:
    """Net liquidity per initialized tick from v4's single signed stream."""
    net: dict[str, dict[int, int]] = {p: {} for p in pools}
    seen = 0
    for day in days():
        if day > through:
            break
        p = RAW / f"uniswap_v4_modify_liquidities_{day}.jsonl.gz"
        if not p.exists():
            continue
        seen += 1
        with gzip.open(p, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                pid = ((r.get("pool") or {}).get("id") or "").lower()
                if pid not in net:
                    continue
                try:
                    amt = int(r.get("amount") or 0)
                    lo, hi = int(r["tickLower"]), int(r["tickUpper"])
                except (TypeError, ValueError, KeyError):
                    continue
                if amt == 0:
                    continue
                d = net[pid]
                d[lo] = d.get(lo, 0) + amt
                d[hi] = d.get(hi, 0) - amt
    print(f"  read {seen} liquidity-event files through {through}", flush=True)
    return net


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=None, help="defaults to the last day held")
    ap.add_argument("--pools", type=int, default=6, help="busiest pools on the day")
    ap.add_argument("--max-per-pool", type=int, default=250)
    args = ap.parse_args()

    day = args.day or days()[-1]
    rows_by_pool: dict[str, list[dict]] = {}
    excluded = 0
    with gzip.open(RAW / f"uniswap_v4_swaps_{day}.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            if not v4_pool_quote_supported(r):
                excluded += 1
                continue
            pid = ((r.get("pool") or {}).get("id") or "").lower()
            if pid:
                rows_by_pool.setdefault(pid, []).append(r)
    busiest = sorted(rows_by_pool, key=lambda k: -len(rows_by_pool[k]))[: args.pools]
    print(f"validating on {day}: {len(rows_by_pool):,} pools traded, "
          f"taking the {len(busiest)} busiest; {excluded:,} unsupported hook/dynamic swaps excluded",
          flush=True)

    net = accumulate_ticks(day, set(busiest))
    out = []
    for pid in busiest:
        s = sorted(
            rows_by_pool[pid],
            key=lambda r: (
                int(block_value(r) or timestamp_value(r) or 0),
                int(r.get("logIndex") or 0),
            ),
        )
        pool = s[0]["pool"]
        t0, t1 = pool["token0"], pool["token1"]
        try:
            d0, d1 = int(t0["decimals"]), int(t1["decimals"])
            fee = int(pool["feeTier"])
            tick_spacing = int(pool["tickSpacing"])
        except (KeyError, TypeError, ValueError):
            continue
        ticks = net[pid]
        if not ticks:
            print(f"  {t0.get('symbol')}/{t1.get('symbol')}: no liquidity events held, skipped")
            continue
        used = 0
        for prev, cur in zip(s, s[1:]):
            if used >= args.max_per_pool:
                break
            try:
                sqrt_before = int(prev.get("sqrtPriceX96") or 0)
                tick_before = int(prev.get("tick") or 0)
                a0, a1 = float(cur["amount0"]), float(cur["amount1"])
            except (TypeError, ValueError, KeyError):
                continue
            if sqrt_before <= 0:
                continue
            liq = sum(v for t, v in ticks.items() if t <= tick_before)
            if liq <= 0:
                continue
            zero_for_one = a0 > 0
            amt_in_h, amt_out_h = (a0, -a1) if zero_for_one else (a1, -a0)
            if amt_in_h <= 0 or amt_out_h <= 0:
                continue
            dec_in, dec_out = (d0, d1) if zero_for_one else (d1, d0)
            q = quote_exact_input(zero_for_one=zero_for_one,
                                  amount_in=int(amt_in_h * 10 ** dec_in),
                                  sqrt_price_x96=sqrt_before, liquidity=liq,
                                  tick_net=ticks, tick_spacing=tick_spacing, fee_pips=fee)
            pred = q.amount_out / 10 ** dec_out
            out.append({"pool": pid[:18], "pair": f"{t0['symbol']}/{t1['symbol']}",
                        "fee": fee, "zero_for_one": zero_for_one,
                        "crossed": q.crossed_ticks,
                        "err_pct": 100 * (pred - amt_out_h) / amt_out_h})
            used += 1
        print(f"  {t0['symbol']}/{t1['symbol']} fee={fee}: {used} swaps", flush=True)

    df = pd.DataFrame(out)
    if df.empty:
        print("no comparable v4 swaps")
        return 1
    df["abs_err"] = df.err_pct.abs()
    print(f"\n{len(df):,} realised v4 swaps re-quoted offline\n")
    print("BY DIRECTION:")
    for zfo, g in df.groupby("zero_for_one"):
        lab = "token0->token1 (price falls)" if zfo else "token1->token0 (price rises)"
        print(f"  {lab:<32} n={len(g):>5}  median |err| {g.abs_err.median():>9.4f}%  "
              f"within 1% {100 * (g.abs_err < 1).mean():>5.1f}%")
    print("\nBY TICK CROSSING (a traversal fault is directional):")
    for (zfo, cr), g in df.assign(cr=df.crossed > 0).groupby(["zero_for_one", "cr"]):
        print(f"  {'0->1' if zfo else '1->0'}  crossed={str(cr):<5} n={len(g):>5}  "
              f"median signed {g.err_pct.median():>+10.4f}%")
    print("\nPER SUPPORTED POOL:")
    for (pair, fee), g in df.groupby(["pair", "fee"]):
        print(f"  {pair:<22} fee={fee:<7} n={len(g):>5}  "
              f"median |err| {g.abs_err.median():>9.4f}%")
    write_exhibit(df, OUT)
    print(f"\nwrote {OUT.relative_to(OUTPUT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
