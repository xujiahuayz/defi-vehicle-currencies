#!/usr/bin/env python3
"""Does the offline V3 quoter reproduce realised V3 swap outputs?

The v2 constant-product quoter in `src/ddvc/cpquote.py` was accepted only after it
reproduced realised swap outputs at a median absolute error of 0.0000%. The V3
quoter in `src/ddvc/pricing/v3quote.py` carries the route-cost panel and the whole
multi-venue counterfactual, and it had no equivalent validation, so its errors
would arrive as economics rather than as a failed test.

Method. Consecutive swaps in the same pool give the pre-trade state for free: the
`sqrtPriceX96` and `tick` recorded on swap i-1 are the state immediately before
swap i, since nothing but a swap moves the price within a pool. So for each
adjacent pair we quote swap i's realised input against the state left by swap i-1
and compare with swap i's realised output. Active liquidity comes from the
tick-net map accumulated from every mint and burn since pool inception, which the
local data covers because v3 files begin 2021-05-04 and V3 launched 2021-05-05.

Errors are reported SEPARATELY BY DIRECTION. A tick-traversal fault is
directional by construction, so a pooled error statistic would average a broken
direction against a working one and hide it.

Reads   data/raw/thegraph/uniswap_v3/uniswap_v3_{swaps,mints,burns}_*.jsonl.gz
Writes  output/exhibits/v3_quoter_validation.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RAW = ROOT / "data" / "raw" / "thegraph" / "uniswap_v3"
OUT = ROOT / "output" / "exhibits" / "v3_quoter_validation.jsonl"

from ddvc.pricing.v3quote import quote_exact_input  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402
from ddvc.provenance import stamp  # noqa: E402

# Deep pools with unambiguous fee tiers. Token ORDER is deliberately NOT recorded
# here: V3 orders token0/token1 by address, so hardcoding it invites exactly the
# error that made a first run of this script report -100% and +1e17% errors and
# nearly condemned a correct quoter. Order and symbols are read from the swap
# records; only decimals-by-address are asserted, since the raw data omits them.
POOLS = {
    "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640": ("USDC/WETH 0.05%", 500),
    "0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8": ("USDC/WETH 0.30%", 3000),
    "0x4e68ccd3e89f51c3074ca5072bbac773960dfa36": ("WETH/USDT 0.30%", 3000),
    "0xcbcdf9626bc03e24f779434178a73a0b4bad62ed": ("WBTC/WETH 0.30%", 3000),
}

DECIMALS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": 18,   # WETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,    # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7": 6,    # USDT
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": 8,    # WBTC
}


def _days(start: str, end: str) -> list[str]:
    return sorted(p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")]
                  for p in RAW.glob("uniswap_v3_swaps_*.jsonl.gz")
                  if start <= p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")] <= end)


def accumulate_ticks(target_day: str, pools: set[str]) -> dict[str, dict[int, int]]:
    """Net liquidity per initialized tick, from inception through target_day."""
    net: dict[str, dict[int, int]] = {p: {} for p in pools}
    files = 0
    for day in _days("00000000", target_day):
        for kind, sign in (("mints", 1), ("burns", -1)):
            p = RAW / f"uniswap_v3_{kind}_{day}.jsonl.gz"
            if not p.exists():
                continue
            files += 1
            with gzip.open(p, "rt") as fh:
                for line in fh:
                    r = json.loads(line)
                    pid = ((r.get("pool") or {}).get("id") or "").lower()
                    if pid not in net:
                        continue
                    amt = int(r.get("amount") or 0)
                    if amt == 0:
                        continue
                    lo, hi = int(r["tickLower"]), int(r["tickUpper"])
                    d = net[pid]
                    d[lo] = d.get(lo, 0) + sign * amt
                    d[hi] = d.get(hi, 0) - sign * amt
    print(f"  accumulated {files} liquidity-event files through {target_day}", flush=True)
    return net


def active_liquidity(ticks: dict[int, int], tick: int) -> int:
    return sum(v for t, v in ticks.items() if t <= tick)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default="20240115")
    ap.add_argument("--max-per-pool", type=int, default=400)
    args = ap.parse_args()

    net = accumulate_ticks(args.day, set(POOLS))
    for pid, (label, *_rest) in POOLS.items():
        print(f"  {label}: {len(net[pid]):,} initialized ticks", flush=True)

    swaps: dict[str, list[dict]] = {p: [] for p in POOLS}
    with gzip.open(RAW / f"uniswap_v3_swaps_{args.day}.jsonl.gz", "rt") as fh:
        for line in fh:
            r = json.loads(line)
            pid = ((r.get("pool") or {}).get("id") or "").lower()
            if pid in swaps:
                swaps[pid].append(r)

    rows = []
    for pid, (label, fee) in POOLS.items():
        s = sorted(swaps[pid], key=lambda r: (int(r["transaction"]["blockNumber"]),
                                              int(r.get("logIndex") or 0)))
        ticks = net[pid]
        if not s:
            print(f"  {label}: no swaps on this day")
            continue
        pool0 = (s[0]["pool"]["token0"]["id"]).lower()
        pool1 = (s[0]["pool"]["token1"]["id"]).lower()
        if pool0 not in DECIMALS or pool1 not in DECIMALS:
            print(f"  {label}: unknown decimals for {pool0}/{pool1}, skipping")
            continue
        d0, d1 = DECIMALS[pool0], DECIMALS[pool1]
        print(f"  {label}: token0={s[0]['pool']['token0']['symbol']}({d0}) "
              f"token1={s[0]['pool']['token1']['symbol']}({d1})")
        used = 0
        for prev, cur in zip(s, s[1:]):
            if used >= args.max_per_pool:
                break
            sqrt_before = int(prev.get("sqrtPriceX96") or 0)
            tick_before = int(prev.get("tick") or 0)
            if sqrt_before <= 0:
                continue
            L = active_liquidity(ticks, tick_before)
            if L <= 0:
                continue
            a0, a1 = float(cur["amount0"]), float(cur["amount1"])
            # sign convention: positive amount = into the pool
            zero_for_one = a0 > 0
            amt_in_h, amt_out_h = (a0, -a1) if zero_for_one else (a1, -a0)
            if amt_in_h <= 0 or amt_out_h <= 0:
                continue
            dec_in, dec_out = (d0, d1) if zero_for_one else (d1, d0)
            amt_in_raw = int(amt_in_h * 10 ** dec_in)
            q = quote_exact_input(zero_for_one=zero_for_one, amount_in=amt_in_raw,
                                  sqrt_price_x96=sqrt_before, liquidity=L,
                                  tick_net=ticks, tick_spacing=10 if fee == 500 else 60,
                                  fee_pips=fee)
            pred = q.amount_out / 10 ** dec_out
            if amt_out_h <= 0:
                continue
            rows.append({"pool": label, "zero_for_one": zero_for_one,
                         "crossed": q.crossed_ticks,
                         "err_pct": 100 * (pred - amt_out_h) / amt_out_h})
            used += 1
        print(f"  {label}: validated {used} swaps", flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        print("no comparable swaps")
        return 1
    df["abs_err"] = df.err_pct.abs()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_exhibit(df, OUT)

    print(f"\n{len(df):,} realised swaps re-quoted offline\n")
    print("BY DIRECTION (a tick-traversal fault is directional, so never pool these):")
    for zfo, g in df.groupby("zero_for_one"):
        d = "token0->token1 (price falls)" if zfo else "token1->token0 (price rises)"
        print(f"  {d:<32} n={len(g):>5}  median |err| {g.abs_err.median():>8.4f}%  "
              f"within 1% {100*(g.abs_err<1).mean():>5.1f}%  median signed {g.err_pct.median():>+8.4f}%")
    print("\nBY WHETHER THE QUOTE CROSSED AN INITIALIZED TICK:")
    for (zfo, cr), g in df.assign(cr=df.crossed > 0).groupby(["zero_for_one", "cr"]):
        d = "0->1" if zfo else "1->0"
        print(f"  {d}  crossed={str(cr):<5} n={len(g):>5}  median signed err {g.err_pct.median():>+9.4f}%")
    stamp(OUT, code_sources=["src/ddvc/pricing/v3quote.py",
                             "src/ddvc/pricing/v3pools.py",
                             "scripts/validate_v3_quoter.py"],
          rows=len(df),
          notes=f"median |err| {df.abs_err.median():.6f}% over {len(df)} realised swaps")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
