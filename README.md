# The Making of Vehicle Currencies

This repository contains the data pipeline, analysis code, literature workspace, and manuscript source for the current vehicle-currencies paper.

## Repository Layout

- `src/ddvc/` — importable research package for fetching, route reconstruction, pricing, metrics, analysis, and paper export helpers.
- `scripts/` — command-line entry points for reproducible fetch/build/analysis steps. Mathematica/Wolfram source belongs under `scripts/model/`.
- `scripts/process/` — explicit data-processing steps. Each script is a directly runnable wrapper that reads data-layer inputs and writes one reusable analysis table under `data/processed/` or `data/empirical/`.
- `scripts/tabulate/` — one script per journal table. A script named `render_<exhibit>.py` owns exactly one table and writes `output/tables/<exhibit>.tex` containing only `tabular`/`tabularx` content and any essential observation-unit note, plus `output/tables/<exhibit>.pdf` for inspection. Use content-driven or automatically allocated column widths rather than hard-coded fractions of `\linewidth`. Table numbering belongs only in the paper or slides; output filenames must be descriptive and unnumbered. Paper-facing table renderers do not write data sidecars. Captions, labels, sizing, and outer `table` wrappers belong in the paper or slides. Shared table-output helpers live in `scripts/tabulate/utils.py`.
- `data/` — local data workspace for raw responses, intermediate tables, processed panels, external inputs, and run manifests. Data payloads are not committed.
- `output/` — generated paper artifacts, including tables, figures, and internal review PDFs. These are products of scripts, not the source of truth.
- `paper/` — manuscript source. Keep this directory clean: LaTeX files when drafting starts, plus at most one outline Markdown file.
- `slides/` — presentation decks and compiled talk PDFs.
- `literature/` — flat literature workspace for cited, related, and venue-style references.
- `tests/` — offline tests for parsing, reconstruction, pricing, metrics, and analysis helpers.

## Recording Policy

- Put propositions, manuscript structure, and final paper wording in `paper/`.
- Put executable analysis, model, and build logic in `scripts/` or `src/ddvc/`.
- Put generated tables, figures, and review PDFs in `output/`.
- Put local raw/intermediate/generated datasets in `data/`.
- Put bibliography metadata and local PDF retrieval tooling in `literature/`.
- Keep reviewer transcripts, one-off assistant notes, and scratch memos out of `paper/`; fold any durable paper point into the single outline or a manuscript source file.
- Build paper exhibits as separate reproducible units. Tables live under `scripts/tabulate/`, plots under `scripts/figure/`, and diagrams under `scripts/diagram/` when those folders are needed. Do not add new monolithic exhibit builders for paper-facing artifacts. Scripts should stay directly runnable and thin; reusable functions belong in `src/ddvc/`.
- Track paper-facing outputs under `output/tables/`, `output/figures/`, and `output/exhibits/`. Do not generate CSV artifacts, and do not replace CSV sidecars with pickle sidecars. Native serialized intermediates are allowed only for current downstream consumers, expensive reusable caches, or canonical data panels; prefer Parquet for data panels. Paper-facing table artifacts are TeX/PDF only, with no generated data sidecars and no hard-coded `table_01`/`figure_02` style numbering in output filenames.
- Build the canonical wide observations table before rendering summary statistics, regressions, or exploratory plots:

```bash
.venv/bin/python scripts/process/build_observations_table.py
```

This writes `data/processed/observations_token_day.parquet`. Table renderers should read this table or another explicit processing output in a native serialized format.

Build the incremental raw-file inventory and render the descriptive tables with:

```bash
.venv/bin/python scripts/process/build_raw_data_inventory.py
.venv/bin/python scripts/tabulate/render_data_coverage.py
.venv/bin/python scripts/tabulate/render_sample_coverage.py
.venv/bin/python scripts/tabulate/render_summary_statistics.py
```

The inventory is `data/processed/raw_data_inventory.parquet`. It caches exact record counts only for raw files whose sidecars do not contain stream counts; the cache is consumed by the coverage tabulator and avoids rescanning unchanged compressed files. The paper-facing products are the tracked, unnumbered TeX/PDF pairs under `output/tables/`.

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

This orchestrates the descriptive tabulators, supporting analytics, JFE main tables, core RQ tables, then `paper/results_evidence_map.tex` and `paper/results_evidence_map.pdf`. Analysis intermediates stay in native serialized formats under ignored analysis folders such as `output/empirical/`; `output/tables/` is reserved for tracked, descriptive TeX/PDF table artifacts. Both evidence-map artifacts are tracked. The PDF step uses `tectonic`, `latexmk`, or `pdflatex` when available, and falls back to a matplotlib review PDF on machines without a TeX engine.
