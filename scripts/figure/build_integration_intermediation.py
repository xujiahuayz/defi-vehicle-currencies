#!/usr/bin/env python3
"""Build the daily-state association between cross-venue routing and intermediation."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import load_current_parquet, publish_pdf, render_integration_intermediation
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = DATA_DIR / "processed" / "cross_venue_routing_daily.parquet"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "integration_intermediation_bins.pdf"
CODE_SOURCES = [
    "scripts/figure/build_integration_intermediation.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, identity = load_current_parquet(args.input, consumer="integration/intermediation figure")
    publish_pdf(
        args.output,
        renderer=lambda path: render_integration_intermediation(frame, path),
        input_path=args.input,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes="equal-frequency bins of daily cross-venue and intermediary route shares; descriptive association, not a calendar-time or causal design",
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
