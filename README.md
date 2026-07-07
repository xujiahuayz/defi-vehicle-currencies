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
