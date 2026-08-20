"""Receipt/log-validated causal-order corrections for Graph event rows.

Provider captures remain immutable. A direct correction ledger binds each changed
event to its provider identity and independently fetched Ethereum logs, then becomes
an explicit input to canonical state normalization.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from eth_abi import decode as abi_decode
from eth_utils import keccak
from ddvc.amounts import human_to_raw, raw_to_human
from ddvc.ethereum_receipts import receipt_is_current
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.paths import REPO_ROOT
from ddvc.source_records import block_value, timestamp_value, transaction_id
from ddvc.runtime import serialized_read_installs
from ddvc.v2_event_contract import (
    V2_EVENT_BY_TOPIC,
    V2_EVENT_TOPICS,
    V2_EVENT_VENUES,
    V2_RECONCILIATION_SCOPE,
    normalize_token_decimals,
)


SCHEMA_VERSION = 6
RECONCILIATION_CODE_SOURCES = (
    "scripts/process/reconcile_graph_event_order.py",
    "src/ddvc/amounts.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/ethereum_logs.py",
    "src/ddvc/ethereum_receipts.py",
    "src/ddvc/graph_event_order.py",
    "src/ddvc/source_records.py",
    "src/ddvc/v2_event_contract.py",
)
SUPPORTED_VENUES = frozenset({"uniswap_v2", "sushiswap_v2", "uniswap_v3"})
CORE_STREAMS = ("swaps", "mints", "burns")
V3_STATE_EVENT_SIGNATURES = {
    "swap": "Swap(address,address,int256,int256,uint160,uint128,int24)",
    "mint": "Mint(address,address,int24,int24,uint128,uint256,uint256)",
    "burn": "Burn(address,int24,int24,uint128,uint256,uint256)",
}
V3_STATE_EVENT_TOPICS = {
    name: "0x" + keccak(text=signature).hex()
    for name, signature in V3_STATE_EVENT_SIGNATURES.items()
}
V3_STATE_EVENT_BY_TOPIC = {topic: name for name, topic in V3_STATE_EVENT_TOPICS.items()}
STREAM_EVENT_TYPE = {"swaps": "swap", "mints": "mint", "burns": "burn"}
EventValues = tuple[object, ...]
CorrectionKey = tuple[str, str, str, str, int, int | None]
ProviderActionKey = tuple[CorrectionKey, int]
SupplementActionKey = tuple[str, str, str, str, str, int, int]


@dataclass(frozen=True)
class GraphEvent:
    venue: str
    stream: str
    event_id: str
    tx_hash: str
    pool: str
    block_number: int
    provider_log_index: int | None
    event_values: EventValues
    decimals0: int | None
    decimals1: int | None
    needs_complete: bool

    @property
    def structural_key(self) -> tuple[str, str, str]:
        return self.tx_hash, self.pool, STREAM_EVENT_TYPE[self.stream]

    @property
    def duplicate_key(self) -> tuple[object, ...]:
        return (
            self.stream,
            self.tx_hash,
            self.pool,
            self.block_number,
            self.provider_log_index,
            self.event_values,
            self.needs_complete,
        )

    @property
    def correction_key(self) -> CorrectionKey:
        return (
            self.stream,
            self.event_id,
            self.tx_hash,
            self.pool,
            self.block_number,
            self.provider_log_index,
        )


@dataclass(frozen=True)
class ChainEvent:
    venue: str
    event_type: str
    tx_hash: str
    pool: str
    block_number: int
    log_index: int
    event_values: EventValues
    payload: dict[str, int]

    @property
    def structural_key(self) -> tuple[str, str, str]:
        return self.tx_hash, self.pool, self.event_type

    @property
    def stream(self) -> str:
        return f"{self.event_type}s"


class ProviderEventsAbsentError(RuntimeError):
    """Provider events lack exact chain counterparts and require transaction evidence."""

    def __init__(self, events: Iterable[GraphEvent]) -> None:
        self.events = tuple(events)
        super().__init__(
            "exact event-order reconciliation has provider events absent from exact logs: "
            f"{len(self.events):,} unique rows"
        )


@dataclass(frozen=True)
class EventOverride:
    exclude: bool = False
    log_index: int | None = None
    amount0: str | None = None
    amount1: str | None = None
    sqrt_price_x96: int | None = None
    tick: int | None = None
    liquidity_amount: int | None = None
    tick_lower: int | None = None
    tick_upper: int | None = None
    amount0_in: str | None = None
    amount1_in: str | None = None
    amount0_out: str | None = None
    amount1_out: str | None = None
    needs_complete: bool | None = None


def apply_event_override(
    row: dict[str, object],
    override: EventOverride | None,
) -> dict[str, object] | None:
    """Apply one validated reconciliation action to a provider-shaped row."""

    if override is None:
        return dict(row)
    if override.exclude:
        return None
    if (override.amount0 is None) != (override.amount1 is None):
        raise ValueError("partial exact-chain token-amount override")
    v2_swap = (
        override.amount0_in,
        override.amount1_in,
        override.amount0_out,
        override.amount1_out,
    )
    if any(value is not None for value in v2_swap) and any(
        value is None for value in v2_swap
    ):
        raise ValueError("partial exact-chain V2 swap override")
    corrected = dict(row)
    updates = {
        "logIndex": (
            str(override.log_index) if override.log_index is not None else None
        ),
        "amount0": override.amount0,
        "amount1": override.amount1,
        "sqrtPriceX96": (
            str(override.sqrt_price_x96)
            if override.sqrt_price_x96 is not None
            else None
        ),
        "tick": str(override.tick) if override.tick is not None else None,
        "amount": (
            str(override.liquidity_amount)
            if override.liquidity_amount is not None
            else None
        ),
        "tickLower": (
            str(override.tick_lower) if override.tick_lower is not None else None
        ),
        "tickUpper": (
            str(override.tick_upper) if override.tick_upper is not None else None
        ),
        "amount0In": override.amount0_in,
        "amount1In": override.amount1_in,
        "amount0Out": override.amount0_out,
        "amount1Out": override.amount1_out,
        "needsComplete": override.needs_complete,
    }
    corrected.update({key: value for key, value in updates.items() if value is not None})
    return corrected


def _rpc_integer(value: object) -> int:
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def _load_block_timestamp_evidence(path: Path) -> dict[int, int]:
    observed: dict[int, int] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            request, response = row.get("request") or {}, row.get("response") or {}
            params = request.get("params") or []
            if request.get("method") != "eth_getBlockByNumber" or not params:
                raise ValueError("invalid block-timestamp RPC evidence")
            requested = _rpc_integer(params[0])
            returned = _rpc_integer(response.get("number"))
            timestamp = _rpc_integer(response.get("timestamp"))
            if requested != returned:
                raise ValueError("block-timestamp RPC response has the wrong block")
            prior = observed.get(requested)
            if prior is not None and prior != timestamp:
                raise ValueError("conflicting block-timestamp RPC evidence")
            observed[requested] = timestamp
    return observed


def correction_root_for_graph(raw_root: Path) -> Path:
    """Resolve the independent-order evidence sibling of a Graph raw root."""

    return raw_root.parent / "ethereum" / "graph_event_order"


def provider_event_paths(raw_root: Path, venue: str, day: str) -> list[Path]:
    return [raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz" for stream in CORE_STREAMS]


def v3_pool_static_path(raw_root: Path) -> Path | None:
    candidates = sorted(
        (raw_root / "uniswap_v3").glob("uniswap_v3_pool_statics_*.jsonl.gz")
    )
    if len(candidates) > 1:
        raise RuntimeError("multiple V3 pool-static files are present")
    return candidates[0] if candidates else None


def provider_order_input_paths(raw_root: Path, venue: str, day: str) -> list[Path]:
    paths = provider_event_paths(raw_root, venue, day)
    if venue == "uniswap_v3" and (static_path := v3_pool_static_path(raw_root)) is not None:
        paths.append(static_path)
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        paths.append(raw_root / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz")
    return paths


def correction_directory(root: Path, venue: str) -> Path:
    return root / venue


def correction_paths(root: Path, venue: str, day: str) -> tuple[Path, Path]:
    directory = correction_directory(root, venue)
    return directory / f"{day}.actions.jsonl.gz", directory / f"{day}.metadata.json"


def correction_metadata_path(root: Path, venue: str, day: str) -> Path:
    return correction_paths(root, venue, day)[1]


def timestamp_evidence_path(root: Path, venue: str, day: str) -> Path:
    return correction_directory(root, venue) / f"{day}.block_timestamps.jsonl.gz"


def receipt_evidence_path(root: Path, venue: str, day: str) -> Path:
    return correction_directory(root, venue) / f"{day}.transaction_receipts.jsonl.gz"


CORRECTION_POINTER_SCHEMA_VERSION = 1


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def correction_pointer_path(root: Path, venue: str, day: str) -> Path:
    return root / venue / f"{day}.current.json"


def correction_generation_paths(
    root: Path,
    venue: str,
    day: str,
) -> tuple[Path, Path, Path, Path] | None:
    """Resolve one content-addressed correction generation from its pointer."""

    pointer_path = correction_pointer_path(root, venue, day)
    if not pointer_path.exists():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"invalid event-order generation pointer for {venue}/{day}"
        ) from error
    generation_id = str(pointer.get("generation_id") or "")
    metadata_sha256 = str(pointer.get("metadata_sha256") or "")
    if (
        pointer.get("schema_version") != CORRECTION_POINTER_SCHEMA_VERSION
        or pointer.get("venue") != venue
        or pointer.get("day") != day
        or len(generation_id) != 64
        or any(character not in "0123456789abcdef" for character in generation_id)
        or len(metadata_sha256) != 64
        or any(character not in "0123456789abcdef" for character in metadata_sha256)
    ):
        raise ValueError(f"invalid event-order generation pointer for {venue}/{day}")
    directory = root / venue / f"{day}.generations" / generation_id
    paths = (
        directory / "actions.jsonl.gz",
        directory / "metadata.json",
        directory / "block_timestamps.jsonl.gz",
        directory / "transaction_receipts.jsonl.gz",
    )
    if any(not path.is_file() for path in paths):
        raise RuntimeError(f"partial event-order generation for {venue}/{day}")
    if file_sha256(paths[1]) != metadata_sha256:
        raise ValueError(f"stale event-order generation pointer for {venue}/{day}")
    return paths


def normalize_pool_perimeter(values: Iterable[str]) -> set[str]:
    """Normalize pool identities without silently merging case-colliding inputs."""

    perimeter: set[str] = set()
    for raw_pool in values:
        pool = str(raw_pool or "").lower()
        if not pool:
            raise ValueError("expected reconciliation pool identity is empty")
        if pool in perimeter:
            raise ValueError(f"expected reconciliation pool identity is duplicated: {pool}")
        perimeter.add(pool)
    return perimeter



def portable_evidence_path(path: Path, root: Path) -> str:
    """Record raw evidence by repository-relative topology, never host absolute path."""

    boundary = root.resolve().parent
    if not path.resolve().is_relative_to(boundary):
        raise ValueError("exact-log evidence must remain inside the shared raw-data root")
    return Path(os.path.relpath(path, root)).as_posix()


def resolve_portable_evidence_path(relative: str, root: Path) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError("exact-log path must be portable and relative")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve().parent):
        raise ValueError("exact-log source path escapes the shared raw-data root")
    return resolved


def repository_evidence_path(path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("reconciliation authority must remain inside the repository")
    return resolved.relative_to(REPO_ROOT.resolve()).as_posix()


def reconciliation_action_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Rederive every persisted action category from the action ledger itself."""

    counts = {
        "correction_rows": 0,
        "exclusion_rows": 0,
        "supplement_rows": 0,
        "log_index_repairs": 0,
        "payload_mismatches": 0,
        "incomplete_liquidity_status_repairs": 0,
        "reverted_transaction_exclusions": 0,
        "successful_transaction_absence_exclusions": 0,
        "incomplete_liquidity_absence_exclusions": 0,
        "provider_duplicate_exclusions": 0,
    }
    reason_fields = {
        "reverted_transaction_event_absent_from_exact_chain_logs": "reverted_transaction_exclusions",
        "provider_event_absent_from_successful_transaction_receipt": "successful_transaction_absence_exclusions",
        "incomplete_provider_liquidity_event_absent_from_exact_chain_logs": "incomplete_liquidity_absence_exclusions",
        "duplicate_provider_event": "provider_duplicate_exclusions",
    }
    payload_fields = {
        "amount0_override",
        "amount1_override",
        "sqrt_price_x96_override",
        "tick_override",
        "liquidity_amount_override",
        "tick_lower_override",
        "tick_upper_override",
        "amount0_in_override",
        "amount1_in_override",
        "amount0_out_override",
        "amount1_out_override",
    }
    for row in rows:
        action = str(row.get("action") or "")
        if action == "correction":
            counts["correction_rows"] += 1
            counts["log_index_repairs"] += int(
                row.get("provider_log_index") != row.get("chain_log_index")
            )
            counts["payload_mismatches"] += int(
                any(row.get(field) is not None for field in payload_fields)
            )
            counts["incomplete_liquidity_status_repairs"] += int(
                row.get("needs_complete_override") is False
            )
        elif action == "exclusion":
            counts["exclusion_rows"] += 1
            field = reason_fields.get(str(row.get("reason") or ""))
            if field is None:
                raise ValueError(f"unknown event-order exclusion reason: {row.get('reason')}")
            counts[field] += 1
        elif action == "supplement":
            counts["supplement_rows"] += 1
        else:
            raise ValueError(f"unknown event-order action: {action}")
    return counts


