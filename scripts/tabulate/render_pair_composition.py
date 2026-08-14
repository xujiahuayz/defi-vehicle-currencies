#!/usr/bin/env python3
"""Render the paper's pair-composition accounting and regression table."""

from __future__ import annotations

import json

from ddvc.dominance_tables import parse_newcommands, render_pair_composition
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_certified_presentation_source


MACROS = (
    OUTPUT_DIR
    / "exhibits"
    / "vehicle_transition_pair_decomposition_deck_values.tex"
)
FIXED_EFFECTS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
)

macro_provenance = require_certified_presentation_source(MACROS)
fixed_effect_provenance = require_certified_presentation_source(FIXED_EFFECTS)
macro_values = parse_newcommands(MACROS.read_text(encoding="utf-8"))
fixed_effect_rows = [
    json.loads(line) for line in FIXED_EFFECTS.read_text(encoding="utf-8").splitlines()
]
write_table_artifacts(
    "pair_composition",
    render_pair_composition(macro_values, fixed_effect_rows),
    preview_width="8.5in",
    inputs=[MACROS, macro_provenance, FIXED_EFFECTS, fixed_effect_provenance],
    code_sources=[
        "src/ddvc/dominance_tables.py",
        "src/ddvc/presentation.py",
    ],
    notes=(
        "certified route-count and supported-value accounting plus three descriptive "
        "saturated pair-by-month-day-by-realised-scope fixed-effect regressions; "
        "two-way ordered-pair and calendar-date CR1 inference; the bound fixed-effect "
        "payload preserves exact confidence intervals, raw and Holm-adjusted p-values, "
        "cluster counts, and specification metadata"
    ),
)
