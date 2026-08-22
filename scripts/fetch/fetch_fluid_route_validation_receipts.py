#!/usr/bin/env python3
"""Fetch complete transaction receipts for the fixed Fluid route sample."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.analysis.fluid_route_label_validation import (
    fetch_fluid_receipt,
    fetch_pool_constants,
    load_fluid_receipt,
    load_pool_constants,
)
from ddvc.paths import DATA_DIR


DEFAULT_SAMPLE = DATA_DIR / "interim" / "fluid_route_label_validation_sample.parquet"
DEFAULT_CACHE = DATA_DIR / "raw" / "ethereum" / "fluid_route_validation" / "receipts"
DEFAULT_POOL_CACHE = (
    DATA_DIR / "raw" / "ethereum" / "fluid_route_validation" / "pool_constants"
)


def receipt_requests(sample: Path) -> list[tuple[str, int]]:
    frame = pd.read_parquet(sample, columns=["tx_hash", "block_number"])
    frame["tx_hash"] = frame["tx_hash"].astype(str).str.lower()
    unique = frame[["tx_hash", "block_number"]].drop_duplicates()
    if unique["tx_hash"].duplicated().any():
        raise ValueError("Fluid sample assigns one transaction to more than one block")
    return sorted(
        (str(row.tx_hash), int(row.block_number))
        for row in unique.itertuples(index=False)
    )


def pool_requests(sample: Path) -> list[tuple[str, int]]:
    frame = pd.read_parquet(sample, columns=["pool", "block_number"])
    frame["pool"] = frame["pool"].astype(str).str.lower()
    earliest = frame.groupby("pool", as_index=False, sort=True)["block_number"].min()
    return [
        (str(row.pool), int(row.block_number))
        for row in earliest.itertuples(index=False)
    ]


def run(sample: Path, *, cache: Path, pool_cache: Path, workers: int) -> int:
    requests = receipt_requests(sample)
    missing = [
        (tx_hash, block_number)
        for tx_hash, block_number in requests
        if load_fluid_receipt(
            cache,
            tx_hash,
            expected_block=block_number,
            require_evidence=True,
        )
        is None
    ]
    print(
        f"Fluid receipts: {len(requests):,} requested, "
        f"{len(requests) - len(missing):,} retained, {len(missing):,} to fetch",
        flush=True,
    )
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                fetch_fluid_receipt,
                tx_hash,
                cache=cache,
                expected_block=block_number,
            ): tx_hash
            for tx_hash, block_number in missing
        }
        for index, future in enumerate(as_completed(futures), 1):
            tx_hash = futures[future]
            try:
                future.result()
            except Exception as error:
                failures.append((tx_hash, type(error).__name__))
            if index % 20 == 0 or index == len(futures):
                print(
                    f"  fetched {index:,}/{len(futures):,}; "
                    f"failed {len(failures):,}",
                    flush=True,
                )
    if failures:
        examples = ", ".join(f"{tx}:{kind}" for tx, kind in failures[:8])
        raise RuntimeError(f"{len(failures):,} Fluid receipts failed: {examples}")

    pools = pool_requests(sample)
    missing_pools = [
        (pool, block_number)
        for pool, block_number in pools
        if load_pool_constants(
            pool_cache,
            pool,
            block_number=block_number,
            require_evidence=True,
        )
        is None
    ]
    print(
        f"Fluid pool constants: {len(pools):,} requested, "
        f"{len(pools) - len(missing_pools):,} retained, "
        f"{len(missing_pools):,} to fetch",
        flush=True,
    )
    pool_failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool_executor:
        futures = {
            pool_executor.submit(
                fetch_pool_constants,
                pool,
                cache=pool_cache,
                block_number=block_number,
            ): pool
            for pool, block_number in missing_pools
        }
        for future in as_completed(futures):
            pool = futures[future]
            try:
                future.result()
            except Exception as error:
                pool_failures.append((pool, type(error).__name__))
    if pool_failures:
        examples = ", ".join(
            f"{pool}:{kind}" for pool, kind in pool_failures[:8]
        )
        raise RuntimeError(
            f"{len(pool_failures):,} Fluid pool-constant calls failed: {examples}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--pool-cache", type=Path, default=DEFAULT_POOL_CACHE)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    return run(
        args.sample,
        cache=args.cache,
        pool_cache=args.pool_cache,
        workers=args.workers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
