"""Canonical membership, outcome, and support contract for dominance-cost pairs."""

from __future__ import annotations

import math
from collections.abc import Mapping

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


def comparator_symbol(address: object) -> str:
    """Return the prespecified comparator symbol for one canonical address."""

    token = str(address).lower()
    try:
        return COMPARATOR_VEHICLES[token]
    except KeyError as error:
        raise ValueError(f"dominance-cost comparator is outside the locked set: {address}") from error


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
            direct = None
    threshold_edge = None if direct is None else int(direct > comparator) - int(direct > weth)
    return {
        "weth_symmetric_output_edge_bps": symmetric,
        "weth_output_gain_bps_of_notional": 10_000.0 * (weth - comparator) / notional,
        "weth_log_output_ratio": math.log(weth / comparator),
        "weth_signed_win": signed_win,
        "weth_direct_threshold_edge": threshold_edge,
    }


NATIVE_VEHICLE = WETH
