#!/usr/bin/env python3
"""Render the gross and gas-adjusted vehicle-output comparison."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


INPUT = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences.jsonl"
OUTPUT = OUTPUT_DIR / "tables/gas_adjusted_vehicle_consequences.tex"
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


def render(frame: pd.DataFrame) -> str:
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}Xrrrrr@{}}",
        r"\toprule",
        r" & Routes & Gross & Gas-adjusted & Favorable & Unfavorable \\",
        r"\midrule",
        r"\multicolumn{6}{l}{\textit{Panel A. Share using the lower-output vehicle path (\%)}} \\",
    ]
    for size_group, label in SIZE_LABELS.items():
        gross = _row(frame, "gross", size_group)
        central = _row(frame, "central", size_group)
        favorable = _row(frame, "chosen_favorable_bound", size_group)
        unfavorable = _row(frame, "chosen_unfavorable_bound", size_group)
        lines.append(
            f"{label} & {int(central['routes']):,} & "
            f"{100 * gross['lower_output_route_share']:.1f} & "
            f"{100 * central['lower_output_route_share']:.1f} & "
            f"{100 * favorable['lower_output_route_share']:.1f} & "
            f"{100 * unfavorable['lower_output_route_share']:.1f} \\\\" 
        )
    lines.extend(
        [
            r"\addlinespace",
            r"\multicolumn{6}{l}{\textit{Panel B. Input-value-weighted output shortfall (basis points)}} \\",
        ]
    )
    for size_group, label in SIZE_LABELS.items():
        gross = _row(frame, "gross", size_group)
        central = _row(frame, "central", size_group)
        favorable = _row(frame, "chosen_favorable_bound", size_group)
        unfavorable = _row(frame, "chosen_unfavorable_bound", size_group)
        lines.append(
            f"{label} & {int(central['routes']):,} & "
            f"{gross['input_value_weighted_shortfall_bps']:.2f} & "
            f"{central['input_value_weighted_shortfall_bps']:.2f} & "
            f"{favorable['input_value_weighted_shortfall_bps']:.2f} & "
            f"{unfavorable['input_value_weighted_shortfall_bps']:.2f} \\\\" 
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    frame = pd.read_json(args.input, lines=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(render(frame), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