def _raw_integer(value: object, decimals: object) -> int:
    converted = human_to_raw(value, int(decimals))
    if converted is None:
        raise ValueError(f"inexact Graph token amount: {value}/{decimals}")
    return int(converted)


def _pool_and_tokens(row: dict, venue: str) -> tuple[dict, dict, dict]:
    pool = row.get("pool") if venue == "uniswap_v3" else row.get("pair")
    if not isinstance(pool, dict):
        raise ValueError("Graph event lacks a pool object")
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    return pool, token0, token1


def _event_decimals(
    pool: dict,
    token0: dict,
    token1: dict,
    pool_decimals: dict[str, tuple[int, int]] | None,
    audited_token_decimals: Mapping[str, int] | None = None,
) -> tuple[int | None, int | None]:
    decimals0, decimals1 = token0.get("decimals"), token1.get("decimals")
    registered = (pool_decimals or {}).get(str(pool.get("id") or "").lower())
    if audited_token_decimals is not None:
        token_addresses = (
            str(token0.get("id") or "").lower(),
            str(token1.get("id") or "").lower(),
        )
        if any(not token for token in token_addresses):
            raise ValueError("V2 Graph event lacks token identity for audited decimals")
        missing = [
            token for token in token_addresses if token not in audited_token_decimals
        ]
        if missing:
            raise ValueError(
                "V2 Graph event token is absent from the audited decimals registry: "
                + ", ".join(sorted(set(missing)))
            )
        audited = tuple(int(audited_token_decimals[token]) for token in token_addresses)
        observed = (decimals0, decimals1)
        for index, expected in enumerate(audited):
            provider_values = [observed[index]]
            if registered is not None:
                provider_values.append(registered[index])
            if any(
                value is not None and int(value) != expected
                for value in provider_values
            ):
                raise ValueError(
                    "audited token decimals disagree with Graph provider/template decimals"
                )
        return audited
    if decimals0 is None or decimals1 is None:
        if registered is not None:
            decimals0, decimals1 = registered
    return (
        int(decimals0) if decimals0 is not None else None,
        int(decimals1) if decimals1 is not None else None,
    )


def graph_event_values(
    row: dict,
    venue: str,
    stream: str,
    pool_decimals: dict[str, tuple[int, int]] | None = None,
    audited_token_decimals: Mapping[str, int] | None = None,
) -> EventValues:
    """Return exact economic event values independent of provider order."""

    pool, token0, token1 = _pool_and_tokens(row, venue)
    event_type = STREAM_EVENT_TYPE[stream]
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        decimals0, decimals1 = _event_decimals(
            pool,
            token0,
            token1,
            pool_decimals,
            audited_token_decimals,
        )
        if decimals0 is None or decimals1 is None:
            raise ValueError("V2 Graph event lacks token decimals")
        if event_type == "swap":
            return (
                event_type,
                _raw_integer(row.get("amount0In") or "0", decimals0),
                _raw_integer(row.get("amount1In") or "0", decimals1),
                _raw_integer(row.get("amount0Out") or "0", decimals0),
                _raw_integer(row.get("amount1Out") or "0", decimals1),
            )
        amount0, amount1 = row.get("amount0"), row.get("amount1")
        if amount0 is None or amount1 is None:
            if bool(row.get("needsComplete")):
                return event_type, None, None
            raise ValueError("V2 Graph liquidity event lacks exact amounts")
        return event_type, _raw_integer(amount0, decimals0), _raw_integer(amount1, decimals1)
    if venue != "uniswap_v3":
        raise ValueError(f"unsupported Graph event-order venue: {venue}")
    if event_type == "swap":
        decimals0, decimals1 = _event_decimals(pool, token0, token1, pool_decimals)
        if decimals0 is None or decimals1 is None:
            raise ValueError("V3 Graph swap lacks token decimals")
        return (
            event_type,
            _raw_integer(row.get("amount0"), decimals0),
            _raw_integer(row.get("amount1"), decimals1),
            int(row.get("sqrtPriceX96")),
            int(row.get("tick")),
        )
    decimals0, decimals1 = _event_decimals(pool, token0, token1, pool_decimals)
    if decimals0 is None or decimals1 is None:
        raise ValueError("V3 Graph liquidity event lacks token decimals")
    return (
        event_type,
        int(row.get("amount")),
        _raw_integer(row.get("amount0"), decimals0),
        _raw_integer(row.get("amount1"), decimals1),
        int(row.get("tickLower")),
        int(row.get("tickUpper")),
    )


