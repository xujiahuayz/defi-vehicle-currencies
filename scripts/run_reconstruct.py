#!/usr/bin/env python3
"""CLI wrapper for the ddvc reconstruct layer.

Usage:
    ./scripts/run scripts/run_reconstruct.py --start YYYY-MM-DD --end YYYY-MM-DD
    ./scripts/run scripts/run_reconstruct.py --day YYYY-MM-DD
    ./scripts/run scripts/run_reconstruct.py
"""
import argparse
import sys

from ddvc.reconstruct import DEX_FAMILY, run


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reconstruct cross-DEX routes -> unified swap-events table."
    )
    ap.add_argument("--start", default=None, help="YYYY-MM-DD (default: locked research sample start)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD inclusive (default: locked research sample end)")
    ap.add_argument("--day", default=None, help="single day YYYY-MM-DD (overrides start/end)")
    ap.add_argument("--dex", nargs="+", default=list(DEX_FAMILY), help="DEX sources to include")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="recompute even when the day marker is current (default: reuse current days)",
    )
    args = ap.parse_args()
    raise SystemExit(run(
        start=args.start,
        end=args.end,
        day=args.day,
        dexes=args.dex,
        concurrency=args.concurrency,
        skip_existing=not args.no_skip_existing,
    ))


if __name__ == "__main__":
    sys.exit(main())
