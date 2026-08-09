#!/usr/bin/env python3
"""CLI wrapper for the candidate-linked deposited-capital exhibit.

Usage:
    ./scripts/run scripts/run_lp_concentration.py --start YYYY-MM-DD --end YYYY-MM-DD
    ./scripts/run scripts/run_lp_concentration.py --start 2023-01-01 --end 2023-01-03
"""
import argparse
import sys

from ddvc.analysis.lp_concentration import run
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compute candidate-linked deposited capital and its concentration."
    )
    ap.add_argument(
        "--start",
        default=RESEARCH_SAMPLE_START,
        help=f"YYYY-MM-DD start date (inclusive; default {RESEARCH_SAMPLE_START})",
    )
    ap.add_argument(
        "--end",
        default=RESEARCH_SAMPLE_END,
        help=f"YYYY-MM-DD end date (inclusive; default {RESEARCH_SAMPLE_END})",
    )
    ap.add_argument(
        "--no-chart",
        action="store_true",
        help="skip generating the PDF chart",
    )
    args = ap.parse_args()
    df = run(start=args.start, end=args.end, chart=not args.no_chart)
    if not df.empty:
        print(f"\nResult shape: {df.shape}")
        print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
