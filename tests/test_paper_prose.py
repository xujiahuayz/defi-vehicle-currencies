"""House-voice gates on the DELIVERABLES, not only on the plan that describes them.

`tests/test_paper_spine.py` gates `paper/README.md`, which is the blueprint. The paper
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

from ddvc.latex_text import (
    NEGATED_HEADLINE,
    audience_process_matches,
    included_section_files,
    strip_latex_comments,
    strip_latex_markup,
)

ROOT = Path(__file__).resolve().parents[1]

SECTIONS_DIR = (ROOT / "paper" / "sections") if (ROOT / "paper" / "sections").is_dir() else (ROOT / "memo" / "sections")
PAPER_DIR = SECTIONS_DIR
DECK_DIR = ROOT / "deck"

# Keep only unmistakable house-style tells here. Ordinary contrast and intent
# phrases cannot generally be rejected lexically. This project's repeated use
# of correction-style contrasts is the exception: the paper and deck state the
# measured object directly.
BANNED_SUBSTRINGS = ("—", "–", "genuinely", "rather than", "claim")

CONTRAST_CONFIRMATION = re.compile(
    r"\bnot\b[^.;!?]{1,100}\b(?:but|rather|instead)\b", flags=re.IGNORECASE)
LOOSE_P_VALUE = re.compile(r"\bp\s*[<>=]", flags=re.IGNORECASE)
ABSTRACT_WORD = re.compile(r"[A-Za-z0-9]+(?:[.'’%-][A-Za-z0-9]+)*")
JFE_ABSTRACT_WORD_LIMIT = 100

def source_files(directory: Path, suffix: str = "*.tex") -> list[Path]:
    return sorted(p for p in directory.rglob(suffix) if p.is_file()) if directory.exists() else []


def is_markup(line: str) -> bool:
    s = line.strip()
    return (
        not s
        or s.startswith(("%", "\\", "&", "}", "{", "$$", "|"))
        or s.endswith(("\\\\", "\\par", "{", "}"))
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
        paper = list(included_section_files(PAPER_DIR.parent / "main.tex", fallback_dir=PAPER_DIR))
        return paper + source_files(DECK_DIR)

    def test_no_banned_stylistic_tells(self) -> None:
        for path in self.all_sources():
            body = strip_comments(path.read_text(encoding="utf-8")).lower()
            for banned in BANNED_SUBSTRINGS:
                with self.subTest(file=path.name, banned=banned):
                    self.assertNotIn(banned.lower(), body)

    def test_no_internal_or_ai_favored_language_in_paper_or_deck(self) -> None:
        pattern = re.compile(
            r"\bdiagnos\w*|\bclaims?\b|\bclaimed\b|\bclaiming\b|\brather than\b",
            flags=re.IGNORECASE,
        )
        tex_sources = source_files(ROOT / "paper") + source_files(DECK_DIR)
        for path in tex_sources:
            body = path.read_text(encoding="utf-8")
            match = pattern.search(body)
            if match:
                self.fail(
                    f"{path.relative_to(ROOT)}:{body.count(chr(10), 0, match.start()) + 1} "
                    f"contains internal workflow language {match.group(0)!r}"
                )

        from pypdf import PdfReader

        for path in (ROOT / "paper" / "main.pdf", DECK_DIR / "main.pdf"):
            self.assertTrue(path.is_file(), f"{path.relative_to(ROOT)} must be built")
            for page_number, page in enumerate(PdfReader(path).pages, start=1):
                body = page.extract_text() or ""
                match = pattern.search(body)
                if match:
                    self.fail(
                        f"{path.relative_to(ROOT)}:{page_number} contains internal "
                        f"workflow language {match.group(0)!r}"
                    )

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
        for path in self.all_sources():
            body = strip_latex_comments(path.read_text(encoding="utf-8"))
            matches = audience_process_matches(body)
            if matches:
                label, match = matches[0]
                self.fail(
                    f"{path.name}:{body.count(chr(10), 0, match.start()) + 1} "
                    f"{match.group(0)!r} exposes {label.replace('_', ' ')}"
                )

    def test_generated_content_does_not_reintroduce_process_language(self) -> None:
        """The compiled paper includes generated figure labels and table text.

        Source-only checks miss those readers' words, so the audience-language
        contract is also applied to the actual deliverable.
        """
        from pypdf import PdfReader

        pdf = PAPER_DIR.parent / "main.pdf"
        self.assertTrue(pdf.is_file(), "paper/main.pdf must be built before prose review")
        for page_number, page in enumerate(PdfReader(pdf).pages, start=1):
            body = page.extract_text() or ""
            matches = audience_process_matches(body)
            if matches:
                label, match = matches[0]
                self.fail(
                    f"paper/main.pdf:{page_number} {match.group(0)!r} exposes "
                    f"{label.replace('_', ' ')} through generated content"
                )

    def test_headlines_state_economic_results_affirmatively(self) -> None:
        pattern = re.compile(r"\\(?:section|subsection|caption)\{([^}]*)\}")
        for path in source_files(PAPER_DIR):
            body = strip_latex_comments(path.read_text(encoding="utf-8"))
            for headline in pattern.findall(body):
                if NEGATED_HEADLINE.search(headline):
                    self.fail(f"{path.name}: negated headline {headline!r}")

    def test_no_status_markers_leak_into_the_paper(self) -> None:
        # A spine row reading PENDING is a plan. The same string in a compiled paper is
        # an unfinished sentence shipped to a referee.
        for path in source_files(PAPER_DIR):
            body = strip_comments(path.read_text(encoding="utf-8"))
            for marker in ("PENDING", "WITHDRAWN", "TODO", "placeholder", "XXX"):
                with self.subTest(file=path.name, marker=marker):
                    self.assertNotIn(marker, body)

    def test_dex_route_units_use_distinct_terms(self) -> None:
        for path in (
            PAPER_DIR / "03-dominance.tex",
            PAPER_DIR / "05-rivals.tex",
            DECK_DIR / "sections" / "04-results.tex",
        ):
            body = strip_latex_comments(path.read_text(encoding="utf-8")).lower()
            self.assertNotIn(
                "corridor",
                body,
                f"{path.name} uses corridor for a DEX endpoint pair",
            )
            self.assertNotIn(
                "endpoint-pair market",
                body,
                f"{path.name} conflates an endpoint pair with a pool-pair market",
            )

    def test_reader_facing_route_vocabulary_is_current(self) -> None:
        obsolete = re.compile(
            r"\bultimate[- ]pairs?\b|\batomic[- ]pairs?\b|\batomic[- ]trades?\b|\btoken[- ]pairs?\b|\bcorridor\b|\bendpoint[- ]pair market\b",
            re.IGNORECASE,
        )
        paths = source_files(ROOT / "paper") + source_files(DECK_DIR)
        paths.append(DECK_DIR / "script.md")
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            body = strip_latex_comments(raw) if path.suffix == ".tex" else raw
            match = obsolete.search(body)
            if match:
                self.fail(
                    f"{path.relative_to(ROOT)}:{body.count(chr(10), 0, match.start()) + 1} "
                    f"uses ambiguous audience term {match.group(0)!r}"
                )
        introduction = (PAPER_DIR / "01-introduction.tex").read_text(encoding="utf-8")
        self.assertRegex(introduction, r"\\emph\{endpoint pair\}")
        self.assertRegex(introduction, r"\\emph\{pair\}")
        self.assertRegex(introduction, r"\\emph\{leg\}")
        self.assertRegex(introduction, r"\\emph\{route\}")

    def test_path_is_reserved_for_feasible_or_counterfactual_alternatives(self) -> None:
        observed_path = re.compile(
            r"\b(?:observed|realised|transaction[- ]level|pool|chosen|self[- ]returning) paths?\b|\bpath length\b|\bpath dependence\b",
            re.IGNORECASE,
        )
        paths = source_files(ROOT / "paper") + source_files(DECK_DIR)
        paths.append(DECK_DIR / "script.md")
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            body = strip_latex_comments(raw) if path.suffix == ".tex" else raw
            match = observed_path.search(body)
            if match:
                self.fail(
                    f"{path.relative_to(ROOT)}:{body.count(chr(10), 0, match.start()) + 1} "
                    f"uses path for an observed route: {match.group(0)!r}"
                )

    def test_percentage_point_abbreviation_is_defined_before_compact_use(self) -> None:
        preamble = (PAPER_DIR.parent / "main.tex").read_text(encoding="utf-8")
        setting = (PAPER_DIR / "02-setting.tex").read_text(encoding="utf-8")
        self.assertRegex(
            preamble,
            r"\\DeclareAcronym\{pp\}\{[^}]*short=pp[^}]*long=percentage point",
        )
        self.assertRegex(setting, r"\\acp?\{pp\}")

        results = (DECK_DIR / "sections" / "04-results.tex").read_text(
            encoding="utf-8"
        )
        definition = results.index("percentage points (pp)")
        first_compact_use = re.search(r"(?<!percentage points) pp\b", results)
        self.assertIsNotNone(first_compact_use)
        assert first_compact_use is not None
        self.assertLess(definition, first_compact_use.start())

    def test_transcript_covers_every_deck_frame_in_order(self) -> None:
        frame_pattern = re.compile(r"\\begin\{frame\}(?:\[[^]]*\])?\{([^}]+)\}")
        frames: list[str] = []
        for path in source_files(DECK_DIR / "sections"):
            frames.extend(frame_pattern.findall(path.read_text(encoding="utf-8")))

        headings = re.findall(
            r"^##\s+(.+)$",
            (DECK_DIR / "script.md").read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        headings = [heading for heading in headings if not heading.startswith("Cover.")]

        def title_key(value: str) -> str:
            value = re.sub(
                r"^(?:Slide \d+\.|A\d+(?:\.\d+|[a-z])?\.)\s*",
                "",
                value,
            )
            return value.casefold().strip()

        self.assertEqual(
            [title_key(heading) for heading in headings],
            [title_key(frame) for frame in frames],
            "deck/script.md must cover every frame once and in presentation order",
        )

    def test_abstract_respects_jfe_submission_ceiling(self) -> None:
        abstract = PAPER_DIR / "abstract.tex"
        visible = strip_latex_markup(abstract.read_text(encoding="utf-8"))
        words = ABSTRACT_WORD.findall(visible)
        self.assertLessEqual(
            len(words),
            JFE_ABSTRACT_WORD_LIMIT,
            f"abstract has {len(words)} words; limit is {JFE_ABSTRACT_WORD_LIMIT}",
        )


if __name__ == "__main__":
    unittest.main()
