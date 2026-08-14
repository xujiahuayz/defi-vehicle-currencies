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


if __name__ == "__main__":
    unittest.main()
