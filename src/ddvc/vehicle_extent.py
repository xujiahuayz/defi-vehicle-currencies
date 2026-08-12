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
from ddvc.route_roles import (
    VALUE_SUPPORT_COLUMNS,
    component_eligibility,
    component_value_support,
    role_token_values,
)

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


def restrict_routes_to_venues(legs: pd.DataFrame, venues: set[str] | frozenset[str]) -> pd.DataFrame:
    """Keep complete route components only when every leg uses an allowed venue."""
    missing = sorted(set(KEYS + ["source"]) - set(legs.columns))
    if missing:
        raise ValueError(f"venue restriction is missing columns: {', '.join(missing)}")
    blocked = legs.loc[~legs["source"].isin(venues), KEYS].drop_duplicates()
    if blocked.empty:
        return legs.copy()
    marked = legs.merge(blocked.assign(_venue_blocked=True), on=KEYS, how="left", sort=False)
    return marked.loc[marked["_venue_blocked"].isna(), legs.columns].copy()


def aggregate_vehicle_extent(
    frame: pd.DataFrame,
    keys: list[str],
    *,
    level: str,
    period_keys: list[str],
) -> pd.DataFrame:
    """Aggregate raw extent numerators before constructing period-specific shares."""
    aggregations: dict[str, tuple[str, str]] = {
        "intermediate_usd": ("intermediate_usd", "sum"),
        "endpoint_usd": ("endpoint_usd", "sum"),
        "intermediate_routes": ("intermediate_routes", "sum"),
        "endpoint_routes": ("endpoint_routes", "sum"),
        "days": ("date", "nunique"),
    }
    for support in VALUE_SUPPORT_COLUMNS:
        for role in ("intermediate", "endpoint"):
            for quantity in ("usd", "routes"):
                column = f"{role}_{quantity}_{support}"
                if column in frame:
                    aggregations[column] = (column, "sum")
    out = frame.groupby(keys, as_index=False).agg(**aggregations)
    by_period = out.groupby(period_keys)
    out["intermediate_share"] = (
        out["intermediate_usd"] / by_period["intermediate_usd"].transform("sum")
    )
    out["endpoint_share"] = (
        out["endpoint_usd"] / by_period["endpoint_usd"].transform("sum")
    )
    out["vehicle_excess_use_ratio"] = (
        out["intermediate_share"]
        / out["endpoint_share"].where(out["endpoint_share"].gt(0))
    )
    for support in VALUE_SUPPORT_COLUMNS:
        intermediate_column = f"intermediate_usd_{support}"
        endpoint_column = f"endpoint_usd_{support}"
        if intermediate_column not in out or endpoint_column not in out:
            continue
        intermediate_share = f"intermediate_share_{support}"
        endpoint_share = f"endpoint_share_{support}"
        out[intermediate_share] = (
            out[intermediate_column]
            / by_period[intermediate_column].transform("sum")
        )
        out[endpoint_share] = (
            out[endpoint_column]
            / by_period[endpoint_column].transform("sum")
        )
        out[f"vehicle_excess_use_ratio_{support}"] = (
            out[intermediate_share]
            / out[endpoint_share].where(out[endpoint_share].gt(0))
        )
        intermediate_count_column = f"intermediate_routes_{support}"
        endpoint_count_column = f"endpoint_routes_{support}"
        if intermediate_count_column not in out or endpoint_count_column not in out:
            continue
        intermediate_count_share = f"intermediate_count_share_{support}"
        endpoint_count_share = f"endpoint_count_share_{support}"
        out[intermediate_count_share] = (
            out[intermediate_count_column]
            / by_period[intermediate_count_column].transform("sum")
        )
        out[endpoint_count_share] = (
            out[endpoint_count_column]
            / by_period[endpoint_count_column].transform("sum")
        )
        out[f"vehicle_excess_use_count_ratio_{support}"] = (
            out[intermediate_count_share]
            / out[endpoint_count_share].where(out[endpoint_count_share].gt(0))
        )
    out["intermediate_count_share"] = (
        out["intermediate_routes"]
        / by_period["intermediate_routes"].transform("sum")
    )
    out["endpoint_count_share"] = (
        out["endpoint_routes"] / by_period["endpoint_routes"].transform("sum")
    )
    out["vehicle_excess_use_count_ratio"] = (
        out["intermediate_count_share"]
        / out["endpoint_count_share"].where(out["endpoint_count_share"].gt(0))
    )
    out.insert(0, "level", level)
    return out


