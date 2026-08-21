#!/usr/bin/env python3
"""Aggregate the admitted daily intermediation panel into half-year periods."""

from __future__ import annotations

import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit
from scripts.process.build_intermediation_by_type import CODE_SOURCES, halfyear_composition


PANEL = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUTPUT = OUTPUT_DIR / "exhibits" / "intermediation_by_halfyear.jsonl"


def main() -> int:
    panel = pd.read_parquet(PANEL)
    result = halfyear_composition(panel)
    write_exhibit(
        result,
        OUTPUT,
        code_sources=[*CODE_SOURCES, "scripts/process/build_intermediation_halfyear.py"],
        inputs=[PANEL],
        notes=(
            "six-month composition of every realised intermediary position; "
            "value shares require the named route-value agreement band"
        ),
    )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
