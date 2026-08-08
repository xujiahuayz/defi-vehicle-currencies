"""Shared conversion of LaTeX source into prose for text-based diagnostics."""

from __future__ import annotations

import re


NON_PROSE_ENVIRONMENTS = (
    "axis",
    "pgfplots",
    "picture",
    "table",
    "tabular",
    "tikzpicture",
)


def strip_latex_markup(text: str) -> str:
    """Return visible prose without control words, source keys, tables, or maths."""
    for environment in NON_PROSE_ENVIRONMENTS:
        text = re.sub(
            rf"\\begin\{{{environment}\*?\}}.*?\\end\{{{environment}\*?\}}",
            " ",
            text,
            flags=re.DOTALL,
        )
    text = re.sub(r"(?m)^\s*%.*$", " ", text)
    text = re.sub(r"\\(?:begin|end)\{[^}]+\}", " ", text)
    text = re.sub(r"\\(?:cite[tp]?|cite|nocite)\*?(?:\[[^]]*\])*\{[^}]*\}", " ", text)
    text = re.sub(r"\\(?:eqref|ref|pageref|autoref)\*?\{[^}]*\}", " 1 ", text)
    text = re.sub(
        r"\\(?:label|input|include|includegraphics|bibliography|addbibresource)"
        r"\*?(?:\[[^]]*\])*\{[^}]*\}",
        " ",
        text,
    )
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]", " x ", text, flags=re.DOTALL)
    text = re.sub(r"\$[^$]*\$|\\\([^)]*\\\)", " x ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^]]*\])*", " ", text)
    text = re.sub(r"[{}$&\\]", " ", text)
    return re.sub(r"\s+", " ", text.replace("~", " ")).strip()
