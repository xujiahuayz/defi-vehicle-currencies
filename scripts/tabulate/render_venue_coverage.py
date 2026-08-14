#!/usr/bin/env python3
"""Render the paper's nine-source observed-volume table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.provenance import current_artifacts, sidecar_path
from ddvc.venue_tables import render_venue_coverage


INPUT = OUTPUT_DIR / "exhibits" / "venue_volume_by_year.jsonl"

with current_artifacts([INPUT], consumer="venue observed-volume table"):
    rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
    write_table_artifacts(
        "venue_coverage",
        render_venue_coverage(rows),
        preview_width="9.5in",
        inputs=[INPUT, sidecar_path(INPUT)],
        code_sources=["src/ddvc/venue_tables.py"],
        notes=(
            "nine-source observed-volume comparison for 2020--2026; Fluid uses "
            "partial locally available dates and has no TVL field; annual shares "
            "use observed USD volume and pooled shares sum displayed-year volume"
        ),
    )
