#!/usr/bin/env python3
"""Fetch exact receipt gas prices for every route in the gross counterfactual panel."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from pathlib import Path

import pandas as pd

from ddvc.data_release import require_node_d_release
from ddvc.ethereum_receipts import RECEIPT_CACHE, fetch_receipt, write_receipt_snapshot
from ddvc.paths import DATA_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.quoter import rpc_post
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_thread_pool
from ddvc.tables import write_panel


GROSS_PANEL = DATA_DIR / "processed" / "counterfactual_dominance_gross.parquet"
OUT_PANEL = DATA_DIR / "processed" / "route_transaction_gas.parquet"
RECEIPT_EVIDENCE = DATA_DIR / "empirical" / "route_transaction_gas_receipts.jsonl"
CACHE = RECEIPT_CACHE
LOCK = SHARED_RUNTIME_DIR / "route-transaction-gas.lock"
CODE_SOURCES = [
    "scripts/process/build_route_transaction_gas.py",
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


def fetch_one(tx_hash: str, block_number: int) -> dict[str, object]:
    return fetch_receipt(
        tx_hash,
        cache=CACHE,
        expected_block=block_number,
        rpc_request=rpc_post,
    )


def fetch_receipts(
    requests: pd.DataFrame,
    *,
    workers: int,
    batch_size: int,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for start in range(0, len(requests), batch_size):
        batch = requests.iloc[start : start + batch_size]
        failures: list[tuple[str, str]] = []
        with interruptible_thread_pool(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_one, str(row.tx_hash), int(row.block_number)): str(row.tx_hash)
                for row in batch.itertuples(index=False)
            }
            for future in as_completed(futures):
                try:
                    receipts.append(future.result())
                except Exception as exc:
                    failures.append((futures[future], type(exc).__name__))
        completed = min(start + len(batch), len(requests))
        print(
            f"  exact route receipts [{completed:,}/{len(requests):,}]; failed={len(failures):,}",
            flush=True,
        )
        if failures:
            sample = ", ".join(f"{tx}:{error}" for tx, error in failures[:5])
            raise RuntimeError(
                f"exact route receipt batch has {len(failures):,} failures: {sample}"
            )
    return receipts


def receipt_panel(receipts: list[dict[str, object]], requests: pd.DataFrame) -> pd.DataFrame:
    panel = pd.DataFrame.from_records(receipts)
    expected = requests.rename(columns={"block_number": "expected_block"})
    panel = panel.merge(expected, on="tx_hash", how="inner", validate="one_to_one")
    if len(panel) != len(requests):
        raise RuntimeError("exact receipt merge changed the route transaction perimeter")
    if not panel["status"].eq(1).all() or not panel["gas_used"].gt(0).all():
        raise RuntimeError("exact route receipt panel contains a failed or zero-gas transaction")
    if not panel["block_number"].eq(panel["expected_block"]).all():
        raise RuntimeError("exact route receipt panel changed a transaction block identity")
    prices = pd.to_numeric(panel["effective_gas_price_wei"], errors="raise")
    if prices.isna().any() or prices.lt(0).any():
        raise RuntimeError("exact route receipt panel lacks a nonnegative effective gas price")
    panel["gas_price_supported"] = prices.gt(0)
    panel["gas_price_support_reason"] = "receipt_effective_gas_price"
    panel.loc[
        ~panel["gas_price_supported"], "gas_price_support_reason"
    ] = "zero_effective_price_private_payment_possible"
    panel["gas_gwei"] = (prices / 1e9).where(panel["gas_price_supported"])
    return panel.drop(columns="expected_block").sort_values(
        ["block_number", "tx_hash"]
    ).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    require_node_d_release(routes=True, market_state=True)
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--batch-size and --limit must be positive")
    requests = route_receipt_requests()
    if args.limit is not None:
        requests = requests.head(args.limit)
    workers = bounded_workers(args.workers, maximum=8)
    with exclusive_job(LOCK, job="exact route transaction gas prices"):
        receipts = fetch_receipts(requests, workers=workers, batch_size=args.batch_size)
        panel = receipt_panel(receipts, requests)
        if args.limit is not None:
            print(f"PASS: bounded exact route-gas diagnostic receipts={len(panel):,}")
            return 0
        evidence = write_receipt_snapshot(receipts, RECEIPT_EVIDENCE)
        write_panel(
            panel,
            OUT_PANEL,
            code_sources=CODE_SOURCES,
            inputs=[GROSS_PANEL, evidence],
            notes="exact realised-route receipt effective gas price with transaction/block identity",
        )
    supported = int(panel["gas_price_supported"].sum())
    print(
        f"PASS: exact route gas prices {supported:,}/{len(panel):,}; "
        f"wrote {OUT_PANEL.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
