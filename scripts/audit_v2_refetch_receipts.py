#!/usr/bin/env python3
"""Audit economically changed Uniswap V2 refetch rows against chain receipts."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

from eth_utils import keccak

from ddvc.amounts import human_to_raw
from ddvc.fetch.graph import GraphClient, graph_keys
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.quoter import rpc_post, rpc_urls
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.source_records import block_value


RAW_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v2"
DEFAULT_CACHE = DATA_DIR / "interim" / "provider_receipt_audit" / "uniswap_v2.jsonl"
SWAP_TOPIC = "0x" + keccak(text="Swap(address,uint256,uint256,uint256,uint256,address)").hex()


def transaction_id(row: dict) -> str:
    transaction = row.get("transaction")
    value = transaction.get("id") if isinstance(transaction, dict) else transaction
    return str(value or "").lower()


def economic_identity(row: dict) -> tuple[object, ...]:
    pair = row.get("pair") or {}
    token0 = pair.get("token0") or {}
    token1 = pair.get("token1") or {}
    return (
        transaction_id(row),
        str(pair.get("id") or "").lower(),
        str(token0.get("id") or "").lower(),
        str(token1.get("id") or "").lower(),
        str(row.get("timestamp") or ""),
        Decimal(str(row.get("amount0In") or "0")).normalize(),
        Decimal(str(row.get("amount1In") or "0")).normalize(),
        Decimal(str(row.get("amount0Out") or "0")).normalize(),
        Decimal(str(row.get("amount1Out") or "0")).normalize(),
    )


def load_rows(root: Path, day: str) -> list[dict]:
    path = root / f"uniswap_v2_swaps_{day}.jsonl.gz"
    with gzip.open(path, "rt") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def chain_order(row: dict) -> tuple[int, int] | None:
    block = block_value(row)
    try:
        log_index = int(row.get("logIndex"))
    except (TypeError, ValueError):
        return None
    if block is None or block <= 0 or log_index < 0:
        return None
    return block, log_index


def colliding_rows(rows: list[dict]) -> list[dict]:
    """Every distinct economic event sharing a provider chain-order key."""
    by_order: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        order = chain_order(row)
        if order is not None:
            by_order.setdefault(order, []).append(row)
    collisions: list[dict] = []
    for group in by_order.values():
        if len(group) > 1 and len(set(map(economic_identity, group))) > 1:
            collisions.extend(group)
    return collisions


def selected_difference(rows: list[dict], counts: Counter) -> list[dict]:
    selected = []
    for row in rows:
        identity = economic_identity(row)
        if counts[identity]:
            selected.append(row)
            counts[identity] -= 1
    return selected


def changed_rows(
    current_root: Path,
    baseline_root: Path,
    days: list[str],
) -> tuple[list[dict], list[dict], dict[str, int]]:
    current_changed: list[dict] = []
    baseline_changed: list[dict] = []
    decimals: dict[str, int] = {}
    for index, day in enumerate(days, 1):
        current = load_rows(current_root, day)
        baseline = load_rows(baseline_root, day)
        for row in current:
            pair = row.get("pair") or {}
            for side in ("token0", "token1"):
                token = pair.get(side) or {}
                if token.get("id") and token.get("decimals") is not None:
                    decimals[str(token["id"]).lower()] = int(token["decimals"])
        current_counts = Counter(map(economic_identity, current))
        baseline_counts = Counter(map(economic_identity, baseline))
        current_changed.extend(selected_difference(current, current_counts - baseline_counts))
        baseline_changed.extend(selected_difference(baseline, baseline_counts - current_counts))
        print(
            f"diff {index}/{len(days)} current={len(current_changed):,} "
            f"baseline={len(baseline_changed):,}",
            flush=True,
        )
    return current_changed, baseline_changed, decimals


def read_receipt_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    receipts = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row.get("receipt"), dict):
                receipts[str(row.get("tx") or "").lower()] = row["receipt"]
    return receipts


def write_receipt_cache(path: Path, receipts: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for tx_hash in sorted(receipts):
                handle.write(
                    json.dumps(
                        {"tx": tx_hash, "receipt": receipts[tx_hash]},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )


def fetch_missing_receipts(
    tx_hashes: list[str],
    receipts: dict[str, dict],
    *,
    batch_size: int,
) -> list[str]:
    pending = [tx_hash for tx_hash in tx_hashes if tx_hash not in receipts]
    maximum_rounds = max(2, len(rpc_urls()) * 2)
    for attempt in range(maximum_rounds):
        if not pending:
            break
        unresolved: list[str] = []
        for start in range(0, len(pending), batch_size):
            batch_hashes = pending[start : start + batch_size]
            payload = [
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                }
                for index, tx_hash in enumerate(batch_hashes)
            ]
            try:
                response = rpc_post(payload, timeout=20, retries=2)
            except Exception:
                unresolved.extend(batch_hashes)
                continue
            by_id = {
                int(item["id"]): item
                for item in response
                if isinstance(item, dict) and item.get("id") is not None
            } if isinstance(response, list) else {}
            for index, tx_hash in enumerate(batch_hashes):
                result = by_id.get(index, {}).get("result")
                if isinstance(result, dict):
                    receipts[tx_hash] = result
                else:
                    unresolved.append(tx_hash)
        pending = sorted(set(unresolved))
        print(
            f"receipts round {attempt + 1}/{maximum_rounds}: "
            f"resolved={len(tx_hashes) - len(pending):,}/{len(tx_hashes):,}",
            flush=True,
        )
        if pending:
            time.sleep(1)
    return pending


def receipt_swap_log_index(
    row: dict,
    receipt: dict | None,
    decimals: dict[str, int],
) -> int | None:
    if not isinstance(receipt, dict):
        return None
    pair = row.get("pair") or {}
    token0 = pair.get("token0") or {}
    token1 = pair.get("token1") or {}
    decimals0 = decimals.get(str(token0.get("id") or "").lower())
    decimals1 = decimals.get(str(token1.get("id") or "").lower())
    if decimals0 is None or decimals1 is None:
        return None
    target = (
        human_to_raw(row.get("amount0In") or "0", decimals0),
        human_to_raw(row.get("amount1In") or "0", decimals1),
        human_to_raw(row.get("amount0Out") or "0", decimals0),
        human_to_raw(row.get("amount1Out") or "0", decimals1),
    )
    if any(value is None for value in target):
        return None
    expected_amounts = tuple(int(value) for value in target)
    pool = str(pair.get("id") or "").lower()
    matches: list[int] = []
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if (
            str(log.get("address") or "").lower() != pool
            or not topics
            or str(topics[0]).lower() != SWAP_TOPIC.lower()
        ):
            continue
        data = str(log.get("data") or "").removeprefix("0x")
        if len(data) < 256:
            continue
        amounts = tuple(int(data[offset : offset + 64], 16) for offset in range(0, 256, 64))
        log_index = int(str(log.get("logIndex") or "0x0"), 0)
        if amounts == expected_amounts:
            matches.append(log_index)
    return matches[0] if len(matches) == 1 else None


def receipt_match(row: dict, receipt: dict | None, decimals: dict[str, int]) -> bool | None:
    if not isinstance(receipt, dict):
        return None
    pair = row.get("pair") or {}
    token0 = pair.get("token0") or {}
    token1 = pair.get("token1") or {}
    if (
        str(token0.get("id") or "").lower() not in decimals
        or str(token1.get("id") or "").lower() not in decimals
    ):
        return None
    resolved = receipt_swap_log_index(row, receipt, decimals)
    if resolved is None:
        return False
    try:
        return resolved == int(row.get("logIndex"))
    except (TypeError, ValueError):
        return False


def exact_provider_rows(rows: list[dict]) -> dict[str, dict]:
    """Fetch entities by id and require agreement across live provider routes."""
    ids = sorted({str(row.get("id") or "") for row in rows if row.get("id")})
    if not ids:
        return {}
    source = get_source("uniswap_v2")
    entity = next(
        item for item in get_schema(source.schema).entities if item.stream == "swaps"
    )
    query = (
        "query ExactProviderRows($ids: [ID!]!) { "
        f"{entity.entity}(where: {{ id_in: $ids }}) {{ {entity.fields} }} "
        "}"
    )
    answers: list[dict[str, dict]] = []
    for key in graph_keys():
        try:
            data = GraphClient(
                source.subgraph_id,
                [key],
                graph_path=source.graph_path,
                max_transient_retries=1,
                response_deadline_seconds=30,
            ).query(query, {"ids": ids})
        except Exception:
            continue
        fetched = {
            str(row.get("id") or ""): row
            for row in data.get(entity.entity) or []
            if row.get("id")
        }
        if set(fetched) == set(ids):
            answers.append(fetched)
    if len(answers) < 2:
        raise RuntimeError("fewer than two provider routes returned every collision row")
    consensus: dict[str, dict] = {}
    for event_id in ids:
        variants = {
            json.dumps(answer[event_id], sort_keys=True, separators=(",", ":"))
            for answer in answers
        }
        if len(variants) != 1:
            raise RuntimeError(
                f"live provider routes disagree on collision row {event_id}"
            )
        consensus[event_id] = json.loads(variants.pop())
    print(
        f"provider consensus: {len(answers)} live routes, {len(consensus)} collision rows",
        flush=True,
    )
    return consensus


def repair_collision_rows(
    root: Path,
    day: str,
    collisions: list[dict],
    replacements: dict[str, dict],
) -> list[dict[str, object]]:
    """Install exact provider rows while retaining the displaced raw capture."""
    path = root / f"uniswap_v2_swaps_{day}.jsonl.gz"
    rows = load_rows(root, day)
    collision_ids = {str(row.get("id") or "") for row in collisions}
    if not collision_ids or collision_ids != set(replacements):
        raise ValueError("collision replacement ids do not match the detected collision set")
    original_by_id = {
        str(row.get("id") or ""): row
        for row in rows
        if str(row.get("id") or "") in collision_ids
    }
    if set(original_by_id) != collision_ids:
        raise ValueError("a collision entity is not unique in the raw day")
    repairs: list[dict[str, object]] = []
    for event_id in sorted(collision_ids):
        original = original_by_id[event_id]
        replacement = replacements[event_id]
        if economic_identity(original) != economic_identity(replacement):
            raise ValueError(f"provider replacement changes economic payload: {event_id}")
        if chain_order(original) == chain_order(replacement):
            continue
        repairs.append(
            {
                "event_id": event_id,
                "transaction": transaction_id(original),
                "block_number": block_value(original),
                "provider_log_index_before": int(original.get("logIndex")),
                "provider_log_index_after": int(replacement.get("logIndex")),
            }
        )
    if not repairs:
        return []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    history = root / ".superseded" / day / f"uniswap_v2_swaps_{day}.{digest[:16]}.jsonl.gz"
    if not history.exists():
        with atomic_output(history) as temporary:
            shutil.copyfile(path, temporary)
    installed = [replacements.get(str(row.get("id") or ""), row) for row in rows]
    write_jsonl_gz(path, installed)
    metadata_path = root / f"uniswap_v2_meta_{day}.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {"source": "uniswap_v2", "day": f"{day[:4]}-{day[4:6]}-{day[6:]}"}
    ledger = list(metadata.get("receipt_order_repairs") or [])
    known = {(str(item.get("event_id")), item.get("provider_log_index_after")) for item in ledger}
    ledger.extend(
        repair
        for repair in repairs
        if (str(repair["event_id"]), repair["provider_log_index_after"]) not in known
    )
    metadata["receipt_order_repairs"] = ledger
    metadata["streams"] = dict(metadata.get("streams") or {})
    metadata["streams"].setdefault("swaps", {})["status"] = "fetched+receipt-order-reconciled"
    write_json(metadata_path, metadata)
    return repairs


def parse_days(path: Path) -> list[str]:
    return sorted(
        {
            line.strip().replace("-", "")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--days-file", type=Path, required=True)
    parser.add_argument("--current-dir", type=Path, default=RAW_ROOT)
    parser.add_argument("--receipt-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument(
        "--repair-order-collisions",
        action="store_true",
        help="replace only receipt-verified colliding entities with exact current-provider rows",
    )
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        parser.error("--batch-size must be between 1 and 100")
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="raw repair receipt audit"):
        return run_audit(args)


def run_audit(args: argparse.Namespace) -> int:
    days = parse_days(args.days_file)
    current, baseline, decimals = changed_rows(
        args.current_dir,
        args.baseline_dir,
        days,
    )
    collisions_by_day = {
        day: found
        for day in days
        if (found := colliding_rows(load_rows(args.current_dir, day)))
    }
    collision_rows = [row for rows in collisions_by_day.values() for row in rows]
    receipts = read_receipt_cache(args.receipt_cache)
    tx_hashes = sorted({transaction_id(row) for row in [*current, *collision_rows]})
    unresolved = fetch_missing_receipts(
        tx_hashes,
        receipts,
        batch_size=args.batch_size,
    )
    write_receipt_cache(args.receipt_cache, receipts)
    collision_receipt_logs = {
        str(row.get("id") or ""): receipt_swap_log_index(
            row,
            receipts.get(transaction_id(row)),
            decimals,
        )
        for row in collision_rows
    }
    repaired: list[dict[str, object]] = []
    if args.repair_order_collisions and collision_rows:
        if any(value is None for value in collision_receipt_logs.values()):
            raise RuntimeError("a colliding provider row has no unique receipt event")
        replacements = exact_provider_rows(collision_rows)
        for row in collision_rows:
            event_id = str(row.get("id") or "")
            replacement = replacements[event_id]
            if receipt_match(
                replacement,
                receipts.get(transaction_id(row)),
                decimals,
            ) is not True:
                raise RuntimeError(f"exact provider replacement does not match receipt: {event_id}")
        for day, day_collisions in collisions_by_day.items():
            day_ids = {str(row.get("id") or "") for row in day_collisions}
            repaired.extend(
                repair_collision_rows(
                    args.current_dir,
                    day,
                    day_collisions,
                    {event_id: replacements[event_id] for event_id in day_ids},
                )
            )
        current, baseline, decimals = changed_rows(
            args.current_dir,
            args.baseline_dir,
            days,
        )
        collisions_by_day = {
            day: found
            for day in days
            if (found := colliding_rows(load_rows(args.current_dir, day)))
        }
        collision_rows = [row for rows in collisions_by_day.values() for row in rows]
    current_results = [receipt_match(row, receipts.get(transaction_id(row)), decimals) for row in current]
    baseline_results = [receipt_match(row, receipts.get(transaction_id(row)), decimals) for row in baseline]
    summary = {
        "current_changed_rows": len(current),
        "current_auditable_rows": sum(result is not None for result in current_results),
        "current_exact_receipt_matches": sum(result is True for result in current_results),
        "baseline_changed_rows": len(baseline),
        "baseline_auditable_rows": sum(result is not None for result in baseline_results),
        "baseline_exact_receipt_matches": sum(result is True for result in baseline_results),
        "unique_current_transactions": len(tx_hashes),
        "unresolved_receipts": len(unresolved),
        "current_chain_order_collision_rows": len(collision_rows),
        "repaired_chain_order_rows": len(repaired),
        "current_mismatch_transactions": sorted(
            {
                transaction_id(row)
                for row, result in zip(current, current_results, strict=True)
                if result is not True
            }
        )[:20],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return int(
        bool(unresolved)
        or bool(collision_rows)
        or summary["current_auditable_rows"] != summary["current_changed_rows"]
        or summary["current_exact_receipt_matches"] != summary["current_changed_rows"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
