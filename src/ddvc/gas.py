"""Canonical loading and coverage checks for exact transaction gas panels."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import zip_longest
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ddvc.ethereum_blocks import iter_block_header_snapshot
from ddvc.ethereum_receipts import iter_receipt_snapshot


def _exact_integer(value: object) -> int:
    """Parse one persisted integer without accepting truncation or nonfinite values."""

    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError
    return int(parsed)


def validate_route_transaction_gas_frame(
    panel: pd.DataFrame,
    *,
    required_routes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Validate one bounded exact-gas frame and optional matching route perimeter."""

    required_columns = {
        "tx_hash",
        "block_number",
        "block_hash",
        "block_timestamp_utc",
        "status",
        "gas_used",
        "execution_gas_cost_wei",
        "blob_gas_used",
        "blob_gas_price_wei",
        "blob_gas_cost_wei",
        "receipt_total_gas_cost_wei",
        "receipt_gas_cost_scope",
        "off_receipt_payment_status",
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
    try:
        block_numbers = [_exact_integer(value) for value in panel["block_number"]]
        block_timestamps = [
            _exact_integer(value) for value in panel["block_timestamp_utc"]
        ]
        prices = [_exact_integer(value) for value in panel["effective_gas_price_wei"]]
        gas_units = [_exact_integer(value) for value in panel["gas_used"]]
        statuses = [_exact_integer(value) for value in panel["status"]]
    except ValueError as error:
        raise ValueError("route transaction gas panel has malformed receipt integers") from error
    panel["block_number"] = block_numbers
    panel["block_timestamp_utc"] = block_timestamps
    panel["effective_gas_price_wei"] = prices
    panel["gas_used"] = gas_units
    panel["status"] = statuses
    if panel.empty or panel["tx_hash"].duplicated().any():
        raise ValueError("route transaction gas panel is empty or duplicates transactions")
    if any(price < 0 for price in prices):
        raise ValueError("route transaction gas panel has missing or negative prices")
    if any(gas_used <= 0 for gas_used in gas_units):
        raise ValueError("route transaction gas panel has missing or non-positive gas units")
    if any(timestamp <= 0 for timestamp in block_timestamps):
        raise ValueError("route transaction gas panel has invalid block timestamps")
    if not panel["gas_price_supported"].isin([True, False]).all():
        raise ValueError("route transaction gas support flags are not boolean")
    supported = panel["gas_price_supported"].astype(bool)
    expected_supported = pd.Series(
        [price > 0 for price in prices],
        index=panel.index,
    )
    if not supported.eq(expected_supported).all():
        raise ValueError("route transaction gas support disagrees with the receipt price")
    execution_costs: list[str | None] = []
    for raw_cost, gas_used, price, is_supported in zip(
        panel["execution_gas_cost_wei"],
        gas_units,
        prices,
        supported,
        strict=True,
    ):
        if not is_supported:
            if not pd.isna(raw_cost):
                raise ValueError("unsupported execution gas cost must remain missing")
            execution_costs.append(None)
            continue
        expected_cost = str(gas_used * price)
        if not isinstance(raw_cost, str) or raw_cost != expected_cost:
            raise ValueError("route transaction gas panel has inconsistent execution gas cost")
        execution_costs.append(expected_cost)
    panel["execution_gas_cost_wei"] = execution_costs
    blob_units: list[int | None] = []
    blob_prices: list[int | None] = []
    blob_costs: list[str] = []
    total_costs: list[str | None] = []
    for raw_units, raw_price, raw_blob_cost, raw_total, execution in zip(
        panel["blob_gas_used"],
        panel["blob_gas_price_wei"],
        panel["blob_gas_cost_wei"],
        panel["receipt_total_gas_cost_wei"],
        execution_costs,
        strict=True,
    ):
        absent = pd.isna(raw_units) and pd.isna(raw_price)
        if absent:
            units = price = None
            expected_blob = "0"
        elif pd.isna(raw_units) or pd.isna(raw_price):
            raise ValueError("route transaction gas panel has incomplete blob gas fields")
        else:
            try:
                units = _exact_integer(raw_units)
                price = _exact_integer(raw_price)
            except ValueError as error:
                raise ValueError("route transaction gas panel has malformed blob gas fields") from error
            if units < 0 or price < 0:
                raise ValueError("route transaction gas panel has negative blob gas fields")
            expected_blob = str(units * price)
        if not isinstance(raw_blob_cost, str) or raw_blob_cost != expected_blob:
            raise ValueError("route transaction gas panel has inconsistent blob gas cost")
        expected_total = (
            str(int(execution) + int(expected_blob)) if execution is not None else None
        )
        if raw_total != expected_total and not (
            expected_total is None and pd.isna(raw_total)
        ):
            raise ValueError("route transaction gas panel has inconsistent receipt total gas cost")
        blob_units.append(units)
        blob_prices.append(price)
        blob_costs.append(expected_blob)
        total_costs.append(expected_total)
    panel["blob_gas_used"] = blob_units
    panel["blob_gas_price_wei"] = blob_prices
    panel["blob_gas_cost_wei"] = blob_costs
    panel["receipt_total_gas_cost_wei"] = total_costs
    if not panel["receipt_gas_cost_scope"].eq(
        "execution_plus_blob_receipt_fields"
    ).all():
        raise ValueError("route transaction gas panel has an invalid receipt cost scope")
    if not panel["off_receipt_payment_status"].eq(
        "private_bundle_or_direct_block_beneficiary_payments_unobserved"
    ).all():
        raise ValueError("route transaction gas panel overstates off-receipt payment coverage")
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
    base_fee_values: list[int | None] = []
    for value in panel["base_fee_per_gas_wei"]:
        if pd.isna(value):
            base_fee_values.append(None)
            continue
        try:
            base_fee_values.append(_exact_integer(value))
        except ValueError as error:
            raise ValueError("same-block base-fee panel has a malformed integer") from error
    base_fee = pd.Series(base_fee_values, index=panel.index, dtype="Int64")
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
        try:
            expected["block_number"] = [
                _exact_integer(value) for value in expected["block_number"]
            ]
        except ValueError as error:
            raise ValueError("required routes contain malformed block numbers") from error
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


def load_route_transaction_gas(path: Path, *, required_routes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Load exact receipt gas prices and prove transaction/block coverage."""

    if not path.exists():
        raise FileNotFoundError(f"route transaction gas panel does not exist: {path}")
    return validate_route_transaction_gas_frame(pd.read_parquet(path), required_routes=required_routes)


def _copied_field_matches(panel_row: dict[str, object], evidence_row: dict[str, object], mapping: dict[str, str]) -> bool:
    for evidence_field, panel_field in mapping.items():
        panel_value = panel_row.get(panel_field)
        if pd.isna(panel_value):
            panel_value = None
        if panel_value != evidence_row.get(evidence_field):
            return False
    return True


def validate_route_transaction_gas_release(path: Path, required_routes: pd.DataFrame, *, receipt_snapshot: Path, block_header_snapshot: Path, batch_size: int = 5_000) -> dict[str, int]:
    """Stream Parquet beside exact receipt and header evidence and compare every copied field."""

    if batch_size < 1:
        raise ValueError("route transaction gas validation batch size must be positive")
    if not path.exists():
        raise FileNotFoundError(f"route transaction gas panel does not exist: {path}")
    release_evidence_columns = {"tx_to", "tx_from", "parent_hash"}
    missing_release_columns = sorted(release_evidence_columns - set(pq.ParquetFile(path).schema_arrow.names))
    if missing_release_columns:
        raise ValueError(f"route transaction gas release misses copied evidence columns: {missing_release_columns}")
    expected = required_routes[["tx_hash", "block_number"]].copy()
    expected["tx_hash"] = expected["tx_hash"].astype(str).str.lower()
    try:
        expected["block_number"] = [_exact_integer(value) for value in expected["block_number"]]
    except ValueError as error:
        raise ValueError("required routes contain malformed block numbers") from error
    if expected.empty or expected["tx_hash"].duplicated().any():
        raise ValueError("required route transaction perimeter is empty or duplicated")
    expected = expected.sort_values(["block_number", "tx_hash"]).reset_index(drop=True)
    expected_rows = expected.itertuples(index=False, name=None)

    def actual_rows():
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=batch_size):
            original = batch.to_pandas()
            validated = validate_route_transaction_gas_frame(original)
            original_keys = list(zip(original["block_number"], original["tx_hash"], strict=True))
            validated_keys = list(zip(validated["block_number"], validated["tx_hash"], strict=True))
            if original_keys != validated_keys:
                raise ValueError("route transaction gas panel is not strictly ordered")
            yield from validated.to_dict("records")

    sentinel = object()
    rows = 0
    previous: tuple[int, str] | None = None
    receipts = iter_receipt_snapshot(receipt_snapshot, require_evidence=True, order_by_block=True)
    headers = iter_block_header_snapshot(block_header_snapshot, require_evidence=True)
    current_header: object = next(headers, sentinel)
    receipt_mapping = {"tx_hash": "tx_hash", "block_number": "block_number", "block_hash": "block_hash", "gas_used": "gas_used", "status": "status", "tx_to": "tx_to", "tx_from": "tx_from", "effective_gas_price_wei": "effective_gas_price_wei", "blob_gas_used": "blob_gas_used", "blob_gas_price_wei": "blob_gas_price_wei"}
    header_mapping = {"block_number": "block_number", "block_hash": "block_hash", "parent_hash": "parent_hash", "timestamp": "block_timestamp_utc", "base_fee_per_gas_wei": "base_fee_per_gas_wei"}
    for expected_row, actual_row, receipt_row in zip_longest(expected_rows, actual_rows(), receipts, fillvalue=sentinel):
        if expected_row is sentinel or actual_row is sentinel or receipt_row is sentinel:
            raise ValueError("route transaction gas panel differs from the exact route perimeter")
        current = int(actual_row["block_number"]), str(actual_row["tx_hash"]).lower()
        if tuple(expected_row) != (current[1], current[0]) or (int(receipt_row["block_number"]), str(receipt_row["tx_hash"]).lower()) != current:
            raise ValueError("route transaction gas panel differs from the exact route perimeter")
        if previous is not None and current <= previous:
            raise ValueError("route transaction gas panel is duplicated or not strictly ordered")
        if not _copied_field_matches(actual_row, receipt_row, receipt_mapping):
            raise ValueError("route transaction gas panel differs from exact receipt evidence")
        if previous is not None and current[0] != previous[0]:
            current_header = next(headers, sentinel)
        if current_header is sentinel or int(current_header["block_number"]) != current[0] or not _copied_field_matches(actual_row, current_header, header_mapping):
            raise ValueError("route transaction gas panel differs from exact block-header evidence")
        previous = current
        rows += 1
    if current_header is not sentinel:
        current_header = next(headers, sentinel)
    if current_header is not sentinel:
        raise ValueError("block-header evidence exceeds the route transaction perimeter")
    return {"rows": rows}
