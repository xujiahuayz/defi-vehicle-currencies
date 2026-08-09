#!/usr/bin/env python3
"""Balancer weighted-pool executable-depth quote extension.

This checks whether adding Balancer weighted pools materially changes the WETH
route-cost availability story. It uses Balancer daily pool balances, weights,
and swap fees from the canonical market-state layer.
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.prices import day_prices
from ddvc.state_data import STATE_ROOT, read_multi_asset_partition

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
MARKET_STATE = STATE_ROOT

from ddvc.paper_tables import _int, _num, _pct, _write_table

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


def _migrate_cached_output() -> int:
    path = EMP / "balancer_weighted_quote_extension.pkl"
    if not path.exists():
        print(f"no Balancer cache to migrate: {path}")
        return 0
    out = pd.read_pickle(path)
    legacy = "balancer_vehicle_advantage_bps"
    if legacy not in out.columns:
        print(f"Balancer cache already canonical: {path}")
        return 0
    out["balancer_direct_cost_advantage"] = (
        -pd.to_numeric(out[legacy], errors="coerce") / 10_000.0
    )
    out = out.drop(columns=[legacy])
    out.to_pickle(path)
    print(f"migrated {len(out):,} Balancer quote rows -> {path}")
    return 0


def _prices(stamp: str) -> dict[str, float]:
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return {}
    legs = pd.read_parquet(path, columns=[
        "token_in", "token_out", "token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd"
    ])
    return {k: v[1] for k, v in day_prices(legs).items()}


@lru_cache(maxsize=4)
def _load_pools(stamp: str) -> dict[frozenset[str], list[WeightedPool]]:
    pools: dict[frozenset[str], list[WeightedPool]] = defaultdict(list)
    path = MARKET_STATE / "multi_asset" / "balancer" / f"{stamp}.parquet"
    if not path.exists():
        return pools
    state = read_multi_asset_partition("balancer", stamp, root=MARKET_STATE)
    snapshots = state[state["record_type"].eq("snapshot_token")]
    for pid, group in snapshots.groupby("pool", sort=False):
        pool_families = group["pool_family"].dropna()
        if pool_families.empty or str(pool_families.iloc[0]) != "weighted" or len(group) != 2:
            continue
        try:
            rows = list(group.itertuples(index=False))
            t0, t1 = rows
            a0, a1 = str(t0.token).lower(), str(t1.token).lower()
            b0 = int(t0.balance_raw) / 10 ** int(t0.decimals)
            b1 = int(t1.balance_raw) / 10 ** int(t1.decimals)
            w0 = int(t0.weight_1e18) / 10 ** 18
            w1 = int(t1.weight_1e18) / 10 ** 18
            fee = int(t0.fee_1e18) / 10 ** 18
        except (TypeError, ValueError, ArithmeticError):
            continue
        if not a0 or not a1 or b0 <= 0 or b1 <= 0 or w0 <= 0 or w1 <= 0:
            continue
        pools[frozenset((a0, a1))].append(WeightedPool(
            pool=str(pid).lower(),
            token0=a0,
            token1=a1,
            sym0=str(t0.token_symbol or ""),
            sym1=str(t1.token_symbol or ""),
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
                "balancer_direct_cost_advantage": (
                    (bal_direct_usd - bal_vehicle_usd) / bal_direct_usd
                    if bal_direct_usd > 0 and bal_vehicle_usd > 0
                    else np.nan
                ),
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
            "Median Balancer direct cost advantage (fraction)": _num(
                both["balancer_direct_cost_advantage"].median(), 4
            ),
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrate-cache",
        action="store_true",
        help="rewrite a legacy cached result to the canonical direct-cost schema and exit",
    )
    args = parser.parse_args()
    if args.migrate_cache:
        return _migrate_cached_output()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
