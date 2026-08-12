"""Retro-certify installed raw generations without relabelling their query history."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
import subprocess
from copy import deepcopy
from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

from ddvc.artifact_release import canonical_json_sha256, file_sha256, is_sha256
from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.sources import get_source, iter_days
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.graphql_selection import selected_paths
from ddvc.fetch.dune import (
    DUNE_QUERY_END_EXCLUSIVE_FIELD,
    DUNE_QUERY_START_FIELD,
    dune_query_contract_sha256,
    validated_dune_query_window,
)
from ddvc.fetch.raw import (
    committed_source_day_generation_identity,
    graph_query_contract_sha256,
    installed_source_day_paths,
    page_size_for_entity,
    query_chunk_policy,
)
from ddvc.paths import DATA_DIR
from ddvc.raw_perimeter import consumer_required_streams
from ddvc.runtime import atomic_output


CERTIFICATE_SCHEMA_VERSION = 1
LOCAL_SCAN_POLICY = "installed-required-raw-local-scan-v4"
LOCAL_CERTIFICATE_POLICY = "installed-required-raw-local-certificate-v1"
RETRO_CERTIFICATION_POLICY = "legacy-raw-generation-retro-certification-v1"
GENERATION_EVIDENCE_POLICY = "raw-capture-generation-evidence-v1"
ADJUDICATION_EVIDENCE_POLICY = "raw-generation-adjudication-evidence-v1"
ADJUDICATION_ARTIFACT_POLICY = "raw-generation-adjudication-artifact-v1"
FETCH_CODE_ARTIFACT_POLICY = "raw-fetch-code-artifact-v1"
QUERY_ARTIFACT_POLICY = "raw-query-artifact-v1"
SELECTION_FRAME_POLICY = "raw-comparison-selection-frame-v1"
COMPARISON_ENGINE_POLICY = "raw-identity-ledger-comparison-v1"
COMPARISON_ENGINE_CONTRACT = {
    "policy": COMPARISON_ENGINE_POLICY,
    "row_fields": ["day", "identity", "quantities"],
    "identity_key": "canonical_json(identity)",
    "quantity_comparison": "canonical_json(quantities)",
}
COMPARISON_CONTRACT_POLICY = "raw-comparison-field-contract-v1"
GENERATION_KINDS = frozenset(
    {
        "legacy_unfrozen_graph",
        "legacy_unfrozen_dune",
        "current_frozen_graph",
        "dune_sql_export",
        "independent_import",
    }
)
ADJUDICATION_KINDS = frozenset(
    {"fresh_stratified_comparison", "independent_event_certificate"}
)
REQUIRED_COMPARISON_STRATA = frozenset(
    {
        "early_quiet",
        "early_busy",
        "middle_quiet",
        "middle_busy",
        "late_quiet",
        "late_busy",
    }
)


@dataclass(frozen=True, order=True)
class RawPartition:
    source: str
    stream: str
    day: str


@dataclass(frozen=True)
class FieldContract:
    required_paths: tuple[str, ...]
    timestamp_path: str
    identity_path: str
    order_path: str | None = None
    required_any_paths: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ComparisonContract:
    identity_fields: tuple[str, ...]
    quantity_fields: tuple[str, ...]


ROUTE_SWAP_FIELDS: dict[str, tuple[str, ...]] = {
    "uniswap_v2": (
        "id",
        "transaction.id",
        "transaction.blockNumber",
        "transaction.timestamp",
        "timestamp",
        "pair.id",
        "pair.token0.id",
        "pair.token1.id",
        "amount0In",
        "amount0Out",
        "amount1In",
        "amount1Out",
        "amountUSD",
        "logIndex",
    ),
    "uniswap_v3": (
        "id",
        "transaction.id",
        "transaction.blockNumber",
        "transaction.timestamp",
        "timestamp",
        "pool.id",
        "pool.token0.id",
        "pool.token1.id",
        "amount0",
        "amount1",
        "sqrtPriceX96",
        "tick",
        "logIndex",
    ),
    "uniswap_v4": (
        "id",
        "transaction.id",
        "transaction.blockNumber",
        "transaction.timestamp",
        "timestamp",
        "pool.id",
        "pool.token0.id",
        "pool.token1.id",
        "amount0",
        "amount1",
        "logIndex",
    ),
    "messari": (
        "id",
        "hash",
        "logIndex",
        "blockNumber",
        "timestamp",
        "tokenIn.id",
        "tokenOut.id",
        "amountIn",
        "amountOut",
        "amountInUSD",
        "amountOutUSD",
        "pool.id",
    ),
    "balancer": (
        "id",
        "tx",
        "block",
        "timestamp",
        "tokenIn",
        "tokenOut",
        "tokenAmountIn",
        "tokenAmountOut",
        "valueUSD",
        "poolId.id",
    ),
    "fluid": (
        "tx_hash",
        "evt_index",
        "block_number",
        "block_time",
        "token_sold_address",
        "token_sold_amount",
        "token_bought_address",
        "token_bought_amount",
        "amount_usd",
        "pool",
    ),
}


def _field_contracts() -> dict[tuple[str, str], FieldContract]:
    v2_event = (
        "id",
        "transaction.id",
        "transaction.blockNumber",
        "transaction.timestamp",
        "timestamp",
        "pair.id",
        "pair.token0.id",
        "pair.token0.decimals",
        "pair.token1.id",
        "pair.token1.decimals",
        "amount0",
        "amount1",
        "logIndex",
    )
    v3_liquidity = (
        "id",
        "transaction.id",
        "transaction.blockNumber",
        "transaction.timestamp",
        "timestamp",
        "pool.id",
        "amount",
        "amount0",
        "amount1",
        "tickLower",
        "tickUpper",
        "logIndex",
    )
    contracts: dict[tuple[str, str], FieldContract] = {}
    for source in ("uniswap_v2", "sushiswap_v2"):
        contracts[(source, "swaps")] = FieldContract(
            ROUTE_SWAP_FIELDS["uniswap_v2"], "timestamp", "id"
        )
        contracts[(source, "hourly_reserves")] = FieldContract(
            (
                "id",
                "hourStartUnix",
                "pair.id",
                "pair.token0.id",
                "pair.token0.decimals",
                "pair.token1.id",
                "pair.token1.decimals",
                "reserve0",
                "reserve1",
            ),
            "hourStartUnix",
            "id",
        )
        for stream in ("mints", "burns"):
            contracts[(source, stream)] = FieldContract(
                v2_event, "timestamp", "id"
            )
        daily_fields = ["id", "date", "pairAddress", "reserveUSD", "dailyVolumeUSD"]
        if source == "sushiswap_v2":
            daily_fields.extend(("token0.id", "token1.id"))
        contracts[(source, "daily")] = FieldContract(
            tuple(daily_fields), "date", "id"
        )
    contracts[("uniswap_v3", "swaps")] = FieldContract(
        ROUTE_SWAP_FIELDS["uniswap_v3"], "timestamp", "id"
    )
    contracts[("uniswap_v3", "mints")] = FieldContract(
        v3_liquidity, "timestamp", "id"
    )
    contracts[("uniswap_v3", "burns")] = FieldContract(
        v3_liquidity, "timestamp", "id"
    )
    contracts[("uniswap_v3", "daily")] = FieldContract(
        ("id", "date", "pool.id", "tvlUSD", "volumeUSD"), "date", "id"
    )
    contracts[("uniswap_v4", "swaps")] = FieldContract(
        ROUTE_SWAP_FIELDS["uniswap_v4"], "timestamp", "id"
    )
    contracts[("uniswap_v4", "modify_liquidities")] = FieldContract(
        v3_liquidity, "timestamp", "id"
    )
    contracts[("uniswap_v4", "daily")] = FieldContract(
        (
            "id",
            "date",
            "pool.id",
            "pool.token0.id",
            "pool.token1.id",
            "tvlUSD",
            "volumeUSD",
        ),
        "date",
        "id",
    )
    for source in ("curve", "sushiswap_v3"):
        contracts[(source, "swaps")] = FieldContract(
            ROUTE_SWAP_FIELDS["messari"], "timestamp", "id"
        )
    contracts[("curve", "daily")] = FieldContract(
        (
            "id",
            "timestamp",
            "inputTokenBalances",
            "pool.id",
            "pool.inputTokens[].id",
            "pool.inputTokens[].decimals",
            "pool.symbol",
        ),
        "timestamp",
        "id",
    )
    contracts[("balancer", "swaps")] = FieldContract(
        ROUTE_SWAP_FIELDS["balancer"], "timestamp", "id"
    )
    contracts[("balancer", "daily")] = FieldContract(
        (
            "id",
            "timestamp",
            "amounts",
            "pool.id",
            "pool.poolType",
            "pool.swapFee",
            "pool.tokensList",
            "pool.tokens[].address",
            "pool.tokens[].decimals",
        ),
        "timestamp",
        "id",
    )
    contracts[("balancer", "joins_exits")] = FieldContract(
        (
            "id",
            "tx",
            "block",
            "timestamp",
            "type",
            "amounts",
            "pool.id",
            "pool.tokensList",
        ),
        "timestamp",
        "id",
    )
    contracts[("fluid", "swaps")] = FieldContract(
        ROUTE_SWAP_FIELDS["fluid"], "block_time", "tx_hash", "evt_index"
    )
    return contracts


FIELD_CONTRACTS = _field_contracts()


def comparison_contract(source: str, stream: str) -> ComparisonContract:
    field_contract = FIELD_CONTRACTS[(source, stream)]
    required = set(field_contract.required_paths).union(
        *(set(group) for group in field_contract.required_any_paths)
    )
    causal_candidates = (
        ("transaction.blockNumber", "transaction.id", "logIndex"),
        ("block_number", "tx_hash", "evt_index"),
        ("blockNumber", "hash", "logIndex"),
        ("block", "tx", "id"),
    )
    identity = next(
        (candidate for candidate in causal_candidates if set(candidate).issubset(required)),
        (field_contract.identity_path,),
    )
    timestamp_fields = {
        field_contract.timestamp_path,
        "timestamp",
        "transaction.timestamp",
        "block_time",
        "date",
        "hourStartUnix",
    }
    quantities = tuple(
        sorted(required.difference(identity).difference(timestamp_fields))
    )
    if not quantities:
        raise RuntimeError(f"comparison contract lacks signed quantity fields: {source}/{stream}")
    return ComparisonContract(tuple(identity), quantities)


def comparison_contract_identity(source: str, stream: str) -> str:
    contract = comparison_contract(source, stream)
    return canonical_json_sha256(
        {
            "policy": COMPARISON_CONTRACT_POLICY,
            "source": source,
            "stream": stream,
            "identity_fields": contract.identity_fields,
            "quantity_fields": contract.quantity_fields,
        }
    )


def comparison_selection_frame(
    local_partitions: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, str]]:
    local = sorted(local_partitions, key=lambda item: str(item.get("day")))
    population = [
        {
            "day": item.get("day"),
            "activity_rows": item.get("rows"),
            "logical_content_sha256": item.get("logical_content_sha256"),
        }
        for item in local
    ]
    if any(
        not isinstance(item["day"], str)
        or isinstance(item["activity_rows"], bool)
        or not isinstance(item["activity_rows"], int)
        or int(item["activity_rows"]) < 0
        or not is_sha256(item["logical_content_sha256"])
        for item in population
    ):
        raise ValueError("local partitions cannot support a comparison selection frame")
    days = [str(item["day"]) for item in population]
    windows = _expected_selection_windows(days)
    activity = {str(item["day"]): int(item["activity_rows"]) for item in population}
    strata: dict[str, str] = {}
    for name, candidates in windows.items():
        strata[f"{name}_quiet"] = min(
            candidates, key=lambda day: (activity[day], day)
        )
        strata[f"{name}_busy"] = max(
            candidates, key=lambda day: (activity[day], day)
        )
    frame = {
        "policy": SELECTION_FRAME_POLICY,
        "activity_metric": "legacy_rows",
        "tie_rule": "quiet=min(activity_rows,day);busy=max(activity_rows,day)",
        "candidate_start": days[0],
        "candidate_end": days[-1],
        "window_boundaries": {
            name: {"start": candidates[0], "end": candidates[-1]}
            for name, candidates in windows.items()
        },
        "candidate_population": population,
        "candidate_population_sha256": canonical_json_sha256(population),
    }
    return frame, strata


def active_consumer_streams() -> dict[str, frozenset[str]]:
    """Return the canonical perimeter after checking certification contracts."""

    required = consumer_required_streams()
    if missing := sorted(
        (source, stream)
        for source, streams in required.items()
        for stream in streams
        if (source, stream) not in FIELD_CONTRACTS
    ):
        raise RuntimeError(f"active raw streams lack consumer field contracts: {missing}")
    return required


def research_end_exclusive() -> dt.date:
    return dt.datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").date() + dt.timedelta(days=1)


def required_partitions(
    *,
    end_exclusive: dt.date | None = None,
    required: Mapping[str, Iterable[str]] | None = None,
    genesis: Mapping[str, dt.date] | None = None,
) -> tuple[RawPartition, ...]:
    end = end_exclusive or research_end_exclusive()
    streams_by_source = required or active_consumer_streams()
    starts = genesis or {source: get_source(source).genesis for source in streams_by_source}
    return tuple(
        RawPartition(source, stream, day.strftime("%Y%m%d"))
        for source in sorted(streams_by_source)
        for stream in sorted(streams_by_source[source])
        for day in iter_days(starts[source], end)
    )


def contract_identity(source: str, stream: str) -> str:
    contract = FIELD_CONTRACTS[(source, stream)]
    return canonical_json_sha256(
        {
            "policy": LOCAL_SCAN_POLICY,
            "source": source,
            "stream": stream,
            "required_paths": contract.required_paths,
            "timestamp_path": contract.timestamp_path,
            "identity_path": contract.identity_path,
            "order_path": contract.order_path,
            "required_any_paths": contract.required_any_paths,
        }
    )


def generation_identity(entry: Mapping[str, object]) -> str:
    return canonical_json_sha256(
        {
            "source": entry.get("source"),
            "stream": entry.get("stream"),
            "generation_kind": entry.get("generation_kind"),
            "provenance_status": entry.get("provenance_status"),
            "fetch_code_identity_sha256": entry.get("fetch_code_identity_sha256"),
            "fetch_code_artifact_sha256": entry.get("fetch_code_artifact_sha256"),
            "query_generation_identity_sha256": entry.get(
                "query_generation_identity_sha256"
            ),
            "query_artifact_sha256": entry.get("query_artifact_sha256"),
        }
    )


def _partition_identity(partition: RawPartition | Mapping[str, object]) -> tuple[str, str, str]:
    if isinstance(partition, RawPartition):
        return partition.source, partition.stream, partition.day
    return (
        str(partition.get("source")),
        str(partition.get("stream")),
        str(partition.get("day")),
    )


def require_exact_partition_perimeter(
    partitions: Iterable[RawPartition | Mapping[str, object]],
) -> list[tuple[str, str, str]]:
    observed = [_partition_identity(partition) for partition in partitions]
    expected = [_partition_identity(partition) for partition in required_partitions()]
    if observed != expected:
        observed_set = set(observed)
        expected_set = set(expected)
        missing = sorted(expected_set - observed_set)[:3]
        extra = sorted(observed_set - expected_set)[:3]
        duplicate_count = len(observed) - len(observed_set)
        raise ValueError(
            "raw certificate partition perimeter mismatch: "
            f"observed={len(observed)}, expected={len(expected)}, "
            f"duplicates={duplicate_count}, missing={missing}, extra={extra}"
        )
    return observed


def _partition_path(data_root: Path, partition: RawPartition) -> Path:
    backend = get_source(partition.source).backend
    return (
        data_root
        / "raw"
        / ("dune" if backend == "dune" else "thegraph")
        / partition.source
        / f"{partition.source}_{partition.stream}_{partition.day}.jsonl.gz"
    )


def _metadata_path(data_root: Path, partition: RawPartition) -> Path:
    backend = get_source(partition.source).backend
    return (
        data_root
        / "raw"
        / ("dune" if backend == "dune" else "thegraph")
        / partition.source
        / f"{partition.source}_meta_{partition.day}.json"
    )


def _path_values(value: object, dotted: str) -> list[object]:
    values = [value]
    for part in dotted.split("."):
        repeated = part.endswith("[]")
        key = part[:-2] if repeated else part
        next_values: list[object] = []
        for item in values:
            if not isinstance(item, Mapping) or key not in item:
                return []
            child = item[key]
            if repeated:
                if not isinstance(child, list) or not child:
                    return []
                next_values.extend(child)
            else:
                next_values.append(child)
        values = next_values
    return values


def _populated_path(value: object, dotted: str) -> bool:
    values = _path_values(value, dotted)
    return bool(values) and all(
        item is not None
        and (not isinstance(item, str) or bool(item.strip()))
        and (not isinstance(item, (list, tuple, dict, set)) or bool(item))
        for item in values
    )


def write_normalized_legacy_ledger(
    data_root: Path,
    source: str,
    stream: str,
    days: Iterable[str],
    output: Path,
) -> int:
    """Retain the exact comparison fields for selected installed raw days."""

    contract = comparison_contract(source, stream)
    rows_written = 0
    with atomic_output(output) as temporary:
        with temporary.open("w", encoding="utf-8") as destination:
            for day in sorted(set(days)):
                partition = RawPartition(source, stream, day)
                path = _partition_path(data_root, partition)
                if not path.is_file():
                    raise ValueError(f"selected legacy partition is missing: {source}/{stream}/{day}")
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"selected legacy partition is malformed: {source}/{stream}/{day}"
                            ) from exc
                        if not isinstance(raw, dict):
                            raise ValueError(
                                f"selected legacy partition has a non-object row: {source}/{stream}/{day}"
                            )

                        def retained(
                            fields: Iterable[str], *, nullable: set[str] | None = None
                        ) -> dict[str, object]:
                            values: dict[str, object] = {}
                            for field in fields:
                                observed = _path_values(raw, field)
                                if not observed:
                                    if field in (nullable or set()):
                                        values[field] = None
                                        continue
                                    raise ValueError(
                                        f"selected legacy row lacks comparison field {field}: "
                                        f"{source}/{stream}/{day}"
                                    )
                                values[field] = (
                                    observed if "[]" in field or len(observed) != 1 else observed[0]
                                )
                            return values

                        destination.write(
                            json.dumps(
                                {
                                    "day": day,
                                    "identity": retained(contract.identity_fields),
                                    "quantities": retained(
                                        contract.quantity_fields,
                                        nullable={
                                            field
                                            for group in FIELD_CONTRACTS[
                                                (source, stream)
                                            ].required_any_paths
                                            for field in group
                                        },
                                    ),
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        rows_written += 1
    return rows_written


def _timestamp(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        normalized = str(value).replace(" UTC", "+00:00").replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return None


def _metadata_observations(path: Path, partition: RawPartition) -> dict[str, object]:
    if not path.is_file():
        return {"metadata_present": False, "metadata_error": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "metadata_present": True,
            "metadata_error": f"metadata_unreadable:{type(exc).__name__}",
        }
    error = None
    if payload.get("source", payload.get("dex")) != partition.source:
        error = "metadata_source_identity"
    observed_day = str(payload.get("day") or "").replace("-", "")
    if observed_day != partition.day:
        error = "metadata_day_identity"
    stream_item = (payload.get("streams") or {}).get(partition.stream) or {}
    recorded_rows = stream_item.get("rows")
    if isinstance(recorded_rows, bool):
        error = error or "metadata_row_count"
        recorded_rows = None
    if not isinstance(recorded_rows, int):
        fallback = "pool_days" if partition.stream == "daily" else partition.stream
        recorded_rows = payload.get(fallback)
        if isinstance(recorded_rows, bool):
            error = error or "metadata_row_count"
            recorded_rows = None
    return {
        "metadata_present": True,
        "metadata_error": error,
        "metadata_sha256": file_sha256(path),
        "recorded_rows": (
            recorded_rows
            if isinstance(recorded_rows, int) and not isinstance(recorded_rows, bool)
            else None
        ),
        "observed_query_contract_sha256": stream_item.get("query_contract_sha256"),
        "observed_query_start_date": stream_item.get(DUNE_QUERY_START_FIELD),
        "observed_query_end_date_exclusive": stream_item.get(
            DUNE_QUERY_END_EXCLUSIVE_FIELD
        ),
        "metadata_logical_content_sha256": stream_item.get(
            "logical_content_sha256"
        ),
        "observed_head_block_at_fetch": stream_item.get(
            "head_block_at_fetch", payload.get("head_block_at_fetch")
        ),
    }


def _scan_partition(data_root_text: str, partition: RawPartition) -> dict[str, object]:
    data_root = Path(data_root_text)
    path = _partition_path(data_root, partition)
    relative = str(path.relative_to(data_root))
    contract = FIELD_CONTRACTS[(partition.source, partition.stream)]
    errors: set[str] = set()
    if not path.is_file():
        return {
            "source": partition.source,
            "stream": partition.stream,
            "day": partition.day,
            "path": relative,
            "contract_sha256": contract_identity(partition.source, partition.stream),
            "local_pass": False,
            "errors": ["missing_file"],
        }
    metadata = _metadata_observations(_metadata_path(data_root, partition), partition)
    if metadata.get("metadata_error"):
        errors.add(str(metadata["metadata_error"]))
    logical = hashlib.sha256()
    rows = 0
    first_identity: str | None = None
    last_identity: str | None = None
    seen_identities: set[str] = set()
    global_identity_order = True
    hour_identity_order = True
    previous_hour_identity: tuple[int, str] | None = None
    previous_fluid_order: tuple[int, int] | None = None
    lower = int(
        dt.datetime.strptime(partition.day, "%Y%m%d")
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )
    upper = lower + 86_400
    minimum_timestamp: int | None = None
    maximum_timestamp: int | None = None
    try:
        with gzip.open(path, "rb") as handle:
            for raw_line in handle:
                logical.update(raw_line)
                if not raw_line.strip():
                    errors.add("empty_jsonl_line")
                    continue
                rows += 1
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    errors.add("malformed_json")
                    continue
                if not isinstance(row, dict):
                    errors.add("non_object_row")
                    continue
                for required_path in contract.required_paths:
                    if not _populated_path(row, required_path):
                        errors.add(f"missing_field:{required_path}")
                for alternatives in contract.required_any_paths:
                    if not any(_populated_path(row, path) for path in alternatives):
                        errors.add(f"missing_any_field:{'|'.join(alternatives)}")
                identity_values = _path_values(row, contract.identity_path)
                identity = str(identity_values[0]) if identity_values else ""
                if not identity:
                    errors.add("missing_pagination_identity")
                if partition.source == "fluid":
                    order_values = _path_values(row, contract.order_path or "")
                    block_values = _path_values(row, "block_number")
                    timestamp_values = _path_values(row, contract.timestamp_path)
                    timestamp = _timestamp(timestamp_values[0]) if timestamp_values else None
                    try:
                        order = (
                            int(block_values[0]),
                            int(order_values[0]),
                        )
                    except (IndexError, TypeError, ValueError):
                        order = (-1, -1)
                        errors.add("invalid_block_event_order")
                    event_identity = f"{identity}:{order[1]}"
                    if event_identity in seen_identities:
                        errors.add("duplicate_pagination_identity")
                    seen_identities.add(event_identity)
                    if previous_fluid_order is not None and order < previous_fluid_order:
                        errors.add("unstable_pagination_order")
                    previous_fluid_order = order
                else:
                    timestamp_values = _path_values(row, contract.timestamp_path)
                    timestamp = _timestamp(timestamp_values[0]) if timestamp_values else None
                    if identity in seen_identities:
                        errors.add("duplicate_pagination_identity")
                    seen_identities.add(identity)
                    if last_identity is not None and identity <= last_identity:
                        global_identity_order = False
                    hour_identity = ((timestamp or -1) // 3600, identity)
                    if previous_hour_identity is not None and hour_identity <= previous_hour_identity:
                        hour_identity_order = False
                    previous_hour_identity = hour_identity
                if timestamp is None:
                    errors.add("invalid_timestamp")
                elif not lower <= timestamp < upper:
                    errors.add("outside_utc_day")
                else:
                    minimum_timestamp = (
                        timestamp
                        if minimum_timestamp is None
                        else min(minimum_timestamp, timestamp)
                    )
                    maximum_timestamp = (
                        timestamp
                        if maximum_timestamp is None
                        else max(maximum_timestamp, timestamp)
                    )
                first_identity = first_identity or identity or None
                last_identity = identity or last_identity
    except (OSError, EOFError) as exc:
        errors.add(f"gzip_unreadable:{type(exc).__name__}")
    recorded_rows = metadata.get("recorded_rows")
    permits_hour_chunks = partition.stream in {"swaps", "hourly_reserves"}
    if partition.source != "fluid" and not global_identity_order and not (
        permits_hour_chunks and hour_identity_order
    ):
        errors.add("unstable_pagination_order")
    pagination_order_mode = (
        "dune_block_event"
        if partition.source == "fluid"
        else "global_identity"
        if global_identity_order
        else "hour_then_identity"
        if permits_hour_chunks and hour_identity_order
        else "invalid"
    )
    if isinstance(recorded_rows, int) and recorded_rows != rows:
        errors.add("sidecar_row_count_mismatch")
    logical_sha256 = logical.hexdigest()
    metadata_logical_sha256 = metadata.get("metadata_logical_content_sha256")
    if metadata_logical_sha256 is not None and metadata_logical_sha256 != logical_sha256:
        errors.add("sidecar_content_hash_mismatch")
    result = {
        "source": partition.source,
        "stream": partition.stream,
        "day": partition.day,
        "path": relative,
        "container_bytes": path.stat().st_size,
        "container_mtime_ns": path.stat().st_mtime_ns,
        "container_ctime_ns": path.stat().st_ctime_ns,
        "logical_content_sha256": logical_sha256,
        "rows": rows,
        "recorded_rows": recorded_rows,
        "first_pagination_identity": first_identity,
        "last_pagination_identity": last_identity,
        "pagination_order_mode": pagination_order_mode,
        "min_timestamp_utc": minimum_timestamp,
        "max_timestamp_utc": maximum_timestamp,
        "contract_sha256": contract_identity(partition.source, partition.stream),
        "local_pass": not errors,
        "errors": sorted(errors),
        **metadata,
    }
    return result


def _month_shards(partitions: Iterable[RawPartition]) -> dict[str, list[RawPartition]]:
    shards: dict[str, list[RawPartition]] = {}
    for partition in partitions:
        key = f"{partition.source}--{partition.stream}--{partition.day[:6]}"
        shards.setdefault(key, []).append(partition)
    return shards


def _expected_input_stats(
    data_root: Path, partitions: Iterable[RawPartition]
) -> list[dict[str, object]]:
    inputs: list[dict[str, object]] = []
    for partition in partitions:
        for kind, path in (
            ("raw_partition", _partition_path(data_root, partition)),
            ("metadata_sidecar", _metadata_path(data_root, partition)),
        ):
            item: dict[str, object] = {
                "kind": kind,
                "path": str(path.relative_to(data_root)),
            }
            try:
                path_stat = path.stat()
            except OSError:
                item["exists"] = False
            else:
                item.update(
                    {
                        "exists": True,
                        "is_file": path.is_file(),
                        "size": path_stat.st_size,
                        "mtime_ns": path_stat.st_mtime_ns,
                        "ctime_ns": path_stat.st_ctime_ns,
                    }
                )
            inputs.append(item)
    return inputs


def _expected_partition_contracts(
    partitions: Iterable[RawPartition],
) -> list[dict[str, str]]:
    return [
        {
            "source": partition.source,
            "stream": partition.stream,
            "day": partition.day,
            "contract_sha256": contract_identity(partition.source, partition.stream),
        }
        for partition in partitions
    ]


def _cache_current(
    cache: Mapping[str, object],
    data_root: Path,
    partitions: Iterable[RawPartition],
) -> bool:
    inputs = cache.get("input_stats")
    return (
        cache.get("scan_policy") == LOCAL_SCAN_POLICY
        and isinstance(inputs, list)
        and inputs == _expected_input_stats(data_root, partitions)
        and cache.get("partition_contracts")
        == _expected_partition_contracts(partitions)
    )


def _scan_shard(
    data_root_text: str,
    shard_key: str,
    partitions: list[RawPartition],
) -> dict[str, object]:
    data_root = Path(data_root_text)
    input_stats = _expected_input_stats(data_root, partitions)
    results = [_scan_partition(data_root_text, partition) for partition in partitions]
    if input_stats != _expected_input_stats(data_root, partitions):
        raise RuntimeError(f"raw inputs changed while scanning shard {shard_key}")
    return {
        "scan_policy": LOCAL_SCAN_POLICY,
        "shard": shard_key,
        "input_stats": input_stats,
        "partition_contracts": _expected_partition_contracts(partitions),
        "partitions": results,
    }


def scan_installed_generation(
    data_root: Path,
    work_dir: Path,
    *,
    workers: int,
    partitions: Iterable[RawPartition] | None = None,
) -> list[dict[str, object]]:
    """Scan deterministic monthly shards and reuse unchanged completed shards."""

    selected = tuple(sorted(partitions or required_partitions()))
    shards = _month_shards(selected)
    work_dir.mkdir(parents=True, exist_ok=True)
    completed: dict[str, dict[str, object]] = {}
    pending: dict[str, list[RawPartition]] = {}
    for key, members in sorted(shards.items()):
        cache_path = work_dir / f"{key}.json"
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict) and _cache_current(cached, data_root, members):
            completed[key] = cached
        else:
            pending[key] = members
    if pending and workers == 1:
        for key, members in pending.items():
            payload = _scan_shard(str(data_root), key, members)
            with atomic_output(work_dir / f"{key}.json") as temporary:
                temporary.write_text(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
            completed[key] = payload
    elif pending:
        with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(_scan_shard, str(data_root), key, members): key
                for key, members in pending.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                payload = future.result()
                with atomic_output(work_dir / f"{key}.json") as temporary:
                    temporary.write_text(
                        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                completed[key] = payload
    return sorted(
        (
            partition
            for key in sorted(completed)
            for partition in completed[key]["partitions"]
        ),
        key=lambda item: (item["source"], item["stream"], item["day"]),
    )


def write_local_scan_ledger(path: Path, partitions: Iterable[Mapping[str, object]]) -> dict[str, object]:
    ordered = sorted(
        partitions,
        key=lambda item: (item["source"], item["stream"], item["day"]),
    )
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for item in ordered:
                handle.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
    failures = [item for item in ordered if not item.get("local_pass")]
    return {
        "policy": LOCAL_SCAN_POLICY,
        "partitions": len(ordered),
        "passed": len(ordered) - len(failures),
        "failed": len(failures),
        "ledger": path.name,
        "ledger_sha256": file_sha256(path),
        "failed_source_streams": sorted(
            {f"{item['source']}/{item['stream']}" for item in failures}
        ),
    }


def write_local_scan_certificate(
    output: Path,
    partitions: Iterable[Mapping[str, object]],
    *,
    expected_partitions: Iterable[RawPartition],
    ledger_path: Path | None = None,
) -> dict[str, object]:
    """Publish one content-bound installed-generation scan without overstating provenance."""

    ordered = sorted(
        (dict(item) for item in partitions),
        key=lambda item: (item["source"], item["stream"], item["day"]),
    )
    expected = tuple(sorted(expected_partitions))
    actual = tuple(
        RawPartition(str(item["source"]), str(item["stream"]), str(item["day"]))
        for item in ordered
    )
    if actual != expected:
        raise ValueError("local scan certificate perimeter mismatch")
    for item, partition in zip(ordered, expected):
        if item.get("local_pass") is not True or item.get("errors") != []:
            raise ValueError(
                f"local scan certificate contains failed partition: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        if item.get("contract_sha256") != contract_identity(
            partition.source, partition.stream
        ):
            raise ValueError(
                f"local scan certificate contains stale contract: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        if not is_sha256(item.get("logical_content_sha256")):
            raise ValueError(
                f"local scan certificate lacks content identity: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        if (
            not isinstance(item.get("container_bytes"), int)
            or not isinstance(item.get("container_mtime_ns"), int)
            or not isinstance(item.get("container_ctime_ns"), int)
        ):
            raise ValueError(
                f"local scan certificate lacks cheap mutation identity: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        metadata_present = item.get("metadata_present")
        if not isinstance(metadata_present, bool) or (
            metadata_present and not is_sha256(item.get("metadata_sha256"))
        ):
            raise ValueError(
                f"local scan certificate lacks metadata identity: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
    ledger = ledger_path or output.with_suffix(".partitions.jsonl")
    if ledger.resolve() == output.resolve():
        raise ValueError("local scan ledger and certificate paths must be distinct")
    if ledger.parent.resolve() != output.parent.resolve():
        raise ValueError("local scan ledger and certificate must be siblings")
    write_local_scan_ledger(ledger, ordered)
    certificate = {
        "schema_version": CERTIFICATE_SCHEMA_VERSION,
        "policy": LOCAL_CERTIFICATE_POLICY,
        "status": "passed",
        "scan_policy": LOCAL_SCAN_POLICY,
        "partition_ledger": ledger.name,
        "partition_ledger_sha256": file_sha256(ledger),
        "partition_count": len(ordered),
        "partition_perimeter_sha256": canonical_json_sha256(
            [partition.__dict__ for partition in expected]
        ),
        "active_consumer_contracts_sha256": canonical_json_sha256(
            {
                f"{source}/{stream}": contract_identity(source, stream)
                for source, stream in sorted(
                    {(partition.source, partition.stream) for partition in expected}
                )
            }
        ),
        "provenance_scope": "installed payload integrity and active consumer fields only",
        "asserts_current_frozen_head_query_contract": False,
    }
    body = {
        **certificate,
        "certificate_sha256": canonical_json_sha256(certificate),
    }
    with atomic_output(output) as temporary:
        temporary.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return body


@lru_cache(maxsize=16)
def _load_certified_ledger_cached(
    certificate_path_text: str,
    certificate_stat: tuple[int, int, int],
    ledger_path_text: str,
    ledger_stat: tuple[int, int, int],
) -> tuple[dict[str, object], str, tuple[dict[str, object], ...]]:
    del certificate_stat, ledger_stat
    certificate_path = Path(certificate_path_text)
    ledger_path = Path(ledger_path_text)
    certificate = _load_json(certificate_path, "local scan certificate")
    recorded_certificate_sha256 = certificate.pop("certificate_sha256", None)
    if (
        certificate.get("policy") != LOCAL_CERTIFICATE_POLICY
        or certificate.get("schema_version") != CERTIFICATE_SCHEMA_VERSION
        or certificate.get("status") != "passed"
        or certificate.get("scan_policy") != LOCAL_SCAN_POLICY
        or certificate.get("asserts_current_frozen_head_query_contract") is not False
        or recorded_certificate_sha256 != canonical_json_sha256(certificate)
    ):
        raise ValueError("local scan certificate envelope mismatch")
    if not ledger_path.is_file() or file_sha256(ledger_path) != certificate.get(
        "partition_ledger_sha256"
    ):
        raise ValueError("local scan certificate partition ledger mismatch")
    rows: list[dict[str, object]] = []
    try:
        with ledger_path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("local scan ledger rows must be JSON objects")
                rows.append(item)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("local scan certificate partition ledger is unreadable") from exc
    identities = tuple(
        RawPartition(str(item.get("source")), str(item.get("stream")), str(item.get("day")))
        for item in rows
    )
    if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
        raise ValueError("local scan certificate partition ledger is unordered or duplicated")
    if (
        certificate.get("partition_count") != len(rows)
        or certificate.get("partition_perimeter_sha256")
        != canonical_json_sha256([partition.__dict__ for partition in identities])
    ):
        raise ValueError("local scan certificate partition perimeter mismatch")
    pairs = {(partition.source, partition.stream) for partition in identities}
    if certificate.get("active_consumer_contracts_sha256") != canonical_json_sha256(
        {
            f"{source}/{stream}": contract_identity(source, stream)
            for source, stream in sorted(pairs)
        }
    ):
        raise ValueError("local scan certificate consumer contracts changed")
    for partition, item in zip(identities, rows):
        backend = get_source(partition.source).backend
        expected_relative = (
            f"raw/{backend}/{partition.source}/"
            f"{partition.source}_{partition.stream}_{partition.day}.jsonl.gz"
        )
        if (
            item.get("path") != expected_relative
            or item.get("local_pass") is not True
            or item.get("errors") != []
            or item.get("contract_sha256")
            != contract_identity(partition.source, partition.stream)
            or not is_sha256(item.get("logical_content_sha256"))
            or not isinstance(item.get("metadata_present"), bool)
            or (
                item.get("metadata_present") is True
                and not is_sha256(item.get("metadata_sha256"))
            )
        ):
            raise ValueError(
                f"local scan certificate row mismatch: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
    return certificate, str(recorded_certificate_sha256), tuple(rows)


def load_certified_partition_ledger(
    certificate_path: Path,
    *,
    data_root: Path = DATA_DIR,
    partitions: Iterable[RawPartition] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Validate one local scan release without a second pass through gzip payloads."""

    preview = _load_json(certificate_path, "local scan certificate")
    ledger_path = certificate_path.with_name(
        str(preview.get("partition_ledger") or "")
    )
    if not ledger_path.is_file():
        raise ValueError("local scan certificate partition ledger mismatch")
    certificate_file_stat = certificate_path.stat()
    ledger_file_stat = ledger_path.stat()
    certificate, recorded_certificate_sha256, cached_rows = _load_certified_ledger_cached(
        str(certificate_path.resolve()),
        (
            certificate_file_stat.st_size,
            certificate_file_stat.st_mtime_ns,
            certificate_file_stat.st_ctime_ns,
        ),
        str(ledger_path.resolve()),
        (
            ledger_file_stat.st_size,
            ledger_file_stat.st_mtime_ns,
            ledger_file_stat.st_ctime_ns,
        ),
    )
    rows = list(cached_rows)
    identities = tuple(
        RawPartition(str(item.get("source")), str(item.get("stream")), str(item.get("day")))
        for item in rows
    )
    indexed = dict(zip(identities, rows))
    selected = tuple(sorted(partitions)) if partitions is not None else identities
    if missing := [partition for partition in selected if partition not in indexed]:
        first = missing[0]
        raise ValueError(
            f"local scan certificate does not cover requested partition: "
            f"{first.source}/{first.stream}/{first.day}"
        )
    cached_selected_rows = [indexed[partition] for partition in selected]
    for partition, item in zip(selected, cached_selected_rows):
        expected_path = _partition_path(data_root, partition)
        if not expected_path.is_file():
            raise ValueError(
                f"certified raw partition is missing: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        if item.get("contract_sha256") != contract_identity(
            partition.source, partition.stream
        ):
            raise ValueError(
                f"certified raw partition consumer contract changed: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        metadata_path = _metadata_path(data_root, partition)
        expected_metadata_present = item.get("metadata_present") is True
        if metadata_path.is_file() != expected_metadata_present:
            raise ValueError(
                f"certified raw metadata presence changed after scan: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        if expected_metadata_present and file_sha256(metadata_path) != item.get(
            "metadata_sha256"
        ):
            raise ValueError(
                f"certified raw metadata changed after scan: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
        stat = expected_path.stat()
        if (
            item.get("container_bytes") != stat.st_size
            or item.get("container_mtime_ns") != stat.st_mtime_ns
            or item.get("container_ctime_ns") != stat.st_ctime_ns
        ):
            raise ValueError(
                f"certified raw partition changed after scan: "
                f"{partition.source}/{partition.stream}/{partition.day}"
            )
    selected_identity = [
        {
            "source": item["source"],
            "stream": item["stream"],
            "day": item["day"],
            "logical_content_sha256": item["logical_content_sha256"],
            "contract_sha256": item["contract_sha256"],
            "observed_query_contract_sha256": item.get(
                "observed_query_contract_sha256"
            ),
            "observed_head_block_at_fetch": item.get("observed_head_block_at_fetch"),
            "metadata_sha256": item.get("metadata_sha256"),
        }
        for item in cached_selected_rows
    ]
    selected_rows = [deepcopy(item) for item in cached_selected_rows]
    return selected_rows, {
        "policy": LOCAL_CERTIFICATE_POLICY,
        "certificate_sha256": recorded_certificate_sha256,
        "partition_ledger_sha256": certificate["partition_ledger_sha256"],
        "partition_count": len(rows),
        "selected_partition_count": len(cached_selected_rows),
        "selected_partition_identity_sha256": canonical_json_sha256(selected_identity),
    }


def local_scan_certificate_path(
    source: str, *, data_root: Path = DATA_DIR
) -> Path:
    """Canonical per-source local-integrity certificate location."""

    return data_root / "processed" / "raw_generation" / f"{source}_local_certificate.json"


def raw_partition_read_authority(
    source: str,
    stream: str,
    day: str,
    *,
    data_root: Path,
) -> dict[str, object]:
    """Resolve the exact authority and logical hash for one installed partition."""

    def file_generation(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def source_registry_generation() -> str:
        source_record = get_source(source)
        values: dict[str, object] = {}
        for field in fields(source_record):
            value = getattr(source_record, field.name)
            values[field.name] = value.isoformat() if isinstance(value, dt.date) else value
        return canonical_json_sha256(values)

    parsed_day = dt.datetime.strptime(day, "%Y%m%d").date()
    path, marker_path = installed_source_day_paths(
        source, stream, parsed_day, data_root=data_root
    )
    marker_payload: object | None = None
    marker_has_promotion = False
    if marker_path.is_file():
        try:
            marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker_has_promotion = True
        else:
            marker_has_promotion = not isinstance(marker_payload, dict) or (
                "promotion" in marker_payload
            )
    if marker_has_promotion:
        committed_generation_identity = committed_source_day_generation_identity(
            source, stream, parsed_day, data_root=data_root
        )
        marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
        stream_marker = marker_payload["streams"][stream]
        expected_hash = stream_marker["logical_content_sha256"]
        registry_generation = source_registry_generation()
        generation_identity = canonical_json_sha256(
            {
                "committed_generation_identity_sha256": committed_generation_identity,
                "source_registry_generation_sha256": registry_generation,
            }
        )
        return {
            "authority_kind": "promoted-source-day-v1",
            "path": path,
            "path_generation": file_generation(path),
            "authority_generation": file_generation(marker_path),
            "source_registry_generation": registry_generation,
            "logical_content_sha256": expected_hash,
            "contract_sha256": contract_identity(source, stream),
            "metadata_present": True,
            "metadata_sha256": file_sha256(marker_path),
            "observed_query_contract_sha256": stream_marker.get(
                "query_contract_sha256"
            ),
            "observed_head_block_at_fetch": stream_marker.get(
                "head_block_at_fetch", marker_payload.get("head_block_at_fetch")
            ),
            "observed_query_start_date": stream_marker.get(
                DUNE_QUERY_START_FIELD
            ),
            "observed_query_end_date_exclusive": stream_marker.get(
                DUNE_QUERY_END_EXCLUSIVE_FIELD
            ),
            "generation_identity_sha256": generation_identity,
        }
    partition = RawPartition(source, stream, day)
    certificate_path = local_scan_certificate_path(source, data_root=data_root)
    rows, authority = load_certified_partition_ledger(
        certificate_path,
        data_root=data_root,
        partitions=[partition],
    )
    certificate = _load_json(certificate_path, "local scan certificate")
    ledger_path = certificate_path.with_name(str(certificate["partition_ledger"]))
    metadata_path = _metadata_path(data_root, partition)
    row = rows[0]
    registry_generation = source_registry_generation()
    generation_identity = canonical_json_sha256(
        {
            "authority": authority,
            "source": source,
            "stream": stream,
            "day": day,
            "logical_content_sha256": row["logical_content_sha256"],
            "contract_sha256": row["contract_sha256"],
            "observed_query_contract_sha256": row.get(
                "observed_query_contract_sha256"
            ),
            "observed_head_block_at_fetch": row.get(
                "observed_head_block_at_fetch"
            ),
            "metadata_sha256": row.get("metadata_sha256"),
            "source_registry_generation_sha256": registry_generation,
        }
    )
    return {
        "authority_kind": LOCAL_CERTIFICATE_POLICY,
        "path": path,
        "path_generation": file_generation(path),
        "authority_generation": (
            file_generation(certificate_path),
            file_generation(ledger_path),
        ),
        "metadata_generation": (
            file_generation(metadata_path)
            if row.get("metadata_present") is True
            else None
        ),
        "source_registry_generation": registry_generation,
        "logical_content_sha256": row["logical_content_sha256"],
        "contract_sha256": row["contract_sha256"],
        "metadata_present": row.get("metadata_present"),
        "metadata_sha256": row.get("metadata_sha256"),
        "observed_query_contract_sha256": row.get(
            "observed_query_contract_sha256"
        ),
        "observed_head_block_at_fetch": row.get("observed_head_block_at_fetch"),
        "observed_query_start_date": row.get("observed_query_start_date"),
        "observed_query_end_date_exclusive": row.get(
            "observed_query_end_date_exclusive"
        ),
        "generation_identity_sha256": generation_identity,
    }


RAW_PARTITION_SCIENTIFIC_IDENTITY_FIELDS = (
    "source_registry_generation",
    "logical_content_sha256",
    "contract_sha256",
    "metadata_present",
    "metadata_sha256",
    "observed_query_contract_sha256",
    "observed_head_block_at_fetch",
    "observed_query_start_date",
    "observed_query_end_date_exclusive",
)


def _raw_partition_scientific_identity(
    source: str,
    stream: str,
    day: str,
    *,
    authority: Mapping[str, object],
) -> dict[str, object]:
    identity = {
        "source": source,
        "stream": stream,
        "day": day,
        **{
            field: authority.get(field)
            for field in RAW_PARTITION_SCIENTIFIC_IDENTITY_FIELDS
        },
    }
    if (
        not is_sha256(identity["source_registry_generation"])
        or not is_sha256(identity["logical_content_sha256"])
        or not is_sha256(identity["contract_sha256"])
        or not isinstance(identity["metadata_present"], bool)
        or (
            identity["metadata_present"] is True
            and not is_sha256(identity["metadata_sha256"])
        )
    ):
        raise ValueError(
            f"raw partition lacks relocation identity: {source}/{stream}/{day}"
        )
    return identity


def raw_partition_relocation_identity(
    source: str,
    stream: str,
    day: str,
    *,
    data_root: Path = DATA_DIR,
) -> dict[str, object]:
    """Bind one storage generation to its storage-independent scientific meaning."""

    authority = raw_partition_read_authority(
        source, stream, day, data_root=data_root
    )
    generation = authority.get("generation_identity_sha256")
    if not is_sha256(generation):
        raise ValueError(
            f"raw partition lacks generation identity: {source}/{stream}/{day}"
        )
    return {
        "generation_identity_sha256": generation,
        "scientific_identity": _raw_partition_scientific_identity(
            source, stream, day, authority=authority
        ),
    }


def raw_partition_scientific_identity(
    source: str,
    stream: str,
    day: str,
    *,
    data_root: Path = DATA_DIR,
) -> dict[str, object]:
    """Return raw meaning while excluding storage and certificate generations."""

    identity = raw_partition_relocation_identity(
        source, stream, day, data_root=data_root
    )["scientific_identity"]
    assert isinstance(identity, dict)
    return dict(identity)


def raw_partition_generation_identity(
    source: str,
    stream: str,
    day: str,
    *,
    data_root: Path = DATA_DIR,
) -> str:
    """Resolve one exact raw generation through promotion or a certified local ledger."""

    return str(
        raw_partition_read_authority(
            source, stream, day, data_root=data_root
        )["generation_identity_sha256"]
    )


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _portable_evidence_artifact(
    base: Path,
    entry: Mapping[str, object],
    *,
    path_field: str,
    hash_field: str,
    label: str,
    key: tuple[str, str],
) -> tuple[Path, dict[str, object]]:
    artifact = (base / str(entry.get(path_field) or "")).resolve()
    if not artifact.is_relative_to(base) or not artifact.is_file():
        raise ValueError(f"{label} artifact missing or outside evidence root: {key}")
    if not is_sha256(entry.get(hash_field)) or file_sha256(artifact) != entry.get(
        hash_field
    ):
        raise ValueError(f"{label} artifact hash mismatch: {key}")
    return artifact, _load_json(artifact, f"{label} artifact")


def _validate_fetch_code_artifact(
    artifact: Mapping[str, object], key: tuple[str, str]
) -> str:
    if (
        artifact.get("policy") != FETCH_CODE_ARTIFACT_POLICY
        or artifact.get("source") != key[0]
        or artifact.get("stream") != key[1]
    ):
        raise ValueError(f"fetch-code artifact perimeter mismatch: {key}")
    commit = artifact.get("repository_commit_sha")
    if not (
        isinstance(commit, str)
        and len(commit) == 40
        and all(character in "0123456789abcdef" for character in commit)
    ):
        raise ValueError(f"fetch-code artifact lacks a git commit: {key}")
    blobs = artifact.get("tracked_blobs")
    if not isinstance(blobs, list) or not blobs:
        raise ValueError(f"fetch-code artifact lacks tracked blobs: {key}")
    normalized: list[tuple[str, str]] = []
    for blob in blobs:
        if not isinstance(blob, dict):
            raise ValueError(f"fetch-code artifact has invalid tracked blobs: {key}")
        path = blob.get("path")
        digest = blob.get("blob_sha256")
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or not is_sha256(digest)
        ):
            raise ValueError(f"fetch-code artifact has invalid tracked blobs: {key}")
        normalized.append((path, str(digest)))
    if normalized != sorted(set(normalized)):
        raise ValueError(f"fetch-code artifact blobs are not canonical: {key}")
    backend = get_source(key[0]).backend
    expected_paths = {
        "scripts/fetch_raw_market_data.py",
        "src/ddvc/fetch/raw.py",
        f"src/ddvc/fetch/{'dune' if backend == 'dune' else 'graph'}.py",
    }
    if {path for path, _digest in normalized} != expected_paths:
        raise ValueError(f"fetch-code artifact does not bind canonical owners: {key}")
    repository = Path(__file__).resolve().parents[2]
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        for path, digest in normalized:
            content = subprocess.run(
                ["git", "show", f"{commit}:{path}"],
                cwd=repository,
                check=True,
                capture_output=True,
            ).stdout
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"fetch-code artifact blob hash mismatch: {key}")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"fetch-code artifact commit or path is unavailable: {key}") from exc
    return canonical_json_sha256(artifact)


