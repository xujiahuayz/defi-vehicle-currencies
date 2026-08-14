# Table Rendering and Manuscript Lineage

`scripts/tabulate/` owns generic table fragments and their standalone inspection PDFs. A renderer writes `output/tables/<stem>.tex` and `<stem>.pdf`; `write_table_artifacts` also records the renderer, declared scientific code, declared inputs, and exact output bytes under `data/manifests/output/tables/`.

The paper owns captions, labels, notes, placement, and numbering. A table becomes a deliverable input only when the paper or deck explicitly consumes it and its payload and provenance are current.

## Named renderers

| Renderer | Inputs | Current status and consumer |
|---|---|---|
| `render_data_coverage.py` | `data/processed/raw_data_inventory.parquet` | Runnable inspection table; no current paper or deck consumer. |
| `render_variable_notation.py` | `src/ddvc/variable_registry.py` | Runnable notation audit; no current paper or deck consumer. |
| `render_summary_statistics.py` | `data/processed/observations_token_day.parquet` through `DEFAULT_OBSERVATIONS_TABLE` | Input and renderer are present, but no generated fragment is checked in and there is no current deliverable consumer. |
| `render_sample_coverage.py` | `bridge_daily`, `route_cost_panel_v2`, LP-capital concentration, and V4 route-unit panels | Blocked. `route_cost_panel_v2` is withdrawn pending its registered rebuild. Do not run or cite the checked-in fragment meanwhile. |
| `render_dominance_rotation.py` | Certified `intermediation_complexity_rival.jsonl` and sidecar | Current paper body for `tab:rotation`; selects the exact two-leg count and within-20\% supported-value rows. |
| `render_pair_composition.py` | Certified pair-decomposition presentation binding and fixed-effect exhibit, with both sidecars | Current paper body for `tab:pair-composition`; Panels A--B are the certified accounting and Panel C contains all three descriptive fixed-effect rows. |
| `render_usdt_transition.py` | `provisional_results_deck_values.tex` | Current paper body for `tab:usdt-transition`. Its output is exact-hash bound, but the upstream macro binding remains provisional and unstamped pending the current excess-use release. |

## Tables in the current manuscript

Three live manuscript tables now have one-to-one `scripts/tabulate/` renderers and are consumed as generated body fragments. The other nine table bodies remain inline and presentation-owned, even when their values come from generated exhibits. “Inline” means the values must still be checked against the listed source; it does not make the TeX table a data release.

| Manuscript label | Presentation owner | Quantitative source | Status |
|---|---|---|---|
| `tab:panel` | `paper/sections/02-setting.tex` | `unified_route_quality.jsonl`; `round_trip_share_by_day.jsonl` | Active, inline, hand-transcribed from stamped exhibits. |
| `tab:venues` | `paper/sections/02-setting.tex` | venue-specific quoter validation exhibits; `docs/venue-coverage-bounds.md` | Active, inline, hand-transcribed from mixed exhibit and review sources. |
| `tab:rotation` | `paper/sections/03-dominance.tex` inputs `output/tables/dominance_rotation.tex` | Certified `intermediation_complexity_rival.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:pair-composition` | `paper/sections/03-dominance.tex` inputs `output/tables/pair_composition.tex` | Certified pair-decomposition macros and all three rows of `vehicle_transition_pair_fixed_effects.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:usdt-transition` | `paper/sections/03-dominance.tex` inputs `output/tables/usdt_transition.tex` | `provisional_results_deck_values.tex`; `docs/findings-freeze.md` | Active generated body. Its output is provenance-stamped against the exact macro bytes; the upstream macro file remains provisional and unstamped. |
| `tab:app:cl` | `paper/sections/08-appendix.tex` | `v4_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:curve` | `paper/sections/08-appendix.tex` | `curve_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:weighted` | `paper/sections/08-appendix.tex` | `weighted_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:support` | `paper/sections/08-appendix.tex` | `quoter_support_bounds.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:venues` | `paper/sections/08-appendix.tex` | `docs/venue-coverage-bounds.md` and its named venue-volume exhibits | Active, inline, hand-transcribed from the review record. |
| `tab:app:curveleg` | `paper/sections/08-appendix.tex` | `docs/venue-coverage-bounds.md` and its named Curve-exclusion exhibits | Active, inline, hand-transcribed from the review record. |
| `tab:app:roundtrip` | `paper/sections/08-appendix.tex` | `round_trip_share_by_day.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |

The remaining migration should create one descriptive renderer per inline empirical table and have the manuscript input its fragment. Captions and notes remain in the manuscript. Migrate each table and its tests atomically; do not duplicate an inline table while leaving both copies live.

Before removing an older file from `output/tables/`, search paper, deck, scripts, tests, docs, and manifests for consumers. Git history is the archive only after a current owner and every live reference have been reconciled.
