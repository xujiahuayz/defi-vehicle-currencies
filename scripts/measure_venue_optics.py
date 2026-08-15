#!/usr/bin/env python3
"""What a JFE paper LOOKS like, measured, and where this draft sits against it.

Java's objection, and it is correct: the draft reads as a process document and not as a
paper. It carries no tables, no figures, almost no citations, no notation, and no appendix,
and at 24 pages it is roughly half the typeset length of the venue's median before any
online appendix. Prose quality was gated from the first commit; the APPARATUS was not
gated at all, so it simply never got built.

Structure is not decoration here. A referee forms a judgement from the shape of a paper
before reading a sentence of it: how many exhibits, how dense the citation, whether the
objects are defined in symbols, whether there is an appendix carrying the machinery. A
paper that argues in continuous prose with nothing to look at reads as a memo.

So this measures the exemplars instead of asserting what they contain, and reports the
draft in the same units. Every target below is an empirical quantile of 14 published
papers, and the gate that consumes this file fails on the features that are absent
altogether, since a count of zero is a structural absence and not a stylistic preference.

Reads   literature/pdf-sources.json and the registered JFE exemplar PDFs
        paper/main.tex and paper/sections/*.tex
Writes  output/exhibits/venue_optics.jsonl
"""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS_DIR = (ROOT / "paper" / "sections") if (ROOT / "paper" / "sections").is_dir() else (ROOT / "memo" / "sections")

from ddvc.tables import write_exhibit  # noqa: E402
from ddvc.latex_text import included_section_files  # noqa: E402
from ddvc.venue_corpus import resolve_venue_corpus  # noqa: E402

SECTIONS = SECTIONS_DIR
OUT = ROOT / "output" / "exhibits" / "venue_optics.jsonl"

# Homebrew python carries PyMuPDF; the project venv does not, and adding it for a
# measurement script is not worth a dependency.
BREW_PY = "/opt/homebrew/bin/python3"

EXTRACT = r"""
import sys, re, json
# PyMuPDF >= 1.28 prints a deprecation warning to stdout on `import fitz`,
# which corrupts the JSON this script emits; the renamed module is silent.
import pymupdf as fitz
d = fitz.open(sys.argv[1])
text = "".join(p.get_text() for p in d)
low = text.lower()
# A displayed equation in a two-column PDF shows up as a line ending in a bare equation
# number. Inline maths is not countable this way and is not counted.
eqs = len(re.findall(r"\n\s*\(\d{1,2}(?:\.\d{1,2})?\)\s*\n", text))
out = {
  "pages": d.page_count,
  "tables": len(set(re.findall(r"\bTable\s+([IVX]+|\d{1,2})\b", text))),
  "figures": len(set(re.findall(r"\bFig(?:ure)?\.?\s+(\d{1,2})\b", text))),
  "equations": eqs,
  # Author-year citations, the dominant style at this venue.
  "citations": len(re.findall(r"\(\s*[A-Z][A-Za-z'-]+(?:\s+(?:et al\.|and\s+[A-Z][A-Za-z'-]+))?,?\s+(?:19|20)\d{2}[a-z]?\s*\)", text))
               + len(re.findall(r"[A-Z][A-Za-z'-]+(?:\s+et al\.| and [A-Z][A-Za-z'-]+)?\s+\(\s*(?:19|20)\d{2}[a-z]?\s*\)", text)),
  "has_appendix": int(bool(re.search(r"\n\s*Appendix\s+[A-Z1]?", text))),
  "words": len(text.split()),
  "greek": len(re.findall(r"[\u03b1-\u03c9\u0391-\u03a9]", text)),
  # Regression apparatus: a paper reporting conditional estimates says so in these words.
  "fixed_effects": len(re.findall(r"fixed effect", low)),
  "std_errors": len(re.findall(r"standard error|clustered|t-statistic|\bR2\b|R\u00b2|adjusted R", low)),
}
print(json.dumps(out))
"""