def _validate_query_artifact(
    artifact: Mapping[str, object], key: tuple[str, str]
) -> str:
    if (
        artifact.get("policy") != QUERY_ARTIFACT_POLICY
        or artifact.get("source") != key[0]
        or artifact.get("stream") != key[1]
        or artifact.get("endpoint_family") not in {"thegraph", "dune", "rpc", "import"}
        or not isinstance(artifact.get("entity"), str)
        or not artifact.get("entity")
    ):
        raise ValueError(f"query artifact perimeter is incomplete: {key}")
    field_contract = FIELD_CONTRACTS[key]
    expected_fields = sorted(
        set(field_contract.required_paths).union(
            *(set(group) for group in field_contract.required_any_paths)
        )
    )
    selected_fields = artifact.get("selected_fields")
    if (
        not isinstance(selected_fields, list)
        or not selected_fields
        or selected_fields != sorted(set(selected_fields))
        or not all(isinstance(field, str) and field for field in selected_fields)
        or selected_fields != expected_fields
    ):
        raise ValueError(f"query artifact fields are incomplete: {key}")
    bounds = artifact.get("bounds")
    if not isinstance(bounds, dict) or set(bounds) != {"field", "lower", "upper"} or not all(
        isinstance(bounds[field], str) and bounds[field]
        for field in ("field", "lower", "upper")
    ):
        raise ValueError(f"query artifact bounds are incomplete: {key}")
    pagination = artifact.get("pagination")
    if (
        not isinstance(pagination, dict)
        or set(pagination)
        != {"chunk_policy", "direction", "order_field", "page_size"}
        or not isinstance(pagination.get("page_size"), int)
        or isinstance(pagination.get("page_size"), bool)
        or int(pagination["page_size"]) < 1
        or not all(
            isinstance(pagination.get(field), str) and pagination.get(field)
            for field in ("chunk_policy", "direction", "order_field")
        )
    ):
        raise ValueError(f"query artifact pagination is incomplete: {key}")
    query_contract = artifact.get("query_contract")
    if not isinstance(query_contract, dict) or not query_contract:
        raise ValueError(f"query artifact lacks a substantive contract: {key}")
    source = get_source(key[0])
    if source.backend == "thegraph":
        entity = next(
            entity
            for entity in get_schema(source.schema).entities
            if entity.stream == key[1]
        )
        expected_entity = entity.entity
        expected_pagination = {
            "chunk_policy": query_chunk_policy(entity),
            "direction": "ascending",
            "order_field": "id",
            "page_size": page_size_for_entity(entity),
        }
        selected_query_paths = selected_paths(entity.fields)
        if not {
            field.replace("[]", "") for field in expected_fields
        }.issubset(selected_query_paths):
            raise ValueError(f"canonical Graph query omits consumer fields: {key}")
        expected_recorded_query_contracts = [graph_query_contract_sha256(entity)]
    else:
        expected_entity = "dex.trades"
        expected_pagination = {
            "chunk_policy": "day_sql_v1",
            "direction": "ascending",
            "order_field": "block_time,evt_index",
            "page_size": 1000,
        }
        sample_days = query_contract.get("sample_days")
        if not isinstance(sample_days, list) or not sample_days:
            raise ValueError(f"Dune query artifact lacks sample days: {key}")
        expected_recorded_query_contracts = sorted(
            {
                dune_query_contract_sha256(
                    source,
                    dt.datetime.strptime(str(day), "%Y%m%d").date(),
                    dt.datetime.strptime(str(day), "%Y%m%d").date()
                    + dt.timedelta(days=1),
                )
                for day in sample_days
            }
        )
    expected_bounds = {
        "field": field_contract.timestamp_path,
        "lower": "inclusive_utc_day",
        "upper": "exclusive_utc_day",
    }
    if (
        artifact.get("entity") != expected_entity
        or bounds != expected_bounds
        or pagination != expected_pagination
    ):
        raise ValueError(f"query artifact does not match canonical stream semantics: {key}")
    if query_contract.get("recorded_query_contracts") != expected_recorded_query_contracts:
        raise ValueError(f"query artifact does not bind executed query contracts: {key}")
    return canonical_json_sha256(query_contract)


