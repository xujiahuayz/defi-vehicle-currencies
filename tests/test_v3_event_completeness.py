from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import pytest

import ddvc.v3_event_completeness as contract
import scripts.audit_v3_graph_event_completeness as auditor
from ddvc.artifact_release import file_sha256
from ddvc.v3_event_completeness import (
    COUNT_FIELDS,
    V3_COMPARISON_LEDGER,
    V3_CORE_EVENTS,
    V3_EVENT_SOURCE_SCHEMA_VERSION,
    V3_IDENTITY_FIELDS,
    V3_EXCEPTION_FIELDS,
    V3_PAYLOAD_FIELDS,
    V3_POOL_PERIMETER,
    V3_QUARANTINE_FIELDS,
    V3_RECONCILIATION_SCOPE,
    V3EventPayload,
    V3PoolAuthority,
    audit_calendar_sha256,
    block_perimeter_sha256,
    canonical_event_map,
    compare_event_maps,
    exact_event_map,
    ensure_block_header_snapshot,
    pool_authorities,
    pool_perimeter_sha256,
    validate_v3_event_source_certificate,
    validate_v3_event_source_evidence_bundle,
)
from ddvc.v3_inventory import PoolStatic
from ddvc.v3_pool_registry import V3FactoryPool, registry_sha256


POOL = "0x" + "11" * 20
TOKEN0 = "0x" + "22" * 20
TOKEN1 = "0x" + "33" * 20
DAY = "20250115"


def authority() -> V3PoolAuthority:
    return V3PoolAuthority(POOL, TOKEN0, TOKEN1, 6, 18, 3_000, 60)


def payload() -> V3EventPayload:
    return V3EventPayload(
        1_700_000_000,
        TOKEN0,
        TOKEN1,
        6,
        18,
        3_000,
        60,
        -100,
        200,
        2**96,
        -12,
        None,
        None,
        None,
    )


def test_auditor_help_never_starts_the_expensive_build(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["audit_v3_graph_event_completeness.py", "--help"])
    monkeypatch.setattr(
        auditor,
        "build",
        lambda **_kwargs: pytest.fail("--help started the expensive audit"),
    )
    with pytest.raises(SystemExit) as stopped:
        auditor.main()
    assert stopped.value.code == 0


def test_auditor_preflight_reports_missing_state_before_raw_scan(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="build_market_state.py.*--audit-calendar"):
        auditor.require_audit_state_inputs([DAY], state_root=tmp_path)


def test_auditor_preflight_rejects_failed_state_before_raw_scan(
    tmp_path: Path, monkeypatch
) -> None:
    auditor.tick_partition_path("uniswap_v3", DAY, root=tmp_path).parent.mkdir(
        parents=True
    )
    auditor.tick_partition_path("uniswap_v3", DAY, root=tmp_path).touch()
    auditor.tick_quality_path("uniswap_v3", DAY, root=tmp_path).touch()
    monkeypatch.setattr(
        auditor,
        "read_tick_quality",
        lambda *_args, **_kwargs: SimpleNamespace(passed=False),
    )

    with pytest.raises(ValueError, match=r"stale=0, failed=1.*upstream state data contract"):
        auditor.require_audit_state_inputs([DAY], state_root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestamp", 1_700_000_001),
        ("token0", TOKEN1),
        ("decimals0", 18),
        ("fee_pips", 500),
        ("tick_spacing", 10),
        ("amount0_raw", -101),
        ("amount1_raw", 201),
        ("sqrt_price_x96", 2**96 + 1),
        ("tick", -11),
        ("liquidity_delta", 1),
        ("tick_lower", -60),
        ("tick_upper", 60),
    ],
)
def test_every_registered_payload_field_is_comparison_load_bearing(
    field: str, value: object
) -> None:
    key = ("swap", 100, "0xtx", 7, POOL)
    summaries, exceptions = compare_event_maps(
        DAY,
        {key: payload()},
        {key: replace(payload(), **{field: value})},
        Counter({key: 1}),
    )
    row = next(row for row in summaries if row["event_type"] == "swap")
    assert row["payload_mismatches"] == 1
    assert [item["status"] for item in exceptions] == ["payload_mismatch"]


