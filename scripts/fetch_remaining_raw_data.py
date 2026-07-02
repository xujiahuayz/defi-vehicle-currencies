#!/usr/bin/env python3
"""Fetch only raw DVC source-days still missing after DDC import.

This runner is intentionally conservative: it checks the DVC target path before
fetching, fetches only absent streams, and writes into the canonical raw layout.
Existing files and symlinks are left untouched unless --overwrite is passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.fetch.dune import dune_meta_path, dune_path, fetch_dune_month, stream_names_for_dune_source
from ddvc.fetch.raw import fetch_source_day, meta_path, raw_path, stream_names_for_source
from ddvc.fetch.sources import get_source, iter_days, source_names


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def expected_streams(name: str) -> list[str]:
    source = get_source(name)
    return stream_names_for_dune_source(source) if source.backend == "dune" else stream_names_for_source(name)


def stream_path(name: str, stream: str, day: dt.date) -> Path:
    source = get_source(name)
    return dune_path(name, stream, day) if source.backend == "dune" else raw_path(name, stream, day)


def source_meta_path(name: str, day: dt.date) -> Path:
    source = get_source(name)
    return dune_meta_path(name, day) if source.backend == "dune" else meta_path(name, day)


def missing_for_day(name: str, day: dt.date, streams: list[str]) -> list[str]:
    return [stream for stream in streams if not stream_path(name, stream, day).exists()]


def coverage(end: dt.date, names: list[str]) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for name in names:
        source = get_source(name)
        streams = expected_streams(name)
        days = iter_days(source.genesis, end)
        stream_missing: dict[str, list[str]] = {stream: [] for stream in streams}
        meta_missing: list[str] = []
        for day in days:
            for stream in streams:
                if not stream_path(name, stream, day).exists():
                    stream_missing[stream].append(day.isoformat())
            if not source_meta_path(name, day).exists():
                meta_missing.append(day.isoformat())
        report[name] = {
            "backend": source.backend,
            "start": source.genesis.isoformat(),
            "end_exclusive": end.isoformat(),
            "days": len(days),
            "missing": {stream: len(items) for stream, items in stream_missing.items()},
            "missing_ranges": {
                stream: ([items[0], items[-1]] if items else [])
                for stream, items in stream_missing.items()
            },
            "missing_meta": len(meta_missing),
            "missing_meta_range": [meta_missing[0], meta_missing[-1]] if meta_missing else [],
        }
    return report


def fetch_missing_source(
    name: str,
    end: dt.date,
    *,
    overwrite: bool,
    dry_run: bool,
    dune_sleep: float,
) -> dict[str, int]:
    source = get_source(name)
    streams = expected_streams(name)
    counts = {"days_seen": 0, "days_fetched": 0, "streams_fetched": 0}
    for day in iter_days(source.genesis, end):
        counts["days_seen"] += 1
        missing = streams if overwrite else missing_for_day(name, day, streams)
        if not missing:
            continue
        counts["days_fetched"] += 1
        counts["streams_fetched"] += len(missing)
        if dry_run:
            print(json.dumps({"source": name, "day": day.isoformat(), "missing_streams": missing}, sort_keys=True), flush=True)
            continue
        if source.backend == "dune":
            fetch_dune_month(
                source,
                day,
                day + dt.timedelta(days=1),
                streams=set(missing),
                skip_existing=not overwrite,
            )
            if dune_sleep:
                time.sleep(dune_sleep)
        else:
            fetch_source_day(source, day, streams=set(missing), skip_existing=not overwrite)
        print(json.dumps({"source": name, "day": day.isoformat(), "fetched_streams": missing}, sort_keys=True), flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dex", nargs="+", default=["all"], help="Source names or all.")
    parser.add_argument("--end", default="2026-07-01", help="Exclusive YYYY-MM-DD.")
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dune-sleep", type=float, default=2.0)
    args = parser.parse_args()

    names = source_names(args.dex)
    end = parse_date(args.end)
    if args.coverage_only:
        print(json.dumps(coverage(end, names), indent=2, sort_keys=True))
        return 0

    totals: dict[str, dict[str, int]] = {}
    for name in names:
        totals[name] = fetch_missing_source(
            name,
            end,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            dune_sleep=args.dune_sleep,
        )
    print(json.dumps({"totals": totals, "coverage": coverage(end, names)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
