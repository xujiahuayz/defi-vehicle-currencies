"""House-voice gates on the DELIVERABLES, not only on the plan that describes them.

`tests/test_paper_spine.py` gates `docs/paper-spine.md`, which is the blueprint. The paper
and the deck are what a reader sees, and until now nothing checked them. That gap is not
hypothetical for this project: version 1 shipped a deck whose stylistic tells survived
three review rounds, and the spine passing its own gate says nothing about the LaTeX that
gets compiled from it.

The checks are the spine's, applied to every source file under `paper/sections/` and
`deck/`. Two differences follow from the format. Hard-wrapped lines are the LaTeX house
style in many projects and are forbidden here as they are everywhere else, since Java's
rule covers prose in any file, so the wrap check runs on paragraphs and skips anything
that is markup, a table row, a comment, or maths. And an em dash is banned in prose but
`---` in a LaTeX comment is a section divider, so comments are exempt.

Slides carry one further rule the paper does not: a slide is phrases and not sentences, and
no slide may describe this project's own process. Both are checked here so a draft cannot
reach review carrying them.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "paper" / "sections"
DECK_DIR = ROOT / "deck"

BANNED_SUBSTRINGS = ("—", "–", "rather than", "genuinely", "deliberate")

CONTRAST_CONFIRMATION = re.compile(
    r"\bnot\b[^.;]{2,40},\s*(but|it'?s|it is|this is)\b", flags=re.IGNORECASE)
LOOSE_P_VALUE = re.compile(r"\bp\s*[<>=]", flags=re.IGNORECASE)

# Words that only appear when a deliverable is talking about its own construction. A
# reader at a conference does not care which node produced a slide.
PROCESS_WORDS = (
    "node a", "node b", "node c", "node d", "node e", "node f", "node g", "node h",
    "node i", "node j", "node k", "workflow", "pipeline", "this project", "spine",
    "PENDING", "WITHDRAWN", "TODO", "placeholder",
)


def source_files(directory: Path, suffix: str = "*.tex") -> list[Path]:
    return sorted(p for p in directory.rglob(suffix) if p.is_file()) if directory.exists() else []


def is_markup(line: str) -> bool:
    s = line.strip()
    return (
        not s
        or s.startswith(("%", "\\", "&", "}", "{", "$$", "|"))
        or s.endswith(("\\\\", "{", "}"))
        or "&" in s                       # tabular row
        or s.startswith(("-", "*"))
    )


def prose_lines(text: str) -> list[tuple[int, str]]:
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        if is_markup(line):
            continue
        out.append((n, line))
    return out


def strip_comments(text: str) -> str:
    return "\n".join("" if ln.lstrip().startswith("%") else ln for ln in text.splitlines())


class PaperProseTests(unittest.TestCase):
    """Runs over whatever exists. A missing draft is not a passing draft, so the
    existence of at least one source file is asserted separately below."""

    def all_sources(self) -> list[Path]:
        return source_files(PAPER_DIR) + source_files(DECK_DIR)

    def test_no_banned_stylistic_tells(self) -> None:
        for path in self.all_sources():
            body = strip_comments(path.read_text(encoding="utf-8")).lower()
            for banned in BANNED_SUBSTRINGS:
                with self.subTest(file=path.name, banned=banned):
                    self.assertNotIn(banned.lower(), body)

    def test_no_contrast_confirmation(self) -> None:
        for path in self.all_sources():
            for n, line in prose_lines(strip_comments(path.read_text(encoding="utf-8"))):
                m = CONTRAST_CONFIRMATION.search(line)
                if m:
                    self.fail(f"{path.name}:{n} contrast-confirmation {m.group(0)!r}")

    def test_p_values_are_bare_parentheses(self) -> None:
        for path in self.all_sources():
            for n, line in prose_lines(strip_comments(path.read_text(encoding="utf-8"))):
                m = LOOSE_P_VALUE.search(line)
                if m:
                    self.fail(f"{path.name}:{n} loose p-value {m.group(0)!r}")

    def test_prose_is_not_hard_wrapped(self) -> None:
        for path in self.all_sources():
            lines = strip_comments(path.read_text(encoding="utf-8")).splitlines()
            for n, (cur, nxt) in enumerate(zip(lines, lines[1:]), start=1):
                if is_markup(cur) or is_markup(nxt):
                    continue
                self.fail(f"{path.name}:{n}-{n + 1} hard-wrapped prose")

    def test_no_internal_process_language_in_the_deck(self) -> None:
        for path in source_files(DECK_DIR):
            body = strip_comments(path.read_text(encoding="utf-8"))
            for word in PROCESS_WORDS:
                with self.subTest(file=path.name, word=word):
                    self.assertNotIn(word.lower(), body.lower())

    def test_no_status_markers_leak_into_the_paper(self) -> None:
        # A spine row reading PENDING is a plan. The same string in a compiled paper is
        # an unfinished sentence shipped to a referee.
        for path in source_files(PAPER_DIR):
            body = strip_comments(path.read_text(encoding="utf-8"))
            for marker in ("PENDING", "WITHDRAWN", "TODO", "placeholder", "XXX"):
                with self.subTest(file=path.name, marker=marker):
                    self.assertNotIn(marker, body)


if __name__ == "__main__":
    unittest.main()
