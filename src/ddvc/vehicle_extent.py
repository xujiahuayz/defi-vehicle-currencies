"""Non-mechanical vehicle extent from intermediation relative to endpoint demand.

A token's raw intermediation share is mechanically high when it is already a common
endpoint or is widely listed. The excess-use ratio removes that fundamental-demand
benchmark: the token's share of value carried as an intermediary divided by its share
of value demanded as a route source or sink, over the same clean route universe.

The source and sink denominator intentionally includes direct routes. Excluding them
would condition fundamental demand on the decision to route indirectly and put the
outcome back into the benchmark. Cycles are excluded before either side is measured.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.asset_types import canonical_token, classify

CLEAN_ROUTE_CLASSES = ("single", "coherent")
KEYS = ["tx_hash", "component_id"]
REQUIRED_COLUMNS = KEYS + [
    "route_class",
    "token_in",
    "token_out",
    "tin_role",
    "tout_role",
    "amount_usd",
    "log_index",
]


def _role_rows(legs: pd.DataFrame, side: str, role: str) -> pd.DataFrame:
    token = f"token_{side}"
    role_col = "tin_role" if side == "in" else "tout_role"
    return (
        legs.loc[legs[role_col].eq(role), KEYS + [token, "amount_usd"]]
        .rename(columns={token: "token"})
        .copy()
    )


def compute_vehicle_extent(legs: pd.DataFrame) -> pd.DataFrame:
    """One row per token for one period, with auditable numerator and denominator."""
    missing = sorted(set(REQUIRED_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"vehicle extent is missing columns: {', '.join(missing)}")
    d = legs.loc[
        legs["route_class"].isin(CLEAN_ROUTE_CLASSES)
        & pd.to_numeric(legs["amount_usd"], errors="coerce").gt(0),
        REQUIRED_COLUMNS,
    ].copy()
    if d.empty:
        return pd.DataFrame()
    d["token_in"] = d["token_in"].map(lambda value: canonical_token(value) or "")
    d["token_out"] = d["token_out"].map(lambda value: canonical_token(value) or "")
    d = d[d["token_in"].astype(bool) & d["token_out"].astype(bool)]

    sources = _role_rows(d, "in", "source")
    sinks = _role_rows(d, "out", "sink")
    role_cyclic = sources[KEYS + ["token"]].merge(
        sinks[KEYS + ["token"]], on=KEYS + ["token"], how="inner"
    )[KEYS].drop_duplicates()
    ordered = d.sort_values(KEYS + ["log_index"], kind="stable")
    bounds = ordered.groupby(KEYS, as_index=False).agg(
        first_token=("token_in", "first"),
        last_token=("token_out", "last"),
    )
    ordered_cyclic = bounds.loc[
        bounds["first_token"].eq(bounds["last_token"]), KEYS
    ]
    cyclic = pd.concat([role_cyclic, ordered_cyclic], ignore_index=True).drop_duplicates()
    if not cyclic.empty:
        d = d.merge(cyclic.assign(_cycle=1), on=KEYS, how="left")
        d = d[d["_cycle"].isna()].drop(columns="_cycle")
        sources = _role_rows(d, "in", "source")
        sinks = _role_rows(d, "out", "sink")

    # A token appears on both adjacent legs when it is an intermediary. Average its
    # repeated role observations within the component so A->K->B gives K the route's
    # value once, not twice. The same rule handles a split component without allowing
    # its number of recorded legs to manufacture intermediation volume.
    intermediate = pd.concat(
        [_role_rows(d, "in", "intermediate"), _role_rows(d, "out", "intermediate")],
        ignore_index=True,
    )
    intermediate = (
        intermediate.groupby(KEYS + ["token"], as_index=False)["amount_usd"].mean()
        if not intermediate.empty else intermediate
    )
    endpoints = pd.concat([sources, sinks], ignore_index=True)
    endpoints = (
        endpoints.groupby(KEYS + ["token"], as_index=False)["amount_usd"].mean()
        if not endpoints.empty else endpoints
    )

    iv = intermediate.groupby("token")["amount_usd"].sum() if not intermediate.empty else pd.Series(dtype=float)
    ev = endpoints.groupby("token")["amount_usd"].sum() if not endpoints.empty else pd.Series(dtype=float)
    ic = intermediate.groupby("token").size() if not intermediate.empty else pd.Series(dtype="int64")
    ec = endpoints.groupby("token").size() if not endpoints.empty else pd.Series(dtype="int64")
    tokens = iv.index.union(ev.index)
    out = pd.DataFrame({
        "token": tokens,
        "intermediate_usd": iv.reindex(tokens, fill_value=0.0).to_numpy(),
        "endpoint_usd": ev.reindex(tokens, fill_value=0.0).to_numpy(),
        "intermediate_routes": ic.reindex(tokens, fill_value=0).to_numpy(dtype="int64"),
        "endpoint_routes": ec.reindex(tokens, fill_value=0).to_numpy(dtype="int64"),
    })
    total_i = float(out["intermediate_usd"].sum())
    total_e = float(out["endpoint_usd"].sum())
    total_ic = int(out["intermediate_routes"].sum())
    total_ec = int(out["endpoint_routes"].sum())
    out["intermediate_share"] = out["intermediate_usd"] / total_i if total_i else 0.0
    out["endpoint_share"] = out["endpoint_usd"] / total_e if total_e else 0.0
    out["vehicle_excess_use_ratio"] = np.where(
        out["endpoint_share"] > 0,
        out["intermediate_share"] / out["endpoint_share"],
        np.nan,
    )
    out["intermediate_count_share"] = (
        out["intermediate_routes"] / total_ic if total_ic else 0.0
    )
    out["endpoint_count_share"] = out["endpoint_routes"] / total_ec if total_ec else 0.0
    out["vehicle_excess_use_count_ratio"] = np.where(
        out["endpoint_count_share"] > 0,
        out["intermediate_count_share"] / out["endpoint_count_share"],
        np.nan,
    )
    labels = out["token"].map(classify)
    out["symbol"] = labels.map(lambda item: item[0] or "")
    out["asset_type"] = labels.map(lambda item: item[1])
    out["endpoint_supported"] = out["endpoint_share"] > 0
    out["routes_clean"] = int(d[KEYS].drop_duplicates().shape[0])
    out["routes_cyclic_excluded"] = int(cyclic.shape[0])
    return out.sort_values("intermediate_share", ascending=False).reset_index(drop=True)
