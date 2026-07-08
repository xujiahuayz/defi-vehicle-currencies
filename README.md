# The Making of Vehicle Currencies

This repository contains the data pipeline, analysis code, literature workspace, and manuscript source for the current vehicle-currencies paper.

## Repository Layout

- `src/ddvc/` — importable research package for fetching, route reconstruction, pricing, metrics, analysis, and paper export helpers.
- `scripts/` — command-line entry points for reproducible fetch/build/analysis steps. Mathematica/Wolfram source belongs under `scripts/model/`.
- `data/` — local data workspace for raw responses, intermediate tables, processed panels, external inputs, and run manifests. Data payloads are not committed.
- `output/` — generated paper artifacts, including tables, figures, and internal review PDFs. These are products of scripts, not the source of truth.
- `paper/` — manuscript source. Keep this directory clean: LaTeX files when drafting starts, plus at most one outline Markdown file.
- `literature/` — flat literature workspace for cited, related, and venue-style references.
- `tests/` — offline tests for parsing, reconstruction, pricing, metrics, and analysis helpers.

## Recording Policy

- Put propositions, manuscript structure, and final paper wording in `paper/`.
- Put executable analysis, model, and build logic in `scripts/` or `src/ddvc/`.
- Put generated tables, figures, and review PDFs in `output/`.
- Put local raw/intermediate/generated datasets in `data/`.
- Put bibliography metadata and local PDF retrieval tooling in `literature/`.
- Keep reviewer transcripts, one-off assistant notes, and scratch memos out of `paper/`; fold any durable paper point into the single outline or a manuscript source file.

## Current Target

The working sample target is through 2026-06-30 UTC, implemented as an exclusive end date of 2026-07-01 in fetch and build commands.

## Environment

Install runtime dependencies from repo metadata with:

```bash
uv sync
```

For tests and development tools, install the development extra:

```bash
uv sync --extra dev
```

## Results Evidence Map

Regenerate the ignored result tables, the tracked TeX evidence map, and a local PDF render with:

```bash
.venv/bin/python scripts/build_results_evidence_outputs.py
```

This orchestrates the supporting `table_r*` analytics, the JFE main tables (`table_m01`-`table_m07`), the core RQ tables (`table_m08`-`table_m18`), then `paper/results_evidence_map.tex` and `paper/results_evidence_map.pdf`. The TeX file is tracked and should be byte-stable after regeneration. The PDF is intentionally ignored because TeX engines and fallback renderers produce different byte streams even when the document content and page count match. The PDF step uses `tectonic`, `latexmk`, or `pdflatex` when available, and falls back to a matplotlib review PDF on machines without a TeX engine.
