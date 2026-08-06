#!/usr/bin/env python3
"""Hourly quote-state robustness for V2-style route-cost counterfactuals.

The main route-cost panel quotes a common daily state. This robustness check
compares that daily-state benchmark with the realized route hour for the same
endpoint-pair/vehicle observations, using V2/Sushi V2 hourly reserves. It is a
pre-trade state robustness for constant-product pools, not an exact V3 event
replay.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.prices import day_prices

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402
from run_route_cost_panel import (  # noqa: E402
    VEHICLE_BY_ADDRESS,
    _best_quote,
    _load_v2_pools,
)


def _component_vehicle_hours(stamp: str) -> pd.DataFrame:
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return pd.DataFrame()
    cols = [
        "tx_hash", "component_id", "route_class", "token_in", "token_out",
        "token_in_sym", "token_out_sym", "amount_usd", "tin_role", "tout_role",
        "timestamp_utc",
    ]
    legs = pd.read_parquet(path, columns=cols)
    legs = legs[legs["route_class"].isin(["single", "coherent"])].copy()
    if legs.empty:
        return pd.DataFrame()
    keys = ["tx_hash", "component_id"]
    left = legs[keys + ["token_in", "token_in_sym", "tin_role"]].rename(
        columns={"token_in": "token", "token_in_sym": "symbol", "tin_role": "role"}
    )
    right = legs[keys + ["token_out", "token_out_sym", "tout_role"]].rename(
        columns={"token_out": "token", "token_out_sym": "symbol", "tout_role": "role"}
    )
    roles = pd.concat([left, right], ignore_index=True)
    roles["token"] = roles["token"].str.lower()
    sources = roles[roles["role"].eq("source")].drop_duplicates(keys + ["token"]).rename(columns={"token": "src"})
    sinks = roles[roles["role"].eq("sink")].drop_duplicates(keys + ["token"]).rename(columns={"token": "tgt"})
    inter = roles[roles["role"].eq("intermediate")].drop_duplicates(keys + ["token"]).rename(columns={"token": "vehicle"})
    vol = legs.groupby(keys, as_index=False).agg(
        volume=("amount_usd", "mean"),
        hour=("timestamp_utc", lambda s: int(pd.to_numeric(s, errors="coerce").median() // 3600 % 24)),
    )
    comp = sources[keys + ["src"]].merge(sinks[keys + ["tgt"]], on=keys).merge(
        inter[keys + ["vehicle"]], on=keys
    ).merge(vol, on=keys)
    comp = comp[comp["src"].ne(comp["tgt"]) & comp["vehicle"].isin(VEHICLE_BY_ADDRESS.keys())]
    if comp.empty:
        return pd.DataFrame()
    return (
        comp.groupby(["src", "tgt", "vehicle", "hour"], as_index=False)["volume"].sum()
        .sort_values("volume", ascending=False)
    )


def _quote_direct_cost_advantage(
    row: pd.Series, pools: dict, prices: dict[str, tuple[str, float]]
) -> float:
    src = str(row["src"]).lower()
    tgt = str(row["tgt"]).lower()
    vehicle = str(row["vehicle"]).lower()
    src_price = prices.get(src, (None, math.nan))[1]
    tgt_price = prices.get(tgt, (None, math.nan))[1]
    if not (src_price and tgt_price and src_price > 0 and tgt_price > 0):
        return math.nan
    amount_in = float(row["trade_size_usd"]) / float(src_price)
    direct, _, _ = _best_quote(pools, src, tgt, amount_in)
    hop1, _, _ = _best_quote(pools, src, vehicle, amount_in)
    if hop1 <= 0:
        return math.nan
    hop2, _, _ = _best_quote(pools, vehicle, tgt, hop1)
    if direct <= 0 or hop2 <= 0:
        return math.nan
    direct_usd = direct * float(tgt_price)
    vehicle_usd = hop2 * float(tgt_price)
    return (direct_usd - vehicle_usd) / direct_usd


def _canonicalize_cached_output(out: pd.DataFrame) -> pd.DataFrame:
    legacy = {
        "daily_state_advantage_bps": "daily_state_direct_cost_advantage",
        "route_hour_advantage_bps": "route_hour_direct_cost_advantage",
        "difference_bps": "direct_cost_advantage_difference",
    }
    if not set(legacy).intersection(out.columns):
        return out
    converted = out.copy()
    for old, new in legacy.items():
        if old in converted.columns:
            converted[new] = -pd.to_numeric(converted[old], errors="coerce") / 10_000.0
    return converted.drop(columns=list(legacy), errors="ignore")


def _write_summary(out: pd.DataFrame) -> pd.DataFrame:
    table_rows = []
    for size, g in out.groupby("trade_size_usd"):
        d = g.copy()
        for col in [
            "daily_state_direct_cost_advantage",
            "route_hour_direct_cost_advantage",
            "direct_cost_advantage_difference",
        ]:
            d[f"{col}_w"] = d[col].clip(-10, 10)
        diff = d["direct_cost_advantage_difference_w"].to_numpy(float)
        t, p = stats.ttest_1samp(diff, 0.0) if len(diff) > 2 and float(np.std(diff)) > 0 else (math.nan, math.nan)
        corr = (
            float(
                d[
                    [
                        "daily_state_direct_cost_advantage_w",
                        "route_hour_direct_cost_advantage_w",
                    ]
                ].corr().iloc[0, 1]
            )
            if len(d) > 2
            else math.nan
        )
        same_sign = float(
            np.mean(
                np.sign(d["daily_state_direct_cost_advantage_w"])
                == np.sign(d["route_hour_direct_cost_advantage_w"])
            )
        )
        table_rows.append({
            "Trade size": f"${int(size):,}",
            "Rows": _int(len(d)),
            "Median daily-state direct cost advantage (fraction)": _num(
                d["daily_state_direct_cost_advantage"].median(), 4
            ),
            "Median route-hour direct cost advantage (fraction)": _num(
                d["route_hour_direct_cost_advantage"].median(), 4
            ),
            "Median difference (fraction)": _num(
                d["direct_cost_advantage_difference"].median(), 4
            ),
            "Clipped mean difference (fraction)": _num(np.mean(diff), 4),
            "t": _num(t, 2),
            "p": _p(p),
            "Same-sign share (%)": _num(100 * same_sign, 1),
            "Winsor correlation": _num(corr, 3),
        })
    table = pd.DataFrame(table_rows)
    _write_table(
        table,
        "table_r09_transaction_time_quote_state",
        "Hourly quote-state robustness for direct cost advantage against WETH routes.",
        "tab:transaction-time-quote-state",
        note=(
            "The robustness compares the daily-state V2/Sushi V2 counterfactual with a quote "
            "at the realized route hour for the same endpoint pair, WETH vehicle, and trade "
            "size. The table reports medians and winsorized mean differences because hourly "
            "constant-product reserves have extreme thin-pool tails. It is an hourly "
            "constant-product pre-trade-state check, not an exact V3 transaction replay."
        ),
    )
    return table


def run(max_days: int | None = None, force: bool = False) -> pd.DataFrame:
    out_path = EMP / "transaction_time_quote_robustness.pkl"
    if out_path.exists() and not force and max_days is None:
        out = pd.read_pickle(out_path)
        migrated = any(str(col).endswith("_bps") for col in out.columns)
        out = _canonicalize_cached_output(out)
        if migrated:
            out.to_pickle(out_path)
        _write_summary(out)
        print(f"reused {len(out):,} rows -> {out_path}")
        return out
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    panel = panel[
        panel["vehicle_sym"].eq("WETH")
        & panel["direct_available"]
        & panel["vehicle_available"]
        & panel["direct_cost_advantage"].notna()
    ].copy()
    panel["stamp"] = panel["date"].str.replace("-", "", regex=False)
    panel["vehicle"] = panel["vehicle"].str.lower()
    stamps = sorted(panel["stamp"].unique())
    if max_days:
        stamps = stamps[-max_days:]
    rows = []
    for i, stamp in enumerate(stamps, 1):
        day_rows = panel[panel["stamp"].eq(stamp)]
        route_hours = _component_vehicle_hours(stamp)
        if route_hours.empty:
            continue
        top_hour = (
            route_hours.groupby(["src", "tgt", "vehicle"], as_index=False)
            .first()[["src", "tgt", "vehicle", "hour"]]
        )
        d = day_rows.merge(top_hour, on=["src", "tgt", "vehicle"], how="inner")
        if d.empty:
            continue
        unified = pd.read_parquet(DATA / "unified" / f"{stamp}.parquet", columns=[
            "token_in", "token_out", "token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd"
        ])
        prices = day_prices(unified)
        noon = _load_v2_pools(stamp, 12)
        by_hour = {int(h): _load_v2_pools(stamp, int(h)) for h in sorted(d["hour"].dropna().unique())}
        for r in d.itertuples(index=False):
            base = pd.Series(r._asdict())
            adv_noon = _quote_direct_cost_advantage(base, noon, prices)
            adv_hour = _quote_direct_cost_advantage(
                base, by_hour.get(int(base["hour"]), {}), prices
            )
            if np.isfinite(adv_noon) and np.isfinite(adv_hour):
                rows.append({
                    "date": base["date"],
                    "src": base["src"],
                    "tgt": base["tgt"],
                    "trade_size_usd": float(base["trade_size_usd"]),
                    "route_hour_utc": int(base["hour"]),
                    "daily_state_direct_cost_advantage": adv_noon,
                    "route_hour_direct_cost_advantage": adv_hour,
                    "direct_cost_advantage_difference": adv_hour - adv_noon,
                })
        if i % 100 == 0 or i == len(stamps):
            print(f"transaction-time robustness [{i}/{len(stamps)}] {stamp}", flush=True)
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_pickle(out_path)
    _write_summary(out)
    print(f"wrote {len(out):,} rows -> {out_path}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-days", type=int, default=None)
    args = ap.parse_args()
    run(max_days=args.max_days, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
