"""Shared repository paths."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LITERATURE_DIR = REPO_ROOT / "literature"
PAPER_DIR = REPO_ROOT / "paper"
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

LITERATURE_BIB = LITERATURE_DIR / "vehicle-currencies.bib"
LITERATURE_PDF_SOURCES = LITERATURE_DIR / "pdf-sources.json"
LITERATURE_LOCAL_SOURCES = LITERATURE_DIR / "sources.local.json"
LITERATURE_AUTH_HEADERS = LITERATURE_DIR / "auth" / "headers.local.json"
LITERATURE_PAPERS_DIR = LITERATURE_DIR / "papers"
LITERATURE_DOWNLOAD_MANIFEST = LITERATURE_PAPERS_DIR / "download-manifest.json"
