#!/usr/bin/env python3
"""Freeze one Graph acquisition generation to manifests, cutoff and provider heads."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FREEZE, GRAPH_ACTIVE_MANIFEST, GRAPH_NEW_MANIFEST, GRAPH_SCHEMA_INVENTORY, sha256_file, source_contract_sha256
from ddvc.fetch.graph import GraphClient, graph_keys, head_block
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.ethereum_day_cuts import RAW_DAY_BOUND_ROOT, load_or_resolve_utc_day_block_bounds
from ddvc.runtime import atomic_output


DEFAULT_INVENTORY = GRAPH_SCHEMA_INVENTORY
DEFAULT_ACTIVE = GRAPH_ACTIVE_MANIFEST
DEFAULT_NEW = GRAPH_NEW_MANIFEST
DEFAULT_OUTPUT = GRAPH_ACQUISITION_FREEZE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--active-manifest", type=Path, default=DEFAULT_ACTIVE)
    parser.add_argument("--new-manifest", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample-end-bound-root", type=Path, default=RAW_DAY_BOUND_ROOT)
    args = parser.parse_args()
    active = json.loads(args.active_manifest.read_text(encoding="utf-8"))
    new = json.loads(args.new_manifest.read_text(encoding="utf-8"))
    sources = sorted(
        {
            str(source["source"])
            for manifest in (active, new)
            for source in manifest["sources"]
            if source.get("status", "available") == "available"
        }
    )
    keys = graph_keys()
    if not keys:
        raise RuntimeError("Graph acquisition freeze requires the configured key pool")

    def freeze_source(source_name: str) -> dict[str, object]:
        source = DEX_SOURCES[source_name]
        client = GraphClient(source.subgraph_id, keys, graph_path=source.graph_path)
        block = head_block(client)
        if block is None:
            raise RuntimeError(f"cannot freeze Graph head for {source_name}")
        return {
            "source": source_name,
            "head_block": block,
            "source_contract_sha256": source_contract_sha256(source_name),
        }

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(sources)))) as executor:
        frozen_sources = list(executor.map(freeze_source, sources))
    sample_end_boundary = load_or_resolve_utc_day_block_bounds(
        RESEARCH_SAMPLE_END,
        min(int(record["head_block"]) for record in frozen_sources),
        fetch=True,
        root=args.sample_end_bound_root,
        lower_block=min(
            int(DEX_SOURCES[source].genesis_block or 0) for source in sources
        ),
    )
    sample_end_block = int(sample_end_boundary["end_block"])
    for record in frozen_sources:
        record["sample_end_block"] = sample_end_block
    payload = {
        "schema_version": 1,
        "kind": "graph_acquisition_freeze",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_sample_end": RESEARCH_SAMPLE_END,
        "sample_end_boundary": sample_end_boundary,
        "schema_inventory_sha256": sha256_file(args.inventory),
        "active_manifest_sha256": sha256_file(args.active_manifest),
        "new_manifest_sha256": sha256_file(args.new_manifest),
        "sources": frozen_sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps({"sources": len(frozen_sources)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
