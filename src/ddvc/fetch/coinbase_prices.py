"""Coinbase ETH/USD minute-candle transport, request planning, and raw evidence."""

from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import os
import sqlite3
import tempfile
import threading
import time
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import numpy as np
import pandas as pd
import requests

from ddvc.calendar import sample_end_utc_exclusive
from ddvc.fetch.raw import repair_torn_jsonl_journal, write_jsonl_gz
from ddvc.http import DEFAULT_USER_AGENT
from ddvc.runtime import atomic_output, interruptible_thread_pool


SOURCE_ID = "coinbase_exchange_eth_usd_spot_1m_close"
PRODUCT_ID = "ETH-USD"
API_URL = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/candles"
PRODUCT_URL = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}"
INTERVAL_SECONDS = 60
MAX_CANDLES_PER_REQUEST = 300
MAX_FETCH_WORKERS = 3
PARALLEL_WORKER_MIN_INTERVAL_SECONDS = 0.35
SAMPLE_START_UTC = int(pd.Timestamp("2020-05-05T00:00:00Z").timestamp())
SAMPLE_END_UTC_EXCLUSIVE = sample_end_utc_exclusive()
RAW_SCHEMA_VERSION = 1
RAW_RECORD_KEYS = frozenset({"schema_version", "source_id", "request_identity", "request", "fetched_at_utc", "response_headers", "response_body", "response_sha256", "attempt_history"})
RAW_REQUEST_KEYS = frozenset({"method", "url", "product_id", "granularity_seconds", "start_utc", "end_utc_exclusive"})
RAW_RESPONSE_HEADER_KEYS = frozenset({"content-type", "date", "etag", "last-modified"})


def exact_integer(value: object, *, label: str) -> int:
    """Parse an integer-valued field without truncating fractions or nonfinite values."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be an exact integer")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an exact integer") from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError(f"{label} must be an exact integer")
    return int(parsed)


@dataclass(frozen=True)
class CandleRequest:
    """One exact half-open minute-candle request perimeter."""

    start_utc: int
    end_utc_exclusive: int

    def __post_init__(self) -> None:
        start = exact_integer(self.start_utc, label="external-price request start")
        end = exact_integer(self.end_utc_exclusive, label="external-price request end")
        if start % INTERVAL_SECONDS or end % INTERVAL_SECONDS:
            raise ValueError("external-price bounds must lie on UTC minute boundaries")
        if end <= start:
            raise ValueError("external-price interval is empty")
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc_exclusive", end)

    @property
    def end_utc_inclusive(self) -> int:
        return self.end_utc_exclusive - 1

    @property
    def identity(self) -> str:
        return f"{self.start_utc}:{self.end_utc_exclusive}"


@dataclass(frozen=True)
class AnnualEvidencePaths:
    """Canonical raw evidence names for one source year."""

    base: Path
    gaps: Path
    audit: Path


def annual_evidence_paths(raw_root: Path, year: int) -> AnnualEvidencePaths:
    """Resolve one annual evidence bundle from its single naming policy."""

    return AnnualEvidencePaths(base=raw_root / f"{year}.jsonl.gz", gaps=raw_root / f"{year}.gaps.jsonl.gz", audit=raw_root / f"{year}.gap_audit.json")


def plan_candle_requests(start_utc: int, end_utc_exclusive: int) -> list[CandleRequest]:
    """Partition an aligned half-open interval into API-admissible requests."""

    start = exact_integer(start_utc, label="external-price request start")
    end = exact_integer(end_utc_exclusive, label="external-price request end")
    perimeter = CandleRequest(start, end)
    width = MAX_CANDLES_PER_REQUEST * INTERVAL_SECONDS
    return [CandleRequest(cursor, min(cursor + width, perimeter.end_utc_exclusive)) for cursor in range(perimeter.start_utc, perimeter.end_utc_exclusive, width)]


def annual_perimeters(start_utc: int, end_utc_exclusive: int):
    """Yield nonoverlapping annual source perimeters from an arbitrary start."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    cursor = pd.Timestamp(perimeter.start_utc, unit="s", tz="UTC")
    end = pd.Timestamp(perimeter.end_utc_exclusive, unit="s", tz="UTC")
    while cursor < end:
        boundary = min(cursor + pd.offsets.YearBegin(), end)
        yield int(cursor.timestamp()), int(boundary.timestamp()), cursor.year
        cursor = boundary


