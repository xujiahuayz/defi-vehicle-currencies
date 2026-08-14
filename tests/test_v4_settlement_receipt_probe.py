from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts.run_v4_settlement_receipt_probe import (
    TRANSFER_TOPIC,
    _load_exact_leased_selection,
    attach_receipts,
    attach_size_bins,
    estimate_receipt_probe,
    load_receipt_cache,
    matching_transfer_count,
    select_matched_routes,
    support_record,
)


V3 = "uniswap_v3"
V4 = "uniswap_v4"
VEHICLE = "0x" + "ab" * 20
NATIVE = "0x" + "00" * 20


def _routes() -> pd.DataFrame:
    rows = []
    weeks = pd.date_range("2025-01-06", periods=12, freq="7D")
    for pair_index in range(12):
        for week_index, week in enumerate(weeks):
            for dex in (V3, V4):
                for route_index in range(5):
                    rows.append(
                        {
                            "week": week,
                            "src": f"S{pair_index}",
                            "src_id": "0x" + f"{pair_index + 1:040x}",
                            "src_settlement_kind": "erc20",
                            "sink": f"T{pair_index}",
                            "sink_id": "0x" + f"{pair_index + 101:040x}",
                            "sink_settlement_kind": "erc20",
                            "vehicle": "USDC",
                            "vehicle_id": VEHICLE,
                            "vehicle_settlement_kind": "erc20",
                            "dex": dex,
                            "tx_hash": "0x" + hashlib_hex(
                                pair_index, week_index, dex, route_index
                            ),
                            "block_number": 20_000_000 + pair_index * 1_000 + week_index,
                            "component_id": 0,
                            "n_components": 1,
                            "component_is_unique": True,
                            "route_usd": 500.0,
                        }
                    )
    return pd.DataFrame(rows)


