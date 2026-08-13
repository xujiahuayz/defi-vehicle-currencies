# Presentation Deck

This is the single canonical live presentation. `main.tex` owns the build, `sections/` owns authored slides, and `assets/` contains presentation-only branding or media. Generated scientific figures and tables must enter through `../output/`; do not copy data products into this folder or keep a second deck version beside it.

The deck may stage a poll, reveal, screenshot, recording, diagram, or selected paper table when it improves a live explanation. It is both a live scientific-feedback surface and a presentation-ready deliverable. Estimates may evolve, but status labels, commit hashes, generation identities, and repository paths stay in audited source comments. Audience-facing slides state the scientific result, support, and unresolved alternative in ordinary presentation language. Top-finance conference decks set the field register and information density; the reusable academic-deck rules live in [`../docs/research-workflow.md`](../docs/research-workflow.md).

Build from this directory with `latexmk -pdf -interaction=nonstopmode main.tex`. Review the rendered pages visually and check the log for overflow before committing `main.pdf`.
