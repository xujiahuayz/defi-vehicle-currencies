#!/usr/bin/env python3
"""Which KNOWN constructions does this draft use at rates published papers do not?

WHY THIS IS NOT A BLACKLIST. Every stylistic tell caught so far was patched by hand: em
dashes banned, then "rather than", then contrast-confirmation, then the trailing appositive
in "Venue coverage, signed" where the venue would write "Signed venue coverage". Java's
objection to that pattern of fixes is the right one, since a list maintained one incident at
a time only ever catches the tells someone already noticed, and the next one arrives
unlabelled.

This script asks a deliberately narrower question. For any construction already expressed
as a pattern, it measures the rate per thousand words in the 14 published papers and in the
draft. A construction the corpus uses freely should not be banned merely because somebody
dislikes it. One the corpus rarely uses and the draft repeats is an alarm. For the registered
negation family, the reference is the second-highest published-paper rate, so one corpus
outlier cannot mask a draft-wide rhetorical habit. The result says nothing about an
unregistered construction, a one-off use below the frequency threshold, or the rhetorical
function a word performs in its paragraph.

The script is therefore a final diagnostic, not a writing method and not evidence that prose
sounds like a JFE article. Paragraph organization must be reviewed against the raw passages
named in `README.md`; local substitutions do not close that review.

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

ROOT = Path(__file__).resolve().parents[2]

SECTIONS_DIR = (ROOT / "paper" / "sections") if (ROOT / "paper" / "sections").is_dir() else (ROOT / "memo" / "sections")

from ddvc.tables import write_report  # noqa: E402
from ddvc.latex_text import included_section_files, strip_latex_markup  # noqa: E402
from ddvc.venue_corpus import resolve_venue_corpus  # noqa: E402

OUT = ROOT / "output" / "exhibits" / "prose_conventions.jsonl"
BREW_PY = "/opt/homebrew/bin/python3"
DRAFT_FILES = included_section_files(SECTIONS_DIR.parent / "main.tex", fallback_dir=SECTIONS_DIR)

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

# Negation is an ensemble property: titles, topic sentences, result statements, and
# limitations can each be locally defensible while the whole paper still reads as a
# sequence of denials. Use a leave-one-out upper-tail reference for this family rather
# than letting the most negation-heavy published paper define the rule by itself.
ENSEMBLE_TAIL_PROBES = {
    "negation_periphrastic",
    "not_any",
    "neither_nor",
}

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
    # The reference corpus is journal articles. Deck prose is a different register and
    # must be judged against the registered presentation corpus, not mixed into a paper
    # denominator where short slide fragments distort every rate.
    for p in DRAFT_FILES:
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
    print(f"  {'construction':<28}{'corpus med':>12}{'corpus ref':>12}"
          f"{'draft':>10}{'verdict':>12}")
    for name, pattern, _desc in PROBES:
        corpus = sorted(rate(t, pattern) for t in texts)
        med = corpus[len(corpus) // 2]
        mx = corpus[-1]
        reference = corpus[-2] if name in ENSEMBLE_TAIL_PROBES and len(corpus) > 1 else mx
        d = rate(draft, pattern)
        over = d > max(reference * args.tolerance, 1e-9) and d > med
        verdict = "OVERUSED" if over else "in range"
        if over:
            flagged.append((name, d, reference))
        print(f"  {name:<28}{med:>12.3f}{reference:>12.3f}{d:>10.3f}{verdict:>12}")
        rows.append({"construction": name, "corpus_median": med, "corpus_max": mx,
                     "corpus_reference": reference, "corpus_min": corpus[0],
                     "draft": d, "verdict": verdict})

    print()
    if flagged:
        print(f"{len(flagged)} construction(s) used above the registered corpus reference:")
        for name, d, reference in flagged:
            desc = next(x[2] for x in PROBES if x[0] == name)
            print(f"  {name}: draft {d:.3f} per 1,000 words against a corpus reference of "
                  f"{reference:.3f}  ({desc})")
        print("\nThese are alarms for whole-thought review. A construction the corpus uses")
        print("freely is not banned by this test, but context and paragraph function still matter.")
    else:
        print("No REGISTERED construction exceeds its published-corpus reference. This result")
        print("does not assess unregistered phrasing, word sense, or paragraph organization.")
    write_report(__import__("pandas").DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
