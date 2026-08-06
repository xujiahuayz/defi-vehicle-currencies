"""Strict, atomic assembly of Parquet day shards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


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
) -> AssemblyResult:
    """Assemble all shards without exposing a partial output on any failure."""
    ordered = sorted(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    schema = unified_schema(ordered)
    writer: pq.ParquetWriter | None = None
    rows = 0
    nonempty = 0
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
        temporary.replace(output)
    except BaseException:
        try:
            if writer is not None:
                writer.close()
        finally:
            if temporary.exists():
                temporary.unlink()
        raise
    return AssemblyResult(rows=rows, shards=nonempty)
