# Phase 8 — compile and final visual QA

**Build:** `slides/nbc_2026_full.tex` -> `slides/nbc_2026_full.pdf`, 37 pages, `latexmk -pdf`, compiles clean. Zero `Overfull \hbox` (no text bleeding off any slide). One pre-existing cosmetic `Overfull \vbox (4.06pt)` on the title page (title/subtitle/author block slightly tall) -- confirmed below zero any visible-break threshold. One benign `hyperref` metadata warning (multi-line `\date` in the PDF string), invisible-content only.

**Visual inspection (rendered via PyMuPDF at 150dpi, sampled directly, not taken on an agent's word):** title slide (logo renders correctly, plain otherwise, no overlap), abstract-bridging slide, propositions slide, P1 headline table slide, recap slide, backup divider, the one disclosed TODO frame, and the references slide. No overlapping text/figures, no bleed off slide edges, no misalignment found in any sampled page.

**Cosmetic language gate, mechanically re-checked against the actual compiled `.tex` (not a summary of it):**
- Zero rendered instances of "rather than," "genuinely," "honest/honestly," "broader," "deliberate/deliberately" (two "rather than" hits exist only in LaTeX comments, which never render).
- Zero em-dashes, zero "·" middle-dot separators.
- Exactly one "X, not Y" construction in the whole deck (the recap slide's closing line) -- matches the spec's own cap.

**Branding:** UCL CBT logo (`UCL_S_2C_DP_RGB_Ctr_Block_Tech_logos.png`) on the title slide only, confirmed rendering correctly. Every other slide plain, no running footer logo.

**Known gap, disclosed, not hidden:** one appendix frame ("P1 backup: full battery, remaining cells," page 26) is an explicit TODO for a formatting pass -- the underlying numbers exist and are cited to their source CSVs, only the full row-by-row table layout wasn't built out. Everything else is complete.

**Caught during this pipeline, not after:** the appendix-drafting and compile-merge steps independently found and corrected a real factual error in the core deck's first draft (the D-on-L contra-finding was mis-described as recurring in the low-depth subsample; the actual data shows the opposite). This is exactly the kind of error the pipeline's redundant-verification design exists to catch before it ships, and it worked.

**Deliverable:** `slides/nbc_2026_full.pdf` + `slides/nbc_2026_full.tex`, plus the two source files `nbc_2026_core.tex` / `nbc_2026_appendix.tex` kept for reference.
