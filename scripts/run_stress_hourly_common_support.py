#!/usr/bin/env python3
"""Hourly common-support WETH-versus-stable stress-rotation panel.

This builds the high-frequency version of the daily common-support design:
for the largest WETH downside days, compare hourly WETH-minus-stable bridge use
against the same endpoint-pair/hour-of-day baseline over the prior 14 days.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
CACHE = DATA / "empirical" / "_stress_hourly_cache"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402

STABLES = {"USDC", "USDT", "DAI"}
CLEAN_ROUTE_CLASSES = {"single", "coherent"}


def _date_to_stamp(d: pd.Timestamp) -> str:
    return d.strftime("%Y%m%d")


def _cache_path(stamp: str) -> Path:
    return CACHE / f"{stamp}.parquet"


def _unique_tuple(s: pd.Series) -> tuple[str, ...]:
    return tuple(x for x in pd.unique(s.dropna().astype(str)) if x)


def day_hourly_pair_vehicle(stamp: str) -> pd.DataFrame:
    cache = _cache_path(stamp)
    if cache.exists():
        return pd.read_parquet(cache)
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["hour", "pair", "vehicle_group", "volume"])
    cols = [
        "tx_hash", "component_id", "route_class", "token_in_sym", "token_out_sym",
        "amount_usd", "tin_role", "tout_role", "timestamp_utc",
    ]
    legs = pd.read_parquet(path, columns=cols)
    legs = legs[legs["route_class"].isin(CLEAN_ROUTE_CLASSES)].copy()
    if legs.empty:
        out = pd.DataFrame(columns=["hour", "pair", "vehicle_group", "volume"])
        cache.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(cache, index=False)
        return out
    legs["hour"] = (pd.to_numeric(legs["timestamp_utc"], errors="coerce") // 3600).astype("Int64")
    legs = legs.dropna(subset=["hour", "amount_usd"])
    keys = ["hour", "tx_hash", "component_id"]

    left = legs[keys + ["token_in_sym", "tin_role"]].rename(columns={"token_in_sym": "token", "tin_role": "role"})
    right = legs[keys + ["token_out_sym", "tout_role"]].rename(columns={"token_out_sym": "token", "tout_role": "role"})
    roles = pd.concat([left, right], ignore_index=True)
    roles["token"] = roles["token"].astype(str)

    src = roles[roles["role"].eq("source")].groupby(keys)["token"].agg(_unique_tuple).rename("sources")
    sink = roles[roles["role"].eq("sink")].groupby(keys)["token"].agg(_unique_tuple).rename("sinks")
    inter = roles[roles["role"].eq("intermediate")].groupby(keys)["token"].agg(_unique_tuple).rename("inter")
    vol = pd.to_numeric(legs["amount_usd"], errors="coerce").groupby([legs[k] for k in keys]).mean().rename("volume")
    comp = pd.concat([src, sink, inter, vol], axis=1).dropna(subset=["sources", "sinks", "inter", "volume"]).reset_index()

    rows = []
    for r in comp.itertuples(index=False):
        if not math.isfinite(float(r.volume)) or float(r.volume) <= 0:
            continue
        pairs = [(s, t) for s in r.sources for t in r.sinks if s != t]
        if not pairs:
            continue
        per = float(r.volume) / len(pairs)
        groups = []
        for token in r.inter:
            if token == "WETH":
                groups.append("WETH")
            elif token in STABLES:
                groups.append("STABLE")
        if not groups:
            continue
        for s, t in pairs:
            pair = f"{s}->{t}"
            for group in set(groups):
                rows.append((int(r.hour), pair, group, per))
    out = pd.DataFrame(rows, columns=["hour", "pair", "vehicle_group", "volume"])
    if not out.empty:
        out = out.groupby(["hour", "pair", "vehicle_group"], as_index=False)["volume"].sum()
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def build_panel(stamps: set[str]) -> pd.DataFrame:
    frames = []
    for i, stamp in enumerate(sorted(stamps), 1):
        day = day_hourly_pair_vehicle(stamp)
        if not day.empty:
            frames.append(day)
        if i % 10 == 0 or i == len(stamps):
            print(f"hourly common-support cache [{i}/{len(stamps)}] {stamp}", flush=True)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    wide = panel.pivot_table(
        index=["hour", "pair"],
        columns="vehicle_group",
        values="volume",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for col in ["WETH", "STABLE"]:
        if col not in wide:
            wide[col] = 0.0
    wide["total"] = wide["WETH"] + wide["STABLE"]
    wide = wide[wide["total"].gt(0)].copy()
    wide["gap"] = (wide["WETH"] - wide["STABLE"]) / wide["total"]
    # `hour` is an epoch-hour bucket. Convert back to an epoch-second timestamp
    # before matching event dates and hour-of-day baselines.
    wide["dt"] = pd.to_datetime(wide["hour"] * 3600, unit="s", utc=True)
    wide["hod"] = wide["dt"].dt.hour
    wide["stamp"] = wide["dt"].dt.strftime("%Y%m%d")
    return wide


def run(n_events: int, baseline_days: int) -> pd.DataFrame:
    events = pd.read_csv(EMP / "stress_common_support_events.csv")
    events["event_date"] = pd.to_datetime(events["event_date"])
    events = events.sort_values("downside_stress", ascending=False).head(n_events)
    stamps: set[str] = set()
    for d in events["event_date"]:
        stamps.add(_date_to_stamp(d))
        for b in range(1, baseline_days + 1):
            stamps.add(_date_to_stamp(d - pd.Timedelta(days=b)))
    panel = build_panel(stamps)
    rows = []
    for ev in events.itertuples(index=False):
        d = pd.Timestamp(ev.event_date)
        stamp = _date_to_stamp(d)
        event = panel[panel["stamp"].eq(stamp)]
        start = d.tz_localize("UTC") - pd.Timedelta(days=baseline_days)
        end = d.tz_localize("UTC")
        base = panel[(panel["dt"] >= start) & (panel["dt"] < end)]
        if event.empty or base.empty:
            continue
        base_pair = base.groupby(["pair", "hod"], as_index=False).agg(
            base_gap=("gap", "mean"),
            base_hours=("hour", "nunique"),
        )
        comp = event.merge(base_pair, on=["pair", "hod"], how="inner")
        comp = comp[comp["base_hours"].ge(max(3, baseline_days // 3))]
        if comp.empty:
            continue
        comp["effect"] = comp["gap"] - comp["base_gap"]
        rows.append({
            "event_date": stamp,
            "downside_stress": float(ev.downside_stress),
            "hours": int(comp["hour"].nunique()),
            "pair_hours": int(len(comp)),
            "weighted_effect": float(np.average(comp["effect"], weights=comp["total"].clip(lower=1e-9))),
            "mean_effect": float(comp["effect"].mean()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "stress_hourly_common_support_events.csv", index=False)
    if not out.empty:
        effect = out["weighted_effect"].to_numpy(float)
        t, p = stats.ttest_1samp(effect, 0.0)
        table = pd.DataFrame([{
            "Events": _int(len(effect)),
            "Mean hours": _num(out["hours"].mean(), 1),
            "Mean pair-hours": _int(out["pair_hours"].mean()),
            "Effect (pp)": _num(100 * effect.mean(), 2),
            "SE (pp)": _num(100 * stats.sem(effect), 2),
            "t": _num(t, 2),
            "p": _p(p),
        }])
        _write_table(
            table,
            "table_r07_stress_hourly_common_support",
            "Hourly common-support stress rotation.",
            "tab:stress-hourly-common-support",
            note=(
                "For the largest WETH downside events, the outcome compares hourly WETH-minus-stable "
                "BridgeShare with the same endpoint pair and hour-of-day over the prior 14 days."
            ),
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=20)
    ap.add_argument("--baseline-days", type=int, default=14)
    args = ap.parse_args()
    out = run(args.events, args.baseline_days)
    print(f"wrote {len(out):,} hourly stress events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
