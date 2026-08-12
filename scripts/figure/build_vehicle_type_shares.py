#!/usr/bin/env python3
"""Build the full-path quarterly vehicle-type share figure.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/figures/vehicle_type_shares_quarterly.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import load_current_parquet, publish_pdf, render_vehicle_type_shares
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "vehicle_type_shares_quarterly.pdf"
CODE_SOURCES = [
    "scripts/figure/build_vehicle_type_shares.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, input_identity = load_current_parquet(args.input, consumer="vehicle-type share figure")
    publish_pdf(
        args.output,
        renderer=lambda path: render_vehicle_type_shares(frame, path),
        input_path=args.input,
        input_identity=input_identity,
        code_sources=CODE_SOURCES,
        notes="quarterly ratios of totals; counts use full topology support and values require within-20-percent source-intermediary-sink amount coherence",
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
