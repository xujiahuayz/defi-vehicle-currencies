#!/usr/bin/env python3
"""Fetch raw DEX market data from genesis through the last complete month.

Examples:

  ./scripts/run scripts/fetch_raw_market_data.py plan --dex all
  ./scripts/run scripts/fetch_raw_market_data.py audit-genesis --dex all
  ./scripts/run scripts/fetch_raw_market_data.py fetch --dex uniswap_v3 --start genesis --end 2026-07-01
  GRAPH_API_KEYS=... ./scripts/run scripts/fetch_raw_market_data.py fetch --dex all --streams swaps daily mints burns modify_liquidities hourly_reserves

The script is raw-first and intentionally over-fetches fields. Outputs are
verbatim gzipped JSONL under data/raw/thegraph/ or data/raw/dune/, plus per-day
metadata sidecars.
"""

from __future__ import annotations

import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import json
import sys
import time
from pathlib import Path

from ddvc.fetch.dune import dune_meta_path, dune_path, fetch_dune_month, month_ranges, stream_names_for_dune_source
from ddvc.fetch.graph import GraphClient, first_record, graph_keys, paginate
from ddvc.fetch.raw import (
    fetch_source_day,
    meta_path,
    midnight_ts,
    raw_path,
    stream_names_for_source,
    write_json,
    write_jsonl_gz,
)
from ddvc.fetch.schemas import UNISWAP_V4_STATIC_FIELDS, get_schema
from ddvc.fetch.sources import (
    DEX_SOURCES,
    UNISWAP_V4_STATICS_SUBGRAPH_ID,
    get_source,
    iter_days,
    last_complete_month_exclusive,
    source_names,
)
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.runtime import bounded_workers, exclusive_job
from ddvc.source_records import (
    block_value,
    merge_v4_statics,
    timestamp_value,
    v4_statics_complete,
)

RAW_MUTATION_LOCK = RAW_MARKET_DATA_LOCK


