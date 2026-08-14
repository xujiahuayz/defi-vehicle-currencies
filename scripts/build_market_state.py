#!/usr/bin/env python3
"""Build and audit canonical market-state inputs before empirical execution."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from concurrent.futures import as_completed
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.data_release import (
    V4_STATIC_QUARANTINE_PANEL,
    audit_cross_venue_order_conflicts,
    audit_v4_pool_static_conflicts,
)
from ddvc.fetch.sources import get_source
from ddvc.graph_event_order import SUPPORTED_VENUES, load_event_order_generation_metadata
from ddvc.paths import DATA_DIR, OUTPUT_DIR, RAW_MARKET_DATA_LOCK
from ddvc.provenance import stamp
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
    interruptible_thread_pool,
)
from ddvc.state_data import (
    CP_COLUMNS,
    CP_STATE_GENERATION,
    CODE_SOURCES,
    FAMILY_STREAMS,
    MULTI_ASSET_COLUMNS,
    MULTI_ASSET_STATE_GENERATIONS,
    QUALITY_COLUMNS,
    SCHEMA_VERSION,
    STATE_ENGINE,
    STATE_ROOT,
    StatePartitionQuality,
    balancer_pool_family,
    bind_state_partition_output,
    cp_partition_path,
    cp_quality_path,
    multi_asset_partition_path,
    multi_asset_quality_path,
    normalise_cp_partition,
    normalise_multi_asset_partition,
    normalise_tick_partition,
    partition_input_fingerprint,
    pool_semantics,
    raw_stream_path,
    read_cp_quality,
    read_multi_asset_quality,
    read_tick_quality,
    state_partition_output_is_current,
    tick_scientific_support,
    write_cp_partition,
    write_multi_asset_partition,
    write_tick_partition,
    tick_partition_path,
    tick_quality_path,
)
from ddvc.tables import write_exhibit, write_panel
from ddvc.tick_state_events import initialization_day_inputs, v4_state_day_inputs, validate_initialization_day, validate_v4_state_day


RAW = DATA_DIR / "raw" / "thegraph"
QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
QUALITY_EXHIBIT = OUTPUT_DIR / "exhibits" / "market_state_quality.jsonl"
LOCK = DATA_DIR / "processed" / ".market_state.lock"
LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST = (
    DATA_DIR
    / "raw"
    / "ethereum"
    / "token_decimals"
    / "v2_main_route_cost_selected_anchors.json"
)
LEGACY_V2_ROUTE_COST_UNRESOLVED = (
    DATA_DIR
    / "raw"
    / "ethereum"
    / "token_decimals"
    / "v2_main_route_cost_unresolved_tokens.json"
)
LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY = (
    DATA_DIR / "processed" / "v2_main_route_cost_token_decimals.parquet"
)
LEGACY_V2_ROUTE_COST_CODE_SOURCES = [
    "scripts/build_market_state.py",
    "scripts/run_route_cost_panel.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/token_decimals.py",
    "src/ddvc/v2_event_completeness.py",
]


def market_state_quality_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Build the engine-bound ledger rows consumed by the node-D release gate."""

    records: list[dict[str, object]] = []
    for row in rows:
        record = dict(row)
        record["scientific_support"] = tick_scientific_support(RAW, str(record["venue"]), str(record["day"])) if record.get("family") == "tick" else True
        records.append(record)
    quality = pd.DataFrame(records, columns=[*QUALITY_COLUMNS, "scientific_support"]).sort_values(
        ["family", "venue", "day"]
    )
    quality.insert(1, "engine", STATE_ENGINE)
    return quality


def _current_partition_fingerprint(family: str, venue: str, day: str) -> str:
    required = [] if family == "tick" and venue == "uniswap_v4" else [
        raw_stream_path(RAW, venue, stream, day)
        for stream, _kind, _sign in FAMILY_STREAMS[family][venue]
    ]
    if family == "tick":
        required.extend(initialization_day_inputs(RAW, venue, day))
        if venue == "uniswap_v4":
            required.extend(v4_state_day_inputs(RAW, day))
    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"required raw stream(s) missing for {family}/{venue}/{day}: "
            f"{', '.join(missing)}"
        )
    if family == "tick":
        validate_initialization_day(RAW, venue, day)
        if venue == "uniswap_v4":
            validate_v4_state_day(RAW, day)
    return partition_input_fingerprint(required)


