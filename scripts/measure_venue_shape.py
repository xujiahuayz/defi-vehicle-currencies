#!/usr/bin/env python3
"""What a JFE paragraph IS, measured, so a rewrite has something to aim at.

WHY THIS EXISTS ALONGSIDE THE BLACKLIST. `measure_prose_conventions.py` and
`find_prose_outliers.py` both answer one question: what does this draft over-use relative to
the published corpus? That question is subtractive. It names constructions to remove and it
never names a convention to acquire, so a draft can pass every deletion the two scripts ask
for and still read nothing like the venue, because deleting a tell does not install a shape.
Forty-two clean deletions moved the discovered-tell count by a third and moved both gates by
nothing at all, which is the signature of a corrective loop with no target.

So this measures the corpus POSITIVELY and reports target bands. Sentence length, clause
load, how many sentences carry no subordinate clause at all, paragraph length, and heading
grammar. A rewrite can hit a distribution. It cannot hit one by subtracting from a document
that never resembled it.

Both directions are needed and both are kept. The blacklist says which constructions are
disqualifying; this says what to write instead. A draft is finished when it sits inside
these bands AND clears the two discovery gates.

  python scripts/measure_venue_shape.py                    corpus bands, and the whole draft
  python scripts/measure_venue_shape.py --section 03       one section against the bands

Reads   ../defi-dominant-currency/lit/jfe-exemplars/*.pdf
        paper/sections/*.tex
Writes  output/exhibits/venue_shape.jsonl
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

EXEMPLARS = ROOT.parent / "defi-dominant-currency" / "lit" / "jfe-exemplars"
OUT = ROOT / "output" / "exhibits" / "venue_shape.jsonl"
BREW_PY = "/opt/homebrew/bin/python3"

# Flat get_text() emits line breaks and not paragraph breaks, so paragraph structure was
# unmeasurable and the first version of this script reported a corpus median of 265
# sentences per paragraph. Layout recovers it: the body left margin is the most common
# line-start x on a page, and a line beginning to the right of it is an indented first line,
# which is where a paragraph starts. That reads paragraphs on all 14 papers.
EXTRACT = r"""
import sys, fitz
from collections import Counter
d = fitz.open(sys.argv[1])
out, cur = [], []
for pg in d:
    lines = []
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            txt = " ".join(s["text"] for s in l["spans"]).strip()
            if txt:
                lines.append((round(l["bbox"][0], 1), txt))
    if not lines:
        continue
    margin = Counter(x for x, _ in lines).most_common(1)[0][0]
    for x, txt in lines:
        if x > margin + 4 and cur:
            out.append(" ".join(cur)); cur = []
        cur.append(txt)
if cur:
    out.append(" ".join(cur))
