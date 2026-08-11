from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from ddvc.analysis.dominance_cost_contract import (
    COMPARATOR_VEHICLES,
    NATIVE_VEHICLE,
    SUPPORT_STAGES,
    dominance_outcomes,
)
from ddvc.analysis.dominance_cost_release import (
    DOMINANCE_COST_RELEASE_RELATIVE,
    resolve_dominance_cost_release,
)
from ddvc.d3_stage_registry import D3_BUILD_STAGES
from scripts import build_dominance_cost_panel as builder


SOURCE_SCHEMA = pa.schema(
    [
        ("date", pa.large_string()),
        ("method", pa.large_string()),
        ("reserve_hour_utc", pa.int64()),
        ("src", pa.large_string()),
        ("src_sym", pa.large_string()),
        ("tgt", pa.large_string()),
        ("tgt_sym", pa.large_string()),
        ("vehicle", pa.large_string()),
        ("vehicle_sym", pa.large_string()),
        ("trade_size_usd", pa.float64()),
        ("direct_available", pa.bool_()),
        ("vehicle_available", pa.bool_()),
        ("direct_output_usd", pa.float64()),
        ("vehicle_output_usd", pa.float64()),
        ("direct_cost_advantage", pa.float64()),
        ("direct_source", pa.large_string()),
        ("direct_pool", pa.large_string()),
        ("hop1_source", pa.large_string()),
        ("hop1_pool", pa.large_string()),
        ("hop2_source", pa.large_string()),
        ("hop2_pool", pa.large_string()),
        ("realized_bridge_volume_usd", pa.float64()),
        ("n_realized_routes", pa.int64()),
    ]
)


def address(symbol: str) -> str:
    if symbol == "WETH":
        return NATIVE_VEHICLE
    return next(value for value, name in COMPARATOR_VEHICLES.items() if name == symbol)


def quote_row(
    vehicle_symbol: str,
    *,
    trade_size_usd: float,
    output_usd: float,
    available: bool = True,
    direct_available: bool = True,
    direct_output_usd: float = 985.0,
    method: str = "v2_cp_plus_v3_exact_tick",
) -> dict[str, object]:
    vehicle = address(vehicle_symbol)
    return {
        "date": "2026-01-01",
        "method": method,
        "reserve_hour_utc": 12,
        "src": address("DAI"),
        "src_sym": "DAI",
        "tgt": "0x00000000000000000000000000000000000000aa",
        "tgt_sym": "A",
        "vehicle": vehicle,
        "vehicle_sym": vehicle_symbol,
        "trade_size_usd": trade_size_usd,
        "direct_available": direct_available,
        "vehicle_available": available,
        "direct_output_usd": direct_output_usd,
        "vehicle_output_usd": output_usd,
        "direct_cost_advantage": 0.0,
        "direct_source": "uniswap_v3",
        "direct_pool": "0xdirect",
        "hop1_source": "uniswap_v3" if vehicle_symbol == "WETH" else "uniswap_v2",
        "hop1_pool": f"0x{vehicle_symbol.lower()}1",
        "hop2_source": "uniswap_v4" if vehicle_symbol == "WETH" else "sushiswap_v2",
        "hop2_pool": f"0x{vehicle_symbol.lower()}2",
        "realized_bridge_volume_usd": 1_000.0,
        "n_realized_routes": 1,
    }


def write_source(path: Path, rows: list[dict[str, object]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), path, compression="zstd")


def write_calendar(path: Path, days: list[str]) -> None:
    pq.write_table(
        pa.table(
            {
                "day": days,
                "output_rows": [1 if index == 0 else 0 for index, _day in enumerate(days)],
                "passed": [True] * len(days),
            }
        ),
        path,
        compression="zstd",
    )


