#!/usr/bin/env python3
"""Fetch exact, block-bound receipt gas prices and RPC evidence for every gross route."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from pathlib import Path
from typing import Callable

import pandas as pd

from ddvc.data_release import require_node_d_release
from ddvc.ethereum_blocks import (
    BLOCK_HEADER_CACHE,
    block_header_is_current,
    fetch_block_header,
    write_block_header_snapshot,
)
from ddvc.ethereum_receipts import (
    RECEIPT_CACHE,
    fetch_receipt,
    receipt_is_current,
    write_receipt_snapshot,
)
from ddvc.paths import DATA_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.provenance import require_current_artifacts
from ddvc.quoter import RPC_EVIDENCE_FIELDS, rpc_post
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_thread_pool
from ddvc.tables import write_panel


GROSS_PANEL = DATA_DIR / "processed" / "counterfactual_dominance_gross.parquet"
OUT_PANEL = DATA_DIR / "processed" / "route_transaction_gas.parquet"
RECEIPT_EVIDENCE = DATA_DIR / "empirical" / "route_transaction_gas_receipts.jsonl"
BLOCK_HEADER_EVIDENCE = DATA_DIR / "empirical" / "route_transaction_gas_blocks.jsonl"
CACHE = RECEIPT_CACHE
HEADER_CACHE = BLOCK_HEADER_CACHE
LOCK = SHARED_RUNTIME_DIR / "route-transaction-gas.lock"
CODE_SOURCES = [
    "scripts/process/build_route_transaction_gas.py",
    "src/ddvc/ethereum_blocks.py",
    "src/ddvc/ethereum_receipts.py",
    "src/ddvc/quoter.py",
    "src/ddvc/runtime.py",
]


def route_receipt_requests(path: Path = GROSS_PANEL) -> pd.DataFrame:
    if not path.is_file():
        raise RuntimeError("gross counterfactual route panel has not been released")
    requests = pd.read_parquet(path, columns=["tx", "block"]).rename(
        columns={"tx": "tx_hash", "block": "block_number"}
    )
    requests["tx_hash"] = requests["tx_hash"].astype(str).str.lower()
    requests["block_number"] = pd.to_numeric(
        requests["block_number"], errors="raise"
    ).astype("int64")
    if requests.empty or requests["tx_hash"].eq("").any():
        raise RuntimeError("gross counterfactual routes contain no usable transaction identities")
    duplicated = requests["tx_hash"].duplicated(keep=False)
    if duplicated.any():
        conflicts = requests[duplicated].groupby("tx_hash")["block_number"].nunique()
        if conflicts.gt(1).any():
            raise ValueError("one route transaction is assigned to multiple Ethereum blocks")
        requests = requests.drop_duplicates("tx_hash", keep="first")
    return requests.sort_values(["block_number", "tx_hash"]).reset_index(drop=True)


def shard_requests(
    requests: pd.DataFrame, *, shard_index: int, shards: int
) -> pd.DataFrame:
    """Select one deterministic disjoint cache-filling shard."""

    if shards < 1 or shard_index < 0 or shard_index >= shards:
        raise ValueError("cache shard must satisfy 0 <= shard-index < shards")
    return requests.iloc[shard_index::shards].reset_index(drop=True)


def block_header_requests(requests: pd.DataFrame) -> pd.DataFrame:
    return (
        requests[["block_number"]]
        .drop_duplicates()
        .sort_values("block_number")
        .reset_index(drop=True)
    )


def fetch_one(tx_hash: str, block_number: int) -> dict[str, object]:
    return fetch_receipt(
        tx_hash,
        cache=CACHE,
        expected_block=block_number,
        require_block_hash=True,
        require_evidence=True,
        rpc_request=rpc_post,
    )


def fetch_one_header(block_number: int) -> dict[str, object]:
    return fetch_block_header(
        block_number,
        cache=HEADER_CACHE,
        require_evidence=True,
        rpc_request=rpc_post,
    )


def fetch_batches(
    items: list[tuple[object, ...]],
    *,
    fetcher: Callable[..., dict[str, object]],
    workers: int,
    batch_size: int,
    progress_label: str,
    failure_label: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        failures: list[tuple[object, str]] = []
        with interruptible_thread_pool(max_workers=workers) as pool:
            futures = {
                pool.submit(fetcher, *item): item[0]
                for item in batch
            }
            for future in as_completed(futures):
                try:
                    rows.append(future.result())
                except Exception as exc:
                    failures.append((futures[future], type(exc).__name__))
        completed = min(start + len(batch), len(items))
        print(
            f"  {progress_label} [{completed:,}/{len(items):,}]; failed={len(failures):,}",
            flush=True,
        )
        if failures:
            sample = ", ".join(f"{identity}:{error}" for identity, error in failures[:5])
            raise RuntimeError(
                f"{failure_label} batch has {len(failures):,} failures: {sample}"
            )
    return rows


def fetch_receipts(
    requests: pd.DataFrame,
    *,
    workers: int,
    batch_size: int,
) -> list[dict[str, object]]:
    return fetch_batches(
        [
            (str(row.tx_hash), int(row.block_number))
            for row in requests.itertuples(index=False)
        ],
        fetcher=fetch_one,
        workers=workers,
        batch_size=batch_size,
        progress_label="exact route receipts",
        failure_label="exact route receipt",
    )


def fetch_headers(
    requests: pd.DataFrame,
    *,
    workers: int,
    batch_size: int,
) -> list[dict[str, object]]:
    return fetch_batches(
        [(int(row.block_number),) for row in requests.itertuples(index=False)],
        fetcher=fetch_one_header,
        workers=workers,
        batch_size=batch_size,
        progress_label="exact route block headers",
        failure_label="exact route block-header",
    )


def receipt_panel(
    receipts: list[dict[str, object]],
    requests: pd.DataFrame,
    headers: list[dict[str, object]],
) -> pd.DataFrame:
    panel = pd.DataFrame.from_records(receipts)
    if any(
        not receipt_is_current(
            row,
            str(row.get("tx_hash") or ""),
            expected_block=row.get("block_number"),
            require_block_hash=True,
            require_evidence=True,
        )
        for row in receipts
    ):
        raise RuntimeError("exact route receipt evidence cannot be reopened")
    if any(
        not block_header_is_current(
            row,
            int(row.get("block_number", -1)),
            require_evidence=True,
        )
        for row in headers
    ):
        raise RuntimeError("exact route block-header evidence cannot be reopened")
    panel = panel.drop(
        columns=[column for column in RPC_EVIDENCE_FIELDS if column in panel],
    )
    expected = requests.rename(columns={"block_number": "expected_block"})
    panel = panel.merge(expected, on="tx_hash", how="inner", validate="one_to_one")
    if len(panel) != len(requests):
        raise RuntimeError("exact receipt merge changed the route transaction perimeter")
    if not panel["status"].eq(1).all() or not panel["gas_used"].gt(0).all():
        raise RuntimeError("exact route receipt panel contains a failed or zero-gas transaction")
    if not panel["block_number"].eq(panel["expected_block"]).all():
        raise RuntimeError("exact route receipt panel changed a transaction block identity")
    header_panel = pd.DataFrame.from_records(headers).rename(
        columns={"block_hash": "header_block_hash"}
    )
    header_panel = header_panel.drop(
        columns=[column for column in RPC_EVIDENCE_FIELDS if column in header_panel],
    )
    expected_blocks = block_header_requests(requests)
    if header_panel.empty or header_panel["block_number"].duplicated().any():
        raise RuntimeError("exact route block-header evidence is empty or duplicated")
    if set(header_panel["block_number"]) != set(expected_blocks["block_number"]):
        raise RuntimeError("exact route block-header evidence changed the block perimeter")
    panel = panel.merge(
        header_panel,
        on="block_number",
        how="left",
        validate="many_to_one",
    )
    if panel["header_block_hash"].isna().any() or not panel["block_hash"].eq(
        panel["header_block_hash"]
    ).all():
        raise RuntimeError("exact route receipt and block-header hashes disagree")
    prices = pd.to_numeric(panel["effective_gas_price_wei"], errors="raise")
    if prices.isna().any() or prices.lt(0).any():
        raise RuntimeError("exact route receipt panel lacks a nonnegative effective gas price")
    panel["gas_price_supported"] = prices.gt(0)
    panel["gas_price_support_reason"] = "receipt_effective_gas_price"
    panel.loc[
        ~panel["gas_price_supported"], "gas_price_support_reason"
    ] = "zero_effective_price_private_payment_possible"
    panel["gas_gwei"] = (prices / 1e9).where(panel["gas_price_supported"])
    base_fee = pd.to_numeric(panel["base_fee_per_gas_wei"], errors="coerce")
    if base_fee.dropna().lt(0).any():
        raise RuntimeError("exact route block headers contain a negative base fee")
    panel["base_fee_supported"] = base_fee.notna()
    panel["base_fee_support_reason"] = "same_block_base_fee_per_gas"
    panel.loc[
        ~panel["base_fee_supported"], "base_fee_support_reason"
    ] = "pre_eip1559_block_no_base_fee"
    panel["base_fee_gwei"] = (base_fee / 1e9).where(panel["base_fee_supported"])
    return panel.drop(columns=["expected_block", "header_block_hash"]).sort_values(
        ["block_number", "tx_hash"]
    ).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    require_node_d_release(routes=True, market_state=True)
    require_current_artifacts([GROSS_PANEL], consumer="exact route transaction gas")
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--batch-size and --limit must be positive")
    if args.shards != 1 and not args.cache_only:
        parser.error("multi-shard runs must use --cache-only before one full assembly run")
    requests = route_receipt_requests()
    if args.limit is not None:
        requests = requests.head(args.limit)
    try:
        receipt_requests = shard_requests(
            requests, shard_index=args.shard_index, shards=args.shards
        )
        header_requests = shard_requests(
            block_header_requests(requests),
            shard_index=args.shard_index,
            shards=args.shards,
        )
    except ValueError as error:
        parser.error(str(error))
    workers = bounded_workers(args.workers, maximum=8)
    with exclusive_job(LOCK, job="exact route transaction gas prices"):
        receipts = fetch_receipts(
            receipt_requests,
            workers=workers,
            batch_size=args.batch_size,
        )
        headers = fetch_headers(
            header_requests,
            workers=workers,
            batch_size=args.batch_size,
        )
        if args.cache_only:
            print(
                f"PASS: exact route-gas cache shard {args.shard_index + 1}/{args.shards}; "
                f"receipts={len(receipts):,}; blocks={len(headers):,}"
            )
            return 0
        panel = receipt_panel(receipts, receipt_requests, headers)
        if args.limit is not None:
            print(
                f"PASS: exact route-gas bounded diagnostic; "
                f"receipts={len(panel):,}; blocks={len(headers):,}"
            )
            return 0
        evidence = write_receipt_snapshot(
            receipts,
            RECEIPT_EVIDENCE,
            require_evidence=True,
        )
        block_evidence = write_block_header_snapshot(
            headers,
            BLOCK_HEADER_EVIDENCE,
            require_evidence=True,
        )
        write_panel(
            panel,
            OUT_PANEL,
            code_sources=CODE_SOURCES,
            inputs=[GROSS_PANEL, evidence, block_evidence],
            notes="exact realised-route receipt effective gas price plus same-block base fee with transaction/block/hash identity",
        )
    supported = int(panel["gas_price_supported"].sum())
    print(
        f"PASS: exact route gas prices {supported:,}/{len(panel):,}; "
        f"wrote {OUT_PANEL.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
