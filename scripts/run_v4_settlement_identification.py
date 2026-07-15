#!/usr/bin/env python3
"""Matched V3/V4 settlement-implementation test for Proposition 4b.

The route table tells us whether a token is used as the route intermediary. To
test V4 flash accounting, we need to ask whether that intermediary also moves as
an ERC-20 transfer in the transaction receipt. The design matches route units by
endpoint pair, week, and intermediate token, then compares Uniswap V3 and V4.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.paths import DATA_DIR, OUTPUT_DIR  # noqa: E402


DEXES = ("uniswap_v3", "uniswap_v4")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
PRIMARY_VEHICLES = {"WETH", "ETH", "USDC", "USDT", "DAI", "WBTC", "XAUt", "XAUT"}
DEFAULT_RPCS = (
    "https://ethereum-rpc.publicnode.com",
    "https://ethereum.publicnode.com",
    "https://rpc.mevblocker.io",
    "https://eth-mainnet.public.blastapi.io",
)
OUT_DATA = DATA_DIR / "empirical"
OUT = OUTPUT_DIR / "empirical"
RECEIPT_CACHE = OUT_DATA / "v4_receipts" / "receipts.jsonl"


@dataclass
class TTest:
    n: int
    mean: float
    t: float
    p: float


def _stamp_to_date(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def _week(date: pd.Series) -> pd.Series:
    d = pd.to_datetime(date)
    return (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.normalize()


def _vehicle_family(sym: object) -> str:
    s = "" if sym is None else str(sym)
    if s in {"ETH", "WETH"}:
        return "ETH/WETH"
    if s.upper() == "XAUT":
        return "XAUt"
    return s


def _rpc_urls() -> list[str]:
    raw = os.getenv("ETH_RPC_URLS") or os.getenv("ETH_RPC_URL") or ""
    urls = [u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()]
    return urls or list(DEFAULT_RPCS)


def _rpc_post(payload: Any, *, timeout: int = 120, retries: int = 3) -> Any:
    data = json.dumps(payload).encode()
    last: Exception | None = None
    for url in _rpc_urls():
        for attempt in range(retries):
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "glotl-ddvc/1.0"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429 or 500 <= e.code < 600:
                    break
                time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = e
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Ethereum RPC request failed: {last}")


def _load_receipt_cache() -> dict[str, dict[str, Any] | None]:
    out: dict[str, dict[str, Any] | None] = {}
    if not RECEIPT_CACHE.exists():
        return out
    with RECEIPT_CACHE.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            out[str(rec["tx"]).lower()] = rec.get("receipt")
    return out


def fetch_receipts(txs: list[str], *, batch_size: int = 25) -> dict[str, dict[str, Any] | None]:
    RECEIPT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_receipt_cache()
    missing = [tx.lower() for tx in txs if tx.lower() not in cache]
    if not missing:
        return cache
    with RECEIPT_CACHE.open("a") as fh:
        for off in range(0, len(missing), batch_size):
            batch = missing[off : off + batch_size]
            payload = [
                {"jsonrpc": "2.0", "id": i, "method": "eth_getTransactionReceipt", "params": [tx]}
                for i, tx in enumerate(batch)
            ]
            response = _rpc_post(payload)
            if not isinstance(response, list):
                raise RuntimeError(f"Unexpected RPC response: {response}")
            by_id = {int(r.get("id")): r for r in response if isinstance(r, dict)}
            for i, tx in enumerate(batch):
                item = by_id.get(i, {})
                receipt = item.get("result")
                cache[tx] = receipt
                fh.write(json.dumps({"tx": tx, "receipt": receipt}, separators=(",", ":")) + "\n")
            fh.flush()
            print(f"  receipts [{min(off + batch_size, len(missing))}/{len(missing)}]", flush=True)
            time.sleep(0.25)
    return cache


def build_route_units(start: str, end: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    files = sorted((DATA_DIR / "unified").glob("[0-9]" * 8 + ".parquet"))
    s = start.replace("-", "")
    e = end.replace("-", "")
    files = [p for p in files if s <= p.stem <= e]
    cols = [
        "tx_hash", "log_index", "source", "token_in", "token_out",
        "token_in_sym", "token_out_sym", "amount_usd", "component_id",
        "route_class", "tin_role", "tout_role",
    ]
    for i, path in enumerate(files, 1):
        day = _stamp_to_date(path.stem)
        df = pd.read_parquet(path, columns=cols)
        df = df[df["source"].isin(DEXES) & df["route_class"].eq("coherent")]
        if df.empty:
            continue
        for (tx, component, dex), g in df.groupby(["tx_hash", "component_id", "source"], sort=False):
            if len(g) < 2:
                continue
            role: dict[tuple[str, str], str] = {}
            for r in g.itertuples(index=False):
                for addr, sym, rl in (
                    (r.token_in, r.token_in_sym, r.tin_role),
                    (r.token_out, r.token_out_sym, r.tout_role),
                ):
                    key = (str(addr).lower(), str(sym))
                    if role.get(key) == "intermediate":
                        continue
                    if rl == "intermediate" or key not in role:
                        role[key] = str(rl)
            sources = [k for k, rl in role.items() if rl == "source"]
            sinks = [k for k, rl in role.items() if rl == "sink"]
            inter = [k for k, rl in role.items() if rl == "intermediate"]
            if not sources or not sinks or not inter:
                continue
            vol = float(pd.to_numeric(g["amount_usd"], errors="coerce").mean())
            if not math.isfinite(vol) or vol <= 0:
                continue
            for src_addr, src_sym in sources:
                for sink_addr, sink_sym in sinks:
                    if src_addr == sink_addr:
                        continue
                    for veh_addr, veh_sym in inter:
                        family = _vehicle_family(veh_sym)
                        if family not in {_vehicle_family(x) for x in PRIMARY_VEHICLES}:
                            continue
                        vehicle_id = WETH_ADDR if veh_addr == ZERO_ADDR and family == "ETH/WETH" else veh_addr
                        if vehicle_id == ZERO_ADDR:
                            continue
                        rows.append({
                            "date": day,
                            "week": pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).weekday()),
                            "dex": dex,
                            "tx_hash": str(tx).lower(),
                            "component_id": int(component),
                            "src": src_sym,
                            "sink": sink_sym,
                            "vehicle": family,
                            "vehicle_id": vehicle_id,
                            "route_usd": vol,
                        })
        if i % 50 == 0 or i == len(files):
            print(f"  v4 route units [{i}/{len(files)}] {day}", flush=True)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.drop_duplicates(["dex", "tx_hash", "component_id", "src", "sink", "vehicle", "vehicle_id"])
    out["week"] = pd.to_datetime(out["week"])
    _write(out, OUT_DATA / "v4_settlement_route_units.parquet")
    return out


def eligible_cells(routes: pd.DataFrame, min_routes: int) -> pd.DataFrame:
    cell = (
        routes.groupby(["week", "src", "sink", "vehicle", "dex"], as_index=False)
        .agg(routes=("tx_hash", "count"), route_usd=("route_usd", "sum"))
    )
    wide = cell.pivot(index=["week", "src", "sink", "vehicle"], columns="dex", values=["routes", "route_usd"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.dropna(subset=[f"routes_{d}" for d in DEXES])
    for dex in DEXES:
        wide = wide[wide[f"routes_{dex}"].ge(min_routes)]
    wide["min_route_usd"] = wide[[f"route_usd_{d}" for d in DEXES]].min(axis=1)
    wide = wide[wide["min_route_usd"].gt(0)].copy()
    wide["sample_weight"] = np.log1p(wide["min_route_usd"])
    out = wide.reset_index()
    _write(out, OUT_DATA / "v4_settlement_eligible_cells.parquet")
    return out


def sample_routes(routes: pd.DataFrame, cells: pd.DataFrame, n_cells: int, per_dex_cell: int, seed: int) -> pd.DataFrame:
    selected = cells.sample(
        n=min(n_cells, len(cells)),
        weights="sample_weight",
        random_state=seed,
    )[["week", "src", "sink", "vehicle"]]
    narrowed = routes.merge(selected, on=["week", "src", "sink", "vehicle"], how="inner")
    chunks: list[pd.DataFrame] = []
    for j, (_, g) in enumerate(narrowed.groupby(["week", "src", "sink", "vehicle", "dex"], sort=False)):
        chunks.append(g.sample(n=min(per_dex_cell, len(g)), weights=g["route_usd"].clip(lower=1e-9), random_state=seed + j))
    out = pd.concat(chunks, ignore_index=True)
    out["cell_id"] = (
        out["week"].astype(str) + "|" + out["src"].astype(str) + "|" + out["sink"].astype(str) + "|" + out["vehicle"].astype(str)
    )
    _write(out, OUT_DATA / "v4_settlement_sample.parquet")
    return out


def matching_transfer_count(receipt: dict[str, Any] | None, vehicle_id: str) -> int:
    if not isinstance(receipt, dict):
        return 0
    vehicle = vehicle_id.lower()
    return sum(
        1
        for lg in receipt.get("logs", [])
        if str(lg.get("address", "")).lower() == vehicle
        and lg.get("topics")
        and str(lg["topics"][0]).lower() == TRANSFER_TOPIC
    )


def transfer_detail(sample: pd.DataFrame) -> pd.DataFrame:
    receipts = fetch_receipts(sorted(sample["tx_hash"].str.lower().unique()))
    rows = []
    for r in sample.itertuples(index=False):
        receipt = receipts.get(str(r.tx_hash).lower())
        n = matching_transfer_count(receipt, str(r.vehicle_id))
        rows.append({
            "week": r.week,
            "dex": r.dex,
            "src": r.src,
            "sink": r.sink,
            "vehicle": r.vehicle,
            "tx_hash": r.tx_hash,
            "component_id": r.component_id,
            "route_usd": r.route_usd,
            "vehicle_id": r.vehicle_id,
            "cell_id": r.cell_id,
            "receipt_found": isinstance(receipt, dict),
            "matching_transfer_logs": n,
            "has_matching_transfer": n > 0,
            "total_logs": len(receipt.get("logs", [])) if isinstance(receipt, dict) else 0,
        })
    out = pd.DataFrame(rows)
    _write(out, OUT_DATA / "v4_settlement_transfer_detail.parquet")
    return out


def _ttest(values: pd.Series) -> TTest:
    d = pd.to_numeric(values, errors="coerce").dropna()
    if len(d) < 3:
        return TTest(len(d), math.nan, math.nan, math.nan)
    t, p = stats.ttest_1samp(d, 0.0)
    return TTest(len(d), float(d.mean()), float(t), float(p))


def summarize(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dex_summary = (
        detail.groupby("dex", as_index=False)
        .agg(
            observations=("tx_hash", "count"),
            cells=("cell_id", "nunique"),
            receipt_found_share=("receipt_found", "mean"),
            transfer_share=("has_matching_transfer", "mean"),
            mean_transfer_logs=("matching_transfer_logs", "mean"),
            median_route_usd=("route_usd", "median"),
        )
        .sort_values("dex")
    )
    cell = (
        detail.groupby(["cell_id", "vehicle", "dex"], as_index=False)
        .agg(transfer_share=("has_matching_transfer", "mean"), observations=("tx_hash", "count"))
    )
    wide = cell.pivot(index=["cell_id", "vehicle"], columns="dex", values=["transfer_share", "observations"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.dropna(subset=[f"transfer_share_{d}" for d in DEXES]).copy()
    wide["diff"] = wide["transfer_share_uniswap_v4"] - wide["transfer_share_uniswap_v3"]
    test = _ttest(wide["diff"])
    paired = pd.DataFrame([{
        "test": "matched_cell_transfer",
        "cells": test.n,
        "v3_mean": wide["transfer_share_uniswap_v3"].mean(),
        "v4_mean": wide["transfer_share_uniswap_v4"].mean(),
        "diff": test.mean,
        "t": test.t,
        "p": test.p,
    }])
    het = []
    for vehicle, g in wide.reset_index().groupby("vehicle"):
        if len(g) < 5:
            continue
        ht = _ttest(g["diff"])
        het.append({
            "vehicle": vehicle,
            "cells": ht.n,
            "v3_mean": g["transfer_share_uniswap_v3"].mean(),
            "v4_mean": g["transfer_share_uniswap_v4"].mean(),
            "diff": ht.mean,
            "t": ht.t,
            "p": ht.p,
        })
    heterogeneity = pd.DataFrame(het).sort_values("cells", ascending=False) if het else pd.DataFrame()
    _write(dex_summary, OUT / "v4_settlement_dex_summary.pkl")
    _write(paired, OUT / "v4_settlement_paired.pkl")
    _write(heterogeneity, OUT / "v4_settlement_heterogeneity.pkl")
    return dex_summary, paired, heterogeneity


def _fmt_pct(x: float) -> str:
    return "" if pd.isna(x) else f"{x:.1%}"


def _fmt_pp(x: float) -> str:
    return "" if pd.isna(x) else f"{100 * x:.1f}"


def _fmt_p(x: float) -> str:
    if pd.isna(x):
        return ""
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def write_memo(routes: pd.DataFrame, cells: pd.DataFrame, sample: pd.DataFrame, dex: pd.DataFrame, paired: pd.DataFrame, het: pd.DataFrame) -> None:
    p = paired.iloc[0]
    lines = [
        "# V4 matched settlement implementation",
        "",
        "Design: match coherent multi-hop Uniswap V3 and V4 route units by week, endpoint pair, and intermediate vehicle token. The route role is held fixed; the outcome is whether the transaction receipt contains an ERC-20 Transfer log for the intermediate token.",
        "",
        f"Route units: {len(routes):,}. Eligible matched cells: {len(cells):,}. Receipt sample: {sample['cell_id'].nunique():,} cells and {len(sample):,} route observations.",
        "",
        "| Test | Cells | V3 | V4 | V4 - V3 | t | p |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| ERC-20 transfer incidence | {int(p.cells):,} | {_fmt_pct(p.v3_mean)} | {_fmt_pct(p.v4_mean)} | {_fmt_pp(p['diff'])} pp | {p.t:.2f} | {_fmt_p(p.p)} |",
        "",
        "| DEX | Observations | Cells | Receipt found | Matching transfer | Mean transfer logs | Median route size |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in dex.itertuples(index=False):
        lines.append(
            f"| {r.dex} | {int(r.observations):,} | {int(r.cells):,} | {_fmt_pct(r.receipt_found_share)} | "
            f"{_fmt_pct(r.transfer_share)} | {r.mean_transfer_logs:.2f} | ${float(r.median_route_usd):,.0f} |"
        )
    if not het.empty:
        lines += ["", "| Vehicle | Cells | V3 transfer | V4 transfer | V4 - V3 | p |", "|---|---:|---:|---:|---:|---:|"]
        for r in het.itertuples(index=False):
            lines.append(
                f"| {r.vehicle} | {int(r.cells):,} | {_fmt_pct(r.v3_mean)} | {_fmt_pct(r.v4_mean)} | "
                f"{_fmt_pp(r.diff)} pp | {_fmt_p(r.p)} |"
            )
    lines += [
        "",
        "Interpretation: V4 does not eliminate vehicle routes. It weakens the link between route intermediation and physical intermediary-token settlement. This is the architecture proposition, distinct from the route-cost proposition.",
        "",
    ]
    path = OUT / "v4_settlement_identification.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        tmp = path.with_suffix(".tmp.parquet")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    else:
        df.to_pickle(path)

def run(args: argparse.Namespace) -> None:
    route_path = OUT_DATA / "v4_settlement_route_units.parquet"
    if route_path.exists() and not args.force:
        routes = pd.read_parquet(route_path)
        routes["week"] = pd.to_datetime(routes["week"])
    else:
        routes = build_route_units(args.start, args.end)
    cells = eligible_cells(routes, args.min_routes)
    sample = sample_routes(routes, cells, args.cells, args.per_dex_cell, args.seed)
    detail = transfer_detail(sample)
    dex, paired, het = summarize(detail)
    write_memo(routes, cells, sample, dex, paired, het)
    print(f"wrote {OUT / 'v4_settlement_identification.md'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2025-01-24")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--cells", type=int, default=500)
    ap.add_argument("--per-dex-cell", type=int, default=1)
    ap.add_argument("--min-routes", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260624)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
