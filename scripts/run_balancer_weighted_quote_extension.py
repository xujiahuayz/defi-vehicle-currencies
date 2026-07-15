#!/usr/bin/env python3
"""Balancer weighted-pool executable-depth quote extension.

This checks whether adding Balancer weighted pools materially changes the WETH
route-cost availability story. It uses Balancer daily pool balances, weights,
and swap fees already present in the rebuilt raw layer.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _pct, _write_table  # noqa: E402
from run_route_cost_panel import _day_prices  # noqa: E402

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


@dataclass(frozen=True)
class WeightedPool:
    pool: str
    token0: str
    token1: str
    sym0: str
    sym1: str
    balance0: float
    balance1: float
    weight0: float
    weight1: float
    fee: float


def _raw_daily(stamp: str) -> Path:
    return DATA / "raw" / "thegraph" / "balancer" / f"balancer_daily_{stamp}.jsonl.gz"


def _prices(stamp: str) -> dict[str, float]:
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return {}
    legs = pd.read_parquet(path, columns=[
        "token_in", "token_out", "token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd"
    ])
    return {k: v[1] for k, v in _day_prices(legs).items()}


def _load_pools(stamp: str) -> dict[frozenset[str], list[WeightedPool]]:
    path = _raw_daily(stamp)
    pools: dict[frozenset[str], list[WeightedPool]] = defaultdict(list)
    if not path.exists():
        return pools
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            pool = rec.get("pool") or {}
            if str(pool.get("poolType") or "").lower() != "weighted":
                continue
            toks = pool.get("tokens") or []
            if len(toks) != 2:
                continue
            try:
                t0, t1 = toks
                a0 = str(t0.get("address") or "").lower()
                a1 = str(t1.get("address") or "").lower()
                b0 = float(t0.get("balance") or 0.0)
                b1 = float(t1.get("balance") or 0.0)
                w0 = float(t0.get("weight") or 0.0)
                w1 = float(t1.get("weight") or 0.0)
                fee = float(pool.get("swapFee") or 0.0)
            except (TypeError, ValueError):
                continue
            if not a0 or not a1 or b0 <= 0 or b1 <= 0 or w0 <= 0 or w1 <= 0:
                continue
            pools[frozenset((a0, a1))].append(WeightedPool(
                pool=str(pool.get("id") or "").lower(),
                token0=a0,
                token1=a1,
                sym0=str(t0.get("symbol") or ""),
                sym1=str(t1.get("symbol") or ""),
                balance0=b0,
                balance1=b1,
                weight0=w0,
                weight1=w1,
                fee=max(0.0, min(fee, 0.5)),
            ))
    return pools


def _quote_pool(p: WeightedPool, token_in: str, token_out: str, amount_in: float) -> float:
    if amount_in <= 0:
        return 0.0
    if token_in == p.token0 and token_out == p.token1:
        bi, bo, wi, wo = p.balance0, p.balance1, p.weight0, p.weight1
    elif token_in == p.token1 and token_out == p.token0:
        bi, bo, wi, wo = p.balance1, p.balance0, p.weight1, p.weight0
    else:
        return 0.0
    amount_after_fee = amount_in * (1.0 - p.fee)
    if amount_after_fee <= 0:
        return 0.0
    try:
        return bo * (1.0 - (bi / (bi + amount_after_fee)) ** (wi / wo))
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0.0


def _best_quote(pools: dict[frozenset[str], list[WeightedPool]], token_in: str, token_out: str, amount_in: float) -> float:
    return max(
        (_quote_pool(p, token_in, token_out, amount_in) for p in pools.get(frozenset((token_in, token_out)), [])),
        default=0.0,
    )


def run() -> pd.DataFrame:
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle"].str.lower().eq(WETH)].copy()
    d["stamp"] = d["date"].str.replace("-", "", regex=False)
    d = d[d["stamp"].ge("20210422")].copy()
    rows = []
    for i, (stamp, g) in enumerate(d.groupby("stamp"), 1):
        pools = _load_pools(stamp)
        if not pools:
            continue
        prices = _prices(stamp)
        for r in g.itertuples(index=False):
            src = str(r.src).lower()
            tgt = str(r.tgt).lower()
            src_price = prices.get(src)
            tgt_price = prices.get(tgt)
            if not src_price or not tgt_price or src_price <= 0 or tgt_price <= 0:
                continue
            amount_in = float(r.trade_size_usd) / src_price
            direct_out = _best_quote(pools, src, tgt, amount_in)
            hop1 = _best_quote(pools, src, WETH, amount_in)
            hop2 = _best_quote(pools, WETH, tgt, hop1) if hop1 > 0 else 0.0
            bal_direct_usd = direct_out * tgt_price
            bal_vehicle_usd = hop2 * tgt_price
            rows.append({
                "date": r.date,
                "src": src,
                "tgt": tgt,
                "trade_size_usd": float(r.trade_size_usd),
                "existing_direct_available": bool(r.direct_available),
                "existing_vehicle_available": bool(r.vehicle_available),
                "balancer_direct_available": bal_direct_usd > 0,
                "balancer_vehicle_available": bal_vehicle_usd > 0,
                "balancer_direct_output_usd": bal_direct_usd,
                "balancer_vehicle_output_usd": bal_vehicle_usd,
                "balancer_vehicle_advantage_bps": (bal_vehicle_usd / bal_direct_usd - 1.0) * 10_000.0 if bal_direct_usd > 0 and bal_vehicle_usd > 0 else np.nan,
            })
        if i % 100 == 0:
            print(f"Balancer quote extension [{i}/{d['stamp'].nunique()}] {stamp}", flush=True)
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "balancer_weighted_quote_extension.pkl")
    table_rows = []
    for size, g in out.groupby("trade_size_usd"):
        both = g[g["balancer_direct_available"] & g["balancer_vehicle_available"]]
        table_rows.append({
            "Trade size": f"${int(size):,}",
            "Rows": _int(len(g)),
            "Balancer direct available (%)": _pct(g["balancer_direct_available"].mean()),
            "Balancer WETH route available (%)": _pct(g["balancer_vehicle_available"].mean()),
            "Adds direct rows": _int((~g["existing_direct_available"] & g["balancer_direct_available"]).sum()),
            "Adds WETH-route rows": _int((~g["existing_vehicle_available"] & g["balancer_vehicle_available"]).sum()),
            "Median Balancer WETH advantage (bp)": _num(both["balancer_vehicle_advantage_bps"].median(), 2),
        })
    table = pd.DataFrame(table_rows)
    _write_table(
        table,
        "table_r15_balancer_weighted_quote_extension",
        "Balancer weighted-pool quote extension.",
        "tab:balancer-weighted-quote-extension",
        note=(
            "Quotes use Balancer weighted-pool balances, weights, and swap fees. The table "
            "shows whether adding Balancer materially changes route availability relative to "
            "the existing V2/Sushi V2/Uniswap V3 route-cost panel."
        ),
    )
    print(f"wrote {len(out):,} Balancer quote rows")
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
