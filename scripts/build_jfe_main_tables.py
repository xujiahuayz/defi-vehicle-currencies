#!/usr/bin/env python3
"""Build the JFE-facing main table set.

These tables deliberately privilege the bounded claims selected after the
independent reviews. They are not a dump of all results.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _artifact_stem, _int, _num, _p, _write_table


def _read(name: str) -> pd.DataFrame:
    stem = Path(name).stem
    return pd.read_pickle(EMP / f"{_artifact_stem(stem)}.pkl")


def _write_evidence_input(df: pd.DataFrame, stem: str) -> None:
    """Persist only main-table data consumed by evidence-map/review builders."""

    EMP.mkdir(parents=True, exist_ok=True)
    df.to_pickle(EMP / f"{stem}.pkl")


def _float(x: object) -> float:
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except ValueError:
        return math.nan


def table_01_measurement_scope() -> pd.DataFrame:
    denom = _read("table_r16_bridge_denominator_robustness.pkl")
    scope = _read("table_r28_curve_fluid_scope_bound.pkl")
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
    _write_evidence_input(out, "measurement_scope")
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
    r12 = _read("table_r12_route_cost_decomposition.pkl")
    rows = []
    for _, r in r12.iterrows():
        rows.append(
            {
                "Trade size": r["Trade size"],
                "Direct available (%)": r["Direct available (%)"],
                "WETH indirect route available (%)": r["WETH route available (%)"],
                "Indirect-only WETH rows": r["No-direct, WETH-available rows"],
                "Thin-direct DirectCostAdvantage (fraction)": r[
                    "Median thin-direct direct cost advantage (fraction)"
                ],
                "High-quality-direct DirectCostAdvantage (fraction)": r[
                    "Median high-quality-direct cost advantage (fraction)"
                ],
                "Common-support DirectCostAdvantage (fraction)": r[
                    "Median common-support direct cost advantage (fraction)"
                ],
            }
        )
    out = pd.DataFrame(rows)
    _write_evidence_input(out, "p1_availability_thin_direct")
    _write_table(
        out,
        "table_m02_p1_availability_thin_direct",
        "Availability and thin-direct-market protection by WETH indirect routes.",
        "tab:main-p1-availability",
        note=(
            "This is the main P1 table. The claim is not universal route-cost superiority. "
            "It is route availability and execution protection when direct routes are "
            "missing or thin, in exact-quote-covered venues."
        ),
    )
    return out


def table_04_p3_stress() -> pd.DataFrame:
    decomp = _read("table_r18_stress_rotation_decomposition.pkl")
    sens = _read("table_r26_stress_threshold_overlap_sensitivity.pkl")
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
    _write_evidence_input(out, "p3_stress_rotation")
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
    evt = _read("table_r19_v3_event_time_pretrends.pkl")
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
    _write_evidence_input(out, "p4a_v3_opportunity")
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


def main() -> int:
    table_01_measurement_scope()
    table_02_p1_availability()
    table_04_p3_stress()
    table_05_p4a_v3()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
