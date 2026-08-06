#!/usr/bin/env python3
"""CLI wrapper for the ddvc metrics layer.

Usage:
    ./scripts/run scripts/run_metrics.py --start YYYY-MM-DD --end YYYY-MM-DD
    ./scripts/run scripts/run_metrics.py --day YYYY-MM-DD
    ./scripts/run scripts/run_metrics.py --all
"""
import argparse
import sys

from ddvc.metrics import run


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compute per-day vehicle-currency dominance metrics."
    )
    ap.add_argument("--start", default=None, help="YYYY-MM-DD (default: earliest available)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default: latest available)")
    ap.add_argument("--day", default=None, help="single day YYYY-MM-DD (overrides start/end)")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="recompute days already in data/metrics/ (default: skip them)",
    )
    ap.add_argument(
        "--no-rebuild-combined",
        action="store_true",
        help="skip rebuilding data/metrics/daily_token_metrics.parquet",
    )
    args = ap.parse_args()
    run(
        start=args.start,
        end=args.end,
        day=args.day,
        concurrency=args.concurrency,
        skip_existing=not args.no_skip_existing,
        rebuild_combined=not args.no_rebuild_combined,
    )


if __name__ == "__main__":
    sys.exit(main())
