#!/usr/bin/env python3
"""Bound the scientific effect of venue-state gaps on clean realised vehicle routes.

This is a named node-D defect diagnosis. It consumes the canonical realised-route extractor instead of defining another route unit. Counts are primary. Value weights are component source/sink notional and are reported on both full and strict 20-percent flow-coherence support. Canonical endpoint cycles are excluded by the extractor. No current input identifies sandwich trades or general MEV, so the output must not describe itself as MEV-clean.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import as_completed
from pathlib import Path
from typing import Iterable

import pandas as pd

from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.fetch.raw import (
    RawFetchInvariantError,
    require_committed_source_day_stream,
    verified_source_day_rows,
    write_json,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import ROUTE_COLUMNS, extract_realised_routes
from ddvc.runtime import bounded_workers, interruptible_process_pool


TARGET_SOURCES = ("balancer", "curve")
STATE_QUALITY = DATA_DIR / "processed" / "market_state_quality.parquet"
UNIFIED_QUALITY = DATA_DIR / "processed" / "unified_route_quality.parquet"
DEFAULT_OUTPUT = OUTPUT_DIR / "exhibits" / "state_coverage_materiality.json"
STRICT_VALUE_SUPPORT = "within_20pct"
MAX_COST_BPS = 500.0
KEYS = ["tx_hash", "component_id"]


def _tuple(values: Iterable[object]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        if value is None:
            continue
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text:
            normalized.add(text)
    return tuple(sorted(normalized))


def _pool_identity(source: str, row: dict[str, object]) -> tuple[str, int, str] | None:
    if source == "curve":
        tx = str(row.get("hash") or "").lower()
        try:
            log_index = int(row.get("logIndex"))
        except (TypeError, ValueError):
            return None
        pool = str((row.get("pool") or {}).get("id") or "").lower()  # type: ignore[union-attr]
    elif source == "balancer":
        tx = str(row.get("tx") or "").lower()
        suffix = str(row.get("id") or "")[len(tx) :]
        try:
            log_index = int(suffix)
        except ValueError:
            return None
        pool = str((row.get("poolId") or {}).get("id") or "").lower()  # type: ignore[union-attr]
    else:
        raise ValueError(f"unsupported pool-map source: {source}")
    return (tx, log_index, pool) if tx and pool else None


def _raw_swap_path(data_root: Path, source: str, day: str) -> Path:
    return data_root / "raw" / "thegraph" / source / f"{source}_swaps_{day}.jsonl.gz"


def _retain_pool_identity(
    mapping: dict[tuple[str, int], str], source: str, row: dict[str, object]
) -> None:
    resolved = _pool_identity(source, row)
    if resolved is None:
        return
    tx, log_index, pool = resolved
    key = (tx, log_index)
    prior = mapping.get(key)
    if prior is not None and prior != pool:
        raise ValueError(f"conflicting {source} pool identity for {key}")
    mapping[key] = pool


def raw_pool_map(
    data_root: Path, source: str, day: str
) -> tuple[dict[tuple[str, int], str], str, dict[str, object]]:
    """Read a marker-bound provider partition or label an unreleased diagnostic."""
    parsed_day = dt.datetime.strptime(day, "%Y%m%d").date()
    path = _raw_swap_path(data_root, source, day)
    mapping: dict[tuple[str, int], str] = {}
    try:
        with verified_source_day_rows(
            source, "swaps", parsed_day, data_root=data_root
        ) as rows:
            for row in rows:
                _retain_pool_identity(mapping, source, row)
        verified_path = require_committed_source_day_stream(
            source, "swaps", parsed_day, data_root=data_root
        )
        digest = hashlib.sha256()
        with gzip.open(verified_path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return mapping, digest.hexdigest(), {"status": "committed_source_day"}
    except RawFetchInvariantError as exc:
        if not path.is_file():
            raise FileNotFoundError(path) from exc
        diagnostic_reason = type(exc).__name__
        mapping.clear()
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for raw in handle:
            digest.update(raw)
            if not raw.strip():
                continue
            _retain_pool_identity(mapping, source, json.loads(raw))
    return mapping, digest.hexdigest(), {
        "status": "diagnostic_unreleased",
        "reason": diagnostic_reason,
    }


def allocate_pool_cells(
    selected_legs: pd.DataFrame,
    components: pd.DataFrame,
    *,
    source: str,
) -> list[dict[str, object]]:
    pool_legs = selected_legs.groupby(KEYS + ["pool"], as_index=False).size()
    totals = pool_legs.groupby(KEYS)["size"].transform("sum")
    pool_legs["allocation"] = pool_legs["size"] / totals
    allocated = pool_legs.merge(
        components[KEYS + ["component_notional_usd", STRICT_VALUE_SUPPORT]],
        on=KEYS,
        how="inner",
    )
    cells: list[dict[str, object]] = []
    for pool, group in allocated.groupby("pool", sort=False):
        strict = group[STRICT_VALUE_SUPPORT].fillna(False).astype(bool)
        cells.append(
            {
                "source": source,
                "pool": str(pool),
                "component_count_allocation": float(group["allocation"].sum()),
                "notional_usd_allocation": float(
                    (group["allocation"] * group["component_notional_usd"]).sum()
                ),
                "strict_component_count_allocation": float(
                    group.loc[strict, "allocation"].sum()
                ),
                "strict_notional_usd_allocation": float(
                    (
                        group.loc[strict, "allocation"]
                        * group.loc[strict, "component_notional_usd"]
                    ).sum()
                ),
            }
        )
    return cells


def _aggregate(mask: pd.Series, components: pd.DataFrame) -> dict[str, float | int]:
    selected = components.loc[mask]
    strict = selected[STRICT_VALUE_SUPPORT].fillna(False).astype(bool)
    return {
        "components": int(len(selected)),
        "notional_usd": float(selected["component_notional_usd"].sum()),
        "strict_components": int(strict.sum()),
        "strict_notional_usd": float(
            selected.loc[strict, "component_notional_usd"].sum()
        ),
    }


def reduce_day(
    path: Path,
    *,
    data_root: Path,
    state_gap_days: dict[str, frozenset[str]],
    stress_days: frozenset[str],
    include_pool_map: bool = True,
) -> dict[str, object]:
    """Reduce one unified day with the existing canonical realised-route owner."""
    day = path.stem
    legs = pd.read_parquet(path, columns=ROUTE_COLUMNS)
    routes = extract_realised_routes(legs, require_positive_value=False)
    if routes.empty:
        return {
            "day": day,
            "year": int(day[:4]),
            "stress": day in stress_days,
            "cells": [],
            "candidate_cells": [],
            "pool_cells": [],
            "raw_pool_hashes": {},
            "raw_pool_bindings": {},
            "pool_mapping_missing_legs": {},
        }
    routes["component_notional_usd"] = (
        pd.to_numeric(routes["source_usd"], errors="coerce")
        + pd.to_numeric(routes["sink_usd"], errors="coerce")
    ) / 2
    components = routes.drop_duplicates(KEYS).copy()
    component_keys = components[KEYS]
    component_legs = legs.merge(component_keys, on=KEYS, how="inner")
    venue_sets = (
        component_legs.groupby(KEYS, as_index=False)["source"]
        .agg(_tuple)
        .rename(columns={"source": "venue_set"})
    )
    components = components.merge(venue_sets, on=KEYS, how="inner")
    all_mask = pd.Series(True, index=components.index)
    cells = [{"scope": "all", **_aggregate(all_mask, components)}]
    for source in TARGET_SOURCES:
        source_mask = components["venue_set"].map(lambda venues: source in venues)
        gap_active = day in state_gap_days.get(source, frozenset())
        cells.append(
            {
                "scope": source,
                "state_gap_active": gap_active,
                **_aggregate(source_mask & gap_active, components),
            }
        )
    affected = components["venue_set"].map(
        lambda venues: any(
            source in venues and day in state_gap_days.get(source, frozenset())
            for source in TARGET_SOURCES
        )
    )
    cells.append({"scope": "any_state_gap", **_aggregate(affected, components)})

    route_venues = routes.merge(venue_sets, on=KEYS, how="inner")
    candidate_cells: list[dict[str, object]] = []
    for address, symbol in VEHICLE_CANDIDATES.items():
        selected = route_venues[route_venues["vehicle"].eq(address)]
        if selected.empty:
            continue
        candidate_components = selected.drop_duplicates(KEYS)
        candidate_affected = candidate_components["venue_set"].map(
            lambda venues: any(
                source in venues and day in state_gap_days.get(source, frozenset())
                for source in TARGET_SOURCES
            )
        )
        candidate_cells.append(
            {
                "candidate": symbol,
                "candidate_address": address,
                **_aggregate(candidate_affected, candidate_components),
            }
        )

    pool_cells: list[dict[str, object]] = []
    raw_pool_hashes: dict[str, str] = {}
    raw_pool_bindings: dict[str, dict[str, object]] = {}
    pool_mapping_missing_legs: dict[str, int] = {}
    if include_pool_map:
        for source in TARGET_SOURCES:
            if day not in state_gap_days.get(source, frozenset()):
                continue
            selected_legs = component_legs[component_legs["source"].eq(source)].copy()
            if selected_legs.empty:
                continue
            mapping, logical_hash, binding = raw_pool_map(
                data_root, source, day
            )
            raw_pool_hashes[source] = logical_hash
            raw_pool_bindings[source] = binding
            selected_legs["pool"] = [
                mapping.get((str(tx).lower(), int(log_index)))
                for tx, log_index in zip(
                    selected_legs["tx_hash"], selected_legs["log_index"], strict=True
                )
            ]
            pool_mapping_missing_legs[source] = int(selected_legs["pool"].isna().sum())
            selected_legs = selected_legs.dropna(subset=["pool"])
            pool_cells.extend(
                allocate_pool_cells(selected_legs, components, source=source)
            )
    return {
        "day": day,
        "year": int(day[:4]),
        "stress": day in stress_days,
        "cells": cells,
        "candidate_cells": candidate_cells,
        "pool_cells": pool_cells,
        "raw_pool_hashes": raw_pool_hashes,
        "raw_pool_bindings": raw_pool_bindings,
        "pool_mapping_missing_legs": pool_mapping_missing_legs,
    }


def installed_generation_identity(
    quality_path: Path, unified_dir: Path
) -> tuple[dict[str, object], frozenset[str]]:
    quality = pd.read_parquet(quality_path).sort_values("day", kind="stable")
    if quality.empty or not quality["passed"].all() or quality["engine"].nunique() != 1:
        raise ValueError("unified quality perimeter is empty, mixed, or failed")
    fields = [
        "day",
        "engine",
        "input_fingerprint",
        "output_rows",
        "output_bytes",
        "output_mtime_ns",
        "passed",
    ]
    records = quality[fields].to_dict("records")
    for row in records:
        path = unified_dir / f"{row['day']}.parquet"
        stat = path.stat()
        if stat.st_size != int(row["output_bytes"]) or stat.st_mtime_ns != int(
            row["output_mtime_ns"]
        ):
            raise ValueError(f"unified partition changed after quality marker: {row['day']}")
    days = frozenset(quality["day"].astype(str))
    return {
        "engine": str(quality["engine"].iloc[0]),
        "days": int(len(quality)),
        "calendar_sha256": canonical_json_sha256(sorted(days)),
        "rows": int(quality["output_rows"].sum()),
        "quality_file_sha256": file_sha256(quality_path),
        "installed_generation_sha256": canonical_json_sha256(records),
    }, days


def state_gap_calendar(
    path: Path, unified_days: frozenset[str]
) -> tuple[dict[str, frozenset[str]], dict[str, object]]:
    quality = pd.read_parquet(path)
    required = {"venue", "day", "usable_rows", "passed", "engine"}
    if missing := sorted(required - set(quality.columns)):
        raise ValueError(f"state quality misses columns: {missing}")
    selected = quality[quality["venue"].isin(TARGET_SOURCES)].copy()
    selected["venue"] = selected["venue"].astype(str)
    selected["day"] = selected["day"].astype(str)
    if selected.duplicated(["venue", "day"]).any():
        raise ValueError("state quality has duplicate venue-day rows")
    expected = {
        (source, day) for source in TARGET_SOURCES for day in unified_days
    }
    observed = set(zip(selected["venue"], selected["day"], strict=True))
    if extras := sorted(observed.difference(expected)):
        raise ValueError(f"state quality has unexpected venue-days: {extras[:10]}")
    indexed = {
        (str(row.venue), str(row.day)): row
        for row in selected.itertuples(index=False)
    }
    gaps_mutable = {source: set() for source in TARGET_SOURCES}
    reasons = {source: Counter() for source in TARGET_SOURCES}
    for source, day in sorted(expected):
        row = indexed.get((source, day))
        if row is None:
            gaps_mutable[source].add(day)
            reasons[source]["missing_quality_row"] += 1
            continue
        passed = getattr(row, "passed")
        if pd.isna(passed) or not bool(passed):
            gaps_mutable[source].add(day)
            reasons[source]["not_passed"] += 1
        usable = pd.to_numeric(pd.Series([getattr(row, "usable_rows")]), errors="coerce").iloc[0]
        if pd.isna(usable) or float(usable) <= 0:
            gaps_mutable[source].add(day)
            reasons[source]["no_usable_rows"] += 1
    gaps = {source: frozenset(days) for source, days in gaps_mutable.items()}
    records = selected.sort_values(["venue", "day"], kind="stable").to_dict("records")
    return gaps, {
        "file_sha256": file_sha256(path),
        "generation_sha256": canonical_json_sha256(
            {"expected_days": sorted(unified_days), "records": records}
        ),
        "engines": sorted(selected["engine"].astype(str).unique()),
        "gap_days": {source: len(days) for source, days in gaps.items()},
        "gap_reasons": {
            source: dict(sorted(counts.items())) for source, counts in reasons.items()
        },
    }


def stress_calendar(path: Path | None) -> tuple[frozenset[str], dict[str, object]]:
    if path is None:
        return frozenset(), {"status": "unavailable"}
    panel = pd.read_parquet(path, columns=["date", "weth_price"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.dropna().drop_duplicates("date").sort_values("date")
    panel["return"] = panel["weth_price"].astype(float).map(math.log).diff()
    panel.loc[panel["return"].abs().gt(0.5), "return"] = float("nan")
    days = frozenset(panel.loc[panel["return"].le(-0.08), "date"].dt.strftime("%Y%m%d"))
    return days, {
        "status": "available",
        "file_sha256": file_sha256(path),
        "definition": "exact daily log WETH return <= -8%; absolute returns above 50% treated unsupported",
        "days": len(days),
    }


def _sum_cells(results: list[dict[str, object]], field: str) -> list[dict[str, object]]:
    totals: dict[tuple[object, ...], Counter[str]] = {}
    key_fields = (
        ("scope",) if field == "cells" else ("candidate", "candidate_address")
    )
    for result in results:
        for cell in result[field]:  # type: ignore[index]
            key = tuple(cell.get(name) for name in key_fields)
            counter = totals.setdefault(key, Counter())
            for name in (
                "components",
                "notional_usd",
                "strict_components",
                "strict_notional_usd",
            ):
                counter[name] += cell.get(name, 0)
    return [
        {**dict(zip(key_fields, key, strict=True)), **dict(values)}
        for key, values in sorted(totals.items())
    ]


def year_stress_cells(results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = [
        {"year": row["year"], "stress": row["stress"], **cell}
        for row in results
        for cell in row["cells"]  # type: ignore[index]
    ]
    if not rows:
        return []
    output: list[dict[str, object]] = []
    for (year, stress, scope), group in pd.DataFrame(rows).groupby(
        ["year", "stress", "scope"], sort=True
    ):
        output.append(
            {
                "year": int(year),
                "stress": bool(stress),
                "scope": str(scope),
                **{
                    name: float(group[name].sum())
                    for name in (
                        "components",
                        "notional_usd",
                        "strict_components",
                        "strict_notional_usd",
                    )
                },
            }
        )
    return output


def omission_bounds(summary: list[dict[str, object]]) -> dict[str, object]:
    by_scope = {str(row["scope"]): row for row in summary}
    total = by_scope["all"]
    missing = by_scope["any_state_gap"]
    shares = {
        "count": float(missing["components"]) / float(total["components"]),
        "strict_value": float(missing["strict_notional_usd"])
        / float(total["strict_notional_usd"]),
    }
    return {
        "missing_mass": shares,
        "bounded_mean_cost_bps": {
            weighting: {
                "assumed_outcome_support_bps": [0.0, MAX_COST_BPS],
                "identification_interval_width_bps": share * MAX_COST_BPS,
                "formula": "market mean in [(1-s)*covered_mean, (1-s)*covered_mean+s*500]",
            }
            for weighting, share in shares.items()
        },
        "rent_regression": {
            "assumption_free_bound": None,
            "reason": "A regression coefficient is unbounded when omitted route strata can differ arbitrarily in outcomes and covariates.",
        },
        "best_route_direction": "Adding missing venue states weakly lowers minimum executable cost, but its effect on vehicle advantage is sign-indeterminate because the omitted venue can improve either the direct or vehicle path.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_DIR)
    parser.add_argument("--state-quality", type=Path, default=STATE_QUALITY)
    parser.add_argument("--unified-quality", type=Path, default=UNIFIED_QUALITY)
    parser.add_argument("--stress-panel", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-pool-map", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    unified_dir = args.data_root / "unified"
    generation, unified_days = installed_generation_identity(
        args.unified_quality, unified_dir
    )
    gaps, state_generation = state_gap_calendar(args.state_quality, unified_days)
    stress_days, stress_generation = stress_calendar(args.stress_panel)
    files = sorted(unified_dir.glob("[0-9]" * 8 + ".parquet"))
    if frozenset(path.stem for path in files) != unified_days:
        raise ValueError("unified file calendar disagrees with its quality perimeter")
    if args.limit is not None:
        files = files[: args.limit]
    workers = bounded_workers(args.workers)
    results: list[dict[str, object]] = []
    with interruptible_process_pool(workers) as pool:
        futures = {
            pool.submit(
                reduce_day,
                path,
                data_root=args.data_root,
                state_gap_days=gaps,
                stress_days=stress_days,
                include_pool_map=not args.no_pool_map,
            ): path
            for path in files
        }
        for index, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if index % 250 == 0 or index == len(files):
                print(f"materiality [{index:,}/{len(files):,}]", flush=True)
    results.sort(key=lambda row: str(row["day"]))
    summary = _sum_cells(results, "cells")
    candidates = _sum_cells(results, "candidate_cells")
    by_year_stress = year_stress_cells(results)
    pool_totals: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for result in results:
        for cell in result["pool_cells"]:  # type: ignore[index]
            counter = pool_totals[(str(cell["source"]), str(cell["pool"]))]
            for name in (
                "component_count_allocation",
                "notional_usd_allocation",
                "strict_component_count_allocation",
                "strict_notional_usd_allocation",
            ):
                counter[name] += float(cell[name])
    pools_by_source: dict[str, list[dict[str, object]]] = {}
    for source in TARGET_SOURCES:
        rows = [
            {"pool": pool, **dict(values)}
            for (observed_source, pool), values in pool_totals.items()
            if observed_source == source
        ]
        rows.sort(key=lambda row: float(row["strict_notional_usd_allocation"]), reverse=True)
        total = sum(float(row["strict_notional_usd_allocation"]) for row in rows)
        for row in rows:
            row["strict_value_share"] = (
                float(row["strict_notional_usd_allocation"]) / total if total else None
            )
        pools_by_source[source] = rows[:20]
    raw_hashes = [
        {"day": result["day"], "source": source, "logical_sha256": digest}
        for result in results
        for source, digest in result["raw_pool_hashes"].items()  # type: ignore[union-attr]
    ]
    raw_bindings = [
        {"day": result["day"], "source": source, **binding}
        for result in results
        for source, binding in result["raw_pool_bindings"].items()  # type: ignore[union-attr]
    ]
    unbound_pool_partitions = sum(
        item["status"] != "committed_source_day" for item in raw_bindings
    )
    missing_pool_legs = Counter()
    for result in results:
        missing_pool_legs.update(result["pool_mapping_missing_legs"])  # type: ignore[arg-type]
    payload = {
        "status": "diagnostic_provisional",
        "completion_blockers": [
            *(["limited_calendar"] if args.limit is not None else []),
            *(
                ["unreleased_raw_pool_partitions"]
                if unbound_pool_partitions
                else []
            ),
            "state_generation_not_yet_node_d_released",
        ],
        "semantics": {
            "unit": "one topology-valid coherent non-cyclic transaction component carrying at least one intermediary; components with multiple intermediaries count once in component totals and once per named candidate only in candidate cells",
            "count_weighting": "one per clean component",
            "value_weighting": "mean of total component source-side and sink-side USD; never summed leg or provider volume",
            "strict_value_support": "source, sink and every intermediary flow reconcile within 20 percent",
            "native_identity": "native ETH canonicalized to WETH by ddvc.realised",
            "round_trips": "directed cycles and identical endpoint routes excluded",
            "wash_mev": "cycle exclusion is an atomic-arbitrage proxy only; no current input identifies sandwich trades, wash trades generally or general MEV",
            "dominance_route_evidence": "observed route topology remains covered even when state is absent",
            "counterfactual_state_evidence": "best-route and executable-cost coverage is absent on affected source-days",
            "pool_allocation": "within a component-source, count and notional are allocated across touched pools in proportion to that pool's leg count; allocations preserve component totals",
        },
        "inputs": {
            "unified": generation,
            "state_quality": state_generation,
            "stress": stress_generation,
            "pool_raw_logical_generation_sha256": canonical_json_sha256(raw_hashes),
            "pool_raw_partitions": len(raw_hashes),
            "pool_raw_binding_sha256": canonical_json_sha256(raw_bindings),
            "pool_raw_unbound_partitions": unbound_pool_partitions,
        },
        "summary": summary,
        "candidate_summary": candidates,
        "by_year_stress": by_year_stress,
        "top_pools": pools_by_source,
        "pool_mapping_missing_legs": dict(missing_pool_legs),
        "bounds": omission_bounds(summary),
    }
    if args.limit is None:
        write_json(args.output, payload)
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
