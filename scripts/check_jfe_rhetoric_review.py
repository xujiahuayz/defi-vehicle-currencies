#!/usr/bin/env python3
"""Require every compiled paper section to have a current raw-passage review record.

This checks review freshness and source existence, not prose quality. The review itself is
editorial judgment recorded in ``docs/reviews/paper-rhetoric.json``. Hashing the reviewed
source prevents a later content edit from inheriting an old claim that the paragraph was
read against the JFE analogues.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ddvc.latex_text import included_section_files

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs" / "reviews" / "paper-rhetoric.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    try:
        review = json.loads(REVIEW.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"invalid rhetorical review ledger: {error}")
        return 1

    files = included_section_files(ROOT / "paper" / "main.tex",
                                   fallback_dir=ROOT / "paper" / "sections")
    expected = {str(path.relative_to(ROOT)) for path in files}
    rows = review.get("sections", {})
    recorded = set(rows)
    errors: list[str] = []
    if expected != recorded:
        for path in sorted(expected - recorded):
            errors.append(f"missing review: {path}")
        for path in sorted(recorded - expected):
            errors.append(f"review records an uncompiled source: {path}")

    for relative in sorted(expected & recorded):
        path = ROOT / relative
        row = rows[relative]
        if digest(path) != row.get("sha256"):
            errors.append(f"stale review after content change: {relative}")
        exemplars = row.get("exemplars", [])
        if not isinstance(exemplars, list) or not exemplars:
            errors.append(f"no raw exemplar registered: {relative}")
        for reference in exemplars if isinstance(exemplars, list) else []:
            source = re.sub(r":\d+(?:-\d+)?$", "", str(reference))
            if not (ROOT / source).is_file():
                errors.append(f"missing raw exemplar for {relative}: {source}")
        if not str(row.get("judgment", "")).strip():
            errors.append(f"no paragraph-level judgment recorded: {relative}")

    if errors:
        print("\n".join(errors))
        return 1

    open_rows = [path for path, row in rows.items() if row.get("status") == "reviewed_open"]
    print(f"current raw-passage review: {len(rows)} compiled sources")
    if open_rows:
        print(f"editorial rewrites remain open in {len(open_rows)} source(s):")
        for path in open_rows:
            print(f"  {path}: {rows[path].get('open_issue', 'unspecified')}")
    print("freshness is verified; rhetorical quality remains an editorial judgment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
