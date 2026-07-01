#!/usr/bin/env python3
"""Fetch raw DEX market data from genesis through the last complete month.

Examples:

  python3 scripts/fetch_raw_market_data.py plan --dex all
  python3 scripts/fetch_raw_market_data.py fetch --dex uniswap_v3 --start genesis --end 2026-07-01
  GRAPH_API_KEYS=... python3 scripts/fetch_raw_market_data.py fetch --dex all --streams swaps daily mints burns modify_liquidities hourly_reserves

The script is raw-first and intentionally over-fetches fields. Outputs are
verbatim gzipped JSONL under data/raw/thegraph/, plus per-day metadata sidecars.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.fetch.raw import fetch_source_day, raw_path, stream_names_for_source
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import (
    DEX_SOURCES,
    get_source,
    iter_days,
    last_complete_month_exclusive,
    source_names,
)


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def effective_range(source_name: str, start: str, end: str | None) -> tuple[dt.date, dt.date]:
    source = get_source(source_name)
    start_date = source.genesis if start == "genesis" else max(parse_date(start), source.genesis)
    end_date = parse_date(end) if end else last_complete_month_exclusive()
    if end_date <= start_date:
        raise ValueError(f"empty date range for {source_name}: {start_date} to {end_date}")
    return start_date, end_date


def selected_streams(source_name: str, requested: list[str] | None) -> set[str] | None:
    available = set(stream_names_for_source(source_name))
    if not requested or requested == ["all"]:
        return None
    unknown = set(requested) - available
    if unknown:
        raise ValueError(
            f"{source_name} does not support streams {sorted(unknown)}; "
            f"available streams: {sorted(available)}"
        )
    return set(requested)


def cmd_plan(args: argparse.Namespace) -> int:
    rows = []
    for name in source_names(args.dex):
        source = get_source(name)
        start, end = effective_range(name, args.start, args.end)
        streams = stream_names_for_source(name) if args.streams == ["all"] else args.streams
        days = iter_days(start, end)
        rows.append(
            {
                "source": name,
                "schema": source.schema,
                "genesis": source.genesis.isoformat(),
                "start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "days": len(days),
                "streams": streams,
                "notes": source.notes,
            }
        )
    print(json.dumps(rows, indent=2))
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    for name in source_names(args.dex):
        source = get_source(name)
        start, end = effective_range(name, args.start, args.end)
        streams = selected_streams(name, args.streams)
        days = iter_days(start, end)
        if args.max_days:
            days = days[: args.max_days]
        for day in days:
            if args.dry_run:
                names = stream_names_for_source(name) if streams is None else sorted(streams)
                targets = [str(raw_path(name, stream, day)) for stream in names]
                print(json.dumps({"source": name, "day": day.isoformat(), "targets": targets}))
                continue
            meta = fetch_source_day(source, day, streams=streams, skip_existing=not args.overwrite)
            print(json.dumps(meta, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [("plan", cmd_plan), ("fetch", cmd_fetch)]:
        p = sub.add_parser(name)
        p.add_argument("--dex", nargs="+", default=["all"], help="Source names or 'all'.")
        p.add_argument("--start", default="genesis", help="'genesis' or YYYY-MM-DD.")
        p.add_argument("--end", default=None, help="Exclusive YYYY-MM-DD; defaults to current month start.")
        p.add_argument(
            "--streams",
            nargs="+",
            default=["all"],
            help="Stream names or 'all' (e.g. swaps daily mints burns modify_liquidities).",
        )
        p.set_defaults(func=fn)
    sub.choices["fetch"].add_argument("--dry-run", action="store_true")
    sub.choices["fetch"].add_argument("--overwrite", action="store_true")
    sub.choices["fetch"].add_argument("--max-days", type=int, default=0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
