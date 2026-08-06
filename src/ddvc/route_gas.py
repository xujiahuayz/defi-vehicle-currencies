"""Pure candidate construction and deterministic sampling for route-gas measurement."""

from __future__ import annotations

import hashlib
import math

import pandas as pd

from ddvc.asset_types import canonical_token, classify
from ddvc.fetch.sources import DEX_SOURCES

SUPPORTED_VENUES = frozenset(DEX_SOURCES)
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
SAMPLE_CELLS = ["year", "legs", "venue_sequence", "gas_vehicle"]
CANDIDATE_COLUMNS = [
    "date",
    "day",
    "year",
    "tx_hash",
    "legs",
    "venue_sequence",
    "mid",
    "mid_symbol",
    "mid_type",
    "gas_vehicle",
    "route_notional_usd",
]


def candidate_transactions(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    """Return one row per exact one-component transaction on registered venues."""
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"gas-unit candidates are missing columns: {', '.join(missing)}")
    rows = []
    for tx_hash, group in frame.groupby("tx_hash", sort=False):
        if not group["source"].isin(SUPPORTED_VENUES).all():
            continue
        if group["component_id"].nunique() != 1:
            continue
        n_components = pd.to_numeric(group["n_components"], errors="coerce").dropna()
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
            *ordered.loc[ordered["tin_role"].eq("intermediate"), "token_in"],
            *ordered.loc[ordered["tout_role"].eq("intermediate"), "token_out"],
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
        gas_vehicle = mid if mid_symbol is not None else mid_type
        route_notional = float(pd.to_numeric(ordered["amount_usd"], errors="coerce").max())
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
                "gas_vehicle": gas_vehicle,
                "route_notional_usd": route_notional,
            }
        )
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


def deterministic_cell_sample(candidates: pd.DataFrame, per_cell: int) -> pd.DataFrame:
    """Apply a reproducible hash-ranked cap within prespecified comparison cells."""
    if candidates.empty:
        return candidates.copy()
    if per_cell < 1:
        raise ValueError("per_cell must be positive")
    out = candidates.copy()
    out["_rank"] = [
        hashlib.sha256(f"{year}|{tx_hash}".encode()).hexdigest()
        for year, tx_hash in zip(out["year"], out["tx_hash"], strict=True)
    ]
    out = (
        out.sort_values(SAMPLE_CELLS + ["_rank"], kind="stable")
        .groupby(SAMPLE_CELLS, as_index=False, group_keys=False)
        .head(per_cell)
    )
    return out.drop(columns=["_rank"]).reset_index(drop=True)
