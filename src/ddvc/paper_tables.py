"""Canonical formatting and rendering helpers for paper-facing tables."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

from ddvc.paths import REPO_ROOT


TABLES_DIR = REPO_ROOT / "output" / "tables"
NUMBERED_ARTIFACT_RE = re.compile(
    r"^(?:table|figure)_(?:[a-z]\d+|\d+)(?:_|$)", re.IGNORECASE
)
LOGGER = logging.getLogger(__name__)


def _pct(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return ""
    return f"{100 * float(value):.{digits}f}"


def _num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.{digits}f}"


def _int(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{int(round(float(value))):,}"


def _p(value: float) -> str:
    if pd.isna(value):
        return ""
    value = float(value)
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"


def _latex_escape(value: object, *, allow_breaks: bool = False) -> str:
    text = "" if value is None else str(value)
    escaped = (
        text.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )
    escaped = escaped.replace("<", r"\ensuremath{<}").replace(
        ">", r"\ensuremath{>}"
    )
    if allow_breaks:
        escaped = escaped.replace(r"\_", r"\_\allowbreak{}").replace(
            "/", r"/\allowbreak{}"
        )
    return escaped


def _artifact_stem(stem: str) -> str:
    """Drop legacy paper-order prefixes from generated output filenames."""
    return NUMBERED_ARTIFACT_RE.sub("", stem)


def validate_output_stem(stem: str) -> str:
    """Return a descriptive artifact stem or reject hard-coded numbering."""
    if stem.endswith((".tex", ".pdf", ".pkl")):
        raise ValueError("Pass an artifact stem without a file extension.")
    if NUMBERED_ARTIFACT_RE.match(stem):
        raise ValueError(
            "Output artifact stems must be descriptive and unnumbered; "
            "paper/slides own table and figure numbering."
        )
    if not stem or "/" in stem or "\\" in stem:
        raise ValueError("Output artifact stems must be simple filenames.")
    return stem


def _standalone_document(table_latex: str, preview_width: str | None = None) -> str:
    lines = [
        r"\documentclass[border=2pt]{standalone}",
        r"\usepackage{booktabs}",
        r"\usepackage{array}",
        r"\usepackage{tabularx}",
        r"\begin{document}",
        r"\scriptsize",
    ]
    if preview_width is not None:
        lines.append(rf"\begin{{minipage}}{{{preview_width}}}")
    lines.append(table_latex)
    if preview_width is not None:
        lines.append(r"\end{minipage}")
    lines.extend([r"\end{document}", ""])
    return "\n".join(lines)


def _compile_with_tectonic(tex_path: Path, out_dir: Path) -> Path:
    tectonic = shutil.which("tectonic")
    if tectonic is None:
        raise FileNotFoundError("tectonic")
    subprocess.run(
        [tectonic, "-X", "compile", str(tex_path), "--outdir", str(out_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return out_dir / f"{tex_path.stem}.pdf"


def _compile_with_latexmk(tex_path: Path, out_dir: Path) -> Path:
    latexmk = shutil.which("latexmk")
    if latexmk is None:
        raise FileNotFoundError("latexmk")
    subprocess.run(
        [
            latexmk,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-outdir={out_dir}",
            str(tex_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return out_dir / f"{tex_path.stem}.pdf"


def _compile_with_pdflatex(tex_path: Path, out_dir: Path) -> Path:
    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        raise FileNotFoundError("pdflatex")
    for _ in range(2):
        subprocess.run(
            [
                pdflatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={out_dir}",
                str(tex_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    return out_dir / f"{tex_path.stem}.pdf"


def render_standalone_pdf(
    table_latex: str,
    pdf_path: Path,
    *,
    preview_width: str | None = None,
) -> Path:
    """Compile a table fragment into a standalone inspection PDF."""
    with tempfile.TemporaryDirectory(prefix="dvc_table_") as temporary:
        temporary_dir = Path(temporary)
        out_dir = temporary_dir / "out"
        out_dir.mkdir()
        tex_path = temporary_dir / "standalone_table.tex"
        tex_path.write_text(
            _standalone_document(table_latex, preview_width), encoding="utf-8"
        )
        errors: list[str] = []
        compiled: Path | None = None
        for compiler in (
            _compile_with_tectonic,
            _compile_with_latexmk,
            _compile_with_pdflatex,
        ):
            try:
                compiled = compiler(tex_path, out_dir)
                break
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                errors.append(f"{compiler.__name__}: {exc}")
        if compiled is None or not compiled.exists():
            raise RuntimeError(
                "Could not compile standalone table PDF. " + " | ".join(errors)
            )
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiled, pdf_path)
    return pdf_path


def write_table_artifacts(
    stem: str,
    table_latex: str,
    *,
    preview_width: str | None = None,
) -> tuple[Path, Path]:
    """Write a paper-input TeX fragment and matching standalone PDF."""
    stem = validate_output_stem(stem)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    tex_path = TABLES_DIR / f"{stem}.tex"
    pdf_path = TABLES_DIR / f"{stem}.pdf"
    tex_path.write_text(table_latex, encoding="utf-8")
    render_standalone_pdf(table_latex, pdf_path, preview_width=preview_width)
    LOGGER.info("wrote %s", tex_path.relative_to(REPO_ROOT))
    LOGGER.info("wrote %s", pdf_path.relative_to(REPO_ROOT))
    return tex_path, pdf_path


def _write_table(
    frame: pd.DataFrame,
    stem: str,
    caption: str,
    label: str,
    *,
    align: str | None = None,
    note: str | None = None,
) -> None:
    """Write the legacy table fragment and inspection PDF used by runners."""
    del caption, label
    stem = _artifact_stem(stem)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    tex_path = TABLES_DIR / f"{stem}.tex"
    pdf_path = TABLES_DIR / f"{stem}.pdf"
    align = align or ("l" + "r" * (len(frame.columns) - 1))
    use_tabularx = "X" in align
    begin = (
        f"\\begin{{tabularx}}{{\\linewidth}}{{{align}}}"
        if use_tabularx
        else f"\\begin{{tabular}}{{{align}}}"
    )
    end = "\\end{tabularx}" if use_tabularx else "\\end{tabular}"
    lines = [
        begin,
        "\\toprule",
        " & ".join(_latex_escape(column) for column in frame.columns) + " \\\\",
        "\\midrule",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append(
            " & ".join(
                _latex_escape(value, allow_breaks=use_tabularx) for value in row
            )
            + " \\\\"
        )
    lines.extend(["\\bottomrule", end])
    if note:
        lines.append(f"% Notes for paper wrapper: {_latex_escape(note)}")
    table_latex = "\n".join(lines) + "\n"
    tex_path.write_text(table_latex, encoding="utf-8")
    render_standalone_pdf(
        table_latex,
        pdf_path,
        preview_width="24cm" if use_tabularx else None,
    )
