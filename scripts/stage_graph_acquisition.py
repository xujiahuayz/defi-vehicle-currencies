#!/usr/bin/env python3
"""Validate the Graph inventory or stage an explicitly selected thin acquisition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FORECAST, GRAPH_ACQUISITION_FREEZE, GRAPH_ACTIVE_MANIFEST, GRAPH_CANARY_CURRENT, GRAPH_CANARY_CURRENT_EVIDENCE, GRAPH_CANARY_EVIDENCE, GRAPH_CANARY_FINAL, GRAPH_NEW_MANIFEST, GRAPH_ROOT_POPULATION, GRAPH_SCHEMA_INVENTORY, GRAPH_THIN_CONSUMER_AUDIT, validate_prelaunch_inputs
from ddvc.fetch.acquisition_release import acquisition_tasks, publish_graph_acquisition
from ddvc.fetch.material_consumers import GRAPH_MATERIAL_CONSUMER_INTENTS, validate_material_consumer_selection
from ddvc.fetch.thin_consumer_audit import resolve_thin_consumer_audit
from ddvc.paths import DATA_DIR, PRIMARY_REPO_ROOT
from ddvc.runtime import exclusive_job


DEFAULT_POINTER = DATA_DIR / "raw" / "thegraph_d1" / "current.json"
DEFAULT_DATA_ROOT = PRIMARY_REPO_ROOT / "data"
DEFAULT_CERTIFICATE_ROOT = DEFAULT_DATA_ROOT / "processed" / "graph_thin_consumer_audit" / "source_markers"


def certify_installed_no_fetch(
    *,
    thin_audit: Path,
    data_root: Path,
    certificate_root: Path,
    prelaunch: dict[str, object],
    intents=None,
) -> dict[str, object]:
    """Reopen exact installed identities and match the prelaunch hash chain."""

    certification = resolve_thin_consumer_audit(thin_audit, data_root=data_root, certificate_root=certificate_root, intents=intents)
    if certification["audit_sha256"] != prelaunch["thin_consumer_audit_sha256"] or certification["consumer_registry_sha256"] != prelaunch["consumer_registry_sha256"]:
        raise ValueError("Graph thin-consumer certification changed after prelaunch validation")
    return certification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=GRAPH_ACQUISITION_FREEZE)
    parser.add_argument("--inventory", type=Path, default=GRAPH_SCHEMA_INVENTORY)
    parser.add_argument("--active-manifest", type=Path, default=GRAPH_ACTIVE_MANIFEST)
    parser.add_argument("--new-manifest", type=Path, default=GRAPH_NEW_MANIFEST)
    parser.add_argument("--canary", type=Path, default=GRAPH_CANARY_FINAL)
    parser.add_argument("--canary-evidence", type=Path, default=GRAPH_CANARY_EVIDENCE)
    parser.add_argument("--current-canary", type=Path, default=GRAPH_CANARY_CURRENT)
    parser.add_argument("--current-canary-evidence", type=Path, default=GRAPH_CANARY_CURRENT_EVIDENCE)
    parser.add_argument("--root-population", type=Path, default=GRAPH_ROOT_POPULATION)
    parser.add_argument("--forecast", type=Path, default=GRAPH_ACQUISITION_FORECAST)
    parser.add_argument("--thin-audit", type=Path, default=GRAPH_THIN_CONSUMER_AUDIT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--certificate-root", type=Path, default=DEFAULT_CERTIFICATE_ROOT)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--max-pages-per-chunk", type=int, default=10_000)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--stream", action="append", default=[], metavar="SOURCE/STREAM", help="stage one named stream; repeat for a bounded thin acquisition")
    parser.add_argument("--consumer", choices=sorted(GRAPH_MATERIAL_CONSUMER_INTENTS), help="closed material-consumer intent whose reviewed allowlist owns the selected streams")
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
        current_canary_evidence_path=args.current_canary_evidence,
        root_population_path=args.root_population,
        forecast_path=args.forecast,
        thin_audit_path=args.thin_audit,
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
    try:
        certification = certify_installed_no_fetch(thin_audit=args.thin_audit, data_root=args.data_root, certificate_root=args.certificate_root, prelaunch=prelaunch)
    except (FileNotFoundError, OSError, ValueError) as error:
        if args.execute:
            raise
        print(json.dumps({"status": "inventory_validated_only_certification_unavailable", "inventoried_streams": len(tasks), "freeze_sha256": prelaunch["freeze_sha256"], "certification_error": str(error)}, sort_keys=True))
        return 0
    if not args.execute:
        print(json.dumps({"status": "inventory_validated_no_fetch", "inventoried_streams": len(tasks), "freeze_sha256": prelaunch["freeze_sha256"], "thin_consumer_audit_sha256": certification["audit_sha256"]}, sort_keys=True))
        return 0
    if not args.stream or not args.consumer:
        raise ValueError("execution requires at least one --stream and one closed --consumer intent; the frozen inventory is not an acquisition plan")
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
    validate_material_consumer_selection(args.consumer, set(requested))
    selected_tasks = tuple(task_map[key] for key in sorted(requested))
    inputs = [args.freeze, args.inventory, args.active_manifest, args.new_manifest, args.canary, args.canary_evidence, args.current_canary, args.current_canary_evidence, args.root_population, args.forecast, args.thin_audit]
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
            material_consumer=args.consumer,
        )
    print(json.dumps({"status": "released", "streams": len(selected_tasks), "pointer": str(args.pointer)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
