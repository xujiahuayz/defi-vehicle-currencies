"""Exact historical ERC-20 decimals with reopenable RPC evidence.

This module owns the decimals policy shared by event-source audits. A provider or subgraph may report token metadata, but it never supplies the canonical anchor value. Each anchor value comes from an exact ``eth_call`` at a canonical block hash where an independent chain record proves that the token was present. One anchor does not prove time-invariance: callers must retain all provider observations, reject any reported variation, and state this remaining proxy-history assumption in their release contract.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pandas as pd

from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.quoter import (
    RpcEnvelope,
    canonical_json_sha256,
    coerce_rpc_envelope,
    rpc_post,
    validate_rpc_attempts,
)
from ddvc.runtime import atomic_output, interruptible_thread_pool


TOKEN_DECIMALS_EVIDENCE_SCHEMA_VERSION = 1
TOKEN_DECIMALS_REGISTRY_SCHEMA_VERSION = 1
ERC20_DECIMALS_SELECTOR = "0x313ce567"
MAX_TOKEN_DECIMALS = 36
RAW_TOKEN_DECIMALS_ROOT = DATA_DIR / "raw" / "ethereum" / "token_decimals"
TOKEN_DECIMALS_REGISTRY_COLUMNS = (
    "schema_version",
    "token",
    "status",
    "decimals",
    "anchor_priority",
    "anchor_block_number",
    "anchor_block_hash",
    "anchor_proof_kind",
    "anchor_venue",
    "anchor_pool",
    "anchor_event_type",
    "anchor_transaction_hash",
    "anchor_transaction_index",
    "anchor_log_index",
    "anchor_identity_sha256",
    "provider_decimals_json",
    "provider_invalid_json",
    "provider_distinct_reports",
    "provider_status",
    "evidence_path",
    "evidence_sha256",
)


@dataclass(frozen=True)
class TokenDecimalsAnchor:
    """One exact chain identity proving a token's historical presence."""

    token: str
    block_number: int
    block_hash: str
    priority: int
    proof_kind: str
    venue: str
    pool: str
    event_type: str
    transaction_hash: str
    transaction_index: int
    log_index: int


def _address(value: object, *, label: str) -> str:
    address = str(value or "").lower()
    if (
        not address.startswith("0x")
        or len(address) != 42
        or any(character not in "0123456789abcdef" for character in address[2:])
    ):
        raise ValueError(f"{label} is not an exact Ethereum address")
    return address


def _hash(value: object, *, label: str) -> str:
    digest = str(value or "").lower()
    if (
        not digest.startswith("0x")
        or len(digest) != 66
        or any(character not in "0123456789abcdef" for character in digest[2:])
    ):
        raise ValueError(f"{label} is not an exact Ethereum hash")
    return digest


def validate_token_decimals_anchor(anchor: TokenDecimalsAnchor) -> TokenDecimalsAnchor:
    token = _address(anchor.token, label="token-state token")
    block_hash = _hash(anchor.block_hash, label="token-state block hash")
    pool = _address(anchor.pool, label="token-state pool")
    transaction_hash = _hash(anchor.transaction_hash, label="token-state transaction hash")
    if token != anchor.token or block_hash != anchor.block_hash or pool != anchor.pool or transaction_hash != anchor.transaction_hash:
        raise ValueError("token-state anchor identities must be lowercase canonical hex")
    if anchor.block_number < 0 or anchor.priority < 0 or anchor.transaction_index < 0 or anchor.log_index < 0:
        raise ValueError("token-state anchor contains a negative chain coordinate")
    if not anchor.proof_kind or not anchor.venue or not anchor.event_type:
        raise ValueError("token-state anchor lacks proof provenance")
    return anchor


def token_decimals_anchor_sha256(anchor: TokenDecimalsAnchor) -> str:
    validate_token_decimals_anchor(anchor)
    return canonical_json_sha256(asdict(anchor))


