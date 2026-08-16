#!/usr/bin/env python3
"""Render the paper's route-structure-around-router-releases table."""

from __future__ import annotations

import json

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.provenance import current_artifacts, sidecar_path
from ddvc.venue_tables import render_routing_technology_windows


INPUT = OUTPUT_DIR / "exhibits" / "routing_technology_windows.jsonl"

with current_artifacts([INPUT], consumer="router-release window table"):
    rows = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]
    write_table_artifacts(
        "routing_technology_windows",
        render_routing_technology_windows(rows),
        preview_width="8in",
        inputs=[INPUT, sidecar_path(INPUT)],
        code_sources=["src/ddvc/venue_tables.py"],
        notes=(
            "market-wide route structure in symmetric 60-day windows either side "
            "of three dated public router releases, excluding the release date; "
            "shares are of economic routes except the cross-exchange share, which "
            "is of intermediated routes, and the over-two-legs share, which is of "
            "indirect routes; descriptive composition and not a treatment effect"
        ),
    )
