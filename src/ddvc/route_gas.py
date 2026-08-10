"""Pure candidate construction and deterministic sampling for route-gas measurement."""

from __future__ import annotations

import hashlib
import math

import pandas as pd

from ddvc.asset_types import canonical_token, classify
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.route_roles import component_eligibility, component_notional

SUPPORTED_VENUES = frozenset(DEX_SOURCES)
REQUIRED_COLUMNS = [
    "tx_hash",
    "block_number",
    "component_id",
    "n_components",
    "source",
    "token_in",
    "token_out",
    "amount_usd",
    "log_index",
    "route_class",
]
SAMPLE_CELLS = ["year", "legs", "venue_sequence", "gas_vehicle"]
GAS_REQUEST_COLUMNS = [
    "year",
    "legs",
    "venue_sequence",
    "gas_vehicle",
    "mid_type",
]
GAS_SUPPORT_LEVELS = (
    ("year_venue_vehicle", ["year", "legs", "venue_sequence", "gas_vehicle"]),
    ("year_venue_type", ["year", "legs", "venue_sequence", "mid_type"]),
    ("year_venue", ["year", "legs", "venue_sequence"]),
    ("year_type", ["year", "legs", "mid_type"]),
    ("year_topology", ["year", "legs"]),
    ("topology", ["legs"]),
)
GAS_ESTIMATE_COLUMNS = [
    "gas_units_median",
    "gas_units_p25",
    "gas_units_p75",
    "gas_support_level",
    "gas_support_cells",
    "gas_support_transactions",
]
CANDIDATE_COLUMNS = [
    "date",
    "day",
    "year",
    "tx_hash",
    "block_number",
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
    clean = frame.copy()
    clean["token_in"] = clean["token_in"].map(lambda value: canonical_token(value) or "")
    clean["token_out"] = clean["token_out"].map(lambda value: canonical_token(value) or "")
    clean = clean[
        clean["token_in"].astype(bool)
        & clean["token_out"].astype(bool)
        & clean["route_class"].isin(["single", "coherent"])
    ]
    if clean.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    keys = ["tx_hash", "component_id"]
    eligibility = component_eligibility(clean, keys=keys)
    eligible_keys = set(eligibility.eligible[keys].itertuples(index=False, name=None))
    intermediary_tokens = {
        key: set(group["token"])
        for key, group in eligibility.token_roles[
            eligibility.token_roles["role"].eq("intermediate")
        ].groupby(keys, sort=False)
    }
    notionals = component_notional(
        clean, keys=keys, token_roles=eligibility.token_roles
    ).set_index(keys)["amount_usd"].to_dict()

    rows = []
    for tx_hash, group in clean.groupby("tx_hash", sort=False):
        if not group["source"].isin(SUPPORTED_VENUES).all():
            continue
        if group["component_id"].nunique() != 1:
            continue
        block_numbers = pd.to_numeric(group["block_number"], errors="coerce").dropna()
        if block_numbers.nunique() != 1 or int(block_numbers.iloc[0]) < 0:
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
        component_key = (tx_hash, ordered.iloc[0]["component_id"])
        if component_key not in eligible_keys:
            continue
        connected = all(
            left == right
            for left, right in zip(
                ordered["token_out"].iloc[:-1],
                ordered["token_in"].iloc[1:],
                strict=True,
            )
        )
        if not connected:
            continue
        intermediaries = intermediary_tokens.get(component_key, set())
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
        route_notional = float(notionals.get(component_key, float("nan")))
        if not math.isfinite(route_notional) or route_notional <= 0:
            continue
        rows.append(
            {
                "date": pd.to_datetime(day, format="%Y%m%d"),
                "day": day,
                "year": int(day[:4]),
                "tx_hash": str(tx_hash).lower(),
                "block_number": int(block_numbers.iloc[0]),
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


def _gas_sample_cells(panel: pd.DataFrame) -> pd.DataFrame:
    """Collapse the capped receipt sample to its prespecified sampling cells."""
    required = set(GAS_REQUEST_COLUMNS + ["gas_used", "status"])
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"route-gas panel is missing columns: {', '.join(missing)}")
    valid = panel[
        panel["status"].eq(1)
        & pd.to_numeric(panel["gas_used"], errors="coerce").gt(0)
    ].copy()
    if valid.empty:
        raise ValueError("route-gas panel has no successful positive-gas receipts")
    return valid.groupby(SAMPLE_CELLS, as_index=False, dropna=False).agg(
        mid_type=("mid_type", "first"),
        gas_units_median=("gas_used", "median"),
        gas_units_p25=("gas_used", lambda values: values.quantile(0.25)),
        gas_units_p75=("gas_used", lambda values: values.quantile(0.75)),
        gas_support_transactions=("gas_used", "size"),
    )


def _gas_level_lookup(
    cells: pd.DataFrame, level: str, keys: list[str]
) -> pd.DataFrame:
    """Build one cell-balanced fallback level for route-gas estimation."""
    if keys == SAMPLE_CELLS:
        exact = cells.copy()
        exact["gas_support_cells"] = 1
        exact["gas_support_level"] = level
        return exact[keys + GAS_ESTIMATE_COLUMNS]
    lookup = cells.groupby(keys, as_index=False, dropna=False).agg(
        gas_units_median=("gas_units_median", "median"),
        gas_units_p25=("gas_units_p25", "median"),
        gas_units_p75=("gas_units_p75", "median"),
        gas_support_cells=("gas_units_median", "size"),
        gas_support_transactions=("gas_support_transactions", "sum"),
    )
    lookup["gas_support_level"] = level
    return lookup[keys + GAS_ESTIMATE_COLUMNS]


def estimate_route_gas(
    requests: pd.DataFrame, receipt_panel: pd.DataFrame
) -> pd.DataFrame:
    """Estimate gas units with explicit exact-cell-to-topology fallback support.

    The deterministic receipt sample is capped within year, topology, venue
    sequence and intermediary cells. Broader fallbacks therefore aggregate cell
    medians, not raw transactions, so vehicles with more selected receipts do not
    receive accidental extra weight.
    """
    missing = sorted(set(GAS_REQUEST_COLUMNS) - set(requests.columns))
    if missing:
        raise ValueError(f"route-gas requests are missing columns: {', '.join(missing)}")
    cells = _gas_sample_cells(receipt_panel)
    query = requests[GAS_REQUEST_COLUMNS].reset_index(drop=True).copy()
    query["_gas_row"] = range(len(query))
    result = pd.DataFrame(index=range(len(query)))
    for column in GAS_ESTIMATE_COLUMNS:
        result[column] = pd.NA if column == "gas_support_level" else float("nan")
    for level, keys in GAS_SUPPORT_LEVELS:
        unresolved = result["gas_units_median"].isna()
        if not unresolved.any():
            break
        lookup = _gas_level_lookup(cells, level, keys)
        matches = query.loc[unresolved, ["_gas_row", *keys]].merge(
            lookup,
            on=keys,
            how="left",
            validate="many_to_one",
        )
        matches = matches[matches["gas_units_median"].notna()]
        if matches.empty:
            continue
        rows = matches["_gas_row"].astype(int).to_numpy()
        result.loc[rows, GAS_ESTIMATE_COLUMNS] = matches[
            GAS_ESTIMATE_COLUMNS
        ].to_numpy()
    result.index = requests.index
    return result
