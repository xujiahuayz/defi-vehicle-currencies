#!/usr/bin/env python3
"""Direct runner for Table 1: summary statistics."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABULATE = ROOT / "scripts" / "tabulate"
if str(TABULATE) not in sys.path:
    sys.path.insert(0, str(TABULATE))

from utils import write_table_artifacts  # noqa: E402
from ddvc.analysis.observations import DEFAULT_OBSERVATIONS_TABLE  # noqa: E402
from ddvc.export.tables import build_summary_rows, render_summary_statistics_latex  # noqa: E402


rows = build_summary_rows(DEFAULT_OBSERVATIONS_TABLE)
out_tex, out_pdf = write_table_artifacts("table_01_summary_statistics", render_summary_statistics_latex(rows))
print(f"wrote {out_tex.relative_to(ROOT)}")
print(f"wrote {out_pdf.relative_to(ROOT)}")
