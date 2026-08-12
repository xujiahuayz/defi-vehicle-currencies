#!/usr/bin/env python3
"""Build full-calendar round-trip count and value share paths.

Reads   data/processed/cross_venue_routing_daily.parquet
Writes  output/figures/round_trip_shares_full_calendar.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import load_current_parquet, publish_pdf, render_round_trip_shares
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = DATA_DIR / "processed" / "cross_venue_routing_daily.parquet"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "round_trip_shares_full_calendar.pdf"
CODE_SOURCES = [
    "scripts/figure/build_round_trip_shares.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, input_identity = load_current_parquet(args.input, consumer="round-trip share figure")
    publish_pdf(
        args.output,
        renderer=lambda path: render_round_trip_shares(frame, path),
        input_path=args.input,
        input_identity=input_identity,
        code_sources=CODE_SOURCES,
        notes="all certified daily observations with quarterly medians of the daily count and diagnostic-value shares among multi-leg routes",
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
