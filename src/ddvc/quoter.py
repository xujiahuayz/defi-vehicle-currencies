"""Shared JSON-RPC transport and historical-state quote helpers.

Historical route comparisons must evaluate rival paths against the same
pre-trade block state. This module supplies the reusable request, retry, cache,
and quote primitives used by the current acquisition and processing stages.

Method. Uniswap's V3 Quoter is a deployed contract whose `quoteExactInput(bytes,
uint256)` simulates a swap without executing it. Called through `eth_call` with a
historical block tag, it returns what the swap would have produced against that
block's pool state. The original V3 Quoter is used because QuoterV2 is not
deployed from the V3 launch period, and the sample begins there.

Every JSON-RPC request and response is persisted
verbatim before any quote is decoded. Reruns then cost nothing and a decode bug
never requires refetching.

Callers pace requests and treat a throttled response as retryable rather than as
a missing quote; `is_cached` counts only successful responses.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from eth_abi import decode as abi_decode
from eth_utils import keccak

from ddvc.config import dotenv_value

# The original Quoter, deployed 2021-05, covering the whole V3 sample.
UNISWAP_V3_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
QUOTE_SELECTOR = "0x" + keccak(text="quoteExactInput(bytes,uint256)")[:4].hex()

# Fee tiers in hundredths of a bip: 0.01%, 0.05%, 0.30%, 1.00%.
FEE_TIERS = (100, 500, 3000, 10000)

_UA = "ddvc-quoter/1.0"
_DEFAULT_RPCS = (
    "https://mainnet.gateway.tenderly.co",
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
)
_rpc_idx = 0
_rpc_idx_lock = threading.Lock()
_disabled_rpc_urls: set[str] = set()
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
_CAPACITY_MARKERS = (
    "block range",
    "range over",
    "ranges over",
    "response size",
    "result limit",
    "too many results",
    "query timeout",
    "request timeout",
)
_AUTHENTICATION_MARKERS = ("unauthorized", "authenticat", "api key", "personal token")
_TRANSIENT_RPC_MARKERS = ("rate limit", "usage limit", "temporarily unavailable", "can't route")
RPC_EVIDENCE_FIELDS = (
    "rpc_request",
    "rpc_response",
    "rpc_endpoint",
    "rpc_attempts",
)


def rpc_urls() -> list[str]:
    raw = (
        os.getenv("ETH_RPC_URLS")
        or os.getenv("ETH_RPC_URL")
        or dotenv_value("ETH_RPC_URLS", "ETH_RPC_URL")
    )
    if raw:
        urls = [u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()]
        if urls:
            return urls
    return list(_DEFAULT_RPCS)


def _authentication_error(error: object) -> bool:
    if not isinstance(error, dict):
        return False
    message = str(error.get("message") or "").lower()
    return any(marker in message for marker in _AUTHENTICATION_MARKERS)


def _authentication_failure(payload: object) -> bool:
    if isinstance(payload, list):
        return any(
            _authentication_error(item.get("error"))
            for item in payload
            if isinstance(item, dict)
        )
    return isinstance(payload, dict) and _authentication_error(payload.get("error"))


class Throttled(RuntimeError):
    """Endpoint refused for rate-limit reasons; the job is retryable."""


@dataclass(frozen=True)
class RpcEnvelope:
    """One successful RPC response plus credential-safe transport evidence."""

    response: object
    endpoint: dict[str, str]
    attempts: tuple[dict[str, object], ...]


def coerce_rpc_envelope(response: object) -> RpcEnvelope:
    """Wrap an injected test transport in the canonical evidence shape."""

    if isinstance(response, RpcEnvelope) and response.attempts:
        return response
    endpoint = (
        response.endpoint
        if isinstance(response, RpcEnvelope)
        else {"host": "injected"}
    )
    attempt = {
        "endpoint": endpoint,
        "attempt": 1,
        "classification": "success",
        "http_status": None,
        "rpc_code": None,
        "message": "success",
    }
    payload = response.response if isinstance(response, RpcEnvelope) else response
    return RpcEnvelope(payload, endpoint, (attempt,))


class RpcCapacityError(RuntimeError):
    """An explicit provider range or result cap that licenses bisection."""

    def __init__(self, message: str, *, attempts: tuple[dict[str, object], ...] = ()) -> None:
        super().__init__(message)
        self.attempts = attempts


class RpcSemanticError(RuntimeError):
    """A non-transient JSON-RPC failure that must not be treated as empty data."""

    def __init__(self, message: str, *, attempts: tuple[dict[str, object], ...] = ()) -> None:
        super().__init__(message)
        self.attempts = attempts


def sanitized_endpoint_identity(url: str) -> dict[str, str]:
    """Identify a provider by host without retaining credentials or URLs."""

    parsed = urlsplit(url)
    host = (parsed.hostname or "unknown").lower()
    return {"host": host}


def validate_rpc_attempts(
    attempts: object,
    endpoint: object,
) -> None:
    """Validate one successful transport history against its winning endpoint."""

    def valid_endpoint(value: object) -> bool:
        return bool(
            isinstance(value, dict)
            and set(value) == {"host"}
            and isinstance(value.get("host"), str)
            and value["host"]
        )

    if not valid_endpoint(endpoint):
        raise ValueError("RPC evidence lacks a sanitized endpoint identity")
    if not isinstance(attempts, (list, tuple)) or not attempts:
        raise ValueError("RPC evidence lacks attempt history")
    allowed = {"capacity", "success", "terminal", "transient"}
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or not valid_endpoint(attempt.get("endpoint")):
            raise ValueError("RPC attempt evidence contains a malformed endpoint")
        if not isinstance(attempt.get("attempt"), int) or int(attempt["attempt"]) < 1:
            raise ValueError("RPC attempt evidence contains an invalid attempt number")
        classification = attempt.get("classification")
        if classification not in allowed:
            raise ValueError("RPC attempt evidence contains an invalid classification")
        if attempt.get("http_status") is not None and not isinstance(attempt["http_status"], int):
            raise ValueError("RPC attempt evidence contains an invalid HTTP status")
        if attempt.get("rpc_code") is not None and not isinstance(attempt["rpc_code"], int):
            raise ValueError("RPC attempt evidence contains an invalid RPC code")
        if not isinstance(attempt.get("message"), str) or not attempt["message"]:
            raise ValueError("RPC attempt evidence contains an invalid message category")
        if classification == "success" and index != len(attempts) - 1:
            raise ValueError("RPC attempt evidence contains a non-terminal success")
    final = attempts[-1]
    if final.get("classification") != "success" or final.get("endpoint") != endpoint:
        raise ValueError("RPC attempt evidence is not bound to the successful endpoint")
    if final.get("rpc_code") is not None:
        raise ValueError("successful RPC attempt evidence contains an RPC error code")


def _rpc_error_details(payload: object) -> tuple[int | None, str]:
    if isinstance(payload, list):
        errors = [item for item in payload if isinstance(item, dict) and isinstance(item.get("error"), dict)]
        if not errors:
            return None, ""
        return _rpc_error_details(errors[0])
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None, ""
    error = payload["error"]
    try:
        code = int(error.get("code")) if error.get("code") is not None else None
    except (TypeError, ValueError):
        code = None
    return code, str(error.get("message") or "")


def _capacity_failure(http_status: int | None, rpc_code: int | None, message: str) -> bool:
    normalized = message.lower()
    return bool(
        http_status == 408
        or rpc_code in {30, 35}
        or any(marker in normalized for marker in _CAPACITY_MARKERS)
    )


def _attempt_record(
    endpoint: dict[str, str],
    *,
    attempt: int,
    classification: str,
    http_status: int | None,
    rpc_code: int | None,
    message: str,
) -> dict[str, object]:
    normalized = message.lower()
    evidence_markers = (
        *_CAPACITY_MARKERS,
        *_TRANSIENT_RPC_MARKERS,
        *_AUTHENTICATION_MARKERS,
        "invalid params",
        "execution reverted",
        "unknown block hash",
    )
    message_category = next(
        (marker for marker in evidence_markers if marker in normalized),
        "success" if classification == "success" else f"{classification} RPC failure",
    )
    return {
        "endpoint": endpoint,
        "attempt": attempt,
        "classification": classification,
        "http_status": http_status,
        "rpc_code": rpc_code,
        "message": message_category,
    }


def rpc_post(payload: dict | list[dict], *, timeout: int = 60,
             retries: int = 3, sleep: float = 0.0,
             retry_json_errors: bool = False,
             return_evidence: bool = False,
             classify_capacity: bool = False,
             retry_delay: float | None = None,
             response_validator: Callable[[Any], object] | None = None) -> Any:
    """POST a JSON-RPC payload, rotating endpoints on failure.

    Raises Throttled when every endpoint refuses for rate-limit reasons, so the
    caller can distinguish "ask again later" from "this quote does not exist".
    """
    if retries < 1:
        raise ValueError("RPC retries must be positive")
    global _rpc_idx
    data = json.dumps(payload).encode()
    urls = rpc_urls()
    with _rpc_idx_lock:
        urls = [url for url in urls if url not in _disabled_rpc_urls]
        if not urls:
            raise RuntimeError("no enabled Ethereum RPC endpoint remains")
        start = _rpc_idx % len(urls)
    ordered = urls[start:] + urls[:start]
    attempts: list[dict[str, object]] = []
    capacity_failures: list[dict[str, object]] = []
    transient_failures: list[dict[str, object]] = []
    terminal_failures: list[dict[str, object]] = []
    last: Exception | None = None
    for url in ordered:
        endpoint = sanitized_endpoint_identity(url)
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json", "User-Agent": _UA},
                method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    response = json.loads(r.read())
                    http_status = int(getattr(r, "status", 200))
                    rpc_code, message = _rpc_error_details(response)
                    if rpc_code is not None and (retry_json_errors or classify_capacity):
                        authentication_failure = _authentication_failure(response)
                        if authentication_failure:
                            with _rpc_idx_lock:
                                _disabled_rpc_urls.add(url)
                            classification = "transient"
                        elif classify_capacity and _capacity_failure(http_status, rpc_code, message):
                            classification = "capacity"
                        elif rpc_code in {-32001, -32005} or any(
                            marker in message.lower() for marker in _TRANSIENT_RPC_MARKERS
                        ):
                            classification = "transient"
                        else:
                            classification = "terminal"
                        record = _attempt_record(
                            endpoint,
                            attempt=attempt,
                            classification=classification,
                            http_status=http_status,
                            rpc_code=rpc_code,
                            message=message,
                        )
                        attempts.append(record)
                        last = RuntimeError(f"JSON-RPC error {rpc_code}: {message}")
                        if classification == "capacity":
                            capacity_failures.append(record)
                            break
                        if classification == "transient":
                            transient_failures.append(record)
                            if authentication_failure:
                                break
                            if attempt < retries:
                                time.sleep(retry_delay if retry_delay is not None else max(sleep, 1.0))
                                continue
                            break
                        terminal_failures.append(record)
                        break
                    if response_validator is not None:
                        try:
                            response_validator(response)
                        except (RuntimeError, TypeError, ValueError) as exc:
                            last = exc
                            record = _attempt_record(
                                endpoint,
                                attempt=attempt,
                                classification="transient",
                                http_status=http_status,
                                rpc_code=None,
                                message=f"invalid successful response: {type(exc).__name__}",
                            )
                            attempts.append(record)
                            transient_failures.append(record)
                            break
                    with _rpc_idx_lock:
                        _rpc_idx = urls.index(url)
                    attempts.append(_attempt_record(
                        endpoint,
                        attempt=attempt,
                        classification="success",
                        http_status=http_status,
                        rpc_code=None,
                        message="success",
                    ))
                    if sleep:
                        time.sleep(sleep)
                    if return_evidence:
                        return RpcEnvelope(response, endpoint, tuple(attempts))
                    return response
            except urllib.error.HTTPError as exc:
                last = exc
                try:
                    error_payload = json.loads(exc.read())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    error_payload = {}
                rpc_code, message = _rpc_error_details(error_payload)
                message = message or str(exc)
                if classify_capacity and _capacity_failure(exc.code, rpc_code, message):
                    classification = "capacity"
                elif exc.code in _RETRYABLE_HTTP_CODES or exc.code == 403:
                    classification = "transient"
                else:
                    classification = "terminal"
                record = _attempt_record(
                    endpoint,
                    attempt=attempt,
                    classification=classification,
                    http_status=exc.code,
                    rpc_code=rpc_code,
                    message=message,
                )
                attempts.append(record)
                if classification == "capacity":
                    capacity_failures.append(record)
                    break
                if classification == "transient":
                    transient_failures.append(record)
                    if exc.code == 403:
                        break
                    if attempt < retries:
                        time.sleep(retry_delay if retry_delay is not None else max(sleep, 1.0))
                        continue
                    break
                terminal_failures.append(record)
                break
            except Exception as exc:  # transport failures are retryable
                last = exc
                record = _attempt_record(
                    endpoint,
                    attempt=attempt,
                    classification="transient",
                    http_status=None,
                    rpc_code=None,
                    message=f"{type(exc).__name__}: {exc}",
                )
                attempts.append(record)
                transient_failures.append(record)
                if attempt < retries:
                    time.sleep(retry_delay if retry_delay is not None else max(sleep, 0.5))
    frozen_attempts = tuple(attempts)
    if classify_capacity and terminal_failures:
        raise RpcSemanticError("RPC request failed semantically", attempts=frozen_attempts)
    if classify_capacity and capacity_failures:
        raise RpcCapacityError("RPC request exceeded provider capacity", attempts=frozen_attempts)
    if transient_failures:
        raise Throttled("all RPC endpoints were transiently unavailable")
    if return_evidence and terminal_failures:
        raise RpcSemanticError("RPC request failed semantically", attempts=frozen_attempts)
    raise RuntimeError(f"all RPC endpoints failed: {last}")


def encode_path(tokens: Iterable[str], fees: Iterable[int]) -> bytes:
    """Encode a V3 multi-hop path: token, fee, token, fee, ... token.

    Generalised from the original's fixed three-token form so an arbitrary
    number of intermediaries can be priced.
    """
    toks = [t.lower().removeprefix("0x") for t in tokens]
    fs = list(fees)
    if len(toks) != len(fs) + 1:
        raise ValueError(f"{len(toks)} tokens needs {len(toks)-1} fees, got {len(fs)}")
    out = bytes.fromhex(toks[0])
    for fee, tok in zip(fs, toks[1:]):
        out += int(fee).to_bytes(3, "big") + bytes.fromhex(tok)
    return out


def calldata(tokens: Iterable[str], fees: Iterable[int], amount_in: int) -> str:
    path = encode_path(tokens, fees)
    # quoteExactInput(bytes path, uint256 amountIn): offset, amount, len, payload
    head = (32 * 2).to_bytes(32, "big") + int(amount_in).to_bytes(32, "big")
    body = len(path).to_bytes(32, "big") + path.ljust(((len(path) + 31) // 32) * 32, b"\0")
    return QUOTE_SELECTOR + (head + body).hex()


@dataclass(frozen=True)
class QuoteJob:
    """One counterfactual question: this path, this size, this historical block."""
    job_id: str
    block: int
    tokens: tuple[str, ...]
    fees: tuple[int, ...]
    amount_in: int

    def request(self, rpc_id: int) -> dict:
        return {
            "jsonrpc": "2.0", "id": rpc_id, "method": "eth_call",
            "params": [{"to": UNISWAP_V3_QUOTER,
                        "data": calldata(self.tokens, self.fees, self.amount_in)},
                       hex(self.block)],
        }


def decode_quote(result: str) -> int | None:
    """Decode a uint256 amountOut; None when the call reverted (no liquidity)."""
    if not result or result in ("0x", "0x0"):
        return None
    try:
        return int(abi_decode(["uint256"], bytes.fromhex(result[2:]))[0])
    except Exception:
        return None


class QuoteStore:
    """Append-only raw store of request/response pairs, keyed by job id.

    Only SUCCESSFUL quotes count as cached. The earlier run stalled because
    throttled error lines were treated as answers, so a rerun skipped them and
    could never finish.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: set[str] | None = None

    def cached_ids(self) -> set[str]:
        if self._done is not None:
            return self._done
        done: set[str] = set()
        if self.path.exists():
            with gzip.open(self.path, "rt") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("amount_out") is not None:
                        done.add(rec["job_id"])
        self._done = done
        return done

    def append(self, records: list[dict]) -> None:
        if not records:
            return
        with gzip.open(self.path, "at") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        if self._done is not None:
            self._done.update(r["job_id"] for r in records
                              if r.get("amount_out") is not None)


