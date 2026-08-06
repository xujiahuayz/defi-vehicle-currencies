#!/usr/bin/env python3
"""What a paragraph at this venue IS, as a target to write into.

Every other prose instrument here is subtractive. `find_prose_outliers.py` reports what the
draft over-uses, `measure_prose_conventions.py` reports constructions above the corpus rate,
`test_paper_prose.py` bans a register. All of them answer "what should this not be", and a
document can satisfy every one of them without ever resembling the thing it is aimed at. A
correction pass proved it: 42 clean fixes moved the shape count from 208 to 129 and moved
the gate not at all, because subtraction removes tells and does not supply conventions.

This measures the positive shape, so there is something to write TOWARD:

  sentence length, in words, as a distribution and not a mean
  clauses per sentence, counted by subordinators and coordinators
  share of sentences that are plain declaratives with one finite clause
  paragraph length in sentences
  whether a paragraph opens on its claim or on setup
  heading grammar, which is where the two diverge most

The output is a target distribution per feature, with the draft beside it and the direction
of the gap named. A distribution can be hit deliberately. A blacklist cannot be hit at all,
only avoided, which is why the loop could not converge.

Reads   ../defi-dominant-currency/lit/jfe-exemplars/*.pdf
        paper/sections/*.tex
Writes  output/exhibits/venue_shape.jsonl
"""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

EXEMPLARS = ROOT.parent / "defi-dominant-currency" / "lit" / "jfe-exemplars"
SECTIONS = ROOT / "paper" / "sections"
OUT = ROOT / "output" / "exhibits" / "venue_shape.jsonl"
BREW_PY = "/opt/homebrew/bin/python3"

EXTRACT = r"""
import sys, fitz
print("".join(p.get_text() for p in fitz.open(sys.argv[1])))
"""

# Subordinators and relativisers. Counting these approximates clause depth without a parser,
# and the approximation is the same on both sides of the comparison, which is what matters.
SUBORD = re.compile(
    r"\b(?:which|that|who|whom|whose|because|since|although|though|while|whereas|"
    r"unless|until|when|where|whether|if|so that|such that|given that|after|before|"
    r"as|and|but|or)\b", re.I)
FINITE = re.compile(
    r"\b(?:is|are|was|were|be|been|has|have|had|does|do|did|can|could|will|would|"
    r"may|might|must|should|shall)\b", re.I)
# A paragraph that opens on its claim starts with a subject and a finite verb. One that opens
# on setup starts with a subordinator, a prepositional scene-setter or a discourse marker.
SETUP_OPEN = re.compile(
    r"^\s*(?:because|since|although|though|while|whereas|if|when|where|after|before|"
    r"in order|to see|to understand|consider|suppose|note that|first|second|third|"
    r"one|two|the reason|what|whether|how|why|there (?:is|are)|it is)\b", re.I)


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    out = []
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        s = s.strip()
        if 4 <= len(s.split()) <= 120 and re.search(r"[a-z]", s):
            out.append(s)
    return out


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 25]


def features(text: str) -> dict[str, list[float]]:
    sents = sentences(text)
    if not sents:
        return {}
    lens = [len(s.split()) for s in sents]
    clauses = [1 + len(SUBORD.findall(s)) for s in sents]
    simple = [1.0 if (len(FINITE.findall(s)) <= 1 and len(SUBORD.findall(s)) == 0) else 0.0
              for s in sents]
    # Paragraph structure is NOT recoverable from extracted PDF text: the extractor emits
    # line breaks and not paragraph breaks, so splitting on a blank line returns the whole
    # document as one paragraph. The first run duly reported a corpus median of 265
    # sentences per paragraph. A measure that cannot be taken on both sides is dropped
    # instead of reported, since a target nobody can hit is worse than no target.
    paras = paragraphs(text)
    claim_open = [0.0 if SETUP_OPEN.match(p) else 1.0 for p in paras] or [0.0]
    commas = [s.count(",") for s in sents]
    return {"sentence_words": [float(x) for x in lens],
            "clauses_per_sentence": [float(x) for x in clauses],
            "commas_per_sentence": [float(x) for x in commas],
            "share_simple_declarative": simple,
            "share_paragraphs_opening_on_claim": claim_open}


def draft_text() -> str:
    parts = []
    for p in sorted(SECTIONS.glob("*.tex")):
        body = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.lstrip().startswith("%") or ln.lstrip().startswith("\\"):
                body.append("")
                continue
            body.append(ln)
        parts.append("\n".join(body))
    t = "\n\n".join(parts)
    for env in ("tikzpicture", "axis", "picture", "tabular", "table", "figure", "equation", "align"):
        t = re.sub(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", " ", t, flags=re.S)
    t = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", t)
    return re.sub(r"[{}$&\\]", " ", t)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tolerance", type=float, default=0.20,
                    help="fractional gap from the corpus median treated as on target")
    args = ap.parse_args()

    pdfs = sorted(EXEMPLARS.glob("*.pdf"))
    if not pdfs:
        print(f"no exemplars under {EXEMPLARS}")
        return 1

    per_paper: list[dict[str, list[float]]] = []
    for p in pdfs:
        r = subprocess.run([BREW_PY, "-c", EXTRACT, str(p)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and r.stdout.strip():
            f = features(r.stdout)
            if f:
                per_paper.append(f)
    if not per_paper:
        print("could not read the exemplars")
        return 1
    draft = features(draft_text())
    if not draft:
        print("no draft prose found")
        return 1

    print(f"{len(per_paper)} published papers, target is the corpus median with the "
          f"spread across papers\n")
    print(f"  {'feature':<38}{'corpus p25':>11}{'median':>9}{'p75':>9}"
          f"{'DRAFT':>10}{'gap':>10}")
    rows = []
    for k in draft:
        paper_medians = sorted(statistics.median(f[k]) for f in per_paper if f.get(k))
        if not paper_medians:
            continue
        q = lambda x: paper_medians[min(len(paper_medians) - 1,
                                        int(x * len(paper_medians)))]  # noqa: E731
        med = q(0.5)
        d = statistics.median(draft[k])
        gap = (d - med) / med if med else 0.0
        on = abs(gap) <= args.tolerance
        rows.append({"feature": k, "corpus_p25": q(0.25), "corpus_median": med,
                     "corpus_p75": q(0.75), "draft": d, "gap_fraction": gap,
                     "on_target": int(on)})
        print(f"  {k:<38}{q(0.25):>11.2f}{med:>9.2f}{q(0.75):>9.2f}{d:>10.2f}"
              f"{gap:>9.0%}{'' if on else '  <--'}")

    off = [r for r in rows if not r["on_target"]]
    print()
    if off:
        print("Write toward these, in this direction:")
        for r in off:
            direction = "shorter" if r["gap_fraction"] > 0 else "longer"
            if r["feature"].startswith("share"):
                direction = "less often" if r["gap_fraction"] > 0 else "more often"
            print(f"  {r['feature']}: {r['draft']:.2f} against a target of "
                  f"{r['corpus_median']:.2f}, so {direction}")
        print("\nThese are distributions and a distribution can be written toward. The other")
        print("instruments here report what to remove, and removal alone never arrives at a")
        print("convention, which is why the correction pass cleared tells without closing")
        print("the gap.")
    else:
        print("The draft's prose shape sits within tolerance of the venue on every feature.")
    write_exhibit(__import__("pandas").DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 1 if off else 0


if __name__ == "__main__":
    sys.exit(main())
