#!/usr/bin/env python3
"""Route a research action through the live graph before files are mutated."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs" / "findings-freeze.md"


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} has no frontmatter")
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    raise ValueError(f"{path} has unterminated frontmatter")


ROUTES = {
    "data": "Read workflow sections 0 and 2 plus the current data-gate row. Search the ledger for the same data family before building. Classify economic weight and concentration before repair.",
    "analysis": "Read workflow sections 2-6 and bind the exact released D3 generation. Separate calendar patterns from design, opportunity, adoption, exit, and reversal mechanisms.",
    "deck": "Read workflow sections 6-7 and docs/reviews/deck-visual-composition.md. Run semantic diff, focused tests, compile, audits, and changed-page inspection on every touch.",
    "prose": "Read workflow sections 1, 6, and 7. Use cards only to locate analogues; compare the rewrite directly with the named raw published JFE passages. Vocabulary lint is diagnostic; revision operates on the economic argument and whole paragraph sequence.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ROUTES))
    args = parser.parse_args()
    state = frontmatter(FREEZE)
    print(f"freeze={state.get('freeze_status', '?')}")
    print(f"studio={state.get('studio_node', '?')}")
    print(f"m3={state.get('m3_node', '?')}")
    print(f"meeting={state.get('meeting_edge', '?')}")
    print(ROUTES[args.action])
    if args.action == "prose" and state.get("prose_node", "closed").lower() != "open":
        print("BLOCKED: prose node P is closed. Develop the economic argument in docs/paper-spine.md and leave paper/ unchanged. Do not perform term substitution or create a second style memo.")
        return 2
    print(f"ALLOWED: {args.action} action is inside the current graph boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