def test_exact_and_canonical_maps_retain_swap_and_liquidity_state() -> None:
    authorities = {POOL: authority()}
    raw = [
        {
            "event_type": "mint",
            "pool": POOL,
            "block_number": 100,
            "tx_hash": "0xmint",
            "log_index": 1,
            "amount0_delta_raw": 1_500_000,
            "amount1_delta_raw": 2 * 10**18,
            "sqrt_price_x96": None,
            "tick": None,
            "liquidity_amount": 99,
            "tick_lower": -120,
            "tick_upper": 120,
        },
        {
            "event_type": "swap",
            "pool": POOL,
            "block_number": 101,
            "tx_hash": "0xswap",
            "log_index": 2,
            "amount0_delta_raw": -1_000_000,
            "amount1_delta_raw": 10**18,
            "sqrt_price_x96": 2**96,
            "tick": -7,
            "liquidity_amount": None,
            "tick_lower": None,
            "tick_upper": None,
        },
    ]
    exact = exact_event_map(raw, authorities, {100: 10, 101: 11})
    assert exact[("mint", 100, "0xmint", 1, POOL)].liquidity_delta == 99
    assert exact[("mint", 100, "0xmint", 1, POOL)].tick_lower == -120
    assert exact[("swap", 101, "0xswap", 2, POOL)].sqrt_price_x96 == 2**96
    assert exact[("swap", 101, "0xswap", 2, POOL)].tick == -7

    canonical = pd.DataFrame(
        [
            {
                "pool": POOL,
                "record_type": "liquidity",
                "source_stream": "burns",
                "block_number": 102,
                "tx_hash": "0xburn",
                "log_index": 3,
                "timestamp": 12,
                "token0_raw": TOKEN0,
                "token1_raw": TOKEN1,
                "decimals0": 6,
                "decimals1": 18,
                "amount0": "2.5",
                "amount1": "3",
                "sqrt_price_x96": None,
                "tick": None,
                "liquidity_delta": -50,
                "tick_lower": -60,
                "tick_upper": 60,
            }
        ]
    )
    observed, occurrences = canonical_event_map(canonical, authorities)
    key = ("burn", 102, "0xburn", 3, POOL)
    assert occurrences[key] == 1
    assert observed[key].liquidity_delta == -50
    assert observed[key].amount0_raw == 2_500_000


def test_canonical_map_uses_authority_for_absent_provider_statics() -> None:
    frame = pd.DataFrame(
        [
            {
                "pool": POOL,
                "record_type": "swap",
                "source_stream": "swaps",
                "block_number": 101,
                "tx_hash": "0xswap",
                "log_index": 2,
                "timestamp": 11,
                "token0_raw": None,
                "token1_raw": None,
                "decimals0": None,
                "decimals1": None,
                "amount0": "-1",
                "amount1": "1",
                "sqrt_price_x96": str(2**96),
                "tick": -7,
                "liquidity_delta": None,
                "tick_lower": None,
                "tick_upper": None,
            }
        ]
    )
    observed, _occurrences = canonical_event_map(frame, {POOL: authority()})
    key = ("swap", 101, "0xswap", 2, POOL)
    assert observed[key].decimals0 == 6
    assert observed[key].decimals1 == 18
    frame.loc[0, "token0_raw"] = TOKEN1
    with pytest.raises(ValueError, match="wrong factory/token statics"):
        canonical_event_map(frame, {POOL: authority()})


def test_duplicate_multiplicity_counts_every_extra_row() -> None:
    key = ("mint", 100, "0xtx", 1, POOL)
    summaries, exceptions = compare_event_maps(
        DAY,
        {key: payload()},
        {key: payload()},
        Counter({key: 4}),
    )
    mint = next(row for row in summaries if row["event_type"] == "mint")
    assert mint["canonical_duplicate_rows"] == 3
    assert exceptions[0]["duplicate_rows"] == 3


def test_block_header_fetch_keeps_only_a_bounded_future_window(
    tmp_path: Path, monkeypatch
) -> None:
    class Future:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def result(self) -> dict[str, object]:
            return self.value

    class Pool:
        def submit(self, _function, block: int, **_kwargs) -> Future:
            return Future({"block_number": block, "timestamp": block + 1})

    @contextmanager
    def fake_pool(*, max_workers: int):
        assert max_workers == 2
        yield Pool()

    maximum = 0

    def fake_wait(futures, *, return_when):
        nonlocal maximum
        assert return_when == contract.FIRST_COMPLETED
        maximum = max(maximum, len(futures))
        completed = {next(iter(futures))}
        return completed, set(futures) - completed

    installed: list[dict[str, object]] = []

    def fake_write(headers, path: Path, **_kwargs) -> None:
        installed.extend(headers)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("installed\n", encoding="utf-8")

    monkeypatch.setattr(contract, "interruptible_thread_pool", fake_pool)
    monkeypatch.setattr(contract, "wait", fake_wait)
    monkeypatch.setattr(contract, "write_block_header_snapshot", fake_write)
    monkeypatch.setattr(
        contract,
        "iter_block_header_snapshot",
        lambda _path, **_kwargs: iter(installed),
    )
    path = tmp_path / "headers.jsonl"
    assert ensure_block_header_snapshot(range(1, 21), path, workers=2) == path
    assert maximum == 4
    assert [row["block_number"] for row in installed] == list(range(1, 21))


