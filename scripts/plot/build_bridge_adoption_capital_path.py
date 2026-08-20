#!/usr/bin/env python3
"""Build the bridge-capital path around first use of the supported stablecoin."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.figure_outputs import (
    load_current_jsonl,
    publish_pdf,
    render_bridge_adoption_capital_path,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


DEFAULT_INPUT = OUTPUT_DIR / "exhibits" / "bridge_liquidity_dominance.jsonl"
DEFAULT_OUTPUT = OUTPUT_DIR / "figures" / "experiments" / "bridge_adoption_capital_path.pdf"
CODE_SOURCES = [
    "scripts/plot/build_bridge_adoption_capital_path.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    frame, identity = load_current_jsonl(
        args.input,
        consumer="bridge adoption capital-path figure",
    )
    publish_pdf(
        args.output,
        renderer=lambda path: render_bridge_adoption_capital_path(frame, path),
        input_path=args.input,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes=(
            "Equal-event changes in prior-calendar weak-leg deposited capital "
            "around first use of a stablecoin in the exact support set; sample "
            "requires persistent support at least seven days before route use"
        ),
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
