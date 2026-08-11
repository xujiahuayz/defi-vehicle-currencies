"""Certified assembly and installed-generation release for exact V3 inventory events."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, wait
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import shutil

from ddvc.ethereum_logs import file_sha256, is_sha256, validate_anchored_log_evidence, validate_canonical_log_records
from ddvc.fetch.raw import write_jsonl_gz
from ddvc.provenance import portable_content_sha256
from ddvc.quoter import canonical_json_sha256
from ddvc.runtime import atomic_output, bounded_workers, interruptible_process_pool
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    INVENTORY_ASSEMBLY_CERTIFICATE_GENERATION,
    INVENTORY_ASSEMBLY_CERTIFICATE_SCHEMA_VERSION,
    INVENTORY_FIRST_CONSUMER_GENERATION,
    INVENTORY_FIRST_CONSUMER_SCHEMA_VERSION,
    INVENTORY_INITIALIZATION_CONSUMERS,
    INVENTORY_INSTALLED_GENERATION,
    INVENTORY_INSTALLED_GENERATION_SCHEMA_VERSION,
    _factory_manifest_identity,
    _inventory_chunk_files,
    _validate_inventory_destination_names,
    block_ranges,
    decode_inventory_log,
    inventory_chunk_paths,
    inventory_chunk_evidence_path,
    inventory_chunk_triplet,
    inventory_assembly_certificate_path,
    inventory_first_consuming_event_paths,
    inventory_installed_generation_marker_path,
    inventory_manifest_chunk_record,
    inventory_ordered_manifest_path,
    inventory_ordered_manifest_record,
    load_inventory_chunk_records,
    validate_inventory_shard_partition,
)

def _file_state(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def _exact_lower_hex(value: object, length: int) -> bool:
    text = str(value or "")
    return bool(
        len(text) == length
        and text.startswith("0x")
        and all(character in "0123456789abcdef" for character in text[2:])
    )


def _assembly_certificate_identity(record: dict[str, object]) -> str:
    return canonical_json_sha256(
        {
            key: value
            for key, value in record.items()
            if key != "certificate_identity_sha256"
        }
    )


def _validation_code_sha256() -> str:
    """Fingerprint only the functions that establish chunk admissibility."""

    owners = (
        load_inventory_chunk_records,
        decode_inventory_log,
        validate_anchored_log_evidence,
        validate_canonical_log_records,
        portable_content_sha256,
        _validate_assembly_certificate,
        _install_inventory_triplet,
        _certify_inventory_chunk_job,
    )
    unwrapped = [getattr(owner, "_mock_wraps", owner) for owner in owners]
    return canonical_json_sha256(
        {
            f"{owner.__module__}.{owner.__qualname__}": inspect.getsource(owner)
            for owner in unwrapped
        }
    )


def _validate_first_consumers(
    rows: object,
    *,
    lower: int,
    upper: int,
) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        raise ValueError("V3 inventory chunk certificate lacks first consumers")
    validated: list[dict[str, object]] = []
    prior_pool: str | None = None
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("V3 inventory first-consumer row is malformed")
        pool = str(item.get("pool") or "").lower()
        transaction_hash = str(item.get("transaction_hash") or "").lower()
        block = int(item.get("block_number", -1))
        transaction_index = int(item.get("transaction_index", -1))
        log_index = int(item.get("log_index", -1))
        kind = str(item.get("kind") or "")
        if (
            not _exact_lower_hex(pool, 42)
            or not _exact_lower_hex(transaction_hash, 66)
            or not lower <= block <= upper
            or transaction_index < 0
            or log_index < 0
            or kind not in INVENTORY_INITIALIZATION_CONSUMERS
            or (prior_pool is not None and pool <= prior_pool)
        ):
            raise ValueError("V3 inventory first-consumer row violates its contract")
        validated.append(
            {
                "pool": pool,
                "block_number": block,
                "transaction_index": transaction_index,
                "log_index": log_index,
                "transaction_hash": transaction_hash,
                "kind": kind,
            }
        )
        prior_pool = pool
    return validated


def _validate_assembly_certificate(
    record: object,
    *,
    lower: int,
    upper: int,
    validation_code_sha256: str,
    frozen_upper_identity_sha256: str,
) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ValueError("V3 inventory chunk certificate is not a JSON object")
    files = record.get("files")
    raw_by_event = record.get("raw_by_event")
    if (
        not isinstance(files, dict)
        or not isinstance(raw_by_event, dict)
    ):
        raise ValueError("V3 inventory chunk certificate lacks file or event identities")
    expected_files = {
        "raw": inventory_chunk_paths(lower, upper, Path("."))[0].name,
        "evidence": inventory_chunk_evidence_path(lower, upper, Path(".")).name,
        "marker": inventory_chunk_paths(lower, upper, Path("."))[1].name,
    }
    normalized_events = {
        name: int(raw_by_event.get(name, -1))
        for name in EVENT_TOPICS
    }
    first_consumers = _validate_first_consumers(
        record.get("first_consumers"),
        lower=lower,
        upper=upper,
    )
    valid_files = bool(
        set(files) == set(expected_files)
        and all(
            isinstance(files.get(role), dict)
            and files[role].get("name") == name
            and is_sha256(files[role].get("sha256"))
            and int(files[role].get("container_bytes", -1)) >= 0
            for role, name in expected_files.items()
        )
        and is_sha256(files["evidence"].get("portable_content_sha256"))
    )
    if (
        record.get("status") != "complete"
        or int(record.get("schema_version", -1))
        != INVENTORY_ASSEMBLY_CERTIFICATE_SCHEMA_VERSION
        or record.get("generation") != INVENTORY_ASSEMBLY_CERTIFICATE_GENERATION
        or int(record.get("lower", -1)) != lower
        or int(record.get("upper", -1)) != upper
        or record.get("validation_code_sha256") != validation_code_sha256
        or record.get("frozen_upper_identity_sha256")
        != frozen_upper_identity_sha256
        or not is_sha256(record.get("parquet_schema_sha256"))
        or set(raw_by_event) != set(EVENT_TOPICS)
        or any(count < 0 for count in normalized_events.values())
        or int(record.get("rows", -1)) != sum(normalized_events.values())
        or not valid_files
        or record.get("certificate_identity_sha256")
        != _assembly_certificate_identity(record)
    ):
        raise ValueError(f"V3 inventory chunk certificate is stale: {lower}-{upper}")
    return {
        **record,
        "raw_by_event": normalized_events,
        "first_consumers": first_consumers,
    }


def _load_assembly_certificate(
    path: Path,
    *,
    lower: int,
    upper: int,
    validation_code_sha256: str,
    frozen_upper_identity_sha256: str,
) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    if len(lines) != 1:
        raise ValueError("V3 inventory chunk certificate must contain one JSON row")
    return _validate_assembly_certificate(
        json.loads(lines[0]),
        lower=lower,
        upper=upper,
        validation_code_sha256=validation_code_sha256,
        frozen_upper_identity_sha256=frozen_upper_identity_sha256,
    )


def _source_file_hashes(
    triplet: tuple[Path, Path, Path],
) -> tuple[dict[str, str], dict[str, int]]:
    roles = ("raw", "evidence", "marker")
    before = {role: _file_state(path) for role, path in zip(roles, triplet, strict=True)}
    hashes = {role: file_sha256(path) for role, path in zip(roles, triplet, strict=True)}
    after = {role: _file_state(path) for role, path in zip(roles, triplet, strict=True)}
    if before != after:
        raise RuntimeError("V3 inventory source mutated while its chunk was hashed")
    return hashes, {role: state[0] for role, state in before.items()}


def _install_inventory_triplet(
    source_triplet: tuple[Path, Path, Path],
    destination_triplet: tuple[Path, Path, Path],
    expected_hashes: dict[str, str],
) -> int:
    copied_bytes = 0
    for role, source, target in zip(
        ("raw", "evidence", "marker"),
        source_triplet,
        destination_triplet,
        strict=True,
    ):
        if source.resolve() == target.resolve():
            continue
        if target.exists():
            if file_sha256(target) != expected_hashes[role]:
                raise FileExistsError(f"V3 inventory merge collision: {target.name}")
            continue
        source_state = _file_state(source)
        with atomic_output(target) as temporary:
            shutil.copyfile(source, temporary)
        if _file_state(source) != source_state:
            raise RuntimeError(f"V3 inventory source mutated during copy: {source.name}")
        if file_sha256(target) != expected_hashes[role]:
            raise OSError(f"V3 inventory copy verification failed: {target.name}")
        copied_bytes += target.stat().st_size
    return copied_bytes


def _certify_inventory_chunk_job(
    source_root: Path,
    destination: Path,
    lower: int,
    upper: int,
    frozen_upper: dict[str, object],
    validation_code_sha256: str,
) -> dict[str, object]:
    source_triplet = inventory_chunk_triplet(lower, upper, source_root)
    destination_triplet = inventory_chunk_triplet(lower, upper, destination)
    certificate_path = inventory_assembly_certificate_path(
        lower,
        upper,
        destination,
        validation_code_sha256,
    )
    reused = certificate_path.is_file()
    if reused:
        certificate = _load_assembly_certificate(
            certificate_path,
            lower=lower,
            upper=upper,
            validation_code_sha256=validation_code_sha256,
            frozen_upper_identity_sha256=str(
                frozen_upper["header_identity_sha256"]
            ),
        )
        hashes, sizes = _source_file_hashes(source_triplet)
        for role in ("raw", "evidence", "marker"):
            if (
                hashes[role] != certificate["files"][role]["sha256"]
                or sizes[role] != int(certificate["files"][role]["container_bytes"])
            ):
                raise ValueError(
                    f"V3 inventory source disagrees with its chunk certificate: {lower}-{upper}"
                )
    else:
        states_before = tuple(_file_state(path) for path in source_triplet)
        first_consumers: dict[str, dict[str, object]] = {}
        records, marker, schema = load_inventory_chunk_records(
            lower,
            upper,
            source_root,
            frozen_upper=frozen_upper,
            first_consumers=first_consumers,
        )
        evidence_portable_sha256 = portable_content_sha256(source_triplet[1])
        states_after = tuple(_file_state(path) for path in source_triplet)
        if states_before != states_after:
            raise RuntimeError(
                f"V3 inventory source mutated during semantic validation: {lower}-{upper}"
            )
        hashes = {
            "raw": str(marker["raw_sha256"]),
            "evidence": str(marker["rpc_evidence_sha256"]),
            "marker": file_sha256(source_triplet[2]),
        }
        sizes = {
            role: state[0]
            for role, state in zip(
                ("raw", "evidence", "marker"),
                states_after,
                strict=True,
            )
        }
        certificate = {
            "status": "complete",
            "schema_version": INVENTORY_ASSEMBLY_CERTIFICATE_SCHEMA_VERSION,
            "generation": INVENTORY_ASSEMBLY_CERTIFICATE_GENERATION,
            "lower": lower,
            "upper": upper,
            "validation_code_sha256": validation_code_sha256,
            "frozen_upper_identity_sha256": frozen_upper[
                "header_identity_sha256"
            ],
            "rows": len(records),
            "raw_by_event": {
                name: int(marker["raw_by_event"][name])
                for name in EVENT_TOPICS
            },
            "parquet_schema_sha256": hashlib.sha256(
                schema.serialize().to_pybytes()
            ).hexdigest(),
            "files": {
                role: {
                    "name": path.name,
                    "container_bytes": sizes[role],
                    "sha256": hashes[role],
                    **(
                        {"portable_content_sha256": evidence_portable_sha256}
                        if role == "evidence"
                        else {}
                    ),
                }
                for role, path in zip(
                    ("raw", "evidence", "marker"),
                    source_triplet,
                    strict=True,
                )
            },
            "first_consumers": [
                first_consumers[pool]
                for pool in sorted(first_consumers)
            ],
        }
        certificate["certificate_identity_sha256"] = (
            _assembly_certificate_identity(certificate)
        )
        certificate = _validate_assembly_certificate(
            certificate,
            lower=lower,
            upper=upper,
            validation_code_sha256=validation_code_sha256,
            frozen_upper_identity_sha256=str(
                frozen_upper["header_identity_sha256"]
            ),
        )
    copied_bytes = _install_inventory_triplet(
        source_triplet,
        destination_triplet,
        {
            role: str(certificate["files"][role]["sha256"])
            for role in ("raw", "evidence", "marker")
        },
    )
    if not reused:
        certificate_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl_gz(certificate_path, [certificate])
    return {
        "certificate": certificate,
        "certificate_reused": reused,
        "copied_bytes": copied_bytes,
    }


def _run_inventory_chunk_jobs(
    jobs: list[tuple[Path, Path, int, int, dict[str, object], str]],
    *,
    workers: int,
) -> Iterator[dict[str, object]]:
    worker_count = bounded_workers(workers)
    if worker_count == 1:
        for job in jobs:
            yield _certify_inventory_chunk_job(*job)
        return
    pending_jobs = deque(jobs)
    with interruptible_process_pool(worker_count) as executor:
        futures: dict[object, int] = {}
        completed: dict[int, dict[str, object]] = {}
        next_submitted = 0
        next_emitted = 0
        while pending_jobs and len(futures) < worker_count * 2:
            job = pending_jobs.popleft()
            future = executor.submit(_certify_inventory_chunk_job, *job)
            futures[future] = next_submitted
            next_submitted += 1
        while pending_jobs or futures:
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                completed[futures.pop(future)] = future.result()
            while next_emitted in completed:
                yield completed.pop(next_emitted)
                next_emitted += 1
                if pending_jobs:
                    job = pending_jobs.popleft()
                    future = executor.submit(_certify_inventory_chunk_job, *job)
                    futures[future] = next_submitted
                    next_submitted += 1


def _ordered_manifest_from_certificates(
    root: Path,
    ranges: list[tuple[int, int]],
    certificates: list[dict[str, object]],
    *,
    chunk_size: int,
    frozen_upper: dict[str, object],
    factory_certificate: dict[str, object],
) -> dict[str, object]:
    chunks: list[dict[str, object]] = []
    portable: list[dict[str, object]] = []
    for (lower, upper), certificate in zip(ranges, certificates, strict=True):
        files = certificate["files"]
        raw_by_event = {
            name: int(certificate["raw_by_event"][name])
            for name in EVENT_TOPICS
        }
        chunks.append(
            inventory_manifest_chunk_record(
                lower=lower,
                upper=upper,
                rows=int(certificate["rows"]),
                raw_by_event=raw_by_event,
                parquet_schema_sha256=str(
                    certificate["parquet_schema_sha256"]
                ),
                raw_file=str(files["raw"]["name"]),
                raw_sha256=str(files["raw"]["sha256"]),
                marker_file=str(files["marker"]["name"]),
                marker_sha256=str(files["marker"]["sha256"]),
                evidence_file=str(files["evidence"]["name"]),
                evidence_sha256=str(files["evidence"]["sha256"]),
            )
        )
        portable.extend(
            [
                {
                    "path": files["marker"]["name"],
                    "container_bytes": files["marker"]["container_bytes"],
                    "content_sha256": files["marker"]["sha256"],
                    "content_encoding": "identity",
                },
                {
                    "path": files["raw"]["name"],
                    "container_bytes": files["raw"]["container_bytes"],
                    "content_sha256": files["raw"]["sha256"],
                    "content_encoding": "identity",
                },
                {
                    "path": files["evidence"]["name"],
                    "container_bytes": files["evidence"]["container_bytes"],
                    "content_sha256": files["evidence"][
                        "portable_content_sha256"
                    ],
                    "content_encoding": "gzip",
                },
            ]
        )
    return inventory_ordered_manifest_record(
        ranges,
        chunks,
        portable,
        chunk_size=chunk_size,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
    )


def _ordered_manifest_identity(record: dict[str, object]) -> dict[str, object]:
    return {
        key: record[key]
        for key in (
            "schema_version",
            "inventory_raw_generation",
            "inventory_marker_schema_version",
            "start_block",
            "end_block",
            "chunk_size",
            "chunk_count",
            "raw_logs",
            "raw_by_event",
            "chunk_manifest_sha256",
            "portable_manifest_sha256",
            "factory_identity",
        )
    }


def _write_first_consuming_event_certificate(
    root: Path,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    *,
    frozen_upper: dict[str, object],
) -> dict[str, object]:
    data_path, marker_path = inventory_first_consuming_event_paths(root)
    write_jsonl_gz(data_path, rows)
    source_identity = _ordered_manifest_identity(manifest)
    marker = {
        "status": "complete",
        "schema_version": INVENTORY_FIRST_CONSUMER_SCHEMA_VERSION,
        "generation": INVENTORY_FIRST_CONSUMER_GENERATION,
        "consumer_event_types": sorted(INVENTORY_INITIALIZATION_CONSUMERS),
        "source_ordered_manifest_identity_sha256": canonical_json_sha256(
            source_identity
        ),
        "source_ordered_manifest_semantic_sha256": canonical_json_sha256(manifest),
        "source_chunk_manifest_sha256": manifest["chunk_manifest_sha256"],
        "source_portable_manifest_sha256": manifest["portable_manifest_sha256"],
        "factory_identity": manifest["factory_identity"],
        "frozen_upper_identity_sha256": frozen_upper["header_identity_sha256"],
        "exact_consuming_events": sum(
            int(manifest["raw_by_event"][name])
            for name in INVENTORY_INITIALIZATION_CONSUMERS
        ),
        "exact_consuming_events_by_kind": {
            name: int(manifest["raw_by_event"][name])
            for name in sorted(INVENTORY_INITIALIZATION_CONSUMERS)
        },
        "distinct_consuming_pools": len(rows),
        "rows": len(rows),
        "data_file": data_path.name,
        "data_sha256": file_sha256(data_path),
        "data_portable_sha256": portable_content_sha256(data_path),
        "summary_semantic_sha256": canonical_json_sha256(rows),
    }
    marker["certificate_identity_sha256"] = _assembly_certificate_identity(marker)
    with atomic_output(marker_path) as temporary:
        temporary.write_text(
            json.dumps(marker, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return marker


def load_v3_first_consuming_events(
    root: Path,
    *,
    ordered_manifest: dict[str, object],
    frozen_upper: dict[str, object],
    factory_certificate: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Load exact earliest consuming events without asserting prior Initialize state."""

    _paths, installed_manifest, _binding = load_certified_inventory_generation(
        root,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
    )
    if installed_manifest != ordered_manifest:
        raise ValueError("V3 first-consuming-event manifest is not the installed generation")

    data_path, marker_path = inventory_first_consuming_event_paths(root)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    source_identity = _ordered_manifest_identity(ordered_manifest)
    expected_factory_identity = _factory_manifest_identity(
        factory_certificate,
        frozen_upper,
    )
    with gzip.open(data_path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    validated_rows = _validate_first_consumers(
        rows,
        lower=int(ordered_manifest["start_block"]),
        upper=int(ordered_manifest["end_block"]),
    )
    exact_by_kind = {
        name: int(ordered_manifest["raw_by_event"][name])
        for name in sorted(INVENTORY_INITIALIZATION_CONSUMERS)
    }
    if (
        marker.get("status") != "complete"
        or int(marker.get("schema_version", -1))
        != INVENTORY_FIRST_CONSUMER_SCHEMA_VERSION
        or marker.get("generation") != INVENTORY_FIRST_CONSUMER_GENERATION
        or marker.get("consumer_event_types")
        != sorted(INVENTORY_INITIALIZATION_CONSUMERS)
        or marker.get("source_ordered_manifest_identity_sha256")
        != canonical_json_sha256(source_identity)
        or marker.get("source_ordered_manifest_semantic_sha256")
        != canonical_json_sha256(ordered_manifest)
        or marker.get("source_chunk_manifest_sha256")
        != ordered_manifest.get("chunk_manifest_sha256")
        or marker.get("source_portable_manifest_sha256")
        != ordered_manifest.get("portable_manifest_sha256")
        or marker.get("factory_identity") != expected_factory_identity
        or marker.get("frozen_upper_identity_sha256")
        != frozen_upper.get("header_identity_sha256")
        or marker.get("exact_consuming_events_by_kind") != exact_by_kind
        or int(marker.get("exact_consuming_events", -1)) != sum(exact_by_kind.values())
        or int(marker.get("distinct_consuming_pools", -1)) != len(validated_rows)
        or int(marker.get("rows", -1)) != len(validated_rows)
        or marker.get("data_file") != data_path.name
        or marker.get("data_sha256") != file_sha256(data_path)
        or marker.get("data_portable_sha256") != portable_content_sha256(data_path)
        or marker.get("summary_semantic_sha256")
        != canonical_json_sha256(validated_rows)
        or marker.get("certificate_identity_sha256")
        != _assembly_certificate_identity(marker)
    ):
        raise ValueError("V3 first-consuming-event certificate is stale or invalid")
    return validated_rows, marker


def _installed_file_record(
    path: Path,
    *,
    sha256: str,
) -> dict[str, object]:
    size, mtime_ns, ctime_ns, inode = _file_state(path)
    return {
        "name": path.name,
        "container_bytes": size,
        "container_mtime_ns": mtime_ns,
        "container_ctime_ns": ctime_ns,
        "container_inode": inode,
        "sha256": sha256,
    }


def _write_installed_generation_marker(
    root: Path,
    manifest: dict[str, object],
    certificates: list[dict[str, object]],
    *,
    validation_code_sha256: str,
    first_consumer_marker: dict[str, object],
) -> dict[str, object]:
    chunks: list[dict[str, object]] = []
    for chunk, certificate in zip(
        manifest["chunks"], certificates, strict=True
    ):
        lower, upper = int(chunk["lower"]), int(chunk["upper"])
        paths = inventory_chunk_triplet(lower, upper, root)
        files = {
            role: _installed_file_record(
                path,
                sha256=str(certificate["files"][role]["sha256"]),
            )
            for role, path in zip(
                ("raw", "evidence", "marker"), paths, strict=True
            )
        }
        chunks.append(
            {
                "lower": lower,
                "upper": upper,
                "rows": int(certificate["rows"]),
                "certificate_identity_sha256": certificate[
                    "certificate_identity_sha256"
                ],
                "files": files,
            }
        )
    manifest_path = inventory_ordered_manifest_path(root)
    first_data_path, first_marker_path = inventory_first_consuming_event_paths(root)
    marker = {
        "status": "complete",
        "schema_version": INVENTORY_INSTALLED_GENERATION_SCHEMA_VERSION,
        "generation": INVENTORY_INSTALLED_GENERATION,
        "validation_code_sha256": validation_code_sha256,
        "ordered_manifest_file": manifest_path.name,
        "ordered_manifest_sha256": file_sha256(manifest_path),
        "ordered_manifest_semantic_sha256": canonical_json_sha256(manifest),
        "chunk_manifest_sha256": manifest["chunk_manifest_sha256"],
        "portable_manifest_sha256": manifest["portable_manifest_sha256"],
        "factory_identity": manifest["factory_identity"],
        "chunk_count": len(chunks),
        "chunks_identity_sha256": canonical_json_sha256(chunks),
        "chunks": chunks,
        "first_consumer_marker_file": first_marker_path.name,
        "first_consumer_marker_sha256": file_sha256(first_marker_path),
        "first_consumer_data_file": first_data_path.name,
        "first_consumer_data_sha256": file_sha256(first_data_path),
        "first_consumer_certificate_identity_sha256": first_consumer_marker[
            "certificate_identity_sha256"
        ],
    }
    marker["certificate_identity_sha256"] = _assembly_certificate_identity(marker)
    with atomic_output(inventory_installed_generation_marker_path(root)) as temporary:
        temporary.write_text(
            json.dumps(marker, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return marker


def load_certified_inventory_generation(
    root: Path,
    *,
    frozen_upper: dict[str, object],
    factory_certificate: dict[str, object],
) -> tuple[list[Path], dict[str, object], dict[str, object]]:
    marker_path = inventory_installed_generation_marker_path(root)
    if not marker_path.is_file():
        raise FileNotFoundError("V3 inventory generation lacks its final completion marker")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    manifest_path = inventory_ordered_manifest_path(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = marker.get("chunks")
    manifest_chunks = manifest.get("chunks")
    first_data_path, first_marker_path = inventory_first_consuming_event_paths(root)
    if (
        not isinstance(chunks, list)
        or not isinstance(manifest_chunks, list)
        or marker.get("status") != "complete"
        or int(marker.get("schema_version", -1))
        != INVENTORY_INSTALLED_GENERATION_SCHEMA_VERSION
        or marker.get("generation") != INVENTORY_INSTALLED_GENERATION
        or marker.get("validation_code_sha256") != _validation_code_sha256()
        or marker.get("ordered_manifest_file") != manifest_path.name
        or marker.get("ordered_manifest_sha256") != file_sha256(manifest_path)
        or marker.get("ordered_manifest_semantic_sha256")
        != canonical_json_sha256(manifest)
        or marker.get("chunk_manifest_sha256")
        != manifest.get("chunk_manifest_sha256")
        or marker.get("portable_manifest_sha256")
        != manifest.get("portable_manifest_sha256")
        or marker.get("factory_identity")
        != _factory_manifest_identity(factory_certificate, frozen_upper)
        or int(marker.get("chunk_count", -1)) != len(chunks)
        or marker.get("chunks_identity_sha256") != canonical_json_sha256(chunks)
        or len(chunks) != len(manifest_chunks)
        or marker.get("first_consumer_marker_file") != first_marker_path.name
        or marker.get("first_consumer_marker_sha256") != file_sha256(first_marker_path)
        or marker.get("first_consumer_data_file") != first_data_path.name
        or marker.get("first_consumer_data_sha256") != file_sha256(first_data_path)
        or marker.get("certificate_identity_sha256")
        != _assembly_certificate_identity(marker)
    ):
        raise ValueError("V3 installed inventory generation is stale or invalid")
    raw_paths: list[Path] = []
    for installed, manifest_chunk in zip(chunks, manifest_chunks, strict=True):
        if not isinstance(installed, dict) or not isinstance(manifest_chunk, dict):
            raise ValueError("V3 installed inventory generation has malformed chunks")
        bounds = int(manifest_chunk.get("lower", -1)), int(
            manifest_chunk.get("upper", -1)
        )
        if (
            (int(installed.get("lower", -1)), int(installed.get("upper", -1)))
            != bounds
            or int(installed.get("rows", -1)) != int(manifest_chunk.get("rows", -2))
        ):
            raise ValueError("V3 installed inventory generation order or perimeter drifted")
        expected_hashes = {
            "raw": manifest_chunk.get("raw_sha256"),
            "evidence": manifest_chunk.get("evidence_sha256"),
            "marker": manifest_chunk.get("marker_sha256"),
        }
        triplet = inventory_chunk_triplet(*bounds, root)
        files = installed.get("files")
        if not isinstance(files, dict) or set(files) != set(expected_hashes):
            raise ValueError("V3 installed inventory generation lacks a triplet identity")
        for role, path in zip(("raw", "evidence", "marker"), triplet, strict=True):
            item = files[role]
            if not isinstance(item, dict) or not path.is_file():
                raise ValueError("V3 installed inventory generation lacks a listed file")
            state = _file_state(path)
            recorded_state = (
                item.get("container_bytes"),
                item.get("container_mtime_ns"),
                item.get("container_ctime_ns"),
                item.get("container_inode"),
            )
            if (
                item.get("name") != path.name
                or item.get("sha256") != expected_hashes[role]
                or recorded_state != state
            ):
                raise ValueError(
                    f"V3 installed inventory file changed after certification: {path.name}"
                )
        raw_paths.append(triplet[0])
    listed = {path.name for path in raw_paths}
    extras = sorted(
        path.name
        for path in root.glob("blocks_*.parquet")
        if path.name not in listed
    )
    binding = {
        "policy": INVENTORY_INSTALLED_GENERATION,
        "completion_marker_sha256": file_sha256(marker_path),
        "certificate_identity_sha256": marker["certificate_identity_sha256"],
        "ordered_manifest_sha256": marker["ordered_manifest_sha256"],
        "chunk_count": len(raw_paths),
        "listed_raw_paths_sha256": canonical_json_sha256(
            [path.name for path in raw_paths]
        ),
        "ignored_extra_raw_files": extras,
    }
    return raw_paths, manifest, binding


def _validate_inventory_source_names(
    owners: dict[tuple[int, int], Path],
    ranges: list[tuple[int, int]],
    destination: Path,
) -> None:
    expected_by_root: dict[Path, set[tuple[int, int]]] = {}
    for bounds, root in owners.items():
        expected_by_root.setdefault(root, set()).add(bounds)
    perimeter_lower, perimeter_upper = ranges[0][0], ranges[-1][1]
    for root, expected in expected_by_root.items():
        allowed = set(ranges) if root.resolve() == destination.resolve() else expected
        discovered = _inventory_chunk_files(root)
        alternates = [
            bounds
            for bounds in discovered
            if bounds not in allowed
            and bounds[0] <= perimeter_upper
            and bounds[1] >= perimeter_lower
        ]
        if alternates:
            raise ValueError(
                f"V3 inventory source contains alternate overlapping chunks: {alternates[:3]}"
            )
        for lower, upper in sorted(expected):
            names = {
                path.name
                for path in inventory_chunk_triplet(lower, upper, root)
            }
            if discovered.get((lower, upper), set()) != names:
                raise FileNotFoundError(
                    f"V3 inventory source triplet is incomplete: {lower}-{upper}"
                )


def _assemble_inventory_shards(
    sources: list[tuple[Path, tuple[int, int]]],
    destination: Path,
    *,
    start: int,
    end: int,
    chunk_size: int,
    frozen_upper: dict[str, object],
    factory_certificate: dict[str, object],
    workers: int = 1,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, object]:
    """Certify chunks once, reduce in order, and publish completion marker last."""

    ranges = validate_inventory_shard_partition(
        [bounds for _root, bounds in sources],
        start=start,
        end=end,
        chunk_size=chunk_size,
    )
    owners: dict[tuple[int, int], Path] = {}
    for root, (lower, upper) in sources:
        for item in block_ranges(lower, upper, chunk_size):
            if item in owners:
                raise ValueError(f"V3 inventory chunk has multiple shard owners: {item}")
            owners[item] = root
    _validate_inventory_source_names(owners, ranges, destination)
    destination.mkdir(parents=True, exist_ok=True)
    _validate_inventory_destination_names(destination, ranges, complete=False)
    validation_code_sha256 = _validation_code_sha256()
    jobs = [
        (
            owners[(lower, upper)],
            destination,
            lower,
            upper,
            frozen_upper,
            validation_code_sha256,
        )
        for lower, upper in ranges
    ]
    certificates: list[dict[str, object]] = []
    first_by_pool: dict[str, dict[str, object]] = {}
    counters = {
        "chunks_complete": 0,
        "chunks_total": len(ranges),
        "raw_logs_verified": 0,
        "source_bytes_verified": 0,
        "copied_bytes": 0,
        "certificates_reused": 0,
    }
    for index, result in enumerate(_run_inventory_chunk_jobs(jobs, workers=workers)):
        certificate = result["certificate"]
        bounds = int(certificate["lower"]), int(certificate["upper"])
        if bounds != ranges[index]:
            raise ValueError("V3 inventory chunk reducer received out-of-order evidence")
        for row in certificate["first_consumers"]:
            pool = str(row["pool"])
            prior = first_by_pool.get(pool)
            order = int(row["block_number"]), int(row["log_index"])
            if prior is None or order < (
                int(prior["block_number"]),
                int(prior["log_index"]),
            ):
                first_by_pool[pool] = dict(row)
        certificates.append(dict(certificate))
        counters["chunks_complete"] += 1
        counters["raw_logs_verified"] += int(certificate["rows"])
        counters["source_bytes_verified"] += sum(
            int(certificate["files"][role]["container_bytes"])
            for role in ("raw", "evidence", "marker")
        )
        counters["copied_bytes"] += int(result["copied_bytes"])
        counters["certificates_reused"] += int(result["certificate_reused"])
        if progress is not None:
            progress(dict(counters))
    if len(certificates) != len(ranges):
        raise RuntimeError("V3 inventory assembly did not certify its complete perimeter")
    _validate_inventory_destination_names(destination, ranges, complete=True)
    record = _ordered_manifest_from_certificates(
        destination,
        ranges,
        certificates,
        chunk_size=chunk_size,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
    )
    manifest_path = inventory_ordered_manifest_path(destination)
    if manifest_path.exists():
        observed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if observed != record:
            raise ValueError("V3 inventory ordered manifest disagrees with certified chunks")
    if not manifest_path.exists():
        with atomic_output(manifest_path) as temporary:
            temporary.write_text(
                json.dumps(record, allow_nan=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    first_marker = _write_first_consuming_event_certificate(
        destination,
        record,
        [first_by_pool[pool] for pool in sorted(first_by_pool)],
        frozen_upper=frozen_upper,
    )
    _write_installed_generation_marker(
        destination,
        record,
        certificates,
        validation_code_sha256=validation_code_sha256,
        first_consumer_marker=first_marker,
    )
    return record


def assemble_inventory_shards(
    sources: list[tuple[Path, tuple[int, int]]],
    destination: Path,
    *,
    start: int,
    end: int,
    chunk_size: int,
    frozen_upper: dict[str, object],
    factory_certificate: dict[str, object],
    workers: int = 1,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, object]:
    """Own publication locks and install one complete certified generation."""

    from ddvc import paths as ddvc_paths
    from ddvc.runtime import exclusive_interval_job, exclusive_job

    with exclusive_job(ddvc_paths.RAW_MARKET_DATA_LOCK, job="V3 inventory shard assembly"):
        with exclusive_interval_job(
            ddvc_paths.V3_INVENTORY_RANGE_LOCK_ROOT,
            start,
            end,
            job="V3 inventory shard assembly",
        ):
            return _assemble_inventory_shards(
                sources,
                destination,
                start=start,
                end=end,
                chunk_size=chunk_size,
                frozen_upper=frozen_upper,
                factory_certificate=factory_certificate,
                workers=workers,
                progress=progress,
            )
