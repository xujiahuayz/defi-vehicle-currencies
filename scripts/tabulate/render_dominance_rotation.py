#!/usr/bin/env python3
"""Render the paper's endpoint-year vehicle-dominance table."""

from __future__ import annotations

import json

from ddvc.dominance_tables import render_dominance_rotation
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.provenance import current_artifacts, sidecar_path


INPUT = OUTPUT_DIR / "exhibits" / "intermediation_complexity_rival.jsonl"

with current_artifacts([INPUT], consumer="dominance rotation table"):
    rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
    write_table_artifacts(
        "dominance_rotation",
        render_dominance_rotation(rows),
        preview_width="7.5in",
        inputs=[INPUT, sidecar_path(INPUT)],
        code_sources=["src/ddvc/dominance_tables.py"],
        notes=(
            "current two-leg endpoint-year stable-share estimates on common calendar "
            "support; count and within-20-percent dollar-weighted specifications"
        ),
    )
