#!/usr/bin/env python3
"""Render the canonical variable-notation and construction table."""

from __future__ import annotations

from ddvc.variable_registry import NOTATION_DEFINITIONS, specs_by_group
from utils import write_table_artifacts


LATEX_ESCAPES = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def latex_escape(value: object) -> str:
    """Escape plain text without altering trusted notation strings."""

    return "".join(LATEX_ESCAPES.get(char, char) for char in str(value or ""))


def latex_texttt_breakable(value: str) -> str:
    """Render a machine column name with line breaks allowed at underscores."""

    parts = [latex_escape(part) for part in value.split("_")]
    return r"\texttt{" + r"\_\allowbreak{}".join(parts) + "}"


def table_row(*cells: str) -> str:
    return " & ".join(cells) + r" \\"


def group_header(label: str, columns: int) -> str:
    return rf"\multicolumn{{{columns}}}{{@{{}}l}}{{\textit{{{latex_escape(label)}}}}} \\"


def render_table() -> str:
    """Build a width-adaptive table fragment for paper and standalone use."""

    lines = [
        r"% Requires \usepackage{booktabs,tabularx,array}.",
        r"\begingroup",
        r"\renewcommand{\arraystretch}{1.45}",
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\raggedright\arraybackslash}X"
        r"l"
        r">{\raggedright\arraybackslash}X@{}}",
        r"\toprule",
        table_row("Symbol", "Unit", "Meaning"),
        r"\midrule",
    ]

    symbol_group = None
    for item in NOTATION_DEFINITIONS:
        if item.group != symbol_group:
            if symbol_group is not None:
                lines.append(r"\addlinespace")
            lines.append(group_header(item.group, 3))
            symbol_group = item.group
        lines.append(
            table_row(
                item.notation,
                latex_escape(item.unit),
                item.definition,
            )
        )

    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\begin{tabularx}{\linewidth}{@{}"
            r">{\raggedright\arraybackslash}X"
            r">{\raggedright\arraybackslash}X"
            r"l"
            r">{\raggedright\arraybackslash}X"
            r">{\raggedright\arraybackslash}X@{}}",
            r"\toprule",
            table_row("Variable", "Formula", "Unit", "Data column", "Definition"),
            r"\midrule",
        ]
    )

    for group, specs in specs_by_group().items():
        lines.extend([r"\addlinespace", group_header(group, 5)])
        for spec in specs:
            lines.append(
                table_row(
                    spec.notation,
                    spec.formula,
                    latex_escape(spec.unit),
                    latex_texttt_breakable(spec.column),
                    spec.construction,
                )
            )

    lines.extend([r"\bottomrule", r"\end{tabularx}", r"\endgroup"])
    return "\n".join(lines) + "\n"


write_table_artifacts(
    "variable_notation",
    render_table(),
    preview_width="10in",
)
