"""Shared repository paths."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LITERATURE_DIR = REPO_ROOT / "literature"
# TWO ARTEFACTS, ONE PAPER.
#   memo/   the discovery draft. Every result, number and provenance comment, in the
#           register it was found in. Frozen for style; it is a record, not a deliverable.
#   paper/  the paper, written FROM the memo against the venue's measured shape bands.
# There is exactly one of each. A parallel "v2" copy of the paper was tried and removed,
# and the standing supersede-means-delete rule is why: two live copies of a deliverable
# already cost one full review cycle spent on the wrong file.
MEMO_DIR = REPO_ROOT / "memo"
PAPER_DIR = REPO_ROOT / "paper"


def prose_root() -> Path:
    """Whichever of the two currently holds the prose the gates should judge.

    The paper is the target once it exists. Until then the memo is the only prose in the
    repository, and measuring it is honest: the gates report how far the discovery draft
    sits from the venue, which is exactly the distance the rewrite has to travel.
    """
    return PAPER_DIR if (PAPER_DIR / "sections").is_dir() else MEMO_DIR


def sections_dir() -> Path:
    return prose_root() / "sections"
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

LITERATURE_BIB = LITERATURE_DIR / "vehicle-currencies.bib"
LITERATURE_PDF_SOURCES = LITERATURE_DIR / "pdf-sources.json"
LITERATURE_LOCAL_SOURCES = LITERATURE_DIR / "sources.local.json"
LITERATURE_AUTH_HEADERS = LITERATURE_DIR / "auth" / "headers.local.json"
LITERATURE_PAPERS_DIR = LITERATURE_DIR / "papers"
LITERATURE_DOWNLOAD_MANIFEST = LITERATURE_PAPERS_DIR / "download-manifest.json"