def measure_pdf(path: Path) -> dict | None:
    try:
        r = subprocess.run([BREW_PY, "-c", EXTRACT, str(path)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            return None
        import json
        return json.loads(r.stdout)
    except Exception:
        return None


def measure_draft() -> dict:
    """The same features, read off the LaTeX source and the compiled PDF."""
    files = included_section_files(SECTIONS_DIR.parent / "main.tex", fallback_dir=SECTIONS)
    tex = "\n".join(p.read_text(encoding="utf-8") for p in files)
    body = "\n".join(ln for ln in tex.splitlines() if not ln.lstrip().startswith("%"))
    pdf = SECTIONS_DIR.parent / "main.pdf"
    pages = 0
    if pdf.exists():
        got = measure_pdf(pdf)
        pages = got["pages"] if got else 0
    return {
        "pages": pages,
        "tables": len(re.findall(r"\\begin\{table", body)),
        "figures": len(re.findall(r"\\begin\{figure", body)),
        "equations": len(re.findall(r"\\begin\{(?:equation|align|gather)", body)),
        "citations": len(re.findall(r"\\cite[tp]?\*?\{", body)),
        "has_appendix": int(bool(re.search(r"\\appendix|\\section\{Appendix", body))),
        "words": len(re.sub(r"\\[a-zA-Z]+\*?|[{}$\\]", " ", body).split()),
        "greek": len(re.findall(r"\\(?:alpha|beta|gamma|delta|theta|lambda|mu|sigma|tau|phi|psi|omega|rho|pi|eta)\b", body)),
        "fixed_effects": len(re.findall(r"fixed effect", body, flags=re.IGNORECASE)),
        "std_errors": len(re.findall(r"standard error|clustered|t-statistic|R\^?2", body, flags=re.IGNORECASE)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    corpus = resolve_venue_corpus()
    if corpus.missing:
        print("missing canonical JFE exemplars: " + ", ".join(corpus.missing))
        return 1
    pdfs = list(corpus.pdfs)
    print(f"measuring {len(pdfs)} published papers\n", flush=True)

    got = []
    for p in pdfs:
        m = measure_pdf(p)
        if m:
            m["stem"] = p.stem
            got.append(m)
        else:
            print(f"  {p.stem}: could not read", flush=True)
    if not got:
        print("nothing measurable")
        return 1

    draft = measure_draft()
    fields = ["pages", "words", "tables", "figures", "equations", "citations", "greek",
              "fixed_effects", "std_errors"]
    print(f"  {'feature':<12}{'min':>8}{'p25':>8}{'median':>9}{'p75':>8}{'max':>8}"
          f"{'DRAFT':>9}{'verdict':>12}")
    rows = []
    for f in fields:
        vals = sorted(m[f] for m in got)
        q = lambda x: vals[min(len(vals) - 1, int(x * len(vals)))]  # noqa: E731
        d = draft[f]
        lo = q(0.25)
        verdict = "absent" if d == 0 and q(0.5) > 0 else ("below p25" if d < lo else "in range")
        print(f"  {f:<12}{vals[0]:>8,}{lo:>8,}{q(0.5):>9,}{q(0.75):>8,}{vals[-1]:>8,}"
              f"{d:>9,}{verdict:>12}")
        rows.append({"feature": f, "exemplar_min": vals[0], "exemplar_p25": lo,
                     "exemplar_median": q(0.5), "exemplar_p75": q(0.75),
                     "exemplar_max": vals[-1], "draft": d, "verdict": verdict})
    napp = sum(m["has_appendix"] for m in got)
    print(f"  {'appendix':<12}{'':>8}{'':>8}{f'{napp}/{len(got)}':>9}{'':>8}{'':>8}"
          f"{draft['has_appendix']:>9}"
          f"{('in range' if draft['has_appendix'] or napp <= len(got) / 2 else 'absent'):>12}")
    rows.append({"feature": "appendix", "exemplar_min": 0, "exemplar_p25": 0,
                 "exemplar_median": napp, "exemplar_p75": len(got), "exemplar_max": len(got),
                 "draft": draft["has_appendix"],
                 "verdict": "in range" if draft["has_appendix"] else "absent"})

    absent = [r["feature"] for r in rows if r["verdict"] == "absent"]
    below = [r["feature"] for r in rows if r["verdict"] == "below p25"]
    print()
    if absent:
        print(f"ABSENT ALTOGETHER: {', '.join(absent)}. A count of zero on a feature every")
        print("published paper in the sample carries is a structural gap and not a choice.")
    if below:
        print(f"Below the first quartile: {', '.join(below)}.")
    if not absent and not below:
        print("The draft sits inside the venue's range on every measured feature.")
    write_exhibit(__import__("pandas").DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
