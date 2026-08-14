#!/usr/bin/env python3
"""Require every compiled paper section to have a current raw-passage review record.

This checks review freshness and source existence, not prose quality. The review itself is
editorial judgment recorded in ``docs/reviews/paper-rhetoric.json``. Hashing the reviewed
source prevents a later content edit from inheriting an old claim that the paragraph was
read against the JFE analogues. The ledger separately fingerprints passages used to review
anecdotes and analogies. That dimension records what a passage does and how it hands off to
evidence; it does not prescribe how many examples a paper needs or how long they should be.
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


def passage_digest(path: Path, line_start: int, line_end: int) -> str:
    """Hash an inclusive raw-text line range exactly as reviewed."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise ValueError(
            f"invalid line range {line_start}-{line_end} for {path} ({len(lines)} lines)"
        )
    return hashlib.sha256("".join(lines[line_start - 1:line_end]).encode("utf-8")).hexdigest()


def anecdote_analogy_errors(review: dict, root: Path = ROOT) -> list[str]:
    """Validate freshness and editorial content of the anecdote/analogy review.

    Deliberately absent are counts, target lengths, lexical rules, and required placements.
    The checker only proves that the named raw passages and the draft passages still match
    the editorial judgments recorded after reading them.
    """
    dimension = review.get("anecdote_analogy_review")
    if not isinstance(dimension, dict):
        return ["missing anecdote/analogy resemblance review"]

    errors: list[str] = []
    collections = (
        ("precedents", (
            "paper_page_section", "kind", "placement", "rhetorical_job", "handoff",
            "draft_relevance",
        )),
        ("draft_uses", ("kind", "rhetorical_job", "handoff", "judgment")),
    )
    for collection, editorial_fields in collections:
        rows = dimension.get(collection)
        if not isinstance(rows, list) or not rows:
            errors.append(f"no {collection.replace('_', ' ')} registered")
            continue
        for index, row in enumerate(rows, start=1):
            label = f"{collection}[{index}]"
            if not isinstance(row, dict):
                errors.append(f"invalid anecdote/analogy row: {label}")
                continue
            source = row.get("source")
            line_start = row.get("line_start")
            line_end = row.get("line_end")
            expected_digest = row.get("sha256")
            if not isinstance(source, str) or not source:
                errors.append(f"missing source in {label}")
                continue
            path = root / source
            if not path.is_file():
                errors.append(f"missing anecdote/analogy source in {label}: {source}")
                continue
            if not isinstance(line_start, int) or not isinstance(line_end, int):
                errors.append(f"missing line range in {label}: {source}")
            else:
                try:
                    current_digest = passage_digest(path, line_start, line_end)
                except (OSError, UnicodeError, ValueError) as error:
                    errors.append(f"invalid anecdote/analogy range in {label}: {error}")
                else:
                    if current_digest != expected_digest:
                        errors.append(
                            f"stale anecdote/analogy review after passage change: {source}:"
                            f"{line_start}-{line_end}"
                        )
            for field in editorial_fields:
                if not str(row.get(field, "")).strip():
                    errors.append(f"missing {field.replace('_', ' ')} in {label}: {source}")
    return errors


def transition_review_errors(relative: str, row: dict) -> list[str]:
    """Require an editorial account of how each compiled section advances.

    These fields are judgments, not transition-word or paragraph-length targets. They make
    the reviewer name the incoming object, the section's scientific progression, and the
    outgoing handoff, so vague referents cannot inherit a stale prose approval.
    """
    errors: list[str] = []
    for field in ("entry_handoff", "internal_progression", "exit_handoff"):
        if not str(row.get(field, "")).strip():
            errors.append(f"missing {field.replace('_', ' ')}: {relative}")
    return errors


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
    errors.extend(anecdote_analogy_errors(review))
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
        errors.extend(transition_review_errors(relative, row))

    if errors:
        print("\n".join(errors))
        return 1

    open_rows = [path for path, row in rows.items() if row.get("status") == "reviewed_open"]
    print(f"current raw-passage review: {len(rows)} compiled sources")
    dimension = review["anecdote_analogy_review"]
    print(
        "current anecdote/analogy review: "
        f"{len(dimension['precedents'])} raw precedents, "
        f"{len(dimension['draft_uses'])} draft uses"
    )
    if open_rows:
        print(f"editorial rewrites remain open in {len(open_rows)} source(s):")
        for path in open_rows:
            print(f"  {path}: {rows[path].get('open_issue', 'unspecified')}")
    print("freshness is verified; rhetorical quality remains an editorial judgment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