def load_generation_evidence(
    path: Path,
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, object]]:
    payload = _load_json(path, "generation evidence")
    if payload.get("policy") != GENERATION_EVIDENCE_POLICY:
        raise ValueError("generation evidence policy mismatch")
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    base = path.parent.resolve()
    for raw in payload.get("generations") or []:
        if not isinstance(raw, dict):
            raise ValueError("generation evidence entries must be objects")
        key = (str(raw.get("source")), str(raw.get("stream")))
        if key in indexed:
            raise ValueError(f"duplicate generation evidence: {key}")
        if raw.get("generation_kind") not in GENERATION_KINDS:
            raise ValueError(f"unknown generation kind for {key}")
        provenance_status = raw.get("provenance_status")
        normalized = dict(raw)
        if provenance_status == "available":
            fetch_path, fetch_artifact = _portable_evidence_artifact(
                base,
                raw,
                path_field="fetch_code_artifact",
                hash_field="fetch_code_artifact_sha256",
                label="fetch-code",
                key=key,
            )
            query_path, query_artifact = _portable_evidence_artifact(
                base,
                raw,
                path_field="query_artifact",
                hash_field="query_artifact_sha256",
                label="query",
                key=key,
            )
            if raw.get("fetch_code_identity_sha256") != _validate_fetch_code_artifact(
                fetch_artifact, key
            ):
                raise ValueError(f"fetch-code identity is not artifact-derived: {key}")
            query_identity = _validate_query_artifact(query_artifact, key)
            if raw.get("query_generation_identity_sha256") != query_identity:
                raise ValueError(f"query identity is not artifact-derived: {key}")
            normalized["fetch_code_artifact"] = str(fetch_path.relative_to(base))
            normalized["query_artifact"] = str(query_path.relative_to(base))
            query_contract = query_artifact["query_contract"]
            normalized["observed_query_contract_sha256s"] = query_contract[
                "recorded_query_contracts"
            ]
        elif provenance_status in {
            "legacy_graph_code_or_query_unavailable",
            "legacy_dune_code_or_query_unavailable",
        }:
            expected_kind = (
                "legacy_unfrozen_dune"
                if provenance_status.startswith("legacy_dune")
                else "legacy_unfrozen_graph"
            )
            if raw.get("generation_kind") != expected_kind:
                raise ValueError(f"legacy provenance backend mismatch: {key}")
            prohibited = (
                "fetch_code_artifact",
                "fetch_code_artifact_sha256",
                "query_artifact",
                "query_artifact_sha256",
            )
            if (
                raw.get("fetch_code_identity_sha256") is not None
                or raw.get("query_generation_identity_sha256") is not None
                or any(raw.get(field) is not None for field in prohibited)
            ):
                raise ValueError(f"legacy provenance downgrade contains invented identities: {key}")
        else:
            raise ValueError(f"generation provenance status is absent or unknown: {key}")
        if not is_sha256(raw.get("generation_identity_sha256")):
            raise ValueError(f"invalid generation_identity_sha256 for {key}")
        if raw["generation_identity_sha256"] != generation_identity(raw):
            raise ValueError(f"generation identity does not bind its inputs: {key}")
        indexed[key] = normalized
    unknown = sorted(set(indexed).difference(pairs))
    if unknown:
        raise ValueError(f"generation evidence names inactive streams: {unknown}")
    return indexed


