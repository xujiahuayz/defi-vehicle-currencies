from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from ddvc.pricing.tick_replay import TickReplayEvent
from ddvc.route_cache import (
    day_cache_is_current,
    marker_path,
    write_day_cache,
    write_ordered_shard_manifest,
)
from ddvc.route_state import (
    OrderedTickStateCursor,
    TickStateCut,
    load_cp_quote_states_by_hour,
    released_state_lineage_inputs,
)
from ddvc.state_data import write_cp_partition
from scripts import run_route_cost_panel


def _write_gzip_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_route_quotes_exact_requested_hour_from_canonical_partition(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    state_root = tmp_path / "state"
    venue = "uniswap_v2"
    pair = {
        "id": "0xpool",
        "token0": {
            "id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "symbol": "WETH",
            "decimals": "18",
        },
        "token1": {
            "id": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "symbol": "USDC",
            "decimals": "6",
        },
    }
    day_start = 1_735_689_600
    _write_gzip_rows(
        raw_root / venue / f"{venue}_hourly_reserves_20250101.jsonl.gz",
        [
            {"id": "h0", "hourStartUnix": str(day_start), "reserve0": "10", "reserve1": "20", "pair": pair},
            {"id": "h1", "hourStartUnix": str(day_start + 3600), "reserve0": "30", "reserve1": "40", "pair": pair},
        ],
    )
    for stream in ("swaps", "mints", "burns"):
        _write_gzip_rows(
            raw_root / venue / f"{venue}_{stream}_20250101.jsonl.gz",
            [],
        )
    write_cp_partition(raw_root, venue, "20250101", root=state_root)

    states = load_cp_quote_states_by_hour(
        "20250101",
        (1,),
        state_root=state_root,
        raw_root=raw_root,
        venues=(venue,),
    )

    assert list(states) == [1]
    assert [(state.reserve0, state.reserve1) for state in states[1]] == [(30.0, 40.0)]


def test_each_state_lineage_change_creates_a_new_quote_cache_generation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    correction = tmp_path / "corrections"
    certificate = tmp_path / "certificate.json"
    state.mkdir()
    correction.mkdir()
    (state / "20250101.parquet").write_bytes(b"canonical-state")
    action = correction / "20250101.jsonl.gz"
    action.write_bytes(b"correction-v1")
    certificate.write_text('{"status":"complete"}\n', encoding="utf-8")
    inputs = [state, correction, certificate]
    generations = [run_route_cost_panel.quote_cache_generation(inputs=inputs)]

    (state / "20250101.parquet").write_bytes(b"canonical-state-v2")
    generations.append(run_route_cost_panel.quote_cache_generation(inputs=inputs))
    action.write_bytes(b"correction-v2-with-provider-omission")
    generations.append(run_route_cost_panel.quote_cache_generation(inputs=inputs))
    certificate.write_text('{"status":"complete","version":2}\n', encoding="utf-8")
    generations.append(run_route_cost_panel.quote_cache_generation(inputs=inputs))

    assert len(set(generations)) == 4


def test_state_lineage_resolves_the_marker_released_v2_generation(tmp_path: Path, monkeypatch) -> None:
    import ddvc.route_state as route_state

    pointer = tmp_path / "release" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}\n", encoding="utf-8")
    artifacts = tuple(tmp_path / "release" / name for name in ("summary.parquet", "exceptions.parquet", "certificate.json"))
    lineage = (pointer, *artifacts, *(route_state.sidecar_path(path) for path in artifacts))
    release = type("Release", (), {"lineage_paths": lineage})()
    monkeypatch.setattr(route_state, "V2_EVENT_SOURCE_CURRENT", pointer)
    monkeypatch.setattr(route_state, "resolve_v2_event_source_release", lambda: release)
    inputs = released_state_lineage_inputs(
        state_root=tmp_path / "state",
        raw_root=tmp_path / "raw",
    )
    assert pointer in inputs
    assert all(path in inputs for path in artifacts)
    assert all(route_state.sidecar_path(path) in inputs for path in artifacts)


