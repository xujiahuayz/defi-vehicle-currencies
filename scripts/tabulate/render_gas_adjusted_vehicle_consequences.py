#!/usr/bin/env python3
"""Render the compact gas consequence panel, appendix checks, and value macros."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


INPUT = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences_support.jsonl"
OUTPUT = OUTPUT_DIR / "tables/gas_adjusted_vehicle_consequences.tex"
APPENDIX = OUTPUT_DIR / "tables/gas_adjusted_vehicle_consequences_appendix.tex"
MACROS = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences_values.tex"
SIZE_LABELS = {
    "all": "All routes",
    "usd_100_to_999": r"\$100--999",
    "usd_1k_to_9_999": r"\$1,000--9,999",
    "usd_10k_to_99_999": r"\$10,000--99,999",
    "usd_100k_plus": r"\$100,000 and above",
}


def _row(frame: pd.DataFrame, scenario: str, size_group: str) -> pd.Series:
    matched = frame[
        frame["gas_scenario"].eq(scenario) & frame["size_group"].eq(size_group)
    ]
    if len(matched) != 1:
        raise ValueError(f"expected one gas consequence row: {scenario}/{size_group}")
    return matched.iloc[0]


def _validation_row(support: pd.DataFrame, sample: str) -> pd.Series:
    matched = support[
        support["record_type"].eq("held_out_gas_validation")
        & support["sample"].eq(sample)
    ]
    if len(matched) != 1:
        raise ValueError(f"expected one held-out gas validation row: {sample}")
    return matched.iloc[0]


def render(frame: pd.DataFrame) -> str:
    """Return the compact main-text panel: gross output versus net of gas."""

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrr@{}}",
        r"\toprule",
        r" & Routes & \multicolumn{2}{c}{Lower-output route [\%]} & \multicolumn{2}{c}{Weighted shortfall [bp]} \\",
        r"\cmidrule(lr){3-4}\cmidrule(l){5-6}",
        r"Input value & & Gross & Net of gas & Gross & Net of gas \\",
        r"\midrule",
    ]
    for size_group, label in SIZE_LABELS.items():
        gross = _row(frame, "gross", size_group)
        central = _row(frame, "central", size_group)
        lines.append(
            f"{label} & {int(central['routes']):,} & "
            f"{100 * gross['lower_output_route_share']:.1f} & "
            f"{100 * central['lower_output_route_share']:.1f} & "
            f"{gross['input_value_weighted_shortfall_bps']:.2f} & "
            f"{central['input_value_weighted_shortfall_bps']:.2f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}"])
    return "\n".join(lines) + "\n"


def render_appendix(frame: pd.DataFrame, support: pd.DataFrame) -> str:
    """Return prediction validation and path-specific interquartile bounds."""

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrrr@{}}",
        r"\toprule",
        r"\multicolumn{7}{@{}l}{\textit{Panel A. Held-out prediction accuracy}} \\",
        r"Sample & Test routes & Actual gas & MAE & MAPE [\%] & Legs-only MAPE [\%] & IQR coverage [\%] \\",
        r"\midrule",
    ]
    for sample, label in (
        ("all_routes", "All routes"),
        ("exact_two_leg_routes", "Two-leg routes"),
    ):
        row = _validation_row(support, sample)
        lines.append(
            f"{label} & {int(row['test_transactions']):,} & "
            f"{float(row['median_actual_gas_units']):,.0f} & "
            f"{float(row['median_absolute_error_gas_units']):,.0f} & "
            f"{100 * float(row['median_absolute_percentage_error']):.1f} & "
            f"{100 * float(row['legs_only_median_absolute_percentage_error']):.1f} & "
            f"{100 * float(row['interquartile_interval_coverage']):.1f} \\\\"
        )
    lines.extend(
        [
            r"\addlinespace",
            r"\multicolumn{7}{@{}l}{\textit{Panel B. Path-specific interquartile gas bounds}} \\",
            r" & \multicolumn{3}{c}{Lower-output route [\%]} & \multicolumn{3}{c}{Weighted shortfall [bp]} \\",
            r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
            r"Input value & Central & Favorable & Unfavorable & Central & Favorable & Unfavorable \\",
            r"\midrule",
        ]
    )
    for size_group, label in SIZE_LABELS.items():
        central = _row(frame, "central", size_group)
        favorable = _row(frame, "chosen_favorable_bound", size_group)
        unfavorable = _row(frame, "chosen_unfavorable_bound", size_group)
        lines.append(
            f"{label} & {100 * central['lower_output_route_share']:.1f} & "
            f"{100 * favorable['lower_output_route_share']:.1f} & "
            f"{100 * unfavorable['lower_output_route_share']:.1f} & "
            f"{central['input_value_weighted_shortfall_bps']:.2f} & "
            f"{favorable['input_value_weighted_shortfall_bps']:.2f} & "
            f"{unfavorable['input_value_weighted_shortfall_bps']:.2f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}"])
    return "\n".join(lines) + "\n"


def render_macros(frame: pd.DataFrame) -> str:
    """Return main-text values for all routes and the smallest size cell."""

    overall_gross = _row(frame, "gross", "all")
    overall_central = _row(frame, "central", "all")
    small_gross = _row(frame, "gross", "usd_100_to_999")
    small_central = _row(frame, "central", "usd_100_to_999")
    values = {
        "GasConsequenceOverallGrossLowerShare": (
            f"{100 * overall_gross['lower_output_route_share']:.1f}\\%"
        ),
        "GasConsequenceOverallNetLowerShare": (
            f"{100 * overall_central['lower_output_route_share']:.1f}\\%"
        ),
        "GasConsequenceOverallGrossShortfallBp": (
            f"{overall_gross['input_value_weighted_shortfall_bps']:.2f}"
        ),
        "GasConsequenceOverallNetShortfallBp": (
            f"{overall_central['input_value_weighted_shortfall_bps']:.2f}"
        ),
        "GasConsequenceSmallGrossLowerShare": (
            f"{100 * small_gross['lower_output_route_share']:.1f}\\%"
        ),
        "GasConsequenceSmallNetLowerShare": (
            f"{100 * small_central['lower_output_route_share']:.1f}\\%"
        ),
        "GasConsequenceSmallGrossShortfallBp": (
            f"{small_gross['input_value_weighted_shortfall_bps']:.2f}"
        ),
        "GasConsequenceSmallNetShortfallBp": (
            f"{small_central['input_value_weighted_shortfall_bps']:.2f}"
        ),
    }
    lines = [
        "% Generated by scripts/tabulate/render_gas_adjusted_vehicle_consequences.py; do not edit."
    ]
    lines.extend(rf"\newcommand{{\{name}}}{{{value}}}" for name, value in values.items())
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        temporary.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--appendix", type=Path, default=APPENDIX)
    parser.add_argument("--macros", type=Path, default=MACROS)
    args = parser.parse_args()
    frame = pd.read_json(args.input, lines=True)
    support = pd.read_json(args.support, lines=True)
    _write(args.output, render(frame))
    _write(args.appendix, render_appendix(frame, support))
    _write(args.macros, render_macros(frame))
    print(f"wrote {args.output}, {args.appendix}, and {args.macros}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
