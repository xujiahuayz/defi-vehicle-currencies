#!/usr/bin/env python3
"""Materialize pairwise WETH-versus-comparator route-cost outcomes and support."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

import duckdb
import pyarrow.parquet as pq

from ddvc.analysis.dominance_cost_contract import (
    COMPARATOR_VEHICLES,
    NATIVE_VEHICLE,
    OUTCOME_COLUMNS,
    OUTCOME_REQUIRED_SUPPORT_STAGE,
    PAIR_CELL_KEYS,
    PAIR_MEMBER_EQUAL_FIELDS,
    SUPPORT_STAGES,
    SUPPORT_STRATA_KEYS,
    validate_support_counts,
)
from ddvc.analysis.dominance_cost_release import (
    DOMINANCE_COST_RELEASE as RELEASE,
    DOMINANCE_COST_RELEASE_FILENAMES as RELEASE_FILENAMES,
    DOMINANCE_COST_RELEASE_KIND as RELEASE_KIND,
    DOMINANCE_COST_RELEASE_SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    resolve_dominance_cost_release,
)
from ddvc.artifact_release import publish_artifact_release
from ddvc.d3_stage_registry import D3_BUILD_STAGES
from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import cache_key, install_stamped_artifact, prepare_stamp, require_current_artifacts, sidecar_path, verify
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days
from ddvc.route_cost import MAIN_ROUTE_COST_SPEC, QUOTE_CELL_KEYS
from ddvc.runtime import exclusive_job, staged_output


SOURCE = DATA_DIR / "empirical" / "route_cost_panel_v2.parquet"
CALENDAR = UNIFIED_QUALITY_PANEL
CACHE_ROOT = DATA_DIR / "processed" / "_dominance_cost_pair_stage"
LOCK = DATA_DIR / "processed" / ".dominance_cost_panel.lock"
CACHE_CODE_SOURCES = [
    "scripts/build_dominance_cost_panel.py",
    "src/ddvc/analysis/dominance_cost_contract.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/release_calendar.py",
    "src/ddvc/route_cost.py",
]
RELEASE_CODE_SOURCES = [
    *CACHE_CODE_SOURCES,
    "src/ddvc/analysis/dominance_cost_release.py",
    "src/ddvc/artifact_release.py",
]
# Generations selected under the release pointer are immutable evidence and are retained. Only superseded candidate/pair caches under CACHE_ROOT are disposable and pruned.
REQUIRED_SOURCE_COLUMNS = {
    *PAIR_MEMBER_EQUAL_FIELDS,
    "vehicle",
    "vehicle_available",
    "vehicle_output_usd",
    "hop1_source",
    "hop1_pool",
    "hop2_source",
    "hop2_pool",
}


def _quoted(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _candidate_values_sql() -> str:
    rows = ",".join(
        f"({_sql_string(address)},{_sql_string(symbol)})"
        for address, symbol in COMPARATOR_VEHICLES.items()
    )
    return f"(VALUES {rows}) AS comparators(comparator, comparator_symbol)"


def _address_values_sql() -> str:
    values = (NATIVE_VEHICLE, *COMPARATOR_VEHICLES)
    return ",".join(_sql_string(value) for value in values)


def _calendar_values_sql(days: list[str]) -> str:
    if not days:
        raise ValueError("canonical route calendar is empty")
    rows = ",".join(f"({_sql_string(day)})" for day in days)
    return f"(VALUES {rows}) AS released_calendar(date)"


def _route_calendar_days(days: list[str]) -> list[str]:
    normalized: list[str] = []
    for day in days:
        compact = str(day).replace("-", "")
        try:
            normalized.append(datetime.strptime(compact, "%Y%m%d").strftime("%Y-%m-%d"))
        except ValueError as error:
            raise ValueError(f"canonical route calendar day is malformed: {day}") from error
    if len(normalized) != len(set(normalized)):
        raise ValueError("canonical route calendar duplicates a day after normalization")
    return normalized


def _trade_size_values_sql() -> str:
    rows = ",".join(f"({float(value)!r})" for value in MAIN_ROUTE_COST_SPEC.trade_sizes_usd)
    return f"(VALUES {rows}) AS locked_notional(trade_size_usd)"


def _source_columns(connection: duckdb.DuckDBPyConnection, source: Path) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{_quoted(source)}')"
        ).fetchall()
    }


def _assert_source_contract(connection: duckdb.DuckDBPyConnection, source: Path) -> int:
    if not source.is_file():
        raise FileNotFoundError(f"canonical route-cost panel is absent: {source}")
    missing = sorted(REQUIRED_SOURCE_COLUMNS - _source_columns(connection, source))
    if missing:
        raise ValueError(f"canonical route-cost panel lacks columns: {missing}")
    source_rows = int(pq.ParquetFile(source).metadata.num_rows)
    if source_rows < 1:
        raise ValueError("canonical route-cost panel is empty")
    return source_rows


def _assert_source_perimeter(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    calendar_days: list[str],
) -> None:
    unexpected_day = connection.execute(
        f"""
        SELECT DISTINCT date
        FROM read_parquet('{_quoted(source)}')
        WHERE date IS NULL OR date NOT IN (SELECT date FROM {_calendar_values_sql(calendar_days)})
        LIMIT 1
        """
    ).fetchone()
    if unexpected_day is not None:
        raise ValueError(f"route-cost source date is outside the released calendar: {unexpected_day}")
    unexpected_size = connection.execute(
        f"""
        SELECT DISTINCT trade_size_usd
        FROM read_parquet('{_quoted(source)}')
        WHERE trade_size_usd IS NULL
           OR trade_size_usd NOT IN (SELECT trade_size_usd FROM {_trade_size_values_sql()})
        LIMIT 1
        """
    ).fetchone()
    if unexpected_size is not None:
        raise ValueError(f"route-cost source notional is outside the locked grid: {unexpected_size}")


def _write_candidate_stage(
    connection: duckdb.DuckDBPyConnection, source: Path, output: Path
) -> None:
    projected = ",\n                ".join(
        [
            "date",
            "reserve_hour_utc",
            "lower(src) AS src",
            "lower(tgt) AS tgt",
            "lower(vehicle) AS vehicle",
            "trade_size_usd",
            "method",
            "direct_available",
            "direct_output_usd",
            "direct_source",
            "direct_pool",
            "vehicle_available",
            "vehicle_output_usd",
            "hop1_source",
            "hop1_pool",
            "hop2_source",
            "hop2_pool",
        ]
    )
    connection.execute(
        f"""
        COPY (
            SELECT {projected}
            FROM read_parquet('{_quoted(source)}')
            WHERE lower(vehicle) IN ({_address_values_sql()})
            ORDER BY date, reserve_hour_utc, src, tgt, trade_size_usd, vehicle
        ) TO '{_quoted(output)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _assert_candidate_stage(
    connection: duckdb.DuckDBPyConnection, candidate_stage: Path
) -> int:
    rows = int(pq.ParquetFile(candidate_stage).metadata.num_rows)
    if rows < 1:
        raise ValueError("canonical route-cost panel has no locked candidate rows")
    keys = ",".join(QUOTE_CELL_KEYS)
    duplicate = connection.execute(
        f"""
        SELECT {keys}, count(*) AS rows
        FROM read_parquet('{_quoted(candidate_stage)}')
        GROUP BY {keys}
        HAVING count(*)<>1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            f"canonical route-cost panel has duplicate candidate quote cells: {duplicate}"
        )
    invalid_available = connection.execute(
        f"""
        SELECT date, reserve_hour_utc, src, tgt, vehicle, trade_size_usd
        FROM read_parquet('{_quoted(candidate_stage)}')
        WHERE vehicle_available=true
          AND (vehicle_output_usd IS NULL
               OR NOT isfinite(vehicle_output_usd)
               OR vehicle_output_usd<=0)
        LIMIT 1
        """
    ).fetchone()
    if invalid_available is not None:
        raise ValueError(
            "dominance-cost available indirect output is nonfinite or nonpositive: "
            f"{invalid_available}"
        )
    return rows


def _pair_ctes(candidate_stage: Path) -> str:
    quote_keys_without_vehicle = [key for key in QUOTE_CELL_KEYS if key != "vehicle"]
    economic_keys = ", ".join(quote_keys_without_vehicle)
    join = " AND ".join(f"member.{key}=attempted.{key}" for key in quote_keys_without_vehicle)
    return f"""
        candidate_rows AS (
            SELECT * FROM read_parquet('{_quoted(candidate_stage)}')
        ),
        economic_cells AS (
            SELECT {economic_keys},
                count(*) FILTER (WHERE coalesce(vehicle_available,false))::INTEGER
                    AS available_candidate_count
            FROM candidate_rows
            GROUP BY {economic_keys}
        ),
        attempted AS (
            SELECT economic_cells.*, comparators.comparator, comparators.comparator_symbol
            FROM economic_cells
            CROSS JOIN {_candidate_values_sql()}
            WHERE src NOT IN ({_sql_string(NATIVE_VEHICLE)}, comparator)
              AND tgt NOT IN ({_sql_string(NATIVE_VEHICLE)}, comparator)
        ),
        paired AS (
            SELECT
                attempted.*,
                weth.vehicle IS NOT NULL AS weth_row_present,
                member.vehicle IS NOT NULL AS comparator_row_present,
                weth.method,
                weth.direct_available,
                weth.direct_output_usd,
                weth.direct_source,
                weth.direct_pool,
                weth.vehicle_available AS weth_indirect_available,
                member.vehicle_available AS comparator_indirect_available,
                weth.vehicle_output_usd AS weth_output_usd,
                member.vehicle_output_usd AS comparator_output_usd,
                weth.hop1_source AS weth_hop1_source,
                weth.hop1_pool AS weth_hop1_pool,
                weth.hop2_source AS weth_hop2_source,
                weth.hop2_pool AS weth_hop2_pool,
                member.hop1_source AS comparator_hop1_source,
                member.hop1_pool AS comparator_hop1_pool,
                member.hop2_source AS comparator_hop2_source,
                member.hop2_pool AS comparator_hop2_pool,
                member.method AS comparator_method,
                member.direct_available AS comparator_direct_available,
                member.direct_output_usd AS comparator_direct_output_usd,
                member.direct_source AS comparator_direct_source,
                member.direct_pool AS comparator_direct_pool
            FROM attempted
            LEFT JOIN candidate_rows AS weth
              ON {join.replace('member.', 'weth.')}
             AND weth.vehicle={_sql_string(NATIVE_VEHICLE)}
            LEFT JOIN candidate_rows AS member
              ON {join}
             AND member.vehicle=attempted.comparator
        ),
        staged AS (
            SELECT *,
                weth_row_present AND comparator_row_present
                    AND coalesce(weth_indirect_available,false)
                    AND coalesce(comparator_indirect_available,false)
                    AS both_indirect_available,
                weth_row_present AND comparator_row_present
                    AND coalesce(weth_indirect_available,false)
                    AND coalesce(comparator_indirect_available,false)
                    AND isfinite(weth_output_usd) AND weth_output_usd>0
                    AND isfinite(comparator_output_usd) AND comparator_output_usd>0
                    AS positive_finite_indirect_outputs
            FROM paired
        ),
        supported AS (
            SELECT *,
                positive_finite_indirect_outputs AND coalesce(direct_available,false)
                    AS direct_available_stage,
                positive_finite_indirect_outputs AND coalesce(direct_available,false)
                    AND isfinite(direct_output_usd) AND direct_output_usd>0
                    AS positive_finite_direct_output
            FROM staged
        )
    """


def _write_pair_stage(
    connection: duckdb.DuckDBPyConnection,
    candidate_stage: Path,
    output: Path,
) -> None:
    connection.execute(
        f"""
        COPY (
            WITH {_pair_ctes(candidate_stage)}
            SELECT * FROM supported
            ORDER BY date, reserve_hour_utc, src, tgt, trade_size_usd, comparator
        ) TO '{_quoted(output)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _assert_pair_stage(
    connection: duckdb.DuckDBPyConnection, pair_stage: Path
) -> int:
    rows = int(pq.ParquetFile(pair_stage).metadata.num_rows)
    non_key_fields = [
        field
        for field in PAIR_MEMBER_EQUAL_FIELDS
        if field not in QUOTE_CELL_KEYS or field == "method"
    ]
    mismatches = [
        f"NOT ({field} IS NOT DISTINCT FROM comparator_{field})"
        for field in non_key_fields
    ]
    row = connection.execute(
        f"""
        SELECT date, reserve_hour_utc, src, tgt, trade_size_usd, comparator
        FROM read_parquet('{_quoted(pair_stage)}')
        WHERE weth_row_present AND comparator_row_present
          AND ({' OR '.join(mismatches)} OR method IS NULL OR trim(method)='')
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        raise ValueError(f"dominance-cost pair members disagree on asserted common fields: {row}")
    invalid_direct = connection.execute(
        f"""
        SELECT date, reserve_hour_utc, src, tgt, trade_size_usd, comparator
        FROM read_parquet('{_quoted(pair_stage)}')
        WHERE weth_row_present AND comparator_row_present
          AND direct_available=true
          AND (direct_output_usd IS NULL OR NOT isfinite(direct_output_usd) OR direct_output_usd<=0)
        LIMIT 1
        """
    ).fetchone()
    if invalid_direct is not None:
        raise ValueError(
            "dominance-cost present direct output is nonfinite or nonpositive: "
            f"{invalid_direct}"
        )
    return rows


def _stage_current(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        verdict = verify(path)
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        return False
    return verdict.get("status") == "ok"


def _ensure_candidate_stage(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    path: Path,
) -> tuple[int, bool]:
    if _stage_current(path):
        return int(pq.ParquetFile(path).metadata.num_rows), True
    with staged_output(path) as temporary:
        _write_candidate_stage(connection, source, temporary)
        rows = _assert_candidate_stage(connection, temporary)
        prepared = prepare_stamp(
            path,
            content_path=temporary,
            code_sources=CACHE_CODE_SOURCES,
            inputs=[source],
            rows=rows,
            notes="normalized locked-candidate projection; immutable recovery boundary before pair expansion",
        )
        install_stamped_artifact(temporary, path, prepared)
    return rows, False


def _ensure_pair_stage(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    candidate_stage: Path,
    path: Path,
) -> tuple[int, bool]:
    if _stage_current(path):
        return int(pq.ParquetFile(path).metadata.num_rows), True
    with staged_output(path) as temporary:
        _write_pair_stage(connection, candidate_stage, temporary)
        rows = _assert_pair_stage(connection, temporary)
        prepared = prepare_stamp(
            path,
            content_path=temporary,
            code_sources=CACHE_CODE_SOURCES,
            inputs=[source, candidate_stage],
            rows=rows,
            notes="pairwise WETH-versus-comparator attempt stage with member architecture and exact-cell available-candidate breadth",
        )
        install_stamped_artifact(temporary, path, prepared)
    return rows, False


def _prune_superseded_cache(cache_root: Path, keep: set[Path]) -> None:
    for path in cache_root.glob("*.parquet"):
        if path in keep:
            continue
        path.unlink()
        sidecar_path(path).unlink(missing_ok=True)


def _write_panel(
    connection: duckdb.DuckDBPyConnection, pair_stage: Path, output: Path
) -> None:
    connection.execute(
        f"""
        COPY (
            SELECT
                date, reserve_hour_utc, src, tgt, trade_size_usd,
                comparator, comparator_symbol, method,
                weth_output_usd, comparator_output_usd,
                available_candidate_count,
                weth_hop1_source, weth_hop1_pool, weth_hop2_source, weth_hop2_pool,
                comparator_hop1_source, comparator_hop1_pool,
                comparator_hop2_source, comparator_hop2_pool,
                direct_available_stage AS direct_available,
                CASE WHEN positive_finite_direct_output THEN direct_output_usd ELSE NULL END
                    AS direct_output_usd,
                CASE WHEN positive_finite_direct_output THEN direct_source ELSE NULL END
                    AS direct_source,
                CASE WHEN positive_finite_direct_output THEN direct_pool ELSE NULL END
                    AS direct_pool,
                20000.0*(weth_output_usd-comparator_output_usd)
                    /(weth_output_usd+comparator_output_usd)
                    AS weth_symmetric_output_edge_bps,
                10000.0*(weth_output_usd-comparator_output_usd)/trade_size_usd
                    AS weth_output_gain_bps_of_notional,
                ln(weth_output_usd)-ln(comparator_output_usd)
                    AS weth_log_output_ratio,
                ((weth_output_usd>comparator_output_usd)::INTEGER
                    -(comparator_output_usd>weth_output_usd)::INTEGER)
                    AS weth_signed_win,
                CASE WHEN positive_finite_direct_output THEN
                    ((weth_output_usd>direct_output_usd)::INTEGER
                    -(comparator_output_usd>direct_output_usd)::INTEGER)
                    ELSE NULL END AS weth_direct_threshold_edge,
                {_sql_string(OUTCOME_REQUIRED_SUPPORT_STAGE['weth_symmetric_output_edge_bps'])}
                    AS primary_support_stage,
                CASE WHEN positive_finite_direct_output THEN
                    {_sql_string(OUTCOME_REQUIRED_SUPPORT_STAGE['weth_direct_threshold_edge'])}
                    ELSE NULL END AS direct_threshold_support_stage
            FROM read_parquet('{_quoted(pair_stage)}')
            WHERE positive_finite_indirect_outputs
            ORDER BY date, reserve_hour_utc, src, tgt, trade_size_usd, comparator
        ) TO '{_quoted(output)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _write_support(
    connection: duckdb.DuckDBPyConnection,
    calendar_days: list[str],
    pair_stage: Path,
    output: Path,
) -> None:
    connection.execute(
        f"""
        COPY (
            WITH strata AS (
                SELECT released_calendar.date, comparators.comparator,
                       comparators.comparator_symbol, locked_notional.trade_size_usd
                FROM {_calendar_values_sql(calendar_days)}
                CROSS JOIN {_trade_size_values_sql()}
                CROSS JOIN {_candidate_values_sql()}
            ),
            counts AS (
                SELECT date, comparator, trade_size_usd,
                    count(*)::BIGINT AS candidate_pair_attempted,
                    count(*) FILTER (WHERE both_indirect_available)::BIGINT
                        AS both_indirect_available,
                    count(*) FILTER (WHERE positive_finite_indirect_outputs)::BIGINT
                        AS positive_finite_indirect_outputs,
                    count(*) FILTER (WHERE direct_available_stage)::BIGINT
                        AS direct_available,
                    count(*) FILTER (WHERE positive_finite_direct_output)::BIGINT
                        AS positive_finite_direct_output
                FROM read_parquet('{_quoted(pair_stage)}')
                GROUP BY date, comparator, trade_size_usd
            )
            SELECT strata.*,
                coalesce(counts.candidate_pair_attempted,0)::BIGINT AS candidate_pair_attempted,
                coalesce(counts.both_indirect_available,0)::BIGINT AS both_indirect_available,
                coalesce(counts.positive_finite_indirect_outputs,0)::BIGINT AS positive_finite_indirect_outputs,
                coalesce(counts.direct_available,0)::BIGINT AS direct_available,
                coalesce(counts.positive_finite_direct_output,0)::BIGINT AS positive_finite_direct_output
            FROM strata
            LEFT JOIN counts USING (date, comparator, trade_size_usd)
            ORDER BY date, comparator, trade_size_usd
        ) TO '{_quoted(output)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _validate_outputs(
    connection: duckdb.DuckDBPyConnection,
    panel: Path,
    support: Path,
    *,
    expected_support_rows: int,
) -> tuple[int, int, int]:
    pair_keys = ",".join(PAIR_CELL_KEYS)
    duplicate = connection.execute(
        f"SELECT {pair_keys} FROM read_parquet('{_quoted(panel)}') GROUP BY {pair_keys} HAVING count(*)<>1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise ValueError(f"dominance-cost panel has duplicate economic pairs: {duplicate}")
    panel_columns = _source_columns(connection, panel)
    missing_outcomes = sorted(set(OUTCOME_COLUMNS) - panel_columns)
    if missing_outcomes:
        raise ValueError(f"dominance-cost panel lacks outcomes: {missing_outcomes}")
    support_rows = connection.execute(
        f"SELECT {','.join(SUPPORT_STRATA_KEYS)}, {','.join(SUPPORT_STAGES)} FROM read_parquet('{_quoted(support)}') ORDER BY {','.join(SUPPORT_STRATA_KEYS)}"
    ).fetchall()
    seen: set[tuple[object, ...]] = set()
    totals = {stage: 0 for stage in SUPPORT_STAGES}
    for row in support_rows:
        key = tuple(row[: len(SUPPORT_STRATA_KEYS)])
        if key in seen:
            raise ValueError(f"dominance-cost support ledger duplicates stratum: {key}")
        seen.add(key)
        counts = {
            stage: int(row[len(SUPPORT_STRATA_KEYS) + index])
            for index, stage in enumerate(SUPPORT_STAGES)
        }
        validate_support_counts(counts)
        for stage, value in counts.items():
            totals[stage] += int(value)
    panel_rows = int(pq.ParquetFile(panel).metadata.num_rows)
    support_count = int(pq.ParquetFile(support).metadata.num_rows)
    if support_count != expected_support_rows:
        raise ValueError(
            "dominance-cost support ledger does not span the full "
            "date-comparator-notional perimeter"
        )
    direct_rows = int(
        connection.execute(
            f"SELECT count(*) FROM read_parquet('{_quoted(panel)}') WHERE weth_direct_threshold_edge IS NOT NULL"
        ).fetchone()[0]
    )
    if panel_rows != totals["positive_finite_indirect_outputs"]:
        raise ValueError("dominance-cost panel rows do not equal primary support")
    if direct_rows != totals["positive_finite_direct_output"]:
        raise ValueError("dominance-cost direct outcomes do not equal direct support")
    invalid_outcome = connection.execute(
        f"""
        SELECT date, reserve_hour_utc, src, tgt, trade_size_usd, comparator,
               weth_symmetric_output_edge_bps, weth_output_gain_bps_of_notional,
               weth_log_output_ratio, weth_signed_win, weth_direct_threshold_edge
        FROM read_parquet('{_quoted(panel)}')
        WHERE NOT isfinite(weth_symmetric_output_edge_bps)
           OR abs(weth_symmetric_output_edge_bps)>20000
           OR NOT isfinite(weth_output_gain_bps_of_notional)
           OR NOT isfinite(weth_log_output_ratio)
           OR weth_signed_win NOT IN (-1,0,1)
           OR (weth_direct_threshold_edge IS NOT NULL
               AND weth_direct_threshold_edge NOT IN (-1,0,1))
           OR direct_available IS DISTINCT FROM (weth_direct_threshold_edge IS NOT NULL)
        LIMIT 1
        """
    ).fetchone()
    if invalid_outcome is not None:
        raise ValueError(f"dominance-cost outcome violates its contract: {invalid_outcome}")
    return panel_rows, support_count, totals["candidate_pair_attempted"]


def _assert_sole_materializer() -> None:
    relative_outputs = {RELEASE.relative_to(REPO_ROOT).as_posix()}
    owners = {
        output: [stage.script for stage in D3_BUILD_STAGES if output in stage.outputs]
        for output in relative_outputs
    }
    if any(value != ["build_dominance_cost_panel.py"] for value in owners.values()):
        raise RuntimeError(f"dominance-cost outputs lack one canonical materializer: {owners}")


def build_panel(
    source: Path,
    calendar: Path,
    *,
    pointer_path: Path = RELEASE,
    cache_root: Path | None = None,
    threads: int = 1,
    memory_limit: str = "2GB",
    write_pointer: Callable[[Path, dict[str, object]], None] = write_json,
) -> dict[str, int | bool | str]:
    if threads < 1:
        raise ValueError("DuckDB thread count must be positive")
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = cache_root or (
        CACHE_ROOT
        if pointer_path == RELEASE
        else pointer_path.parent / "_dominance_cost_pair_stage"
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    generation = cache_key(CACHE_CODE_SOURCES, inputs=[source], length=64)
    candidate_stage = cache_root / f"candidate-{generation}.parquet"
    pair_stage = cache_root / f"pair-{generation}.parquet"
    with TemporaryDirectory(
        prefix="dominance-cost-duckdb-", dir=pointer_path.parent
    ) as temporary_directory:
        connection = duckdb.connect()
        try:
            connection.execute(f"SET threads={int(threads)}")
            connection.execute(f"SET memory_limit={_sql_string(memory_limit)}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory={_sql_string(temporary_directory)}")
            source_rows = _assert_source_contract(connection, source)
            calendar_days = _route_calendar_days(
                released_route_days(calendar, nonempty=False)
            )
            _assert_source_perimeter(connection, source, calendar_days)
            candidate_rows, candidate_reused = _ensure_candidate_stage(
                connection, source, candidate_stage
            )
            pair_stage_rows, pair_reused = _ensure_pair_stage(
                connection, source, candidate_stage, pair_stage
            )
            expected_support_rows = (
                len(calendar_days)
                * len(MAIN_ROUTE_COST_SPEC.trade_sizes_usd)
                * len(COMPARATOR_VEHICLES)
            )
            panel_rows, attempted_pairs = (
                int(value)
                for value in connection.execute(
                    f"""
                    SELECT count(*) FILTER (WHERE positive_finite_indirect_outputs),
                           count(*)
                    FROM read_parquet('{_quoted(pair_stage)}')
                    """
                ).fetchone()
            )

            def validate_staged(paths: Mapping[str, Path]) -> None:
                observed_panel_rows, observed_support_rows, observed_attempts = _validate_outputs(
                    connection,
                    paths["panel"],
                    paths["support"],
                    expected_support_rows=expected_support_rows,
                )
                if (
                    observed_panel_rows != panel_rows
                    or observed_support_rows != expected_support_rows
                    or observed_attempts != attempted_pairs
                ):
                    raise ValueError("dominance-cost release rows changed across publication")

            release = publish_artifact_release(
                pointer_path=pointer_path,
                kind=RELEASE_KIND,
                schema_version=RELEASE_SCHEMA_VERSION,
                filenames=RELEASE_FILENAMES,
                writers={
                    "panel": lambda path: _write_panel(connection, pair_stage, path),
                    "support": lambda path: _write_support(
                        connection, calendar_days, pair_stage, path
                    ),
                },
                row_counts={
                    "panel": panel_rows,
                    "support": expected_support_rows,
                },
                code_sources=RELEASE_CODE_SOURCES,
                inputs=[source, calendar, candidate_stage, pair_stage],
                notes="immutable pairwise WETH-versus-comparator outcomes and full zero-retention support; no all-five balance; prior generations retained as evidence",
                validate_staged=validate_staged,
                write_pointer=write_pointer,
            )
            _prune_superseded_cache(cache_root, {candidate_stage, pair_stage})
        finally:
            connection.close()
    return {
        "source_rows": source_rows,
        "calendar_days": len(calendar_days),
        "candidate_rows": candidate_rows,
        "pair_stage_rows": pair_stage_rows,
        "panel_rows": panel_rows,
        "support_rows": expected_support_rows,
        "attempted_pairs": attempted_pairs,
        "candidate_stage_reused": candidate_reused,
        "pair_stage_reused": pair_reused,
        "generation_id": release.generation_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-limit", default="2GB")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--calendar", type=Path, default=CALENDAR)
    parser.add_argument("--release", type=Path, default=RELEASE)
    parser.add_argument("--cache-root", type=Path, default=CACHE_ROOT)
    args = parser.parse_args()
    _assert_sole_materializer()
    if args.source == SOURCE and args.calendar == CALENDAR:
        require_current_artifacts([SOURCE, CALENDAR], consumer="dominance-cost D3 materializer")
    with exclusive_job(LOCK, job="pairwise dominance-cost D3 materialization"):
        results = build_panel(
            args.source,
            args.calendar,
            pointer_path=args.release,
            cache_root=args.cache_root,
            threads=args.threads,
            memory_limit=args.memory_limit,
        )
    print(
        f"validated {results['source_rows']:,} source rows; wrote {results['panel_rows']:,} supported pairs and {results['support_rows']:,} support strata from {results['attempted_pairs']:,} pair attempts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
