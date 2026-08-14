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
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]

from ddvc.calendar import sample_end_iso  # noqa: E402
from ddvc.paths import DATA_DIR  # noqa: E402
from ddvc.provenance import current_artifacts, stamp  # noqa: E402


DEXES = ("uniswap_v3", "uniswap_v4")
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
PRIMARY_VEHICLES = {"WETH", "ETH", "USDC", "USDT", "DAI", "WBTC", "XAUt", "XAUT"}
OUT_DATA = DATA_DIR / "empirical"
UNIFIED_ROUTE_COLUMNS = [
    "tx_hash", "block_number", "log_index", "source", "token_in", "token_out",
    "token_in_sym", "token_out_sym", "amount_usd", "component_id",
    "n_components", "route_class", "tin_role", "tout_role",
]


def _stamp_to_date(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def _vehicle_family(sym: object) -> str:
    s = "" if sym is None else str(sym)
    if s in {"ETH", "WETH"}:
        return "ETH/WETH"
    if s.upper() == "XAUT":
        return "XAUt"
    return s


PRIMARY_VEHICLE_FAMILIES = {_vehicle_family(value) for value in PRIMARY_VEHICLES}


def _read_unified_route_partition(path: Path) -> pd.DataFrame:
    """Read the exact route identity contract or report the upstream blocker."""

    available = set(pq.read_schema(path).names)
    missing = sorted(set(UNIFIED_ROUTE_COLUMNS) - available)
    if missing:
        detail = ", ".join(missing)
        raise ValueError(
            f"canonical unified route partition {path} lacks required identity columns: "
            f"{detail}; extend the canonical unified owner rather than inferring block "
            "identity from timestamp_utc"
        )
    return pd.read_parquet(path, columns=UNIFIED_ROUTE_COLUMNS)


def _normalize_identity_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate immutable transaction, block, component and token identities."""

    missing = sorted(set(UNIFIED_ROUTE_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(
            "V4 route-unit source lacks required identity columns: " + ", ".join(missing)
        )
    data = frame.copy()
    data["tx_hash"] = data["tx_hash"].astype(str).str.lower()
    if not data["tx_hash"].str.fullmatch(r"0x[0-9a-f]{64}").all():
        raise ValueError("V4 route-unit source contains an invalid transaction hash")
    for column in ("token_in", "token_out"):
        data[column] = data[column].astype(str).str.lower()
        if not data[column].str.fullmatch(r"0x[0-9a-f]{40}").all():
            raise ValueError(f"V4 route-unit source contains an invalid {column} identity")
    for column in ("block_number", "log_index", "component_id", "n_components"):
        values = pd.to_numeric(data[column], errors="coerce")
        if values.isna().any() or values.mod(1).ne(0).any():
            raise ValueError(f"V4 route-unit source contains a non-integer {column}")
        data[column] = values.astype("int64")
    if data["block_number"].lt(0).any() or data["log_index"].lt(0).any():
        raise ValueError("V4 route-unit source contains a negative causal-order identity")
    if data["component_id"].lt(0).any() or data["n_components"].lt(1).any():
        raise ValueError("V4 route-unit source contains an invalid component identity")
    if data.duplicated(["tx_hash", "log_index"]).any():
        raise ValueError("V4 route-unit source repeats a transaction-log identity")

    transaction_identity = data.groupby("tx_hash", sort=False).agg(
        block_count=("block_number", "nunique"),
        declared_component_counts=("n_components", "nunique"),
        declared_components=("n_components", "first"),
        observed_components=("component_id", "nunique"),
    )
    if transaction_identity["block_count"].ne(1).any():
        raise ValueError("V4 route-unit source maps one transaction to multiple blocks")
    if transaction_identity["declared_component_counts"].ne(1).any():
        raise ValueError("V4 route-unit source disagrees on a transaction's component count")
    if transaction_identity["declared_components"].ne(
        transaction_identity["observed_components"]
    ).any():
        raise ValueError("V4 route-unit source omits or invents a transaction component")
    return data


def _exclusive_architecture(group: pd.DataFrame) -> str | None:
    """Return one admitted architecture only when the complete route is pure."""
    sources = set(group["source"].astype(str))
    if len(sources) != 1:
        return None
    source = next(iter(sources))
    return source if source in DEXES else None


def _route_units_for_day(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    """Construct exact-identity route units for one canonical daily partition."""

    data = _normalize_identity_columns(frame)
    data = data[data["route_class"].eq("coherent")]
    rows: list[dict[str, Any]] = []
    for (tx, component), group in data.groupby(["tx_hash", "component_id"], sort=False):
        dex = _exclusive_architecture(group)
        if len(group) < 2 or dex is None:
            continue
        blocks = group["block_number"].unique()
        component_counts = group["n_components"].unique()
        if len(blocks) != 1 or len(component_counts) != 1:
            raise ValueError("V4 route component has inconsistent transaction identity")
        token_roles: dict[str, str] = {}
        token_symbols: dict[str, str] = {}
        for row in group.sort_values("log_index", kind="stable").itertuples(index=False):
            for address, symbol, route_role in (
                (row.token_in, row.token_in_sym, row.tin_role),
                (row.token_out, row.token_out_sym, row.tout_role),
            ):
                token_id = str(address).lower()
                token_symbols.setdefault(token_id, str(symbol))
                if token_roles.get(token_id) == "intermediate":
                    continue
                if route_role == "intermediate" or token_id not in token_roles:
                    token_roles[token_id] = str(route_role)
        sources = [
            (token_id, token_symbols[token_id])
            for token_id, route_role in token_roles.items()
            if route_role == "source"
        ]
        sinks = [
            (token_id, token_symbols[token_id])
            for token_id, route_role in token_roles.items()
            if route_role == "sink"
        ]
        intermediaries = [
            (token_id, token_symbols[token_id])
            for token_id, route_role in token_roles.items()
            if route_role == "intermediate"
        ]
        if not sources or not sinks or not intermediaries:
            continue
        route_usd = float(pd.to_numeric(group["amount_usd"], errors="coerce").mean())
        if not math.isfinite(route_usd) or route_usd <= 0:
            continue
        n_components = int(component_counts[0])
        for src_id, src_symbol in sources:
            for sink_id, sink_symbol in sinks:
                if src_id == sink_id:
                    continue
                for vehicle_id, vehicle_symbol in intermediaries:
                    family = _vehicle_family(vehicle_symbol)
                    if family not in PRIMARY_VEHICLE_FAMILIES:
                        continue
                    rows.append(
                        {
                            "date": day,
                            "week": pd.Timestamp(day)
                            - pd.Timedelta(days=pd.Timestamp(day).weekday()),
                            "dex": dex,
                            "tx_hash": str(tx).lower(),
                            "block_number": int(blocks[0]),
                            "component_id": int(component),
                            "n_components": n_components,
                            "component_is_unique": n_components == 1,
                            "src": src_symbol,
                            "src_id": src_id,
                            "src_settlement_kind": (
                                "native" if src_id == ZERO_ADDR else "erc20"
                            ),
                            "sink": sink_symbol,
                            "sink_id": sink_id,
                            "sink_settlement_kind": (
                                "native" if sink_id == ZERO_ADDR else "erc20"
                            ),
                            "vehicle": family,
                            "vehicle_id": vehicle_id,
                            "vehicle_settlement_kind": (
                                "native" if vehicle_id == ZERO_ADDR else "erc20"
                            ),
                            "route_usd": route_usd,
                        }
                    )
    columns = [
        "date", "week", "dex", "tx_hash", "block_number", "component_id",
        "n_components", "component_is_unique", "src", "src_id",
        "src_settlement_kind", "sink", "sink_id", "sink_settlement_kind",
        "vehicle", "vehicle_id", "vehicle_settlement_kind", "route_usd",
    ]
    return pd.DataFrame(rows, columns=columns)


def build_route_units(start: str, end: str) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    files = sorted((DATA_DIR / "unified").glob("[0-9]" * 8 + ".parquet"))
    s = start.replace("-", "")
    e = end.replace("-", "")
    files = [p for p in files if s <= p.stem <= e]
    for i, path in enumerate(files, 1):
        day = _stamp_to_date(path.stem)
        df = _read_unified_route_partition(path)
        # Keep the complete reconstructed component until architecture purity is
        # known. Filtering to V3/V4 first can turn one mixed route into a false
        # single-architecture route.
        part = _route_units_for_day(df, day)
        if not part.empty:
            parts.append(part)
        if i % 50 == 0 or i == len(files):
            print(f"  v4 route units [{i}/{len(files)}] {day}", flush=True)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if out.empty:
        return out
    out = out.drop_duplicates(
        [
            "dex", "tx_hash", "block_number", "component_id", "src_id", "sink_id",
            "vehicle_id",
        ]
    )
    out["week"] = pd.to_datetime(out["week"])
    route_path = OUT_DATA / "v4_settlement_route_units.parquet"
    _write(out, route_path)
    stamp(
        route_path,
        code_sources=["scripts/run_v4_settlement_identification.py"],
        inputs=[DATA_DIR / "unified"],
        rows=len(out),
        notes=(
            "exclusive V3/V4 coherent route units with exact block, endpoint, component "
            "and native-token identities; mixed-source components excluded"
        ),
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
            pd.read_parquet(
                route_path,
                columns=[
                    "week", "src", "src_id", "sink", "sink_id", "vehicle",
                    "vehicle_id", "vehicle_settlement_kind", "dex", "tx_hash",
                    "block_number", "component_id", "n_components",
                    "component_is_unique", "route_usd",
                ],
            )
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
