#!/usr/bin/env python3
"""Render the paper's route-structure-around-router-releases table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.venue_tables import render_routing_technology_windows


INPUT = OUTPUT_DIR / "exhibits" / "routing_technology_windows.jsonl"

rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
write_table_artifacts(
    "routing_technology_windows",
    render_routing_technology_windows(rows),
    preview_width="8in",
)
