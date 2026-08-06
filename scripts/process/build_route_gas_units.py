#!/usr/bin/env python3
"""Receipt-measured gas units by route topology, venue sequence and router.

The paper currently carries three pooled constants for one-, two- and three-leg
routes, but the script that produced them did not survive. That is not reproducible
and it cannot support venue-specific all-in route costs. This instrument selects
transactions containing exactly one coherent reconstructed route component, keeps
its ordered venue sequence and intermediary type, fetches one stored receipt per
transaction, and reports the distribution of total gas used.

Receipt gas is transaction-level. Restricting to one reconstructed component
removes visible route mixtures, but a router transaction may still perform token
approvals, transfers or bookkeeping outside the AMM logs. Medians and interquartile
ranges are therefore primary, and the raw sampled panel retains the router address
so later matching can compare like with like.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/route_gas_units.parquet
        output/exhibits/route_gas_units_summary.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.asset_types import canonical_token, classify
from ddvc.calendar import nearest_monthly_days
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.quoter import rpc_post
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
CACHE = DATA_DIR / "interim" / "route_gas_receipts"
OUT_PANEL = DATA_DIR / "processed" / "route_gas_units.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "route_gas_units_summary.jsonl"
VENUES = {"uniswap_v2", "sushiswap_v2"}
REQUIRED_COLUMNS = [
    "tx_hash",
    "component_id",
    "n_components",
    "source",
    "token_in",
    "token_out",
    "amount_usd",
    "log_index",
    "route_class",
    "tin_role",
    "tout_role",
]
CODE_SOURCES = [
    "scripts/process/build_route_gas_units.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/quoter.py",
]


def candidate_transactions(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    """One row per exact one-component V2-family transaction."""
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"gas-unit candidates are missing columns: {', '.join(missing)}")
    rows = []
    for tx_hash, group in frame.groupby("tx_hash", sort=False):
        if not group["source"].isin(VENUES).all():
            continue
        if group["component_id"].nunique() != 1:
            continue
        n_components = pd.to_numeric(
            group["n_components"], errors="coerce"
        ).dropna()
        if n_components.empty or not n_components.eq(1).all():
            continue
        ordered = group.sort_values("log_index", kind="stable")
        if ordered["log_index"].duplicated().any():
            continue
        legs = len(ordered)
        if legs not in (1, 2, 3):
            continue
        expected_class = "single" if legs == 1 else "coherent"
        if not ordered["route_class"].eq(expected_class).all():
            continue
        if ordered.iloc[0]["tin_role"] != "source":
            continue
        if ordered.iloc[-1]["tout_role"] != "sink":
            continue
        if ordered["tin_role"].eq("source").sum() != 1:
            continue
        if ordered["tout_role"].eq("sink").sum() != 1:
            continue
        connected = all(
            canonical_token(left) == canonical_token(right)
            for left, right in zip(
                ordered["token_out"].iloc[:-1],
                ordered["token_in"].iloc[1:],
                strict=True,
            )
        )
        if not connected:
            continue
        intermediaries = set()
        intermediate_values = [
            *ordered.loc[
                ordered["tin_role"].eq("intermediate"), "token_in"
            ],
            *ordered.loc[
                ordered["tout_role"].eq("intermediate"), "token_out"
            ],
        ]
        for value in intermediate_values:
            token = canonical_token(value)
            if token:
                intermediaries.add(token)
        if legs == 1:
            mid = None
            mid_symbol = None
            mid_type = "direct"
        elif len(intermediaries) == 1:
            mid = next(iter(intermediaries))
            mid_symbol, mid_type = classify(mid)
        else:
            mid = "|".join(sorted(intermediaries)) or None
            mid_symbol = None
            mid_type = "multi"
        route_notional = float(
            pd.to_numeric(ordered["amount_usd"], errors="coerce").max()
        )
        if not math.isfinite(route_notional) or route_notional <= 0:
            continue
        rows.append(
            {
                "date": pd.to_datetime(day, format="%Y%m%d"),
                "day": day,
                "year": int(day[:4]),
                "tx_hash": str(tx_hash).lower(),
                "legs": legs,
                "venue_sequence": ">".join(ordered["source"].astype(str)),
                "mid": mid,
                "mid_symbol": mid_symbol,
                "mid_type": mid_type,
                "route_notional_usd": route_notional,
            }
        )
    return pd.DataFrame(rows)


def deterministic_cell_sample(
    candidates: pd.DataFrame, per_cell: int
) -> pd.DataFrame:
    """Hash-ranked cap within prespecified gas-comparison cells."""
    if candidates.empty:
        return candidates.copy()
    if per_cell < 1:
        raise ValueError("per_cell must be positive")
    out = candidates.copy()
    out["_rank"] = [
        hashlib.sha256(f"{year}|{tx_hash}".encode()).hexdigest()
        for year, tx_hash in zip(out["year"], out["tx_hash"], strict=True)
    ]
    cells = ["year", "legs", "venue_sequence", "mid_type"]
    out = (
        out.sort_values(cells + ["_rank"], kind="stable")
        .groupby(cells, as_index=False, group_keys=False)
        .head(per_cell)
    )
    return out.drop(columns=["_rank"]).reset_index(drop=True)


def parse_receipt(tx_hash: str, response: object) -> dict | None:
    """Normalised successful JSON-RPC receipt, or None when unusable."""
    if not isinstance(response, dict) or response.get("error"):
        return None
    result = response.get("result") or {}
    try:
        gas_used = int(result["gasUsed"], 16)
        status = int(result.get("status", "0x1"), 16)
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "tx_hash": tx_hash.lower(),
        "gas_used": gas_used,
        "status": status,
        "router": str(result.get("to") or "").lower() or None,
        "sender": str(result.get("from") or "").lower() or None,
        "effective_gas_price_wei": (
            int(result["effectiveGasPrice"], 16)
            if result.get("effectiveGasPrice")
            else None
        ),
    }


def fetch_receipt(tx_hash: str) -> dict:
    """Fetch and atomically cache one transaction receipt."""
    cached = CACHE / f"{tx_hash.lower()}.json"
    if cached.exists():
        row = json.loads(cached.read_text())
        if (
            row.get("tx_hash") == tx_hash.lower()
            and isinstance(row.get("gas_used"), int)
            and row["gas_used"] > 0
        ):
            return row
    response = rpc_post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        },
        timeout=20,
        retries=2,
        sleep=0.02,
    )
    row = parse_receipt(tx_hash, response)
    if row is None:
        raise RuntimeError("receipt response is missing gasUsed")
    CACHE.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", nargs="+")
    parser.add_argument("--per-cell", type=int, default=25)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.per_cell < 1:
        parser.error("--per-cell must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")

    days = args.days or nearest_monthly_days(
        path.stem for path in UNIFIED.glob("[0-9]" * 8 + ".parquet")
    )
    parts = []
    for index, day in enumerate(days, 1):
        path = UNIFIED / f"{day}.parquet"
        if path.exists():
            frame = pd.read_parquet(path, columns=REQUIRED_COLUMNS)
            candidates = candidate_transactions(frame, day)
            if not candidates.empty:
                parts.append(candidates)
        if index % 12 == 0 or index == len(days):
            print(
                f"  candidate days {index}/{len(days)} | "
                f"rows {sum(map(len, parts)):,}",
                flush=True,
            )
    if not parts:
        print("no exact one-component route transactions")
        return 1
    candidates = pd.concat(parts, ignore_index=True)
    sample = deterministic_cell_sample(candidates, args.per_cell)
    print(
        f"selected {len(sample):,} of {len(candidates):,} candidates across "
        f"{sample[['year', 'legs', 'venue_sequence', 'mid_type']].drop_duplicates().shape[0]:,} cells",
        flush=True,
    )

    receipts = []
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_receipt, tx_hash): tx_hash
            for tx_hash in sample["tx_hash"]
        }
        for index, future in enumerate(as_completed(futures), 1):
            tx_hash = futures[future]
            try:
                receipts.append(future.result())
            except Exception as exc:
                failed.append((tx_hash, type(exc).__name__))
            if index % 100 == 0 or index == len(futures):
                print(
                    f"  receipts {index}/{len(futures)} | failed {len(failed)}",
                    flush=True,
                )
    if not receipts:
        print("no receipts resolved")
        return 1
    if failed:
        print(
            f"refusing a selected sample with {len(failed)} unresolved receipts; rerun to fill the deterministic cache"
        )
        return 2
    panel = sample.merge(
        pd.DataFrame(receipts), on="tx_hash", how="inner", validate="one_to_one"
    )
    if len(panel) != len(sample):
        raise RuntimeError("receipt merge changed the deterministic sample size")
    if not panel["status"].eq(1).all():
        raise RuntimeError("a reconstructed swap transaction has a failed receipt")
    if not panel["gas_used"].gt(0).all():
        raise RuntimeError("a selected receipt has non-positive gas usage")
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED, CACHE],
        notes=f"hash-ranked cap of {args.per_cell} exact one-component transactions per year-topology-venue-intermediary cell",
    )
    cells = ["year", "legs", "venue_sequence", "mid_type"]
    summary = panel.groupby(cells, as_index=False).agg(
        transactions=("gas_used", "size"),
        routers=("router", "nunique"),
        median_gas_used=("gas_used", "median"),
        p25_gas_used=("gas_used", lambda values: values.quantile(0.25)),
        p75_gas_used=("gas_used", lambda values: values.quantile(0.75)),
        median_notional_usd=("route_notional_usd", "median"),
    )
    write_exhibit(
        summary,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes="receipt-measured gas units; transaction-level medians and interquartile ranges",
    )
    print(
        f"\nwrote {OUT_PANEL.relative_to(REPO_ROOT)} with {len(panel):,} receipts "
        f"and {OUT_EXHIBIT.relative_to(REPO_ROOT)} with {len(summary):,} cells"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
