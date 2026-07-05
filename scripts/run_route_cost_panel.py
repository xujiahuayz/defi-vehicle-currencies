#!/usr/bin/env python3
"""Build a first DVC-native route-cost panel for Proposition 1.

This ports the counterfactual idea from DDC into the DVC raw layout. The first
implemented layer uses V2-style constant-product pools from Uniswap V2 and
SushiSwap V2 hourly reserves. For each day, endpoint pair, vehicle candidate,
and trade-size bucket, it compares the best direct route against the best
two-hop vehicle route available in the same daily reserve snapshot.

The output is deliberately marked v2_cp. It is a real counterfactual route-cost
panel, but not the final all-venue quoter: V3 exact tick-level quoting still
needs the DDC V3 quoter port.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.paths import DATA_DIR, OUTPUT_DIR  # noqa: E402
from ddvc.pricing.v2quote import quote_exact_input_float  # noqa: E402


VEHICLE_BY_ADDRESS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
}
VEHICLE_ADDRESSES = tuple(VEHICLE_BY_ADDRESS)
V2_SOURCES = ("uniswap_v2", "sushiswap_v2")
OUT_DATA = DATA_DIR / "empirical"
OUT = OUTPUT_DIR / "empirical"


@dataclass(frozen=True)
class Pool:
    source: str
    pool: str
    token0: str
    token1: str
    sym0: str
    sym1: str
    reserve0: float
    reserve1: float


def _raw_path(source: str, stream: str, stamp: str) -> Path:
    return DATA_DIR / "raw" / "thegraph" / source / f"{source}_{stream}_{stamp}.jsonl.gz"


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


def _day_prices(legs: pd.DataFrame) -> dict[str, tuple[str, float]]:
    rows = []
    for side in ("in", "out"):
        amount = legs[f"amount_{side}"].replace(0, np.nan)
        px = legs["amount_usd"] / amount
        tmp = pd.DataFrame({
            "token": legs[f"token_{side}"].str.lower(),
            "symbol": legs[f"token_{side}_sym"],
            "price": px,
            "weight": legs["amount_usd"],
        })
        rows.append(tmp)
    d = pd.concat(rows, ignore_index=True)
    d = d[np.isfinite(d["price"]) & (d["price"] > 0) & (d["price"] < 1_000_000)]
    out: dict[str, tuple[str, float]] = {}
    for token, g in d.groupby("token"):
        if len(g) < 3:
            continue
        # Weighted median without pulling in extra dependencies.
        g = g.sort_values("price")
        w = g["weight"].clip(lower=1e-9).to_numpy()
        cdf = np.cumsum(w) / w.sum()
        price = float(g["price"].to_numpy()[np.searchsorted(cdf, 0.5)])
        symbol = str(g["symbol"].mode().iloc[0]) if not g["symbol"].mode().empty else token[:8]
        out[token] = (symbol, price)
    return out


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
    roles["token"] = roles["token"].str.lower()
    sources = (
        roles[roles["role"].eq("source")][["component_key", "token", "symbol"]]
        .drop_duplicates()
        .rename(columns={"token": "src", "symbol": "src_sym"})
    )
    sinks = (
        roles[roles["role"].eq("sink")][["component_key", "token", "symbol"]]
        .drop_duplicates()
        .rename(columns={"token": "tgt", "symbol": "tgt_sym"})
    )
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
        out.groupby(["src", "src_sym", "tgt", "tgt_sym"], as_index=False)
        .agg(realized_bridge_volume_usd=("volume", "sum"), n_routes=("volume", "size"))
        .sort_values("realized_bridge_volume_usd", ascending=False)
        .head(top_pairs)
    )
    return out


def _load_v2_pools(stamp: str, hour: int) -> dict[frozenset[str], list[Pool]]:
    target_ts = int(pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]} {hour:02d}:00:00", tz="UTC").timestamp())
    pools: dict[frozenset[str], list[Pool]] = defaultdict(list)
    for source in V2_SOURCES:
        path = _raw_path(source, "hourly_reserves", stamp)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for line in fh:
                rec = json.loads(line)
                if int(rec.get("hourStartUnix", -1)) != target_ts:
                    continue
                pair = rec.get("pair") or {}
                t0 = pair.get("token0") or {}
                t1 = pair.get("token1") or {}
                try:
                    r0 = float(rec.get("reserve0") or 0)
                    r1 = float(rec.get("reserve1") or 0)
                except (TypeError, ValueError):
                    continue
                a0 = str(t0.get("id", "")).lower()
                a1 = str(t1.get("id", "")).lower()
                if not a0 or not a1 or r0 <= 0 or r1 <= 0:
                    continue
                pools[frozenset((a0, a1))].append(Pool(
                    source=source,
                    pool=str(pair.get("id", "")).lower(),
                    token0=a0,
                    token1=a1,
                    sym0=str(t0.get("symbol", "")),
                    sym1=str(t1.get("symbol", "")),
                    reserve0=r0,
                    reserve1=r1,
                ))
    return pools


def _best_quote(
    pools: dict[frozenset[str], list[Pool]],
    token_in: str,
    token_out: str,
    amount_in: float,
) -> tuple[float, str, str] | tuple[float, None, None]:
    best = 0.0
    best_source = None
    best_pool = None
    for p in pools.get(frozenset((token_in, token_out)), []):
        if token_in == p.token0 and token_out == p.token1:
            out = quote_exact_input_float(amount_in, p.reserve0, p.reserve1)
        elif token_in == p.token1 and token_out == p.token0:
            out = quote_exact_input_float(amount_in, p.reserve1, p.reserve0)
        else:
            continue
        if out > best:
            best = out
            best_source = p.source
            best_pool = p.pool
    return best, best_source, best_pool


def _build_day(stamp: str, trade_sizes: list[float], top_pairs: int, hour: int) -> pd.DataFrame:
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
    prices = _day_prices(legs)
    pairs = _routes_by_pair(legs, top_pairs=top_pairs)
    if pairs.empty:
        return pd.DataFrame()
    pools = _load_v2_pools(stamp, hour=hour)
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
                advantage = (
                    (veh_usd - direct_usd) / direct_usd
                    if direct_usd > 0 and veh_usd > 0 else math.nan
                )
                rows.append({
                    "date": date,
                    "method": "v2_cp_daily_hour",
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
                    "vehicle_route_advantage": advantage,
                    "direct_source": direct_source,
                    "direct_pool": direct_pool,
                    "hop1_source": hop1_source,
                    "hop1_pool": hop1_pool,
                    "hop2_source": hop2_source,
                    "hop2_pool": hop2_pool,
                    "realized_bridge_volume_usd": float(r.realized_bridge_volume_usd),
                    "n_realized_routes": int(r.n_routes),
                })
    return pd.DataFrame(rows)


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _summarize(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    x = panel.copy()
    x["advantage_bps"] = x["vehicle_route_advantage"] * 10_000
    rows = []
    for (vehicle, size), g in x.groupby(["vehicle_sym", "trade_size_usd"]):
        avail = g[g["vehicle_available"]]
        both = g[g["vehicle_available"] & g["direct_available"] & np.isfinite(g["vehicle_route_advantage"])]
        adv = both["advantage_bps"].clip(lower=-100_000, upper=100_000) if len(both) else pd.Series(dtype=float)
        t_stat = p_value = math.nan
        if len(adv) > 2 and float(adv.std()) > 0:
            t_stat, p_value = stats.ttest_1samp(adv.to_numpy(dtype=float), 0.0)
        rows.append({
            "vehicle": vehicle,
            "trade_size_usd": size,
            "rows": int(len(g)),
            "vehicle_available_share": float(g["vehicle_available"].mean()),
            "direct_available_share": float(g["direct_available"].mean()),
            "both_available_rows": int(len(both)),
            "vehicle_beats_direct_share": float((both["vehicle_route_advantage"] > 0).mean()) if len(both) else math.nan,
            "median_advantage_bps": float(both["advantage_bps"].median()) if len(both) else math.nan,
            "p25_advantage_bps": float(both["advantage_bps"].quantile(0.25)) if len(both) else math.nan,
            "p75_advantage_bps": float(both["advantage_bps"].quantile(0.75)) if len(both) else math.nan,
            "mean_advantage_bps_winsor": float(adv.mean()) if len(adv) else math.nan,
            "t_winsor_mean": float(t_stat) if np.isfinite(t_stat) else math.nan,
            "p_winsor_mean": float(p_value) if np.isfinite(p_value) else math.nan,
            "no_direct_vehicle_available_rows": int((~g["direct_available"] & g["vehicle_available"]).sum()),
            "covered_realized_volume_usd": float(avail["realized_bridge_volume_usd"].sum()),
        })
    return pd.DataFrame(rows).sort_values(["trade_size_usd", "vehicle"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Run DVC route-cost counterfactual panel.")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--top-pairs", type=int, default=200)
    ap.add_argument("--trade-sizes", default="1000,10000,100000")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out_path = OUT_DATA / "route_cost_panel_v2.parquet"
    summary_path = OUT / "route_cost_panel_v2_summary.csv"
    if out_path.exists() and not args.force:
        panel = pd.read_parquet(out_path)
    else:
        sizes = [float(x) for x in args.trade_sizes.split(",") if x.strip()]
        frames = []
        stamps = _available_stamps(args.start, args.end)
        for i, stamp in enumerate(stamps, 1):
            day = _build_day(stamp, sizes, top_pairs=args.top_pairs, hour=args.hour)
            if not day.empty:
                frames.append(day)
            if i % 25 == 0 or i == len(stamps):
                print(f"route-cost panel [{i}/{len(stamps)}] {stamp}", flush=True)
        panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        _write(panel, out_path)
    summary = _summarize(panel)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)
    print(f"wrote {len(panel):,} rows -> {out_path}")
    print(f"wrote summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
