#!/usr/bin/env python3
"""Fetch raw DEX market data from genesis through the last complete month.

Examples:

  python3 scripts/fetch_raw_market_data.py plan --dex all
  python3 scripts/fetch_raw_market_data.py audit-genesis --dex all
  python3 scripts/fetch_raw_market_data.py fetch --dex uniswap_v3 --start genesis --end 2026-07-01
  GRAPH_API_KEYS=... python3 scripts/fetch_raw_market_data.py fetch --dex all --streams swaps daily mints burns modify_liquidities hourly_reserves

The script is raw-first and intentionally over-fetches fields. Outputs are
verbatim gzipped JSONL under data/raw/thegraph/ or data/raw/dune/, plus per-day
metadata sidecars.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.fetch.dune import dune_path, fetch_dune_month, month_ranges, stream_names_for_dune_source
from ddvc.fetch.graph import GraphClient, first_record, graph_keys
from ddvc.fetch.raw import (
    block_value,
    fetch_source_day,
    midnight_ts,
    raw_path,
    stream_names_for_source,
    timestamp_value,
)
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
    source = get_source(source_name)
    available = (
        set(stream_names_for_dune_source(source))
        if source.backend == "dune"
        else set(stream_names_for_source(source_name))
    )
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
        if args.streams == ["all"]:
            streams = (
                stream_names_for_dune_source(source)
                if source.backend == "dune"
                else stream_names_for_source(name)
            )
        else:
            streams = args.streams
        days = iter_days(start, end)
        rows.append(
            {
                "source": name,
                "backend": source.backend,
                "schema": source.schema,
                "genesis_block": source.genesis_block,
                "genesis_date_utc": source.genesis_date_utc.isoformat(),
                "subgraph_id": source.subgraph_id or None,
                "dune_project": source.dune_project,
                "dune_version": source.dune_version,
                "start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "days": len(days),
                "streams": streams,
                "notes": source.notes,
            }
        )
    print(json.dumps(rows, indent=2))
    return 0


def first_swap_entity(source_name: str):
    schema = get_schema(get_source(source_name).schema)
    for entity in schema.entities:
        if entity.stream == "swaps":
            return entity
    raise ValueError(f"{source_name} has no swaps stream")


def audit_source_genesis(source_name: str) -> dict[str, object]:
    source = get_source(source_name)
    if source.backend != "thegraph":
        return {
            "source": source.name,
            "backend": source.backend,
            "configured_genesis_block": source.genesis_block,
            "configured_genesis_date_utc": source.genesis_date_utc.isoformat(),
            "status": "skipped-non-graph-backend",
        }
    entity = first_swap_entity(source_name)
    client = GraphClient(source.subgraph_id, graph_keys())
    genesis_ts = midnight_ts(source.genesis_date_utc)
    previous_day = {
        f"{entity.time_field}_gte": str(genesis_ts - 86_400),
        f"{entity.time_field}_lt": str(genesis_ts),
    }
    genesis_day = {
        f"{entity.time_field}_gte": str(genesis_ts),
        f"{entity.time_field}_lt": str(genesis_ts + 86_400),
    }
    first = first_record(
        client,
        entity=entity.entity,
        fields=entity.fields,
        order_by=entity.time_field,
    )
    prior = first_record(
        client,
        entity=entity.entity,
        fields=entity.fields,
        order_by=entity.time_field,
        where=previous_day,
    )
    first_on_genesis_day = first_record(
        client,
        entity=entity.entity,
        fields=entity.fields,
        order_by=entity.time_field,
        where=genesis_day,
    )
    first_ts = timestamp_value(first)
    first_block = block_value(first)
    observed_day = (
        dt.datetime.fromtimestamp(first_ts, tz=dt.timezone.utc).date().isoformat()
        if first_ts is not None
        else None
    )
    return {
        "source": source.name,
        "backend": source.backend,
        "subgraph_id": source.subgraph_id,
        "configured_genesis_block": source.genesis_block,
        "configured_genesis_date_utc": source.genesis_date_utc.isoformat(),
        "first_indexed_swap_block": first_block,
        "first_indexed_swap_timestamp": first_ts,
        "first_indexed_swap_date_utc": observed_day,
        "first_indexed_swap_matches_configured_day": observed_day
        == source.genesis_date_utc.isoformat(),
        "first_indexed_swap_block_delta": first_block - source.genesis_block
        if first_block is not None
        else None,
        "has_prior_day_swap": prior is not None,
        "first_configured_day_swap_block": block_value(first_on_genesis_day),
        "first_configured_day_swap_timestamp": timestamp_value(first_on_genesis_day),
    }


def cmd_audit_genesis(args: argparse.Namespace) -> int:
    names = source_names(args.dex)
    needs_graph = any(get_source(name).backend == "thegraph" for name in names)
    if needs_graph and not graph_keys():
        raise RuntimeError("No Graph API key set. Use GRAPH_API_KEYS or GRAPH_API_KEY.")
    rows = [audit_source_genesis(name) for name in names]
    print(json.dumps(rows, indent=2, sort_keys=True))
    bad = [
        row
        for row in rows
        if row.get("status") != "skipped-non-graph-backend"
        and (row["has_prior_day_swap"] or not row["first_indexed_swap_matches_configured_day"])
    ]
    return 1 if bad and args.strict else 0


def cmd_fetch(args: argparse.Namespace) -> int:
    for name in source_names(args.dex):
        source = get_source(name)
        start, end = effective_range(name, args.start, args.end)
        streams = selected_streams(name, args.streams)
        if source.backend == "dune":
            for month_start, month_end in month_ranges(start, end):
                if args.max_days and month_start >= start + dt.timedelta(days=args.max_days):
                    break
                if args.dry_run:
                    days = iter_days(month_start, month_end)
                    if args.max_days:
                        days = days[: max(0, args.max_days - (month_start - start).days)]
                    selected = stream_names_for_dune_source(source) if streams is None else sorted(streams)
                    for day in days:
                        targets = [str(dune_path(name, stream, day)) for stream in selected]
                        print(json.dumps({"source": name, "backend": "dune", "day": day.isoformat(), "targets": targets}))
                    continue
                metas = fetch_dune_month(source, month_start, month_end, streams=streams, skip_existing=not args.overwrite)
                for meta in metas:
                    print(json.dumps(meta, sort_keys=True))
            continue
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
    for name, fn in [("plan", cmd_plan), ("fetch", cmd_fetch), ("audit-genesis", cmd_audit_genesis)]:
        p = sub.add_parser(name)
        p.add_argument("--dex", nargs="+", default=["all"], help="Source names or 'all'.")
        if name != "audit-genesis":
            p.add_argument("--start", default="genesis", help="'genesis' or YYYY-MM-DD.")
            p.add_argument("--end", default=None, help="Exclusive YYYY-MM-DD; defaults to current month start.")
            p.add_argument(
                "--streams",
                nargs="+",
                default=["all"],
                help="Stream names or 'all' (e.g. swaps daily mints burns modify_liquidities).",
            )
        else:
            p.add_argument("--strict", action="store_true", help="Exit nonzero on an audit mismatch.")
        p.set_defaults(func=fn)
    sub.choices["fetch"].add_argument("--dry-run", action="store_true")
    sub.choices["fetch"].add_argument("--overwrite", action="store_true")
    sub.choices["fetch"].add_argument("--max-days", type=int, default=0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
