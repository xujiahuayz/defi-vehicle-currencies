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

from ddvc.latex_text import included_section_files, strip_latex_markup

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs" / "reviews" / "paper-rhetoric.json"
HEADING_RE = re.compile(r"^\\(?:section|subsection|subsubsection)\*?\{([^{}]+)\}", re.MULTILINE)


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


def opening_review_errors(relative: str, row: dict, path: Path) -> list[str]:
    """Require one substantive editorial judgment for every current heading opening.

    This is an enumeration gate, not a prose classifier.  A reviewer may approve a direct
    opening, a bridge, or an explicit roadmap when that function fits the argument.  The
    gate prevents a local correction from being recorded as a manuscript-wide sweep while
    another section or subsection was never inspected.
    """
    expected = HEADING_RE.findall(path.read_text(encoding="utf-8")) or ["Abstract"]
    openings = row.get("openings")
    if not isinstance(openings, list):
        return [f"missing enumerated opening review: {relative}"]

    errors: list[str] = []
    reviewed: list[str] = []
    allowed = {"substantive_bridge", "direct", "roadmap"}
    for index, opening in enumerate(openings, start=1):
        label = f"{relative} openings[{index}]"
        if not isinstance(opening, dict):
            errors.append(f"invalid opening review: {label}")
            continue
        heading = str(opening.get("heading", "")).strip()
        reviewed.append(heading)
        if opening.get("classification") not in allowed:
            errors.append(f"invalid opening classification: {label}")
        for field in ("incoming_object", "opening_function", "judgment", "raw_exemplar"):
            if not str(opening.get(field, "")).strip():
                errors.append(f"missing {field.replace('_', ' ')}: {label}")
        reference = str(opening.get("raw_exemplar", ""))
        source = re.sub(r":\d+(?:-\d+)?$", "", reference)
        if source and not (ROOT / source).is_file():
            errors.append(f"missing raw opening exemplar: {label}: {source}")

    if reviewed != expected:
        errors.append(
            f"opening review coverage differs: {relative}; "
            f"expected={expected!r}; reviewed={reviewed!r}"
        )
    return errors


def conclusion_review_errors(relative: str, row: dict) -> list[str]:
    """Require the conclusion review to reach synthesis, consequence, and a real ending."""
    if not relative.endswith("07-conclusion.tex"):
        return []
    review = row.get("conclusion_review")
    if not isinstance(review, dict):
        return [f"missing conclusion review: {relative}"]
    errors: list[str] = []
    for field in ("synthesis", "economic_consequence", "scope_condition", "final_sentence_function"):
        if not str(review.get(field, "")).strip():
            errors.append(f"missing conclusion {field.replace('_', ' ')}: {relative}")
    exemplars = review.get("raw_exemplars")
    if not isinstance(exemplars, list) or not exemplars:
        errors.append(f"no raw conclusion exemplar: {relative}")
    else:
        for reference in exemplars:
            source = re.sub(r":\d+(?:-\d+)?$", "", str(reference))
            if not (ROOT / source).is_file():
                errors.append(f"missing raw conclusion exemplar: {relative}: {source}")
    return errors


def prose_paragraph_lines(path: Path) -> list[int]:
    """Return reader-facing prose paragraph lines under the repository's one-line style."""
    lines: list[int] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if (not stripped or stripped.startswith(("%", "\\")) or "&" in stripped
                or stripped.endswith("\\\\")):
            continue
        visible = strip_latex_markup(stripped)
        if len(re.findall(r"[A-Za-z][A-Za-z'-]*", visible)) < 20:
            continue
        # TeX's negative thin-space command (``\\!``) must not make an equation look
        # like a prose sentence.  Reader-facing paragraphs here end in a period or question.
        if not re.search(r"[.?]", visible):
            continue
        lines.append(line_number)
    return lines


def paragraph_flow_errors(relative: str, row: dict, path: Path) -> list[str]:
    """Verify that every substantive paragraph handoff was included in the review.

    The ledger does not pretend to classify rhetoric automatically.  It records the exact
    transition perimeter reviewed by an editor and any jumps found there; the source hash
    and line inventory prevent one repaired paragraph from masquerading as a complete sweep.
    """
    paragraphs = prose_paragraph_lines(path)
    expected = paragraphs[1:]
    review = row.get("paragraph_flow_review")
    if not isinstance(review, dict):
        return [f"missing paragraph-flow review: {relative}"]
    errors: list[str] = []
    if review.get("transition_lines") != expected:
        errors.append(
            f"paragraph-flow coverage differs: {relative}; "
            f"expected={expected!r}; reviewed={review.get('transition_lines')!r}"
        )
    if not str(review.get("judgment", "")).strip():
        errors.append(f"missing paragraph-flow judgment: {relative}")
    exemplars = review.get("raw_exemplars")
    if not isinstance(exemplars, list) or not exemplars:
        errors.append(f"no raw paragraph-flow exemplar: {relative}")
    else:
        for reference in exemplars:
            source = re.sub(r":\d+(?:-\d+)?$", "", str(reference))
            if not (ROOT / source).is_file():
                errors.append(f"missing raw paragraph-flow exemplar: {relative}: {source}")
    jumps = review.get("jumps")
    if not isinstance(jumps, list):
        errors.append(f"missing paragraph-flow jump inventory: {relative}")
    else:
        for index, jump in enumerate(jumps, start=1):
            label = f"{relative} jumps[{index}]"
            if not isinstance(jump, dict) or jump.get("line") not in expected:
                errors.append(f"invalid paragraph-flow jump: {label}")
                continue
            for field in ("issue", "resolution"):
                if not str(jump.get(field, "")).strip():
                    errors.append(f"missing {field}: {label}")
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
        errors.extend(opening_review_errors(relative, row, path))
        errors.extend(conclusion_review_errors(relative, row))
        errors.extend(paragraph_flow_errors(relative, row, path))

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
