#!/usr/bin/env python3
"""One command that says whether the paper and the deck still conform, and to what.

WHY THIS IS A LOOP AND NOT A STEP. Conformance was treated as a one-off: the paper was
written, the venue optics were measured once, an agent was dispatched by hand to fix what
the measurement found. Java's objection is that this has to run EVERY time content changes,
because every rewrite for content can break language, structure and resemblance again, and
a check that depends on someone remembering to dispatch it is not a check.

So this is the whole conformance surface behind one command, in the order a reviewer would
apply it. It exits non-zero when a validity or declared house-style check fails and reports
distributional or classifier-based departures as advisories. It measures first and asserts
second, so the venue thresholds are always the current empirical quantiles of the exemplars
and never a number frozen into a test.

The surface is cumulative. A new correction is added to STAGES or to a test already invoked
by STAGES; it does not displace an older check. Removing or weakening a stage requires an
explicit withdrawal in the canonical workflow. When two standing rules conflict, the edit
stays open until Java resolves the conflict instead of allowing the newest rule to win.

Run it after ANY content change to the paper or the deck, and before calling either one
done. `docs/research-workflow.md` names it as the gate that closes the writing loop.

  ./scripts/run scripts/check_deliverable_conformance.py            check
  ./scripts/run scripts/check_deliverable_conformance.py --brief    also print an agent brief
                                                             naming exactly what to fix
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
OPTICS = ROOT / "output" / "exhibits" / "venue_optics.jsonl"

# Each stage is (label, argv, failure meaning, blocking). These automated stages are alarms,
# not a JFE-authorship certificate. They can show that the draft uses a known construction
# unusually often or has an unusual sentence distribution; they cannot judge whether an
# economic argument is introduced, developed, qualified, and handed to the next paragraph
# as published authors do. That judgment requires the raw-passage review registered below.
# STAGES is cumulative: a later concern adds to this surface. A stage is not removed or
# weakened without an explicit withdrawal recorded in docs/research-workflow.md.
# Venue-shape quartiles and the unsupervised outlier classifier remain advisory because
# domain vocabulary and rhetorical function require editorial judgment.
STAGES = [
    ("raw-passage JFE review is current for every compiled section",
     [str(PY), "scripts/check_jfe_rhetoric_review.py"],
     "a changed manuscript section has not been reread and recorded against raw JFE "
     "analogues", True),
    ("venue-structure alarm against the exemplars",
     [str(PY), "scripts/measure_venue_optics.py"],
     "could not measure the published papers, so the thresholds below are stale", True),
    ("known-construction alarm against the exemplars",
     [str(PY), "scripts/measure_prose_conventions.py"],
     "a known construction is used at a rate no published paper in the corpus reaches; "
     "rewrite the complete thought, then inspect its surrounding paragraph", True),
    ("discovered over-used constructions, nobody naming them first",
     [str(PY), "scripts/find_prose_outliers.py"],
     "a word, phrase or syntactic template is used above every published paper's rate; "
     "inspect whether this is rhetoric, subject matter, or a classifier error", False),
    ("prose shape against the venue's own distributions",
     [str(PY), "scripts/measure_venue_shape.py"],
     "sentence length or clause count sits outside the venue's range, which no amount of "
     "word-level correction can fix", False),
    ("house voice and register",
     [str(PY), "-m", "pytest", "tests/test_paper_prose.py", "-q"],
     "banned register, em dashes, hard-wrapped prose, or process language in a deliverable", True),
    ("exhibit note presence and typography",
     [str(PY), "-m", "pytest", "tests/test_exhibit_notes.py", "-q"],
     "an empirical exhibit is missing its note or bypasses the shared label, width, alignment, and spacing", True),
    ("generated evidence in the deck",
     [str(PY), "scripts/audit_deck_evidence.py"],
     "a scientific plot or measured value is typed into slide source instead of generated through output/", True),
    ("provenance of every number",
     [str(PY), "-m", "pytest", "tests/test_paper_provenance.py", "-q"],
     "a measured number names no artefact, or names one that does not exist", True),
    ("structural resemblance to the venue",
     [str(PY), "-m", "pytest", "tests/test_venue_optics.py", "-q"],
     "the paper is short of a venue quartile on a structural feature; investigate the "
     "scientific reason, but never add equations, citations, or length as filler", False),
    ("the spine still matches the paper",
     [str(PY), "-m", "pytest", "tests/test_paper_spine.py", "-q"],
     "the blueprint and the deliverable have diverged", True),
]


def build(target: Path) -> tuple[bool, str]:
    """Compile a LaTeX target and report whether it is clean."""
    if not (target / "main.tex").exists():
        return True, "absent"
    r = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "main.tex"],
                       cwd=target, capture_output=True, text=True)
    log = (target / "main.log")
    txt = log.read_text(errors="replace") if log.exists() else ""
    undef = txt.count("undefined")
    pages = ""
    for ln in txt.splitlines():
        if "Output written" in ln:
            pages = ln.split("(")[-1].split(" page")[0]
    ok = r.returncode == 0 and undef == 0
    return ok, (f"{pages} pages, {undef} undefined" if pages else f"exit {r.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brief", action="store_true",
                    help="print an agent brief naming what to fix")
    args = ap.parse_args()

    failures: list[tuple[str, str]] = []
    advisories: list[tuple[str, str]] = []
    for label, argv, meaning, blocking in STAGES:
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        ok = r.returncode == 0
        status = "ok  " if ok else ("FAIL" if blocking else "WARN")
        print(f"  {status}  {label}")
        if not ok:
            (failures if blocking else advisories).append((label, meaning))

    doc = ROOT / "paper" if (ROOT / "paper" / "main.tex").exists() else ROOT / "memo"
    for name, path in ((doc.name, doc), ("deck", ROOT / "deck")):
        ok, detail = build(path)
        print(f"  {'ok  ' if ok else 'FAIL'}  {name} compiles cleanly ({detail})")
        if not ok:
            failures.append((f"{name} build", "the deliverable does not compile cleanly"))

    # The optics table is the actionable part, so print where the draft sits regardless.
    if OPTICS.exists():
        rows = [json.loads(l) for l in OPTICS.read_text().splitlines() if l.strip()]
        short = [r for r in rows if r["verdict"] != "in range"]
        if short:
            print(f"\n  short of the venue on {len(short)} feature(s):")
            for r in short:
                print(f"    {r['feature']:<12} draft {r['draft']:>6,}   "
                      f"exemplar p25 {r['exemplar_p25']:>6,}   "
                      f"median {r['exemplar_median']:>6,}   [{r['verdict']}]")

    if not failures:
        if advisories:
            noun = "advisory" if len(advisories) == 1 else "advisories"
            verb = "remains" if len(advisories) == 1 else "remain"
            print(f"\nAll blocking conformance checks pass; {len(advisories)} {noun} "
                  f"{verb} visible for the next substantive rewrite.")
        else:
            print("\nAll automated alarms are clear. This does not certify JFE rhetoric; "
                  "the raw-passage paragraph review remains a separate judgment.")
        return 0

    print(f"\n{len(failures)} check(s) failed:")
    for label, meaning in failures:
        print(f"  {label}: {meaning}")

    if args.brief:
        print("\n" + "=" * 72)
        print("AGENT BRIEF, paste into a subagent that owns the affected files")
        print("=" * 72)
        print("Bring the paper and deck back into conformance. Failing checks:\n")
        for label, meaning in failures:
            print(f"  - {label}: {meaning}")
        for label, meaning in advisories:
            print(f"  - advisory, {label}: {meaning}")
        if OPTICS.exists():
            for r in (json.loads(l) for l in OPTICS.read_text().splitlines() if l.strip()):
                if r["verdict"] != "in range":
                    print(f"  - {r['feature']}: draft has {r['draft']}, the exemplars' first "
                          f"quartile is {r['exemplar_p25']} and the median is "
                          f"{r['exemplar_median']}")
        print("\nEvery number must come from a real artefact and carry a trailing comment "
              "naming it and its sample. Treat vocabulary and construction alarms as "
              "diagnostics, not term-replacement instructions: reread the closest raw "
              "published passages and revise the economic argument, transitions, sentence "
              "functions, and paragraph rhythm. Remove hard-wrapped prose and backstage "
              "process language. Re-run this script until it exits zero.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