def run_jobs(jobs: list[QuoteJob], store: QuoteStore, *, batch: int = 20,
             sleep: float = 0.6, progress: bool = True) -> dict[str, int]:
    """Quote every job not already answered, persisting raw responses.

    Returns counts of ok / reverted / throttled, so a caller can decide whether
    to keep going or back off.
    """
    todo = [j for j in jobs if j.job_id not in store.cached_ids()]
    stats = {"ok": 0, "reverted": 0, "throttled": 0, "skipped": len(jobs) - len(todo)}
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        payload = [j.request(n) for n, j in enumerate(chunk)]
        try:
            resp = rpc_post(payload, sleep=sleep)
        except Throttled:
            stats["throttled"] += len(chunk)
            time.sleep(5.0)
            continue
        except Exception:
            stats["throttled"] += len(chunk)
            continue
        by_id = {r.get("id"): r for r in (resp if isinstance(resp, list) else [resp])}
        recs = []
        for n, j in enumerate(chunk):
            r = by_id.get(n) or {}
            out = decode_quote(r.get("result", ""))
            recs.append({"job_id": j.job_id, "block": j.block,
                         "tokens": list(j.tokens), "fees": list(j.fees),
                         "amount_in": str(j.amount_in),
                         "amount_out": str(out) if out is not None else None,
                         "error": (r.get("error") or {}).get("message")})
            stats["ok" if out is not None else "reverted"] += 1
        store.append(recs)
        if progress and (i // batch) % 10 == 0:
            print(f"  quoted {i + len(chunk):,}/{len(todo):,}  {stats}", flush=True)
    return stats
