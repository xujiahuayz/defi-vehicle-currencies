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
import time
from typing import Callable, Iterable, Mapping

import pandas as pd

from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.quoter import (
    RpcEnvelope,
    RpcSemanticError,
    Throttled,
    canonical_json_sha256,
    coerce_rpc_envelope,
    rpc_post,
    validate_rpc_attempts,
)
from ddvc.runtime import atomic_output, interruptible_thread_pool


TOKEN_DECIMALS_EVIDENCE_SCHEMA_VERSION = 1
TOKEN_DECIMALS_REGISTRY_SCHEMA_VERSION = 1
TOKEN_DECIMALS_ANCHOR_MANIFEST_SCHEMA_VERSION = 1
UNRESOLVED_TOKEN_DECIMALS_LEDGER_SCHEMA_VERSION = 1
ERC20_DECIMALS_SELECTOR = "0x313ce567"
MAX_TOKEN_DECIMALS = 36
RAW_TOKEN_DECIMALS_ROOT = DATA_DIR / "raw" / "ethereum" / "token_decimals"
TOKEN_DECIMALS_ANCHOR_MANIFEST = RAW_TOKEN_DECIMALS_ROOT / "v2_selected_anchors.json"
UNRESOLVED_TOKEN_DECIMALS_LEDGER = RAW_TOKEN_DECIMALS_ROOT / "v2_unresolved_tokens.json"
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


class TokenDecimalsResolutionError(RuntimeError):
    """All missing anchors were attempted and the complete failure ledger is durable."""

    def __init__(
        self,
        message: str,
        *,
        records: Mapping[str, Mapping[str, object]],
        paths: Mapping[str, Path],
        failures: Mapping[str, Mapping[str, object]],
        ledger_path: Path | None,
    ) -> None:
        super().__init__(message)
        self.records = dict(records)
        self.paths = dict(paths)
        self.failures = dict(failures)
        self.ledger_path = ledger_path


class InvalidCachedTokenDecimalsEvidence(ValueError):
    """An existing cache row failed JSON decoding or semantic validation."""


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


def token_decimals_anchors_sha256(
    anchors: Mapping[str, TokenDecimalsAnchor],
) -> str:
    """Digest the complete selected-anchor perimeter in canonical token order."""

    rows = []
    for token, anchor in sorted(anchors.items()):
        validate_token_decimals_anchor(anchor)
        if token != anchor.token:
            raise ValueError("token decimals anchor map key disagrees with its token")
        rows.append(asdict(anchor))
    return canonical_json_sha256(rows)