def iso_utc(value: int) -> str:
    exact = exact_integer(value, label="external-price timestamp")
    return datetime.fromtimestamp(exact, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def body_sha256(body: str | bytes) -> str:
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return hashlib.sha256(payload).hexdigest()


def _response_rows(body: str) -> list[list[object]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("Coinbase candle response is not JSON") from error
    if not isinstance(payload, list):
        raise ValueError("Coinbase candle response is not a list")
    if any(not isinstance(row, list) or len(row) != 6 for row in payload):
        raise ValueError("Coinbase candle response has an unexpected row schema")
    return payload


def validate_response_body(body: str, request: CandleRequest) -> list[list[object]]:
    """Validate every returned candle before selecting the requested perimeter."""

    validated: list[list[object]] = []
    for row in _response_rows(body):
        timestamp = exact_integer(row[0], label="Coinbase candle timestamp")
        if timestamp % INTERVAL_SECONDS:
            raise ValueError(f"Coinbase response has an off-grid minute in {request.identity}")
        if any(isinstance(value, bool) for value in row[1:6]):
            raise ValueError(f"Coinbase response has invalid OHLCV in {request.identity}")
        try:
            low, high, opened, closed, volume = map(float, row[1:6])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Coinbase response has invalid OHLCV in {request.identity}") from error
        values = np.asarray([low, high, opened, closed, volume])
        if not np.isfinite(values).all() or min(low, high, opened, closed) <= 0 or volume < 0 or low > min(opened, closed) or high < max(opened, closed):
            raise ValueError(f"Coinbase response has invalid OHLCV in {request.identity}")
        validated.append([timestamp, *row[1:6]])
    times = [int(row[0]) for row in validated]
    if len(times) != len(set(times)):
        raise ValueError(f"Coinbase response duplicates a minute in {request.identity}")
    return [row for row in validated if request.start_utc <= int(row[0]) < request.end_utc_exclusive]


def fetch_candle_request(session: requests.Session, request: CandleRequest, *, max_attempts: int = 6, minimum_interval_seconds: float = 0.12) -> dict[str, object]:
    """Fetch one request while retaining the exact winning response and attempts."""

    attempts: list[dict[str, object]] = []
    for attempt in range(1, max_attempts + 1):
        started = datetime.now(timezone.utc).isoformat()
        response = None
        try:
            response = session.get(API_URL, params={"granularity": INTERVAL_SECONDS, "start": iso_utc(request.start_utc), "end": iso_utc(request.end_utc_inclusive)}, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}, timeout=30)
            body_bytes = response.content
            body = body_bytes.decode("utf-8")
            attempts.append({"attempt": attempt, "started_at_utc": started, "status_code": response.status_code, "response_sha256": body_sha256(body_bytes)})
            if response.status_code == 200:
                validate_response_body(body, request)
                time.sleep(minimum_interval_seconds)
                return {
                    "schema_version": RAW_SCHEMA_VERSION,
                    "source_id": SOURCE_ID,
                    "request_identity": request.identity,
                    "request": {"method": "GET", "url": response.request.url, "product_id": PRODUCT_ID, "granularity_seconds": INTERVAL_SECONDS, "start_utc": request.start_utc, "end_utc_exclusive": request.end_utc_exclusive},
                    "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                    "response_headers": {key.lower(): value for key, value in response.headers.items() if key.lower() in {"content-type", "date", "etag", "last-modified"}},
                    "response_body": body,
                    "response_sha256": body_sha256(body_bytes),
                    "attempt_history": attempts,
                }
        except (requests.RequestException, ValueError) as error:
            message = f"{type(error).__name__}: {error}"
            if attempts and attempts[-1].get("attempt") == attempt:
                attempts[-1]["error"] = message
            else:
                attempts.append({"attempt": attempt, "started_at_utc": started, "error": message})
        if attempt < max_attempts:
            retry_after = 0.0
            if response is not None and response.status_code == 429:
                try:
                    retry_after = float(response.headers.get("Retry-After", 0))
                except ValueError:
                    retry_after = 0.0
            time.sleep(max(minimum_interval_seconds, retry_after, min(30.0, 2 ** (attempt - 1))))
    raise RuntimeError(f"Coinbase candle request {request.identity} failed after {max_attempts} attempts: {attempts[-1]}")


def validate_source_identity_body(body: str) -> dict[str, object]:
    """Require the advertised spot product to be native ETH quoted in fiat USD."""

    try:
        product = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("Coinbase product response is not JSON") from error
    expected = {"id": PRODUCT_ID, "base_currency": "ETH", "quote_currency": "USD"}
    if not isinstance(product, dict) or any(product.get(key) != value for key, value in expected.items()):
        raise ValueError("Coinbase product identity is not ETH quoted in USD")
    return product


def validate_source_identity_file(path: Path) -> dict[str, object]:
    """Reopen the exact product-identity response and verify every copied field."""

    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or not isinstance(record.get("request"), dict) or not isinstance(record.get("response_body"), str):
        raise ValueError("external-price source-identity digest mismatch")
    body = record["response_body"]
    parsed = urlparse(str(record["request"].get("url") or ""))
    if record.get("schema_version") != RAW_SCHEMA_VERSION or record.get("source_id") != SOURCE_ID or record.get("request") != {"method": "GET", "url": PRODUCT_URL} or parsed.scheme != "https" or parsed.netloc != "api.exchange.coinbase.com" or record.get("response_sha256") != body_sha256(body):
        raise ValueError("external-price source-identity digest mismatch")
    validate_source_identity_body(body)
    return record


def fetch_source_identity(path: Path, *, session: requests.Session | None = None) -> Path:
    """Capture exact external-market identity once without silently replacing it."""

    if path.exists():
        validate_source_identity_file(path)
        return path
    client = session or requests.Session()
    try:
        response = client.get(PRODUCT_URL, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}, timeout=30)
        response.raise_for_status()
        body_bytes = response.content
        body = body_bytes.decode("utf-8")
        validate_source_identity_body(body)
        record = {"schema_version": RAW_SCHEMA_VERSION, "source_id": SOURCE_ID, "request": {"method": "GET", "url": response.request.url}, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "response_body": body, "response_sha256": body_sha256(body_bytes)}
    finally:
        if session is None:
            client.close()
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _exact_query(parsed_url, start_utc: int, end_utc_exclusive: int) -> bool:
    pairs = parse_qsl(parsed_url.query, keep_blank_values=True)
    keys = [key for key, _value in pairs]
    if len(keys) != 3 or len(keys) != len(set(keys)) or set(keys) != {"granularity", "start", "end"}:
        return False
    query = dict(pairs)
    return query == {"granularity": str(INTERVAL_SECONDS), "start": iso_utc(start_utc), "end": iso_utc(end_utc_exclusive - 1)}


