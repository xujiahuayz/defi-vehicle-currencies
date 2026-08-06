"""Strict, atomic assembly of Parquet day shards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.runtime import atomic_output


@dataclass(frozen=True)
class AssemblyResult:
    rows: int
    shards: int


def unified_schema(files: list[Path]) -> pa.Schema:
    """Unify every shard schema, including columns null-typed on early days."""
    if not files:
        raise ValueError("no Parquet shards supplied")
    schemas = [pq.ParquetFile(path).schema_arrow for path in files]
    schema = pa.unify_schemas(schemas, promote_options="permissive")
    return pa.schema(
        [
            pa.field(field.name, pa.large_string() if pa.types.is_null(field.type) else field.type)
            for field in schema
        ],
        metadata=schema.metadata,
    )


def align_table(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Add absent columns and cast present columns to the unified schema."""
    columns = []
    for field in schema:
        if field.name not in table.column_names:
            columns.append(pa.nulls(table.num_rows, type=field.type))
            continue
        column = table.column(field.name)
        columns.append(column if column.type == field.type else column.cast(field.type))
    return pa.Table.from_arrays(columns, schema=schema)


def assemble_parquet_shards(
    files: list[Path],
    output: Path,
    *,
    progress: Callable[[int, int, int], None] | None = None,
    unique_keys: tuple[str, ...] = (),
) -> AssemblyResult:
    """Assemble all shards without exposing a partial output on any failure."""
    ordered = sorted(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = unified_schema(ordered)
    rows = 0
    nonempty = 0
    with atomic_output(output) as temporary:
        writer: pq.ParquetWriter | None = None
        try:
            for index, path in enumerate(ordered, 1):
                table = pq.read_table(path)
                if table.num_rows:
                    if writer is None:
                        writer = pq.ParquetWriter(temporary, schema, compression="snappy")
                    writer.write_table(align_table(table, schema))
                    rows += table.num_rows
                    nonempty += 1
                if progress is not None:
                    progress(index, len(ordered), rows)
            if writer is None:
                raise RuntimeError("all Parquet shards are empty")
            writer.close()
            writer = None
            if unique_keys:
                assert_unique_parquet_keys(temporary, unique_keys)
        except BaseException:
            if writer is not None:
                writer.close()
            raise
    return AssemblyResult(rows=rows, shards=nonempty)


def assert_unique_parquet_keys(path: Path, keys: tuple[str, ...]) -> None:
    """Refuse an assembled panel containing duplicate economic cells."""
    import duckdb

    if not keys:
        raise ValueError("unique key contract is empty")
    schema_names = set(pq.ParquetFile(path).schema.names)
    missing = sorted(set(keys) - schema_names)
    if missing:
        raise ValueError(f"unique key columns are missing: {', '.join(missing)}")
    columns = ", ".join(f'"{column}"' for column in keys)
    connection = duckdb.connect()
    try:
        duplicate = connection.execute(
            f"""
            SELECT {columns}, count(*) AS duplicate_count
            FROM read_parquet(?)
            GROUP BY {columns}
            HAVING count(*) > 1
            LIMIT 1
            """,
            [str(path)],
        ).fetchone()
    finally:
        connection.close()
    if duplicate is not None:
        sample = dict(zip((*keys, "duplicate_count"), duplicate, strict=True))
        raise ValueError(f"assembled panel has duplicate keys: {sample}")
