#!/usr/bin/env python3
"""Split 2024 H1/2026 H1 one-window pairs by full endpoint-pair history.

Reads   data/processed/endpoint_candidate_choices.parquet
        data/processed/endpoint_candidate_pair_support.parquet
        output/exhibits/vehicle_transition_pair_contributions.parquet
        output/exhibits/vehicle_transition_pair_decomposition.jsonl
Writes  output/exhibits/vehicle_transition_pair_lifecycle.jsonl
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.pair_turnover_lifecycle import (
    summarize_pair_turnover_lifecycle,
    validate_exclusive_totals,
)
from ddvc.endpoint_candidate_composition_data import (
    ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output, exclusive_job


CHOICES = ENDPOINT_CANDIDATE_COMPOSITION_PATHS["choices"]
PAIR_SUPPORT = ENDPOINT_CANDIDATE_COMPOSITION_PATHS["pair_support"]
CONTRIBUTIONS = OUTPUT_DIR / "exhibits/vehicle_transition_pair_contributions.parquet"
DECOMPOSITION = OUTPUT_DIR / "exhibits/vehicle_transition_pair_decomposition.jsonl"
OUTPUT = OUTPUT_DIR / "exhibits/vehicle_transition_pair_lifecycle.jsonl"
LOCK = SHARED_RUNTIME_DIR / "vehicle-transition-pair-lifecycle.lock"


def load_exclusive_contributions(path: Path) -> pd.DataFrame:
    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            SELECT
                metric,
                source_column,
                reporting_scope,
                baseline_year,
                comparison_year,
                src,
                tgt,
                support_status,
                contribution_share,
                denominator_baseline,
                denominator_comparison,
                stable_baseline,
                stable_comparison
            FROM read_parquet(?)
            WHERE reporting_scope = 'pooled'
              AND support_status IN ('baseline_exclusive', 'comparison_exclusive')
            ORDER BY metric, src, tgt
            """,
            [str(path)],
        ).fetchdf()
    finally:
        connection.close()


def load_pair_histories(
    choices_path: Path,
    pair_support_path: Path,
    contributions_path: Path,
) -> pd.DataFrame:
    """Read full endpoint-market histories on the decomposition calendar."""

    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            WITH common_days AS (
                SELECT strftime(date, '%m-%d') AS month_day
                FROM read_parquet(?)
                WHERE year(date) IN (2024, 2026)
                GROUP BY 1
                HAVING count(DISTINCT year(date)) = 2
            ), exclusive AS (
                SELECT DISTINCT metric, source_column, src, tgt
                FROM read_parquet(?)
                WHERE reporting_scope = 'pooled'
                  AND support_status IN ('baseline_exclusive', 'comparison_exclusive')
            ), endpoint_history AS (
                SELECT
                    e.metric,
                    e.source_column,
                    e.src,
                    e.tgt,
                    min(s.date) FILTER (WHERE s.market_route_count > 0)
                        AS first_observed_date,
                    max(s.date) FILTER (WHERE s.market_route_count > 0)
                        AS last_observed_date,
                    count(DISTINCT s.date) FILTER (WHERE s.market_route_count > 0)
                        ::INTEGER AS positive_days,
                    sum(
                        CASE
                            WHEN year(s.date) = 2024
                             AND strftime(s.date, '%m-%d') IN (
                                SELECT month_day FROM common_days
                             )
                            THEN s.market_route_count
                            ELSE 0
                        END
                    )::DOUBLE AS baseline_market_route_count,
                    sum(
                        CASE
                            WHEN year(s.date) = 2026
                             AND strftime(s.date, '%m-%d') IN (
                                SELECT month_day FROM common_days
                             )
                            THEN s.market_route_count
                            ELSE 0
                        END
                    )::DOUBLE AS comparison_market_route_count
                FROM exclusive AS e
                INNER JOIN read_parquet(?) AS s USING (src, tgt)
                GROUP BY 1, 2, 3, 4
            )
            SELECT *
            FROM endpoint_history
            ORDER BY metric, src, tgt
            """,
            [str(choices_path), str(contributions_path), str(pair_support_path)],
        ).fetchdf()
    finally:
        connection.close()


def run(
    *,
    root: Path = REPO_ROOT,
    choices_path: Path = CHOICES,
    pair_support_path: Path = PAIR_SUPPORT,
    contributions_path: Path = CONTRIBUTIONS,
    decomposition_path: Path = DECOMPOSITION,
    output_path: Path = OUTPUT,
) -> int:
    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    choices_path = resolved(choices_path)
    pair_support_path = resolved(pair_support_path)
    contributions_path = resolved(contributions_path)
    decomposition_path = resolved(decomposition_path)
    output_path = resolved(output_path)
    for path in (
        choices_path,
        pair_support_path,
        contributions_path,
        decomposition_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"pair lifecycle input is missing: {path}")

    contributions = load_exclusive_contributions(contributions_path)
    histories = load_pair_histories(
        choices_path,
        pair_support_path,
        contributions_path,
    )
    lifecycle = summarize_pair_turnover_lifecycle(contributions, histories)
    decomposition = pd.read_json(decomposition_path, lines=True)
    validate_exclusive_totals(lifecycle, decomposition)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output_path) as temporary:
        lifecycle.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    totals = lifecycle[lifecycle["aggregation_level"].eq("exclusive_total")]
    rendered = ", ".join(
        f"{row.metric} {row.contribution_pp:+.3f} pp"
        for row in totals.itertuples(index=False)
    )
    print(f"wrote {len(lifecycle):,} pair-lifecycle rows; {rendered}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="pair lifecycle split"):
        raise SystemExit(main())
