#!/usr/bin/env python3
"""Render the paper's within-day intermediary-role control ladder.

Each cell is selected by its full scientific identity (specification, sample and
term) rather than by row order, so a reordering of the exhibit cannot silently
move a five-token magnitude into a thirty-seven-token cell.
"""

from __future__ import annotations

import json
import math

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "excess_use_date_fe_ladder.jsonl"
ALL = "all_endpoint_supported"
DASH = "---"
SPECIFICATIONS = (
    ("L1 pooled type dummies", "Pooled"),
    ("L2 + date FE", "Date FE"),
    ("L3 + date FE + own demand share", "{}+ demand"),
    ("L4 two-way token + date FE", "{}+ currency FE"),
)


def _cell(rows: list[dict], spec: str, term: str) -> dict | None:
    matches = [r for r in rows if r["spec"] == spec and r["sample"] == ALL and r["term"] == term]
    if len(matches) > 1:
        raise ValueError(f"ladder exhibit has {len(matches)} rows for {spec}/{term}")
    return matches[0] if matches else None


def _pp(row: dict | None) -> str:
    if row is None:
        return DASH
    value = float(row["beta"])
    if not math.isfinite(value):
        raise ValueError("a displayed coefficient must be finite")
    return f"${value:+.2f}{_stars(float(row['p']))}$"


def _pp_se(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"({float(row['se']):.2f})"


def _slope_pp(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"${float(row['beta']):+.2f}{_stars(float(row['p']))}$"


def _slope_pp_se(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"({float(row['se']):.2f})"


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def render_within_day_ladder(rows: list[dict]) -> str:
    models: list[dict[str, dict | None]] = []
    for spec, _label in SPECIFICATIONS:
        native = _cell(rows, spec, "native")
        stable = _cell(rows, spec, "stable")
        demand = _cell(rows, spec, "demand")
        anchor = demand or native or stable
        if anchor is None:
            raise ValueError(f"ladder exhibit lacks model {spec}")
        for field in ("n", "dates", "tokens", "r_squared"):
            if field not in anchor:
                raise ValueError(f"ladder model {spec} lacks {field}")
        models.append(
            {"native": native, "stable": stable, "demand": demand, "anchor": anchor}
        )

    def coefficient_row(label: str, term: str, formatter) -> list[str]:
        return [label, *(formatter(model[term]) for model in models)]

    body: list[str] = []
    for label, term, coefficient_formatter, se_formatter in (
        ("Native currency", "native", _pp, _pp_se),
        ("Stablecoin", "stable", _pp, _pp_se),
        (
            r"Own endpoint-demand share ($D_{a,t}$)",
            "demand",
            _slope_pp,
            _slope_pp_se,
        ),
    ):
        body.append(" & ".join(coefficient_row(label, term, coefficient_formatter)) + r" \\")
        body.append(" & ".join(coefficient_row("", term, se_formatter)) + r" \\")

    anchors = [model["anchor"] for model in models]
    body.extend(
        [
            r"\addlinespace",
            "$R^2$ & " + " & ".join(f"{float(row['r_squared']):.3f}" for row in anchors) + r" \\",
            "Observations & " + " & ".join(f"{int(row['n']):,}" for row in anchors) + r" \\",
            "Currencies & " + " & ".join(f"{int(row['tokens']):,}" for row in anchors) + r" \\",
            "Dates & " + " & ".join(f"{int(row['dates']):,}" for row in anchors) + r" \\",
            r"Date fixed effects & No & Yes & Yes & Yes \\",
            r"Currency fixed effects & No & No & No & Yes \\",
        ]
    )
    return "\n".join(
        [
            r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{4}{>{\centering\arraybackslash}p{0.92in}}@{}}",
            r"\toprule",
            r" & \multicolumn{4}{c}{Intermediary episode share ($I_{a,t}$) [pp]} \\",
            r"\cmidrule(lr){2-5}",
            r" & (1) & (2) & (3) & (4) \\",
            " & " + " & ".join(label for _spec, label in SPECIFICATIONS) + r" \\",
            r"\midrule",
            *body,
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    ) + "\n"


def main() -> int:
    records = [
        json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()
    ]
    write_table_artifacts(
        "within_day_ladder",
        render_within_day_ladder(records),
        preview_width="7.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
