#!/usr/bin/env python3
"""JFE pre-write construct-validity and identification checks.

This script addresses the second independent review at the empirical-design
level. It does not add a new paper story; it stress-tests whether the existing
vehicle-currency measures survive alternative denominators, economic weighting,
and decomposition of the stress/event evidence.
"""
from __future__ import annotations

import importlib.util
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

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _pct, _write_table  # noqa: E402


VEHICLES = ("WETH", "USDC", "USDT", "DAI", "WBTC")
STABLES = {"USDC", "USDT", "DAI"}


def _load_module(name: str, file: str):
    path = SCRIPTS / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ttest(values: pd.Series | np.ndarray) -> tuple[float, float, float]:
    arr = pd.Series(values, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    if len(arr) < 3:
        return math.nan, math.nan, math.nan
    t, p = stats.ttest_1samp(arr, 0.0)
    return float(arr.mean()), float(t), float(p)


def route_denominator_panel(force: bool = False) -> pd.DataFrame:
    """Build daily all-route/direct/indirect denominators from unified routes."""
    out = DATA / "empirical" / "route_denominator_daily.parquet"
    if out.exists() and not force:
        return pd.read_parquet(out)

    empirical = _load_module("dvc_empirical_denoms", "run_empirical_proposition_tests.py")
    rows = []
    files = sorted((DATA / "unified").glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet"))
    for i, path in enumerate(files, 1):
        date = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        legs = pd.read_parquet(
            path,
            columns=[
                "tx_hash",
                "component_id",
                "route_class",
                "token_in_sym",
                "token_out_sym",
                "amount_usd",
                "tin_role",
                "tout_role",
            ],
        )
        routes = empirical._routes(legs[legs["route_class"].isin(empirical.CLEAN_ROUTE_CLASSES)])
        all_vol = float(sum(r["vol"] for r in routes))
        direct_vol = float(sum(r["vol"] for r in routes if not r["inter"]))
        indirect_vol = float(sum(r["vol"] for r in routes if r["inter"]))
        all_count = len(routes)
        direct_count = sum(1 for r in routes if not r["inter"])
        indirect_count = all_count - direct_count
        rows.append(
            {
                "date": date,
                "all_route_volume_usd": all_vol,
                "direct_route_volume_usd": direct_vol,
                "indirect_route_volume_usd": indirect_vol,
                "all_route_count": all_count,
                "direct_route_count": direct_count,
                "indirect_route_count": indirect_count,
                "direct_route_share": direct_vol / all_vol if all_vol > 0 else math.nan,
                "indirect_route_share": indirect_vol / all_vol if all_vol > 0 else math.nan,
            }
        )
        if i % 250 == 0 or i == len(files):
            print(f"route denominator scan [{i}/{len(files)}] {date}", flush=True)
    df = pd.DataFrame(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def bridge_denominator_robustness() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    den = route_denominator_panel()
    d = bridge.merge(den[["date", "all_route_volume_usd", "direct_route_share"]], on="date", how="left")
    d["year"] = pd.to_datetime(d["date"]).dt.year
    d["AllRouteBridgeShare"] = d["bridge_volume_usd"] / d["all_route_volume_usd"].replace(0, np.nan)
    d["DirectRouteShare"] = d["direct_route_share"]
    rows = []
    for token in VEHICLES:
        g = d[(d["token"].eq(token)) & d["year"].eq(2026)].copy()
        rows.append(
            {
                "Token": token,
                "Indirect BridgeShare (%)": _pct(g["BridgeShare"].mean()),
                "All-route bridge share (%)": _pct(g["AllRouteBridgeShare"].mean()),
                "PairCoverage (%)": _pct(g["PairCoverage"].mean()),
                "PairMainVehicle (%)": _pct(g["PairMainVehicleShare"].mean()),
                "Bridge volume ($bn)": _num(g["bridge_volume_usd"].sum() / 1e9, 2),
                "Mean direct-route share (%)": _pct(g["DirectRouteShare"].mean()),
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r16_bridge_denominator_robustness",
        "Vehicle-use measurement under alternative denominators.",
        "tab:bridge-denominator-robustness",
        note=(
            "The main BridgeShare denominator is indirect-route volume. The all-route "
            "variant divides the same intermediate-token bridge volume by all clean route "
            "volume, so direct-route substitution mechanically lowers every vehicle's share."
        ),
    )
    out.to_csv(EMP / "bridge_denominator_robustness.csv", index=False)
    return out


def route_cost_distribution_weighting() -> pd.DataFrame:
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle_sym"].eq("WETH") & panel["direct_available"] & panel["vehicle_available"]].copy()
    d["adv_bps"] = d["vehicle_route_advantage"] * 10_000.0
    d["pair_day"] = d["date"].astype(str) + "|" + d["src"].astype(str) + "|" + d["tgt"].astype(str)
    d["weight"] = d["realized_bridge_volume_usd"].fillna(0).clip(lower=0)
    rows = []
    for size, g in d.groupby("trade_size_usd"):
        x = g["adv_bps"].replace([np.inf, -np.inf], np.nan).dropna().clip(-100_000, 100_000)
        pair_day = g.groupby("pair_day", as_index=False)["adv_bps"].mean()
        mean_pd, t, p = _ttest(pair_day["adv_bps"].clip(-100_000, 100_000))
        weight = g.loc[x.index, "weight"]
        vw = float(np.average(x, weights=weight + 1e-9)) if len(x) else math.nan
        ew_dollar = float((size * mean_pd) / 10_000.0) if np.isfinite(mean_pd) else math.nan
        median_dollar = float((size * x.median()) / 10_000.0) if len(x) else math.nan
        rows.append(
            {
                "Trade size": f"${int(size):,}",
                "Rows": _int(len(x)),
                "Pair-days": _int(len(pair_day)),
                "Mean advantage (bp)": _num(mean_pd, 2),
                "Median advantage (bp)": _num(x.median(), 2),
                "p10/p90 (bp)": f"{_num(x.quantile(0.10), 1)} / {_num(x.quantile(0.90), 1)}",
                "Volume-weighted mean (bp)": _num(vw, 2),
                "Mean dollar saving": _num(ew_dollar, 2),
                "Median dollar saving": _num(median_dollar, 2),
                "Pair-day t": _num(t, 2),
                "p": _p(p),
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r17_route_cost_distribution_weighting",
        "Distribution and economic weighting of WETH route-cost advantages.",
        "tab:route-cost-distribution-weighting",
        note=(
            "The t-statistic tests whether the endpoint-pair-day mean advantage differs from "
            "zero. Median and percentile columns show why the claim is availability and "
            "thin-market protection rather than universal cost dominance."
        ),
    )
    out.to_csv(EMP / "route_cost_distribution_weighting.csv", index=False)
    return out


def stress_rotation_decomposition() -> pd.DataFrame:
    weekly = _load_module("stress_weekly_decomp", "run_stress_weekly_common_support.py")
    empirical = weekly._load_empirical_module()
    events = pd.read_csv(EMP / "stress_common_support_events.csv")
    events["event_date"] = pd.to_datetime(events["event_date"])
    events = events.sort_values("downside_stress", ascending=False).head(20)

    stamps: set[str] = set()
    for d in events["event_date"]:
        stamps.add(weekly._stamp(d))
        for b in range(1, 29):
            stamps.add(weekly._stamp(d - pd.Timedelta(days=b)))
    panel = weekly._build_panel(stamps, empirical)
    den = route_denominator_panel()
    den["date"] = pd.to_datetime(den["date"])

    rows = []
    for ev in events.itertuples(index=False):
        d = pd.Timestamp(ev.event_date)
        event = weekly._window_gap(panel, d, 1).rename(
            columns={"WETH": "event_weth", "STABLE": "event_stable"}
        )
        base = weekly._window_gap(panel, d - pd.Timedelta(days=28), 28)
        # Recompute full WETH/STABLE shares because _window_gap keeps only the gap.
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

        den_event = den[den["date"].eq(d)]
        den_base = den[(den["date"] >= d - pd.Timedelta(days=28)) & (den["date"] < d)]
        direct_effect = (
            float(den_event["direct_route_share"].mean() - den_base["direct_route_share"].mean())
            if not den_event.empty and not den_base.empty
            else math.nan
        )
        indirect_volume_effect = (
            float(np.log(den_event["indirect_route_volume_usd"].mean()) - np.log(den_base["indirect_route_volume_usd"].mean()))
            if not den_event.empty and not den_base.empty and den_event["indirect_route_volume_usd"].mean() > 0 and den_base["indirect_route_volume_usd"].mean() > 0
            else math.nan
        )
        rows.append(
            {
                "event_date": d.strftime("%Y-%m-%d"),
                "downside_stress": float(ev.downside_stress),
                "n_pairs": int(len(comp)),
                "weth_effect": float(np.average(comp["weth_effect"], weights=weights)),
                "stable_effect": float(np.average(comp["stable_effect"], weights=weights)),
                "gap_effect": float(np.average(comp["gap_effect"], weights=weights)),
                "direct_route_share_effect": direct_effect,
                "log_indirect_volume_effect": indirect_volume_effect,
            }
        )

    effects = pd.DataFrame(rows)
    effects.to_csv(EMP / "stress_rotation_decomposition_events.csv", index=False)
    summary_rows = []
    for col, label, units in [
        ("weth_effect", "WETH share change", "pp"),
        ("stable_effect", "Stable share change", "pp"),
        ("gap_effect", "WETH-minus-stable change", "pp"),
        ("direct_route_share_effect", "Aggregate direct-route share change", "pp"),
        ("log_indirect_volume_effect", "Log indirect-route volume change", "log points"),
    ]:
        mean, t, p = _ttest(effects[col])
        scale = 100 if units == "pp" else 1
        summary_rows.append(
            {
                "Component": label,
                "Events": _int(effects[col].notna().sum()),
                "Effect": _num(scale * mean, 2),
                "t": _num(t, 2),
                "p": _p(p),
                "Units": units,
            }
        )
    out = pd.DataFrame(summary_rows)
    _write_table(
        out,
        "table_r18_stress_rotation_decomposition",
        "Stress-rotation decomposition.",
        "tab:stress-rotation-decomposition",
        note=(
            "The first three rows use common endpoint-pair sets. The last two rows are "
            "aggregate route-denominator diagnostics for direct-route substitution and "
            "overall indirect-route activity on the event day relative to the prior 28 days."
        ),
    )
    return out


def write_specification_registry() -> None:
    text = """# Empirical Specification Registry

This registry is the pre-write contract for the empirical section. It separates
what the estimates identify from what they do not identify.

## P1. Route Availability and Thin-Direct-Market Value

- Unit: endpoint-pair, vehicle, date, trade-size bucket.
- Main sample: route-cost panel for WETH using V2/Sushi V2 constant-product
  state plus DVC-native exact-crossing V3 tick-net quotes.
- Main outcomes: direct-route availability, WETH-route availability,
  no-direct/WETH-available indicator, common-support route-cost advantage.
- Main estimand: availability and execution-cost value of the vehicle route
  relative to direct routing, especially when direct liquidity is missing or thin.
- Inference: endpoint-pair-day aggregation for central t-tests; report p-values.
- Weights: report equal-weighted, realized-bridge-volume-weighted, and
  endpoint-pair-day estimates.
- Identification claim: descriptive counterfactual quote evidence, not causal
  proof that WETH always lowers costs.

## P2. Liquidity Concentration and Stickiness

- Unit: token-day.
- Main sample: candidate vehicle tokens WETH, USDC, USDT, DAI, WBTC.
- Main outcomes: future BridgeShare and BridgeShare persistence.
- Main regressor: vehicle-linked LP concentration.
- Fixed effects: token and date fixed effects in robustness.
- Inference: date-clustered or block-bootstrap inference.
- Identification claim: predictive association and persistence. Do not claim
  causal LP feedback unless a separate shock design is added.
- Repositioning diagnostic: currently not positive-clean; use as a limitation
  or referee-proofing diagnostic, not as mechanism evidence.

## P3. Stress Rotation

- Unit: stress event by endpoint-pair opportunity set.
- Main treatment: large WETH downside events, defined from WETH returns.
- Main outcome: WETH-minus-stable BridgeShare within common-support endpoint
  pairs.
- Required decomposition: WETH share change, stable share change, aggregate
  direct-route share change, and indirect-route volume change.
- Baseline: prior 28 days unless stated otherwise.
- Inference: event-level t-tests and placebo/randomization distributions.
- Identification claim: short-window event association, not persistent stress
  regime rotation.

## P4a. V3 Architecture

- Unit: endpoint-pair/date/trade-size bucket around the V3 launch.
- Main outcomes: direct-route availability, WETH-route availability,
  no-direct/WETH-available cases, and direct-route quality.
- Fixed effects: endpoint-pair fixed effects; event-time/pre-trend checks still
  required before causal launch language.
- Identification claim: route-opportunity expansion evidence, not a clean causal
  estimate unless a control group/pre-trend design is added.

## P4b. V4 Settlement Virtualization

- Unit: matched V3/V4 route unit or matched route cell.
- Main outcome: ERC-20 transfer incidence of the intermediary token.
- Matching: week, endpoint pair, intermediate vehicle token, and route-size
  cells where available.
- Required validation: receipt-parser checks against known V4 flash-accounting
  examples and matched-cell balance diagnostics.
- Identification claim: settlement-mechanics evidence conditional on matched
  route use; not a claim that V4 eliminates vehicle currencies.

## Cross-Chain Scope

Cross-chain native-asset replication is an external-validity extension, not a
prerequisite for the Ethereum vehicle-currency paper. It becomes necessary only
if the paper claims a universal native-currency mechanism rather than an
Ethereum/AMM vehicle-currency mechanism. If added, the clean design is to use
chain-level replications for WETH-on-Ethereum, WBNB-on-BNB, WMATIC-on-Polygon,
WAVAX-on-Avalanche, and WETH/ETH-on-Base/Arbitrum/Optimism, using the same
BridgeShare, route-cost availability, and direct-route-substitution definitions.
"""
    (ROOT / "paper" / "empirical_specification_registry.md").write_text(text, encoding="utf-8")


def main() -> int:
    EMP.mkdir(parents=True, exist_ok=True)
    bridge_denominator_robustness()
    route_cost_distribution_weighting()
    stress_rotation_decomposition()
    write_specification_registry()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
