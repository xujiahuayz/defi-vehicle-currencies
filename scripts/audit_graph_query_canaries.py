#!/usr/bin/env python3
"""Validate admitted Graph selections and measure bounded payload samples."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import statistics
import time
from typing import Any

from ddvc.fetch.graph import GraphClient, graph_keys, head_block
from ddvc.fetch.acquisition import GRAPH_ACTIVE_MANIFEST, GRAPH_BLOCK_FIELDS, GRAPH_CANARY_EVIDENCE, GRAPH_CANARY_FINAL, GRAPH_NEW_MANIFEST, GRAPH_SCHEMA_INVENTORY, GRAPH_TIME_FIELDS, frozen_provider_heads, path_value, repository_path_identity, research_sample_end_unix, sha256_file, validate_freeze, vector_alignment_failures, vector_alignment_results
from ddvc.fetch.graphql_selection import render_selection
from ddvc.fetch.raw import write_jsonl_gz
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.runtime import atomic_output


ACTIVE_MANIFEST = GRAPH_ACTIVE_MANIFEST
NEW_MANIFEST = GRAPH_NEW_MANIFEST
SCHEMA_INVENTORY = GRAPH_SCHEMA_INVENTORY
DEFAULT_OUTPUT = GRAPH_CANARY_FINAL
TIME_ORDER_FIELDS = GRAPH_TIME_FIELDS
BLOCK_ORDER_FIELDS = GRAPH_BLOCK_FIELDS
ORDER_FIELDS = (*TIME_ORDER_FIELDS, *BLOCK_ORDER_FIELDS, "id")
SAMPLE_END_UNIX = research_sample_end_unix()
TEMPORAL_MODES = frozenset({"active_stream", "historical_event_full", "historical_snapshot_full"})


def _query(
    entity: str,
    selection: str,
    *,
    rows: int,
    order_by: str,
    block: int,
    cutoff_field: str | None = None,
    upper_value: int | None = None,
) -> str:
    where = f", where: {{ {cutoff_field}_lte: {upper_value} }}" if cutoff_field is not None and upper_value is not None else ""
    return (
        "query Canary { "
        f"{entity}(first: {rows}, orderBy: {order_by}, orderDirection: desc, block: {{ number: {block} }}{where}) "
        f"{{ {selection} }} "
        "}"
    )


def _path_values(value: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return list(value) if isinstance(value, list) else [value]
    if isinstance(value, list):
        return [resolved for item in value for resolved in _path_values(item, parts)]
    if not isinstance(value, dict):
        return [None]
    return _path_values(value.get(parts[0]), parts[1:])


def _path_is_missing(row: dict[str, Any], path: str) -> bool:
    values = _path_values(row, path.split("."))
    return not values or all(value is None for value in values)


def _stream_records(
    active: dict,
    new: dict,
    *,
    active_current: bool = False,
    active_only: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for source in active["sources"]:
        if source["status"] != "available":
            continue
        records.setdefault(source["source"], []).extend(
            {
                "mode": "active_stream",
                "stream": entity["stream"],
                "entity": entity["entity"],
                "selection": (
                    render_selection(entity["current_selected_paths"])
                    if active_current
                    else entity["proposed_selection"]
                ),
                "paths": (
                    entity["current_selected_paths"]
                    if active_current
                    else entity["proposed_selected_paths"]
                ),
                "vector_owners": entity.get("vector_owners") or [],
            }
            for entity in source["entities"]
        )
    for source in ([] if active_only else new["sources"]):
        records.setdefault(source["source"], []).extend(
            {
                "mode": entity["mode"],
                "stream": entity["entity"],
                "entity": entity["entity"],
                "selection": entity["proposed_selection"],
                "paths": entity["proposed_selected_paths"],
                "vector_owners": entity.get("vector_owners") or [],
            }
            for entity in source["entities"]
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-manifest", type=Path, default=ACTIVE_MANIFEST)
    parser.add_argument("--new-manifest", type=Path, default=NEW_MANIFEST)
    parser.add_argument("--schema-inventory", type=Path, default=SCHEMA_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-output", type=Path, default=GRAPH_CANARY_EVIDENCE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--large-sample", type=int, default=1000)
    parser.add_argument("--retry-failed-from", type=Path)
    parser.add_argument("--retry-stale-from", type=Path)
    parser.add_argument("--head-block", action="append", default=[], metavar="SOURCE=BLOCK")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--head-only", action="store_true")
    parser.add_argument("--active-current", action="store_true")
    parser.add_argument("--active-only", action="store_true")
    args = parser.parse_args()
    head_overrides = {}
    for item in args.head_block:
        source_name, separator, value = item.partition("=")
        if not separator or source_name not in DEX_SOURCES:
            raise ValueError(f"invalid --head-block override: {item}")
        head_overrides[source_name] = int(value)
    active = json.loads(args.active_manifest.read_text(encoding="utf-8"))
    new = json.loads(args.new_manifest.read_text(encoding="utf-8"))
    records = _stream_records(
        active,
        new,
        active_current=args.active_current,
        active_only=args.active_only,
    )
    freeze = None
    if args.freeze:
        freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
        sample_end_blocks = validate_freeze(
            freeze,
            inventory=args.schema_inventory,
            active_manifest=args.active_manifest,
            new_manifest=args.new_manifest,
            expected_sources=set(records),
        )
        provider_heads = frozen_provider_heads(freeze)
        for source_name, block in provider_heads.items():
            prior = head_overrides.get(source_name)
            if prior is not None and prior != block:
                raise ValueError(f"head override disagrees with freeze for {source_name}")
            head_overrides[source_name] = block
    else:
        sample_end_blocks = {}
    if args.retry_failed_from:
        prior = json.loads(args.retry_failed_from.read_text(encoding="utf-8"))
        failed = {
            (source["source"], stream["entity"], stream["mode"])
            for source in prior["sources"]
            for stream in source["streams"]
            if stream["summary"]["failed_samples"]
        }
        records = {
            source: [stream for stream in streams if (source, stream["entity"], stream["mode"]) in failed]
            for source, streams in records.items()
        }
        records = {source: streams for source, streams in records.items() if streams}
    if args.retry_stale_from:
        prior = json.loads(args.retry_stale_from.read_text(encoding="utf-8"))
        prior_paths = {
            (source["source"], stream["entity"], stream["mode"]): stream["paths"]
            for source in prior["sources"]
            for stream in source["streams"]
        }
        records = {
            source: [
                stream
                for stream in streams
                if prior_paths.get((source, stream["entity"], stream["mode"])) != stream["paths"]
            ]
            for source, streams in records.items()
        }
        records = {source: streams for source, streams in records.items() if streams}
    keys = graph_keys()
    if not keys:
        raise RuntimeError("Graph query canaries require the configured key pool")

    def inspect_source(item: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
        source_name, streams = item
        source = DEX_SOURCES[source_name]
        client = GraphClient(source.subgraph_id, keys, graph_path=source.graph_path)
        terminal = head_overrides.get(source_name) or head_block(client)
        if terminal is None or source.genesis_block is None:
            raise RuntimeError(f"cannot establish canary block range for {source_name}")
        cutoff_block = sample_end_blocks.get(source_name, terminal)
        span = cutoff_block - source.genesis_block
        block_epochs = {
            "early": source.genesis_block + max(1, span // 10),
            "middle": source.genesis_block + max(1, span // 2),
            "head": cutoff_block,
        }
        sample_start_unix = int(datetime.combine(source.genesis, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        time_span = SAMPLE_END_UNIX - sample_start_unix
        time_epochs = {
            "early": sample_start_unix + max(1, time_span // 10),
            "middle": sample_start_unix + max(1, time_span // 2),
            "head": SAMPLE_END_UNIX,
        }
        results = []
        evidence_rows = []
        for stream in streams:
            direct_paths = {path for path in stream["paths"] if "." not in path}
            order_by = next((field for field in ORDER_FIELDS if field in direct_paths), "id")
            samples = []
            if stream["mode"] in TEMPORAL_MODES and order_by in TIME_ORDER_FIELDS:
                epochs = [(name, terminal, order_by, upper) for name, upper in time_epochs.items()]
            elif stream["mode"] in TEMPORAL_MODES and order_by in BLOCK_ORDER_FIELDS:
                epochs = [(name, terminal, order_by, upper) for name, upper in block_epochs.items()]
            elif stream["mode"] == "block_pinned_configuration":
                epochs = [(name, block, None, None) for name, block in block_epochs.items()]
            else:
                cutoff_field = next((field for field in (*TIME_ORDER_FIELDS, *BLOCK_ORDER_FIELDS) if field in direct_paths), None)
                upper = SAMPLE_END_UNIX if cutoff_field in TIME_ORDER_FIELDS else sample_end_blocks.get(source_name)
                query_block = terminal if cutoff_field else sample_end_blocks.get(source_name, terminal)
                epochs = [("head", query_block, cutoff_field, upper)]
            if args.head_only:
                epochs = [epoch for epoch in epochs if epoch[0] == "head"]
            for epoch, block, cutoff_field, upper_value in epochs:
                sample_sizes = (
                    (args.large_sample,)
                    if args.head_only
                    else ((100, args.large_sample) if epoch == "head" else (100,))
                )
                for requested in sample_sizes:
                    started = time.monotonic()
                    try:
                        data = client.query(
                            _query(
                                stream["entity"],
                                stream["selection"],
                                rows=requested,
                                order_by=order_by,
                                block=block,
                                cutoff_field=cutoff_field,
                                upper_value=upper_value,
                            ),
                            {},
                        )
                        rows = data.get(stream["entity"]) or []
                        encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()
                        order_values = []
                        for row in rows:
                            try:
                                order_values.append(int(path_value(row, order_by)))
                            except (TypeError, ValueError):
                                continue
                        null_rates = {}
                        for path in stream["paths"]:
                            null_rates[path] = (
                                sum(_path_is_missing(row, path) for row in rows) / len(rows)
                                if rows
                                else None
                            )
                        sample_key = f"{source_name}/{stream['stream']}/{epoch}/{requested}"
                        failure_indices = []
                        for row_index, row in enumerate(rows):
                            failures = vector_alignment_failures(row, stream["vector_owners"])
                            if failures:
                                failure_indices.append(row_index)
                            evidence_rows.append(
                                {
                                    "sample_key": sample_key,
                                    "source": source_name,
                                    "stream": stream["stream"],
                                    "epoch": epoch,
                                    "requested_rows": requested,
                                    "row_index": row_index,
                                    "row": row,
                                    "missing_paths": [
                                        path for path in stream["paths"] if _path_is_missing(row, path)
                                    ],
                                    "alignment_failures": failures,
                                }
                            )
                        samples.append(
                            {
                                "epoch": epoch,
                                "block": block,
                                "requested_rows": requested,
                                "returned_rows": len(rows),
                                "elapsed_seconds": round(time.monotonic() - started, 6),
                                "uncompressed_bytes": len(encoded),
                                "gzip_bytes": len(gzip.compress(encoded, compresslevel=6)),
                                "order_value_min": min(order_values) if order_values else None,
                                "order_value_max": max(order_values) if order_values else None,
                                "null_rates": null_rates,
                                "alignment_results": vector_alignment_results(
                                    rows, stream["vector_owners"]
                                ),
                                "pre_quarantine_evidence_key": sample_key,
                                "pre_quarantine_evidence_rows": len(rows),
                                "alignment_failure_row_indices": failure_indices,
                                "status": "ok",
                            }
                        )
                    except Exception as error:
                        samples.append(
                            {
                                "epoch": epoch,
                                "block": block,
                                "requested_rows": requested,
                                "elapsed_seconds": round(time.monotonic() - started, 6),
                                "status": "error",
                                "error_type": type(error).__name__,
                                "error": str(error)[:1000],
                            }
                        )
            ok = [sample for sample in samples if sample["status"] == "ok" and sample["returned_rows"]]
            bytes_per_row = [sample["gzip_bytes"] / sample["returned_rows"] for sample in ok]
            failed_samples = [sample for sample in samples if sample["status"] != "ok"]
            provider_archive_unavailable = bool(
                failed_samples
                and len(failed_samples) == len(samples)
                and stream["mode"] in {"static_identity", "static_or_right_censored_auxiliary"}
                and all("missing block" in str(sample.get("error", "")).lower() for sample in failed_samples)
            )
            has_alignment_failures = any(
                any(sample.get("alignment_failure_row_indices", []))
                for sample in samples
            )
            results.append(
                {
                    **stream,
                    "order_by": order_by,
                    "samples": samples,
                    "quality_action": (
                        "provider_archive_unavailable_quarantined"
                        if provider_archive_unavailable
                        else "unresolved_query_failure"
                        if failed_samples
                        else "row_quarantine_before_release"
                        if has_alignment_failures
                        else "admit"
                    ),
                    "summary": {
                        "successful_samples": len(ok),
                        "failed_samples": len(failed_samples),
                        "gzip_bytes_per_row_median": round(statistics.median(bytes_per_row), 3) if bytes_per_row else None,
                        "gzip_bytes_per_row_max": round(max(bytes_per_row), 3) if bytes_per_row else None,
                        "max_observed_null_rate": max(
                            (rate for sample in ok for rate in sample["null_rates"].values() if rate is not None),
                            default=None,
                        ),
                        "alignment_comparisons": sum(
                            sum(
                                result["compared_rows"]
                                for result in sample["alignment_results"].values()
                            )
                            for sample in ok
                        ),
                        "alignment_failure_comparisons": sum(
                            sum(
                                result["failure_rows"]
                                for result in sample["alignment_results"].values()
                            )
                            for sample in ok
                        ),
                        "alignment_failure_rows": sum(
                            len(sample.get("alignment_failure_row_indices", []))
                            for sample in ok
                        ),
                    },
                }
            )
        return {"source": source_name, "genesis_block": source.genesis_block, "head_block": terminal, "sample_end_block": sample_end_blocks.get(source_name), "streams": results, "evidence_rows": evidence_rows}

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(records)))) as executor:
        sources = list(executor.map(inspect_source, sorted(records.items())))
    evidence_rows = sorted(
        (row for source in sources for row in source.pop("evidence_rows")),
        key=lambda row: (row["source"], row["stream"], row["epoch"], row["requested_rows"], row["row_index"]),
    )
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_gz(args.evidence_output, evidence_rows)
    payload = {
        "schema_version": 2,
        "kind": "graph_admitted_query_canaries",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_sample_end": RESEARCH_SAMPLE_END,
        "schema_inventory_sha256": sha256_file(args.schema_inventory),
        "active_manifest_sha256": sha256_file(args.active_manifest),
        "new_manifest_sha256": sha256_file(args.new_manifest),
        "freeze_sha256": sha256_file(args.freeze) if args.freeze else None,
        "pre_quarantine_evidence": {
            "path": repository_path_identity(args.evidence_output),
            "sha256": sha256_file(args.evidence_output),
            "rows": len(evidence_rows),
        },
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    streams = [stream for source in sources for stream in source["streams"]]
    print(
        json.dumps(
            {
                "streams": len(streams),
                "streams_with_failed_samples": sum(stream["summary"]["failed_samples"] > 0 for stream in streams),
                "alignment_comparisons": sum(
                    stream["summary"]["alignment_comparisons"] for stream in streams
                ),
                "alignment_failure_comparisons": sum(
                    stream["summary"]["alignment_failure_comparisons"] for stream in streams
                ),
                "alignment_failure_rows": sum(
                    stream["summary"]["alignment_failure_rows"] for stream in streams
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
