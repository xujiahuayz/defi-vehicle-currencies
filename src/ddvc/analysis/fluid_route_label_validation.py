"""Exact receipt checks for Fluid route labels.

Fluid enters the route panel through Dune's ``dex.trades`` table.  The checks
below use the transaction receipt instead: the log selected by Dune's event
index must be the Fluid pool's swap event, and independent ERC-20 Transfer
logs must carry the labelled input and output tokens in the labelled amounts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.ethereum_receipts import receipt_payload
from ddvc.quoter import coerce_rpc_envelope, rpc_post, validate_rpc_attempts
from ddvc.runtime import atomic_output


FLUID_SWAP_TOPIC = (
    "0xdc004dbca4ef9c966218431ee5d9133d337ad018dd5b5c5493722803f75c64f7"
)
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
CONSTANTS_VIEW_SELECTOR = "0xb7791bf2"
FLUID_NATIVE_ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
HALF_YEARS = ("2024H2", "2025H1", "2025H2", "2026H1")
SAMPLE_COUNTS = {
    "cross_venue": {"high_value": 20, "rank_spread": 10},
    "fluid_only": {"high_value": 10, "rank_spread": 5},
}


def parse_complete_receipt(
    tx_hash: str,
    response: object,
    *,
    expected_block: int,
) -> dict[str, object] | None:
    """Normalize a complete receipt while retaining legal zero-topic logs.

    Some Fluid transactions contain anonymous events.  Ethereum permits those
    logs, so excluding them would turn an otherwise complete receipt into a
    false retrieval failure.
    """

    if not isinstance(response, dict) or response.get("error"):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    try:
        returned_hash = str(result["transactionHash"]).lower()
        block_number = int(str(result["blockNumber"]), 16)
        status = int(str(result.get("status", "0x1")), 16)
        gas_used = int(str(result["gasUsed"]), 16)
        raw_logs = result["logs"]
    except (KeyError, TypeError, ValueError):
        return None
    normalized_hash = tx_hash.lower()
    if (
        returned_hash != normalized_hash
        or block_number != int(expected_block)
        or status not in (0, 1)
        or gas_used <= 0
        or not isinstance(raw_logs, list)
    ):
        return None
    logs: list[dict[str, object]] = []
    for raw_log in raw_logs:
        if not isinstance(raw_log, dict):
            return None
        try:
            log_index = int(str(raw_log["logIndex"]), 16)
        except (KeyError, TypeError, ValueError):
            return None
        address = str(raw_log.get("address") or "").lower()
        topics = [str(topic).lower() for topic in raw_log.get("topics") or []]
        data = str(raw_log.get("data") or "").lower()
        if (
            len(address) != 42
            or not address.startswith("0x")
            or log_index < 0
            or any(len(topic) != 66 or not topic.startswith("0x") for topic in topics)
            or not data.startswith("0x")
        ):
            return None
        logs.append(
            {
                "address": address,
                "log_index": log_index,
                "topics": topics,
                "data": data,
            }
        )
    logs.sort(key=lambda row: int(row["log_index"]))
    if len({int(row["log_index"]) for row in logs}) != len(logs):
        return None
    return {
        "tx_hash": normalized_hash,
        "block_number": block_number,
        "block_hash": str(result.get("blockHash") or "").lower(),
        "gas_used": gas_used,
        "status": status,
        "tx_to": str(result.get("to") or "").lower() or None,
        "tx_from": str(result.get("from") or "").lower() or None,
        "logs": logs,
    }


def fluid_receipt_is_current(
    row: object,
    tx_hash: str,
    *,
    expected_block: int,
    require_evidence: bool,
) -> bool:
    if not isinstance(row, dict):
        return False
    normalized_hash = tx_hash.lower()
    core = {
        key: row.get(key)
        for key in (
            "tx_hash",
            "block_number",
            "block_hash",
            "gas_used",
            "status",
            "tx_to",
            "tx_from",
            "logs",
        )
    }
    if (
        core["tx_hash"] != normalized_hash
        or core["block_number"] != int(expected_block)
        or core["status"] not in (0, 1)
        or not isinstance(core["logs"], list)
    ):
        return False
    if not require_evidence:
        return True
    try:
        validate_rpc_attempts(row.get("rpc_attempts"), row.get("rpc_endpoint"))
        if row.get("rpc_request") != receipt_payload(normalized_hash):
            return False
        parsed = parse_complete_receipt(
            normalized_hash,
            row.get("rpc_response"),
            expected_block=expected_block,
        )
    except (TypeError, ValueError):
        return False
    return parsed == core


def load_fluid_receipt(
    cache: Path,
    tx_hash: str,
    *,
    expected_block: int,
    require_evidence: bool = True,
) -> dict[str, object] | None:
    path = cache / f"{tx_hash.lower()}.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (
        row
        if fluid_receipt_is_current(
            row,
            tx_hash,
            expected_block=expected_block,
            require_evidence=require_evidence,
        )
        else None
    )


def fetch_fluid_receipt(
    tx_hash: str,
    *,
    cache: Path,
    expected_block: int,
) -> dict[str, object]:
    """Fetch and retain one exact receipt with its complete log perimeter."""

    retained = load_fluid_receipt(
        cache,
        tx_hash,
        expected_block=expected_block,
        require_evidence=True,
    )
    if retained is not None:
        return retained
    request = receipt_payload(tx_hash)

    def validate_response(response: object) -> None:
        if parse_complete_receipt(
            tx_hash, response, expected_block=expected_block
        ) is None:
            raise ValueError("receipt response differs from the sampled transaction")

    response = rpc_post(
        request,
        timeout=60,
        retries=3,
        sleep=0.02,
        retry_json_errors=True,
        return_evidence=True,
        response_validator=validate_response,
    )
    envelope = coerce_rpc_envelope(response)
    parsed = parse_complete_receipt(
        tx_hash,
        envelope.response,
        expected_block=expected_block,
    )
    if parsed is None:
        raise RuntimeError("receipt response differs from the sampled transaction")
    parsed.update(
        {
            "rpc_request": request,
            "rpc_response": envelope.response,
            "rpc_endpoint": envelope.endpoint,
            "rpc_attempts": list(envelope.attempts),
        }
    )
    if not fluid_receipt_is_current(
        parsed,
        tx_hash,
        expected_block=expected_block,
        require_evidence=True,
    ):
        raise RuntimeError("stored receipt cannot reproduce its normalized fields")
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cache / f"{tx_hash.lower()}.json") as temporary:
        temporary.write_text(json.dumps(parsed, sort_keys=True), encoding="utf-8")
    return parsed


def pool_constants_payload(pool: str, block_number: int) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": pool.lower(), "data": CONSTANTS_VIEW_SELECTOR},
            hex(int(block_number)),
        ],
    }


def parse_pool_constants(
    pool: str,
    response: object,
    *,
    block_number: int,
) -> dict[str, object] | None:
    """Decode token0 and token1 from the pool's immutable constants view."""

    if not isinstance(response, dict) or response.get("error"):
        return None
    result = str(response.get("result") or "").lower()
    if not result.startswith("0x") or (len(result) - 2) < 18 * 64:
        return None
    words = [
        result[2 + 64 * index : 2 + 64 * (index + 1)]
        for index in range((len(result) - 2) // 64)
    ]
    try:
        token0 = "0x" + words[9][-40:]
        token1 = "0x" + words[10][-40:]
        int(token0[2:], 16)
        int(token1[2:], 16)
    except (IndexError, ValueError):
        return None
    if token0 == token1 or int(token0, 16) == 0 or int(token1, 16) == 0:
        return None
    return {
        "pool": pool.lower(),
        "block_number": int(block_number),
        "token0": token0,
        "token1": token1,
    }


def pool_constants_are_current(
    row: object,
    pool: str,
    *,
    block_number: int,
    require_evidence: bool,
) -> bool:
    if not isinstance(row, dict):
        return False
    core = {
        key: row.get(key)
        for key in ("pool", "block_number", "token0", "token1")
    }
    if core["pool"] != pool.lower() or core["block_number"] != int(block_number):
        return False
    if not require_evidence:
        return True
    try:
        validate_rpc_attempts(row.get("rpc_attempts"), row.get("rpc_endpoint"))
        if row.get("rpc_request") != pool_constants_payload(pool, block_number):
            return False
        parsed = parse_pool_constants(
            pool,
            row.get("rpc_response"),
            block_number=block_number,
        )
    except (TypeError, ValueError):
        return False
    return parsed == core


def load_pool_constants(
    cache: Path,
    pool: str,
    *,
    block_number: int,
    require_evidence: bool = True,
) -> dict[str, object] | None:
    path = cache / f"{pool.lower()}.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (
        row
        if pool_constants_are_current(
            row,
            pool,
            block_number=block_number,
            require_evidence=require_evidence,
        )
        else None
    )


