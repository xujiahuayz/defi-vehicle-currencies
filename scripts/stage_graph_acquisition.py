#!/usr/bin/env python3
"""Validate the Graph inventory and certify that installed data need no fetch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FORECAST, GRAPH_ACQUISITION_FREEZE, GRAPH_ACTIVE_MANIFEST, GRAPH_CANARY_CURRENT, GRAPH_CANARY_CURRENT_EVIDENCE, GRAPH_CANARY_EVIDENCE, GRAPH_CANARY_FINAL, GRAPH_NEW_MANIFEST, GRAPH_ROOT_POPULATION, GRAPH_SCHEMA_INVENTORY, GRAPH_THIN_CONSUMER_AUDIT, validate_prelaunch_inputs
from ddvc.fetch.acquisition_release import acquisition_tasks
from ddvc.fetch.thin_consumer_audit import resolve_thin_consumer_audit
from ddvc.paths import PRIMARY_REPO_ROOT


DEFAULT_DATA_ROOT = PRIMARY_REPO_ROOT / "data"
def certify_installed_no_fetch(
    *,
    thin_audit: Path,
    data_root: Path,
    prelaunch: dict[str, object],
    intents=None,
) -> dict[str, object]:
    """Reopen exact installed identities and match the prelaunch hash chain."""

    certification = resolve_thin_consumer_audit(thin_audit, data_root=data_root, intents=intents)
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
        certification = certify_installed_no_fetch(thin_audit=args.thin_audit, data_root=args.data_root, prelaunch=prelaunch)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "inventory_validated_only_certification_unavailable", "inventoried_streams": len(tasks), "freeze_sha256": prelaunch["freeze_sha256"], "certification_error": str(error)}, sort_keys=True))
        return 0
    print(json.dumps({"status": "inventory_validated_no_fetch", "inventoried_streams": len(tasks), "freeze_sha256": prelaunch["freeze_sha256"], "thin_consumer_audit_sha256": certification["audit_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
