from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

import scripts.build_ethereum_day_calendar as calendar_builder
import ddvc.ethereum_day_cuts as day_cuts
from ddvc.ethereum_day_cuts import (
    load_or_resolve_utc_day_block_bounds,
    load_utc_day_block_bounds,
    validate_utc_day_block_bounds,
)


def _evidence(block: int, timestamp: int) -> dict[str, object]:
    return {
        "request": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBlockByNumber",
            "params": [hex(block), False],
        },
        "response": {
            "number": hex(block),
            "hash": "0x" + f"{block:064x}",
            "parentHash": "0x" + f"{max(0, block - 1):064x}",
            "timestamp": hex(timestamp),
        },
    }


def _v3_cut(day: str, end_block: int, end_timestamp: int) -> dict[str, object]:
    target = int(
        (
            datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        ).timestamp()
    )
    return {
        "status": "complete",
        "day": day,
        "target_timestamp": target,
        "day_end_block": end_block,
        "day_end_block_timestamp": end_timestamp,
        "next_block": end_block + 1,
        "next_block_timestamp": target,
        "initial_lower_bracket": end_block - 10,
        "resolved_upper_bracket": end_block + 1,
        "rpc_evidence": [
            _evidence(end_block, end_timestamp),
            _evidence(end_block + 1, target),
        ],
    }


def test_adjacent_v3_cuts_promote_to_a_chain_wide_utc_day(tmp_path, monkeypatch) -> None:
    cut_root = tmp_path / "v3-cuts"
    bound_root = tmp_path / "bounds"
    cut_root.mkdir()
    day = "20250115"
    previous_day = "20250114"
    start = int(datetime(2025, 1, 15, tzinfo=timezone.utc).timestamp())
    end = start + 86_400
    (cut_root / f"{previous_day}.json").write_text(
        json.dumps(_v3_cut(previous_day, 99, start - 1))
    )
    (cut_root / f"{day}.json").write_text(
        json.dumps(_v3_cut(day, 199, end - 1))
    )
    monkeypatch.setattr(calendar_builder, "RAW_DAY_CUT_ROOT", cut_root)
    monkeypatch.setattr(calendar_builder, "RAW_DAY_BOUND_ROOT", bound_root)
    monkeypatch.setattr(day_cuts, "RAW_DAY_BOUND_ROOT", bound_root)
    monkeypatch.setattr(calendar_builder, "graph_head_upper", lambda _day: pytest.fail("metadata lookup"))

    record = calendar_builder.resolve_day(day, fetch=True)

    assert record is not None
    assert record["start_block"] == 100
    assert record["end_block"] == 199
    assert record["promoted_from"] == "uniswap_v3_inventory_day_cuts"
    assert (bound_root / f"{day}.json").is_file()


def test_graph_metadata_is_only_an_upper_search_bracket(tmp_path, monkeypatch) -> None:
    graph_root = tmp_path / "thegraph"
    for venue, upper in (("uniswap_v1", 100), ("uniswap_v2", 120)):
        venue_root = graph_root / venue
        venue_root.mkdir(parents=True)
        (venue_root / f"{venue}_meta_20200101.json").write_text(
            json.dumps({"head_block_at_fetch": upper})
        )
    monkeypatch.setattr(calendar_builder, "GRAPH_ROOT", graph_root)

    assert calendar_builder.graph_head_upper("20200101") == 120


class HeaderTransport:
    def __init__(self, origin_timestamp: int) -> None:
        self.origin_timestamp = origin_timestamp
        self.calls: list[int] = []

    def __call__(self, payload: dict[str, object], **_kwargs) -> dict[str, object]:
        block = int(str(payload["params"][0]), 16)
        self.calls.append(block)
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "number": hex(block),
                "hash": "0x" + f"{block:064x}",
                "parentHash": "0x" + f"{max(0, block - 1):064x}",
                "timestamp": hex(self.origin_timestamp + 12 * block),
            },
        }


