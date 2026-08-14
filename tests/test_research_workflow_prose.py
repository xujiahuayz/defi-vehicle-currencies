from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs" / "research-workflow.md"


def is_structural_markdown(line: str, *, in_fence: bool) -> bool:
    stripped = line.lstrip()
    return bool(
        in_fence
        or stripped.startswith(("#", "|", "- ", "* ", "+ ", ">", "```", "~~~", r"\[", r"\]", "$$"))
        or re.match(r"^\d+[.)] ", stripped)
    )


class ResearchWorkflowProseTests(unittest.TestCase):
    def test_prose_is_not_hard_wrapped(self) -> None:
        lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
        in_fence = False
        structural: list[bool] = []
        for line in lines:
            structural.append(is_structural_markdown(line, in_fence=in_fence))
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence

        for number, ((current, following), (current_structural, following_structural)) in enumerate(
            zip(zip(lines, lines[1:]), zip(structural, structural[1:])), start=1
        ):
            if not current or not following:
                continue
            if current_structural or following_structural:
                continue
            self.fail(f"hard-wrapped Markdown prose at lines {number}-{number + 1}")

    def test_method_selection_contract_names_every_required_dimension_and_family(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("- **Method selection follows the estimand, never a battery.**")
        end = text.index("- **One economic choice gets one primary vote.**", start)
        contract = text[start:end]
        required_dimensions = (
            "Estimand",
            "Unit or risk set and identifying variation",
            "Dependence and inference",
            "Falsifier",
            "Current support state",
            "Presentation destination",
        )
        required_families = (
            "Paired daily change with calendar HAC",
            "Denominator-mass WLS with matched fixed effects",
            "Grouped-binomial share model",
            "PPML utilisation model",
            "Block-bootstrap ECDF and quantile comparison",
            "Discrete-time logit or complementary-log-log hazard",
            "Cox is not primary",
            "DiD or exposure event study",
            "iid t-test, textbook KS, or route-level binary logit",
        )
        for phrase in (*required_dimensions, *required_families):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)


if __name__ == "__main__":
    unittest.main()
