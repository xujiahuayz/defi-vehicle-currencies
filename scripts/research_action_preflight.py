#!/usr/bin/env python3
"""Check whether a research action is open in the live workflow state."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs" / "findings-freeze.md"

ROUTES = {
    "operations": "supervise or synchronize the active run",
    "literature": "inspect or update source support",
    "data": "fetch or process data for a named research use",
    "analysis": "estimate or validate a named result",
    "deck": "update the live presentation",
    "prose": "update the live manuscript",
    "review": "review a frozen result or deliverable",
    "repository": "clean or reorganize the repository",
}


def frontmatter(path: Path) -> dict[str, str]:
    """Read the small workflow-state header from ``findings-freeze.md``."""
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


def prose_gate(state: dict[str, str]) -> tuple[bool, str]:
    node = state.get("prose_node", "closed").lower()
    if node == "open":
        return True, "ALLOWED: prose node is open"
    if node == "tiered":
        return True, (
            "ALLOWED-TIERED: route-only facts and argument may be edited; "
            "unlocked exact-state coefficients must remain out."
        )
    return False, "BLOCKED: prose node is closed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ROUTES))
    parser.add_argument("--node", help="optional workflow-node label for the action")
    args = parser.parse_args()

    state = frontmatter(FREEZE)
    print(f"freeze={state.get('freeze_status', '?')}")
    print(f"action={args.action}")
    if args.node:
        print(f"node={args.node}")
    print(f"scope={ROUTES[args.action]}")
    print(f"meeting={state.get('meeting_edge', '?')}")

    if args.action == "prose":
        allowed, message = prose_gate(state)
        print(message)
        return 0 if allowed else 2

    print(f"ALLOWED: {args.action} action is inside the current workflow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
