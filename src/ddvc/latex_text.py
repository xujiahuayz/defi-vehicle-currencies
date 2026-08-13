"""Shared conversion of LaTeX source into prose for text-based diagnostics."""

from __future__ import annotations

import re
from pathlib import Path


NON_PROSE_ENVIRONMENTS = (
    "axis",
    "pgfplots",
    "picture",
    "table",
    "tabular",
    "tikzpicture",
)


def included_section_files(main: Path, *, fallback_dir: Path | None = None) -> tuple[Path, ...]:
    """Return section sources in the order the compiled document includes them.

    Draft and retired design files can coexist under ``paper/sections``. Text diagnostics
    must inspect the manuscript a reader receives, not every nearby ``.tex`` file. The
    fallback preserves compatibility with a memo that has no explicit main-file inputs.
    """
    try:
        source = main.read_text(encoding="utf-8")
    except OSError:
        source = ""
    paths: list[Path] = []
    for raw in re.findall(r"\\(?:input|include)\{(sections/[^}]+)\}", source):
        path = main.parent / (raw if raw.endswith(".tex") else raw + ".tex")
        if path.is_file():
            paths.append(path)
    if paths:
        return tuple(paths)
    directory = fallback_dir or main.parent / "sections"
    return tuple(sorted(directory.rglob("*.tex"))) if directory.is_dir() else ()


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
