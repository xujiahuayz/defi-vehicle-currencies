#!/usr/bin/env python3
"""Build the manifest, local replay, and deck values for one real route."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.datasets import require_datasets
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.route_replay import manifest_from_partition, write_route_replay_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True, help="UTC day in YYYYMMDD format")
    parser.add_argument("--tx-hash", required=True)
    parser.add_argument("--component-id", type=int, default=0)
    parser.add_argument("--manifest", type=Path, default=OUTPUT_DIR / "exhibits" / "route_replay.json")
    parser.add_argument("--html", type=Path, default=OUTPUT_DIR / "live" / "route_replay.html")
    parser.add_argument("--tex", type=Path, default=OUTPUT_DIR / "exhibits" / "route_replay_deck_values.tex")
    args = parser.parse_args()

    require_datasets(routes=True)
    partition = DATA_DIR / "unified" / f"{args.day}.parquet"
    if not partition.exists():
        raise FileNotFoundError(partition)
    manifest = manifest_from_partition(
        partition,
        day=args.day,
        tx_hash=args.tx_hash,
        component_id=args.component_id,
    )
    write_route_replay_bundle(
        manifest,
        manifest_path=args.manifest,
        html_path=args.html,
        tex_path=args.tex,
    )
    print(f"wrote {args.manifest}, {args.html}, and {args.tex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
