#!/usr/bin/env python3
"""Snapshot live GraphQL fields before deciding one batched raw backfill."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.acquisition import GRAPH_SCHEMA_INVENTORY
from ddvc.fetch.schema_inventory import inventory_entity, inventory_query_roots, inventory_reachable_types
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.runtime import atomic_output


DEFAULT_OUTPUT = GRAPH_SCHEMA_INVENTORY


def build_inventory(
    source_names: list[str],
    *,
    max_depth: int,
    workers: int = 4,
) -> dict[str, object]:
    keys = graph_keys()
    if not keys:
        raise RuntimeError("Graph schema inventory requires the configured Graph key pool")
    def inspect(source_name: str) -> dict[str, object] | None:
        source = DEX_SOURCES[source_name]
        if source.backend != "thegraph":
            return None
        client = GraphClient(source.subgraph_id, keys, graph_path=source.graph_path)
        query_roots = inventory_query_roots(client)
        entities = []
        for specification in get_schema(source.schema).entities:
            entities.append(
                {
                    "stream": specification.stream,
                    **inventory_entity(
                        client,
                        entity=specification.entity,
                        selected_fields=specification.fields,
                        max_depth=max_depth,
                    ),
                }
            )
        type_catalog = inventory_reachable_types(
            client,
            seed_types=sorted(
                {
                    str(root["type"])
                    for root in query_roots
                    if root["kind"] in {"OBJECT", "INTERFACE"}
                }
            ),
        )
        return {
            "source": source_name,
            "schema_family": source.schema,
            "status": "available",
            "entities": entities,
            "query_roots": query_roots,
            "reachable_type_catalog": type_catalog,
        }

    def inspect_safe(source_name: str) -> dict[str, object] | None:
        try:
            return inspect(source_name)
        except Exception as error:
            source = DEX_SOURCES[source_name]
            return {
                "source": source_name,
                "schema_family": source.schema,
                "status": "unavailable",
                "error_type": type(error).__name__,
                "error": str(error)[:1000],
                "entities": [],
                "query_roots": [],
                "reachable_type_catalog": [],
            }

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(source_names)))) as executor:
        sources = [source for source in executor.map(inspect_safe, source_names) if source is not None]
    return {
        "schema_version": 1,
        "kind": "live_graphql_schema_inventory",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection_policy": "admit every nondeprecated primitive field reachable through bounded singular child identities; list-valued child fields require an explicit row-multiplication adjudication",
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=sorted(DEX_SOURCES))
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    selected = args.source or sorted(
        name for name, source in DEX_SOURCES.items() if source.backend == "thegraph"
    )
    payload = build_inventory(
        selected,
        max_depth=args.max_depth,
        workers=args.workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entities = sum(len(source["entities"]) for source in payload["sources"])
    missing = sum(
        len(entity["unselected_primitive_paths"])
        + len(entity["unselected_list_primitive_paths"])
        for source in payload["sources"]
        for entity in source["entities"]
    )
    print(f"Graph schema inventory: {len(payload['sources'])} sources, {entities} entities, {missing} unselected primitive paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
