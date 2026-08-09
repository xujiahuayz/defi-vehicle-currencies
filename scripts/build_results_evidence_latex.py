#!/usr/bin/env python3
"""Build a JFE-style evidence map for the DVC empirical results.

This is a presentation layer. Its inputs are ignored analysis outputs under
``output/empirical/`` plus tracked paper-facing TeX/PDF artifacts under
``output/tables/``. Paper-facing output filenames are descriptive and unnumbered;
paper/slides own table numbering.

For a clean reproducible rebuild from tracked scripts, run:

    ./scripts/run scripts/build_results_evidence_outputs.py

The TeX output is tracked. The PDF output is a local ignored render because
different TeX engines produce different PDF byte streams.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import textwrap

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EMP = ROOT / "output" / "empirical"
PAPER = ROOT / "paper"
OUT_TEX = PAPER / "results_evidence_map.tex"
OUT_PDF = PAPER / "results_evidence_map.pdf"
FULL_REBUILD_COMMAND = "./scripts/run scripts/build_results_evidence_outputs.py"
NUMBERED_ARTIFACT_RE = re.compile(r"^(?:table|figure)_(?:[a-z]\d+|\d+)_", re.IGNORECASE)


@dataclass(frozen=True)
class RawLatex:
    text: str


def esc(value: object) -> str:
    if isinstance(value, RawLatex):
        return value.text
    text = "" if value is None else str(value)
    if text == "nan":
        return ""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = text.replace("<0.001", r"$<$0.001")
    return text


def significance_stars(p_value: object) -> str:
    text = str(p_value).strip()
    if not text:
        return ""
    text = (
        text.replace("$<$", "<")
        .replace("p < ", "")
        .replace("p=", "")
        .replace("p ", "")
        .strip()
    )
    if "," in text:
        return ""
    try:
        if text.startswith("<"):
            p = float(text[1:])
            threshold_is_strict = True
        else:
            p = float(text)
            threshold_is_strict = False
    except ValueError:
        return ""
    if p < 0.01 or (threshold_is_strict and p <= 0.01):
        return "***"
    if p < 0.05 or (threshold_is_strict and p <= 0.05):
        return "**"
    if p < 0.10 or (threshold_is_strict and p <= 0.10):
        return "*"
    return ""


def starred(value: object, p_value: object) -> object:
    stars = significance_stars(p_value)
    if not stars or value is None or str(value) == "":
        return value
    return RawLatex(f"{esc(value)}$^{{{stars}}}$")


def p_label(p_value: object) -> str:
    text = str(p_value).strip()
    if not text:
        return ""
    if text.startswith("<"):
        return f"p{text}"
    if text.startswith("p"):
        return text
    return f"p={text}"


def coef_p_cell(value: object, p_value: object) -> object:
    if value is None or str(value) == "":
        return ""
    stars = significance_stars(p_value)
    star_tex = f"$^{{{stars}}}$" if stars else ""
    p_text = p_label(p_value)
    if not p_text:
        return RawLatex(f"\\makecell{{{esc(value)}{star_tex}}}")
    return RawLatex(f"\\makecell{{{esc(value)}{star_tex} \\\\ {{\\scriptsize {esc(p_text)}}}}}")


def header_cell(number: str, *labels: str) -> RawLatex:
    label_lines = " \\\\ ".join(esc(label) for label in labels)
    return RawLatex(f"\\makecell{{{esc(number)} \\\\ {label_lines}}}")


def read_table(stem: str) -> pd.DataFrame:
    clean_stem = NUMBERED_ARTIFACT_RE.sub("", stem)
    path = EMP / f"{clean_stem}.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Run {FULL_REBUILD_COMMAND} first."
        )
    return pd.read_pickle(path).astype(str).fillna("")


def clean_regressor(name: str) -> str:
    mapping = {
        "BridgeShare": "Current vehicle share",
        "direct_cost_advantage": "Direct cost advantage",
        "direct_cost_advantage_median": "Median direct cost advantage",
        "vehicle_available": "Indirect route available",
        "vehicle_available_share": "Indirect-route availability",
        "vehicle_quote_quality": "Indirect-route quote quality",
        "lp_capital_share": "LP capital share",
        "no_direct_vehicle_available_share": "Indirect-only availability",
        "direct_available_share": "Direct-route availability",
        "market_capital_factor_loo": "Market capital factor",
        "vehicle_capital_factor_loo": "Vehicle capital factor",
        "vehicle_capital_factor_x_stress": "Vehicle capital factor x stress",
        "vehicle_capital_factor_x_post_v3": "Vehicle capital factor x post-V3",
        "log V3 route count": "Log V3 route count",
        "log V3 route volume": "Log V3 route volume",
    }
    return mapping.get(name, name)


def clean_outcome(name: str) -> str:
    mapping = {
        "VehicleShare": "Vehicle share",
        "LPCapitalShare": "LP capital share",
        "log VehicleLinkedCapital": "Log vehicle-linked capital",
        "Change in LPCapitalShare": "Change in LP capital share",
        "Change in log VehicleLinkedCapital": "Change in log vehicle-linked capital",
        "Actual vehicle share": "Actual vehicle share",
        "Log actual vehicle volume": "Log actual vehicle volume",
        "No-direct WETH availability": "No-direct, WETH-available",
        "Direct-route availability": "Direct-route availability",
        "Log V4 route count": "Log V4 route count",
        "Log V4 route volume": "Log V4 route volume",
    }
    return mapping.get(name, name)


def clean_sample(name: str) -> str:
    mapping = {
        "uniswap_v3": "Uniswap V3",
        "uniswap_v4": "Uniswap V4",
        "V4 - V3 within cell": "V4 minus V3 within cell",
        "challenger <= incumbent": "Challenger <= incumbent",
        "0 to 0.0025": "0-0.0025",
        "0.0025 to 0.01": "0.0025-0.01",
        "0.01 to 0.025": "0.01-0.025",
    }
    return mapping.get(name, name)


def first_match(df: pd.DataFrame, **where: str) -> pd.Series | None:
    g = df.copy()
    for key, val in where.items():
        g = g[g[key].astype(str).eq(val)]
    if g.empty:
        return None
    return g.iloc[0]


def reg_cell(df: pd.DataFrame, *, estimate_col: str = "Beta", p_col: str = "p", **where: str) -> object:
    r = first_match(df, **where)
    if r is None:
        return ""
    return coef_p_cell(r[estimate_col], r[p_col])


def value_cell(df: pd.DataFrame, column: str, **where: str) -> str:
    r = first_match(df, **where)
    if r is None:
        return ""
    return str(r[column])


@dataclass
class TableSpec:
    number: str
    caption: str
    label: str
    columns: list[str]
    widths: list[str]
    rows: list[list[object]]
    note: str
    landscape: bool = False


def table_tex(spec: TableSpec) -> str:
    align = "@{}" + "".join(f">{{\\raggedright\\arraybackslash}}p{{{w}}}" for w in spec.widths) + "@{}"
    lines: list[str] = []
    if spec.landscape:
        lines.append(r"\begin{landscape}")
    lines.extend(
        [
            r"\begin{table}[!htbp]",
            r"\centering",
            r"\scriptsize",
            r"\setlength{\tabcolsep}{2.5pt}",
            r"\begin{threeparttable}",
            f"\\caption{{{esc(spec.caption)}}}",
            f"\\label{{{spec.label}}}",
            f"\\begin{{tabular}}{{{align}}}",
            r"\toprule",
            " & ".join(esc(c) for c in spec.columns) + r" \\",
            r"\midrule",
        ]
    )
    current_panel = None
    for row in spec.rows:
        panel = row[0] if row and str(row[0]).startswith("Panel ") else None
        if panel and panel != current_panel:
            if current_panel is not None:
                lines.append(r"\addlinespace")
            lines.append(f"\\multicolumn{{{len(spec.columns)}}}{{l}}{{\\textit{{{esc(panel)}}}}} \\\\")
            current_panel = panel
            continue
        lines.append(" & ".join(esc(v) for v in row) + r" \\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\begin{tablenotes}[flushleft]",
            r"\footnotesize",
            f"\\item \\textit{{Notes:}} {esc(spec.note)}",
            r"\end{tablenotes}",
            r"\end{threeparttable}",
            r"\end{table}",
        ]
    )
    if spec.landscape:
        lines.append(r"\end{landscape}")
    return "\n".join(lines)


def evidence_map() -> TableSpec:
    rows = [
        [
            "RQ1",
            "When does one asset become the vehicle?",
            "Endpoint pair x candidate vehicle x day.",
            "Direct cost advantage, indirect-route availability, indirect-route quote quality.",
            "Table 4",
            "Actual vehicle share and future vehicle share rise with executable indirect-route economics.",
        ],
        [
            "RQ2",
            "How does liquidity provision make a vehicle?",
            "Token x day dynamic panel.",
            "LP capital share, vehicle-linked deposited capital, lagged vehicle share.",
            "Table 5",
            "Relative LP capital allocation and vehicle use are mutually persistent; absolute deposited capital moves differently.",
        ],
        [
            "RQ3",
            "Why does vehicle status persist or get displaced?",
            "Incumbent-challenger pair x day.",
            "Lagged vehicle share and challenger route-cost edge.",
            "Table 5",
            "Incumbents persist, but large challenger cost edges predict share losses.",
        ],
        [
            "RQ4",
            "When does vehicle status switch under stress?",
            "Common-support stress-event days.",
            "WETH-minus-stable vehicle share relative to a prior baseline.",
            "Table 6",
            "Stress rotates share away from WETH and toward stable vehicles on event days.",
        ],
        [
            "RQ5",
            "How does architecture change vehicle formation?",
            "Endpoint-pair event windows around V3.",
            "Direct-route availability and no-direct/WETH-available cases.",
            "Table 7",
            "V3 expands direct-route opportunity and reduces no-direct dependence on WETH.",
        ],
        [
            "RQ6",
            "How does settlement design change vehicle use?",
            "Matched V3/V4 route cells and receipt-audited route units.",
            "Intermediate-token transfer incidence and matched-cell V4 route use.",
            "Table 8",
            "V4 lowers physical intermediary transfers while vehicle use persists.",
        ],
        [
            "RQ7",
            "Does a vehicle create common LP capital movements?",
            "Pool x vehicle x day deposited-capital panel.",
            "Leave-one-out vehicle capital factor.",
            "Table 9",
            "Vehicle-linked pools share a same-vehicle deposited-capital component beyond market capital movements.",
        ],
    ]
    return TableSpec(
        "1",
        "Research questions, empirical objects, and evidence.",
        "tab:rq-evidence-map",
        ["RQ", "Research question", "Unit", "Main proxy", "Evidence", "Empirical answer"],
        ["0.06\\textwidth", "0.20\\textwidth", "0.15\\textwidth", "0.20\\textwidth", "0.08\\textwidth", "0.23\\textwidth"],
        rows,
        "The table is the organizing map for the results document. It separates the research question from the test bed, empirical proxy, and table that answers it.",
        landscape=True,
    )


def scope_table() -> TableSpec:
    df = read_table("measurement_scope")
    rows = []
    current_panel = None
    for _, r in df.iterrows():
        panel = f"Panel {r['Panel']}"
        if panel != current_panel:
            rows.append([panel, "", "", "", ""])
            current_panel = panel
        rows.append([
            "",
            r["Quantity"],
            r["Main estimate"],
            r["Scope / companion estimate"],
            r["Interpretation"],
        ])
    return TableSpec(
        "2",
        "Vehicle-use measurement and exact-quote scope.",
        "tab:measurement-scope",
        ["Panel", "Quantity", "Main estimate", "Companion estimate", "Interpretation"],
        ["0.16\\textwidth", "0.18\\textwidth", "0.21\\textwidth", "0.20\\textwidth", "0.21\\textwidth"],
        rows,
        "BridgeShare is conditional on indirect routes. All-route bridge share and endpoint-pair coverage are reported so the conditional vehicle measure is not confused with a share of all DEX volume. Exact executable-depth route-cost results are scoped to covered quoteable venues.",
        landscape=True,
    )


def variable_table() -> TableSpec:
    df = read_table("variable_construction")
    keep = [
        "VehicleShare",
        "DirectCostAdvantage",
        "DirectAvailable",
        "IndirectAvailable",
        "VehicleLinkedCapital",
        "LPCapitalShare",
        "SettlementTransferIncidence",
        "VehicleCapitalFactor",
    ]
    display_name = {
        "VehicleShare": "Vehicle share",
        "DirectCostAdvantage": "Direct cost advantage",
        "DirectAvailable": "Direct available",
        "IndirectAvailable": "Indirect route available",
        "VehicleLinkedCapital": "Vehicle-linked capital",
        "LPCapitalShare": "LP capital share",
        "SettlementTransferIncidence": "Transfer incidence",
        "VehicleCapitalFactor": "Vehicle capital factor",
    }
    rows = []
    for _, r in df[df["Variable / proxy"].isin(keep)].iterrows():
        rows.append([display_name.get(r["Variable / proxy"], r["Variable / proxy"]), r["Level"], r["Construction"], r["Used for"]])
    return TableSpec(
        "3",
        "Variable construction and empirical proxies.",
        "tab:variables",
        ["Variable", "Level", "Construction", "Used for"],
        ["0.17\\textwidth", "0.17\\textwidth", "0.46\\textwidth", "0.10\\textwidth"],
        rows,
        "All variables are generated from the reconstructed route and liquidity data. VehicleShare is conditional on indirect routed volume; all-route shares are used only as scope diagnostics.",
        landscape=True,
    )


def rq1_table() -> TableSpec:
    actual = read_table("actual_route_choice")
    core = read_table("core_panel_regressions")
    rows: list[list[object]] = [
        [
            "Direct cost adv. (fraction)",
            reg_cell(actual, Outcome="Actual vehicle share", Regressor="direct_cost_advantage"),
            reg_cell(core, Outcome="VehicleShare", Regressor="direct_cost_advantage_median", **{"Horizon (days)": "7"}),
            reg_cell(core, Outcome="VehicleShare", Regressor="direct_cost_advantage_median", **{"Horizon (days)": "30"}),
        ],
        [
            "Indirect-route avail.",
            reg_cell(actual, Outcome="Actual vehicle share", Regressor="vehicle_available"),
            reg_cell(core, Outcome="VehicleShare", Regressor="vehicle_available_share", **{"Horizon (days)": "7"}),
            reg_cell(core, Outcome="VehicleShare", Regressor="vehicle_available_share", **{"Horizon (days)": "30"}),
        ],
        [
            "Indirect-route quote quality",
            reg_cell(actual, Outcome="Actual vehicle share", Regressor="vehicle_quote_quality"),
            "",
            "",
        ],
        [
            "LP capital share",
            "",
            reg_cell(core, Outcome="VehicleShare", Regressor="lp_capital_share", **{"Horizon (days)": "7"}),
            "",
        ],
        [
            "Lagged vehicle share",
            "",
            "",
            reg_cell(core, Outcome="VehicleShare", Regressor="BridgeShare", **{"Horizon (days)": "30"}),
        ],
        [
            "FE",
            "Endpoint-pair x date",
            "Token and date",
            "Token and date",
        ],
        [
            "SE cluster",
            "Date",
            "Date",
            "Date",
        ],
        [
            "Obs.",
            value_cell(actual, "N", Outcome="Actual vehicle share", Regressor="direct_cost_advantage"),
            value_cell(core, "N", Outcome="VehicleShare", Regressor="direct_cost_advantage_median", **{"Horizon (days)": "7"}),
            value_cell(core, "N", Outcome="VehicleShare", Regressor="direct_cost_advantage_median", **{"Horizon (days)": "30"}),
        ],
    ]
    return TableSpec(
        "4",
        "Vehicle formation: route economics, availability, and realized route choice.",
        "tab:rq1-formation",
        [
            "",
            header_cell("(1)", "Actual", "vehicle share"),
            header_cell("(2)", "Vehicle share", RawLatex(r"$\tau=7$")),
            header_cell("(3)", "Vehicle share", RawLatex(r"$\tau=30$")),
        ],
        ["0.24\\textwidth", "0.19\\textwidth", "0.19\\textwidth", "0.19\\textwidth"],
        rows,
        "Cells report coefficients with p-values beneath them. Stars denote 10%, 5%, and 1% significance. DirectCostAdvantage is a direct-minus-indirect fraction of direct-route output, so a negative coefficient links stronger indirect-route performance to greater vehicle use.",
        landscape=True,
    )


def rq2_rq3_table() -> TableSpec:
    lp = read_table("lp_allocation_feedback")
    thresholds = read_table("persistence_thresholds")
    rows: list[list[object]] = [
        ["Panel A. Liquidity-route dynamics", "", "", "", "", ""],
        [
            "LP capital share",
            reg_cell(lp, Panel="A. Stock feedback", Outcome="VehicleShare", Regressor="lp_capital_share", **{"Horizon (days)": "7"}),
            "",
            "",
            "",
            "",
        ],
        [
            "Lagged vehicle share",
            "",
            reg_cell(lp, Panel="A. Stock feedback", Outcome="LPCapitalShare", Regressor="BridgeShare", **{"Horizon (days)": "7"}),
            reg_cell(lp, Panel="A. Stock feedback", Outcome="log VehicleLinkedCapital", Regressor="BridgeShare", **{"Horizon (days)": "7"}),
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in LPCapitalShare", Regressor="BridgeShare", **{"Horizon (days)": "30"}),
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in log VehicleLinkedCapital", Regressor="BridgeShare", **{"Horizon (days)": "30"}),
        ],
        [
            "Indirect-route avail.",
            "",
            "",
            "",
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in LPCapitalShare", Regressor="vehicle_available_share", **{"Horizon (days)": "30"}),
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in log VehicleLinkedCapital", Regressor="vehicle_available_share", **{"Horizon (days)": "30"}),
        ],
        [
            "Indirect-only avail.",
            "",
            "",
            "",
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in LPCapitalShare", Regressor="no_direct_vehicle_available_share", **{"Horizon (days)": "30"}),
            reg_cell(lp, Panel="B. LP stock change", Outcome="Change in log VehicleLinkedCapital", Regressor="no_direct_vehicle_available_share", **{"Horizon (days)": "30"}),
        ],
        ["FE", "Token and date", "Token and date", "Token and date", "Token and date", "Token and date"],
        ["SE cluster", "Date", "Date", "Date", "Date", "Date"],
        [
            "Obs.",
            value_cell(lp, "N", Panel="A. Stock feedback", Outcome="VehicleShare", Regressor="lp_capital_share", **{"Horizon (days)": "7"}),
            value_cell(lp, "N", Panel="A. Stock feedback", Outcome="LPCapitalShare", Regressor="BridgeShare", **{"Horizon (days)": "7"}),
            value_cell(lp, "N", Panel="A. Stock feedback", Outcome="log VehicleLinkedCapital", Regressor="BridgeShare", **{"Horizon (days)": "7"}),
            value_cell(lp, "N", Panel="B. LP stock change", Outcome="Change in LPCapitalShare", Regressor="BridgeShare", **{"Horizon (days)": "30"}),
            value_cell(lp, "N", Panel="B. LP stock change", Outcome="Change in log VehicleLinkedCapital", Regressor="BridgeShare", **{"Horizon (days)": "30"}),
        ],
        ["Panel B. Challenger displacement thresholds", "", "", "", "", ""],
    ]
    for _, r in thresholds.iterrows():
        rows.append([
            clean_sample(r["Challenger cost-edge bin"]),
            "",
            "",
            "",
            coef_p_cell(r["Mean incumbent VehicleShare change (pp)"], r["p"]),
            r["Incumbent days"],
        ])
    return TableSpec(
        "5",
        "Liquidity provision, persistence, and challenger displacement.",
        "tab:rq2-rq3-liquidity-persistence",
        [
            "",
            header_cell("(1)", "Vehicle share", RawLatex(r"$\tau=7$")),
            header_cell("(2)", "LP conc.", RawLatex(r"$\tau=7$")),
            header_cell("(3)", "Log LP liq.", RawLatex(r"$\tau=7$")),
            header_cell("(4)", "Chg. LP conc.", RawLatex(r"$\tau=30$")),
            header_cell("(5)", "Chg. log LP liq.", RawLatex(r"$\tau=30$")),
        ],
        ["0.22\\textwidth", "0.13\\textwidth", "0.13\\textwidth", "0.13\\textwidth", "0.13\\textwidth", "0.14\\textwidth"],
        rows,
        "Cells report coefficients with p-values beneath them. Panel A uses token and date fixed effects with date-clustered standard errors. Panel B reports incumbent share changes by challenger route-cost edge bins; the last column gives the number of incumbent days.",
        landscape=True,
    )


def stress_table() -> TableSpec:
    stress = read_table("p3_stress_rotation")
    et = read_table("stress_event_time")
    rows: list[list[object]] = [
        [
            "Stress event day",
            value_cell(stress, "Events", Panel="A. Main decomposed same-day effect", Estimate="WETH share change"),
            coef_p_cell(value_cell(stress, "Effect", Panel="A. Main decomposed same-day effect", Estimate="WETH share change"), value_cell(stress, "p", Panel="A. Main decomposed same-day effect", Estimate="WETH share change")),
            coef_p_cell(value_cell(stress, "Effect", Panel="A. Main decomposed same-day effect", Estimate="Stable share change"), value_cell(stress, "p", Panel="A. Main decomposed same-day effect", Estimate="Stable share change")),
            coef_p_cell(value_cell(stress, "Effect", Panel="A. Main decomposed same-day effect", Estimate="WETH-minus-stable change"), value_cell(stress, "p", Panel="A. Main decomposed same-day effect", Estimate="WETH-minus-stable change")),
            coef_p_cell(value_cell(stress, "Effect", Panel="A. Main decomposed same-day effect", Estimate="Aggregate direct-route share change"), value_cell(stress, "p", Panel="A. Main decomposed same-day effect", Estimate="Aggregate direct-route share change")),
            coef_p_cell(value_cell(stress, "Effect", Panel="A. Main decomposed same-day effect", Estimate="Log indirect-route volume change"), value_cell(stress, "p", Panel="A. Main decomposed same-day effect", Estimate="Log indirect-route volume change")),
        ],
        ["Panel B. WETH-minus-stable event-time gap", "", "", "", "", "", ""],
        [
            "Gap change",
            value_cell(et, "Events", Window="event day", Outcome="gap change pp"),
            coef_p_cell(value_cell(et, "Mean effect (pp)", Window="pre -14 to -1", Outcome="gap change pp"), value_cell(et, "p", Window="pre -14 to -1", Outcome="gap change pp")),
            coef_p_cell(value_cell(et, "Mean effect (pp)", Window="event day", Outcome="gap change pp"), value_cell(et, "p", Window="event day", Outcome="gap change pp")),
            coef_p_cell(value_cell(et, "Mean effect (pp)", Window="post 1 to 7", Outcome="gap change pp"), value_cell(et, "p", Window="post 1 to 7", Outcome="gap change pp")),
            coef_p_cell(value_cell(et, "Mean effect (pp)", Window="post 8 to 30", Outcome="gap change pp"), value_cell(et, "p", Window="post 8 to 30", Outcome="gap change pp")),
            "",
        ],
        ["Panel C. Threshold and overlap sensitivity", "", "", "", "", "", ""],
    ]
    for _, r in stress[stress["Panel"].eq("B. Threshold/overlap sensitivity")].iterrows():
        estimate = (
            r["Estimate"]
            .replace("all events, threshold ", "All, ")
            .replace("top 20, threshold ", "Top 20, ")
            .replace("non-overlap, threshold ", "Nonoverlap, ")
        )
        rows.append([estimate, r["Events"], "", "", coef_p_cell(r["Effect"], r["p"]), "", r["Interpretation"].replace("negative share ", "neg. share ")])
    return TableSpec(
        "6",
        "Stress rotation inside common route opportunities.",
        "tab:rq4-stress",
        [
            "",
            "Events",
            header_cell("(1)", "WETH", "or pre gap"),
            header_cell("(2)", "Stable", "or event gap"),
            header_cell("(3)", "Gap", "or post 1-7"),
            header_cell("(4)", "Direct", "or post 8-30"),
            header_cell("(5)", "Indir. vol.", "or note"),
        ],
        ["0.21\\textwidth", "0.06\\textwidth", "0.12\\textwidth", "0.12\\textwidth", "0.12\\textwidth", "0.12\\textwidth", "0.15\\textwidth"],
        rows,
        "Cells report event effects with p-values beneath them. Panel A is the same-day decomposition relative to a prior 28-day baseline. Panel B uses the same WETH-minus-stable gap in event-time windows; pre-movement means the result should be written as a common-support rotation, not a clean surprise-shock causal design.",
        landscape=True,
    )


def architecture_table() -> TableSpec:
    main = read_table("p4a_v3_opportunity")
    dose = read_table("v3_dose_response")
    rows: list[list[object]] = [
        [
            "Post V3",
            reg_cell(main, estimate_col="Post-V3 effect", Outcome="No-direct WETH availability"),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q1 weakest", "Outcome": "Direct-route availability"}),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q1 weakest", "Outcome": "No-direct WETH availability"}),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q2", "Outcome": "Direct-route availability"}),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q2", "Outcome": "No-direct WETH availability"}),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q4 strongest", "Outcome": "Direct-route availability"}),
            reg_cell(dose, estimate_col="Post-V3 effect", **{"Pre-V3 direct availability quartile": "Q4 strongest", "Outcome": "No-direct WETH availability"}),
        ],
        [
            "Pair FE",
            "yes",
            "yes",
            "yes",
            "yes",
            "yes",
            "yes",
            "yes",
        ],
        [
            "SE cluster",
            "Pair",
            "Pair",
            "Pair",
            "Pair",
            "Pair",
            "Pair",
            "Pair",
        ],
        [
            "Obs.",
            value_cell(main, "Rows", Outcome="No-direct WETH availability"),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q1 weakest", "Outcome": "Direct-route availability"}),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q1 weakest", "Outcome": "No-direct WETH availability"}),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q2", "Outcome": "Direct-route availability"}),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q2", "Outcome": "No-direct WETH availability"}),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q4 strongest", "Outcome": "Direct-route availability"}),
            value_cell(dose, "Rows", **{"Pre-V3 direct availability quartile": "Q4 strongest", "Outcome": "No-direct WETH availability"}),
        ],
    ]
    return TableSpec(
        "7",
        "Architecture and direct-route opportunity.",
        "tab:rq5-architecture",
        [
            "",
            header_cell("(1)", "No-direct", "WETH"),
            header_cell("(2)", "Q1", "direct"),
            header_cell("(3)", "Q1", "no-direct"),
            header_cell("(4)", "Q2", "direct"),
            header_cell("(5)", "Q2", "no-direct"),
            header_cell("(6)", "Q4", "direct"),
            header_cell("(7)", "Q4", "no-direct"),
        ],
        ["0.14\\textwidth", "0.10\\textwidth", "0.10\\textwidth", "0.11\\textwidth", "0.10\\textwidth", "0.11\\textwidth", "0.10\\textwidth", "0.11\\textwidth"],
        rows,
        "Dependent variables are route-opportunity measures. Cells report post-V3 effects in percentage points with p-values beneath them. The table is scoped to route opportunity around V3 and should not be read as a broad causal launch effect for every V3 outcome.",
        landscape=True,
    )


def settlement_table() -> TableSpec:
    settle = read_table("p4b_v4_settlement")
    persist = read_table("v4_route_use_persistence")
    rows: list[list[object]] = [
        [
            "V4 - V3 transfer inc.",
            coef_p_cell(value_cell(settle, "Difference / balance", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "All"}), value_cell(settle, "p", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "All"})),
            coef_p_cell(value_cell(settle, "Difference / balance", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Small"}), value_cell(settle, "p", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Small"})),
            coef_p_cell(value_cell(settle, "Difference / balance", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Medium"}), value_cell(settle, "p", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Medium"})),
            coef_p_cell(value_cell(settle, "Difference / balance", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Large"}), value_cell(settle, "p", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Large"})),
            "",
            "",
        ],
        [
            "V3 transfer inc.",
            value_cell(settle, "V3", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "All"}),
            value_cell(settle, "V3", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Small"}),
            value_cell(settle, "V3", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Medium"}),
            value_cell(settle, "V3", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Large"}),
            "",
            "",
        ],
        [
            "V4 transfer inc.",
            value_cell(settle, "V4", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "All"}),
            value_cell(settle, "V4", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Small"}),
            value_cell(settle, "V4", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Medium"}),
            value_cell(settle, "V4", Panel="A. Transfer incidence by route-size bin", **{"Sample / diagnostic": "Route size: Large"}),
            "",
            "",
        ],
        ["Panel B. Matched-cell route-use persistence", "", "", "", "", "", ""],
        [
            "Log V3 route count",
            "",
            "",
            "",
            "",
            reg_cell(persist, estimate_col="Estimate", Outcome="Log V4 route count"),
            "",
        ],
        [
            "Log V3 route volume",
            "",
            "",
            "",
            "",
            "",
            reg_cell(persist, estimate_col="Estimate", Outcome="Log V4 route volume"),
        ],
        [
            "Week FE / vehicle FE",
            "",
            "",
            "",
            "",
            "yes",
            "yes",
        ],
        [
            "Week clusters",
            "",
            "",
            "",
            "",
            value_cell(persist, "Week clusters", Outcome="Log V4 route count"),
            value_cell(persist, "Week clusters", Outcome="Log V4 route volume"),
        ],
    ]
    return TableSpec(
        "8",
        "Settlement design, physical transfer incidence, and matched-cell route use.",
        "tab:rq6-settlement",
        [
            "",
            header_cell("(1)", "All", "sizes"),
            header_cell("(2)", "Small"),
            header_cell("(3)", "Medium"),
            header_cell("(4)", "Large"),
            header_cell("(5)", "Log V4", "route count"),
            header_cell("(6)", "Log V4", "route vol."),
        ],
        ["0.20\\textwidth", "0.11\\textwidth", "0.10\\textwidth", "0.10\\textwidth", "0.10\\textwidth", "0.14\\textwidth", "0.14\\textwidth"],
        rows,
        "Columns (1)-(4) compare matched V3 and V4 route units; cells report transfer-incidence gaps with p-values beneath them. Columns (5)-(6) are matched endpoint-vehicle-week regressions of V4 route use on V3 route use.",
        landscape=True,
    )


def common_pool_capital_table() -> TableSpec:
    common = read_table("common_pool_capital")
    het = read_table("common_pool_capital_heterogeneity")
    rows: list[list[object]] = [
        [
            "Market capital factor",
            reg_cell(common, **{"Sample / specification": "Full sample", "Regressor": "market_capital_factor_loo"}),
            reg_cell(common, **{"Sample / specification": "Stress interaction", "Regressor": "market_capital_factor_loo"}),
            reg_cell(het, Sample="High average VehicleShare vehicles", Regressor="market_capital_factor_loo"),
            reg_cell(het, Sample="Low average VehicleShare vehicles", Regressor="market_capital_factor_loo"),
            reg_cell(het, Sample="Excluding top 1% mean-capital pools", Regressor="market_capital_factor_loo"),
        ],
        [
            "Vehicle capital factor",
            reg_cell(common, **{"Sample / specification": "Full sample", "Regressor": "vehicle_capital_factor_loo"}),
            reg_cell(common, **{"Sample / specification": "Stress interaction", "Regressor": "vehicle_capital_factor_loo"}),
            reg_cell(het, Sample="High average VehicleShare vehicles", Regressor="vehicle_capital_factor_loo"),
            reg_cell(het, Sample="Low average VehicleShare vehicles", Regressor="vehicle_capital_factor_loo"),
            reg_cell(het, Sample="Excluding top 1% mean-capital pools", Regressor="vehicle_capital_factor_loo"),
        ],
        [
            "Vehicle factor x stress",
            "",
            reg_cell(common, **{"Sample / specification": "Stress interaction", "Regressor": "vehicle_capital_factor_x_stress"}),
            "",
            "",
            "",
        ],
        ["Pool-vehicle FE", "yes", "yes", "yes", "yes", "yes"],
        ["SE cluster", "Date", "Date", "Date", "Date", "Date"],
        [
            "Obs.",
            value_cell(common, "N", **{"Sample / specification": "Full sample", "Regressor": "vehicle_capital_factor_loo"}),
            value_cell(common, "N", **{"Sample / specification": "Stress interaction", "Regressor": "vehicle_capital_factor_loo"}),
            value_cell(het, "N", Sample="High average VehicleShare vehicles", Regressor="vehicle_capital_factor_loo"),
            value_cell(het, "N", Sample="Low average VehicleShare vehicles", Regressor="vehicle_capital_factor_loo"),
            value_cell(het, "N", Sample="Excluding top 1% mean-capital pools", Regressor="vehicle_capital_factor_loo"),
        ],
    ]
    return TableSpec(
        "9",
        "Common deposited capital across pools linked to the same vehicle.",
        "tab:rq7-common-pool-capital",
        [
            "",
            header_cell("(1)", "Full", "sample"),
            header_cell("(2)", "Stress", "interact."),
            header_cell("(3)", "High", "vehicle use"),
            header_cell("(4)", "Low", "vehicle use"),
            header_cell("(5)", "Excl.", "top pools"),
        ],
        ["0.22\\textwidth", "0.13\\textwidth", "0.14\\textwidth", "0.13\\textwidth", "0.13\\textwidth", "0.13\\textwidth"],
        rows,
        "Dependent variable is the daily pool-level log change in deposited capital. Cells report coefficients with p-values beneath them. Regressions include pool-vehicle fixed effects and date-clustered standard errors. The vehicle factor is leave-one-out across other pools linked to the same vehicle.",
        landscape=True,
    )


def specification_table() -> TableSpec:
    df = read_table("specification_registry")
    compact = {
        "P1 availability/thin-direct": "P1 availability",
        "P2 liquidity-route dynamics": "P2 dynamics",
        "P3 impact stress": "P3 stress",
        "P4a V3 opportunity": "P4a V3",
        "P4b V4 settlement": "P4b V4",
        "endpoint-pair x day x trade size": "pair x day x size",
        "event x common endpoint-pair set": "event x pair set",
        "endpoint-pair x month": "pair x month",
        "matched route unit; token x week": "route unit; token-week",
        "V2/Sushi V2/V3 exact quoteable venues": "quoteable venues",
        "WETH downside event days": "WETH downside events",
        "balanced V3 launch-window pairs": "V3 launch pairs",
        "matched V3/V4 cells; LP panel around launch": "matched V3/V4 cells",
        "route availability and DirectCostAdvantage": "availability; direct cost adv.",
        "VehicleShare; LP capital share/log capital": "share; LP capital",
        "WETH-minus-stable BridgeShare": "WETH-stable share",
        "no-direct/WETH-available indicator": "no-direct WETH",
        "transfer incidence; LP liquidity response": "transfer inc.; LP response",
        "LP capital share; current BridgeShare": "LP capital; lagged share",
        "event-day WETH downside stress": "WETH stress day",
        "V4 route unit; post x netting exposure": "V4; post x netting",
        "endpoint-pair-day aggregation": "pair-day aggregation",
        "token/date FE; date-clustered SE": "token/date FE; date SE",
        "matched-cell tests; token/week FE": "matched tests; token/week FE",
        "direct available 72.1%": "direct avail. 72.1%",
        "prior 28-day common-pair baseline": "prior 28-day baseline",
        "pre/post balanced pair panel": "balanced pair panel",
        "V3 transfer incidence 100%": "V3 transfer 100%",
        "availability and thin-direct execution protection": "availability/thin-direct protection",
        "relative persistence; absolute capital is specification-sensitive": "relative persistence; level sensitivity",
        "same-day rotation away from WETH toward stable vehicles": "same-day WETH-to-stable rotation",
        "settlement netting lowers movement and predicts LP supply response": "netting lowers movement; LP response",
    }

    def c(value: object) -> object:
        text = str(value)
        if " no-direct rows; thin-direct DirectCostAdvantage " in text:
            return text.replace(
                " no-direct rows; thin-direct DirectCostAdvantage ",
                " no-direct; direct cost adv. ",
            )
        return compact.get(text, value)

    rows = []
    for _, r in df.iterrows():
        rows.append([
            c(r["Test"]),
            c(r["Unit"]),
            c(r["Sample"]),
            c(r["Outcome"]),
            c(r["Regressor / treatment"]),
            c(r["FE / SE"]),
            c(r["Main estimate"]),
            c(r["Economic interpretation"]),
        ])
    return TableSpec(
        "10",
        "Specification registry for paper-facing tests.",
        "tab:specification-registry",
        ["Test", "Unit", "Sample", "Outcome", "Treatment / regressor", "FE / SE", "Main estimate", "Interpretation"],
        ["0.09\\textwidth", "0.10\\textwidth", "0.12\\textwidth", "0.11\\textwidth", "0.12\\textwidth", "0.11\\textwidth", "0.14\\textwidth", "0.15\\textwidth"],
        rows,
        "This registry fixes the paper-facing unit, sample, outcome, treatment or regressor, inference convention, headline estimate, and bounded interpretation for each main test.",
        landscape=True,
    )


def document(tables: list[TableSpec]) -> str:
    parts = [
        r"\documentclass[12pt]{article}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{booktabs}",
        r"\usepackage{threeparttable}",
        r"\usepackage{makecell}",
        r"\usepackage{array}",
        r"\usepackage{pdflscape}",
        r"\usepackage{setspace}",
        r"\usepackage{caption}",
        r"\captionsetup{font=small,labelfont=bf}",
        r"\newcommand{\ra}[1]{\renewcommand{\arraystretch}{#1}}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\Large Results Evidence Map for \textit{The Making of Vehicle Currencies}}\\[0.5em]",
        r"{\normalsize Internal results packet. Not manuscript prose.}",
        r"\end{center}",
        r"\onehalfspacing",
        r"\section*{Purpose and Reading Order}",
        (
            "This document reorganizes the current empirical evidence around research questions, "
            "not around the order in which the analyses were built. Table \\ref{tab:rq-evidence-map} "
            "is the master map: every empirical claim must point to one research question, one "
            "proxy, and one primary table. The tables use a JFE-style hierarchy: compact headline "
            "estimates in the main rows, conventional significance stars shown on estimates, p-values shown explicitly, fixed effects and clustering "
            "reported in notes, and weaker or conditional evidence labelled as such."
        ),
        r"\section*{Interpretation Rules}",
        r"\begin{enumerate}",
        r"\item Definitions are not propositions. Vehicle use is defined by intermediate-token use in indirect routes; the propositions are about emergence, persistence, rotation, architecture, and settlement design.",
        r"\item ``Value'' is not a primitive. Feasibility, depth/capacity, execution-cost advantage, settlement-transfer incidence, and LP-liquidity response are the measurable objects.",
        r"\item WETH, stablecoins, V3, and V4 are empirical test beds. They should not be written as the propositions themselves.",
        r"\item Conventional significance stars are shown on estimates ($^{*}$, $^{**}$, $^{***}$ for 10\%, 5\%, and 1\%). P-values are also reported directly so significance is not hidden behind stars. Weak, noisy, or pre-trending results are labelled in the table notes.",
        r"\end{enumerate}",
    ]
    for spec in tables:
        parts.append(table_tex(spec))
    parts.extend([r"\end{document}", ""])
    return "\n\n".join(parts)


def build_specs() -> list[TableSpec]:
    return [
        evidence_map(),
        scope_table(),
        variable_table(),
        rq1_table(),
        rq2_rq3_table(),
        stress_table(),
        architecture_table(),
        settlement_table(),
        common_pool_capital_table(),
        specification_table(),
    ]


def _wrap_cell(value: object, width: int) -> list[str]:
    text = str(value)
    if isinstance(value, RawLatex):
        text = value.text
    replacements = [
        (r"$^{***}$", "***"),
        (r"$^{**}$", "**"),
        (r"$^{*}$", "*"),
        (r"\textit{", ""),
        (r"\textbackslash{}", "\\"),
        (r"\&", "&"),
        (r"\%", "%"),
        (r"\$", "$"),
        (r"\_", "_"),
        (r"$<$", "<"),
        ("$", ""),
        ("^", ""),
        ("{", ""),
        ("}", ""),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return textwrap.wrap(text, width=width, replace_whitespace=False) or [""]


def _pdf_text_page(pdf, title: str, body: str, *, fontsize: int = 9) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(11, 8.5))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.05, 0.95, title, fontsize=16, fontweight="bold", va="top")
    wrapped: list[str] = []
    for para in body.split("\n"):
        if not para.strip():
            wrapped.append("")
        else:
            wrapped.extend(textwrap.wrap(para, width=132, replace_whitespace=False))
    ax.text(0.05, 0.89, "\n".join(wrapped), fontsize=fontsize, va="top", family="DejaVu Sans Mono")
    pdf.savefig(fig)
    plt.close(fig)


def _pdf_table_page(pdf, spec: TableSpec) -> None:
    import matplotlib.pyplot as plt

    col_count = max(len(spec.columns), 1)
    widths = [max(10, int(118 / col_count))] * col_count
    rows = [spec.columns] + spec.rows
    lines: list[str] = []
    for idx, row in enumerate(rows):
        normalized = list(row) + [""] * (col_count - len(row))
        wrapped_cells = [_wrap_cell(value, width) for value, width in zip(normalized[:col_count], widths)]
        height = max(len(cell) for cell in wrapped_cells)
        for line_idx in range(height):
            parts = [
                cell[line_idx] if line_idx < len(cell) else ""
                for cell in wrapped_cells
            ]
            lines.append(" | ".join(part.ljust(width) for part, width in zip(parts, widths)).rstrip())
        if idx == 0:
            lines.append("-" * min(150, sum(widths) + 3 * (col_count - 1)))

    chunk_size = 42
    chunks = [lines[i : i + chunk_size] for i in range(0, len(lines), chunk_size)] or [[]]
    for page_idx, chunk in enumerate(chunks, start=1):
        fig = plt.figure(figsize=(11, 8.5))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        suffix = f" ({page_idx}/{len(chunks)})" if len(chunks) > 1 else ""
        ax.text(
            0.04,
            0.965,
            f"Table {spec.number}. {spec.caption}{suffix}",
            fontsize=14,
            fontweight="bold",
            va="top",
        )
        ax.text(0.04, 0.91, "\n".join(chunk), fontsize=6.1, va="top", family="DejaVu Sans Mono")
        note = textwrap.fill(f"Notes: {spec.note}", width=150)
        ax.text(0.04, 0.055, note, fontsize=6.8, va="bottom", family="DejaVu Sans")
        pdf.savefig(fig)
        plt.close(fig)


def compile_latex_pdf() -> bool:
    engines: list[list[str]] = []
    tectonic = shutil.which("tectonic")
    if tectonic:
        engines.append([tectonic, "--chatter", "minimal", "--outdir", str(PAPER), str(OUT_TEX)])
    latexmk = shutil.which("latexmk")
    if latexmk:
        engines.append([
            latexmk,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-outdir={PAPER}",
            str(OUT_TEX),
        ])
    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        engines.append([
            pdflatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={PAPER}",
            str(OUT_TEX),
        ])

    for cmd in engines:
        print("+ " + " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=ROOT, check=True)
        if cmd[0] == pdflatex:
            subprocess.run(cmd, cwd=ROOT, check=True)
        print(f"wrote {OUT_PDF}")
        return True
    return False


def write_matplotlib_pdf(specs: list[TableSpec]) -> None:
    from matplotlib.backends.backend_pdf import PdfPages

    PAPER.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT_PDF) as pdf:
        _pdf_text_page(
            pdf,
            "Results Evidence Map for The Making of Vehicle Currencies",
            (
                "Internal results packet. Not manuscript prose.\n\n"
                "This PDF is generated from the same table specifications as "
                "paper/results_evidence_map.tex. It uses matplotlib's PDF backend so the "
                "review packet remains reproducible on machines without a LaTeX installation.\n\n"
                "Interpretation rules: definitions are not propositions; value is measured "
                "through feasibility, depth/capacity, execution-cost advantage, settlement-transfer "
                "incidence, and LP-liquidity response; WETH, stablecoins, V3, and V4 are empirical "
                "test beds rather than the propositions themselves."
            ),
        )
        for spec in specs:
            _pdf_table_page(pdf, spec)
    print(f"wrote {OUT_PDF}")


def write_pdf(specs: list[TableSpec]) -> None:
    if compile_latex_pdf():
        return
    print("No TeX engine found; writing matplotlib review PDF instead.", flush=True)
    write_matplotlib_pdf(specs)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        action="store_true",
        help=(
            "Also write paper/results_evidence_map.pdf. Uses tectonic/latexmk/pdflatex "
            "when available, otherwise falls back to matplotlib's PDF backend."
        ),
    )
    args = parser.parse_args(argv)
    PAPER.mkdir(parents=True, exist_ok=True)
    specs = build_specs()
    OUT_TEX.write_text(document(specs), encoding="utf-8")
    print(f"wrote {OUT_TEX}")
    if args.pdf:
        write_pdf(specs)


if __name__ == "__main__":
    main()
