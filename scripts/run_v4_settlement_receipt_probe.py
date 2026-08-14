#!/usr/bin/env python3
"""Estimate V4 intermediary-token transfer incidence on matched route units.

The current route-unit builder and this receipt estimator are separate owners.
This script first matches pure Uniswap V3 and V4 routes on ordered endpoints,
vehicle address, UTC week, and fixed dollar-size bin.  It selects transactions
without consulting receipt availability.  Estimation then requires a complete,
current receipt cache and compares intermediary-token ERC-20 Transfer incidence
within the matched route cells.

The result is an architecture first stage, not a causal V4-adoption estimate.
It establishes whether a token that appears between the route endpoints also
emits an ERC-20 Transfer somewhere in the same transaction.  Route units do not
contain sufficient intermediate-token quantities to identify physical movement
in dollars or settlement intensity; those outcomes require a separate decoded
transfer/PoolManager-delta owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import holm_adjusted_pvalues, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit, write_panel


ROUTES = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"
RECEIPTS = DATA_DIR / "empirical" / "v4_settlement_receipts.jsonl"
SELECTION = DATA_DIR / "empirical" / "v4_settlement_receipt_selection.parquet"
RESULTS = OUTPUT_DIR / "exhibits" / "v4_settlement_receipt_probe_results.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "v4_settlement_receipt_probe_support.jsonl"
DEXES = ("uniswap_v3", "uniswap_v4")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
SIZE_BIN_EDGES = (0.0, 100.0, 1_000.0, 10_000.0, 100_000.0, 1_000_000.0, np.inf)
SIZE_BIN_LABELS = ("lt_100", "100_1k", "1k_10k", "10k_100k", "100k_1m", "ge_1m")
CELL_KEYS = ("week", "src", "sink", "vehicle_id", "size_bin")
CODE_SOURCES = [
    "scripts/run_v4_settlement_receipt_probe.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]


def attach_size_bins(routes: pd.DataFrame) -> pd.DataFrame:
    required = {
        "week", "src", "sink", "vehicle", "vehicle_id", "dex", "tx_hash",
        "component_id", "route_usd",
    }
    missing = sorted(required - set(routes.columns))
    if missing:
        raise ValueError(f"V4 settlement routes lack columns: {missing}")
    data = routes[routes["dex"].isin(DEXES)].copy()
    data["week"] = pd.to_datetime(data["week"], errors="raise").dt.normalize()
    data["route_usd"] = pd.to_numeric(data["route_usd"], errors="raise")
    if data["route_usd"].le(0).any() or not np.isfinite(data["route_usd"]).all():
        raise ValueError("V4 settlement routes require positive finite route values")
    data["vehicle_id"] = data["vehicle_id"].astype(str).str.lower()
    data["tx_hash"] = data["tx_hash"].astype(str).str.lower()
    data["size_bin"] = pd.cut(
        data["route_usd"],
        bins=SIZE_BIN_EDGES,
        labels=SIZE_BIN_LABELS,
        right=False,
        include_lowest=True,
    ).astype(str)
    if data["size_bin"].isna().any():
        raise ValueError("V4 settlement routes contain unassigned size bins")
    duplicate_keys = ["dex", "tx_hash", "component_id", "src", "sink", "vehicle_id"]
    if data.duplicated(duplicate_keys).any():
        raise ValueError("V4 settlement routes repeat an architecture-route unit")
    return data


def _selection_score(row: pd.Series, seed: int) -> str:
    payload = "|".join(
        str(row[column])
        for column in (*CELL_KEYS, "dex", "tx_hash", "component_id")
    )
    return hashlib.sha256(f"{seed}|{payload}".encode()).hexdigest()


def select_matched_routes(
    routes: pd.DataFrame,
    *,
    min_routes: int,
    max_cells: int,
    per_architecture: int,
    seed: int,
) -> pd.DataFrame:
    """Select balanced architecture observations before reading receipts."""

    if min_routes < 1 or max_cells < 1 or per_architecture < 1:
        raise ValueError("V4 receipt selection counts must be positive")
    data = attach_size_bins(routes)
    counts = (
        data.groupby([*CELL_KEYS, "dex"], observed=True)
        .size()
        .unstack("dex")
    )
    if any(dex not in counts for dex in DEXES):
        raise ValueError("V4 receipt selection lacks one architecture")
    eligible = counts.dropna(subset=list(DEXES)).copy()
    eligible = eligible[(eligible[list(DEXES)] >= min_routes).all(axis=1)].reset_index()
    if eligible.empty:
        raise ValueError("V4 receipt selection has no matched route cells")
    eligible["cell_id"] = eligible[list(CELL_KEYS)].astype(str).agg("|".join, axis=1)
    eligible["cell_score"] = eligible["cell_id"].map(
        lambda value: hashlib.sha256(f"{seed}|{value}".encode()).hexdigest()
    )
    eligible = eligible.sort_values(["cell_score", "cell_id"], kind="stable").head(max_cells)
    narrowed = data.merge(eligible[list(CELL_KEYS) + ["cell_id"]], on=list(CELL_KEYS), how="inner")
    narrowed["selection_score"] = narrowed.apply(_selection_score, axis=1, seed=seed)
    selected = (
        narrowed.sort_values(["cell_id", "dex", "selection_score"], kind="stable")
        .groupby(["cell_id", "dex"], observed=True, sort=False)
        .head(per_architecture)
        .copy()
    )
    architecture_counts = selected.groupby(["cell_id", "dex"], observed=True).size().unstack("dex")
    if architecture_counts.isna().any().any():
        raise RuntimeError("V4 receipt selection lost architecture balance")
    if not architecture_counts.nunique(axis=1).eq(1).all():
        # A cell may have fewer than the requested observations only if both
        # architectures have the same count. The min-routes gate normally
        # prevents this, but this assertion keeps the balance explicit.
        raise RuntimeError("V4 receipt selection is not balanced within route cells")
    columns = [
        *CELL_KEYS, "cell_id", "dex", "vehicle", "tx_hash", "component_id",
        "route_usd", "selection_score",
    ]
    return selected[columns].sort_values(["cell_id", "dex", "selection_score"], kind="stable").reset_index(drop=True)


def load_receipt_cache(path: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"V4 receipt cache has a blank row at line {line_number}")
            record = json.loads(line)
            tx_hash = str(record.get("tx") or record.get("tx_hash") or "").lower()
            # Accept both the repository's canonical normalized receipt snapshot
            # and the retired raw-RPC wrapper.  New acquisition should use the
            # canonical direct row; wrapper support exists only to make an
            # explicit old-cache audit possible.
            receipt = record.get("receipt") if "receipt" in record else record
            if not tx_hash.startswith("0x") or len(tx_hash) != 66:
                raise ValueError(f"V4 receipt cache has an invalid transaction at line {line_number}")
            if tx_hash in receipts:
                raise ValueError(f"V4 receipt cache repeats transaction {tx_hash}")
            if not isinstance(receipt, dict) or not isinstance(receipt.get("logs"), list):
                raise ValueError(f"V4 receipt cache lacks a decoded receipt at line {line_number}")
            receipt_hash = str(
                receipt.get("transactionHash") or receipt.get("tx_hash") or tx_hash
            ).lower()
            if receipt_hash != tx_hash:
                raise ValueError(f"V4 receipt transaction hash disagrees at line {line_number}")
            receipts[tx_hash] = receipt
    return receipts


def matching_transfer_count(receipt: dict[str, Any], vehicle_id: str) -> int:
    vehicle = str(vehicle_id).lower()
    return sum(
        1
        for log in receipt.get("logs", [])
        if str(log.get("address", "")).lower() == vehicle
        and isinstance(log.get("topics"), list)
        and bool(log["topics"])
        and str(log["topics"][0]).lower() == TRANSFER_TOPIC
    )


def attach_receipts(selection: pd.DataFrame, receipts: dict[str, dict[str, Any]]) -> pd.DataFrame:
    required = set(selection["tx_hash"].astype(str).str.lower())
    missing = sorted(required - set(receipts))
    if missing:
        raise ValueError(
            f"V4 receipt cache misses {len(missing):,} of {len(required):,} selected transactions; "
            "selection is fixed before receipt acquisition"
        )
    detail = selection.copy()
    detail["matching_transfer_logs"] = [
        matching_transfer_count(receipts[str(row.tx_hash).lower()], str(row.vehicle_id))
        for row in detail.itertuples(index=False)
    ]
    detail["has_matching_transfer"] = detail["matching_transfer_logs"].gt(0).astype(float)
    detail["receipt_total_logs"] = [
        len(receipts[str(tx_hash).lower()]["logs"]) for tx_hash in detail["tx_hash"]
    ]
    return detail


def _paired_cells(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        detail.groupby(["cell_id", *CELL_KEYS, "dex"], observed=True, as_index=False)
        .agg(
            transfer_share=("has_matching_transfer", "mean"),
            mean_transfer_logs=("matching_transfer_logs", "mean"),
            observations=("tx_hash", "size"),
            median_route_usd=("route_usd", "median"),
        )
    )
    wide = grouped.pivot(
        index=["cell_id", *CELL_KEYS],
        columns="dex",
        values=["transfer_share", "mean_transfer_logs", "observations", "median_route_usd"],
    )
    required = [("transfer_share", dex) for dex in DEXES]
    if any(column not in wide.columns for column in required):
        raise ValueError("V4 receipt detail lacks a matched architecture")
    wide = wide.dropna(subset=required).reset_index()
    wide.columns = [
        column if isinstance(column, str) else "_".join(part for part in column if part)
        for column in wide.columns
    ]
    wide["ordered_pair"] = wide["src"].astype(str) + "|" + wide["sink"].astype(str)
    wide["transfer_difference"] = (
        wide["transfer_share_uniswap_v4"] - wide["transfer_share_uniswap_v3"]
    )
    wide["transfer_log_difference"] = (
        wide["mean_transfer_logs_uniswap_v4"] - wide["mean_transfer_logs_uniswap_v3"]
    )
    return wide


def _fit_difference(frame: pd.DataFrame, outcome: str) -> dict[str, object]:
    fit = ols_clustered(
        frame[outcome],
        np.ones(len(frame)),
        frame["week"],
        add_constant=False,
        additional_clusters=(frame["ordered_pair"],),
        min_observations=30,
        min_clusters=10,
    )
    standard_error = float(fit.standard_errors[0])
    if not np.isfinite(standard_error) or standard_error <= 0:
        raise RuntimeError(f"{outcome} has invalid two-way clustered variance")
    degrees_freedom = fit.n_clusters - 1
    critical = float(stats.t.ppf(0.975, degrees_freedom))
    estimate = float(fit.beta[0])
    return {
        "cells": int(fit.n_observations),
        "ordered_pair_clusters": int(fit.cluster_counts[1]),
        "calendar_week_clusters": int(fit.cluster_counts[0]),
        "v4_minus_v3": estimate,
        "standard_error": standard_error,
        "t_statistic": float(fit.t_statistics[0]),
        "p_value": float(fit.p_values[0]),
        "confidence_interval_lower": estimate - critical * standard_error,
        "confidence_interval_upper": estimate + critical * standard_error,
        "covariance": "two_way_ordered_pair_calendar_week_cr1",
    }


def estimate_receipt_probe(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    paired = _paired_cells(detail)
    rows: list[dict[str, object]] = []
    families: list[tuple[str, pd.DataFrame]] = [("all", paired)]
    families.extend(
        (f"size_bin:{size_bin}", group)
        for size_bin, group in paired.groupby("size_bin", observed=True)
        if len(group) >= 30 and group["ordered_pair"].nunique() >= 10 and group["week"].nunique() >= 10
    )
    for sample, frame in families:
        fit = _fit_difference(frame, "transfer_difference")
        rows.append(
            {
                "sample": sample,
                "outcome": "intermediary_token_transfer_incidence",
                "v3_mean": float(frame["transfer_share_uniswap_v3"].mean()),
                "v4_mean": float(frame["transfer_share_uniswap_v4"].mean()),
                **fit,
                "claim_status": "descriptive_matched_architecture_first_stage",
            }
        )
    results = pd.DataFrame(rows)
    results["p_value_holm"] = holm_adjusted_pvalues(results["p_value"])
    return results, paired


def support_record(
    selection: pd.DataFrame,
    paired: pd.DataFrame,
    *,
    min_routes: int,
    max_cells: int,
    per_architecture: int,
    seed: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "selected_rows": len(selection),
                "selected_transactions": int(selection["tx_hash"].nunique()),
                "matched_cells": len(paired),
                "ordered_pairs": int(paired["ordered_pair"].nunique()),
                "calendar_weeks": int(paired["week"].nunique()),
                "minimum_routes_per_architecture_cell": min_routes,
                "maximum_cells": max_cells,
                "selected_rows_per_architecture_cell": per_architecture,
                "seed": seed,
                "matching_dimensions": "ordered_endpoints|vehicle_address|calendar_week|fixed_route_size_bin|direction",
                "size_bins_usd": "[0,100)|[100,1000)|[1000,10000)|[10000,100000)|[100000,1000000)|[1000000,inf)",
                "selection_uses_receipt_availability": False,
                "identified_outcome": "same_transaction_intermediary_token_erc20_transfer_incidence",
                "unidentified_outcomes": "physical_transfer_value_usd|settlement_intensity|poolmanager_net_delta|causal_route_adoption",
            }
        ]
    )


def run(
    *,
    routes_path: Path,
    receipt_path: Path,
    selection_output: Path,
    results_output: Path,
    support_output: Path,
    min_routes: int,
    max_cells: int,
    per_architecture: int,
    seed: int,
    select_only: bool,
) -> pd.DataFrame | None:
    with current_artifacts([routes_path], consumer="V4 settlement receipt selection"):
        routes = pd.read_parquet(routes_path)
        selection = select_matched_routes(
            routes,
            min_routes=min_routes,
            max_cells=max_cells,
            per_architecture=per_architecture,
            seed=seed,
        )
        write_panel(
            selection,
            selection_output,
            code_sources=CODE_SOURCES,
            inputs=[routes_path],
            notes="Receipt-independent matched V3/V4 route selection; exact transaction requests for settlement first stage",
        )
    if select_only:
        print(
            f"selected {selection['cell_id'].nunique():,} cells, "
            f"{selection['tx_hash'].nunique():,} transactions; receipts not read",
            flush=True,
        )
        return None
    with current_artifacts(
        [routes_path, selection_output, receipt_path],
        consumer="V4 settlement receipt estimator",
    ):
        receipts = load_receipt_cache(receipt_path)
        detail = attach_receipts(selection, receipts)
        results, paired = estimate_receipt_probe(detail)
        support = support_record(
            selection,
            paired,
            min_routes=min_routes,
            max_cells=max_cells,
            per_architecture=per_architecture,
            seed=seed,
        )
        notes = (
            "Matched V3/V4 intermediary-token ERC20 Transfer first stage; selection precedes "
            "receipt acquisition; two-way ordered-pair and calendar-week CR1 inference; "
            "not physical movement in dollars and not a causal V4-adoption effect"
        )
        write_exhibit(
            results,
            results_output,
            code_sources=CODE_SOURCES,
            inputs=[routes_path, selection_output, receipt_path],
            notes=notes,
        )
        write_exhibit(
            support,
            support_output,
            code_sources=CODE_SOURCES,
            inputs=[routes_path, selection_output, receipt_path],
            notes=notes,
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=ROUTES)
    parser.add_argument("--receipts", type=Path, default=RECEIPTS)
    parser.add_argument("--selection-output", type=Path, default=SELECTION)
    parser.add_argument("--results-output", type=Path, default=RESULTS)
    parser.add_argument("--support-output", type=Path, default=SUPPORT)
    parser.add_argument("--min-routes", type=int, default=5)
    parser.add_argument("--max-cells", type=int, default=500)
    parser.add_argument("--per-architecture", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    results = run(
        routes_path=args.routes,
        receipt_path=args.receipts,
        selection_output=args.selection_output,
        results_output=args.results_output,
        support_output=args.support_output,
        min_routes=args.min_routes,
        max_cells=args.max_cells,
        per_architecture=args.per_architecture,
        seed=args.seed,
        select_only=args.select_only,
    )
    if results is not None:
        for row in results.itertuples(index=False):
            print(
                f"{row.sample}: {100 * row.v4_minus_v3:+.2f} pp "
                f"(SE {100 * row.standard_error:.2f}; Holm p={row.p_value_holm:.4g})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
