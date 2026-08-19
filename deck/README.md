# Presentation deck

This is the single canonical live presentation. `main.tex` owns the build, `sections/` owns authored slides, and `assets/` contains presentation-only branding or media. Generated scientific figures and tables must enter through `../output/`; do not copy data products into this folder or keep a second deck version beside it.

The deck may stage a poll, reveal, screenshot, recording, diagram, or selected paper table when it improves a live explanation. It is both a scientific-feedback surface and a presentation-ready deliverable. Audience-facing slides state the result, support, and unresolved alternative in ordinary presentation language. Detailed evidence stays in the named generated input and current workflow state, not on the slide.

The consolidated slide-language, visual-rhetoric, and review rules live in
[`../docs/research/writing-and-rhetoric.md`](../docs/research/writing-and-rhetoric.md);
this README only owns deck folder structure and build handoff.

Build from this directory with `latexmk -pdf -interaction=nonstopmode main.tex`. Review the rendered pages visually and check the log for overflow before committing `main.pdf`.

For the live transition into the vehicle-rotation evidence, the generated
[11-second vehicle-currency timelapse](../output/figures/vehicle_dominance_timelapse.mp4)
shows the monthly WETH, USDC, USDT, and DAI route-share contest and closes on
the ordered-ultimate-pair decomposition. Its
[static poster](../output/figures/vehicle_dominance_timelapse_poster.pdf) is the
PDF-safe fallback. The links live here instead of occupying slide space.

For the 30-minute research talk, the core deck is capped at 24 static frames.
Core pages may carry at most 70 visible words, including chart and table labels;
the 55-word budget remains the default. Appendix pages may retain denser
question-defense exhibits.

## Folder map

| Path | Purpose |
|---|---|
| `main.tex` | document setup and section order |
| `sections/` | one authored live narrative; `01`--`05` are the talk and `90` is the appendix |
| `assets/` | presentation-only diagrams, logo, and layout fragments; generated scientific figures stay in `../output/figures/` |
| `density-ledger.json` | directly consumed slide-density allowances for the deck audit |
| `main.pdf` | canonical built presentation |

There is no separate deck outline: this README and the ordered section files are
the outline. Scientific status and blockers live in `../docs/findings/`, not in
deck-specific planning notes.