def select_token_decimals_anchors(
    candidates: Iterable[TokenDecimalsAnchor],
) -> dict[str, TokenDecimalsAnchor]:
    """Choose one deterministic best historical anchor per token."""

    selected: dict[str, TokenDecimalsAnchor] = {}
    for candidate in candidates:
        validate_token_decimals_anchor(candidate)
        current = selected.get(candidate.token)
        candidate_order = (
            candidate.priority,
            candidate.block_number,
            candidate.transaction_index,
            candidate.log_index,
            candidate.transaction_hash,
            candidate.pool,
            candidate.venue,
            candidate.event_type,
        )
        if current is None:
            selected[candidate.token] = candidate
            continue
        current_order = (
            current.priority,
            current.block_number,
            current.transaction_index,
            current.log_index,
            current.transaction_hash,
            current.pool,
            current.venue,
            current.event_type,
        )
        if candidate_order < current_order:
            selected[candidate.token] = candidate
    return dict(sorted(selected.items()))


def token_decimals_request(anchor: TokenDecimalsAnchor) -> dict[str, object]:
    validate_token_decimals_anchor(anchor)
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": anchor.token, "data": ERC20_DECIMALS_SELECTOR},
            {"blockHash": anchor.block_hash, "requireCanonical": True},
        ],
    }


def _decode_decimals_response(response: object) -> int:
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0" or response.get("id") != 1:
        raise ValueError("malformed_json_rpc_response")
    if response.get("error") is not None:
        raise ValueError("historical_eth_call_error")
    result = response.get("result")
    if not isinstance(result, str) or not result.startswith("0x") or len(result) != 66:
        raise ValueError("malformed_decimals_result")
    try:
        decimals = int(result, 16)
    except ValueError as error:
        raise ValueError("malformed_decimals_result") from error
    if not 0 <= decimals <= MAX_TOKEN_DECIMALS:
        raise ValueError("decimals_outside_0_36")
    return decimals


def _rpc_envelope(
    payload: dict[str, object],
    rpc_request: Callable[..., object] | None,
) -> RpcEnvelope:
    if rpc_request is None:
        response = rpc_post(
            payload,
            timeout=30,
            retries=3,
            retry_json_errors=True,
            return_evidence=True,
            retry_delay=0.5,
            response_validator=_decode_decimals_response,
        )
    else:
        response = rpc_request(payload, timeout=30, retries=3)
    envelope = coerce_rpc_envelope(response)
    _decode_decimals_response(envelope.response)
    return envelope


def fetch_token_decimals_evidence(
    anchor: TokenDecimalsAnchor,
    *,
    rpc_request: Callable[..., object] | None = None,
) -> dict[str, object]:
    """Fetch one historical ``decimals()`` value without guessing or defaulting."""

    request = token_decimals_request(anchor)
    envelope = _rpc_envelope(request, rpc_request)
    response = envelope.response
    decimals = _decode_decimals_response(response)
    record = {
        "schema_version": TOKEN_DECIMALS_EVIDENCE_SCHEMA_VERSION,
        "kind": "erc20_decimals",
        "status": "complete",
        "token": anchor.token,
        "block_number": anchor.block_number,
        "block_hash": anchor.block_hash,
        "anchor": asdict(anchor),
        "anchor_identity_sha256": token_decimals_anchor_sha256(anchor),
        "decimals": decimals,
        "support_reason": "exact_historical_erc20_decimals_call",
        "rpc_request": request,
        "rpc_response": response,
        "response_sha256": canonical_json_sha256(response),
        "rpc_endpoint": envelope.endpoint,
        "rpc_attempts": list(envelope.attempts),
    }
    validate_token_decimals_evidence(record, expected_anchor=anchor)
    return record


