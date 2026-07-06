#!/usr/bin/env python3
"""Remaining JFE pre-write blocker fixes.

This pass produces paper-facing tables for the issues the third independent
review still treated as blockers:

1. exact stress-event definition and event table;
2. Curve/Fluid materiality and stablecoin-heavy coverage limitation;
3. manual V4 no-transfer audit against receipt transfers for source/sink/vehicle;
4. one-row-per-proposition main-test registry with economic magnitudes.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _pct, _write_table  # noqa: E402


STABLES = {"USDC", "USDT", "DAI", "USDE", "SUSDE", "FRAX", "LUSD", "PYUSD", "USDP", "GUSD"}
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _load_module(name: str, file: str):
    path = SCRIPTS / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bool(v: Any) -> bool:
    return str(v).lower() in {"true", "1", "yes"}


def _iter_jsonl_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def stress_event_definition_table() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = np.log(px["weth_price"]).diff()
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)

    events = pd.read_csv(EMP / "stress_rotation_decomposition_events.csv")
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
    out.to_csv(EMP / "stress_event_definition_table.csv", index=False)
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
    summary.to_csv(EMP / "stress_design_summary.csv", index=False)
    return out


def stress_threshold_overlap_sensitivity() -> pd.DataFrame:
    weekly = _load_module("stress_weekly_for_sensitivity", "run_stress_weekly_common_support.py")
    empirical = weekly._load_empirical_module()
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = np.log(px["weth_price"]).diff()
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
    out.to_csv(EMP / "stress_threshold_overlap_sensitivity.csv", index=False)
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
    out.to_csv(EMP / "curve_fluid_materiality.csv", index=False)
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
    mat = pd.read_csv(EMP / "curve_fluid_materiality.csv")
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
    out.to_csv(EMP / "curve_fluid_scope_bound.csv", index=False)
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


def _load_receipts() -> dict[str, dict[str, Any] | None]:
    module = _load_module("v4_settlement_for_audit", "run_v4_settlement_identification.py")
    return module._load_receipt_cache()


def _transfer_count(receipt: dict[str, Any] | None, token: str) -> int:
    if not isinstance(receipt, dict) or not token:
        return 0
    token = token.lower()
    return sum(
        1
        for lg in receipt.get("logs", [])
        if str(lg.get("address", "")).lower() == token
        and lg.get("topics")
        and str(lg["topics"][0]).lower() == TRANSFER_TOPIC
    )


def _route_tokens_for_sample(row: pd.Series) -> dict[str, tuple[str, str]]:
    stamp = str(row["date"]).replace("-", "")
    path = DATA / "unified" / f"{stamp}.parquet"
    d = pd.read_parquet(
        path,
        columns=[
            "tx_hash",
            "component_id",
            "source",
            "token_in",
            "token_out",
            "token_in_sym",
            "token_out_sym",
            "tin_role",
            "tout_role",
        ],
    )
    g = d[
        d["tx_hash"].astype(str).str.lower().eq(str(row["tx_hash"]).lower())
        & d["component_id"].eq(int(row["component_id"]))
        & d["source"].eq(str(row["dex"]))
    ]
    roles: dict[str, tuple[str, str]] = {}
    for r in g.itertuples(index=False):
        for addr, sym, role in [
            (r.token_in, r.token_in_sym, r.tin_role),
            (r.token_out, r.token_out_sym, r.tout_role),
        ]:
            role = str(role)
            if role in {"source", "sink", "intermediate"} and role not in roles:
                roles[role] = (str(addr).lower(), str(sym))
    return roles


def v4_manual_no_transfer_audit() -> pd.DataFrame:
    detail = pd.read_csv(DATA / "empirical" / "v4_settlement_transfer_detail.csv")
    sample = pd.read_csv(DATA / "empirical" / "v4_settlement_sample.csv")
    d = detail.merge(
        sample[["date", "dex", "tx_hash", "component_id"]],
        on=["dex", "tx_hash", "component_id"],
        how="left",
    )
    d["has_matching_transfer"] = d["has_matching_transfer"].map(_bool)
    d["receipt_found"] = d["receipt_found"].map(_bool)
    audit = d[d["dex"].eq("uniswap_v4") & d["receipt_found"] & (~d["has_matching_transfer"])].copy()
    receipts = _load_receipts()
    rows = []
    for r in audit.itertuples(index=False):
        row = pd.Series(r._asdict())
        roles = _route_tokens_for_sample(row)
        receipt = receipts.get(str(row["tx_hash"]).lower())
        src_addr, src_sym = roles.get("source", ("", str(row["src"])))
        sink_addr, sink_sym = roles.get("sink", ("", str(row["sink"])))
        int_addr, int_sym = str(row["vehicle_id"]).lower(), str(row["vehicle"])
        rows.append(
            {
                "tx_hash": row["tx_hash"],
                "date": row["date"],
                "route": f"{src_sym}->{int_sym}->{sink_sym}",
                "route_usd": float(row["route_usd"]),
                "source_transfer_logs": _transfer_count(receipt, src_addr),
                "sink_transfer_logs": _transfer_count(receipt, sink_addr),
                "intermediate_transfer_logs": _transfer_count(receipt, int_addr),
                "total_logs": int(row["total_logs"]),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "v4_no_transfer_manual_audit_enriched.csv", index=False)

    summary = pd.DataFrame(
        [
            {
                "Audit check": "No-transfer sample size",
                "N": _int(len(out)),
                "Pass rate (%)": "",
                "Interpretation": "All sampled V4 route units with no intermediary-token ERC-20 transfer",
            },
            {
                "Audit check": "Populated receipts",
                "N": _int(len(out)),
                "Pass rate (%)": _pct(out["total_logs"].gt(0).mean()),
                "Interpretation": "No-transfer examples are not empty receipt failures",
            },
            {
                "Audit check": "Source/sink transfer present",
                "N": _int(len(out)),
                "Pass rate (%)": _pct(((out["source_transfer_logs"] > 0) | (out["sink_transfer_logs"] > 0)).mean()),
                "Interpretation": "Receipt contains external endpoint-token movement while intermediary token is absent",
            },
            {
                "Audit check": "Intermediary transfer absent",
                "N": _int(len(out)),
                "Pass rate (%)": _pct(out["intermediate_transfer_logs"].eq(0).mean()),
                "Interpretation": "Confirms the sampled route unit has no ERC-20 transfer for the route intermediary",
            },
        ]
    )
    _write_table(
        summary,
        "table_r24_v4_manual_audit",
        "Manual audit of V4 no-transfer route units.",
        "tab:v4-manual-audit",
        note=(
            "The audit takes all V4 matched route units with no intermediary-token "
            "transfer and counts ERC-20 Transfer logs for the source, sink, and intermediary "
            "token addresses in the transaction receipt."
        ),
    )
    summary.to_csv(EMP / "v4_manual_audit_summary.csv", index=False)
    return out


def v4_balance_diagnostics() -> pd.DataFrame:
    detail = pd.read_csv(DATA / "empirical" / "v4_settlement_transfer_detail.csv")
    detail["has_matching_transfer"] = detail["has_matching_transfer"].map(_bool)
    detail["receipt_found"] = detail["receipt_found"].map(_bool)
    detail["log_route_usd"] = np.log1p(detail["route_usd"])
    rows = []
    for dex, g in detail.groupby("dex"):
        rows.append(
            {
                "DEX": dex,
                "Observations": _int(len(g)),
                "Cells": _int(g["cell_id"].nunique()),
                "Median route ($)": f"${_int(g['route_usd'].median())}",
                "p25/p75 route ($)": f"${_int(g['route_usd'].quantile(0.25))} / ${_int(g['route_usd'].quantile(0.75))}",
                "ETH/WETH vehicle (%)": _pct(g["vehicle"].isin(["ETH/WETH", "ETH", "WETH"]).mean()),
                "Stable vehicle (%)": _pct(g["vehicle"].isin(["USDC", "USDT", "DAI"]).mean()),
                "Mean total logs": _num(g["total_logs"].mean(), 2),
                "Transfer incidence (%)": _pct(g["has_matching_transfer"].mean()),
            }
        )
    # Within-cell route-size balance is the key observable matching diagnostic.
    cell = (
        detail.pivot_table(index="cell_id", columns="dex", values="log_route_usd", aggfunc="mean")
        .dropna()
        .reset_index()
    )
    if {"uniswap_v3", "uniswap_v4"}.issubset(cell.columns):
        diff = cell["uniswap_v4"] - cell["uniswap_v3"]
        from scipy import stats

        t, p = stats.ttest_1samp(diff, 0.0)
        rows.append(
            {
                "DEX": "V4 - V3 within cell",
                "Observations": "",
                "Cells": _int(len(cell)),
                "Median route ($)": "",
                "p25/p75 route ($)": "",
                "ETH/WETH vehicle (%)": "",
                "Stable vehicle (%)": "",
                "Mean total logs": f"log route diff={_num(diff.mean(), 3)}",
                "Transfer incidence (%)": f"t={_num(t, 2)}, p={_p(p)}",
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "v4_balance_diagnostics.csv", index=False)
    _write_table(
        out,
        "table_r29_v4_balance_diagnostics",
        "V3/V4 matched-sample balance diagnostics.",
        "tab:v4-balance-diagnostics",
        note=(
            "Matched cells are week by endpoint pair by intermediate vehicle. The table "
            "reports observable balance in route size, vehicle composition, and receipt logs. "
            "Router, pool type, gas, and user composition remain unobserved in the current "
            "route-unit panel."
        ),
    )
    return out


def main_test_registry_table() -> pd.DataFrame:
    rows = [
        {
            "Proposition": "P1",
            "Pre-specified main test": "WETH availability/thin-direct-market protection",
            "Main estimate": "9,584 no-direct/WETH-available rows; thin-direct medians 142.65/190.21/349.28 bp",
            "Economic unit": "route availability and bp by trade size",
            "Status": "main-ready, descriptive counterfactual",
        },
        {
            "Proposition": "P2",
            "Pre-specified main test": "LP concentration predicts future BridgeShare",
            "Main estimate": "within-token beta 0.2817; p<0.001",
            "Economic unit": "future bridge-share association",
            "Status": "downgrade to predictive association",
        },
        {
            "Proposition": "P3",
            "Pre-specified main test": "same-day WETH downside event decomposition",
            "Main estimate": "WETH -1.48 pp, stable +1.48 pp; p=0.018",
            "Economic unit": "bridge-share pp within common-support pairs",
            "Status": "main-ready as short-window event result",
        },
        {
            "Proposition": "P4a",
            "Pre-specified main test": "V3 no-direct/WETH-available decline",
            "Main estimate": "-25.81 pp; p<0.001; pretrend p=0.922",
            "Economic unit": "route-opportunity pp",
            "Status": "usable architecture evidence, not broad launch causality",
        },
        {
            "Proposition": "P4b",
            "Pre-specified main test": "V4 intermediary transfer incidence",
            "Main estimate": "V4 81.4% vs V3 100%; 25-case no-transfer audit exported",
            "Economic unit": "ERC-20 transfer incidence",
            "Status": "main-ready if audit examples are discussed carefully",
        },
    ]
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r25_main_test_registry",
        "Pre-specified main empirical tests and claim status.",
        "tab:main-test-registry",
        note=(
            "This table freezes one main test per proposition before drafting. Robustness "
            "families are reported separately to avoid selecting only significant slices."
        ),
    )
    out.to_csv(EMP / "main_test_registry.csv", index=False)
    return out


def compact_specification_registry_table() -> pd.DataFrame:
    rows = [
        {
            "Test": "P1 availability/thin-direct",
            "Outcome": "direct route exists; WETH route exists; route-cost advantage",
            "Unit": "endpoint-pair x day x trade size",
            "Sample": "V2/Sushi V2/V3 exact quoteable venues",
            "Treatment/regressor": "WETH vehicle route availability/cost",
            "FE / clustering": "endpoint-pair-day aggregation",
            "Main coefficient": "9,584 no-direct/WETH-available rows",
            "Interpretation": "descriptive counterfactual, covered venues",
        },
        {
            "Test": "P2 predictability",
            "Outcome": "future BridgeShare",
            "Unit": "token x day",
            "Sample": "WETH, USDC, USDT, DAI, WBTC",
            "Treatment/regressor": "vehicle-linked LP concentration",
            "FE / clustering": "token/date FE robustness; date clustering",
            "Main coefficient": "beta 0.2817, p<0.001",
            "Interpretation": "predictive association, not causal feedback",
        },
        {
            "Test": "P3 stress rotation",
            "Outcome": "WETH-minus-stable BridgeShare",
            "Unit": "event x endpoint-pair set",
            "Sample": "top WETH downside event days",
            "Treatment/regressor": "same-day WETH downside event",
            "FE / clustering": "event-level inference",
            "Main coefficient": "-2.96 pp, p=0.018",
            "Interpretation": "same-day association",
        },
        {
            "Test": "P4a V3 architecture",
            "Outcome": "no-direct/WETH-available indicator",
            "Unit": "endpoint-pair x month",
            "Sample": "balanced pairs around V3 launch",
            "Treatment/regressor": "post-V3 indicator",
            "FE / clustering": "pair FE; pair clustering",
            "Main coefficient": "-25.81 pp, p<0.001; pretrend p=0.922",
            "Interpretation": "route-opportunity evidence",
        },
        {
            "Test": "P4b V4 settlement",
            "Outcome": "intermediary ERC-20 transfer incidence",
            "Unit": "matched route unit",
            "Sample": "matched V3/V4 route cells",
            "Treatment/regressor": "V4 route unit",
            "FE / clustering": "matched-cell paired difference",
            "Main coefficient": "-18.6 pp, p<0.001",
            "Interpretation": "settlement-mechanics evidence",
        },
    ]
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "compact_specification_registry.csv", index=False)
    _write_table(
        out,
        "table_r27_compact_specification_registry",
        "Compact empirical specification registry.",
        "tab:compact-spec-registry",
        note=(
            "This table is the paper-facing version of the specification registry: it states "
            "the unit, sample, identifying variation, inference convention, and bounded "
            "interpretation for each main test."
        ),
    )
    return out


def main() -> int:
    EMP.mkdir(parents=True, exist_ok=True)
    stress_event_definition_table()
    stress_threshold_overlap_sensitivity()
    curve_fluid_materiality()
    curve_fluid_scope_bound()
    v4_manual_no_transfer_audit()
    v4_balance_diagnostics()
    main_test_registry_table()
    compact_specification_registry_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
