"""Canonical loading and coverage checks for exact transaction gas panels."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_route_transaction_gas(
    path: Path,
    *,
    required_routes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Load exact receipt gas prices and prove transaction/block coverage."""

    if not path.exists():
        raise FileNotFoundError(f"route transaction gas panel does not exist: {path}")
    panel = pd.read_parquet(path)
    required_columns = {
        "tx_hash",
        "block_number",
        "block_hash",
        "status",
        "gas_used",
        "realised_gas_cost_wei",
        "effective_gas_price_wei",
        "gas_gwei",
        "gas_price_supported",
        "gas_price_support_reason",
        "base_fee_per_gas_wei",
        "base_fee_gwei",
        "base_fee_supported",
        "base_fee_support_reason",
    }
    missing_columns = sorted(required_columns - set(panel.columns))
    if missing_columns:
        raise ValueError(f"route transaction gas panel misses columns: {missing_columns}")
    panel = panel.copy()
    panel["tx_hash"] = panel["tx_hash"].astype(str).str.lower()
    panel["block_number"] = pd.to_numeric(panel["block_number"], errors="raise").astype(
        "int64"
    )
    try:
        prices = [int(value) for value in panel["effective_gas_price_wei"]]
        gas_units = [int(value) for value in panel["gas_used"]]
        statuses = [int(value) for value in panel["status"]]
    except (TypeError, ValueError) as error:
        raise ValueError("route transaction gas panel has malformed receipt integers") from error
    panel["effective_gas_price_wei"] = prices
    panel["gas_used"] = gas_units
    panel["status"] = statuses
    if panel.empty or panel["tx_hash"].duplicated().any():
        raise ValueError("route transaction gas panel is empty or duplicates transactions")
    if any(price < 0 for price in prices):
        raise ValueError("route transaction gas panel has missing or negative prices")
    if any(gas_used <= 0 for gas_used in gas_units):
        raise ValueError("route transaction gas panel has missing or non-positive gas units")
    if not panel["gas_price_supported"].isin([True, False]).all():
        raise ValueError("route transaction gas support flags are not boolean")
    supported = panel["gas_price_supported"].astype(bool)
    expected_supported = pd.Series(
        [price > 0 for price in prices],
        index=panel.index,
    )
    if not supported.eq(expected_supported).all():
        raise ValueError("route transaction gas support disagrees with the receipt price")
    exact_costs: list[str | None] = []
    for raw_cost, gas_used, price, is_supported in zip(
        panel["realised_gas_cost_wei"],
        gas_units,
        prices,
        supported,
        strict=True,
    ):
        if not is_supported:
            if not pd.isna(raw_cost):
                raise ValueError("unsupported realised gas cost must remain missing")
            exact_costs.append(None)
            continue
        expected_cost = str(gas_used * price)
        if not isinstance(raw_cost, str) or raw_cost != expected_cost:
            raise ValueError("route transaction gas panel has inconsistent realised gas cost")
        exact_costs.append(expected_cost)
    panel["realised_gas_cost_wei"] = exact_costs
    block_hashes = panel["block_hash"].astype(str).str.lower()
    if not all(
        len(block_hash) == 66 and block_hash.startswith("0x")
        for block_hash in block_hashes
    ):
        raise ValueError("route transaction gas panel has malformed block hashes")
    panel["block_hash"] = block_hashes
    if any(status != 1 for status in statuses):
        raise ValueError("route transaction gas panel contains a failed transaction")
    gas_gwei = pd.to_numeric(panel["gas_gwei"], errors="coerce")
    if gas_gwei[supported].isna().any() or not gas_gwei[supported].gt(0).all():
        raise ValueError("supported route transaction gas prices are not positive")
    if gas_gwei[~supported].notna().any():
        raise ValueError("unsupported route transaction gas prices must remain missing")
    expected_gwei = pd.Series(
        [price / 1e9 if is_supported else None for price, is_supported in zip(prices, supported, strict=True)],
        index=panel.index,
        dtype="float64",
    )
    if not gas_gwei[supported].eq(expected_gwei[supported]).all():
        raise ValueError("route transaction gas gwei disagrees with the receipt price")
    expected_gas_reasons = pd.Series(
        [
            "receipt_effective_gas_price"
            if is_supported
            else "zero_effective_price_private_payment_possible"
            for is_supported in supported
        ],
        index=panel.index,
    )
    if not panel["gas_price_support_reason"].eq(expected_gas_reasons).all():
        raise ValueError("route transaction gas support reason is inconsistent")
    base_fee = pd.to_numeric(panel["base_fee_per_gas_wei"], errors="coerce")
    if not panel["base_fee_supported"].isin([True, False]).all():
        raise ValueError("same-block base-fee support flags are not boolean")
    base_supported = panel["base_fee_supported"].astype(bool)
    base_gwei = pd.to_numeric(panel["base_fee_gwei"], errors="coerce")
    if not base_supported.eq(base_fee.notna()).all():
        raise ValueError("same-block base-fee support disagrees with the block header")
    if base_fee[base_supported].isna().any() or base_fee[base_supported].lt(0).any():
        raise ValueError("supported same-block base fees are missing or negative")
    if base_fee[~base_supported].notna().any() or base_gwei[~base_supported].notna().any():
        raise ValueError("unsupported same-block base fees must remain missing")
    if base_gwei[base_supported].isna().any() or base_gwei[base_supported].lt(0).any():
        raise ValueError("supported same-block base fees are not nonnegative")
    if not base_gwei[base_supported].eq(base_fee[base_supported] / 1e9).all():
        raise ValueError("same-block base-fee gwei disagrees with the block header")
    expected_base_reasons = pd.Series(
        [
            "same_block_base_fee_per_gas"
            if is_supported
            else "pre_eip1559_block_no_base_fee"
            for is_supported in base_supported
        ],
        index=panel.index,
    )
    if not panel["base_fee_support_reason"].eq(expected_base_reasons).all():
        raise ValueError("same-block base-fee support reason is inconsistent")
    if required_routes is not None:
        expected = required_routes[["tx", "block"]].rename(
            columns={"tx": "tx_hash", "block": "block_number"}
        )
        expected["tx_hash"] = expected["tx_hash"].astype(str).str.lower()
        expected["block_number"] = pd.to_numeric(
            expected["block_number"], errors="raise"
        ).astype("int64")
        expected = expected.drop_duplicates()
        coverage = expected.merge(
            panel[["tx_hash", "block_number"]],
            on=["tx_hash", "block_number"],
            how="left",
            indicator=True,
            validate="one_to_one",
        )
        missing = int(coverage["_merge"].ne("both").sum())
        if missing:
            raise ValueError(f"route transaction gas panel misses {missing:,} exact routes")
    return panel.sort_values(["block_number", "tx_hash"]).reset_index(drop=True)
