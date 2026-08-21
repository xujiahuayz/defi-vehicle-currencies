#!/usr/bin/env python3
"""Join the retained receipt cache to the deterministic route-gas sample.

Run ``build_route_gas_sample.py`` first, then
``fetch/fetch_route_gas_receipts.py``.  This step performs no network access.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.ethereum_receipts import RECEIPT_CACHE, load_cached_receipt
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import write_report


DEFAULT_SAMPLE = DATA_DIR / "interim/route_gas_sample.parquet"
DEFAULT_OUTPUT = DATA_DIR / "processed/route_gas_units.parquet"
DEFAULT_SUMMARY = OUTPUT_DIR / "exhibits/route_gas_units_summary.jsonl"


def run(sample_path: Path, cache: Path, output: Path, summary_path: Path) -> int:
    sample = pd.read_parquet(sample_path)
    receipts: list[dict[str, object]] = []
    missing: list[str] = []
    for tx_hash in sample["tx_hash"].astype(str):
        receipt = load_cached_receipt(cache, tx_hash, expected_block=None)
        if receipt is None:
            missing.append(tx_hash)
        else:
            receipts.append(receipt)
    if missing:
        raise RuntimeError(
            f"{len(missing):,} sampled receipts are absent; run "
            "scripts/fetch/fetch_route_gas_receipts.py first"
        )
    receipt_panel = pd.DataFrame(receipts)
    panel = sample.merge(receipt_panel, on="tx_hash", how="inner", validate="one_to_one")
    if len(panel) != len(sample):
        raise RuntimeError("receipt join changed the deterministic route sample")
    if not panel["status"].eq(1).all() or not panel["gas_used"].gt(0).all():
        raise RuntimeError("route-gas panel includes failed or zero-gas transactions")
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        panel.to_parquet(temporary, index=False)
    summary = panel.groupby(
        ["year", "legs", "venue_sequence", "mid_type"],
        as_index=False,
        dropna=False,
    ).agg(
        transactions=("gas_used", "size"),
        routers=("tx_to", "nunique"),
        median_gas_used=("gas_used", "median"),
        p25_gas_used=("gas_used", lambda values: values.quantile(0.25)),
        p75_gas_used=("gas_used", lambda values: values.quantile(0.75)),
        median_notional_usd=("route_notional_usd", "median"),
    )
    write_report(summary, summary_path)
    print(f"wrote {len(panel):,} receipt-measured routes to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--cache", type=Path, default=RECEIPT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    return run(args.sample, args.cache, args.output, args.summary)


if __name__ == "__main__":
    raise SystemExit(main())

