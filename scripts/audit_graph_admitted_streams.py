#!/usr/bin/env python3
"""Inventory every newly admitted Graph collection before query construction."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.acquisition import GRAPH_NEW_STREAM_INVENTORY, GRAPH_SCHEMA_INVENTORY
from ddvc.fetch.schema_admission import build_field_admission_manifest
from ddvc.fetch.schema_inventory import inventory_entity, query_fields
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.runtime import atomic_output


DEFAULT_INVENTORY = GRAPH_SCHEMA_INVENTORY
DEFAULT_OUTPUT = GRAPH_NEW_STREAM_INVENTORY


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    admission = build_field_admission_manifest(inventory)
    keys = graph_keys()
    if not keys:
        raise RuntimeError("Graph admitted-stream inventory requires the configured key pool")

    def inspect(source_record: dict) -> dict:
        source_name = str(source_record["source"])
        source = DEX_SOURCES[source_name]
        roots = [
            root
            for root in source_record["query_root_decisions"]
            if root["decision"] == "admit" and root["mode"] != "active_stream"
        ]
        if not roots:
            return {"source": source_name, "status": source_record["status"], "entities": []}
        client = GraphClient(source.subgraph_id, keys, graph_path=source.graph_path)
        available_query_fields = query_fields(client)
        type_cache: dict[str, list[dict]] = {}
        entities = []
        for root in roots:
            entities.append(
                {
                    "mode": root["mode"],
                    **inventory_entity(
                        client,
                        entity=str(root["name"]),
                        selected_fields="",
                        max_depth=args.max_depth,
                        query_field_catalog=available_query_fields,
                        type_cache=type_cache,
                    ),
                }
            )
        return {"source": source_name, "status": "available", "entities": entities}

    available = [source for source in admission["sources"] if source["status"] == "available"]
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(available)))) as executor:
        sources = list(executor.map(inspect, available))
    payload = {
        "schema_version": 1,
        "kind": "graph_newly_admitted_stream_inventory",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_inventory_captured_at_utc": inventory.get("captured_at_utc"),
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    count = sum(len(source["entities"]) for source in sources)
    print(f"Admitted stream inventory: {count} new collections across {len(sources)} sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
