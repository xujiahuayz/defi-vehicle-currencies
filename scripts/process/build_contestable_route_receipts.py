#!/usr/bin/env python3
"""Build receipt attributes for the exact stablecoin-versus-WETH comparison."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.ethereum_receipts import RECEIPT_CACHE, load_cached_receipt
from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output


FRONTIER = DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
OUTPUT = DATA_DIR / "processed/contestable_route_receipts.parquet"


def run(frontier_path: Path, cache: Path, output: Path) -> int:
    frontier = pd.read_parquet(
        frontier_path, columns=["tx_hash", "vehicle_families_contestable"]
    )
    hashes = sorted(
        frontier.loc[
            frontier["vehicle_families_contestable"].astype(bool), "tx_hash"
        ].astype(str).str.lower().drop_duplicates()
    )
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for tx_hash in hashes:
        receipt = load_cached_receipt(cache, tx_hash, expected_block=None)
        if receipt is None:
            missing.append(tx_hash)
        else:
            rows.append(receipt)
    if missing:
        raise RuntimeError(
            f"{len(missing):,} contestable-route receipts are absent; run "
            "scripts/fetch/fetch_route_gas_receipts.py --contestable-only first"
        )
    panel = pd.DataFrame(rows).sort_values("tx_hash", kind="stable")
    if panel["tx_hash"].duplicated().any() or not panel["status"].eq(1).all():
        raise RuntimeError("contestable receipt panel is duplicated or contains failures")
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        panel.to_parquet(temporary, index=False)
    print(f"wrote {len(panel):,} contestable-route receipts to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--cache", type=Path, default=RECEIPT_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    return run(args.frontier, args.cache, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