def graph_event(
    row: dict,
    venue: str,
    stream: str,
    pool_decimals: dict[str, tuple[int, int]] | None = None,
    audited_token_decimals: Mapping[str, int] | None = None,
) -> GraphEvent:
    pool, token0, token1 = _pool_and_tokens(row, venue)
    block = block_value(row)
    tx_hash = transaction_id(row)
    event_id = str(row.get("id") or "")
    pool_id = str(pool.get("id") or "").lower()
    raw_provider_log_index = row.get("logIndex")
    try:
        provider_log_index = (
            int(raw_provider_log_index) if raw_provider_log_index is not None else None
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Graph event has a malformed provider log index") from error
    if block is None or block < 1 or (
        provider_log_index is not None and provider_log_index < 0
    ):
        raise ValueError("Graph event lacks a valid block-log order")
    if not event_id or not tx_hash or not pool_id:
        raise ValueError("Graph event lacks exact event, transaction, or pool identity")
    decimals0, decimals1 = _event_decimals(
        pool,
        token0,
        token1,
        pool_decimals,
        audited_token_decimals,
    )
    return GraphEvent(
        venue=venue,
        stream=stream,
        event_id=event_id,
        tx_hash=str(tx_hash).lower(),
        pool=pool_id,
        block_number=int(block),
        provider_log_index=provider_log_index,
        event_values=graph_event_values(
            row,
            venue,
            stream,
            pool_decimals,
            audited_token_decimals,
        ),
        decimals0=decimals0,
        decimals1=decimals1,
        needs_complete=bool(row.get("needsComplete")),
    )


def load_v3_pool_decimals(raw_root: Path) -> dict[str, tuple[int, int]]:
    if v3_pool_static_path(raw_root) is None:
        return {}
    return _pool_template_decimals(load_pool_templates(raw_root, "uniswap_v3", ""))


def load_v2_pool_decimals(
    raw_root: Path,
    venue: str,
    day: str,
) -> dict[str, tuple[int, int]]:
    return _pool_template_decimals(load_pool_templates(raw_root, venue, day))


def load_pool_templates(raw_root: Path, venue: str, day: str) -> dict[str, dict]:
    """Load the canonical pool statics needed to materialise omitted exact events."""

    if venue == "uniswap_v3":
        path = v3_pool_static_path(raw_root)
        if path is None:
            raise FileNotFoundError("V3 pool-static registry is absent")
        container = "pool"
    elif venue in {"uniswap_v2", "sushiswap_v2"}:
        path = raw_root / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz"
        if not path.is_file():
            raise FileNotFoundError(path)
        container = "pair"
    else:
        raise ValueError(f"unsupported pool-template venue: {venue}")
    templates: dict[str, dict] = {}
    identities: dict[str, tuple[object, ...]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            template = row if venue == "uniswap_v3" else row.get(container) or {}
            pool = str(template.get("id") or "").lower()
            token0, token1 = template.get("token0") or {}, template.get("token1") or {}
            identity = (
                str(token0.get("id") or "").lower(),
                str(token1.get("id") or "").lower(),
                token0.get("decimals"),
                token1.get("decimals"),
                template.get("feeTier"),
            )
            if not pool or any(value in (None, "") for value in identity[:4]):
                continue
            prior = identities.get(pool)
            if prior is not None and prior != identity:
                raise ValueError(f"conflicting canonical pool template: {venue}/{pool}")
            identities[pool] = identity
            templates[pool] = template
    return templates


def _pool_template_decimals(
    templates: dict[str, dict],
) -> dict[str, tuple[int, int]]:
    return {
        pool: (int(template["token0"]["decimals"]), int(template["token1"]["decimals"]))
        for pool, template in templates.items()
    }


def supplement_source_row(
    event: ChainEvent,
    pool_template: dict,
    timestamp: int,
) -> dict[str, object]:
    """Materialise one exact-chain omission in the provider-shaped canonical boundary."""

    token0, token1 = pool_template.get("token0") or {}, pool_template.get("token1") or {}
    if token0.get("decimals") is None or token1.get("decimals") is None:
        raise ValueError(f"supplement lacks pool decimals: {event.venue}/{event.pool}")
    decimals0, decimals1 = int(token0["decimals"]), int(token1["decimals"])
    row: dict[str, object] = {
        "id": f"chain:{event.tx_hash}:{event.log_index}",
        "transaction": {
            "id": event.tx_hash,
            "blockNumber": str(event.block_number),
            "timestamp": str(timestamp),
        },
        "timestamp": str(timestamp),
        "logIndex": str(event.log_index),
        "amountUSD": None,
    }
    if event.venue == "uniswap_v3":
        row["pool"] = pool_template
        if event.event_type == "swap":
            row.update(
                {
                    "amount0": raw_to_human(event.payload["amount0"], decimals0),
                    "amount1": raw_to_human(event.payload["amount1"], decimals1),
                    "sqrtPriceX96": str(event.payload["sqrt_price_x96"]),
                    "tick": str(event.payload["tick"]),
                }
            )
        else:
            row.update(
                {
                    "amount": str(event.payload["amount"]),
                    "amount0": raw_to_human(event.payload["amount0"], decimals0),
                    "amount1": raw_to_human(event.payload["amount1"], decimals1),
                    "tickLower": str(event.payload["tick_lower"]),
                    "tickUpper": str(event.payload["tick_upper"]),
                }
            )
        return row
    row["pair"] = pool_template
    if event.event_type == "swap":
        row.update(
            {
                "amount0In": raw_to_human(event.payload["amount0_in"], decimals0),
                "amount1In": raw_to_human(event.payload["amount1_in"], decimals1),
                "amount0Out": raw_to_human(event.payload["amount0_out"], decimals0),
                "amount1Out": raw_to_human(event.payload["amount1_out"], decimals1),
            }
        )
    else:
        row.update(
            {
                "amount0": raw_to_human(event.payload["amount0"], decimals0),
                "amount1": raw_to_human(event.payload["amount1"], decimals1),
            }
        )
    return row


def supplement_action(event: ChainEvent, source_row: dict[str, object]) -> dict[str, object]:
    return {
        "action": "supplement",
        "schema_version": SCHEMA_VERSION,
        "venue": event.venue,
        "stream": event.stream,
        "event_id": source_row["id"],
        "tx_hash": event.tx_hash,
        "pool": event.pool,
        "block_number": event.block_number,
        "provider_log_index": None,
        "chain_log_index": event.log_index,
        "source_row": source_row,
    }


def load_graph_events(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    audited_token_decimals: Mapping[str, int] | None = None,
    expected_pools: Iterable[str] | None = None,
    allow_empty: bool = False,
) -> list[GraphEvent]:
    if venue not in SUPPORTED_VENUES:
        raise ValueError(f"unsupported Graph event-order venue: {venue}")
    if audited_token_decimals is not None and venue not in {
        "uniswap_v2",
        "sushiswap_v2",
    }:
        raise ValueError("audited token decimals are only supported for V2 venues")
    audited_decimals: dict[str, int] | None = None
    admitted_pools = (
        normalize_pool_perimeter(expected_pools)
        if expected_pools is not None
        else None
    )
    if audited_token_decimals is not None:
        audited_decimals = {}
        for raw_token, raw_decimals in audited_token_decimals.items():
            token = str(raw_token or "").lower()
            decimals = int(raw_decimals)
            if not token or decimals < 0 or decimals > 255:
                raise ValueError("invalid audited token-decimals registry entry")
            prior = audited_decimals.get(token)
            if prior is not None and prior != decimals:
                raise ValueError("conflicting audited token-decimals registry entry")
            audited_decimals[token] = decimals
    events: list[GraphEvent] = []
    identities: dict[tuple[str, str], GraphEvent] = {}
    pool_decimals = (
        load_v3_pool_decimals(raw_root)
        if venue == "uniswap_v3"
        else {}
        if audited_decimals is not None
        else load_v2_pool_decimals(raw_root, venue, day)
    )
    for stream, path in zip(CORE_STREAMS, provider_event_paths(raw_root, venue, day), strict=True):
        if not path.is_file():
            raise FileNotFoundError(path)
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if admitted_pools is not None:
                    pair = row.get("pair")
                    pool = str(pair.get("id", "")).lower() if isinstance(pair, dict) else ""
                    if pool not in admitted_pools:
                        continue
                event = graph_event(
                    row,
                    venue,
                    stream,
                    pool_decimals,
                    audited_decimals,
                )
                identity = stream, event.event_id
                prior = identities.get(identity)
                if prior is not None and prior != event:
                    raise ValueError(f"conflicting duplicate Graph event entity: {identity}")
                identities[identity] = event
                events.append(event)
    if not events and not allow_empty:
        raise RuntimeError(f"Graph event-order audit has no events for {venue}/{day}")
    return events


def _topic_int24(topic: str) -> int:
    return int(abi_decode(["int24"], bytes.fromhex(topic.removeprefix("0x")))[0])


def chain_event(record: dict[str, object], venue: str) -> ChainEvent:
    topics = [str(value).lower() for value in record.get("topics") or []]
    if not topics:
        raise ValueError("exact Ethereum event lacks topics")
    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        event_type = V2_EVENT_BY_TOPIC.get(topics[0])
        if event_type == "swap":
            values = tuple(int(value) for value in abi_decode(["uint256"] * 4, data))
            event_values = (event_type, *values)
            payload = {
                "amount0_in": values[0],
                "amount1_in": values[1],
                "amount0_out": values[2],
                "amount1_out": values[3],
            }
        elif event_type in {"mint", "burn"}:
            values = tuple(int(value) for value in abi_decode(["uint256"] * 2, data))
            event_values = (event_type, *values)
            payload = {"amount0": values[0], "amount1": values[1]}
        else:
            raise ValueError("exact Ethereum event has an unregistered V2 topic")
    elif venue == "uniswap_v3":
        event_type = V3_STATE_EVENT_BY_TOPIC.get(topics[0])
        if event_type == "swap":
            amount0, amount1, sqrt_price, _liquidity, tick = abi_decode(
                ["int256", "int256", "uint160", "uint128", "int24"], data
            )
            event_values = (
                event_type,
                int(amount0),
                int(amount1),
                int(sqrt_price),
                int(tick),
            )
            payload = {
                "amount0": int(amount0),
                "amount1": int(amount1),
                "sqrt_price_x96": int(sqrt_price),
                "liquidity": int(_liquidity),
                "tick": int(tick),
            }
        elif event_type == "mint":
            _sender, amount, amount0, amount1 = abi_decode(
                ["address", "uint128", "uint256", "uint256"], data
            )
            tick_lower, tick_upper = _topic_int24(topics[2]), _topic_int24(topics[3])
            event_values = (
                event_type,
                int(amount),
                int(amount0),
                int(amount1),
                tick_lower,
                tick_upper,
            )
            payload = {
                "amount": int(amount),
                "amount0": int(amount0),
                "amount1": int(amount1),
                "tick_lower": tick_lower,
                "tick_upper": tick_upper,
            }
        elif event_type == "burn":
            amount, amount0, amount1 = abi_decode(
                ["uint128", "uint256", "uint256"], data
            )
            tick_lower, tick_upper = _topic_int24(topics[2]), _topic_int24(topics[3])
            event_values = (
                event_type,
                int(amount),
                int(amount0),
                int(amount1),
                tick_lower,
                tick_upper,
            )
            payload = {
                "amount": int(amount),
                "amount0": int(amount0),
                "amount1": int(amount1),
                "tick_lower": tick_lower,
                "tick_upper": tick_upper,
            }
        else:
            raise ValueError("exact Ethereum event has an unregistered V3 topic")
    else:
        raise ValueError(f"unsupported exact event-order venue: {venue}")
    return ChainEvent(
        venue=venue,
        event_type=event_type,
        tx_hash=str(record["transaction_hash"]).lower(),
        pool=str(record["address"]).lower(),
        block_number=int(record["block_number"]),
        log_index=int(record["log_index"]),
        event_values=event_values,
        payload=payload,
    )


def event_topics(venue: str) -> list[str]:
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        return [V2_EVENT_TOPICS[name] for name in sorted(V2_EVENT_TOPICS)]
    if venue == "uniswap_v3":
        return [V3_STATE_EVENT_TOPICS[name] for name in sorted(V3_STATE_EVENT_TOPICS)]
    raise ValueError(f"unsupported Graph event-order venue: {venue}")


def receipt_proves_event_absence(
    receipt: Mapping[str, object],
    *,
    venue: str,
    stream: str,
    tx_hash: str,
    pool: str,
    block_number: int,
) -> bool:
    """Prove one claimed provider event is absent from its complete exact receipt."""

    logs = receipt.get("logs")
    status = receipt.get("status")
    if (
        str(receipt.get("tx_hash") or "").lower() != tx_hash.lower()
        or receipt.get("block_number") != int(block_number)
        or len(str(receipt.get("block_hash") or "")) != 66
        or status not in {0, 1}
        or not isinstance(logs, list)
    ):
        return False
    if status == 0:
        return not logs
    event_type = STREAM_EVENT_TYPE.get(stream)
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        expected_topic = V2_EVENT_TOPICS.get(str(event_type))
    elif venue == "uniswap_v3":
        expected_topic = V3_STATE_EVENT_TOPICS.get(str(event_type))
    else:
        expected_topic = None
    if expected_topic is None:
        return False
    return all(
        not (
            isinstance(log, dict)
            and str(log.get("address") or "").lower() == pool.lower()
            and isinstance(log.get("topics"), list)
            and bool(log["topics"])
            and str(log["topics"][0]).lower() == expected_topic
        )
        for log in logs
    )


def _v2_swap_anchor_matches(
    provider: GraphEvent,
    candidates: Iterable[ChainEvent],
) -> list[ChainEvent]:
    """Return V2 swaps uniquely anchored by direction and one exact nonzero amount."""

    if provider.stream != "swaps" or len(provider.event_values) != 5:
        return []
    provider_amounts = tuple(int(value) for value in provider.event_values[1:])
    provider_direction = tuple(value > 0 for value in provider_amounts)
    return [
        candidate
        for candidate in candidates
        if len(candidate.event_values) == 5
        and tuple(int(value) > 0 for value in candidate.event_values[1:]) == provider_direction
        and any(
            provider_value > 0 and provider_value == int(chain_value)
            for provider_value, chain_value in zip(
                provider_amounts,
                candidate.event_values[1:],
                strict=True,
            )
        )
    ]


def _v2_constant_log_offset_matches(
    provider_groups: Iterable[list[GraphEvent]],
    candidates: Iterable[ChainEvent],
) -> dict[CorrectionKey, ChainEvent]:
    """Match repeated V2 swaps only when their exact order has one constant shift."""

    providers = [min(group, key=lambda event: event.event_id) for group in provider_groups]
    chain = list(candidates)
    if (
        len(providers) < 2
        or len(providers) != len(chain)
        or any(event.stream != "swaps" or event.provider_log_index is None for event in providers)
    ):
        return {}
    ordered_providers = sorted(
        providers,
        key=lambda event: (int(event.provider_log_index), event.event_id),
    )
    ordered_chain = sorted(chain, key=lambda event: event.log_index)
    provider_indices = [int(event.provider_log_index) for event in ordered_providers]
    if len(set(provider_indices)) != len(provider_indices):
        return {}
    offsets = {
        exact.log_index - provider_index
        for provider_index, exact in zip(provider_indices, ordered_chain, strict=True)
    }
    if len(offsets) != 1:
        return {}
    if any(
        exact not in _v2_swap_anchor_matches(provider, ordered_chain)
        for provider, exact in zip(ordered_providers, ordered_chain, strict=True)
    ):
        return {}
    return {
        provider.correction_key: exact
        for provider, exact in zip(ordered_providers, ordered_chain, strict=True)
    }


def match_event_orders(
    graph_events: Iterable[GraphEvent],
    exact_records: Iterable[dict[str, object]],
    venue: str,
    *,
    receipt_statuses: Mapping[str, int] | None = None,
    expected_pools: Iterable[str] | None = None,
) -> tuple[list[dict[str, object]], list[ChainEvent], dict[str, int]]:
    """Reconcile provider rows to exact logs without treating omissions as order fixes."""

    graph = list(graph_events)
    if not graph and expected_pools is None:
        raise ValueError(
            "empty provider reconciliation requires an explicit pool perimeter"
        )
    proved_receipts = {
        str(tx_hash).lower(): int(status)
        for tx_hash, status in (receipt_statuses or {}).items()
        if int(status) in {0, 1}
    }
    graph_pools = {event.pool for event in graph}
    if expected_pools is None:
        perimeter = graph_pools
    else:
        perimeter = normalize_pool_perimeter(expected_pools)
    outside = graph_pools - perimeter
    if outside:
        raise ValueError(
            "Graph event pool falls outside the expected reconciliation perimeter: "
            + ", ".join(sorted(outside))
        )
    exact = [
        chain_event(record, venue)
        for record in exact_records
        if str(record.get("address") or "").lower() in perimeter
    ]
    graph_groups: dict[tuple[str, str, str], list[GraphEvent]] = defaultdict(list)
    exact_groups: dict[tuple[str, str, str], list[ChainEvent]] = defaultdict(list)
    provider_occurrences: dict[int, int] = {}
    occurrence_counts: dict[CorrectionKey, int] = defaultdict(int)
    for event in graph:
        graph_groups[event.structural_key].append(event)
        provider_occurrences[id(event)] = occurrence_counts[event.correction_key]
        occurrence_counts[event.correction_key] += 1
    for event in exact:
        exact_groups[event.structural_key].append(event)
    corrections: list[dict[str, object]] = []
    supplements: list[ChainEvent] = []
    provider_duplicate_rows = 0
    unique_graph_events = 0
    matched_events = 0
    payload_mismatches = 0
    log_index_repairs = 0
    incomplete_liquidity_status_repairs = 0
    ignored_zero_liquidity_events = 0
    unmatched_graph_events: list[GraphEvent] = []
    excluded_provider_events = 0
    reverted_transaction_exclusions = 0
    successful_transaction_absence_exclusions = 0
    incomplete_liquidity_absence_exclusions = 0
    provider_duplicate_exclusions = 0
    correction_keys: set[ProviderActionKey] = set()
    for key in sorted(set(graph_groups) | set(exact_groups), key=str):
        duplicate_groups: dict[tuple[object, ...], list[GraphEvent]] = defaultdict(list)
        for event in graph_groups.get(key, []):
            duplicate_groups[event.duplicate_key].append(event)
        provider_groups = sorted(
            duplicate_groups.values(),
            key=lambda group: (
                group[0].provider_log_index is None,
                group[0].provider_log_index or 0,
                group[0].event_id,
            ),
        )
        chain_remaining = sorted(exact_groups.get(key, []), key=lambda event: event.log_index)
        constant_offset_matches = (
            _v2_constant_log_offset_matches(provider_groups, chain_remaining)
            if venue in {"uniswap_v2", "sushiswap_v2"}
            else {}
        )
        unique_graph_events += len(provider_groups)
        provider_duplicate_rows += sum(len(group) - 1 for group in provider_groups)
        for duplicate_group in provider_groups:
            provider = min(duplicate_group, key=lambda event: event.event_id)
            exact_payload_matches = [
                event
                for event in chain_remaining
                if event.event_values == provider.event_values
            ]
            if exact_payload_matches:
                chain = min(exact_payload_matches, key=lambda event: event.log_index)
            else:
                same_log = (
                    [
                        event
                        for event in chain_remaining
                        if event.log_index == provider.provider_log_index
                    ]
                    if provider.provider_log_index is not None
                    else []
                )
                if len(same_log) == 1:
                    chain = same_log[0]
                elif venue in {"uniswap_v2", "sushiswap_v2"} and len(
                    v2_anchor_matches := _v2_swap_anchor_matches(provider, chain_remaining)
                ) == 1:
                    chain = v2_anchor_matches[0]
                elif (
                    offset_match := constant_offset_matches.get(provider.correction_key)
                ) in chain_remaining:
                    chain = offset_match
                elif len(chain_remaining) == 1:
                    chain = chain_remaining[0]
                elif chain_remaining:
                    raise RuntimeError(
                        "ambiguous structural payload reconciliation: "
                        f"{venue}/{provider.stream}/{provider.tx_hash}/{provider.pool}"
                    )
                else:
                    chain = None
            if chain is None:
                incomplete_liquidity_absence = bool(
                    venue in {"uniswap_v2", "sushiswap_v2"}
                    and provider.stream in {"mints", "burns"}
                    and provider.needs_complete
                )
                receipt_status = proved_receipts.get(provider.tx_hash)
                receipt_proven_absence = receipt_status in {0, 1}
                if not (incomplete_liquidity_absence or receipt_proven_absence):
                    unmatched_graph_events.append(provider)
                    continue
                ordered_duplicates = [
                    provider,
                    *(event for event in duplicate_group if event is not provider),
                ]
                for duplicate_index, duplicate in enumerate(ordered_duplicates):
                    provider_occurrence = provider_occurrences[id(duplicate)]
                    action_key = duplicate.correction_key, provider_occurrence
                    if action_key in correction_keys:
                        raise AssertionError("duplicate provider exclusion action")
                    correction_keys.add(action_key)
                    corrections.append(
                        {
                            "action": "exclusion",
                            "schema_version": SCHEMA_VERSION,
                            "venue": venue,
                            "stream": duplicate.stream,
                            "event_id": duplicate.event_id,
                            "tx_hash": duplicate.tx_hash,
                            "pool": duplicate.pool,
                            "block_number": duplicate.block_number,
                            "provider_log_index": duplicate.provider_log_index,
                            "provider_occurrence": provider_occurrence,
                            "chain_log_index": None,
                            "reason": (
                                "duplicate_provider_event"
                                if duplicate_index > 0
                                else "reverted_transaction_event_absent_from_exact_chain_logs"
                                if receipt_status == 0
                                else "provider_event_absent_from_successful_transaction_receipt"
                                if receipt_status == 1
                                else "incomplete_provider_liquidity_event_absent_from_exact_chain_logs"
                            ),
                        }
                    )
                    excluded_provider_events += 1
                    provider_duplicate_exclusions += int(duplicate_index > 0)
                    reverted_transaction_exclusions += int(
                        duplicate_index == 0 and receipt_status == 0
                    )
                    successful_transaction_absence_exclusions += int(
                        duplicate_index == 0 and receipt_status == 1
                    )
                    incomplete_liquidity_absence_exclusions += int(
                        duplicate_index == 0
                        and incomplete_liquidity_absence
                        and not receipt_proven_absence
                    )
                continue
            chain_remaining.remove(chain)
            if provider.block_number != chain.block_number:
                raise ValueError(
                    f"Graph and chain blocks disagree for {provider.stream}/{provider.event_id}"
                )
            matched_events += 1
            payload_mismatch = provider.event_values != chain.event_values
            incomplete_v2_liquidity = bool(
                venue in {"uniswap_v2", "sushiswap_v2"}
                and chain.event_type in {"mint", "burn"}
                and provider.needs_complete
            )
            if (
                payload_mismatch
                and chain.event_type != "swap"
                and not incomplete_v2_liquidity
                and venue != "uniswap_v3"
            ):
                raise RuntimeError(
                    "exact event-order reconciliation found an unsupported payload mismatch: "
                    f"{venue}/{provider.stream}/{provider.event_id}"
                )
            amount_overrides: dict[str, str] = {}
            if payload_mismatch:
                if provider.decimals0 is None or provider.decimals1 is None:
                    raise ValueError("V3 payload correction lacks canonical token decimals")
                payload_mismatches += 1
                if venue == "uniswap_v3":
                    amount_overrides = {
                        "amount0_override": raw_to_human(
                            chain.payload["amount0"], provider.decimals0
                        ),
                        "amount1_override": raw_to_human(
                            chain.payload["amount1"], provider.decimals1
                        ),
                        **(
                            {
                                "liquidity_amount_override": chain.payload["amount"],
                                "tick_lower_override": chain.payload["tick_lower"],
                                "tick_upper_override": chain.payload["tick_upper"],
                            }
                            if chain.event_type in {"mint", "burn"}
                            else {
                                "sqrt_price_x96_override": chain.payload[
                                    "sqrt_price_x96"
                                ],
                                "tick_override": chain.payload["tick"],
                            }
                        ),
                    }
                elif chain.event_type == "swap":
                    amount_overrides = {
                        "amount0_in_override": raw_to_human(
                            chain.payload["amount0_in"], provider.decimals0
                        ),
                        "amount1_in_override": raw_to_human(
                            chain.payload["amount1_in"], provider.decimals1
                        ),
                        "amount0_out_override": raw_to_human(
                            chain.payload["amount0_out"], provider.decimals0
                        ),
                        "amount1_out_override": raw_to_human(
                            chain.payload["amount1_out"], provider.decimals1
                        ),
                    }
                else:
                    amount_overrides = {
                        "amount0_override": raw_to_human(
                            chain.payload["amount0"], provider.decimals0
                        ),
                        "amount1_override": raw_to_human(
                            chain.payload["amount1"], provider.decimals1
                        ),
                    }
            completion_repair = bool(
                venue in {"uniswap_v2", "sushiswap_v2"}
                and chain.event_type in {"mint", "burn"}
                and provider.needs_complete
            )
            incomplete_liquidity_status_repairs += int(completion_repair)
            for duplicate in duplicate_group:
                if duplicate is provider:
                    continue
                provider_occurrence = provider_occurrences[id(duplicate)]
                action_key = duplicate.correction_key, provider_occurrence
                if action_key in correction_keys:
                    raise AssertionError("duplicate provider exclusion action")
                correction_keys.add(action_key)
                corrections.append(
                    {
                        "action": "exclusion",
                        "schema_version": SCHEMA_VERSION,
                        "venue": venue,
                        "stream": duplicate.stream,
                        "event_id": duplicate.event_id,
                        "tx_hash": duplicate.tx_hash,
                        "pool": duplicate.pool,
                        "block_number": duplicate.block_number,
                        "provider_log_index": duplicate.provider_log_index,
                        "provider_occurrence": provider_occurrence,
                        "chain_log_index": None,
                        "reason": "duplicate_provider_event",
                    }
                )
                excluded_provider_events += 1
                provider_duplicate_exclusions += 1
            if (
                provider.provider_log_index == chain.log_index
                and not payload_mismatch
                and not completion_repair
            ):
                continue
            provider_occurrence = provider_occurrences[id(provider)]
            action_key = provider.correction_key, provider_occurrence
            if action_key in correction_keys:
                raise AssertionError("duplicate provider correction action")
            correction_keys.add(action_key)
            log_index_repairs += int(provider.provider_log_index != chain.log_index)
            corrections.append(
                {
                    "action": "correction",
                    "schema_version": SCHEMA_VERSION,
                    "venue": venue,
                    "stream": provider.stream,
                    "event_id": provider.event_id,
                    "tx_hash": provider.tx_hash,
                    "pool": provider.pool,
                    "block_number": provider.block_number,
                    "provider_log_index": provider.provider_log_index,
                    "provider_occurrence": provider_occurrence,
                    "chain_log_index": chain.log_index,
                    **(
                        {"needs_complete_override": False}
                        if completion_repair
                        else {}
                    ),
                    **amount_overrides,
                }
            )
        for chain in chain_remaining:
            is_zero_liquidity = bool(
                venue == "uniswap_v3"
                and chain.event_type in {"mint", "burn"}
                and chain.payload["amount"] == 0
            )
            if is_zero_liquidity:
                ignored_zero_liquidity_events += 1
            else:
                supplements.append(chain)
    if unmatched_graph_events:
        raise ProviderEventsAbsentError(unmatched_graph_events)
    if matched_events + len(supplements) + ignored_zero_liquidity_events != len(exact):
        raise AssertionError("exact event reconciliation accounting does not balance")
    return corrections, supplements, {
        "graph_events": len(graph),
        "unique_graph_events": unique_graph_events,
        "provider_duplicate_rows": provider_duplicate_rows,
        "exact_events_in_graph_pool_perimeter": sum(
            event.pool in graph_pools for event in exact
        ),
        "exact_events_in_reconciliation_pool_perimeter": len(exact),
        "reconciliation_pool_perimeter_pools": len(perimeter),
        "matched_events": matched_events,
        "correction_rows": sum(row["action"] == "correction" for row in corrections),
        "exclusion_rows": excluded_provider_events,
        "reverted_transaction_exclusions": reverted_transaction_exclusions,
        "successful_transaction_absence_exclusions": successful_transaction_absence_exclusions,
        "incomplete_liquidity_absence_exclusions": incomplete_liquidity_absence_exclusions,
        "provider_duplicate_exclusions": provider_duplicate_exclusions,
        "payload_mismatches": payload_mismatches,
        "log_index_repairs": log_index_repairs,
        "incomplete_liquidity_status_repairs": incomplete_liquidity_status_repairs,
        "supplement_rows": len(supplements),
        "ignored_zero_liquidity_events": ignored_zero_liquidity_events,
        "unmatched_graph_events": 0,
        "unmatched_exact_events": 0,
    }


class EventOrderCorrections:
    """Validated one-use exact-event reconciliation for one venue-day partition."""

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        self._rows: dict[ProviderActionKey, EventOverride] = {}
        self._supplements: dict[
            str,
            list[tuple[SupplementActionKey, dict[str, object]]],
        ] = defaultdict(list)
        self._actions: set[tuple[str, object]] = set()
        self._consumed: set[tuple[str, object]] = set()
        self._provider_occurrences: dict[CorrectionKey, int] = defaultdict(int)
        self._consumed_streams: set[str] = set()
        for row in rows:
            action = str(row.get("action") or "")
            if action == "supplement":
                stream = str(row.get("stream") or "")
                source_row = row.get("source_row")
                if stream not in CORE_STREAMS or not isinstance(source_row, dict):
                    raise ValueError("invalid exact-event supplement")
                venue = str(row.get("venue") or "")
                pool, _token0, _token1 = _pool_and_tokens(source_row, venue)
                if (
                    str(source_row.get("id") or "") != str(row.get("event_id") or "")
                    or str(transaction_id(source_row) or "").lower()
                    != str(row.get("tx_hash") or "").lower()
                    or str(pool.get("id") or "").lower()
                    != str(row.get("pool") or "").lower()
                    or int(block_value(source_row)) != int(row["block_number"])
                    or int(source_row["logIndex"]) != int(row["chain_log_index"])
                ):
                    raise ValueError("exact-event supplement identity does not reconcile")
                supplement_key: SupplementActionKey = (
                    venue,
                    stream,
                    str(row.get("event_id") or ""),
                    str(row.get("tx_hash") or "").lower(),
                    str(row.get("pool") or "").lower(),
                    int(row["block_number"]),
                    int(row["chain_log_index"]),
                )
                action_key = "supplement", supplement_key
                if action_key in self._actions:
                    raise ValueError(f"duplicate exact-event supplement: {supplement_key}")
                self._actions.add(action_key)
                self._supplements[stream].append((supplement_key, source_row))
                continue
            if action not in {"correction", "exclusion"}:
                raise ValueError(f"unknown event reconciliation action: {action}")
            key = (
                str(row["stream"]),
                str(row["event_id"]),
                str(row["tx_hash"]).lower(),
                str(row["pool"]).lower(),
                int(row["block_number"]),
                (
                    int(row["provider_log_index"])
                    if row.get("provider_log_index") is not None
                    else None
                ),
            )
            try:
                provider_occurrence = int(row.get("provider_occurrence", 0))
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid provider occurrence: {key}") from error
            if provider_occurrence < 0:
                raise ValueError(f"invalid provider occurrence: {key}")
            provider_key = key, provider_occurrence
            action_key = "provider", provider_key
            if action_key in self._actions:
                raise ValueError(f"duplicate event-order correction: {provider_key}")
            self._actions.add(action_key)
            if action == "exclusion":
                if (
                    row.get("chain_log_index") is not None
                    or row.get("reason") not in {
                        "incomplete_provider_liquidity_event_absent_from_exact_chain_logs",
                        "reverted_transaction_event_absent_from_exact_chain_logs",
                        "provider_event_absent_from_successful_transaction_receipt",
                        "duplicate_provider_event",
                    }
                ):
                    raise ValueError(f"invalid exact-chain exclusion: {key}")
                self._rows[provider_key] = EventOverride(exclude=True)
                continue
            if provider_occurrence > 0:
                raise ValueError(
                    f"duplicate provider occurrence cannot be corrected: {provider_key}"
                )
            chain_log_index = int(row["chain_log_index"])
            amount0 = row.get("amount0_override")
            amount1 = row.get("amount1_override")
            sqrt_price_x96 = row.get("sqrt_price_x96_override")
            tick = row.get("tick_override")
            liquidity_amount = row.get("liquidity_amount_override")
            tick_lower = row.get("tick_lower_override")
            tick_upper = row.get("tick_upper_override")
            amount0_in = row.get("amount0_in_override")
            amount1_in = row.get("amount1_in_override")
            amount0_out = row.get("amount0_out_override")
            amount1_out = row.get("amount1_out_override")
            needs_complete = row.get("needs_complete_override")
            if (amount0 is None) != (amount1 is None):
                raise ValueError(f"partial payload correction: {key}")
            v2_amounts = (amount0_in, amount1_in, amount0_out, amount1_out)
            if any(value is not None for value in v2_amounts) and any(
                value is None for value in v2_amounts
            ):
                raise ValueError(f"partial V2 payload correction: {key}")
            if amount0 is not None and amount0_in is not None:
                raise ValueError(f"mixed V2/V3 payload correction: {key}")
            v3_swap_state = (sqrt_price_x96, tick)
            if any(value is not None for value in v3_swap_state) and any(
                value is None for value in v3_swap_state
            ):
                raise ValueError(f"partial V3 swap-state correction: {key}")
            if any(value is not None for value in v3_swap_state):
                if (
                    str(row.get("venue") or "") != "uniswap_v3"
                    or key[0] != "swaps"
                    or amount0 is None
                    or amount1 is None
                    or amount0_in is not None
                ):
                    raise ValueError(f"invalid V3 swap-state correction: {key}")
                try:
                    sqrt_price_x96 = int(sqrt_price_x96)
                    tick = int(tick)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"malformed V3 swap-state correction: {key}") from error
                if sqrt_price_x96 <= 0:
                    raise ValueError(f"invalid V3 swap-state correction: {key}")
            elif (
                str(row.get("venue") or "") == "uniswap_v3"
                and key[0] == "swaps"
                and amount0 is not None
            ):
                raise ValueError(f"partial V3 swap-state correction: {key}")
            v3_liquidity_state = (liquidity_amount, tick_lower, tick_upper)
            if any(value is not None for value in v3_liquidity_state) and any(
                value is None for value in v3_liquidity_state
            ):
                raise ValueError(f"partial V3 liquidity-state correction: {key}")
            if any(value is not None for value in v3_liquidity_state):
                if (
                    str(row.get("venue") or "") != "uniswap_v3"
                    or key[0] not in {"mints", "burns"}
                    or amount0 is None
                    or amount1 is None
                    or amount0_in is not None
                ):
                    raise ValueError(f"invalid V3 liquidity-state correction: {key}")
                try:
                    liquidity_amount = int(liquidity_amount)
                    tick_lower = int(tick_lower)
                    tick_upper = int(tick_upper)
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"malformed V3 liquidity-state correction: {key}"
                    ) from error
                if liquidity_amount < 0 or tick_lower >= tick_upper:
                    raise ValueError(f"invalid V3 liquidity-state correction: {key}")
            elif (
                str(row.get("venue") or "") == "uniswap_v3"
                and key[0] in {"mints", "burns"}
                and amount0 is not None
            ):
                raise ValueError(f"partial V3 liquidity-state correction: {key}")
            if needs_complete not in (None, False):
                raise ValueError(f"invalid liquidity-completion correction: {key}")
            if chain_log_index < 0 or (
                chain_log_index == key[-1]
                and amount0 is None
                and amount0_in is None
                and needs_complete is None
            ):
                raise ValueError(f"invalid event-order correction: {key}")
            self._rows[provider_key] = EventOverride(
                log_index=chain_log_index,
                amount0=str(amount0) if amount0 is not None else None,
                amount1=str(amount1) if amount1 is not None else None,
                sqrt_price_x96=(
                    int(sqrt_price_x96) if sqrt_price_x96 is not None else None
                ),
                tick=int(tick) if tick is not None else None,
                liquidity_amount=(
                    int(liquidity_amount) if liquidity_amount is not None else None
                ),
                tick_lower=int(tick_lower) if tick_lower is not None else None,
                tick_upper=int(tick_upper) if tick_upper is not None else None,
                amount0_in=str(amount0_in) if amount0_in is not None else None,
                amount1_in=str(amount1_in) if amount1_in is not None else None,
                amount0_out=str(amount0_out) if amount0_out is not None else None,
                amount1_out=str(amount1_out) if amount1_out is not None else None,
                needs_complete=False if needs_complete is False else None,
            )

    def _resolve(self, venue: str, stream: str, row: dict) -> EventOverride | None:
        pool, _token0, _token1 = _pool_and_tokens(row, venue)
        block = block_value(row)
        try:
            raw_provider_log = row.get("logIndex")
            provider_log = (
                int(raw_provider_log) if raw_provider_log is not None else None
            )
        except (TypeError, ValueError):
            return None
        key = (
            stream,
            str(row.get("id") or ""),
            str(transaction_id(row) or "").lower(),
            str(pool.get("id") or "").lower(),
            int(block or 0),
            provider_log,
        )
        provider_occurrence = self._provider_occurrences[key]
        self._provider_occurrences[key] += 1
        provider_key = key, provider_occurrence
        corrected = self._rows.get(provider_key)
        if provider_occurrence > 0 and corrected is None:
            raise ValueError(
                f"duplicate provider row lacks an explicit exclusion: {provider_key}"
            )
        if corrected is not None:
            action_key = "provider", provider_key
            if action_key in self._consumed:
                raise ValueError(f"event-order action consumed more than once: {provider_key}")
            self._consumed.add(action_key)
        return corrected

    def reconciled_rows(
        self,
        venue: str,
        stream: str,
        provider_rows: Iterable[dict[str, object]],
    ) -> Iterable[dict[str, object] | None]:
        """Stream corrected provider rows, exclusions, then exact supplements once."""

        if stream not in CORE_STREAMS:
            raise ValueError(f"event-order reconciliation does not own stream: {stream}")
        if stream in self._consumed_streams:
            raise ValueError(f"event-order stream consumed more than once: {stream}")
        self._consumed_streams.add(stream)
        for row in provider_rows:
            yield apply_event_override(row, self._resolve(venue, stream, row))
        for supplement_key, source_row in self._supplements.get(stream, []):
            action_key = "supplement", supplement_key
            if action_key in self._consumed:
                raise ValueError(
                    f"event-order action consumed more than once: {supplement_key}"
                )
            self._consumed.add(action_key)
            yield dict(source_row)

    def require_fully_applied(self) -> None:
        unused = self._actions - self._consumed
        if unused:
            raise ValueError(
                f"event-order correction contains {len(unused):,} stale or unapplied actions"
            )


