#!/usr/bin/env python3
"""Render the paper's nine-source observed-volume table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.venue_tables import render_market_coverage, render_venue_coverage


INPUT = OUTPUT_DIR / "exhibits" / "venue_volume_by_year.jsonl"
MARKET_INPUT = OUTPUT_DIR / "exhibits" / "ethereum_dex_market_coverage.jsonl"

rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
market_rows = [
    json.loads(line) for line in MARKET_INPUT.read_text(encoding="utf-8").splitlines()
]
write_table_artifacts(
    "venue_coverage",
    render_venue_coverage(rows) + render_market_coverage(market_rows),
    preview_width="9.5in",
)