class RecordingReplay:
    def __init__(self) -> None:
        self.applied: list[tuple[str, tuple[int, int]]] = []

    def apply(self, event: TickReplayEvent) -> None:
        self.applied.append((event.kind, event.order))


def _tick_event(order: tuple[int, int], kind: str, timestamp: int) -> TickReplayEvent:
    return TickReplayEvent(
        order=order,
        venue="uniswap_v3",
        kind=kind,
        row={"transaction": {"id": f"tx-{order}", "timestamp": timestamp}},
        sign=1 if kind == "liquidity" else 0,
    )


def test_ordered_tick_cursor_keeps_intervening_liquidity_and_distinct_cuts() -> None:
    day_start = 1_735_689_600
    events = (
        _tick_event((10, 1), "swap", day_start + 10),
        _tick_event((10, 2), "liquidity", day_start + 20),
        _tick_event((11, 1), "swap", day_start + 3_700),
    )
    hourly = RecordingReplay()
    cursor = OrderedTickStateCursor(events)
    cursor.apply_until(hourly, TickStateCut.hour_end(day_start + 3_600))
    assert hourly.applied == [("swap", (10, 1)), ("liquidity", (10, 2))]
    cursor.apply_until(hourly, TickStateCut.hour_end(day_start + 7_200))
    cursor.require_consumed()
    assert hourly.applied[-1] == ("swap", (11, 1))

    frontier = RecordingReplay()
    cursor = OrderedTickStateCursor(events)
    cursor.apply_until(frontier, TickStateCut.strict_before_event((10, 2)))
    assert frontier.applied == [("swap", (10, 1))]


def _route_day(day: str = "2025-01-01") -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "date": day,
            "reserve_hour_utc": 12,
            "src": "a",
            "tgt": "b",
            "vehicle": "v",
            "trade_size_usd": 1_000.0,
            "direct_output_usd": 900.0,
        }]
    )


def test_day_cache_refuses_missing_marker_and_mutated_content(tmp_path: Path) -> None:
    path = tmp_path / "20250101.parquet"
    identity = {"day": "20250101", "engine": "test", "state": {"tick/uniswap_v3": "abc"}}
    _route_day().to_parquet(path, index=False)
    assert not day_cache_is_current(path, identity=identity)

    write_day_cache(_route_day(), path, identity=identity)
    assert day_cache_is_current(path, identity=identity)
    marker = marker_path(path)
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["quote_key_sha256"] = "mutated"
    marker.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert not day_cache_is_current(path, identity=identity)

    write_day_cache(_route_day(), path, identity=identity)
    marker_path(path).unlink()
    assert not day_cache_is_current(path, identity=identity)

    write_day_cache(_route_day(), path, identity=identity)
    path.write_bytes(path.read_bytes() + b"mutated")
    assert not day_cache_is_current(path, identity=identity)


def test_ordered_shard_manifest_refuses_one_mutated_bundle(tmp_path: Path) -> None:
    paths = [tmp_path / "20250101.parquet", tmp_path / "20250102.parquet"]
    identities = [
        {"day": path.stem, "scope": "main", "quote_dependency_fingerprint": "engine"}
        for path in paths
    ]
    for path, identity in zip(paths, identities, strict=True):
        write_day_cache(
            _route_day(f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"),
            path,
            identity=identity,
        )
    output = tmp_path / "ordered.complete.json"
    write_ordered_shard_manifest(paths, identities=identities, output=output)
    record = json.loads(output.read_text(encoding="utf-8"))
    assert [shard["day"] for shard in record["shards"]] == ["20250101", "20250102"]

    marker_path(paths[1]).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing, stale, or mutated"):
        write_ordered_shard_manifest(paths, identities=identities, output=output)
