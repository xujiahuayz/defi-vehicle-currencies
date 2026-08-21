"""Route-level receipt samples and gas-unit predictions.

The receipt records measure total transaction gas for transactions containing
one reconstructed route component.  They therefore include router bookkeeping
as well as pool execution.  The estimators below preserve that distinction:
they predict total gas from the transaction callee, ordered venue sequence, and
route complexity; they do not pretend to isolate a pool's marginal opcode cost.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ddvc.asset_types import canonical_token, classify
from ddvc.fetch.sources import DEX_SOURCES


ROUTE_GAS_COLUMNS = [
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
UNIFIED_ROUTE_COLUMNS = [
    "tx_hash",
    "component_id",
    "n_components",
    "source",
    "token_in",
    "token_out",
    "amount_usd",
    "log_index",
    "route_class",
]
SAMPLE_CELL_COLUMNS = ["year", "legs", "venue_sequence", "gas_vehicle"]


def route_gas_rows(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    """Return one row per linear, single-component route transaction."""

    missing = sorted(set(UNIFIED_ROUTE_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"unified route day lacks columns: {missing}")
    data = frame.loc[:, UNIFIED_ROUTE_COLUMNS].copy()
    for column in ("token_in", "token_out"):
        data[column] = data[column].map(lambda value: canonical_token(value) or "")
    data = data[
        data["token_in"].astype(bool)
        & data["token_out"].astype(bool)
        & data["source"].isin(DEX_SOURCES)
        & data["route_class"].isin(("single", "coherent"))
    ].copy()
    if data.empty:
        return pd.DataFrame(columns=ROUTE_GAS_COLUMNS)
    data["n_components"] = pd.to_numeric(data["n_components"], errors="coerce")
    data["amount_usd"] = pd.to_numeric(data["amount_usd"], errors="coerce")
    data = data.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    data["next_token_in"] = data.groupby("tx_hash", sort=False)["token_in"].shift(-1)
    data["next_tx_hash"] = data["tx_hash"].shift(-1)
    data["connected_leg"] = data["next_tx_hash"].ne(data["tx_hash"]) | data[
        "token_out"
    ].eq(data["next_token_in"])
    grouped = data.groupby("tx_hash", sort=False, dropna=False)
    routes = grouped.agg(
        component_count=("component_id", "nunique"),
        declared_components_min=("n_components", "min"),
        declared_components_max=("n_components", "max"),
        legs=("log_index", "size"),
        unique_log_indices=("log_index", "nunique"),
        route_class=("route_class", "first"),
        route_class_count=("route_class", "nunique"),
        connected=("connected_leg", "all"),
        venue_sequence=("source", lambda values: ">".join(values.astype(str))),
        first_mid=("token_out", "first"),
        first_value=("amount_usd", "first"),
        last_value=("amount_usd", "last"),
    ).reset_index()
    routes = routes[
        routes["component_count"].eq(1)
        & routes["declared_components_min"].eq(1)
        & routes["declared_components_max"].eq(1)
        & routes["legs"].isin((1, 2, 3))
        & routes["unique_log_indices"].eq(routes["legs"])
        & routes["route_class_count"].eq(1)
        & routes["connected"]
        & (
            (routes["legs"].eq(1) & routes["route_class"].eq("single"))
            | (routes["legs"].gt(1) & routes["route_class"].eq("coherent"))
        )
    ].copy()
    routes["route_notional_usd"] = routes[["first_value", "last_value"]].min(axis=1)
    routes = routes[
        routes["route_notional_usd"].gt(0)
        & np.isfinite(routes["route_notional_usd"])
    ].copy()
    routes["mid"] = np.select(
        [routes["legs"].eq(1), routes["legs"].eq(2)],
        [None, routes["first_mid"]],
        default="multi",
    )
    classifications = {
        mid: classify(mid)
        for mid in routes.loc[routes["legs"].eq(2), "mid"].dropna().unique()
    }
    routes["mid_symbol"] = routes["mid"].map(
        lambda mid: classifications.get(mid, (None, "multi"))[0]
    )
    routes["mid_type"] = np.select(
        [routes["legs"].eq(1), routes["legs"].eq(2)],
        ["direct", routes["mid"].map(lambda mid: classifications.get(mid, (None, "other"))[1])],
        default="multi",
    )
    routes["gas_vehicle"] = routes["mid"].where(
        routes["mid_symbol"].notna(), routes["mid_type"]
    )
    routes["date"] = pd.to_datetime(day, format="%Y%m%d")
    routes["day"] = day
    routes["year"] = int(day[:4])
    routes["tx_hash"] = routes["tx_hash"].astype(str).str.lower()
    return routes.loc[:, ROUTE_GAS_COLUMNS].reset_index(drop=True)


def deterministic_route_sample(frame: pd.DataFrame, per_cell: int = 25) -> pd.DataFrame:
    """Cap each comparison cell using the transaction hash's lexical order.

    Ethereum transaction hashes are already immutable transaction identifiers.
    Sorting those identifiers avoids an additional fingerprint or provenance
    layer while giving the same sample on every rerun.
    """

    if per_cell < 1:
        raise ValueError("per_cell must be positive")
    if frame.empty:
        return frame.copy()
    missing = sorted(set(SAMPLE_CELL_COLUMNS + ["tx_hash"]) - set(frame.columns))
    if missing:
        raise ValueError(f"route-gas sample lacks columns: {missing}")
    return (
        frame.sort_values(SAMPLE_CELL_COLUMNS + ["tx_hash"], kind="stable")
        .groupby(SAMPLE_CELL_COLUMNS, group_keys=False, dropna=False)
        .head(per_cell)
        .sort_values(["day", "tx_hash"], kind="stable")
        .reset_index(drop=True)
    )


def router_classes(addresses: pd.Series, *, common: set[str] | None = None) -> pd.Series:
    """Pool low-frequency transaction callees into one router class."""

    normalized = addresses.astype("string").str.lower().fillna("")
    if common is None:
        counts = normalized[normalized.ne("")].value_counts()
        common = set(counts[counts.ge(40)].index.astype(str))
    return normalized.where(normalized.isin(common), "other_router")


def gas_features(frame: pd.DataFrame, *, common_routers: set[str] | None = None) -> pd.DataFrame:
    """Normalize the explanatory cells used for receipt-gas prediction."""

    required = {"year", "legs", "venue_sequence", "tx_to"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"gas feature frame lacks columns: {missing}")
    data = frame.copy()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    data["legs"] = pd.to_numeric(data["legs"], errors="raise").astype(int)
    data["venue_sequence"] = (
        data["venue_sequence"].astype("string").str.replace("|", ">", regex=False)
    )
    data["router_class"] = router_classes(data["tx_to"], common=common_routers)
    data["unique_venues"] = data["venue_sequence"].str.split(">").map(
        lambda values: len(set(values))
    )
    data["cross_venue"] = data["unique_venues"].gt(1)
    return data


@dataclass(frozen=True)
class GasPrediction:
    median: np.ndarray
    p25: np.ndarray
    p75: np.ndarray
    support: np.ndarray


class RouteGasEstimator:
    """Hierarchical cell medians for total transaction gas."""

    LEVELS = (
        ("year_router_ordered_venues", ("year", "router_class", "legs", "venue_sequence"), 8),
        ("router_ordered_venues", ("router_class", "legs", "venue_sequence"), 8),
        ("year_ordered_venues", ("year", "legs", "venue_sequence"), 8),
        ("ordered_venues", ("legs", "venue_sequence"), 8),
        ("year_router_complexity", ("year", "router_class", "legs", "cross_venue"), 12),
        ("year_complexity", ("year", "legs", "cross_venue"), 12),
        ("route_complexity", ("legs", "cross_venue"), 12),
        ("legs", ("legs",), 12),
    )

    def __init__(self, training: pd.DataFrame):
        required = {"gas_used", "tx_to", "year", "legs", "venue_sequence"}
        missing = sorted(required - set(training.columns))
        if missing:
            raise ValueError(f"receipt-gas training panel lacks columns: {missing}")
        counts = training["tx_to"].astype("string").str.lower().value_counts()
        self.common_routers = set(counts[counts.ge(40)].index.astype(str))
        data = gas_features(training, common_routers=self.common_routers)
        data["gas_used"] = pd.to_numeric(data["gas_used"], errors="coerce")
        data = data[
            data["gas_used"].gt(0) & np.isfinite(data["gas_used"])
        ].copy()
        if len(data) < 500:
            raise ValueError("receipt-gas training panel has insufficient support")
        self.lookups: list[tuple[str, tuple[str, ...], pd.DataFrame]] = []
        for name, keys, minimum in self.LEVELS:
            lookup = data.groupby(list(keys), dropna=False)["gas_used"].agg(
                observations="size",
                gas_median="median",
                gas_p25=lambda values: values.quantile(0.25),
                gas_p75=lambda values: values.quantile(0.75),
            ).reset_index()
            lookup = lookup[lookup["observations"].ge(minimum)].copy()
            self.lookups.append((name, keys, lookup))

    def predict(self, frame: pd.DataFrame) -> GasPrediction:
        query = gas_features(frame, common_routers=self.common_routers).reset_index(drop=True)
        query["_row"] = np.arange(len(query))
        out = pd.DataFrame(
            {
                "gas_median": np.nan,
                "gas_p25": np.nan,
                "gas_p75": np.nan,
                "support": pd.Series([None] * len(query), dtype="object"),
            }
        )
        for name, keys, lookup in self.lookups:
            unresolved = out["gas_median"].isna()
            if not unresolved.any():
                break
            matches = query.loc[unresolved, ["_row", *keys]].merge(
                lookup, on=list(keys), how="left", validate="many_to_one"
            )
            matches = matches[matches["gas_median"].notna()]
            if matches.empty:
                continue
            rows = matches["_row"].astype(int).to_numpy()
            out.loc[rows, ["gas_median", "gas_p25", "gas_p75"]] = matches[
                ["gas_median", "gas_p25", "gas_p75"]
            ].to_numpy()
            out.loc[rows, "support"] = name
        if out["gas_median"].isna().any():
            raise ValueError("gas estimator left routes without a supported prediction")
        return GasPrediction(
            median=out["gas_median"].to_numpy(dtype=float),
            p25=out["gas_p25"].to_numpy(dtype=float),
            p75=out["gas_p75"].to_numpy(dtype=float),
            support=out["support"].astype(str).to_numpy(),
        )