def test_v3_release_resolution_requires_current_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    observed: dict[str, object] = {}
    release = object()

    def resolve(pointer_path: Path, **kwargs):
        observed.update(kwargs)
        observed["pointer_path"] = pointer_path
        return release

    monkeypatch.setattr(contract, "resolve_artifact_release", resolve)
    pointer = tmp_path / "current.json"
    assert contract.resolve_v3_event_source_release(pointer) is release
    assert observed["pointer_path"] == pointer
    assert observed["require_current_provenance"] is True


def _summary() -> pd.DataFrame:
    rows = []
    for event_type in V3_CORE_EVENTS:
        rows.append(
            {
                "day": DAY,
                "event_type": event_type,
                "exact_events": 0,
                "canonical_events": 0,
                "matched_identities": 0,
                "missing_from_canonical": 0,
                "canonical_only": 0,
                "canonical_duplicate_rows": 0,
                "payload_mismatches": 0,
                "passed": True,
            }
        )
    result = pd.DataFrame(rows)
    result[list(COUNT_FIELDS)] = result[list(COUNT_FIELDS)].astype("int64")
    result["passed"] = result["passed"].astype(bool)
    return result


def _certificate(summary: pd.DataFrame) -> dict[str, object]:
    corrections: dict[str, object] = {}
    raw_by_event = {
        event_type: int(
            summary.loc[summary["event_type"] == event_type, "exact_events"].sum()
        )
        for event_type in contract.EVENT_TOPICS
    }
    classification = contract.inventory_classification_record(
        [(1, 200)],
        raw_logs=sum(raw_by_event.values()),
        raw_by_event=raw_by_event,
        quarantine_rows=[],
    )
    return {
        "schema_version": V3_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": audit_calendar_sha256([DAY]),
        "audit_dates": 1,
        "first_day": DAY,
        "last_day": DAY,
        "summary_rows": 3,
        "exception_rows": 0,
        "event_types": list(V3_CORE_EVENTS),
        "pool_perimeter": V3_POOL_PERIMETER,
        "comparison_ledger": V3_COMPARISON_LEDGER,
        "reconciliation_scope": V3_RECONCILIATION_SCOPE,
        "identity_fields": list(V3_IDENTITY_FIELDS),
        "payload_fields": list(V3_PAYLOAD_FIELDS),
        "factory_registry_sha256": "1" * 64,
        "pool_perimeter_sha256": "2" * 64,
        "ordered_raw_manifest_sha256": "3" * 64,
        "block_header_snapshot_sha256": "4" * 64,
        "block_perimeter_sha256": "5" * 64,
        "correction_generations": corrections,
        "correction_generations_sha256": contract.correction_generation_sha256(
            corrections
        ),
        "inventory_classification": classification,
        "inventory_classification_sha256": contract.canonical_json_sha256(
            classification
        ),
        "pool_count": 1,
        "quarantine_rows": 0,
        "raw_inventory_logs": int(summary["exact_events"].sum()),
        **{field: int(summary[field].sum()) for field in COUNT_FIELDS},
    }


def _empty_exceptions() -> pd.DataFrame:
    result = pd.DataFrame(columns=list(V3_EXCEPTION_FIELDS))
    for field in ("block_number", "log_index", "duplicate_rows"):
        result[field] = result[field].astype("int64")
    return result


def _empty_quarantine() -> pd.DataFrame:
    result = pd.DataFrame(columns=list(V3_QUARANTINE_FIELDS))
    for field in ("first_block", "last_block", "logs"):
        result[field] = result[field].astype("int64")
    for field in result.columns:
        if field.endswith("_logs"):
            result[field] = result[field].astype("int64")
    return result


@pytest.mark.parametrize("defect", ["float_count", "broken_algebra", "stale_calendar"])
def test_certificate_rejects_adversarial_count_and_calendar_contracts(
    defect: str,
) -> None:
    summary = _summary()
    certificate = _certificate(summary)
    expected = [DAY]
    if defect == "float_count":
        summary["exact_events"] = summary["exact_events"].astype(float)
    elif defect == "broken_algebra":
        summary.loc[0, "exact_events"] = 1
    else:
        expected = ["20250215"]
    with pytest.raises(ValueError):
        validate_v3_event_source_certificate(
            summary,
            _empty_exceptions(),
            _empty_quarantine(),
            certificate,
            expected,
        )


