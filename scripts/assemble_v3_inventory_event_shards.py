#!/usr/bin/env python3
"""Assemble exact V3 inventory-event shards and publish one ordered root manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from ddvc.paths import V3_INVENTORY_RAW_ROOT
from ddvc.v3_inventory import INVENTORY_CHUNK_SIZE
from ddvc.v3_inventory_assembly import assemble_inventory_shards
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
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()
    if args.progress_every < 1:
        raise ValueError("progress interval must be positive")
    frozen_upper, factory_certificate = load_certified_frozen_upper()
    sources = [
        (Path(root), (int(lower), int(upper)))
        for root, lower, upper in args.source
    ]
    started = time.monotonic()

    def report(counters: dict[str, int]) -> None:
        complete = counters["chunks_complete"]
        total = counters["chunks_total"]
        if complete != total and complete % args.progress_every:
            return
        elapsed = max(time.monotonic() - started, 1e-9)
        rate = complete / elapsed
        remaining = (total - complete) / rate if rate else 0.0
        print(
            f"ASSEMBLY: chunks={complete:,}/{total:,}; "
            f"raw_logs_verified={counters['raw_logs_verified']:,}; "
            f"source_gib_verified={counters['source_bytes_verified'] / 2**30:.2f}; "
            f"copied_gib={counters['copied_bytes'] / 2**30:.2f}; "
            f"certificates_reused={counters['certificates_reused']:,}; "
            f"elapsed_minutes={elapsed / 60:.1f}; "
            f"eta_minutes={remaining / 60:.1f}",
            flush=True,
        )

    record = assemble_inventory_shards(
        sources,
        args.destination,
        start=V3_FACTORY_DEPLOYMENT_BLOCK,
        end=int(frozen_upper["block_number"]),
        chunk_size=args.chunk_size,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
        workers=args.workers,
        progress=report,
    )
    print(
        f"COMPLETE: V3 inventory chunks={record['chunk_count']:,}; "
        f"raw_logs={record['raw_logs']:,}; "
        f"portable_manifest={record['portable_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
