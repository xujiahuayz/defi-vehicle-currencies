"""Independent Uniswap V3 pool census from canonical factory creation events."""

from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
from pathlib import Path

from eth_abi import decode as abi_decode
from eth_utils import keccak
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    fetch_exact_logs_with_evidence,
    load_or_resolve_frozen_block,
    validate_anchored_log_evidence,
    validate_canonical_log_records,
    validate_frozen_block,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_json
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR
from ddvc.pricing.v3pools import (
    FACTORY,
    compute_pool_address,
)
from ddvc.quoter import Throttled
from ddvc.runtime import atomic_output, interruptible_thread_pool


V3_POOL_REGISTRY_SCHEMA_VERSION = 2
V3_FACTORY_EVENT_LEAF_KIND = "uniswap_v3_factory_events"
V3_FACTORY = "0x" + FACTORY.hex()
POOL_CREATED_SIGNATURE = "PoolCreated(address,address,uint24,int24,address)"
POOL_CREATED_TOPIC = "0x" + keccak(text=POOL_CREATED_SIGNATURE).hex()
FEE_AMOUNT_ENABLED_SIGNATURE = "FeeAmountEnabled(uint24,int24)"
FEE_AMOUNT_ENABLED_TOPIC = "0x" + keccak(text=FEE_AMOUNT_ENABLED_SIGNATURE).hex()
FACTORY_EVENT_TOPICS = [POOL_CREATED_TOPIC, FEE_AMOUNT_ENABLED_TOPIC]
V3_FACTORY_ROOT_SPAN = 10_000
RAW_V3_POOL_REGISTRY_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_pool_registry"
V3_POOL_REGISTRY = RAW_V3_POOL_REGISTRY_ROOT / "uniswap_v3_factory_pools.parquet"
V3_POOL_REGISTRY_CERTIFICATE = RAW_V3_POOL_REGISTRY_ROOT / "certificate.json"
V3_POOL_REGISTRY_SCHEMA = pa.schema(
    [
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token0", pa.string(), nullable=False),
        pa.field("token1", pa.string(), nullable=False),
        pa.field("fee", pa.int32(), nullable=False),
        pa.field("tick_spacing", pa.int32(), nullable=False),
        pa.field("creation_block", pa.int64(), nullable=False),
        pa.field("creation_block_hash", pa.string(), nullable=False),
        pa.field("creation_tx_hash", pa.string(), nullable=False),
        pa.field("creation_log_index", pa.int64(), nullable=False),
    ]
)


@dataclass(frozen=True)
class V3FactoryPool:
    pool: str
    token0: str
    token1: str
    fee: int
    tick_spacing: int
    creation_block: int
    creation_block_hash: str
    creation_tx_hash: str
    creation_log_index: int


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registry_sha256(pools: list[V3FactoryPool]) -> str:
    payload = [asdict(pool) for pool in sorted(pools, key=lambda item: item.pool)]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def frozen_upper_path(upper_block: int, *, root: Path | None = None) -> Path:
    return (root or RAW_V3_POOL_REGISTRY_ROOT) / f"frozen_upper_{upper_block:08d}.json"


def load_or_resolve_frozen_upper(
    upper_block: int,
    *,
    fetch: bool,
    root: Path | None = None,
    rpc_request=None,
) -> dict[str, object]:
    return load_or_resolve_frozen_block(
        upper_block,
        path=frozen_upper_path(upper_block, root=root),
        schema_version=V3_POOL_REGISTRY_SCHEMA_VERSION,
        fetch=fetch,
        rpc_request=rpc_request,
    )


def root_ranges(deployment_block: int, upper_block: int) -> list[tuple[int, int]]:
    return block_ranges(deployment_block, upper_block, V3_FACTORY_ROOT_SPAN)


def leaf_paths(
    start_block: int,
    end_block: int,
    *,
    root: Path | None = None,
) -> tuple[Path, Path]:
    directory = (root or RAW_V3_POOL_REGISTRY_ROOT) / "leaves"
    stem = f"blocks_{start_block:08d}_{end_block:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.meta.json"