def compute_vehicle_extent(legs: pd.DataFrame) -> pd.DataFrame:
    """One row per token for one period, with auditable numerator and denominator."""
    missing = sorted(set(REQUIRED_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"vehicle extent is missing columns: {', '.join(missing)}")
    d = legs.loc[
        legs["route_class"].isin(CLEAN_ROUTE_CLASSES),
        REQUIRED_COLUMNS,
    ].copy()
    d["amount_usd"] = pd.to_numeric(d["amount_usd"], errors="coerce")
    if d.empty:
        return pd.DataFrame()
    d["token_in"] = d["token_in"].map(lambda value: canonical_token(value) or "")
    d["token_out"] = d["token_out"].map(lambda value: canonical_token(value) or "")
    d = d[d["token_in"].astype(bool) & d["token_out"].astype(bool)]

    eligibility = component_eligibility(d, keys=KEYS)
    cyclic = eligibility.cyclic
    eligible = eligibility.eligible
    ambiguous = eligibility.ambiguous
    if eligible.empty:
        return pd.DataFrame()
    d = d.merge(eligible[KEYS], on=KEYS, how="inner")
    value_support = component_value_support(
        d, keys=KEYS, token_roles=eligibility.token_roles
    )
    sources = role_token_values(
        d, "source", keys=KEYS, token_roles=eligibility.token_roles
    )
    sinks = role_token_values(
        d, "sink", keys=KEYS, token_roles=eligibility.token_roles
    )

    # A token appears on both adjacent legs when it is an intermediary. Average its
    # repeated role observations within the component so A->K->B gives K the route's
    # value once, not twice. The same rule handles a split component without allowing
    # its number of recorded legs to manufacture intermediation volume.
    intermediate = role_token_values(
        d, "intermediate", keys=KEYS, token_roles=eligibility.token_roles
    )
    intermediate = intermediate.merge(
        eligible[KEYS + ["src", "tgt"]], on=KEYS, how="inner"
    )
    intermediate = intermediate[
        intermediate["token"].ne(intermediate["src"])
        & intermediate["token"].ne(intermediate["tgt"])
    ].drop(columns=["src", "tgt"])
    intermediate = intermediate.merge(
        value_support[KEYS + list(VALUE_SUPPORT_COLUMNS)], on=KEYS, how="inner"
    )
    endpoints = pd.concat([sources, sinks], ignore_index=True)
    endpoints = (
        endpoints.groupby(KEYS + ["token"], as_index=False)["amount_usd"].mean()
        if not endpoints.empty else endpoints
    )
    endpoints = endpoints.merge(
        value_support[KEYS + list(VALUE_SUPPORT_COLUMNS)], on=KEYS, how="inner"
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
    for support in VALUE_SUPPORT_COLUMNS:
        supported_intermediate = intermediate[intermediate[support]]
        supported_endpoints = endpoints[endpoints[support]]
        supported_iv = (
            supported_intermediate.groupby("token")["amount_usd"].sum()
            if not supported_intermediate.empty
            else pd.Series(dtype=float)
        )
        supported_ev = (
            supported_endpoints.groupby("token")["amount_usd"].sum()
            if not supported_endpoints.empty
            else pd.Series(dtype=float)
        )
        out[f"intermediate_usd_{support}"] = supported_iv.reindex(
            tokens, fill_value=0.0
        ).to_numpy()
        out[f"endpoint_usd_{support}"] = supported_ev.reindex(
            tokens, fill_value=0.0
        ).to_numpy()
        supported_ic = (
            supported_intermediate.groupby("token").size()
            if not supported_intermediate.empty
            else pd.Series(dtype="int64")
        )
        supported_ec = (
            supported_endpoints.groupby("token").size()
            if not supported_endpoints.empty
            else pd.Series(dtype="int64")
        )
        out[f"intermediate_routes_{support}"] = supported_ic.reindex(
            tokens, fill_value=0
        ).to_numpy(dtype="int64")
        out[f"endpoint_routes_{support}"] = supported_ec.reindex(
            tokens, fill_value=0
        ).to_numpy(dtype="int64")
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
    for support in VALUE_SUPPORT_COLUMNS:
        intermediate_value_column = f"intermediate_usd_{support}"
        endpoint_value_column = f"endpoint_usd_{support}"
        total_intermediate_value = float(out[intermediate_value_column].sum())
        total_endpoint_value = float(out[endpoint_value_column].sum())
        intermediate_value_share = f"intermediate_share_{support}"
        endpoint_value_share = f"endpoint_share_{support}"
        out[intermediate_value_share] = (
            out[intermediate_value_column] / total_intermediate_value
            if total_intermediate_value
            else 0.0
        )
        out[endpoint_value_share] = (
            out[endpoint_value_column] / total_endpoint_value
            if total_endpoint_value
            else 0.0
        )
        out[f"vehicle_excess_use_ratio_{support}"] = np.where(
            out[endpoint_value_share] > 0,
            out[intermediate_value_share] / out[endpoint_value_share],
            np.nan,
        )
        intermediate_count_column = f"intermediate_routes_{support}"
        endpoint_count_column = f"endpoint_routes_{support}"
        total_intermediate_count = int(out[intermediate_count_column].sum())
        total_endpoint_count = int(out[endpoint_count_column].sum())
        intermediate_count_share = f"intermediate_count_share_{support}"
        endpoint_count_share = f"endpoint_count_share_{support}"
        out[intermediate_count_share] = (
            out[intermediate_count_column] / total_intermediate_count
            if total_intermediate_count
            else 0.0
        )
        out[endpoint_count_share] = (
            out[endpoint_count_column] / total_endpoint_count
            if total_endpoint_count
            else 0.0
        )
        out[f"vehicle_excess_use_count_ratio_{support}"] = np.where(
            out[endpoint_count_share] > 0,
            out[intermediate_count_share] / out[endpoint_count_share],
            np.nan,
        )
    labels = out["token"].map(classify)
    out["symbol"] = labels.map(lambda item: item[0] or "")
    out["asset_type"] = labels.map(lambda item: item[1])
    out["endpoint_supported"] = out["endpoint_share"] > 0
    out["routes_clean"] = int(d[KEYS].drop_duplicates().shape[0])
    out["routes_cyclic_excluded"] = int(cyclic.shape[0])
    out["routes_ambiguous_excluded"] = int(ambiguous.shape[0])
    return out.sort_values("intermediate_share", ascending=False).reset_index(drop=True)
