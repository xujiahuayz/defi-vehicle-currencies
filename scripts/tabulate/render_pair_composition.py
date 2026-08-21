#!/usr/bin/env python3
"""Render the paper's pair-composition accounting and regression table."""

from __future__ import annotations

import json

from ddvc.dominance_tables import (
    parse_newcommands,
    render_pair_composition,
    render_pair_market_accounting,
)
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


MACROS = (
    OUTPUT_DIR
    / "exhibits"
    / "vehicle_transition_pair_decomposition_deck_values.tex"
)
LIFECYCLE_MACROS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_lifecycle_values.tex"
)
FIXED_EFFECTS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
)

macro_values = {
    **parse_newcommands(MACROS.read_text(encoding="utf-8")),
    **parse_newcommands(LIFECYCLE_MACROS.read_text(encoding="utf-8")),
}
fixed_effect_rows = [
    json.loads(line) for line in FIXED_EFFECTS.read_text(encoding="utf-8").splitlines()
]
write_table_artifacts(
    "pair_composition",
    render_pair_composition(macro_values, fixed_effect_rows),
    preview_width="8.5in",
)
write_table_artifacts(
    "pair_market_accounting",
    render_pair_market_accounting(macro_values),
    preview_width="7.0in",
)
