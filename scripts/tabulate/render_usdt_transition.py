#!/usr/bin/env python3
"""Render the paper's provisional USDT excess-use table."""

from __future__ import annotations

from ddvc.dominance_tables import parse_newcommands, render_usdt_transition
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_current_presentation_source


INPUT = OUTPUT_DIR / "exhibits" / "provisional_results_deck_values.tex"

PROVENANCE = require_current_presentation_source(INPUT)
write_table_artifacts(
    "usdt_transition",
    render_usdt_transition(parse_newcommands(INPUT.read_text(encoding="utf-8"))),
    preview_width="7.5in",
    inputs=[INPUT, PROVENANCE],
    code_sources=["src/ddvc/dominance_tables.py"],
    notes=(
        "generated presentation binding for current certified USDT annual excess-use "
        "and endpoint-gap values; provisional status concerns scientific scope, not lineage"
    ),
)
