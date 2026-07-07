#!/usr/bin/env python3
"""Build the JFE-facing main table set.

These tables deliberately privilege the bounded claims selected after the
independent reviews. They are not a dump of all results.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / "tables" / name)


def _float(x: object) -> float:
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except ValueError:
        return math.nan


def table_01_measurement_scope() -> pd.DataFrame:
    denom = _read("table_r16_bridge_denominator_robustness.csv")
    scope = _read("table_r28_curve_fluid_scope_bound.csv")
    rows = []
    for token in ["WETH", "USDC", "USDT"]:
        r = denom[denom["Token"].eq(token)].iloc[0]
        rows.append(
            {
                "Panel": "A. Vehicle-use denominators, 2026",
                "Quantity": token,
                "Main estimate": f"{r['Indirect BridgeShare (%)']}% conditional BridgeShare",
                "Scope / companion estimate": f"{r['All-route bridge share (%)']}% all-route bridge share",
                "Interpretation": f"{r['PairCoverage (%)']}% endpoint-pair coverage",
            }
        )
    for _, r in scope.iterrows():
        rows.append(
            {
                "Panel": "B. Exact-quote scope",
                "Quantity": r["Quantity"],
                "Main estimate": str(r["Value"]),
                "Scope / companion estimate": "",
                "Interpretation": r["Interpretation"],
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m01_measurement_scope",
        "Vehicle-use measurement and exact-quote scope.",
        "tab:main-measurement-scope",
        note=(
            "BridgeShare is conditional on indirect routes. The all-route bridge share is "
            "reported alongside it to prevent interpreting vehicle use as a share of all "
            "DEX volume. Exact executable-depth route-cost tests are scoped to covered "
            "quoteable venues."
        ),
    )
    return out


def table_02_p1_availability() -> pd.DataFrame:
    r12 = _read("table_r12_route_cost_decomposition.csv")
    rows = []
    for _, r in r12.iterrows():
        rows.append(
            {
                "Trade size": r["Trade size"],
                "Direct available (%)": r["Direct available (%)"],
                "WETH route available (%)": r["WETH route available (%)"],
                "No-direct / WETH-available rows": r["No-direct, WETH-available rows"],
                "Thin-direct median advantage (bp)": r["Median thin-direct advantage (bp)"],
                "High-quality-direct median advantage (bp)": r["Median high-quality-direct advantage (bp)"],
                "Common-support median (bp)": r["Median common-support advantage (bp)"],
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m02_p1_availability_thin_direct",
        "Availability and thin-direct-market protection by WETH vehicle routes.",
        "tab:main-p1-availability",
        note=(
            "This is the main P1 table. The claim is not universal route-cost superiority. "
            "It is route availability and execution protection when direct routes are "
            "missing or thin, in exact-quote-covered venues."
        ),
    )
    return out


def table_03_p2_predictability() -> pd.DataFrame:
    dyn = _read("table_r31_p2_dynamic_persistence.csv")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    d = bridge.merge(lp[["date", "token", "lp_concentration_share"]], on=["date", "token"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    rows = []
    for _, r in dyn.iterrows():
        h = int(str(r["Horizon"]).replace("t+", ""))
        dd = d.copy()
        dd["future"] = dd.groupby("token")["BridgeShare"].shift(-h)
        base = dd["future"].mean()
        lp_beta = _float(r["LP beta"])
        rho = _float(r["Persistence beta"])
        rows.append(
            {
                "Horizon": r["Horizon"],
                "Baseline future BridgeShare (%)": _num(100 * base, 2),
                "LP beta": r["LP beta"],
                "LP SE": r["LP SE"],
                "LP p": r["LP p"],
                "Effect of +10pp LP concentration (pp)": _num(10 * lp_beta, 2),
                "Persistence beta": r["Persistence beta"],
                "Persistence SE": r["Persistence SE"],
                "Persistence p": r["Persistence p"],
                "Effect of +10pp current BridgeShare (pp)": _num(10 * rho, 2),
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m03_p2_dynamic_predictability",
        "Liquidity concentration and bridge-use predictability.",
        "tab:main-p2-predictability",
        note=(
            "Outcome is future BridgeShare. Regressors are current LP concentration and "
            "current BridgeShare. Variables are residualized by token and date fixed effects; "
            "standard errors are clustered by date. This is predictability, not causal LP "
            "feedback."
        ),
    )
    return out


def table_04_p3_stress() -> pd.DataFrame:
    decomp = _read("table_r18_stress_rotation_decomposition.csv")
    sens = _read("table_r26_stress_threshold_overlap_sensitivity.csv")
    rows = []
    for _, r in decomp.iterrows():
        rows.append(
            {
                "Panel": "A. Main decomposed same-day effect",
                "Estimate": r["Component"],
                "Events": r["Events"],
                "Effect": f"{r['Effect']} {r['Units']}",
                "t": r["t"],
                "p": r["p"],
                "Interpretation": "event-day minus prior-28-day baseline",
            }
        )
    for _, r in sens.iterrows():
        rows.append(
            {
                "Panel": "B. Threshold/overlap sensitivity",
                "Estimate": r["Event set"],
                "Events": r["Events"],
                "Effect": f"{r['Gap effect (pp)']} pp",
                "t": r["t"],
                "p": r["p"],
                "Interpretation": f"negative share {r['Negative share (%)']}%",
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m04_p3_stress_rotation",
        "Impact stress rotation in common endpoint-pair opportunities.",
        "tab:main-p3-stress",
        note=(
            "The main paper-facing estimate is the decomposed same-day event effect. "
            "Alternative thresholds and non-overlapping event sets preserve the sign and "
            "statistical significance. Longer hourly/weekly/multi-day windows are robustness "
            "checks on duration, not the main estimand."
        ),
    )
    return out


def table_05_p4a_v3() -> pd.DataFrame:
    evt = _read("table_r19_v3_event_time_pretrends.csv")
    keep = evt[evt["Outcome"].eq("No-direct WETH availability")].copy()
    keep = keep.rename(
        columns={
            "Post effect": "Post-V3 effect",
            "Post t": "t",
            "Post p": "p",
        }
    )
    out = keep[
        ["Outcome", "Rows", "Pairs", "Post-V3 effect", "t", "p", "Pretrend slope", "Pretrend t", "Pretrend p", "Units"]
    ]
    _write_table(
        out,
        "table_m05_p4a_v3_opportunity",
        "V3 route-opportunity evidence: no-direct/WETH-available cases.",
        "tab:main-p4a-v3",
        note=(
            "The paper-facing V3 result is restricted to the outcome without a detectable "
            "pretrend. Broader V3 launch effects remain suggestive/appendix evidence."
        ),
    )
    return out


def table_06_p4b_v4() -> pd.DataFrame:
    size = _read("table_r05_v4_robustness.csv")
    balance = _read("table_r29_v4_balance_diagnostics.csv")
    rows = []
    for _, r in size.iterrows():
        rows.append(
            {
                "Panel": "A. Transfer incidence by route-size bin",
                "Sample / diagnostic": r["Sample"],
                "Cells": r["Cells"],
                "V3": f"{r['V3 transfer (%)']}%",
                "V4": f"{r['V4 transfer (%)']}%",
                "Difference / balance": f"{r['V4 - V3 (pp)']} pp",
                "p": r["p"],
            }
        )
    for _, r in balance.iterrows():
        rows.append(
            {
                "Panel": "B. Matched-sample balance",
                "Sample / diagnostic": r["DEX"],
                "Cells": r["Cells"],
                "V3": r["Median route ($)"] if r["DEX"] == "uniswap_v3" else "",
                "V4": r["Median route ($)"] if r["DEX"] == "uniswap_v4" else "",
                "Difference / balance": r["Mean total logs"],
                "p": r["Transfer incidence (%)"],
            }
        )
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m06_p4b_v4_settlement",
        "V4 settlement virtualization and route-size balance.",
        "tab:main-p4b-v4",
        note=(
            "V4 lowers intermediary-token transfer incidence relative to matched V3 route "
            "units. Because V4 route units are smaller within cells, size-bin estimates and "
            "balance diagnostics are part of the main evidence."
        ),
    )
    return out


def table_07_spec_registry() -> pd.DataFrame:
    rows = [
        {
            "Test": "P1 availability/thin-direct",
            "Unit": "endpoint-pair x day x trade size",
            "Sample": "V2/Sushi V2/V3 exact quoteable venues",
            "Outcome": "route availability and WETH advantage",
            "Regressor / treatment": "WETH vehicle route",
            "FE / SE": "endpoint-pair-day aggregation",
            "Baseline mean": "direct available 72.1%",
            "Main estimate": "9,584 no-direct rows; thin-direct 142.65-349.28 bp",
            "Economic interpretation": "availability and thin-direct execution protection",
        },
        {
            "Test": "P2 predictability",
            "Unit": "token x day",
            "Sample": "vehicle candidates",
            "Outcome": "future BridgeShare",
            "Regressor / treatment": "LP concentration; current BridgeShare",
            "FE / SE": "token/date FE; date-clustered SE",
            "Baseline mean": "see Table m03",
            "Main estimate": "LP beta 0.120-0.148; p<0.001",
            "Economic interpretation": "predictability and persistence, not causal feedback",
        },
        {
            "Test": "P3 impact stress",
            "Unit": "event x common endpoint-pair set",
            "Sample": "WETH downside event days",
            "Outcome": "WETH-minus-stable BridgeShare",
            "Regressor / treatment": "event-day WETH downside stress",
            "FE / SE": "event-level t-tests",
            "Baseline mean": "prior 28-day common-pair baseline",
            "Main estimate": "-2.96 pp, p=0.018",
            "Economic interpretation": "same-day rotation away from WETH toward stable vehicles",
        },
        {
            "Test": "P4a V3 opportunity",
            "Unit": "endpoint-pair x month",
            "Sample": "balanced V3 launch-window pairs",
            "Outcome": "no-direct/WETH-available indicator",
            "Regressor / treatment": "post-V3",
            "FE / SE": "pair FE; pair-clustered SE",
            "Baseline mean": "pre/post balanced pair panel",
            "Main estimate": "-25.81 pp, p<0.001; pretrend p=0.922",
            "Economic interpretation": "direct-route opportunity expansion",
        },
        {
            "Test": "P4b V4 settlement",
            "Unit": "matched route unit",
            "Sample": "matched V3/V4 cells",
            "Outcome": "intermediary-token transfer incidence",
            "Regressor / treatment": "V4 route unit",
            "FE / SE": "matched-cell paired tests",
            "Baseline mean": "V3 transfer incidence 100%",
            "Main estimate": "V4 81.4%; gap -18.6 pp",
            "Economic interpretation": "route intermediation partly separated from physical transfer",
        },
    ]
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_m07_specification_registry",
        "Paper-facing specification registry for main empirical tests.",
        "tab:main-spec-registry",
        note=(
            "This table freezes the main paper tests and their bounded interpretations before "
            "drafting. Robustness and alternative definitions are appendix material."
        ),
    )
    return out


def main() -> int:
    table_01_measurement_scope()
    table_02_p1_availability()
    table_03_p2_predictability()
    table_04_p3_stress()
    table_05_p4a_v3()
    table_06_p4b_v4()
    table_07_spec_registry()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
