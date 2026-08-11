"""Canonical membership, outcome, and support contract for dominance-cost pairs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ddvc.asset_types import VEHICLE_CANDIDATES, WETH
from ddvc.route_cost import QUOTE_CELL_KEYS


COMPARATOR_SYMBOLS = ("USDC", "USDT", "DAI", "WBTC")
COMPARATOR_VEHICLES = {
    address: symbol
    for address, symbol in VEHICLE_CANDIDATES.items()
    if symbol in COMPARATOR_SYMBOLS
}
if set(COMPARATOR_VEHICLES.values()) != set(COMPARATOR_SYMBOLS):
    raise RuntimeError("dominance-cost comparator addresses are incomplete")

QUOTE_CELL_WITHOUT_VEHICLE = tuple(key for key in QUOTE_CELL_KEYS if key != "vehicle")
if len(QUOTE_CELL_WITHOUT_VEHICLE) != len(QUOTE_CELL_KEYS) - 1:
    raise RuntimeError("route-cost cell contract contains no unique vehicle field")

PAIR_CELL_KEYS = (*QUOTE_CELL_WITHOUT_VEHICLE, "comparator")
PAIR_MEMBER_EQUAL_FIELDS = (*QUOTE_CELL_WITHOUT_VEHICLE, "method", "direct_available", "direct_output_usd", "direct_source", "direct_pool")
SUPPORT_STRATA_KEYS = ("date", "comparator", "trade_size_usd")
SUPPORT_STAGES = (
    "candidate_pair_attempted",
    "both_indirect_available",
    "positive_finite_indirect_outputs",
    "direct_available",
    "positive_finite_direct_output",
)
OUTCOME_COLUMNS = (
    "weth_symmetric_output_edge_bps",
    "weth_output_gain_bps_of_notional",
    "weth_log_output_ratio",
    "weth_signed_win",
    "weth_direct_threshold_edge",
)
OUTCOME_REQUIRED_SUPPORT_STAGE = {
    "weth_symmetric_output_edge_bps": "positive_finite_indirect_outputs",
    "weth_output_gain_bps_of_notional": "positive_finite_indirect_outputs",
    "weth_log_output_ratio": "positive_finite_indirect_outputs",
    "weth_signed_win": "positive_finite_indirect_outputs",
    "weth_direct_threshold_edge": "positive_finite_direct_output",
}
if set(OUTCOME_REQUIRED_SUPPORT_STAGE) != set(OUTCOME_COLUMNS):
    raise RuntimeError("dominance-cost outcome support ownership is incomplete")


def comparator_symbol(address: object) -> str:
    """Return the prespecified comparator symbol for one canonical address."""

    token = str(address).lower()
    try:
        return COMPARATOR_VEHICLES[token]
    except KeyError as error:
        raise ValueError(f"dominance-cost comparator is outside the locked set: {address}") from error


def _same_value(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        if math.isnan(float(left)) and math.isnan(float(right)):
            return True
    except (TypeError, ValueError):
        pass
    return bool(left == right)


def validate_pair_members(weth_row: Mapping[str, Any], comparator_row: Mapping[str, Any]) -> str:
    """Validate two independently quoted rows before they become one economic pair."""

    required = {*PAIR_MEMBER_EQUAL_FIELDS, "vehicle"}
    for label, row in (("WETH", weth_row), ("comparator", comparator_row)):
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"dominance-cost {label} row lacks fields: {missing}")
    if str(weth_row["vehicle"]).lower() != NATIVE_VEHICLE:
        raise ValueError("dominance-cost native pair member is not WETH")
    symbol = comparator_symbol(comparator_row["vehicle"])
    mismatches = [field for field in PAIR_MEMBER_EQUAL_FIELDS if not _same_value(weth_row[field], comparator_row[field])]
    if mismatches:
        raise ValueError(f"dominance-cost pair members disagree on common quote fields: {mismatches}")
    method = weth_row["method"]
    if not isinstance(method, str) or not method.strip():
        raise ValueError("dominance-cost quote method must be one nonempty asserted value")
    return symbol


def validate_support_counts(counts: Mapping[str, object]) -> None:
    """Require each support stage to be a nested subset of its predecessor."""

    missing = sorted(set(SUPPORT_STAGES) - set(counts))
    if missing:
        raise ValueError(f"dominance-cost support ledger lacks stages: {missing}")
    values: list[int] = []
    for stage in SUPPORT_STAGES:
        value = counts[stage]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"dominance-cost support count is invalid for {stage}")
        values.append(value)
    if any(current > prior for prior, current in zip(values, values[1:])):
        raise ValueError("dominance-cost support stages are not nested")


def dominance_outcomes(
    *,
    weth_output_usd: object,
    comparator_output_usd: object,
    trade_size_usd: object,
    direct_output_usd: object | None,
) -> Mapping[str, float | int | None]:
    """Compute bounded primary and separately named magnitude/tail outcomes."""

    weth = float(weth_output_usd)
    comparator = float(comparator_output_usd)
    notional = float(trade_size_usd)
    if not all(math.isfinite(value) and value > 0 for value in (weth, comparator, notional)):
        raise ValueError("dominance-cost indirect outputs and notional must be finite and positive")
    denominator = weth + comparator
    symmetric = 20_000.0 * (weth - comparator) / denominator
    if not math.isfinite(symmetric) or abs(symmetric) > 20_000.0:
        raise ValueError("dominance-cost symmetric edge violated its finite bound")
    signed_win = int(weth > comparator) - int(comparator > weth)
    direct: float | None
    if direct_output_usd is None:
        direct = None
    else:
        direct = float(direct_output_usd)
        if not math.isfinite(direct) or direct <= 0:
            raise ValueError("dominance-cost direct output must be absent or finite and positive")
    threshold_edge = None if direct is None else int(weth > direct) - int(comparator > direct)
    return {
        "weth_symmetric_output_edge_bps": symmetric,
        "weth_output_gain_bps_of_notional": 10_000.0 * (weth - comparator) / notional,
        "weth_log_output_ratio": math.log(weth) - math.log(comparator),
        "weth_signed_win": signed_win,
        "weth_direct_threshold_edge": threshold_edge,
    }


NATIVE_VEHICLE = WETH
