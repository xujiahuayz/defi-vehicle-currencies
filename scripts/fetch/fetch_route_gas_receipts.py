#!/usr/bin/env python3
"""Fetch transaction receipts used by route-gas measurement.

The request file may be the deterministic route-gas sample or the exact vehicle
frontier.  For the latter, ``--contestable-only`` retains transactions for which
both the stablecoin and WETH paths are feasible.  Successful normalized receipts
are retained under ``data/raw/ethereum/rpc_cache/receipts``; reruns reuse them.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.ethereum_receipts import RECEIPT_CACHE, fetch_receipt, load_cached_receipt


def request_hashes(path: Path, *, contestable_only: bool) -> list[str]:
    columns = ["tx_hash"]
    if contestable_only:
        columns.append("vehicle_families_contestable")
    frame = pd.read_parquet(path, columns=columns)
    if contestable_only:
        frame = frame[frame["vehicle_families_contestable"].astype(bool)]
    hashes = frame["tx_hash"].astype(str).str.lower()
    hashes = hashes[hashes.str.match(r"^0x[0-9a-f]{64}$")]
    return sorted(hashes.drop_duplicates())


def run(
    requests: Path,
    *,
    cache: Path,
    workers: int,
    contestable_only: bool,
) -> int:
    hashes = request_hashes(requests, contestable_only=contestable_only)
    missing = [
        tx_hash
        for tx_hash in hashes
        if load_cached_receipt(cache, tx_hash, expected_block=None) is None
    ]
    print(
        f"route receipts: {len(hashes):,} requested, "
        f"{len(hashes) - len(missing):,} retained, {len(missing):,} to fetch",
        flush=True,
    )
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fetch_receipt, tx_hash, cache=cache): tx_hash
            for tx_hash in missing
        }
        for index, future in enumerate(as_completed(futures), 1):
            tx_hash = futures[future]
            try:
                future.result()
            except Exception as error:  # the failed identity is reported and rerunnable
                failures.append((tx_hash, type(error).__name__))
            if index % 1_000 == 0 or index == len(futures):
                print(
                    f"  fetched {index:,}/{len(futures):,}; "
                    f"failed {len(failures):,}",
                    flush=True,
                )
    if failures:
        sample = ", ".join(f"{tx}:{kind}" for tx, kind in failures[:8])
        raise RuntimeError(f"{len(failures):,} route receipts failed: {sample}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", type=Path)
    parser.add_argument("--cache", type=Path, default=RECEIPT_CACHE)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--contestable-only", action="store_true")
    args = parser.parse_args()
    return run(
        args.requests,
        cache=args.cache,
        workers=args.workers,
        contestable_only=args.contestable_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())

