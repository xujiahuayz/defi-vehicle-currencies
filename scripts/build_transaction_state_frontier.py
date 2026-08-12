#!/usr/bin/env python3
"""Build and validate the strict pre-transaction V2/V3/V4 route frontier.

The frontier scores routes whose two realised legs execute on the exact-state V2,
V3, or V4 adapters and searches all supported paths at the same pre-transaction
state. Every admitted route and replay event requires block-log order. Curve,
Balancer, and Fluid remain outside the exact-state perimeter.

The current audit calendar validates construction and measures chosen-route reproduction. It is never an estimation sample. Only after its integrity and calendar contracts pass does ``--daily-calendar`` publish the separate full-daily analysis input used for exact 1-, 7-, 30-, and 120-calendar-day outcome links. The aggregate reproduction share is a diagnostic; individual routes still enter only inside the registered error tolerance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import shutil
from collections import defaultdict
from concurrent.futures import as_completed
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.analysis.transaction_frontier import (
    CHOSEN_REPRODUCTION_DASHBOARD_REFERENCE,
    MAX_CHOSEN_REPRODUCTION_ERROR,
    MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
    QUOTE_OUTCOME_REASONS,
    RealisedPath,
    chosen_quote_coverage_share,
    chosen_reproduction_share,
    positive_finite_amount,
    relative_output_error,
    score_frontier_from_quote,
)
from ddvc.asset_types import (
    IMPORTED,
    NATIVE,
    STABLE,
    STAKED_NATIVE,
    asset_type,
    canonical_token,
)
from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.pricing.mixed_frontier import (
    MixedFrontierState,
    mixed_leg_quotes,
    quote_mixed_pool,
)
from ddvc.pricing.path_frontier import PathQuote
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    load_tick_day_events,
    warm_tick_day,
)
from ddvc.pricing.v3pools import load_token_decimals
from ddvc.pricing.v2_replay import V2ReplayDay, V2_VENUES, load_v2_replay_day
from ddvc.provenance import cache_key, require_current_artifacts, stamp
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import (
    released_route_days,
    select_transaction_frontier_audit_days,
    transaction_frontier_audit_days,
)
from ddvc.route_cost import MAX_PRICE_IMPACT
from ddvc.route_state import OrderedTickStateCursor, TickStateCut
from ddvc.runtime import atomic_output, exclusive_job, interruptible_process_pool
from ddvc.state_data import RAW_ROOT, state_partition_inputs, tick_partition_path
from ddvc.tables import write_exhibit, write_panel
from ddvc.transaction_targets import TargetRelease, read_target_day, resolve_target_release, strict_route_order
from ddvc.v4_quarantine import (
    V4_STATIC_QUARANTINE_PANEL,
    load_v4_static_quarantine,
)
from ddvc.work_partition import weighted_contiguous_chunks


UNIFIED = DATA_DIR / "unified"
AUDIT_PANEL = DATA_DIR / "processed" / "transaction_state_frontier_audit.parquet"
AUDIT_REJECTIONS = DATA_DIR / "processed" / "transaction_state_frontier_audit_rejections.parquet"
AUDIT_SUMMARY = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_audit_summary.jsonl"
AUDIT_SUPPORT = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_audit_support.jsonl"
DAILY_PANEL = DATA_DIR / "processed" / "transaction_state_frontier_daily.parquet"
DAILY_REJECTIONS = DATA_DIR / "processed" / "transaction_state_frontier_daily_rejections.parquet"
DAILY_SUPPORT = DATA_DIR / "processed" / "transaction_state_frontier_daily_support.parquet"
LOCK = DATA_DIR / "processed" / ".transaction_state_frontier.lock"
TICK_VENUES = ("uniswap_v3", "uniswap_v4")
EXACT_VENUES = (*V2_VENUES, *TICK_VENUES)
REPLAY_START = "20210504"
TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"
MIN_INPUT_USD = 100.0
INTERMEDIATE_FLOW_TOLERANCE_BPS = 0.01
CHECKPOINT_INTERVAL_DAYS = 180
CHECKPOINT_GLOB = "pre_" + "[0-9]" * 8 + ".pkl"
REPLAY_CHECKPOINT_SCHEMA_VERSION = 5
REPLAY_CHECKPOINT_BOUNDARY = "strictly_before_first_event_of_day"
DAY_CACHE_SCHEMA_VERSION = 2
ORDERED_SHARD_MANIFEST_SCHEMA_VERSION = 1
MAX_DAILY_WORKERS = 4
DEFAULT_DAILY_WORKERS = 2
DAILY_PARENT_MEMORY_RESERVE_BYTES = 12 * 1024**3
DAILY_WORKER_MEMORY_BUDGET_BYTES = 12 * 1024**3
REPLAY_CAUSAL_FIELDS = (
    "unify_wrapped",
    "ticks_by_venue",
    "states_by_venue",
    "swap_samples",
    "token_decimals",
    "quarantined_pools",
    "initialization_status_by_venue",
    "scientifically_unsupported_venues",
)
FRONTIER_DEPENDENCY_REGISTRY = {
    "scoring": (
        "scripts/build_transaction_state_frontier.py",
        "src/ddvc/analysis/transaction_frontier.py",
        "src/ddvc/asset_types.py",
        "src/ddvc/calendar.py",
        "src/ddvc/cpquote.py",
        "src/ddvc/pricing/path_frontier.py",
        "src/ddvc/pricing/mixed_frontier.py",
        "src/ddvc/pricing/tick_frontier.py",
        "src/ddvc/pricing/tick_quote.py",
        "src/ddvc/pricing/tick_replay.py",
        "src/ddvc/pricing/tick_state.py",
        "src/ddvc/pricing/v3pools.py",
        "src/ddvc/pricing/v3quote.py",
        "src/ddvc/pricing/v2_frontier.py",
        "src/ddvc/pricing/v2_replay.py",
        "src/ddvc/prices.py",
        "src/ddvc/realised.py",
        "src/ddvc/reconstruct/__init__.py",
        "src/ddvc/release_calendar.py",
        "src/ddvc/route_cost.py",
        "src/ddvc/route_state.py",
        "src/ddvc/route_roles.py",
        "src/ddvc/source_records.py",
        "src/ddvc/state_data.py",
        "src/ddvc/transaction_targets.py",
        "src/ddvc/v4_quarantine.py",
        "src/ddvc/work_partition.py",
    ),
    "publication": (
        "src/ddvc/panel_assembly.py",
        "src/ddvc/provenance.py",
        "src/ddvc/runtime.py",
        "src/ddvc/tables.py",
    ),
}


def frontier_dependency_sources(*groups: str) -> list[str]:
    sources = [
        source
        for group in groups
        for source in FRONTIER_DEPENDENCY_REGISTRY[group]
    ]
    if len(sources) != len(set(sources)):
        raise RuntimeError("frontier dependency groups overlap")
    return sources


SCORING_CACHE_SOURCES = frontier_dependency_sources("scoring")
OUTPUT_PROVENANCE_SOURCES = frontier_dependency_sources("scoring", "publication")


@dataclass(frozen=True)
class DailySegment:
    """One exclusive contiguous slice of the full-daily calendar."""

    index: int
    days: tuple[str, ...]
    checkpoint_path: Path
    scoring_weight: int


@dataclass(frozen=True)
class DailySegmentTask:
    """Complete immutable input contract for one scoring process."""

    segment: DailySegment
    checkpoint_engine_key: str
    read_day_cache: Path
    write_day_cache: Path
    frontier_engine_key: str
    frontier_input_key: str
    vehicles: tuple[str, ...]
    target_release: TargetRelease
    market_state: Path | None
    cp_market_state: Path | None = None


@dataclass(frozen=True)
class DailySegmentResult:
    """Ordered support closure returned by one segment process."""

    index: int
    days: tuple[str, ...]
    support_rows: tuple[dict[str, object], ...]
    scored_days: int
    cached_days: int


@dataclass(frozen=True)
class ReplayShardTask:
    """One contiguous calendar slice loaded by an independent process."""

    index: int
    days: tuple[str, ...]
    market_state: Path | None
    raw_root: Path
    output_path: Path


@dataclass(frozen=True)
class ReplayShardResult:
    """One closed ordered event stream owned by a single map task."""

    index: int
    days: tuple[str, ...]
    output_path: Path
    event_count: int


def candidate_vehicles() -> tuple[str, ...]:
    addresses = set().union(NATIVE, STAKED_NATIVE, STABLE, IMPORTED)
    return tuple(
        sorted(
            {
                canonical
                for address in addresses
                if (canonical := canonical_token(address)) is not None
            }
        )
    )


def frontier_cache_identity(
    inputs: list[Path], *, source_identity: str | None = None
) -> tuple[str, str, str]:
    """Return separate code/input identities plus their short cache generation."""
    engine_key = cache_key(SCORING_CACHE_SOURCES, length=64)
    base_input_key = cache_key([], inputs=inputs, length=64)
    input_key = hashlib.sha256(
        f"{base_input_key}:{source_identity or 'no-release-context'}".encode()
    ).hexdigest()
    generation = hashlib.sha256(f"{engine_key}:{input_key}".encode()).hexdigest()[:12]
    return engine_key, input_key, generation


def replay_checkpoint_engine_key(
    inputs: list[Path], *, source_identity: str | None = None
) -> str:
    """Identify the checkpoint schema, replay code, and immutable replay inputs."""
    base = cache_key(
        SCORING_CACHE_SOURCES,
        inputs=inputs,
        length=64,
    )
    return hashlib.sha256(
        f"{base}:{source_identity or 'no-release-context'}".encode()
    ).hexdigest()


def save_replay_checkpoint(
    path: Path,
    replay: TickReplayState,
    *,
    engine_key: str,
    pre_day: str,
) -> None:
    if checkpoint_day(path) != pre_day:
        raise ValueError("replay checkpoint pre-day disagrees with filename")
    if path.exists():
        raise FileExistsError(f"replay checkpoint is immutable once installed: {path}")
    causal_state = {field: getattr(replay, field) for field in REPLAY_CAUSAL_FIELDS}
    causal_state_pickle = pickle.dumps(causal_state, protocol=pickle.HIGHEST_PROTOCOL)
    payload = {
        "schema_version": REPLAY_CHECKPOINT_SCHEMA_VERSION,
        "engine_key": engine_key,
        "pre_day": pre_day,
        "causal_boundary": REPLAY_CHECKPOINT_BOUNDARY,
        "causal_state_sha256": hashlib.sha256(causal_state_pickle).hexdigest(),
        "causal_state_pickle": causal_state_pickle,
    }
    with atomic_output(path) as temporary:
        with temporary.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_replay_checkpoint(
    path: Path,
    *,
    engine_key: str,
    pre_day: str,
) -> TickReplayState:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"legacy or invalid tick replay checkpoint: {path}")
    if payload.get("schema_version") != REPLAY_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(f"tick replay checkpoint schema mismatch: {path}")
    if payload.get("engine_key") != engine_key:
        raise ValueError(f"tick replay checkpoint engine mismatch: {path}")
    if payload.get("pre_day") != pre_day or checkpoint_day(path) != pre_day:
        raise ValueError(f"tick replay checkpoint pre-day mismatch: {path}")
    if payload.get("causal_boundary") != REPLAY_CHECKPOINT_BOUNDARY:
        raise ValueError(f"tick replay checkpoint boundary mismatch: {path}")
    causal_state_pickle = payload.get("causal_state_pickle")
    if not isinstance(causal_state_pickle, bytes) or payload.get("causal_state_sha256") != hashlib.sha256(causal_state_pickle).hexdigest():
        raise ValueError(f"tick replay checkpoint content mismatch: {path}")
    try:
        causal_state = pickle.loads(causal_state_pickle)
    except (AttributeError, EOFError, ImportError, IndexError, pickle.UnpicklingError) as error:
        raise ValueError(f"tick replay checkpoint causal-state payload is invalid: {path}") from error
    if not isinstance(causal_state, dict) or set(causal_state) != set(REPLAY_CAUSAL_FIELDS):
        raise ValueError(f"tick replay checkpoint causal-state mismatch: {path}")
    replay = TickReplayState(**causal_state)
    replay.rebuild_derived_indexes()
    return replay


def ensure_replay_checkpoint(path: Path, replay: TickReplayState, *, engine_key: str, pre_day: str) -> bool:
    """Install one immutable checkpoint or prove an existing one has identical causal state."""
    if not path.exists():
        save_replay_checkpoint(path, replay, engine_key=engine_key, pre_day=pre_day)
        created = True
    else:
        created = False
    restored = load_replay_checkpoint(path, engine_key=engine_key, pre_day=pre_day)
    if any(getattr(restored, field) != getattr(replay, field) for field in REPLAY_CAUSAL_FIELDS):
        raise ValueError(f"tick replay checkpoint disagrees with sequential causal state: {path}")
    return created


def checkpoint_day(path: Path) -> str:
    name = path.stem
    if not name.startswith("pre_") or len(name) != 12 or not name[4:].isdigit():
        raise ValueError(f"invalid replay checkpoint name: {path.name}")
    return name[4:]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _route_key_sha256(keys: set[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for key in sorted(keys):
        digest.update(json.dumps(key, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _shard_contract(
    path: Path,
    *,
    day: str,
    rows: int,
    label: str,
) -> tuple[dict[str, object], set[tuple[str, str]]]:
    if rows == 0:
        if path.exists():
            raise ValueError(f"zero-row {label} cache should not exist: {path}")
        return {
            "rows": 0,
            "content_sha256": None,
            "schema_sha256": None,
            "day_start": None,
            "day_end": None,
            "route_key_count": 0,
            "route_key_sha256": _route_key_sha256(set()),
        }, set()
    if not path.exists():
        raise ValueError(f"frontier day-cache marker lacks {label}: {path}")
    parquet = pq.ParquetFile(path)
    observed_rows = parquet.metadata.num_rows
    if observed_rows != rows:
        raise ValueError(
            f"frontier {label} row mismatch for {day}: {observed_rows:,} != {rows:,}"
        )
    required = {"day", "route_id"}
    missing = sorted(required - set(parquet.schema.names))
    if missing:
        raise ValueError(
            f"frontier {label} route-key columns are missing: {', '.join(missing)}"
        )
    columns = pq.read_table(path, columns=["day", "route_id"]).to_pydict()
    days = [str(value) for value in columns["day"]]
    route_ids = columns["route_id"]
    if any(value is None or not str(value) for value in route_ids):
        raise ValueError(f"frontier {label} contains an empty route_id for {day}")
    keys = set(zip(days, (str(value) for value in route_ids), strict=True))
    if len(keys) != rows:
        raise ValueError(f"frontier {label} contains duplicate route keys for {day}")
    day_start = min(days)
    day_end = max(days)
    if day_start != day or day_end != day:
        raise ValueError(
            f"frontier {label} day bounds disagree for {day}: {day_start}..{day_end}"
        )
    schema_sha256 = hashlib.sha256(
        parquet.schema_arrow.serialize().to_pybytes()
    ).hexdigest()
    return {
        "rows": rows,
        "content_sha256": _file_sha256(path),
        "schema_sha256": schema_sha256,
        "day_start": day_start,
        "day_end": day_end,
        "route_key_count": len(keys),
        "route_key_sha256": _route_key_sha256(keys),
    }, keys


def _cached_day_contract(
    directory: Path,
    day: str,
    *,
    engine_key: str,
    input_key: str,
) -> tuple[Path, Path, dict[str, object]] | None:
    """Validate one marker-last cache bundle against its complete identity."""
    panel_path = directory / f"{day}.parquet"
    rejection_path = directory / f"{day}.rejections.parquet"
    support_path = directory / f"{day}.support.json"
    if not support_path.exists():
        return None
    marker = json.loads(support_path.read_text(encoding="utf-8"))
    if marker.get("schema_version") != DAY_CACHE_SCHEMA_VERSION:
        raise ValueError(f"frontier day-cache schema mismatch: {support_path}")
    if marker.get("engine_key") != engine_key:
        raise ValueError(f"frontier day-cache engine mismatch: {support_path}")
    if marker.get("input_key") != input_key:
        raise ValueError(f"frontier day-cache input mismatch: {support_path}")
    if marker.get("day_start") != day or marker.get("day_end") != day:
        raise ValueError(f"frontier day-cache bounds disagree with filename: {support_path}")
    support = marker.get("support")
    if not isinstance(support, dict):
        raise ValueError(f"frontier day-cache marker lacks support: {support_path}")
    if support.get("day") != day:
        raise ValueError(f"frontier day-cache marker disagrees with filename: {support_path}")
    expected = int(support.get("scored_routes", -1))
    rejected = int(support.get("rejected_routes", -1))
    if expected < 0 or rejected < 0:
        raise ValueError(f"frontier day-cache marker lacks row contracts: {support_path}")
    shards = marker.get("shards")
    if not isinstance(shards, dict) or set(shards) != {"panel", "rejections"}:
        raise ValueError(f"frontier day-cache marker lacks shard contracts: {support_path}")
    observed_panel, panel_keys = _shard_contract(
        panel_path, day=day, rows=expected, label="panel"
    )
    observed_rejections, rejection_keys = _shard_contract(
        rejection_path, day=day, rows=rejected, label="rejection panel"
    )
    if observed_panel != shards["panel"] or observed_rejections != shards["rejections"]:
        raise ValueError(f"frontier day-cache content contract mismatch: {support_path}")
    overlap = panel_keys & rejection_keys
    if overlap:
        raise ValueError(f"frontier day-cache route key appears in both shards: {min(overlap)}")
    return panel_path, rejection_path, support


def load_cached_day(
    directory: Path,
    day: str,
    *,
    engine_key: str,
    input_key: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]] | None:
    """Load a complete day result; the support marker is installed last."""
    contract = _cached_day_contract(
        directory, day, engine_key=engine_key, input_key=input_key
    )
    if contract is None:
        return None
    panel_path, rejection_path, support = contract
    panel = pd.read_parquet(panel_path) if panel_path.exists() else pd.DataFrame()
    rejections = (
        pd.read_parquet(rejection_path) if rejection_path.exists() else pd.DataFrame()
    )
    return panel, rejections, support


def load_cached_day_support(
    directory: Path,
    day: str,
    *,
    engine_key: str,
    input_key: str,
) -> dict[str, object] | None:
    """Validate a complete cached day without loading either route-level shard."""
    contract = _cached_day_contract(
        directory, day, engine_key=engine_key, input_key=input_key
    )
    if contract is None:
        return None
    return contract[2]


def write_cached_day(
    directory: Path,
    day: str,
    panel: pd.DataFrame,
    rejections: pd.DataFrame,
    support: dict[str, object],
    *,
    engine_key: str,
    input_key: str,
) -> None:
    """Atomically cache one scored audit day, installing its marker last."""
    if str(support.get("day")) != day:
        raise ValueError("frontier support day disagrees with cache key")
    if int(support.get("scored_routes", -1)) != len(panel):
        raise ValueError("frontier support count disagrees with cached panel")
    if int(support.get("rejected_routes", -1)) != len(rejections):
        raise ValueError("frontier support count disagrees with cached rejections")
    directory.mkdir(parents=True, exist_ok=True)
    marker_path = directory / f"{day}.support.json"
    marker_path.unlink(missing_ok=True)
    for frame, path in (
        (panel, directory / f"{day}.parquet"),
        (rejections, directory / f"{day}.rejections.parquet"),
    ):
        if frame.empty:
            path.unlink(missing_ok=True)
            continue
        with atomic_output(path) as temporary:
            frame.to_parquet(temporary, index=False)
    serialisable = {
        key: value.item() if isinstance(value, np.generic) else value
        for key, value in support.items()
    }
    panel_contract, panel_keys = _shard_contract(
        directory / f"{day}.parquet",
        day=day,
        rows=len(panel),
        label="panel",
    )
    rejection_contract, rejection_keys = _shard_contract(
        directory / f"{day}.rejections.parquet",
        day=day,
        rows=len(rejections),
        label="rejection panel",
    )
    overlap = panel_keys & rejection_keys
    if overlap:
        raise ValueError(f"frontier day-cache route key appears in both shards: {min(overlap)}")
    marker = {
        "schema_version": DAY_CACHE_SCHEMA_VERSION,
        "engine_key": engine_key,
        "input_key": input_key,
        "day_start": day,
        "day_end": day,
        "support": serialisable,
        "shards": {
            "panel": panel_contract,
            "rejections": rejection_contract,
        },
    }
    with atomic_output(marker_path) as temporary:
        temporary.write_text(
            json.dumps(marker, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def _install_immutable_file(source: Path, target: Path) -> bool:
    """Install one private staged file without replacing an existing generation."""

    if target.exists():
        if _file_sha256(target) != _file_sha256(source):
            raise FileExistsError(f"immutable frontier cache differs: {target}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(target) as temporary:
        shutil.copyfile(source, temporary)
    return True


def promote_cached_days(
    staging: Path,
    target: Path,
    days: tuple[str, ...],
    *,
    engine_key: str,
    input_key: str,
) -> tuple[Path, ...]:
    """Publish complete private day bundles marker-last and return new paths."""

    installed: list[Path] = []
    try:
        for day in days:
            if _cached_day_contract(
                staging, day, engine_key=engine_key, input_key=input_key
            ) is None:
                raise RuntimeError(f"frontier private day bundle is incomplete: {day}")
            marker = target / f"{day}.support.json"
            if marker.exists():
                if _cached_day_contract(
                    target, day, engine_key=engine_key, input_key=input_key
                ) is None:
                    raise RuntimeError(f"frontier installed day bundle is incomplete: {day}")
                continue
            target_paths = (
                target / f"{day}.parquet",
                target / f"{day}.rejections.parquet",
                marker,
            )
            if any(path.exists() for path in target_paths):
                raise FileExistsError(
                    f"frontier cache contains an unpublished partial bundle: {day}"
                )
            for suffix in (".parquet", ".rejections.parquet"):
                source = staging / f"{day}{suffix}"
                if source.exists():
                    destination = target / source.name
                    if _install_immutable_file(source, destination):
                        installed.append(destination)
            if _install_immutable_file(staging / marker.name, marker):
                installed.append(marker)
            if _cached_day_contract(
                target, day, engine_key=engine_key, input_key=input_key
            ) is None:
                raise RuntimeError(f"frontier promoted day bundle did not reopen: {day}")
    except BaseException:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        raise
    return tuple(installed)


def latest_replay_checkpoint(directory: Path, target_day: str) -> Path | None:
    candidates = [
        path
        for path in directory.glob(CHECKPOINT_GLOB)
        if checkpoint_day(path) <= target_day
    ]
    return max(candidates, key=checkpoint_day) if candidates else None


def replay_checkpoint_due(*, index: int) -> bool:
    """Bound resumed replay to fewer than ``CHECKPOINT_INTERVAL_DAYS`` days."""
    return (index - 1) % CHECKPOINT_INTERVAL_DAYS == 0


def physical_memory_bytes() -> int | None:
    """Return installed memory without adding a platform-specific dependency."""
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def daily_worker_count(requested: int | None, *, total_memory_bytes: int | None = None, cpu_count: int | None = None) -> int:
    """Bound full-daily processes by CPU and a conservative per-process memory budget."""
    memory = physical_memory_bytes() if total_memory_bytes is None else total_memory_bytes
    processors = os.cpu_count() if cpu_count is None else cpu_count
    cpu_cap = max(1, min(MAX_DAILY_WORKERS, int(processors or 1)))
    if memory is None:
        capacity = min(DEFAULT_DAILY_WORKERS, cpu_cap)
    else:
        memory_cap = max(1, (int(memory) - DAILY_PARENT_MEMORY_RESERVE_BYTES) // DAILY_WORKER_MEMORY_BUDGET_BYTES)
        capacity = min(cpu_cap, memory_cap)
    if requested is None:
        return capacity
    if requested < 1:
        raise ValueError("full-daily frontier workers must be positive")
    return min(int(requested), capacity)


def target_day_scoring_weights(release: TargetRelease) -> dict[str, int]:
    """Read deterministic route-count weights from the already certified target release."""
    if len(release.calendar) != len(release.day_markers):
        raise ValueError("daily target release calendar and marker counts disagree")
    weights: dict[str, int] = {}
    for day, marker in zip(release.calendar, release.day_markers, strict=True):
        record = json.loads(marker.read_text(encoding="utf-8"))
        support = record.get("support")
        if record.get("day") != day or record.get("generation") != release.generation or not isinstance(support, dict):
            raise ValueError(f"daily target marker identity drifted before segment planning: {day}")
        routes = int(support.get("admitted_provider_targets", -1))
        if routes < 0:
            raise ValueError(f"daily target marker lacks a scoring weight: {day}")
        weights[day] = max(1, routes)
    return weights


def plan_daily_segments(days: list[str], *, workers: int, checkpoint_dir: Path, scoring_weights: dict[str, int] | None = None) -> tuple[DailySegment, ...]:
    """Partition one exact daily calendar into deterministic exclusive contiguous segments."""
    if workers < 1:
        raise ValueError("daily segment worker count must be positive")
    if not days or days != sorted(set(days)):
        raise ValueError("full-daily frontier calendar must be nonempty, unique, and ordered")
    expected = [day.strftime("%Y%m%d") for day in pd.date_range(pd.to_datetime(days[0], format="%Y%m%d"), pd.to_datetime(days[-1], format="%Y%m%d"), freq="D")]
    if days != expected:
        raise ValueError("full-daily frontier calendar contains a gap")
    segment_count = min(workers, len(days))
    if scoring_weights is None:
        quotient, remainder = divmod(len(days), segment_count)
        boundaries = []
        offset = 0
        for index in range(segment_count - 1):
            offset += quotient + int(index < remainder)
            boundaries.append(offset)
        weights = {day: 1 for day in days}
    else:
        if set(scoring_weights) != set(days) or any(isinstance(weight, bool) or not isinstance(weight, int) or weight < 1 for weight in scoring_weights.values()):
            raise ValueError("full-daily frontier scoring weights must be positive integers on the exact calendar")
        weights = scoring_weights
        cumulative = [0]
        for day in days:
            cumulative.append(cumulative[-1] + weights[day])
        boundaries = []
        prior = 0
        for index in range(1, segment_count):
            target = cumulative[-1] * index / segment_count
            maximum = len(days) - (segment_count - index)
            candidates = range(prior + 1, maximum + 1)
            boundary = min(candidates, key=lambda value: (abs(cumulative[value] - target), value))
            boundaries.append(boundary)
            prior = boundary
    boundaries.append(len(days))
    segments: list[DailySegment] = []
    offset = 0
    for index, boundary in enumerate(boundaries):
        owned = tuple(days[offset:boundary])
        segments.append(DailySegment(index, owned, checkpoint_dir / f"pre_{owned[0]}.pkl", sum(weights[day] for day in owned)))
        offset = boundary
    validate_daily_segment_plan(segments, days)
    return tuple(segments)


def validate_daily_segment_plan(segments: list[DailySegment] | tuple[DailySegment, ...], days: list[str]) -> None:
    """Prove exact ordered ownership before any worker can write a shard."""
    if not segments:
        raise ValueError("full-daily frontier segment plan is empty")
    if [segment.index for segment in segments] != list(range(len(segments))):
        raise ValueError("full-daily frontier segment indexes are not canonical")
    flattened = [day for segment in segments for day in segment.days]
    if flattened != days or len(flattened) != len(set(flattened)):
        raise ValueError("full-daily frontier segments overlap or leave a gap")
    for segment in segments:
        if not segment.days or segment.scoring_weight < 1 or checkpoint_day(segment.checkpoint_path) != segment.days[0]:
            raise ValueError("full-daily frontier segment lacks its exact pre-start checkpoint")


def new_tick_replay() -> TickReplayState:
    """Construct the sole canonical empty replay state for this frontier."""
    return TickReplayState(token_decimals=load_token_decimals(TOKEN_DECIMALS), quarantined_pools={"uniswap_v4": load_v4_static_quarantine()})


def plan_replay_shard_tasks(days: tuple[str, ...], *, workers: int, market_state: Path | None, raw_root: Path, output_dir: Path) -> tuple[ReplayShardTask, ...]:
    """Split an ordered calendar into bounded contiguous partition-load tasks."""
    if workers < 1:
        raise ValueError("replay checkpoint workers must be positive")
    if not days:
        return ()
    if days != tuple(sorted(set(days))):
        raise ValueError("replay checkpoint calendar must be unique and ordered")
    def partition_bytes(day: str) -> int:
        paths = (
            [tick_partition_path(venue, day, root=market_state) for venue in TICK_VENUES]
            if market_state is not None
            else [
                path
                for venue in TICK_VENUES
                for path in state_partition_inputs(raw_root, "tick", venue, day)
            ]
        )
        return sum(path.stat().st_size for path in paths if path.exists())

    weights = [partition_bytes(day) for day in days]
    chunks = weighted_contiguous_chunks(days, weights, workers * 2)
    tasks = [ReplayShardTask(index, tuple(owned), market_state, raw_root, output_dir / f"events_{index:04d}.pkl") for index, owned in enumerate(chunks)]
    if [day for task in tasks for day in task.days] != list(days):
        raise RuntimeError("replay shard plan does not own the exact ordered calendar")
    return tuple(tasks)


def write_replay_event_shard(task: ReplayShardTask) -> ReplayShardResult:
    """Load certified day partitions and write one memory-bounded ordered stream."""
    event_count = 0
    with task.output_path.open("wb") as handle:
        pickler = pickle.Pickler(handle, protocol=pickle.HIGHEST_PROTOCOL)
        for day in task.days:
            for event in load_tick_day_events(task.market_state, day, raw_root=task.raw_root):
                pickler.dump((day, event))
                pickler.clear_memo()
                event_count += 1
    return ReplayShardResult(task.index, task.days, task.output_path, event_count)


def replay_ordered_event_shards(results: list[ReplayShardResult], *, boundaries: tuple[str, ...], checkpoint_paths: dict[str, Path], checkpoint_engine_key: str, replay: TickReplayState) -> tuple[int, int]:
    """Fold loaded shards in strict order and install exact pre-day checkpoints."""
    if not boundaries or tuple(sorted(checkpoint_paths)) != boundaries:
        raise ValueError("replay checkpoint boundaries are missing or out of order")
    if [result.index for result in results] != list(range(len(results))):
        raise ValueError("replay event shards are missing or out of order")
    boundary_index = 0
    events_applied = 0
    created_checkpoints = 0
    prior_key: tuple[str, tuple[int, int]] | None = None

    def checkpoint_before(day: str) -> None:
        nonlocal boundary_index, created_checkpoints
        while boundary_index < len(boundaries) and boundaries[boundary_index] <= day:
            boundary = boundaries[boundary_index]
            created_checkpoints += int(ensure_replay_checkpoint(checkpoint_paths[boundary], replay, engine_key=checkpoint_engine_key, pre_day=boundary))
            boundary_index += 1

    for result in results:
        shard_events = 0
        with result.output_path.open("rb") as handle:
            while True:
                try:
                    day, event = pickle.load(handle)
                except EOFError:
                    break
                if not isinstance(day, str) or not isinstance(event, TickReplayEvent) or event.venue not in TICK_VENUES:
                    raise ValueError(f"invalid tick replay event shard: {result.output_path}")
                key = (day, event.order)
                if prior_key is not None and key <= prior_key:
                    raise ValueError(f"tick replay event shard is not in strict causal order: {result.output_path}")
                checkpoint_before(day)
                replay.apply(event)
                prior_key = key
                shard_events += 1
                events_applied += 1
                if events_applied % 10_000_000 == 0:
                    print(f"checkpoint replay reduce: {events_applied:,} events through {day}", flush=True)
        if shard_events != result.event_count:
            raise ValueError(f"tick replay event shard count mismatch: {result.output_path}")
    checkpoint_before("99999999")
    if boundary_index != len(boundaries):
        raise RuntimeError("checkpoint replay did not close every pre-day boundary")
    return events_applied, created_checkpoints


def materialize_segment_checkpoints(
    segments: tuple[DailySegment, ...],
    *,
    checkpoint_dir: Path,
    checkpoint_engine_key: str,
    target_release: TargetRelease,
    market_state: Path | None = None,
    raw_root: Path = RAW_ROOT,
    workers: int = 1,
) -> tuple[int, int]:
    """Resume the latest pre-day state, prefetch its suffix, and replay it exactly once."""
    if workers < 1:
        raise ValueError("replay checkpoint workers must be positive")
    target_release.assert_current()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_paths = {segment.days[0]: segment.checkpoint_path for segment in segments}
    if not checkpoint_paths or len(checkpoint_paths) != len(segments):
        raise ValueError("replay checkpoint segments are empty or share a boundary")
    missing: list[str] = []
    for day, path in checkpoint_paths.items():
        if path.exists():
            load_replay_checkpoint(path, engine_key=checkpoint_engine_key, pre_day=day)
        else:
            missing.append(day)
    if not missing:
        return 0, 0
    first_missing = min(missing)
    last_missing = max(missing)
    resume_checkpoint = latest_replay_checkpoint(checkpoint_dir, first_missing)
    if resume_checkpoint is None:
        replay_start = min(REPLAY_START, first_missing)
        replay = new_tick_replay()
    else:
        replay_start = checkpoint_day(resume_checkpoint)
        replay = load_replay_checkpoint(resume_checkpoint, engine_key=checkpoint_engine_key, pre_day=replay_start)
    active_checkpoint_paths = {
        day: path
        for day, path in checkpoint_paths.items()
        if replay_start <= day <= last_missing
    }
    boundaries = tuple(sorted(active_checkpoint_paths))
    if not boundaries or min(missing) < replay_start or max(missing) > boundaries[-1]:
        raise RuntimeError("checkpoint resume window does not contain every missing boundary")
    history_days = tuple(day.strftime("%Y%m%d") for day in pd.date_range(pd.to_datetime(replay_start, format="%Y%m%d"), pd.to_datetime(last_missing, format="%Y%m%d") - pd.Timedelta(days=1), freq="D"))
    with TemporaryDirectory(prefix=".checkpoint-transaction-", dir=checkpoint_dir) as transaction_directory:
        transaction_root = Path(transaction_directory)
        event_directory = transaction_root / "events"
        event_directory.mkdir()
        staged_checkpoint_directory = transaction_root / "checkpoints"
        staged_checkpoint_directory.mkdir()
        transactional_checkpoint_paths = {
            day: (
                path
                if path.exists()
                else staged_checkpoint_directory / path.name
            )
            for day, path in active_checkpoint_paths.items()
        }
        tasks = plan_replay_shard_tasks(history_days, workers=workers, market_state=market_state, raw_root=raw_root, output_dir=event_directory)
        if workers == 1 or len(tasks) <= 1:
            results = [write_replay_event_shard(task) for task in tasks]
        else:
            by_index: dict[int, ReplayShardResult] = {}
            with interruptible_process_pool(min(workers, len(tasks))) as pool:
                futures = {pool.submit(write_replay_event_shard, task): task.index for task in tasks}
                for future in as_completed(futures):
                    result = future.result()
                    if result.index != futures[future] or result.index in by_index:
                        raise RuntimeError("replay partition loader returned the wrong shard identity")
                    by_index[result.index] = result
                    print(f"checkpoint event load: {len(by_index):,}/{len(tasks):,} shards complete", flush=True)
            if sorted(by_index) != list(range(len(tasks))):
                raise RuntimeError("replay partition loader result set is incomplete")
            results = [by_index[index] for index in range(len(tasks))]
        if [day for result in results for day in result.days] != list(history_days):
            raise RuntimeError("replay event shards do not close the exact historical calendar")
        mapped_events = sum(result.event_count for result in results)
        events_applied, created_checkpoints = replay_ordered_event_shards(results, boundaries=boundaries, checkpoint_paths=transactional_checkpoint_paths, checkpoint_engine_key=checkpoint_engine_key, replay=replay)
        if events_applied != mapped_events:
            raise RuntimeError("checkpoint replay event count disagrees with loaded partitions")
        temporary_bytes = sum(path.stat().st_size for path in event_directory.glob("events_*.pkl"))
        print(f"checkpoint event closure: {events_applied:,} events; temporary shuffle {temporary_bytes / 1024**3:.2f} GiB", flush=True)
        target_release.assert_current()
        installed: list[Path] = []
        try:
            for day, live_path in active_checkpoint_paths.items():
                staged_path = transactional_checkpoint_paths[day]
                if staged_path == live_path:
                    continue
                if _install_immutable_file(staged_path, live_path):
                    installed.append(live_path)
                load_replay_checkpoint(
                    live_path,
                    engine_key=checkpoint_engine_key,
                    pre_day=day,
                )
            target_release.assert_current()
        except BaseException:
            for path in reversed(installed):
                path.unlink(missing_ok=True)
            raise
    return len(history_days), created_checkpoints


def score_daily_segment(task: DailySegmentTask) -> DailySegmentResult:
    """Score one exclusive segment from its exact immutable pre-start state."""
    segment = task.segment
    replay = load_replay_checkpoint(segment.checkpoint_path, engine_key=task.checkpoint_engine_key, pre_day=segment.days[0])
    support_rows: list[dict[str, object]] = []
    scored_days = 0
    cached_days = 0
    for offset, day in enumerate(segment.days, 1):
        cached = load_cached_day_support(task.read_day_cache, day, engine_key=task.frontier_engine_key, input_key=task.frontier_input_key)
        if cached is not None:
            warm_tick_day(task.market_state, day, replay)
            support = cached
            cached_days += 1
        else:
            events = load_tick_day_events(task.market_state, day)
            v2_replay = load_v2_replay_day(task.cp_market_state or task.market_state, day)
            frame, rejections, support = score_day(day, events, replay, v2_replay, task.vehicles, task.target_release)
            write_cached_day(task.write_day_cache, day, frame, rejections, support, engine_key=task.frontier_engine_key, input_key=task.frontier_input_key)
            support = load_cached_day_support(task.write_day_cache, day, engine_key=task.frontier_engine_key, input_key=task.frontier_input_key)
            if support is None:
                raise RuntimeError(f"frontier worker failed to reopen its completed day: {day}")
            scored_days += 1
        support_rows.append(support)
        if offset % 30 == 0 or offset == len(segment.days):
            print(f"frontier segment {segment.index + 1}: {offset:,}/{len(segment.days):,} days; {scored_days:,} scored; {cached_days:,} cached; through {day}", flush=True)
    return DailySegmentResult(segment.index, segment.days, tuple(support_rows), scored_days, cached_days)


def run_daily_segments(segments: tuple[DailySegment, ...], *, workers: int, checkpoint_engine_key: str, day_cache: Path, frontier_engine_key: str, frontier_input_key: str, vehicles: tuple[str, ...], target_release: TargetRelease, market_state: Path | None = None, cp_market_state: Path | None = None) -> list[dict[str, object]]:
    """Run bounded disjoint scoring processes and return support in canonical calendar order."""
    expected_days = [day for segment in segments for day in segment.days]
    validate_daily_segment_plan(segments, expected_days)
    target_release.assert_current()
    day_cache.parent.mkdir(parents=True, exist_ok=True)
    results: dict[int, DailySegmentResult] = {}
    with TemporaryDirectory(prefix=".frontier-day-transaction-", dir=day_cache.parent) as temporary_directory:
        staging_cache = Path(temporary_directory)
        tasks = [DailySegmentTask(segment, checkpoint_engine_key, day_cache, staging_cache, frontier_engine_key, frontier_input_key, vehicles, target_release, market_state, cp_market_state) for segment in segments]
        if workers == 1:
            for task in tasks:
                result = score_daily_segment(task)
                results[result.index] = result
        else:
            with interruptible_process_pool(min(workers, len(tasks))) as pool:
                futures = {pool.submit(score_daily_segment, task): task.segment.index for task in tasks}
                for future in as_completed(futures):
                    result = future.result()
                    if result.index != futures[future] or result.index in results:
                        raise RuntimeError("full-daily frontier worker returned the wrong segment identity")
                    results[result.index] = result
                    completed = sum(len(item.days) for item in results.values())
                    print(f"parallel frontier segments {len(results):,}/{len(tasks):,}; days {completed:,}/{len(expected_days):,}", flush=True)
        target_release.assert_current()
        staged_days = tuple(
            day
            for day in expected_days
            if (staging_cache / f"{day}.support.json").is_file()
        )
        installed = promote_cached_days(
            staging_cache,
            day_cache,
            staged_days,
            engine_key=frontier_engine_key,
            input_key=frontier_input_key,
        )
        try:
            target_release.assert_current()
        except BaseException:
            for path in reversed(installed):
                path.unlink(missing_ok=True)
            raise
    if sorted(results) != list(range(len(segments))):
        raise RuntimeError("full-daily frontier worker result set is incomplete")
    support_rows: list[dict[str, object]] = []
    for segment in segments:
        result = results[segment.index]
        if result.days != segment.days or tuple(str(row.get("day")) for row in result.support_rows) != segment.days:
            raise RuntimeError("full-daily frontier worker support does not match segment ownership")
        support_rows.extend(result.support_rows)
    return support_rows


def available_days(*, nonempty: bool = False) -> list[str]:
    return released_route_days(UNIFIED_QUALITY_PANEL, nonempty=nonempty)


def select_days(
    available: list[str],
    *,
    explicit: list[str] | None,
    audit_calendar: bool,
    daily_calendar: bool = False,
) -> list[str]:
    if explicit:
        selected = list(dict.fromkeys(day.replace("-", "") for day in explicit))
    elif audit_calendar:
        selected = select_transaction_frontier_audit_days(available)
    elif daily_calendar:
        selected = available
    else:
        raise ValueError("select explicit, audit, or full daily frontier dates")
    missing = sorted(set(selected) - set(available))
    if missing:
        raise ValueError("requested frontier day unavailable: " + ", ".join(missing))
    if not selected:
        raise ValueError("no transaction-state frontier days selected")
    return sorted(selected)


def require_full_daily_target_release(expected_days: list[str] | None = None) -> TargetRelease:
    """Resolve the current provider-derived daily target release without a fallback reader."""

    return resolve_target_release("daily", expected_days=expected_days)


def validate_reproduction_support(
    support: pd.DataFrame,
    expected_days: list[str],
    *,
    label: str,
) -> tuple[float, float, float]:
    """Validate one frontier calendar and report chosen-route reproduction."""
    required = {
        "day",
        "within_20pct_chosen_quote_eligible_routes",
        "within_20pct_chosen_quote_available",
        "within_20pct_chosen_output_mismatch",
    }
    missing_columns = sorted(required - set(support.columns))
    if missing_columns:
        raise ValueError(
            f"{label} support is missing columns: "
            + ", ".join(missing_columns)
        )
    normalised = support.loc[:, sorted(required)].copy()
    normalised["day"] = normalised["day"].astype(str).str.replace("-", "", regex=False)
    malformed = normalised.loc[~normalised["day"].str.fullmatch(r"\d{8}")]
    if not malformed.empty:
        raise ValueError(f"{label} support contains malformed days")
    duplicates = normalised.loc[normalised["day"].duplicated(), "day"].tolist()
    if duplicates:
        raise ValueError(
            f"{label} support contains duplicate days: "
            + ", ".join(sorted(set(duplicates)))
        )
    actual_days = sorted(normalised["day"].tolist())
    expected = sorted(day.replace("-", "") for day in expected_days)
    if actual_days != expected:
        missing_days = sorted(set(expected) - set(actual_days))
        extra_days = sorted(set(actual_days) - set(expected))
        details = []
        if missing_days:
            details.append("missing " + ", ".join(missing_days))
        if extra_days:
            details.append("extra " + ", ".join(extra_days))
        raise ValueError(
            f"{label} support calendar does not match the current release: "
            + "; ".join(details)
        )
    counts = normalised[
        [
            "within_20pct_chosen_quote_available",
            "within_20pct_chosen_quote_eligible_routes",
            "within_20pct_chosen_output_mismatch",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if counts.isna().any().any() or (counts < 0).any().any():
        raise ValueError(f"{label} support contains invalid reproduction counts")
    if not np.equal(counts, np.floor(counts)).all().all():
        raise ValueError(f"{label} support contains non-integer reproduction counts")
    eligible = int(counts["within_20pct_chosen_quote_eligible_routes"].sum())
    available = int(counts["within_20pct_chosen_quote_available"].sum())
    mismatches = int(counts["within_20pct_chosen_output_mismatch"].sum())
    if available > eligible:
        raise ValueError(f"{label} available chosen quotes exceed eligible routes")
    if mismatches > available:
        raise ValueError(f"{label} mismatches exceed available chosen quotes")
    state_coverage = chosen_quote_coverage_share(eligible, available)
    verified_coverage = chosen_quote_coverage_share(
        eligible, available - mismatches
    )
    reproduction = chosen_reproduction_share(available, mismatches)
    return reproduction, state_coverage, verified_coverage


def validate_audit_support(
    support: pd.DataFrame,
    expected_days: list[str],
) -> tuple[float, float, float]:
    """Validate the current construction-audit certificate."""
    return validate_reproduction_support(
        support,
        expected_days,
        label="frontier audit",
    )


def validate_daily_support(
    support: pd.DataFrame,
    expected_days: list[str],
) -> tuple[float, float, float]:
    """Validate the full-daily ledger before publishing any canonical artifact."""
    return validate_reproduction_support(
        support,
        expected_days,
        label="full-daily frontier",
    )


def require_frontier_audit_gate(
    expected_days: list[str],
) -> tuple[float, float, float]:
    """Require a current, complete audit certificate before a full-daily build."""
    require_current_artifacts(
        [AUDIT_PANEL, AUDIT_REJECTIONS, AUDIT_SUPPORT],
        consumer="full-daily transaction-state frontier",
    )
    support = pd.read_json(AUDIT_SUPPORT, lines=True, dtype={"day": str})
    return validate_audit_support(support, expected_days)


def rejection_record(
    day: str,
    route: dict[str, object],
    reason: str,
    *,
    reason_detail: str | None = None,
    causal_order: tuple[int, int] | None = None,
    venues: tuple[str, ...] | None = None,
    pools: tuple[str, ...] | None = None,
    chosen_quote_out: float | None = None,
    signed_validation_error_bps: float | None = None,
    chosen_leg1_validation_error_bps: float | None = None,
    chosen_leg2_validation_error_bps: float | None = None,
) -> dict[str, object]:
    """Preserve the economic and causal identity of every excluded exact route."""
    realised_venues = venues or tuple(
        str(route.get(column) or "")
        for column in ("realised_hop1_source", "realised_hop2_source")
    )
    realised_pools = pools or ()
    return {
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "day": day,
        "route_id": str(route.get("route_id") or ""),
        "tx_hash": str(route.get("tx_hash") or "").lower(),
        "component_id": int(route.get("component_id") or 0),
        "timestamp_utc": int(route.get("timestamp_utc") or 0),
        "block_number": causal_order[0] if causal_order is not None else None,
        "first_log_index": causal_order[1] if causal_order is not None else None,
        "src": str(route.get("src") or ""),
        "tgt": str(route.get("tgt") or ""),
        "vehicle": str(route.get("vehicle") or ""),
        "vehicle_type": asset_type(str(route.get("vehicle") or "")),
        "input_usd": float(route.get("input_usd") or 0.0),
        "output_usd": float(route.get("output_usd") or 0.0),
        "within_20pct": bool(route.get("within_20pct")),
        "cross_venue": bool(route.get("cross_venue")),
        "realised_amount_in": float(route.get("realised_amount_in") or 0.0),
        "realised_amount_out": float(route.get("realised_amount_out") or 0.0),
        "realised_leg1_output": route.get("realised_leg1_output"),
        "realised_leg2_input": route.get("realised_leg2_input"),
        "intermediate_amount_gap_bps": route.get("intermediate_amount_gap_bps"),
        "realised_venues": "|".join(value for value in realised_venues if value),
        "realised_pools": "|".join(value for value in realised_pools if value),
        "reason": reason,
        "reason_detail": reason_detail,
        "chosen_quote_out": chosen_quote_out,
        "signed_validation_error_bps": signed_validation_error_bps,
        "chosen_leg1_validation_error_bps": chosen_leg1_validation_error_bps,
        "chosen_leg2_validation_error_bps": chosen_leg2_validation_error_bps,
        "validation_tolerance_bps": MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
    }


def intermediate_amount_gap_bps(
    leg1_output: object, leg2_input: object
) -> float | None:
    """Token-unit discontinuity between the two claimed legs of one route."""
    try:
        first = float(leg1_output)
        second = float(leg2_input)
    except (TypeError, ValueError):
        return None
    if not positive_finite_amount(first) or not positive_finite_amount(second):
        return None
    return 10_000 * (second / first - 1.0)


def load_target_routes(
    day: str,
    release: TargetRelease,
    v2_replay: V2ReplayDay,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    ledger, released_support = read_target_day(release, day)
    targets: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    mapped = len(ledger)
    above_minimum = 0
    intermediate_amount_coherent = 0
    intermediate_amount_incoherent = 0
    structurally_rejected = 0
    for route in ledger.to_dict("records"):
        flow_gap = intermediate_amount_gap_bps(route["realised_leg1_output"], route["realised_leg2_input"])
        route = {
            **route,
            "intermediate_amount_gap_bps": flow_gap,
        }
        if flow_gap is None or abs(flow_gap) > INTERMEDIATE_FLOW_TOLERANCE_BPS:
            intermediate_amount_incoherent += 1
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "intermediate_amount_incoherent",
                    reason_detail=(
                        "nonpositive_or_missing"
                        if flow_gap is None
                        else f"gap_bps={flow_gap}"
                    ),
                )
            )
            continue
        intermediate_amount_coherent += 1
        venues = (str(route["leg1_venue"]), str(route["leg2_venue"]))
        pools = (str(route["leg1_pool"]), str(route["leg2_pool"]))
        target_order = (int(route["target_order_block"]), int(route["target_order_log_index"]))
        if not bool(route["target_admitted"]):
            structurally_rejected += 1
            detail = route.get("target_structural_rejection")
            if pd.isna(detail):
                detail = None
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "certified_target_structural_rejection",
                    reason_detail=str(detail) if detail else None,
                    causal_order=target_order,
                    venues=venues,
                    pools=pools,
                )
            )
            continue
        input_usd = float(route["input_usd"])
        if not np.isfinite(input_usd) or input_usd < MIN_INPUT_USD:
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "realised_input_below_minimum",
                    reason_detail=f"input_usd={input_usd}",
                    causal_order=target_order,
                    venues=venues,
                    pools=pools,
                )
            )
            continue
        above_minimum += 1
        target_timestamp = int(route["target_timestamp"])
        targets.append(
            {
                **route,
                "day": day,
                "target_order": target_order,
                "v2_hour": target_timestamp - target_timestamp % 3600,
                "v2_order": target_order,
                "realised_venues": venues,
                "realised_pools": pools,
                "vehicle_type": asset_type(str(route["vehicle"])),
            }
        )
    targets.sort(key=lambda row: (row["target_order"], row["route_id"]))
    tick_only = ledger[ledger["leg1_venue"].isin(TICK_VENUES) & ledger["leg2_venue"].isin(TICK_VENUES)]
    v2_only = ledger[ledger["leg1_venue"].isin(V2_VENUES) & ledger["leg2_venue"].isin(V2_VENUES)]
    support = {
        "day": day,
        "all_exact_two_leg_routes": int(released_support["all_exact_two_leg_routes"]),
        "exact_venue_two_leg_routes": int(released_support["exact_venue_two_leg_routes"]),
        "exact_venue_share": float(len(ledger) / int(released_support["all_exact_two_leg_routes"])) if int(released_support["all_exact_two_leg_routes"]) else None,
        "tick_venue_exact_two_leg_routes": int(len(tick_only)),
        "v2_venue_exact_two_leg_routes": int(len(v2_only)),
        "mixed_family_exact_two_leg_routes": int(len(ledger) - len(tick_only) - len(v2_only)),
        "block_order_unavailable_routes": 0,
        "raw_tx_log_mapped_routes": mapped,
        "certified_target_structural_rejections": structurally_rejected,
        "intermediate_amount_coherent_routes": intermediate_amount_coherent,
        "intermediate_amount_incoherent_routes": int(
            intermediate_amount_incoherent
        ),
        "intermediate_flow_tolerance_bps": INTERMEDIATE_FLOW_TOLERANCE_BPS,
        "routes_at_least_100usd": above_minimum,
        "chosen_quote_eligible_routes": len(targets),
        "within_20pct_chosen_quote_eligible_routes": sum(
            bool(target["within_20pct"]) for target in targets
        ),
        "scored_routes": 0,
        "rejected_routes": len(rejections),
        "invalid_realised_input": 0,
        "invalid_realised_output": 0,
        "invalid_chosen_output": 0,
        "chosen_state_unavailable": 0,
        "chosen_output_mismatch": 0,
        "chosen_validation_tolerance_bps": MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
        "quarantined_tick_pools": 0,
        "candidate_v2_pool_hours": int(len(v2_replay.pool_hour_events)),
        "clean_v2_pool_hours": int(len(v2_replay.state_support)),
    }
    return targets, rejections, support


def validation_error_diagnostics(errors_bps: list[float]) -> dict[str, object]:
    """Summarise every available chosen-route quote, including rejected tails."""
    absolute = pd.Series(errors_bps, dtype=float).abs()
    mismatch = absolute[absolute.gt(MAX_CHOSEN_REPRODUCTION_ERROR_BPS)]

    def quantile(values: pd.Series, probability: float) -> float | None:
        return float(values.quantile(probability)) if not values.empty else None

    return {
        "quote_available": int(len(absolute)),
        "output_mismatch": int(len(mismatch)),
        "validation_abs_median_bps": quantile(absolute, 0.5),
        "validation_abs_p90_bps": quantile(absolute, 0.9),
        "validation_abs_p99_bps": quantile(absolute, 0.99),
        "validation_abs_max_bps": quantile(absolute, 1.0),
        "validation_within_tolerance_share": (
            float(absolute.le(MAX_CHOSEN_REPRODUCTION_ERROR_BPS).mean())
            if not absolute.empty
            else None
        ),
        "mismatch_abs_min_bps": quantile(mismatch, 0.0),
        "mismatch_abs_median_bps": quantile(mismatch, 0.5),
        "mismatch_abs_p90_bps": quantile(mismatch, 0.9),
        "mismatch_abs_max_bps": quantile(mismatch, 1.0),
    }


def chosen_path_validation_errors(
    *,
    realised_leg1_output: float,
    realised_path_output: float,
    quoted_leg1_output: float,
    quoted_leg2_output: float,
    quoted_path_output: float,
) -> dict[str, float] | None:
    """Return both leg errors, composed-path error and their maximum magnitude."""
    errors = {
        "chosen_leg1_validation_error_bps": relative_output_error(
            realised_leg1_output, quoted_leg1_output
        ),
        "chosen_leg2_validation_error_bps": relative_output_error(
            realised_path_output, quoted_leg2_output
        ),
        "chosen_validation_error_bps": relative_output_error(
            realised_path_output, quoted_path_output
        ),
    }
    if any(error is None for error in errors.values()):
        return None
    scaled = {name: 10_000 * float(error) for name, error in errors.items()}
    scaled["chosen_validation_max_abs_error_bps"] = max(
        abs(error) for error in scaled.values()
    )
    return scaled


def score_day(
    day: str,
    events: list[TickReplayEvent],
    replay: TickReplayState,
    v2_replay: V2ReplayDay,
    vehicles: tuple[str, ...],
    target_release: TargetRelease,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    targets, rejection_rows, support = load_target_routes(day, target_release, v2_replay)
    by_order: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for target in targets:
        by_order[target["target_order"]].append(target)
    rows: list[dict[str, object]] = []
    validation_errors_bps: list[float] = []
    coherent_validation_errors_bps: list[float] = []
    event_cursor = OrderedTickStateCursor(tuple(events))
    for order in sorted(by_order):
        event_cursor.apply_until(replay, TickStateCut.strict_before_event(order))
        for target in by_order[order]:
            route = RealisedPath(
                token_in=str(target["src"]),
                token_out=str(target["tgt"]),
                vehicle=str(target["vehicle"]),
                amount_in=float(target["realised_amount_in"]),
                amount_out=float(target["realised_amount_out"]),
                venues=target["realised_venues"],
                pools=target["realised_pools"],
            )
            frontier_state = MixedFrontierState(
                tick_pool_index=replay.pool_index,
                tick_states_by_venue=replay.states_by_venue,
                tick_ticks_by_venue=replay.ticks_by_venue,
                tick_quote_indexes_by_venue=replay.quote_indexes_by_venue,
                v2_replay=v2_replay,
                v2_hour=int(target["v2_hour"]),
                v2_order=target["v2_order"],
            )
            if not positive_finite_amount(route.amount_in):
                support["invalid_realised_input"] += 1
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "invalid_realised_input",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                    )
                )
                continue

            quote_legs = partial(
                mixed_leg_quotes,
                state=frontier_state,
                allowed_venues=None,
                max_support=MAX_PRICE_IMPACT,
            )
            chosen_leg1 = quote_mixed_pool(
                route.token_in,
                route.vehicle,
                route.amount_in,
                venue=route.venues[0],
                pool_id=route.pools[0],
                state=frontier_state,
                max_support=None,
            )
            chosen_leg2 = (
                quote_mixed_pool(
                    route.vehicle,
                    route.token_out,
                    float(target["realised_leg2_input"]),
                    venue=route.venues[1],
                    pool_id=route.pools[1],
                    state=frontier_state,
                    max_support=None,
                )
                if chosen_leg1 is not None
                else None
            )
            composed_leg2 = (
                quote_mixed_pool(
                    route.vehicle,
                    route.token_out,
                    chosen_leg1.amount_out,
                    venue=route.venues[1],
                    pool_id=route.pools[1],
                    state=frontier_state,
                    max_support=None,
                )
                if chosen_leg1 is not None
                else None
            )
            chosen = (
                PathQuote(
                    amount_out=composed_leg2.amount_out,
                    vehicle=route.vehicle,
                    venues=route.venues,
                    pools=route.pools,
                    price_impacts=(
                        chosen_leg1.price_impact,
                        composed_leg2.price_impact,
                    ),
                )
                if chosen_leg1 is not None and composed_leg2 is not None
                else None
            )
            if chosen is None or chosen_leg2 is None:
                support["chosen_state_unavailable"] += 1
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "chosen_state_unavailable",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                    )
                )
                continue
            validation = chosen_path_validation_errors(
                realised_leg1_output=float(target["realised_leg1_output"]),
                realised_path_output=route.amount_out,
                quoted_leg1_output=chosen_leg1.amount_out,
                quoted_leg2_output=chosen_leg2.amount_out,
                quoted_path_output=chosen.amount_out,
            )
            if validation is None:
                if not positive_finite_amount(route.amount_out):
                    support["invalid_realised_output"] += 1
                    reason = "invalid_realised_output"
                else:
                    support["invalid_chosen_output"] += 1
                    reason = "invalid_chosen_output"
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        reason,
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                        chosen_quote_out=float(chosen.amount_out),
                    )
                )
                continue
            signed_validation_error_bps = validation["chosen_validation_error_bps"]
            leg1_validation_error_bps = validation[
                "chosen_leg1_validation_error_bps"
            ]
            leg2_validation_error_bps = validation[
                "chosen_leg2_validation_error_bps"
            ]
            maximum_validation_error_bps = validation[
                "chosen_validation_max_abs_error_bps"
            ]
            validation_errors_bps.append(maximum_validation_error_bps)
            if bool(target["within_20pct"]):
                coherent_validation_errors_bps.append(validation_errors_bps[-1])
            if maximum_validation_error_bps > MAX_CHOSEN_REPRODUCTION_ERROR_BPS:
                support["chosen_output_mismatch"] += 1
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "chosen_output_mismatch",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                        chosen_quote_out=float(chosen.amount_out),
                        signed_validation_error_bps=signed_validation_error_bps,
                        chosen_leg1_validation_error_bps=leg1_validation_error_bps,
                        chosen_leg2_validation_error_bps=leg2_validation_error_bps,
                    )
                )
                continue
            score = score_frontier_from_quote(
                route,
                chosen=chosen,
                vehicles=vehicles,
                quote_legs=quote_legs,
                validation_tolerance=MAX_CHOSEN_REPRODUCTION_ERROR,
            )
            if score is None:
                raise AssertionError("validated chosen path was rejected during frontier scoring")
            realised_out = route.amount_out
            target_price = float(target["output_usd"]) / realised_out
            public_gain_usd = max(
                0.0,
                (float(score["public_path_out"]) - realised_out) * target_price,
            )
            rows.append(
                {
                    "date": pd.to_datetime(day, format="%Y%m%d"),
                    "day": day,
                    "route_id": target["route_id"],
                    "tx_hash": target["tx_hash"],
                    "component_id": int(target["component_id"]),
                    "timestamp_utc": int(target["timestamp_utc"]),
                    "first_log_index": int(order[1]),
                    "v2_block_order_available": target["v2_order"] is not None,
                    "src": route.token_in,
                    "tgt": route.token_out,
                    "vehicle": route.vehicle,
                    "vehicle_type": target["vehicle_type"],
                    "input_usd": float(target["input_usd"]),
                    "output_usd": float(target["output_usd"]),
                    "within_20pct": bool(target["within_20pct"]),
                    "cross_venue": bool(target["cross_venue"]),
                    "realised_amount_in": route.amount_in,
                    "realised_amount_out": route.amount_out,
                    "realised_leg1_output": target["realised_leg1_output"],
                    "realised_leg2_input": target["realised_leg2_input"],
                    "intermediate_amount_gap_bps": target[
                        "intermediate_amount_gap_bps"
                    ],
                    "realised_venues": "|".join(route.venues),
                    "realised_pools": "|".join(route.pools),
                    "public_gain_usd": public_gain_usd,
                    "chosen_leg1_validation_error_bps": leg1_validation_error_bps,
                    "chosen_leg2_validation_error_bps": leg2_validation_error_bps,
                    "chosen_validation_max_abs_error_bps": maximum_validation_error_bps,
                    **score,
                }
            )
        event_cursor.apply_until(
            replay,
            TickStateCut.strict_before_event((order[0], order[1] + 1)),
        )
    event_cursor.apply_remaining(replay)
    support["scored_routes"] = len(rows)
    support["rejected_routes"] = len(rejection_rows)
    if len(rows) + len(rejection_rows) != int(support["exact_venue_two_leg_routes"]):
        raise AssertionError("frontier route ledger does not reconcile to exact support")
    support["quarantined_tick_pools"] = sum(
        len(pools) for pools in replay.quarantined_pools.values()
    )
    diagnostics = validation_error_diagnostics(validation_errors_bps)
    support.update({f"chosen_{key}": value for key, value in diagnostics.items()})
    coherent_diagnostics = validation_error_diagnostics(coherent_validation_errors_bps)
    support.update(
        {
            f"within_20pct_chosen_{key}": value
            for key, value in coherent_diagnostics.items()
        }
    )
    quote_outcome_rejections = [
        rejection
        for rejection in rejection_rows
        if rejection["reason"] in QUOTE_OUTCOME_REASONS
    ]
    if len(rows) + len(quote_outcome_rejections) != int(
        support["chosen_quote_eligible_routes"]
    ):
        raise AssertionError("frontier chosen-quote outcome funnel does not reconcile")
    within_20pct_outcomes = sum(bool(row["within_20pct"]) for row in rows) + sum(
        bool(rejection["within_20pct"]) for rejection in quote_outcome_rejections
    )
    if within_20pct_outcomes != int(
        support["within_20pct_chosen_quote_eligible_routes"]
    ):
        raise AssertionError(
            "frontier coherent chosen-quote outcome funnel does not reconcile"
        )
    if int(support["chosen_quote_available"]) != len(rows) + int(
        support["chosen_output_mismatch"]
    ):
        raise AssertionError("frontier chosen-quote availability does not reconcile")
    support["chosen_quote_coverage_share"] = chosen_quote_coverage_share(
        int(support["chosen_quote_eligible_routes"]),
        int(support["chosen_quote_available"]),
    )
    support["within_20pct_chosen_quote_coverage_share"] = (
        chosen_quote_coverage_share(
            int(support["within_20pct_chosen_quote_eligible_routes"]),
            int(support["within_20pct_chosen_quote_available"]),
        )
    )
    support["chosen_verified_routes"] = int(support["chosen_quote_available"]) - int(
        support["chosen_output_mismatch"]
    )
    support["chosen_verified_coverage_share"] = chosen_quote_coverage_share(
        int(support["chosen_quote_eligible_routes"]),
        int(support["chosen_verified_routes"]),
    )
    support["within_20pct_chosen_verified_routes"] = int(
        support["within_20pct_chosen_quote_available"]
    ) - int(support["within_20pct_chosen_output_mismatch"])
    support["within_20pct_chosen_verified_coverage_share"] = (
        chosen_quote_coverage_share(
            int(support["within_20pct_chosen_quote_eligible_routes"]),
            int(support["within_20pct_chosen_verified_routes"]),
        )
    )
    return pd.DataFrame(rows), pd.DataFrame(rejection_rows), support


def _concentration(values: pd.Series) -> float | None:
    positive = values[np.isfinite(values) & values.gt(0)].sort_values(ascending=False)
    if positive.empty:
        return None
    count = max(1, int(np.ceil(0.01 * len(positive))))
    return float(positive.iloc[:count].sum() / positive.sum())


def summarise(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    groups: list[tuple[str, str, pd.DataFrame]] = []
    for label, frame in (("all", panel), ("within_20pct", panel[panel["within_20pct"]])):
        groups.append(("pooled", label, frame))
        groups.extend(
            (str(day), label, day_frame)
            for day, day_frame in frame.groupby("day", sort=True)
        )
    for day, sample, frame in groups:
        if frame.empty:
            continue
        regret = frame["public_path_regret_bps"].astype(float)
        direct = pd.to_numeric(frame["direct_omission_bps"], errors="coerce")
        gain = frame["public_gain_usd"].astype(float)
        rows.append(
            {
                "day": day,
                "sample": sample,
                "routes": int(len(frame)),
                "input_usd": float(frame["input_usd"].sum()),
                "chosen_validation_abs_median_bps": float(
                    frame["chosen_validation_error_bps"].abs().median()
                ),
                "within_reach_regret_positive_share": float(
                    frame["within_reach_search_regret_bps"].gt(0).mean()
                ),
                "public_reach_regret_positive_share": float(
                    frame["public_reach_same_vehicle_regret_bps"].gt(0).mean()
                ),
                "public_path_regret_positive_share": float(regret.gt(0).mean()),
                "public_path_regret_over_0p01bps_share": float(regret.gt(0.01).mean()),
                "public_path_regret_over_1bps_share": float(regret.gt(1.0).mean()),
                "public_path_regret_over_10bps_share": float(regret.gt(10).mean()),
                "public_path_regret_median_bps": float(regret.median()),
                "public_path_regret_p90_bps": float(regret.quantile(0.9)),
                "within_reach_increment_mean_bps": float(
                    frame["within_reach_search_regret_bps"].mean()
                ),
                "within_reach_regret_over_0p01bps_share": float(
                    frame["within_reach_search_regret_bps"].gt(0.01).mean()
                ),
                "within_reach_regret_over_1bps_share": float(
                    frame["within_reach_search_regret_bps"].gt(1.0).mean()
                ),
                "reach_increment_mean_bps": float(frame["reach_increment_bps"].mean()),
                "reach_increment_over_0p01bps_share": float(
                    frame["reach_increment_bps"].gt(0.01).mean()
                ),
                "reach_increment_over_1bps_share": float(
                    frame["reach_increment_bps"].gt(1.0).mean()
                ),
                "path_choice_increment_mean_bps": float(
                    frame["path_choice_increment_bps"].mean()
                ),
                "path_choice_increment_over_0p01bps_share": float(
                    frame["path_choice_increment_bps"].gt(0.01).mean()
                ),
                "path_choice_increment_over_1bps_share": float(
                    frame["path_choice_increment_bps"].gt(1.0).mean()
                ),
                "direct_available_share": float(direct.notna().mean()),
                "direct_omission_positive_share": float(direct.fillna(0).gt(0).mean()),
                "aggregate_public_gain_usd": float(gain.sum()),
                "median_public_gain_usd": float(gain.median()),
                "public_gain_top_1pct_share": _concentration(gain),
            }
        )
    return pd.DataFrame(rows)


def write_ordered_shard_manifest(
    day_cache: Path,
    support_rows: list[dict[str, object]],
    *,
    suffix: str,
    count_column: str,
    output: Path,
    engine_key: str,
    input_key: str,
) -> tuple[Path, list[Path]]:
    """Materialise the ordered marker closure for one assembled output."""
    ordered_days = [str(row["day"]) for row in support_rows]
    if not ordered_days or ordered_days != sorted(set(ordered_days)):
        raise ValueError("frontier shard manifest days must be unique and ordered")
    entries: list[dict[str, object]] = []
    marker_paths: list[Path] = []
    for row, day in zip(support_rows, ordered_days, strict=True):
        contract = _cached_day_contract(
            day_cache,
            day,
            engine_key=engine_key,
            input_key=input_key,
        )
        if contract is None:
            raise ValueError(f"frontier shard manifest lacks cached day: {day}")
        marker_path = day_cache / f"{day}.support.json"
        marker_paths.append(marker_path)
        rows = int(row[count_column])
        entries.append(
            {
                "day": day,
                "rows": rows,
                "shard": f"{day}{suffix}" if rows else None,
                "marker": marker_path.name,
                "marker_sha256": _file_sha256(marker_path),
            }
        )
    manifest_body = {
        "schema_version": ORDERED_SHARD_MANIFEST_SCHEMA_VERSION,
        "artefact": output.name,
        "engine_key": engine_key,
        "input_key": input_key,
        "count_column": count_column,
        "shard_suffix": suffix,
        "entries": entries,
    }
    root = hashlib.sha256(
        json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {**manifest_body, "ordered_shard_manifest_root": root}
    manifest_path = day_cache / f"{output.name}.ordered-shards.json"
    with atomic_output(manifest_path) as temporary:
        temporary.write_text(
            json.dumps(manifest, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return manifest_path, marker_paths


def assemble_cached_output(
    day_cache: Path,
    support_rows: list[dict[str, object]],
    *,
    suffix: str,
    count_column: str,
    output: Path,
    inputs: list[Path],
    notes: str,
    engine_key: str,
    input_key: str,
) -> int:
    """Assemble a full-daily route ledger from validated day shards out of core."""
    manifest_path, marker_paths = write_ordered_shard_manifest(
        day_cache,
        support_rows,
        suffix=suffix,
        count_column=count_column,
        output=output,
        engine_key=engine_key,
        input_key=input_key,
    )
    expected = sum(int(row[count_column]) for row in support_rows)
    files = [
        day_cache / f"{row['day']}{suffix}"
        for row in support_rows
        if int(row[count_column]) > 0
    ]
    if expected == 0:
        raise RuntimeError(f"no rows available for {output.name}")

    def progress(index: int, total: int, rows: int) -> None:
        if index % 180 == 0 or index == total:
            print(
                f"  assembled {output.name} [{index:,}/{total:,}] rows={rows:,}",
                flush=True,
            )

    result = assemble_parquet_shards(
        files,
        output,
        progress=progress,
        unique_keys=("day", "route_id"),
    )
    if result.rows != expected:
        raise RuntimeError(
            f"assembled {output.name} row mismatch: {result.rows:,} != {expected:,}"
        )
    stamp(
        output,
        code_sources=OUTPUT_PROVENANCE_SOURCES,
        inputs=[*inputs, manifest_path, *marker_paths],
        rows=result.rows,
        notes=(
            f"{notes}; resumable day cache {day_cache.name}; "
            f"ordered shard manifest {manifest_path.name}"
        ),
    )
    return result.rows


def publish_full_daily_frontier(support_rows: list[dict[str, object]], *, selected: list[str], day_cache: Path, inputs: list[Path], engine_key: str, input_key: str) -> int:
    """Validate complete worker closure before the existing ordered assembly publishes anything."""
    support = pd.DataFrame(support_rows)
    daily_reproduction, daily_state_coverage, daily_verified_coverage = validate_daily_support(support, selected)
    panel_rows = assemble_cached_output(day_cache, support_rows, suffix=".parquet", count_column="scored_routes", output=DAILY_PANEL, inputs=inputs, notes="full-daily strict pre-transaction V2/V3/V4 realised and public-path frontier; distinct from the construction audit", engine_key=engine_key, input_key=input_key)
    rejection_rows = assemble_cached_output(day_cache, support_rows, suffix=".rejections.parquet", count_column="rejected_routes", output=DAILY_REJECTIONS, inputs=inputs, notes="full-daily route-level exclusion and chosen-route reproduction ledger", engine_key=engine_key, input_key=input_key)
    write_panel(support, DAILY_SUPPORT, code_sources=OUTPUT_PROVENANCE_SOURCES, inputs=inputs, notes="daily V2/V3/V4 exact-state support funnel for the full estimation frontier")
    print(f"wrote full-daily frontier on {len(selected):,} calendar days: {panel_rows:,} scored and {rejection_rows:,} rejected routes; chosen-route reproduction {daily_reproduction:.2%}; chosen-state coverage {daily_state_coverage:.2%}; verified coverage {daily_verified_coverage:.2%}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--day", action="append", help="repeat for an unpublished explicit-date diagnostic"
    )
    selection.add_argument(
        "--audit-calendar",
        action="store_true",
        help="audit one exact daily snapshot per calendar month, nearest the 15th",
    )
    selection.add_argument(
        "--daily-calendar",
        action="store_true",
        help="materialise the distinct full-daily estimation frontier after the audit passes",
    )
    parser.add_argument("--workers", type=int, help="bounded full-daily scoring processes; ignored by serial audit and explicit-day modes")
    args = parser.parse_args()
    require_node_d_release(routes=True)
    require_current_artifacts(
        [TOKEN_DECIMALS], consumer="transaction-state frontier"
    )
    try:
        selected = select_days(
            available_days(nonempty=args.audit_calendar),
            explicit=args.day,
            audit_calendar=args.audit_calendar,
            daily_calendar=args.daily_calendar,
        )
    except ValueError as error:
        print(f"error: {error}")
        return 1
    vehicles = candidate_vehicles()
    selected_set = set(selected)
    daily_mode = bool(args.daily_calendar)
    try:
        if daily_mode:
            target_release = require_full_daily_target_release(selected)
        elif args.audit_calendar:
            target_release = resolve_target_release("audit", expected_days=selected)
        else:
            target_release = resolve_target_release("audit")
            if not selected_set.issubset(target_release.calendar):
                target_release = resolve_target_release("daily")
            if not selected_set.issubset(target_release.calendar):
                raise ValueError("explicit frontier dates are absent from every certified target release")
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: certified transaction-target release gate failed: {error}")
        return 1
    if daily_mode:
        expected_audit_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
        try:
            audit_reproduction, audit_state_coverage, audit_verified_coverage = (
                require_frontier_audit_gate(expected_audit_days)
            )
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            print(f"error: full-daily frontier audit gate failed: {error}")
            return 1
        print(
            f"current frontier audit gate passed on {len(expected_audit_days):,} dates "
            f"with {audit_reproduction:.2%} chosen-route reproduction and "
            f"{audit_state_coverage:.2%} chosen-state coverage; "
            f"verified coverage {audit_verified_coverage:.2%}",
            flush=True,
        )
    frames: list[pd.DataFrame] = []
    rejection_frames: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    inputs = [
        UNIFIED,
        UNIFIED_QUALITY_PANEL,
        TOKEN_DECIMALS,
        V4_STATIC_QUARANTINE_PANEL,
        target_release.pointer_path,
        target_release.manifest_path,
        target_release.day_markers[0].parents[1],
        *target_release.day_markers,
    ]
    frontier_engine_key, frontier_input_key, frontier_generation = (
        frontier_cache_identity(
            inputs, source_identity=target_release.content_identity_sha256
        )
    )
    day_cache = (
        DATA_DIR
        / "empirical"
        / "_transaction_state_frontier_day_cache"
        / f"engine_{frontier_generation}"
    )
    cached_days = {
        day: (
            load_cached_day_support(
                day_cache,
                day,
                engine_key=frontier_engine_key,
                input_key=frontier_input_key,
            )
            if daily_mode
            else load_cached_day(
                day_cache,
                day,
                engine_key=frontier_engine_key,
                input_key=frontier_input_key,
            )
        )
        for day in selected
    }
    uncached_days = [day for day in selected if cached_days[day] is None]
    replay_inputs = [
        target_release.pointer_path,
        target_release.manifest_path,
        TOKEN_DECIMALS,
        V4_STATIC_QUARANTINE_PANEL,
    ]
    checkpoint_engine_key = replay_checkpoint_engine_key(
        replay_inputs, source_identity=target_release.content_identity_sha256
    )
    checkpoint_dir = (
        DATA_DIR
        / "empirical"
        / "_tick_replay_checkpoints"
        / f"engine_v{REPLAY_CHECKPOINT_SCHEMA_VERSION}_{checkpoint_engine_key[:12]}"
    )
    if daily_mode:
        try:
            workers = daily_worker_count(args.workers)
            if args.workers is not None and workers != args.workers:
                print(f"capped full-daily workers at {workers:,} for this host's CPU/memory budget", flush=True)
            target_weights = target_day_scoring_weights(target_release)
            scoring_weights = {day: 1 if cached_days[day] is not None else target_weights[day] for day in selected}
            segments = plan_daily_segments(selected, workers=workers, checkpoint_dir=checkpoint_dir, scoring_weights=scoring_weights)
            if uncached_days:
                mapped_days, created_checkpoints = materialize_segment_checkpoints(segments, checkpoint_dir=checkpoint_dir, checkpoint_engine_key=checkpoint_engine_key, target_release=target_release, market_state=None, workers=workers)
                print(f"full-daily checkpoint phase: {mapped_days:,} historical days mapped; {created_checkpoints:,} checkpoints created; {workers:,} bounded workers", flush=True)
                print("full-daily segment loads: " + ", ".join(f"{segment.days[0]}..{segment.days[-1]}={segment.scoring_weight:,}" for segment in segments), flush=True)
                support_rows = run_daily_segments(segments, workers=workers, checkpoint_engine_key=checkpoint_engine_key, day_cache=day_cache, frontier_engine_key=frontier_engine_key, frontier_input_key=frontier_input_key, vehicles=vehicles, target_release=target_release, market_state=None, cp_market_state=None)
            else:
                support_rows = [cached_days[day] for day in selected if cached_days[day] is not None]
            return publish_full_daily_frontier(support_rows, selected=selected, day_cache=day_cache, inputs=inputs, engine_key=frontier_engine_key, input_key=frontier_input_key)
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            print(f"error: full-daily frontier scoring/release failed: {error}")
            return 1
    replay_start: str | None = None
    replay: TickReplayState | None = None
    if uncached_days:
        resume_checkpoint = latest_replay_checkpoint(checkpoint_dir, uncached_days[0])
        if resume_checkpoint is not None:
            replay_start = checkpoint_day(resume_checkpoint)
            replay = load_replay_checkpoint(
                resume_checkpoint,
                engine_key=checkpoint_engine_key,
                pre_day=replay_start,
            )
            print(f"loaded replay checkpoint before {replay_start}", flush=True)
        else:
            replay = TickReplayState(
                token_decimals=load_token_decimals(TOKEN_DECIMALS),
                quarantined_pools={
                    "uniswap_v4": load_v4_static_quarantine()
                },
            )
            replay_start = min(REPLAY_START, uncached_days[0])
    for day in selected:
        if replay_start is not None and day >= replay_start:
            break
        cached = cached_days[day]
        if cached is None:
            raise RuntimeError(f"uncached frontier day precedes replay start: {day}")
        frame, rejections, support = cached
        frames.append(frame)
        rejection_frames.append(rejections)
        support_rows.append(support)
    calendar = (
        pd.date_range(
            pd.to_datetime(replay_start, format="%Y%m%d"),
            pd.to_datetime(max(selected), format="%Y%m%d"),
            freq="D",
        )
        if replay_start is not None
        else []
    )
    for index, observed in enumerate(calendar, 1):
        assert replay is not None
        day = observed.strftime("%Y%m%d")
        checkpoint = checkpoint_dir / f"pre_{day}.pkl"
        if replay_checkpoint_due(index=index):
            if not checkpoint.exists():
                save_replay_checkpoint(
                    checkpoint,
                    replay,
                    engine_key=checkpoint_engine_key,
                    pre_day=day,
                )
                print(f"wrote replay checkpoint before {day}", flush=True)
        if day in selected_set:
            cached = cached_days[day]
            if cached is not None:
                frame, rejections, support = cached
                warm_tick_day(None, day, replay)
                cache_note = " [cached]"
            else:
                events = load_tick_day_events(None, day)
                v2_replay = load_v2_replay_day(None, day)
                frame, rejections, support = score_day(
                    day, events, replay, v2_replay, vehicles, target_release
                )
                write_cached_day(
                    day_cache,
                    day,
                    frame,
                    rejections,
                    support,
                    engine_key=frontier_engine_key,
                    input_key=frontier_input_key,
                )
                cache_note = ""
            frames.append(frame)
            rejection_frames.append(rejections)
            support_rows.append(support)
            print(
                f"{day}: {support['all_exact_two_leg_routes']:,} exact two-leg; "
                f"{support['exact_venue_two_leg_routes']:,} V2/V3/V4; "
                f"{support['scored_routes']:,} exact-state scored{cache_note}",
                flush=True,
            )
        else:
            warm_tick_day(None, day, replay)
        if index % 180 == 0:
            print(f"replayed through {day} ({index:,}/{len(calendar):,} days)", flush=True)
    support = pd.DataFrame(support_rows)
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    rejections = (
        pd.concat(rejection_frames, ignore_index=True)
        if rejection_frames
        else pd.DataFrame()
    )
    if panel.empty:
        print("no transaction-state frontier routes survived validation")
        return 1
    if args.day:
        print(
            f"explicit diagnostic complete: {len(selected):,} day(s), "
            f"{len(panel):,} scored and {len(rejections):,} rejected routes; "
            "canonical outputs unchanged"
        )
        return 0

    summary = summarise(panel)
    write_panel(
        panel,
        AUDIT_PANEL,
        code_sources=OUTPUT_PROVENANCE_SOURCES,
        inputs=inputs,
        notes=f"{len(selected)}-date construction audit of the strict pre-transaction V2/V3/V4 frontier",
    )
    write_panel(
        rejections,
        AUDIT_REJECTIONS,
        code_sources=OUTPUT_PROVENANCE_SOURCES,
        inputs=inputs,
        notes=f"{len(selected)}-date route-level exclusion and chosen-route reproduction ledger",
    )
    write_exhibit(
        summary,
        AUDIT_SUMMARY,
        code_sources=OUTPUT_PROVENANCE_SOURCES,
        inputs=[AUDIT_PANEL],
        notes="construction-audit route and dollar magnitudes; not an estimation sample",
    )
    write_exhibit(
        support,
        AUDIT_SUPPORT,
        code_sources=OUTPUT_PROVENANCE_SOURCES,
        inputs=inputs,
        notes=f"{len(selected)}-date V2/V3/V4 exact-state support and chosen-route reproduction diagnostics",
    )
    coherent_available = int(support["within_20pct_chosen_quote_available"].sum())
    coherent_mismatches = int(
        support["within_20pct_chosen_output_mismatch"].sum()
    )
    reproduction = chosen_reproduction_share(
        coherent_available, coherent_mismatches
    )
    print(
        f"chosen-route reproduction: {reproduction:.2%} "
        f"({coherent_available - coherent_mismatches:,}/{coherent_available:,})"
    )
    if reproduction < CHOSEN_REPRODUCTION_DASHBOARD_REFERENCE:
        print(
            "DIAGNOSTIC: chosen-route reproduction is below the former "
            f"{CHOSEN_REPRODUCTION_DASHBOARD_REFERENCE:.0%} dashboard reference; "
            "inspect the error distribution and concentration before promotion"
        )
    pooled = summary[
        (summary["day"] == "pooled") & (summary["sample"] == "within_20pct")
    ].iloc[0]
    print(
        f"pooled coherent: {int(pooled.routes):,} routes; public regret >1 bp "
        f"{100 * pooled.public_path_regret_over_1bps_share:.2f}%, >10 bp "
        f"{100 * pooled.public_path_regret_over_10bps_share:.2f}%; "
        f"median {pooled.public_path_regret_median_bps:.2f} bps; "
        f"aggregate gain ${pooled.aggregate_public_gain_usd:,.2f}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="transaction-state frontier"):
        raise SystemExit(main())