def decode_pool_created(record: dict[str, object]) -> V3FactoryPool:
    topics = [str(topic).lower() for topic in record.get("topics") or []]
    if str(record.get("address") or "").lower() != V3_FACTORY or len(topics) != 4 or topics[0] != POOL_CREATED_TOPIC:
        raise ValueError("Uniswap V3 PoolCreated log has the wrong factory or topic shape")
    if any(topic[2:26] != "0" * 24 for topic in topics[1:3]):
        raise ValueError("Uniswap V3 PoolCreated token topic is not ABI-padded")
    token0 = "0x" + topics[1][-40:]
    token1 = "0x" + topics[2][-40:]
    if topics[3][2:-6] != "0" * 58:
        raise ValueError("Uniswap V3 PoolCreated fee topic is not uint24-padded")
    fee = int(topics[3], 16)
    data = str(record.get("data") or "0x")
    if len(data) != 130:
        raise ValueError("Uniswap V3 PoolCreated data has the wrong ABI length")
    tick_spacing, pool = abi_decode(
        ["int24", "address"],
        bytes.fromhex(data.removeprefix("0x")),
    )
    pool_address = str(pool).lower()
    if token0 >= token1:
        raise ValueError("Uniswap V3 PoolCreated token order is noncanonical")
    if not 0 < fee < 1_000_000 or not 0 < int(tick_spacing) < 16_384:
        raise ValueError("Uniswap V3 PoolCreated fee or tick spacing is outside factory bounds")
    if compute_pool_address(token0, token1, fee) != pool_address:
        raise ValueError("Uniswap V3 PoolCreated address fails canonical CREATE2 identity")
    return V3FactoryPool(
        pool=pool_address,
        token0=token0,
        token1=token1,
        fee=fee,
        tick_spacing=int(tick_spacing),
        creation_block=int(record["block_number"]),
        creation_block_hash=str(record["block_hash"]).lower(),
        creation_tx_hash=str(record["transaction_hash"]).lower(),
        creation_log_index=int(record["log_index"]),
    )


def decode_fee_amount_enabled(record: dict[str, object]) -> tuple[int, int]:
    topics = [str(topic).lower() for topic in record.get("topics") or []]
    if (
        str(record.get("address") or "").lower() != V3_FACTORY
        or len(topics) != 3
        or topics[0] != FEE_AMOUNT_ENABLED_TOPIC
        or str(record.get("data") or "0x") != "0x"
    ):
        raise ValueError("Uniswap V3 FeeAmountEnabled log has the wrong factory or ABI shape")
    if topics[1][2:-6] != "0" * 58:
        raise ValueError("Uniswap V3 FeeAmountEnabled fee topic is not uint24-padded")
    fee = int(topics[1], 16)
    tick_spacing = int(abi_decode(["int24"], bytes.fromhex(topics[2][2:]))[0])
    if not 0 < fee < 1_000_000 or not 0 < tick_spacing < 16_384:
        raise ValueError("Uniswap V3 FeeAmountEnabled values are outside factory bounds")
    return fee, tick_spacing


def validate_factory_event(record: dict[str, object]) -> None:
    topic = str((record.get("topics") or [""])[0]).lower()
    if topic == POOL_CREATED_TOPIC:
        decode_pool_created(record)
    elif topic == FEE_AMOUNT_ENABLED_TOPIC:
        decode_fee_amount_enabled(record)
    else:
        raise ValueError("Uniswap V3 factory log has an unregistered event topic")