def _expected_selection_windows(days: list[str]) -> dict[str, list[str]]:
    first = len(days) // 3
    second = 2 * len(days) // 3
    slices = {
        "early": days[:first],
        "middle": days[first:second],
        "late": days[second:],
    }
    if any(len(window) < 2 for window in slices.values()):
        raise ValueError("comparison selection calendar is too short")
    return slices


def _validate_selection_frame(
    frame: object,
    strata: object,
    key: tuple[str, str],
    local_partitions: Iterable[Mapping[str, object]],
) -> None:
    if not isinstance(frame, dict) or frame.get("policy") != SELECTION_FRAME_POLICY:
        raise ValueError(f"fresh comparison lacks a selection frame: {key}")
    local = sorted(local_partitions, key=lambda item: str(item.get("day")))
    expected_days = [str(item.get("day")) for item in local]
    population = frame.get("candidate_population")
    if not isinstance(population, list) or len(population) != len(expected_days):
        raise ValueError(f"comparison selection population is incomplete: {key}")
    normalized: list[tuple[str, int, str]] = []
    for candidate in population:
        if not isinstance(candidate, dict) or set(candidate) != {
            "activity_rows",
            "day",
            "logical_content_sha256",
        }:
            raise ValueError(f"comparison selection candidate is invalid: {key}")
        day = candidate.get("day")
        activity = candidate.get("activity_rows")
        digest = candidate.get("logical_content_sha256")
        if (
            not isinstance(day, str)
            or isinstance(activity, bool)
            or not isinstance(activity, int)
            or activity < 0
            or not is_sha256(digest)
        ):
            raise ValueError(f"comparison selection candidate is invalid: {key}")
        normalized.append((day, activity, str(digest)))
    if [day for day, _activity, _digest in normalized] != expected_days:
        raise ValueError(f"comparison selection population is not the full calendar: {key}")
    expected_population = [
        (
            str(item.get("day")),
            item.get("rows"),
            item.get("logical_content_sha256"),
        )
        for item in local
    ]
    if normalized != expected_population:
        raise ValueError(f"comparison selection population does not match local evidence: {key}")
    expected_windows = _expected_selection_windows(expected_days)
    window_boundaries = {
        name: {"start": days[0], "end": days[-1]}
        for name, days in expected_windows.items()
    }
    if (
        frame.get("activity_metric") != "legacy_rows"
        or frame.get("tie_rule")
        != "quiet=min(activity_rows,day);busy=max(activity_rows,day)"
        or frame.get("candidate_start") != expected_days[0]
        or frame.get("candidate_end") != expected_days[-1]
        or frame.get("window_boundaries") != window_boundaries
        or frame.get("candidate_population_sha256")
        != canonical_json_sha256(population)
    ):
        raise ValueError(f"comparison selection frame is not canonical: {key}")
    by_day = {day: activity for day, activity, _digest in normalized}
    expected_strata: dict[str, str] = {}
    for name, days in expected_windows.items():
        expected_strata[f"{name}_quiet"] = min(days, key=lambda day: (by_day[day], day))
        expected_strata[f"{name}_busy"] = max(days, key=lambda day: (by_day[day], day))
    if strata != expected_strata:
        raise ValueError(f"fresh comparison strata do not follow the selection frame: {key}")
    derived_frame, derived_strata = comparison_selection_frame(local)
    if frame != derived_frame or strata != derived_strata:
        raise ValueError(f"fresh comparison selection is not reproducible: {key}")


