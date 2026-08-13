#!/usr/bin/env python3
"""Build the latest candidate-level count/value excess-use heatmap."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import load_current_jsonl, publish_pdf, render_vehicle_excess_use_heatmap
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = OUTPUT_DIR / "exhibits" / "e0_vehicle_rotation_analysis.jsonl"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "vehicle_excess_use_cross_section.pdf"
CODE_SOURCES = [
    "scripts/figure/build_vehicle_excess_use_heatmap.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, identity = load_current_jsonl(args.input, consumer="vehicle excess-use heatmap")
    publish_pdf(
        args.output,
        renderer=lambda path: render_vehicle_excess_use_heatmap(frame, path),
        input_path=args.input,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes="latest candidate cross-section; excess use is intermediary share divided by endpoint-demand share, shown separately by count and common-support value",
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
