#!/usr/bin/env python3
"""Render the paper's excess-use-by-venue-pricing-family table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.venue_tables import render_venue_technology_rival


INPUT = OUTPUT_DIR / "exhibits" / "venue_technology_rival.jsonl"

rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
write_table_artifacts(
    "venue_technology_rival",
    render_venue_technology_rival(rows),
    preview_width="9.5in",
)
