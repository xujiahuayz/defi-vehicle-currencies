#!/usr/bin/env python3
"""Reject scientific figures and measured values typed into deck source."""

from __future__ import annotations

from pathlib import Path

from ddvc.deck_evidence import audit_deck_sources


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    defects = audit_deck_sources(ROOT / "deck")
    for defect in defects:
        relative = defect.path.relative_to(ROOT)
        print(f"{relative}:{defect.line}: {defect.kind}: {defect.detail}")
    if defects:
        print(f"FAIL: {len(defects)} deck evidence-boundary defect(s)")
        return 1
    print("PASS: deck scientific values are generated through output/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
