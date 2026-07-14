#!/usr/bin/env python3
"""Direct runner for Table 0: variable notation and construction."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.export.tables import render_variable_notation_latex  # noqa: E402


out_tex = ROOT / "output" / "tables" / "table_00_variable_notation.tex"
out_tex.parent.mkdir(parents=True, exist_ok=True)
out_tex.write_text(render_variable_notation_latex(), encoding="utf-8")
print(f"wrote {out_tex.relative_to(ROOT)}")
