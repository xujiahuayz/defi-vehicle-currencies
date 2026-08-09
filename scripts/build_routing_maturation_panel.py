#!/usr/bin/env python3
"""Materialise estimator-ready routing-maturation panels from the daily frontier.

Reads
  data/processed/transaction_state_frontier_daily.parquet
  data/processed/transaction_state_frontier_daily_support.parquet

Writes
  data/processed/routing_maturation_cell_day.parquet
  data/processed/routing_transition_cells.parquet
  data/processed/routing_maturation_exact_horizons.parquet

This is a node-D3 transform. It validates and aggregates the route-level frontier;
it does not fit a model or write a finding exhibit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ddvc.analysis.routing_contract import (
    HORIZONS_DAYS,
    REGRET_BIN_LEVELS,
    REGRET_MARGINS_BPS,
    REGRET_THRESHOLDS_BPS,
    REPRODUCTION_TOLERANCES_BPS,
    TRANSITION_REPRODUCTION_TOLERANCE_BPS,
    TRANSITION_YEARS,
)
from ddvc.analysis.transaction_frontier import (
    MIN_CHOSEN_REPRODUCTION,
    chosen_quote_coverage_share,
)
from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.runtime import atomic_output, exclusive_job


SOURCE = DATA_DIR / "processed" / "transaction_state_frontier_daily.parquet"
SUPPORT = DATA_DIR / "processed" / "transaction_state_frontier_daily_support.parquet"
CELL_DAY = DATA_DIR / "processed" / "routing_maturation_cell_day.parquet"
TRANSITION = DATA_DIR / "processed" / "routing_transition_cells.parquet"
EXACT_HORIZONS = DATA_DIR / "processed" / "routing_maturation_exact_horizons.parquet"
LOCK = DATA_DIR / "processed" / ".routing_maturation_panel.lock"
CODE_SOURCES = [
    "scripts/build_routing_maturation_panel.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/analysis/routing_contract.py",
    "src/ddvc/analysis/transaction_frontier.py",
]

REQUIRED_COLUMNS = {
    "date",
    "src",
    "tgt",
    "vehicle",
    "vehicle_type",
    "input_usd",
    "within_20pct",
    "realised_venues",
    "public_gain_usd",
    "chosen_leg1_validation_error_bps",
    "chosen_leg2_validation_error_bps",
    "chosen_validation_error_bps",
    "chosen_validation_max_abs_error_bps",
    *REGRET_MARGINS_BPS,
}


def _quoted(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def observed_reach_sql(column: str = "realised_venues") -> str:
    """Canonical order-insensitive, deduplicated venue-set expression."""
    first = f"split_part({column}, '|', 1)"
    second = f"split_part({column}, '|', 2)"
    return (
        f"CASE WHEN {first}={second} THEN {first} "
        f"ELSE least({first},{second})||'|'||greatest({first},{second}) END"
    )


def notional_bin_sql(column: str = "input_usd") -> str:
    """Fixed ex-ante notional bins registered in the specification lock."""
    return (
        f"CASE WHEN {column}<1000 THEN 'b1_100_1k' "
        f"WHEN {column}<10000 THEN 'b2_1k_10k' "
        f"WHEN {column}<100000 THEN 'b3_10k_100k' "
        f"WHEN {column}<1000000 THEN 'b4_100k_1m' "
        "ELSE 'b5_1m_plus' END"
    )


def regret_bin_sql(column: str) -> str:
    """Saturated regret bins used by the conditioned transition test."""
    first, second, third = REGRET_THRESHOLDS_BPS
    low, medium, high, upper = REGRET_BIN_LEVELS
    return (
        f"CASE WHEN {column}<={first} THEN '{low}' "
        f"WHEN {column}<={second:g} THEN '{medium}' "
        f"WHEN {column}<={third:g} THEN '{high}' "
        f"ELSE '{upper}' END"
    )


def _values(values: tuple[float | int, ...], name: str) -> str:
    return f"(VALUES {','.join(f'({value})' for value in values)}) AS {name}(value)"


def _eligible_sql(source: Path) -> str:
    reach = observed_reach_sql()
    notional = notional_bin_sql()
    return f"""
        SELECT
            cast(date AS DATE) AS date,
            lower(src) AS src,
            lower(tgt) AS tgt,
            lower(vehicle) AS vehicle,
            vehicle_type,
            {reach} AS observed_reach,
            {notional} AS notional_bin,
            input_usd,
            public_gain_usd,
            chosen_validation_max_abs_error_bps AS chosen_abs_error_bps,
            {', '.join(REGRET_MARGINS_BPS)}
        FROM read_parquet('{_quoted(source)}')
        WHERE within_20pct
          AND isfinite(input_usd)
          AND input_usd>=100
          AND isfinite(chosen_validation_max_abs_error_bps)
          AND chosen_validation_max_abs_error_bps<=1
    """


def _validate_source(con: duckdb.DuckDBPyConnection, source: Path) -> int:
    schema = set(pq.ParquetFile(source).schema.names)
    missing = REQUIRED_COLUMNS - schema
    if missing:
        raise ValueError(f"transaction frontier lacks columns: {sorted(missing)}")
    rows = pq.ParquetFile(source).metadata.num_rows
    bad = con.execute(
        f"""
        SELECT
            count(*) FILTER (
                WHERE realised_venues IS NULL
                   OR len(string_split(realised_venues, '|'))!=2
                   OR split_part(realised_venues, '|', 1)=''
                   OR split_part(realised_venues, '|', 2)=''
            ) AS bad_reach,
            count(*) FILTER (
                WHERE vehicle_type IS NULL OR src IS NULL OR tgt IS NULL OR vehicle IS NULL
            ) AS bad_identity,
            count(*) FILTER (
                WHERE NOT isfinite(chosen_leg1_validation_error_bps)
                   OR NOT isfinite(chosen_leg2_validation_error_bps)
                   OR NOT isfinite(chosen_validation_error_bps)
                   OR NOT isfinite(chosen_validation_max_abs_error_bps)
                   OR chosen_validation_max_abs_error_bps<0
                   OR abs(
                       chosen_validation_max_abs_error_bps - greatest(
                           abs(chosen_leg1_validation_error_bps),
                           abs(chosen_leg2_validation_error_bps),
                           abs(chosen_validation_error_bps)
                       )
                   )>1e-10
            ) AS bad_validation,
            count(*) FILTER (
                WHERE {REGRET_MARGINS_BPS[0]}<0 OR NOT isfinite({REGRET_MARGINS_BPS[0]})
                   OR {REGRET_MARGINS_BPS[1]}<0 OR NOT isfinite({REGRET_MARGINS_BPS[1]})
                   OR {REGRET_MARGINS_BPS[2]}<0 OR NOT isfinite({REGRET_MARGINS_BPS[2]})
                   OR {REGRET_MARGINS_BPS[3]}<0 OR NOT isfinite({REGRET_MARGINS_BPS[3]})
            ) AS bad_regret,
            count(*) FILTER (
                WHERE abs(
                    {REGRET_MARGINS_BPS[3]} - {REGRET_MARGINS_BPS[0]}
                    - {REGRET_MARGINS_BPS[1]} - {REGRET_MARGINS_BPS[2]}
                ) > 1e-8 * greatest(1, abs({REGRET_MARGINS_BPS[3]}))
            ) AS bad_decomposition
        FROM read_parquet('{_quoted(source)}')
        """
    ).fetchone()
    if any(bad):
        raise ValueError(
            "transaction frontier violates reach/identity/validation/regret/decomposition "
            f"invariants: {bad}"
        )
    inconsistent_vehicle_types = con.execute(
        f"""
        SELECT count(*) FROM (
            SELECT lower(vehicle)
            FROM read_parquet('{_quoted(source)}')
            GROUP BY lower(vehicle)
            HAVING count(DISTINCT vehicle_type)!=1
        )
        """
    ).fetchone()[0]
    if inconsistent_vehicle_types:
        raise ValueError(
            f"{inconsistent_vehicle_types:,} vehicle address(es) map to multiple types"
        )
    return rows


def _validate_support(
    con: duckdb.DuckDBPyConnection, support: Path, source_rows: int
) -> tuple[float, float]:
    scored, eligible, available, mismatches = con.execute(
        f"""
        SELECT
            coalesce(sum(scored_routes),0),
            coalesce(sum(within_20pct_chosen_quote_eligible_routes),0),
            coalesce(sum(within_20pct_chosen_quote_available),0),
            coalesce(sum(within_20pct_chosen_output_mismatch),0)
        FROM read_parquet('{_quoted(support)}')
        """
    ).fetchone()
    if int(scored) != source_rows:
        raise ValueError(
            f"frontier/support row mismatch: {source_rows:,} != {int(scored):,}"
        )
    coverage = chosen_quote_coverage_share(int(eligible), int(available))
    if int(available) > int(eligible):
        raise ValueError("frontier available chosen quotes exceed eligible routes")
    reproduction = 0.0 if available <= 0 else 1.0 - mismatches / available
    if reproduction < MIN_CHOSEN_REPRODUCTION:
        raise ValueError(
            f"chosen-route reproduction {reproduction:.3%} is below "
            f"{MIN_CHOSEN_REPRODUCTION:.0%}"
        )
    return float(reproduction), coverage


def _margin_aggregates() -> str:
    fields: list[str] = []
    for margin in REGRET_MARGINS_BPS:
        prefix = margin.removesuffix("_bps")
        fields.extend(
            [
                f"avg({margin}) AS {prefix}_mean_bps",
                f"avg(ln(1+{margin})) AS {prefix}_mean_log1p_bps",
                f"avg(({margin}>0.01)::INTEGER) AS {prefix}_over_0p01_share",
                f"avg(({margin}>1)::INTEGER) AS {prefix}_over_1_share",
                f"avg(({margin}>10)::INTEGER) AS {prefix}_over_10_share",
            ]
        )
    return ",\n                    ".join(fields)


def _write_cell_day(
    con: duckdb.DuckDBPyConnection,
    source: Path,
    output: Path,
    *,
    full_years: tuple[int, ...],
    primary_min_days: int,
    strict_min_days: int,
) -> int:
    years = ",".join(str(year) for year in full_years)
    expected_years = len(full_years)
    with atomic_output(output) as temporary:
        con.execute(
            f"""
            COPY (
                WITH eligible AS ({_eligible_sql(source)}),
                expanded AS (
                    SELECT eligible.*, tolerance.value::DOUBLE AS reproduction_tolerance_bps
                    FROM eligible
                    CROSS JOIN {_values(REPRODUCTION_TOLERANCES_BPS, 'tolerance')}
                    WHERE chosen_abs_error_bps<=tolerance.value
                ),
                grouped AS (
                    SELECT
                        date, src, tgt, vehicle, vehicle_type, observed_reach,
                        notional_bin, reproduction_tolerance_bps,
                        md5(concat_ws('|',src,tgt,vehicle,observed_reach,notional_bin)) AS cell_id,
                        count(*)::BIGINT AS route_count,
                        sum(input_usd) AS input_usd_total,
                        sum(public_gain_usd) FILTER (WHERE isfinite(public_gain_usd))
                            AS public_gain_usd_total,
                        count(*) FILTER (WHERE isfinite(public_gain_usd))::BIGINT
                            AS public_gain_supported_routes,
                        contains(observed_reach, '|') AS cross_venue,
                        {_margin_aggregates()}
                    FROM expanded
                    GROUP BY ALL
                ),
                cell_year AS (
                    SELECT cell_id, reproduction_tolerance_bps, year(date) AS year,
                           count(DISTINCT date) AS observed_days
                    FROM grouped
                    WHERE year(date) IN ({years})
                    GROUP BY ALL
                ),
                recurrence AS (
                    SELECT cell_id, reproduction_tolerance_bps,
                           count(*)={expected_years}
                               AND min(observed_days)>={primary_min_days}
                               AS recurrent_primary,
                           count(*)={expected_years}
                               AND min(observed_days)>={strict_min_days}
                               AS recurrent_strict,
                           min(observed_days) AS minimum_full_year_days
                    FROM cell_year
                    GROUP BY cell_id, reproduction_tolerance_bps
                )
                SELECT grouped.*,
                       coalesce(recurrent_primary,false) AS recurrent_primary,
                       coalesce(recurrent_strict,false) AS recurrent_strict,
                       coalesce(minimum_full_year_days,0)::INTEGER AS minimum_full_year_days,
                       {primary_min_days}::INTEGER AS primary_minimum_days,
                       {strict_min_days}::INTEGER AS strict_minimum_days
                FROM grouped
                LEFT JOIN recurrence USING (cell_id,reproduction_tolerance_bps)
                ORDER BY date, cell_id, reproduction_tolerance_bps DESC
            ) TO '{_quoted(temporary)}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    return int(
        con.execute(
            f"SELECT count(*) FROM read_parquet('{_quoted(output)}')"
        ).fetchone()[0]
    )


