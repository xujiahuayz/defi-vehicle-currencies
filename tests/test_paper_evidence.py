"""Every number in the paper must name an artefact, and that artefact must exist.

An adversarial audit checked roughly 290 numeric claims in the paper by hand and found 22
defects. Most were not arithmetic. They were right numbers describing the wrong population,
a four-day figure standing as the headline of a 2,277-day study, a share of swaps quoted as
a share of senders, a superseded exhibit still being cited. That class survives casual
checking precisely because the number IS in the source someone looks at.

A test cannot judge whether a sample is correctly described. It can enforce the two
conditions that made the audit possible at all: a numeric claim has to carry an
evidence-source comment, and the artefact that comment names has to exist on disk. This
keeps every paper-facing number inspectable from its current producing output.

What this deliberately does NOT do is verify values, because a check that greps the cited
file for the digits would pass on a number that appears there in a different role, which is
several of the defects the audit found. Value checking stays human, and this keeps the
conditions that make it feasible.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS_DIR = (ROOT / "paper" / "sections") if (ROOT / "paper" / "sections").is_dir() else (ROOT / "memo" / "sections")
SECTIONS = SECTIONS_DIR

# A claim worth sourcing. Bare small integers ("two arms", "section 3", "four days") are
# structural prose and not measurements, so the threshold is a decimal, a percentage, a
# thousands separator, or a currency amount.
NUMERIC = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+\\%|\\\$[\d,]+)")

# An evidence-source comment names a path under output/, docs/, scripts/, src/ or data/.
# Trailing punctuation belongs to the prose around the path, not to the path. Leaving it
# in made this test report a dozen files as missing that were all present, which is a
# gate that cries wolf and gets ignored.
# The class includes a backslash because paths written inside \texttt{} carry escaped
# underscores; without it the match truncates at the first one and reports a file that is
# present as missing.
EVIDENCE_PATH = re.compile(r"(?:output|docs|scripts|src|data|literature)/[\w./{},*\\-]+")

# Section 7 restates section 3 in words and asserts no new numbers in its own header, and
# the abstract carries none by venue convention. Both are exempt from the comment rule.
EXEMPT = {"07-conclusion.tex", "abstract.tex"}


def paragraphs(text: str) -> list[tuple[int, str, str]]:
    """(line number, prose, the comment block immediately following it)."""
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("%") or line.lstrip().startswith("\\"):
            i += 1
            continue
        comments = []
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith("%"):
            comments.append(lines[j])
            j += 1
        out.append((i + 1, line, "\n".join(comments)))
        i = max(j, i + 1)
    return out


class PaperEvidenceTests(unittest.TestCase):
    def sources(self) -> list[Path]:
        return sorted(SECTIONS.glob("*.tex")) if SECTIONS.exists() else []

    def test_numeric_paragraphs_name_an_evidence_source(self) -> None:
        missing: list[str] = []
        for path in self.sources():
            if path.name in EXEMPT:
                continue
            for lineno, prose, comment in paragraphs(path.read_text(encoding="utf-8")):
                nums = NUMERIC.findall(prose)
                if not nums:
                    continue
                if not EVIDENCE_PATH.search(comment):
                    missing.append(f"{path.name}:{lineno} carries {len(nums)} numeric "
                                   f"claim(s) with no artefact named: {nums[:3]}")
        self.assertEqual(missing, [], "\n" + "\n".join(missing))

    def test_every_cited_artefact_exists(self) -> None:
        absent: list[str] = []
        for path in self.sources():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.lstrip().startswith("%"):
                    continue
                for ref in EVIDENCE_PATH.findall(line):
                    ref = ref.rstrip('.,;:}').replace('\\_', '_').rstrip('}')
                    # A brace expansion names several siblings at once.
                    if "{" in ref:
                        head, rest = ref.split("{", 1)
                        names = rest.split("}", 1)[0].split(",")
                        tail = rest.split("}", 1)[1] if "}" in rest else ""
                        candidates = [f"{head}{n}{tail}" for n in names]
                    else:
                        candidates = [ref]
                    for c in candidates:
                        if "*" in c:
                            if not list(ROOT.glob(c)):
                                absent.append(f"{path.name}:{lineno} no match for {c}")
                        elif not (ROOT / c).exists():
                            absent.append(f"{path.name}:{lineno} missing {c}")
        self.assertEqual(absent, [], "\n" + "\n".join(absent))


if __name__ == "__main__":
    unittest.main()
