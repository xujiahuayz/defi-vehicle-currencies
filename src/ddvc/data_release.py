"""Executable node-D release gate for every analysis-panel builder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source
from ddvc.reconstruct import (
    DEX_FAMILY,
    RECONSTRUCTION_ENGINE,
    UNIFIED_QUALITY_PANEL,
    active_route_sources,
    read_unified_quality,
)
from ddvc.state_data import (
    FAMILY_STREAMS,
    QUALITY_COLUMNS,
    read_cp_quality,
    read_multi_asset_quality,
    read_tick_quality,
)
from ddvc.paths import DATA_DIR
from ddvc.provenance import require_current_artifacts
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.v2_event_completeness import (
    read_v2_event_source_certificate,
    resolve_v2_event_source_release,
    validate_v2_event_source_certificate,
    validate_v2_event_source_evidence_bundle,
)
from ddvc.v4_quarantine import (
    V4_STATIC_QUARANTINE_PANEL,
    audit_v4_pool_static_conflicts,
    load_v4_static_quarantine,
)


MARKET_STATE_QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
MARKET_STATE_QUALITY_COLUMNS = [
    *QUALITY_COLUMNS,
    "cross_venue_order_conflicts",
    "v4_static_conflict_pools",
]


def audit_cross_venue_order_conflicts(
    venue_paths: Mapping[str, Iterable[str | Path]], *, sample_limit: int = 3
) -> tuple[int, list[dict[str, object]]]:
    """Count causal keys claimed by each pair of canonical tick-state venues."""
    import duckdb

    ordered = {
        venue: sorted(str(Path(path)) for path in paths)
        for venue, paths in sorted(venue_paths.items())
    }
    empty = [venue for venue, paths in ordered.items() if not paths]
    if len(ordered) < 2 or empty:
        raise ValueError(
            "cross-venue order audit requires at least two nonempty venue perimeters"
        )
    if sample_limit < 1:
        raise ValueError("cross-venue order audit sample limit must be positive")
    connection = duckdb.connect()
    collision_count = 0
    samples: list[dict[str, object]] = []
    try:
        venues = list(ordered)
        for left_index, left_venue in enumerate(venues):
            for right_venue in venues[left_index + 1 :]:
                pair_count = int(
                    connection.execute(
                        """
                        SELECT count(*)
                        FROM (
                            SELECT left_state.block_number, left_state.log_index
                            FROM read_parquet(?, union_by_name=true) AS left_state
                            INNER JOIN read_parquet(?, union_by_name=true) AS right_state
                            USING (block_number, log_index)
                            WHERE left_state.usable AND right_state.usable
                            GROUP BY left_state.block_number, left_state.log_index
                        )
                        """,
                        [ordered[left_venue], ordered[right_venue]],
                    ).fetchone()[0]
                )
                collision_count += pair_count
                remaining = sample_limit - len(samples)
                if pair_count == 0 or remaining == 0:
                    continue
                rows = connection.execute(
                    """
                    SELECT
                        left_state.block_number,
                        left_state.log_index,
                        list(DISTINCT left_state.tx_hash ORDER BY left_state.tx_hash),
                        list(DISTINCT right_state.tx_hash ORDER BY right_state.tx_hash)
                    FROM read_parquet(?, union_by_name=true) AS left_state
                    INNER JOIN read_parquet(?, union_by_name=true) AS right_state
                    USING (block_number, log_index)
                    WHERE left_state.usable AND right_state.usable
                    GROUP BY left_state.block_number, left_state.log_index
                    ORDER BY left_state.block_number, left_state.log_index
                    LIMIT ?
                    """,
                    [ordered[left_venue], ordered[right_venue], remaining],
                ).fetchall()
                samples.extend(
                    {
                        "block_number": int(block_number),
                        "log_index": int(log_index),
                        "venues": [left_venue, right_venue],
                        "transaction_hashes": sorted({*left_hashes, *right_hashes}),
                    }
                    for block_number, log_index, left_hashes, right_hashes in rows
                )
    finally:
        connection.close()
    return collision_count, samples


def _exact_key_gate(
    *,
    label: str,
    actual: Iterable[tuple[str, ...]],
    expected: Iterable[tuple[str, ...]],
) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    if actual_set == expected_set:
        return
    missing = sorted(expected_set - actual_set)[:3]
    extra = sorted(actual_set - expected_set)[:3]
    raise RuntimeError(
        f"node D has not released {label}: missing={missing}, extra={extra}"
    )


def expected_route_days() -> list[str]:
    return calendar_days(RESEARCH_SAMPLE_START, RESEARCH_SAMPLE_END)


def expected_state_keys() -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for family, venues in FAMILY_STREAMS.items():
        for venue in venues:
            start = max(
                RESEARCH_SAMPLE_START,
                get_source(venue).genesis.strftime("%Y%m%d"),
            )
            keys.extend(
                (family, venue, day)
                for day in calendar_days(start, RESEARCH_SAMPLE_END)
            )
    return keys


def require_route_release() -> None:
    if not UNIFIED_QUALITY_PANEL.exists():
        raise RuntimeError("node D has not released the full directed-route quality ledger")
    quality = pd.read_parquet(UNIFIED_QUALITY_PANEL)
    expected_days = expected_route_days()
    _exact_key_gate(
        label="the full directed-route calendar",
        actual=((str(day).zfill(8),) for day in quality["day"]),
        expected=((day,) for day in expected_days),
    )
    if quality["day"].astype(str).duplicated().any():
        raise RuntimeError("node D directed-route ledger contains duplicate days")
    if not quality["passed"].astype(bool).all():
        raise RuntimeError("node D directed-route ledger contains failed days")
    if set(quality["engine"].astype(str)) != {RECONSTRUCTION_ENGINE}:
        raise RuntimeError("node D directed-route ledger belongs to a stale engine")
    expected_venue_days = sum(
        len(active_route_sources(day, list(DEX_FAMILY))) for day in expected_days
    )
    if int(quality["expected_sources"].sum()) != expected_venue_days:
        raise RuntimeError("node D directed-route venue-day perimeter is incomplete")
    stale = [
        day
        for day in expected_days
        if read_unified_quality(day, list(DEX_FAMILY)) is None
    ]
    if stale:
        raise RuntimeError(
            f"node D directed-route release has {len(stale)} stale day(s), first={stale[0]}"
        )


def require_market_state_prerelease() -> None:
    """Require structural state integrity before dependent source certificates exist."""

    if not MARKET_STATE_QUALITY_PANEL.exists():
        raise RuntimeError("node D has not released the full market-state quality ledger")
    quality = pd.read_parquet(MARKET_STATE_QUALITY_PANEL)
    if list(quality.columns) != MARKET_STATE_QUALITY_COLUMNS:
        raise RuntimeError("node D market-state quality schema is stale")
    expected = expected_state_keys()
    actual = (
        (str(row.family), str(row.venue), str(row.day).zfill(8))
        for row in quality.itertuples(index=False)
    )
    _exact_key_gate(label="the full market-state calendar", actual=actual, expected=expected)
    if quality.duplicated(["family", "venue", "day"]).any():
        raise RuntimeError("node D market-state ledger contains duplicate partitions")
    if not quality["passed"].astype(bool).all():
        raise RuntimeError("node D market-state ledger contains failed partitions")
    conflict_counts = quality["cross_venue_order_conflicts"].astype(int)
    if conflict_counts.nunique() != 1:
        raise RuntimeError("node D market-state ledger has inconsistent global conflict counts")
    if int(conflict_counts.iloc[0]) != 0:
        raise RuntimeError("node D market-state ledger contains cross-venue block-log conflicts")
    quarantine_counts = quality["v4_static_conflict_pools"].astype(int)
    if quarantine_counts.nunique() != 1:
        raise RuntimeError("node D market-state ledger has inconsistent V4 quarantine counts")
    quarantined = load_v4_static_quarantine()
    if int(quarantine_counts.iloc[0]) != len(quarantined):
        raise RuntimeError("node D market-state ledger disagrees with the V4 quarantine")
    readers = {
        "tick": read_tick_quality,
        "constant_product": read_cp_quality,
        "multi_asset": read_multi_asset_quality,
    }
    stale = [
        (family, venue, day)
        for family, venue, day in expected
        if readers[family](DATA_DIR / "raw" / "thegraph", venue, day) is None
    ]
    if stale:
        raise RuntimeError(
            f"node D market-state release has {len(stale)} stale partition(s), first={stale[0]}"
        )


def require_market_state_release() -> None:
    """Require structural state integrity and every independent source certificate."""

    require_market_state_prerelease()
    require_v2_event_source_release()


def require_v2_event_source_release() -> None:
    """Require the current independent-chain certificate for V2 replay events."""

    try:
        release = resolve_v2_event_source_release()
        require_current_artifacts(
            list(release.artifact_paths),
            consumer="node D V2-family market-state release",
        )
        summary, exceptions, certificate = read_v2_event_source_certificate(*release.artifact_paths)
        expected_days = transaction_frontier_audit_days(UNIFIED_QUALITY_PANEL)
        validate_v2_event_source_certificate(
            summary,
            exceptions,
            certificate,
            expected_days,
        )
        validate_v2_event_source_evidence_bundle(certificate, summary=summary)
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"node D V2-family event-source certificate failed: {error}"
        ) from error


def require_node_d_release(*, routes: bool = False, market_state: bool = False) -> None:
    if not routes and not market_state:
        raise ValueError("at least one node-D contract must be required")
    if routes:
        require_route_release()
    if market_state:
        require_market_state_release()
