from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddvc import provenance


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "build_rent_incidence_panel_shards",
    ROOT / "scripts" / "build_rent_incidence_panel.py",
)
rent = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rent)


def v2_frame(day: str, pool: str, *, symbol: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "venue": ["uniswap_v2"],
            "day": [day],
            "pool": [pool],
            "sym0": [symbol],
            "capital_source": ["uniswap_v2.reserveUSD"],
            "quantity_kind": ["deposited_capital"],
            "pool_family": ["full_range_constant_product"],
            "invariant_family": ["full_range_constant_product"],
            "state_generation": ["provider_pool_day_v1"],
            "capital_validation_status": ["reported_plausible"],
            "exact_lag_valid": [False],
        }
    ).reindex(columns=rent.V2_COLUMNS)


def test_resume_selects_only_missing_or_schema_stale_days() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        cache = Path(temporary)
        rent._write_day_shard(
            v2_frame("20250101", "pool-a"),
            cache / "20250101.parquet",
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        pd.DataFrame({"day": ["20250102"]}).to_parquet(
            cache / "20250102.parquet", index=False
        )

        missing = rent._missing_day_shards(
            ["20250101", "20250102", "20250103"],
            cache,
            venue="uniswap_v2",
            columns=rent.V2_COLUMNS,
        )

        assert missing == ["20250102", "20250103"]


def test_resume_rejects_same_columns_with_wrong_arrow_type() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        cache = Path(temporary)
        path = cache / "20250101.parquet"
        rent._write_day_shard(
            v2_frame("20250101", "pool-a"),
            path,
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        valid = pq.read_table(path)
        wrong_schema = pa.schema(
            [
                pa.field(field.name, pa.int64(), nullable=False)
                if field.name == "pool"
                else field
                for field in rent.V2_SCHEMA
            ]
        )
        wrong = pa.Table.from_arrays(
            [
                pa.array([1], type=pa.int64())
                if field.name == "pool"
                else valid.column(field.name)
                for field in wrong_schema
            ],
            schema=wrong_schema,
        )
        pq.write_table(wrong, path)

        assert rent._missing_day_shards(
            ["20250101"],
            cache,
            venue="uniswap_v2",
            columns=rent.V2_COLUMNS,
        ) == ["20250101"]


def test_shard_writer_refuses_a_missing_semantic_column() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "20250101.parquet"
        incomplete = v2_frame("20250101", "pool-a").drop(columns="rv")
        with pytest.raises(ValueError, match="missing=.*rv"):
            rent._write_day_shard(
                incomplete,
                path,
                venue="uniswap_v2",
                day="20250101",
                columns=rent.V2_COLUMNS,
            )


def test_atomic_shard_write_rejects_duplicate_pool_day_and_preserves_prior_file() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "20250101.parquet"
        rent._write_day_shard(
            v2_frame("20250101", "old"),
            path,
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        before = path.read_bytes()
        duplicate = pd.concat(
            [v2_frame("20250101", "same"), v2_frame("20250101", "same")],
            ignore_index=True,
        )

        with pytest.raises(ValueError, match="duplicate"):
            rent._write_day_shard(
                duplicate,
                path,
                venue="uniswap_v2",
                day="20250101",
                columns=rent.V2_COLUMNS,
            )

        assert path.read_bytes() == before
        assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_assembly_refuses_a_missing_day_before_replacing_output(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cache = root / "cache"
        cache.mkdir()
        output = root / "panel.parquet"
        pd.DataFrame({"old": [1]}).to_parquet(output, index=False)
        before = output.read_bytes()
        rent._write_day_shard(
            v2_frame("20250101", "pool-a"),
            cache / "20250101.parquet",
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        monkeypatch.setattr(rent, "stamp", lambda *args, **kwargs: None)

        with pytest.raises(RuntimeError, match="1 day shards"):
            rent._assemble_family(
                days=["20250101", "20250102"],
                cache_dir=cache,
                venue="uniswap_v2",
                columns=rent.V2_COLUMNS,
                output=output,
                code_sources=[],
                canonical_inputs=[],
                generation="test",
            )

        assert output.read_bytes() == before


def test_assembly_unifies_null_and_string_shard_schema(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cache = root / "cache"
        output = root / "panel.parquet"
        rent._write_day_shard(
            v2_frame("20250101", "pool-a"),
            cache / "20250101.parquet",
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        rent._write_day_shard(
            v2_frame("20250102", "pool-b", symbol="TOKEN"),
            cache / "20250102.parquet",
            venue="uniswap_v2",
            day="20250102",
            columns=rent.V2_COLUMNS,
        )
        stamps = []
        monkeypatch.setattr(
            rent,
            "stamp",
            lambda artefact, **kwargs: stamps.append((artefact, kwargs)),
        )
        canonical = root / "canonical-input"
        canonical.touch()

        rent._assemble_family(
            days=["20250101", "20250102"],
            cache_dir=cache,
            venue="uniswap_v2",
            columns=rent.V2_COLUMNS,
            output=output,
            code_sources=["scripts/build_rent_incidence_panel.py"],
            canonical_inputs=[canonical],
            generation="test",
        )

        assembled = pq.read_table(output)
        assert assembled.num_rows == 2
        assert assembled.column("sym0").to_pylist() == [
            None,
            "TOKEN",
        ]
        assert stamps[0][0] == output
        assert stamps[0][1]["inputs"] == [canonical, cache]
        assert stamps[0][1]["rows"] == 2
        assert "generation test" in stamps[0][1]["notes"]


def test_interrupted_stamp_cannot_leave_old_provenance_blessing_new_panel(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cache = root / "cache"
        output = root / "panel.parquet"
        rent._write_day_shard(
            v2_frame("20250101", "new"),
            cache / "20250101.parquet",
            venue="uniswap_v2",
            day="20250101",
            columns=rent.V2_COLUMNS,
        )
        v2_frame("20240101", "old").to_parquet(output, index=False)
        old_sidecar = provenance.sidecar_path(output)
        old_sidecar.write_text('{"old": true}\n')
        monkeypatch.setattr(
            rent,
            "stamp",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("interrupted")),
        )

        with pytest.raises(RuntimeError, match="interrupted"):
            rent._assemble_family(
                days=["20250101"],
                cache_dir=cache,
                venue="uniswap_v2",
                columns=rent.V2_COLUMNS,
                output=output,
                code_sources=["scripts/build_rent_incidence_panel.py"],
                canonical_inputs=[],
                generation="new",
            )

        assert not old_sidecar.exists()
        assert pq.read_table(output).column("pool").to_pylist() == ["new"]


def test_top_n_is_part_of_the_v3_cache_namespace() -> None:
    root = Path("cache")
    assert rent._generation_cache_dir("v3", "abc", top_n=400, root=root) != (
        rent._generation_cache_dir("v3", "abc", top_n=200, root=root)
    )


def test_work_partition_changes_invalidate_the_shard_generation(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for relative in rent.V2_SHARD_CODE_SOURCES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {relative}\n")
        monkeypatch.setattr(provenance, "ROOT", root)

        before = rent.cache_key(rent.V2_SHARD_CODE_SOURCES)
        (root / "src/ddvc/work_partition.py").write_text("CHANGED = True\n")
        after = rent.cache_key(rent.V2_SHARD_CODE_SOURCES)

        assert "src/ddvc/work_partition.py" in rent.V2_SHARD_CODE_SOURCES
        assert after != before


def test_generation_change_aborts_before_publication(monkeypatch) -> None:
    monkeypatch.setattr(rent, "cache_key", lambda *args, **kwargs: "new")
    with pytest.raises(RuntimeError, match="changed during the build"):
        rent._require_generation_current(
            "old",
            code_sources=[],
            inputs=[],
        )


def test_v3_top_n_uses_full_calendar_not_a_systematic_date_sample(monkeypatch) -> None:
    days = [f"d{index:03d}" for index in range(180)]

    class LocalPool:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, function, items):
            return map(function, items)

    def counts(day):
        return {"episodic": 1_000} if day == "d001" else {"persistent": 1}

    monkeypatch.setattr(rent, "interruptible_process_pool", lambda _workers: LocalPool())
    monkeypatch.setattr(rent, "_day_input_bytes", lambda *args: 1)
    monkeypatch.setattr(rent, "_v3_count_day", counts)

    assert rent._v3_pool_universe(days, top_n=1, workers=3) == {"episodic"}


def test_v3_resume_replays_warm_prefix_but_writes_only_missing_day(monkeypatch) -> None:
    calls = []

    def day_state(day, keep, *, summarize):
        calls.append((day, summarize))
        events = [("pool", 0, 10, 100)] if day == "20250101" else []
        return {}, {}, events

    def day_frame(day, swaps, counts, index, trees):
        assert trees["pool"].prefix(0) == 100
        return v2_frame(day, "pool").reindex(columns=rent.V3_COLUMNS)

    written = []

    def write(frame, path, *, venue, day, columns):
        written.append((day, venue, columns))
        return 1

    monkeypatch.setattr(rent, "_v3_day_state", day_state)
    monkeypatch.setattr(rent, "_v3_day_frame", day_frame)
    monkeypatch.setattr(rent, "_write_day_shard", write)

    built, rows = rent._replay_v3_chunk(
        {
            "warm_days": ["20250101"],
            "chunk_days": ["20250102"],
            "build_days": ["20250102"],
            "keep": {"pool"},
            "tick_lists": {"pool": [0, 10]},
            "cache_dir": "cache",
        }
    )

    assert calls == [("20250101", False), ("20250102", True)]
    assert written == [("20250102", "uniswap_v3", rent.V3_COLUMNS)]
    assert (built, rows) == (1, 1)


def test_v3_parallel_chunks_match_serial_with_cached_event_day_and_burn(monkeypatch) -> None:
    events = {
        "d1": [("pool", 0, 10, 100)],
        "d2": [("pool", 0, 10, 20)],
        "d3": [("pool", 0, 10, -40)],
        "d4": [],
    }

    def day_state(day, keep, *, summarize):
        return {}, {}, events[day]

    def day_frame(day, swaps, counts, index, trees):
        frame = v2_frame(day, "pool").reindex(columns=rent.V3_COLUMNS)
        frame.loc[0, "liquidity"] = trees["pool"].prefix(0)
        return frame

    outputs = {}

    def write(frame, path, *, venue, day, columns):
        outputs[(path.parent.name, day)] = float(frame.loc[0, "liquidity"])
        return 1

    monkeypatch.setattr(rent, "_v3_day_state", day_state)
    monkeypatch.setattr(rent, "_v3_day_frame", day_frame)
    monkeypatch.setattr(rent, "_write_day_shard", write)

    common = {"keep": {"pool"}, "tick_lists": {"pool": [0, 10]}}
    rent._replay_v3_chunk(
        {
            **common,
            "warm_days": [],
            "chunk_days": ["d1", "d2", "d3", "d4"],
            "build_days": ["d1", "d3", "d4"],
            "cache_dir": "serial",
        }
    )
    rent._replay_v3_chunk(
        {
            **common,
            "warm_days": [],
            "chunk_days": ["d1", "d2"],
            "build_days": ["d1"],
            "cache_dir": "parallel-a",
        }
    )
    rent._replay_v3_chunk(
        {
            **common,
            "warm_days": ["d1", "d2"],
            "chunk_days": ["d3", "d4"],
            "build_days": ["d3", "d4"],
            "cache_dir": "parallel-b",
        }
    )

    assert outputs[("serial", "d1")] == outputs[("parallel-a", "d1")] == 100
    assert outputs[("serial", "d3")] == outputs[("parallel-b", "d3")] == 80
    assert outputs[("serial", "d4")] == outputs[("parallel-b", "d4")] == 80


def test_resume_cleans_only_orphaned_atomic_shard_temporaries() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        cache = Path(temporary)
        shard = cache / "20250101.parquet"
        orphan = cache / ".20250102.parquet.dead.tmp"
        unrelated = cache / "keep.tmp"
        shard.touch()
        orphan.touch()
        unrelated.touch()

        removed = rent._clean_interrupted_shard_temps(cache)

        assert removed == 1
        assert shard.exists()
        assert unrelated.exists()
        assert not orphan.exists()


def test_input_locks_follow_canonical_raw_then_market_state_order() -> None:
    source = (ROOT / "scripts" / "build_rent_incidence_panel.py").read_text()
    entrypoint = source.split('if __name__ == "__main__":', 1)[1]
    assert entrypoint.index("RAW_MARKET_DATA_LOCK") < entrypoint.index("MARKET_STATE_LOCK")
