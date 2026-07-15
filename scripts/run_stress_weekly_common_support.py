#!/usr/bin/env python3
"""Weekly common-support WETH-versus-stable stress-rotation panel.

The hourly panel is noisy; this version aggregates the same endpoint-pair
opportunities over the event week and compares them with the same endpoint pair
over the prior four weeks.
"""
from __future__ import annotations

import argparse
import importlib.util
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
CACHE = DATA / "empirical" / "_stress_daily_pair_cache"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402


def _load_empirical_module():
    path = SCRIPTS / "run_empirical_proposition_tests.py"
    spec = importlib.util.spec_from_file_location("dvc_empirical", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stamp(d: pd.Timestamp) -> str:
    return d.strftime("%Y%m%d")


def _day_pair_vehicle(stamp: str, empirical_module) -> pd.DataFrame:
    cache = CACHE / f"{stamp}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    out = empirical_module._pair_vehicle_for_day(stamp)
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def _build_panel(stamps: set[str], empirical_module) -> pd.DataFrame:
    frames = []
    for i, stamp in enumerate(sorted(stamps), 1):
        day = _day_pair_vehicle(stamp, empirical_module)
        if not day.empty:
            frames.append(day)
        if i % 50 == 0 or i == len(stamps):
            print(f"weekly common-support cache [{i}/{len(stamps)}] {stamp}", flush=True)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    wide = panel.pivot_table(
        index=["date", "pair"],
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
    wide["date"] = pd.to_datetime(wide["date"])
    return wide


def _window_gap(panel: pd.DataFrame, start: pd.Timestamp, days: int) -> pd.DataFrame:
    end = start + pd.Timedelta(days=days)
    d = panel[(panel["date"] >= start) & (panel["date"] < end)]
    if d.empty:
        return pd.DataFrame(columns=["pair", "gap", "total", "days"])
    g = d.groupby("pair", as_index=False).agg(
        WETH=("WETH", "sum"),
        STABLE=("STABLE", "sum"),
        total=("total", "sum"),
        days=("date", "nunique"),
    )
    g = g[g["total"].gt(0)].copy()
    g["gap"] = (g["WETH"] - g["STABLE"]) / g["total"]
    return g[["pair", "gap", "total", "days"]]


def run(n_events: int, event_days: int, baseline_days: int) -> pd.DataFrame:
    empirical = _load_empirical_module()
    events = pd.read_pickle(EMP / "stress_common_support_events.pkl")
    events["event_date"] = pd.to_datetime(events["event_date"])
    events = events.sort_values("downside_stress", ascending=False).head(n_events)
    stamps: set[str] = set()
    for d in events["event_date"]:
        for k in range(event_days):
            stamps.add(_stamp(d + pd.Timedelta(days=k)))
        for b in range(1, baseline_days + 1):
            stamps.add(_stamp(d - pd.Timedelta(days=b)))

    panel = _build_panel(stamps, empirical)
    rows = []
    for ev in events.itertuples(index=False):
        d = pd.Timestamp(ev.event_date)
        event = _window_gap(panel, d, event_days).rename(
            columns={"gap": "event_gap", "total": "event_total", "days": "event_days_seen"}
        )
        base = _window_gap(panel, d - pd.Timedelta(days=baseline_days), baseline_days).rename(
            columns={"gap": "baseline_gap", "total": "baseline_total", "days": "baseline_days_seen"}
        )
        comp = event.merge(base, on="pair", how="inner")
        comp = comp[comp["baseline_days_seen"].ge(max(7, baseline_days // 3))]
        if comp.empty:
            continue
        comp["effect"] = comp["event_gap"] - comp["baseline_gap"]
        weights = comp["event_total"].clip(lower=1e-9)
        rows.append({
            "event_date": d.strftime("%Y-%m-%d"),
            "downside_stress": float(ev.downside_stress),
            "event_days": event_days,
            "baseline_days": baseline_days,
            "n_pairs": int(len(comp)),
            "weighted_effect": float(np.average(comp["effect"], weights=weights)),
            "mean_effect": float(comp["effect"].mean()),
        })

    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_pickle(EMP / "stress_weekly_common_support_events.pkl")
    if not out.empty:
        effect = out["weighted_effect"].to_numpy(float)
        t, p = stats.ttest_1samp(effect, 0.0)
        table = pd.DataFrame([{
            "Events": _int(len(effect)),
            "Event window": f"{event_days} days",
            "Baseline window": f"{baseline_days} days",
            "Mean pairs": _int(out["n_pairs"].mean()),
            "Effect (pp)": _num(100 * effect.mean(), 2),
            "SE (pp)": _num(100 * stats.sem(effect), 2),
            "t": _num(t, 2),
            "p": _p(p),
        }])
        _write_table(
            table,
            "table_r10_stress_weekly_common_support",
            "Weekly common-support stress rotation.",
            "tab:stress-weekly-common-support",
            note=(
                "For the largest WETH downside events, the outcome compares WETH-minus-stable "
                "BridgeShare over the event week with the same endpoint pair over the prior "
                "four weeks."
            ),
        )
    print(f"wrote {len(out):,} weekly stress events")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=20)
    ap.add_argument("--event-days", type=int, default=7)
    ap.add_argument("--baseline-days", type=int, default=28)
    args = ap.parse_args()
    run(args.events, args.event_days, args.baseline_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