def leaf_complete(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> bool:
    raw_path, marker_path = leaf_paths(start_block, end_block, root=root)
    if not raw_path.is_file() or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        table = pq.read_table(raw_path)
        records = validate_canonical_log_records(
            table.to_pylist(),
            start_block=start_block,
            end_block=end_block,
            topics=FACTORY_EVENT_TOPICS,
            address=V3_FACTORY,
        )
        for record in records:
            validate_factory_event(record)
        validate_anchored_log_evidence(marker, records, frozen_upper)
    except (IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        marker.get("status") == "complete"
        and int(marker.get("schema_version", -1)) == V3_POOL_REGISTRY_SCHEMA_VERSION
        and marker.get("kind") == V3_FACTORY_EVENT_LEAF_KIND
        and marker.get("address_filter") == V3_FACTORY
        and marker.get("event_topics") == FACTORY_EVENT_TOPICS
        and int(marker.get("start_block", -1)) == start_block
        and int(marker.get("end_block", -1)) == end_block
        and int(marker.get("root_span", -1)) == V3_FACTORY_ROOT_SPAN
        and marker.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(marker.get("raw_logs", -1)) == table.num_rows
        and table.schema == RAW_LOG_SCHEMA
        and marker.get("raw_sha256") == _file_sha256(raw_path)
    )


def fetch_leaf(
    start_block: int,
    end_block: int,
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
    rpc_request=None,
) -> dict[str, object]:
    raw_path, marker_path = leaf_paths(start_block, end_block, root=root)
    if leaf_complete(start_block, end_block, frozen_upper=frozen_upper, root=root):
        return json.loads(marker_path.read_text(encoding="utf-8"))
    if raw_path.exists() or marker_path.exists():
        raise RuntimeError(f"partial or invalid V3 factory leaf must be quarantined: {raw_path.name}")
    records, evidence = fetch_exact_logs_with_evidence(
        start_block=start_block,
        end_block=end_block,
        topics=FACTORY_EVENT_TOPICS,
        address=V3_FACTORY,
        frozen_upper=frozen_upper,
        rpc_request=rpc_request,
    )
    for record in records:
        validate_factory_event(record)
    return write_exact_log_chunk(
        raw_path,
        marker_path,
        records,
        {
            "kind": V3_FACTORY_EVENT_LEAF_KIND,
            "schema_version": V3_POOL_REGISTRY_SCHEMA_VERSION,
            "start_block": start_block,
            "end_block": end_block,
            "root_span": V3_FACTORY_ROOT_SPAN,
            "address_filter": V3_FACTORY,
            "query_scope": "canonical_factory_creation_and_fee_topics",
            "event_topics": FACTORY_EVENT_TOPICS,
            "rpc_request": evidence["request"],
            "rpc_endpoint": evidence["endpoint"],
            "rpc_attempts": evidence["attempts"],
            "response_sha256": evidence["response_sha256"],
            "frozen_upper_request": evidence["frozen_upper_request"],
            "frozen_upper_response": evidence["frozen_upper_response"],
            "frozen_upper_response_sha256": evidence["frozen_upper_response_sha256"],
        },
    )


def fetch_missing_leaves(
    ranges: list[tuple[int, int]],
    *,
    frozen_upper: dict[str, object],
    workers: int,
    max_attempts: int,
    root: Path | None = None,
    rpc_request=None,
) -> None:
    queue = deque((start, end, 1) for start, end in ranges if not leaf_complete(start, end, frozen_upper=frozen_upper, root=root))
    total = len(queue)
    complete = 0
    with interruptible_thread_pool(max_workers=max(1, min(workers, 4))) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < max(1, min(workers, 4)):
                start, end, attempt = queue.popleft()
                future = executor.submit(
                    fetch_leaf,
                    start,
                    end,
                    frozen_upper=frozen_upper,
                    root=root,
                    rpc_request=rpc_request,
                )
                futures[future] = (start, end, attempt)
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                start, end, attempt = futures.pop(future)
                try:
                    future.result()
                except Throttled:
                    if attempt >= max_attempts:
                        raise RuntimeError(f"V3 factory leaf exhausted retries: {start}:{end}")
                    queue.append((start, end, attempt + 1))
                    continue
                complete += 1
                if complete % 100 == 0 or complete == total:
                    print(f"  V3 factory roots [{complete:,}/{total:,}]; queued={len(queue):,}", flush=True)


def read_registry(
    ranges: list[tuple[int, int]],
    *,
    frozen_upper: dict[str, object],
    root: Path | None = None,
) -> tuple[list[V3FactoryPool], dict[int, int], list[Path]]:
    expected_start = get_source("uniswap_v3").genesis_block
    expected_end = int(frozen_upper["block_number"])
    if ranges != root_ranges(expected_start, expected_end):
        raise ValueError("V3 factory ranges do not cover the exact frozen perimeter")
    pools: list[V3FactoryPool] = []
    inputs: list[Path] = []
    causal_keys: set[tuple[int, str, int]] = set()
    pool_ids: set[str] = set()
    factory_records: list[dict[str, object]] = []
    for start, end in ranges:
        if not leaf_complete(start, end, frozen_upper=frozen_upper, root=root):
            raise RuntimeError(f"incomplete V3 factory leaf: {start}:{end}")
        raw_path, marker_path = leaf_paths(start, end, root=root)
        factory_records.extend(pq.read_table(raw_path).to_pylist())
        inputs.extend((raw_path, marker_path))
    fee_tick_spacings: dict[int, int] = {}
    factory_records.sort(
        key=lambda record: (
            int(record["block_number"]),
            int(record["transaction_index"]),
            int(record["log_index"]),
        )
    )
    for record in factory_records:
        topic = str((record.get("topics") or [""])[0]).lower()
        if topic == FEE_AMOUNT_ENABLED_TOPIC:
            fee, tick_spacing = decode_fee_amount_enabled(record)
            if fee in fee_tick_spacings:
                raise ValueError("V3 factory registry repeats a fee-enablement identity")
            fee_tick_spacings[fee] = tick_spacing
            continue
        if topic == POOL_CREATED_TOPIC:
            decoded = decode_pool_created(record)
            if fee_tick_spacings.get(decoded.fee) != decoded.tick_spacing:
                raise ValueError("V3 pool was created before its exact fee/tick-spacing enablement")
            causal_key = (
                decoded.creation_block,
                decoded.creation_tx_hash,
                decoded.creation_log_index,
            )
            if causal_key in causal_keys or decoded.pool in pool_ids:
                raise ValueError("V3 factory registry contains a duplicate causal or pool identity")
            causal_keys.add(causal_key)
            pool_ids.add(decoded.pool)
            pools.append(decoded)
            continue
        raise ValueError("V3 factory registry contains an unregistered event")
    pools.sort(key=lambda item: (item.creation_block, item.creation_log_index, item.pool))
    if not pools:
        raise RuntimeError("V3 factory registry is empty")
    if not fee_tick_spacings:
        raise RuntimeError("V3 factory registry contains no fee-enablement history")
    return pools, fee_tick_spacings, inputs


def graph_pool_addresses(path: Path) -> set[str]:
    addresses: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            address = str(json.loads(line).get("id") or "").lower()
            if len(address) != 42 or not address.startswith("0x") or address in addresses:
                raise ValueError("Graph V3 static registry contains an invalid or duplicate pool")
            addresses.add(address)
    if not addresses:
        raise ValueError("Graph V3 static registry is empty")
    return addresses


def build_registry(
    upper_block: int,
    graph_static_path: Path,
    *,
    analysis_cutoff_block: int | None = None,
    fetch: bool,
    workers: int,
    max_attempts: int,
    root: Path | None = None,
    rpc_request=None,
) -> tuple[int, int]:
    evidence_root = root or RAW_V3_POOL_REGISTRY_ROOT
    analysis_cutoff = upper_block if analysis_cutoff_block is None else analysis_cutoff_block
    if not get_source("uniswap_v3").genesis_block <= analysis_cutoff <= upper_block:
        raise ValueError("V3 analysis cutoff must lie inside the registry snapshot perimeter")
    frozen_upper = load_or_resolve_frozen_upper(
        upper_block,
        fetch=fetch,
        root=evidence_root,
        rpc_request=rpc_request,
    )
    validate_frozen_block(
        frozen_upper,
        upper_block,
        schema_version=V3_POOL_REGISTRY_SCHEMA_VERSION,
    )
    ranges = root_ranges(get_source("uniswap_v3").genesis_block, upper_block)
    missing = [item for item in ranges if not leaf_complete(*item, frozen_upper=frozen_upper, root=evidence_root)]
    if missing and not fetch:
        raise RuntimeError(f"V3 pool registry lacks {len(missing):,}/{len(ranges):,} factory roots")
    if missing:
        fetch_missing_leaves(
            ranges,
            frozen_upper=frozen_upper,
            workers=workers,
            max_attempts=max_attempts,
            root=evidence_root,
            rpc_request=rpc_request,
        )
    pools, fee_tick_spacings, inputs = read_registry(
        ranges,
        frozen_upper=frozen_upper,
        root=evidence_root,
    )
    graph_pools = graph_pool_addresses(graph_static_path)
    factory_pools = {pool.pool for pool in pools}
    graph_only = graph_pools - factory_pools
    if graph_only:
        raise ValueError(f"Graph V3 registry contains {len(graph_only):,} pools absent from the factory sequence")
    missing_from_graph = factory_pools - graph_pools
    registry_path = evidence_root / V3_POOL_REGISTRY.name
    with atomic_output(registry_path) as temporary:
        pq.write_table(
            pa.Table.from_pylist([asdict(pool) for pool in pools], schema=V3_POOL_REGISTRY_SCHEMA),
            temporary,
            compression="zstd",
        )
    certificate = {
        "status": "pass",
        "schema_version": V3_POOL_REGISTRY_SCHEMA_VERSION,
        "factory": V3_FACTORY,
        "event_topics": FACTORY_EVENT_TOPICS,
        "deployment_block": get_source("uniswap_v3").genesis_block,
        "registry_snapshot_upper_block": upper_block,
        "registry_snapshot_upper_block_hash": frozen_upper["block_hash"],
        "registry_snapshot_upper_block_timestamp": frozen_upper["timestamp"],
        "analysis_cutoff_block": analysis_cutoff,
        "root_span": V3_FACTORY_ROOT_SPAN,
        "root_count": len(ranges),
        "pool_count": len(pools),
        "analysis_pool_count": sum(pool.creation_block <= analysis_cutoff for pool in pools),
        "post_cutoff_pool_count": sum(pool.creation_block > analysis_cutoff for pool in pools),
        "fee_amount_count": len(fee_tick_spacings),
        "fee_tick_spacings": {
            str(fee): tick_spacing for fee, tick_spacing in sorted(fee_tick_spacings.items())
        },
        "graph_pool_count": len(graph_pools),
        "missing_from_graph": len(missing_from_graph),
        "graph_only": 0,
        "first_creation_block": pools[0].creation_block,
        "last_creation_block": pools[-1].creation_block,
        "registry_sha256": registry_sha256(pools),
        "registry_file_sha256": _file_sha256(registry_path),
        "frozen_upper_sha256": _file_sha256(frozen_upper_path(upper_block, root=evidence_root)),
        "leaf_raw_logs": sum(int(json.loads(path.read_text())["raw_logs"]) for path in inputs if path.name.endswith(".meta.json")),
    }
    write_json(evidence_root / V3_POOL_REGISTRY_CERTIFICATE.name, certificate)
    return len(pools), len(missing_from_graph)
