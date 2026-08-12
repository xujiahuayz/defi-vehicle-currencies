#!/usr/bin/env python3
"""Probe every Graph collection root at the frozen acquisition generation."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FREEZE, GRAPH_ACTIVE_MANIFEST, GRAPH_NEW_MANIFEST, GRAPH_ROOT_POPULATION, GRAPH_SCHEMA_INVENTORY, GRAPH_TIME_FIELDS, frozen_provider_heads, research_sample_end_unix, sha256_file, validate_freeze
from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.runtime import atomic_output


SCHEMA_INVENTORY = GRAPH_SCHEMA_INVENTORY
ACTIVE_MANIFEST = GRAPH_ACTIVE_MANIFEST
NEW_MANIFEST = GRAPH_NEW_MANIFEST
FREEZE = GRAPH_ACQUISITION_FREEZE
DEFAULT_OUTPUT = GRAPH_ROOT_POPULATION
TIME_FIELDS = GRAPH_TIME_FIELDS
SAMPLE_END_UNIX = research_sample_end_unix()


def _type_catalog(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record["name"]): record for record in source["reachable_type_catalog"]}


def _probe_contract(root: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> tuple[str, str | None]:
    fields = catalog[str(root["type"])]["fields"]
    primitive = [
        str(field["name"])
        for field in fields
        if field["kind"] in {"SCALAR", "ENUM"} and not field["list_valued"] and not field["deprecated"]
    ]
    if not primitive:
        raise ValueError(f"Graph root has no primitive probe field: {root['name']}")
    selection = "id" if "id" in primitive else primitive[0]
    time_field = next((field for field in TIME_FIELDS if field in primitive), None)
    has_where = any(argument["name"] == "where" for argument in root["arguments"])
    return selection, time_field if has_where else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-inventory", type=Path, default=SCHEMA_INVENTORY)
    parser.add_argument("--active-manifest", type=Path, default=ACTIVE_MANIFEST)
    parser.add_argument("--new-manifest", type=Path, default=NEW_MANIFEST)
    parser.add_argument("--freeze", type=Path, default=FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=7)
    args = parser.parse_args()
    inventory = json.loads(args.schema_inventory.read_text(encoding="utf-8"))
    active = json.loads(args.active_manifest.read_text(encoding="utf-8"))
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    source_names = {
        str(source["source"])
        for source in inventory["sources"]
        if source["status"] == "available"
    }
    sample_end_blocks = validate_freeze(
        freeze,
        inventory=args.schema_inventory,
        active_manifest=args.active_manifest,
        new_manifest=args.new_manifest,
        expected_sources=source_names,
    )
    provider_heads = frozen_provider_heads(freeze)
    decisions = {
        (str(source["source"]), str(root["name"])): root
        for source in active["sources"]
        for root in source["query_root_decisions"]
    }
    keys = graph_keys()
    if not keys:
        raise RuntimeError("Graph root probes require the configured key pool")

    def inspect(source: dict[str, Any]) -> dict[str, Any]:
        source_name = str(source["source"])
        contract = DEX_SOURCES[source_name]
        client = GraphClient(contract.subgraph_id, keys, graph_path=contract.graph_path)
        catalog = _type_catalog(source)
        roots = []
        for root in source["query_roots"]:
            if not root["list_valued"] or str(root["name"]).startswith("_"):
                continue
            selection, time_field = _probe_contract(root, catalog)
            where = f", where: {{ {time_field}_lte: {SAMPLE_END_UNIX} }}" if time_field else ""
            query_block = provider_heads[source_name] if time_field else sample_end_blocks[source_name]
            query = (
                "query RootPopulation { "
                f"{root['name']}(first: 1, block: {{ number: {query_block} }}{where}) "
                f"{{ {selection} }} "
                "}"
            )
            record = {
                "root": root["name"],
                "type": root["type"],
                "probe_field": selection,
                "cutoff_field": time_field,
                "adjudication": decisions[(source_name, str(root["name"]))],
            }
            try:
                rows = client.query(query, {}).get(str(root["name"])) or []
                roots.append({**record, "status": "nonempty" if rows else "empty", "returned_rows": len(rows)})
            except Exception as error:
                error_text = str(error)[:1000]
                provider_archive_unavailable = bool(
                    time_field is None and "missing block" in error_text.lower()
                )
                roots.append(
                    {
                        **record,
                        "status": (
                            "provider_archive_unavailable_quarantined"
                            if provider_archive_unavailable
                            else "error"
                        ),
                        "error_type": type(error).__name__,
                        "error": error_text,
                    }
                )
        return {"source": source_name, "head_block": provider_heads[source_name], "sample_end_block": sample_end_blocks[source_name], "roots": roots}

    available = [source for source in inventory["sources"] if source["status"] == "available"]
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(available)))) as executor:
        sources = list(executor.map(inspect, available))
    roots = [root for source in sources for root in source["roots"]]
    payload = {
        "schema_version": 1,
        "kind": "graph_root_population_at_frozen_generation",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_sample_end": RESEARCH_SAMPLE_END,
        "schema_inventory_sha256": sha256_file(args.schema_inventory),
        "active_manifest_sha256": sha256_file(args.active_manifest),
        "new_manifest_sha256": sha256_file(args.new_manifest),
        "freeze_sha256": sha256_file(args.freeze),
        "summary": {
            "collection_roots": len(roots),
            "nonempty": sum(root["status"] == "nonempty" for root in roots),
            "empty": sum(root["status"] == "empty" for root in roots),
            "errors": sum(root["status"] == "error" for root in roots),
            "provider_archive_unavailable_quarantined": sum(root["status"] == "provider_archive_unavailable_quarantined" for root in roots),
            "confirmed_empty_adjudications": sum(
                root["adjudication"]["reason"] == "confirmed_empty_at_frozen_cutoff"
                for root in roots
            ),
        },
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