def validate_token_decimals_evidence(
    record: Mapping[str, object],
    *,
    expected_anchor: TokenDecimalsAnchor | None = None,
) -> int:
    """Reopen one raw exchange and rederive its exact result."""

    if int(record.get("schema_version", -1)) != TOKEN_DECIMALS_EVIDENCE_SCHEMA_VERSION or record.get("kind") != "erc20_decimals":
        raise ValueError("token decimals evidence has a stale schema")
    anchor_value = record.get("anchor")
    if not isinstance(anchor_value, dict):
        raise ValueError("token decimals evidence lacks its chain anchor")
    try:
        anchor = TokenDecimalsAnchor(**anchor_value)
    except TypeError as error:
        raise ValueError("token decimals evidence has a malformed chain anchor") from error
    validate_token_decimals_anchor(anchor)
    if expected_anchor is not None and anchor != expected_anchor:
        raise ValueError("token decimals evidence names a different chain anchor")
    if record.get("token") != anchor.token or int(record.get("block_number", -1)) != anchor.block_number or record.get("block_hash") != anchor.block_hash:
        raise ValueError("token decimals evidence perimeter disagrees with its anchor")
    if record.get("anchor_identity_sha256") != token_decimals_anchor_sha256(anchor):
        raise ValueError("token decimals anchor digest disagrees")
    request = record.get("rpc_request")
    response = record.get("rpc_response")
    if request != token_decimals_request(anchor):
        raise ValueError("token decimals evidence contains a different RPC request")
    if record.get("response_sha256") != canonical_json_sha256(response):
        raise ValueError("token decimals response digest disagrees")
    validate_rpc_attempts(record.get("rpc_attempts"), record.get("rpc_endpoint"))
    try:
        decimals = _decode_decimals_response(response)
    except ValueError as error:
        raise ValueError("token decimals evidence lacks a valid exact response") from error
    if record.get("status") != "complete" or record.get("support_reason") != "exact_historical_erc20_decimals_call" or record.get("decimals") != decimals:
        raise ValueError("token decimals evidence value disagrees with its response")
    return decimals


def token_decimals_evidence_path(
    anchor: TokenDecimalsAnchor,
    *,
    root: Path | None = None,
) -> Path:
    validate_token_decimals_anchor(anchor)
    directory = root or RAW_TOKEN_DECIMALS_ROOT
    return directory / "decimals" / anchor.token / f"block_{anchor.block_number:08d}_{anchor.block_hash[2:]}.json"


def load_or_fetch_token_decimals_evidence(
    anchor: TokenDecimalsAnchor,
    *,
    fetch: bool,
    root: Path | None = None,
    rpc_request: Callable[..., object] | None = None,
) -> tuple[dict[str, object], Path]:
    """Reuse a valid immutable call or atomically create the one canonical cache row."""

    path = token_decimals_evidence_path(anchor, root=root)
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError(f"token decimals evidence is not an object: {path}")
        validate_token_decimals_evidence(record, expected_anchor=anchor)
        return record, path
    if not fetch:
        raise RuntimeError(f"missing exact token decimals evidence for {anchor.token}")
    record = fetch_token_decimals_evidence(anchor, rpc_request=rpc_request)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record, path


def resolve_token_decimals_evidence(
    anchors: Mapping[str, TokenDecimalsAnchor],
    *,
    fetch: bool,
    workers: int,
    root: Path | None = None,
    rpc_request: Callable[..., object] | None = None,
) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    """Resolve a bounded, resumable set of exact calls with no unbounded queue."""

    worker_count = max(1, min(int(workers), 4))
    queue = deque(sorted(anchors.items()))
    records: dict[str, dict[str, object]] = {}
    paths: dict[str, Path] = {}
    with interruptible_thread_pool(max_workers=worker_count) as executor:
        futures: dict[object, tuple[str, TokenDecimalsAnchor]] = {}
        while queue or futures:
            while queue and len(futures) < worker_count:
                token, anchor = queue.popleft()
                future = executor.submit(
                    load_or_fetch_token_decimals_evidence,
                    anchor,
                    fetch=fetch,
                    root=root,
                    rpc_request=rpc_request,
                )
                futures[future] = (token, anchor)
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                token, _anchor = futures.pop(future)
                record, path = future.result()
                records[token] = record
                paths[token] = path
    return dict(sorted(records.items())), dict(sorted(paths.items()))


