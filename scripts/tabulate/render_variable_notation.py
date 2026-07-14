#!/usr/bin/env python3
"""Direct runner for Table 0: variable notation and construction."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABULATE = ROOT / "scripts" / "tabulate"
if str(TABULATE) not in sys.path:
    sys.path.insert(0, str(TABULATE))

from utils import write_table_artifacts  # noqa: E402
from ddvc.export.tables import render_variable_notation_latex  # noqa: E402


out_tex, out_pdf = write_table_artifacts("table_00_variable_notation", render_variable_notation_latex())
print(f"wrote {out_tex.relative_to(ROOT)}")
print(f"wrote {out_pdf.relative_to(ROOT)}")