def test_full_consumer_perimeter_rejects_any_nonfactory_pool() -> None:
    pools = [
        V3FactoryPool(POOL, TOKEN0, TOKEN1, 3_000, 60, 1, "0x" + "1" * 64, "0x1", 0),
        V3FactoryPool("0x" + "44" * 20, TOKEN0, TOKEN1, 500, 10, 2, "0x" + "2" * 64, "0x2", 0),
    ]
    unknown = "0x" + "55" * 20
    statics = {unknown: PoolStatic(unknown, TOKEN0, TOKEN1, "A", "B", 6, 18)}
    with pytest.raises(ValueError, match="full consumer statics disagree"):
        pool_authorities(pools, statics)


def test_full_consumer_perimeter_may_be_a_strict_factory_subset() -> None:
    pools = [
        V3FactoryPool(POOL, TOKEN0, TOKEN1, 3_000, 60, 1, "0x" + "1" * 64, "0x1", 0),
        V3FactoryPool("0x" + "44" * 20, TOKEN0, TOKEN1, 500, 10, 2, "0x" + "2" * 64, "0x2", 0),
    ]
    statics = {POOL: PoolStatic(POOL, TOKEN0, TOKEN1, "A", "B", 6, 18)}
    observed = pool_authorities(pools, statics)
    assert set(observed) == {POOL}