def sparse_days(path: Path, source_name: str) -> list[dt.date]:
    """Read a sorted unique repair calendar, one ISO date per non-comment line."""
    genesis = get_source(source_name).genesis
    days = sorted(
        {
            parse_date(line.strip())
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    )
    if not days:
        raise ValueError(f"empty sparse-day file: {path}")
    before_genesis = [day for day in days if day < genesis]
    if before_genesis:
        raise ValueError(
            f"{source_name} sparse-day file precedes genesis: {before_genesis[0]}"
        )
    return days


def enrich_v4_statics_day(day: dt.date) -> dict[str, object]:
    """Fill quote statics without replacing signed amounts or block provenance."""
    path = raw_path("uniswap_v4", "swaps", day)
    if not path.exists():
        raise RuntimeError(f"missing canonical v4 swaps for {day}")
    with gzip.open(path, "rt") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    metadata_path = meta_path("uniswap_v4", day)
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        metadata = {"source": "uniswap_v4", "day": day.isoformat()}

    incomplete = [row for row in rows if not v4_statics_complete(row)]
    missing_ids = [row.get("id") for row in incomplete]
    if any(not isinstance(row_id, str) or not row_id for row_id in missing_ids):
        raise RuntimeError(f"canonical v4 swaps contain a missing record ID on {day}")
    missing = set(missing_ids)
    if len(missing) != len(missing_ids):
        raise RuntimeError(f"canonical v4 swaps contain duplicate record IDs on {day}")
    if not missing:
        enrichment = metadata.get("statics_enrichment")
        if isinstance(enrichment, dict) and enrichment.get("status") == "prepared":
            enrichment["status"] = "complete"
            enrichment["enriched_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            write_json(metadata_path, metadata)
            return {"day": day.isoformat(), "rows": len(rows), "enriched": 0, "status": "recovered"}
        return {"day": day.isoformat(), "rows": len(rows), "enriched": 0, "status": "already_complete"}

    client = GraphClient(UNISWAP_V4_STATICS_SUBGRAPH_ID, graph_keys())
    start = midnight_ts(day)
    auxiliary_rows = paginate(
        client,
        entity="swaps",
        fields=UNISWAP_V4_STATIC_FIELDS,
        base_where={"timestamp_gte": str(start), "timestamp_lt": str(start + 86_400)},
    )
    auxiliary_ids = [row.get("id") for row in auxiliary_rows]
    if any(not isinstance(row_id, str) or not row_id for row_id in auxiliary_ids):
        raise RuntimeError(f"auxiliary v4 swaps contain a missing record ID on {day}")
    auxiliary = dict(zip(auxiliary_ids, auxiliary_rows, strict=True))
    if len(auxiliary) != len(auxiliary_rows):
        raise RuntimeError(f"auxiliary v4 swaps contain duplicate record IDs on {day}")
    unresolved = sorted(missing.difference(auxiliary))
    if unresolved:
        raise RuntimeError(
            f"v4 statics source misses {len(unresolved):,}/{len(missing):,} canonical swaps on {day}"
        )
    for row in rows:
        row_id = row.get("id")
        if row_id in missing:
            merge_v4_statics(row, auxiliary[row_id])
    metadata["statics_enrichment"] = {
        "source_subgraph_id": UNISWAP_V4_STATICS_SUBGRAPH_ID,
        "matched_by": "swap_id",
        "fields": [
            "pool.feeTier",
            "pool.tickSpacing",
            "pool.hooks",
            "pool.token0.decimals",
            "pool.token1.decimals",
        ],
        "rows": len(missing),
        "status": "prepared",
        "prepared_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(metadata_path, metadata)
    write_jsonl_gz(path, rows)
    metadata["statics_enrichment"]["status"] = "complete"
    metadata["statics_enrichment"]["enriched_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(metadata_path, metadata)
    return {"day": day.isoformat(), "rows": len(rows), "enriched": len(missing), "status": "enriched"}


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
    with exclusive_job(RAW_MUTATION_LOCK, job="raw market-data fetch or enrichment"):
        return _cmd_fetch(args)


def _cmd_fetch(args: argparse.Namespace) -> int:
    failures: list[tuple[str, str, str]] = []
    if args.days_file and args.gaps_only:
        raise ValueError("--days-file and --gaps-only are mutually exclusive")
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
        days = sparse_days(args.days_file, name) if args.days_file else None
        start, end = (
            (days[0], days[-1] + dt.timedelta(days=1))
            if days is not None
            else effective_range(name, args.start, args.end)
        )
        streams = selected_streams(name, args.streams)
        if source.backend == "dune":
            if days is not None:
                raise ValueError("--days-file currently supports The Graph sources only")
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
        days = days if days is not None else iter_days(start, end)
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
        workers = bounded_workers(args.workers)
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
                    failures.append((name, day.isoformat(), f"{type(exc).__name__}: {exc}"))
                    print(json.dumps({"source": name, "day": day.isoformat(),
                                      "error": f"{type(exc).__name__}: {exc}"[:300]}))
                done += 1
                if done % 50 == 0 or done == len(days):
                    print(f"# {name}: {done}/{len(days)} days", flush=True)
    if failures:
        print(
            f"error: {len(failures):,} day fetch(es) failed; first was "
            f"{failures[0][0]} {failures[0][1]}: {failures[0][2][:200]}",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_enrich_v4_statics(args: argparse.Namespace) -> int:
    with exclusive_job(RAW_MUTATION_LOCK, job="raw market-data fetch or enrichment"):
        return _enrich_v4_statics(args)


def _enrich_v4_statics(args: argparse.Namespace) -> int:
    start, end = effective_range("uniswap_v4", args.start, args.end)
    days = iter_days(start, end)
    if args.max_days:
        days = days[: args.max_days]
    failures: list[tuple[str, str]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=bounded_workers(args.workers)) as pool:
        futures = {pool.submit(enrich_v4_statics_day, day): day for day in days}
        for future in as_completed(futures):
            day = futures[future]
            try:
                print(json.dumps(future.result(), sort_keys=True), flush=True)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                failures.append((day.isoformat(), error))
                print(json.dumps({"day": day.isoformat(), "error": error[:500]}), flush=True)
            done += 1
            if done % 50 == 0 or done == len(days):
                print(f"# uniswap_v4 statics: {done}/{len(days)} days", flush=True)
    if failures:
        print(
            f"error: {len(failures):,} v4 static-enrichment day(s) failed; first was "
            f"{failures[0][0]}: {failures[0][1][:200]}",
            file=sys.stderr,
        )
        return 2
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
    sub.choices["fetch"].add_argument(
        "--days-file",
        type=Path,
        help="Fetch only the ISO dates listed in this file; The Graph sources only.",
    )
    sub.choices["fetch"].add_argument("--dune-sleep", type=float, default=2.0, help="Seconds to sleep between day-sized Dune gap fetches.")
    sub.choices["fetch"].add_argument("--max-retries", type=int, default=50, help="Per-day retries for transient provider/indexer errors in --gaps-only mode.")
    enrich = sub.add_parser(
        "enrich-v4-statics",
        help="merge quote statics into canonical signed v4 swaps by exact record ID",
    )
    enrich.add_argument("--start", default="genesis", help="'genesis' or YYYY-MM-DD")
    enrich.add_argument("--end", default=None, help="exclusive YYYY-MM-DD")
    enrich.add_argument("--workers", type=int, default=5)
    enrich.add_argument("--max-days", type=int, default=0)
    enrich.set_defaults(func=cmd_enrich_v4_statics)
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
