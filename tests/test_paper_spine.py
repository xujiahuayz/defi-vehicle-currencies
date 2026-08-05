"""Gates on the node G paper spine.

The spine is a prose deliverable, so the tests that matter here are the house-voice
and structural ones. They exist because version 1 of this project shipped a deck
whose stylistic tells were only noticed after three review rounds, and because a
spine that loses its section architecture or its convergence sections stops being
usable by nodes F and H.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPINE_PATH = ROOT / "docs" / "paper-spine.md"

# Tells calibrated against the JFE corpus plus the house-voice blocklist.
BANNED_SUBSTRINGS = (
    "—",  # em dash
    "–",  # en dash
    "rather than",
    "genuinely",
    "deliberate",
)

# Contrast-confirmation, e.g. "not a defect, it is the finding".
CONTRAST_CONFIRMATION = re.compile(
    r"\bnot\b[^.;]{2,40},\s*(but|it'?s|it is|this is)\b",
    flags=re.IGNORECASE,
)

# A p-value must be a bare three-decimal parenthesis, never "p < 0.01".
LOOSE_P_VALUE = re.compile(r"\bp\s*[<>=]", flags=re.IGNORECASE)
BARE_P_VALUE = re.compile(r"\(\d\.\d{3}\)")


def is_structural_markdown(line: str) -> bool:
    return bool(
        line.startswith(("#", "|", "- ", "```", r"\["))
        or re.match(r"^\d+\. ", line)
        or re.match(r"^\s", line)
    )


def prose_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or is_structural_markdown(line):
            continue
        out.append((number, line))
    return out


class PaperSpineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SPINE_PATH.read_text(encoding="utf-8")

    def test_prose_is_not_hard_wrapped(self) -> None:
        lines = self.text.splitlines()
        in_fence = False
        for number, (current, following) in enumerate(zip(lines, lines[1:]), start=1):
            if current.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence or not current or not following:
                continue
            if is_structural_markdown(current) or is_structural_markdown(following):
                continue
            self.fail(f"hard-wrapped Markdown prose at lines {number}-{number + 1}")

    def test_no_banned_stylistic_tells(self) -> None:
        lowered = self.text.lower()
        for banned in BANNED_SUBSTRINGS:
            with self.subTest(banned=banned):
                self.assertNotIn(banned.lower(), lowered)

    def test_no_contrast_confirmation(self) -> None:
        for number, line in prose_lines(self.text):
            match = CONTRAST_CONFIRMATION.search(line)
            if match:
                self.fail(f"contrast-confirmation at line {number}: {match.group(0)!r}")

    def test_p_values_are_bare_parentheses(self) -> None:
        for number, line in prose_lines(self.text):
            match = LOOSE_P_VALUE.search(line)
            if match:
                self.fail(f"loose p-value notation at line {number}: {match.group(0)!r}")
        self.assertTrue(BARE_P_VALUE.search(self.text))

    def test_section_architecture_is_seven_sections_ending_in_a_conclusion(self) -> None:
        """Seven, not six, and the seventh is evidence and not drift.

        The corpus re-derivation off `literature/text/*.txt` found Makarov and Schoar's
        section 8, "Discussion of arbitrages and constraints", a top-level defence of the
        measured object sitting immediately before their conclusion. This paper's object
        is a counterfactual quote for a route nobody executed, so it takes the same slot.
        Seven top-level sections is inside the observed band of 4 to 9 and matches two of
        the nine papers read. The gate holds the band and the terminal conclusion.
        """
        block = re.search(r"```\n(1\. Introduction.*?)```", self.text, flags=re.DOTALL)
        self.assertIsNotNone(block, "the architecture block is missing")
        top_level = re.findall(r"^(\d)\. (.+?)(?:\s{2,}|$)", block.group(1), flags=re.MULTILINE)
        self.assertEqual([n for n, _ in top_level], ["1", "2", "3", "4", "5", "6", "7"])
        self.assertTrue(top_level[-1][1].startswith("Conclusion"))
        self.assertIn("Are the measured gaps real?", block.group(1))

    def test_definitions_live_in_a_numbered_subsection(self) -> None:
        self.assertIn("2.2 Definitions", self.text)
        definitions = re.findall(r"^\*\*Definition (\d+),", self.text, flags=re.MULTILINE)
        self.assertEqual(definitions, [str(index) for index in range(1, len(definitions) + 1)])
        self.assertGreaterEqual(len(definitions), 10)

    def test_every_claim_row_carries_an_evidentiary_status(self) -> None:
        rows = [
            line
            for line in self.text.splitlines()
            if line.startswith("| ") and line.count("|") >= 5
        ]
        claim_rows = [row for row in rows if "EXISTS" in row or "PENDING" in row]
        self.assertGreaterEqual(len(claim_rows), 30)

    def test_convergence_sections_are_present_and_last(self) -> None:
        headings = re.findall(r"^## (.+)$", self.text, flags=re.MULTILINE)
        self.assertEqual(headings[-2:], ["What G needs from F", "What G needs from H"])

    def test_horse_race_names_its_rivals(self) -> None:
        rivals = re.findall(r"^### 5\.\d (.+)$", self.text, flags=re.MULTILINE)
        self.assertEqual(len(rivals), 5)
        self.assertEqual(rivals[-1], "What survives")

    def test_superseded_outline_is_deleted(self) -> None:
        self.assertFalse((ROOT / "paper" / "jfe_detailed_outline.md").exists())


if __name__ == "__main__":
    unittest.main()
