#!/usr/bin/env python3
"""V3 LP repositioning tests for vehicle-currency liquidity feedback.

This is a mechanism check for P2. It builds token-day measures of V3 mints and
burns in vehicle-linked pools and asks whether lagged near-active net minting
predicts VehicleShare. It uses existing raw mints/burns plus daily pool ticks; it
does not refetch data.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.dynamics import value_at_day_offset
from ddvc.prices import day_prices

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
CACHE = DATA / "empirical" / "_lp_repositioning_day_cache"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402

VEHICLES = {"WETH", "USDC", "USDT", "DAI", "WBTC"}
FEE_TO_SPACING = {100: 1, 500: 10, 3000: 60, 10000: 200}


def _raw(source: str, stream: str, stamp: str) -> Path:
    return DATA / "raw" / "thegraph" / source / f"{source}_{stream}_{stamp}.jsonl.gz"


def _iter(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _prices(stamp: str) -> tuple[dict[str, float], dict[str, float]]:
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return {}, {}
    legs = pd.read_parquet(path, columns=[
        "token_in", "token_out", "token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd"
    ])
    by_addr = {k: v[1] for k, v in day_prices(legs).items()}
    rows = []
    for side in ("in", "out"):
        amount = legs[f"amount_{side}"].replace(0, np.nan)
        px = legs["amount_usd"] / amount
        rows.append(pd.DataFrame({
            "symbol": legs[f"token_{side}_sym"].astype(str),
            "price": px,
            "weight": legs["amount_usd"],
        }))
    d = pd.concat(rows, ignore_index=True)
    d = d[np.isfinite(d["price"]) & (d["price"] > 0) & (d["price"] < 1_000_000)]
    by_sym: dict[str, float] = {}
    for sym, g in d.groupby("symbol"):
        g = g.sort_values("price")
        w = g["weight"].clip(lower=1e-9).to_numpy()
        cdf = np.cumsum(w) / w.sum()
        by_sym[str(sym)] = float(g["price"].to_numpy()[np.searchsorted(cdf, 0.5)])
    return by_addr, by_sym


def _pool_state(stamp: str) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for rec in _iter(_raw("uniswap_v3", "daily", stamp)) or []:
        pool_obj = rec.get("pool") or {}
        pool = pool_obj.get("id")
        tick = rec.get("tick")
        if not pool:
            continue
        pid = str(pool).lower()
        state: dict[str, object] = {}
        if tick not in (None, ""):
            try:
                state["tick"] = int(tick)
            except ValueError:
                pass
        state["feeTier"] = pool_obj.get("feeTier")
        state["token0"] = pool_obj.get("token0") or {}
        state["token1"] = pool_obj.get("token1") or {}
        out[pid] = state
    return out


def _day(stamp: str) -> pd.DataFrame:
    cache = CACHE / f"{stamp}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    prices, sym_prices = _prices(stamp)
    pool_state = _pool_state(stamp)
    rows = []
    for stream, sign in [("mints", 1.0), ("burns", -1.0)]:
        for rec in _iter(_raw("uniswap_v3", stream, stamp)) or []:
            pool = rec.get("pool") or {}
            state = pool_state.get(str(pool.get("id") or "").lower(), {})
            t0 = pool.get("token0") or state.get("token0") or {}
            t1 = pool.get("token1") or state.get("token1") or {}
            s0 = str(t0.get("symbol") or "")
            s1 = str(t1.get("symbol") or "")
            vehicles = [s for s in (s0, s1) if s in VEHICLES]
            if not vehicles:
                continue
            p0 = prices.get(str(t0.get("id") or "").lower()) or sym_prices.get(s0)
            p1 = prices.get(str(t1.get("id") or "").lower()) or sym_prices.get(s1)
            try:
                a0 = abs(float(rec.get("amount0") or 0.0))
                a1 = abs(float(rec.get("amount1") or 0.0))
                fee = int(pool.get("feeTier") or state.get("feeTier") or 3000)
                lower = int(rec.get("tickLower"))
                upper = int(rec.get("tickUpper"))
            except (TypeError, ValueError):
                continue
            usd = (a0 * p0 if p0 and np.isfinite(p0) else 0.0) + (a1 * p1 if p1 and np.isfinite(p1) else 0.0)
            # Imported historical mint/burn rows occasionally carry malformed
            # token metadata that makes symbol-level pricing explode. Keep the
            # mechanism test on economically plausible LP events rather than
            # letting a few bad rows dominate scaled regressors.
            if not np.isfinite(usd) or usd <= 0 or usd > 1_000_000_000:
                continue
            tick = state.get("tick")
            spacing = FEE_TO_SPACING.get(fee, 60)
            active = tick is not None and lower <= tick <= upper
            near = active and (upper - lower) <= 20 * spacing
            for vehicle in set(vehicles):
                rows.append({
                    "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
                    "token": vehicle,
                    "stream": stream,
                    "gross_usd": usd,
                    "signed_usd": sign * usd,
                    "active_signed_usd": sign * usd if active else 0.0,
                    "near_signed_usd": sign * usd if near else 0.0,
                    "near_gross_usd": usd if near else 0.0,
                })
    if rows:
        out = pd.DataFrame(rows).groupby(["date", "token"], as_index=False).agg(
            gross_reposition_usd=("gross_usd", "sum"),
            net_reposition_usd=("signed_usd", "sum"),
            active_net_reposition_usd=("active_signed_usd", "sum"),
            near_net_reposition_usd=("near_signed_usd", "sum"),
            near_gross_reposition_usd=("near_gross_usd", "sum"),
        )
    else:
        out = pd.DataFrame(columns=[
            "date", "token", "gross_reposition_usd", "net_reposition_usd",
            "active_net_reposition_usd", "near_net_reposition_usd", "near_gross_reposition_usd",
        ])
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def _cluster_ols(y: pd.Series, x: pd.Series, cluster: pd.Series) -> tuple[int, int, float, float, float, float]:
    d = pd.DataFrame({"y": y, "x": x, "cluster": cluster}).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    if n < 10 or c < 2 or np.isclose(float(d["x"].var()), 0):
        return n, c, math.nan, math.nan, math.nan, math.nan
    xmat = np.column_stack([np.ones(n), d["x"].to_numpy(float)])
    yy = d["y"].to_numpy(float)
    beta = np.linalg.lstsq(xmat, yy, rcond=None)[0]
    resid = yy - xmat @ beta
    bread = np.linalg.inv(xmat.T @ xmat)
    meat = np.zeros((2, 2))
    for _, idx in d.groupby("cluster").indices.items():
        score = xmat[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - xmat.shape[1], 1))
    cov = finite * bread @ meat @ bread
    se = float(math.sqrt(max(cov[1, 1], 0.0)))
    t = float(beta[1] / se) if se > 0 else math.nan
    p = float(2 * stats.t.sf(abs(t), c - 1)) if np.isfinite(t) else math.nan
    return n, c, float(beta[1]), se, t, p


def _demean_two(s: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    return s - s.groupby(a).transform("mean") - s.groupby(b).transform("mean") + s.mean()


def run() -> pd.DataFrame:
    stamps = sorted(p.stem for p in (DATA / "unified").glob("[0-9]" * 8 + ".parquet") if p.stem >= "20210505")
    frames = []
    for i, stamp in enumerate(stamps, 1):
        day = _day(stamp)
        if not day.empty:
            frames.append(day)
        if i % 100 == 0 or i == len(stamps):
            print(f"LP repositioning [{i}/{len(stamps)}] {stamp}", flush=True)
    rep = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    EMP.mkdir(parents=True, exist_ok=True)
    rep.to_pickle(EMP / "lp_repositioning_daily.pkl")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    d = rep.merge(lp[["date", "token", "total_lp_liquidity_usd"]], on=["date", "token"], how="left")
    d["date"] = pd.to_datetime(d["date"])
    bridge["date"] = pd.to_datetime(bridge["date"])
    d = d.merge(bridge, on=["date", "token"], how="left")
    d = d.sort_values(["token", "date"])
    denom = d["total_lp_liquidity_usd"].replace(0, np.nan)
    for col in ["net_reposition_usd", "active_net_reposition_usd", "near_net_reposition_usd", "near_gross_reposition_usd"]:
        d[f"{col}_share"] = (d[col] / denom).clip(lower=-5, upper=5)
    rows = []
    for horizon in [1, 7, 14, 30]:
        d[f"BridgeShare_t{horizon}"] = value_at_day_offset(
            d, "BridgeShare", horizon
        )
        y_raw = d[f"BridgeShare_t{horizon}"]
        for var in ["net_reposition_usd_share", "active_net_reposition_usd_share", "near_net_reposition_usd_share", "near_gross_reposition_usd_share"]:
            y = _demean_two(y_raw, d["token"], d["date"])
            x = _demean_two(d[var], d["token"], d["date"])
            n, clusters, beta, se, t, p = _cluster_ols(y, x, d["date"])
            rows.append({
                "Horizon (days)": horizon,
                "Regressor": var.replace("_usd_share", "").replace("_", " "),
                "N": _int(n),
                "Date clusters": _int(clusters),
                "Beta": _num(beta, 3),
                "SE": _num(se, 3),
                "t": _num(t, 2),
                "p": _p(p),
            })
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "lp_repositioning_tests.pkl")
    _write_table(
        out,
        "table_r13_lp_repositioning",
        "LP repositioning and subsequent vehicle use.",
        "tab:lp-repositioning",
        note=(
            "Regressions predict VehicleShare from lagged V3 mints/burns in vehicle-linked "
            "pools, scaled by vehicle-linked LP liquidity. Active ranges contain the daily "
            "pool tick; near ranges also have width no more than 20 tick spacings. "
            "Specifications include token and date fixed effects and cluster by date."
        ),
    )
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