def install_without_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "prepare_stamp", lambda *args, **kwargs: b"prepared")
    monkeypatch.setattr(builder, "verify", lambda _path: {"status": "ok"})

    def install(staged: Path, target: Path, _stamp: bytes) -> Path:
        Path(staged).replace(target)
        return target.with_suffix(target.suffix + ".prov.json")

    monkeypatch.setattr(builder, "install_stamped_artifact", install)


def release_members(pointer: Path) -> tuple[Path, Path]:
    release = resolve_dominance_cost_release(pointer)
    return release.artifacts["panel"], release.artifacts["support"]


def sorted_pair_stage(path: Path) -> pa.Table:
    table = pq.read_table(path)
    indices = pc.sort_indices(
        table,
        sort_keys=[
            ("date", "ascending"),
            ("reserve_hour_utc", "ascending"),
            ("src", "ascending"),
            ("tgt", "ascending"),
            ("trade_size_usd", "ascending"),
            ("comparator", "ascending"),
        ],
    )
    return pc.take(table, indices)


def test_streamed_candidate_stage_matches_globally_sorted_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.parquet"
    streamed = tmp_path / "streamed.parquet"
    reference = tmp_path / "reference.parquet"
    rows = [
        quote_row("USDC", trade_size_usd=10_000.0, output_usd=9_800.0),
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        {**quote_row("WETH", trade_size_usd=1_000.0, output_usd=995.0), "date": "2026-01-02"},
        {**quote_row("USDT", trade_size_usd=1_000.0, output_usd=985.0), "date": "2026-01-02"},
    ]
    write_source(source, rows)
    connection = builder.duckdb.connect()
    try:
        builder._write_candidate_stage(connection, source, streamed, batch_days=1)
        connection.execute(
            f"COPY ({builder._candidate_select_sql(source)}) "
            f"TO '{reference.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
    assert pq.read_table(streamed).equals(pq.read_table(reference))


def test_streamed_pair_stage_matches_globally_sorted_reference(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.parquet"
    streamed = tmp_path / "streamed.parquet"
    reference = tmp_path / "reference.parquet"
    rows = [
        quote_row("USDC", trade_size_usd=10_000.0, output_usd=9_800.0),
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        quote_row("DAI", trade_size_usd=1_000.0, output_usd=975.0, available=False),
        quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
        quote_row("WETH", trade_size_usd=10_000.0, output_usd=9_900.0),
    ]
    second_day = [
        {**quote_row("WETH", trade_size_usd=1_000.0, output_usd=995.0), "date": "2026-01-02"},
        {**quote_row("USDT", trade_size_usd=1_000.0, output_usd=985.0), "date": "2026-01-02"},
    ]
    rows.extend(second_day)
    write_source(candidate, rows)
    connection = builder.duckdb.connect()
    try:
        builder._write_pair_stage(connection, candidate, streamed, batch_days=1)
        connection.execute(
            f"""
            COPY (
                WITH {builder._pair_ctes(candidate)}
                SELECT * FROM supported
                ORDER BY date, reserve_hour_utc, src, tgt, trade_size_usd, comparator
            ) TO '{reference.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        connection.close()
    assert sorted_pair_stage(streamed).equals(pq.read_table(reference))
    assert pq.read_table(streamed).equals(pq.read_table(reference))


def test_batched_stage_bytes_and_release_are_deterministic_across_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    first_pointer = tmp_path / "first" / "current.json"
    second_pointer = tmp_path / "second" / "current.json"
    days = [f"2026-01-{day:02d}" for day in range(1, builder.STAGE_BATCH_DAYS + 2)]
    rows = [
        {**quote_row(symbol, trade_size_usd=1_000.0, output_usd=output), "date": day}
        for day in days
        for symbol, output in (("WETH", 990.0), ("USDC", 980.0), ("DAI", 975.0))
    ]
    write_source(source, rows)
    write_calendar(calendar, [day.replace("-", "") for day in days])
    install_without_provenance(monkeypatch)
    first = builder.build_panel(
        source,
        calendar,
        pointer_path=first_pointer,
        cache_root=tmp_path / "first-cache",
        threads=1,
        memory_limit="256MB",
    )
    second = builder.build_panel(
        source,
        calendar,
        pointer_path=second_pointer,
        cache_root=tmp_path / "second-cache",
        threads=2,
        memory_limit="256MB",
    )
    first_panel, first_support = release_members(first_pointer)
    second_panel, second_support = release_members(second_pointer)
    first_candidate = next((tmp_path / "first-cache").glob("candidate-*.parquet"))
    second_candidate = next((tmp_path / "second-cache").glob("candidate-*.parquet"))
    first_pair = next((tmp_path / "first-cache").glob("pair-*.parquet"))
    second_pair = next((tmp_path / "second-cache").glob("pair-*.parquet"))
    assert first["pair_stage_rows"] == second["pair_stage_rows"]
    assert pq.read_table(first_candidate).equals(pq.read_table(second_candidate))
    assert first_candidate.read_bytes() == second_candidate.read_bytes()
    assert pq.read_table(first_pair).equals(pq.read_table(second_pair))
    assert first_pair.read_bytes() == second_pair.read_bytes()
    assert pq.read_table(first_panel).equals(pq.read_table(second_panel))
    assert pq.read_table(first_support).equals(pq.read_table(second_support))


def test_streaming_pairwise_panel_retains_member_architecture_and_zero_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    rows = [
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
        quote_row("WETH", trade_size_usd=10_000.0, output_usd=9_900.0, direct_available=False, direct_output_usd=0.0),
        quote_row("USDC", trade_size_usd=10_000.0, output_usd=9_800.0, direct_available=False, direct_output_usd=0.0),
    ]
    write_source(source, rows)
    write_calendar(calendar, ["20260101", "20260102"])
    install_without_provenance(monkeypatch)
    result = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        memory_limit="256MB",
    )
    panel, support = release_members(pointer)
    assert result == {
        "source_rows": 4,
        "calendar_days": 2,
        "candidate_rows": 4,
        "pair_stage_rows": 6,
        "panel_rows": 2,
        "support_rows": 24,
        "attempted_pairs": 6,
        "candidate_stage_reused": False,
        "pair_stage_reused": False,
        "generation_id": resolve_dominance_cost_release(pointer).generation_id,
    }
    paired = pq.read_table(panel).to_pylist()
    assert {row["comparator_symbol"] for row in paired} == {"USDC"}
    assert {row["available_candidate_count"] for row in paired} == {2}
    first = next(row for row in paired if row["trade_size_usd"] == 1_000.0)
    expected = dominance_outcomes(
        weth_output_usd=990.0,
        comparator_output_usd=980.0,
        trade_size_usd=1_000.0,
        direct_output_usd=985.0,
    )
    for outcome, value in expected.items():
        assert first[outcome] == pytest.approx(value) if isinstance(value, float) else first[outcome] == value
    assert first["weth_signed_win"] in {-1, 0, 1}
    assert first["weth_direct_threshold_edge"] == 1
    assert (
        first["weth_hop1_source"],
        first["weth_hop2_source"],
        first["comparator_hop1_source"],
        first["comparator_hop2_source"],
    ) == ("uniswap_v3", "uniswap_v4", "uniswap_v2", "sushiswap_v2")
    assert (
        first["weth_hop1_pool"],
        first["weth_hop2_pool"],
        first["comparator_hop1_pool"],
        first["comparator_hop2_pool"],
    ) == ("0xweth1", "0xweth2", "0xusdc1", "0xusdc2")
    second = next(row for row in paired if row["trade_size_usd"] == 10_000.0)
    assert second["direct_available"] is False
    assert second["direct_output_usd"] is None
    assert second["weth_direct_threshold_edge"] is None
    ledger = pq.read_table(support).to_pylist()
    for row in ledger:
        assert all(type(row[stage]) is int for stage in SUPPORT_STAGES)
    absent = [row for row in ledger if row["date"] == "2026-01-02"]
    assert len(absent) == 12
    assert all(all(row[stage] == 0 for stage in SUPPORT_STAGES) for row in absent)
    dai = [row for row in ledger if row["comparator_symbol"] == "DAI"]
    assert len(dai) == 6
    assert all(all(row[stage] == 0 for stage in SUPPORT_STAGES) for row in dai)
    usdc = {
        row["trade_size_usd"]: row
        for row in ledger
        if row["date"] == "2026-01-01" and row["comparator_symbol"] == "USDC"
    }
    assert [usdc[1_000.0][stage] for stage in SUPPORT_STAGES] == [1, 1, 1, 1, 1]
    assert [usdc[10_000.0][stage] for stage in SUPPORT_STAGES] == [1, 1, 1, 0, 0]
    marker = json.loads(pointer.read_text(encoding="utf-8"))
    assert marker["generation_id"] == result["generation_id"]
    assert set(marker["artifacts"]) == {"panel", "support"}
    panel_digest = panel.read_bytes()
    repeated = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        memory_limit="256MB",
    )
    assert repeated["candidate_stage_reused"] is True
    assert repeated["pair_stage_reused"] is True
    assert repeated["generation_id"] == result["generation_id"]
    assert panel.read_bytes() == panel_digest


def test_pair_member_method_drift_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
            quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0, method="other"),
        ],
    )
    write_calendar(calendar, ["20260101"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="asserted common fields"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


def test_normalized_candidate_quote_duplicates_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    weth = quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0)
    write_source(source, [weth, {**weth, "vehicle": str(weth["vehicle"]).upper()}])
    write_calendar(calendar, ["20260101"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="duplicate candidate quote cells"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


def test_source_outside_released_calendar_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
            quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
        ],
    )
    write_calendar(calendar, ["20260102"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="outside the released calendar"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


def test_source_outside_locked_notional_grid_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=2_000.0, output_usd=1_990.0),
            quote_row("USDC", trade_size_usd=2_000.0, output_usd=1_980.0),
        ],
    )
    write_calendar(calendar, ["20260101"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="outside the locked grid"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


@pytest.mark.parametrize("direct_output", [math.nan, 0.0, -1.0])
def test_present_invalid_direct_output_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, direct_output: float
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0, direct_output_usd=direct_output),
            quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0, direct_output_usd=direct_output),
        ],
    )
    write_calendar(calendar, ["20260101"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="present direct output"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


@pytest.mark.parametrize("vehicle_symbol", ["WETH", "USDC"])
@pytest.mark.parametrize("indirect_output", [None, math.nan, 0.0, -1.0])
def test_available_invalid_indirect_output_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vehicle_symbol: str,
    indirect_output: float | None,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    rows = [
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
    ]
    for row in rows:
        if row["vehicle"] == address(vehicle_symbol):
            row["vehicle_output_usd"] = indirect_output
    write_source(source, rows)
    write_calendar(calendar, ["20260101"])
    install_without_provenance(monkeypatch)
    with pytest.raises(ValueError, match="available indirect output"):
        builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    assert not pointer.exists()


def test_malformed_candidate_and_pair_cache_provenance_is_rebuilt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    cache_root = tmp_path / "cache"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
            quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
        ],
    )
    write_calendar(calendar, ["20260101"])
    first = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        cache_root=cache_root,
        memory_limit="256MB",
    )
    assert first["candidate_stage_reused"] is False
    assert first["pair_stage_reused"] is False
    candidate = next(cache_root.glob("candidate-*.parquet"))
    pair = next(cache_root.glob("pair-*.parquet"))
    builder.sidecar_path(candidate).write_text("{bad", encoding="utf-8")
    after_candidate_tamper = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        cache_root=cache_root,
        memory_limit="256MB",
    )
    assert after_candidate_tamper["candidate_stage_reused"] is False
    assert after_candidate_tamper["pair_stage_reused"] is True
    builder.sidecar_path(pair).write_text("{bad", encoding="utf-8")
    after_pair_tamper = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        cache_root=cache_root,
        memory_limit="256MB",
    )
    assert after_pair_tamper["candidate_stage_reused"] is True
    assert after_pair_tamper["pair_stage_reused"] is False


def test_cache_provenance_io_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = tmp_path / "candidate.parquet"
    stage.write_bytes(b"cache")
    monkeypatch.setattr(builder, "verify", lambda _path: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        builder._stage_current(stage)


@pytest.mark.parametrize("damage", ["missing_support", "tampered_panel", "tampered_provenance"])
def test_pointer_resolver_rejects_partial_or_tampered_selected_generation(
    tmp_path: Path,
    damage: str,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    write_source(
        source,
        [
            quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
            quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
        ],
    )
    write_calendar(calendar, ["20260101"])
    builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        memory_limit="256MB",
    )
    selected = resolve_dominance_cost_release(pointer)
    if damage == "missing_support":
        selected.artifacts["support"].unlink()
    elif damage == "tampered_panel":
        selected.artifacts["panel"].write_bytes(b"tampered")
    else:
        builder.sidecar_path(selected.artifacts["panel"]).write_text("{}\n", encoding="utf-8")
    with pytest.raises((FileNotFoundError, ValueError)):
        resolve_dominance_cost_release(pointer)


def test_marker_last_interruption_preserves_prior_generation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    rows = [
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
    ]
    write_source(source, rows)
    write_calendar(calendar, ["20260101"])
    first = builder.build_panel(
        source,
        calendar,
        pointer_path=pointer,
        memory_limit="256MB",
    )
    def interrupted(_path: Path, _payload: dict[str, object]) -> None:
        raise RuntimeError("simulated pointer interruption")

    with pytest.raises(RuntimeError, match="pointer interruption"):
        builder.build_panel(
            source,
            calendar,
            pointer_path=pointer,
            memory_limit="256MB",
            write_pointer=interrupted,
        )
    assert resolve_dominance_cost_release(pointer).generation_id == first["generation_id"]


def test_pointer_resolves_generation_paths_and_retains_prior_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "route_cost_panel_v2.parquet"
    calendar = tmp_path / "unified_route_quality.parquet"
    pointer = tmp_path / "release" / "current.json"
    rows = [
        quote_row("WETH", trade_size_usd=1_000.0, output_usd=990.0),
        quote_row("USDC", trade_size_usd=1_000.0, output_usd=980.0),
    ]
    write_source(source, rows)
    write_calendar(calendar, ["20260101"])
    builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    first = resolve_dominance_cost_release(pointer)
    assert first.artifacts["panel"] == pointer.parent / "generations" / first.generation_id / builder.RELEASE_FILENAMES["panel"]
    assert first.artifacts["support"] == pointer.parent / "generations" / first.generation_id / builder.RELEASE_FILENAMES["support"]
    assert not (pointer.parent / builder.RELEASE_FILENAMES["panel"]).exists()
    assert not (pointer.parent / builder.RELEASE_FILENAMES["support"]).exists()
    rows[1]["vehicle_output_usd"] = 979.0
    write_source(source, rows)
    builder.build_panel(source, calendar, pointer_path=pointer, memory_limit="256MB")
    second = resolve_dominance_cost_release(pointer)
    assert second.generation_id != first.generation_id
    assert all(path.is_file() for path in first.artifact_paths)


def test_registered_outputs_have_exactly_one_materializer() -> None:
    outputs = {DOMINANCE_COST_RELEASE_RELATIVE}
    for output in outputs:
        assert [stage.script for stage in D3_BUILD_STAGES if output in stage.outputs] == [
            "build_dominance_cost_panel.py"
        ]
