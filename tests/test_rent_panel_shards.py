from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddvc import provenance
from ddvc.capital_contracts import CAPITAL_SOURCE, CP_CAPITAL_STATE_GENERATION


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
            "reported_capital_usd": [100.0],
            "reported_capital_source": ["uniswap_v2.reserveUSD"],
            "reconstructed_capital_usd": [100.0],
            "capital_usd": [100.0],
            "reserve_source": ["provider_pool_day_closing_reserves"],
            "reserve_state_timestamp": [1_735_775_999],
            "reserve_validation_status": ["positive_provider_pool_day_reserves"],
            "capital_source": [CAPITAL_SOURCE],
            "price_source": ["canonical_repriced_route_legs_with_address_time_sanity"],
            "quantity_kind": ["deposited_capital"],
            "pool_family": ["full_range_constant_product"],
            "invariant_family": ["full_range_constant_product"],
            "state_generation": [CP_CAPITAL_STATE_GENERATION],
            "capital_validation_status": ["exact_state_current"],
            "capital_valid": [True],
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


def test_missing_provider_capital_is_explicitly_typed_and_not_coerced(monkeypatch) -> None:
    base = v2_frame("20250101", "pool-a").drop(columns=list(rent.CAPITAL_COLUMNS))
    empty_capital = pd.DataFrame(columns=["day", "pool", *rent.CAPITAL_COLUMNS])
    monkeypatch.setattr(rent, "_capital_day", lambda _venue, _day, _path: empty_capital)

    merged = rent._merge_capital_day(
        base,
        venue="uniswap_v2",
        day="20250101",
        columns=rent.V2_COLUMNS,
        capital_path=Path("unused"),
    ).iloc[0]

    assert merged["reported_capital_source"] == "unavailable_missing_provider_pool_day"
    assert merged["reserve_source"] == "unavailable_missing_provider_pool_day"
    assert merged["reserve_validation_status"] == "unavailable_missing_provider_pool_day"
    assert merged["capital_source"] == CAPITAL_SOURCE
    assert merged["price_source"] == "unavailable_missing_provider_pool_day"
    assert merged["capital_validation_status"] == "missing_pool_day_capital"
    assert merged["quantity_kind"] == "deposited_capital"
    assert not merged["exact_lag_valid"]
    assert not merged["capital_valid"]
    assert pd.isna(merged[rent.CAPITAL_COLUMN])


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
        stamped = json.loads(provenance.sidecar_path(output).read_text())
        assert stamped["inputs"][0]["path"] == str(canonical)
        assert stamped["rows"] == 2
        assert "generation test" in stamped["notes"]
        assert "resumable cache" in stamped["notes"]


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
        old_panel = output.read_bytes()
        old_provenance = old_sidecar.read_bytes()
        monkeypatch.setattr(
            "ddvc.tables.prepare_stamp",
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

        assert output.read_bytes() == old_panel
        assert old_sidecar.read_bytes() == old_provenance


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


def test_v2_rent_build_uses_raw_lock_without_wide_market_state_lock() -> None:
    source = (ROOT / "scripts" / "build_rent_incidence_panel.py").read_text()
    execution = source.split("def main() -> None:", 1)[1].split(
        'if __name__ == "__main__":', 1
    )[0]
    assert "RAW_MARKET_DATA_LOCK" in execution
    assert "MARKET_STATE_LOCK" not in source
    assert "certified_cp_event_stream" in source
