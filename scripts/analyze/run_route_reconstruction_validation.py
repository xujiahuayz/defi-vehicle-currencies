#!/usr/bin/env python3
"""Measure route consequences of exact-chain swap correction ledgers."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path
import pickle
import time

import pandas as pd

from ddvc.analysis.route_reconstruction_validation import (
    AUDITED_VENUES,
    decomposition_consequence_rows,
    full_day_audit_days,
    stable_share_rows,
    summarize_event_reconciliation,
    summarize_release_boundary,
    swap_action_transactions,
    validate_route_day,
)
from ddvc.paths import OUTPUT_DIR, PRIMARY_REPO_ROOT
from ddvc.runtime import atomic_output, bounded_workers


DEFAULT_OUTPUT = (
    OUTPUT_DIR / "exhibits" / "route_reconstruction_exact_chain_validation.jsonl"
)


def _write_jsonl(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        frame.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )


def _checkpoint_path(checkpoint_dir: Path, day: str) -> Path:
    return checkpoint_dir / f"{day}.pkl"


def _read_checkpoint(checkpoint_dir: Path, day: str) -> dict[str, object] | None:
    path = _checkpoint_path(checkpoint_dir, day)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        result = pickle.load(handle)
    if not isinstance(result, dict) or result.get("day") != day:
        raise ValueError(f"invalid route-validation checkpoint: {path}")
    return result


def _write_checkpoint(
    checkpoint_dir: Path,
    result: dict[str, object],
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(checkpoint_dir, str(result["day"]))
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary, path)


def _pooled_assignment_rows(results: list[dict[str, object]]) -> list[dict]:
    daily = pd.DataFrame(
        [row for result in results for row in result["assignments"]]
    )
    pooled = (
        daily.groupby("dimension", as_index=False, sort=True)
        .agg(
            affected_transactions=("affected_transactions", "sum"),
            linked_transactions=("linked_transactions", "sum"),
            unchanged_transactions=("unchanged_transactions", "sum"),
            changed_transactions=("changed_transactions", "sum"),
        )
    )
    pooled["unchanged_share"] = (
        pooled["unchanged_transactions"] / pooled["linked_transactions"]
    )
    return pooled.to_dict("records")


def run(
    *,
    data_root: Path,
    output: Path,
    workers: int,
    checkpoint_dir: Path | None = None,
) -> pd.DataFrame:
    started = time.monotonic()
    raw_root = data_root / "raw" / "thegraph"
    coverage = full_day_audit_days(raw_root)
    event_rows = summarize_event_reconciliation(raw_root)
    release_boundary = summarize_release_boundary(data_root)
    union_days = sorted(set().union(*coverage.values()))
    action_days = [
        day
        for day in union_days
        if swap_action_transactions(raw_root, day)
    ]
    iso_days = [f"{day[:4]}-{day[4:6]}-{day[6:]}" for day in action_days]
    selected_workers = bounded_workers(workers)
    route_results: list[dict[str, object]] = []
    pending_days = []
    for day in iso_days:
        checkpoint = (
            _read_checkpoint(checkpoint_dir, day)
            if checkpoint_dir is not None
            else None
        )
        if checkpoint is None:
            pending_days.append(day)
        else:
            route_results.append(checkpoint)
    if route_results:
        print(
            f"  resumed {len(route_results):,}/{len(iso_days):,} dates from checkpoints",
            flush=True,
        )
    if selected_workers == 1:
        for day in pending_days:
            result = validate_route_day(str(data_root), day)
            route_results.append(result)
            if checkpoint_dir is not None:
                _write_checkpoint(checkpoint_dir, result)
            print(
                f"  reconstructed {len(route_results):,}/{len(iso_days):,} dates",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=selected_workers) as pool:
            futures = {
                pool.submit(validate_route_day, str(data_root), day): day
                for day in pending_days
            }
            for future in as_completed(futures):
                result = future.result()
                route_results.append(result)
                if checkpoint_dir is not None:
                    _write_checkpoint(checkpoint_dir, result)
                print(
                    f"  reconstructed {len(route_results):,}/{len(iso_days):,} dates",
                    flush=True,
                )
    route_results.sort(key=lambda row: str(row["day"]))

    assignment_rows = _pooled_assignment_rows(route_results)
    share_rows = stable_share_rows(
        [row["raw_mass"] for row in route_results],
        [row["corrected_mass"] for row in route_results],
        dates=len(route_results),
    )
    raw_choices = pd.concat(
        [
            row["raw_choices"]
            for row in route_results
            if row["raw_choices"] is not None
        ],
        ignore_index=True,
    )
    corrected_choices = pd.concat(
        [
            row["corrected_choices"]
            for row in route_results
            if row["corrected_choices"] is not None
        ],
        ignore_index=True,
    )
    decomposition_rows = decomposition_consequence_rows(
        raw_choices,
        corrected_choices,
    )
    elapsed = time.monotonic() - started
    records: list[dict[str, object]] = []
    records.extend({"record_type": "event_reconciliation", **row} for row in event_rows)
    records.extend({"record_type": "route_assignment", **row} for row in assignment_rows)
    records.extend({"record_type": "stable_share", **row} for row in share_rows)
    records.extend({"record_type": "sampled_decomposition", **row} for row in decomposition_rows)
    records.append({"record_type": "release_boundary", **release_boundary})
    records.append(
        {
            "record_type": "support",
            "audited_venue_days": sum(len(days) for days in coverage.values()),
            "audited_union_days": len(union_days),
            "route_reconstruction_days": len(route_results),
            "affected_swap_transactions": sum(
                int(row["affected_transactions"]) for row in route_results
            ),
            "raw_route_rows": sum(int(row["raw_rows"]) for row in route_results),
            "corrected_route_rows": sum(
                int(row["corrected_rows"]) for row in route_results
            ),
            "runtime_seconds": elapsed,
            "audited_venues": "|".join(AUDITED_VENUES),
            "route_scope": "full_day_ledgers_with_at_least_one_swap_action",
            "decomposition_scope": "common_january_june_month_days_in_2024_and_2026",
        }
    )
    frame = pd.DataFrame(records)
    _write_jsonl(frame, output)
    print(f"wrote {len(frame):,} rows to {output}")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=PRIMARY_REPO_ROOT / "data",
        help="full-data checkout's data directory",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        help="optional local directory for restartable per-date results",
    )
    args = parser.parse_args()
    run(
        data_root=args.data_root,
        output=args.output,
        workers=args.workers,
        checkpoint_dir=args.checkpoint_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