def _write_transition(
    con: duckdb.DuckDBPyConnection, source: Path, output: Path
) -> int:
    within_bin = regret_bin_sql(REGRET_MARGINS_BPS[0])
    reach_bin = regret_bin_sql(REGRET_MARGINS_BPS[1])
    path_bin = regret_bin_sql(REGRET_MARGINS_BPS[2])
    with atomic_output(output) as temporary:
        con.execute(
            f"""
            COPY (
                WITH eligible AS ({_eligible_sql(source)}),
                expanded AS (
                    SELECT eligible.*, 1.0::DOUBLE AS reproduction_tolerance_bps,
                           {within_bin} AS within_reach_regret_bin,
                           {reach_bin} AS reach_increment_bin,
                           {path_bin} AS path_choice_increment_bin
                    FROM eligible
                    WHERE chosen_abs_error_bps<={TRANSITION_REPRODUCTION_TOLERANCE_BPS:g}
                      AND vehicle_type IN ('native','stable')
                      AND year(date) IN ({','.join(str(year) for year in TRANSITION_YEARS)})
                )
                SELECT
                    date, strftime(date,'%m-%d') AS month_day,
                    src, tgt, observed_reach, notional_bin,
                    within_reach_regret_bin, reach_increment_bin,
                    path_choice_increment_bin, reproduction_tolerance_bps,
                    vehicle_type, (vehicle_type='stable')::INTEGER AS stable_indicator,
                    md5(concat_ws('|',src,tgt)) AS endpoint_pair_id,
                    md5(concat_ws('|',src,tgt,observed_reach,notional_bin))
                        AS opportunity_cell_id,
                    md5(concat_ws('|',src,tgt,observed_reach,notional_bin,
                        within_reach_regret_bin,reach_increment_bin,
                        path_choice_increment_bin)) AS transition_cell_id,
                    count(*)::BIGINT AS route_count,
                    sum(input_usd) AS input_usd_total
                FROM expanded
                GROUP BY ALL
                ORDER BY date, transition_cell_id, reproduction_tolerance_bps DESC,
                         stable_indicator
            ) TO '{_quoted(temporary)}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    return int(
        con.execute(
            f"SELECT count(*) FROM read_parquet('{_quoted(output)}')"
        ).fetchone()[0]
    )


def _write_exact_horizons(
    con: duckdb.DuckDBPyConnection,
    cell_day: Path,
    output: Path,
    *,
    full_years: tuple[int, ...],
    horizons: tuple[int, ...],
) -> int:
    outcome_fields: list[str] = []
    for margin in REGRET_MARGINS_BPS:
        outcome = margin.removesuffix("_bps") + "_over_1_share"
        outcome_fields.extend(
            [f"origin.{outcome} AS current_{outcome}", f"future.{outcome} AS future_{outcome}"]
        )
    years = ",".join(str(year) for year in full_years)
    with atomic_output(output) as temporary:
        con.execute(
            f"""
            COPY (
                SELECT
                    origin.cell_id,
                    origin.reproduction_tolerance_bps,
                    origin.date AS origin_date,
                    origin.date + horizon.value * INTERVAL 1 DAY AS target_date,
                    horizon.value::INTEGER AS horizon_days,
                    origin.route_count AS current_route_count,
                    future.route_count AS future_route_count,
                    future.date IS NOT NULL AS target_observed,
                    {', '.join(outcome_fields)}
                FROM read_parquet('{_quoted(cell_day)}') AS origin
                CROSS JOIN {_values(horizons, 'horizon')}
                LEFT JOIN read_parquet('{_quoted(cell_day)}') AS future
                  ON future.cell_id=origin.cell_id
                 AND future.reproduction_tolerance_bps=origin.reproduction_tolerance_bps
                 AND future.date=origin.date + horizon.value * INTERVAL 1 DAY
                WHERE origin.recurrent_primary
                  AND year(origin.date) IN ({years})
                ORDER BY origin_date, cell_id, reproduction_tolerance_bps DESC,
                         horizon_days
            ) TO '{_quoted(temporary)}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    return int(
        con.execute(
            f"SELECT count(*) FROM read_parquet('{_quoted(output)}')"
        ).fetchone()[0]
    )


