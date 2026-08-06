#!/usr/bin/env python3
"""Report which derived artefacts are still the product of the current code.

This is the check that was missing when the route-cost day cache kept serving
quotes from a since-fixed V3 quoter. Staleness was undetectable: the cached files
looked exactly like fresh ones, the panel built from them looked plausible, and
nothing in the repository could answer "was this built by the code I have now?".

Three verdicts matter, in descending severity:

  stale       stamped, and the sources that can change it have changed since.
              Its numbers must not be quoted or plotted. Rebuild it.
  unstamped   exists with no provenance at all, so the question cannot be
              answered. Every artefact predating `ddvc.provenance` is here; the
              count going DOWN over time is the measure of progress.
  ok          stamped and the fingerprint still matches.

Exit code is 1 when anything is stale, so this can gate a paper build: a table
should never be rendered from a panel whose code has moved on. Unstamped alone
does not fail the run, since that would block every existing artefact at once;
use `--strict` to fail on those too once coverage is complete.

Usage
    ./scripts/run scripts/check_reproducibility.py [--strict] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from ddvc.provenance import git_state, verify  # noqa: E402

# Where derived artefacts live. Raw data is excluded on purpose: it carries its
# own per-day fetch `meta` sidecars and is an input, not a product of this code.
ARTEFACT_DIRS = (
    "data/processed",
    "data/empirical",
    "data/unified",
    "data/interim",
    "data/metrics",
    "output/exhibits",
    "output/empirical",
    "output/tables",
    "output/figures",
)
# Parquet for analytic panels, JSON Lines for paper-facing exhibits, TeX and PDF
# for rendered tables, images for figures. Delimited text is absent by design: the
# repository forbids generating it and a test enforces that, so there is nothing of
# that kind left to scan for.
SUFFIXES = (".parquet", ".pkl", ".jsonl", ".json", ".gz", ".tex", ".pdf", ".png", ".svg")


# Per-day cache shards are not stamped individually and should not be reported as
# missing provenance. Their generation is already encoded in the directory name,
# which is a fingerprint of the quoting sources plus the arguments that decide what
# is computed, so a shard from superseded code is unreachable rather than merely
# unlabelled. Stamping each of 2,277 shards would add thousands of sidecars that
# say the same thing as their parent directory.
CACHE_MARKERS = ("_route_cost_day_cache", "_day_cache", "__pycache__")


def collect() -> list[Path]:
    out: list[Path] = []
    for d in ARTEFACT_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            if any(m in p.parts for m in CACHE_MARKERS):
                continue
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="also fail when an artefact has no provenance stamp")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit-list", type=int, default=15)
    args = ap.parse_args()

    g = git_state()
    arts = collect()
    verdicts = [verify(p) for p in arts]
    by = {"ok": [], "stale": [], "unstamped": [], "missing_artefact": []}
    for v in verdicts:
        by[str(v["status"])].append(v)

    if args.json:
        print(json.dumps({"git": g, "verdicts": verdicts}, indent=1))
    else:
        dirty = g.get("dirty")
        print(f"commit {g.get('commit') or '?'} on {g.get('branch') or '?'}"
              f"{'  (WORKING TREE DIRTY: stamps made now are not reproducible from this commit alone)' if dirty else ''}")
        print(f"\n{len(arts):,} derived artefacts scanned across {len(ARTEFACT_DIRS)} directories\n")
        print(f"  ok         {len(by['ok']):>6}   stamped, code unchanged since")
        print(f"  STALE      {len(by['stale']):>6}   built by code that has since changed")
        print(f"  unstamped  {len(by['unstamped']):>6}   no provenance, cannot be verified")
        if by["stale"]:
            print("\nSTALE, do not quote these until rebuilt:")
            for v in by["stale"][: args.limit_list]:
                print(f"  {v['artefact']}")
                print(f"     stamped {str(v['stamped_fingerprint'])[:12]} at {v['created_at']}"
                      f"  ->  current {str(v['current_fingerprint'])[:12]}")
            if len(by["stale"]) > args.limit_list:
                print(f"  ... and {len(by['stale']) - args.limit_list} more")
        if by["unstamped"]:
            print(f"\nunstamped (add `provenance.stamp(...)` to the script that writes each):")
            for v in by["unstamped"][: args.limit_list]:
                print(f"  {v['artefact']}")
            if len(by["unstamped"]) > args.limit_list:
                print(f"  ... and {len(by['unstamped']) - args.limit_list} more")

    if by["stale"]:
        return 1
    if args.strict and by["unstamped"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
