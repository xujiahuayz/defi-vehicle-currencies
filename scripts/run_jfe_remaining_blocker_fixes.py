#!/usr/bin/env python3
"""Remaining JFE pre-write blocker fixes.

This pass produces paper-facing tables for the issues the third independent
review still treated as blockers:

1. exact stress-event definition and event table;
2. Curve/Fluid materiality and stablecoin-heavy coverage limitation;
3. one-row-per-proposition main-test registry with economic magnitudes.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import exact_daily_log_return

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _pct, _write_table


STABLES = {"USDC", "USDT", "DAI", "USDE", "SUSDE", "FRAX", "LUSD", "PYUSD", "USDP", "GUSD"}


def _load_module(name: str, file: str):
    path = SCRIPTS / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _iter_jsonl_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def stress_event_definition_table() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)

    events = pd.read_pickle(EMP / "stress_rotation_decomposition_events.pkl")
    events["event_date"] = pd.to_datetime(events["event_date"])
    events = events.sort_values("downside_stress", ascending=False).reset_index(drop=True)
    all_threshold = px[px["downside_stress"].ge(0.08)][["date", "downside_stress"]].copy()
    selected = set(events["event_date"])
    rows = []
    sorted_dates = list(events["event_date"])
    for i, r in events.iterrows():
        d = pd.Timestamp(r["event_date"])
        prev_gap = min((abs((d - od).days) for od in sorted_dates if od < d), default=math.nan)
        next_gap = min((abs((od - d).days) for od in sorted_dates if od > d), default=math.nan)
        rows.append(
            {
                "Rank": i + 1,
                "Event date": d.strftime("%Y-%m-%d"),
                "WETH return (%)": _pct(-float(r["downside_stress"])),
                "Threshold met": "yes" if float(r["downside_stress"]) >= 0.08 else "no",
                "Pairs": _int(r["n_pairs"]),
                "WETH effect (pp)": _num(100 * float(r["weth_effect"]), 2),
                "Stable effect (pp)": _num(100 * float(r["stable_effect"]), 2),
                "Gap effect (pp)": _num(100 * float(r["gap_effect"]), 2),
                "Direct-route effect (pp)": _num(100 * float(r["direct_route_share_effect"]), 2),
                "Nearest selected event (days)": _int(np.nanmin([prev_gap, next_gap])),
                "Overlaps 14d window": "yes" if np.nanmin([prev_gap, next_gap]) <= 14 else "no",
            }
        )
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "stress_event_definition.pkl")
    _write_table(
        out.head(20),
        "table_r21_stress_event_definition",
        "Stress-event definition and event-level decomposition.",
        "tab:stress-event-definition",
        note=(
            "Stress events are the top 20 WETH downside days among days with an 8 percent "
            "or larger negative WETH log return after dropping absolute daily returns above "
            "50 percent as price-construction outliers. Baseline windows use the prior 28 days; "
            "the overlap column flags selected events whose baseline/event windows may overlap."
        ),
    )

    summary = pd.DataFrame(
        [
            {
                "Definition": "Candidate threshold",
                "Value": "WETH downside log return >= 8%",
            },
            {
                "Definition": "Candidate event days",
                "Value": _int(len(all_threshold)),
            },
            {
                "Definition": "Selected event days",
                "Value": _int(len(events)),
            },
            {
                "Definition": "Events with another selected event within 14 days",
                "Value": _int(out["Overlaps 14d window"].eq("yes").sum()),
            },
            {
                "Definition": "Baseline window",
                "Value": "prior 28 calendar days",
            },
        ]
    )
    _write_table(
        summary,
        "table_r22_stress_design_summary",
        "Stress-event design summary.",
        "tab:stress-design-summary",
    )
    summary.to_pickle(EMP / "stress_design_summary.pkl")
    return out


def stress_threshold_overlap_sensitivity() -> pd.DataFrame:
    weekly = _load_module("stress_weekly_for_sensitivity", "run_stress_weekly_common_support.py")
    empirical = weekly._load_empirical_module()
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)

    candidate_sets: list[tuple[str, pd.DataFrame]] = []
    for threshold in [0.06, 0.08, 0.10, 0.12]:
        cand = px[px["downside_stress"].ge(threshold)][["date", "downside_stress"]].copy()
        candidate_sets.append((f"all events, threshold {int(threshold * 100)}%", cand))
    top20 = px[px["downside_stress"].ge(0.08)].nlargest(20, "downside_stress")[["date", "downside_stress"]]
    candidate_sets.append(("top 20, threshold 8%", top20))
    greedy = []
    for r in px[px["downside_stress"].ge(0.08)].sort_values("downside_stress", ascending=False).itertuples(index=False):
        d = pd.Timestamp(r.date)
        if all(abs((d - pd.Timestamp(x.date)).days) > 14 for x in greedy):
            greedy.append(r)
    nonoverlap = pd.DataFrame({"date": [x.date for x in greedy], "downside_stress": [x.downside_stress for x in greedy]})
    candidate_sets.append(("non-overlap, threshold 8%", nonoverlap))

    stamps: set[str] = set()
    for _, events in candidate_sets:
        for d in events["date"]:
            d = pd.Timestamp(d)
            stamps.add(weekly._stamp(d))
            for b in range(1, 29):
                stamps.add(weekly._stamp(d - pd.Timedelta(days=b)))
    panel = weekly._build_panel(stamps, empirical)

    rows = []
    for label, events in candidate_sets:
        effects = []
        pairs = []
        for ev in events.itertuples(index=False):
            d = pd.Timestamp(ev.date)
            raw_event = panel[(panel["date"] >= d) & (panel["date"] < d + pd.Timedelta(days=1))]
            raw_base = panel[(panel["date"] >= d - pd.Timedelta(days=28)) & (panel["date"] < d)]
            ev_pair = raw_event.groupby("pair", as_index=False).agg(WETH_e=("WETH", "sum"), STABLE_e=("STABLE", "sum"), total_e=("total", "sum"))
            ba_pair = raw_base.groupby("pair", as_index=False).agg(WETH_b=("WETH", "sum"), STABLE_b=("STABLE", "sum"), total_b=("total", "sum"), days_b=("date", "nunique"))
            comp = ev_pair.merge(ba_pair, on="pair", how="inner")
            comp = comp[(comp["total_e"].gt(0)) & (comp["total_b"].gt(0)) & comp["days_b"].ge(7)]
            if comp.empty:
                continue
            comp["weth_effect"] = comp["WETH_e"] / comp["total_e"] - comp["WETH_b"] / comp["total_b"]
            comp["stable_effect"] = comp["STABLE_e"] / comp["total_e"] - comp["STABLE_b"] / comp["total_b"]
            comp["gap_effect"] = comp["weth_effect"] - comp["stable_effect"]
            weights = comp["total_e"].clip(lower=1e-9)
            effects.append(float(np.average(comp["gap_effect"], weights=weights)))
            pairs.append(len(comp))
        arr = np.array(effects, dtype=float)
        if len(arr) > 2:
            from scipy import stats

            t, p = stats.ttest_1samp(arr, 0.0)
            se = stats.sem(arr)
        else:
            t = p = se = math.nan
        rows.append(
            {
                "Event set": label,
                "Events": _int(len(arr)),
                "Mean pairs": _int(np.mean(pairs) if pairs else math.nan),
                "Gap effect (pp)": _num(100 * arr.mean(), 2) if len(arr) else "",
                "SE (pp)": _num(100 * se, 2),
                "t": _num(t, 2),
                "p": _p(p),
                "Negative share (%)": _pct(float(np.mean(arr < 0)) if len(arr) else math.nan),
            }
        )
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "stress_threshold_overlap_sensitivity.pkl")
    _write_table(
        out,
        "table_r26_stress_threshold_overlap_sensitivity",
        "Stress-rotation sensitivity to thresholds and overlapping events.",
        "tab:stress-threshold-overlap",
        note=(
            "Outcome is same-day WETH-minus-stable BridgeShare change within common "
            "endpoint-pair sets relative to the prior 28 days. Non-overlap greedily keeps "
            "the largest downside events more than 14 days apart."
        ),
    )
    return out


def curve_fluid_materiality() -> pd.DataFrame:
    """Quantify excluded exact-quote venues by volume and stablecoin intensity."""
    rows = []
    files = sorted((DATA / "unified").glob("[0-9]" * 8 + ".parquet"))
    for i, path in enumerate(files, 1):
        d = pd.read_parquet(path, columns=["source", "amount_usd", "token_in_sym", "token_out_sym", "tx_hash"])
        d["token_in_u"] = d["token_in_sym"].astype(str).str.upper()
        d["token_out_u"] = d["token_out_sym"].astype(str).str.upper()
        d["stable_leg"] = d["token_in_u"].isin(STABLES) | d["token_out_u"].isin(STABLES)
        d["weth_leg"] = d["token_in_u"].isin({"ETH", "WETH"}) | d["token_out_u"].isin({"ETH", "WETH"})
        g = d.groupby("source", as_index=False).agg(
            leg_volume_usd=("amount_usd", "sum"),
            legs=("amount_usd", "size"),
            transactions=("tx_hash", "nunique"),
            stable_leg_volume_usd=("amount_usd", lambda s: float(s[d.loc[s.index, "stable_leg"]].sum())),
            weth_leg_volume_usd=("amount_usd", lambda s: float(s[d.loc[s.index, "weth_leg"]].sum())),
        )
        rows.append(g)
        if i % 500 == 0 or i == len(files):
            print(f"Curve/Fluid materiality scan [{i}/{len(files)}] {path.stem}", flush=True)
    source = pd.concat(rows, ignore_index=True).groupby("source", as_index=False).sum(numeric_only=True)
    total = float(source["leg_volume_usd"].sum())
    source["exact_quote_status"] = source["source"].map(
        {
            "curve": "excluded exact quote",
            "fluid": "excluded exact quote",
            "balancer": "weighted pools quoteable",
            "uniswap_v1": "covered/Graph",
            "uniswap_v2": "covered exact CP",
            "uniswap_v3": "covered exact tick",
            "uniswap_v4": "covered settlement only",
            "sushiswap_v2": "covered exact CP",
            "sushiswap_v3": "covered raw; not main quoter",
        }
    ).fillna("other")
    keep = source[source["source"].isin(["curve", "fluid", "balancer", "uniswap_v2", "uniswap_v3", "sushiswap_v2"])].copy()
    out = pd.DataFrame(
        [
            {
                "Source": r.source,
                "Volume share (%)": _pct(r.leg_volume_usd / total if total else math.nan),
                "Legs": _int(r.legs),
                "Transactions": _int(r.transactions),
                "Stable-leg share (%)": _pct(r.stable_leg_volume_usd / r.leg_volume_usd if r.leg_volume_usd else math.nan),
                "ETH/WETH-leg share (%)": _pct(r.weth_leg_volume_usd / r.leg_volume_usd if r.leg_volume_usd else math.nan),
                "Exact-quote status": r.exact_quote_status,
            }
            for r in keep.sort_values("leg_volume_usd", ascending=False).itertuples(index=False)
        ]
    )
    out.to_pickle(EMP / "curve_fluid_materiality.pkl")
    _write_table(
        out,
        "table_r23_curve_fluid_materiality",
        "Materiality of exact-quote coverage limits.",
        "tab:curve-fluid-materiality",
        note=(
            "Volume shares are measured from unified swap legs. Stable-leg share is the "
            "fraction of source volume where either side of a leg is a major stablecoin. "
            "Curve and Fluid are excluded from exact executable-depth quotes in the current "
            "route-cost panel, so this table bounds the coverage limitation."
        ),
    )
    return out


def curve_fluid_scope_bound() -> pd.DataFrame:
    mat = pd.read_pickle(EMP / "curve_fluid_materiality.pkl")
    def pct_to_float(x: object) -> float:
        try:
            return float(str(x).replace(",", ""))
        except ValueError:
            return math.nan

    mat["volume_share"] = mat["Volume share (%)"].map(pct_to_float)
    quoteable = mat[mat["Exact-quote status"].str.contains("covered|quoteable", case=False, na=False)]
    excluded = mat[mat["Exact-quote status"].str.contains("excluded", case=False, na=False)]
    qshare = float(quoteable["volume_share"].sum())
    eshare = float(excluded["volume_share"].sum())
    stable_weighted = float(
        np.average(
            excluded["Stable-leg share (%)"].map(pct_to_float),
            weights=excluded["volume_share"].clip(lower=1e-9),
        )
    )
    rows = [
        {
            "Quantity": "Exact-quote covered share",
            "Value": _num(qshare, 1),
            "Interpretation": "Unified leg-volume share covered by V2/Sushi V2/V3 plus Balancer weighted quote extension",
        },
        {
            "Quantity": "Excluded Curve+Fluid share",
            "Value": _num(eshare, 1),
            "Interpretation": "Unified leg-volume share not covered by exact executable-depth quotes",
        },
        {
            "Quantity": "Excluded / covered ratio",
            "Value": _num(eshare / qshare, 3) if qshare else "",
            "Interpretation": "Maximum exact-quote scope exposure relative to covered quoteable venues",
        },
        {
            "Quantity": "Excluded stable-leg share",
            "Value": _num(stable_weighted, 1),
            "Interpretation": "Excluded venues are stablecoin-heavy, so route-cost claims must be scoped",
        },
    ]
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "curve_fluid_scope_bound.pkl")
    _write_table(
        out,
        "table_r28_curve_fluid_scope_bound",
        "Scope bound for Curve and Fluid exact-quote exclusion.",
        "tab:curve-fluid-scope-bound",
        note=(
            "This table does not impute unobserved Curve/Fluid executable-depth quotes. It "
            "bounds the scope of the route-cost panel by comparing excluded stablecoin-heavy "
            "venue volume with exact-quote-covered venue volume."
        ),
    )
    return out


def main() -> int:
    EMP.mkdir(parents=True, exist_ok=True)
    stress_event_definition_table()
    stress_threshold_overlap_sensitivity()
    curve_fluid_materiality()
    curve_fluid_scope_bound()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
