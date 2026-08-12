#!/usr/bin/env python3
"""Forecast the frozen Graph acquisition before any full backfill is launched."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import socket
import statistics
from typing import Any

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import GRAPH_ACQUISITION_FORECAST, GRAPH_ACQUISITION_FREEZE, GRAPH_BLOCK_FIELDS, GRAPH_CANARY_CURRENT, GRAPH_CANARY_FINAL, GRAPH_ROOT_POPULATION, GRAPH_THIN_CONSUMER_AUDIT, sha256_file
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.fetch.thin_consumer_audit import validate_thin_consumer_audit_envelope
from ddvc.paths import PRIMARY_REPO_ROOT, RAW_MARKET_DATA_LOCK
from ddvc.runtime import atomic_output, exclusive_job


FINAL_CANARY = GRAPH_CANARY_FINAL
CURRENT_CANARY = GRAPH_CANARY_CURRENT
ROOT_POPULATION = GRAPH_ROOT_POPULATION
FREEZE = GRAPH_ACQUISITION_FREEZE
THIN_AUDIT = GRAPH_THIN_CONSUMER_AUDIT
DEFAULT_RAW_ROOT = PRIMARY_REPO_ROOT / "data" / "raw" / "thegraph"
DEFAULT_OUTPUT = GRAPH_ACQUISITION_FORECAST
TEMPORAL_MODES = frozenset({"historical_event_full", "historical_snapshot_full"})
BLOCK_ORDER_FIELDS = frozenset(GRAPH_BLOCK_FIELDS)
PAGE_SIZE = 1000
CAPPED_STATIC_STRESS_ROWS = 10_000_000
DENSE_DAY_STRESS_ROWS = 10_000


def _large_head(stream: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            sample
            for sample in stream["samples"]
            if sample["status"] == "ok"
            and sample["epoch"] == "head"
            and sample["requested_rows"] == PAGE_SIZE
        ),
        None,
    )


def _source_days(source_name: str) -> int:
    end = datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date()
    return max(1, (end - DEX_SOURCES[source_name].genesis).days + 1)


def _temporal_row_forecast(
    source: dict[str, Any], stream: dict[str, Any]
) -> tuple[int, int, int] | None:
    rates = []
    for sample in stream["samples"]:
        lower = sample.get("order_value_min")
        upper = sample.get("order_value_max")
        rows = sample.get("returned_rows")
        if (
            sample.get("status") == "ok"
            and sample.get("requested_rows") == 100
            and isinstance(rows, int)
            and rows >= 2
            and isinstance(lower, int)
            and isinstance(upper, int)
            and upper > lower
        ):
            rates.append(rows / (upper - lower + 1))
    if not rates:
        return None
    if stream["order_by"] in BLOCK_ORDER_FIELDS:
        perimeter = int(source["head_block"]) - int(source["genesis_block"]) + 1
    else:
        perimeter = _source_days(str(source["source"])) * 86_400
    low = math.ceil(min(rates) * perimeter)
    central = math.ceil(statistics.median(rates) * perimeter)
    high = math.ceil(max(rates) * perimeter * 2)
    return low, central, high


def _raw_inventory(root: Path) -> tuple[int, int, int, int, dict[str, dict[str, int]]]:
    records: dict[str, dict[str, int]] = {}
    for source_root in sorted(path for path in root.iterdir() if path.is_dir()):
        files = 0
        payload_files = 0
        logical_size = 0
        entry_physical_size = 0
        for path in source_root.rglob("*"):
            if path.is_file():
                files += 1
                payload_files += int(path.name.endswith(".jsonl.gz"))
                logical_size += path.stat().st_size
                entry_physical_size += path.lstat().st_blocks * 512
        records[source_root.name] = {
            "files": files,
            "payload_files": payload_files,
            "logical_bytes": logical_size,
            "entry_physical_bytes": entry_physical_size,
        }
    return (
        sum(record["files"] for record in records.values()),
        sum(record["payload_files"] for record in records.values()),
        sum(record["logical_bytes"] for record in records.values()),
        sum(record["entry_physical_bytes"] for record in records.values()),
        records,
    )


def _stream_map(payload: dict[str, Any], *, active_only: bool = False) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(source["source"]), str(stream["stream"])): stream
        for source in payload["sources"]
        for stream in source["streams"]
        if not active_only or stream["mode"] == "active_stream"
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-canary", type=Path, default=FINAL_CANARY)
    parser.add_argument("--current-canary", type=Path, default=CURRENT_CANARY)
    parser.add_argument("--root-population", type=Path, default=ROOT_POPULATION)
    parser.add_argument("--freeze", type=Path, default=FREEZE)
    parser.add_argument("--thin-audit", type=Path, default=THIN_AUDIT)
    parser.add_argument("--existing-raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--available-disk-bytes", type=int)
    parser.add_argument("--available-disk-host")
    parser.add_argument("--available-disk-path", type=Path)
    parser.add_argument("--pagination-benchmark", type=Path, help="sustained multi-page/rate-limit benchmark evidence; without it runtime remains unbounded")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _build_and_publish_forecast(args: argparse.Namespace) -> int:
    """Read the installed raw inventory and publish its forecast under one lease."""

    if args.available_disk_bytes is not None and (
        not args.available_disk_host or args.available_disk_path is None
    ):
        raise ValueError("a disk-space override requires its measured host and path")
    final = json.loads(args.final_canary.read_text(encoding="utf-8"))
    current = json.loads(args.current_canary.read_text(encoding="utf-8"))
    population = json.loads(args.root_population.read_text(encoding="utf-8"))
    freeze_hash = sha256_file(args.freeze)
    thin_audit = validate_thin_consumer_audit_envelope(args.thin_audit)
    authorization = thin_audit["authorized_graph_acquisition"]
    if int(authorization["stream_count"]):
        raise ValueError("incremental Graph acquisition execution is disabled; a nonzero registry requires a reviewed executor and measured budget")
    for name, payload in (("final canary", final), ("current canary", current), ("root population", population)):
        if payload.get("freeze_sha256") != freeze_hash:
            raise ValueError(f"{name} is not bound to the current freeze")
    for key in ("schema_inventory_sha256", "active_manifest_sha256", "new_manifest_sha256"):
        values = {final.get(key), current.get(key), population.get(key)}
        if len(values) != 1:
            raise ValueError(f"Graph forecast inputs disagree on {key}")
    current_files, current_payload_files, current_bytes, current_entry_physical_bytes, raw_sources = _raw_inventory(args.existing_raw_root)
    proposed_streams = _stream_map(final)
    current_streams = _stream_map(current, active_only=True)
    source_records = []
    total_active = 0
    total_active_calls_low = 0
    total_active_calls_central = 0
    total_active_calls_stress = 0
    total_new_low = 0
    total_new_central = 0
    total_new_high = 0
    total_minimum_calls = 0
    total_central_calls = 0
    total_stress_calls = 0
    for source in final["sources"]:
        source_name = str(source["source"])
        active = [stream for stream in source["streams"] if stream["mode"] == "active_stream"]
        proposed_sample_bytes = sum((_large_head(stream) or {}).get("gzip_bytes", 0) for stream in active)
        current_sample_bytes = sum(
            (_large_head(current_streams[(source_name, stream["stream"])]) or {}).get("gzip_bytes", 0)
            for stream in active
        )
        payload_factor = proposed_sample_bytes / current_sample_bytes
        installed = raw_sources.get(source_name, {"logical_bytes": 0, "entry_physical_bytes": 0, "files": 0, "payload_files": 0})
        active_bytes = math.ceil(int(installed["logical_bytes"]) * payload_factor)
        total_active += active_bytes
        current_bytes_per_row = sorted(
            sample["gzip_bytes"] / sample["returned_rows"]
            for stream in active
            for sample in [_large_head(current_streams[(source_name, stream["stream"])])]
            if sample is not None and sample["returned_rows"]
        )
        installed_bytes = int(installed["logical_bytes"])
        installed_payloads = int(installed["payload_files"])
        active_calls_low = max(
            installed_payloads,
            math.ceil(installed_bytes / max(current_bytes_per_row) / PAGE_SIZE),
        )
        active_calls_central = max(
            installed_payloads,
            math.ceil(installed_bytes / statistics.median(current_bytes_per_row) / PAGE_SIZE),
        )
        active_calls_stress = max(
            installed_payloads,
            math.ceil(installed_bytes / min(current_bytes_per_row) / PAGE_SIZE),
        )
        total_active_calls_low += active_calls_low
        total_active_calls_central += active_calls_central
        total_active_calls_stress += active_calls_stress
        new_records = []
        for stream in source["streams"]:
            if stream["mode"] == "active_stream":
                continue
            head = _large_head(stream)
            rows: tuple[int, int, int | None]
            reason: str
            if stream.get("quality_action") == "provider_archive_unavailable_quarantined":
                rows = (0, 0, 0)
                reason = "provider_archive_unavailable_quarantined_no_payload"
            elif stream["mode"] in TEMPORAL_MODES and stream["order_by"] != "id":
                forecast = _temporal_row_forecast(source, stream)
                if forecast is None:
                    days = _source_days(source_name)
                    observed = int((head or {}).get("returned_rows", 0))
                    rows = (
                        observed,
                        observed * days,
                        DENSE_DAY_STRESS_ROWS * days,
                    )
                    reason = "same_period_head_cap_with_ten_thousand_rows_per_day_stress_ceiling"
                else:
                    rows = forecast
                    reason = "early_middle_head_local_density_with_two_times_observed_peak"
            elif stream["mode"] == "block_pinned_configuration":
                observed = int((head or {}).get("returned_rows", 0))
                days = _source_days(source_name)
                rows = (
                    observed * days,
                    observed * days,
                    (DENSE_DAY_STRESS_ROWS if observed == PAGE_SIZE else observed) * days,
                )
                reason = "daily_block_checkpoint_head_population_with_dense_day_stress_ceiling"
            elif stream["mode"] == "head_validation_only":
                rows = (0, 0, 0)
                reason = "canary_only_never_backfill"
            else:
                observed = int((head or {}).get("returned_rows", 0))
                rows = (
                    observed,
                    observed,
                    CAPPED_STATIC_STRESS_ROWS if observed == PAGE_SIZE else observed,
                )
                reason = "frozen_head_population_with_ten_million_row_stress_ceiling"
            bytes_per_row = float(stream["summary"].get("gzip_bytes_per_row_max") or 0)
            low_bytes = math.ceil(rows[0] * bytes_per_row)
            central_bytes = math.ceil(rows[1] * bytes_per_row)
            high_bytes = math.ceil(rows[2] * bytes_per_row)
            days = _source_days(source_name) if stream["mode"] in TEMPORAL_MODES | {"block_pinned_configuration"} else 1
            minimum_calls = max(days, math.ceil(rows[0] / PAGE_SIZE)) if rows[0] else 0
            stress_calls = max(days, math.ceil(rows[2] / PAGE_SIZE)) if rows[2] else 0
            central_calls = max(days, math.ceil(rows[1] / PAGE_SIZE)) if rows[1] else 0
            total_new_low += low_bytes
            total_new_central += central_bytes
            total_minimum_calls += minimum_calls
            total_new_high += high_bytes
            total_stress_calls += stress_calls
            total_central_calls += central_calls
            new_records.append(
                {
                    "stream": stream["stream"],
                    "mode": stream["mode"],
                    "order_by": stream["order_by"],
                    "row_scenarios_not_bounds": {"low": rows[0], "central": rows[1], "high": rows[2]},
                    "compressed_byte_scenarios_not_bounds": {"low": low_bytes, "central": central_bytes, "high": high_bytes},
                    "minimum_calls": minimum_calls,
                    "central_calls": central_calls,
                    "stress_calls": stress_calls,
                    "basis": reason,
                }
            )
        source_records.append(
            {
                "source": source_name,
                "active_payload_factor": round(payload_factor, 6),
                "installed_active_logical_bytes": installed["logical_bytes"],
                "forecast_active_bytes": active_bytes,
                "active_call_forecast": {
                    "low": active_calls_low,
                    "central": active_calls_central,
                    "stress": active_calls_stress,
                },
                "new_streams": new_records,
            }
        )
    canary_streams = [stream for source in final["sources"] for stream in source["streams"]]
    alignment_compared = sum(stream["summary"]["alignment_comparisons"] for stream in canary_streams)
    alignment_failed = sum(stream["summary"]["alignment_failure_comparisons"] for stream in canary_streams)
    alignment_failure_rows = sum(stream["summary"]["alignment_failure_rows"] for stream in canary_streams)
    unresolved_quality = [
        f"{source['source']}/{stream['stream']}"
        for source in final["sources"]
        for stream in source["streams"]
        if stream.get("quality_action") == "unresolved_query_failure"
    ]
    provider_quarantines = [
        f"{source['source']}/{stream['stream']}"
        for source in final["sources"]
        for stream in source["streams"]
        if stream.get("quality_action") == "provider_archive_unavailable_quarantined"
    ]
    unresolved_root_errors = int(population.get("summary", {}).get("errors", 0))
    root_provider_quarantines = int(
        population.get("summary", {}).get("provider_archive_unavailable_quarantined", 0)
    )
    generation_high = total_active + total_new_high
    peak_disk = current_bytes + math.ceil(generation_high * 1.1)
    stat = os.statvfs(args.existing_raw_root)
    observed_available = stat.f_bavail * stat.f_frsize
    available_disk = args.available_disk_bytes if args.available_disk_bytes is not None else observed_available
    disk_headroom_ratio = (
        available_disk / peak_disk
        if peak_disk
        else None
    )
    benchmark = None
    if args.pagination_benchmark:
        benchmark = json.loads(args.pagination_benchmark.read_text(encoding="utf-8"))
        if (
            benchmark.get("kind") != "graph_sustained_pagination_benchmark"
            or benchmark.get("freeze_sha256") != freeze_hash
            or int(benchmark.get("completed_calls", 0)) < 100
            or int(benchmark.get("multi_page_streams", 0)) < 1
            or not isinstance(benchmark.get("rate_limit_events"), int)
            or float(benchmark.get("sustained_calls_per_second", 0)) <= 0
        ):
            raise ValueError("pagination benchmark is not sustained, multi-page, rate-limit evidence")
    launch_decision = "inventory_validated_consumer_selection_required"
    elapsed = sorted(
        float(sample["elapsed_seconds"])
        for source in final["sources"]
        for stream in source["streams"]
        for sample in stream["samples"]
        if sample["status"] == "ok"
    )
    percentile = lambda proportion: elapsed[min(len(elapsed) - 1, int(proportion * len(elapsed)))]
    total_call_forecast = {
        "low": total_active_calls_low + total_minimum_calls,
        "central": total_active_calls_central + total_central_calls,
        "stress": total_active_calls_stress + total_stress_calls,
    }
    wall_hours = None
    if benchmark is not None:
        calls_per_second = float(benchmark["sustained_calls_per_second"])
        wall_hours = {
            "central_scenario": total_call_forecast["central"] / calls_per_second / 3600,
            "stress_scenario": total_call_forecast["stress"] / calls_per_second / 3600,
        }
    payload = {
        "schema_version": 2,
        "kind": "graph_acquisition_prelaunch_forecast",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_sample_end": RESEARCH_SAMPLE_END,
        "inputs": {
            "final_canary_sha256": sha256_file(args.final_canary),
            "current_canary_sha256": sha256_file(args.current_canary),
            "root_population_sha256": sha256_file(args.root_population),
            "freeze_sha256": freeze_hash,
            "thin_consumer_audit_sha256": thin_audit["audit_sha256"],
            "consumer_registry_sha256": thin_audit["consumer_registry_sha256"],
            "pagination_benchmark_sha256": sha256_file(args.pagination_benchmark) if args.pagination_benchmark else None,
        },
        "existing_raw": {
            "files": current_files,
            "payload_files": current_payload_files,
            "logical_bytes": current_bytes,
            "entry_physical_bytes": current_entry_physical_bytes,
            "measurement_note": "logical bytes follow symlink targets; entry physical bytes count only storage owned below this root",
            "sources": raw_sources,
        },
        "forecast": {
            "forecast_class": "whole_inventory_engineering_scenarios_not_an_acquisition_plan",
            "authorized_fetch": {**authorization, "bytes": 0, "graph_calls": 0},
            "selection_policy": "the reviewed registry authorizes no incremental stream; adding one requires a reviewed executor and measured budget",
            "active_bytes": total_active,
            "new_byte_scenarios_not_bounds": {"low": total_new_low, "central": total_new_central, "high": total_new_high},
            "generation_byte_scenarios_not_bounds": {
                "low": total_active + total_new_low,
                "central": total_active + total_new_central,
                "high": generation_high,
            },
            "peak_disk_bytes_with_rollback_and_ten_percent_staging_margin": peak_disk,
            "available_disk_bytes": available_disk,
            "available_disk_evidence": {
                "host": args.available_disk_host or socket.gethostname(),
                "path": str((args.available_disk_path or args.existing_raw_root).resolve()),
                "observed_statvfs_available_bytes": observed_available,
                "override_bytes": args.available_disk_bytes,
                "inventory_observation_host": socket.gethostname(),
                "inventory_observation_path": str(args.existing_raw_root.resolve()),
            },
            "disk_headroom_ratio": disk_headroom_ratio,
            "minimum_graph_calls_new_streams": total_minimum_calls,
            "central_graph_calls_new_streams": total_central_calls,
            "stress_graph_calls_new_streams": total_stress_calls,
            "active_graph_call_forecast_from_installed_bytes_and_frozen_current_bytes_per_row": {
                "low": total_active_calls_low,
                "central": total_active_calls_central,
                "stress": total_active_calls_stress,
            },
            "total_graph_call_forecast": total_call_forecast,
            "runtime_estimate": {
                "status": "scenario_only" if benchmark is not None else "unbounded_without_sustained_pagination_benchmark",
                "wall_hours": wall_hours,
                "benchmark": benchmark,
                "canary_latency_not_used_as_eta_seconds": {"p50": percentile(0.5), "p90": percentile(0.9), "p95": percentile(0.95)},
            },
            "alignment_comparisons": alignment_compared,
            "alignment_failure_comparisons": alignment_failed,
            "alignment_failure_rows": alignment_failure_rows,
            "alignment_failure_comparison_rate": alignment_failed / alignment_compared if alignment_compared else None,
            "quality": {
                "unresolved_streams": unresolved_quality,
                "provider_archive_quarantined_streams": provider_quarantines,
                "unresolved_root_errors": unresolved_root_errors,
                "provider_archive_quarantined_roots": root_provider_quarantines,
            },
            "scenario_assumptions_not_empirical_bounds": {
                "capped_static_rows_per_stream": CAPPED_STATIC_STRESS_ROWS,
                "dense_rows_per_day_per_stream": DENSE_DAY_STRESS_ROWS,
                "temporal_observed_peak_multiplier": 2,
            },
        },
        "launch_decision": launch_decision,
        "sources": source_records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**payload["forecast"], "launch_decision": payload["launch_decision"]}, sort_keys=True))
    return 0


def main() -> int:
    args = _parse_args()
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="Graph acquisition inventory forecast",
    ):
        return _build_and_publish_forecast(args)


if __name__ == "__main__":
    raise SystemExit(main())
