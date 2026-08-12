#!/usr/bin/env python3
"""Validate the Graph inventory or stage an explicitly selected thin acquisition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FORECAST, GRAPH_ACQUISITION_FREEZE, GRAPH_ACTIVE_MANIFEST, GRAPH_CANARY_CURRENT, GRAPH_CANARY_EVIDENCE, GRAPH_CANARY_FINAL, GRAPH_NEW_MANIFEST, GRAPH_ROOT_POPULATION, GRAPH_SCHEMA_INVENTORY, validate_prelaunch_inputs
from ddvc.fetch.acquisition_release import acquisition_tasks, publish_graph_acquisition
from ddvc.paths import DATA_DIR
from ddvc.runtime import exclusive_job


DEFAULT_POINTER = DATA_DIR / "raw" / "thegraph_d1" / "current.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=GRAPH_ACQUISITION_FREEZE)
    parser.add_argument("--inventory", type=Path, default=GRAPH_SCHEMA_INVENTORY)
    parser.add_argument("--active-manifest", type=Path, default=GRAPH_ACTIVE_MANIFEST)
    parser.add_argument("--new-manifest", type=Path, default=GRAPH_NEW_MANIFEST)
    parser.add_argument("--canary", type=Path, default=GRAPH_CANARY_FINAL)
    parser.add_argument("--canary-evidence", type=Path, default=GRAPH_CANARY_EVIDENCE)
    parser.add_argument("--current-canary", type=Path, default=GRAPH_CANARY_CURRENT)
    parser.add_argument("--root-population", type=Path, default=GRAPH_ROOT_POPULATION)
    parser.add_argument("--forecast", type=Path, default=GRAPH_ACQUISITION_FORECAST)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--max-pages-per-chunk", type=int, default=10_000)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--stream", action="append", default=[], metavar="SOURCE/STREAM", help="stage one named stream; repeat for a bounded thin acquisition")
    parser.add_argument("--materiality-reason", help="named consumer and material missing field that justify the selected acquisition")
    parser.add_argument("--execute", action="store_true", help="perform only the explicitly selected fetch; omitted means inventory validation only")
    args = parser.parse_args()
    prelaunch = validate_prelaunch_inputs(
        freeze_path=args.freeze,
        inventory_path=args.inventory,
        active_manifest_path=args.active_manifest,
        new_manifest_path=args.new_manifest,
        canary_path=args.canary,
        canary_evidence_path=args.canary_evidence,
        current_canary_path=args.current_canary,
        root_population_path=args.root_population,
        forecast_path=args.forecast,
    )
    tasks = acquisition_tasks(
        active_manifest=args.active_manifest,
        new_manifest=args.new_manifest,
        sample_end_blocks=prelaunch["sample_end_blocks"],
        provider_head_blocks=prelaunch["provider_head_blocks"],
        canary_path=args.canary,
    )
    if len(tasks) != int(prelaunch["stream_count"]):
        raise ValueError("prelaunch canary and frozen manifest stream perimeters disagree")
    if not args.execute:
        print(json.dumps({"status": "inventory_validated_no_fetch", "inventoried_streams": len(tasks), "freeze_sha256": prelaunch["freeze_sha256"]}, sort_keys=True))
        return 0
    if not args.stream or not args.materiality_reason:
        raise ValueError("execution requires at least one --stream and --materiality-reason; the frozen inventory is not an acquisition plan")
    requested = []
    for value in args.stream:
        source, separator, stream = value.partition("/")
        if not separator or not source or not stream:
            raise ValueError(f"invalid --stream {value!r}; expected SOURCE/STREAM")
        requested.append((source, stream))
    if len(requested) != len(set(requested)):
        raise ValueError("selected Graph streams contain duplicates")
    task_map = {(task.source, task.entity.stream): task for task in tasks}
    unknown = sorted(set(requested).difference(task_map))
    if unknown:
        raise ValueError(f"selected Graph streams are outside the frozen inventory: {unknown}")
    selected_tasks = tuple(task_map[key] for key in sorted(requested))
    inputs = [args.freeze, args.inventory, args.active_manifest, args.new_manifest, args.canary, args.canary_evidence, args.current_canary, args.root_population, args.forecast]
    with exclusive_job(args.pointer.with_suffix(".lock"), job="selected Graph acquisition"):
        publish_graph_acquisition(
            pointer_path=args.pointer,
            tasks=selected_tasks,
            inputs=inputs,
            code_sources=[
                "scripts/stage_graph_acquisition.py",
                "src/ddvc/fetch/acquisition.py",
                "src/ddvc/fetch/acquisition_release.py",
                "src/ddvc/fetch/raw.py",
                "src/ddvc/fetch/schemas.py",
            ],
            max_pages_per_chunk=args.max_pages_per_chunk,
            workers=args.workers,
            selection_reason=args.materiality_reason,
        )
    print(json.dumps({"status": "released", "streams": len(selected_tasks), "pointer": str(args.pointer)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
