#!/usr/bin/env python3
"""Verify a candidate replacement word BEFORE substituting it.

Swapping one flagged word for another unvetted word is how the last tell was created.
This asks the same three questions find_prose_outliers.py asks, using that script's own
functions so the verdict cannot drift from the gate:

  venue    rate per 1,000 words in the 14 JFE exemplars (max across papers)
  field    how many of the 54 domain papers use the token at all
  sense    whether the field's usage keeps the company the draft's usage keeps

A candidate is SAFE when the venue uses it at a rate above the draft's projected rate,
or the field uses it in the same sense. Anything else would land in the report as a new
outlier the moment it is used enough to clear min-count.
"""
import importlib.util, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/dsf-pro16-m3/projects/defi-vehicle-currencies")
spec = importlib.util.spec_from_file_location("fpo", ROOT / "scripts" / "find_prose_outliers.py")
fpo = importlib.util.module_from_spec(spec)
sys.modules["fpo"] = fpo
spec.loader.exec_module(fpo)

corpus = fpo.corpus_texts()
per_paper = [fpo.rates(fpo.words(c), 1) for c in corpus]
body, heads = fpo.draft_parts()
dw = fpo.words(body)
drate = fpo.rates(dw, 1)
dcount = fpo.grams(dw, 1)

lit = ROOT / "literature" / "text"
litseen: Counter = Counter()
for p in sorted(lit.glob("*.txt")):
    litseen.update(set(fpo.WORD.findall(p.read_text(errors="ignore").lower())))
NLIT = len(list(lit.glob("*.txt")))

NW = len(dw)
print(f"  draft body = {NW:,} words; ceiling = corpus_max * {NW/1000:.1f}\n")
print(f"  {'candidate':<18}{'venue max':>10}{'now':>6}{'ceiling':>9}{'headroom':>10}"
      f"{'field':>7}{'sense':>7}  verdict")
for term in sys.argv[1:]:
    t = term.lower()
    mx = max((r.get(t, 0.0) for r in per_paper), default=0.0)
    now = dcount.get(t, 0)
    ceil = mx * NW / 1000.0
    nlit = litseen.get(t, 0)
    try:
        sense = fpo.sense_matches(t) if nlit else False
    except Exception:
        sense = False
    head = ceil - now
    if mx == 0.0 and not (nlit >= 3 and sense):
        v = "NEVER USE (corpus and field both silent)"
    elif head < 1:
        v = "AT CEILING, do not add"
    elif head < 5:
        v = f"tight, room for ~{int(head)}"
    else:
        v = f"SAFE, room for ~{int(head)}"
    print(f"  {term:<18}{mx:>10.3f}{now:>6}{ceil:>9.1f}{head:>10.1f}"
          f"{nlit:>7}{str(sense):>7}  {v}")
