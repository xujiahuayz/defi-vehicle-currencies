from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts.run_v4_settlement_receipt_probe import (
    TRANSFER_TOPIC,
    attach_receipts,
    attach_size_bins,
    estimate_receipt_probe,
    load_receipt_cache,
    matching_transfer_count,
    select_matched_routes,
)


V3 = "uniswap_v3"
V4 = "uniswap_v4"
VEHICLE = "0x" + "ab" * 20


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
                            "sink": f"T{pair_index}",
                            "vehicle": "USDC",
                            "vehicle_id": VEHICLE,
                            "dex": dex,
                            "tx_hash": "0x" + hashlib_hex(
                                pair_index, week_index, dex, route_index
                            ),
                            "component_id": 0,
                            "route_usd": 500.0,
                        }
                    )
    return pd.DataFrame(rows)


def hashlib_hex(*values: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()


def _receipt(tx_hash: str, *, transfer: bool) -> dict:
    logs = [
        {
            "address": VEHICLE,
            "topics": [TRANSFER_TOPIC, "0x1", "0x2"],
            "data": "0x01",
        }
    ] if transfer else [{"address": VEHICLE, "topics": ["0xdead"], "data": "0x"}]
    return {"transactionHash": tx_hash, "logs": logs}


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


def test_receipt_cache_is_exact_and_missing_selection_fails(tmp_path) -> None:
    selection = select_matched_routes(
        _routes(), min_routes=5, max_cells=1, per_architecture=1, seed=2
    )
    tx = selection.iloc[0]["tx_hash"]
    path = tmp_path / "receipts.jsonl"
    path.write_text(json.dumps({"tx": tx, "receipt": _receipt(tx, transfer=True)}) + "\n")
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
        receipts[row.tx_hash] = _receipt(row.tx_hash, transfer=transfer)
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
