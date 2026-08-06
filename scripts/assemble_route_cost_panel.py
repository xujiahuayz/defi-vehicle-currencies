#!/usr/bin/env python3
"""Assemble the route-cost panel from the day cache, without re-pricing anything.

A four-hour rebuild priced all 2,277 days into the cache and then produced a panel holding
three of them. The pricing was fine; the assembly failed on the last step and threw away
the run's visible output:

    pyarrow.lib.ArrowNotImplementedError: Unsupported cast from large_string to null

The writer takes its schema from the FIRST day it writes. On that day one column happened
to be entirely null, so Arrow typed it `null`, and the schema was then fixed. A later day
carried real strings in that column, casting `large_string` into `null` is not a thing, and
the exception propagated out of the assembly loop. The `finally` closed the writer on a
partial file, so the panel on disk looked like a finished artefact holding three days.

Two reasons this lives in its own script. Assembly is cheap and pricing is not, so a failure
in the last step should never cost the first four hours again. And the panel builder's
source is part of the cache key, so editing it to fix this would invalidate every one of the
2,277 cached days and force the whole rebuild.

The schema is unified before anything is written: a column typed `null` anywhere is promoted
to `large_string`, and the union of all days' fields is taken from a scan, so no day can
narrow the schema for the days that follow.

Reads   data/empirical/_route_cost_day_cache/engine_*/h*/YYYYMMDD.parquet
Writes  data/empirical/route_cost_panel_v2.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.provenance import stamp  # noqa: E402

CACHE = ROOT / "data" / "empirical" / "_route_cost_day_cache"
OUT = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
CODE_SOURCES = [
    "scripts/assemble_route_cost_panel.py",
    "scripts/run_route_cost_panel.py",
    "src/ddvc/pricing/stableswap.py",
    "src/ddvc/pricing/v2quote.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/pricing/v3quote.py",
    "src/ddvc/pricing/weighted.py",
]


def newest_spec() -> Path | None:
    """The cache directory holding the most priced days."""
    dirs = [d for d in CACHE.glob("engine_*/*") if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: len(list(d.glob("[0-9]*.parquet"))))


def unified_schema(files: list[Path], scan: int) -> pa.Schema:
    """Union of every day's fields, with null-typed columns promoted to string.

    Scanning a sample and taking the union is what stops one unlucky day from deciding the
    types for two thousand others.
    """
    fields: dict[str, pa.DataType] = {}
    step = max(1, len(files) // scan)
    for f in files[::step][:scan] + files[-3:]:
        for fld in pq.ParquetFile(f).schema_arrow:
            t = fld.type
            if pa.types.is_null(t):
                t = pa.large_string()
            prev = fields.get(fld.name)
            if prev is None or pa.types.is_null(prev):
                fields[fld.name] = t
            elif prev != t:
                # Widen rather than fail. A column read as int on one day and float on
                # another is the same measurement at different precision.
                if pa.types.is_integer(prev) and pa.types.is_floating(t):
                    fields[fld.name] = t
                elif pa.types.is_string(t) or pa.types.is_large_string(t):
                    fields[fld.name] = pa.large_string()
    return pa.schema([pa.field(k, v) for k, v in fields.items()])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", type=int, default=120,
                    help="days sampled when deriving the unified schema")
    ap.add_argument("--spec", default=None, help="cache directory, defaults to the fullest")
    args = ap.parse_args()

    spec = Path(args.spec) if args.spec else newest_spec()
    if spec is None:
        print(f"no day cache under {CACHE.relative_to(ROOT)}")
        return 1
    files = sorted(spec.glob("[0-9]*.parquet"))
    if not files:
        print(f"no cached days in {spec}")
        return 1
    print(f"assembling {len(files):,} cached days from {spec.relative_to(ROOT)}", flush=True)

    schema = unified_schema(files, args.scan)
    print(f"unified schema: {len(schema)} columns", flush=True)

    writer = None
    rows = skipped = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp.parquet")
    try:
        for i, f in enumerate(files, 1):
            try:
                tbl = pq.read_table(f)
            except Exception as exc:
                print(f"  {f.name}: unreadable, {type(exc).__name__}")
                skipped += 1
                continue
            if tbl.num_rows == 0:
                continue
            # Add any column this day lacks, as nulls of the unified type, then reorder.
            cols, names = [], []
            for fld in schema:
                names.append(fld.name)
                if fld.name in tbl.column_names:
                    col = tbl.column(fld.name)
                    if col.type != fld.type:
                        try:
                            col = col.cast(fld.type)
                        except Exception:
                            col = pa.chunked_array(
                                [pa.array([None] * tbl.num_rows, type=fld.type)])
                    cols.append(col)
                else:
                    cols.append(pa.chunked_array(
                        [pa.array([None] * tbl.num_rows, type=fld.type)]))
            out = pa.Table.from_arrays([c.combine_chunks() for c in cols], names=names)
            if writer is None:
                writer = pq.ParquetWriter(tmp, schema, compression="snappy")
            writer.write_table(out)
            rows += out.num_rows
            if i % 250 == 0:
                print(f"  [{i}/{len(files)}] {rows:,} rows", flush=True)
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        print("nothing assembled")
        return 1
    tmp.replace(OUT)
    print(f"\nassembled {rows:,} rows from {len(files) - skipped:,} days into "
          f"{OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.0f} MB)")
    if skipped:
        print(f"{skipped} day(s) were unreadable and are named above")
    manifest = stamp(OUT, code_sources=CODE_SOURCES, inputs=[spec], rows=rows,
                     notes=(f"assembled {len(files) - skipped} readable day shards from "
                            f"{spec.relative_to(ROOT)}; {skipped} unreadable"))
    print(f"stamped {manifest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
