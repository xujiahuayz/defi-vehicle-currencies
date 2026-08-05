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
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.fetch.dune import dune_meta_path, dune_path, fetch_dune_month, month_ranges, stream_names_for_dune_source
from ddvc.fetch.graph import GraphClient, first_record, graph_keys
from ddvc.fetch.raw import (
    block_value,
    fetch_source_day,
    meta_path,
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
    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
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


def available_streams(source_name: str) -> list[str]:
    source = get_source(source_name)
    return stream_names_for_dune_source(source) if source.backend == "dune" else stream_names_for_source(source_name)


def stream_target(source_name: str, stream: str, day: dt.date) -> Path:
    source = get_source(source_name)
    return dune_path(source_name, stream, day) if source.backend == "dune" else raw_path(source_name, stream, day)


def metadata_target(source_name: str, day: dt.date) -> Path:
    source = get_source(source_name)
    return dune_meta_path(source_name, day) if source.backend == "dune" else meta_path(source_name, day)


def missing_streams(source_name: str, day: dt.date, streams: list[str]) -> list[str]:
    return [stream for stream in streams if not stream_target(source_name, stream, day).exists()]


def coverage_report(names: list[str], end_by_source: dict[str, dt.date]) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for name in names:
        source = get_source(name)
        end = end_by_source[name]
        streams = available_streams(name)
        days = iter_days(source.genesis, end)
        by_stream: dict[str, list[str]] = {stream: [] for stream in streams}
        meta_missing: list[str] = []
        for day in days:
            for stream in streams:
                if not stream_target(name, stream, day).exists():
                    by_stream[stream].append(day.isoformat())
            if not metadata_target(name, day).exists():
                meta_missing.append(day.isoformat())
        report[name] = {
            "backend": source.backend,
            "start": source.genesis.isoformat(),
            "end_exclusive": end.isoformat(),
            "days": len(days),
            "missing": {stream: len(items) for stream, items in by_stream.items()},
            "missing_ranges": {
                stream: ([items[0], items[-1]] if items else [])
                for stream, items in by_stream.items()
            },
            "missing_meta": len(meta_missing),
            "missing_meta_range": [meta_missing[0], meta_missing[-1]] if meta_missing else [],
        }
    return report


def cmd_coverage(args: argparse.Namespace) -> int:
    names = source_names(args.dex)
    end_by_source = {name: effective_range(name, "genesis", args.end)[1] for name in names}
    print(json.dumps(coverage_report(names, end_by_source), indent=2, sort_keys=True))
    return 0


def fetch_gap_days(
    source_name: str,
    start: dt.date,
    end: dt.date,
    *,
    streams: set[str] | None,
    overwrite: bool,
    dry_run: bool,
    dune_sleep: float,
    max_retries: int,
) -> dict[str, int]:
    source = get_source(source_name)
    selected = sorted(streams) if streams is not None else available_streams(source_name)
    counts = {"days_seen": 0, "days_fetched": 0, "streams_fetched": 0}
    for day in iter_days(start, end):
        counts["days_seen"] += 1
        missing = selected if overwrite else missing_streams(source_name, day, selected)
        if not missing:
            continue
        counts["days_fetched"] += 1
        counts["streams_fetched"] += len(missing)
        if dry_run:
            print(json.dumps({"source": source_name, "day": day.isoformat(), "missing_streams": missing}, sort_keys=True))
            continue
        attempt = 0
        while True:
            try:
                if source.backend == "dune":
                    metas = fetch_dune_month(
                        source,
                        day,
                        day + dt.timedelta(days=1),
                        streams=set(missing),
                        skip_existing=not overwrite,
                    )
                    for meta in metas:
                        print(json.dumps(meta, sort_keys=True), flush=True)
                    if dune_sleep:
                        time.sleep(dune_sleep)
                else:
                    meta = fetch_source_day(source, day, streams=set(missing), skip_existing=not overwrite)
                    print(json.dumps(meta, sort_keys=True), flush=True)
                break
            except RuntimeError as exc:
                attempt += 1
                if attempt > max_retries:
                    raise
                sleep_seconds = min(300, 10 * attempt)
                print(
                    json.dumps(
                        {
                            "source": source_name,
                            "day": day.isoformat(),
                            "missing_streams": missing,
                            "status": "retrying",
                            "attempt": attempt,
                            "sleep_seconds": sleep_seconds,
                            "error": str(exc)[:500],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                time.sleep(sleep_seconds)
    return counts


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.gaps_only:
        totals = {}
        end_by_source = {}
        for name in source_names(args.dex):
            start, end = effective_range(name, args.start, args.end)
            end_by_source[name] = end
            streams = selected_streams(name, args.streams)
            totals[name] = fetch_gap_days(
                name,
                start,
                end,
                streams=streams,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
                dune_sleep=args.dune_sleep,
                max_retries=args.max_retries,
            )
        print(json.dumps({"totals": totals, "coverage": coverage_report(list(totals), end_by_source)}, indent=2, sort_keys=True))
        return 0

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
        if args.dry_run:
            names = stream_names_for_source(name) if streams is None else sorted(streams)
            for day in days:
                targets = [str(raw_path(name, stream, day)) for stream in names]
                print(json.dumps({"source": name, "day": day.isoformat(), "targets": targets}))
            continue

        # Days are independent and the work is waiting on gateway replies, not CPU,
        # so fetching them one at a time left the machine idle: a measured 64
        # seconds per day put a two-stream backfill of 2,248 days at roughly 38
        # hours. `fetch_source_day` already builds its own client per day, so it is
        # safe to run several at once, and threads are the right tool because the
        # GIL is released during requests. Concurrency is capped near the number of
        # LIVE keys rather than pushed higher: twelve concurrent workers is what
        # tripped the public RPC endpoints' rate limits earlier, and the same
        # mistake is available here.
        workers = max(1, args.workers)
        if workers == 1:
            for day in days:
                meta = fetch_source_day(source, day, streams=streams,
                                        skip_existing=not args.overwrite)
                print(json.dumps(meta, sort_keys=True))
            continue
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(fetch_source_day, source, day, streams=streams,
                            skip_existing=not args.overwrite): day
                for day in days
            }
            for fut in as_completed(futs):
                day = futs[fut]
                try:
                    print(json.dumps(fut.result(), sort_keys=True))
                except Exception as exc:
                    print(json.dumps({"source": name, "day": day.isoformat(),
                                      "error": f"{type(exc).__name__}: {exc}"[:300]}))
                done += 1
                if done % 50 == 0 or done == len(days):
                    print(f"# {name}: {done}/{len(days)} days", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [("plan", cmd_plan), ("fetch", cmd_fetch), ("coverage", cmd_coverage), ("audit-genesis", cmd_audit_genesis)]:
        p = sub.add_parser(name)
        p.add_argument("--dex", nargs="+", default=["all"], help="Source names or 'all'.")
        if name == "fetch":
            p.add_argument("--workers", type=int, default=5,
                           help="days fetched concurrently. Default matches the "
                                "number of live Graph keys; the work is gateway "
                                "latency, not CPU.")
        if name != "audit-genesis":
            p.add_argument("--start", default="genesis", help="'genesis' or YYYY-MM-DD.")
            p.add_argument("--end", default=None, help="Exclusive YYYY-MM-DD; defaults to current month start.")
            if name != "coverage":
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
    sub.choices["fetch"].add_argument("--gaps-only", action="store_true", help="Fetch only missing day/stream targets.")
    sub.choices["fetch"].add_argument("--dune-sleep", type=float, default=2.0, help="Seconds to sleep between day-sized Dune gap fetches.")
    sub.choices["fetch"].add_argument("--max-retries", type=int, default=50, help="Per-day retries for transient provider/indexer errors in --gaps-only mode.")
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
