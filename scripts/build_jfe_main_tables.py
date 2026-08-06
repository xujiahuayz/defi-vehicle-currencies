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


def table_03_p2_predictability() -> pd.DataFrame:
    dyn = _read("table_r32_p2_liquidity_route_feedback.pkl")
    rows = []
    keep = dyn[
        dyn["Horizon (days)"].isin([7, 30])
        & dyn["Outcome"].isin(["VehicleShare", "LP concentration", "log LP liquidity"])
    ].copy()
    for _, r in keep.iterrows():
        rows.append(
            {
                "Panel": r["Panel"],
                "Horizon (days)": r["Horizon (days)"],
                "Outcome": r["Outcome"],
                "Main regressor": r["Main regressor"],
                "Beta": r["Beta"],
                "SE": r["SE"],
                "t": r["t"],
                "p": r["p"],
                "Control": r["Control"],
            }
        )
    out = pd.DataFrame(rows)
    _write_evidence_input(out, "p2_dynamic_predictability")
    _write_table(
        out,
        "table_m03_p2_dynamic_predictability",
        "Candidate-linked liquidity and vehicle-use dynamics.",
        "tab:main-p2-predictability",
        note=(
            "Panel A tests whether lagged candidate-linked LP concentration predicts VehicleShare. "
            "Panel B tests whether lagged VehicleShare predicts LP concentration and log LP liquidity. "
            "All variables are residualized by token and date fixed effects; standard errors are clustered by date. "
            "Relative concentration and absolute liquidity are reported separately."
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


def table_06_p4b_v4() -> pd.DataFrame:
    size = _read("table_r05_v4_robustness.pkl")
    balance = _read("table_r29_v4_balance_diagnostics.pkl")
    lp_response = _read("table_r33_p4b_netting_lp_response.pkl")
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
    for _, r in lp_response[lp_response["Panel"].eq("A. LP response around settlement-netting architecture")].iterrows():
        rows.append(
            {
                "Panel": "C. LP response by netting exposure",
                "Sample / diagnostic": r["Outcome"],
                "Cells": r["N"],
                "V3": "",
                "V4": "",
                "Difference / balance": f"{r['Treatment / exposure']} beta {r['Beta']} (t={r['t']})",
                "p": r["p"],
            }
        )
    out = pd.DataFrame(rows)
    _write_evidence_input(out, "p4b_v4_settlement")
    _write_table(
        out,
        "table_m06_p4b_v4_settlement",
        "Settlement netting, transfer incidence, and LP response.",
        "tab:main-p4b-v4",
        note=(
            "Panels A-B show that the settlement architecture lowers intermediary-token transfer incidence relative "
            "to matched route units and report balance diagnostics. Panel C tests the behavioral implication: vehicles "
            "with greater no-transfer exposure have higher post-launch log LP liquidity, while LP concentration share "
            "moves in the opposite direction. The LP response is suggestive mechanism evidence."
        ),
    )
    return out


def table_07_spec_registry() -> pd.DataFrame:
    p2 = pd.read_pickle(EMP / "p2_dynamic_predictability.pkl")
    p1 = pd.read_pickle(EMP / "p1_availability_thin_direct.pkl")

    def p2_cell(outcome: str) -> tuple[str, str]:
        row = p2[p2["Horizon (days)"].eq(7) & p2["Outcome"].eq(outcome)]
        if len(row) != 1:
            raise RuntimeError(f"Expected one 7-day P2 row for {outcome!r}.")
        result = row.iloc[0]
        return str(result["Beta"]), str(result["p"])

    lp_to_share_beta, lp_to_share_p = p2_cell("VehicleShare")
    share_to_conc_beta, share_to_conc_p = p2_cell("LP concentration")
    share_to_tvl_beta, share_to_tvl_p = p2_cell("log LP liquidity")
    p2_estimate = (
        f"LP->share {lp_to_share_beta} (p {lp_to_share_p}); "
        f"share->LP conc. {share_to_conc_beta} (p {share_to_conc_p}); "
        f"share->log TVL {share_to_tvl_beta} (p {share_to_tvl_p})"
    )
    p1_direct_available = str(p1.iloc[0]["Direct available (%)"])
    p1_indirect_only = str(p1.iloc[0]["Indirect-only WETH rows"])
    p1_thin_values = "/".join(
        p1["Thin-direct DirectCostAdvantage (fraction)"].astype(str)
    )

    rows = [
        {
            "Test": "P1 availability/thin-direct",
            "Unit": "endpoint-pair x day x trade size",
            "Sample": "V2/Sushi V2/V3 exact quoteable venues",
            "Outcome": "route availability and DirectCostAdvantage",
            "Regressor / treatment": "WETH indirect route",
            "FE / SE": "endpoint-pair-day aggregation",
            "Baseline mean": f"direct available {p1_direct_available}%",
            "Main estimate": (
                f"{p1_indirect_only} no-direct rows; thin-direct "
                f"DirectCostAdvantage {p1_thin_values}"
            ),
            "Economic interpretation": "availability and thin-direct execution protection",
        },
        {
            "Test": "P2 liquidity-route dynamics",
            "Unit": "token x day",
            "Sample": "vehicle candidates",
            "Outcome": "VehicleShare; LP concentration/log TVL",
            "Regressor / treatment": "lagged LP concentration; lagged VehicleShare",
            "FE / SE": "token/date FE; date-clustered SE",
            "Baseline mean": "see p2_dynamic_predictability",
            "Main estimate": p2_estimate,
            "Economic interpretation": "relative persistence; absolute TVL is specification-sensitive",
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
            "Unit": "matched route unit; token x week",
            "Sample": "matched V3/V4 cells; LP panel around launch",
            "Outcome": "transfer incidence; LP liquidity response",
            "Regressor / treatment": "V4 route unit; post x netting exposure",
            "FE / SE": "matched-cell tests; token/week FE",
            "Baseline mean": "V3 transfer incidence 100%",
            "Main estimate": "V4 gap -18.6 pp; log LP beta 2.132",
            "Economic interpretation": "settlement netting lowers movement and predicts LP supply response",
        },
    ]
    out = pd.DataFrame(rows)
    _write_evidence_input(out, "specification_registry")
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
