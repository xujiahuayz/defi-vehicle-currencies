#!/usr/bin/env python3
"""Rebuild the registered vehicle-transition result from its processed release.

This four-term accounting is not a decomposition of a fixed-effects coefficient.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import (
    estimate_pair_fixed_effect_rotation,
    load_market_incidence_annual_pairs,
    vehicle_rotation_composition,
    vehicle_rotation_market_incidence_decomposition,
)
from ddvc.endpoint_candidate_composition_release import ENDPOINT_CANDIDATE_COMPOSITION_RELEASE
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output, exclusive_job


PAIR_PANEL = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.parquet"
PAIR_CONTRIBUTIONS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_contributions.parquet"
)
DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_support.jsonl"
FIXED_EFFECT_RESULTS = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
)
LOCK = DATA_DIR / "processed" / ".vehicle-transition.lock"


def attach_spec_ids(
    frame: pd.DataFrame, *, prefix: str, columns: tuple[str, ...]
) -> pd.DataFrame:
    """Attach readable row labels used by downstream selectors."""

    output = frame.copy()
    labels = output.loc[:, list(columns)].astype(str).agg("-".join, axis=1)
    output["spec_id"] = prefix + ":" + labels.str.replace(r"\s+", "_", regex=True)
    return output


def run(
    *,
    root: Path = REPO_ROOT,
    environment=None,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    pair_panel_output: Path = PAIR_PANEL,
    pair_contribution_output: Path = PAIR_CONTRIBUTIONS,
    decomposition_output: Path = DECOMPOSITION,
    support_output: Path = SUPPORT,
    fixed_effect_output: Path = FIXED_EFFECT_RESULTS,
) -> int:
    del environment
    pointer = pointer_path if pointer_path.is_absolute() else root / pointer_path
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    generation = str(payload.get("generation_id") or "")
    artifacts = payload.get("artifacts") or {}
    generation_dir = pointer.parent / "generations" / generation

    def artifact(name: str) -> Path:
        record = artifacts.get(name) or {}
        filename = str(record.get("filename") or "")
        path = generation_dir / filename
        if not filename or not path.is_file():
            raise FileNotFoundError(f"endpoint composition input missing: {path}")
        return path

    choices_path = artifact("choices")
    pair_support_path = artifact("pair_support")
    choices = pd.read_parquet(choices_path)
    detail, decomposition, support, pair_contributions = vehicle_rotation_composition(
        choices
    )
    fixed_effect_results = estimate_pair_fixed_effect_rotation(detail)
    annual_market_pairs = load_market_incidence_annual_pairs(
        pair_support_path, choices_path
    )
    market_decomposition, market_support = (
        vehicle_rotation_market_incidence_decomposition(annual_market_pairs)
    )
    decomposition = pd.concat(
        [decomposition, market_decomposition], ignore_index=True, sort=False
    )
    support = pd.concat([support, market_support], ignore_index=True, sort=False)
    decomposition = attach_spec_ids(
        decomposition,
        prefix="vehicle_transition_pair_decomposition",
        columns=(
            "metric",
            "reporting_scope",
            "baseline_year",
            "comparison_year",
            "estimand_scope",
        ),
    )
    fixed_effect_results = attach_spec_ids(
        fixed_effect_results,
        prefix="vehicle_transition_pair_fixed_effects",
        columns=("metric", "baseline_year", "comparison_year", "estimator_id"),
    )

    def write_parquet(frame: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(path) as temporary:
            frame.to_parquet(temporary, index=False)

    def write_jsonl(frame: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(path) as temporary:
            frame.to_json(
                temporary,
                orient="records",
                lines=True,
                date_format="iso",
            )

    write_parquet(detail, pair_panel_output)
    write_parquet(pair_contributions, pair_contribution_output)
    write_jsonl(fixed_effect_results, fixed_effect_output)
    write_jsonl(decomposition, decomposition_output)
    write_jsonl(support, support_output)
    print(
        f"wrote {len(detail):,} cell rows, {len(pair_contributions):,} ranked pair "
        f"contributions, {len(fixed_effect_results):,} fixed-effect results, "
        f"{len(decomposition):,} decomposition rows, and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle-transition rebuild"):
        raise SystemExit(main())
