#!/usr/bin/env python3
"""Run and marker-release the exact registered E1-1 and E1-2 estimators."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from ddvc.analysis.vehicle_transition_e1 import (
    DECOMPOSITION_OUTPUT_COLUMNS,
    E1Outputs,
    PAIR_PANEL_OUTPUT_COLUMNS,
    SUPPORT_OUTPUT_COLUMNS,
    build_e1_outputs,
    load_registered_e1_design,
    release_calendar,
    validate_e1_outputs,
)
from ddvc.artifact_release import (
    ArtifactRelease,
    current_artifact_release,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    load_endpoint_candidate_composition_release,
    resolve_endpoint_candidate_composition_release_pointer,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


SPECIFICATION_LOCK = REPO_ROOT / "docs" / "specification-lock.json"
OUTPUT_RELEASE_POINTER = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_release" / "current.json"
OUTPUT_FILENAMES = {
    "pair_panel": "vehicle_transition_pair_panel.jsonl",
    "pair_decomposition": "vehicle_transition_pair_decomposition.jsonl",
    "pair_support": "vehicle_transition_pair_support.jsonl",
}
OUTPUT_KIND = "vehicle_transition_pair_e1"
OUTPUT_SCHEMA_VERSION = 1
CODE_SOURCES = [
    "scripts/run_vehicle_transition_e1.py",
    "src/ddvc/analysis/vehicle_transition_e1.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/endpoint_candidate_composition.py",
    "src/ddvc/endpoint_candidate_composition_release.py",
    "src/ddvc/model_registry.py",
]


def _write_jsonl(frame: pd.DataFrame):
    records = frame.to_dict(orient="records")

    def writer(path: Path) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                clean = {
                    key: None if pd.isna(value) else value
                    for key, value in record.items()
                }
                handle.write(json.dumps(clean, allow_nan=False, default=str, sort_keys=True) + "\n")

    return writer


def _read_jsonl(path: Path) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"E1 staged JSONL contains a blank row at line {line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"E1 staged JSONL row is not an object at line {line_number}")
            records.append(value)
    return pd.DataFrame.from_records(records)


def _read_ordered_jsonl(path: Path, columns: tuple[str, ...]) -> pd.DataFrame:
    frame = _read_jsonl(path)
    if set(frame.columns) != set(columns):
        raise ValueError(f"E1 staged JSONL has an invalid schema: {path.name}")
    return frame.loc[:, list(columns)]


def publish_e1_release(
    outputs: E1Outputs,
    *,
    measures,
    inputs: list[Path],
    pointer_path: Path = OUTPUT_RELEASE_POINTER,
) -> ArtifactRelease:
    """Publish all three registered JSONL files under one marker-last pointer."""

    validate_e1_outputs(outputs, measures=measures)

    def validate_staged(paths: Mapping[str, Path]) -> None:
        reopened = E1Outputs(
            pair_panel=_read_ordered_jsonl(paths["pair_panel"], PAIR_PANEL_OUTPUT_COLUMNS),
            pair_decomposition=_read_ordered_jsonl(
                paths["pair_decomposition"], DECOMPOSITION_OUTPUT_COLUMNS
            ),
            pair_support=_read_ordered_jsonl(paths["pair_support"], SUPPORT_OUTPUT_COLUMNS),
        )
        validate_e1_outputs(reopened, measures=measures)
        if reopened.pair_panel["spec_id"].tolist() != outputs.pair_panel["spec_id"].tolist():
            raise ValueError("E1 staged pair-panel specification order changed")
        if reopened.pair_decomposition["spec_id"].tolist() != outputs.pair_decomposition["spec_id"].tolist():
            raise ValueError("E1 staged decomposition specification order changed")

    frames = {
        "pair_panel": outputs.pair_panel,
        "pair_decomposition": outputs.pair_decomposition,
        "pair_support": outputs.pair_support,
    }
    return publish_artifact_release(
        pointer_path=pointer_path,
        kind=OUTPUT_KIND,
        schema_version=OUTPUT_SCHEMA_VERSION,
        filenames=OUTPUT_FILENAMES,
        writers={name: _write_jsonl(frame) for name, frame in frames.items()},
        row_counts={name: len(frame) for name, frame in frames.items()},
        code_sources=CODE_SOURCES,
        inputs=list(dict.fromkeys(inputs)),
        notes="registered E1-1 saturated-cell WLS and E1-2 exact conditional pair decomposition",
        validate_staged=validate_staged,
    )


def resolve_e1_release(
    pointer_path: Path = OUTPUT_RELEASE_POINTER,
    *,
    specification_path: Path = SPECIFICATION_LOCK,
) -> ArtifactRelease:
    """Reopen one complete E1 generation and reproduce its output contract."""

    _claim, measures = load_registered_e1_design(specification_path)
    release = resolve_artifact_release(
        pointer_path,
        kind=OUTPUT_KIND,
        schema_version=OUTPUT_SCHEMA_VERSION,
        filenames=OUTPUT_FILENAMES,
        require_current_provenance=True,
    )
    with current_artifact_release(release):
        outputs = E1Outputs(
            pair_panel=_read_ordered_jsonl(
                release.artifacts["pair_panel"], PAIR_PANEL_OUTPUT_COLUMNS
            ),
            pair_decomposition=_read_ordered_jsonl(
                release.artifacts["pair_decomposition"],
                DECOMPOSITION_OUTPUT_COLUMNS,
            ),
            pair_support=_read_ordered_jsonl(
                release.artifacts["pair_support"], SUPPORT_OUTPUT_COLUMNS
            ),
        )
        validate_e1_outputs(outputs, measures=measures)
    return release


def run_vehicle_transition_e1(
    *,
    release_pointer: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    specification_path: Path = SPECIFICATION_LOCK,
    output_pointer: Path = OUTPUT_RELEASE_POINTER,
) -> ArtifactRelease:
    """Consume one four-table endpoint pointer and publish one three-file E1 release."""

    _claim, measures = load_registered_e1_design(specification_path)
    endpoint_release = resolve_endpoint_candidate_composition_release_pointer(
        release_pointer
    )
    with current_artifact_release(endpoint_release.bundle):
        bundle = load_endpoint_candidate_composition_release(endpoint_release)
        outputs = build_e1_outputs(
            bundle.choices,
            release_calendar(bundle),
            measures,
            endpoint_release_generation=endpoint_release.generation_id,
        )
        published = publish_e1_release(
            outputs,
            measures=measures,
            inputs=[*endpoint_release.bundle.lineage_paths, specification_path],
            pointer_path=output_pointer,
        )
        reopened = resolve_e1_release(
            output_pointer,
            specification_path=specification_path,
        )
        if reopened.generation_id != published.generation_id:
            raise RuntimeError("installed E1 generation differs from the staged generation")
        return reopened


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-pointer", type=Path, default=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE)
    parser.add_argument("--specification-lock", type=Path, default=SPECIFICATION_LOCK)
    parser.add_argument("--output-release-pointer", type=Path, default=OUTPUT_RELEASE_POINTER)
    args = parser.parse_args()
    release = run_vehicle_transition_e1(
        release_pointer=args.release_pointer,
        specification_path=args.specification_lock,
        output_pointer=args.output_release_pointer,
    )
    print(
        f"E1 release={release.generation_id}; pair-panel=3; pair-decomposition=9; support=12"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
