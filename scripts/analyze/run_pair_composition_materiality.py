#!/usr/bin/env python3
"""Run material-pair sensitivities for the central composition accounting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.analysis.pair_composition_materiality import material_pair_composition
from ddvc.endpoint_candidate_composition_data import (
    ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output, exclusive_job


DECOMPOSITION = (
    OUTPUT_DIR / "exhibits/vehicle_transition_pair_materiality_decomposition.jsonl"
)
SUPPORT = OUTPUT_DIR / "exhibits/vehicle_transition_pair_materiality_support.jsonl"
LOCK = SHARED_RUNTIME_DIR / "vehicle-transition-pair-materiality.lock"


def run(
    *,
    root: Path = REPO_ROOT,
    choices_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_PATHS["choices"],
    decomposition_output: Path = DECOMPOSITION,
    support_output: Path = SUPPORT,
) -> int:
    choices_path = choices_path if choices_path.is_absolute() else root / choices_path
    if not choices_path.is_file():
        raise FileNotFoundError("endpoint-candidate choices input is missing")
    decomposition, support = material_pair_composition(pd.read_parquet(choices_path))

    for frame, path in (
        (decomposition, decomposition_output),
        (support, support_output),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(path) as temporary:
            frame.to_json(
                temporary,
                orient="records",
                lines=True,
                date_format="iso",
                double_precision=15,
            )
    print(
        f"wrote {len(decomposition):,} materiality decompositions and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="pair-composition materiality"):
        raise SystemExit(main())
