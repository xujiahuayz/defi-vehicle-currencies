"""Exact independent-chain completeness contract for V2-family state events."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from eth_abi import decode as abi_decode, encode as abi_encode
from eth_utils import keccak
import pandas as pd
import pyarrow.parquet as pq

from ddvc.amounts import human_to_raw
from ddvc.artifact_release import (
    ArtifactRelease,
    file_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.ethereum_day_cuts import (
    RAW_DAY_BOUND_ROOT,
    day_bound_path,
    validate_utc_day_block_bounds,
)
from ddvc.ethereum_logs import (
    EXACT_LOG_BLOCK_CAP,
    ExactLogCapacityError,
    ExactLogRpcError,
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    fetch_exact_logs,
    fetch_exact_logs_with_evidence,
    file_sha256 as _file_sha256,
    is_sha256 as _is_sha256,
    load_or_resolve_frozen_block,
    exact_log_block_ranges,
    rpc_post_with_evidence,
    rpc_integer,
    validate_canonical_log_records,
    validate_anchored_log_evidence,
    validate_frozen_block,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_json
from ddvc.fetch.sources import get_source
from ddvc.graph_event_order import (
    SCHEMA_VERSION as EVENT_ORDER_SCHEMA_VERSION,
    correction_pointer_path,
    correction_root_for_graph,
    load_event_order_corrections,
    load_event_order_generation_metadata,
    portable_evidence_path,
    semantic_mapping_sha256,
)
from ddvc.paths import V2_AUDITED_TOKEN_DECIMALS_REGISTRY, DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import sidecar_path
from ddvc.quoter import (
    RpcEnvelope,
    canonical_json_sha256 as _canonical_json_sha256,
    coerce_rpc_envelope,
    validate_rpc_attempts,
)
from ddvc.runtime import interruptible_thread_pool, serialized_read_installs
from ddvc.token_decimals import (
    token_decimals_registry_sha256,
    validate_token_decimals_registry,
)
from ddvc.v2_event_contract import (
    V2_COMPARISON_LEDGER,
    V2_CORE_EVENTS,
    V2_EVENT_BY_TOPIC,
    V2_EVENT_SIGNATURES,
    V2_EVENT_SOURCE_SCHEMA_VERSION,
    V2_EVENT_TOPICS,
    V2_EVENT_VENUES,
    V2_POOL_PERIMETER,
    V2_RECONCILIATION_COUNT_FIELDS,
    V2_RECONCILIATION_DETAILED_EXCLUSION_FIELDS,
    V2_RECONCILIATION_SCOPE,
)


V2_FACTORIES = {
    venue: str(get_source(venue).factory_address).lower()
    for venue in V2_EVENT_VENUES
}
if any(not address.startswith("0x") or len(address) != 42 for address in V2_FACTORIES.values()):
    raise RuntimeError("V2 event-source venues require exact factory addresses in the source registry")
PAIR_CREATED_TOPIC = "0x" + keccak(
    text="PairCreated(address,address,address,uint256)"
).hex()
RAW_V2_EVENT_ROOT = DATA_DIR / "raw" / "ethereum" / "v2_core_event_source"
V2_EXACT_LOG_CACHE_ROOT = RAW_V2_EVENT_ROOT / "global_50_block_chunks"
V2_EXACT_LOG_CHUNK_SIZE = EXACT_LOG_BLOCK_CAP
V2_FACTORY_INITIAL_BLOCK_SPAN = 10_000
V2_FACTORY_STATE_SAMPLE_SIZE = 1_024
V2_FACTORY_EVIDENCE_SCHEMA_VERSION = 4
RAW_V2_FACTORY_ROOT = DATA_DIR / "raw" / "ethereum" / "v2_factory_pair_registry"
# Legacy paths remain available only for callers that pass all three paths explicitly.
V2_EVENT_SOURCE_SUMMARY = DATA_DIR / "processed" / "v2_core_event_source_audit.parquet"
V2_EVENT_SOURCE_EXCEPTIONS = DATA_DIR / "processed" / "v2_core_event_source_exceptions.parquet"
V2_EVENT_SOURCE_CERTIFICATE = OUTPUT_DIR / "exhibits" / "v2_core_event_source_certificate.json"
V2_EVENT_SOURCE_RELEASE_SCHEMA_VERSION = 1
V2_EVENT_SOURCE_RELEASE_KIND = "v2_event_source_release"
V2_EVENT_SOURCE_RELEASE_ROOT = DATA_DIR / "processed" / "v2_core_event_source_release"
V2_EVENT_SOURCE_CURRENT = V2_EVENT_SOURCE_RELEASE_ROOT / "current.json"
V2_EVENT_SOURCE_RELEASE_FILENAMES = {
    "summary": "summary.parquet",
    "exceptions": "exceptions.parquet",
    "certificate": "certificate.json",
}
V2_TOKEN_DECIMALS_REGISTRY = V2_AUDITED_TOKEN_DECIMALS_REGISTRY
V2_TOKEN_DECIMALS_CONTRACT = "one_exact_erc20_decimals_call_per_token_at_deterministic_canonical_event_anchor"
V2_TOKEN_DECIMALS_SCOPE = "provider_decimals_observed_on_every_graph_event_must_be_constant_and_match_exact_anchor; exact_proxy_history_between_anchor_and_other_event_blocks_is_not_proven"

EventKey = tuple[str, str, int, str, int, str]
ALL_PAIRS_LENGTH_SELECTOR = "0x" + keccak(text="allPairsLength()")[:4].hex()
ALL_PAIRS_SELECTOR = "0x" + keccak(text="allPairs(uint256)")[:4].hex()
GET_PAIR_SELECTOR = "0x" + keccak(text="getPair(address,address)")[:4].hex()


@dataclass(frozen=True)
class PoolStatic:
    pool: str
    token0: str
    token1: str
    decimals0: int | None
    decimals1: int | None


@dataclass(frozen=True)
class FactoryPair:
    venue: str
    factory: str
    pool: str
    token0: str
    token1: str
    creation_block: int
    creation_tx_hash: str
    creation_log_index: int
    ordinal: int


@dataclass(frozen=True)
class EventAmounts:
    amount0_delta_raw: int
    amount1_delta_raw: int
    amount0_in_raw: int
    amount1_in_raw: int
    amount0_out_raw: int
    amount1_out_raw: int


@dataclass(frozen=True)
class V2EventSourceRelease:
    """One verified immutable V2 event-source generation."""

    generation_id: str
    pointer_path: Path
    summary_path: Path
    exceptions_path: Path
    certificate_path: Path
    pointer_sha256: str

    @property
    def artifact_paths(self) -> tuple[Path, Path, Path]:
        return self.summary_path, self.exceptions_path, self.certificate_path

    @property
    def provenance_paths(self) -> tuple[Path, Path, Path]:
        return tuple(sidecar_path(path) for path in self.artifact_paths)

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return self.pointer_path, *self.artifact_paths, *self.provenance_paths

    def assert_current(self) -> None:
        if not self.pointer_path.is_file() or file_sha256(self.pointer_path) != self.pointer_sha256:
            raise RuntimeError("V2 event-source pointer changed after resolution")


@contextmanager
def current_v2_event_source_release(release: V2EventSourceRelease):
    """Lease the selected V2 pointer and every artifact through the complete read."""

    with serialized_read_installs(release.lineage_paths):
        release.assert_current()
        yield release
        release.assert_current()


def _v2_event_source_release(release: ArtifactRelease) -> V2EventSourceRelease:
    """Expose the established V2 path API over the shared bundle owner."""

    if set(release.artifacts) != set(V2_EVENT_SOURCE_RELEASE_FILENAMES):
        raise ValueError("V2 event-source release has an unexpected artifact perimeter")
    return V2EventSourceRelease(
        generation_id=release.generation_id,
        pointer_path=release.pointer_path,
        summary_path=release.artifacts["summary"],
        exceptions_path=release.artifacts["exceptions"],
        certificate_path=release.artifacts["certificate"],
        pointer_sha256=release.pointer_sha256,
    )


def v2_exact_log_ranges(start_block: int, end_block: int) -> list[tuple[int, int]]:
    """Cover an inclusive perimeter with globally aligned provider-safe chunks."""

    if start_block < 0 or end_block < start_block:
        raise ValueError("invalid V2 exact-log block perimeter")
    return exact_log_block_ranges(start_block, end_block, aligned=True)


def missing_v2_exact_log_ranges(
    perimeters: Iterable[tuple[int, int]],
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> list[tuple[int, int]]:
    """Return each missing global chunk once across overlapping consumers."""

    return sorted(
        {
            block_range
            for start_block, end_block in perimeters
            for block_range in v2_exact_log_ranges(start_block, end_block)
            if not v2_exact_log_chunk_complete(*block_range, frozen_upper=frozen_upper, root=root)
        }
    )


def _require_canonical_v2_exact_range(start_block: int, end_block: int) -> None:
    if (
        start_block < 0
        or start_block % V2_EXACT_LOG_CHUNK_SIZE != 0
        or end_block != start_block + V2_EXACT_LOG_CHUNK_SIZE - 1
    ):
        raise ValueError("V2 exact-log cache keys must be aligned 50-block ranges")


def v2_exact_log_chunk_paths(
    start_block: int,
    end_block: int,
    *,
    root: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve the one canonical raw location for a global V2 topic query."""

    _require_canonical_v2_exact_range(start_block, end_block)
    directory = root or V2_EXACT_LOG_CACHE_ROOT
    stem = f"blocks_{start_block:08d}_{end_block:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def v2_exact_log_chunk_complete(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> bool:
    """Accept a shared chunk only after its exact marker and Parquet agree."""

    try:
        _read_complete_v2_exact_log_chunk(
            start_block,
            end_block,
            frozen_upper=frozen_upper,
            root=root,
        )
    except (ExactLogRpcError, IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


def _read_complete_v2_exact_log_chunk(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> list[dict[str, object]]:
    """Validate one immutable chunk and return the rows already opened for validation."""

    raw_path, marker_path = v2_exact_log_chunk_paths(start_block, end_block, root=root)
    if not raw_path.is_file() or not marker_path.is_file():
        raise FileNotFoundError(raw_path if not raw_path.is_file() else marker_path)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    table = pq.read_table(raw_path)
    records = table.to_pylist()
    validate_canonical_log_records(
        records,
        start_block=start_block,
        end_block=end_block,
        topics=[V2_EVENT_TOPICS[name] for name in V2_CORE_EVENTS],
        address=None,
    )
    validation_upper = persisted_chunk_frozen_upper(
        marker,
        current_frozen_upper=frozen_upper,
        end_block=end_block,
        root=root,
    )
    validate_anchored_log_evidence(marker, records, validation_upper)
    complete = bool(
        marker.get("status") == "complete"
        and int(marker.get("schema_version", -1)) == V2_FACTORY_EVIDENCE_SCHEMA_VERSION
        and marker.get("kind") == "global_v2_core_events"
        and int(marker.get("start_block", -1)) == start_block
        and int(marker.get("end_block", -1)) == end_block
        and int(marker.get("chunk_size", -1)) == V2_EXACT_LOG_CHUNK_SIZE
        and marker.get("address_filter") is None
        and set(marker.get("event_topics") or []) == set(V2_EVENT_TOPICS.values())
        and marker.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(marker.get("raw_logs", -1)) == table.num_rows
        and table.schema == RAW_LOG_SCHEMA
        and marker.get("raw_sha256") == _file_sha256(raw_path)
    )
    if not complete:
        raise ValueError("shared V2 exact-log chunk marker disagrees with its canonical rows")
    return records


def persisted_chunk_frozen_upper(
    marker: dict[str, object],
    *,
    current_frozen_upper: dict[str, object],
    end_block: int,
    root: Path | None,
) -> dict[str, object]:
    """Resolve the immutable chain anchor recorded when a raw chunk was fetched."""

    validate_frozen_upper_block(
        current_frozen_upper,
        int(current_frozen_upper["block_number"]),
    )
    request = marker.get("frozen_upper_request")
    if (
        not isinstance(request, dict)
        or request.get("method") != "eth_getBlockByNumber"
        or request.get("id") != 2
    ):
        raise ValueError("exact-log evidence lacks its frozen-upper request")
    params = request.get("params")
    if not isinstance(params, list) or len(params) != 2 or params[1] is not False:
        raise ValueError("exact-log evidence has a malformed frozen-upper request")
    anchored_block = int(str(params[0]), 16)
    current_block = int(current_frozen_upper["block_number"])
    if anchored_block < end_block or anchored_block > current_block:
        raise ValueError("exact-log evidence has a frozen anchor outside the admissible perimeter")
    if anchored_block == current_block:
        return current_frozen_upper
    return load_or_resolve_frozen_upper_block(
        anchored_block,
        fetch=False,
        root=root,
    )


def fetch_v2_exact_log_chunk(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
    rpc_request=None,
) -> dict[str, object]:
    """Fetch one missing immutable chunk; complete shared raw is always reused."""

    raw_path, marker_path = v2_exact_log_chunk_paths(
        start_block,
        end_block,
        root=root,
    )
    if v2_exact_log_chunk_complete(start_block, end_block, frozen_upper=frozen_upper, root=root):
        return json.loads(marker_path.read_text(encoding="utf-8"))
    if raw_path.exists() or marker_path.exists():
        raise RuntimeError(
            "partial or invalid shared V2 exact-log chunk must be quarantined, not overwritten: "
            f"{raw_path.name}"
        )
    kwargs = {"rpc_request": rpc_request} if rpc_request is not None else {}
    topics = [V2_EVENT_TOPICS[name] for name in V2_CORE_EVENTS]
    records, rpc_evidence = fetch_exact_logs_with_evidence(
        start_block=start_block,
        end_block=end_block,
        topics=topics,
        address=None,
        frozen_upper=frozen_upper,
        **kwargs,
    )
    return write_exact_log_chunk(
        raw_path,
        marker_path,
        records,
        {
            "kind": "global_v2_core_events",
            "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
            "start_block": start_block,
            "end_block": end_block,
            "chunk_size": V2_EXACT_LOG_CHUNK_SIZE,
            "address_filter": None,
            "query_scope": "global_aligned_50_block_topic_only_no_address_filter",
            "event_topics": topics,
            "rpc_request": rpc_evidence["request"],
            "rpc_response": rpc_evidence["response"],
            "rpc_endpoint": rpc_evidence["endpoint"],
            "rpc_attempts": rpc_evidence["attempts"],
            "response_sha256": rpc_evidence["response_sha256"],
            "frozen_upper_request": rpc_evidence["frozen_upper_request"],
            "frozen_upper_response": rpc_evidence["frozen_upper_response"],
            "frozen_upper_response_sha256": rpc_evidence["frozen_upper_response_sha256"],
            "raw_by_event": dict(
                Counter(V2_EVENT_BY_TOPIC[str(record["topics"][0])] for record in records)
            ),
        },
    )


def read_v2_exact_logs(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> tuple[list[dict[str, object]], list[Path]]:
    """Read shared chunks and return only records inside the consumer's perimeter."""

    records: list[dict[str, object]] = []
    inputs: list[Path] = []
    for lower, upper in v2_exact_log_ranges(start_block, end_block):
        try:
            chunk = _read_complete_v2_exact_log_chunk(
                lower,
                upper,
                frozen_upper=frozen_upper,
                root=root,
            )
        except (ExactLogRpcError, IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(f"shared V2 exact-log chunk is incomplete: {lower}:{upper}") from error

        raw_path, marker_path = v2_exact_log_chunk_paths(lower, upper, root=root)
        if any(not lower <= int(record["block_number"]) <= upper for record in chunk):
            raise ValueError(f"shared V2 exact-log chunk contains an out-of-range row: {lower}:{upper}")
        records.extend(
            record
            for record in chunk
            if start_block <= int(record["block_number"]) <= end_block
        )
        inputs.extend((raw_path, marker_path))
    return records, inputs


def _rpc_envelope(payload: object, rpc_request=None) -> RpcEnvelope:
    if rpc_request is None:
        return rpc_post_with_evidence(payload)
    response = rpc_request(payload, timeout=30, retries=2)
    return coerce_rpc_envelope(response)


def frozen_upper_block_path(block: int, *, root: Path | None = None) -> Path:
    directory = root or RAW_V2_FACTORY_ROOT
    return directory / "frozen_upper_blocks" / f"block_{block:08d}.json"


def factory_deployment_path(
    venue: str,
    upper_block: int,
    *,
    root: Path | None = None,
) -> Path:
    if venue not in V2_EVENT_VENUES or upper_block < 0:
        raise ValueError("invalid V2 factory deployment perimeter")
    return (root or RAW_V2_FACTORY_ROOT) / venue / f"deployment_{upper_block:08d}.json"


def validate_factory_deployment_proof(
    record: dict[str, object],
    venue: str,
    upper_block: int,
    upper_hash: str,
) -> int:
    """Revalidate the factory's exact deployment edge and frozen-upper bytecode."""

    factory = V2_FACTORIES[venue]
    deployment_block = int(record.get("deployment_block", -1))
    if (
        record.get("status") != "complete"
        or int(record.get("schema_version", -1)) != V2_FACTORY_EVIDENCE_SCHEMA_VERSION
        or record.get("venue") != venue
        or record.get("factory") != factory
        or deployment_block < 1
        or int(record.get("upper_block", -1)) != upper_block
        or record.get("upper_block_hash") != upper_hash
    ):
        raise ValueError(f"stale {venue} factory deployment evidence")
    evidence = record.get("rpc_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{venue} factory deployment evidence is absent")
    observed: dict[int, str] = {}
    frozen_observed: str | None = None
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError(f"{venue} factory deployment evidence is malformed")
        request = item.get("request")
        response = item.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise ValueError(f"{venue} factory deployment evidence lacks an exact RPC exchange")
        if request.get("jsonrpc") != "2.0" or request.get("method") != "eth_getCode":
            raise ValueError(f"{venue} factory deployment evidence contains a non-code request")
        params = request.get("params")
        if not isinstance(params, list) or len(params) != 2 or params[0] != factory:
            raise ValueError(f"{venue} factory deployment evidence names a different factory")
        if (
            response.get("jsonrpc") != "2.0"
            or response.get("id") != request.get("id")
            or response.get("error") is not None
        ):
            raise ValueError(f"{venue} factory deployment evidence lacks a successful RPC response")
        code = response.get("result")
        if (
            not isinstance(code, str)
            or not code.startswith("0x")
            or len(code) % 2 != 0
            or any(character not in "0123456789abcdef" for character in code[2:].lower())
        ):
            raise ValueError(f"{venue} factory deployment evidence contains malformed bytecode")
        if item.get("response_sha256") != _canonical_json_sha256(response):
            raise ValueError(f"{venue} factory code response digest disagrees")
        endpoint = item.get("rpc_endpoint")
        try:
            validate_rpc_attempts(item.get("rpc_attempts"), endpoint)
        except ValueError as error:
            raise ValueError(f"{venue} factory code proof has invalid RPC attempt evidence") from error
        block_reference = params[1]
        if isinstance(block_reference, dict):
            if block_reference != {"blockHash": upper_hash, "requireCanonical": True}:
                raise ValueError(f"{venue} factory code proof names a different frozen block hash")
            frozen_observed = code
        else:
            observed[int(str(block_reference), 16)] = code
    if observed.get(deployment_block - 1) not in {"0x", "0x0"}:
        raise ValueError(f"{venue} pre-deployment factory code is not empty")
    if observed.get(deployment_block) in {None, "", "0x", "0x0"}:
        raise ValueError(f"{venue} deployment-block factory code is empty")
    if frozen_observed in {None, "", "0x", "0x0"}:
        raise ValueError(f"{venue} frozen-upper factory code is empty")
    deployment_hash = hashlib.sha256(
        bytes.fromhex(observed[deployment_block].removeprefix("0x"))
    ).hexdigest()
    frozen_hash = hashlib.sha256(
        bytes.fromhex(str(frozen_observed).removeprefix("0x"))
    ).hexdigest()
    if deployment_hash != frozen_hash or record.get("runtime_code_sha256") != deployment_hash:
        raise ValueError(f"{venue} factory runtime code changed across the frozen perimeter")
    return deployment_block


def validate_frozen_upper_block(record: dict[str, object], block: int) -> None:
    validate_frozen_block(
        record,
        block,
        schema_version=V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
    )


def load_or_resolve_frozen_upper_block(
    block: int,
    *,
    fetch: bool,
    root: Path | None = None,
    rpc_request=None,
) -> dict[str, object]:
    """Freeze the exact upper block header once; invalid evidence is never overwritten."""

    return load_or_resolve_frozen_block(
        block,
        path=frozen_upper_block_path(block, root=root),
        schema_version=V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        fetch=fetch,
        rpc_request=rpc_request,
    )


def factory_root_ranges(
    deployment_block: int,
    upper_block: int,
    *,
    initial_span: int = V2_FACTORY_INITIAL_BLOCK_SPAN,
) -> list[tuple[int, int]]:
    """Define deterministic address-filtered roots independently of provider splits."""

    return block_ranges(deployment_block, upper_block, initial_span)


def _bisected_factory_children(start_block: int, end_block: int) -> tuple[tuple[int, int], tuple[int, int]]:
    if start_block >= end_block:
        raise ValueError("a one-block factory range cannot be bisected")
    midpoint = (start_block + end_block) // 2
    return (start_block, midpoint), (midpoint + 1, end_block)


def _validate_canonical_factory_root(
    marker: dict[str, object],
    *,
    start_block: int,
    end_block: int,
    deterministic_roots: list[tuple[int, int]],
) -> None:
    matching_roots = [
        perimeter
        for perimeter in deterministic_roots
        if perimeter[0] <= start_block <= end_block <= perimeter[1]
    ]
    marker_root = (
        int(marker.get("root_start_block", -1)),
        int(marker.get("root_end_block", -1)),
    )
    if len(matching_roots) != 1 or marker_root != matching_roots[0]:
        raise ValueError("V2 factory leaf ancestry names a non-canonical root")


def factory_leaf_paths(
    venue: str,
    start_block: int,
    end_block: int,
    *,
    root: Path | None = None,
) -> tuple[Path, Path]:
    if venue not in V2_EVENT_VENUES or start_block < 0 or end_block < start_block:
        raise ValueError("invalid V2 factory leaf perimeter")
    directory = (root or RAW_V2_FACTORY_ROOT) / venue / "leaves"
    stem = f"blocks_{start_block:08d}_{end_block:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def factory_leaf_complete(
    venue: str,
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> bool:
    raw_path, marker_path = factory_leaf_paths(
        venue,
        start_block,
        end_block,
        root=root,
    )
    if not raw_path.is_file() or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        table = pq.read_table(raw_path)
        _validate_factory_leaf_lineage(marker, start_block=start_block, end_block=end_block)
        records = validate_canonical_log_records(
            table.to_pylist(),
            start_block=start_block,
            end_block=end_block,
            topics=[PAIR_CREATED_TOPIC],
            address=V2_FACTORIES[venue],
        )
        for record in records:
            decode_pair_created_log(venue, record)
        validation_upper = persisted_chunk_frozen_upper(
            marker,
            current_frozen_upper=frozen_upper,
            end_block=end_block,
            root=root,
        )
        validate_anchored_log_evidence(marker, records, validation_upper)
    except (ExactLogRpcError, IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        marker.get("status") == "complete"
        and int(marker.get("schema_version", -1)) == V2_FACTORY_EVIDENCE_SCHEMA_VERSION
        and marker.get("kind") == "factory_pair_created"
        and marker.get("venue") == venue
        and marker.get("address_filter") == V2_FACTORIES[venue]
        and marker.get("event_topics") == [PAIR_CREATED_TOPIC]
        and int(marker.get("start_block", -1)) == start_block
        and int(marker.get("end_block", -1)) == end_block
        and marker.get("query_scope") == "factory_address_and_paircreated_topic"
        and marker.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(marker.get("raw_logs", -1)) == table.num_rows
        and table.schema == RAW_LOG_SCHEMA
        and marker.get("raw_sha256") == _file_sha256(raw_path)
        and isinstance(marker.get("rpc_endpoint"), dict)
        and len(str(marker["rpc_endpoint"].get("endpoint_sha256") or "")) == 64
    )


def _validate_factory_leaf_lineage(
    marker: dict[str, object],
    *,
    start_block: int,
    end_block: int,
) -> None:
    """Require each adaptive leaf to descend through exact midpoint bisections."""

    root_start = int(marker.get("root_start_block", -1))
    root_end = int(marker.get("root_end_block", -1))
    depth = int(marker.get("adaptive_depth", -1))
    ancestry = marker.get("split_ancestry")
    if not isinstance(ancestry, list) or depth != len(ancestry):
        raise ValueError("factory leaf ancestry depth is invalid")
    if not root_start <= start_block <= end_block <= root_end:
        raise ValueError("factory leaf lies outside its deterministic root")
    current = (root_start, root_end)
    if not ancestry:
        if current != (start_block, end_block):
            raise ValueError("unsplit factory leaf does not equal its deterministic root")
        return
    for index, split in enumerate(ancestry):
        if not isinstance(split, dict):
            raise ValueError("factory leaf ancestry contains a malformed split")
        observed = (int(split.get("start_block", -1)), int(split.get("end_block", -1)))
        if observed != current:
            raise ValueError("factory leaf ancestry does not follow its deterministic root")
        children = _bisected_factory_children(*current)
        descendant = (
            (int(ancestry[index + 1]["start_block"]), int(ancestry[index + 1]["end_block"]))
            if index + 1 < len(ancestry) and isinstance(ancestry[index + 1], dict)
            else (start_block, end_block)
        )
        if descendant not in children:
            raise ValueError("factory leaf ancestry violates exact midpoint bisection")
        current = descendant


def _existing_factory_split(
    venue: str,
    start_block: int,
    end_block: int,
    *,
    root_start: int,
    root_end: int,
    depth: int,
    frozen_upper: dict[str, object],
    root: Path | None,
) -> dict[str, object] | None:
    """Recover a published descendant's split so an interrupted root cannot overlap it."""

    leaf_directory = (root or RAW_V2_FACTORY_ROOT) / venue / "leaves"
    if not leaf_directory.is_dir():
        return None
    split_records: list[dict[str, object]] = []
    for marker_path in leaf_directory.glob("blocks_*.meta.json"):
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            leaf_start = int(marker.get("start_block", -1))
            leaf_end = int(marker.get("end_block", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            int(marker.get("root_start_block", -1)) != root_start
            or int(marker.get("root_end_block", -1)) != root_end
            or not start_block <= leaf_start <= leaf_end <= end_block
            or (leaf_start, leaf_end) == (start_block, end_block)
        ):
            continue
        if not factory_leaf_complete(venue, leaf_start, leaf_end, frozen_upper=frozen_upper, root=root):
            raise RuntimeError("published V2 factory descendant is invalid and must be quarantined")
        ancestry = marker.get("split_ancestry")
        if not isinstance(ancestry, list) or len(ancestry) <= depth:
            raise RuntimeError("published V2 factory descendant lacks its parent split")
        split = ancestry[depth]
        if not isinstance(split, dict):
            raise RuntimeError("published V2 factory descendant has malformed split evidence")
        split_records.append(split)
    if not split_records:
        return None
    canonical = json.dumps(split_records[0], sort_keys=True, separators=(",", ":"))
    if any(json.dumps(split, sort_keys=True, separators=(",", ":")) != canonical for split in split_records[1:]):
        raise RuntimeError("published V2 factory descendants disagree on their parent split")
    if (
        int(split_records[0].get("start_block", -1)) != start_block
        or int(split_records[0].get("end_block", -1)) != end_block
    ):
        raise RuntimeError("published V2 factory descendant points to a different parent root")
    return split_records[0]


def fetch_factory_root_adaptive(
    venue: str,
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root_start: int | None = None,
    root_end: int | None = None,
    depth: int = 0,
    split_ancestry: tuple[dict[str, object], ...] = (),
    root: Path | None = None,
    rpc_request=None,
) -> list[tuple[int, int]]:
    """Fetch one root, bisecting only structured capacity/timeout failures."""

    root_start = start_block if root_start is None else root_start
    root_end = end_block if root_end is None else root_end
    raw_path, marker_path = factory_leaf_paths(venue, start_block, end_block, root=root)
    existing_split = _existing_factory_split(
        venue,
        start_block,
        end_block,
        root_start=root_start,
        root_end=root_end,
        depth=depth,
        frozen_upper=frozen_upper,
        root=root,
    )
    if factory_leaf_complete(venue, start_block, end_block, frozen_upper=frozen_upper, root=root):
        if existing_split is not None:
            raise RuntimeError("V2 factory root overlaps already published descendants")
        return [(start_block, end_block)]
    if raw_path.exists() or marker_path.exists():
        raise RuntimeError(
            "partial or invalid V2 factory leaf must be quarantined, not overwritten: "
            f"{raw_path.name}"
        )
    if existing_split is not None:
        left_range, right_range = _bisected_factory_children(start_block, end_block)
        ancestry = (*split_ancestry, existing_split)
        left = fetch_factory_root_adaptive(
            venue,
            *left_range,
            root_start=root_start,
            root_end=root_end,
            depth=depth + 1,
            split_ancestry=ancestry,
            frozen_upper=frozen_upper,
            root=root,
            rpc_request=rpc_request,
        )
        right = fetch_factory_root_adaptive(
            venue,
            *right_range,
            root_start=root_start,
            root_end=root_end,
            depth=depth + 1,
            split_ancestry=ancestry,
            frozen_upper=frozen_upper,
            root=root,
            rpc_request=rpc_request,
        )
        return [*left, *right]
    try:
        records, rpc_evidence = fetch_exact_logs_with_evidence(
            start_block=start_block,
            end_block=end_block,
            topics=[PAIR_CREATED_TOPIC],
            address=V2_FACTORIES[venue],
            frozen_upper=frozen_upper,
            rpc_request=rpc_request,
        )
    except ExactLogCapacityError as error:
        if start_block == end_block:
            raise RuntimeError(
                f"V2 factory exact-log query failed at one block: {venue}/{start_block}"
            ) from error
        left_range, right_range = _bisected_factory_children(start_block, end_block)
        split = {
            "start_block": start_block,
            "end_block": end_block,
            "attempts": list(error.attempts),
        }
        ancestry = (*split_ancestry, split)
        left = fetch_factory_root_adaptive(
            venue,
            *left_range,
            root_start=root_start,
            root_end=root_end,
            depth=depth + 1,
            split_ancestry=ancestry,
            frozen_upper=frozen_upper,
            root=root,
            rpc_request=rpc_request,
        )
        right = fetch_factory_root_adaptive(
            venue,
            *right_range,
            root_start=root_start,
            root_end=root_end,
            depth=depth + 1,
            split_ancestry=ancestry,
            frozen_upper=frozen_upper,
            root=root,
            rpc_request=rpc_request,
        )
        return [*left, *right]
    write_exact_log_chunk(
        raw_path,
        marker_path,
        records,
        {
            "kind": "factory_pair_created",
            "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
            "venue": venue,
            "start_block": start_block,
            "end_block": end_block,
            "root_start_block": root_start,
            "root_end_block": root_end,
            "adaptive_depth": depth,
            "split_ancestry": list(split_ancestry),
            "address_filter": V2_FACTORIES[venue],
            "query_scope": "factory_address_and_paircreated_topic",
            "event_topics": [PAIR_CREATED_TOPIC],
            "rpc_request": rpc_evidence["request"],
            "rpc_response": rpc_evidence["response"],
            "rpc_endpoint": rpc_evidence["endpoint"],
            "rpc_attempts": rpc_evidence["attempts"],
            "response_sha256": rpc_evidence["response_sha256"],
            "frozen_upper_request": rpc_evidence["frozen_upper_request"],
            "frozen_upper_response": rpc_evidence["frozen_upper_response"],
            "frozen_upper_response_sha256": rpc_evidence["frozen_upper_response_sha256"],
        },
    )
    return [(start_block, end_block)]


def validate_factory_coverage_ranges(
    ranges: Iterable[tuple[int, int]],
    deployment_block: int,
    upper_block: int,
) -> list[tuple[int, int]]:
    ordered = sorted((int(start), int(end)) for start, end in ranges)
    if not ordered or ordered[0][0] != deployment_block or ordered[-1][1] != upper_block:
        raise ValueError("V2 factory coverage does not bind both frozen perimeter edges")
    previous_end = deployment_block - 1
    for start, end in ordered:
        if start > end:
            raise ValueError("V2 factory coverage contains an inverted leaf")
        if start != previous_end + 1:
            relation = "gap" if start > previous_end + 1 else "overlap"
            raise ValueError(f"V2 factory coverage contains a {relation}: {previous_end}/{start}")
        previous_end = end
    return ordered


def factory_coverage_manifest_path(
    venue: str,
    upper_block: int,
    *,
    root: Path | None = None,
) -> Path:
    return (root or RAW_V2_FACTORY_ROOT) / venue / f"coverage_{upper_block:08d}.json"


def validate_factory_coverage_manifest(
    manifest: dict[str, object],
    *,
    venue: str,
    deployment_block: int,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> list[tuple[int, int]]:
    upper_block = int(frozen_upper["block_number"])
    expected = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": V2_FACTORIES[venue],
        "deployment_block": deployment_block,
        "upper_block": upper_block,
        "upper_block_hash": frozen_upper["block_hash"],
        "upper_block_timestamp": frozen_upper["timestamp"],
        "initial_block_span": V2_FACTORY_INITIAL_BLOCK_SPAN,
    }
    stale = {
        key: (manifest.get(key), value)
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    if stale:
        raise ValueError(f"V2 factory coverage manifest is stale: {stale}")
    leaves = manifest.get("leaves")
    if not isinstance(leaves, list):
        raise ValueError("V2 factory coverage manifest lacks leaves")
    ranges = validate_factory_coverage_ranges(
        [(int(leaf["start_block"]), int(leaf["end_block"])) for leaf in leaves],
        deployment_block,
        upper_block,
    )
    base = (root or RAW_V2_FACTORY_ROOT) / venue
    deterministic_roots = factory_root_ranges(deployment_block, upper_block)
    rows = 0
    for leaf, (start, end) in zip(leaves, ranges, strict=True):
        raw_relative = Path(str(leaf.get("raw_path") or ""))
        marker_relative = Path(str(leaf.get("marker_path") or ""))
        if raw_relative.is_absolute() or marker_relative.is_absolute() or ".." in raw_relative.parts or ".." in marker_relative.parts:
            raise ValueError("V2 factory coverage contains a non-portable leaf path")
        raw_path, marker_path = factory_leaf_paths(venue, start, end, root=root)
        if raw_path != base / raw_relative or marker_path != base / marker_relative:
            raise ValueError("V2 factory coverage leaf path disagrees with its canonical range")
        if not factory_leaf_complete(venue, start, end, frozen_upper=frozen_upper, root=root):
            raise ValueError(f"V2 factory coverage leaf is incomplete: {start}:{end}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        _validate_factory_leaf_lineage(marker, start_block=start, end_block=end)
        _validate_canonical_factory_root(
            marker,
            start_block=start,
            end_block=end,
            deterministic_roots=deterministic_roots,
        )
        if leaf.get("raw_sha256") != marker.get("raw_sha256") or leaf.get("marker_sha256") != _file_sha256(marker_path):
            raise ValueError(f"V2 factory coverage leaf digest changed: {start}:{end}")
        rows += int(marker["raw_logs"])
    if int(manifest.get("raw_logs", -1)) != rows or int(manifest.get("leaf_count", -1)) != len(ranges):
        raise ValueError("V2 factory coverage manifest totals disagree")
    return ranges


def write_factory_coverage_manifest(
    venue: str,
    deployment_block: int,
    frozen_upper: dict[str, object],
    ranges: Iterable[tuple[int, int]],
    *,
    root: Path | None = None,
) -> dict[str, object]:
    validate_frozen_upper_block(frozen_upper, int(frozen_upper["block_number"]))
    upper_block = int(frozen_upper["block_number"])
    ordered = validate_factory_coverage_ranges(ranges, deployment_block, upper_block)
    base = (root or RAW_V2_FACTORY_ROOT) / venue
    deterministic_roots = factory_root_ranges(deployment_block, upper_block)
    leaves: list[dict[str, object]] = []
    for start, end in ordered:
        raw_path, marker_path = factory_leaf_paths(venue, start, end, root=root)
        if not marker_path.is_file():
            raise ValueError(f"cannot manifest incomplete V2 factory leaf: {start}:{end}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        _validate_factory_leaf_lineage(marker, start_block=start, end_block=end)
        _validate_canonical_factory_root(
            marker,
            start_block=start,
            end_block=end,
            deterministic_roots=deterministic_roots,
        )
        if not factory_leaf_complete(venue, start, end, frozen_upper=frozen_upper, root=root):
            raise ValueError(f"cannot manifest incomplete V2 factory leaf: {start}:{end}")
        leaves.append(
            {
                "start_block": start,
                "end_block": end,
                "raw_logs": int(marker["raw_logs"]),
                "raw_path": raw_path.relative_to(base).as_posix(),
                "marker_path": marker_path.relative_to(base).as_posix(),
                "raw_sha256": marker["raw_sha256"],
                "marker_sha256": _file_sha256(marker_path),
            }
        )
    manifest = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": V2_FACTORIES[venue],
        "deployment_block": deployment_block,
        "upper_block": upper_block,
        "upper_block_hash": frozen_upper["block_hash"],
        "upper_block_timestamp": frozen_upper["timestamp"],
        "initial_block_span": V2_FACTORY_INITIAL_BLOCK_SPAN,
        "leaf_count": len(leaves),
        "raw_logs": sum(int(leaf["raw_logs"]) for leaf in leaves),
        "leaves": leaves,
    }
    path = factory_coverage_manifest_path(venue, upper_block, root=root)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        validate_factory_coverage_manifest(
            existing,
            venue=venue,
            deployment_block=deployment_block,
            frozen_upper=frozen_upper,
            root=root,
        )
        if existing != manifest:
            raise RuntimeError("immutable V2 factory coverage manifest disagrees with current leaves")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, manifest)
    return manifest


def read_factory_coverage_records(
    manifest: dict[str, object],
    *,
    venue: str,
    deployment_block: int,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> tuple[list[dict[str, object]], list[Path]]:
    ranges = validate_factory_coverage_manifest(
        manifest,
        venue=venue,
        deployment_block=deployment_block,
        frozen_upper=frozen_upper,
        root=root,
    )
    records: list[dict[str, object]] = []
    inputs: list[Path] = []
    for start, end in ranges:
        raw_path, marker_path = factory_leaf_paths(venue, start, end, root=root)
        records.extend(pq.read_table(raw_path).to_pylist())
        inputs.extend((raw_path, marker_path))
    return records, inputs


def audit_calendar_sha256(days: Iterable[str]) -> str:
    payload = json.dumps(sorted(set(days)), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def event_key(
    venue: str,
    event_type: str,
    block: object,
    tx_hash: object,
    log_index: object,
    pool: object,
) -> EventKey:
    return (
        str(venue),
        str(event_type),
        int(block),
        str(tx_hash).lower(),
        int(log_index),
        str(pool).lower(),
    )


def _exact_raw(value: object, decimals: int, *, label: str) -> int:
    converted = human_to_raw(value, decimals)
    if converted is None:
        raise ValueError(f"{label} is not an exact base-unit token amount")
    return int(converted)


def _address(value: object, *, label: str) -> str:
    address = str(value or "").lower()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"{label} lacks an exact contract address")
    return address


def _transaction_hash(value: object, *, label: str) -> str:
    transaction_hash = str(value or "").lower()
    if not transaction_hash.startswith("0x") or len(transaction_hash) != 66:
        raise ValueError(f"{label} lacks an exact transaction hash")
    return transaction_hash


def iter_graph_rows(path: Path) -> Iterator[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"non-object Graph record in {path.name}")
                yield record


def graph_stream_path(graph_root: Path, venue: str, stream: str, day: str) -> Path:
    return graph_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"


def _pool_static_from_row(
    row: dict[str, object],
    token_decimals: dict[str, int],
) -> PoolStatic:
    pair = row.get("pair")
    if not isinstance(pair, dict):
        raise ValueError("V2 Graph record lacks a pair object")
    token0 = pair.get("token0")
    token1 = pair.get("token1")
    if not isinstance(token0, dict) or not isinstance(token1, dict):
        raise ValueError("V2 Graph pair lacks token objects")
    pool = _address(pair.get("id"), label="V2 pool")
    token0_address = _address(token0.get("id"), label=f"{pool} token0")
    token1_address = _address(token1.get("id"), label=f"{pool} token1")
    decimals0 = token_decimals.get(token0_address)
    decimals1 = token_decimals.get(token1_address)
    for token, expected, label in (
        (token0, decimals0, "token0"),
        (token1, decimals1, "token1"),
    ):
        observed = token.get("decimals")
        if observed is not None and expected is not None and int(observed) != expected:
            raise ValueError(
                f"{pool} {label} decimals disagree with the audited registry: "
                f"{observed} versus {expected}"
            )
    return PoolStatic(pool, token0_address, token1_address, decimals0, decimals1)


def graph_token_observations(
    graph_root: Path,
    venue: str,
    day: str,
    statics: dict[str, PoolStatic],
) -> tuple[set[str], dict[str, list[object]]]:
    """Read provider token reports without asserting an exact event identity."""

    observed_pools: set[str] = set()
    observations: dict[str, list[object]] = {}
    for stream in ("mints", "burns", "swaps"):
        for row in iter_graph_rows(graph_stream_path(graph_root, venue, stream, day)):
            observed = _pool_static_from_row(row, {})
            static = statics.get(observed.pool)
            if static is None:
                raise ValueError(
                    f"V2 event pool {observed.pool} is absent from the factory registry"
                )
            if (observed.token0, observed.token1) != (static.token0, static.token1):
                raise ValueError(
                    f"Graph event disagrees with factory pair identity for {observed.pool}"
                )
            pair = row["pair"]
            for token_name, token_address in (
                ("token0", observed.token0),
                ("token1", observed.token1),
            ):
                token = pair[token_name]
                value = token.get("decimals")
                distinct = observations.setdefault(token_address, [])
                if value not in distinct:
                    distinct.append(value)
            observed_pools.add(observed.pool)
    return observed_pools, observations


def canonical_v2_pool_templates(
    statics: dict[str, PoolStatic],
) -> dict[str, dict[str, object]]:
    """Build supplement templates only from factory identity and audited decimals."""

    templates: dict[str, dict[str, object]] = {}
    for pool, static in statics.items():
        if pool != static.pool or static.decimals0 is None or static.decimals1 is None:
            raise ValueError(f"V2 canonical pool template lacks audited identity: {pool}")
        templates[pool] = {
            "id": pool,
            "token0": {"id": static.token0, "decimals": str(static.decimals0)},
            "token1": {"id": static.token1, "decimals": str(static.decimals1)},
        }
    return templates


def decode_pair_created_log(venue: str, log: dict[str, object]) -> FactoryPair:
    """Decode one canonical factory log into an independently registered V2 pair."""

    factory = _address(log.get("address"), label=f"{venue} factory")
    if factory != V2_FACTORIES[venue]:
        raise ValueError(f"PairCreated log came from an unregistered {venue} factory")
    if bool(log.get("removed")):
        raise ValueError("removed PairCreated log cannot enter the pool registry")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if len(topics) != 3 or topics[0] != PAIR_CREATED_TOPIC:
        raise ValueError("factory log is not an exact PairCreated event")
    token0 = _address("0x" + topics[1][-40:], label="PairCreated token0")
    token1 = _address("0x" + topics[2][-40:], label="PairCreated token1")
    pool, ordinal = abi_decode(
        ["address", "uint256"],
        bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x")),
    )
    pool = _address(pool, label="PairCreated pair")
    if token0 == "0x" + "0" * 40 or token1 == "0x" + "0" * 40 or pool == "0x" + "0" * 40:
        raise ValueError("PairCreated contains a zero token or pair address")
    if token0 >= token1:
        raise ValueError("PairCreated token order violates the factory contract")
    if int(ordinal) < 1:
        raise ValueError("PairCreated ordinal must be positive")
    return FactoryPair(
        venue=venue,
        factory=factory,
        pool=pool,
        token0=token0,
        token1=token1,
        creation_block=rpc_integer(log.get("blockNumber", log.get("block_number"))),
        creation_tx_hash=_transaction_hash(
            log.get("transactionHash", log.get("transaction_hash")),
            label="PairCreated",
        ),
        creation_log_index=rpc_integer(log.get("logIndex", log.get("log_index"))),
        ordinal=int(ordinal),
    )


def factory_pair_registry(
    venue: str,
    records: Iterable[dict[str, object]],
    token_decimals: dict[str, int],
) -> tuple[dict[str, PoolStatic], list[FactoryPair]]:
    """Build a fail-closed pool registry from the factory's complete event history."""

    by_pool: dict[str, FactoryPair] = {}
    by_ordinal: dict[int, FactoryPair] = {}
    by_tokens: dict[tuple[str, str], FactoryPair] = {}
    by_identity: dict[tuple[int, str, int], FactoryPair] = {}
    for record in records:
        pair = decode_pair_created_log(venue, record)
        if pair.pool in by_pool:
            raise ValueError(f"duplicate PairCreated pool identity: {pair.pool}")
        if pair.ordinal in by_ordinal:
            raise ValueError(f"duplicate PairCreated ordinal: {pair.ordinal}")
        token_key = (pair.token0, pair.token1)
        if token_key in by_tokens:
            raise ValueError(f"duplicate PairCreated token identity: {token_key}")
        identity = (pair.creation_block, pair.creation_tx_hash, pair.creation_log_index)
        if identity in by_identity:
            raise ValueError(f"duplicate PairCreated chain identity: {identity}")
        by_pool[pair.pool] = pair
        by_ordinal[pair.ordinal] = pair
        by_tokens[token_key] = pair
        by_identity[identity] = pair
    expected_ordinals = set(range(1, len(by_ordinal) + 1))
    if set(by_ordinal) != expected_ordinals:
        missing = sorted(expected_ordinals - set(by_ordinal))[:3]
        raise ValueError(f"factory PairCreated sequence is incomplete; missing={missing}")
    chronological = sorted(
        by_pool.values(),
        key=lambda pair: (pair.creation_block, pair.creation_log_index),
    )
    if [pair.ordinal for pair in chronological] != list(range(1, len(chronological) + 1)):
        raise ValueError("factory PairCreated ordinals disagree with exact chain order")
    statics = {
        pair.pool: PoolStatic(
            pool=pair.pool,
            token0=pair.token0,
            token1=pair.token1,
            decimals0=token_decimals.get(pair.token0),
            decimals1=token_decimals.get(pair.token1),
        )
        for pair in by_pool.values()
    }
    return statics, sorted(by_pool.values(), key=lambda pair: pair.ordinal)


def factory_registry_sha256(pairs: Iterable[FactoryPair]) -> str:
    rows = [asdict(pair) for pair in sorted(pairs, key=lambda pair: (pair.venue, pair.ordinal))]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def deterministic_factory_state_sample(
    pairs: Iterable[FactoryPair],
    *,
    sample_size: int = V2_FACTORY_STATE_SAMPLE_SIZE,
) -> list[FactoryPair]:
    """Select fixed boundary plus hash-ranked ordinals without Graph input."""

    ordered = sorted(pairs, key=lambda pair: pair.ordinal)
    if sample_size < 1:
        raise ValueError("factory state sample size must be positive")
    if len(ordered) <= sample_size:
        return ordered
    if sample_size == 1:
        return [ordered[0]]
    forced = {ordered[0].ordinal, ordered[-1].ordinal}
    ranked = sorted(
        (pair for pair in ordered if pair.ordinal not in forced),
        key=lambda pair: hashlib.sha256(
            f"v2-factory-state-v1:{pair.venue}:{pair.ordinal}:{pair.pool}".encode()
        ).digest(),
    )
    chosen = [ordered[0], ordered[-1], *ranked[: sample_size - 2]]
    return sorted(chosen, key=lambda pair: pair.ordinal)


def _rpc_result_address(result: object, *, label: str) -> str:
    value = str(result or "")
    if not value.startswith("0x") or len(value) != 66:
        raise ValueError(f"{label} lacks an exact ABI address result")
    return _address("0x" + value[-40:], label=label)


def _factory_state_batch(
    specs: list[dict[str, object]],
    *,
    upper_block: int,
    upper_block_hash: str,
    rpc_request=None,
) -> list[dict[str, object]]:
    block_reference = {
        "blockHash": upper_block_hash,
        "requireCanonical": True,
    }
    payload = [
        {
            "jsonrpc": "2.0",
            "id": int(spec["id"]),
            "method": "eth_call",
            "params": [
                {"to": spec["target"], "data": spec["data"]},
                block_reference,
            ],
        }
        for spec in specs
    ]
    requests_by_id = {int(request["id"]): request for request in payload}
    envelope = _rpc_envelope(payload, rpc_request)
    responses = envelope.response
    if not isinstance(responses, list):
        raise RuntimeError("factory state batch lacks a JSON-RPC result list")
    by_id = {
        int(response["id"]): response
        for response in responses
        if isinstance(response, dict) and "id" in response
    }
    if set(by_id) != {int(spec["id"]) for spec in specs}:
        raise RuntimeError("factory state batch response IDs are incomplete")
    evidence: list[dict[str, object]] = []
    for spec in specs:
        response = by_id[int(spec["id"])]
        if response.get("error") is not None:
            raise RuntimeError(f"factory state call failed: {response['error']}")
        observed = _rpc_result_address(
            response.get("result"),
            label=f"factory {spec['method']}",
        )
        expected = str(spec["expected"])
        if observed != expected:
            raise ValueError(
                f"factory state disagrees at ordinal {spec['ordinal']} for {spec['method']}: "
                f"{observed} != {expected}"
            )
        evidence.append(
            {
                "id": int(spec["id"]),
                "ordinal": int(spec["ordinal"]),
                "method": spec["method"],
                "expected": expected,
                "observed": observed,
                "target": spec["target"],
                "calldata": spec["data"],
                "upper_block": upper_block,
                "upper_block_hash": upper_block_hash,
                "rpc_request": requests_by_id[int(spec["id"])],
                "rpc_response": response,
                "response_sha256": _canonical_json_sha256(response),
                "rpc_endpoint": envelope.endpoint,
                "rpc_attempts": list(envelope.attempts),
            }
        )
    return evidence


def validate_factory_state_proof(
    proof: dict[str, object],
    *,
    venue: str,
    pairs: list[FactoryPair],
    frozen_upper: dict[str, object],
    sample_size: int = V2_FACTORY_STATE_SAMPLE_SIZE,
) -> None:
    expected_sample = deterministic_factory_state_sample(pairs, sample_size=sample_size)
    upper_block = int(frozen_upper["block_number"])
    upper_block_hash = str(frozen_upper["block_hash"])
    expected = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": V2_FACTORIES[venue],
        "upper_block": upper_block,
        "upper_block_hash": upper_block_hash,
        "registry_rows": len(pairs),
        "all_pairs_length": len(pairs),
        "registry_sha256": factory_registry_sha256(pairs),
        "sample_size": len(expected_sample),
        "sample_contract": "first_last_plus_sha256_ranked_ordinals_v1",
    }
    stale = {
        key: (proof.get(key), value)
        for key, value in expected.items()
        if proof.get(key) != value
    }
    if stale:
        raise ValueError(f"V2 factory state proof is stale or count-mismatched: {stale}")
    block_reference = {
        "blockHash": upper_block_hash,
        "requireCanonical": True,
    }
    expected_length_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": V2_FACTORIES[venue], "data": ALL_PAIRS_LENGTH_SELECTOR},
            block_reference,
        ],
    }
    if proof.get("length_rpc_request") != expected_length_request:
        raise ValueError("V2 factory state proof lacks exact length RPC request evidence")
    length_response = proof.get("length_rpc_response")
    if not isinstance(length_response, dict):
        raise ValueError("V2 factory state proof lacks exact length RPC response evidence")
    if proof.get("length_rpc_response_sha256") != _canonical_json_sha256(length_response):
        raise ValueError("V2 factory state proof length response digest disagrees")
    length_result = length_response.get("result")
    if not isinstance(length_result, str) or not length_result.startswith("0x"):
        raise ValueError("V2 factory state proof length response is not revalidatable")
    if int(length_result, 16) != len(pairs):
        raise ValueError("V2 factory state proof length response disagrees with the registry")
    length_endpoint = proof.get("length_rpc_endpoint")
    try:
        validate_rpc_attempts(proof.get("length_rpc_attempts"), length_endpoint)
    except ValueError as error:
        raise ValueError("V2 factory state proof has invalid length RPC attempt evidence") from error
    results = proof.get("sample_results")
    if not isinstance(results, list):
        raise ValueError("V2 factory state proof lacks sample results")
    expected_specs: dict[tuple[int, str], dict[str, object]] = {}
    for pair in expected_sample:
        expected_specs[(pair.ordinal, "allPairs")] = {
            "target": pair.factory,
            "calldata": ALL_PAIRS_SELECTOR + abi_encode(["uint256"], [pair.ordinal - 1]).hex(),
            "expected": pair.pool,
        }
        expected_specs[(pair.ordinal, "getPair")] = {
            "target": pair.factory,
            "calldata": GET_PAIR_SELECTOR + abi_encode(["address", "address"], [pair.token0, pair.token1]).hex(),
            "expected": pair.pool,
        }
    observed_keys: set[tuple[int, str]] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("V2 factory state proof contains malformed sample evidence")
        key = (int(result.get("ordinal", -1)), str(result.get("method") or ""))
        spec = expected_specs.get(key)
        if spec is None or key in observed_keys:
            raise ValueError("V2 factory state proof sample is incomplete or duplicated")
        observed_keys.add(key)
        if (
            result.get("target") != spec["target"]
            or result.get("calldata") != spec["calldata"]
            or int(result.get("upper_block", -1)) != upper_block
            or result.get("upper_block_hash") != upper_block_hash
        ):
            raise ValueError("V2 factory state proof sample request or calldata evidence disagrees")
        expected_request = {
            "jsonrpc": "2.0",
            "id": int(result.get("id", -1)),
            "method": "eth_call",
            "params": [
                {"to": spec["target"], "data": spec["calldata"]},
                block_reference,
            ],
        }
        if result.get("rpc_request") != expected_request:
            raise ValueError("V2 factory state proof sample RPC request evidence disagrees")
        response = result.get("rpc_response")
        if not isinstance(response, dict) or response.get("error") is not None:
            raise ValueError("V2 factory state proof lacks an exact sample RPC response")
        if result.get("response_sha256") != _canonical_json_sha256(response):
            raise ValueError("V2 factory state proof sample response digest disagrees")
        observed = _rpc_result_address(response.get("result"), label="factory state proof sample")
        if result.get("expected") != spec["expected"] or result.get("observed") != observed or observed != spec["expected"]:
            raise ValueError("V2 factory state proof sample result disagrees with exact RPC evidence")
        endpoint = result.get("rpc_endpoint")
        try:
            validate_rpc_attempts(result.get("rpc_attempts"), endpoint)
        except ValueError as error:
            raise ValueError("V2 factory state proof sample has invalid RPC attempt evidence") from error
    if observed_keys != set(expected_specs) or len(results) != len(expected_specs):
        raise ValueError("V2 factory state proof sample is incomplete or mismatched")


def build_factory_state_proof(
    venue: str,
    pairs: list[FactoryPair],
    frozen_upper: dict[str, object],
    *,
    sample_size: int = V2_FACTORY_STATE_SAMPLE_SIZE,
    workers: int = 4,
    rpc_request=None,
) -> dict[str, object]:
    """Prove exact event count and a deterministic state identity sample at frozen U."""

    validate_frozen_upper_block(frozen_upper, int(frozen_upper["block_number"]))
    upper_block = int(frozen_upper["block_number"])
    upper_block_hash = str(frozen_upper["block_hash"])
    block_reference = {
        "blockHash": upper_block_hash,
        "requireCanonical": True,
    }
    length_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": V2_FACTORIES[venue], "data": ALL_PAIRS_LENGTH_SELECTOR},
            block_reference,
        ],
    }
    length_envelope = _rpc_envelope(length_payload, rpc_request)
    length_response = length_envelope.response
    if isinstance(length_response, dict) and length_response.get("error") is not None:
        raise RuntimeError(
            f"historical allPairsLength failed at frozen canonical block hash: {length_response['error']}"
        )
    result = length_response.get("result") if isinstance(length_response, dict) else None
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError("historical allPairsLength lacks an exact result")
    observed_length = int(result, 16)
    if observed_length != len(pairs):
        raise ValueError(
            f"historical allPairsLength disagrees with PairCreated sequence: "
            f"{observed_length} != {len(pairs)}"
        )
    sample = deterministic_factory_state_sample(pairs, sample_size=sample_size)
    specs: list[dict[str, object]] = []
    for pair in sample:
        specs.extend(
            [
                {
                    "id": len(specs),
                    "ordinal": pair.ordinal,
                    "method": "allPairs",
                    "target": pair.factory,
                    "data": ALL_PAIRS_SELECTOR + abi_encode(["uint256"], [pair.ordinal - 1]).hex(),
                    "expected": pair.pool,
                },
                {
                    "id": len(specs) + 1,
                    "ordinal": pair.ordinal,
                    "method": "getPair",
                    "target": pair.factory,
                    "data": GET_PAIR_SELECTOR + abi_encode(["address", "address"], [pair.token0, pair.token1]).hex(),
                    "expected": pair.pool,
                },
            ]
        )
    batches = [specs[offset : offset + 3] for offset in range(0, len(specs), 3)]
    sample_results: list[dict[str, object]] = []
    with interruptible_thread_pool(max_workers=max(1, min(workers, 4))) as executor:
        futures = [
            executor.submit(
                _factory_state_batch,
                batch,
                upper_block=upper_block,
                upper_block_hash=upper_block_hash,
                rpc_request=rpc_request,
            )
            for batch in batches
        ]
        for future in as_completed(futures):
            sample_results.extend(future.result())
    sample_results.sort(key=lambda item: int(item["id"]))
    proof = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": V2_FACTORIES[venue],
        "upper_block": upper_block,
        "upper_block_hash": frozen_upper["block_hash"],
        "registry_rows": len(pairs),
        "all_pairs_length": observed_length,
        "registry_sha256": factory_registry_sha256(pairs),
        "sample_size": len(sample),
        "sample_contract": "first_last_plus_sha256_ranked_ordinals_v1",
        "length_rpc_request": length_payload,
        "length_rpc_response": length_response,
        "length_rpc_response_sha256": _canonical_json_sha256(length_response),
        "length_rpc_endpoint": length_envelope.endpoint,
        "length_rpc_attempts": list(length_envelope.attempts),
        "sample_results": sample_results,
    }
    validate_factory_state_proof(
        proof,
        venue=venue,
        pairs=pairs,
        frozen_upper=frozen_upper,
        sample_size=sample_size,
    )
    return proof


def factory_state_proof_path(
    venue: str,
    upper_block: int,
    *,
    root: Path | None = None,
) -> Path:
    return (root or RAW_V2_FACTORY_ROOT) / venue / f"state_proof_{upper_block:08d}.json"


def load_or_build_factory_state_proof(
    venue: str,
    pairs: list[FactoryPair],
    frozen_upper: dict[str, object],
    *,
    fetch: bool,
    sample_size: int = V2_FACTORY_STATE_SAMPLE_SIZE,
    workers: int = 4,
    root: Path | None = None,
    rpc_request=None,
) -> dict[str, object]:
    path = factory_state_proof_path(
        venue,
        int(frozen_upper["block_number"]),
        root=root,
    )
    if path.is_file():
        proof = json.loads(path.read_text(encoding="utf-8"))
        validate_factory_state_proof(
            proof,
            venue=venue,
            pairs=pairs,
            frozen_upper=frozen_upper,
            sample_size=sample_size,
        )
        return proof
    if not fetch:
        raise RuntimeError(f"V2 factory registry lacks historical state proof for {venue}")
    proof = build_factory_state_proof(
        venue,
        pairs,
        frozen_upper,
        sample_size=sample_size,
        workers=workers,
        rpc_request=rpc_request,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, proof)
    return proof


def _graph_event_amounts(
    row: dict[str, object],
    event_type: str,
    static: PoolStatic,
) -> EventAmounts:
    if static.decimals0 is None or static.decimals1 is None:
        missing = [
            token
            for token, decimals in (
                (static.token0, static.decimals0),
                (static.token1, static.decimals1),
            )
            if decimals is None
        ]
        raise ValueError(
            f"{static.pool} event token decimals are absent from the audited registry: "
            f"{missing}"
        )
    if event_type == "swap":
        amount0_in = _exact_raw(row.get("amount0In") or "0", static.decimals0, label="amount0In")
        amount1_in = _exact_raw(row.get("amount1In") or "0", static.decimals1, label="amount1In")
        amount0_out = _exact_raw(row.get("amount0Out") or "0", static.decimals0, label="amount0Out")
        amount1_out = _exact_raw(row.get("amount1Out") or "0", static.decimals1, label="amount1Out")
        return EventAmounts(
            amount0_in - amount0_out,
            amount1_in - amount1_out,
            amount0_in,
            amount1_in,
            amount0_out,
            amount1_out,
        )
    amount0 = _exact_raw(row.get("amount0"), static.decimals0, label="amount0")
    amount1 = _exact_raw(row.get("amount1"), static.decimals1, label="amount1")
    sign = 1 if event_type == "mint" else -1
    return EventAmounts(sign * amount0, sign * amount1, 0, 0, 0, 0)


def _add_event(
    events: dict[EventKey, object],
    duplicates: set[EventKey],
    key: EventKey,
    value: object,
) -> None:
    if key in events:
        duplicates.add(key)
        return
    events[key] = value


def graph_core_event_rows(
    graph_root: Path,
    venue: str,
    day: str,
    statics: dict[str, PoolStatic],
    *,
    provider_observations: dict[str, list[object]] | None = None,
) -> tuple[dict[EventKey, tuple[dict[str, object], str, PoolStatic]], set[EventKey]]:
    """Read Graph identities and token metadata before any decimal conversion."""

    rows_by_stream = {
        stream: iter_graph_rows(graph_stream_path(graph_root, venue, stream, day))
        for stream in ("mints", "burns", "swaps")
    }
    return provider_core_event_rows(
        rows_by_stream,
        venue,
        statics,
        provider_observations=provider_observations,
    )


def provider_core_event_rows(
    rows_by_stream: Mapping[str, Iterable[dict[str, object]]],
    venue: str,
    statics: dict[str, PoolStatic],
    *,
    provider_observations: dict[str, list[object]] | None = None,
) -> tuple[dict[EventKey, tuple[dict[str, object], str, PoolStatic]], set[EventKey]]:
    """Parse provider-shaped V2 rows from raw or corrected canonical streams."""

    if set(rows_by_stream) != {"mints", "burns", "swaps"}:
        raise ValueError("V2 core-event rows require exact mint, burn, and swap streams")
    events: dict[EventKey, tuple[dict[str, object], str, PoolStatic]] = {}
    duplicates: set[EventKey] = set()
    for event_type, stream in (("mint", "mints"), ("burn", "burns"), ("swap", "swaps")):
        for row in rows_by_stream[stream]:
            pair = row.get("pair")
            pool = _address(pair.get("id") if isinstance(pair, dict) else None, label="V2 event pool")
            static = statics.get(pool)
            if static is None:
                raise ValueError(f"V2 event pool {pool} is absent from the factory registry")
            observed = _pool_static_from_row(
                row,
                {
                    token: decimals
                    for token, decimals in (
                        (static.token0, static.decimals0),
                        (static.token1, static.decimals1),
                    )
                    if decimals is not None
                },
            )
            if (observed.pool, observed.token0, observed.token1) != (
                static.pool,
                static.token0,
                static.token1,
            ):
                raise ValueError(f"Graph event disagrees with factory pair identity for {pool}")
            if provider_observations is not None and isinstance(pair, dict):
                for token_name, token_address in (
                    ("token0", observed.token0),
                    ("token1", observed.token1),
                ):
                    token = pair.get(token_name)
                    if isinstance(token, dict):
                        value = token.get("decimals")
                        distinct = provider_observations.setdefault(token_address, [])
                        if value not in distinct:
                            distinct.append(value)
            transaction = row.get("transaction")
            tx_hash = transaction.get("id") if isinstance(transaction, dict) else transaction
            block = transaction.get("blockNumber") if isinstance(transaction, dict) else None
            key = event_key(
                venue,
                event_type,
                block,
                tx_hash,
                row.get("logIndex"),
                pool,
            )
            _add_event(events, duplicates, key, (row, event_type, static))
    return events, duplicates


def provider_core_events(
    rows_by_stream: Mapping[str, Iterable[dict[str, object]]],
    venue: str,
    statics: dict[str, PoolStatic],
) -> tuple[dict[EventKey, EventAmounts], set[EventKey]]:
    """Decode one corrected provider-shaped ledger at exact identity and quantities."""

    rows, duplicates = provider_core_event_rows(rows_by_stream, venue, statics)
    return {
        key: _graph_event_amounts(row, event_type, static)
        for key, (row, event_type, static) in rows.items()
    }, duplicates


def graph_core_events(
    graph_root: Path,
    venue: str,
    day: str,
    statics: dict[str, PoolStatic],
) -> tuple[dict[EventKey, EventAmounts | None], set[EventKey]]:
    return graph_core_events_for_amount_keys(
        graph_root,
        venue,
        day,
        statics,
        amount_keys=None,
    )


def graph_core_events_for_amount_keys(
    graph_root: Path,
    venue: str,
    day: str,
    statics: dict[str, PoolStatic],
    *,
    amount_keys: set[EventKey] | None,
) -> tuple[dict[EventKey, EventAmounts | None], set[EventKey]]:
    """Decode amounts only where identity comparison says an amount is needed."""

    rows, duplicates = graph_core_event_rows(graph_root, venue, day, statics)
    events: dict[EventKey, EventAmounts | None] = {}
    for key, (row, event_type, static) in rows.items():
        events[key] = (
            _graph_event_amounts(row, event_type, static)
            if amount_keys is None or key in amount_keys
            else None
        )
    return events, duplicates


def decode_v2_log(venue: str, log: dict[str, object]) -> tuple[EventKey, EventAmounts]:
    """Decode one canonical raw V2 log into exact event identity and raw amounts."""

    if bool(log.get("removed")):
        raise ValueError("removed V2 log cannot enter the source certificate")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if not topics or topics[0] not in V2_EVENT_BY_TOPIC:
        raise ValueError("log is not a registered V2 core event")
    event_type = V2_EVENT_BY_TOPIC[topics[0]]
    data = bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x"))
    if event_type == "swap":
        amount0_in, amount1_in, amount0_out, amount1_out = (
            int(value)
            for value in abi_decode(["uint256", "uint256", "uint256", "uint256"], data)
        )
        amounts = EventAmounts(
            amount0_in - amount0_out,
            amount1_in - amount1_out,
            amount0_in,
            amount1_in,
            amount0_out,
            amount1_out,
        )
    else:
        amount0, amount1 = (int(value) for value in abi_decode(["uint256", "uint256"], data))
        sign = 1 if event_type == "mint" else -1
        amounts = EventAmounts(sign * amount0, sign * amount1, 0, 0, 0, 0)
    key = event_key(
        venue,
        event_type,
        rpc_integer(log.get("blockNumber", log.get("block_number"))),
        log.get("transactionHash", log.get("transaction_hash")),
        rpc_integer(log.get("logIndex", log.get("log_index"))),
        log.get("address"),
    )
    return key, amounts


def raw_core_events(
    venue: str,
    records: Iterable[dict[str, object]],
    *,
    expected_pools: set[str],
    expected_creation_blocks: dict[str, int] | None = None,
    ignore_unregistered: bool = False,
) -> dict[EventKey, EventAmounts]:
    rows = raw_core_event_records(
        venue,
        records,
        expected_pools=expected_pools,
        expected_creation_blocks=expected_creation_blocks,
        ignore_unregistered=ignore_unregistered,
    )
    return {key: decode_v2_log(venue, record)[1] for key, record in rows.items()}


def raw_core_event_records(
    venue: str,
    records: Iterable[dict[str, object]],
    *,
    expected_pools: set[str],
    expected_creation_blocks: dict[str, int] | None = None,
    ignore_unregistered: bool = False,
) -> dict[EventKey, dict[str, object]]:
    """Retain exact raw records so their block hashes can anchor contract state."""

    events: dict[EventKey, dict[str, object]] = {}
    duplicates: set[EventKey] = set()
    for record in records:
        pool = _address(record.get("address"), label="raw V2 event pool")
        if pool not in expected_pools and ignore_unregistered:
            continue
        key, _amounts = decode_v2_log(venue, record)
        if key[-1] not in expected_pools:
            raise ValueError(f"raw V2 log pool outside the declared batch perimeter: {key[-1]}")
        if (
            expected_creation_blocks is not None
            and key[2] < expected_creation_blocks[key[-1]]
        ):
            raise ValueError(f"raw V2 event predates its PairCreated identity: {key}")
        _add_event(events, duplicates, key, record)
    if duplicates:
        raise ValueError(f"exact raw V2 audit has {len(duplicates):,} duplicate identities")
    return events


def _amount_columns(prefix: str, amounts: EventAmounts | None) -> dict[str, str | None]:
    values = asdict(amounts) if amounts is not None else {}
    return {
        f"{prefix}_{name}": str(values[name]) if name in values else None
        for name in EventAmounts.__dataclass_fields__
    }


def _exception_row(
    day: str,
    key: EventKey,
    status: str,
    exact: EventAmounts | None,
    canonical: EventAmounts | None,
) -> dict[str, object]:
    venue, event_type, block, tx_hash, log_index, pool = key
    return {
        "day": day,
        "venue": venue,
        "event_type": event_type,
        "status": status,
        "block_number": block,
        "tx_hash": tx_hash,
        "log_index": log_index,
        "pool": pool,
        **_amount_columns("exact", exact),
        **_amount_columns("canonical", canonical),
    }


def compare_event_maps(
    day: str,
    venue: str,
    exact: dict[EventKey, EventAmounts],
    canonical: dict[EventKey, EventAmounts | None],
    canonical_duplicates: set[EventKey],
    *,
    launch_status: str = "audited",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    for event_type in V2_CORE_EVENTS:
        exact_keys = {key for key in exact if key[1] == event_type}
        canonical_keys = {key for key in canonical if key[1] == event_type}
        matched = exact_keys & canonical_keys
        missing = exact_keys - canonical_keys
        canonical_only = canonical_keys - exact_keys
        duplicates = {key for key in canonical_duplicates if key[1] == event_type}
        unavailable = {key for key in matched if canonical[key] is None}
        if unavailable:
            raise ValueError(
                f"matched V2 identities lack decoded canonical amounts: {sorted(unavailable)[:3]}"
            )
        mismatches = {key for key in matched if exact[key] != canonical[key]}
        summaries.append(
            {
                "day": day,
                "venue": venue,
                "event_type": event_type,
                "launch_status": launch_status,
                "exact_events": len(exact_keys),
                "canonical_events": len(canonical_keys),
                "matched_identities": len(matched),
                "missing_from_canonical": len(missing),
                "canonical_only": len(canonical_only),
                "canonical_duplicate_identities": len(duplicates),
                "amount_mismatches": len(mismatches),
                "passed": not (missing or canonical_only or duplicates or mismatches),
            }
        )
        exceptions.extend(
            _exception_row(day, key, "missing_from_canonical", exact[key], None)
            for key in sorted(missing)
        )
        exceptions.extend(
            _exception_row(day, key, "canonical_only", None, canonical[key])
            for key in sorted(canonical_only)
        )
        exceptions.extend(
            _exception_row(day, key, "amount_mismatch", exact[key], canonical[key])
            for key in sorted(mismatches)
        )
        exceptions.extend(
            _exception_row(day, key, "canonical_duplicate_identity", exact.get(key), canonical.get(key))
            for key in sorted(duplicates)
        )
    return summaries, exceptions


def canonical_v2_reconciliation_counts(
    audit: Mapping[str, object],
    *,
    canonical_rows: int,
) -> dict[str, int]:
    """Translate one exact reconciliation audit into the certificate contract."""

    if any(
        type(audit.get(field)) is not int or int(audit[field]) != 0
        for field in (
            "ignored_zero_liquidity_events",
            "unmatched_graph_events",
            "unmatched_exact_events",
        )
    ):
        raise ValueError("V2 reconciliation retained ignored or unmatched events")
    values = {
        "provider_rows": audit.get("graph_events"),
        "unique_provider_events": audit.get("unique_graph_events"),
        "provider_duplicate_rows": audit.get("provider_duplicate_rows"),
        "exact_events_in_provider_observed_pool_perimeter": audit.get(
            "exact_events_in_graph_pool_perimeter"
        ),
        "exact_events_in_factory_pool_perimeter": audit.get(
            "exact_events_in_reconciliation_pool_perimeter"
        ),
        "matched_events": audit.get("matched_events"),
        "correction_rows": audit.get("correction_rows"),
        "log_index_repairs": audit.get("log_index_repairs"),
        "payload_repairs": audit.get("payload_mismatches"),
        "incomplete_liquidity_repairs": audit.get(
            "incomplete_liquidity_status_repairs"
        ),
        "exclusion_rows": audit.get("exclusion_rows"),
        "reverted_transaction_exclusions": audit.get(
            "reverted_transaction_exclusions"
        ),
        "successful_transaction_absence_exclusions": audit.get(
            "successful_transaction_absence_exclusions"
        ),
        "incomplete_liquidity_absence_exclusions": audit.get(
            "incomplete_liquidity_absence_exclusions"
        ),
        "provider_duplicate_exclusions": audit.get(
            "provider_duplicate_exclusions"
        ),
        "supplement_rows": audit.get("supplement_rows"),
        "canonical_rows": canonical_rows,
    }
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("V2 reconciliation audit contains invalid counts")
    return values


def expected_summary_keys(days: Iterable[str]) -> set[tuple[str, str, str]]:
    return {
        (venue, day, event_type)
        for venue in V2_EVENT_VENUES
        for day in days
        for event_type in V2_CORE_EVENTS
    }


def validate_v2_event_source_certificate(
    summary: pd.DataFrame,
    exceptions: pd.DataFrame,
    certificate: dict[str, object],
    expected_days: list[str],
) -> tuple[int, int]:
    """Validate exact calendar, identities, quantities, and zero-exception release."""

    required = {
        "day",
        "venue",
        "event_type",
        "launch_status",
        "exact_events",
        "canonical_events",
        "matched_identities",
        "missing_from_canonical",
        "canonical_only",
        "canonical_duplicate_identities",
        "amount_mismatches",
        "passed",
    }
    missing_columns = sorted(required - set(summary.columns))
    if missing_columns:
        raise ValueError(f"V2 event-source summary lacks columns: {missing_columns}")
    if summary.duplicated(["venue", "day", "event_type"]).any():
        raise ValueError("V2 event-source summary contains duplicate keys")
    actual = set(
        summary[["venue", "day", "event_type"]].astype(str).itertuples(index=False, name=None)
    )
    expected = expected_summary_keys(expected_days)
    if actual != expected:
        raise ValueError(
            "V2 event-source calendar does not match the frontier audit calendar: "
            f"missing={sorted(expected - actual)[:3]}, extra={sorted(actual - expected)[:3]}"
        )
    count_columns = [
        "exact_events",
        "canonical_events",
        "matched_identities",
        "missing_from_canonical",
        "canonical_only",
        "canonical_duplicate_identities",
        "amount_mismatches",
    ]
    if any(
        not pd.api.types.is_integer_dtype(summary[column].dtype)
        or pd.api.types.is_bool_dtype(summary[column].dtype)
        for column in count_columns
    ):
        raise ValueError("V2 event-source summary counts are not integer typed")
    counts = summary[count_columns]
    if counts.isna().any().any() or (counts < 0).any().any():
        raise ValueError("V2 event-source summary contains invalid counts")
    if not pd.api.types.is_bool_dtype(summary["passed"].dtype) or summary["passed"].isna().any():
        raise ValueError("V2 event-source summary pass flag is not Boolean")
    for index, row in counts.iterrows():
        exact_events = int(row["exact_events"])
        canonical_events = int(row["canonical_events"])
        matched = int(row["matched_identities"])
        missing = int(row["missing_from_canonical"])
        canonical_only = int(row["canonical_only"])
        duplicates = int(row["canonical_duplicate_identities"])
        mismatches = int(row["amount_mismatches"])
        if exact_events != matched + missing or canonical_events != matched + canonical_only:
            raise ValueError("V2 event-source summary contains impossible identity count algebra")
        if matched > min(exact_events, canonical_events) or duplicates > canonical_events or mismatches > matched:
            raise ValueError("V2 event-source summary contains impossible comparison counts")
        expected_pass = not (missing or canonical_only or duplicates or mismatches)
        observed_pass = summary.loc[index, "passed"]
        if bool(observed_pass) != expected_pass:
            raise ValueError("V2 event-source summary pass flag disagrees with its counts")
    failures = counts[["missing_from_canonical", "canonical_only", "canonical_duplicate_identities", "amount_mismatches"]].sum(axis=1)
    if int(failures.sum()) != 0:
        raise ValueError("V2 event-source summary contains failed comparisons")
    for row in summary.itertuples(index=False):
        genesis = get_source(str(row.venue)).genesis.strftime("%Y%m%d")
        expected_status = "pre_genesis" if str(row.day) < genesis else "audited"
        if str(row.launch_status) != expected_status:
            raise ValueError(
                f"V2 event-source launch status is wrong for {row.venue}/{row.day}: "
                f"{row.launch_status}"
            )
        if expected_status == "pre_genesis" and any(int(getattr(row, name)) for name in count_columns):
            raise ValueError(f"pre-genesis V2 event row is nonzero for {row.venue}/{row.day}")
    if not exceptions.empty:
        raise ValueError(f"V2 event-source certificate has {len(exceptions):,} exception rows")
    expected_hash = audit_calendar_sha256(expected_days)
    expected_certificate = {
        "schema_version": V2_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": expected_hash,
        "audit_dates": len(expected_days),
        "first_day": expected_days[0],
        "last_day": expected_days[-1],
        "summary_rows": len(expected),
        "exception_rows": 0,
        "venues": list(V2_EVENT_VENUES),
        "event_types": list(V2_CORE_EVENTS),
        "pool_perimeter": V2_POOL_PERIMETER,
        "reconciliation_scope": V2_RECONCILIATION_SCOPE,
        "comparison_ledger": V2_COMPARISON_LEDGER,
        "registry_source": "complete_factory_PairCreated_histories",
        "global_event_query": "topic_only_without_address_filter",
        "identity_fields": [
            "venue",
            "event_type",
            "block_number",
            "transaction_hash",
            "log_index",
            "pool",
        ],
        "quantity_contract": "exact_raw_token_deltas_and_swap_in_out_fields",
        "token_decimals_contract": V2_TOKEN_DECIMALS_CONTRACT,
        "token_decimals_scope": V2_TOKEN_DECIMALS_SCOPE,
    }
    mismatched = {
        key: (certificate.get(key), value)
        for key, value in expected_certificate.items()
        if certificate.get(key) != value
    }
    if mismatched:
        raise ValueError(f"V2 event-source certificate fields are stale: {mismatched}")
    for field in count_columns:
        if type(certificate.get(field)) is not int or certificate[field] != int(counts[field].sum()):
            raise ValueError(f"V2 event-source certificate total disagrees for {field}")
    correction_schema = certificate.get("correction_generation_schema_version")
    if type(correction_schema) is not int or correction_schema != EVENT_ORDER_SCHEMA_VERSION:
        raise ValueError("V2 event-source certificate lacks a correction-generation schema")
    reconciliation = certificate.get("reconciliation_totals")
    if not isinstance(reconciliation, dict) or set(reconciliation) != set(V2_RECONCILIATION_COUNT_FIELDS):
        raise ValueError("V2 event-source certificate lacks exact reconciliation totals")
    if any(type(reconciliation[field]) is not int for field in V2_RECONCILIATION_COUNT_FIELDS):
        raise ValueError("V2 event-source certificate has malformed reconciliation totals")
    reconciliation_counts = {
        field: reconciliation[field] for field in V2_RECONCILIATION_COUNT_FIELDS
    }
    if any(value < 0 for value in reconciliation_counts.values()):
        raise ValueError("V2 event-source certificate has invalid reconciliation totals")
    exact_total = int(counts["exact_events"].sum())
    if reconciliation_counts["provider_rows"] - reconciliation_counts["provider_duplicate_rows"] != reconciliation_counts["unique_provider_events"]:
        raise ValueError("V2 provider duplicate accounting does not balance")
    if reconciliation_counts["provider_duplicate_exclusions"] != reconciliation_counts["provider_duplicate_rows"]:
        raise ValueError("V2 provider duplicates are not all explicitly excluded")
    detailed_exclusions = sum(
        reconciliation_counts[field]
        for field in V2_RECONCILIATION_DETAILED_EXCLUSION_FIELDS
    )
    if detailed_exclusions != reconciliation_counts["exclusion_rows"]:
        raise ValueError("V2 reconciliation exclusion accounting does not balance")
    canonical_rows = reconciliation_counts["provider_rows"] - reconciliation_counts["exclusion_rows"] + reconciliation_counts["supplement_rows"]
    if canonical_rows != reconciliation_counts["canonical_rows"] or canonical_rows != exact_total:
        raise ValueError("V2 corrected-ledger row accounting does not balance")
    if reconciliation_counts["matched_events"] + reconciliation_counts["supplement_rows"] != exact_total:
        raise ValueError("V2 exact-event reconciliation accounting does not balance")
    if reconciliation_counts["exact_events_in_factory_pool_perimeter"] != exact_total:
        raise ValueError("V2 factory-perimeter exact-event count disagrees")
    if reconciliation_counts["exact_events_in_provider_observed_pool_perimeter"] > exact_total:
        raise ValueError("V2 provider-observed exact-event perimeter exceeds the factory perimeter")
    nonduplicate_absences = detailed_exclusions - reconciliation_counts["provider_duplicate_exclusions"]
    if reconciliation_counts["unique_provider_events"] != reconciliation_counts["matched_events"] + nonduplicate_absences:
        raise ValueError("V2 unique-provider reconciliation accounting does not balance")
    if reconciliation_counts["correction_rows"] > reconciliation_counts["matched_events"]:
        raise ValueError("V2 correction rows exceed matched events")
    for field in ("log_index_repairs", "payload_repairs", "incomplete_liquidity_repairs"):
        if reconciliation_counts[field] > reconciliation_counts["correction_rows"]:
            raise ValueError(f"V2 reconciliation {field} exceeds correction rows")
    if reconciliation_counts["correction_rows"] > sum(
        reconciliation_counts[field]
        for field in ("log_index_repairs", "payload_repairs", "incomplete_liquidity_repairs")
    ):
        raise ValueError("V2 correction rows lack a recorded repair reason")
    expected_generation_keys = {
        f"{venue}/{day}"
        for venue in V2_EVENT_VENUES
        for day in expected_days
        if day >= get_source(venue).genesis.strftime("%Y%m%d")
    }
    generations = certificate.get("correction_generations")
    if not isinstance(generations, dict) or set(generations) != expected_generation_keys:
        raise ValueError("V2 event-source certificate lacks the exact correction-generation perimeter")
    generation_totals = Counter(
        {field: 0 for field in V2_RECONCILIATION_COUNT_FIELDS}
    )
    for key, record in generations.items():
        if not isinstance(record, dict):
            raise ValueError(f"V2 correction-generation record is malformed: {key}")
        required_digests = (
            "generation_id",
            "pointer_sha256",
            "data_sha256",
            "metadata_sha256",
            "reconciliation_pool_perimeter_sha256",
            "audited_token_decimals_sha256",
        )
        if any(not _is_sha256(record.get(field)) for field in required_digests):
            raise ValueError(f"V2 correction-generation record lacks digests: {key}")
        if record.get("scope") != V2_RECONCILIATION_SCOPE:
            raise ValueError(f"V2 correction-generation scope is stale: {key}")
        if any(
            type(record.get(field)) is not int or int(record[field]) < 0
            for field in (
                "start_block",
                "end_block",
                "reconciliation_pool_perimeter_count",
                "audited_token_decimals_count",
            )
        ):
            raise ValueError(f"V2 correction-generation perimeter is malformed: {key}")
        record_counts = record.get("reconciliation_counts")
        if not isinstance(record_counts, dict) or set(record_counts) != set(V2_RECONCILIATION_COUNT_FIELDS):
            raise ValueError(f"V2 correction-generation counts are malformed: {key}")
        if any(type(record_counts[field]) is not int or record_counts[field] < 0 for field in V2_RECONCILIATION_COUNT_FIELDS):
            raise ValueError(f"V2 correction-generation counts are invalid: {key}")
        generation_totals.update(record_counts)
        for evidence_field in ("exact_log_inputs_sha256", "authority_inputs_sha256"):
            evidence = record.get(evidence_field)
            if not isinstance(evidence, dict) or not evidence or any(
                not isinstance(path, str) or not _is_sha256(digest)
                for path, digest in evidence.items()
            ):
                raise ValueError(f"V2 correction-generation evidence is malformed: {key}")
    if dict(generation_totals) != reconciliation_counts:
        raise ValueError("V2 correction-generation counts do not reproduce certificate totals")
    for field in ("raw_factory_chunks", "raw_event_chunks"):
        if not isinstance(certificate.get(field), int) or int(certificate[field]) < 1:
            raise ValueError(f"V2 event-source certificate lacks a positive {field}")
    if not isinstance(certificate.get("raw_global_event_logs"), int) or int(certificate["raw_global_event_logs"]) < int(counts["exact_events"].sum()):
        raise ValueError("V2 event-source certificate global log total is impossible")
    pair_counts = certificate.get("factory_pairs_by_venue")
    if not isinstance(pair_counts, dict) or set(pair_counts) != set(V2_EVENT_VENUES):
        raise ValueError("V2 event-source certificate lacks exact factory pair counts")
    if any(int(pair_counts[venue]) <= 0 for venue in V2_EVENT_VENUES):
        raise ValueError("V2 event-source certificate contains an empty factory registry")
    if int(certificate.get("factory_pairs", -1)) != sum(
        int(pair_counts[venue]) for venue in V2_EVENT_VENUES
    ):
        raise ValueError("V2 event-source certificate factory pair totals disagree")
    registry_hash = str(certificate.get("factory_registry_sha256") or "")
    if not _is_sha256(registry_hash):
        raise ValueError("V2 event-source certificate lacks a factory-registry digest")
    if not isinstance(certificate.get("token_decimals_registry_rows"), int) or int(certificate["token_decimals_registry_rows"]) < 1:
        raise ValueError("V2 event-source certificate lacks a positive token-decimals perimeter")
    if not _is_sha256(certificate.get("token_decimals_registry_sha256")) or not _is_sha256(certificate.get("token_decimals_registry_file_sha256")):
        raise ValueError("V2 event-source certificate lacks token-decimals registry digests")
    if not isinstance(certificate.get("token_decimals_evidence_files"), int) or int(certificate["token_decimals_evidence_files"]) != int(certificate["token_decimals_registry_rows"]):
        raise ValueError("V2 event-source certificate token-decimals evidence count disagrees")
    upper_block = certificate.get("factory_registry_upper_block")
    upper_hash = str(certificate.get("factory_registry_upper_block_hash") or "")
    upper_timestamp = certificate.get("factory_registry_upper_block_timestamp")
    if not isinstance(upper_block, int) or upper_block < 0:
        raise ValueError("V2 event-source certificate lacks a frozen registry upper block")
    if not upper_hash.startswith("0x") or len(upper_hash) != 66 or not _is_sha256(upper_hash[2:]):
        raise ValueError("V2 event-source certificate lacks a frozen upper-block hash")
    if not isinstance(upper_timestamp, int) or upper_timestamp < 1:
        raise ValueError("V2 event-source certificate lacks a frozen upper-block timestamp")
    if not _is_sha256(certificate.get("frozen_upper_block_sha256")):
        raise ValueError("V2 event-source certificate lacks the frozen-upper evidence digest")
    for field in (
        "factory_deployment_proof_sha256_by_venue",
        "factory_coverage_manifest_sha256_by_venue",
        "factory_state_proof_sha256_by_venue",
    ):
        digests = certificate.get(field)
        if not isinstance(digests, dict) or set(digests) != set(V2_EVENT_VENUES):
            raise ValueError(f"V2 event-source certificate lacks exact {field}")
        if any(not _is_sha256(digests[venue]) for venue in V2_EVENT_VENUES):
            raise ValueError(f"V2 event-source certificate contains an invalid {field}")
    sample_sizes = certificate.get("factory_state_sample_size_by_venue")
    if not isinstance(sample_sizes, dict) or set(sample_sizes) != set(V2_EVENT_VENUES):
        raise ValueError("V2 event-source certificate lacks exact factory state sample sizes")
    expected_sample_sizes = {
        venue: min(int(pair_counts[venue]), V2_FACTORY_STATE_SAMPLE_SIZE)
        for venue in V2_EVENT_VENUES
    }
    if sample_sizes != expected_sample_sizes:
        raise ValueError("V2 event-source certificate contains a noncanonical factory state sample size")
    return len(expected_days), int(counts["exact_events"].sum())


def reopen_v2_factory_pool_registry(
    certificate: dict[str, object],
    *,
    root: Path | None = None,
) -> tuple[dict[str, set[str]], dict[str, list[FactoryPair]], list[Path], int]:
    """Reopen every cited factory artifact and return exact venue ownership."""

    evidence_root = root or RAW_V2_FACTORY_ROOT
    upper_block = int(certificate["factory_registry_upper_block"])
    upper_hash = str(certificate["factory_registry_upper_block_hash"])
    frozen_path = frozen_upper_block_path(upper_block, root=evidence_root)
    if _file_sha256(frozen_path) != certificate.get("frozen_upper_block_sha256"):
        raise ValueError("V2 frozen-upper evidence digest disagrees with the cited artifact")
    frozen_upper = json.loads(frozen_path.read_text(encoding="utf-8"))
    validate_frozen_upper_block(frozen_upper, upper_block)
    if (
        frozen_upper["block_hash"] != upper_hash
        or int(frozen_upper["timestamp"]) != int(certificate["factory_registry_upper_block_timestamp"])
    ):
        raise ValueError("V2 frozen-upper evidence disagrees with the certificate perimeter")
    deployment_digests = certificate["factory_deployment_proof_sha256_by_venue"]
    coverage_digests = certificate["factory_coverage_manifest_sha256_by_venue"]
    state_digests = certificate["factory_state_proof_sha256_by_venue"]
    sample_sizes = certificate["factory_state_sample_size_by_venue"]
    all_pairs: list[FactoryPair] = []
    pools_by_venue: dict[str, set[str]] = {}
    pairs_by_venue: dict[str, list[FactoryPair]] = {}
    inputs = [frozen_path]
    leaf_count = 0
    for venue in V2_EVENT_VENUES:
        deployment_path = factory_deployment_path(venue, upper_block, root=evidence_root)
        if _file_sha256(deployment_path) != deployment_digests[venue]:
            raise ValueError(f"{venue} deployment proof digest disagrees with the cited artifact")
        inputs.append(deployment_path)
        deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
        deployment_block = validate_factory_deployment_proof(
            deployment,
            venue,
            upper_block,
            upper_hash,
        )
        coverage_path = factory_coverage_manifest_path(venue, upper_block, root=evidence_root)
        if _file_sha256(coverage_path) != coverage_digests[venue]:
            raise ValueError(f"{venue} coverage manifest digest disagrees with the cited artifact")
        inputs.append(coverage_path)
        manifest = json.loads(coverage_path.read_text(encoding="utf-8"))
        ranges = validate_factory_coverage_manifest(
            manifest,
            venue=venue,
            deployment_block=deployment_block,
            frozen_upper=frozen_upper,
            root=evidence_root,
        )
        records, leaf_inputs = read_factory_coverage_records(
            manifest,
            venue=venue,
            deployment_block=deployment_block,
            frozen_upper=frozen_upper,
            root=evidence_root,
        )
        _statics, pairs = factory_pair_registry(venue, records, {})
        state_path = factory_state_proof_path(venue, upper_block, root=evidence_root)
        if _file_sha256(state_path) != state_digests[venue]:
            raise ValueError(f"{venue} state proof digest disagrees with the cited artifact")
        inputs.extend((state_path, *leaf_inputs))
        state_proof = json.loads(state_path.read_text(encoding="utf-8"))
        validate_factory_state_proof(
            state_proof,
            venue=venue,
            pairs=pairs,
            frozen_upper=frozen_upper,
            sample_size=int(sample_sizes[venue]),
        )
        if int(certificate["factory_pairs_by_venue"][venue]) != len(pairs):
            raise ValueError(f"{venue} factory pair count disagrees with reopened evidence")
        pools_by_venue[venue] = {pair.pool for pair in pairs}
        pairs_by_venue[venue] = pairs
        all_pairs.extend(pairs)
        leaf_count += len(ranges)
    if int(certificate["factory_pairs"]) != len(all_pairs):
        raise ValueError("V2 factory pair total disagrees with reopened evidence")
    if certificate["factory_registry_sha256"] != factory_registry_sha256(all_pairs):
        raise ValueError("V2 factory registry digest disagrees with reopened evidence")
    if int(certificate["raw_factory_chunks"]) != leaf_count:
        raise ValueError("V2 factory chunk total disagrees with reopened evidence")
    if set.intersection(*pools_by_venue.values()):
        raise ValueError("V2 factory registries assign one pool to multiple venues")
    return pools_by_venue, pairs_by_venue, inputs, leaf_count


def validate_v2_event_source_evidence_bundle(
    certificate: dict[str, object],
    *,
    summary: pd.DataFrame | None = None,
    root: Path | None = None,
    token_registry_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    graph_root: Path | None = None,
    day_bound_root: Path | None = None,
    exact_root: Path | None = None,
) -> tuple[int, int]:
    """Reopen every cited input and reproduce the released corrected-ledger audit."""

    evidence_root = root or RAW_V2_FACTORY_ROOT
    pools_by_venue, pairs_by_venue, _inputs, leaf_count = reopen_v2_factory_pool_registry(
        certificate,
        root=root,
    )
    registry_path = token_registry_path or V2_TOKEN_DECIMALS_REGISTRY
    if _file_sha256(registry_path) != certificate.get("token_decimals_registry_file_sha256"):
        raise ValueError("V2 token-decimals registry file digest disagrees")
    decimals, registry = validate_token_decimals_registry(
        registry_path,
        repo_root=repo_root,
    )
    if len(registry) != int(certificate.get("token_decimals_registry_rows", -1)) or len(decimals) != len(registry):
        raise ValueError("V2 token-decimals registry perimeter disagrees with the certificate")
    if token_decimals_registry_sha256(registry) != certificate.get("token_decimals_registry_sha256"):
        raise ValueError("V2 token-decimals registry semantic digest disagrees")
    frozen_path = frozen_upper_block_path(
        int(certificate["factory_registry_upper_block"]),
        root=evidence_root,
    )
    frozen_upper = json.loads(frozen_path.read_text(encoding="utf-8"))
    provider_root = graph_root or DATA_DIR / "raw" / "thegraph"
    correction_root = correction_root_for_graph(provider_root)
    bounds_root = day_bound_root or RAW_DAY_BOUND_ROOT
    raw_exact_root = exact_root or V2_EXACT_LOG_CACHE_ROOT
    generations = certificate.get("correction_generations")
    if not isinstance(generations, dict):
        raise ValueError("V2 certificate lacks correction-generation evidence")
    rederived_summaries: list[dict[str, object]] = []
    rederived_totals = Counter(
        {field: 0 for field in V2_RECONCILIATION_COUNT_FIELDS}
    )
    for key in sorted(generations):
        venue, separator, day = key.partition("/")
        if not separator or venue not in V2_EVENT_VENUES or len(day) != 8:
            raise ValueError(f"invalid V2 correction-generation key: {key}")
        record = generations[key]
        bound_path = day_bound_path(day, root=bounds_root)
        bounds = json.loads(bound_path.read_text(encoding="utf-8"))
        validate_utc_day_block_bounds(bounds, day)
        start_block = int(bounds["start_block"])
        end_block = int(bounds["end_block"])
        if record.get("start_block") != start_block or record.get("end_block") != end_block:
            raise ValueError(f"V2 correction-generation bounds disagree: {key}")
        expected_pools = pools_by_venue[venue]
        expected_pool_hash = semantic_mapping_sha256(
            {pool: True for pool in expected_pools}
        )
        expected_decimals_hash = semantic_mapping_sha256(decimals)
        if (
            record.get("reconciliation_pool_perimeter_count") != len(expected_pools)
            or record.get("reconciliation_pool_perimeter_sha256") != expected_pool_hash
            or record.get("audited_token_decimals_count") != len(decimals)
            or record.get("audited_token_decimals_sha256") != expected_decimals_hash
        ):
            raise ValueError(f"V2 correction-generation registry perimeter disagrees: {key}")
        generation = load_event_order_generation_metadata(provider_root, venue, day)
        if generation is None:
            raise ValueError(f"V2 correction generation is missing: {key}")
        data_path, metadata_path, metadata = generation
        pointer_path = correction_pointer_path(correction_root, venue, day)
        expected_generation_fields = {
            "generation_id": metadata["generation_id"],
            "pointer_sha256": _file_sha256(pointer_path),
            "data_sha256": _file_sha256(data_path),
            "metadata_sha256": _file_sha256(metadata_path),
            "scope": V2_RECONCILIATION_SCOPE,
            "start_block": start_block,
            "end_block": end_block,
            "reconciliation_pool_perimeter_count": len(expected_pools),
            "reconciliation_pool_perimeter_sha256": expected_pool_hash,
            "audited_token_decimals_count": len(decimals),
            "audited_token_decimals_sha256": expected_decimals_hash,
            "exact_log_inputs_sha256": metadata["exact_log_inputs_sha256"],
            "authority_inputs_sha256": metadata["authority_inputs_sha256"],
        }
        mismatched = {
            field: (record.get(field), value)
            for field, value in expected_generation_fields.items()
            if record.get(field) != value
        }
        if mismatched:
            raise ValueError(f"V2 correction-generation record is stale: {key}: {mismatched}")
        exact_records, exact_paths = read_v2_exact_logs(
            start_block,
            end_block,
            frozen_upper=frozen_upper,
            root=raw_exact_root,
        )
        expected_exact_inputs = {
            portable_evidence_path(path, correction_root): _file_sha256(path)
            for path in exact_paths
        }
        if metadata.get("exact_log_inputs_sha256") != expected_exact_inputs:
            raise ValueError(f"V2 correction generation cites the wrong exact chunks: {key}")
        statics = {
            pair.pool: PoolStatic(
                pair.pool,
                pair.token0,
                pair.token1,
                decimals.get(pair.token0),
                decimals.get(pair.token1),
            )
            for pair in pairs_by_venue[venue]
        }
        exact = raw_core_events(
            venue,
            exact_records,
            expected_pools=expected_pools,
            expected_creation_blocks={
                pair.pool: pair.creation_block for pair in pairs_by_venue[venue]
            },
            ignore_unregistered=True,
        )
        reconciliation, _correction_inputs = load_event_order_corrections(
            provider_root,
            venue,
            day,
        )
        if reconciliation is None:
            raise ValueError(f"V2 correction generation is absent after validation: {key}")
        rows_by_stream = {
            stream: reconciliation.reconciled_rows(
                venue,
                stream,
                iter_graph_rows(graph_stream_path(provider_root, venue, stream, day)),
            )
            for stream in ("mints", "burns", "swaps")
        }
        canonical, duplicates = provider_core_events(rows_by_stream, venue, statics)
        reconciliation.require_fully_applied()
        day_summary, day_exceptions = compare_event_maps(
            day,
            venue,
            exact,
            canonical,
            duplicates,
        )
        if day_exceptions or not all(row["passed"] for row in day_summary):
            raise ValueError(f"V2 correction generation no longer matches exact logs: {key}")
        rederived_summaries.extend(day_summary)
        generation_counts = canonical_v2_reconciliation_counts(
            metadata,
            canonical_rows=len(canonical),
        )
        if record.get("reconciliation_counts") != generation_counts:
            raise ValueError(f"V2 correction-generation counts no longer reproduce: {key}")
        rederived_totals.update(generation_counts)
    if dict(rederived_totals) != certificate.get("reconciliation_totals"):
        raise ValueError("V2 reopened correction generations do not reproduce certificate totals")
    if summary is None:
        raise ValueError("V2 evidence validation requires the released summary")
    pre_genesis = summary.loc[summary["launch_status"].astype(str) == "pre_genesis"].copy()
    rederived = pd.concat(
        [pre_genesis, pd.DataFrame(rederived_summaries)],
        ignore_index=True,
    )[list(summary.columns)]
    sort_columns = ["venue", "day", "event_type"]
    observed = summary.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    expected = rederived.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(observed, expected, check_dtype=True)
    except AssertionError as error:
        raise ValueError("V2 released summary does not match reopened correction generations") from error
    return sum(len(pools) for pools in pools_by_venue.values()), leaf_count


def resolve_v2_event_source_release(
    pointer_path: Path = V2_EVENT_SOURCE_CURRENT,
) -> V2EventSourceRelease:
    """Resolve and hash-verify the one marker-released V2 generation."""

    pointer_path = Path(pointer_path)
    if not pointer_path.is_file() and pointer_path == V2_EVENT_SOURCE_CURRENT and any(
        path.is_file()
        for path in (
            V2_EVENT_SOURCE_SUMMARY,
            V2_EVENT_SOURCE_EXCEPTIONS,
            V2_EVENT_SOURCE_CERTIFICATE,
        )
    ):
        raise RuntimeError("legacy flat V2 event-source artifacts require regeneration")
    release = resolve_artifact_release(
        pointer_path,
        kind=V2_EVENT_SOURCE_RELEASE_KIND,
        schema_version=V2_EVENT_SOURCE_RELEASE_SCHEMA_VERSION,
        filenames=V2_EVENT_SOURCE_RELEASE_FILENAMES,
        require_current_provenance=True,
    )
    return _v2_event_source_release(release)


def _write_v2_event_source_pointer(pointer_path: Path, pointer: dict[str, object]) -> None:
    write_json(pointer_path, pointer)


def publish_v2_event_source_release(
    summary: pd.DataFrame,
    exceptions: pd.DataFrame,
    certificate: dict[str, object],
    *,
    code_sources: list[str],
    inputs: list[str | Path] | None = None,
    notes: str | None = None,
    pointer_path: Path = V2_EVENT_SOURCE_CURRENT,
) -> V2EventSourceRelease:
    """Install, stamp, reopen, and marker-release one immutable generation."""

    pointer_path = Path(pointer_path)
    resolved_inputs = list(inputs or [])

    def validate(paths: Mapping[str, Path]) -> None:
        pd.testing.assert_frame_equal(
            summary,
            pd.read_parquet(paths["summary"]),
            check_dtype=True,
        )
        pd.testing.assert_frame_equal(
            exceptions,
            pd.read_parquet(paths["exceptions"]),
            check_dtype=True,
        )
        reopened_certificate = json.loads(
            paths["certificate"].read_text(encoding="utf-8")
        )
        if reopened_certificate != certificate:
            raise ValueError("V2 event-source certificate does not round-trip exactly")

    release = publish_artifact_release(
        pointer_path=pointer_path,
        kind=V2_EVENT_SOURCE_RELEASE_KIND,
        schema_version=V2_EVENT_SOURCE_RELEASE_SCHEMA_VERSION,
        filenames=V2_EVENT_SOURCE_RELEASE_FILENAMES,
        writers={
            "summary": lambda path: summary.to_parquet(path, index=False),
            "exceptions": lambda path: exceptions.to_parquet(path, index=False),
            "certificate": lambda path: write_json(path, certificate),
        },
        row_counts={
            "summary": len(summary),
            "exceptions": len(exceptions),
            "certificate": 1,
        },
        code_sources=code_sources,
        inputs=resolved_inputs,
        notes=notes,
        validate_staged=validate,
        write_pointer=_write_v2_event_source_pointer,
    )
    return _v2_event_source_release(release)


def read_v2_event_source_certificate(
    summary_path: Path | None = None,
    exceptions_path: Path | None = None,
    certificate_path: Path | None = None,
    *,
    pointer_path: Path = V2_EVENT_SOURCE_CURRENT,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    explicit = (summary_path, exceptions_path, certificate_path)
    if any(path is not None for path in explicit) and not all(path is not None for path in explicit):
        raise ValueError("explicit V2 event-source reads require all three artifact paths")
    if all(path is None for path in explicit):
        release = resolve_v2_event_source_release(pointer_path)
        with current_v2_event_source_release(release):
            return read_v2_event_source_certificate(*release.artifact_paths)
    resolved = tuple(Path(path) for path in (summary_path, exceptions_path, certificate_path) if path is not None)
    if len(resolved) != 3:
        raise AssertionError("V2 event-source artifact resolution is incomplete")
    missing = [path.name for path in resolved if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing V2 event-source artifacts: {missing}")
    summary = pd.read_parquet(resolved[0])
    exceptions = pd.read_parquet(resolved[1])
    certificate = json.loads(resolved[2].read_text(encoding="utf-8"))
    if not isinstance(certificate, dict):
        raise ValueError("V2 event-source certificate is not a JSON object")
    return summary, exceptions, certificate
