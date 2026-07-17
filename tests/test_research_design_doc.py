from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "research-questions-and-empirical-design.md"


def is_structural_markdown(line: str) -> bool:
    return bool(
        line.startswith(("#", "|", "- ", r"\["))
        or re.match(r"^\d+\. ", line)
    )


class ResearchDesignDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DESIGN_PATH.read_text(encoding="utf-8")

    def test_prose_is_not_hard_wrapped(self) -> None:
        lines = self.text.splitlines()
        for line_number, (current, following) in enumerate(zip(lines, lines[1:]), start=1):
            if not current or not following:
                continue
            if is_structural_markdown(current) or is_structural_markdown(following):
                continue
            self.fail(f"hard-wrapped Markdown prose at lines {line_number}-{line_number + 1}")

    def test_each_rq_has_literature_anchors_and_decision_rules(self) -> None:
        headings = re.findall(r"^## RQ(\d)\.", self.text, flags=re.MULTILINE)
        self.assertEqual(headings, ["1", "2", "3", "4", "5"])
        sections = re.split(r"^## RQ\d\. ", self.text, flags=re.MULTILINE)[1:]
        for rq, section in enumerate(sections, start=1):
            with self.subTest(rq=rq):
                self.assertIn("### Literature anchors", section)
                self.assertIn(f"### Decision rule for RQ{rq}", section)
                self.assertIn("**Potentially surprising result:**", section)

    def test_literature_types_are_not_overstated(self) -> None:
        self.assertIn("Li, Wang, and Ye (2021)", self.text)
        self.assertIn("Theory/model paper, not pure empirical", self.text)
        self.assertIn("Somogyi (2026)", self.text)
        self.assertIn("Model plus empirical evidence, not pure empirical", self.text)
        self.assertIn("Heimbach, Pahari, and Schertenleib (2024)", self.text)
        self.assertIn("Computer-science paper", self.text)
        self.assertIn("local corpus includes the published version", self.text)

    def test_design_remains_on_execution_hold(self) -> None:
        self.assertIn("## Execution hold", self.text)
        self.assertIn("Do not run or modify empirical experiment scripts", self.text)


if __name__ == "__main__":
    unittest.main()