def build_panels(
    source: Path,
    support: Path,
    cell_day: Path,
    transition: Path,
    exact_horizons: Path,
    *,
    full_years: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025),
    primary_min_days: int = 10,
    strict_min_days: int = 30,
    horizons: tuple[int, ...] = HORIZONS_DAYS,
    memory_limit: str = "1GB",
    threads: int = 1,
) -> dict[str, int | float]:
    if (
        not full_years
        or tuple(sorted(set(full_years))) != full_years
        or primary_min_days <= 0
        or strict_min_days < primary_min_days
    ):
        raise ValueError("invalid recurrent-support contract")
    if tuple(horizons) != HORIZONS_DAYS:
        raise ValueError(
            f"dynamic horizons must equal {HORIZONS_DAYS}, got {horizons}"
        )
    con = duckdb.connect()
    try:
        con.execute(f"SET threads={int(threads)}")
        con.execute(f"SET memory_limit='{memory_limit}'")
        con.execute("SET preserve_insertion_order=false")
        temp_dir = cell_day.parent / "_duckdb_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{_quoted(temp_dir)}'")
        source_rows = _validate_source(con, source)
        reproduction, coverage = _validate_support(con, support, source_rows)
        cell_rows = _write_cell_day(
            con,
            source,
            cell_day,
            full_years=full_years,
            primary_min_days=primary_min_days,
            strict_min_days=strict_min_days,
        )
        transition_rows = _write_transition(con, source, transition)
        horizon_rows = _write_exact_horizons(
            con,
            cell_day,
            exact_horizons,
            full_years=full_years,
            horizons=horizons,
        )
    finally:
        con.close()
    return {
        "source_rows": source_rows,
        "chosen_reproduction": reproduction,
        "chosen_state_coverage": coverage,
        "cell_rows": cell_rows,
        "transition_rows": transition_rows,
        "horizon_rows": horizon_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-limit", default="1GB")
    args = parser.parse_args()
    require_node_d_release(routes=True, market_state=True)
    require_current_artifacts(
        [SOURCE, SUPPORT], consumer="routing-maturation D3 materializer"
    )
    results = build_panels(
        SOURCE,
        SUPPORT,
        CELL_DAY,
        TRANSITION,
        EXACT_HORIZONS,
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    inputs = [SOURCE, SUPPORT]
    stamp(
        CELL_DAY,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        rows=int(results["cell_rows"]),
        notes="equal cell-day exact-state routing margins; fixed 2021-2025 recurrent support; no fitted models",
    )
    stamp(
        TRANSITION,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        rows=int(results["transition_rows"]),
        notes=(
            "2024/2026 native-versus-stable route counts at the locked one-basis-point "
            "reproduction tolerance, with separate endpoint-reach-notional opportunity "
            "keys and saturated regret strata; no fitted models"
        ),
    )
    stamp(
        EXACT_HORIZONS,
        code_sources=CODE_SOURCES,
        inputs=[CELL_DAY],
        rows=int(results["horizon_rows"]),
        notes="exact 1/7/30/120-calendar-day links with missing targets retained as missing; no fitted models",
    )
    print(
        f"validated {int(results['source_rows']):,} route rows at "
        f"{float(results['chosen_reproduction']):.3%} chosen-route reproduction and "
        f"{float(results['chosen_state_coverage']):.3%} chosen-state coverage"
    )
    print(
        f"wrote {int(results['cell_rows']):,} cell-days, "
        f"{int(results['transition_rows']):,} transition cells, and "
        f"{int(results['horizon_rows']):,} exact-horizon links"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="routing-maturation panel"):
        raise SystemExit(main())
