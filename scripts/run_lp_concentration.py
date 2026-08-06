#!/usr/bin/env python3
"""CLI wrapper for the candidate-linked liquidity exhibit.

Usage:
    ./scripts/run scripts/run_lp_concentration.py --start YYYY-MM-DD --end YYYY-MM-DD
    ./scripts/run scripts/run_lp_concentration.py --start 2023-01-01 --end 2023-01-03
"""
import argparse
import sys

from ddvc.analysis.lp_concentration import run


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compute candidate-linked liquidity and concentration."
    )
    ap.add_argument("--start", required=True, help="YYYY-MM-DD start date (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD end date (inclusive)")
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