def _load_comparison_ledger(
    base: Path,
    manifest: Mapping[str, object],
    *,
    path_field: str,
    hash_field: str,
    key: tuple[str, str],
) -> list[dict[str, object]]:
    path = (base / str(manifest.get(path_field) or "")).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError(f"comparison ledger missing or outside evidence root: {key}")
    if not is_sha256(manifest.get(hash_field)) or file_sha256(path) != manifest.get(
        hash_field
    ):
        raise ValueError(f"comparison ledger hash mismatch: {key}")
    rows: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if (
                    not isinstance(row, dict)
                    or set(row) != {"day", "identity", "quantities"}
                    or not isinstance(row.get("day"), str)
                    or not isinstance(row.get("identity"), dict)
                    or not row.get("identity")
                    or not isinstance(row.get("quantities"), dict)
                    or not row.get("quantities")
                ):
                    raise ValueError(f"comparison ledger row is invalid: {key}")
                rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"comparison ledger is unreadable: {key}") from exc
    return rows


def comparison_counts(
    legacy_rows: list[dict[str, object]],
    reference_rows: list[dict[str, object]],
) -> dict[str, int]:
    def indexed(rows: list[dict[str, object]]) -> tuple[dict[tuple[str, str], str], int]:
        output: dict[tuple[str, str], str] = {}
        duplicates = 0
        for row in rows:
            identity = canonical_json_sha256(row["identity"])
            key = (str(row["day"]), identity)
            if key in output:
                duplicates += 1
            else:
                output[key] = canonical_json_sha256(row["quantities"])
        return output, duplicates

    legacy, legacy_duplicates = indexed(legacy_rows)
    reference, reference_duplicates = indexed(reference_rows)
    common = set(legacy).intersection(reference)
    return {
        "compared_rows": len(common),
        "missing_rows": len(set(reference).difference(legacy)),
        "extra_rows": len(set(legacy).difference(reference)),
        "duplicate_rows": legacy_duplicates + reference_duplicates,
        "quantity_mismatch_rows": sum(
            legacy[identity] != reference[identity] for identity in common
        ),
    }


