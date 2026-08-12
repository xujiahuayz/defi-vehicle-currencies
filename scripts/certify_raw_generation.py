#!/usr/bin/env python3
"""Scan and retro-certify the installed consumer-required raw generation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.fetch.dune import fetch_dune_month
from ddvc.fetch.raw import (
    fetch_source_day,
    frozen_graph_head,
    promote_source_day,
    query_chunk_policy,
)
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import get_source
from ddvc.raw_certification import (
    ADJUDICATION_ARTIFACT_POLICY,
    ADJUDICATION_EVIDENCE_POLICY,
    COMPARISON_ENGINE_CONTRACT,
    FIELD_CONTRACTS,
    FETCH_CODE_ARTIFACT_POLICY,
    GENERATION_EVIDENCE_POLICY,
    LOCAL_SCAN_POLICY,
    QUERY_ARTIFACT_POLICY,
    RawPartition,
    active_consumer_streams,
    comparison_contract,
    comparison_contract_identity,
    comparison_counts,
    comparison_selection_frame,
    generation_identity,
    require_exact_partition_perimeter,
    required_partitions,
    scan_installed_generation,
    validate_comparison_rows,
    verify_retro_certificate,
    write_normalized_legacy_ledger,
    write_local_scan_certificate,
    write_local_scan_ledger,
    write_retro_certificate,
)
from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job


EVIDENCE_PREPARATION_POLICY = "legacy-raw-evidence-preparation-v1"
REFERENCE_ACQUISITION_POLICY = "fresh-reference-acquisition-plan-v1"


def selected_required_partitions(
    sources: list[str] | None,
    streams: list[str] | None,
) -> tuple[RawPartition, ...]:
    """Resolve an exact active subset for a repeatable local integrity scan."""

    active = active_consumer_streams()
    selected_sources = set(sources or active)
    if unknown_sources := sorted(selected_sources.difference(active)):
        raise ValueError(
            f"unknown or inactive raw source(s): {', '.join(unknown_sources)}"
        )
    selected_streams = set(streams or ())
    if selected_streams and not sources:
        raise ValueError("--stream requires at least one --source")
    required = {
        source: frozenset(selected_streams) if selected_streams else active[source]
        for source in sorted(selected_sources)
    }
    if unavailable := sorted(
        f"{source}/{stream}"
        for source, source_streams in required.items()
        for stream in source_streams.difference(active[source])
    ):
        raise ValueError(
            f"source does not expose active stream(s): {', '.join(unavailable)}"
        )
    return required_partitions(required=required)


def publish_local_scan(
    ledger_output: Path,
    certificate_output: Path | None,
    local: list[dict[str, object]],
    partitions: tuple[RawPartition, ...],
) -> dict[str, object]:
    """Publish one diagnostic ledger and a certificate only for an exact passing scan."""

    failures = [item for item in local if item.get("local_pass") is not True]
    if certificate_output is None or failures:
        summary = write_local_scan_ledger(ledger_output, local)
        if certificate_output is not None:
            certificate_output.unlink(missing_ok=True)
        return summary
    certificate = write_local_scan_certificate(
        certificate_output,
        local,
        expected_partitions=partitions,
        ledger_path=ledger_output,
    )
    return {
        "policy": LOCAL_SCAN_POLICY,
        "partitions": len(local),
        "passed": len(local),
        "failed": 0,
        "ledger": ledger_output.name,
        "ledger_sha256": certificate["partition_ledger_sha256"],
        "failed_source_streams": [],
        "certificate": certificate["certificate_sha256"],
    }


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row is not an object: {path}")
            rows.append(row)
    return rows


def write_json(path: Path, payload: object) -> None:
    with atomic_output(path) as temporary:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def fetch_code_artifact(source: str, stream: str, backend: str) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    paths = [
        "scripts/fetch_raw_market_data.py",
        "src/ddvc/fetch/raw.py",
        f"src/ddvc/fetch/{'dune' if backend == 'dune' else 'graph'}.py",
    ]
    blobs = []
    for path in sorted(paths):
        content = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout
        if (repository / path).read_bytes() != content:
            raise RuntimeError(
                f"reference acquisition code is not committed at {commit}: {path}"
            )
        blobs.append({"path": path, "blob_sha256": hashlib.sha256(content).hexdigest()})
    return {
        "policy": FETCH_CODE_ARTIFACT_POLICY,
        "source": source,
        "stream": stream,
        "repository_commit_sha": commit,
        "tracked_blobs": blobs,
    }


def prepare_evidence(data_root: Path, local_ledger: Path, output_dir: Path) -> dict[str, object]:
    """Build local ledgers and a plan; this function does not acquire fresh references."""

    local = read_jsonl(local_ledger)
    require_exact_partition_perimeter(local)
    failures = [row for row in local if row.get("local_pass") is not True]
    if failures:
        raise ValueError(
            f"local ledger has {len(failures)} failures; repair or explicitly adjudicate them before reference acquisition"
        )
    by_pair: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in local:
        key = (str(row.get("source")), str(row.get("stream")))
        by_pair.setdefault(key, []).append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundled_local = output_dir / "local-scan.jsonl"
    with atomic_output(bundled_local) as temporary:
        temporary.write_bytes(local_ledger.read_bytes())
    (output_dir / "legacy_ledgers").mkdir(exist_ok=True)
    (output_dir / "reference_ledgers").mkdir(exist_ok=True)
    generations: list[dict[str, object]] = []
    acquisition: list[dict[str, object]] = []
    for (source, stream), partitions in sorted(by_pair.items()):
        frame, strata = comparison_selection_frame(partitions)
        sample_days = sorted(strata.values())
        stem = f"{source}--{stream}"
        legacy_relative = Path("legacy_ledgers") / f"{stem}.jsonl"
        write_normalized_legacy_ledger(
            data_root,
            source,
            stream,
            sample_days,
            output_dir / legacy_relative,
        )
        generation = {
            "source": source,
            "stream": stream,
            "generation_kind": (
                "legacy_unfrozen_dune" if source == "fluid" else "legacy_unfrozen_graph"
            ),
            "provenance_status": (
                "legacy_dune_code_or_query_unavailable"
                if source == "fluid"
                else "legacy_graph_code_or_query_unavailable"
            ),
            "fetch_code_identity_sha256": None,
            "query_generation_identity_sha256": None,
        }
        generation["generation_identity_sha256"] = generation_identity(generation)
        generations.append(generation)
        field_contract = FIELD_CONTRACTS[(source, stream)]
        retained_contract = comparison_contract(source, stream)
        source_record = get_source(source)
        chunk_policy = "day_sql_v1"
        if source_record.backend == "thegraph":
            entity = next(
                entity
                for entity in get_schema(source_record.schema).entities
                if entity.stream == stream
            )
            chunk_policy = query_chunk_policy(entity)
        acquisition.append(
            {
                "source": source,
                "stream": stream,
                "backend": "dune" if source == "fluid" else "thegraph",
                "sample_days": sample_days,
                "strata": strata,
                "selection_frame": frame,
                "legacy_ledger": str(legacy_relative),
                "legacy_ledger_sha256": file_sha256(output_dir / legacy_relative),
                "reference_ledger": str(
                    Path("reference_ledgers") / f"{stem}.jsonl"
                ),
                "identity_fields": list(retained_contract.identity_fields),
                "quantity_fields": list(retained_contract.quantity_fields),
                "timestamp_field": field_contract.timestamp_path,
                "day_bounds": "timestamp >= day_utc and timestamp < next_day_utc",
                "pagination_order_field": (
                    "block_time,evt_index"
                    if source_record.backend == "dune"
                    else "id"
                ),
                "chunk_policy": chunk_policy,
                "page_size": 1000,
                "max_pages_per_day": 10_000,
                "max_concurrency": 4,
                "max_retries_per_page": 5,
                "required_output_schema": ["day", "identity", "quantities"],
                "comparison_contract_sha256": comparison_contract_identity(
                    source, stream
                ),
            }
        )
    generation_payload = {
        "policy": GENERATION_EVIDENCE_POLICY,
        "generations": generations,
    }
    plan = {
        "policy": REFERENCE_ACQUISITION_POLICY,
        "preparation_policy": EVIDENCE_PREPARATION_POLICY,
        "local_ledger": bundled_local.name,
        "local_ledger_sha256": file_sha256(bundled_local),
        "comparisons": acquisition,
    }
    write_json(output_dir / "generation.json", generation_payload)
    write_json(output_dir / "fresh-reference-plan.json", plan)
    return {
        "status": "reference_acquisition_required",
        "pairs": len(by_pair),
        "sample_days": sum(len(item["sample_days"]) for item in acquisition),
        "generation_evidence": "generation.json",
        "reference_plan": "fresh-reference-plan.json",
    }


def acquire_references(
    output_dir: Path,
    *,
    scratch_root: Path,
    workers: int,
) -> dict[str, object]:
    if scratch_root.resolve() == DATA_DIR.resolve() or scratch_root.resolve().is_relative_to(
        DATA_DIR.resolve()
    ) or not scratch_root.resolve().is_relative_to(output_dir.resolve()):
        raise ValueError("reference acquisition root must be isolated from canonical data")
    plan_path = output_dir / "fresh-reference-plan.json"
    plan = json.loads(plan_path.read_text())
    if plan.get("policy") != REFERENCE_ACQUISITION_POLICY:
        raise ValueError("reference acquisition plan policy mismatch")
    local_path = output_dir / str(plan.get("local_ledger") or "")
    if not local_path.is_file() or file_sha256(local_path) != plan.get(
        "local_ledger_sha256"
    ):
        raise ValueError("reference acquisition local ledger changed")
    local = read_jsonl(local_path)
    require_exact_partition_perimeter(local)
    by_pair: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in local:
        by_pair.setdefault((str(row["source"]), str(row["stream"])), []).append(row)
    expected_pairs = set(by_pair)
    planned_pairs = {
        (str(item.get("source")), str(item.get("stream")))
        for item in plan.get("comparisons") or []
    }
    if planned_pairs != expected_pairs:
        raise ValueError("reference acquisition plan perimeter changed")
    scratch_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for item in plan["comparisons"]:
        source_name = str(item["source"])
        stream = str(item["stream"])
        frame, strata = comparison_selection_frame(by_pair[(source_name, stream)])
        if item.get("selection_frame") != frame or item.get("strata") != strata:
            raise ValueError(f"reference selection changed: {source_name}/{stream}")
        source = get_source(source_name)
        days = [dt.datetime.strptime(day, "%Y%m%d").date() for day in item["sample_days"]]
        concurrency = min(
            bounded_workers(workers),
            int(item["max_concurrency"]),
            len(days),
        )
        if source.backend == "thegraph":
            head = frozen_graph_head(source)

            def fetch_day(day: dt.date) -> object:
                return fetch_source_day(
                    source,
                    day,
                    streams={stream},
                    skip_existing=False,
                    head_block_at_fetch=head,
                    data_root=scratch_root,
                    max_pages_per_chunk=int(item["max_pages_per_day"]),
                    max_transient_retries=int(item["max_retries_per_page"]),
                )

        elif source.backend == "dune":

            def fetch_day(day: dt.date) -> object:
                return fetch_dune_month(
                    source,
                    day,
                    day + dt.timedelta(days=1),
                    streams={stream},
                    skip_existing=False,
                    data_root=scratch_root,
                    max_result_pages=int(item["max_pages_per_day"]),
                    max_page_retries=int(item["max_retries_per_page"]),
                )

            concurrency = 1
        else:
            raise ValueError(f"unsupported reference backend: {source.backend}")
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {pool.submit(fetch_day, day): day for day in days}
            for future in as_completed(futures):
                future.result()
        reference_path = output_dir / str(item["reference_ledger"])
        write_normalized_legacy_ledger(
            scratch_root,
            source_name,
            stream,
            item["sample_days"],
            reference_path,
        )
        raw_artifacts: list[dict[str, str]] = []
        recorded_query_contracts: set[str] = set()
        backend = "dune" if source.backend == "dune" else "thegraph"
        for day in item["sample_days"]:
            for path in (
                scratch_root
                / "raw"
                / backend
                / source_name
                / f"{source_name}_{stream}_{day}.jsonl.gz",
                scratch_root
                / "raw"
                / backend
                / source_name
                / f"{source_name}_meta_{day}.json",
            ):
                if not path.is_file():
                    raise ValueError(
                        f"reference acquisition omitted provider evidence: {source_name}/{stream}/{day}"
                    )
                raw_artifacts.append(
                    {
                        "path": str(path.relative_to(output_dir)),
                        "sha256": file_sha256(path),
                    }
                )
                if path.suffix == ".json":
                    metadata = json.loads(path.read_text())
                    stream_metadata = (metadata.get("streams") or {}).get(stream) or {}
                    query_identity = stream_metadata.get("query_contract_sha256")
                    if not isinstance(query_identity, str) or len(query_identity) != 64:
                        raise ValueError(
                            f"reference acquisition lacks query identity: {source_name}/{stream}/{day}"
                        )
                    recorded_query_contracts.add(query_identity)
        code_payload = fetch_code_artifact(source_name, stream, source.backend)
        code_path = output_dir / "reference_evidence" / f"{source_name}--{stream}--code.json"
        code_path.parent.mkdir(exist_ok=True)
        write_json(code_path, code_payload)
        field_contract = FIELD_CONTRACTS[(source_name, stream)]
        selected_fields = sorted(
            set(field_contract.required_paths).union(
                *(set(group) for group in field_contract.required_any_paths)
            )
        )
        query_contract = {
            "backend": source.backend,
            "source": source_name,
            "stream": stream,
            "recorded_query_contracts": sorted(recorded_query_contracts),
            "sample_days": item["sample_days"],
        }
        query_payload = {
            "policy": QUERY_ARTIFACT_POLICY,
            "source": source_name,
            "stream": stream,
            "endpoint_family": backend,
            "entity": (
                next(
                    entity.entity
                    for entity in get_schema(source.schema).entities
                    if entity.stream == stream
                )
                if backend == "thegraph"
                else "dex.trades"
            ),
            "selected_fields": selected_fields,
            "bounds": {
                "field": field_contract.timestamp_path,
                "lower": "inclusive_utc_day",
                "upper": "exclusive_utc_day",
            },
            "pagination": {
                "chunk_policy": item["chunk_policy"],
                "direction": "ascending",
                "order_field": item["pagination_order_field"],
                "page_size": item["page_size"],
            },
            "query_contract": query_contract,
        }
        query_path = output_dir / "reference_evidence" / f"{source_name}--{stream}--query.json"
        write_json(query_path, query_payload)
        evidence_payload = {
            "policy": "fresh-reference-provider-evidence-v1",
            "source": source_name,
            "stream": stream,
            "backend": source.backend,
            "sample_days": item["sample_days"],
            "comparison_contract_sha256": item["comparison_contract_sha256"],
            "raw_artifacts": raw_artifacts,
            "reference_ledger": item["reference_ledger"],
            "reference_ledger_sha256": file_sha256(reference_path),
            "fetch_code_artifact": str(code_path.relative_to(output_dir)),
            "fetch_code_artifact_sha256": file_sha256(code_path),
            "query_artifact": str(query_path.relative_to(output_dir)),
            "query_artifact_sha256": file_sha256(query_path),
            "query_generation_identity_sha256": canonical_json_sha256(query_contract),
        }
        evidence_path = output_dir / "reference_evidence" / f"{source_name}--{stream}.json"
        evidence_path.parent.mkdir(exist_ok=True)
        write_json(evidence_path, evidence_payload)
        entries.append(
            {
                "source": source_name,
                "stream": stream,
                "evidence": str(evidence_path.relative_to(output_dir)),
                "evidence_sha256": file_sha256(evidence_path),
                "reference_ledger": item["reference_ledger"],
                "reference_ledger_sha256": file_sha256(reference_path),
            }
        )
    marker = {
        "policy": "fresh-reference-acquisition-v1",
        "plan_sha256": file_sha256(plan_path),
        "scratch_root": str(scratch_root.relative_to(output_dir)),
        "entries": sorted(entries, key=lambda item: (item["source"], item["stream"])),
    }
    write_json(output_dir / "reference-acquisition.json", marker)
    return {"pairs": len(entries), "status": "acquired"}


def finalize_evidence(output_dir: Path) -> dict[str, object]:
    plan_path = output_dir / "fresh-reference-plan.json"
    plan = json.loads(plan_path.read_text())
    acquisition_path = output_dir / "reference-acquisition.json"
    if not acquisition_path.is_file():
        raise ValueError("fresh reference acquisition marker is missing")
    acquisition = json.loads(acquisition_path.read_text())
    if (
        acquisition.get("policy") != "fresh-reference-acquisition-v1"
        or acquisition.get("plan_sha256") != file_sha256(plan_path)
    ):
        raise ValueError("fresh reference acquisition marker is stale")
    acquired = {
        (entry["source"], entry["stream"]): entry
        for entry in acquisition.get("entries") or []
    }
    generation_payload = json.loads((output_dir / "generation.json").read_text())
    generations = {
        (entry["source"], entry["stream"]): entry
        for entry in generation_payload["generations"]
    }
    artifact_dir = output_dir / "adjudications"
    artifact_dir.mkdir(exist_ok=True)
    manifests: list[dict[str, object]] = []
    for item in plan["comparisons"]:
        source, stream = item["source"], item["stream"]
        acquisition_entry = acquired.get((source, stream))
        if acquisition_entry is None:
            raise ValueError(f"fresh reference acquisition is partial: {source}/{stream}")
        evidence_path = output_dir / acquisition_entry["evidence"]
        if (
            not evidence_path.is_file()
            or file_sha256(evidence_path) != acquisition_entry["evidence_sha256"]
        ):
            raise ValueError(f"fresh reference evidence changed: {source}/{stream}")
        provider_evidence = json.loads(evidence_path.read_text())
        for retained in provider_evidence.get("raw_artifacts") or []:
            retained_path = output_dir / retained["path"]
            if not retained_path.is_file() or file_sha256(retained_path) != retained["sha256"]:
                raise ValueError(f"fresh provider response changed: {source}/{stream}")
        legacy_path = output_dir / item["legacy_ledger"]
        reference_path = output_dir / item["reference_ledger"]
        if not reference_path.is_file():
            raise ValueError(f"fresh reference ledger is missing: {source}/{stream}")
        legacy_rows = read_jsonl(legacy_path)
        reference_rows = read_jsonl(reference_path)
        validate_comparison_rows((*legacy_rows, *reference_rows), source, stream)
        counts = comparison_counts(legacy_rows, reference_rows)
        has_exceptions = any(
            counts[field]
            for field in (
                "missing_rows",
                "extra_rows",
                "duplicate_rows",
                "quantity_mismatch_rows",
            )
        )
        generation = generations[(source, stream)]
        artifact = {
            "policy": ADJUDICATION_ARTIFACT_POLICY,
            "kind": "fresh_stratified_comparison",
            "source": source,
            "stream": stream,
            "generation_identity_sha256": generation["generation_identity_sha256"],
            "status": "passed" if not has_exceptions and counts["compared_rows"] else "failed",
            "zero_exceptions": not has_exceptions,
            "sample_days": item["sample_days"],
            "strata": item["strata"],
            "selection_frame": item["selection_frame"],
            **counts,
            "comparison_engine_identity_sha256": canonical_json_sha256(
                COMPARISON_ENGINE_CONTRACT
            ),
            "comparison_contract_sha256": item["comparison_contract_sha256"],
            "identity_fields": item["identity_fields"],
            "quantity_fields": item["quantity_fields"],
            "legacy_ledger": item["legacy_ledger"],
            "legacy_ledger_sha256": file_sha256(legacy_path),
            "reference_ledger": item["reference_ledger"],
            "reference_ledger_sha256": file_sha256(reference_path),
            "reference_evidence": acquisition_entry["evidence"],
            "reference_evidence_sha256": acquisition_entry["evidence_sha256"],
        }
        artifact_path = artifact_dir / f"{source}--{stream}.json"
        write_json(artifact_path, artifact)
        manifests.append(
            {
                key: value
                for key, value in artifact.items()
                if key != "policy"
            }
            | {
                "artifact": str(artifact_path.relative_to(output_dir)),
                "artifact_sha256": file_sha256(artifact_path),
            }
        )
    adjudication = {
        "policy": ADJUDICATION_EVIDENCE_POLICY,
        "evidence": manifests,
    }
    write_json(output_dir / "adjudication.json", adjudication)
    return {
        "pairs": len(manifests),
        "passed": sum(item["status"] == "passed" for item in manifests),
        "failed": sum(item["status"] != "passed" for item in manifests),
        "adjudication_evidence": "adjudication.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan")
    scan.add_argument("--data-root", type=Path, default=DATA_DIR)
    scan.add_argument("--work-dir", type=Path, required=True)
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--generation-evidence", type=Path, required=True)
    scan.add_argument("--adjudication-evidence", type=Path, required=True)
    scan.add_argument("--workers", type=int, default=4)
    local = subparsers.add_parser("local-scan")
    local.add_argument("--data-root", type=Path, default=DATA_DIR)
    local.add_argument("--work-dir", type=Path, required=True)
    local.add_argument("--output", type=Path, required=True)
    local.add_argument("--certificate-output", type=Path)
    local.add_argument("--source", action="append")
    local.add_argument("--stream", action="append")
    local.add_argument("--workers", type=int, default=4)
    verify = subparsers.add_parser("verify")
    verify.add_argument("certificate", type=Path)
    verify.add_argument("--data-root", type=Path, default=DATA_DIR)
    prepare = subparsers.add_parser(
        "prepare-evidence",
        help="build local comparison ledgers and a bounded plan; does not fetch references",
    )
    prepare.add_argument("--data-root", type=Path, default=DATA_DIR)
    prepare.add_argument("--local-ledger", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    finalize = subparsers.add_parser(
        "finalize-evidence",
        help="validate separately acquired reference ledgers and build adjudication evidence",
    )
    finalize.add_argument("--output-dir", type=Path, required=True)
    acquire = subparsers.add_parser(
        "acquire-reference",
        help="fetch selected fresh references into an isolated retained evidence root",
    )
    acquire.add_argument("--output-dir", type=Path, required=True)
    acquire.add_argument("--scratch-root", type=Path)
    acquire.add_argument("--workers", type=int, default=4)
    promote = subparsers.add_parser(
        "promote-source-day",
        help="promote fully acquired source-day candidates and commit their sidecar last",
    )
    promote.add_argument("--source", required=True)
    promote.add_argument("--day", required=True)
    promote.add_argument("--stream", action="append", required=True)
    promote.add_argument("--candidate-root", type=Path, required=True)
    promote.add_argument("--evidence-root", type=Path, required=True)
    promote.add_argument("--data-root", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    if args.command == "verify":
        payload = verify_retro_certificate(args.certificate, data_root=args.data_root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "prepare-evidence":
        payload = prepare_evidence(args.data_root, args.local_ledger, args.output_dir)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "finalize-evidence":
        payload = finalize_evidence(args.output_dir)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return int(payload["failed"] != 0)
    if args.command == "acquire-reference":
        scratch_root = args.scratch_root or args.output_dir / "reference_raw"
        payload = acquire_references(
            args.output_dir,
            scratch_root=scratch_root,
            workers=args.workers,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "promote-source-day":
        with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw source-day promotion"):
            payload = promote_source_day(
                args.source,
                dt.datetime.strptime(args.day, "%Y%m%d").date(),
                set(args.stream),
                candidate_root=args.candidate_root,
                evidence_root=args.evidence_root,
                data_root=args.data_root,
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    try:
        partitions = (
            selected_required_partitions(args.source, args.stream)
            if args.command == "local-scan"
            else required_partitions()
        )
    except ValueError as exc:
        parser.error(str(exc))
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw generation certification"):
        local = scan_installed_generation(
            args.data_root,
            args.work_dir,
            workers=bounded_workers(args.workers),
            partitions=partitions,
        )
        if args.command == "local-scan":
            summary = publish_local_scan(
                args.output,
                args.certificate_output,
                local,
                partitions,
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return int(summary["failed"] != 0)
        certificate = write_retro_certificate(
            args.output,
            local,
            generation_evidence=args.generation_evidence,
            adjudication_evidence=args.adjudication_evidence,
        )
    print(json.dumps(certificate, indent=2, sort_keys=True))
    return int(certificate["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
