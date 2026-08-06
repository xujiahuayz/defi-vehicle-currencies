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

The schema is unified across every shard before anything is written, so no day can narrow
the schema for the days that follow. Assembly writes to a temporary file, refuses an
unreadable shard, and replaces the final panel only after all shards succeed.

Reads   data/empirical/_route_cost_day_cache/engine_*/h*/YYYYMMDD.parquet
Writes  data/empirical/route_cost_panel_v2.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, ROUTE_COST_JOB_LOCK
from ddvc.provenance import stamp
from ddvc.route_cost_summary import write_route_cost_summary
from ddvc.runtime import exclusive_job
from scripts.run_route_cost_panel import QUOTE_CELL_KEYS

CACHE = DATA_DIR / "empirical" / "_route_cost_day_cache"
OUT = DATA_DIR / "empirical" / "route_cost_panel_v2.parquet"
SUMMARY = OUTPUT_DIR / "empirical" / "route_cost_panel_v2_summary.pkl"
CODE_SOURCES = [
    "scripts/assemble_route_cost_panel.py",
    "src/ddvc/panel_assembly.py",
    "scripts/run_route_cost_panel.py",
    "src/ddvc/pricing/stableswap.py",
    "src/ddvc/pricing/v2quote.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/pricing/v3quote.py",
    "src/ddvc/pricing/weighted.py",
]


def fullest_spec() -> Path | None:
    """Return the unique fullest cache, refusing an ambiguous engine tie."""
    dirs = [d for d in CACHE.glob("engine_*/*") if d.is_dir()]
    if not dirs:
        return None
    counts = {directory: len(list(directory.glob("[0-9]*.parquet"))) for directory in dirs}
    fullest = max(counts.values())
    winners = sorted(directory for directory, count in counts.items() if count == fullest)
    if len(winners) != 1:
        choices = ", ".join(str(path.relative_to(CACHE)) for path in winners)
        raise RuntimeError(f"ambiguous fullest caches ({fullest:,} days): {choices}; pass --spec")
    return winners[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default=None, help="cache directory, defaults to the fullest")
    args = ap.parse_args()

    spec = Path(args.spec) if args.spec else fullest_spec()
    if spec is None:
        print(f"no day cache under {CACHE.relative_to(REPO_ROOT)}")
        return 1
    files = sorted(spec.glob("[0-9]*.parquet"))
    if not files:
        print(f"no cached days in {spec}")
        return 1
    print(f"assembling {len(files):,} cached days from {spec.relative_to(REPO_ROOT)}", flush=True)

    def progress(index: int, total: int, rows: int) -> None:
        if index % 250 == 0 or index == total:
            print(f"  [{index}/{total}] {rows:,} rows", flush=True)

    result = assemble_parquet_shards(
        files,
        OUT,
        progress=progress,
        unique_keys=QUOTE_CELL_KEYS,
    )
    print(f"\nassembled {result.rows:,} rows from {result.shards:,} nonempty days into "
          f"{OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size / 1e6:.0f} MB)")
    manifest = stamp(OUT, code_sources=CODE_SOURCES, inputs=[spec], rows=result.rows,
                     notes=(f"assembled all {len(files)} readable day shards from "
                            f"{spec.relative_to(REPO_ROOT)}; {result.shards} nonempty"))
    print(f"stamped {manifest.relative_to(REPO_ROOT)}")
    summary = write_route_cost_summary(OUT, SUMMARY)
    summary_manifest = stamp(
        SUMMARY,
        code_sources=[*CODE_SOURCES, "src/ddvc/route_cost_summary.py"],
        inputs=[OUT],
        rows=len(summary),
    )
    print(
        f"wrote {len(summary):,} summary rows and stamped "
        f"{summary_manifest.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(ROUTE_COST_JOB_LOCK, job="route-cost panel build or assembly"):
        raise SystemExit(main())
