#!/usr/bin/env python3
"""Materialize pure Uniswap V3/V4 intermediary-route units.

The output is the current input contract for architecture-state analysis.  A
route is assigned to an architecture only after its complete reconstructed
component is shown to use exactly one admitted V3/V4 source.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.calendar import sample_end_iso  # noqa: E402
from ddvc.paths import DATA_DIR  # noqa: E402
from ddvc.provenance import current_artifacts, stamp  # noqa: E402


DEXES = ("uniswap_v3", "uniswap_v4")
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
PRIMARY_VEHICLES = {"WETH", "ETH", "USDC", "USDT", "DAI", "WBTC", "XAUt", "XAUT"}
OUT_DATA = DATA_DIR / "empirical"


def _stamp_to_date(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def _vehicle_family(sym: object) -> str:
    s = "" if sym is None else str(sym)
    if s in {"ETH", "WETH"}:
        return "ETH/WETH"
    if s.upper() == "XAUT":
        return "XAUt"
    return s


def _exclusive_architecture(group: pd.DataFrame) -> str | None:
    """Return one admitted architecture only when the complete route is pure."""
    sources = set(group["source"].astype(str))
    if len(sources) != 1:
        return None
    source = next(iter(sources))
    return source if source in DEXES else None


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
        # Keep the complete reconstructed component until architecture purity is
        # known. Filtering to V3/V4 first can turn one mixed route into a false
        # single-architecture route.
        df = df[df["route_class"].eq("coherent")]
        if df.empty:
            continue
        for (tx, component), g in df.groupby(["tx_hash", "component_id"], sort=False):
            dex = _exclusive_architecture(g)
            if len(g) < 2 or dex is None:
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
    route_path = OUT_DATA / "v4_settlement_route_units.parquet"
    _write(out, route_path)
    stamp(
        route_path,
        code_sources=["scripts/run_v4_settlement_identification.py"],
        inputs=[DATA_DIR / "unified"],
        rows=len(out),
        notes="exclusive V3/V4 coherent route units; mixed-source components excluded",
    )
    return out

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
        with current_artifacts([route_path], consumer="V3/V4 architecture-state analysis"):
            pd.read_parquet(route_path, columns=["week", "src", "sink", "vehicle", "dex", "route_usd"])
    else:
        build_route_units(args.start, args.end)
    print(f"current exclusive-architecture route units: {route_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2025-01-24")
    ap.add_argument("--end", default=sample_end_iso())
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--build-routes-only",
        action="store_true",
        help="compatibility alias; route-unit materialization is now the script's only action",
    )
    args = ap.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