def _validate_attempt_history(attempts: object, response_sha256: str) -> bool:
    if not isinstance(attempts, list) or not attempts:
        return False
    for expected_attempt, envelope in enumerate(attempts, start=1):
        if not isinstance(envelope, dict) or envelope.get("attempt") != expected_attempt or not isinstance(envelope.get("started_at_utc"), str) or not envelope["started_at_utc"]:
            return False
        keys = set(envelope)
        response_keys = {"attempt", "started_at_utc", "status_code", "response_sha256"}
        exception_keys = {"attempt", "started_at_utc", "error"}
        if "status_code" in envelope:
            if keys not in (response_keys, response_keys | {"error"}) or isinstance(envelope["status_code"], bool) or not isinstance(envelope["status_code"], int) or not 100 <= envelope["status_code"] <= 599 or not isinstance(envelope.get("response_sha256"), str) or len(envelope["response_sha256"]) != 64 or any(character not in "0123456789abcdef" for character in envelope["response_sha256"]):
                return False
        elif keys != exception_keys:
            return False
        if "error" in envelope and (not isinstance(envelope["error"], str) or not envelope["error"]):
            return False
    final = attempts[-1]
    return final.get("status_code") == 200 and "error" not in final and final.get("response_sha256") == response_sha256


def _validate_raw_record(record: dict[str, object], path: Path) -> str:
    if not isinstance(record, dict) or set(record) != RAW_RECORD_KEYS or not isinstance(record.get("response_body"), str):
        raise ValueError(f"invalid external-price raw evidence in {path.name}")
    request = record.get("request") or {}
    if not isinstance(request, dict):
        raise ValueError(f"invalid external-price raw evidence in {path.name}")
    try:
        start_utc = exact_integer(request.get("start_utc"), label="external-price request start")
        end_utc_exclusive = exact_integer(request.get("end_utc_exclusive"), label="external-price request end")
        request_spec = CandleRequest(start_utc, end_utc_exclusive)
    except ValueError as error:
        raise ValueError(f"invalid external-price raw evidence in {path.name}") from error
    identity = str(record.get("request_identity") or "")
    parsed_url = urlparse(str(request.get("url") or ""))
    response_headers = record.get("response_headers")
    response_sha256 = record.get("response_sha256")
    if record.get("schema_version") != RAW_SCHEMA_VERSION or record.get("source_id") != SOURCE_ID or identity != request_spec.identity or not isinstance(record.get("fetched_at_utc"), str) or not record["fetched_at_utc"] or not isinstance(response_sha256, str) or response_sha256 != body_sha256(record["response_body"]) or set(request) != RAW_REQUEST_KEYS or request.get("method") != "GET" or request.get("product_id") != PRODUCT_ID or request.get("granularity_seconds") != INTERVAL_SECONDS or not isinstance(response_headers, dict) or not set(response_headers).issubset(RAW_RESPONSE_HEADER_KEYS) or any(not isinstance(value, str) for value in response_headers.values()) or parsed_url.scheme != "https" or parsed_url.netloc != "api.exchange.coinbase.com" or parsed_url.path != f"/products/{PRODUCT_ID}/candles" or parsed_url.fragment or not _exact_query(parsed_url, start_utc, end_utc_exclusive) or not _validate_attempt_history(record.get("attempt_history"), response_sha256):
        raise ValueError(f"invalid external-price raw evidence in {path.name}")
    validate_response_body(record["response_body"], request_spec)
    return identity


