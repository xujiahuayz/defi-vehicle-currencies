#!/usr/bin/env python3
"""Which constructions does this draft use at rates published papers do not?

WHY THIS IS NOT A BLACKLIST. Every stylistic tell caught so far was patched by hand: em
dashes banned, then "rather than", then contrast-confirmation, then the trailing appositive
in "Venue coverage, signed" where the venue would write "Signed venue coverage". Java's
objection to that pattern of fixes is the right one, since a list maintained one incident at
a time only ever catches the tells someone already noticed, and the next one arrives
unlabelled.

The general method asks a different question. For any construction that can be expressed as
a pattern, measure its rate per thousand words in the 14 published papers, and measure the
same rate in the draft. A construction the corpus uses freely is a convention of the field.
One the corpus almost never uses and the draft uses repeatedly is a tell, whoever wrote it.
The judgement moves from a person's taste to a comparison, and a new construction can be
added to the probe list without anyone deciding in advance whether it is bad.

That also settles disputes in the other direction. Several constructions that read as
"AI-ish" turn out to be entirely normal in this literature, and the corpus says so, which
stops the house style from drifting into something no published paper resembles.

Reads   literature/pdf-sources.json and the registered JFE exemplar PDFs
        paper/sections/*.tex, deck/**/*.tex
Writes  output/exhibits/prose_conventions.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS_DIR = (ROOT / "paper" / "sections") if (ROOT / "paper" / "sections").is_dir() else (ROOT / "memo" / "sections")

from ddvc.tables import write_exhibit  # noqa: E402
from ddvc.latex_text import strip_latex_markup  # noqa: E402
from ddvc.venue_corpus import resolve_venue_corpus  # noqa: E402

OUT = ROOT / "output" / "exhibits" / "prose_conventions.jsonl"
BREW_PY = "/opt/homebrew/bin/python3"

# Each probe is (name, pattern, what it looks like). Patterns run over plain prose, so they
# must not depend on LaTeX markup. Adding a probe requires no judgement about whether the
# construction is bad: the corpus decides.
PROBES: list[tuple[str, str, str]] = [
    ("trailing_appositive",
     r"[a-z]{4,},\s+(?:signed|measured|stated|revisited|reconsidered|explained|compared|"
     r"quantified|formalised|formalized|derived|extended|refined|revised)\b",
     "'Venue coverage, signed' where the venue writes 'Signed venue coverage'"),
    ("em_dash", r"\u2014", "em dash"),
    ("en_dash_in_prose", r"(?<=[a-z])\u2013(?=[a-z])", "en dash between words"),
    ("contrast_confirmation",
     r"\bnot\b[^.;]{2,40},\s*(?:but|it'?s|it is|this is)\b",
     "'not X, but Y'"),
    ("rather_than", r"\brather than\b", "'rather than'"),
    ("genuinely", r"\bgenuinely\b", "'genuinely'"),
    ("what_matters", r"\bwhat matters\b|\bmatters\b", "'matters' as a verb"),
    ("it_is_worth", r"\bit is worth (?:noting|stating|saying)\b", "'it is worth noting'"),
    ("importantly", r"\b(?:Importantly|Notably|Crucially|Critically)\b,", "sentence-initial adverb plus comma"),
    ("triple_list",
     r"\b\w+,\s+\w+,\s+and\s+\w+\b", "three-item parallel list"),
    ("so_that_tail", r",\s+so\s+(?:it|this|that|the)\b", "trailing 'so ...' justification"),
    ("document_self_reference",
     r"\bthis (?:paper|section|subsection|table|figure) (?:does|asks|establishes|shows that|is stated)\b",
     "the document describing itself"),
    ("screen_word", r"\bscreen(?:s|ed|ing)?\b", "'screen' as noun or verb"),
    ("against_prep", r"\bagainst\b", "'against' as a preposition"),
    ("what_cleft",
     r"\bwhat\s+(?:\w+\s+){0,3}?(?:is|are|was|were|does|do|did|means|makes|shows|matters|follows|remains|survives|holds)\b",
     "'what X does' cleft construction"),
    ("negation_periphrastic",
     r"\b(?:does|do|did|is|are|was|were|can|could|would|will|has|have|had)\s+not\b|\bcannot\b",
     "periphrastic negation, 'does not X'"),
    ("not_any", r"\bnot\b", "any use of 'not'"),
    ("neither_nor", r"\bneither\b|\bnor\b", "'neither ... nor'"),
    ("hedging_stack", r"\b(?:may|might|could) (?:possibly|perhaps|arguably)\b", "stacked hedges"),
]

EXTRACT = r"""
import sys, fitz
d = fitz.open(sys.argv[1])
print("".join(p.get_text() for p in d))
"""


def exemplar_text(path: Path) -> str:
    r = subprocess.run([BREW_PY, "-c", EXTRACT, str(path)],
                       capture_output=True, text=True, timeout=180)
    return r.stdout if r.returncode == 0 else ""


def draft_text() -> str:
    parts = []
    for d in (SECTIONS_DIR, ROOT / "deck"):
        for p in sorted(d.rglob("*.tex")) if d.exists() else []:
            body = "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines()
                             if not ln.lstrip().startswith("%"))
            parts.append(body)
    return strip_latex_markup("\n".join(parts))


def rate(text: str, pattern: str) -> float:
    words = max(len(text.split()), 1)
    return 1000.0 * len(re.findall(pattern, text, flags=re.IGNORECASE)) / words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tolerance", type=float, default=1.0,
                    help="multiple of the exemplar maximum the draft may reach")
    args = ap.parse_args()

    corpus = resolve_venue_corpus()
    if corpus.missing:
        print("missing canonical JFE exemplars: " + ", ".join(corpus.missing))
        return 1
    pdfs = list(corpus.pdfs)
    print(f"measuring {len(pdfs)} published papers, then the draft\n", flush=True)

    texts = [t for t in (exemplar_text(p) for p in pdfs) if t]
    if not texts:
        print("could not read the exemplars")
        return 1
    draft = draft_text()

    rows, flagged = [], []
    print(f"  {'construction':<28}{'corpus med':>12}{'corpus max':>12}"
          f"{'draft':>10}{'verdict':>12}")
    for name, pattern, _desc in PROBES:
        corpus = sorted(rate(t, pattern) for t in texts)
        med = corpus[len(corpus) // 2]
        mx = corpus[-1]
        d = rate(draft, pattern)
        over = d > max(mx * args.tolerance, 1e-9) and d > med
        verdict = "OVERUSED" if over else "in range"
        if over:
            flagged.append((name, d, mx))
        print(f"  {name:<28}{med:>12.3f}{mx:>12.3f}{d:>10.3f}{verdict:>12}")
        rows.append({"construction": name, "corpus_median": med, "corpus_max": mx,
                     "corpus_min": corpus[0], "draft": d, "verdict": verdict})

    print()
    if flagged:
        print(f"{len(flagged)} construction(s) used at a rate no published paper reaches:")
        for name, d, mx in flagged:
            desc = next(x[2] for x in PROBES if x[0] == name)
            print(f"  {name}: draft {d:.3f} per 1,000 words against a corpus maximum of "
                  f"{mx:.3f}  ({desc})")
        print("\nThese are the tells. A construction the corpus uses freely is a convention")
        print("of the field and is left alone whatever it sounds like.")
    else:
        print("No construction exceeds what the published corpus does. Constructions that")
        print("read as artificial but sit inside the corpus range are conventions here.")
    write_exhibit(__import__("pandas").DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
