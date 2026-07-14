#!/usr/bin/env python3
"""Direct runner for Table 1: summary statistics."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.analysis.observations import DEFAULT_OBSERVATIONS_TABLE  # noqa: E402
from ddvc.export.tables import build_summary_rows, render_summary_statistics_latex  # noqa: E402


out_tex = ROOT / "output" / "tables" / "table_01_summary_statistics.tex"
out_tex.parent.mkdir(parents=True, exist_ok=True)
rows = build_summary_rows(DEFAULT_OBSERVATIONS_TABLE)
out_tex.write_text(render_summary_statistics_latex(rows), encoding="utf-8")
print(f"wrote {out_tex.relative_to(ROOT)}")
