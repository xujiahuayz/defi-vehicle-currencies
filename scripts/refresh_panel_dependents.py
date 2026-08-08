#!/usr/bin/env python3
"""Rebuild canonical claim inputs and validated diagnostics after node D changes.

Many scripts read `data/empirical/route_cost_panel_v2.parquet`, but the definition audit
withheld most of their estimands: route-level realised incidence is not the required
pair-candidate-period unit, the realised join omitted quote hour, the two duration arms
compare asymmetric events, and the old HDFE result uses a retired vehicle definition.
Automatically running those scripts would convert a fresh panel into fresh-looking invalid
findings. This refresher therefore owns only the diagnostics whose definitions survive.

The order below is a dependency order and not an alphabetical one. Support is measured
before screened windows, and the arbitrage bound reads those windows. Finding estimators
return here only after their specification is locked in `docs/findings-freeze.md`.

Two things this refuses to do. It will not run while a rebuild is in flight or against a panel that predates one, for the reason in `rebuild_in_flight`. Independent legacy diagnostics continue after one fails so the pass reports every arm. The ordered D3 claim-input chain fails fast, because running a child against a stale parent wastes work and can publish a misleading partial generation. Every failure exits non-zero.

The full-daily transaction-state frontier is built by its own expensive owner. This script verifies that frontier's admitted, rejected and support artifacts before rebuilding every other registered claim input. Those transforms run serially with one BLAS thread because concurrent panel builders caused an out-of-memory warning during D3.

Usage
  ./scripts/run scripts/refresh_panel_dependents.py --dry-run
  ./scripts/run scripts/refresh_panel_dependents.py --scope claim-inputs
  ./scripts/run scripts/refresh_panel_dependents.py --scope all
  ./scripts/run scripts/refresh_panel_dependents.py --only measure_realised_dominance
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from ddvc.paths import SHARED_RUNTIME_DIR
from ddvc.provenance import verify
from ddvc.runtime import exclusive_job

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
LOGS = ROOT / "logs" / "refresh"
REFRESH_LOCK = SHARED_RUNTIME_DIR / "panel-dependent-refresh.lock"

# (script, args, why it sits here in the order). Withheld scripts are deliberately absent;
# `audit_findings_freeze.py` tests that they do not silently return.
STAGES: list[tuple[str, list[str], str]] = [
    ("measure_quoter_support.py", [],
     "the support bound every later screen depends on"),
    ("measure_dominance_windows.py", [],
     "the screened cost-surface diagnostic, which defines the quotable population"),
    ("test_gap_arbitrage_bound.py", [],
     "whether gaps surviving the support screen could have been taken"),
]

DAILY_FRONTIER_PREREQUISITES = (
    "data/processed/transaction_state_frontier_daily.parquet",
    "data/processed/transaction_state_frontier_daily_rejections.parquet",
    "data/processed/transaction_state_frontier_daily_support.parquet",
)

# This is the executable owner of D3-refresh. These are canonical panels, not finding estimators. The order keeps raw- and receipt-dependent measurement ahead of consumers and deliberately runs one memory-heavy transform at a time.
CLAIM_INPUT_STAGES: list[tuple[str, list[str], str, tuple[str, ...]]] = [
    (
        "process/fetch_daily_gas_price_graph.py",
        ["--workers", "8", "--panel-only"],
        "daily gas prices used by all-in route comparisons",
        ("data/processed/daily_gas_price_graph.parquet",),
    ),
    (
        "process/build_route_gas_units.py",
        ["--workers", "8", "--panel-only"],
        "receipt-measured route gas by topology, venue and vehicle",
        ("data/processed/route_gas_units.parquet",),
    ),
    (
        "build_intermediation_by_type.py",
        ["--workers", "8", "--panel-only"],
        "one-vehicle route counts and value support by asset type",
        ("data/processed/intermediation_by_type_daily.parquet",),
    ),
    (
        "build_cross_venue_routing_series.py",
        ["--workers", "8", "--panel-only"],
        "routing integration, splitting and complexity margins",
        ("data/processed/cross_venue_routing_daily.parquet",),
    ),
    (
        "build_vehicle_excess_use.py",
        ["--workers", "8", "--panel-only"],
        "continuous vehicle dominance normalized by endpoint demand",
        ("data/processed/vehicle_excess_use_daily.parquet",),
    ),
    (
        "build_vehicle_centrality.py",
        ["--stride", "24", "--jobs", "4", "--out", "data/processed/vehicle_centrality_dense.parquet", "--panel-only"],
        "metric-sensitive topology companion",
        ("data/processed/vehicle_centrality_dense.parquet",),
    ),
    (
        "build_rent_incidence_panel.py",
        ["both"],
        "v2 and v3 liquidity-provider rent inputs",
        (
            "data/processed/rent_incidence_v2_pool_day.parquet",
            "data/processed/rent_incidence_v3_pool_day.parquet",
        ),
    ),
    (
        "build_counterfactual_dominance.py",
        ["--panel-only"],
        "legacy-support comparison retained as a bounded diagnostic",
        ("data/processed/counterfactual_dominance.parquet",),
    ),
]


def current_artifacts(paths: tuple[str, ...]) -> tuple[bool, list[str]]:
    """Return whether every artifact exists with current input-aware provenance."""
    bad = []
    for relative in paths:
        path = ROOT / relative
        status = str(verify(path).get("status")) if path.exists() else "missing"
        if status != "ok":
            bad.append(f"{relative}:{status}")
    return not bad, bad


def terminate_process_group(process: subprocess.Popen) -> None:
    """Stop a stage and every worker it spawned before releasing the refresh lock."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_stage(command: list[str], *, log, env: dict[str, str], timeout: int) -> int:
    """Run one stage in its own process group and clean up every exit path."""
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except BaseException:
        terminate_process_group(process)
        raise


