"""Canonical token-role values within reconstructed route components."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd


ROUTE_KEYS = ("tx_hash", "component_id")


@dataclass(frozen=True)
class ComponentEligibility:
    eligible: pd.DataFrame
    cyclic: pd.DataFrame
    ambiguous: pd.DataFrame


def role_token_values(
    legs: pd.DataFrame,
    role: str,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
) -> pd.DataFrame:
    """Return net or pass-through value per component-token for one route role.

    A sequential route records an intermediary on both adjacent legs, while a split route can record it on several incoming and outgoing legs. Summing either side and then averaging the two flow directions counts the routed value once in both cases. Source and sink values are their net component flows, matching the role assignment in route reconstruction.
    """
    key_columns = list(keys)
    required = set(key_columns + ["token_in", "token_out", "tin_role", "tout_role", "amount_usd"])
    missing = sorted(required - set(legs.columns))
    if missing:
        raise ValueError(f"route-role values are missing columns: {', '.join(missing)}")
    rows = []
    for side, role_column in (("in", "tin_role"), ("out", "tout_role")):
        token_column = f"token_{side}"
        value_column = f"{side}_usd"
        selected = legs.loc[
            legs[role_column].eq(role), key_columns + [token_column, "amount_usd"]
        ].rename(columns={token_column: "token", "amount_usd": value_column})
        selected[value_column] = pd.to_numeric(selected[value_column], errors="coerce")
        rows.append(selected)
    combined = pd.concat(rows, ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=[*key_columns, "token", "amount_usd"])
    combined = combined.dropna(subset=["token"])
    values = combined.groupby(key_columns + ["token"], as_index=False).agg(
        in_usd=("in_usd", "sum"),
        out_usd=("out_usd", "sum"),
    )
    if role == "source":
        values["amount_usd"] = values["in_usd"] - values["out_usd"]
    elif role == "sink":
        values["amount_usd"] = values["out_usd"] - values["in_usd"]
    elif role == "intermediate":
        values["amount_usd"] = (values["in_usd"] + values["out_usd"]) / 2
    else:
        raise ValueError(f"unsupported route role: {role}")
    return values[key_columns + ["token", "amount_usd"]]


def component_notional(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
) -> pd.DataFrame:
    """Return one component notional as the mean of total source and sink flow."""
    key_columns = list(keys)
    sources = role_token_values(legs, "source", keys=key_columns).groupby(
        key_columns, as_index=False
    )["amount_usd"].sum().rename(columns={"amount_usd": "source_usd"})
    sinks = role_token_values(legs, "sink", keys=key_columns).groupby(
        key_columns, as_index=False
    )["amount_usd"].sum().rename(columns={"amount_usd": "sink_usd"})
    out = sources.merge(sinks, on=key_columns, how="inner")
    out["amount_usd"] = (out["source_usd"] + out["sink_usd"]) / 2
    return out[key_columns + ["amount_usd"]]


def component_endpoints(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
) -> pd.DataFrame:
    """Return source and sink identities plus their counts for each component."""
    key_columns = list(keys)
    source_tokens = role_token_values(legs, "source", keys=key_columns)
    sink_tokens = role_token_values(legs, "sink", keys=key_columns)
    return _component_endpoints_from_values(source_tokens, sink_tokens, key_columns)


def _component_endpoints_from_values(
    source_tokens: pd.DataFrame,
    sink_tokens: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    sources = source_tokens.groupby(keys, as_index=False).agg(
        src=("token", "first"), source_tokens=("token", "nunique")
    )
    sinks = sink_tokens.groupby(keys, as_index=False).agg(
        tgt=("token", "first"), sink_tokens=("token", "nunique")
    )
    return sources.merge(sinks, on=keys, how="inner")


def component_eligibility(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
) -> ComponentEligibility:
    """Partition components into economic routes, cycles, and ambiguous residue."""
    key_columns = list(keys)
    ordered = legs.sort_values(key_columns + ["log_index"], kind="stable")
    bounds = ordered.groupby(key_columns, as_index=False).agg(
        first_token=("token_in", "first"),
        last_token=("token_out", "last"),
    )
    source_tokens = role_token_values(legs, "source", keys=key_columns)
    sink_tokens = role_token_values(legs, "sink", keys=key_columns)
    endpoints = _component_endpoints_from_values(
        source_tokens, sink_tokens, key_columns
    )
    role_cyclic = source_tokens[key_columns + ["token"]].merge(
        sink_tokens[key_columns + ["token"]],
        on=key_columns + ["token"],
        how="inner",
    )[key_columns]
    ordered_cyclic = bounds.loc[
        bounds["first_token"].eq(bounds["last_token"]), key_columns
    ]
    cyclic = pd.concat([role_cyclic, ordered_cyclic], ignore_index=True).drop_duplicates()
    eligible = endpoints[
        endpoints["source_tokens"].eq(1)
        & endpoints["sink_tokens"].eq(1)
        & endpoints["src"].ne(endpoints["tgt"])
    ].merge(bounds, on=key_columns, how="inner")
    if not cyclic.empty:
        eligible = eligible.merge(
            cyclic.assign(_cyclic=True), on=key_columns, how="left"
        )
        eligible = eligible[eligible["_cyclic"].isna()].drop(columns="_cyclic")
    all_components = legs[key_columns].drop_duplicates()
    classified = pd.concat(
        [cyclic[key_columns], eligible[key_columns]], ignore_index=True
    ).drop_duplicates()
    ambiguous = all_components.merge(
        classified.assign(_classified=True), on=key_columns, how="left"
    )
    ambiguous = ambiguous[ambiguous["_classified"].isna()][key_columns]
    return ComponentEligibility(
        eligible=eligible.drop(columns=["first_token", "last_token"]),
        cyclic=cyclic,
        ambiguous=ambiguous,
    )