def hashlib_hex(*values: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()


def _receipt(tx_hash: str, *, transfer: bool, block_number: int = 20_000_000) -> dict:
    logs = [
        {
            "address": VEHICLE,
            "topics": [TRANSFER_TOPIC, "0x1", "0x2"],
            "data": "0x01",
        }
    ] if transfer else [{"address": VEHICLE, "topics": ["0xdead"], "data": "0x"}]
    return {
        "transactionHash": tx_hash,
        "blockNumber": hex(block_number),
        "logs": logs,
    }


def test_size_bins_are_fixed_and_left_closed() -> None:
    routes = _routes().iloc[:6].copy()
    routes["route_usd"] = [99.0, 100.0, 999.0, 1_000.0, 999_999.0, 1_000_000.0]
    binned = attach_size_bins(routes)
    assert binned["size_bin"].tolist() == [
        "lt_100", "100_1k", "100_1k", "1k_10k", "100k_1m", "ge_1m"
    ]


def test_selection_is_balanced_deterministic_and_receipt_independent() -> None:
    routes = _routes()
    first = select_matched_routes(
        routes, min_routes=5, max_cells=50, per_architecture=1, seed=19
    )
    second = select_matched_routes(
        routes.sample(frac=1, random_state=7),
        min_routes=5,
        max_cells=50,
        per_architecture=1,
        seed=19,
    )
    pd.testing.assert_frame_equal(first, second)
    counts = first.groupby(["cell_id", "dex"]).size().unstack("dex")
    assert len(counts) == 50
    assert (counts[[V3, V4]] == 1).all().all()


def test_symbol_equality_does_not_match_different_endpoint_contracts() -> None:
    routes = _routes()
    target = (
        routes["src"].eq("S0")
        & routes["week"].eq(pd.Timestamp("2025-01-06"))
        & routes["dex"].eq(V4)
    )
    routes.loc[target, "src_id"] = "0x" + "fe" * 20
    selection = select_matched_routes(
        routes, min_routes=5, max_cells=144, per_architecture=1, seed=19
    )
    assert selection["cell_id"].nunique() == 143
    assert not (
        selection["week"].eq(pd.Timestamp("2025-01-06"))
        & selection["src"].eq("S0")
    ).any()


def test_multi_component_transaction_cannot_create_receipt_false_positive() -> None:
    routes = _routes()
    contaminated = (
        routes["src"].eq("S0")
        & routes["week"].eq(pd.Timestamp("2025-01-06"))
    )
    contaminated_hashes = set(routes.loc[contaminated, "tx_hash"])
    routes.loc[contaminated, "n_components"] = 2
    routes.loc[contaminated, "component_is_unique"] = False
    # Even if a receipt for one of these transactions contains the vehicle's
    # Transfer event, the transaction-wide log cannot be attributed to this
    # component and the route must never enter the primary selection.
    false_positive = _receipt(next(iter(contaminated_hashes)), transfer=True)
    assert matching_transfer_count(false_positive, VEHICLE) == 1
    selection = select_matched_routes(
        routes, min_routes=5, max_cells=144, per_architecture=1, seed=19
    )
    assert contaminated_hashes.isdisjoint(set(selection["tx_hash"]))
    assert selection["cell_id"].nunique() == 143


def test_native_intermediary_is_excluded_from_erc20_primary_selection() -> None:
    routes = _routes()
    native = (
        routes["src"].eq("S0")
        & routes["week"].eq(pd.Timestamp("2025-01-06"))
    )
    native_hashes = set(routes.loc[native, "tx_hash"])
    routes.loc[native, "vehicle_id"] = NATIVE
    routes.loc[native, "vehicle_settlement_kind"] = "native"
    selection = select_matched_routes(
        routes, min_routes=5, max_cells=144, per_architecture=1, seed=19
    )
    assert native_hashes.isdisjoint(set(selection["tx_hash"]))
    assert selection["vehicle_settlement_kind"].eq("erc20").all()


def test_receipt_cache_is_exact_and_missing_selection_fails(tmp_path) -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    tx = selection.iloc[0]["tx_hash"]
    block_number = int(selection.iloc[0]["block_number"])
    path = tmp_path / "receipts.jsonl"
    path.write_text(
        json.dumps(
            {
                "tx": tx,
                "receipt": _receipt(tx, transfer=True, block_number=block_number),
            }
        )
        + "\n"
    )
    receipts = load_receipt_cache(path)
    assert matching_transfer_count(receipts[tx], VEHICLE) == 1
    with pytest.raises(ValueError, match="selection is fixed before receipt acquisition"):
        attach_receipts(selection, receipts)


def test_receipt_cache_accepts_canonical_normalized_snapshot(tmp_path) -> None:
    tx = "0x" + "12" * 32
    row = {"tx_hash": tx, **_receipt(tx, transfer=True)}
    path = tmp_path / "receipts.jsonl"
    path.write_text(json.dumps(row) + "\n")
    receipts = load_receipt_cache(path)
    assert matching_transfer_count(receipts[tx], VEHICLE) == 1


def test_receipt_cache_requires_explicit_valid_inner_transaction_hash(tmp_path) -> None:
    tx = "0x" + "12" * 32
    path = tmp_path / "receipts.jsonl"
    path.write_text(
        json.dumps({"tx": tx, "receipt": {"blockNumber": "0x10", "logs": []}})
        + "\n"
    )
    with pytest.raises(ValueError, match="lacks its own transaction identity"):
        load_receipt_cache(path)

    invalid = "0x" + "zz" * 32
    path.write_text(
        json.dumps(
            {
                "tx": invalid,
                "receipt": {
                    "transactionHash": invalid,
                    "blockNumber": "0x10",
                    "logs": [],
                },
            }
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="invalid transaction"):
        load_receipt_cache(path)


def test_receipt_block_must_match_selected_route_identity() -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    receipts = {
        row.tx_hash: _receipt(
            row.tx_hash,
            transfer=True,
            block_number=int(row.block_number) + (1 if index == 0 else 0),
        )
        for index, row in enumerate(selection.itertuples(index=False))
    }
    with pytest.raises(ValueError, match="selected block identity"):
        attach_receipts(selection, receipts)


@pytest.mark.parametrize("invalid_block", [20_000_000.5, True])
def test_receipt_block_rejects_noninteger_values(invalid_block: object) -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    receipts = {
        row.tx_hash: _receipt(
            row.tx_hash,
            transfer=True,
            block_number=int(row.block_number),
        )
        for row in selection.itertuples(index=False)
    }
    receipts[selection.iloc[0]["tx_hash"]]["blockNumber"] = invalid_block
    with pytest.raises(ValueError, match="exact block identity"):
        attach_receipts(selection, receipts)


@pytest.mark.parametrize("invalid_block", [20_000_000.5, False])
def test_selected_block_rejects_noninteger_values(invalid_block: object) -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    selection["block_number"] = selection["block_number"].astype(object)
    selection.loc[selection.index[0], "block_number"] = invalid_block
    with pytest.raises(ValueError, match="selection lacks an exact block identity"):
        attach_receipts(selection, {})


def test_receipt_block_accepts_decimal_integer_and_hex() -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    receipts = {}
    for index, row in enumerate(selection.itertuples(index=False)):
        receipt = _receipt(
            row.tx_hash,
            transfer=True,
            block_number=int(row.block_number),
        )
        receipt["blockNumber"] = (
            str(int(row.block_number)) if index == 0 else hex(int(row.block_number))
        )
        receipts[row.tx_hash] = receipt
    detail = attach_receipts(selection, receipts)
    assert len(detail) == len(selection)


def test_leased_selection_replacement_fails_closed(tmp_path) -> None:
    expected = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    path = tmp_path / "selection.parquet"
    expected.to_parquet(path, index=False)
    observed = _load_exact_leased_selection(path, expected)
    pd.testing.assert_frame_equal(expected, observed, check_dtype=False)

    replacement = expected.copy()
    replacement.loc[replacement.index[0], "selection_score"] = "0" * 64
    replacement.to_parquet(path, index=False)
    with pytest.raises(RuntimeError, match="changed between publication and estimation"):
        _load_exact_leased_selection(path, expected)


def test_paired_estimator_uses_two_way_clusters() -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=144, per_architecture=1, seed=4
    )
    receipts = {}
    # V3 always transfers. V4 transfer probability varies by pair and week so
    # the two-way covariance is non-degenerate.
    for row in selection.itertuples(index=False):
        pair_index = int(str(row.src)[1:])
        week_index = int((pd.Timestamp(row.week) - pd.Timestamp("2025-01-06")).days / 7)
        transfer = row.dex == V3 or int(
            hashlib_hex(pair_index, week_index)[:8], 16
        ) % 5 < 2
        receipts[row.tx_hash] = _receipt(
            row.tx_hash,
            transfer=transfer,
            block_number=int(row.block_number),
        )
    detail = attach_receipts(selection, receipts)
    results, paired = estimate_receipt_probe(detail)
    overall = results.set_index("sample").loc["all"]
    assert len(paired) == 144
    assert overall["v3_mean"] == 1.0
    expected_v4 = detail.loc[detail["dex"].eq(V4), "has_matching_transfer"].mean()
    assert np.isclose(overall["v4_mean"], expected_v4)
    assert np.isclose(overall["v4_minus_v3"], expected_v4 - 1.0)
    assert overall["ordered_pair_clusters"] == 12
    assert overall["calendar_week_clusters"] == 12
    assert np.isfinite(overall["standard_error"])
    support = support_record(
        selection,
        paired,
        min_routes=5,
        max_cells=144,
        per_architecture=1,
        seed=4,
    ).iloc[0]
    assert support["transaction_component_scope"] == "single_reconstructed_component"
    assert support["intermediary_settlement_scope"] == "erc20_only"
    assert "native_intermediary_movement_requires_trace" in support["unidentified_outcomes"]
