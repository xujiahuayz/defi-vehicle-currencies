"""The Graph gateway client for raw, restartable fetches."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator
import datetime as dt
import threading
from dataclasses import dataclass
from typing import Any

from ddvc.config import dotenv_value
from ddvc.http import DEFAULT_USER_AGENT
from ddvc.paths import REPO_ROOT

GRAPH_ENDPOINT = "https://gateway.thegraph.com/api/{key}/{graph_path}/{subgraph_id}"
PAGE_SIZE = 1000


def graph_keys() -> list[str]:
    """Read an ordered, de-duplicated Graph API-key pool from the environment."""
    raw = (
        os.getenv("GRAPH_API_KEYS")
        or os.getenv("GRAPH_API_KEY")
        or dotenv_value("GRAPH_API_KEYS", "GRAPH_API_KEY")
    )
    keys: list[str] = []
    seen: set[str] = set()
    for value in re.split(r"[,\n]", raw):
        key = value.strip()
        if not key or key in {"your_key_here", "YOUR_API_KEY", "[api-key]"} or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys

# Per-key health, persisted so every process does not rediscover the same dead
# keys. Free Graph quota is per ACCOUNT and resets monthly, so a key is marked dead
# only for the current UTC month and is retried automatically next month.
KEY_STATE_PATH = REPO_ROOT / "data" / ".graph_key_state.json"
_STATE_LOCK = threading.Lock()


def _month() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m")


def _load_key_state() -> dict[str, Any]:
    try:
        state = json.loads(KEY_STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_key_state(state: dict[str, Any]) -> None:
    try:
        KEY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEY_STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    except OSError:
        pass


def mark_key_exhausted(key: str) -> None:
    """Record that this key has no quota left this month."""
    with _STATE_LOCK:
        state = _load_key_state()
        state.setdefault("exhausted", {})[key[-8:]] = _month()
        _save_key_state(state)


def key_is_exhausted(key: str) -> bool:
    return _load_key_state().get("exhausted", {}).get(key[-8:]) == _month()


class AllKeysExhausted(RuntimeError):
    """Every key in the pool is out of quota for the current month."""


@dataclass
class GraphClient:
    """Rotating Graph gateway client.

    Rotation is the whole point of holding a key pool, and it previously failed in
    five ways that all surfaced as "the Graph is down" rather than as a key problem.
    The index restarted at zero for every client, so with the first five of eleven
    keys exhausted each new client spent five failed round-trips before reaching a
    live one. Rotation never wrapped, so reaching the last key disabled the client
    permanently even though free quota is monthly and earlier keys recover. Nothing
    was persisted, so every process rediscovered the same dead keys. The index was
    mutated without a lock while several threads shared one client, which can rotate
    past a healthy key. And only 401, 403, 429 and "payment required" rotated, so a
    5xx or a timeout raised immediately with no retry at all.

    Now: dead keys are skipped from the start and remembered for the month, rotation
    wraps, mutation is locked, transient failures back off and retry, and the only
    fatal condition is every key being genuinely out of quota.
    """

    subgraph_id: str
    keys: list[str]
    graph_path: str = "subgraphs/id"
    sleep_seconds: float = 0.1
    max_transient_retries: int = 4
    response_deadline_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.keys:
            raise RuntimeError("No Graph API key set. Use GRAPH_API_KEYS or GRAPH_API_KEY.")
        import requests

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self._lock = threading.Lock()
        # Begin on a key not already known to be out of quota this month.
        self._key_index = next(
            (i for i, k in enumerate(self.keys) if not key_is_exhausted(k)), 0)
        self._dead: set[int] = {
            i for i, k in enumerate(self.keys) if key_is_exhausted(k)}

    @property
    def url(self) -> str:
        return GRAPH_ENDPOINT.format(
            key=self.keys[self._key_index],
            graph_path=self.graph_path,
            subgraph_id=self.subgraph_id,
        )

    def _advance(self, *, exhausted: bool) -> bool:
        """Move to the next usable key. False when the pool is spent."""
        with self._lock:
            if exhausted:
                self._dead.add(self._key_index)
                mark_key_exhausted(self.keys[self._key_index])
            if len(self._dead) >= len(self.keys):
                return False
            idx = self._key_index
            for _ in range(len(self.keys)):
                idx = (idx + 1) % len(self.keys)
                if idx not in self._dead:
                    self._key_index = idx
                    return True
            return False

    def _response_json(self, response: Any) -> dict[str, Any]:
        """Read one streamed response under a true wall-clock body deadline."""
        deadline = time.monotonic() + self.response_deadline_seconds
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Graph response exceeded {self.response_deadline_seconds:g}s body deadline"
                )
            if chunk:
                body.extend(chunk)
        return json.loads(body)

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        transient = 0
        while True:
            try:
                response = self.session.post(
                    self.url,
                    json={"query": query, "variables": variables},
                    timeout=(15, 30),
                    stream=True,
                )
            except Exception:
                transient += 1
                if transient > self.max_transient_retries:
                    raise
                time.sleep(min(2 ** transient, 20))
                continue

            if response.status_code in {401, 403}:
                response.close()
                if self._advance(exhausted=True):
                    continue
                raise AllKeysExhausted(
                    f"all {len(self.keys)} keys rejected (HTTP {response.status_code})")
            if response.status_code == 429:
                # Throttling is about rate, not quota, so the key stays usable.
                response.close()
                if self._advance(exhausted=False):
                    time.sleep(self.sleep_seconds)
                    continue
            if response.status_code >= 500:
                response.close()
                transient += 1
                if transient > self.max_transient_retries:
                    response.raise_for_status()
                time.sleep(min(2 ** transient, 20))
                continue

            try:
                response.raise_for_status()
                payload = self._response_json(response)
            except Exception:
                transient += 1
                if transient > self.max_transient_retries:
                    raise
                time.sleep(min(2 ** transient, 20))
                continue
            finally:
                response.close()
            errors = payload.get("errors") or []
            if errors:
                text = json.dumps(errors)
                low = text.lower()
                if "payment required" in low or "auth error" in low:
                    if self._advance(exhausted=True):
                        continue
                    raise AllKeysExhausted(
                        f"all {len(self.keys)} keys out of quota this month: {text[:200]}")
                raise RuntimeError(text)
            return payload["data"]


def live_keys(subgraph_id: str, keys: list[str] | None = None) -> list[str]:
    """Probe EVERY key and return those that answer. Never sample a pool.

    Reporting a pool as exhausted from a partial probe sent this project chasing a
    paid top-up when 5 of 11 keys were live: the dead ones sat at the front of a
    list that had grown by appending, so the first four looked conclusive.
    """
    pool = keys if keys is not None else graph_keys()
    out = []
    for k in pool:
        try:
            c = GraphClient(subgraph_id, [k])
            c.query("{_meta{block{number}}}", {})
            out.append(k)
        except Exception:
            continue
    return out


def _where_literal(where: dict[str, Any]) -> str:
    parts = []
    for key, value in where.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int | float):
            rendered = str(value)
        elif isinstance(value, str) and key != "id_gt" and re.fullmatch(r"-?\d+(\.\d+)?", value):
            rendered = value
        else:
            rendered = json.dumps(str(value))
        parts.append(f"{key}: {rendered}")
    return "{ " + ", ".join(parts) + " }"


def build_query(
    entity: str,
    fields: str,
    where: dict[str, Any],
    *,
    page_size: int = PAGE_SIZE,
    block_number: int | None = None,
) -> str:
    block_clause = f", block: {{ number: {block_number} }}" if block_number is not None else ""
    return (
        "query FetchPage { "
        f"{entity}(first: {page_size}, orderBy: id, orderDirection: asc, "
        f"where: {_where_literal(where)}{block_clause}) {{ {fields} }} "
        "}"
    )


def build_first_query(
    entity: str,
    fields: str,
    *,
    order_by: str,
    where: dict[str, Any] | None = None,
) -> str:
    where_clause = f", where: {_where_literal(where)}" if where else ""
    return (
        "query FetchFirst { "
        f"{entity}(first: 1, orderBy: {order_by}, orderDirection: asc{where_clause}) "
        f"{{ {fields} }} "
        "}"
    )


def first_record(
    client: GraphClient,
    *,
    entity: str,
    fields: str,
    order_by: str,
    where: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    data = client.query(build_first_query(entity, fields, order_by=order_by, where=where), {})
    rows = data.get(entity) or []
    return rows[0] if rows else None


def iter_paginate(
    client: GraphClient,
    *,
    entity: str,
    fields: str,
    base_where: dict[str, Any],
    page_size: int = PAGE_SIZE,
    block_number: int | None = None,
    progress: Callable[[int, str], None] | None = None,
    max_pages: int = 10_000,
) -> Iterator[dict[str, Any]]:
    row_count = 0
    last_id = ""
    pages = 0
    while True:
        pages += 1
        if pages > max_pages:
            raise RuntimeError(f"Graph pagination exceeded {max_pages} pages for {entity}")
        where = dict(base_where)
        if last_id:
            where["id_gt"] = last_id
        data = client.query(
            build_query(
                entity,
                fields,
                where,
                page_size=page_size,
                block_number=block_number,
            ),
            {},
        )
        page = data[entity]
        if not page:
            break
        for row in page:
            yield row
        row_count += len(page)
        last_id = page[-1]["id"]
        if progress is not None:
            progress(row_count, last_id)
        if len(page) < page_size:
            break
        if client.sleep_seconds:
            time.sleep(client.sleep_seconds)


def paginate(
    client: GraphClient,
    *,
    entity: str,
    fields: str,
    base_where: dict[str, Any],
    page_size: int = PAGE_SIZE,
    block_number: int | None = None,
    progress: Callable[[int, str], None] | None = None,
    max_pages: int = 10_000,
) -> list[dict[str, Any]]:
    """Compatibility collector over the canonical streaming paginator."""

    return list(
        iter_paginate(
            client,
            entity=entity,
            fields=fields,
            base_where=base_where,
            page_size=page_size,
            block_number=block_number,
            progress=progress,
            max_pages=max_pages,
        )
    )


def head_block(client: GraphClient) -> int | None:
    data = client.query("query Head { _meta { block { number } } }", {})
    try:
        return int(data["_meta"]["block"]["number"])
    except (KeyError, TypeError, ValueError):
        return None


def redact_keys(keys: Iterable[str]) -> list[str]:
    return [f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "***" for key in keys]