def _provider_values(values: Iterable[object]) -> tuple[list[int], list[str], str]:
    observed: list[int] = []
    invalid: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            invalid.append(json.dumps(value))
            continue
        text = str(value)
        if not text.isdigit():
            invalid.append(text)
            continue
        decimals = int(text)
        if not 0 <= decimals <= MAX_TOKEN_DECIMALS:
            invalid.append(text)
            continue
        observed.append(decimals)
    unique = sorted(set(observed))
    return unique, sorted(set(invalid)), "invalid" if invalid else "absent" if not observed else "observed"


def _distinct_provider_reports(values: Iterable[object]) -> list[object]:
    distinct: list[object] = []
    identities: set[str] = set()
    for value in values:
        identity = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if identity not in identities:
            identities.add(identity)
            distinct.append(value)
    return distinct


def _portable_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"token decimals evidence path is outside the repository: {path}") from error


def build_token_decimals_registry(
    anchors: Mapping[str, TokenDecimalsAnchor],
    evidence: Mapping[str, Mapping[str, object]],
    evidence_paths: Mapping[str, Path],
    provider_observations: Mapping[str, Iterable[object]],
    *,
    repo_root: Path = REPO_ROOT,
) -> pd.DataFrame:
    """Build one deterministic registry and preserve every provider comparison."""

    if set(anchors) != set(evidence) or set(anchors) != set(evidence_paths):
        raise ValueError("token decimals registry inputs have different token perimeters")
    rows: list[dict[str, object]] = []
    for token in sorted(anchors):
        anchor = anchors[token]
        record = evidence[token]
        exact = validate_token_decimals_evidence(record, expected_anchor=anchor)
        raw_provider_values = _distinct_provider_reports(provider_observations.get(token, ()))
        provider_values, provider_invalid, provider_state = _provider_values(raw_provider_values)
        if provider_state == "invalid":
            provider_status = "invalid"
        elif len(provider_values) > 1:
            provider_status = "time_varying"
        elif provider_values and provider_values[0] != exact:
            provider_status = "disagrees"
        else:
            provider_status = "absent" if not provider_values else "agrees"
        path = evidence_paths[token]
        rows.append(
            {
                "schema_version": TOKEN_DECIMALS_REGISTRY_SCHEMA_VERSION,
                "token": token,
                "status": str(record["status"]),
                "decimals": exact,
                "anchor_priority": anchor.priority,
                "anchor_block_number": anchor.block_number,
                "anchor_block_hash": anchor.block_hash,
                "anchor_proof_kind": anchor.proof_kind,
                "anchor_venue": anchor.venue,
                "anchor_pool": anchor.pool,
                "anchor_event_type": anchor.event_type,
                "anchor_transaction_hash": anchor.transaction_hash,
                "anchor_transaction_index": anchor.transaction_index,
                "anchor_log_index": anchor.log_index,
                "anchor_identity_sha256": token_decimals_anchor_sha256(anchor),
                "provider_decimals_json": json.dumps(provider_values, separators=(",", ":")),
                "provider_invalid_json": json.dumps(provider_invalid, separators=(",", ":")),
                "provider_distinct_reports": sum(1 for value in raw_provider_values if value is not None and value != ""),
                "provider_status": provider_status,
                "evidence_path": _portable_path(path, repo_root),
                "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return pd.DataFrame(rows, columns=TOKEN_DECIMALS_REGISTRY_COLUMNS)


def write_token_decimals_registry(frame: pd.DataFrame, path: Path) -> None:
    with atomic_output(path) as temporary:
        frame.to_parquet(temporary, index=False)


def token_decimals_registry_sha256(frame: pd.DataFrame) -> str:
    rows = []
    for row in frame.sort_values("token").to_dict("records"):
        rows.append({key: (None if pd.isna(value) else value) for key, value in row.items()})
    return canonical_json_sha256(rows)


def validate_token_decimals_registry(
    path: Path,
    *,
    expected_anchors: Mapping[str, TokenDecimalsAnchor] | None = None,
    provider_observations: Mapping[str, Iterable[object]] | None = None,
    repo_root: Path = REPO_ROOT,
    fail_on_unresolved: bool = True,
) -> tuple[dict[str, int], pd.DataFrame]:
    """Reopen the registry, every raw exchange, and all requested comparisons."""

    frame = pd.read_parquet(path)
    if tuple(frame.columns) != TOKEN_DECIMALS_REGISTRY_COLUMNS or frame.empty:
        raise ValueError("token decimals registry has a stale schema or empty perimeter")
    if frame["token"].duplicated().any() or list(frame["token"]) != sorted(frame["token"]):
        raise ValueError("token decimals registry is not uniquely and deterministically ordered")
    if expected_anchors is not None and set(frame["token"]) != set(expected_anchors):
        raise ValueError("token decimals registry token perimeter is stale")
    values: dict[str, int] = {}
    unresolved: list[str] = []
    for row in frame.to_dict("records"):
        token = str(row["token"])
        anchor = TokenDecimalsAnchor(
            token=token,
            block_number=int(row["anchor_block_number"]),
            block_hash=str(row["anchor_block_hash"]),
            priority=int(row["anchor_priority"]),
            proof_kind=str(row["anchor_proof_kind"]),
            venue=str(row["anchor_venue"]),
            pool=str(row["anchor_pool"]),
            event_type=str(row["anchor_event_type"]),
            transaction_hash=str(row["anchor_transaction_hash"]),
            transaction_index=int(row["anchor_transaction_index"]),
            log_index=int(row["anchor_log_index"]),
        )
        if expected_anchors is not None and anchor != expected_anchors[token]:
            raise ValueError(f"token decimals registry anchor changed for {token}")
        if row["anchor_identity_sha256"] != token_decimals_anchor_sha256(anchor):
            raise ValueError(f"token decimals registry anchor digest changed for {token}")
        relative = Path(str(row["evidence_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("token decimals registry contains a non-portable evidence path")
        evidence_path = repo_root / relative
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != row["evidence_sha256"]:
            raise ValueError(f"token decimals evidence digest changed for {token}")
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        exact = validate_token_decimals_evidence(record, expected_anchor=anchor)
        stored_decimals = None if pd.isna(row["decimals"]) else int(row["decimals"])
        if stored_decimals != exact or row["status"] != record["status"]:
            raise ValueError(f"token decimals registry value changed for {token}")
        stored_provider = json.loads(str(row["provider_decimals_json"]))
        stored_invalid = json.loads(str(row["provider_invalid_json"]))
        raw_provider_values = (
            _distinct_provider_reports(provider_observations.get(token, ()))
            if provider_observations is not None
            else [*stored_provider, *stored_invalid]
        )
        provider_values, provider_invalid, provider_state = _provider_values(
            raw_provider_values
        )
        expected_provider_status = (
            "invalid"
            if provider_state == "invalid"
            else "time_varying"
            if len(provider_values) > 1
            else "disagrees"
            if provider_values and provider_values[0] != exact
            else "absent"
            if not provider_values
            else "agrees"
        )
        expected_provider_reports = (
            sum(
                1
                for value in raw_provider_values
                if value is not None and value != ""
            )
            if provider_observations is not None
            else int(row["provider_distinct_reports"])
        )
        if int(row["provider_distinct_reports"]) < 0 or int(row["provider_distinct_reports"]) != expected_provider_reports:
            raise ValueError(f"provider decimals distinct-report count changed for {token}")
        if stored_provider != provider_values or stored_invalid != provider_invalid or row["provider_status"] != expected_provider_status:
            raise ValueError(f"provider decimals comparison changed for {token}")
        if expected_provider_status not in {"absent", "agrees"}:
            unresolved.append(token)
        else:
            values[token] = exact
    if fail_on_unresolved and unresolved:
        raise ValueError(
            f"token decimals registry has {len(unresolved):,} invalid, varying, or disagreeing provider reports; first={unresolved[:3]}"
        )
    return values, frame