def iter_raw_records(path: Path, *, require_sorted: bool = False):
    """Stream and verify exact raw records, optionally requiring request order."""

    opener = gzip.open if path.suffix == ".gz" else open
    previous_start: int | None = None
    with tempfile.TemporaryDirectory(prefix="ddvc-external-raw-seen-") as index_directory:
        index = sqlite3.connect(Path(index_directory) / "seen.sqlite3")
        try:
            index.execute("CREATE TABLE seen (identity TEXT PRIMARY KEY)")
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"invalid external-price raw evidence in {path.name}") from error
                    identity = _validate_raw_record(record, path)
                    try:
                        index.execute("INSERT INTO seen VALUES (?)", (identity,))
                    except sqlite3.IntegrityError as error:
                        raise ValueError(f"invalid external-price raw evidence in {path.name}") from error
                    start = exact_integer(record["request"]["start_utc"], label="external-price request start")
                    if require_sorted and previous_start is not None and start <= previous_start:
                        raise ValueError(f"external-price raw evidence is not strictly ordered in {path.name}")
                    previous_start = start
                    yield record
        finally:
            index.close()


def read_raw_records(path: Path) -> list[dict[str, object]]:
    """Read and verify a final gzip evidence file or repaired plain journal."""

    return list(iter_raw_records(path))


