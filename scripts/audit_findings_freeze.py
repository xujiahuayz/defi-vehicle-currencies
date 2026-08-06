#!/usr/bin/env python3
"""Audit whether the project may leave findings work and enter prose refinement."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
from ddvc.provenance import sidecar_path, verify

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
EXTENT = ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
V4 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v4"
REFRESH = ROOT / "scripts" / "refresh_panel_dependents.py"
STATE = ROOT / "docs" / "findings-freeze.md"
GRAPH_FIELDS = ("active_node", "parent_loop", "next_edge", "prose_node")


def _manifest(path: Path) -> dict:
    sidecar = sidecar_path(path)
    return json.loads(sidecar.read_text()) if sidecar.exists() else {}


def _nonempty_v4_days() -> set[str]:
    days: set[str] = set()
    prefix = "uniswap_v4_swaps_"
    suffix = ".jsonl.gz"
    for path in V4.glob(f"{prefix}*{suffix}"):
        with gzip.open(path, "rb") as handle:
            if handle.read(1):
                days.add(path.name[len(prefix):-len(suffix)])
    return days


def parse_state_frontmatter(text: str) -> dict[str, str]:
    """Read the scalar workflow state from the document's leading frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        name, separator, value = line.partition(":")
        if separator and name.strip():
            fields[name.strip()] = value.strip()
    return {}


def _state_fields() -> dict[str, str]:
    return parse_state_frontmatter(STATE.read_text()) if STATE.exists() else {}


def graph_status(fields: dict[str, str]) -> str:
    """One-line status contract for terminal, chat and automated logs."""
    return (
        f"active={fields.get('active_node') or 'missing'}; "
        f"parent={fields.get('parent_loop') or 'missing'}; "
        f"next={fields.get('next_edge') or 'missing'}; "
        f"prose={fields.get('prose_node') or 'missing'}"
    )


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    state = _state_fields()

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append((name, passed, detail))

    missing_graph_fields = [name for name in GRAPH_FIELDS if not state.get(name)]
    record(
        "workflow graph state",
        not missing_graph_fields,
        graph_status(state),
    )

    if PANEL.exists():
        meta = pq.ParquetFile(PANEL).metadata
        panel_manifest = _manifest(PANEL)
        record(
            "panel manifest row contract",
            panel_manifest.get("rows") == meta.num_rows,
            f"parquet={meta.num_rows:,}; manifest={panel_manifest.get('rows')}",
        )
        verdict = verify(PANEL)
        record(
            "panel provenance current",
            verdict.get("status") == "ok" and bool(panel_manifest.get("inputs")),
            f"status={verdict.get('status')}; inputs={len(panel_manifest.get('inputs') or [])}",
        )
        con = duckdb.connect()
        summary = con.execute(
            f"""
            SELECT count(DISTINCT date), min(date), max(date)
            FROM read_parquet('{PANEL.as_posix()}')
            """
        ).fetchone()
        v4_days = {
            str(row[0]).replace("-", "")
            for row in con.execute(
                f"""
                SELECT DISTINCT date
                FROM read_parquet('{PANEL.as_posix()}')
                WHERE direct_source='uniswap_v4'
                   OR hop1_source='uniswap_v4'
                   OR hop2_source='uniswap_v4'
                """
            ).fetchall()
        }
        con.close()
        record(
            "panel time coverage",
            int(summary[0]) >= 2_238 and str(summary[2]) == "2026-06-30",
            f"days={summary[0]:,}; range={summary[1]}..{summary[2]}",
        )
        raw_v4 = _nonempty_v4_days()
        overlap = len(v4_days & raw_v4)
        coverage = overlap / len(raw_v4) if raw_v4 else 0.0
        record(
            "v4 historical pricing coverage",
            coverage >= 0.90,
            f"priced={overlap:,}; nonempty raw days={len(raw_v4):,}; share={coverage:.1%}",
        )
    else:
        record("route-cost panel exists", False, str(PANEL.relative_to(ROOT)))

    if EXTENT.exists():
        con = duckdb.connect()
        extent_days = con.execute(
            f"SELECT count(DISTINCT date) FROM read_parquet('{EXTENT.as_posix()}')"
        ).fetchone()[0]
        con.close()
        record(
            "vehicle extent full sample",
            extent_days == 2_277 and verify(EXTENT).get("status") == "ok",
            f"days={extent_days:,}; provenance={verify(EXTENT).get('status')}",
        )
    else:
        record("vehicle extent exists", False, str(EXTENT.relative_to(ROOT)))

    refresh = REFRESH.read_text() if REFRESH.exists() else ""
    retired = [
        name
        for name in (
            "measure_realised_dominance.py",
            "run_dominance_specification_curve.py",
            "run_vehicle_dominance_hdfe.py",
            "run_survival_after_dominance.py",
            "run_displacement_asymmetry.py",
            "run_jfe_construct_validity_checks.py",
            "build_paper_exhibits.py",
        )
        if name in refresh
    ]
    record(
        "refresh graph excludes retired estimands",
        not retired,
        f"retired={retired or 'none'}; "
        "only validated diagnostics may run",
    )

    stable_passes = int(state.get("stable_passes") or 0)
    record(
        "two unchanged findings passes",
        stable_passes >= 2,
        f"stable_passes={stable_passes}",
    )

    print(f"GRAPH  {graph_status(state)}\n")
    width = max(len(name) for name, _passed, _detail in checks)
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<{width}}  {detail}")
    failures = [name for name, passed, _detail in checks if not passed]
    print(
        f"\nfreeze gate: {'PASS' if not failures else 'RED'} "
        f"({len(failures)} blocking check(s))"
    )
    if failures:
        print("blocking: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