def write_event_order_corrections(
    *,
    root: Path,
    raw_root: Path,
    venue: str,
    day: str,
    corrections: list[dict[str, object]],
    supplements: list[dict[str, object]],
    block_timestamp_evidence: list[dict[str, object]],
    exact_log_paths: list[Path],
    audit: dict[str, int],
    start_block: int,
    end_block: int,
    transaction_receipt_evidence: list[dict[str, object]] | None = None,
    scope: str = "complete_graph_observed_block_span",
    expected_pools: Iterable[str] | None = None,
    audited_token_decimals: Mapping[str, int] | None = None,
    authority_inputs: Iterable[Path] | None = None,
) -> tuple[Path, Path]:
    """Write one direct correction ledger and its evidence files.

    Metadata is installed last, after the correction and evidence files are
    written directly beside the retained raw event stream.
    """

    ordered = sorted(
        ({**row, "day": day} for row in [*corrections, *supplements]),
        key=lambda row: (
            int(row["block_number"]),
            int(row["chain_log_index"])
            if row.get("chain_log_index") is not None
            else -1,
            str(row["stream"]),
            str(row["event_id"]),
        ),
    )
    receipts = sorted(
        transaction_receipt_evidence or [],
        key=lambda row: str(row.get("tx_hash") or ""),
    )
    pools = normalize_pool_perimeter(expected_pools or [])
    decimals = normalize_token_decimals(audited_token_decimals)
    if scope == V2_RECONCILIATION_SCOPE and (
        venue not in V2_EVENT_VENUES or not pools or not decimals
    ):
        raise ValueError("full-day V2 reconciliation lacks its pool or token perimeter")
    if type(start_block) is not int or type(end_block) is not int or start_block < 0 or end_block < start_block:
        raise ValueError("event-order correction has invalid block bounds")
    if any(type(value) is not int or value < 0 for value in audit.values()):
        raise ValueError("event-order correction audit counts must be nonnegative integers")
    EventOrderCorrections(ordered)
    derived_actions = reconciliation_action_counts(ordered)
    mismatched_actions = {
        field: (audit.get(field), value)
        for field, value in derived_actions.items()
        if audit.get(field) != value
    }
    if mismatched_actions:
        raise ValueError(f"event-order correction action counts disagree: {mismatched_actions}")

    provider_paths = provider_order_input_paths(raw_root, venue, day)
    exact_paths = sorted(set(exact_log_paths), key=str)
    authority_paths = sorted(set(authority_inputs or []), key=str)
    if any(not path.is_file() for path in provider_paths):
        raise FileNotFoundError(f"event-order provider inputs are incomplete: {venue}/{day}")
    if any(not path.is_file() for path in exact_paths):
        raise FileNotFoundError(f"event-order exact-log inputs are incomplete: {venue}/{day}")
    if authority_paths and any(not path.is_file() for path in authority_paths):
        raise FileNotFoundError(f"event-order authority inputs are incomplete: {venue}/{day}")

    data_path, meta_path = correction_paths(root, venue, day)
    timestamp_path = timestamp_evidence_path(root, venue, day)
    receipts_path = receipt_evidence_path(root, venue, day)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_gz(data_path, ordered)
    write_jsonl_gz(timestamp_path, block_timestamp_evidence)
    write_jsonl_gz(receipts_path, receipts)
    metadata = {
        "status": "complete",
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "day": day,
        "scope": scope,
        "start_block": start_block,
        "end_block": end_block,
        "reconciliation_pool_perimeter_count": len(pools),
        "validated_token_decimals_count": len(decimals),
        "provider_inputs": [path.relative_to(raw_root).as_posix() for path in provider_paths],
        "exact_log_inputs": [portable_evidence_path(path, root) for path in exact_paths],
        "authority_inputs": [repository_evidence_path(path) for path in authority_paths],
        "event_topics": event_topics(venue),
        "transaction_receipt_evidence_rows": len(receipts),
        **audit,
    }
    write_json(meta_path, metadata)
    return data_path, meta_path


