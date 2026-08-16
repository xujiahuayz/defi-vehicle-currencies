#!/usr/bin/env python3
"""Reject typed scientific values and unbudgeted slide density in the deck."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.deck_evidence import (
    audit_deck_density,
    audit_deck_sources,
    audit_rendered_deck,
    deck_density_summary,
    write_deck_density_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
DENSITY_LEDGER = ROOT / "docs" / "deck-density-ledger.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record-density",
        action="store_true",
        help=(
            "rewrite the density ledger from the current rendered deck; the recorded "
            "debt is machine-measured, never hand-typed"
        ),
    )
    args = parser.parse_args()
    deck_root = ROOT / "deck"
    rendered = deck_root / "main.pdf"
    if args.record_density:
        recorded = write_deck_density_ledger(rendered, DENSITY_LEDGER)
        print(f"recorded {recorded} over-budget page(s) in {DENSITY_LEDGER.relative_to(ROOT)}")
    defects = audit_deck_sources(deck_root)
    defects.extend(audit_rendered_deck(rendered))
    defects.extend(audit_deck_density(rendered, DENSITY_LEDGER))
    for defect in defects:
        relative = defect.path.relative_to(ROOT)
        print(f"{relative}:{defect.line}: {defect.kind}: {defect.detail}")
    print(deck_density_summary(rendered, DENSITY_LEDGER))
    if defects:
        print(f"FAIL: {len(defects)} deck evidence-boundary defect(s)")
        return 1
    print("PASS: deck evidence is generated and audience language stays field-facing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
