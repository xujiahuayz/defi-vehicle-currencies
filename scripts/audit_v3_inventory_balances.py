#!/usr/bin/env python3
"""Validate event-replayed V3 inventories against historical token custody balances."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.fetch.raw import write_json
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import DATA_DIR, SHARED_RUNTIME_DIR, TOKEN_PRICE_DAILY_PANEL
from ddvc.provenance import cache_key, require_current_artifacts, stamp
from ddvc.quoter import rpc_post
from ddvc.runtime import atomic_output, exclusive_job, interruptible_thread_pool
from ddvc.v3_inventory import balance_of_calldata, decode_balance_of_result


INVENTORY_PANEL = DATA_DIR / "processed" / "v3_pool_inventory_daily.parquet"
SAMPLE = DATA_DIR / "processed" / "v3_inventory_balance_audit_sample.parquet"
OUT = DATA_DIR / "processed" / "v3_inventory_balance_validation.parquet"
RAW_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_balance_audit"
CACHE_ROOT = DATA_DIR / "processed" / "_v3_inventory_balance_validation_shards"
LOCK = SHARED_RUNTIME_DIR / "v3-inventory-balance-audit.lock"
VALUE_MASS_SHARE = 0.99
MIN_VALUE_POOLS_PER_AUDIT_DAY = 50
TAIL_POOLS_PER_AUDIT_DAY = 50
DEFAULT_BATCH_SIZE = 20
MAX_BATCH_ATTEMPTS = 12
CODE_SOURCES = [
    "scripts/audit_v3_inventory_balances.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/panel_assembly.py",
    "src/ddvc/quoter.py",
    "src/ddvc/runtime.py",
    "src/ddvc/v3_inventory.py",
]


@dataclass(frozen=True)
class BalanceCall:
    job_id: str
    day: str
    block: int
    pool: str
    token: str
    side: int
    expected_raw: str
    sample_reason: str

    def request(self, rpc_id: int) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "eth_call",
            "params": [
                {"to": self.token, "data": balance_of_calldata(self.pool)},
                hex(self.block),
            ],
        }


VALIDATION_SCHEMA = pa.schema(
    [
        pa.field("day", pa.string(), nullable=False),
        pa.field("day_end_block", pa.int64(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token_address", pa.string(), nullable=False),
        pa.field("token_side", pa.int8(), nullable=False),
        pa.field("expected_balance_raw", pa.string(), nullable=False),
        pa.field("observed_balance_raw", pa.string(), nullable=False),
        pa.field("signed_difference_raw", pa.string(), nullable=False),
        pa.field("exact_match", pa.bool_(), nullable=False),
        pa.field("sample_reason", pa.string(), nullable=False),
        pa.field("raw_evidence", pa.string(), nullable=False),
        pa.field("validation_status", pa.string(), nullable=False),
    ]
)


def audit_sample_table(
    inventory_path: Path = INVENTORY_PANEL,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
) -> pa.Table:
    """Select edge, value-mass, and deterministic-tail validation pool-days."""

    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=2")
    query = """
        WITH base AS (
            SELECT venue, day, day_end_block, pool,
                token0_address, token0_symbol, token0_decimals,
                token1_address, token1_symbol, token1_decimals,
                balance0_raw, balance1_raw, balance0_units, balance1_units,
                negative_inventory, replay_arithmetic_valid, state_generation,
                quantity_kind, custody_validation_status, ownership_validation_status
            FROM read_parquet(?)
        ), edge_ranked AS (
            SELECT day, pool,
                row_number() OVER (PARTITION BY pool ORDER BY day) AS first_rank,
                row_number() OVER (PARTITION BY pool ORDER BY day DESC) AS final_rank
            FROM base
        ), edge_reasons AS (
            SELECT day, pool, 'first_observed_pool_cut' AS reason
            FROM edge_ranked WHERE first_rank=1
            UNION ALL
            SELECT day, pool, 'final_observed_pool_cut' AS reason
            FROM edge_ranked WHERE final_rank=1
        ), audit_days AS (
            SELECT max(day) AS day FROM base GROUP BY substr(day, 1, 6)
        ), audit_valued AS (
            SELECT b.day, b.pool,
                CASE WHEN p0.price_usd IS NOT NULL AND p1.price_usd IS NOT NULL
                    AND b.replay_arithmetic_valid
                    THEN b.balance0_units*p0.price_usd + b.balance1_units*p1.price_usd
                    ELSE NULL END AS inventory_value_usd
            FROM base b
            JOIN audit_days d USING (day)
            LEFT JOIN read_parquet(?) p0
                ON p0.day=b.day AND p0.token=b.token0_address
            LEFT JOIN read_parquet(?) p1
                ON p1.day=b.day AND p1.token=b.token1_address
        ), value_ranked AS (
            SELECT *, row_number() OVER (
                    PARTITION BY day ORDER BY inventory_value_usd DESC, pool
                ) AS value_rank,
                sum(inventory_value_usd) OVER (PARTITION BY day) AS total_value_usd,
                sum(inventory_value_usd) OVER (
                    PARTITION BY day ORDER BY inventory_value_usd DESC, pool
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) - inventory_value_usd AS value_before_usd
            FROM audit_valued
            WHERE inventory_value_usd IS NOT NULL AND inventory_value_usd>=0
        ), value_reasons AS (
            SELECT day, pool, 'audit_date_value_mass' AS reason
            FROM value_ranked
            WHERE value_rank<=? OR value_before_usd < ?*total_value_usd
        ), tail_ranked AS (
            SELECT a.day, a.pool, row_number() OVER (
                    PARTITION BY a.day ORDER BY hash(a.day || ':' || a.pool), a.pool
                ) AS tail_rank
            FROM audit_valued a
            LEFT JOIN value_reasons v USING (day, pool)
            WHERE v.pool IS NULL
        ), tail_reasons AS (
            SELECT day, pool, 'audit_date_deterministic_tail' AS reason
            FROM tail_ranked WHERE tail_rank<=?
        ), reasons AS (
            SELECT * FROM edge_reasons
            UNION ALL SELECT * FROM value_reasons
            UNION ALL SELECT * FROM tail_reasons
        ), selected AS (
            SELECT day, pool, string_agg(reason, ',' ORDER BY reason) AS sample_reason
            FROM reasons GROUP BY day, pool
        )
        SELECT b.*, s.sample_reason,
            CASE WHEN p0.price_usd IS NOT NULL AND p1.price_usd IS NOT NULL
                AND b.replay_arithmetic_valid
                THEN b.balance0_units*p0.price_usd + b.balance1_units*p1.price_usd
                ELSE NULL END AS inventory_value_usd,
            p0.price_usd IS NOT NULL AND p1.price_usd IS NOT NULL
                AS full_valuation_support
        FROM base b
        JOIN selected s USING (day, pool)
        LEFT JOIN read_parquet(?) p0
            ON p0.day=b.day AND p0.token=b.token0_address
        LEFT JOIN read_parquet(?) p1
            ON p1.day=b.day AND p1.token=b.token1_address
        ORDER BY b.day, b.pool
    """
    try:
        table = con.execute(
            query,
            [
                str(inventory_path),
                str(price_path),
                str(price_path),
                MIN_VALUE_POOLS_PER_AUDIT_DAY,
                VALUE_MASS_SHARE,
                TAIL_POOLS_PER_AUDIT_DAY,
                str(price_path),
                str(price_path),
            ],
        ).to_arrow_table()
    finally:
        con.close()
    return table


def build_audit_sample(
    inventory_path: Path = INVENTORY_PANEL,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    output: Path = SAMPLE,
) -> int:
    """Lock the validation sample before making any historical RPC request."""

    require_current_artifacts(
        [inventory_path, price_path],
        consumer="V3 historical custody-balance audit sample",
    )
    table = audit_sample_table(inventory_path, price_path)
    if table.num_rows == 0:
        raise RuntimeError("V3 custody-balance audit sample is empty")
    keys = table.select(["day", "pool"]).to_pandas()
    if keys.duplicated().any():
        raise RuntimeError("V3 custody-balance audit sample has duplicate pool-days")
    with atomic_output(output) as temporary:
        pq.write_table(table, temporary, compression="snappy")
    stamp(
        output,
        code_sources=CODE_SOURCES,
        inputs=[inventory_path, price_path],
        rows=table.num_rows,
        notes=(
            "precommitted first/final pool cuts plus one audit date per calendar month; "
            f"value mass={VALUE_MASS_SHARE:.1%}; minimum value pools/day="
            f"{MIN_VALUE_POOLS_PER_AUDIT_DAY}; deterministic tail/day="
            f"{TAIL_POOLS_PER_AUDIT_DAY}; audit dates are validation support, not horizons"
        ),
    )
    return table.num_rows


def balance_calls(sample_path: Path = SAMPLE) -> list[BalanceCall]:
    require_current_artifacts([sample_path], consumer="V3 historical custody-balance audit")
    frame = pq.read_table(
        sample_path,
        columns=[
            "day",
            "day_end_block",
            "pool",
            "token0_address",
            "token1_address",
            "balance0_raw",
            "balance1_raw",
            "sample_reason",
        ],
    ).to_pandas()
    calls: list[BalanceCall] = []
    for row in frame.itertuples(index=False):
        for side in (0, 1):
            calls.append(
                BalanceCall(
                    job_id=f"{row.day}:{row.pool}:{side}",
                    day=str(row.day),
                    block=int(row.day_end_block),
                    pool=str(row.pool),
                    token=str(getattr(row, f"token{side}_address")),
                    side=side,
                    expected_raw=str(getattr(row, f"balance{side}_raw")),
                    sample_reason=str(row.sample_reason),
                )
            )
    if len({call.job_id for call in calls}) != len(calls):
        raise RuntimeError("V3 custody-balance audit calls are not unique")
    return calls


def _batch_identity(calls: list[BalanceCall]) -> str:
    body = "\n".join(call.job_id for call in calls).encode()
    return hashlib.sha256(body).hexdigest()


def _batch_path(root: Path, index: int) -> Path:
    return root / f"batch_{index:06d}.json"


def _completed_batch(
    path: Path, *, generation: str, calls: list[BalanceCall]
) -> bool:
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    results = record.get("results") or []
    return bool(
        record.get("status") == "complete"
        and record.get("generation") == generation
        and record.get("batch_identity") == _batch_identity(calls)
        and len(results) == len(calls)
        and all(item.get("observed_balance_raw") is not None for item in results)
    )


def _singleton_response(request: dict[str, object]) -> dict[str, object]:
    response = rpc_post(
        request,
        timeout=45,
        retries=3,
        retry_json_errors=True,
    )
    if not isinstance(response, dict) or response.get("result") is None:
        raise RuntimeError("historical balanceOf call lacks a JSON-RPC result")
    return response


def _fetch_batch(
    index: int,
    calls: list[BalanceCall],
    *,
    root: Path,
    generation: str,
) -> int:
    path = _batch_path(root, index)
    if _completed_batch(path, generation=generation, calls=calls):
        return len(calls)
    requests = [call.request(rpc_id) for rpc_id, call in enumerate(calls)]
    response = rpc_post(requests, timeout=60, retries=3)
    records = response if isinstance(response, list) else [response]
    by_id = {
        int(item["id"]): item
        for item in records
        if isinstance(item, dict) and item.get("id") is not None
    }
    results: list[dict[str, object]] = []
    for rpc_id, (call, request) in enumerate(zip(calls, requests, strict=True)):
        item = by_id.get(rpc_id)
        if not isinstance(item, dict) or item.get("result") is None:
            item = _singleton_response(request)
        observed = decode_balance_of_result(item.get("result"))
        expected = int(call.expected_raw)
        results.append(
            {
                "job_id": call.job_id,
                "day": call.day,
                "day_end_block": call.block,
                "pool": call.pool,
                "token_address": call.token,
                "token_side": call.side,
                "expected_balance_raw": call.expected_raw,
                "observed_balance_raw": str(observed),
                "signed_difference_raw": str(observed - expected),
                "exact_match": observed == expected,
                "sample_reason": call.sample_reason,
                "request": request,
                "response": item,
            }
        )
    write_json(
        path,
        {
            "status": "complete",
            "generation": generation,
            "batch_identity": _batch_identity(calls),
            "results": results,
        },
    )
    return len(calls)


def fetch_balances(
    calls: list[BalanceCall],
    *,
    workers: int,
    batch_size: int,
    max_attempts: int = MAX_BATCH_ATTEMPTS,
) -> tuple[Path, int]:
    if batch_size <= 0 or max_attempts <= 0:
        raise ValueError("balance audit batch size and attempts must be positive")
    generation = cache_key(CODE_SOURCES, inputs=[SAMPLE])
    root = RAW_ROOT / f"engine_{generation}"
    root.mkdir(parents=True, exist_ok=True)
    batches = [calls[index:index + batch_size] for index in range(0, len(calls), batch_size)]
    queue = deque((index, batch, 1) for index, batch in enumerate(batches))
    failures: list[tuple[int, str]] = []
    completed = 0
    with interruptible_thread_pool(max_workers=max(1, min(workers, 4))) as executor:
        futures = {}
        while queue or futures:
            while queue and len(futures) < max(1, min(workers, 4)):
                index, batch, attempt = queue.popleft()
                if _completed_batch(
                    _batch_path(root, index), generation=generation, calls=batch
                ):
                    completed += len(batch)
                    continue
                future = executor.submit(
                    _fetch_batch,
                    index,
                    batch,
                    root=root,
                    generation=generation,
                )
                futures[future] = (index, batch, attempt)
            if not futures:
                continue
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                index, batch, attempt = futures.pop(future)
                try:
                    completed += int(future.result())
                except Exception as error:
                    if attempt < max_attempts:
                        queue.append((index, batch, attempt + 1))
                    else:
                        failures.append((index, str(error)))
                if completed and (
                    completed % (batch_size * 100) == 0 or completed == len(calls)
                ):
                    print(
                        f"  V3 balanceOf audit [{completed:,}/{len(calls):,}]; "
                        f"queued_batches={len(queue):,}; terminal_failures={len(failures):,}",
                        flush=True,
                    )
    if failures:
        preview = ", ".join(f"batch {index}: {error}" for index, error in failures[:3])
        raise RuntimeError(
            f"historical balanceOf audit exhausted retries for {len(failures):,} "
            f"batches; first={preview}"
        )
    return root, len(batches)


def assemble_validation(
    calls: list[BalanceCall],
    raw_root: Path,
    batch_count: int,
    *,
    batch_size: int,
    output: Path = OUT,
) -> int:
    generation = raw_root.name.removeprefix("engine_")
    shard_root = CACHE_ROOT / f"engine_{generation}"
    shard_root.mkdir(parents=True, exist_ok=True)
    shards: list[Path] = []
    for index in range(batch_count):
        batch = calls[index * batch_size:(index + 1) * batch_size]
        raw_path = _batch_path(raw_root, index)
        if not _completed_batch(raw_path, generation=generation, calls=batch):
            raise RuntimeError(f"missing or invalid V3 balance audit raw batch {index}")
        record = json.loads(raw_path.read_text())
        results = record.get("results") or []
        if record.get("generation") != generation or not results:
            raise RuntimeError(f"invalid V3 balance audit raw batch {index}")
        rows = []
        evidence = str(raw_path.relative_to(DATA_DIR.parent))
        for item in results:
            rows.append(
                {
                    **{key: item[key] for key in (
                        "day",
                        "day_end_block",
                        "pool",
                        "token_address",
                        "token_side",
                        "expected_balance_raw",
                        "observed_balance_raw",
                        "signed_difference_raw",
                        "exact_match",
                        "sample_reason",
                    )},
                    "raw_evidence": evidence,
                    "validation_status": (
                        "exact_historical_balance_match"
                        if item["exact_match"]
                        else "historical_custody_balance_mismatch"
                    ),
                }
            )
        shard = shard_root / f"batch_{index:06d}.parquet"
        table = pa.Table.from_pylist(rows, schema=VALIDATION_SCHEMA)
        with atomic_output(shard) as temporary:
            pq.write_table(table, temporary, compression="snappy")
        shards.append(shard)
    assembled = assemble_parquet_shards(
        shards,
        output,
        unique_keys=("day", "pool", "token_side"),
    )
    if assembled.rows != len(calls):
        raise RuntimeError(
            f"V3 balance validation rows differ from calls: {assembled.rows:,}!={len(calls):,}"
        )
    stamp(
        output,
        code_sources=CODE_SOURCES,
        inputs=[SAMPLE, raw_root],
        rows=assembled.rows,
        notes=(
            "historical ERC20 custody balance reconciliation; direct donations and rebasing "
            "remain discrepancies and do not overwrite claim-associated event replay"
        ),
    )
    return assembled.rows


def summarize(output: Path = OUT) -> dict[str, int]:
    con = duckdb.connect()
    try:
        row = con.execute(
            """
            WITH calls AS (SELECT * FROM read_parquet(?)),
            pool_day AS (
                SELECT day, pool, bool_and(exact_match) AS exact_match
                FROM calls GROUP BY day, pool
            )
            SELECT (SELECT count(*) FROM calls),
                (SELECT count(*) FROM calls WHERE exact_match),
                (SELECT count(*) FROM pool_day),
                (SELECT count(*) FROM pool_day WHERE exact_match)
            """,
            [str(output)],
        ).fetchone()
    finally:
        con.close()
    return {
        "calls": int(row[0]),
        "exact_calls": int(row[1]),
        "pool_days": int(row[2]),
        "exact_pool_days": int(row[3]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    with exclusive_job(LOCK, job="V3 historical custody-balance audit"):
        sample_rows = build_audit_sample()
        print(f"locked V3 balance audit sample: {sample_rows:,} pool-days", flush=True)
        if args.sample_only:
            return 0
        calls = balance_calls()
        raw_root, batches = fetch_balances(
            calls,
            workers=args.workers,
            batch_size=args.batch_size,
        )
        rows = assemble_validation(
            calls,
            raw_root,
            batches,
            batch_size=args.batch_size,
        )
        stats = summarize()
    print(
        f"wrote {rows:,} validation calls; exact={stats['exact_calls']:,}/"
        f"{stats['calls']:,}; exact_pool_days={stats['exact_pool_days']:,}/"
        f"{stats['pool_days']:,}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