def fetch_pool_constants(
    pool: str,
    *,
    cache: Path,
    block_number: int,
) -> dict[str, object]:
    retained = load_pool_constants(
        cache,
        pool,
        block_number=block_number,
        require_evidence=True,
    )
    if retained is not None:
        return retained
    request = pool_constants_payload(pool, block_number)

    def validate_response(response: object) -> None:
        if parse_pool_constants(
            pool, response, block_number=block_number
        ) is None:
            raise ValueError("pool constants differ from the sampled contract")

    response = rpc_post(
        request,
        timeout=60,
        retries=3,
        sleep=0.02,
        retry_json_errors=True,
        return_evidence=True,
        response_validator=validate_response,
    )
    envelope = coerce_rpc_envelope(response)
    parsed = parse_pool_constants(
        pool,
        envelope.response,
        block_number=block_number,
    )
    if parsed is None:
        raise RuntimeError("pool constants differ from the sampled contract")
    parsed.update(
        {
            "rpc_request": request,
            "rpc_response": envelope.response,
            "rpc_endpoint": envelope.endpoint,
            "rpc_attempts": list(envelope.attempts),
        }
    )
    if not pool_constants_are_current(
        parsed,
        pool,
        block_number=block_number,
        require_evidence=True,
    ):
        raise RuntimeError("stored pool constants cannot reproduce their token identities")
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cache / f"{pool.lower()}.json") as temporary:
        temporary.write_text(json.dumps(parsed, sort_keys=True), encoding="utf-8")
    return parsed


