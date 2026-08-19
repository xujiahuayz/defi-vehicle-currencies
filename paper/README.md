# Paper

This folder contains the single canonical manuscript. `main.tex` owns document assembly and `sections/` owns authored prose. Code-generated tables, figures, macros, and exports belong in `../output/` and are consumed from there; do not duplicate them under `paper/` or maintain a parallel evidence map.

The paper remains downstream of the analysis in [`../README.md`](../README.md).
A compiled PDF is a review artifact, not evidence that its inputs are current.
The paper-writing and rhetoric rules live in
[`../docs/research/writing-and-rhetoric.md`](../docs/research/writing-and-rhetoric.md);
this README only owns manuscript folder structure and build handoff.

Build from this directory with `latexmk -pdf -interaction=nonstopmode main.tex`, then run the repository conformance and findings gates before treating the result as a handoff.

## Folder map

| Path | Purpose |
|---|---|
| `main.tex` | JFE-format setup, generated macro inputs, bibliography, and section order |
| `sections/` | canonical authored manuscript sections; numbered files follow paper order and `08-appendix.tex` owns the appendix |
| `main.pdf` | canonical built working paper |
| `main.bbl` | generated bibliography used by the current PDF build |

The manuscript is the only paper draft. Research design belongs in
`../docs/research/`, current result status in `../docs/findings/`, and generated
tables/figures in `../output/`.
