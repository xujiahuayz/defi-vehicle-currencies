#!/usr/bin/env python3
"""Per-day gas price and ETH price, so all-in route costs stop using flat constants.

The cost-dominance panel initially priced gas at a flat 25.8 gwei with ETH at
$2,500 across 2020 to 2026. Both are badly wrong at the ends of that span: gas ran
far higher through 2021 and far lower after EIP-4844, and ETH traded from a few
hundred dollars to several thousand. Since the gas term is what makes route choice
size-dependent, getting it wrong distorts exactly the margin the paper studies.

Two sources, both already available and neither needing archive state:

  ETH price   the deepest WETH-versus-stablecoin pool's reserve ratio on the day.
              Self-consistent with the rest of the pipeline, since it is the same
              price the router faced, and it needs no external feed.

  gas price   `baseFeePerGas` from one block on the day, fetched with
              eth_getBlockByNumber. Blocks are stored data rather than historical
              state, so pruned nodes serve them. Before EIP-1559 (August 2021)
              blocks carry no base fee, so the fallback samples effectiveGasPrice
              from receipts of transactions on that day.

Base fee understates what a trader actually paid, because priority tips sit on
top. The receipt path captures the total. Where both are available the receipt
median is preferred and the base fee is kept for comparison.

Reads   data/raw/thegraph/uniswap_v2/uniswap_v2_{hourly_reserves,swaps}_*.jsonl.gz
Writes  data/processed/daily_gas_eth.parquet
        output/exhibits/daily_gas_eth.csv
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RAW = ROOT / "data" / "raw" / "thegraph" / "uniswap_v2"
OUT_PARQUET = ROOT / "data" / "processed" / "daily_gas_eth.parquet"
OUT_CSV = ROOT / "output" / "exhibits" / "daily_gas_eth.csv"

from ddvc.quoter import rpc_post  # noqa: E402

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
STABLES = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
}


def eth_price(day: str) -> tuple[float | None, float]:
    """Deepest WETH/stablecoin pool's implied ETH price, and that pool's depth."""
    p = RAW / f"uniswap_v2_hourly_reserves_{day}.jsonl.gz"
    if not p.exists():
        return None, 0.0
    best_px, best_depth = None, Decimal(0)
    with gzip.open(p, "rt") as fh:
        for line in fh:
            d = json.loads(line)
            pr = d["pair"]
            t0, t1 = pr["token0"]["id"].lower(), pr["token1"]["id"].lower()
            r0, r1 = Decimal(d["reserve0"]), Decimal(d["reserve1"])
            if r0 <= 0 or r1 <= 0:
                continue
            if t0 == WETH and t1 in STABLES:
                px, depth = r1 / r0, r1
            elif t1 == WETH and t0 in STABLES:
                px, depth = r0 / r1, r0
            else:
                continue
            if depth > best_depth:
                best_px, best_depth = float(px), depth
    return best_px, float(best_depth)


def _blocks_and_txs(day: str, n: int = 12) -> tuple[list[int], list[str]]:
    p = RAW / f"uniswap_v2_swaps_{day}.jsonl.gz"
    if not p.exists():
        return [], []
    blocks, txs = [], []
    with gzip.open(p, "rt") as fh:
        for i, line in enumerate(fh):
            if i % 500:
                continue
            s = json.loads(line)
            t = s.get("transaction") or {}
            if t.get("blockNumber"):
                blocks.append(int(t["blockNumber"]))
            if t.get("id"):
                txs.append(t["id"])
            if len(blocks) >= n and len(txs) >= n:
                break
    return blocks[:n], txs[:n]


def gas_price_gwei(day: str) -> tuple[float | None, float | None]:
    """(receipt median, block base fee) in gwei; either may be None."""
    blocks, txs = _blocks_and_txs(day)
    base = None
    if blocks:
        try:
            r = rpc_post({"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
                          "params": [hex(blocks[len(blocks) // 2]), False]}, sleep=0.3)
            b = (r or {}).get("result") or {}
            if b.get("baseFeePerGas"):
                base = int(b["baseFeePerGas"], 16) / 1e9
        except Exception:
            pass
    eff = None
    if txs:
        payload = [{"jsonrpc": "2.0", "id": j, "method": "eth_getTransactionReceipt",
                    "params": [t]} for j, t in enumerate(txs[:8])]
        try:
            resp = rpc_post(payload, sleep=0.3)
            vals = []
            for r in (resp if isinstance(resp, list) else [resp]):
                res = r.get("result") or {}
                if res.get("effectiveGasPrice"):
                    vals.append(int(res["effectiveGasPrice"], 16) / 1e9)
                elif res.get("gasPrice"):
                    vals.append(int(res["gasPrice"], 16) / 1e9)
            if vals:
                vals.sort()
                eff = vals[len(vals) // 2]
        except Exception:
            pass
    return eff, base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    days = sorted(p.name.removeprefix("uniswap_v2_swaps_").removesuffix(".jsonl.gz")
                  for p in RAW.glob("uniswap_v2_swaps_*.jsonl.gz"))[:: args.stride]
    if args.limit:
        days = days[: args.limit]
    print(f"resolving gas and ETH price for {len(days)} day(s)", flush=True)

    rows = []
    for i, day in enumerate(days, 1):
        px, depth = eth_price(day)
        eff, base = gas_price_gwei(day)
        rows.append({"date": pd.to_datetime(day, format="%Y%m%d"),
                     "eth_usd": px, "pool_depth_usd": depth,
                     "gas_gwei_receipt": eff, "gas_gwei_basefee": base})
        if i % 20 == 0:
            print(f"  {i}/{len(days)}", flush=True)

    df = pd.DataFrame(rows).sort_values("date")
    # prefer the receipt median, since it includes priority tips
    df["gas_gwei"] = df.gas_gwei_receipt.fillna(df.gas_gwei_basefee)
    df["eth_usd"] = df.eth_usd.ffill().bfill()
    df["gas_gwei"] = df.gas_gwei.ffill().bfill()

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False)

    print(f"\nresolved {df.eth_usd.notna().sum()}/{len(df)} ETH prices, "
          f"{df.gas_gwei.notna().sum()}/{len(df)} gas prices")
    print("\nannual medians (the flat constants were 25.8 gwei and $2,500):")
    y = df.set_index("date").resample("YS").median(numeric_only=True)
    for idx, r in y.iterrows():
        print(f"  {idx.year}   ETH ${r.eth_usd:>8,.0f}   gas {r.gas_gwei:>7.1f} gwei")
    print(f"\nwrote {OUT_PARQUET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
