#!/usr/bin/env python3
"""Import the deprecated DDC raw data layer into the DVC raw layout.

The default mode creates relative symlinks rather than copying tens of gigabytes.
Use --mode copy only when the old DDC data directory will not remain available.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DDC_DATA = ROOT.parent / "defi-dominant-currency" / "data"
DEFAULT_DVC_RAW = ROOT / "data" / "raw"
DATE_RE = re.compile(r"_(\d{8})\.")


@dataclass(frozen=True)
class StreamMap:
    source: str
    ddc_dir: str
    dvc_backend: str
    dvc_stream: str
    dvc_suffix: str


STREAMS = (
    StreamMap("uniswap_v2", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("uniswap_v2", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("uniswap_v2", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("uniswap_v3", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("uniswap_v3", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("uniswap_v3", "raw_mints", "thegraph", "mints", "jsonl.gz"),
    StreamMap("uniswap_v3", "raw_burns", "thegraph", "burns", "jsonl.gz"),
    StreamMap("uniswap_v3", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("uniswap_v4", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("uniswap_v4", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("uniswap_v4", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("curve", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("curve", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("curve", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("balancer", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("balancer", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("balancer", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("sushiswap_v3", "raw_swaps", "thegraph", "swaps", "jsonl.gz"),
    StreamMap("sushiswap_v3", "raw_pool_day", "thegraph", "daily", "jsonl.gz"),
    StreamMap("sushiswap_v3", "raw_meta", "thegraph", "meta", "json"),
    StreamMap("fluid", "raw_swaps", "dune", "swaps", "jsonl.gz"),
    StreamMap("fluid", "raw_pool_day", "dune", "daily", "jsonl.gz"),
    StreamMap("fluid", "raw_meta", "dune", "meta", "json"),
)


def date_from_name(path: Path) -> str | None:
    match = DATE_RE.search(path.name)
    return match.group(1) if match else None


def target_path(raw_root: Path, item: StreamMap, date: str) -> Path:
    suffix = f".{item.dvc_suffix}"
    return raw_root / item.dvc_backend / item.source / f"{item.source}_{item.dvc_stream}_{date}{suffix}"


def install(src: Path, dst: Path, *, mode: str, replace: bool, dry_run: bool) -> str:
    if dst.exists() or dst.is_symlink():
        if not replace:
            return "exists"
        if not dry_run:
            dst.unlink()
    if dry_run:
        return "would-link" if mode == "symlink" else "would-copy"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        rel = os.path.relpath(src, dst.parent)
        dst.symlink_to(rel)
        return "linked"
    shutil.copy2(src, dst)
    return "copied"


def import_data(ddc_data: Path, raw_root: Path, *, mode: str, replace: bool, dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in STREAMS:
        source_dir = ddc_data / item.source / item.ddc_dir
        if not source_dir.exists():
            counts[f"missing:{item.source}:{item.ddc_dir}"] = counts.get(f"missing:{item.source}:{item.ddc_dir}", 0) + 1
            continue
        for src in sorted(source_dir.iterdir()):
            if not src.is_file() or not src.name.endswith((".json", ".jsonl.gz")):
                continue
            date = date_from_name(src)
            if not date:
                continue
            status = install(
                src,
                target_path(raw_root, item, date),
                mode=mode,
                replace=replace,
                dry_run=dry_run,
            )
            counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ddc-data", type=Path, default=DEFAULT_DDC_DATA)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_DVC_RAW)
    parser.add_argument("--mode", choices=["symlink", "copy"], default="symlink")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    counts = import_data(args.ddc_data, args.raw_root, mode=args.mode, replace=args.replace, dry_run=args.dry_run)
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
