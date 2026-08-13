#!/usr/bin/env python3
"""Build the architecture-transition comparison-support composition figure."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import load_current_jsonl, publish_pdf, render_architecture_support
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = OUTPUT_DIR / "exhibits" / "architecture_transition_support.jsonl"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "architecture_transition_support.pdf"
CODE_SOURCES = [
    "scripts/figure/build_architecture_support.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, identity = load_current_jsonl(args.input, consumer="architecture support figure")
    publish_pdf(
        args.output,
        renderer=lambda path: render_architecture_support(frame, path),
        input_path=args.input,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes="detected realised architecture-share entries and exits partitioned into changing comparison sets, incomplete windows, overlaps and usable comparisons",
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
