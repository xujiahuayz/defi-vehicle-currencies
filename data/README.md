# Data Workspace

All data payloads are local and regenerated from code. Do not commit raw, interim, processed, or external data files.

## Layout

- `raw/` — verbatim source responses fetched once from subgraphs, APIs, RPC calls, downloads, or other sources.
- `interim/` — normalized intermediate files that preserve source identifiers and provenance.
- `processed/` — route tables, metrics, analysis panels, and figure-source datasets.
- `external/` — local licensed or manually supplied inputs, if any.
- `manifests/` — lightweight run manifests that are safe to commit when they contain no secrets and no private-source references.

## Date Convention

The target sample through 2026-06-30 UTC should be represented in scripts as `start <= date < 2026-07-01`.

## Data Dictionary

Column definitions will be added here as each table family is created. Keep this file as the only markdown file under `data/`.

