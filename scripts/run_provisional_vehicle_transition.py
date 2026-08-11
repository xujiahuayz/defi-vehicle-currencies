#!/usr/bin/env python3
"""Run the current vehicle-transition design as quarantined provisional evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ddvc.model_artifacts import attach_spec_ids
from ddvc.model_registry import canonical_hash
from ddvc.paths import REPO_ROOT
from ddvc.runtime import atomic_output
from scripts.build_intermediation_by_type import (
    HAC_LAG,
    VEHICLE_TRANSITION_ESTIMANDS,
    VEHICLE_TRANSITION_SCOPES,
    VEHICLE_TRANSITION_SPECIFICATIONS,
    vehicle_transition_support_geometry,
    vehicle_transition_tests,
)
from scripts.run_vehicle_transition_e0 import SPEC_ID_COLUMNS


SCHEMA_VERSION = 1
KIND = "provisional_vehicle_transition_run"
STATUS = "provisional_diagnostic_only"
CODE_SOURCES = (
    "scripts/run_provisional_vehicle_transition.py",
    "scripts/build_intermediation_by_type.py",
    "scripts/run_vehicle_transition_e0.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def analytical_columns() -> tuple[str, ...]:
    columns = {"date"}
    for scope in VEHICLE_TRANSITION_SCOPES:
        for _weighting, _support, prefix in VEHICLE_TRANSITION_ESTIMANDS:
            columns.add(f"{prefix}{scope}_native")
            columns.add(f"{prefix}{scope}_stable")
    return tuple(sorted(columns))


def _code_identity(root: Path) -> tuple[list[dict[str, str]], str]:
    records = []
    for relative in CODE_SOURCES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"provisional engine source is absent: {relative}")
        records.append({"path": relative, "sha256": _file_sha256(path)})
    return records, canonical_hash(records)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for record in frame.to_dict("records"):
                clean = {
                    key: None
                    if value is None or (isinstance(value, (float, np.floating)) and not np.isfinite(value))
                    else value.item()
                    if isinstance(value, np.generic)
                    else value
                    for key, value in record.items()
                }
                handle.write(json.dumps(clean, sort_keys=True, default=str) + "\n")


def _input_snapshot(panel: pd.DataFrame) -> pd.DataFrame:
    required = analytical_columns()
    missing = sorted(set(required) - set(panel.columns))
    if missing:
        raise ValueError(f"provisional vehicle-transition input lacks analytical columns: {missing}")
    snapshot = panel.loc[:, list(required)].copy()
    snapshot["date"] = pd.to_datetime(snapshot["date"]).dt.normalize()
    if snapshot["date"].isna().any() or snapshot["date"].duplicated().any():
        raise ValueError("provisional vehicle-transition input requires unique valid dates")
    return snapshot.sort_values("date", kind="stable").reset_index(drop=True)


def _read_manifest(run_directory: Path) -> dict[str, Any]:
    manifest_path = run_directory / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != KIND:
        raise ValueError(f"comparison target is not a provisional vehicle-transition run: {manifest_path}")
    if payload.get("status") != STATUS or payload.get("paper_claim_eligible") is not False:
        raise ValueError(f"comparison target is not quarantined: {manifest_path}")
    return payload


def compare_runs(previous_directory: Path, current_directory: Path) -> dict[str, Any]:
    previous_manifest = _read_manifest(previous_directory)
    current_manifest = _read_manifest(current_directory)
    previous_input = pd.read_parquet(previous_directory / "analytical_input_snapshot.parquet").set_index("date")
    current_input = pd.read_parquet(current_directory / "analytical_input_snapshot.parquet").set_index("date")
    previous_dates = set(previous_input.index)
    current_dates = set(current_input.index)
    shared = sorted(previous_dates & current_dates)
    common_columns = sorted(set(previous_input.columns) & set(current_input.columns))
    changed_by_variable: dict[str, int] = {}
    row_changed = pd.Series(False, index=shared, dtype=bool)
    for column in common_columns:
        left = previous_input.loc[shared, column]
        right = current_input.loc[shared, column]
        equal = left.eq(right) | (left.isna() & right.isna())
        changed_by_variable[column] = int((~equal).sum())
        row_changed |= ~equal
    changed_by_variable = {key: value for key, value in changed_by_variable.items() if value}

    previous_estimates = pd.read_json(previous_directory / "estimates.provisional.jsonl", lines=True).set_index("spec_id")
    current_estimates = pd.read_json(current_directory / "estimates.provisional.jsonl", lines=True).set_index("spec_id")
    shared_specs = sorted(set(previous_estimates.index) & set(current_estimates.index))
    coefficient_changes = []
    instability = False
    all_outputs_invariant = True
    for spec_id in shared_specs:
        old = previous_estimates.loc[spec_id]
        new = current_estimates.loc[spec_id]
        estimate_delta = float(new["change"] - old["change"])
        se_delta = float(new["hac_standard_error"] - old["hac_standard_error"])
        sample_delta = int(new["days"] - old["days"])
        sign_flip = bool(np.sign(new["change"]) != np.sign(old["change"]))
        significance_flip = bool((old["p_value"] < 0.05) != (new["p_value"] < 0.05))
        material_change = abs(estimate_delta) >= max(0.01, 0.25 * abs(float(old["change"])))
        instability |= sign_flip or significance_flip or material_change
        invariant = abs(estimate_delta) <= 1e-12 and abs(se_delta) <= 1e-12 and sample_delta == 0
        all_outputs_invariant &= invariant
        coefficient_changes.append(
            {
                "spec_id": spec_id,
                "estimate_before": float(old["change"]),
                "estimate_after": float(new["change"]),
                "estimate_delta": estimate_delta,
                "standard_error_before": float(old["hac_standard_error"]),
                "standard_error_after": float(new["hac_standard_error"]),
                "standard_error_delta": se_delta,
                "sample_before": int(old["days"]),
                "sample_after": int(new["days"]),
                "sample_delta": sample_delta,
                "sign_flip": sign_flip,
                "five_percent_significance_flip": significance_flip,
                "material_change": material_change,
            }
        )
    affected_rows = len(previous_dates - current_dates) + len(current_dates - previous_dates) + int(row_changed.sum())
    analytical_input_changed = affected_rows > 0 or set(previous_input.columns) != set(current_input.columns)
    source_file_changed = previous_manifest["input"]["sha256"] != current_manifest["input"]["sha256"]
    affected_fraction = affected_rows / max(len(previous_dates | current_dates), 1)
    return {
        "schema_version": 1,
        "kind": "provisional_vehicle_transition_comparison",
        "previous_run_id": previous_manifest["run_id"],
        "current_run_id": current_manifest["run_id"],
        "source_file_changed": source_file_changed,
        "analytical_input_changed": analytical_input_changed,
        "rows_added": len(current_dates - previous_dates),
        "rows_removed": len(previous_dates - current_dates),
        "rows_changed": int(row_changed.sum()),
        "affected_observations": affected_rows,
        "affected_observation_fraction": affected_fraction,
        "variables_added": sorted(set(current_input.columns) - set(previous_input.columns)),
        "variables_removed": sorted(set(previous_input.columns) - set(current_input.columns)),
        "changed_cells_by_variable": changed_by_variable,
        "coefficient_changes": coefficient_changes,
        "invariance_review_required": bool(analytical_input_changed and all_outputs_invariant),
        "instability_review_required": bool(analytical_input_changed and instability),
        "interpretation": (
            "analytical inputs changed but every fitted coefficient, standard error, and sample size is invariant; verify that the changed cells are outside the estimation support or inspect the code path"
            if analytical_input_changed and all_outputs_invariant
            else "findings are sensitive to the input revision; attribute and inspect the changed observations before promotion"
            if analytical_input_changed and instability
            else "input revision does not trigger the predeclared instability thresholds"
        ),
    }


def run_provisional_vehicle_transition(
    *,
    input_path: Path,
    output_root: Path,
    root: Path = REPO_ROOT,
    specification_path: Path | None = None,
    compare_to: Path | None = None,
    minimum_endpoint_days: int = HAC_LAG + 1,
) -> Path:
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"provisional input is absent: {input_path}")
    specification_path = (specification_path or root / "docs" / "specification-lock.json").resolve()
    if not specification_path.is_file():
        raise FileNotFoundError(f"specification lock is absent: {specification_path}")
    panel = pd.read_parquet(input_path)
    snapshot = _input_snapshot(panel)
    support = vehicle_transition_support_geometry(
        snapshot,
        baseline_year=2024,
        comparison_year=2026,
        minimum_endpoint_days=minimum_endpoint_days,
    )
    if bool(support["support_exit_review_required"].astype(bool).any()):
        raise RuntimeError("provisional vehicle-transition support gate is red")
    estimates = vehicle_transition_tests(snapshot, baseline_year=2024, comparison_year=2026, hac_lag=HAC_LAG)
    if len(estimates) != VEHICLE_TRANSITION_SPECIFICATIONS:
        raise RuntimeError("provisional vehicle-transition fitted perimeter is incomplete")
    estimates = attach_spec_ids(estimates, prefix="vehicle_transition_e0_smoke", columns=SPEC_ID_COLUMNS)
    code_records, engine_hash = _code_identity(root)
    input_identity = {
        "path": str(input_path),
        "sha256": _file_sha256(input_path),
        "bytes": input_path.stat().st_size,
        "rows": len(panel),
        "columns": list(panel.columns),
        "analytical_columns": list(analytical_columns()),
        "analytical_rows": len(snapshot),
    }
    identity = {
        "input_sha256": input_identity["sha256"],
        "engine_hash": engine_hash,
        "specification_sha256": _file_sha256(specification_path),
        "specification_family": "vehicle_transition",
        "specification_count": len(estimates),
    }
    run_id = canonical_hash(identity)[:20]
    run_directory = output_root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    with atomic_output(run_directory / "analytical_input_snapshot.parquet") as temporary:
        snapshot.to_parquet(temporary, index=False)
    _write_jsonl(run_directory / "support.provisional.jsonl", support)
    _write_jsonl(run_directory / "estimates.provisional.jsonl", estimates)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "status": STATUS,
        "run_id": run_id,
        "paper_claim_eligible": False,
        "promotion_prohibited": True,
        "requires_certified_input_rerun": True,
        "identity": identity,
        "input": input_identity,
        "engine_sources": code_records,
        "specification": {
            "path": str(specification_path),
            "sha256": identity["specification_sha256"],
            "claim_id": "vehicle_transition",
            "fitted_specifications": len(estimates),
        },
        "outputs": {
            "support": "support.provisional.jsonl",
            "estimates": "estimates.provisional.jsonl",
            "analytical_input_snapshot": "analytical_input_snapshot.parquet",
        },
    }
    _write_json(run_directory / "manifest.json", manifest)
    if compare_to is not None:
        comparison = compare_runs(compare_to.resolve(), run_directory)
        _write_json(run_directory / f"comparison-from-{comparison['previous_run_id']}.json", comparison)
    return run_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "output" / "provisional" / "vehicle_transition")
    parser.add_argument("--compare-to", type=Path)
    args = parser.parse_args()
    run_directory = run_provisional_vehicle_transition(
        input_path=args.input,
        output_root=args.output_root,
        compare_to=args.compare_to,
    )
    manifest = _read_manifest(run_directory)
    estimates = pd.read_json(run_directory / "estimates.provisional.jsonl", lines=True)
    primary = estimates[
        estimates["routing_scope"].eq("two_leg")
        & estimates["weighting"].eq("episode")
        & estimates["transformation"].eq("share_level")
    ].iloc[0]
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "run_id": manifest["run_id"],
                "run_directory": str(run_directory),
                "specifications": len(estimates),
                "primary_change_percentage_points": 100.0 * float(primary["change"]),
                "primary_standard_error_percentage_points": 100.0 * float(primary["hac_standard_error"]),
                "primary_p_value": float(primary["p_value"]),
                "primary_days": int(primary["days"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
