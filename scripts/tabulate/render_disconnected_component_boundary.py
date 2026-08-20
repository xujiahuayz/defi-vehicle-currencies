#!/usr/bin/env python3
"""Render the disconnected-component sensitivity for the paper and deck."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output
from scripts.analyze.run_disconnected_component_boundary import (
    render_table,
    render_values,
)


INPUT = OUTPUT_DIR / "exhibits/disconnected_component_boundary.jsonl"
VALUE_OUTPUT = OUTPUT_DIR / "exhibits/disconnected_component_boundary_values.tex"


def main() -> int:
    results = pd.read_json(INPUT, lines=True)
    with atomic_output(VALUE_OUTPUT) as temporary:
        temporary.write_text(render_values(results), encoding="utf-8")
    write_table_artifacts(
        "disconnected_component_boundary",
        render_table(results),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