def test_independent_reopener_rederives_state_and_rejects_payload_drift(
    tmp_path: Path, monkeypatch
) -> None:
    factory = V3FactoryPool(
        POOL,
        TOKEN0,
        TOKEN1,
        3_000,
        60,
        1,
        "0x" + "1" * 64,
        "0x1",
        0,
    )
    static = PoolStatic(POOL, TOKEN0, TOKEN1, "A", "B", 6, 18)
    raw_event = {
        "event_type": "swap",
        "pool": POOL,
        "block_number": 100,
        "tx_hash": "0xtx",
        "log_index": 7,
        "amount0_delta_raw": -1_000_000,
        "amount1_delta_raw": 10**18,
        "sqrt_price_x96": 2**96,
        "tick": -7,
        "liquidity_amount": None,
        "tick_lower": None,
        "tick_upper": None,
    }
    state = pd.DataFrame(
        [
            {
                "pool": POOL,
                "record_type": "swap",
                "source_stream": "swaps",
                "block_number": 100,
                "tx_hash": "0xtx",
                "log_index": 7,
                "timestamp": 1_700_000_000,
                "token0_raw": TOKEN0,
                "token1_raw": TOKEN1,
                "decimals0": 6,
                "decimals1": 18,
                "amount0": "-1",
                "amount1": "1",
                "sqrt_price_x96": str(2**96),
                "tick": -7,
                "liquidity_delta": None,
                "tick_lower": None,
                "tick_upper": None,
            }
        ]
    )
    exact = exact_event_map([raw_event], {POOL: authority()}, {100: 1_700_000_000})
    canonical, occurrences = canonical_event_map(state, {POOL: authority()})
    rows, exceptions = compare_event_maps(DAY, exact, canonical, occurrences)
    assert not exceptions
    summary = pd.DataFrame(rows)
    summary[list(COUNT_FIELDS)] = summary[list(COUNT_FIELDS)].astype("int64")
    summary["passed"] = summary["passed"].astype(bool)

    manifest = tmp_path / "ordered.json"
    monkeypatch.setattr(contract, "V3_EVENT_HEADER_ROOT", tmp_path / "headers")
    certificate = _certificate(summary)
    frozen_upper = {
        "block_number": 2_000,
        "block_hash": "0xblock",
        "header_identity_sha256": "6" * 64,
    }
    factory_certificate = {
        "registry_sha256": registry_sha256([factory]),
        "registry_snapshot_upper_block": 2_000,
        "registry_snapshot_upper_block_hash": "0xblock",
    }
    classification = contract.inventory_classification_record(
        [(1, 999), (1_000, 1_999), (2_000, 2_000)],
        raw_logs=1,
        raw_by_event={
            name: int(name == "swap") for name in contract.EVENT_TOPICS
        },
        quarantine_rows=[],
    )
    certificate["inventory_classification"] = classification
    certificate["inventory_classification_sha256"] = (
        contract.canonical_json_sha256(classification)
    )
    manifest.write_text(
        contract.json.dumps(
            {
                "status": "complete",
                "start_block": 1,
                "end_block": 2_000,
                "chunk_size": 1_000,
                "chunk_count": 3,
                "raw_logs": 1,
                "raw_by_event": {
                    name: int(name == "swap") for name in contract.EVENT_TOPICS
                },
                "factory_identity": {
                    "registry_sha256": registry_sha256([factory]),
                    "registry_snapshot_upper_block": 2_000,
                    "registry_snapshot_upper_block_hash": "0xblock",
                    "frozen_upper_identity_sha256": "6" * 64,
                },
                "chunks": [
                    {"lower": 1, "upper": 999},
                    {"lower": 1_000, "upper": 1_999},
                    {"lower": 2_000, "upper": 2_000},
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    certificate.update(
        {
            "factory_registry_sha256": registry_sha256([factory]),
            "pool_perimeter_sha256": pool_perimeter_sha256({POOL: authority()}),
            "ordered_raw_manifest_sha256": file_sha256(manifest),
            "block_perimeter_sha256": block_perimeter_sha256([100]),
            "raw_inventory_logs": 1,
            **{field: int(summary[field].sum()) for field in COUNT_FIELDS},
        }
    )
    snapshot = contract.certified_header_snapshot_path([DAY], certificate)
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("header\n", encoding="utf-8")
    certificate["block_header_snapshot_sha256"] = file_sha256(snapshot)

    import ddvc.state_data as state_data
    import ddvc.v3_inventory as inventory
    import ddvc.v3_inventory_calendar as calendar
    import ddvc.v3_pool_registry as registry
    import scripts.build_v3_inventory_panel as panel

    monkeypatch.setattr(contract, "v3_audit_days", lambda _path: [DAY])
    monkeypatch.setattr(contract, "load_block_timestamps", lambda _path: {100: 1_700_000_000})
    monkeypatch.setattr(contract, "correction_generation_records", lambda *_args: {})
    monkeypatch.setattr(
        registry,
        "reopen_registry_evidence",
        lambda: ([factory], factory_certificate),
    )
    monkeypatch.setattr(registry, "load_registry", lambda: [factory])
    monkeypatch.setattr(
        registry,
        "load_certified_frozen_upper",
        lambda: (frozen_upper, factory_certificate),
    )
    monkeypatch.setattr(panel, "load_full_consumer_statics", lambda: {POOL: static})
    monkeypatch.setattr(
        calendar,
        "load_day_calendar",
        lambda: ([DAY, "20250116"], [999, 2_000]),
    )
    monkeypatch.setattr(panel, "inventory_perimeter", lambda _days, _ends: (1, 2_000))
    monkeypatch.setattr(
        panel,
        "ranges_by_day",
        lambda _ranges, _days, _ends: {
            DAY: [(1, 999)],
            "20250116": [(1_000, 1_999), (2_000, 2_000)],
        },
    )
    monkeypatch.setattr(inventory, "inventory_ordered_manifest_path", lambda _root: manifest)
    opened: list[str] = []

    def decoded(path: Path, *_args, **_kwargs):
        opened.append(path.name)
        if "00001000" in path.name or "00002000" in path.name:
            pytest.fail("ordinary reopening decompressed an out-of-audit-day payload")
        return iter([raw_event])

    monkeypatch.setattr(
        inventory,
        "iter_decoded_inventory_logs",
        decoded,
    )
    monkeypatch.setattr(state_data, "read_tick_partition", lambda *_args: state)

    quarantine = _empty_quarantine()
    assert validate_v3_event_source_evidence_bundle(
        certificate, summary=summary, quarantine=quarantine
    ) == (1, 1)
    assert opened == ["blocks_00000001_00000999.parquet"]
    original_manifest = manifest.read_bytes()
    manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest digest"):
        validate_v3_event_source_evidence_bundle(
            certificate, summary=summary, quarantine=quarantine
        )
    manifest.write_bytes(original_manifest)
    drifted_raw = dict(raw_event, amount0_delta_raw=-1_000_001)
    monkeypatch.setattr(
        inventory,
        "iter_decoded_inventory_logs",
        lambda *_args, **_kwargs: iter([drifted_raw]),
    )
    with pytest.raises(ValueError, match="exceptions on"):
        validate_v3_event_source_evidence_bundle(
            certificate, summary=summary, quarantine=quarantine
        )
    monkeypatch.setattr(inventory, "iter_decoded_inventory_logs", decoded)
    drifted = state.copy()
    drifted.loc[0, "sqrt_price_x96"] = str(2**96 + 1)
    monkeypatch.setattr(state_data, "read_tick_partition", lambda *_args: drifted)
    with pytest.raises(ValueError, match="exceptions on"):
        validate_v3_event_source_evidence_bundle(
            certificate, summary=summary, quarantine=quarantine
        )
