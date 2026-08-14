# Paper

This folder contains the single canonical manuscript. `main.tex` owns document assembly and `sections/` owns authored prose. Code-generated tables, figures, macros, and exports belong in `../output/` and are consumed from there; do not duplicate them under `paper/` or maintain a parallel evidence map.

The paper remains downstream of the findings-freeze and review loops in [`../docs/research-workflow.md`](../docs/research-workflow.md). A compiled PDF is a review artifact, not evidence that its data, specifications, or claims are current.

Build from this directory with `latexmk -pdf -interaction=nonstopmode main.tex`, then run the repository conformance and findings gates before treating the result as a handoff.
