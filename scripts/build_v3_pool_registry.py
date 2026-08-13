#!/usr/bin/env python3
"""Build the complete Uniswap V3 pool census from factory PoolCreated events."""

from __future__ import annotations

import argparse
import json

from ddvc.ethereum_logs import fetch_exact_logs_with_evidence
from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.runtime import exclusive_job
from ddvc.v3_pool_registry import (
    FACTORY_EVENT_TOPICS,
    RAW_V3_POOL_REGISTRY_ROOT,
    V3_FACTORY,
    V3_FACTORY_DEPLOYMENT_BLOCK,
    build_registry,
    load_or_resolve_frozen_upper,
    root_ranges,
)


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
GRAPH_STATIC_PATH = GRAPH_ROOT / f"uniswap_v3_pool_statics_{RESEARCH_SAMPLE_END}.jsonl.gz"
END_META_PATH = GRAPH_ROOT / f"uniswap_v3_meta_{RESEARCH_SAMPLE_END}.json"


def metadata_blocks() -> tuple[int, int]:
    metadata = json.loads(END_META_PATH.read_text(encoding="utf-8"))
    snapshot = metadata.get("head_block_at_fetch") or metadata.get("max_block")
    cutoff = metadata.get("max_block")
    if snapshot is None or cutoff is None:
        raise RuntimeError("V3 research-end metadata lacks snapshot or analysis block bounds")
    return int(snapshot), int(cutoff)


def preflight(upper_block: int) -> None:
    frozen = load_or_resolve_frozen_upper(
        upper_block,
        fetch=True,
        root=RAW_V3_POOL_REGISTRY_ROOT,
    )
    ranges = root_ranges(V3_FACTORY_DEPLOYMENT_BLOCK, upper_block)
    probes = [ranges[0], ranges[len(ranges) // 2], ranges[-1]]
    for start, end in probes:
        rows, evidence = fetch_exact_logs_with_evidence(
            start_block=start,
            end_block=end,
            topics=FACTORY_EVENT_TOPICS,
            address=V3_FACTORY,
            frozen_upper=frozen,
        )
        print(
            f"  preflight {start:,}-{end:,}: rows={len(rows):,}; endpoint={evidence['endpoint']['host']}",
            flush=True,
        )
    print(f"PASS: V3 factory preflight; roots={len(ranges):,}; fixed_span=10,000", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upper-block", type=int)
    parser.add_argument("--analysis-cutoff-block", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=12)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    metadata_snapshot, metadata_cutoff = metadata_blocks()
    upper_block = args.upper_block or metadata_snapshot
    analysis_cutoff = args.analysis_cutoff_block or metadata_cutoff
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="independent Uniswap V3 factory pool census"):
        if not args.no_fetch:
            preflight(upper_block)
        if args.preflight_only:
            return 0
        pools, missing = build_registry(
            upper_block,
            GRAPH_STATIC_PATH,
            analysis_cutoff_block=analysis_cutoff,
            fetch=not args.no_fetch,
            workers=args.workers,
            max_attempts=args.max_attempts,
        )
    print(f"PASS: V3 factory pools={pools:,}; missing_from_graph={missing:,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
