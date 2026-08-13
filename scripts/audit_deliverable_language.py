#!/usr/bin/env python3
"""Keep audience-visible deck and paper language field-facing."""

from __future__ import annotations

from pathlib import Path

from ddvc.deck_evidence import (
    audit_deck_sources,
    audit_paper_sources,
    audit_rendered_deck,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    defects = [
        *audit_deck_sources(ROOT / "deck"),
        *audit_paper_sources(ROOT / "paper"),
        *audit_rendered_deck(ROOT / "deck" / "main.pdf"),
        *audit_rendered_deck(ROOT / "paper" / "main.pdf"),
    ]
    for defect in defects:
        print(f"{defect.path.relative_to(ROOT)}:{defect.line}: {defect.kind}: {defect.detail}")
    if defects:
        print(f"FAIL: {len(defects)} audience-language defect(s)")
        return 1
    print("PASS: deck and paper language stays field-facing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
