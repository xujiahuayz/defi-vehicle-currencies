#!/usr/bin/env python3
"""Verify a candidate replacement word BEFORE substituting it.

WHY THIS EXISTS. Swapping a flagged word for an unvetted one is how the next tell gets
made. Two live examples from the 2026-08-06 rewrite round, both caught by this script
within minutes of being written into the draft:

  "alone"   proposed as a replacement, already at 19 uses against a venue ceiling of 1.5
  "beside"  proposed as a replacement, used by NEITHER the venue nor the field literature

Rates hide this. A word can sit at a harmless-looking rate per thousand and still be
fifteen occurrences over what any published paper reaches, so this reports HEADROOM IN
OCCURRENCES: how many more times the draft may use the word before it becomes an outlier.
A negative number means the word is already a tell and adding one makes it worse.

It reuses `find_prose_outliers.py`'s own functions, so its verdict cannot drift from the
gate that will later judge the draft.

  python scripts/check_replacement_headroom.py restriction versus relative each all

Reads   ../defi-dominant-currency/lit/jfe-exemplars/*.pdf   the venue
        literature/text/*.txt                               the field
        paper/sections or memo/sections                     the draft
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("fpo", ROOT / "scripts" / "find_prose_outliers.py")
fpo = importlib.util.module_from_spec(_spec)
sys.modules["fpo"] = fpo
_spec.loader.exec_module(fpo)


def main() -> int:
    terms = [t for t in sys.argv[1:] if not t.startswith("-")]
    if not terms:
        print(__doc__)
        return 1

    corpus = fpo.corpus_texts()
    if not corpus:
        print("no readable exemplars")
        return 1
    per_paper = [fpo.rates(fpo.words(c), 1) for c in corpus]

    body, _heads = fpo.draft_parts()
    dws = fpo.words(body)
    dcount = fpo.grams(dws, 1)
    nwords = len(dws)

    lit = ROOT / "literature" / "text"
    seen: Counter = Counter()
    for p in sorted(lit.glob("*.txt")):
        seen.update(set(fpo.WORD.findall(p.read_text(errors="ignore").lower())))

    print(f"\n  draft body {nwords:,} words; ceiling = venue max rate x {nwords / 1000:.1f}\n")
    print(f"  {'candidate':<20}{'venue max':>10}{'now':>6}{'ceiling':>9}"
          f"{'headroom':>10}{'field':>7}{'sense':>7}  verdict")

    worst = 0
    for term in terms:
        t = term.lower()
        mx = max((r.get(t, 0.0) for r in per_paper), default=0.0)
        now = dcount.get(t, 0)
        ceiling = mx * nwords / 1000.0
        head = ceiling - now
        nlit = seen.get(t, 0)
        try:
            sense = fpo.sense_matches(t) if nlit else False
        except Exception:
            sense = False

        if mx == 0.0 and not (nlit >= 3 and sense):
            verdict = "NEVER USE, venue and field both silent"
            worst = 1
        elif head < 1:
            verdict = "AT CEILING, do not add"
            worst = 1
        elif head < 5:
            verdict = f"tight, room for about {int(head)}"
        else:
            verdict = f"safe, room for about {int(head)}"

        print(f"  {term:<20}{mx:>10.3f}{now:>6}{ceiling:>9.1f}"
              f"{head:>10.1f}{nlit:>7}{str(sense):>7}  {verdict}")

    print("\n  Aim at the venue's rate, never at zero. A word the corpus uses freely is a")
    print("  convention of the field, and avoiding it entirely is itself a deviation.")
    return worst


if __name__ == "__main__":
    sys.exit(main())
