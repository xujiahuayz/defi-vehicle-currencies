#!/usr/bin/env python3
"""Build the candidate-level 2024-to-2026 excess-use dumbbell figure."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.data_release import require_node_d_release
from ddvc.figure_outputs import (
    load_current_jsonl,
    publish_pdf,
    render_vehicle_excess_use_transition,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = OUTPUT_DIR / "exhibits" / "vehicle_excess_use.jsonl"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "vehicle_excess_use_transition.pdf"
CODE_SOURCES = [
    "scripts/figure/build_vehicle_excess_use_transition.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    frame, identity = load_current_jsonl(args.input, consumer="vehicle excess-use transition figure")
    publish_pdf(
        args.output,
        renderer=lambda path: render_vehicle_excess_use_transition(frame, path),
        input_path=args.input,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes=(
            "USDC and USDT candidate-level 2024-to-2026 route-count and routed-value "
            "excess-use ratios; routed value requires source, intermediary, and destination "
            "dollar amounts to agree within 20 percent; parity shown at one"
        ),
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
