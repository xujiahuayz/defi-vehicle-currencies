#!/usr/bin/env python3
"""Build the deterministic transaction sample for receipt-gas measurement."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.route_gas import (
    UNIFIED_ROUTE_COLUMNS,
    deterministic_route_sample,
    route_gas_rows,
)
from ddvc.runtime import atomic_output


DEFAULT_OUTPUT = DATA_DIR / "interim/route_gas_sample.parquet"


def run(unified: Path, output: Path, *, per_cell: int) -> int:
    parts: list[pd.DataFrame] = []
    paths = sorted(unified.glob("[0-9]" * 8 + ".parquet"))
    for index, path in enumerate(paths, 1):
        frame = pd.read_parquet(path, columns=UNIFIED_ROUTE_COLUMNS)
        rows = route_gas_rows(frame, path.stem)
        if not rows.empty:
            parts.append(deterministic_route_sample(rows, per_cell=per_cell))
        if index % 180 == 0 or index == len(paths):
            print(f"  route days {index:,}/{len(paths):,}", flush=True)
    if not parts:
        raise RuntimeError("unified route files produced no receipt-gas sample")
    sample = deterministic_route_sample(
        pd.concat(parts, ignore_index=True), per_cell=per_cell
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        sample.to_parquet(temporary, index=False)
    print(f"wrote {len(sample):,} sampled route transactions to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unified", type=Path, default=DATA_DIR / "unified")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-cell", type=int, default=25)
    args = parser.parse_args()
    return run(args.unified, args.output, per_cell=args.per_cell)


if __name__ == "__main__":
    raise SystemExit(main())

