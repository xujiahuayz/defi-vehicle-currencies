"""Dune ``dex.trades`` backend for sources without a usable swap subgraph."""

from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from ddvc.fetch.raw import write_jsonl_gz
from ddvc.fetch.sources import DexSource
from ddvc.paths import DATA_DIR

API = "https://api.dune.com/api/v1"


def dune_keys() -> list[str]:
    raw = os.getenv("DUNE_API_KEYS") or os.getenv("DUNE_API_KEY") or ""
    keys: list[str] = []
    seen: set[str] = set()
    for value in raw.replace("\n", ",").split(","):
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def dune_path(source: str, stream: str, day: dt.date) -> Path:
    return DATA_DIR / "raw" / "dune" / source / f"{source}_{stream}_{day:%Y%m%d}.jsonl.gz"


def dune_meta_path(source: str, day: dt.date) -> Path:
    return DATA_DIR / "raw" / "dune" / source / f"{source}_meta_{day:%Y%m%d}.json"


def _request(key: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={"X-Dune-API-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.status, json.loads(response.read().decode())


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    keys = dune_keys()
    if not keys:
        raise RuntimeError("No Dune API key set. Use DUNE_API_KEYS or DUNE_API_KEY.")
    last: tuple[int, Any] = (0, "no Dune key available")
    for key in keys:
        try:
            return _request(key, method, path, body)
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode()[:500]
            last = (exc.code, payload)
            if exc.code not in {401, 402, 403, 429}:
                break
    return last


def _query_state_path() -> Path:
    return DATA_DIR / "raw" / "dune" / "_query_state.json"


def _source_sql(source: DexSource) -> str:
    if not source.dune_project:
        raise ValueError(f"{source.name} is missing dune_project")
    version_filter = f"  AND version = '{source.dune_version}'\n" if source.dune_version else ""
    return f"""
SELECT
    blockchain,
    project,
    version,
    block_month,
    block_date,
    block_time,
    block_number,
    token_pair,
    token_bought_symbol,
    token_sold_symbol,
    token_bought_amount,
    token_sold_amount,
    token_bought_amount_raw,
    token_sold_amount_raw,
    amount_usd,
    token_bought_address,
    token_sold_address,
    taker,
    maker,
    project_contract_address AS pool,
    tx_hash,
    tx_from,
    tx_to,
    evt_index
FROM dex.trades
WHERE blockchain = 'ethereum'
  AND project = '{source.dune_project}'
{version_filter}  AND block_time >= TIMESTAMP '{{{{start}}}}'
  AND block_time <  TIMESTAMP '{{{{end}}}}'
ORDER BY block_time, evt_index
"""


def _query_id(source: DexSource) -> int:
    state_path = _query_state_path()
    state: dict[str, int] = {}
    if state_path.exists():
        state = json.loads(state_path.read_text())
    if source.name in state:
        return state[source.name]
    status, payload = _call(
        "POST",
        "/query",
        {
            "name": f"ddvc {source.name} dex.trades",
            "query_sql": _source_sql(source),
            "is_private": False,
            "parameters": [
                {"key": "start", "type": "text", "value": f"{source.genesis_date_utc} 00:00:00"},
                {"key": "end", "type": "text", "value": f"{source.genesis_date_utc + dt.timedelta(days=1)} 00:00:00"},
            ],
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Dune query create failed ({status}): {payload}")
    qid = int(payload["query_id"])
    state[source.name] = qid
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return qid


def _execute(query_id: int, start: dt.date, end: dt.date) -> str:
    status, payload = _call(
        "POST",
        f"/query/{query_id}/execute",
        {
            "query_parameters": {
                "start": f"{start} 00:00:00",
                "end": f"{end} 00:00:00",
            }
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Dune execute failed ({status}): {payload}")
    return str(payload["execution_id"])


def _await_rows(execution_id: str, *, poll_seconds: int = 3, max_polls: int = 240) -> list[dict[str, Any]]:
    for _ in range(max_polls):
        status, payload = _call("GET", f"/execution/{execution_id}/status")
        if status != 200:
            raise RuntimeError(f"Dune status failed ({status}): {payload}")
        state = payload.get("state")
        if state == "QUERY_STATE_COMPLETED":
            break
        if state == "QUERY_STATE_FAILED":
            raise RuntimeError(f"Dune execution failed: {payload}")
        time.sleep(poll_seconds)
    else:
        raise TimeoutError(f"Dune execution timed out: {execution_id}")

    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        status, payload = _call("GET", f"/execution/{execution_id}/results?limit={limit}&offset={offset}")
        if status != 200:
            raise RuntimeError(f"Dune results failed ({status}): {payload}")
        page = payload.get("result", {}).get("rows", [])
        rows.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return rows


def _date_from_row(row: dict[str, Any]) -> dt.date:
    value = str(row.get("block_date") or row.get("block_time", "")[:10])
    return dt.date.fromisoformat(value[:10])


def _block_values(rows: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for row in rows:
        try:
            values.append(int(row["block_number"]))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def _daily_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pool: dict[str, dict[str, Any]] = {}
    for row in rows:
        pool = str(row.get("pool") or "")
        if not pool:
            continue
        item = by_pool.setdefault(
            pool,
            {
                "pool": pool,
                "rows": 0,
                "amount_usd": 0.0,
                "first_block": None,
                "last_block": None,
            },
        )
        item["rows"] += 1
        try:
            item["amount_usd"] += float(row.get("amount_usd") or 0)
        except (TypeError, ValueError):
            pass
        block = row.get("block_number")
        try:
            block_int = int(block)
        except (TypeError, ValueError):
            continue
        item["first_block"] = block_int if item["first_block"] is None else min(item["first_block"], block_int)
        item["last_block"] = block_int if item["last_block"] is None else max(item["last_block"], block_int)
    return sorted(by_pool.values(), key=lambda row: row["pool"])


def fetch_dune_month(
    source: DexSource,
    month_start: dt.date,
    month_end: dt.date,
    *,
    streams: set[str] | None = None,
    skip_existing: bool = True,
) -> list[dict[str, Any]]:
    selected = streams or {"swaps", "daily"}
    days = [
        month_start + dt.timedelta(days=offset)
        for offset in range((month_end - month_start).days)
    ]
    if skip_existing and all(
        all(dune_path(source.name, stream, day).exists() for stream in selected)
        for day in days
    ):
        return [
            {"source": source.name, "backend": "dune", "day": day.isoformat(), "status": "skipped"}
            for day in days
        ]

    execution_id = _execute(_query_id(source), month_start, month_end)
    rows = _await_rows(execution_id)
    by_day: dict[dt.date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[_date_from_row(row)].append(row)

    metas: list[dict[str, Any]] = []
    for day in days:
        day_rows = by_day.get(day, [])
        stream_meta: dict[str, dict[str, Any]] = {}
        if "swaps" in selected:
            out = dune_path(source.name, "swaps", day)
            write_jsonl_gz(out, day_rows)
            stream_meta["swaps"] = {"path": str(out), "status": "fetched", "rows": len(day_rows)}
        if "daily" in selected:
            summary = _daily_summary(day_rows)
            out = dune_path(source.name, "daily", day)
            write_jsonl_gz(out, summary)
            stream_meta["daily"] = {"path": str(out), "status": "fetched", "rows": len(summary)}
        blocks = _block_values(day_rows)
        meta = {
            "source": source.name,
            "backend": "dune",
            "schema": source.schema,
            "dune_project": source.dune_project,
            "dune_version": source.dune_version,
            "day": day.isoformat(),
            "execution_id": execution_id,
            "source_genesis_block": source.genesis_block,
            "source_genesis_date_utc": source.genesis_date_utc.isoformat(),
            "min_block": min(blocks) if blocks else None,
            "max_block": max(blocks) if blocks else None,
            "streams": stream_meta,
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        meta_out = dune_meta_path(source.name, day)
        meta_out.parent.mkdir(parents=True, exist_ok=True)
        tmp = meta_out.with_name(meta_out.name + ".tmp")
        tmp.write_text(json.dumps(meta, indent=2, sort_keys=True))
        tmp.replace(meta_out)
        metas.append(meta)
    return metas


def month_ranges(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    ranges: list[tuple[dt.date, dt.date]] = []
    cur = start
    while cur < end:
        month_end = dt.date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1]) + dt.timedelta(days=1)
        stop = min(month_end, end)
        ranges.append((cur, stop))
        cur = stop
    return ranges


def stream_names_for_dune_source(source: DexSource) -> list[str]:
    return ["swaps", "daily"]
