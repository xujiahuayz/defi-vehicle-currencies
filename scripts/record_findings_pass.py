#!/usr/bin/env python3
"""Record one F->G findings pass by fingerprinting the claim registry.

The freeze gate needs two consecutive passes that add no claim and retire none.
That used to be a hand-typed `stable_passes` counter inside the very document the
gate audits, which nothing in the repository wrote and nobody could earn. This
script replaces it: at the end of a pass it reads the two canonical registries,
computes the fingerprint defined in `ddvc.model_registry.findings_registry_state`,
and appends one immutable row to `logs/findings-fingerprints.jsonl`.

The fingerprint covers the claim ids with their statuses and the retired families,
and nothing else, so a refreshed estimate or a rewritten section does not reset
the counter while a promotion, demotion, addition or retirement does.

A pass is identified by the commit the registry was read at. Two rows written
without committed work between them are one pass, and the script refuses to append
the second, so the gate cannot be earned by running this twice in a row.

Reads   docs/specification-lock.json
        docs/model-ledger.json
Writes  logs/findings-fingerprints.jsonl (append-only; rows are never edited)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ddvc.model_registry import (
    FINDINGS_FINGERPRINT_LEDGER,
    findings_fingerprint,
    findings_registry_state,
    read_findings_fingerprints,
)
from ddvc.paths import REPO_ROOT

SPECIFICATION_LOCK = REPO_ROOT / "docs" / "specification-lock.json"
MODEL_LEDGER = REPO_ROOT / "docs" / "model-ledger.json"


def head_commit() -> str:
    """Return the commit the registry is being read at, or fail loudly."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"cannot resolve HEAD: {result.stderr.strip()}")
    return result.stdout.strip()


def worktree_clean() -> bool:
    """Report whether the registries and their ledger are committed."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "docs", "logs"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pass-id",
        required=True,
        help="short identity of this F->G pass, e.g. the grind iteration date",
    )
    parser.add_argument(
        "--note",
        default="",
        help="one line on what the pass reviewed; never enters the fingerprint",
    )
    parser.add_argument("--ledger", type=Path, default=FINDINGS_FINGERPRINT_LEDGER)
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="compute and print the fingerprint without appending a row",
    )
    args = parser.parse_args()

    specification = json.loads(SPECIFICATION_LOCK.read_text())
    ledger = json.loads(MODEL_LEDGER.read_text())
    state = findings_registry_state(specification, ledger)
    fingerprint = findings_fingerprint(specification, ledger)
    commit = head_commit()

    if args.print_only:
        print(json.dumps({"fingerprint": fingerprint, "state": state}, indent=2, sort_keys=True))
        return 0

    rows = read_findings_fingerprints(args.ledger)
    if rows and str(rows[-1].get("commit")) == commit:
        print(
            f"refusing to append: the last row is already this pass "
            f"(commit {commit[:12]}, pass {rows[-1].get('pass_id')}). "
            "Commit the pass's work before recording another.",
            file=sys.stderr,
        )
        return 1
    if rows and str(rows[-1].get("pass_id")) == args.pass_id:
        print(
            f"refusing to append: pass id {args.pass_id!r} is already the last row.",
            file=sys.stderr,
        )
        return 1

    row = {
        "claims": state["claims"],
        "commit": commit,
        "fingerprint": fingerprint,
        "note": args.note,
        "pass_id": args.pass_id,
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "retired": state["retired"],
        "worktree_clean": worktree_clean(),
    }
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")

    previous = rows[-1] if rows else None
    print(f"recorded pass {args.pass_id} at {commit[:12]}: {fingerprint}")
    if previous is None:
        print("this is the first pass; the gate needs one more that matches it")
    elif previous["fingerprint"] == fingerprint:
        print(f"unchanged against pass {previous['pass_id']}")
    else:
        print(f"CHANGED against pass {previous['pass_id']}; the counter restarts here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