def half_year(day: str) -> str:
    """Return the sample half-year for one compact calendar date."""

    value = str(day)
    if len(value) != 8 or not value.isdigit():
        raise ValueError("Fluid sample date is not YYYYMMDD")
    if value < "20250101":
        return "2024H2"
    if value < "20250701":
        return "2025H1"
    if value < "20260101":
        return "2025H2"
    if value <= "20260630":
        return "2026H1"
    raise ValueError("Fluid sample date lies outside the paper window")


def _spread_positions(size: int, count: int) -> list[int]:
    if count <= 0 or size <= 0:
        return []
    if size <= count:
        return list(range(size))
    positions = np.linspace(0, size - 1, num=count)
    rounded = [int(round(value)) for value in positions]
    if len(set(rounded)) != count:
        raise RuntimeError("rank-spread selection produced duplicate positions")
    return rounded


def deterministic_component_sample(
    population: pd.DataFrame,
    *,
    sample_counts: Mapping[str, Mapping[str, int]] = SAMPLE_COUNTS,
) -> pd.DataFrame:
    """Select high-value and rank-spread components within fixed strata.

    A transaction can contain more than one reconstructed component.  The
    highest-value component is retained before sampling so each selected
    component requests one distinct receipt.
    """

    required = {
        "day",
        "tx_hash",
        "component_id",
        "component_value_usd",
        "component_leg_count",
        "fluid_leg_count",
        "venue_count",
        "venues",
    }
    missing = required.difference(population.columns)
    if missing:
        raise ValueError(f"Fluid component population is missing {sorted(missing)}")
    frame = population.copy()
    frame["day"] = frame["day"].astype(str)
    frame["tx_hash"] = frame["tx_hash"].astype(str).str.lower()
    frame["half_year"] = frame["day"].map(half_year)
    frame["venue_scope"] = np.where(
        frame["venue_count"].astype(int) > 1,
        "cross_venue",
        "fluid_only",
    )
    frame = frame.sort_values(
        ["component_value_usd", "day", "tx_hash", "component_id"],
        ascending=[False, True, True, True],
        kind="mergesort",
    ).drop_duplicates(["tx_hash"], keep="first")

    selected: list[pd.DataFrame] = []
    for period in HALF_YEARS:
        for venue_scope in ("cross_venue", "fluid_only"):
            cell = frame[
                frame["half_year"].eq(period)
                & frame["venue_scope"].eq(venue_scope)
            ].copy()
            counts = sample_counts[venue_scope]
            needed = int(counts["high_value"]) + int(counts["rank_spread"])
            if len(cell) < needed:
                raise ValueError(
                    f"Fluid sample stratum {period}/{venue_scope} has "
                    f"{len(cell):,} components; {needed:,} are required"
                )
            cell["population_components_in_stratum"] = len(cell)
            cell["population_value_usd_in_stratum"] = float(
                cell["component_value_usd"].sum()
            )
            ranked = cell.sort_values(
                ["component_value_usd", "day", "tx_hash", "component_id"],
                ascending=[False, True, True, True],
                kind="mergesort",
            )
            high_count = int(counts["high_value"])
            high = ranked.head(high_count).copy()
            high["selection_basis"] = "high_value"
            high["selection_rank"] = np.arange(1, len(high) + 1)
            remaining = ranked.iloc[high_count:].sort_values(
                ["day", "tx_hash", "component_id"], kind="mergesort"
            )
            spread_positions = _spread_positions(
                len(remaining), int(counts["rank_spread"])
            )
            spread = remaining.iloc[spread_positions].copy()
            spread["selection_basis"] = "rank_spread"
            spread["selection_rank"] = np.arange(1, len(spread) + 1)
            selected.extend((high, spread))

    output = pd.concat(selected, ignore_index=True)
    if output["tx_hash"].duplicated().any():
        raise RuntimeError("Fluid sample contains a repeated transaction")
    return output.sort_values(
        ["half_year", "venue_scope", "selection_basis", "selection_rank"],
        kind="mergesort",
    ).reset_index(drop=True)


