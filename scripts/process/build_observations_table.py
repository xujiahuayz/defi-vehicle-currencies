#!/usr/bin/env python3
"""Direct runner for the canonical wide observations table."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

from ddvc.analysis.observations import (  # noqa: E402
    DEFAULT_OBSERVATIONS_TABLE,
    DEFAULT_TRADE_SIZE,
    DEFAULT_VEHICLES,
    TRADE_SIZE_SUFFIXES,
    build_observations_table,
)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-root", type=Path, default=ROOT / "data", help="DVC data workspace.")
parser.add_argument(
    "--output",
    type=Path,
    default=DEFAULT_OBSERVATIONS_TABLE,
    help="Output path for the wide observations table.",
)
parser.add_argument("--main-trade-size", type=float, default=DEFAULT_TRADE_SIZE)
parser.add_argument(
    "--trade-sizes",
    type=float,
    nargs="+",
    default=tuple(TRADE_SIZE_SUFFIXES),
    help="Trade-size buckets to attach as suffixed route-cost variables.",
)
parser.add_argument("--vehicles", nargs="+", default=list(DEFAULT_VEHICLES))
args = parser.parse_args()

panel = build_observations_table(
    args.data_root,
    args.output,
    vehicles=tuple(args.vehicles),
    trade_sizes=tuple(float(x) for x in args.trade_sizes),
    main_trade_size=float(args.main_trade_size),
)
rel = args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output
print(
    f"wrote {rel}: {len(panel):,} rows x {len(panel.columns):,} columns; "
    f"{panel['date'].min().date()} to {panel['date'].max().date()}"
)
