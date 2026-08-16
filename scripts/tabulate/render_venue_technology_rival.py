#!/usr/bin/env python3
"""Render the paper's excess-use-by-venue-pricing-family table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.provenance import current_artifacts, sidecar_path
from ddvc.venue_tables import render_venue_technology_rival


INPUT = OUTPUT_DIR / "exhibits" / "venue_technology_rival.jsonl"

with current_artifacts([INPUT], consumer="venue pricing-family rival table"):
    rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
    write_table_artifacts(
        "venue_technology_rival",
        render_venue_technology_rival(rows),
        preview_width="9.5in",
        inputs=[INPUT, sidecar_path(INPUT)],
        code_sources=["src/ddvc/venue_tables.py"],
        notes=(
            "vehicle excess use by venue pricing family, 2020--2026; a route "
            "component enters a scope only when every leg belongs to it; the "
            "denominator is the candidate-currency set; scope-years without an "
            "intermediary episode identify no ratio and are labelled rather than "
            "left blank"
        ),
    )
