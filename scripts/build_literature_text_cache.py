#!/usr/bin/env python3
"""Extract the literature corpus to plain text so it can be grepped instead of loaded.

Why this exists. The corpus is 53 PDFs totalling 67 MB, with individual files up to
5.4 MB, and no text extractor was installed: no pdftotext, no pypdf, no pdfplumber, no
fitz. Any reviewer asked to read the exemplars first-hand therefore had to load whole
PDFs through a file-reading tool, and two review agents stalled for ten minutes each
doing exactly that before producing anything. The corpus was effectively unusable for
the one purpose it was assembled for.

Extracting once turns every later question into a grep. Counting how many exemplars put
identification before results, or how many carry a standalone robustness section, or
what a typical abstract length is, becomes a search over text rather than 53 document
loads. That matters beyond speed: a claim about venue norms should be checkable by
anyone in one command, and this project has already had to retract two such claims that
were asserted from memory of a summary.

Per-page text is kept, because section structure is a page-level property and a
question like "where does the identification discussion sit" needs position, not just
presence.

Reads   literature/papers/*.pdf
Writes  literature/text/<stem>.txt          one file per paper, pages delimited
        literature/text/_index.jsonl        stem, title guess, pages, characters
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ddvc.runtime import atomic_output

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "literature" / "papers"
OUT = ROOT / "literature" / "text"
INDEX = OUT / "_index.jsonl"
PAGE_MARK = "\n\n===== PAGE {n} =====\n\n"


def normalize_extracted_text(text: str) -> str:
    """Remove extractor-only trailing spaces without changing page content."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def extract(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        parts.append(PAGE_MARK.format(n=i) + normalize_extracted_text(txt))
    return "".join(parts), len(reader.pages)


def load_index(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stem = str(record.get("stem") or "")
        if stem:
            records[stem] = record
    return records


def merge_index_records(
    current: list[dict],
    previous: dict[str, dict],
    text_stems: set[str],
) -> list[dict]:
    """Keep durable text-only records while replacing every live PDF record."""
    merged = {stem: record for stem, record in previous.items() if stem in text_stems}
    merged.update({str(record["stem"]): record for record in current})
    return [merged[stem] for stem in sorted(merged)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="re-extract even where a text file already exists")
    args = ap.parse_args()

    pdfs = sorted(PAPERS.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs under {PAPERS.relative_to(ROOT)}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"extracting {len(pdfs)} PDFs to {OUT.relative_to(ROOT)}", flush=True)

    previous_index = load_index(INDEX)
    index = []
    failed = 0
    for i, p in enumerate(pdfs, 1):
        dest = OUT / f"{p.stem}.txt"
        if dest.exists() and not args.force:
            text = dest.read_text(errors="replace")
            pages = text.count("===== PAGE ")
        else:
            try:
                text, pages = extract(p)
            except Exception as exc:
                failed += 1
                print(f"  {p.stem}: FAILED {type(exc).__name__} {str(exc)[:80]}", flush=True)
                continue
            # NEVER replace a longer extract with a shorter one. Two papers in this corpus
            # are scans with no text layer, and their extracts were produced by OCR through
            # a route this script does not have. pypdf returns almost nothing for them, so
            # a --force run would silently overwrite 57,533 and 44,748 characters of real
            # text with a few hundred, restoring the exact defect the OCR fixed and leaving
            # no trace that anything was lost.
            if dest.exists():
                have = dest.read_text(errors="replace")
                if len(have) > max(2000, 2 * len(text)):
                    print(f"  {p.stem}: KEPT existing {len(have):,}-char extract, this run "
                          f"produced only {len(text):,} (probably a scan carrying OCR)",
                          flush=True)
                    text, pages = have, have.count("===== PAGE ")
                    index.append({"stem": p.stem, "pages": pages, "chars": len(text),
                                  "title_guess": next((ln.strip() for ln in
                                                       text.split("===== PAGE 1 =====", 1)[-1]
                                                       .strip().splitlines()
                                                       if len(ln.strip()) > 20), "")[:140],
                                  "pdf_mb": round(p.stat().st_size / 1e6, 2)})
                    continue
            with atomic_output(dest) as temporary:
                temporary.write_text(text)
        # First non-trivial line of page 1 is a serviceable title guess, and a bad
        # guess is visible rather than silent because the raw text sits beside it.
        head = text.split("===== PAGE 1 =====", 1)[-1].strip().splitlines()
        title = next((ln.strip() for ln in head if len(ln.strip()) > 20), "")[:140]
        index.append({"stem": p.stem, "pages": pages, "chars": len(text),
                      "title_guess": title, "pdf_mb": round(p.stat().st_size / 1e6, 2)})
        if i % 10 == 0 or i == len(pdfs):
            print(f"  {i}/{len(pdfs)}", flush=True)

    index = merge_index_records(
        index,
        previous_index,
        {path.stem for path in OUT.glob("*.txt")},
    )
    with atomic_output(INDEX) as temporary:
        temporary.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in index)
        )
    empty = [r["stem"] for r in index if r["chars"] < 2000]
    print(f"\nextracted {len(index)} papers, {failed} failed, "
          f"{sum(r['pages'] for r in index):,} pages, "
          f"{sum(r['chars'] for r in index) / 1e6:.1f}m characters")
    if empty:
        print(f"\n{len(empty)} papers yielded almost no text and are probably scans; "
              f"they need OCR before any claim rests on them:")
        for s in empty[:8]:
            print(f"  {s}")
    print(f"\nNow greppable, for example:")
    print(f"  grep -lic 'identification' {OUT.relative_to(ROOT)}/*.txt | wc -l")
    return 0


if __name__ == "__main__":
    sys.exit(main())