def rebuild_in_flight() -> str | None:
    """Why refreshing now would read a stale or partial panel, or None if it is safe.

    Watching the panel file's mtime is NOT enough, and testing that was how this script
    first went wrong. The builder writes day shards into a cache directory for hours and
    only assembles the panel at the very end, so during a rebuild the panel file sits
    perfectly still while being maximally stale. Running against it then silently
    overwrote a 400-day exhibit set with 4-day numbers, including the paper's headline.

    So the checks are on the two things that actually indicate staleness: whether a
    builder process is alive, and whether the panel covers as many days as the day cache
    already holds.
    """
    try:
        out = subprocess.run(["pgrep", "-f", "run_route_cost_panel.py"],
                             capture_output=True, text=True).stdout.split()
        if out:
            return f"a panel rebuild is running ({len(out)} process(es))"
    except FileNotFoundError:
        pass

    cache_root = ROOT / "data" / "empirical" / "_route_cost_day_cache"
    cached = max((len(list(d.glob("*.parquet")))
                  for d in cache_root.glob("engine_*/*") if d.is_dir()), default=0)
    if not PANEL.exists():
        return None
    try:
        import duckdb
        con = duckdb.connect()
        days = con.execute(
            f"SELECT count(DISTINCT date) FROM read_parquet('{PANEL.as_posix()}')"
        ).fetchone()[0]
        con.close()
    except Exception:
        return None
    if cached > days * 2 and cached - days > 20:
        return (f"the panel covers {days:,} days while the day cache holds {cached:,}, "
                f"so it predates a rebuild and must be reassembled first")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, help="run one stage by script-name substring")
    ap.add_argument(
        "--scope",
        choices=("diagnostics", "claim-inputs", "all"),
        default="diagnostics",
        help="diagnostics preserves the historical behavior; claim-inputs owns D3-refresh",
    )
    ap.add_argument("--timeout", type=int, default=7200, help="per-stage seconds")
    ap.add_argument("--force", action="store_true",
                    help="run even if the panel looks like it is still being written")
    args = ap.parse_args()

    diagnostics = [(script, extra, why, ()) for script, extra, why in STAGES]
    if args.scope == "diagnostics":
        stages = diagnostics
    elif args.scope == "claim-inputs":
        stages = CLAIM_INPUT_STAGES
    else:
        stages = [*CLAIM_INPUT_STAGES, *diagnostics]
    stages = [stage for stage in stages if not args.only or args.only in stage[0]]
    if not stages:
        print(f"no stage matches {args.only!r}")
        return 1

    if args.dry_run:
        print(f"{len(stages)} stages, in dependency order:\n")
        for i, (script, extra, why, _outputs) in enumerate(stages, 1):
            print(f"  {i:>2}. {script} {' '.join(extra)}")
            print(f"      {why}")
        return 0

    if args.scope in {"claim-inputs", "all"}:
        ready, bad = current_artifacts(DAILY_FRONTIER_PREREQUISITES)
        if not ready:
            print(f"REFUSING: full-daily transaction frontier is incomplete or stale: {bad}")
            return 1

    if args.scope in {"diagnostics", "all"}:
        if not PANEL.exists():
            print(f"no panel at {PANEL.relative_to(ROOT)}")
            return 1
        blocked = None if args.force else rebuild_in_flight()
        if blocked:
            print(f"REFUSING: {blocked}.")
            print("Refreshing now would overwrite good exhibits with numbers from a stale panel, and a half-refreshed exhibit set is the hardest state to detect later. Wait for the rebuild, then re-run. Use --force only if you are certain the panel on disk is the one you want.")
            return 1

    if args.scope in {"diagnostics", "all"}:
        import pyarrow.parquet as pq
        meta = pq.ParquetFile(PANEL)
        print(f"panel: {meta.metadata.num_rows:,} rows, {PANEL.stat().st_size / 1e6:.0f} MB\n", flush=True)

    LOGS.mkdir(parents=True, exist_ok=True)
    # One BLAS thread per process. Oversubscription here once drove the load average on a
    # 14-core machine past 300 and made every stage slower than running them in series.
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}

    failures: list[tuple[str, str]] = []
    claim_input_scripts = {stage[0] for stage in CLAIM_INPUT_STAGES}
    for i, (script, extra, _why, outputs) in enumerate(stages, 1):
        path = ROOT / "scripts" / script
        if not path.exists():
            print(f"  {i:>2}/{len(stages)} {script:<44} MISSING")
            failures.append((script, "missing"))
            if script in claim_input_scripts:
                break
            continue
        log = LOGS / f"{script}.log"
        started = time.time()
        print(f"  {i:>2}/{len(stages)} {script:<44} running", end="", flush=True)
        failures_before = len(failures)
        try:
            with log.open("w") as fh:
                returncode = run_stage(
                    [sys.executable, str(path), *extra],
                    log=fh,
                    env=env,
                    timeout=args.timeout,
                )
            took = time.time() - started
            if returncode == 0:
                current, bad = current_artifacts(outputs) if outputs else (True, [])
                if current:
                    print(f"\r  {i:>2}/{len(stages)} {script:<44} ok    {took:>6.0f}s")
                else:
                    print(f"\r  {i:>2}/{len(stages)} {script:<44} STALE {took:>5.0f}s")
                    failures.append((script, f"outputs not current: {bad}"))
            else:
                print(f"\r  {i:>2}/{len(stages)} {script:<44} EXIT {returncode} "
                      f"{took:>5.0f}s")
                failures.append((script, f"exit {returncode}, see {log.name}"))
        except subprocess.TimeoutExpired:
            print(f"\r  {i:>2}/{len(stages)} {script:<44} TIMEOUT after {args.timeout}s")
            failures.append((script, "timeout"))
        if script in claim_input_scripts and len(failures) > failures_before:
            break

    print()
    if failures:
        print(f"{len(failures)} of {len(stages)} stages did not complete:")
        for script, why in failures:
            print(f"  {script:<44} {why}")
        print(f"\nLogs in {LOGS.relative_to(ROOT)}. A partial refresh leaves some exhibits")
        print("stale and others fresh, which is the state hardest to detect later, so fix")
        print("these before reading any number downstream of them.")
        return 1
    print(f"all {len(stages)} requested refresh stages completed with current outputs.")
    print("Finding estimators and paper exhibits remain withheld until their definitions lock and scripts/audit_findings_freeze.py passes.")
    return 0


if __name__ == "__main__":
    if any(argument in {"--dry-run", "-h", "--help"} for argument in sys.argv[1:]):
        sys.exit(main())
    with exclusive_job(REFRESH_LOCK, job="panel-dependent refresh"):
        sys.exit(main())