def _lineage_file_records(
    paths: Iterable[Path],
    *,
    repo_root: Path,
) -> list[dict[str, str]]:
    records = []
    for path in sorted(set(paths), key=str):
        if not path.is_file():
            raise FileNotFoundError(f"token decimals lineage input is absent: {path}")
        records.append(
            {
                "path": _portable_path(path, repo_root),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return records


def build_token_decimals_anchor_manifest(
    anchors: Mapping[str, TokenDecimalsAnchor],
    provider_observations: Mapping[str, Iterable[object]],
    *,
    context: Mapping[str, object],
    lineage_inputs: Iterable[Path],
    statistics: Mapping[str, int],
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Freeze expensive anchor selection before any token-state RPC fetch."""

    if not anchors:
        raise ValueError("token decimals anchor manifest cannot be empty")
    canonical_anchors = [asdict(anchors[token]) for token in sorted(anchors)]
    for token, anchor in sorted(anchors.items()):
        validate_token_decimals_anchor(anchor)
        if token != anchor.token:
            raise ValueError("token decimals anchor map key disagrees with its token")
    observations = {
        token: _distinct_provider_reports(values)
        for token, values in sorted(provider_observations.items())
    }
    lineage = _lineage_file_records(lineage_inputs, repo_root=repo_root)
    normalized_statistics = {
        str(key): int(value) for key, value in sorted(statistics.items())
    }
    manifest = {
        "schema_version": TOKEN_DECIMALS_ANCHOR_MANIFEST_SCHEMA_VERSION,
        "kind": "v2_token_decimals_selected_anchors",
        "status": "complete",
        "context": dict(context),
        "context_sha256": canonical_json_sha256(dict(context)),
        "statistics": normalized_statistics,
        "statistics_sha256": canonical_json_sha256(normalized_statistics),
        "anchors": canonical_anchors,
        "anchor_count": len(canonical_anchors),
        "anchors_sha256": token_decimals_anchors_sha256(anchors),
        "provider_observations": observations,
        "provider_observations_sha256": canonical_json_sha256(observations),
        "lineage_inputs": lineage,
        "lineage_inputs_sha256": canonical_json_sha256(lineage),
    }
    return manifest


def write_token_decimals_anchor_manifest(
    manifest: Mapping[str, object],
    path: Path = TOKEN_DECIMALS_ANCHOR_MANIFEST,
) -> None:
    """Install the complete selected-anchor marker atomically."""

    write_json(path, dict(manifest))


def load_token_decimals_anchor_manifest(
    path: Path = TOKEN_DECIMALS_ANCHOR_MANIFEST,
    *,
    expected_context: Mapping[str, object],
    repo_root: Path = REPO_ROOT,
) -> tuple[
    dict[str, TokenDecimalsAnchor],
    dict[str, list[object]],
    list[Path],
    dict[str, int],
]:
    """Reopen selection without rescanning, after revalidating every cited input."""

    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("token decimals anchor manifest is not an object")
    if (
        int(manifest.get("schema_version", -1))
        != TOKEN_DECIMALS_ANCHOR_MANIFEST_SCHEMA_VERSION
        or manifest.get("kind") != "v2_token_decimals_selected_anchors"
        or manifest.get("status") != "complete"
    ):
        raise ValueError("token decimals anchor manifest has a stale schema or incomplete marker")
    context = manifest.get("context")
    if context != dict(expected_context) or manifest.get("context_sha256") != canonical_json_sha256(context):
        raise ValueError("token decimals anchor manifest context is stale")
    raw_anchors = manifest.get("anchors")
    if not isinstance(raw_anchors, list) or not raw_anchors:
        raise ValueError("token decimals anchor manifest has an empty perimeter")
    anchors: dict[str, TokenDecimalsAnchor] = {}
    for value in raw_anchors:
        if not isinstance(value, dict):
            raise ValueError("token decimals anchor manifest contains a malformed anchor")
        try:
            anchor = TokenDecimalsAnchor(**value)
        except TypeError as error:
            raise ValueError("token decimals anchor manifest contains a malformed anchor") from error
        validate_token_decimals_anchor(anchor)
        if anchor.token in anchors:
            raise ValueError("token decimals anchor manifest contains duplicate tokens")
        anchors[anchor.token] = anchor
    anchors = dict(sorted(anchors.items()))
    if int(manifest.get("anchor_count", -1)) != len(anchors) or manifest.get("anchors_sha256") != token_decimals_anchors_sha256(anchors):
        raise ValueError("token decimals anchor manifest digest disagrees")
    provider_observations = manifest.get("provider_observations")
    if not isinstance(provider_observations, dict) or manifest.get("provider_observations_sha256") != canonical_json_sha256(provider_observations):
        raise ValueError("token decimals anchor manifest provider observations disagree")
    normalized_observations = {
        str(token): list(values)
        for token, values in sorted(provider_observations.items())
        if isinstance(values, list)
    }
    if len(normalized_observations) != len(provider_observations):
        raise ValueError("token decimals anchor manifest provider observations are malformed")
    raw_lineage = manifest.get("lineage_inputs")
    if not isinstance(raw_lineage, list) or manifest.get("lineage_inputs_sha256") != canonical_json_sha256(raw_lineage):
        raise ValueError("token decimals anchor manifest lineage digest disagrees")
    lineage_paths = []
    for record in raw_lineage:
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise ValueError("token decimals anchor manifest lineage record is malformed")
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("token decimals anchor manifest contains a non-portable lineage path")
        lineage_path = repo_root / relative
        if hashlib.sha256(lineage_path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"token decimals anchor manifest lineage changed: {relative}")
        lineage_paths.append(lineage_path)
    statistics = manifest.get("statistics")
    if not isinstance(statistics, dict) or not all(
        isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
        for key, value in statistics.items()
    ):
        raise ValueError("token decimals anchor manifest statistics are malformed")
    if manifest.get("statistics_sha256") != canonical_json_sha256(statistics):
        raise ValueError("token decimals anchor manifest statistics digest disagrees")
    return anchors, normalized_observations, lineage_paths, dict(statistics)


def select_token_decimals_anchors(
    candidates: Iterable[TokenDecimalsAnchor],
) -> dict[str, TokenDecimalsAnchor]:
    """Choose one deterministic best historical anchor per token."""

    selected: dict[str, TokenDecimalsAnchor] = {}
    for candidate in candidates:
        retain_token_decimals_anchor(selected, candidate)
    return dict(sorted(selected.items()))


def token_decimals_anchor_order(anchor: TokenDecimalsAnchor) -> tuple[object, ...]:
    """Return the one canonical ordering used to select historical anchors."""

    validate_token_decimals_anchor(anchor)
    return _token_decimals_anchor_order(anchor)


def _token_decimals_anchor_order(anchor: TokenDecimalsAnchor) -> tuple[object, ...]:
    return (
        anchor.priority,
        anchor.block_number,
        anchor.transaction_index,
        anchor.log_index,
        anchor.transaction_hash,
        anchor.pool,
        anchor.venue,
        anchor.event_type,
    )


def retain_token_decimals_anchor(
    selected: dict[str, TokenDecimalsAnchor],
    candidate: TokenDecimalsAnchor,
) -> None:
    """Retain a candidate online without materialising the full candidate stream."""

    candidate_order = token_decimals_anchor_order(candidate)
    current = selected.get(candidate.token)
    if current is None or candidate_order < _token_decimals_anchor_order(current):
        selected[candidate.token] = candidate


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
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("token decimals evidence is not an object")
            validate_token_decimals_evidence(record, expected_anchor=anchor)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise InvalidCachedTokenDecimalsEvidence(
                f"invalid cached token decimals evidence for {anchor.token}: {error}"
            ) from error
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
    max_attempts: int = 12,
    retry_backoff: float = 0.5,
    unresolved_ledger_path: Path | None = None,
    anchor_manifest_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    """Resolve every anchor, retaining successes and reporting all terminal failures."""

    if max_attempts < 1 or retry_backoff < 0:
        raise ValueError("token decimals retry bounds must be nonnegative with at least one attempt")
    worker_count = max(1, min(int(workers), 4))
    queue = deque(sorted(anchors.items()))
    records: dict[str, dict[str, object]] = {}
    paths: dict[str, Path] = {}
    attempts: dict[str, int] = {}
    retry_ready_at: dict[str, float] = {}
    failures: dict[str, dict[str, object]] = {}
    with interruptible_thread_pool(max_workers=worker_count) as executor:
        futures: dict[object, tuple[str, TokenDecimalsAnchor]] = {}
        while queue or futures:
            scan = len(queue)
            while queue and len(futures) < worker_count and scan:
                token, anchor = queue.popleft()
                if retry_ready_at.get(token, 0.0) > time.monotonic():
                    queue.append((token, anchor))
                    scan -= 1
                    continue
                attempts[token] = attempts.get(token, 0) + 1
                future = executor.submit(
                    load_or_fetch_token_decimals_evidence,
                    anchor,
                    fetch=fetch,
                    root=root,
                    rpc_request=rpc_request,
                )
                futures[future] = (token, anchor)
                scan = len(queue)
            if not futures:
                delay = min(retry_ready_at[token] for token, _anchor in queue) - time.monotonic()
                time.sleep(max(0.0, delay))
                continue
            timeout = None
            if queue and len(futures) < worker_count:
                timeout = max(0.0, min(retry_ready_at.get(token, 0.0) for token, _anchor in queue) - time.monotonic())
            done, _pending = wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
            for future in done:
                token, anchor = futures.pop(future)
                try:
                    record, path = future.result()
                except Throttled as error:
                    if attempts[token] >= max_attempts:
                        failures[token] = _token_decimals_failure_record(
                            anchor,
                            attempts=attempts[token],
                            error=error,
                            classification="transient_attempt_cap",
                        )
                        retry_ready_at.pop(token, None)
                        continue
                    delay = retry_backoff * min(2 ** (attempts[token] - 1), 16)
                    retry_ready_at[token] = time.monotonic() + delay
                    queue.append((token, anchor))
                    continue
                except RpcSemanticError as error:
                    failures[token] = _token_decimals_failure_record(
                        anchor,
                        attempts=attempts[token],
                        error=error,
                        classification="terminal_rpc_semantics",
                    )
                    retry_ready_at.pop(token, None)
                    continue
                except InvalidCachedTokenDecimalsEvidence as error:
                    failures[token] = _token_decimals_failure_record(
                        anchor,
                        attempts=attempts[token],
                        error=error,
                        classification="invalid_cached_evidence",
                    )
                    retry_ready_at.pop(token, None)
                    continue
                except RuntimeError as error:
                    if fetch:
                        raise
                    failures[token] = _token_decimals_failure_record(
                        anchor,
                        attempts=attempts[token],
                        error=error,
                        classification="missing_cached_evidence",
                    )
                    retry_ready_at.pop(token, None)
                    continue
                records[token] = record
                paths[token] = path
                retry_ready_at.pop(token, None)
    records = dict(sorted(records.items()))
    paths = dict(sorted(paths.items()))
    failures = dict(sorted(failures.items()))
    if unresolved_ledger_path is not None:
        ledger = build_unresolved_token_decimals_ledger(
            anchors,
            records=records,
            paths=paths,
            failures=failures,
            anchor_manifest_path=anchor_manifest_path,
            repo_root=repo_root,
        )
        write_unresolved_token_decimals_ledger(ledger, unresolved_ledger_path)
    if failures:
        raise TokenDecimalsResolutionError(
            f"exact token decimals unresolved for {len(failures):,}/{len(anchors):,} anchors after {max_attempts} bounded attempts and complete traversal",
            records=records,
            paths=paths,
            failures=failures,
            ledger_path=unresolved_ledger_path,
        )
    return records, paths


def _token_decimals_failure_record(
    anchor: TokenDecimalsAnchor,
    *,
    attempts: int,
    error: Exception,
    classification: str,
) -> dict[str, object]:
    rpc_attempts = getattr(error, "attempts", ())
    return {
        "token": anchor.token,
        "anchor_identity_sha256": token_decimals_anchor_sha256(anchor),
        "attempts": attempts,
        "classification": classification,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "rpc_attempts": list(rpc_attempts) if isinstance(rpc_attempts, (list, tuple)) else [],
    }


def build_unresolved_token_decimals_ledger(
    anchors: Mapping[str, TokenDecimalsAnchor],
    *,
    records: Mapping[str, Mapping[str, object]],
    paths: Mapping[str, Path],
    failures: Mapping[str, Mapping[str, object]],
    anchor_manifest_path: Path | None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Build the marker-last resolution ledger with exact lineage hashes."""

    if set(records) != set(paths):
        raise ValueError("resolved token decimals records and paths have different perimeters")
    if set(records).intersection(failures) or set(records).union(failures) != set(anchors):
        raise ValueError("token decimals resolution ledger does not partition the anchor perimeter")
    manifest_lineage = None
    if anchor_manifest_path is not None:
        if not anchor_manifest_path.is_file():
            raise FileNotFoundError("token decimals resolution lacks its selected-anchor manifest")
        manifest_lineage = {
            "path": _portable_path(anchor_manifest_path, repo_root),
            "sha256": hashlib.sha256(anchor_manifest_path.read_bytes()).hexdigest(),
        }
    evidence_lineage = [
        {
            "token": token,
            "path": _portable_path(paths[token], repo_root),
            "sha256": hashlib.sha256(paths[token].read_bytes()).hexdigest(),
        }
        for token in sorted(paths)
    ]
    unresolved = []
    for token in sorted(failures):
        failure = failures[token]
        if failure.get("token") != token or failure.get("anchor_identity_sha256") != token_decimals_anchor_sha256(anchors[token]):
            raise ValueError("token decimals failure record disagrees with its anchor")
        unresolved.append(
            {
                "anchor": asdict(anchors[token]),
                **dict(failure),
            }
        )
    return {
        "schema_version": UNRESOLVED_TOKEN_DECIMALS_LEDGER_SCHEMA_VERSION,
        "kind": "unresolved_token_decimals",
        "status": "complete",
        "anchor_count": len(anchors),
        "anchors_sha256": token_decimals_anchors_sha256(anchors),
        "resolved_count": len(records),
        "unresolved_count": len(unresolved),
        "selected_anchor_manifest": manifest_lineage,
        "resolved_evidence": evidence_lineage,
        "resolved_evidence_sha256": canonical_json_sha256(evidence_lineage),
        "unresolved": unresolved,
        "unresolved_sha256": canonical_json_sha256(unresolved),
    }


def write_unresolved_token_decimals_ledger(
    ledger: Mapping[str, object],
    path: Path = UNRESOLVED_TOKEN_DECIMALS_LEDGER,
) -> None:
    """Install the complete failure ledger only after the resolver drains."""

    write_json(path, dict(ledger))


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
