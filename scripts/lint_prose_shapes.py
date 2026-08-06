#!/usr/bin/env python3
"""Lint the DELIVERABLES for rhetorical SHAPES, not words.

Word-level substitution is what produced "and never at economics" out of "and not at
economics": the term changed and the shape, correction-by-negation, survived intact. These
patterns match the shape, so a synonym cannot slip through, and every one of them is a
construction the corpus either never uses or uses far less than the draft.

Run before and after every rewrite. Counts must fall and never rise.
"""
import re, sys
from pathlib import Path

ROOT = Path("/Users/dsf-pro16-m3/projects/defi-vehicle-currencies")

SHAPES = [
    ("correction-by-negation",
     r"\b(?:and|,)\s+(?:and\s+)?(?:not|never|no)\s+(?:at|about|a|an|the|its|his|her|their|to|in|on|of|by|from|for|as|with|because|that|what|when|where|whether|it|this|these|those|onto|into)\b",
     "'X and not Y' / 'X and never Y' -- assert X positively and stop"),
    ("bare and-not", r"\band not\b", "'and not'"),
    ("wh-cleft is-what", r"\bis\s+what\b", "'X is what Y' -- say it directly"),
    ("wh-cleft what-the", r"\bwhat\s+the\s+\w+", "'what the X' -- name the X"),
    ("wh-cleft which-is", r"\bwhich is\b", "'..., which is Y' -- fold Y into the clause"),
    ("rhetorical-negation heading",
     r"\\(?:sub)*section\*?\{[^}]*\b(?:not|cannot|never|no)\b[^}]*\}|\\caption\{[^}]*\b(?:not|cannot|never)\b[^}]*\}",
     "heading that negates"),
    ("wh-word heading",
     r"\\(?:sub)*section\*?\{\s*(?:What|Where|Whether|Why|Which|How|Who)\b|\\caption\{\s*(?:What|Where|Whether|Why|Which|How|Who)\b"
     r"|\\begin\{frame\}\{\s*(?:What|Where|Whether|Why|Which|How|Who)\b",
     "heading opening on a wh-word"),
    ("comma-tail heading",
     r"\\(?:sub)*section\*?\{[^}]*,\s+and\s+(?:what|where|why|whether|which|how)\b"
     r"|\\caption\{[^}]*,\s+and\s+(?:what|where|why|whether|which|how)\b",
     "heading with a comma plus trailing wh-clause"),
    ("document self-reference",
     r"\b(?:this|the)\s+(?:paper|section|subsection|exercise)\s+(?:does|asks|claims|establishes|shows|reports|puts|takes|settles|measures|defends|gives|states)\b",
     "the document describing itself"),
    ("contrast-confirmation",
     r"\bnot\b[^.;]{2,40},\s*(?:but|it'?s|it is|this is)\b", "'not X, but Y'"),
]

def sources():
    out = []
    for d in (ROOT / "paper" / "sections", ROOT / "deck"):
        out += sorted(d.rglob("*.tex")) if d.exists() else []
    return out

def main() -> int:
    show = "-v" in sys.argv
    total = 0
    for name, pat, why in SHAPES:
        hits = []
        for f in sources():
            for ln, line in enumerate(f.read_text().splitlines(), 1):
                if line.lstrip().startswith("%"):
                    continue
                for m in re.finditer(pat, line, re.I):
                    a = max(0, m.start() - 60); b = min(len(line), m.end() + 60)
                    hits.append(f"      {f.name}:{ln}  ...{line[a:b]}...")
        total += len(hits)
        print(f"  {len(hits):>4}  {name:<28} {why}")
        if show:
            for h in hits:
                print(h)
    print(f"\n  {total} shape occurrence(s) total")
    return 0

if __name__ == "__main__":
    sys.exit(main())
