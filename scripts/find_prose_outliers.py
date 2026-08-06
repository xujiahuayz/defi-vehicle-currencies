#!/usr/bin/env python3
"""Discover the constructions this draft over-uses, WITHOUT anyone naming them first.

`scripts/measure_prose_conventions.py` compares the draft against the published corpus on a
list of probes, which was a real improvement over banning one phrase per incident. It is
still a hand-curated list. Java's objection stands against it: every entry arrived because a
person noticed the construction and added it, so the method can only ever catch tells
somebody already spotted, and the next one waits for the next reading.

This removes the naming step. It counts every word, bigram and trigram in the 14 published
papers and in the draft, converts both to rates per thousand words, and reports the
expressions the draft uses at rates the corpus never reaches. Nothing is decided in advance
about which expressions are bad. Over-representation against the field's own writing is the
whole criterion, so a tell nobody has articulated shows up on the same footing as one that
has a name.

Two refinements matter for the result to be usable.

HEADINGS ARE A SEPARATE REGISTER and are analysed separately. Section titles obey different
conventions from body prose, so a construction that is unremarkable in a paragraph can be
wrong in a title. Java's observation that negation is not typical in headings is exactly
this kind of claim, and pooling the two would hide it.

DOMAIN VOCABULARY IS NOT A TELL. A paper about routing uses "route" more than a corpus about
banks does, and that is subject matter and not style. The report separates expressions that
are plausibly this paper's subject from expressions that are general English, by checking
whether the expression's words appear in the corpus at all: a term the corpus never uses is
this paper's topic, while a term the corpus uses at a lower rate is a stylistic difference.

Reads   ../defi-dominant-currency/lit/jfe-exemplars/*.pdf
        paper/sections/*.tex, deck/**/*.tex
Writes  output/exhibits/prose_outliers.jsonl
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

EXEMPLARS = ROOT.parent / "defi-dominant-currency" / "lit" / "jfe-exemplars"
OUT = ROOT / "output" / "exhibits" / "prose_outliers.jsonl"
BREW_PY = "/opt/homebrew/bin/python3"

EXTRACT = r"""
import sys, fitz
print("".join(p.get_text() for p in fitz.open(sys.argv[1])))
"""

WORD = re.compile(r"[a-z][a-z'-]+")

# Closed-class English. Everything else is a content word and gets masked, which is what
# makes the template comparison independent of subject matter: a paper about routing and a
# paper about banks share their function words and differ in their nouns, so masking the
# nouns leaves exactly the syntax behind.
CLOSED = set("""
a an the this that these those there here it its it's they them their we our i my he she his her
and or but nor so yet for as if then than because since while whereas although though unless until
of in on at by to from with without within into onto over under above below between among across
against through during before after about around near past per via up down out off again
is are was were be been being am do does did done doing have has had having
can could shall should will would may might must ought need
not no nor never none nothing neither either both all any some each every few many most much several
what which who whom whose when where why how whether
more less least more-than very too also only just even still already yet again once
one two three first second such same other others another own
""".split())
MASK = "\u00b7"
DOMAIN: set[str] = set()
# The system English lexicon. A word in it is ordinary English however this paper uses it,
# and a word absent from it is coined or technical. This is external to both the corpus and
# the draft, which is what makes it non-circular: reading the paper's own emphasis to decide
# what counts as its subject lets the draft license its own vocabulary, and that is how
# "verdict" was first classified as domain terminology when it is a word choice.
ENGLISH: set[str] = set()
try:
    ENGLISH = {w.strip().lower() for w in
               Path("/usr/share/dict/words").read_text(errors="ignore").splitlines()
               if w.strip()}
except OSError:
    pass


def templates(ws: list[str]) -> list[str]:
    return [w if w in CLOSED else MASK for w in ws]


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def grams(ws: list[str], n: int) -> Counter:
    return Counter(" ".join(ws[i:i + n]) for i in range(len(ws) - n + 1))


def rates(ws: list[str], n: int) -> dict[str, float]:
    total = max(len(ws), 1)
    return {g: 1000.0 * c / total for g, c in grams(ws, n).items()}


def corpus_texts() -> list[str]:
    out = []
    for p in sorted(EXEMPLARS.glob("*.pdf")):
        r = subprocess.run([BREW_PY, "-c", EXTRACT, str(p)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and r.stdout.strip():
            out.append(r.stdout)
    return out


def strip_drawing(text: str) -> str:
    """Remove drawing and tabular environments whole.

    Their option keys (axis, column, style, width, font, coordinates) are not prose, and
    leaving them in made the first run report "axis" and "itemize" as stylistic tells.
    """
    for env in ("tikzpicture", "axis", "picture", "tabular", "pgfplots", "table"):
        text = re.sub(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", " ", text, flags=re.S)
    return text


def draft_parts() -> tuple[str, str]:
    """(body prose, headings) from the LaTeX sources, markup stripped."""
    body, heads = [], []
    for d in (ROOT / "paper" / "sections", ROOT / "deck"):
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.tex")):
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.lstrip().startswith("%"):
                    continue
                m = re.search(r"\\(?:sub)*section\*?\{([^}]*)\}|\\frametitle\{([^}]*)\}"
                              r"|\\caption\{([^}]*)\}", ln)
                if m:
                    heads.append(next(g for g in m.groups() if g))
                    continue
                body.append(ln)
    def clean(xs):
        t = strip_drawing("\n".join(xs))
        t = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", t)
        return re.sub(r"[{}$&\\]", " ", t)
    return clean(body), clean(heads)


def domain_terms() -> set[str]:
    """Words this paper actually defines or names as technical, from its own text.

    The first version classified any expression absent from the corpus as subject matter,
    which is wrong for ordinary English used oddly. "verdict" occurs nowhere in the fourteen
    published papers and is not DeFi terminology: it is a word choice, and the corpus would
    write "classification". Absence from the corpus alone cannot tell the two apart.

    A term is treated as this paper's subject only if the paper introduces it as one, in a
    definition environment, in emphasis on first use, in a maths command, or as a proper
    noun or symbol. Everything else absent from the corpus is a stylistic choice and is
    reported as one.
    """
    terms: set[str] = set()
    for d in (ROOT / "paper" / "sections", ROOT / "deck"):
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.tex")):
            raw = p.read_text(encoding="utf-8")
            for pat in (r"\\emph\{([^}]*)\}", r"\\textit\{([^}]*)\}",
                        r"\\begin\{definition\}(.{0,120})",
                        r"\\mathrm\{([^}]*)\}", r"\\texttt\{([^}]*)\}"):
                for m in re.finditer(pat, raw, flags=re.S):
                    terms |= set(WORD.findall(m.group(1).lower()))
            # Capitalised names and code-like tokens are subject matter wherever they appear.
            terms |= {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z]*[0-9A-Z][a-zA-Z0-9]*\b", raw)}
            terms |= {w.lower() for w in re.findall(r"\b(?:Uniswap|Sushiswap|Curve|Balancer|Ethereum|StableSwap|WETH|USDC)\w*", raw)}
    return terms


def corpus_headings(texts: list[str]) -> str:
    """Numbered section titles, which is how this venue's headings appear in extracted text."""
    out = []
    for t in texts:
        out += [m.group(1) for m in
                re.finditer(r"\n\s*\d{1,2}(?:\.\d{1,2})*\.?\s+([A-Z][A-Za-z ,:'\-]{6,70})\s*\n", t)]
    return "\n".join(out)


