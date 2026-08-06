"""Canonical token-role values within reconstructed route components."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


ROUTE_KEYS = ("tx_hash", "component_id")
VALUE_SUPPORT_BANDS = {
    "within_2x": (0.5, 2.0),
    "within_20pct": (0.8, 1.2),
}
VALUE_SUPPORT_COLUMNS = tuple(VALUE_SUPPORT_BANDS)
VALUE_SUPPORT_SCOPES = ("all_routes", *VALUE_SUPPORT_COLUMNS)


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


def token_flow_values(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
    token_roles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Sum input- and output-side dollars for every component-token."""
    key_columns = list(keys)
    required = set(key_columns + ["token_in", "token_out", "amount_usd"])
    missing = sorted(required - set(legs.columns))
    if missing:
        raise ValueError(f"route-token flows are missing columns: {', '.join(missing)}")
    roles = token_roles if token_roles is not None else topological_token_roles(legs, keys=key_columns)
    input_side = legs[key_columns + ["token_in", "amount_usd"]].rename(
        columns={"token_in": "token", "amount_usd": "input_side_usd"}
    )
    output_side = legs[key_columns + ["token_out", "amount_usd"]].rename(
        columns={"token_out": "token", "amount_usd": "output_side_usd"}
    )
    flows = pd.concat([input_side, output_side], ignore_index=True)
    for column in ("input_side_usd", "output_side_usd"):
        flows[column] = pd.to_numeric(flows[column], errors="coerce")
    flows = flows.groupby(key_columns + ["token"], as_index=False).agg(
        input_side_usd=("input_side_usd", "sum"),
        output_side_usd=("output_side_usd", "sum"),
    )
    return flows.merge(roles, on=key_columns + ["token"], how="inner")


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
    if role not in {"source", "sink", "intermediate"}:
        raise ValueError(f"unsupported route role: {role}")
    values = token_flow_values(legs, keys=key_columns, token_roles=token_roles)
    values = values[values["role"].eq(role)].copy()
    if values.empty:
        return pd.DataFrame(columns=[*key_columns, "token", "amount_usd"])
    if role == "source":
        values["amount_usd"] = values["input_side_usd"] - values["output_side_usd"]
    elif role == "sink":
        values["amount_usd"] = values["output_side_usd"] - values["input_side_usd"]
    elif role == "intermediate":
        values["amount_usd"] = (values["input_side_usd"] + values["output_side_usd"]) / 2
    return values[key_columns + ["token", "amount_usd"]]


def component_value_support(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
    token_roles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Audit dollar-flow coherence without letting dollars define route identity.

    Source-to-sink value must reconcile, and every intermediary's total outgoing
    value must reconcile with its total incoming value. Summing by token before
    testing preserves valid split and join routes. The nested bands match the
    project's transaction-size support convention.
    """
    key_columns = list(keys)
    flows = token_flow_values(legs, keys=key_columns, token_roles=token_roles)
    sources = flows[flows["role"].eq("source")].groupby(key_columns, as_index=False).agg(
        source_usd=("input_side_usd", "sum")
    )
    sinks = flows[flows["role"].eq("sink")].groupby(key_columns, as_index=False).agg(
        sink_usd=("output_side_usd", "sum")
    )
    out = sources.merge(sinks, on=key_columns, how="inner")
    intermediates = flows[flows["role"].eq("intermediate")].copy()
    intermediates["value_ratio"] = (
        intermediates["input_side_usd"] / intermediates["output_side_usd"]
    )
    intermediates["value_positive"] = (
        intermediates["input_side_usd"].gt(0)
        & intermediates["output_side_usd"].gt(0)
    )
    intermediate_bounds = intermediates.groupby(key_columns, as_index=False).agg(
        intermediate_ratio_min=("value_ratio", "min"),
        intermediate_ratio_max=("value_ratio", "max"),
        intermediate_values_positive=("value_positive", "all"),
    )
    out = out.merge(intermediate_bounds, on=key_columns, how="left")
    out[["intermediate_ratio_min", "intermediate_ratio_max"]] = out[
        ["intermediate_ratio_min", "intermediate_ratio_max"]
    ].fillna(1.0)
    out["intermediate_values_positive"] = out[
        "intermediate_values_positive"
    ].fillna(True).astype(bool)
    out["endpoint_value_ratio"] = out["sink_usd"] / out["source_usd"]
    out["value_ratio_min"] = out[
        ["endpoint_value_ratio", "intermediate_ratio_min"]
    ].min(axis=1)
    out["value_ratio_max"] = out[
        ["endpoint_value_ratio", "intermediate_ratio_max"]
    ].max(axis=1)
    positive = out["source_usd"].gt(0) & out["sink_usd"].gt(0)
    for label, (lower, upper) in VALUE_SUPPORT_BANDS.items():
        out[label] = (
            positive
            & out["intermediate_values_positive"]
            & out["value_ratio_min"].ge(lower)
            & out["value_ratio_max"].le(upper)
        )
    out["amount_usd"] = (out["source_usd"] + out["sink_usd"]) / 2
    return out


def component_notional(
    legs: pd.DataFrame,
    *,
    keys: Sequence[str] = ROUTE_KEYS,
    token_roles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return one component notional as the mean of total source and sink flow."""
    key_columns = list(keys)
    return component_value_support(
        legs, keys=key_columns, token_roles=token_roles
    )[key_columns + ["amount_usd"]]


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
