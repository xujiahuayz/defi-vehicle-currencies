#!/usr/bin/env python3
"""Reject scientific figures and measured values typed into deck source."""

from __future__ import annotations

from pathlib import Path

from ddvc.deck_evidence import audit_deck_sources, audit_rendered_deck


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    deck_root = ROOT / "deck"
    defects = audit_deck_sources(deck_root)
    defects.extend(audit_rendered_deck(deck_root / "main.pdf"))
    for defect in defects:
        relative = defect.path.relative_to(ROOT)
        print(f"{relative}:{defect.line}: {defect.kind}: {defect.detail}")
    if defects:
        print(f"FAIL: {len(defects)} deck evidence-boundary defect(s)")
        return 1
    print("PASS: deck evidence is generated and audience language stays field-facing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