def fetch_raw_file(path: Path, requests_to_fetch: Iterable[CandleRequest], *, session: requests.Session | None = None, workers: int = 3) -> Path:
    """Fetch a bounded perimeter into one resumable, content-verifiable raw file."""

    if workers < 1 or workers > MAX_FETCH_WORKERS:
        raise ValueError(f"external-price fetch workers must be between one and {MAX_FETCH_WORKERS}")
    if path.exists():
        sentinel = object()
        for expected_request, record in itertools.zip_longest(requests_to_fetch, iter_raw_records(path, require_sorted=True), fillvalue=sentinel):
            if expected_request is sentinel or record is sentinel or expected_request.identity != record["request_identity"]:
                raise RuntimeError(f"existing {path.name} does not match the requested perimeter")
        return path
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        repair_torn_jsonl_journal(partial)
    partial.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ddvc-external-raw-index-") as index_directory:
        index = sqlite3.connect(Path(index_directory) / "records.sqlite3")
        try:
            index.execute("CREATE TABLE expected (identity TEXT PRIMARY KEY, start_utc INTEGER UNIQUE NOT NULL, end_utc_exclusive INTEGER NOT NULL)")
            index.execute("CREATE TABLE records (identity TEXT PRIMARY KEY, start_utc INTEGER UNIQUE NOT NULL, body TEXT NOT NULL)")
            try:
                index.executemany("INSERT INTO expected VALUES (?, ?, ?)", ((request.identity, request.start_utc, request.end_utc_exclusive) for request in requests_to_fetch))
            except sqlite3.IntegrityError as error:
                raise ValueError("external-price request perimeter duplicates an identity or start") from error
            if partial.exists():
                for record in iter_raw_records(partial):
                    identity = str(record["request_identity"])
                    start = exact_integer(record["request"]["start_utc"], label="external-price request start")
                    if index.execute("SELECT start_utc FROM expected WHERE identity = ?", (identity,)).fetchone() != (start,):
                        raise RuntimeError(f"partial {path.name} escapes the requested perimeter")
                    try:
                        index.execute("INSERT INTO records VALUES (?, ?, ?)", (identity, start, json.dumps(record, sort_keys=True, separators=(",", ":"))))
                    except sqlite3.IntegrityError as error:
                        raise ValueError(f"invalid external-price raw evidence in {partial.name}") from error

            def pending_requests():
                for start, end in index.execute("SELECT start_utc, end_utc_exclusive FROM expected WHERE identity NOT IN (SELECT identity FROM records) ORDER BY start_utc"):
                    yield CandleRequest(start, end)

            with partial.open("a", encoding="utf-8", newline="\n") as handle:
                def persist(record: dict[str, object]) -> None:
                    identity = _validate_raw_record(record, partial)
                    start = exact_integer(record["request"]["start_utc"], label="external-price request start")
                    if index.execute("SELECT start_utc FROM expected WHERE identity = ?", (identity,)).fetchone() != (start,):
                        raise RuntimeError(f"fetched {path.name} record escapes the requested perimeter")
                    body = json.dumps(record, sort_keys=True, separators=(",", ":"))
                    handle.write(body + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    try:
                        index.execute("INSERT INTO records VALUES (?, ?, ?)", (identity, start, body))
                    except sqlite3.IntegrityError as error:
                        raise ValueError(f"invalid external-price raw evidence in {partial.name}") from error

                if session is not None or workers == 1:
                    client = session or requests.Session()
                    try:
                        for request in pending_requests():
                            persist(fetch_candle_request(client, request))
                    finally:
                        if session is None:
                            client.close()
                else:
                    local = threading.local()
                    clients: list[requests.Session] = []
                    clients_lock = threading.Lock()

                    def fetch_one(request: CandleRequest) -> dict[str, object]:
                        if not hasattr(local, "session"):
                            local.session = requests.Session()
                            with clients_lock:
                                clients.append(local.session)
                        return fetch_candle_request(local.session, request, minimum_interval_seconds=PARALLEL_WORKER_MIN_INTERVAL_SECONDS)

                    try:
                        with interruptible_thread_pool(workers) as pool:
                            request_iterator = iter(pending_requests())
                            outstanding = {pool.submit(fetch_one, request) for request in itertools.islice(request_iterator, workers * 2)}
                            while outstanding:
                                completed_futures, outstanding = wait(outstanding, return_when=FIRST_COMPLETED)
                                for future in completed_futures:
                                    persist(future.result())
                                    try:
                                        request = next(request_iterator)
                                    except StopIteration:
                                        continue
                                    outstanding.add(pool.submit(fetch_one, request))
                    finally:
                        for client in clients:
                            client.close()
            expected_count = int(index.execute("SELECT COUNT(*) FROM expected").fetchone()[0])
            record_count = int(index.execute("SELECT COUNT(*) FROM records").fetchone()[0])
            if record_count != expected_count:
                raise RuntimeError(f"raw evidence for {path.name} is incomplete")

            def ordered_records():
                for (body,) in index.execute("SELECT body FROM records ORDER BY start_utc"):
                    yield json.loads(body)

            write_jsonl_gz(path, ordered_records())
        finally:
            index.close()
    for _record in iter_raw_records(path, require_sorted=True):
        pass
    partial.unlink()
    return path