def _resolve_days(
    days: list[str],
    root: Path,
    transport: HeaderTransport,
    *,
    adjacent: bool,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    previous = None
    for day in days:
        record = load_or_resolve_utc_day_block_bounds(
            day,
            20_000_000,
            fetch=True,
            root=root,
            previous_record=previous if adjacent else None,
            rpc_request=transport,
            sleeper=lambda _seconds: None,
        )
        records.append(record)
        previous = record
    return records


def _identity(record: dict[str, object]) -> tuple[object, ...]:
    return tuple(record[column] for column in calendar_builder.CALENDAR_COLUMNS)


def test_adjacent_resolution_preserves_bounds_and_reduces_header_requests(tmp_path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    days = [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(40)]
    origin = int(start.timestamp()) - 1_200
    independent_transport = HeaderTransport(origin)

    independent = _resolve_days(days, tmp_path / "independent", independent_transport, adjacent=False)
    adjacent: list[dict[str, object]] = []
    adjacent_calls = 0
    for index, shard in enumerate(calendar_builder.chronological_shards(days)):
        adjacent_transport = HeaderTransport(origin)
        adjacent.extend(_resolve_days(shard, tmp_path / f"adjacent-{index}", adjacent_transport, adjacent=True))
        adjacent_calls += len(adjacent_transport.calls)

    assert [_identity(record) for record in adjacent] == [_identity(record) for record in independent]
    assert adjacent_calls <= 0.4 * len(independent_transport.calls)
    for day, record in zip(days, adjacent):
        validate_utc_day_block_bounds(record, day)


def test_cached_day_performs_no_rpc_or_metadata_lookup(tmp_path, monkeypatch) -> None:
    day = "20250101"
    origin = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()) - 1_200
    transport = HeaderTransport(origin)
    record = load_or_resolve_utc_day_block_bounds(
        day,
        20_000_000,
        fetch=True,
        root=tmp_path,
        rpc_request=transport,
        sleeper=lambda _seconds: None,
    )
    monkeypatch.setattr(calendar_builder, "RAW_DAY_BOUND_ROOT", tmp_path)
    monkeypatch.setattr(day_cuts, "RAW_DAY_BOUND_ROOT", tmp_path)
    monkeypatch.setattr(calendar_builder, "graph_head_upper", lambda _day: pytest.fail("metadata lookup"))

    cached = calendar_builder.resolve_day(day, fetch=True, previous_record=None)

    assert _identity(cached) == _identity(record)


def test_discontinuous_prior_evidence_falls_back_to_independent_search(tmp_path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first_day = start.strftime("%Y%m%d")
    second_day = (start + timedelta(days=1)).strftime("%Y%m%d")
    origin = int(start.timestamp()) - 1_200
    transport = HeaderTransport(origin)
    first = _resolve_days([first_day], tmp_path / "first", transport, adjacent=True)[0]
    boundary_block = int(first["after_end_block"])
    for item in first["rpc_evidence"]:
        if int(str(item["request"]["params"][0]), 16) == boundary_block:
            item["response"]["parentHash"] = "0x" + "f" * 64
    fallback_transport = HeaderTransport(origin)

    second = load_or_resolve_utc_day_block_bounds(
        second_day,
        20_000_000,
        fetch=True,
        root=tmp_path / "second",
        previous_record=first,
        rpc_request=fallback_transport,
        sleeper=lambda _seconds: None,
    )

    validate_utc_day_block_bounds(second, second_day)
    assert second["initial_lower_bracket"] == 0


@pytest.mark.parametrize("child_field", ["start_block", "after_end_block"])
def test_universal_day_validator_rejects_broken_boundary_parent_link(tmp_path, child_field) -> None:
    day = "20250101"
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    transport = HeaderTransport(int(start.timestamp()) - 1_200)
    record = _resolve_days([day], tmp_path, transport, adjacent=False)[0]
    child_block = int(record[child_field])
    for item in record["rpc_evidence"]:
        if int(str(item["request"]["params"][0]), 16) == child_block:
            item["response"]["parentHash"] = "0x" + "f" * 64

    with pytest.raises(ValueError, match="parent linkage"):
        validate_utc_day_block_bounds(record, day)


def _calendar_record(day: str) -> dict[str, object]:
    start_timestamp = int(datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
    start_block = start_timestamp // 12
    return {
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": start_timestamp + 86_400,
        "start_block": start_block,
        "start_block_timestamp": start_timestamp,
        "end_block": start_block + 7_199,
        "end_block_timestamp": start_timestamp + 86_388,
        "before_start_block": start_block - 1,
        "before_start_block_timestamp": start_timestamp - 12,
        "after_end_block": start_block + 7_200,
        "after_end_block_timestamp": start_timestamp + 86_400,
    }


def test_worker_count_does_not_change_calendar_identity(monkeypatch) -> None:
    start = datetime(2025, 1, 1)
    days = [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(11)]

    def fake_resolve(day: str, *, fetch: bool, previous_record=None) -> dict[str, object]:
        assert fetch
        return _calendar_record(day)

    monkeypatch.setattr(calendar_builder, "load_cached_or_promoted_day", lambda _day: None)
    monkeypatch.setattr(calendar_builder, "resolve_day", fake_resolve)

    serial = calendar_builder.build_calendar(days, fetch=True, workers=1)
    parallel = calendar_builder.build_calendar(days, fetch=True, workers=4)

    pd.testing.assert_frame_equal(serial, parallel)
    assert [len(shard) for shard in calendar_builder.chronological_shards(days)] == [3, 3, 3, 2]


def test_cached_day_inside_chronological_shard_seeds_next_unresolved_day(monkeypatch) -> None:
    start = datetime(2025, 1, 1)
    days = [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(8)]
    cached_day = days[3]
    cached_record = _calendar_record(cached_day)
    predecessors: dict[str, str | None] = {}

    def fake_cached(day: str) -> dict[str, object] | None:
        return cached_record if day == cached_day else None

    def fake_resolve(day: str, *, fetch: bool, previous_record=None) -> dict[str, object]:
        assert fetch
        predecessors[day] = None if previous_record is None else str(previous_record["day"])
        return _calendar_record(day)

    monkeypatch.setattr(calendar_builder, "load_cached_or_promoted_day", fake_cached)
    monkeypatch.setattr(calendar_builder, "resolve_day", fake_resolve)

    frame = calendar_builder.build_calendar(days, fetch=True, workers=1)

    assert frame["day"].tolist() == days
    assert predecessors[days[4]] == cached_day


def test_shard_failure_prevents_calendar_result(monkeypatch) -> None:
    days = ["20250101", "20250102", "20250103", "20250104"]

    def fake_shard(
        shard: list[str],
        *,
        fetch: bool,
        cached_records=None,
        initial_previous=None,
    ) -> list[dict[str, object]]:
        assert fetch
        if "20250103" in shard:
            raise RuntimeError("injected shard failure")
        return [_calendar_record(day) for day in shard]

    monkeypatch.setattr(calendar_builder, "load_cached_or_promoted_day", lambda _day: None)
    monkeypatch.setattr(calendar_builder, "resolve_day_shard", fake_shard)

    with pytest.raises(RuntimeError, match="injected shard failure"):
        calendar_builder.build_calendar(days, fetch=True, workers=2)


def test_main_does_not_replace_published_calendar_after_shard_failure(tmp_path, monkeypatch) -> None:
    target = tmp_path / "calendar.parquet"
    target.write_bytes(b"prior-release")
    monkeypatch.setattr(calendar_builder, "UTC_DAY_BLOCK_CALENDAR", target)
    monkeypatch.setattr(calendar_builder, "require_node_d_release", lambda **_kwargs: None)
    monkeypatch.setattr(calendar_builder, "released_route_days", lambda *_args, **_kwargs: ["20250101"])
    monkeypatch.setattr(calendar_builder, "exclusive_job", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(calendar_builder, "build_calendar", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected shard failure")))
    monkeypatch.setattr(sys, "argv", ["build_ethereum_day_calendar.py"])

    with pytest.raises(RuntimeError, match="injected shard failure"):
        calendar_builder.main()

    assert target.read_bytes() == b"prior-release"


def test_persisted_adjacent_record_retains_all_four_exact_header_proofs(tmp_path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    days = [start.strftime("%Y%m%d"), (start + timedelta(days=1)).strftime("%Y%m%d")]
    transport = HeaderTransport(int(start.timestamp()) - 1_200)

    records = _resolve_days(days, tmp_path, transport, adjacent=True)
    persisted = load_utc_day_block_bounds(days[1], root=tmp_path)

    assert _identity(persisted) == _identity(records[1])
    required = {
        int(persisted["before_start_block"]),
        int(persisted["start_block"]),
        int(persisted["end_block"]),
        int(persisted["after_end_block"]),
    }
    observed = {int(str(item["request"]["params"][0]), 16) for item in persisted["rpc_evidence"]}
    assert required <= observed