def migrate_v1_partition(
    source_root: Path,
    family: str,
    venue: str,
    day: str,
    target_root: Path = STATE_ROOT,
) -> StatePartitionQuality:
    """Migrate an additive v1 state schema without reinterpreting economic payloads."""

    if family not in {"constant_product", "multi_asset"}:
        raise ValueError(f"no v1 migration for state family {family}")
    source_panel = source_root / family / venue / f"{day}.parquet"
    source_marker = source_panel.with_suffix(".quality.json")
    if not source_panel.exists() or not source_marker.exists():
        raise FileNotFoundError(f"v1 source partition missing for {family}/{venue}/{day}")
    payload = json.loads(source_marker.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"migration source is not schema v1: {family}/{venue}/{day}")
    current_fingerprint = _current_partition_fingerprint(family, venue, day)
    if payload.get("input_fingerprint") != current_fingerprint:
        raise ValueError(f"v1 source is stale against raw input: {family}/{venue}/{day}")
    frame = pd.read_parquet(source_panel)
    if not frame.empty and set(frame["schema_version"]) != {1}:
        raise ValueError(f"v1 source rows have mixed schema versions: {family}/{venue}/{day}")
    frame["schema_version"] = SCHEMA_VERSION
    if family == "constant_product":
        pool_family = "full_range_constant_product"
        invariant_family, quote_ready = pool_semantics(
            venue, pool_family, CP_STATE_GENERATION
        )
        if not quote_ready:
            raise ValueError(f"constant-product quote contract is not ready: {venue}")
        frame["pool_family"] = pool_family
        frame["invariant_family"] = invariant_family
        frame["state_generation"] = CP_STATE_GENERATION
        quote_record = frame["record_type"].isin(["snapshot", "swap"])
        frame["quote_unsupported_reason"] = None
        frame.loc[quote_record & ~frame["quote_supported"], "quote_unsupported_reason"] = (
            "row_state_not_quotable"
        )
        columns = CP_COLUMNS
        panel_path = cp_partition_path(venue, day, root=target_root)
        marker_path = cp_quality_path(venue, day, root=target_root)
    else:
        frame = frame.rename(columns={"pool_type": "provider_pool_type"})
        frame["pool_family"] = frame["provider_pool_type"].map(
            lambda value: (
                "ng_or_unclassified"
                if venue == "curve"
                else balancer_pool_family(value)
            )
        )
        generation = MULTI_ASSET_STATE_GENERATIONS[venue]
        frame["invariant_family"] = frame["pool_family"].map(
            lambda pool_family: pool_semantics(venue, str(pool_family), generation)[0]
        )
        frame["state_generation"] = generation
        capability = frame["pool_family"].map(
            lambda pool_family: pool_semantics(venue, str(pool_family), generation)[1]
        )
        old_quote = frame["quote_supported"].fillna(False).astype(bool)
        frame["quote_supported"] = old_quote & capability
        quote_record = frame["record_type"].isin(["snapshot_token", "swap"])
        frame["quote_unsupported_reason"] = None
        frame.loc[quote_record & ~capability, "quote_unsupported_reason"] = (
            "pool_family_or_state_generation_not_admitted"
        )
        frame.loc[quote_record & capability & ~old_quote, "quote_unsupported_reason"] = (
            "row_state_not_quotable"
        )
        columns = MULTI_ASSET_COLUMNS
        panel_path = multi_asset_partition_path(venue, day, root=target_root)
        marker_path = multi_asset_quality_path(venue, day, root=target_root)
    frame = frame.reindex(columns=columns)
    payload["schema_version"] = SCHEMA_VERSION
    payload["output_bytes"] = 0
    payload["output_sha256"] = ""
    payload["quote_supported_swaps"] = int(
        (frame["record_type"].eq("swap") & frame["quote_supported"]).sum()
    )
    with atomic_output(panel_path) as temporary:
        frame.to_parquet(temporary, index=False)
    quality = bind_state_partition_output(StatePartitionQuality(**payload), panel_path)
    with atomic_output(marker_path) as temporary:
        temporary.write_text(
            json.dumps(asdict(quality), allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return quality


def validate_migration_sample(
    family: str,
    venue: str,
    day: str,
    target_root: Path = STATE_ROOT,
) -> None:
    """Require migrated fields and quality to equal a fresh raw normalization exactly."""

    if family == "constant_product":
        expected, expected_quality = normalise_cp_partition(RAW, venue, day)
        migrated = pd.read_parquet(cp_partition_path(venue, day, root=target_root))
    else:
        expected, expected_quality = normalise_multi_asset_partition(RAW, venue, day)
        migrated = pd.read_parquet(multi_asset_partition_path(venue, day, root=target_root))
    pd.testing.assert_frame_equal(
        migrated.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        check_exact=True,
    )
    marker = json.loads(
        (
            cp_quality_path(venue, day, root=target_root)
            if family == "constant_product"
            else multi_asset_quality_path(venue, day, root=target_root)
        ).read_text(encoding="utf-8")
    )
    expected_quality = bind_state_partition_output(
        expected_quality,
        cp_partition_path(venue, day, root=target_root)
        if family == "constant_product"
        else multi_asset_partition_path(venue, day, root=target_root),
    )
    if marker != asdict(expected_quality):
        raise ValueError(f"migrated quality differs from raw normalization: {family}/{venue}/{day}")


def _state_paths(
    root: Path,
    family: str,
    venue: str,
    day: str,
) -> tuple[Path, Path]:
    if family == "tick":
        return tick_partition_path(venue, day, root=root), tick_quality_path(venue, day, root=root)
    if family == "constant_product":
        return cp_partition_path(venue, day, root=root), cp_quality_path(venue, day, root=root)
    return multi_asset_partition_path(venue, day, root=root), multi_asset_quality_path(venue, day, root=root)


def _atomic_hardlink(source: Path, target: Path) -> None:
    """Publish one immutable generated file without duplicating its data blocks."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def rekey_current_partition(
    source_root: Path,
    family: str,
    venue: str,
    day: str,
    target_root: Path = STATE_ROOT,
) -> StatePartitionQuality:
    """Hardlink one schema-current partition after proving its raw input is current."""

    source_panel, source_marker = _state_paths(source_root, family, venue, day)
    target_panel, target_marker = _state_paths(target_root, family, venue, day)
    if not source_panel.is_file() or not source_marker.is_file():
        raise FileNotFoundError(f"rekey source missing for {family}/{venue}/{day}")
    payload = json.loads(source_marker.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"rekey source is not schema v{SCHEMA_VERSION}: {family}/{venue}/{day}")
    if not payload.get("passed"):
        raise ValueError(f"rekey source did not pass its partition gate: {family}/{venue}/{day}")
    current_fingerprint = _current_partition_fingerprint(family, venue, day)
    if payload.get("input_fingerprint") != current_fingerprint:
        raise ValueError(f"rekey source is stale against raw input: {family}/{venue}/{day}")
    quality = StatePartitionQuality(**payload)
    if not state_partition_output_is_current(quality, source_panel):
        raise ValueError(
            f"rekey source content disagrees with its marker: {family}/{venue}/{day}"
        )
    _atomic_hardlink(source_panel, target_panel)
    _atomic_hardlink(source_marker, target_marker)
    return quality


def rekey_source_current(
    source_root: Path,
    family: str,
    venue: str,
    day: str,
) -> bool:
    """Return whether a same-schema source partition still matches its raw inputs."""

    panel, marker = _state_paths(source_root, family, venue, day)
    if not panel.is_file() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    try:
        current_fingerprint = _current_partition_fingerprint(family, venue, day)
    except FileNotFoundError:
        return False
    return bool(
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("passed")
        and payload.get("input_fingerprint") == current_fingerprint
        and state_partition_output_is_current(
            StatePartitionQuality(**payload), panel
        )
    )


def validate_rekey_sample(
    family: str,
    venue: str,
    day: str,
    target_root: Path = STATE_ROOT,
) -> None:
    """Require a rekeyed partition to equal a fresh normalization byte-for-value."""

    normalizers = {
        "tick": normalise_tick_partition,
        "constant_product": normalise_cp_partition,
        "multi_asset": normalise_multi_asset_partition,
    }
    expected, expected_quality = normalizers[family](RAW, venue, day)
    panel, marker = _state_paths(target_root, family, venue, day)
    actual = pd.read_parquet(panel)
    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        check_exact=True,
    )
    expected_quality = bind_state_partition_output(expected_quality, panel)
    if json.loads(marker.read_text(encoding="utf-8")) != asdict(expected_quality):
        raise ValueError(f"rekeyed quality differs from raw normalization: {family}/{venue}/{day}")


def selected_days(
    venue: str,
    start: str | None,
    end: str | None,
) -> list[str]:
    genesis = get_source(venue).genesis.strftime("%Y%m%d")
    lower = max(genesis, (start or RESEARCH_SAMPLE_START).replace("-", ""))
    upper = (end or RESEARCH_SAMPLE_END).replace("-", "")
    return calendar_days(lower, upper) if lower <= upper else []


def preflight_event_order_generations(
    venue_days: list[tuple[str, str]],
) -> None:
    """Report every stale correction schema before the expensive state build starts."""

    failures: list[str] = []
    for venue, day in venue_days:
        if venue not in SUPPORTED_VENUES:
            continue
        try:
            load_event_order_generation_metadata(RAW, venue, day)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"{venue}/{day}: {error}")
    if failures:
        sample = "; ".join(failures[:10])
        raise RuntimeError(
            f"market-state correction preflight found {len(failures):,} invalid generation(s); "
            f"first={sample}"
        )


def legacy_v2_correction_days(
    correction_root: Path,
) -> list[tuple[str, str]]:
    """Return complete flat V2 correction generations lacking a current pointer."""

    from ddvc.graph_event_order import correction_pointer_path
    from ddvc.v2_event_contract import V2_EVENT_VENUES

    legacy: list[tuple[str, str]] = []
    for venue in V2_EVENT_VENUES:
        venue_root = correction_root / venue
        for metadata_path in sorted(venue_root.glob("????????.meta.json")):
            day = metadata_path.name[:8]
            if not day.isdigit() or correction_pointer_path(
                correction_root, venue, day
            ).exists():
                continue
            members = (
                venue_root / f"{day}.jsonl.gz",
                metadata_path,
                venue_root / f"{day}.block_timestamps.jsonl.gz",
                venue_root / f"{day}.transaction_receipts.jsonl.gz",
            )
            missing = [path.name for path in members if not path.is_file()]
            if missing:
                raise RuntimeError(
                    f"partial legacy V2 correction generation for {venue}/{day}: {missing}"
                )
            legacy.append((venue, day))
    return legacy


def legacy_v2_missing_decimals(
    raw_root: Path,
    targets: list[tuple[str, str]],
    statics: dict[str, dict[str, object]],
    *,
    admitted_pools_by_target: dict[tuple[str, str], set[str]] | None = None,
) -> tuple[set[str], set[tuple[str, str]], int]:
    """Bound active legacy-day pools whose exact token decimals are not certified."""

    tokens: set[str] = set()
    pools: set[tuple[str, str]] = set()
    event_rows = 0
    for venue, day in targets:
        for stream in ("mints", "burns", "swaps"):
            path = raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"
            with gzip.open(path, "rt") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    pair = row.get("pair")
                    pool = (
                        str(pair.get("id") or "").lower()
                        if isinstance(pair, dict)
                        else ""
                    )
                    if (
                        admitted_pools_by_target is not None
                        and pool not in admitted_pools_by_target.get((venue, day), set())
                    ):
                        continue
                    static = statics[venue].get(pool)
                    if static is None:
                        continue
                    missing = {
                        str(token).lower()
                        for token, decimals in (
                            (getattr(static, "token0"), getattr(static, "decimals0")),
                            (getattr(static, "token1"), getattr(static, "decimals1")),
                        )
                        if decimals is None
                    }
                    if not missing:
                        continue
                    tokens.update(missing)
                    pools.add((venue, pool))
                    event_rows += 1
    return tokens, pools, event_rows


def legacy_v2_route_cost_endpoints(
    days: list[str],
) -> tuple[dict[str, set[str]], dict[str, dict[str, object]], list[Path]]:
    """Reuse the canonical main-spec selector without retaining full route days."""

    from scripts.run_route_cost_panel import (
        VEHICLE_ADDRESSES,
        _routes_by_pair,
    )

    columns = [
        "tx_hash",
        "component_id",
        "route_class",
        "token_in",
        "token_out",
        "token_in_sym",
        "token_out_sym",
        "amount_usd",
        "tin_role",
        "tout_role",
    ]
    endpoints_by_day: dict[str, set[str]] = {}
    statistics: dict[str, dict[str, object]] = {}
    inputs: list[Path] = []
    for day in sorted(set(days)):
        path = DATA_DIR / "unified" / f"{day}.parquet"
        pairs = _routes_by_pair(pd.read_parquet(path, columns=columns), top_pairs=200)
        if pairs.empty:
            raise RuntimeError(f"main_v1 route-pair selector is empty for {day}")
        endpoints = set(pairs["src"]) | set(pairs["tgt"]) | set(VEHICLE_ADDRESSES)
        endpoints_by_day[day] = endpoints
        statistics[day] = {
            "selected_pairs": int(len(pairs)),
            "endpoint_tokens_including_candidates": int(len(endpoints)),
            "realized_bridge_volume_usd": float(pairs["realized_bridge_volume_usd"].sum()),
        }
        inputs.append(path)
    return endpoints_by_day, statistics, inputs


def legacy_v2_route_cost_activity_perimeter(
    raw_root: Path,
    targets: list[tuple[str, str]],
    pairs_by_venue: dict[str, list[object]],
    endpoints_by_day: dict[str, set[str]],
    *,
    excluded_pools_by_venue: dict[str, set[str]] | None = None,
) -> tuple[
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
    dict[str, list[object]],
    dict[str, int],
    list[Path],
]:
    """Admit only active pools joining main-spec endpoints or locked candidates."""

    by_pool = {
        venue: {str(pair.pool): pair for pair in pairs}
        for venue, pairs in pairs_by_venue.items()
    }
    admitted: dict[tuple[str, str], set[str]] = {}
    anchor_support: dict[tuple[str, str], set[str]] = {}
    provider_observations: dict[str, list[object]] = {}
    active_pool_days: set[tuple[str, str, str]] = set()
    irrelevant_pool_days: set[tuple[str, str, str]] = set()
    admitted_event_rows = 0
    irrelevant_event_rows = 0
    bounded_exclusion_event_rows = 0
    inputs: list[Path] = []
    anchor_tokens = set().union(*endpoints_by_day.values())
    for venue, day in targets:
        allowed_tokens = endpoints_by_day[day]
        target = (venue, day)
        admitted[target] = set()
        anchor_support[target] = set()
        for stream in ("mints", "burns", "swaps"):
            path = raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"
            inputs.append(path)
            with gzip.open(path, "rt") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    raw_pair = row.get("pair")
                    pool = (
                        str(raw_pair.get("id") or "").lower()
                        if isinstance(raw_pair, dict)
                        else ""
                    )
                    if pool in (excluded_pools_by_venue or {}).get(venue, set()):
                        bounded_exclusion_event_rows += 1
                        continue
                    pair = by_pool[venue].get(pool)
                    if pair is None:
                        raise ValueError(
                            f"legacy V2 provider pool is outside the certified factory registry: {venue}/{day}/{pool}"
                        )
                    pool_day = (venue, day, pool)
                    endpoint_tokens = {
                        token
                        for token in (pair.token0, pair.token1)
                        if token in anchor_tokens
                    }
                    if endpoint_tokens:
                        anchor_support[target].add(pool)
                        for name, token in (
                            ("token0", pair.token0),
                            ("token1", pair.token1),
                        ):
                            if token not in endpoint_tokens:
                                continue
                            value = raw_pair[name].get("decimals")
                            observations = provider_observations.setdefault(token, [])
                            if value not in observations:
                                observations.append(value)
                    if pair.token0 not in allowed_tokens or pair.token1 not in allowed_tokens:
                        irrelevant_pool_days.add(pool_day)
                        irrelevant_event_rows += 1
                        continue
                    admitted[target].add(pool)
                    active_pool_days.add(pool_day)
                    admitted_event_rows += 1
        if not admitted[target]:
            raise RuntimeError(f"main_v1 V2 activity perimeter is empty for {venue}/{day}")
    counters = {
        "admitted_pool_days": len(active_pool_days),
        "admitted_unique_pools": len({item[2] for item in active_pool_days}),
        "admitted_event_rows": admitted_event_rows,
        "anchor_support_pool_days": sum(len(pools) for pools in anchor_support.values()),
        "irrelevant_pool_days": len(irrelevant_pool_days),
        "irrelevant_event_rows": irrelevant_event_rows,
        "bounded_exclusion_event_rows": bounded_exclusion_event_rows,
    }
    return admitted, anchor_support, provider_observations, counters, inputs


def legacy_v2_factory_token_anchors(
    tokens: set[str],
    anchor_pools_by_target: dict[tuple[str, str], set[str]],
    factory_inputs: list[Path],
) -> tuple[dict[str, object], list[Path]]:
    """Select deterministic PairCreated anchors from the certified factory leaves."""

    from ddvc.token_decimals import TokenDecimalsAnchor, retain_token_decimals_anchor
    from ddvc.v2_event_completeness import decode_pair_created_log

    admitted_by_venue: dict[str, set[str]] = {}
    for (venue, _day), pools in anchor_pools_by_target.items():
        admitted_by_venue.setdefault(venue, set()).update(pools)
    anchors: dict[str, TokenDecimalsAnchor] = {}
    used_inputs: set[Path] = set()
    leaf_paths = sorted(
        path
        for path in factory_inputs
        if path.suffix == ".parquet" and path.parent.name == "leaves"
    )
    for path in leaf_paths:
        venue = path.parent.parent.name
        if venue not in admitted_by_venue:
            continue
        used = False
        for record in pq.read_table(path).to_pylist():
            pair = decode_pair_created_log(venue, record)
            if pair.pool not in admitted_by_venue[venue]:
                continue
            for token in (pair.token0, pair.token1):
                if token not in tokens:
                    continue
                retain_token_decimals_anchor(
                    anchors,
                    TokenDecimalsAnchor(
                        token=token,
                        block_number=int(record["block_number"]),
                        block_hash=str(record["block_hash"]).lower(),
                        priority=2,
                        proof_kind="factory_pair_created",
                        venue=venue,
                        pool=pair.pool,
                        event_type="pair_created",
                        transaction_hash=str(record["transaction_hash"]).lower(),
                        transaction_index=int(record["transaction_index"]),
                        log_index=int(record["log_index"]),
                    ),
                )
                used = True
        if used:
            used_inputs.add(path)
            marker = path.with_suffix(".meta.json")
            if not marker.is_file():
                raise FileNotFoundError(marker)
            used_inputs.add(marker)
    if set(anchors) != tokens:
        missing = sorted(tokens - set(anchors))
        raise RuntimeError(
            f"purpose-bound V2 tokens lack certified factory anchors: count={len(missing):,}; first={missing[:3]}"
        )
    return dict(sorted(anchors.items())), sorted(used_inputs)


def audit_legacy_v2_correction_inputs(
    *,
    fetch_token_decimals: bool = False,
    refresh: bool = False,
    workers: int = 4,
) -> dict[str, int]:
    """Certify and optionally refresh the purpose-bound legacy V2 corrections."""

    from ddvc.ethereum_logs import file_sha256
    from ddvc.graph_event_order import correction_root_for_graph
    from ddvc.provenance import code_fingerprint, current_artifacts
    from ddvc.token_decimals import (
        build_token_decimals_anchor_manifest,
        build_token_decimals_registry,
        load_token_decimals_anchor_manifest,
        resolve_token_decimals_evidence,
        token_decimals_registry_sha256,
        validate_token_decimals_registry,
        write_token_decimals_anchor_manifest,
        write_token_decimals_registry,
    )
    from ddvc.v2_event_completeness import (
        PoolStatic,
        V2_EVENT_SOURCE_CURRENT,
        V2_TOKEN_DECIMALS_REGISTRY,
        canonical_v2_pool_templates,
        frozen_upper_block_path,
        load_v2_bounded_token_exclusion,
        missing_v2_exact_log_ranges,
        read_v2_event_source_certificate,
        reopen_v2_factory_pool_registry,
        validate_v2_event_source_certificate,
    )
    from ddvc.v2_event_contract import V2_EVENT_VENUES, V2_RECONCILIATION_SCOPE
    from scripts.audit_v2_event_completeness import load_or_resolve_day_bounds
    from scripts.reconcile_graph_event_order import reconcile_day

    correction_root = correction_root_for_graph(RAW)
    targets = legacy_v2_correction_days(correction_root)
    if not targets:
        return {
            "legacy_days": 0,
            "missing_exact_chunks": 0,
            "missing_tokens": 0,
            "missing_pools": 0,
            "missing_event_rows": 0,
        }

    summary, exceptions, certificate = read_v2_event_source_certificate(
        pointer_path=V2_EVENT_SOURCE_CURRENT
    )
    with current_artifacts(
        [UNIFIED_QUALITY_PANEL],
        consumer="legacy V2 correction-input audit",
    ):
        audit_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
    validate_v2_event_source_certificate(
        summary,
        exceptions,
        certificate,
        audit_days,
    )
    _pools_by_venue, pairs_by_venue, factory_inputs, _leaf_count = (
        reopen_v2_factory_pool_registry(certificate)
    )
    bounded_exclusion = load_v2_bounded_token_exclusion()
    if (
        certificate.get("excluded_tokens") != bounded_exclusion["tokens"]
        or certificate.get("excluded_factory_pairs") != bounded_exclusion["pairs"]
        or certificate.get("excluded_factory_pairs_sha256")
        != bounded_exclusion["pairs_sha256"]
    ):
        raise ValueError("V2 bounded exclusion disagrees with the current event certificate")
    excluded_pools = {
        venue: {
            str(row["pool"])
            for row in bounded_exclusion["pairs"]
            if row["venue"] == venue
        }
        for venue in V2_EVENT_VENUES
    }
    pairs_by_venue = {
        venue: [
            pair
            for pair in pairs_by_venue[venue]
            if pair.pool not in excluded_pools[venue]
        ]
        for venue in V2_EVENT_VENUES
    }
    token_decimals, token_registry = validate_token_decimals_registry(
        V2_TOKEN_DECIMALS_REGISTRY
    )
    if (
        len(token_registry) != certificate.get("token_decimals_registry_rows")
        or token_decimals_registry_sha256(token_registry)
        != certificate.get("token_decimals_registry_sha256")
        or file_sha256(V2_TOKEN_DECIMALS_REGISTRY)
        != certificate.get("token_decimals_registry_file_sha256")
    ):
        raise ValueError("V2 token-decimals registry disagrees with the current event certificate")

    maximum_block = int(certificate["factory_registry_upper_block"])
    frozen_upper = json.loads(
        frozen_upper_block_path(maximum_block).read_text(encoding="utf-8")
    )
    missing_exact_chunks = []
    for venue, day in targets:
        bounds = load_or_resolve_day_bounds(day, fetch=False)
        missing_exact_chunks.extend(
            (venue, day, start, end)
            for start, end in missing_v2_exact_log_ranges(
                [(int(bounds["start_block"]), int(bounds["end_block"]))],
                frozen_upper=frozen_upper,
            )
        )
    if missing_exact_chunks:
        raise RuntimeError(
            "legacy V2 correction-input audit lacks cached exact chunks: "
            f"count={len(missing_exact_chunks):,}; first={missing_exact_chunks[0]}"
        )

    endpoints_by_day, endpoint_statistics, route_inputs = legacy_v2_route_cost_endpoints(
        [day for _venue, day in targets]
    )
    (
        admitted_pools_by_target,
        anchor_pools_by_target,
        provider_observations,
        perimeter_counts,
        activity_inputs,
    ) = legacy_v2_route_cost_activity_perimeter(
        RAW,
        targets,
        pairs_by_venue,
        endpoints_by_day,
        excluded_pools_by_venue=excluded_pools,
    )
    base_statics = {
        venue: {
            pair.pool: PoolStatic(
                pair.pool,
                pair.token0,
                pair.token1,
                token_decimals.get(pair.token0),
                token_decimals.get(pair.token1),
            )
            for pair in pairs
        }
        for venue, pairs in pairs_by_venue.items()
    }
    missing_tokens, missing_pools, missing_event_rows = legacy_v2_missing_decimals(
        RAW,
        targets,
        base_statics,
        admitted_pools_by_target=admitted_pools_by_target,
    )
    missing_endpoint_tokens = set(provider_observations) - set(token_decimals)
    anchors, anchor_inputs = legacy_v2_factory_token_anchors(
        missing_endpoint_tokens,
        anchor_pools_by_target,
        factory_inputs,
    )
    event_release_pointer = json.loads(
        V2_EVENT_SOURCE_CURRENT.read_text(encoding="utf-8")
    )
    context = {
        "scope": "main_v1",
        "top_pairs": 200,
        "trade_sizes_usd": [1000, 10000, 100000],
        "hours_utc": list(range(24)),
        "unify_wrapped": True,
        "selection_code_sha256": code_fingerprint(
            LEGACY_V2_ROUTE_COST_CODE_SOURCES
        ),
        "base_event_release_generation": str(event_release_pointer["generation_id"]),
        "base_token_registry_sha256": hashlib.sha256(
            V2_TOKEN_DECIMALS_REGISTRY.read_bytes()
        ).hexdigest(),
        "targets": [
            {
                "venue": venue,
                "day": day,
                "endpoints_including_candidates": sorted(endpoints_by_day[day]),
                "admitted_active_pools": sorted(admitted_pools_by_target[(venue, day)]),
                "endpoint_anchor_support_pool_count": len(
                    anchor_pools_by_target[(venue, day)]
                ),
                "endpoint_anchor_support_pools_sha256": hashlib.sha256(
                    json.dumps(
                        sorted(anchor_pools_by_target[(venue, day)]),
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            for venue, day in targets
        ],
    }
    selection_inputs = sorted(
        {
            UNIFIED_QUALITY_PANEL,
            V2_EVENT_SOURCE_CURRENT,
            V2_TOKEN_DECIMALS_REGISTRY,
            *route_inputs,
            *activity_inputs,
            *anchor_inputs,
        },
        key=str,
    )
    manifest_statistics = {
        "legacy_days": len(targets),
        "distinct_route_days": len(endpoints_by_day),
        "selected_pair_days": sum(
            int(record["selected_pairs"]) for record in endpoint_statistics.values()
        ),
        "admitted_pool_days": perimeter_counts["admitted_pool_days"],
        "admitted_unique_pools": perimeter_counts["admitted_unique_pools"],
        "missing_base_registry_tokens": len(missing_endpoint_tokens),
        "missing_base_registry_pools": len(missing_pools),
    }
    if LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST.is_file():
        (
            persisted_anchors,
            persisted_observations,
            _persisted_inputs,
            persisted_statistics,
        ) = load_token_decimals_anchor_manifest(
            LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST,
            expected_context=context,
        )
        if (
            persisted_anchors != anchors
            or persisted_observations
            != {
                token: provider_observations.get(token, [])
                for token in sorted(anchors)
            }
            or persisted_statistics != manifest_statistics
        ):
            raise ValueError("purpose-bound V2 anchor manifest selection changed")
    else:
        manifest = build_token_decimals_anchor_manifest(
            anchors,
            {
                token: provider_observations.get(token, [])
                for token in sorted(anchors)
            },
            context=context,
            lineage_inputs=selection_inputs,
            statistics=manifest_statistics,
        )
        write_token_decimals_anchor_manifest(
            manifest,
            LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST,
        )

    extension_observations = {
        token: provider_observations.get(token, []) for token in sorted(anchors)
    }
    if LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY.is_file():
        extension_decimals, extension_registry = validate_token_decimals_registry(
            LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY,
            expected_anchors=anchors,
            provider_observations=extension_observations,
        )
    else:
        if not fetch_token_decimals:
            raise RuntimeError(
                "legacy V2 correction-input audit requires cached exact evidence for the "
                f"purpose-bound extension: tokens={len(anchors):,}; pools={len(missing_pools):,}"
            )
        evidence, evidence_paths = resolve_token_decimals_evidence(
            anchors,
            fetch=True,
            workers=workers,
            unresolved_ledger_path=LEGACY_V2_ROUTE_COST_UNRESOLVED,
            anchor_manifest_path=LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST,
        )
        extension_registry = build_token_decimals_registry(
            anchors,
            evidence,
            evidence_paths,
            extension_observations,
        )
        write_token_decimals_registry(
            extension_registry,
            LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY,
        )
        stamp(
            LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY,
            code_sources=LEGACY_V2_ROUTE_COST_CODE_SOURCES,
            inputs=[
                LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST,
                *selection_inputs,
                *evidence_paths.values(),
            ],
            rows=len(extension_registry),
            notes=(
                "exact historical ERC-20 decimals for active V2 pools joining "
                "main_v1 endpoints and locked vehicle candidates on legacy correction days"
            ),
        )
        extension_decimals, extension_registry = validate_token_decimals_registry(
            LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY,
            expected_anchors=anchors,
            provider_observations=extension_observations,
        )

    overlap = set(token_decimals).intersection(extension_decimals)
    if overlap:
        raise ValueError(
            f"purpose-bound V2 decimals extension overlaps the certified base registry: {sorted(overlap)[:3]}"
        )
    merged_decimals = {**token_decimals, **extension_decimals}
    statics = {
        venue: {
            pair.pool: PoolStatic(
                pair.pool,
                pair.token0,
                pair.token1,
                merged_decimals.get(pair.token0),
                merged_decimals.get(pair.token1),
            )
            for pair in pairs
        }
        for venue, pairs in pairs_by_venue.items()
    }
    unresolved_tokens, unresolved_pools, unresolved_event_rows = legacy_v2_missing_decimals(
        RAW,
        targets,
        statics,
        admitted_pools_by_target=admitted_pools_by_target,
    )
    if unresolved_tokens:
        raise RuntimeError(
            "purpose-bound V2 token-decimals extension is incomplete: "
            f"tokens={len(unresolved_tokens):,}; pools={len(unresolved_pools):,}; "
            f"event_rows={unresolved_event_rows:,}"
        )

    refreshed = 0
    if refresh:
        for venue, day in targets:
            expected_pools = admitted_pools_by_target[(venue, day)]
            templates = canonical_v2_pool_templates(
                {pool: statics[venue][pool] for pool in expected_pools}
            )
            bounds = load_or_resolve_day_bounds(day, fetch=False)
            reconcile_day(
                venue,
                day,
                frozen_upper=frozen_upper,
                workers=workers,
                chunk_size=50,
                force=False,
                start_block=int(bounds["start_block"]),
                end_block=int(bounds["end_block"]),
                expected_pools=expected_pools,
                audited_token_decimals=merged_decimals,
                pool_templates=templates,
                raw_root=RAW,
                reconciliation_scope=V2_RECONCILIATION_SCOPE,
                authority_inputs=[
                    V2_EVENT_SOURCE_CURRENT,
                    V2_TOKEN_DECIMALS_REGISTRY,
                    LEGACY_V2_ROUTE_COST_ANCHOR_MANIFEST,
                    LEGACY_V2_ROUTE_COST_TOKEN_REGISTRY,
                ],
            )
            refreshed += 1

    result = {
        "legacy_days": len(targets),
        "missing_exact_chunks": 0,
        "selected_pair_days": manifest_statistics["selected_pair_days"],
        "admitted_pool_days": perimeter_counts["admitted_pool_days"],
        "admitted_unique_pools": perimeter_counts["admitted_unique_pools"],
        "anchor_support_pool_days": perimeter_counts["anchor_support_pool_days"],
        "irrelevant_pool_days": perimeter_counts["irrelevant_pool_days"],
        "irrelevant_event_rows": perimeter_counts["irrelevant_event_rows"],
        "bounded_exclusion_event_rows": perimeter_counts[
            "bounded_exclusion_event_rows"
        ],
        "extension_tokens": len(extension_registry),
        "extension_pools": len(missing_pools),
        "extension_event_rows": missing_event_rows,
        "missing_tokens": 0,
        "missing_pools": 0,
        "missing_event_rows": 0,
        "refreshed_generations": refreshed,
    }
    return result


def build_family(
    family: str,
    venues: list[str],
    *,
    start: str | None,
    end: str | None,
    workers: int,
    force: bool,
    migrate_from: Path | None,
    rekey_from: Path | None = None,
    explicit_days: list[str] | None = None,
) -> list[dict[str, object]]:
    readers = {
        "tick": read_tick_quality,
        "constant_product": read_cp_quality,
        "multi_asset": read_multi_asset_quality,
    }
    writers = {
        "tick": write_tick_partition,
        "constant_product": write_cp_partition,
        "multi_asset": write_multi_asset_partition,
    }
    jobs: list[tuple[str, str]] = []
    qualities: list[dict[str, object]] = []
    selected: list[tuple[str, str]] = []
    for venue in venues:
        genesis = get_source(venue).genesis.strftime("%Y%m%d")
        days = (
            [day for day in explicit_days if genesis <= day <= RESEARCH_SAMPLE_END]
            if explicit_days is not None
            else selected_days(venue, start, end)
        )
        for day in days:
            selected.append((venue, day))
            cached = None if force else readers[family](RAW, venue, day)
            if cached is None:
                jobs.append((venue, day))
            else:
                qualities.append(asdict(cached))
    migration_perimeter: list[tuple[str, str]] = []
    if rekey_from is not None:
        rekey_perimeter = [
            (venue, day)
            for venue, day in selected
            if rekey_source_current(rekey_from, family, venue, day)
        ]
        rekey_keys = set(rekey_perimeter)
        rekey_jobs = [job for job in jobs if job in rekey_keys]
        if rekey_jobs:
            print(
                f"rekeying {len(rekey_jobs):,} schema-current {family} partitions "
                f"with {workers} workers",
                flush=True,
            )
            with interruptible_thread_pool(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        rekey_current_partition,
                        rekey_from,
                        family,
                        venue,
                        day,
                    ): (venue, day)
                    for venue, day in rekey_jobs
                }
                for index, future in enumerate(as_completed(futures), 1):
                    qualities.append(asdict(future.result()))
                    if index % 250 == 0 or index == len(futures):
                        print(f"  {family} rekey [{index:,}/{len(futures):,}]", flush=True)
            jobs = [job for job in jobs if job not in set(rekey_jobs)]
        for venue in sorted({venue for venue, _day in rekey_perimeter}):
            venue_days = sorted(day for item_venue, day in rekey_perimeter if item_venue == venue)
            sample = sorted({venue_days[0], venue_days[len(venue_days) // 2], venue_days[-1]})
            for day in sample:
                validate_rekey_sample(family, venue, day)
            print(
                f"  {family}/{venue} rekey validation: {len(sample)} raw-normalized days exact",
                flush=True,
            )
    if migrate_from is not None and family in {"constant_product", "multi_asset"}:
        migration_perimeter = [
            (venue, day)
            for venue, day in selected
            if (migrate_from / family / venue / f"{day}.parquet").exists()
            and (migrate_from / family / venue / f"{day}.quality.json").exists()
        ]
        migration_keys = set(migration_perimeter)
        migration_jobs = [
            (venue, day)
            for venue, day in jobs
            if (venue, day) in migration_keys
        ]
        if migration_jobs:
            print(
                f"migrating {len(migration_jobs):,} canonical {family} v1 partitions "
                f"with {workers} workers",
                flush=True,
            )
            with interruptible_process_pool(workers) as pool:
                futures = {
                    pool.submit(
                        migrate_v1_partition,
                        migrate_from,
                        family,
                        venue,
                        day,
                    ): (venue, day)
                    for venue, day in migration_jobs
                }
                for index, future in enumerate(as_completed(futures), 1):
                    venue, day = futures[future]
                    qualities.append(asdict(future.result()))
                    if index % 250 == 0 or index == len(futures):
                        print(
                            f"  {family} migration [{index:,}/{len(futures):,}]",
                            flush=True,
                        )
            migration_set = set(migration_jobs)
            jobs = [job for job in jobs if job not in migration_set]
        for venue in sorted({venue for venue, _day in migration_perimeter}):
            venue_days = sorted(
                day
                for migration_venue, day in migration_perimeter
                if migration_venue == venue
            )
            sample = sorted(
                {
                    venue_days[0],
                    venue_days[len(venue_days) // 2],
                    venue_days[-1],
                }
            )
            for day in sample:
                validate_migration_sample(family, venue, day)
            print(
                f"  {family}/{venue} migration validation: {len(sample)} raw-normalized days exact",
                flush=True,
            )
    if jobs:
        print(f"building {len(jobs):,} canonical {family} partitions with {workers} workers", flush=True)
        with interruptible_process_pool(workers) as pool:
            futures = {
                pool.submit(writers[family], RAW, venue, day): (venue, day)
                for venue, day in jobs
            }
            for index, future in enumerate(as_completed(futures), 1):
                qualities.append(asdict(future.result()))
                if index % 100 == 0 or index == len(futures):
                    print(f"  {family} [{index:,}/{len(futures):,}]", flush=True)
    return qualities


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("all", *FAMILY_STREAMS), default="all")
    parser.add_argument("--venue", action="append")
    parser.add_argument("--start", default=RESEARCH_SAMPLE_START)
    parser.add_argument("--end", default=RESEARCH_SAMPLE_END)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--audit-calendar",
        action="store_true",
        help="materialize only the shared transaction-frontier construction-audit dates",
    )
    parser.add_argument(
        "--migrate-from",
        type=Path,
        help="schema-v1 state root for exact additive CP/multi-asset migration",
    )
    parser.add_argument(
        "--rekey-from",
        type=Path,
        help="schema-current state root whose exact partitions may be hardlinked under the new engine key",
    )
    parser.add_argument(
        "--audit-legacy-v2-corrections",
        action="store_true",
        help="reopen the cached full-day inputs needed to replace flat V2 correction days, then stop",
    )
    parser.add_argument(
        "--fetch-token-decimals",
        action="store_true",
        help="resolve missing exact token anchors while preparing legacy V2 corrections",
    )
    parser.add_argument(
        "--refresh-legacy-v2-corrections",
        action="store_true",
        help="publish purpose-bound current correction generations after their inputs pass",
    )
    args = parser.parse_args()
    if args.migrate_from and args.rekey_from:
        parser.error("--migrate-from and --rekey-from are mutually exclusive")
    if args.family == "all" and args.venue:
        parser.error("--venue requires one explicit --family")
    if (
        args.fetch_token_decimals or args.refresh_legacy_v2_corrections
    ) and not args.audit_legacy_v2_corrections:
        parser.error(
            "--fetch-token-decimals and --refresh-legacy-v2-corrections require "
            "--audit-legacy-v2-corrections"
        )
    if args.audit_legacy_v2_corrections:
        if (
            args.audit_calendar
            or args.force
            or args.migrate_from
            or args.rekey_from
            or args.family != "all"
            or args.venue
            or args.start.replace("-", "") != RESEARCH_SAMPLE_START
            or args.end.replace("-", "") != RESEARCH_SAMPLE_END
        ):
            parser.error(
                "--audit-legacy-v2-corrections is a standalone full-calendar prerequisite action"
            )
        with exclusive_job(
            RAW_MARKET_DATA_LOCK,
            job="raw market-data fetch, enrichment, or canonical materialisation",
        ):
            with exclusive_job(LOCK, job="canonical market-state build"):
                result = audit_legacy_v2_correction_inputs(
                    fetch_token_decimals=args.fetch_token_decimals,
                    refresh=args.refresh_legacy_v2_corrections,
                    workers=bounded_workers(args.workers, maximum=4),
                )
        print(f"COMPLETE: legacy V2 correction inputs={result}")
        return 0
    families = list(FAMILY_STREAMS) if args.family == "all" else [args.family]
    if args.family != "all":
        allowed_venues = FAMILY_STREAMS[args.family]
        unknown = sorted(set(args.venue or ()) - set(allowed_venues))
        if unknown:
            parser.error(f"unsupported venue(s) for {args.family}: {', '.join(unknown)}")
    full_run = (
        not args.audit_calendar
        and args.family == "all"
        and args.start.replace("-", "") == RESEARCH_SAMPLE_START
        and args.end.replace("-", "") == RESEARCH_SAMPLE_END
    )
    explicit_days = (
        transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
        if args.audit_calendar
        else None
    )
    venue_days = sorted(
        {
            (venue, day)
            for family in families
            for venue in (args.venue or list(FAMILY_STREAMS[family]))
            for day in (
                [
                    day
                    for day in explicit_days
                    if get_source(venue).genesis.strftime("%Y%m%d")
                    <= day
                    <= RESEARCH_SAMPLE_END
                ]
                if explicit_days is not None
                else selected_days(venue, args.start, args.end)
            )
        }
    )
    preflight_event_order_generations(venue_days)
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with exclusive_job(LOCK, job="canonical market-state build"):
            rows: list[dict[str, object]] = []
            for family in families:
                venues = args.venue or list(FAMILY_STREAMS[family])
                rows.extend(
                    build_family(
                        family,
                        venues,
                        start=args.start,
                        end=args.end,
                        workers=bounded_workers(args.workers, maximum=10),
                        force=args.force,
                        migrate_from=args.migrate_from,
                        rekey_from=args.rekey_from,
                        explicit_days=explicit_days,
                    )
                )
            quality = market_state_quality_frame(rows)
            failed = quality[~quality["passed"]]
            if not full_run:
                print(
                    f"PARTIAL: built/audited {len(quality):,} partition(s); "
                    "the global six-venue quality ledger was not published",
                    flush=True,
                )
                if not failed.empty:
                    print(f"FAILED: {len(failed):,} selected partition(s) violate the data contract")
                    return 1
                return 0
            tick_paths = {
                venue: [
                    tick_partition_path(venue, str(day), root=STATE_ROOT)
                    for day in quality.loc[
                        (quality["family"] == "tick") & (quality["venue"] == venue),
                        "day",
                    ]
                ]
                for venue in FAMILY_STREAMS["tick"]
            }
            cross_venue_conflicts, conflict_samples = audit_cross_venue_order_conflicts(
                tick_paths
            )
            v4_static_quarantine = audit_v4_pool_static_conflicts(
                tick_paths["uniswap_v4"]
            )
            write_panel(
                v4_static_quarantine,
                V4_STATIC_QUARANTINE_PANEL,
                code_sources=[
                    *CODE_SOURCES,
                    "src/ddvc/data_release.py",
                    "scripts/build_market_state.py",
                ],
                inputs=[STATE_ROOT / "tick" / "uniswap_v4"],
                notes="complete V4 pool exclusion set for provider-supplied immutable-static drift",
            )
            quality["cross_venue_order_conflicts"] = cross_venue_conflicts
            quality["v4_static_conflict_pools"] = len(v4_static_quarantine)
            all_venues = [venue for venues in FAMILY_STREAMS.values() for venue in venues]
            write_panel(
                quality,
                QUALITY_PANEL,
                code_sources=[
                    *CODE_SOURCES,
                    "src/ddvc/data_release.py",
                    "scripts/build_market_state.py",
                ],
                inputs=[*[RAW / venue for venue in all_venues], STATE_ROOT],
                notes=f"canonical market-state engine {STATE_ROOT.name}",
            )
            summary = (
                quality.groupby(["family", "venue"], as_index=False)
                .agg(
                    partitions=("day", "size"),
                    raw_rows=("raw_rows", "sum"),
                    canonical_rows=("canonical_rows", "sum"),
                    snapshot_rows=("snapshot_rows", "sum"),
                    swap_rows=("swap_rows", "sum"),
                    liquidity_rows=("liquidity_rows", "sum"),
                    usable_rows=("usable_rows", "sum"),
                    missing_order=("missing_order", "sum"),
                    missing_identity=("missing_identity", "sum"),
                    missing_required_streams=("missing_required_streams", "sum"),
                    invalid_swap_sign=("invalid_swap_sign", "sum"),
                    invalid_state=("invalid_state", "sum"),
                    unsupported_state=("unsupported_state", "sum"),
                    zero_swap_amounts=("zero_swap_amounts", "sum"),
                    missing_quote_statics=("missing_quote_statics", "sum"),
                    quote_supported_swaps=("quote_supported_swaps", "sum"),
                    conflicting_events=("conflicting_events", "sum"),
                    failed_partitions=("passed", lambda values: int((~values).sum())),
                )
            )
            summary["quarantined_rows"] = summary["canonical_rows"] - summary["usable_rows"]
            summary["quote_support_pct"] = (
                100 * summary["quote_supported_swaps"] / summary["swap_rows"].where(summary["swap_rows"] > 0)
            ).round(3)
            summary["static_conflict_rows"] = 0
            v4_summary = (summary["family"] == "tick") & (
                summary["venue"] == "uniswap_v4"
            )
            summary.loc[v4_summary, "static_conflict_rows"] = int(
                v4_static_quarantine["swap_rows"].sum()
            )
            summary["released_quote_supported_swaps"] = (
                summary["quote_supported_swaps"]
                - summary["static_conflict_rows"]
            )
            summary["released_quote_support_pct"] = (
                100
                * summary["released_quote_supported_swaps"]
                / summary["swap_rows"].where(summary["swap_rows"] > 0)
            ).round(3)
            write_exhibit(
                summary,
                QUALITY_EXHIBIT,
                code_sources=[*CODE_SOURCES, "scripts/build_market_state.py"],
                inputs=[QUALITY_PANEL],
                notes="full-calendar canonical market-state quality gate",
            )
            print(summary.to_string(index=False), flush=True)
            print(
                f"cross-venue block-log conflicts: {cross_venue_conflicts:,}",
                flush=True,
            )
            print(
                f"V4 pools quarantined for immutable-static drift: "
                f"{len(v4_static_quarantine):,}",
                flush=True,
            )
            for row in v4_static_quarantine.head(3).to_dict("records"):
                print(f"  V4 quarantine sample: {row}", flush=True)
            for sample in conflict_samples:
                print(f"  conflict sample: {sample}", flush=True)
            if not failed.empty:
                print(f"FAILED: {len(failed):,} canonical partition(s) violate the data contract")
                return 1
            if cross_venue_conflicts:
                print("FAILED: canonical tick state has cross-venue causal-order conflicts")
                return 1
            print(f"PASS: {len(quality):,} canonical partitions under {STATE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
