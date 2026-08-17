#!/usr/bin/env python3
"""Render the paper's endpoint-year vehicle-dominance table."""

from __future__ import annotations

import json

from ddvc.dominance_tables import render_dominance_rotation
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "intermediation_complexity_rival.jsonl"

rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
write_table_artifacts(
    "dominance_rotation",
    render_dominance_rotation(rows),
    preview_width="7.5in",
)
