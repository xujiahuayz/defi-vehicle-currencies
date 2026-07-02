"""The Graph gateway client for raw, restartable fetches."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ddvc.http import DEFAULT_USER_AGENT
from ddvc.paths import REPO_ROOT

GRAPH_ENDPOINT = "https://gateway.thegraph.com/api/{key}/{graph_path}/{subgraph_id}"
PAGE_SIZE = 1000


def graph_keys() -> list[str]:
    """Read an ordered, de-duplicated Graph API-key pool from the environment."""
    raw = os.getenv("GRAPH_API_KEYS") or os.getenv("GRAPH_API_KEY") or _read_dotenv_keys()
    keys: list[str] = []
    seen: set[str] = set()
    for value in re.split(r"[,\n]", raw):
        key = value.strip()
        if not key or key in {"your_key_here", "YOUR_API_KEY", "[api-key]"} or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _read_dotenv_keys() -> str:
    """Small .env reader so fetches work without adding a new dependency."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    values: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values.get("GRAPH_API_KEYS") or values.get("GRAPH_API_KEY") or ""


@dataclass
class GraphClient:
    subgraph_id: str
    keys: list[str]
    graph_path: str = "subgraphs/id"
    sleep_seconds: float = 0.1

    def __post_init__(self) -> None:
        if not self.keys:
            raise RuntimeError("No Graph API key set. Use GRAPH_API_KEYS or GRAPH_API_KEY.")
        import requests

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self._key_index = 0

    @property
    def url(self) -> str:
        return GRAPH_ENDPOINT.format(
            key=self.keys[self._key_index],
            graph_path=self.graph_path,
            subgraph_id=self.subgraph_id,
        )

    def _rotate(self) -> bool:
        if self._key_index + 1 >= len(self.keys):
            return False
        self._key_index += 1
        return True

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        while True:
            response = self.session.post(
                self.url,
                json={"query": query, "variables": variables},
                timeout=90,
            )
            if response.status_code in {401, 403, 429} and self._rotate():
                continue
            response.raise_for_status()
            payload = response.json()
            errors = payload.get("errors") or []
            if errors:
                text = json.dumps(errors)
                if "payment required" in text.lower() and self._rotate():
                    continue
                raise RuntimeError(text)
            return payload["data"]


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


def build_query(entity: str, fields: str, where: dict[str, Any]) -> str:
    return (
        "query FetchPage { "
        f"{entity}(first: {PAGE_SIZE}, orderBy: id, orderDirection: asc, "
        f"where: {_where_literal(where)}) {{ {fields} }} "
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


def paginate(
    client: GraphClient,
    *,
    entity: str,
    fields: str,
    base_where: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_id = ""
    while True:
        where = dict(base_where)
        if last_id:
            where["id_gt"] = last_id
        data = client.query(build_query(entity, fields, where), {})
        page = data[entity]
        if not page:
            break
        rows.extend(page)
        last_id = page[-1]["id"]
        if len(page) < PAGE_SIZE:
            break
        if client.sleep_seconds:
            time.sleep(client.sleep_seconds)
    return rows


def head_block(client: GraphClient) -> int | None:
    data = client.query("query Head { _meta { block { number } } }", {})
    try:
        return int(data["_meta"]["block"]["number"])
    except (KeyError, TypeError, ValueError):
        return None


def redact_keys(keys: Iterable[str]) -> list[str]:
    return [f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "***" for key in keys]