print("\n\n".join(out))
"""

# Markers of a subordinate clause. A sentence carrying none of these is a plain declarative,
# and the share of those is the single number that separates venue prose from memo prose.
SUBORD = re.compile(
    r"\b(?:because|since|while|whereas|although|though|unless|until|if|when|whenever|where|"
    r"wherever|whether|after|before|once|as long as|so that|given that|in order to)\b", re.I)
RELATIVE = re.compile(r",\s*(?:which|who|whose|whom)\b|\bwhich is\b|\bthat is\b", re.I)
ABBREV = re.compile(
    r"\b(?:e\.g|i\.e|cf|vs|et al|Fig|Figs|Eq|Eqs|Tab|No|pp|Ch|Sec|Prof|Dr|Mr|Mrs|Ms|St|Jr|Inc|Ltd)\.$",
    re.I)

WH = re.compile(r"^(?:What|Where|Whether|Why|Which|How|Who)\b")
NEG_HEAD = re.compile(r"\b(?:not|cannot|never|no)\b", re.I)
COMMA_TAIL = re.compile(r",\s+and\s+(?:what|where|why|whether|which|how)\b", re.I)


# --------------------------------------------------------------------------- text plumbing

def exemplar_text(path: Path) -> str:
    r = subprocess.run([BREW_PY, "-c", EXTRACT, str(path)],
                       capture_output=True, text=True, timeout=240)
    return r.stdout if r.returncode == 0 else ""


def corpus_paragraphs(text: str) -> list[str]:
    """Body paragraphs from a PDF text dump, with furniture removed.

    PDF extraction interleaves running heads, page numbers, table cells and the reference
    list with the prose. None of that is a sentence, and leaving it in makes the median
    sentence look far shorter than the venue actually writes.
    """
    cut = max(text.rfind("\nReferences"), text.rfind("\nREFERENCES"))
    if cut > len(text) * 0.4:
        text = text[:cut]
    text = re.sub(r"\(\s*\d{4}\s*\)", " ", text)          # year parentheticals
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split("\n"))
        block = re.sub(r"\s+", " ", block).strip()
        if len(block) < 200:
            continue
        letters = sum(c.isalpha() for c in block)
        if letters / max(len(block), 1) < 0.72:            # tables, formulas, headers
            continue
        if sum(c.isdigit() for c in block) / max(len(block), 1) > 0.06:
            continue
        out.append(block)
    return out


def draft_paragraphs(only: str | None = None) -> list[str]:
    """Prose paragraphs from the LaTeX sources.

    House style keeps each paragraph on ONE long line, so a paragraph is a long line that is
    not markup and not a comment. That makes paragraph boundaries exact here, where they are
    inferred for the corpus.
    """
    out = []
    for p in sorted((ROOT / "paper" / "sections").rglob("*.tex")):
        if only and not p.name.startswith(only):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("%") or s.startswith("\\") or len(s) < 200:
                continue
            if "&" in s or s.endswith("\\\\"):
                continue
            out.append(clean_tex(s))
    return [o for o in out if len(o) > 120]


def clean_tex(s: str) -> str:
    s = re.sub(r"\\(?:citep|citet|cite)\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:eq)?ref\{[^}]*\}", "1", s)
    s = re.sub(r"\$[^$]*\$", "x", s)
    s = re.sub(r"\\(?:emph|textit|texttt|textbf)\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", s)
    s = re.sub(r"[{}$\\]", " ", s)
    s = s.replace("~", " ")
    return re.sub(r"\s+", " ", s).strip()


def sentences(par: str) -> list[str]:
    parts, buf = [], ""
    for tok in re.split(r"(?<=[.!?])\s+", par):
        buf = (buf + " " + tok).strip() if buf else tok
        if ABBREV.search(buf) or re.search(r"\b[A-Z]\.$", buf):
            continue
        parts.append(buf)
        buf = ""
    if buf:
        parts.append(buf)
    return [p for p in parts if len(p.split()) >= 4]


# --------------------------------------------------------------------------- measurement

def shape(paras: list[str]) -> dict:
    sents, per_par = [], []
    for p in paras:
        ss = sentences(p)
        if not ss:
            continue
        per_par.append(len(ss))
        sents.extend(ss)
    if not sents:
        return {}
    lens = [len(s.split()) for s in sents]
    commas = [s.count(",") for s in sents]
    subs = [len(SUBORD.findall(s)) + len(RELATIVE.findall(s)) for s in sents]
    plain = [1 if n == 0 else 0 for n in subs]
    long40 = [1 if n > 40 else 0 for n in lens]
    return {
        "sentences": len(sents),
        "sent_len_median": median(lens),
        "sent_len_p90": sorted(lens)[int(len(lens) * 0.9)],
        "commas_per_sentence": sum(commas) / len(sents),
        "clauses_per_sentence": sum(subs) / len(sents),
        "plain_declarative_share": 100.0 * sum(plain) / len(sents),
        "over_40_words_share": 100.0 * sum(long40) / len(sents),
        "sentences_per_paragraph": sum(per_par) / len(per_par) if per_par else 0.0,
    }


def corpus_headings(texts: list[str]) -> list[str]:
    out = []
    for t in texts:
        out += [m.group(1).strip() for m in re.finditer(
            r"\n\s*\d{1,2}(?:\.\d{1,2})*\.?\s+([A-Z][A-Za-z ,:'\-]{6,70})\s*\n", t)]
    return out


def draft_headings(only: str | None = None) -> list[str]:
    out = []
    for p in sorted((ROOT / "paper" / "sections").rglob("*.tex")):
        if only and not p.name.startswith(only):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("%"):
                continue
            # Section titles ONLY. The corpus side of this comparison is recovered from
            # numbered section titles, and captions are a different register the venue
            # writes long. Pooling the two made the draft's headings look inflated when the
            # captions were doing it, and would have argued for shortening the wrong thing.
            m = re.search(r"\\(?:sub)*section\*?\{([^}]*)\}", line)
            if m:
                out.append(clean_tex(m.group(1)))
    return out


def heading_shape(hs: list[str]) -> dict:
    if not hs:
        return {}
    n = len(hs)
    return {
        "headings": n,
        "heading_words_median": median([len(h.split()) for h in hs]),
        "wh_opening_share": 100.0 * sum(bool(WH.match(h)) for h in hs) / n,
        "comma_tail_share": 100.0 * sum(bool(COMMA_TAIL.search(h)) for h in hs) / n,
        "negating_share": 100.0 * sum(bool(NEG_HEAD.search(h)) for h in hs) / n,
    }


FIELDS = [
    ("sent_len_median", "median sentence, words"),
    ("sent_len_p90", "90th pct sentence, words"),
    ("commas_per_sentence", "commas per sentence"),
    ("clauses_per_sentence", "subordinate clauses per sentence"),
    ("plain_declarative_share", "sentences with NO subordinate clause, %"),
    ("over_40_words_share", "sentences over 40 words, %"),
    ("sentences_per_paragraph", "sentences per paragraph"),   # corpus-side may be unusable
    ("heading_words_median", "median heading, words"),
    ("wh_opening_share", "headings opening on a wh-word, %"),
    ("comma_tail_share", "headings with a comma plus wh-clause, %"),
    ("negating_share", "headings that negate, %"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", help="measure one section file prefix, e.g. 03")
    args = ap.parse_args()

    pdfs = sorted(EXEMPLARS.glob("*.pdf"))
    if not pdfs:
        print(f"no exemplars under {EXEMPLARS}")
        return 1
    print(f"measuring {len(pdfs)} published papers, then the draft\n", flush=True)

    texts = [t for t in (exemplar_text(p) for p in pdfs) if t]
    per_paper = []
    for t in texts:
        s = shape(corpus_paragraphs(t))
        if s:
            per_paper.append(s)
    chead = heading_shape(corpus_headings(texts))

    label = args.section or "whole draft"
    dshape = shape(draft_paragraphs(args.section))
    dhead = heading_shape(draft_headings(args.section))
    if not dshape:
        print(f"no prose found for {label}")
        return 1

    print(f"  corpus: {len(per_paper)} papers, {sum(p['sentences'] for p in per_paper):,} "
          f"sentences; draft ({label}): {dshape['sentences']:,} sentences\n")
    print(f"  {'target':<44}{'p25':>8}{'median':>9}{'p75':>8}{'draft':>9}   verdict")

    rows, out_of_band = [], []
    for key, desc in FIELDS:
        if key in chead:
            vals = [chead[key]]
            lo = hi = med = chead[key]
        else:
            vals = sorted(p[key] for p in per_paper)
            lo = vals[int(len(vals) * 0.25)]
            med = median(vals)
            hi = vals[int(len(vals) * 0.75)]
        d = dhead.get(key, dshape.get(key))
        if d is None:
            continue
        # Paragraph boundaries survive in the LaTeX and are lost in PDF extraction, which
        # collapses a paper into one block. A band built from that is an artefact, so the
        # metric is reported for the draft and withheld as a target.
        if key == "sentences_per_paragraph" and med > 30:
            print(f"  {desc:<44}{'n/a':>8}{'n/a':>9}{'n/a':>8}{d:>9.1f}   "
                  f"not recoverable from PDF")
            rows.append({"metric": key, "description": desc, "corpus_p25": None,
                         "corpus_median": None, "corpus_p75": None, "draft": d,
                         "section": label, "verdict": "no corpus target"})
            continue
        # The aim is the venue's interquartile range. Half the published papers sit inside
        # it by construction, which is the right standard for something to write toward.
        inside = lo <= d <= hi if hi > 0 else d <= 0.5
        if not inside:
            out_of_band.append((desc, d, lo, hi))
        print(f"  {desc:<44}{lo:>8.1f}{med:>9.1f}{hi:>8.1f}{d:>9.1f}   "
              f"{'in band' if inside else 'OUT'}")
        rows.append({"metric": key, "description": desc, "corpus_p25": lo,
                     "corpus_median": med, "corpus_p75": hi, "draft": d,
                     "section": label, "verdict": "in band" if inside else "out of band"})

    print()
    if out_of_band:
        print(f"{len(out_of_band)} target(s) the draft misses:")
        for desc, d, lo, hi in out_of_band:
            print(f"  {desc}: draft {d:.1f}, venue writes between {lo:.1f} and {hi:.1f}")
        print("\nThese are shapes to WRITE, and the discovery gates stay in force on top:")
        print("  scripts/measure_prose_conventions.py   constructions to avoid")
        print("  scripts/find_prose_outliers.py         tells nobody named in advance")
    else:
        print("The draft sits inside every measured shape band of the venue.")
    write_exhibit(__import__("pandas").DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 1 if out_of_band else 0


if __name__ == "__main__":
    sys.exit(main())
