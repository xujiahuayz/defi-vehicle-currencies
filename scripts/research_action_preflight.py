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


COMMON_REGRESSION_CHECKS = (
    "Name the lane, graph node, purpose-bound estimand, and exact evidence generation.",
    "Compare the planned action with the current claim registry and the last 40 ledger lines; a red global gate is not authority to reopen an immaterial branch.",
    "State which prior scientific correction the action could accidentally reverse, and change the plan before mutation if it would.",
)


ACTION_REGRESSION_CHECKS = {
    "data": (
        "Bound missingness by economic weight and concentration in outcome/mechanism cells before acquisition or rebuild; metadata completeness is not the objective.",
        "Repair only if identity, sample, estimate, or inference can materially change; otherwise preserve a disclosed bounded exclusion.",
    ),
    "analysis": (
        "Treat calendar time as a description unless a design supplies treatment; separate design availability from realised adoption, exit, and reversal.",
        "Hold the relevant endpoint, candidate, reach, venue/design, notional, support, and comparison set fixed before assigning a vehicle-rotation mechanism.",
        "Distinguish vehicle-role appearance/disappearance, within-cell substitution, persistence, and hysteresis; none licenses another.",
    ),
    "deck": (
        "Consult the persistent visual backlog so prior requests do not depend on chat recall; select the visual form by the economic comparison.",
        "Keep the deck presentable after the touch; status, generation, paths, and commit hashes stay in source comments/manifests, not the rendered PDF.",
    ),
    "prose": (
        "Cards are locators only. Reread the closest raw published JFE passages before drafting and record those passage locations.",
        "Rewrite the economic argument, paragraph sequence, transitions, and sentence functions; never infer style from term replacement or a generic template.",
    ),
}


def regression_checks(action: str) -> tuple[str, ...]:
    return COMMON_REGRESSION_CHECKS + ACTION_REGRESSION_CHECKS[action]


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
    print("PRIOR-CORRECTION REGRESSION CHECK:")
    for check in regression_checks(args.action):
        print(f"- {check}")
    if args.action == "prose" and state.get("prose_node", "closed").lower() != "open":
        print("BLOCKED: prose node P is closed. Develop the economic argument in docs/paper-spine.md and leave paper/ unchanged. Do not perform term substitution or create a second style memo.")
        return 2
    print(f"ALLOWED: {args.action} action is inside the current graph boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
