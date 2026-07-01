# The Making of Vehicle Currencies

This repository contains the data pipeline, analysis code, literature workspace, and manuscript source for the current vehicle-currencies paper.

## Repository Layout

- `src/ddvc/` — importable research package for fetching, route reconstruction, pricing, metrics, analysis, and paper export helpers.
- `scripts/` — command-line entry points for reproducible fetch/build/analysis steps. Scripts will be added as the empirical design is finalized.
- `data/` — local data workspace for raw responses, intermediate tables, processed panels, external inputs, and run manifests. Data payloads are not committed.
- `output/` — generated paper artifacts, split into `tables/` and `figures/`. These files are regenerated from scripts and are not committed.
- `paper/` — manuscript source and paper-specific build notes.
- `literature/` — flat literature workspace for cited, related, and venue-style references.
- `tests/` — offline tests for parsing, reconstruction, pricing, metrics, and analysis helpers.

## Current Target

The working sample target is through 2026-06-30 UTC, implemented as an exclusive end date of 2026-07-01 in fetch and build commands.

