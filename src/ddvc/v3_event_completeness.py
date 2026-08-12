"""Independent V3 event-source certificate and immutable release contract."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from ddvc.amounts import human_to_raw
from ddvc.artifact_release import (
    ArtifactRelease,
    canonical_json_sha256,
    file_sha256,
    is_sha256,
    current_artifact_release,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.ethereum_blocks import (
    fetch_block_header,
    iter_block_header_snapshot,
    write_block_header_snapshot,
)
from ddvc.fetch.raw import write_json
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.runtime import interruptible_thread_pool
from ddvc.v3_inventory import EVENT_TOPICS, PoolStatic
from ddvc.v3_pool_registry import V3FactoryPool, registry_sha256


V3_EVENT_SOURCE_SCHEMA_VERSION = 1
V3_EVENT_SOURCE_RELEASE_SCHEMA_VERSION = 1
V3_EVENT_SOURCE_KIND = "v3_event_source_release"
V3_EVENT_SOURCE_RELEASE_ROOT = DATA_DIR / "processed" / "v3_core_event_source_release"
V3_EVENT_SOURCE_CURRENT = V3_EVENT_SOURCE_RELEASE_ROOT / "current.json"
V3_EVENT_SOURCE_FILENAMES = {
    "summary": "summary.parquet",
    "exceptions": "exceptions.parquet",
    "quarantine": "perimeter_quarantine.parquet",
    "certificate": "certificate.json",
}
V3_EVENT_HEADER_ROOT = DATA_DIR / "raw" / "ethereum" / "v3_event_source_block_headers"
V3_CORE_EVENTS = ("burn", "mint", "swap")
V3_POOL_PERIMETER = "all_canonical_uniswap_v3_market_state_consumer_pools"
V3_COMPARISON_LEDGER = "corrected_canonical_market_state_against_anchored_global_exact_logs"
V3_RECONCILIATION_SCOPE = "full_utc_day_analysis_cutoff_factory_pool_perimeter"
V3_IDENTITY_FIELDS = (
    "event_type",
    "block_number",
    "transaction_hash",
    "log_index",
    "pool",
)
V3_PAYLOAD_FIELDS = (
    "timestamp",
    "token0",
    "token1",
    "decimals0",
    "decimals1",
    "fee_pips",
    "tick_spacing",
    "amount0_raw",
    "amount1_raw",
    "sqrt_price_x96",
    "tick",
    "liquidity_delta",
    "tick_lower",
    "tick_upper",
)
COUNT_FIELDS = (
    "exact_events",
    "canonical_events",
    "matched_identities",
    "missing_from_canonical",
    "canonical_only",
    "canonical_duplicate_rows",
    "payload_mismatches",
)
FAILURE_FIELDS = (
    "missing_from_canonical",
    "canonical_only",
    "canonical_duplicate_rows",
    "payload_mismatches",
)
V3_SUMMARY_FIELDS = ("day", "event_type", *COUNT_FIELDS, "passed")
V3_EXCEPTION_FIELDS = (
    "day",
    "event_type",
    "status",
    "block_number",
    "tx_hash",
    "log_index",
    "pool",
    "exact_payload_json",
    "canonical_payload_json",
    "duplicate_rows",
)
V3_QUARANTINE_FIELDS = (
    "pool",
    "reason",
    "first_block",
    "last_block",
    "logs",
    *(f"{event_type}_logs" for event_type in sorted(EVENT_TOPICS)),
)
EventKey = tuple[str, int, str, int, str]


@dataclass(frozen=True)
class V3PoolAuthority:
    pool: str
    token0: str
    token1: str
    decimals0: int
    decimals1: int
    fee_pips: int
    tick_spacing: int


@dataclass(frozen=True)
class V3EventPayload:
    timestamp: int
    token0: str
    token1: str
    decimals0: int
    decimals1: int
    fee_pips: int
    tick_spacing: int
    amount0_raw: int
    amount1_raw: int
    sqrt_price_x96: int | None
    tick: int | None
    liquidity_delta: int | None
    tick_lower: int | None
    tick_upper: int | None


def event_key(
    event_type: object,
    block: object,
    tx_hash: object,
    log_index: object,
    pool: object,
) -> EventKey:
    return (
        str(event_type),
        int(block),
        str(tx_hash).lower(),
        int(log_index),
        str(pool).lower(),
    )


def v3_audit_days(quality_panel: str | Path) -> list[str]:
    genesis = get_source("uniswap_v3").genesis.strftime("%Y%m%d")
    days = [day for day in transaction_frontier_audit_days(quality_panel) if day >= genesis]
    if not days:
        raise RuntimeError("shared transaction-frontier calendar has no V3 audit dates")
    return days


def audit_calendar_sha256(days: Iterable[str]) -> str:
    normalized = [str(day).replace("-", "") for day in days]
    if not normalized or normalized != sorted(set(normalized)):
        raise ValueError("V3 audit calendar must be nonempty, unique, and sorted")
    return canonical_json_sha256(normalized)


def block_perimeter_sha256(blocks: Iterable[int]) -> str:
    normalized = sorted({int(block) for block in blocks})
    if not normalized or normalized[0] < 1:
        raise ValueError("V3 event-source block perimeter must be nonempty and positive")
    return canonical_json_sha256(normalized)


def header_snapshot_path(days: Iterable[str], blocks: Iterable[int]) -> Path:
    return V3_EVENT_HEADER_ROOT / (
        f"{audit_calendar_sha256(days)}-{block_perimeter_sha256(blocks)}.jsonl"
    )


def certified_header_snapshot_path(
    days: Iterable[str], certificate: Mapping[str, object]
) -> Path:
    perimeter = certificate.get("block_perimeter_sha256")
    if not is_sha256(perimeter):
        raise ValueError("V3 event-source certificate lacks block_perimeter_sha256")
    return V3_EVENT_HEADER_ROOT / f"{audit_calendar_sha256(days)}-{perimeter}.jsonl"


def pool_authorities(
    factory_pools: Iterable[V3FactoryPool],
    statics: Mapping[str, PoolStatic],
) -> dict[str, V3PoolAuthority]:
    authorities: dict[str, V3PoolAuthority] = {}
    factories = {pool.pool: pool for pool in factory_pools}
    if not statics or not set(statics).issubset(factories):
        extra = sorted(set(statics) - set(factories))[:3]
        raise ValueError(
            f"V3 full consumer statics disagree with factory perimeter: extra={extra}"
        )
    for pool, static in statics.items():
        factory = factories[pool]
        if (static.token0, static.token1) != (factory.token0, factory.token1):
            raise ValueError(f"V3 consumer statics disagree with factory token identity: {pool}")
        authorities[pool] = V3PoolAuthority(
            pool=pool,
            token0=factory.token0,
            token1=factory.token1,
            decimals0=int(static.decimals0),
            decimals1=int(static.decimals1),
            fee_pips=int(factory.fee),
            tick_spacing=int(factory.tick_spacing),
        )
    return authorities


def pool_perimeter_sha256(authorities: Mapping[str, V3PoolAuthority]) -> str:
    return canonical_json_sha256(
        [
            authority.__dict__
            for authority in sorted(authorities.values(), key=lambda item: item.pool)
        ]
    )


def load_block_timestamps(path: Path) -> dict[int, int]:
    timestamps: dict[int, int] = {}
    for row in iter_block_header_snapshot(path, require_evidence=True):
        block = int(row["block_number"])
        if block in timestamps:
            raise ValueError("V3 block-header snapshot contains duplicate blocks")
        timestamps[block] = int(row["timestamp"])
    if not timestamps:
        raise ValueError("V3 block-header snapshot is empty")
    return timestamps


def ensure_block_header_snapshot(
    blocks: Iterable[int],
    path: Path,
    *,
    workers: int = 4,
) -> Path:
    """Build one exact evidence-bearing header snapshot for the audit event blocks."""

    expected = sorted({int(block) for block in blocks})
    if not expected:
        raise ValueError("V3 event-source block perimeter is empty")
    if path.is_file():
        observed = [
            int(row["block_number"])
            for row in iter_block_header_snapshot(path, require_evidence=True)
        ]
        if observed == expected:
            return path
        raise ValueError("existing V3 block-header snapshot has a different perimeter")
    worker_count = max(1, min(int(workers), 8))
    pending_limit = worker_count * 2
    queue = iter(expected)

    def fetched_headers():
        with interruptible_thread_pool(max_workers=worker_count) as pool:
            while True:
                futures: dict[object, int] = {}
                for _slot in range(pending_limit):
                    try:
                        block = next(queue)
                    except StopIteration:
                        break
                    futures[pool.submit(fetch_block_header, block, require_evidence=True)] = block
                if not futures:
                    return
                completed_headers: dict[int, dict[str, object]] = {}
                while futures:
                    completed, _pending = wait(futures, return_when=FIRST_COMPLETED)
                    for future in completed:
                        block = futures.pop(future)
                        completed_headers[block] = future.result()
                yield from (
                    completed_headers[block] for block in sorted(completed_headers)
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    write_block_header_snapshot(
        fetched_headers(),
        path,
        require_evidence=True,
        presorted=True,
    )
    observed = [
        int(row["block_number"])
        for row in iter_block_header_snapshot(path, require_evidence=True)
    ]
    if observed != expected:
        raise ValueError("installed V3 block-header snapshot has a different perimeter")
    return path


def _payload(
    event_type: str,
    authority: V3PoolAuthority,
    timestamp: int,
    *,
    amount0_raw: int,
    amount1_raw: int,
    sqrt_price_x96: int | None,
    tick: int | None,
    liquidity_delta: int | None,
    tick_lower: int | None,
    tick_upper: int | None,
) -> V3EventPayload:
    return V3EventPayload(
        timestamp=int(timestamp),
        token0=authority.token0,
        token1=authority.token1,
        decimals0=authority.decimals0,
        decimals1=authority.decimals1,
        fee_pips=authority.fee_pips,
        tick_spacing=authority.tick_spacing,
        amount0_raw=int(amount0_raw),
        amount1_raw=int(amount1_raw),
        sqrt_price_x96=None if sqrt_price_x96 is None else int(sqrt_price_x96),
        tick=None if tick is None else int(tick),
        liquidity_delta=None if liquidity_delta is None else int(liquidity_delta),
        tick_lower=None if tick_lower is None else int(tick_lower),
        tick_upper=None if tick_upper is None else int(tick_upper),
    )


def exact_event_map(
    events: Iterable[Mapping[str, object]],
    authorities: Mapping[str, V3PoolAuthority],
    block_timestamps: Mapping[int, int],
) -> dict[EventKey, V3EventPayload]:
    result: dict[EventKey, V3EventPayload] = {}
    for event in events:
        event_type = str(event["event_type"])
        if event_type not in V3_CORE_EVENTS:
            continue
        pool = str(event["pool"]).lower()
        if pool not in authorities:
            continue
        block = int(event["block_number"])
        if block not in block_timestamps:
            raise ValueError(f"V3 exact event lacks certified block timestamp: {block}")
        key = event_key(event_type, block, event["tx_hash"], event["log_index"], pool)
        if key in result:
            raise ValueError(f"exact V3 event ledger contains duplicate identity: {key}")
        result[key] = _payload(
            event_type,
            authorities[pool],
            block_timestamps[block],
            amount0_raw=int(event["amount0_delta_raw"]),
            amount1_raw=int(event["amount1_delta_raw"]),
            sqrt_price_x96=event.get("sqrt_price_x96"),
            tick=event.get("tick"),
            liquidity_delta=(
                None
                if event.get("liquidity_amount") is None
                else int(event["liquidity_amount"])
                * (-1 if event_type == "burn" else 1)
            ),
            tick_lower=event.get("tick_lower"),
            tick_upper=event.get("tick_upper"),
        )
    return result


def canonical_event_map(
    frame: pd.DataFrame,
    authorities: Mapping[str, V3PoolAuthority],
) -> tuple[dict[EventKey, V3EventPayload], Counter[EventKey]]:
    result: dict[EventKey, V3EventPayload] = {}
    occurrences: Counter[EventKey] = Counter()
    for row in frame.itertuples(index=False):
        pool = str(row.pool).lower()
        if pool not in authorities:
            continue
        record_type = str(row.record_type)
        stream = str(row.source_stream)
        if record_type == "swap":
            event_type = "swap"
        elif record_type == "liquidity" and stream == "mints":
            event_type = "mint"
        elif record_type == "liquidity" and stream == "burns":
            event_type = "burn"
        else:
            continue
        authority = authorities[pool]
        observed_static = (
            str(row.token0_raw).lower(),
            str(row.token1_raw).lower(),
            int(row.decimals0),
            int(row.decimals1),
        )
        expected_static = (
            authority.token0,
            authority.token1,
            authority.decimals0,
            authority.decimals1,
        )
        if observed_static != expected_static:
            raise ValueError(f"canonical V3 event has wrong factory/token statics: {pool}")
        amount0 = human_to_raw(row.amount0, authority.decimals0)
        amount1 = human_to_raw(row.amount1, authority.decimals1)
        if amount0 is None or amount1 is None:
            raise ValueError(f"canonical V3 event has an inexact token amount: {pool}")
        key = event_key(event_type, row.block_number, row.tx_hash, row.log_index, pool)
        payload = _payload(
            event_type,
            authority,
            int(row.timestamp),
            amount0_raw=int(amount0),
            amount1_raw=int(amount1),
            sqrt_price_x96=row.sqrt_price_x96 if event_type == "swap" else None,
            tick=row.tick if event_type == "swap" else None,
            liquidity_delta=(
                int(row.liquidity_delta) if event_type in {"mint", "burn"} else None
            ),
            tick_lower=row.tick_lower if event_type in {"mint", "burn"} else None,
            tick_upper=row.tick_upper if event_type in {"mint", "burn"} else None,
        )
        occurrences[key] += 1
        result.setdefault(key, payload)
    return result, occurrences


def _payload_json(payload: V3EventPayload | None) -> str | None:
    return (
        None
        if payload is None
        else json.dumps(payload.__dict__, sort_keys=True, separators=(",", ":"))
    )


def compare_event_maps(
    day: str,
    exact: Mapping[EventKey, V3EventPayload],
    canonical: Mapping[EventKey, V3EventPayload],
    occurrences: Mapping[EventKey, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    for event_type in V3_CORE_EVENTS:
        exact_keys = {key for key in exact if key[0] == event_type}
        canonical_keys = {key for key in canonical if key[0] == event_type}
        matched = exact_keys & canonical_keys
        missing = exact_keys - canonical_keys
        canonical_only = canonical_keys - exact_keys
        duplicate_rows = sum(
            max(0, int(count) - 1)
            for key, count in occurrences.items()
            if key[0] == event_type
        )
        mismatches = {key for key in matched if exact[key] != canonical[key]}
        row = {
            "day": day,
            "event_type": event_type,
            "exact_events": len(exact_keys),
            "canonical_events": len(canonical_keys),
            "matched_identities": len(matched),
            "missing_from_canonical": len(missing),
            "canonical_only": len(canonical_only),
            "canonical_duplicate_rows": duplicate_rows,
            "payload_mismatches": len(mismatches),
            "passed": not (missing or canonical_only or duplicate_rows or mismatches),
        }
        summaries.append(row)
        for status, keys in (
            ("missing_from_canonical", missing),
            ("canonical_only", canonical_only),
            ("payload_mismatch", mismatches),
        ):
            exceptions.extend(
                {
                    "day": day,
                    "event_type": event_type,
                    "status": status,
                    "block_number": key[1],
                    "tx_hash": key[2],
                    "log_index": key[3],
                    "pool": key[4],
                    "exact_payload_json": _payload_json(exact.get(key)),
                    "canonical_payload_json": _payload_json(canonical.get(key)),
                    "duplicate_rows": 0,
                }
                for key in sorted(keys)
            )
        exceptions.extend(
            {
                "day": day,
                "event_type": event_type,
                "status": "canonical_duplicate_identity",
                "block_number": key[1],
                "tx_hash": key[2],
                "log_index": key[3],
                "pool": key[4],
                "exact_payload_json": _payload_json(exact.get(key)),
                "canonical_payload_json": _payload_json(canonical.get(key)),
                "duplicate_rows": int(count) - 1,
            }
            for key, count in sorted(occurrences.items())
            if key[0] == event_type and int(count) > 1
        )
    return summaries, exceptions


def expected_summary_keys(days: Iterable[str]) -> set[tuple[str, str]]:
    return {(str(day), event_type) for day in days for event_type in V3_CORE_EVENTS}


def validate_v3_event_source_certificate(
    summary: pd.DataFrame,
    exceptions: pd.DataFrame,
    quarantine: pd.DataFrame,
    certificate: Mapping[str, object],
    expected_days: list[str],
) -> tuple[int, int]:
    schemas = (
        ("summary", summary, V3_SUMMARY_FIELDS),
        ("exceptions", exceptions, V3_EXCEPTION_FIELDS),
        ("quarantine", quarantine, V3_QUARANTINE_FIELDS),
    )
    for label, frame, expected_columns in schemas:
        if tuple(frame.columns) != expected_columns:
            raise ValueError(f"V3 event-source {label} schema is stale")
    if summary.duplicated(["day", "event_type"]).any():
        raise ValueError("V3 event-source summary contains duplicate keys")
    actual = set(
        summary[["day", "event_type"]].astype(str).itertuples(index=False, name=None)
    )
    expected = expected_summary_keys(expected_days)
    if actual != expected:
        raise ValueError(
            "V3 event-source calendar mismatch: "
            f"missing={sorted(expected - actual)[:3]}, extra={sorted(actual - expected)[:3]}"
        )
    if any(
        not pd.api.types.is_integer_dtype(summary[field].dtype)
        or pd.api.types.is_bool_dtype(summary[field].dtype)
        for field in COUNT_FIELDS
    ):
        raise ValueError("V3 event-source counts are not integer typed")
    if not pd.api.types.is_bool_dtype(summary["passed"].dtype):
        raise ValueError("V3 event-source pass flag is not Boolean")
    if summary[list(COUNT_FIELDS)].isna().any().any() or (
        summary[list(COUNT_FIELDS)] < 0
    ).any().any():
        raise ValueError("V3 event-source summary contains invalid counts")
    for row in summary.itertuples(index=False):
        if int(row.exact_events) != int(row.matched_identities) + int(
            row.missing_from_canonical
        ):
            raise ValueError("V3 exact-event identity algebra does not balance")
        if int(row.canonical_events) != int(row.matched_identities) + int(
            row.canonical_only
        ):
            raise ValueError("V3 canonical-event identity algebra does not balance")
        if int(row.payload_mismatches) > int(row.matched_identities):
            raise ValueError("V3 payload mismatches exceed matched identities")
        expected_pass = not any(int(getattr(row, field)) for field in FAILURE_FIELDS)
        if bool(row.passed) != expected_pass:
            raise ValueError("V3 summary pass flag disagrees with failure counts")
    if int(summary[list(FAILURE_FIELDS)].sum().sum()) != 0 or not exceptions.empty:
        raise ValueError("V3 event-source release contains comparison failures")
    expected_certificate = {
        "schema_version": V3_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": audit_calendar_sha256(expected_days),
        "audit_dates": len(expected_days),
        "first_day": expected_days[0],
        "last_day": expected_days[-1],
        "summary_rows": len(expected),
        "exception_rows": 0,
        "event_types": list(V3_CORE_EVENTS),
        "pool_perimeter": V3_POOL_PERIMETER,
        "comparison_ledger": V3_COMPARISON_LEDGER,
        "reconciliation_scope": V3_RECONCILIATION_SCOPE,
        "identity_fields": list(V3_IDENTITY_FIELDS),
        "payload_fields": list(V3_PAYLOAD_FIELDS),
    }
    stale = {
        key: (certificate.get(key), value)
        for key, value in expected_certificate.items()
        if certificate.get(key) != value
    }
    if stale:
        raise ValueError(f"V3 event-source certificate fields are stale: {stale}")
    for field in COUNT_FIELDS:
        if type(certificate.get(field)) is not int or int(certificate[field]) != int(
            summary[field].sum()
        ):
            raise ValueError(f"V3 event-source certificate total disagrees for {field}")
    for field in (
        "factory_registry_sha256",
        "pool_perimeter_sha256",
        "ordered_raw_manifest_sha256",
        "block_header_snapshot_sha256",
        "block_perimeter_sha256",
        "correction_generations_sha256",
    ):
        if not is_sha256(certificate.get(field)):
            raise ValueError(f"V3 event-source certificate lacks {field}")
    corrections = certificate.get("correction_generations")
    if not isinstance(corrections, dict) or not set(corrections).issubset(expected_days):
        raise ValueError("V3 event-source correction-generation ledger is malformed")
    if correction_generation_sha256(corrections) != certificate.get(
        "correction_generations_sha256"
    ):
        raise ValueError("V3 event-source correction-generation digest disagrees")
    for day, record in corrections.items():
        if (
            not isinstance(record, dict)
            or not is_sha256(record.get("generation_id"))
            or not is_sha256(record.get("data_sha256"))
            or not is_sha256(record.get("metadata_sha256"))
            or type(record.get("start_block")) is not int
            or type(record.get("end_block")) is not int
            or int(record["start_block"]) > int(record["end_block"])
            or not isinstance(record.get("scope"), str)
            or not record["scope"]
        ):
            raise ValueError(f"V3 correction-generation record is malformed: {day}")
    if type(certificate.get("pool_count")) is not int or int(certificate["pool_count"]) < 1:
        raise ValueError("V3 event-source certificate has an empty pool perimeter")
    if type(certificate.get("quarantine_rows")) is not int or int(
        certificate["quarantine_rows"]
    ) != len(quarantine):
        raise ValueError("V3 event-source quarantine count disagrees")
    if type(certificate.get("raw_inventory_logs")) is not int or int(
        certificate["raw_inventory_logs"]
    ) < int(summary["exact_events"].sum()):
        raise ValueError("V3 raw inventory log total is impossible")
    return len(expected_days), int(summary["exact_events"].sum())


def resolve_v3_event_source_release(
    pointer_path: Path = V3_EVENT_SOURCE_CURRENT,
) -> ArtifactRelease:
    return resolve_artifact_release(
        pointer_path,
        kind=V3_EVENT_SOURCE_KIND,
        schema_version=V3_EVENT_SOURCE_RELEASE_SCHEMA_VERSION,
        filenames=V3_EVENT_SOURCE_FILENAMES,
        require_current_provenance=True,
    )


def read_v3_event_source_release(
    release: ArtifactRelease | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    observed = release or resolve_v3_event_source_release()
    with current_artifact_release(observed):
        artifacts = observed.artifacts
        summary = pd.read_parquet(artifacts["summary"])
        exceptions = pd.read_parquet(artifacts["exceptions"])
        quarantine = pd.read_parquet(artifacts["quarantine"])
        certificate = json.loads(artifacts["certificate"].read_text(encoding="utf-8"))
        if not isinstance(certificate, dict):
            raise ValueError("V3 event-source certificate is not a JSON object")
        return summary, exceptions, quarantine, certificate


def publish_v3_event_source_release(
    summary: pd.DataFrame,
    exceptions: pd.DataFrame,
    quarantine: pd.DataFrame,
    certificate: dict[str, object],
    *,
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str,
    pointer_path: Path = V3_EVENT_SOURCE_CURRENT,
    write_pointer=write_json,
) -> ArtifactRelease:
    def validate(paths: Mapping[str, Path]) -> None:
        pd.testing.assert_frame_equal(
            summary, pd.read_parquet(paths["summary"]), check_dtype=True
        )
        pd.testing.assert_frame_equal(
            exceptions, pd.read_parquet(paths["exceptions"]), check_dtype=True
        )
        pd.testing.assert_frame_equal(
            quarantine, pd.read_parquet(paths["quarantine"]), check_dtype=True
        )
        if json.loads(paths["certificate"].read_text(encoding="utf-8")) != certificate:
            raise ValueError("V3 event-source certificate does not round-trip exactly")

    return publish_artifact_release(
        pointer_path=pointer_path,
        kind=V3_EVENT_SOURCE_KIND,
        schema_version=V3_EVENT_SOURCE_RELEASE_SCHEMA_VERSION,
        filenames=V3_EVENT_SOURCE_FILENAMES,
        writers={
            "summary": lambda path: summary.to_parquet(path, index=False),
            "exceptions": lambda path: exceptions.to_parquet(path, index=False),
            "quarantine": lambda path: quarantine.to_parquet(path, index=False),
            "certificate": lambda path: write_json(path, certificate),
        },
        row_counts={
            "summary": len(summary),
            "exceptions": len(exceptions),
            "quarantine": len(quarantine),
            "certificate": 1,
        },
        code_sources=code_sources,
        inputs=inputs,
        notes=notes,
        validate_staged=validate,
        write_pointer=write_pointer,
    )


def correction_generation_records(
    raw_root: Path,
    days: Iterable[str],
) -> dict[str, dict[str, object]]:
    from ddvc.graph_event_order import (
        load_event_order_corrections,
        load_event_order_generation_metadata,
    )

    records: dict[str, dict[str, object]] = {}
    for day in days:
        load_event_order_corrections(raw_root, "uniswap_v3", day)
        generation = load_event_order_generation_metadata(raw_root, "uniswap_v3", day)
        if generation is None:
            continue
        data_path, metadata_path, metadata = generation
        records[str(day)] = {
            "generation_id": metadata.get("generation_id"),
            "scope": metadata.get("scope"),
            "start_block": metadata.get("start_block"),
            "end_block": metadata.get("end_block"),
            "data_sha256": file_sha256(data_path),
            "metadata_sha256": file_sha256(metadata_path),
        }
    return records


def correction_generation_inputs(
    raw_root: Path,
    days: Iterable[str],
) -> list[Path]:
    from ddvc.graph_event_order import load_event_order_corrections

    paths: set[Path] = set()
    for day in days:
        _corrections, inputs = load_event_order_corrections(
            raw_root, "uniswap_v3", day
        )
        paths.update(Path(path) for path in inputs)
    return sorted(paths, key=str)


def correction_generation_sha256(records: Mapping[str, object]) -> str:
    return canonical_json_sha256(dict(sorted(records.items())))


def validate_v3_event_source_evidence_bundle(
    certificate: Mapping[str, object],
    *,
    summary: pd.DataFrame,
    quarantine: pd.DataFrame,
) -> tuple[int, int]:
    """Reopen every authority and rederive the released sample comparison."""

    from ddvc.paths import V3_INVENTORY_RAW_ROOT
    from ddvc.state_data import RAW_ROOT, read_tick_partition
    from ddvc.v3_inventory import (
        inventory_chunk_paths,
        inventory_ordered_manifest_path,
        iter_decoded_inventory_logs,
    )
    from ddvc.v3_inventory_calendar import load_day_calendar
    from ddvc.v3_pool_registry import load_registry, reopen_registry_evidence
    from scripts.build_v3_inventory_panel import (
        load_full_consumer_statics,
        inventory_perimeter,
        ranges_by_day,
        require_complete_raw_chunks,
    )
    from ddvc.reconstruct import UNIFIED_QUALITY_PANEL

    expected_days = v3_audit_days(UNIFIED_QUALITY_PANEL)
    factory_all, _factory_certificate = reopen_registry_evidence()
    factory_pools = load_registry()
    if registry_sha256(factory_all) != certificate.get("factory_registry_sha256"):
        raise ValueError("V3 reopened factory registry digest disagrees")
    authorities = pool_authorities(factory_pools, load_full_consumer_statics())
    if (
        len(authorities) != int(certificate.get("pool_count", -1))
        or pool_perimeter_sha256(authorities) != certificate.get("pool_perimeter_sha256")
    ):
        raise ValueError("V3 reopened full consumer pool perimeter disagrees")
    days, end_blocks = load_day_calendar()
    start, end = inventory_perimeter(days, end_blocks)
    ranges, perimeter = require_complete_raw_chunks(start, end)
    quarantine_rows = perimeter.get("quarantine_pool_ledger")
    if not isinstance(quarantine_rows, list):
        raise ValueError("V3 reopened perimeter quarantine ledger is malformed")
    reopened_quarantine = pd.DataFrame(
        quarantine_rows, columns=list(V3_QUARANTINE_FIELDS)
    )
    for field in quarantine.columns:
        reopened_quarantine[field] = reopened_quarantine[field].astype(
            quarantine[field].dtype
        )
    try:
        pd.testing.assert_frame_equal(
            reopened_quarantine.reset_index(drop=True),
            quarantine.reset_index(drop=True),
            check_dtype=True,
        )
    except AssertionError as error:
        raise ValueError("V3 released quarantine disagrees with reopened perimeter") from error
    ordered_manifest = inventory_ordered_manifest_path(V3_INVENTORY_RAW_ROOT)
    if file_sha256(ordered_manifest) != certificate.get("ordered_raw_manifest_sha256"):
        raise ValueError("V3 ordered raw manifest digest disagrees")
    if int(perimeter["raw_logs"]) != int(certificate.get("raw_inventory_logs", -1)):
        raise ValueError("V3 raw inventory total disagrees")
    snapshot = certified_header_snapshot_path(expected_days, certificate)
    if file_sha256(snapshot) != certificate.get("block_header_snapshot_sha256"):
        raise ValueError("V3 block-header snapshot digest disagrees")
    timestamps = load_block_timestamps(snapshot)
    day_ranges = ranges_by_day(ranges, days, end_blocks)
    positions = {day: index for index, day in enumerate(days)}
    summaries: list[dict[str, object]] = []
    observed_blocks: set[int] = set()
    for day in expected_days:
        position = positions[day]
        lower = start if position == 0 else end_blocks[position - 1] + 1
        upper = end_blocks[position]
        def decoded_events():
            for block_lower, block_upper in day_ranges[day]:
                for event in iter_decoded_inventory_logs(
                    inventory_chunk_paths(
                        block_lower, block_upper, V3_INVENTORY_RAW_ROOT
                    )[0],
                    lower=lower,
                    upper=upper,
                    pools=set(authorities),
                ):
                    if event["event_type"] not in V3_CORE_EVENTS:
                        continue
                    observed_blocks.add(int(event["block_number"]))
                    yield event

        exact = exact_event_map(decoded_events(), authorities, timestamps)
        canonical, occurrences = canonical_event_map(
            read_tick_partition("uniswap_v3", day), authorities
        )
        day_summary, day_exceptions = compare_event_maps(
            day, exact, canonical, occurrences
        )
        if day_exceptions:
            raise ValueError(f"V3 reopened evidence has exceptions on {day}")
        summaries.extend(day_summary)
    if block_perimeter_sha256(observed_blocks) != certificate.get(
        "block_perimeter_sha256"
    ):
        raise ValueError("V3 reopened event-block perimeter disagrees")
    observed = pd.DataFrame(summaries, columns=list(summary.columns))
    for field in summary.columns:
        observed[field] = observed[field].astype(summary[field].dtype)
    try:
        pd.testing.assert_frame_equal(
            observed.reset_index(drop=True), summary.reset_index(drop=True), check_dtype=True
        )
    except AssertionError as error:
        raise ValueError("V3 released summary disagrees with independently reopened evidence") from error
    current_corrections = correction_generation_records(RAW_ROOT, expected_days)
    if correction_generation_sha256(current_corrections) != certificate.get(
        "correction_generations_sha256"
    ):
        raise ValueError("V3 correction-generation identity disagrees")
    return len(authorities), int(summary["exact_events"].sum())