def validate_comparison_rows(
    rows: Iterable[Mapping[str, object]], source: str, stream: str
) -> None:
    contract = comparison_contract(source, stream)
    alternative_groups = FIELD_CONTRACTS[(source, stream)].required_any_paths
    for row in rows:
        if (
            set(row.get("identity") or {}) != set(contract.identity_fields)
            or set(row.get("quantities") or {}) != set(contract.quantity_fields)
            or any(
                value is None
                or (isinstance(value, str) and not value.strip())
                or (isinstance(value, (list, tuple, dict, set)) and not value)
                for field, value in {
                    **dict(row.get("identity") or {}),
                    **dict(row.get("quantities") or {}),
                }.items()
                if not any(field in group for group in alternative_groups)
            )
            or any(
                not any(
                    dict(row.get("quantities") or {}).get(field) not in (None, "", [], {})
                    for field in group
                )
                for group in alternative_groups
            )
        ):
            raise ValueError(
                f"comparison ledger retained fields mismatch: {(source, stream)}"
            )


def load_adjudication_evidence(
    path: Path,
    pairs: set[tuple[str, str]],
    generations: Mapping[tuple[str, str], Mapping[str, object]],
    local_partitions: Mapping[tuple[str, str], Iterable[Mapping[str, object]]],
) -> dict[tuple[str, str], dict[str, object]]:
    payload = _load_json(path, "adjudication evidence")
    if payload.get("policy") != ADJUDICATION_EVIDENCE_POLICY:
        raise ValueError("adjudication evidence policy mismatch")
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    base = path.parent.resolve()
    for raw in payload.get("evidence") or []:
        if not isinstance(raw, dict):
            raise ValueError("adjudication evidence entries must be objects")
        key = (str(raw.get("source")), str(raw.get("stream")))
        if key in indexed:
            raise ValueError(f"duplicate adjudication evidence: {key}")
        if key not in pairs:
            raise ValueError(f"adjudication evidence names inactive stream: {key}")
        if raw.get("kind") not in ADJUDICATION_KINDS:
            raise ValueError(f"unknown adjudication kind for {key}")
        generation = generations.get(key)
        if generation is None or raw.get("generation_identity_sha256") != generation.get(
            "generation_identity_sha256"
        ):
            raise ValueError(f"adjudication generation mismatch: {key}")
        artifact = (base / str(raw.get("artifact") or "")).resolve()
        if not artifact.is_relative_to(base) or not artifact.is_file():
            raise ValueError(f"adjudication artifact missing or outside evidence root: {key}")
        if not is_sha256(raw.get("artifact_sha256")) or file_sha256(artifact) != raw.get(
            "artifact_sha256"
        ):
            raise ValueError(f"adjudication artifact hash mismatch: {key}")
        artifact_payload = _load_json(artifact, "adjudication artifact")
        common_fields = (
            "kind",
            "source",
            "stream",
            "generation_identity_sha256",
            "status",
            "zero_exceptions",
            "sample_days",
            "compared_rows",
            "missing_rows",
            "extra_rows",
            "duplicate_rows",
            "quantity_mismatch_rows",
            "comparison_engine_identity_sha256",
            "legacy_ledger",
            "legacy_ledger_sha256",
            "reference_ledger",
            "reference_ledger_sha256",
            "identity_fields",
            "quantity_fields",
            "comparison_contract_sha256",
            "reference_evidence",
            "reference_evidence_sha256",
        )
        if artifact_payload.get("policy") != ADJUDICATION_ARTIFACT_POLICY or any(
            artifact_payload.get(field) != raw.get(field) for field in common_fields
        ):
            raise ValueError(f"adjudication manifest does not bind its artifact: {key}")
        for field in (
            "compared_rows",
            "missing_rows",
            "extra_rows",
            "duplicate_rows",
            "quantity_mismatch_rows",
        ):
            if type(artifact_payload.get(field)) is not int or int(artifact_payload[field]) < 0:
                raise ValueError(f"adjudication artifact has invalid {field}: {key}")
        if artifact_payload.get("comparison_engine_identity_sha256") != canonical_json_sha256(
            COMPARISON_ENGINE_CONTRACT
        ):
            raise ValueError(f"adjudication comparison engine mismatch: {key}")
        identity_fields = artifact_payload.get("identity_fields")
        quantity_fields = artifact_payload.get("quantity_fields")
        expected_contract = comparison_contract(*key)
        if (
            identity_fields != list(expected_contract.identity_fields)
            or quantity_fields != list(expected_contract.quantity_fields)
            or artifact_payload.get("comparison_contract_sha256")
            != comparison_contract_identity(*key)
        ):
            raise ValueError(f"adjudication field contract mismatch: {key}")
        legacy_rows = _load_comparison_ledger(
            base,
            artifact_payload,
            path_field="legacy_ledger",
            hash_field="legacy_ledger_sha256",
            key=key,
        )
        reference_rows = _load_comparison_ledger(
            base,
            artifact_payload,
            path_field="reference_ledger",
            hash_field="reference_ledger_sha256",
            key=key,
        )
        validate_comparison_rows((*legacy_rows, *reference_rows), *key)
        reference_evidence_path = (
            base / str(artifact_payload.get("reference_evidence") or "")
        ).resolve()
        if (
            not reference_evidence_path.is_relative_to(base)
            or not reference_evidence_path.is_file()
            or not is_sha256(artifact_payload.get("reference_evidence_sha256"))
            or file_sha256(reference_evidence_path)
            != artifact_payload.get("reference_evidence_sha256")
        ):
            raise ValueError(f"fresh reference provider evidence mismatch: {key}")
        reference_evidence = _load_json(
            reference_evidence_path, "fresh reference provider evidence"
        )
        if (
            reference_evidence.get("policy")
            != "fresh-reference-provider-evidence-v1"
            or reference_evidence.get("source") != key[0]
            or reference_evidence.get("stream") != key[1]
            or reference_evidence.get("reference_ledger_sha256")
            != artifact_payload.get("reference_ledger_sha256")
            or reference_evidence.get("comparison_contract_sha256")
            != comparison_contract_identity(*key)
        ):
            raise ValueError(f"fresh reference provider evidence is incomplete: {key}")
        retained_artifacts = reference_evidence.get("raw_artifacts")
        if not isinstance(retained_artifacts, list) or not retained_artifacts:
            raise ValueError(f"fresh reference provider responses are absent: {key}")
        observed_reference_queries: set[str] = set()
        observed_reference_days: set[str] = set()
        for retained in retained_artifacts:
            if not isinstance(retained, dict):
                raise ValueError(f"fresh reference provider response is invalid: {key}")
            retained_path = (base / str(retained.get("path") or "")).resolve()
            if (
                not retained_path.is_relative_to(base)
                or not retained_path.is_file()
                or not is_sha256(retained.get("sha256"))
                or file_sha256(retained_path) != retained.get("sha256")
            ):
                raise ValueError(f"fresh reference provider response changed: {key}")
            if retained_path.suffix == ".json":
                metadata = _load_json(retained_path, "fresh reference metadata")
                if metadata.get("source") != key[0]:
                    raise ValueError(f"fresh reference metadata source mismatch: {key}")
                day = str(metadata.get("day") or "").replace("-", "")
                stream_metadata = (metadata.get("streams") or {}).get(key[1]) or {}
                query_identity = stream_metadata.get("query_contract_sha256")
                if not is_sha256(query_identity) or len(day) != 8:
                    raise ValueError(f"fresh reference metadata is incomplete: {key}")
                observed_reference_days.add(day)
                observed_reference_queries.add(str(query_identity))
        _code_path, code_artifact = _portable_evidence_artifact(
            base,
            reference_evidence,
            path_field="fetch_code_artifact",
            hash_field="fetch_code_artifact_sha256",
            label="reference fetch-code",
            key=key,
        )
        _validate_fetch_code_artifact(code_artifact, key)
        _query_path, query_artifact = _portable_evidence_artifact(
            base,
            reference_evidence,
            path_field="query_artifact",
            hash_field="query_artifact_sha256",
            label="reference query",
            key=key,
        )
        if reference_evidence.get(
            "query_generation_identity_sha256"
        ) != _validate_query_artifact(query_artifact, key):
            raise ValueError(f"fresh reference query identity mismatch: {key}")
        query_contract = query_artifact.get("query_contract")
        if (
            not isinstance(query_contract, dict)
            or query_contract.get("recorded_query_contracts")
            != sorted(observed_reference_queries)
            or query_contract.get("sample_days")
            != sorted(observed_reference_days)
        ):
            raise ValueError(f"fresh reference query does not bind provider metadata: {key}")
        recomputed = comparison_counts(legacy_rows, reference_rows)
        if any(artifact_payload.get(field) != value for field, value in recomputed.items()):
            raise ValueError(f"adjudication counts do not match retained ledgers: {key}")
        if int(artifact_payload["compared_rows"]) < 1 or any(
            int(artifact_payload[field]) != 0
            for field in (
                "missing_rows",
                "extra_rows",
                "duplicate_rows",
                "quantity_mismatch_rows",
            )
        ):
            raise ValueError(f"adjudication artifact is hollow or has exceptions: {key}")
        if raw.get("status") != "passed" or raw.get("zero_exceptions") is not True:
            raise ValueError(f"adjudication evidence did not pass: {key}")
        sample_days = raw.get("sample_days")
        if (
            not isinstance(sample_days, list)
            or not sample_days
            or sample_days != sorted(set(sample_days))
            or not all(
                isinstance(day, str)
                and len(day) == 8
                and day.isdigit()
                and get_source(key[0]).genesis.strftime("%Y%m%d") <= day <= RESEARCH_SAMPLE_END
                for day in sample_days
            )
        ):
            raise ValueError(f"adjudication sample calendar is absent or unstable: {key}")
        if any(
            row["day"] not in sample_days for row in (*legacy_rows, *reference_rows)
        ):
            raise ValueError(f"comparison ledger falls outside the sample calendar: {key}")
        if raw["kind"] == "fresh_stratified_comparison":
            strata = raw.get("strata")
            if (
                not isinstance(strata, dict)
                or set(strata) != REQUIRED_COMPARISON_STRATA
                or len(set(strata.values())) != len(REQUIRED_COMPARISON_STRATA)
                or not set(strata.values()).issubset(sample_days)
            ):
                raise ValueError(f"fresh comparison lacks day-assigned required strata: {key}")
            if artifact_payload.get("strata") != strata:
                raise ValueError(f"fresh comparison artifact strata mismatch: {key}")
            selection_frame = raw.get("selection_frame")
            if artifact_payload.get("selection_frame") != selection_frame:
                raise ValueError(f"fresh comparison artifact selection mismatch: {key}")
            _validate_selection_frame(selection_frame, strata, key, local_partitions.get(key, ()))
        if raw["kind"] == "independent_event_certificate":
            if len(expected_contract.identity_fields) < 3:
                raise ValueError(f"independent event evidence lacks causal identities: {key}")
            if artifact_payload.get("identity_fields") != raw.get("identity_fields"):
                raise ValueError(f"independent event artifact identity mismatch: {key}")
        indexed[key] = {**raw, "artifact": str(artifact.relative_to(base))}
    return indexed