def decode_fluid_swap_log(log: Mapping[str, object]) -> dict[str, object] | None:
    """Decode ``Swap(bool,uint256,uint256,address)`` from a receipt log."""

    topics = log.get("topics")
    data = str(log.get("data") or "").lower()
    if (
        not isinstance(topics, list)
        or len(topics) != 1
        or str(topics[0]).lower() != FLUID_SWAP_TOPIC
        or len(data) != 2 + 64 * 4
        or not data.startswith("0x")
    ):
        return None
    try:
        words = [int(data[2 + 64 * index : 2 + 64 * (index + 1)], 16) for index in range(4)]
    except ValueError:
        return None
    if words[0] not in (0, 1) or words[1] <= 0 or words[2] <= 0:
        return None
    recipient = "0x" + f"{words[3]:064x}"[-40:]
    return {
        "swap_zero_to_one": bool(words[0]),
        "amount_in_raw": words[1],
        "amount_out_raw": words[2],
        "recipient": recipient,
    }


def _transfer_amount(log: Mapping[str, object], token: str) -> int | None:
    topics = log.get("topics")
    data = str(log.get("data") or "").lower()
    if (
        str(log.get("address") or "").lower() != token.lower()
        or not isinstance(topics, list)
        or len(topics) != 3
        or str(topics[0]).lower() != TRANSFER_TOPIC
        or len(data) != 66
        or not data.startswith("0x")
    ):
        return None
    try:
        return int(data, 16)
    except ValueError:
        return None


def token_transfer_amounts(
    logs: Sequence[Mapping[str, object]], token: str
) -> list[int]:
    """Return standard ERC-20 Transfer amounts emitted by one token."""

    amounts = [_transfer_amount(log, token) for log in logs]
    return [int(amount) for amount in amounts if amount is not None]


def inferred_decimals(raw_amount: int, reported_amount: float) -> tuple[int | None, float | None]:
    """Match an integer event amount to the reported human-token quantity."""

    if raw_amount <= 0 or not math.isfinite(reported_amount) or reported_amount <= 0:
        return None, None
    best: tuple[float, int] | None = None
    for decimals in range(0, 37):
        scaled = raw_amount / (10**decimals)
        relative_error = abs(scaled - reported_amount) / reported_amount
        if best is None or relative_error < best[0]:
            best = (relative_error, decimals)
    assert best is not None
    return best[1], best[0]


