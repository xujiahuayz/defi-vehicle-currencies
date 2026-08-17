#!/usr/bin/env python3
"""Render the paper's provisional USDT excess-use table."""

from __future__ import annotations

from ddvc.dominance_tables import parse_newcommands, render_usdt_transition
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "provisional_results_deck_values.tex"

write_table_artifacts(
    "usdt_transition",
    render_usdt_transition(parse_newcommands(INPUT.read_text(encoding="utf-8"))),
    preview_width="7.5in",
)
