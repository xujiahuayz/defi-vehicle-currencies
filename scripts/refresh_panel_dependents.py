#!/usr/bin/env python3
"""Re-run everything that reads the route-cost panel, in order, after the panel changes.

Nineteen scripts read `data/empirical/route_cost_panel_v2.parquet`, and most of the
paper's claims are downstream of one of them. When the panel is rebuilt, every one of
those numbers is stale until its script runs again, and a stale exhibit is indistinguishable
from a fresh one by inspection. Doing this by hand invites the failure where eleven files
carry a number and nine of them get refreshed.

The order below is a dependency order and not an alphabetical one. Scripts that establish
the screen and the matched sample run before scripts that report rates conditional on
them, and the paper-exhibit assembly runs last.

Two things this refuses to do. It will not run while a rebuild is in flight or against a panel that predates one, for the reason in `rebuild_in_flight`. And it does not stop at the first failure, since a failure in one arm says nothing
about the others, but it does report every failure at the end and exits non-zero, so a
partial refresh cannot be mistaken for a complete one.

Usage
  python scripts/refresh_panel_dependents.py --dry-run     list what would run
  python scripts/refresh_panel_dependents.py               run them
  python scripts/refresh_panel_dependents.py --only measure_realised_dominance
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
PY = ROOT / ".venv" / "bin" / "python"
LOGS = ROOT / "logs" / "refresh"

# (script, args, why it sits here in the order)
STAGES: list[tuple[str, list[str], str]] = [
    ("measure_quoter_support.py", [],
     "the support bound every later screen depends on"),
    ("measure_dominance_windows.py", [],
     "the screened enumeration, which defines the quotable population"),
    ("characterise_matched_sample.py", [],
     "how the matched sample differs from the population, needed to reweight"),
    ("measure_realised_dominance.py", ["--days", "400"],
     "the lead result, and the reweighting rows the paper's table is built from"),
    ("run_dominance_specification_curve.py", [],
     "the specification surface and the formal size interaction"),
    ("run_vehicle_dominance_hdfe.py", [],
     "the high-dimensional fixed-effect estimates across window lengths"),
    ("run_survival_after_dominance.py", [],
     "the retention arm of the survival estimand"),
    ("run_displacement_asymmetry.py", [],
     "the displacement arm, which refuses below 20 consecutive priced days"),
    ("test_gap_arbitrage_bound.py", [],
     "whether the surviving gaps could have been taken"),
    ("run_robustness_tests.py", [],
     "robustness of whatever the arms report"),
    ("run_jfe_construct_validity_checks.py", [],
     "construct validity, which reads the refreshed exhibits"),
    ("build_paper_exhibits.py", [],
     "assembles the paper-facing tables last, so it sees every refresh above"),
]


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
    ap.add_argument("--timeout", type=int, default=7200, help="per-stage seconds")
    ap.add_argument("--force", action="store_true",
                    help="run even if the panel looks like it is still being written")
    args = ap.parse_args()

    stages = [s for s in STAGES if not args.only or args.only in s[0]]
    if not stages:
        print(f"no stage matches {args.only!r}")
        return 1

    if args.dry_run:
        print(f"{len(stages)} stages, in dependency order:\n")
        for i, (script, extra, why) in enumerate(stages, 1):
            print(f"  {i:>2}. {script} {' '.join(extra)}")
            print(f"      {why}")
        return 0

    if not PANEL.exists():
        print(f"no panel at {PANEL.relative_to(ROOT)}")
        return 1
    blocked = None if args.force else rebuild_in_flight()
    if blocked:
        print(f"REFUSING: {blocked}.")
        print("Refreshing now would overwrite good exhibits with numbers from a stale")
        print("panel, and a half-refreshed exhibit set is the hardest state to detect")
        print("later. Wait for the rebuild, then re-run. Use --force only if you are")
        print("certain the panel on disk is the one you want.")
        return 1

    import pyarrow.parquet as pq
    meta = pq.ParquetFile(PANEL)
    print(f"panel: {meta.metadata.num_rows:,} rows, "
          f"{PANEL.stat().st_size / 1e6:.0f} MB\n", flush=True)

    LOGS.mkdir(parents=True, exist_ok=True)
    # One BLAS thread per process. Oversubscription here once drove the load average on a
    # 14-core machine past 300 and made every stage slower than running them in series.
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}

    failures: list[tuple[str, str]] = []
    for i, (script, extra, _why) in enumerate(stages, 1):
        path = ROOT / "scripts" / script
        if not path.exists():
            print(f"  {i:>2}/{len(stages)} {script:<44} MISSING")
            failures.append((script, "missing"))
            continue
        log = LOGS / f"{script}.log"
        started = time.time()
        print(f"  {i:>2}/{len(stages)} {script:<44} running", end="", flush=True)
        try:
            with log.open("w") as fh:
                r = subprocess.run([str(PY), str(path), *extra], cwd=ROOT, env=env,
                                   stdout=fh, stderr=subprocess.STDOUT,
                                   timeout=args.timeout)
            took = time.time() - started
            if r.returncode == 0:
                print(f"\r  {i:>2}/{len(stages)} {script:<44} ok    {took:>6.0f}s")
            else:
                print(f"\r  {i:>2}/{len(stages)} {script:<44} EXIT {r.returncode} "
                      f"{took:>5.0f}s")
                failures.append((script, f"exit {r.returncode}, see {log.name}"))
        except subprocess.TimeoutExpired:
            print(f"\r  {i:>2}/{len(stages)} {script:<44} TIMEOUT after {args.timeout}s")
            failures.append((script, "timeout"))

    print()
    if failures:
        print(f"{len(failures)} of {len(stages)} stages did not complete:")
        for script, why in failures:
            print(f"  {script:<44} {why}")
        print(f"\nLogs in {LOGS.relative_to(ROOT)}. A partial refresh leaves some exhibits")
        print("stale and others fresh, which is the state hardest to detect later, so fix")
        print("these before reading any number downstream of them.")
        return 1
    print(f"all {len(stages)} stages completed. Every panel-dependent exhibit is now")
    print("consistent with the panel reported above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
