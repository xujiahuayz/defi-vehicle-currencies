# Paper

This folder contains the single canonical manuscript. `main.tex` owns document assembly, `sections/` owns authored prose, and `results_evidence_map.tex` is generated evidence infrastructure. Code-generated tables, figures, macros, and exports belong in `../output/` and are consumed from there; do not duplicate them under `paper/`.

The paper remains downstream of the findings-freeze and review loops in [`../docs/research-workflow.md`](../docs/research-workflow.md). A compiled PDF is a review artifact, not evidence that its data, specifications, or claims are current.

Build from this directory with `latexmk -pdf -interaction=nonstopmode main.tex`, then run the repository conformance and findings gates before treating the result as a handoff.
