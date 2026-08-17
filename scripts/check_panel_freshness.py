#!/usr/bin/env python3
"""Fail unless the canonical analysis-panel pointer is newer than every live input."""

from ddvc.panel_freshness import check_canonical_panel_freshness


def main() -> int:
    passed, detail = check_canonical_panel_freshness()
    print(f"{'PASS' if passed else 'FAIL'} canonical panel freshness: {detail}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
