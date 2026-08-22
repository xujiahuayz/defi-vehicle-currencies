#!/usr/bin/env python3
"""Run leave-one-venue-out checks for the headline pair decomposition."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import duckdb
import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import BASELINE_YEAR, COMPARISON_YEAR
from ddvc.analysis.vehicle_rotation_venue_exclusion import (
    venue_exclusion_decomposition,
)
from ddvc.endpoint_candidate_composition_data import (
    ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
)
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


DEFAULT_CHOICES = ENDPOINT_CANDIDATE_COMPOSITION_PATHS["choices"]
DEFAULT_OUTPUT = (
    OUTPUT_DIR
    / "exhibits"
    / "vehicle_transition_venue_exclusion_decomposition.jsonl"
)
DEFAULT_SUPPORT = (
    OUTPUT_DIR / "exhibits" / "vehicle_transition_venue_exclusion_support.jsonl"
)


def load_endpoint_choices(
    choices_path: Path,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    """Load only the endpoint half-years used by the registered comparison."""

    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            SELECT
                date,
                src,
                tgt,
                candidate_address,
                candidate_type,
                venue_sequence,
                integration_scope,
                route_count::DOUBLE AS route_count,
                within_20pct_routes::DOUBLE AS within_20pct_routes,
                within_20pct_value_usd::DOUBLE AS within_20pct_value_usd
            FROM read_parquet(?)
            WHERE (date >= make_date(?, 1, 1) AND date < make_date(?, 7, 1))
               OR (date >= make_date(?, 1, 1) AND date < make_date(?, 7, 1))
            """,
            [
                str(choices_path),
                baseline_year,
                baseline_year,
                comparison_year,
                comparison_year,
            ],
        ).fetchdf()
    finally:
        connection.close()


def _write_jsonl(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        frame.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )


def run(
    *,
    choices_path: Path = DEFAULT_CHOICES,
    output: Path = DEFAULT_OUTPUT,
    support_output: Path = DEFAULT_SUPPORT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    started = time.monotonic()
    if not choices_path.is_file():
        raise FileNotFoundError(choices_path)
    choices = load_endpoint_choices(choices_path)
    results, support = venue_exclusion_decomposition(choices)
    runtime_seconds = time.monotonic() - started
    _write_jsonl(results, output)
    _write_jsonl(support, support_output)
    print(
        f"wrote {len(results):,} decomposition rows and {len(support):,} support "
        f"rows in {runtime_seconds:.1f}s"
    )
    return results, support


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--choices", type=Path, default=DEFAULT_CHOICES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=DEFAULT_SUPPORT)
    args = parser.parse_args()
    run(
        choices_path=args.choices,
        output=args.output,
        support_output=args.support_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
