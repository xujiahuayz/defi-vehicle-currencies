"""Canonical token-role values within reconstructed route components."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


ROUTE_KEYS = ("tx_hash", "component_id")


@dataclass(frozen=True)
class ComponentEligibility:
    eligible: pd.DataFrame
    cyclic: pd.DataFrame
    ambiguous: pd.DataFrame
    token_roles: pd.DataFrame


def topological_token_roles(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
) -> pd.DataFrame:
    """Assign source, sink and intermediary roles from directed token flow."""
    key_columns = list(keys)
    required = set(key_columns + ["token_in", "token_out"])
    missing = sorted(required - set(legs.columns))
    if missing:
        raise ValueError(f"route topology is missing columns: {', '.join(missing)}")
    inputs = legs[key_columns + ["token_in"]].rename(
        columns={"token_in": "token"}
    ).drop_duplicates().assign(_has_out=True)
    outputs = legs[key_columns + ["token_out"]].rename(
        columns={"token_out": "token"}
    ).drop_duplicates().assign(_has_in=True)
    roles = inputs.merge(outputs, on=key_columns + ["token"], how="outer")
    has_out = roles["_has_out"].fillna(False).astype(bool)
    has_in = roles["_has_in"].fillna(False).astype(bool)
    roles["role"] = np.select(
        [has_out & ~has_in, has_in & ~has_out],
        ["source", "sink"],
        default="intermediate",
    )
    return roles[key_columns + ["token", "role"]]


def _has_directed_cycle(edges: pd.DataFrame) -> bool:
    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {}
    for token_in, token_out in edges[["token_in", "token_out"]].itertuples(index=False, name=None):
        indegree.setdefault(token_in, 0)
        indegree.setdefault(token_out, 0)
        if token_out not in adjacency[token_in]:
            adjacency[token_in].add(token_out)
            indegree[token_out] += 1
    queue = deque(token for token, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        token = queue.popleft()
        visited += 1
        for successor in adjacency[token]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    return visited != len(indegree)


def _cyclic_components(
    legs: pd.DataFrame,
    token_roles: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    edges = legs[keys + ["token_in", "token_out"]].drop_duplicates()
    edge_counts = edges.groupby(keys).size().rename("edges")
    node_counts = token_roles.groupby(keys).size().rename("nodes")
    candidates = edge_counts.to_frame().join(node_counts).query("edges >= nodes").index
    if len(candidates) == 0:
        return pd.DataFrame(columns=keys)
    marked = edges.merge(
        candidates.to_frame(index=False).assign(_cycle_candidate=True),
        on=keys,
        how="inner",
    )
    rows = []
    for component_key, group in marked.groupby(keys, sort=False):
        if _has_directed_cycle(group):
            values = component_key if isinstance(component_key, tuple) else (component_key,)
            rows.append(dict(zip(keys, values, strict=True)))
    return pd.DataFrame(rows, columns=keys)


def role_token_values(
    legs: pd.DataFrame,
    role: str,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
    token_roles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return net or pass-through value per component-token for one route role.

    A sequential route records an intermediary on both adjacent legs, while a split route can record it on several incoming and outgoing legs. Summing either side and then averaging the two flow directions counts the routed value once in both cases. Source and sink values are their net component flows after topology fixes their economic roles.
    """
    key_columns = list(keys)
    required = set(key_columns + ["token_in", "token_out", "amount_usd"])
    missing = sorted(required - set(legs.columns))
    if missing:
        raise ValueError(f"route-role values are missing columns: {', '.join(missing)}")
    if role not in {"source", "sink", "intermediate"}:
        raise ValueError(f"unsupported route role: {role}")
    roles = token_roles if token_roles is not None else topological_token_roles(legs, keys=key_columns)
    selected_tokens = roles.loc[roles["role"].eq(role), key_columns + ["token"]]
    rows = []
    for side in ("in", "out"):
        token_column = f"token_{side}"
        value_column = f"{side}_usd"
        selected = legs[key_columns + [token_column, "amount_usd"]].rename(
            columns={token_column: "token", "amount_usd": value_column}
        ).merge(selected_tokens, on=key_columns + ["token"], how="inner")
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
    return values[key_columns + ["token", "amount_usd"]]


def component_notional(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
    token_roles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return one component notional as the mean of total source and sink flow."""
    key_columns = list(keys)
    sources = role_token_values(
        legs, "source", keys=key_columns, token_roles=token_roles
    ).groupby(
        key_columns, as_index=False
    )["amount_usd"].sum().rename(columns={"amount_usd": "source_usd"})
    sinks = role_token_values(
        legs, "sink", keys=key_columns, token_roles=token_roles
    ).groupby(
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
    roles = topological_token_roles(legs, keys=key_columns)
    return _component_endpoints_from_roles(roles, key_columns)


def _component_endpoints_from_roles(
    token_roles: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    source_tokens = token_roles[token_roles["role"].eq("source")]
    sink_tokens = token_roles[token_roles["role"].eq("sink")]
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
    token_roles = topological_token_roles(legs, keys=key_columns)
    endpoints = _component_endpoints_from_roles(token_roles, key_columns)
    all_components = legs[key_columns].drop_duplicates()
    cyclic = _cyclic_components(legs, token_roles, key_columns)
    eligible = endpoints[
        endpoints["source_tokens"].eq(1)
        & endpoints["sink_tokens"].eq(1)
        & endpoints["src"].ne(endpoints["tgt"])
    ].copy()
    if not cyclic.empty:
        eligible = eligible.merge(
            cyclic.assign(_cyclic=True), on=key_columns, how="left"
        )
        eligible = eligible[eligible["_cyclic"].isna()].drop(columns="_cyclic")
    classified = pd.concat(
        [cyclic[key_columns], eligible[key_columns]], ignore_index=True
    ).drop_duplicates()
    ambiguous = all_components.merge(
        classified.assign(_classified=True), on=key_columns, how="left"
    )
    ambiguous = ambiguous[ambiguous["_classified"].isna()][key_columns]
    return ComponentEligibility(
        eligible=eligible,
        cyclic=cyclic,
        ambiguous=ambiguous,
        token_roles=token_roles,
    )
