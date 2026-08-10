#!/usr/bin/env python3
"""Assemble exact V3 inventory-event shards and publish one ordered root manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.paths import RAW_MARKET_DATA_LOCK, V3_INVENTORY_RAW_ROOT
from ddvc.runtime import exclusive_job
from ddvc.v3_inventory import INVENTORY_CHUNK_SIZE, assemble_inventory_shards
from ddvc.v3_pool_registry import V3_FACTORY_DEPLOYMENT_BLOCK, load_certified_frozen_upper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        nargs=3,
        metavar=("ROOT", "LOWER", "UPPER"),
        required=True,
        help="repeat for each disjoint shard owner",
    )
    parser.add_argument("--destination", type=Path, default=V3_INVENTORY_RAW_ROOT)
    parser.add_argument("--chunk-size", type=int, default=INVENTORY_CHUNK_SIZE)
    args = parser.parse_args()
    frozen_upper, factory_certificate = load_certified_frozen_upper()
    sources = [
        (Path(root), (int(lower), int(upper)))
        for root, lower, upper in args.source
    ]
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="V3 inventory shard assembly"):
        record = assemble_inventory_shards(
            sources,
            args.destination,
            start=V3_FACTORY_DEPLOYMENT_BLOCK,
            end=int(frozen_upper["block_number"]),
            chunk_size=args.chunk_size,
            frozen_upper=frozen_upper,
            factory_certificate=factory_certificate,
        )
    print(
        f"COMPLETE: V3 inventory chunks={record['chunk_count']:,}; "
        f"raw_logs={record['raw_logs']:,}; "
        f"portable_manifest={record['portable_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