def _validate_generation_against_local(
    entry: Mapping[str, object],
    partitions: Iterable[Mapping[str, object]],
) -> list[str]:
    errors: list[str] = []
    generation_kind = entry.get("generation_kind")
    if generation_kind in {"current_frozen_graph", "dune_sql_export"}:
        observed_query_contracts = entry.get("observed_query_contract_sha256s")
        source = get_source(str(entry.get("source")))
        for partition in partitions:
            if generation_kind == "dune_sql_export":
                partition_day = dt.datetime.strptime(
                    str(partition["day"]), "%Y%m%d"
                ).date()
                try:
                    validated_dune_query_window(
                        source,
                        partition_day,
                        {
                            "query_contract_sha256": partition.get(
                                "observed_query_contract_sha256"
                            ),
                            DUNE_QUERY_START_FIELD: partition.get(
                                "observed_query_start_date"
                            ),
                            DUNE_QUERY_END_EXCLUSIVE_FIELD: partition.get(
                                "observed_query_end_date_exclusive"
                            ),
                        },
                    )
                except ValueError:
                    query_matches = False
                else:
                    query_matches = True
            else:
                query_matches = (
                    isinstance(observed_query_contracts, list)
                    and partition.get("observed_query_contract_sha256")
                    in observed_query_contracts
                )
            if not query_matches:
                errors.append(str(partition["day"]))
            if (
                partition.get("metadata_logical_content_sha256")
                != partition.get("logical_content_sha256")
            ):
                errors.append(str(partition["day"]))
            if generation_kind == "current_frozen_graph":
                head = partition.get("observed_head_block_at_fetch")
                if isinstance(head, bool) or not isinstance(head, int) or head < 0:
                    errors.append(str(partition["day"]))
    return sorted(set(errors))


