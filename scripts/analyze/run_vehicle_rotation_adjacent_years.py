#!/usr/bin/env python3
"""Apply the main vehicle-rotation decomposition to adjacent H1 windows.

The main paper compares January--June 2024 with January--June 2026. This
supporting output applies the identical accounting to every adjacent pair of
calendar years with January--June data. It therefore shows whether the same
composition margins account for increases and reversals in vehicle share.

Reads   data/processed/endpoint_candidate_choices.parquet
Writes  output/exhibits/vehicle_transition_adjacent_year_decomposition.jsonl
        output/exhibits/vehicle_transition_nonvehicle_endpoint_decomposition.jsonl
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import vehicle_rotation_composition
from ddvc.asset_types import WETH, asset_type
from ddvc.endpoint_candidate_composition_data import (
    ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output, exclusive_job


CHOICES = ENDPOINT_CANDIDATE_COMPOSITION_PATHS["choices"]
OUTPUT = OUTPUT_DIR / "exhibits/vehicle_transition_adjacent_year_decomposition.jsonl"
ENDPOINT_OUTPUT = (
    OUTPUT_DIR / "exhibits/vehicle_transition_nonvehicle_endpoint_decomposition.jsonl"
)
LOCK = SHARED_RUNTIME_DIR / "vehicle-transition-adjacent-years.lock"
FIRST_COMPLETE_H1_YEAR = 2019
CHOICE_COLUMNS = (
    "date",
    "src",
    "tgt",
    "candidate_address",
    "candidate_type",
    "venue_sequence",
    "integration_scope",
    "route_count",
    "within_20pct_routes",
    "within_20pct_value_usd",
)


def adjacent_year_pairs(years: list[int] | tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    """Return consecutive years beginning with the first complete H1 sample."""

    observed = sorted({int(year) for year in years if int(year) >= FIRST_COMPLETE_H1_YEAR})
    return tuple((year, year + 1) for year in observed if year + 1 in observed)


def summarize_adjacent_years(choices: pd.DataFrame) -> pd.DataFrame:
    """Return the main decomposition for each adjacent January--June window."""

    data = choices.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data = data[data["date"].dt.month.le(6)].copy()
    pairs = adjacent_year_pairs(tuple(data["date"].dt.year.unique()))
    if not pairs:
        raise ValueError("adjacent-year decomposition has no consecutive H1 years")

    rows: list[pd.DataFrame] = []
    years = data["date"].dt.year
    for baseline_year, comparison_year in pairs:
        selected = data[years.isin((baseline_year, comparison_year))].copy()
        _panel, decomposition, _support, _contributions = vehicle_rotation_composition(
            selected,
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            reporting_scopes=("pooled",),
        )
        decomposition.insert(0, "window", "january_june")
        decomposition.insert(1, "comparison_horizon_years", 1)
        rows.append(decomposition)
    output = pd.concat(rows, ignore_index=True, sort=False)
    output["spec_id"] = (
        "vehicle_transition_adjacent_year_decomposition:"
        + output["metric"].astype(str)
        + ":"
        + output["reporting_scope"].astype(str)
        + ":"
        + output["baseline_year"].astype(int).astype(str)
        + "-"
        + output["comparison_year"].astype(int).astype(str)
    )
    return output


def summarize_nonvehicle_endpoints(choices: pd.DataFrame) -> pd.DataFrame:
    """Apply the headline comparison where neither endpoint is WETH or stable."""

    data = choices.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data = data[
        data["date"].dt.year.isin((2024, 2026)) & data["date"].dt.month.le(6)
    ].copy()
    endpoints = pd.unique(pd.concat([data["src"], data["tgt"]], ignore_index=True))
    endpoint_types = {str(token): asset_type(str(token)) for token in endpoints}
    eligible = (
        data["src"].ne(WETH)
        & data["tgt"].ne(WETH)
        & data["src"].map(endpoint_types).ne("stable")
        & data["tgt"].map(endpoint_types).ne("stable")
    )
    selected = data[eligible].copy()
    if selected.empty:
        raise ValueError("nonvehicle-endpoint decomposition sample is empty")
    _panel, decomposition, _support, _contributions = vehicle_rotation_composition(
        selected,
        baseline_year=2024,
        comparison_year=2026,
        reporting_scopes=("pooled",),
    )
    decomposition.insert(0, "endpoint_sample", "neither_weth_nor_stable")
    decomposition["spec_id"] = (
        "vehicle_transition_nonvehicle_endpoint_decomposition:"
        + decomposition["metric"].astype(str)
        + ":"
        + decomposition["reporting_scope"].astype(str)
    )
    return decomposition


def _read_h1_choices(path: Path) -> pd.DataFrame:
    columns = ", ".join(CHOICE_COLUMNS)
    connection = duckdb.connect()
    try:
        return connection.execute(
            f"""
            SELECT {columns}
            FROM read_parquet(?)
            WHERE month(date) <= 6
              AND year(date) >= ?
            """,
            [str(path), FIRST_COMPLETE_H1_YEAR],
        ).fetchdf()
    finally:
        connection.close()


def run(
    *,
    root: Path = REPO_ROOT,
    choices_path: Path = CHOICES,
    output_path: Path = OUTPUT,
    endpoint_output_path: Path = ENDPOINT_OUTPUT,
) -> int:
    choices_path = choices_path if choices_path.is_absolute() else root / choices_path
    output_path = output_path if output_path.is_absolute() else root / output_path
    endpoint_output_path = (
        endpoint_output_path
        if endpoint_output_path.is_absolute()
        else root / endpoint_output_path
    )
    if not choices_path.is_file():
        raise FileNotFoundError(f"endpoint-candidate choices are missing: {choices_path}")
    choices = _read_h1_choices(choices_path)
    result = summarize_adjacent_years(choices)
    endpoint_result = summarize_nonvehicle_endpoints(choices)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output_path) as temporary:
        result.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    endpoint_output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(endpoint_output_path) as temporary:
        endpoint_result.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    comparisons = result[["baseline_year", "comparison_year"]].drop_duplicates()
    print(
        f"wrote {len(result):,} adjacent-year decomposition rows across "
        f"{len(comparisons)} H1 comparisons"
    )
    print(f"wrote {len(endpoint_result):,} nonvehicle-endpoint decomposition rows")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="adjacent-year vehicle-transition rebuild"):
        raise SystemExit(main())