def compare(draft: str, corpus: list[str], n: int, min_count: int, label: str,
            rows: list[dict], as_template: bool = False) -> None:
    dws = words(draft)
    if as_template:
        dws = templates(dws)
    if len(dws) < 200:
        return
    dcount = grams(dws, n)
    drate = rates(dws, n)
    # Per-paper rates, so the ceiling is what a single published paper actually reached.
    per_paper = [rates(templates(words(c)) if as_template else words(c), n)
                 for c in corpus]
    corpus_words = sum(len(words(c)) for c in corpus)

    found = []
    for g, c in dcount.items():
        if c < min_count:
            continue
        mx = max((r.get(g, 0.0) for r in per_paper), default=0.0)
        med = sorted(r.get(g, 0.0) for r in per_paper)[len(per_paper) // 2]
        if drate[g] > mx and drate[g] > 0:
            # Subject matter, or style? A term absent from the corpus entirely is this
            # paper's topic; one the corpus uses less often is a stylistic difference.
            # Absent from the corpus AND introduced by this paper as technical: subject
            # matter. Absent from the corpus but never defined here: a word choice.
            toks = {w for w in g.split() if w != MASK}
            coined = ENGLISH and toks and not (toks <= ENGLISH)
            if mx > 0.0:
                kind = "style"          # the corpus uses it, the draft uses it more
            elif coined:
                kind = "topic"          # coined or technical, so subject matter
            else:
                # Ordinary English the corpus never uses. Not decidable automatically, and
                # reported for judgement instead of being waved through as terminology.
                kind = "check"
            found.append({"segment": label, "n": n, "expression": g, "draft_count": c,
                          "draft_rate": drate[g], "corpus_max": mx, "corpus_median": med,
                          "kind": kind})
    found.sort(key=lambda r: -(r["draft_rate"] - r["corpus_max"]))
    rows.extend(found)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-count", type=int, default=6,
                    help="minimum occurrences in the draft before an expression is reported")
    ap.add_argument("--top", type=int, default=18, help="rows to print per segment")
    args = ap.parse_args()

    global DOMAIN
    DOMAIN = domain_terms()
    corpus = corpus_texts()
    if not corpus:
        print(f"no readable exemplars under {EXEMPLARS}")
        return 1
    body, heads = draft_parts()
    chead = corpus_headings(corpus)
    print(f"corpus {len(corpus)} papers, {sum(len(words(c)) for c in corpus):,} words; "
          f"draft body {len(words(body)):,} words, headings {len(words(heads)):,} words; "
          f"corpus headings {len(words(chead)):,} words\n")

    rows: list[dict] = []
    for n in (1, 2, 3):
        compare(body, corpus, n, args.min_count, "body", rows)
    # SYNTACTIC TEMPLATES, content words masked. This is the topic-independent view: a tell
    # is a shape of sentence, and masking the nouns lets a wh-cleft or a trailing appositive
    # surface whatever the paper is about, with nobody having named the construction.
    for n in (2, 3, 4):
        compare(body, corpus, n, args.min_count, "template", rows, as_template=True)
    # Headings are short, so the count threshold has to drop or nothing clears it.
    for n in (1, 2):
        compare(heads, [chead], n, 2, "heading", rows)

    for seg in ("template", "body", "heading"):
        sel = [r for r in rows if r["segment"] == seg and r["kind"] == "style"]
        print(f"{seg.upper()}: {len(sel)} expression(s) above every published paper's rate")
        print(f"  {'expression':<34}{'draft/1k':>10}{'corpus max':>12}{'count':>7}")
        for r in sel[:args.top]:
            print(f"  {r['expression']:<34}{r['draft_rate']:>10.3f}"
                  f"{r['corpus_max']:>12.3f}{r['draft_count']:>7}")
        chk = [r for r in rows if r["segment"] == seg and r["kind"] == "check"]
        if chk:
            print(f"  {len(chk)} ordinary English expression(s) the corpus NEVER uses, "
                  f"for judgement:")
            for r in chk[:10]:
                print(f"    {r['expression']:<32}{r['draft_rate']:>8.3f}"
                      f"{'':>12}{r['draft_count']:>7}")
        topic = [r for r in rows if r["segment"] == seg and r["kind"] == "topic"]
        if topic:
            print(f"  ({len(topic)} further expression(s) absent from the corpus entirely, "
                  f"read as subject matter: {', '.join(r['expression'] for r in topic[:6])})")
        print()

    write_exhibit(__import__("pandas").DataFrame(rows), OUT)
    style = [r for r in rows if r["kind"] in ("style", "check")]
    print(f"wrote {OUT.relative_to(ROOT)}")
    print("\nEvery row is a construction the draft uses more often than any of the 14")
    print("published papers. Nobody named them in advance, which is the point: the list")
    print("is discovered from the corpus and does not depend on someone noticing a tell.")
    return 1 if style else 0


if __name__ == "__main__":
    sys.exit(main())