def write_retro_certificate(
    output: Path,
    local_partitions: list[dict[str, object]],
    *,
    generation_evidence: Path,
    adjudication_evidence: Path,
) -> dict[str, object]:
    """Write a deterministic partition ledger and immutable retro-certificate."""

    evidence_parent = output.parent.resolve()
    if generation_evidence.parent.resolve() != evidence_parent or adjudication_evidence.parent.resolve() != evidence_parent:
        raise ValueError("certificate and evidence manifests must share one portable bundle directory")
    ordered = sorted(
        local_partitions,
        key=lambda item: (item["source"], item["stream"], item["day"]),
    )
    identities = require_exact_partition_perimeter(ordered)
    pairs = {(source, stream) for source, stream, _day in identities}
    by_pair: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in ordered:
        by_pair.setdefault((str(item["source"]), str(item["stream"])), []).append(item)
    generations = load_generation_evidence(generation_evidence, pairs)
    adjudications = load_adjudication_evidence(
        adjudication_evidence, pairs, generations, by_pair
    )
    generation_mismatches: dict[str, list[str]] = {}
    for (source, stream), items in by_pair.items():
        if (source, stream) not in generations:
            continue
        mismatches = _validate_generation_against_local(
            generations[(source, stream)], items
        )
        if mismatches:
            generation_mismatches[f"{source}/{stream}"] = mismatches
    local_failures = [item for item in ordered if not item.get("local_pass")]
    missing_generation = sorted(pairs.difference(generations))
    missing_adjudication = sorted(pairs.difference(adjudications))
    ledger = output.with_suffix(".partitions.jsonl")
    with atomic_output(ledger) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for item in ordered:
                handle.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
    certificate = {
        "schema_version": CERTIFICATE_SCHEMA_VERSION,
        "policy": RETRO_CERTIFICATION_POLICY,
        "status": (
            "passed"
            if not local_failures
            and not missing_generation
            and not missing_adjudication
            and not generation_mismatches
            else "incomplete"
        ),
        "asserts_current_frozen_head_query_contract": False,
        "partition_ledger": ledger.name,
        "partition_ledger_sha256": file_sha256(ledger),
        "partition_count": len(ordered),
        "source_stream_count": len(pairs),
        "local_failure_count": len(local_failures),
        "local_repair_required": sorted(
            {
                f"{item['source']}/{item['stream']}"
                for item in local_failures
            }
        ),
        "missing_generation_evidence": [f"{source}/{stream}" for source, stream in missing_generation],
        "missing_adjudication_evidence": [f"{source}/{stream}" for source, stream in missing_adjudication],
        "generation_mismatch_days": generation_mismatches,
        "generation_evidence_sha256": file_sha256(generation_evidence),
        "generation_evidence": generation_evidence.name,
        "adjudication_evidence_sha256": file_sha256(adjudication_evidence),
        "adjudication_evidence": adjudication_evidence.name,
        "generations": [generations[key] for key in sorted(generations)],
        "adjudications": [adjudications[key] for key in sorted(adjudications)],
        "active_consumer_contracts_sha256": canonical_json_sha256(
            {
                f"{source}/{stream}": contract_identity(source, stream)
                for source, stream in sorted(pairs)
            }
        ),
    }
    body = {
        **certificate,
        "certificate_sha256": canonical_json_sha256(certificate),
    }
    with atomic_output(output) as temporary:
        temporary.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return body


def verify_retro_certificate(
    path: Path, *, data_root: Path = DATA_DIR
) -> dict[str, object]:
    certificate = _load_json(path, "retro-certificate")
    recorded = certificate.pop("certificate_sha256", None)
    if certificate.get("policy") != RETRO_CERTIFICATION_POLICY:
        raise ValueError("retro-certificate policy mismatch")
    if certificate.get("schema_version") != CERTIFICATE_SCHEMA_VERSION:
        raise ValueError("retro-certificate schema version mismatch")
    if recorded != canonical_json_sha256(certificate):
        raise ValueError("retro-certificate digest mismatch")
    ledger = path.with_name(str(certificate.get("partition_ledger") or ""))
    if not ledger.is_file() or file_sha256(ledger) != certificate.get(
        "partition_ledger_sha256"
    ):
        raise ValueError("retro-certificate partition ledger mismatch")
    partitions: list[dict[str, object]] = []
    try:
        with ledger.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("partition ledger rows must be JSON objects")
                partitions.append(item)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("retro-certificate partition ledger is unreadable") from exc
    identities = require_exact_partition_perimeter(partitions)
    reopened = [
        _scan_partition(str(data_root), RawPartition(source, stream, day))
        for source, stream, day in identities
    ]
    if reopened != partitions:
        raise ValueError("retro-certificate installed raw partitions changed")
    if any(
        item.get("contract_sha256") != contract_identity(source, stream)
        for item, (source, stream, _day) in zip(partitions, identities)
    ):
        raise ValueError("retro-certificate partition contract mismatch")
    if any(item.get("local_pass") is not True or item.get("errors") != [] for item in partitions):
        raise ValueError("retro-certificate partition ledger contains local failures")
    pairs = {(source, stream) for source, stream, _day in identities}
    expected_contracts = canonical_json_sha256(
        {
            f"{source}/{stream}": contract_identity(source, stream)
            for source, stream in sorted(pairs)
        }
    )
    if (
        certificate.get("partition_count") != len(partitions)
        or certificate.get("source_stream_count") != len(pairs)
        or certificate.get("local_failure_count") != 0
        or certificate.get("local_repair_required") != []
        or certificate.get("missing_generation_evidence") != []
        or certificate.get("missing_adjudication_evidence") != []
        or certificate.get("generation_mismatch_days") != {}
        or certificate.get("active_consumer_contracts_sha256") != expected_contracts
    ):
        raise ValueError("retro-certificate summary does not match its partition ledger")
    if certificate.get("asserts_current_frozen_head_query_contract") is not False:
        raise ValueError("retro-certificate falsely asserts a current frozen-head contract")
    if certificate.get("status") != "passed":
        raise ValueError("retro-certificate is not passed")
    generation_path = path.with_name(str(certificate.get("generation_evidence") or ""))
    adjudication_path = path.with_name(str(certificate.get("adjudication_evidence") or ""))
    if not generation_path.is_file() or file_sha256(generation_path) != certificate.get("generation_evidence_sha256"):
        raise ValueError("retro-certificate generation evidence mismatch")
    if not adjudication_path.is_file() or file_sha256(adjudication_path) != certificate.get("adjudication_evidence_sha256"):
        raise ValueError("retro-certificate adjudication evidence mismatch")
    generations = load_generation_evidence(generation_path, pairs)
    if set(generations) != pairs:
        raise ValueError("retro-certificate generation perimeter mismatch")
    by_pair: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in partitions:
        by_pair.setdefault((str(item["source"]), str(item["stream"])), []).append(item)
    adjudications = load_adjudication_evidence(
        adjudication_path, pairs, generations, by_pair
    )
    if set(adjudications) != pairs:
        raise ValueError("retro-certificate adjudication perimeter mismatch")
    if certificate.get("generations") != [generations[key] for key in sorted(generations)]:
        raise ValueError("retro-certificate embedded generations mismatch")
    if certificate.get("adjudications") != [
        adjudications[key] for key in sorted(adjudications)
    ]:
        raise ValueError("retro-certificate embedded adjudications mismatch")
    return {**certificate, "certificate_sha256": recorded}