def load_event_order_metadata(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[Path, Path, dict[str, object]] | None:
    root = correction_root_for_graph(raw_root)
    generation = correction_generation_paths(root, venue, day)
    if generation is not None:
        data_path, meta_path, _timestamp_path, _receipts_path = generation
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        pointer = json.loads(
            correction_pointer_path(root, venue, day).read_text(encoding="utf-8")
        )
        if (
            metadata.get("status") != "complete"
            or metadata.get("schema_version") != SCHEMA_VERSION
            or metadata.get("venue") != venue
            or metadata.get("day") != day
            or metadata.get("generation_id") != pointer.get("generation_id")
            or int(metadata.get("unmatched_graph_events", -1)) != 0
            or int(metadata.get("unmatched_exact_events", -1)) != 0
        ):
            raise ValueError(f"invalid event-order generation metadata for {venue}/{day}")
        return data_path, meta_path, metadata
    data_path, meta_path = correction_paths(root, venue, day)
    timestamp_path = timestamp_evidence_path(root, venue, day)
    receipts_path = receipt_evidence_path(root, venue, day)
    if not meta_path.exists():
        if any(path.exists() for path in (data_path, timestamp_path, receipts_path)):
            raise RuntimeError(f"partial event-order correction files for {venue}/{day}")
        return None
    if any(not path.is_file() for path in (data_path, timestamp_path, receipts_path)):
        raise RuntimeError(f"partial event-order correction files for {venue}/{day}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if (
        metadata.get("status") != "complete"
        or metadata.get("schema_version") != SCHEMA_VERSION
        or metadata.get("venue") != venue
        or metadata.get("day") != day
        or int(metadata.get("unmatched_graph_events", -1)) != 0
        or int(metadata.get("unmatched_exact_events", -1)) != 0
    ):
        raise ValueError(f"invalid event-order correction metadata for {venue}/{day}")
    return data_path, meta_path, metadata


def _load_event_order_corrections_unlocked(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[EventOrderCorrections | None, list[Path]]:
    root = correction_root_for_graph(raw_root)
    package = load_event_order_metadata(raw_root, venue, day)
    if package is None:
        return None, []
    data_path, meta_path, metadata = package
    generation_paths = correction_generation_paths(root, venue, day)
    if generation_paths is None:
        timestamp_path = timestamp_evidence_path(root, venue, day)
        receipts_path = receipt_evidence_path(root, venue, day)
    else:
        _generation_data, _generation_meta, timestamp_path, receipts_path = (
            generation_paths
        )

    if venue in V2_EVENT_VENUES and metadata.get("scope") != V2_RECONCILIATION_SCOPE:
        raise ValueError(f"V2 event-order correction is not full-day: {venue}/{day}")
    if metadata.get("scope") == V2_RECONCILIATION_SCOPE:
        decimals_count = metadata.get(
            "audited_token_decimals_count"
            if generation_paths is not None
            else "validated_token_decimals_count",
            0,
        )
        if (
            venue not in V2_EVENT_VENUES
            or int(metadata.get("reconciliation_pool_perimeter_count", 0)) < 1
            or int(decimals_count) < 1
        ):
            raise ValueError(f"invalid full-day event-order perimeter for {venue}/{day}")

    if generation_paths is None:
        provider_paths = [
            raw_root / value for value in metadata.get("provider_inputs", [])
        ]
        exact_paths = [
            resolve_portable_evidence_path(value, root)
            for value in metadata.get("exact_log_inputs", [])
        ]
        authority_paths = [
            REPO_ROOT / value for value in metadata.get("authority_inputs", [])
        ]
        declared_inputs = [*provider_paths, *exact_paths, *authority_paths]
        if any(not path.is_file() for path in declared_inputs):
            raise ValueError(
                f"event-order correction has a missing declared input: {venue}/{day}"
            )
        newest_input = max(
            (path.stat().st_mtime_ns for path in declared_inputs), default=0
        )
        if newest_input > meta_path.stat().st_mtime_ns:
            raise ValueError(
                f"event-order correction is older than a declared input: {venue}/{day}"
            )
    else:
        provider_paths = provider_order_input_paths(raw_root, venue, day)
        expected_provider = metadata.get("provider_inputs_sha256")
        observed_provider = {
            path.name: file_sha256(path) for path in provider_paths if path.is_file()
        }
        if observed_provider != expected_provider:
            raise ValueError(
                f"stale event-order generation against Graph inputs: {venue}/{day}"
            )
        expected_exact = metadata.get("exact_log_inputs_sha256") or {}
        if not isinstance(expected_exact, dict):
            raise ValueError(f"invalid exact event-order inputs for {venue}/{day}")
        exact_paths = [
            resolve_portable_evidence_path(value, root) for value in expected_exact
        ]
        observed_exact = {
            portable_evidence_path(path, root): file_sha256(path)
            for path in exact_paths
            if path.is_file()
        }
        if observed_exact != expected_exact:
            raise ValueError(
                f"missing or stale exact event-order evidence: {venue}/{day}"
            )
        expected_authorities = metadata.get("authority_inputs_sha256") or {}
        if not isinstance(expected_authorities, dict):
            raise ValueError(
                f"invalid event-order registry authorities: {venue}/{day}"
            )
        authority_paths = []
        for relative, expected_digest in expected_authorities.items():
            path = REPO_ROOT / relative
            if not path.is_file():
                if str(relative).endswith(".prov.json"):
                    continue
                raise ValueError(
                    f"missing event-order registry authority: {venue}/{day}/{relative}"
                )
            if file_sha256(path) != expected_digest:
                raise ValueError(
                    f"stale event-order registry authority: {venue}/{day}/{relative}"
                )
            authority_paths.append(path)
        if metadata.get("reconciliation_sha256") != file_sha256(data_path):
            raise ValueError(
                f"corrupted event-order reconciliation data: {venue}/{day}"
            )
        if metadata.get("block_timestamp_evidence_sha256") != file_sha256(
            timestamp_path
        ):
            raise ValueError(
                f"missing or stale block-timestamp evidence: {venue}/{day}"
            )
        if metadata.get("transaction_receipt_evidence_sha256") != file_sha256(
            receipts_path
        ):
            raise ValueError(
                f"missing or stale transaction-receipt evidence: {venue}/{day}"
            )

    rows: list[dict[str, object]] = []
    with gzip.open(data_path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                row.get("schema_version") != SCHEMA_VERSION
                or row.get("venue") != venue
                or row.get("day") != day
            ):
                raise ValueError(f"wrong event-order correction schema for {venue}/{day}")
            rows.append(row)

    receipt_rows: dict[str, dict[str, object]] = {}
    with gzip.open(receipts_path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            receipt = json.loads(line)
            tx_hash = str(receipt.get("tx_hash") or "").lower()
            if (
                not tx_hash
                or tx_hash in receipt_rows
                or not receipt_is_current(
                    receipt,
                    tx_hash,
                    expected_block=int(receipt.get("block_number", -1)),
                    require_block_hash=True,
                    require_logs=True,
                    require_evidence=True,
                )
            ):
                raise ValueError(f"invalid transaction-receipt evidence for {venue}/{day}")
            if int(receipt["status"]) == 0 and receipt["logs"]:
                raise ValueError(f"reverted receipt retains impossible logs for {venue}/{day}")
            receipt_rows[tx_hash] = receipt
    if len(receipt_rows) != int(metadata.get("transaction_receipt_evidence_rows", -1)):
        raise ValueError(f"transaction-receipt evidence count differs for {venue}/{day}")

    receipt_reasons = {
        "reverted_transaction_event_absent_from_exact_chain_logs",
        "provider_event_absent_from_successful_transaction_receipt",
    }
    receipt_exclusion_txs = {
        str(row.get("tx_hash") or "").lower()
        for row in rows
        if row.get("reason") in receipt_reasons
    }
    if set(receipt_rows) != receipt_exclusion_txs:
        raise ValueError(f"transaction-receipt evidence perimeter differs for {venue}/{day}")
    for row in rows:
        if row.get("reason") not in receipt_reasons:
            continue
        receipt = receipt_rows.get(str(row.get("tx_hash") or "").lower())
        if receipt is None or not receipt_proves_event_absence(
            receipt,
            venue=venue,
            stream=str(row["stream"]),
            tx_hash=str(row["tx_hash"]),
            pool=str(row["pool"]),
            block_number=int(row["block_number"]),
        ):
            raise ValueError(f"unproved transaction-receipt exclusion for {venue}/{day}")
        expected_status = 0 if str(row["reason"]).startswith("reverted_") else 1
        if int(receipt["status"]) != expected_status:
            raise ValueError(f"transaction-receipt exclusion reason disagrees for {venue}/{day}")

    timestamps = _load_block_timestamp_evidence(timestamp_path)
    for row in rows:
        if row.get("action") != "supplement":
            continue
        source_row = row.get("source_row") or {}
        block = int(row["block_number"])
        if timestamp_value(source_row) != timestamps.get(block):
            raise ValueError(f"unproved supplement timestamp for {venue}/{day}/{block}")

    expected_rows = (
        int(metadata.get("correction_rows", -1))
        + int(metadata.get("exclusion_rows", 0))
        + int(metadata.get("supplement_rows", -1))
    )
    if len(rows) != expected_rows:
        raise ValueError(f"event-order reconciliation row count differs for {venue}/{day}")
    derived_actions = reconciliation_action_counts(rows)
    mismatched_actions = {
        field: (metadata.get(field), value)
        for field, value in derived_actions.items()
        if metadata.get(field) != value
    }
    if mismatched_actions:
        raise ValueError(
            f"event-order reconciliation action counts differ for {venue}/{day}: "
            f"{mismatched_actions}"
        )
    pointer_inputs = (
        [correction_pointer_path(root, venue, day)]
        if generation_paths is not None
        else []
    )
    return EventOrderCorrections(rows), [
        *pointer_inputs,
        data_path,
        meta_path,
        timestamp_path,
        receipts_path,
        *exact_paths,
        *authority_paths,
    ]


def load_event_order_corrections(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[EventOrderCorrections | None, list[Path]]:
    """Load one direct correction ledger under a metadata-file lease."""

    root = correction_root_for_graph(raw_root)
    pointer = correction_pointer_path(root, venue, day)
    lease = pointer if pointer.exists() else correction_metadata_path(root, venue, day)
    with serialized_read_installs((lease,), allow_missing=True):
        return _load_event_order_corrections_unlocked(raw_root, venue, day)