def validate_fluid_leg(
    leg: Mapping[str, object],
    receipt: Mapping[str, object] | None,
    pool_constants: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compare one labelled Fluid leg with its complete receipt perimeter."""

    base = {
        key: leg[key]
        for key in (
            "half_year",
            "venue_scope",
            "selection_basis",
            "day",
            "tx_hash",
            "component_id",
            "log_index",
            "pool",
            "token_in",
            "token_out",
        )
        if key in leg
    }
    if receipt is None:
        return {
            **base,
            "receipt_complete": False,
            "event_exact": False,
            "pool_identity_available": pool_constants is not None,
            "pool_direction_exact": False,
            "transfer_tokens_observed": False,
            "exact_transfer_support": False,
            "label_confirmed": False,
            "reported_amounts_consistent": False,
            "result": "receipt_unavailable",
        }
    logs = receipt.get("logs")
    receipt_complete = bool(
        receipt.get("status") == 1
        and int(receipt.get("block_number") or -1) == int(leg["block_number"])
        and isinstance(logs, list)
    )
    indexed = {
        int(log["log_index"]): log
        for log in logs or []
        if isinstance(log, dict) and "log_index" in log
    }
    event_log = indexed.get(int(leg["log_index"]))
    decoded = decode_fluid_swap_log(event_log or {})
    event_exact = bool(
        receipt_complete
        and event_log is not None
        and str(event_log.get("address") or "").lower()
        == str(leg["pool"]).lower()
        and decoded is not None
    )
    if decoded is None:
        amount_in_raw = None
        amount_out_raw = None
        input_decimals = output_decimals = None
        input_error = output_error = None
    else:
        amount_in_raw = int(decoded["amount_in_raw"])
        amount_out_raw = int(decoded["amount_out_raw"])
        input_decimals, input_error = inferred_decimals(
            amount_in_raw, float(leg["amount_in"])
        )
        output_decimals, output_error = inferred_decimals(
            amount_out_raw, float(leg["amount_out"])
        )
    input_transfers = token_transfer_amounts(logs or [], str(leg["token_in"]))
    output_transfers = token_transfer_amounts(logs or [], str(leg["token_out"]))
    input_token_observed = bool(input_transfers)
    output_token_observed = bool(output_transfers)
    transfer_tokens_observed = bool(
        event_exact and input_token_observed and output_token_observed
    )
    input_amount_matches = bool(
        amount_in_raw is not None and amount_in_raw in input_transfers
    )
    output_amount_matches = bool(
        amount_out_raw is not None and amount_out_raw in output_transfers
    )
    exact_transfer_support = bool(input_amount_matches and output_amount_matches)
    reported_amounts_consistent = bool(
        event_exact
        and input_error is not None
        and output_error is not None
        and input_error <= 1e-9
        and output_error <= 1e-9
    )
    pool_identity_available = bool(
        pool_constants is not None
        and str(pool_constants.get("pool") or "").lower()
        == str(leg["pool"]).lower()
    )
    if decoded is None or not pool_identity_available:
        literal_input = literal_output = None
    elif bool(decoded["swap_zero_to_one"]):
        literal_input = str(pool_constants["token0"]).lower()
        literal_output = str(pool_constants["token1"]).lower()
    else:
        literal_input = str(pool_constants["token1"]).lower()
        literal_output = str(pool_constants["token0"]).lower()
    expected_input = WETH if literal_input == FLUID_NATIVE_ETH else literal_input
    expected_output = WETH if literal_output == FLUID_NATIVE_ETH else literal_output
    pool_direction_literal = bool(
        literal_input == str(leg["token_in"]).lower()
        and literal_output == str(leg["token_out"]).lower()
    )
    pool_direction_exact = bool(
        expected_input == str(leg["token_in"]).lower()
        and expected_output == str(leg["token_out"]).lower()
    )
    wrapped_native_equivalent = bool(
        pool_direction_exact and not pool_direction_literal
    )
    label_confirmed = bool(
        event_exact and pool_direction_exact and reported_amounts_consistent
    )
    if label_confirmed:
        result = "confirmed"
    elif event_exact and pool_identity_available:
        result = "contradicted"
    elif event_exact:
        result = "pool_identity_unresolved"
    else:
        result = "event_mismatch"
    return {
        **base,
        "receipt_complete": receipt_complete,
        "event_exact": event_exact,
        "swap_zero_to_one": (
            bool(decoded["swap_zero_to_one"]) if decoded is not None else None
        ),
        "event_amount_in_raw": str(amount_in_raw) if amount_in_raw is not None else None,
        "event_amount_out_raw": (
            str(amount_out_raw) if amount_out_raw is not None else None
        ),
        "event_recipient": decoded.get("recipient") if decoded is not None else None,
        "pool_identity_available": pool_identity_available,
        "pool_direction_literal": pool_direction_literal,
        "pool_direction_exact": pool_direction_exact,
        "wrapped_native_equivalent": wrapped_native_equivalent,
        "literal_token_in": literal_input,
        "literal_token_out": literal_output,
        "expected_token_in": expected_input,
        "expected_token_out": expected_output,
        "transfer_tokens_observed": transfer_tokens_observed,
        "exact_transfer_support": exact_transfer_support,
        "input_token_observed": input_token_observed,
        "output_token_observed": output_token_observed,
        "input_amount_matches": input_amount_matches,
        "output_amount_matches": output_amount_matches,
        "label_confirmed": label_confirmed,
        "reported_amounts_consistent": reported_amounts_consistent,
        "input_decimals_inferred": input_decimals,
        "output_decimals_inferred": output_decimals,
        "input_relative_error": input_error,
        "output_relative_error": output_error,
        "result": result,
    }


def wilson_lower(successes: int, observations: int, *, z: float = 1.959963984540054) -> float | None:
    """Two-sided 95% Wilson interval lower endpoint."""

    if observations <= 0:
        return None
    share = successes / observations
    z2 = z * z
    denominator = 1 + z2 / observations
    centre = share + z2 / (2 * observations)
    margin = z * math.sqrt(
        share * (1 - share) / observations + z2 / (4 * observations**2)
    )
    return (centre - margin) / denominator


def validation_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Summarize receipt coverage and exact direction checks."""

    if results.empty:
        raise ValueError("Fluid route-label validation has no leg results")
    groups: list[tuple[str, pd.DataFrame]] = [("overall", results)]
    groups.extend(
        (f"venue_scope:{key}", group)
        for key, group in results.groupby("venue_scope", sort=True)
    )
    groups.extend(
        (f"half_year:{key}", group)
        for key, group in results.groupby("half_year", sort=True)
    )
    rows: list[dict[str, object]] = []
    for scope, group in groups:
        sampled = len(group)
        testable = int(
            (group["event_exact"] & group["pool_identity_available"]).sum()
        )
        confirmed = int(group["label_confirmed"].sum())
        rows.append(
            {
                "record_type": "estimate",
                "scope": scope,
                "sampled_components": int(
                    group[["tx_hash", "component_id"]].drop_duplicates().shape[0]
                ),
                "sampled_fluid_legs": sampled,
                "complete_receipts": int(group["receipt_complete"].sum()),
                "exact_swap_events": int(group["event_exact"].sum()),
                "pool_identity_testable_legs": testable,
                "pool_direction_matches": int(group["pool_direction_exact"].sum()),
                "literal_contract_token_matches": int(
                    group["pool_direction_literal"].sum()
                ),
                "wrapped_native_equivalents": int(
                    group["wrapped_native_equivalent"].sum()
                ),
                "confirmed_labels": confirmed,
                "contradicted_labels": int((group["result"] == "contradicted").sum()),
                "unresolved_labels": int(
                    (~group["result"].isin(["confirmed", "contradicted"])).sum()
                ),
                "receipt_coverage": float(group["receipt_complete"].mean()),
                "pool_identity_coverage": testable / sampled,
                "exact_confirmation_rate": confirmed / sampled,
                "testable_label_precision": confirmed / testable if testable else None,
                "precision_wilson_95_lower": wilson_lower(confirmed, testable),
                "transfer_token_coverage": float(
                    group["transfer_tokens_observed"].mean()
                ),
                "exact_transfer_support_rate": float(
                    group["exact_transfer_support"].mean()
                ),
                "reported_amount_consistency": float(
                    group["reported_amounts_consistent"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)
